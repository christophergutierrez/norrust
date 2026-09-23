//! Small local backend helpers for the versioned Coordinated Planner selector.
//! The request and response remain the Rust selector v1 JSON contract.

use crate::selector::{SelectorRequest, SelectorResponse};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

#[cfg(unix)]
unsafe extern "C" {
    fn kill(pid: i32, signal: i32) -> i32;
}

pub const COMMAND_ENVELOPE_VERSION: u16 = 1;

/// Request envelope for one isolated selector command invocation. `request`
/// remains the canonical Rust selector contract; the outer identity binds the
/// response to this game decision and prevents reuse of an earlier reply.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SelectorCommandRequest {
    pub schema_version: u16,
    pub game_id: String,
    pub decision_id: String,
    pub request_sha256: String,
    pub request: SelectorRequest,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SelectorCommandResponse {
    pub schema_version: u16,
    pub game_id: String,
    pub decision_id: String,
    pub request_sha256: String,
    pub response: SelectorResponse,
}

impl SelectorCommandRequest {
    pub fn new(game_id: String, decision_id: String, request: SelectorRequest) -> Self {
        let request_sha256 = selector_request_sha256(&request);
        Self {
            schema_version: COMMAND_ENVELOPE_VERSION,
            game_id,
            decision_id,
            request_sha256,
            request,
        }
    }
}

pub fn selector_request_sha256(request: &SelectorRequest) -> String {
    let bytes = serde_json::to_vec(request).expect("selector request serialization is infallible");
    format!("{:x}", Sha256::digest(bytes))
}

impl SelectorCommandResponse {
    pub fn validate_for(&self, request: &SelectorCommandRequest) -> Result<(), &'static str> {
        if self.schema_version != COMMAND_ENVELOPE_VERSION {
            return Err("unsupported selector command response version");
        }
        if self.game_id != request.game_id || self.decision_id != request.decision_id {
            return Err("selector command response identity mismatch");
        }
        if self.request_sha256 != request.request_sha256 {
            return Err("selector command response request hash mismatch");
        }
        self.response.validate_for(&request.request)
    }
}

/// Run a request-dependent selector command without shell interpolation.
/// Arguments are passed as distinct argv values, stdin carries one JSON
/// envelope, and stdout must contain one bounded JSON response envelope.
pub fn invoke_command(
    program: &Path,
    args: &[String],
    request: &SelectorCommandRequest,
    timeout: Duration,
    max_response_bytes: usize,
    usage_sidecar: Option<&Path>,
    evidence_dir: Option<&Path>,
) -> Result<SelectorResponse, String> {
    let input =
        serde_json::to_vec(request).map_err(|error| format!("serialize request: {error}"))?;
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    command.env("NORRUST_GAME_ID", &request.game_id);
    command.env("NORRUST_REQUEST_ID", &request.decision_id);
    if let Some(path) = usage_sidecar {
        command.env("NORRUST_USAGE_SIDECAR", path);
    } else {
        command.env_remove("NORRUST_USAGE_SIDECAR");
    }
    if let Some(path) = evidence_dir {
        command.env("NORRUST_EVIDENCE_DIR", path);
    } else {
        command.env_remove("NORRUST_EVIDENCE_DIR");
    }
    #[cfg(unix)]
    use std::os::unix::process::CommandExt;
    #[cfg(unix)]
    command.process_group(0);

    let mut child = command
        .spawn()
        .map_err(|error| format!("selector command spawn failed: {error}"))?;
    let pid = child.id();
    let mut stdin = child.stdin.take().expect("piped child stdin");
    let stdout = child.stdout.take().expect("piped child stdout");
    let stderr = child.stderr.take().expect("piped child stderr");

    let input_writer = thread::spawn(move || {
        let result = stdin.write_all(&input);
        drop(stdin);
        result
    });
    let stdout_overflow = Arc::new(AtomicBool::new(false));
    let out_overflow = Arc::clone(&stdout_overflow);
    let stdout_reader =
        thread::spawn(move || read_bounded(stdout, max_response_bytes, Some(out_overflow)));
    let stderr_reader = thread::spawn(move || read_bounded(stderr, 16 * 1024, None));

    let started = Instant::now();
    let status = loop {
        if stdout_overflow.load(Ordering::Relaxed) {
            kill_process_group(pid, &mut child);
            break Err("selector command response exceeded byte limit".to_string());
        }
        match child.try_wait() {
            Ok(Some(status)) => {
                // A command may have left descendants holding the pipes open.
                // The selector contract is one process tree per request.
                kill_process_group(pid, &mut child);
                break Ok(status);
            }
            Ok(None) if started.elapsed() < timeout => thread::sleep(Duration::from_millis(5)),
            Ok(None) => {
                kill_process_group(pid, &mut child);
                break Err("selector command timed out; local process group killed (remote cancellation unknown)".to_string());
            }
            Err(error) => {
                kill_process_group(pid, &mut child);
                break Err(format!("selector command wait failed: {error}"));
            }
        }
    };
    // The parent is reaped by kill_process_group on timeout/overflow and by
    // try_wait on normal completion. Join readers so partial pipe evidence is
    // fully drained before this invocation returns.
    let out = stdout_reader
        .join()
        .map_err(|_| "selector stdout reader panicked".to_string())?
        .map_err(|error| format!("read selector stdout: {error}"))?;
    let _err = stderr_reader
        .join()
        .map_err(|_| "selector stderr reader panicked".to_string())?
        .map_err(|error| format!("read selector stderr: {error}"))?;
    let _ = input_writer.join();
    let status = status?;
    if !status.success() {
        return Err(format!("selector command exited with status {status}"));
    }
    let response: SelectorCommandResponse = serde_json::from_slice(&out)
        .map_err(|error| format!("malformed selector command response: {error}"))?;
    response
        .validate_for(request)
        .map_err(|reason| format!("invalid selector command response: {reason}"))?;
    Ok(response.response)
}

fn read_bounded<R: Read>(
    mut reader: R,
    limit: usize,
    overflow: Option<Arc<AtomicBool>>,
) -> std::io::Result<Vec<u8>> {
    let mut bytes = Vec::with_capacity(limit.min(4096));
    let mut buffer = [0u8; 4096];
    loop {
        let count = reader.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        let available = limit.saturating_sub(bytes.len());
        bytes.extend_from_slice(&buffer[..count.min(available)]);
        if count > available {
            if let Some(flag) = &overflow {
                flag.store(true, Ordering::Relaxed);
                break;
            }
        }
    }
    Ok(bytes)
}

fn kill_process_group(pid: u32, child: &mut std::process::Child) {
    #[cfg(unix)]
    unsafe {
        // SAFETY: the command was started in a fresh process group with pgid=pid.
        kill(-(pid as i32), 9);
    }
    #[cfg(not(unix))]
    let _ = child.kill();
    let _ = child.kill();
    let _ = child.wait();
}

#[derive(Debug, Clone, Copy)]
pub struct SelectorLimits {
    pub timeout: Duration,
    pub max_response_bytes: usize,
    pub max_game_requests: u32,
    pub failure_limit: u32,
}

impl Default for SelectorLimits {
    fn default() -> Self {
        Self {
            timeout: Duration::from_secs(60),
            max_response_bytes: 1024,
            max_game_requests: 32,
            failure_limit: 3,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BackendError {
    BudgetExhausted,
    CircuitOpen,
    Provider(String),
    Timeout,
    Oversized,
    Malformed,
    InvalidResponse(String),
}

/// Per-game limits and failure circuit breaker. Failed physical requests still
/// consume the request allowance.
#[derive(Debug, Clone)]
pub struct SelectorBudget {
    limits: SelectorLimits,
    requests: u32,
    consecutive_failures: u32,
}

impl SelectorBudget {
    pub fn new(limits: SelectorLimits) -> Self {
        Self {
            limits,
            requests: 0,
            consecutive_failures: 0,
        }
    }

    pub fn requests(&self) -> u32 {
        self.requests
    }

    pub fn invoke<F>(
        &mut self,
        request: &SelectorRequest,
        backend: F,
    ) -> Result<SelectorResponse, BackendError>
    where
        F: FnOnce(&SelectorRequest) -> Result<Vec<u8>, String>,
    {
        if self.consecutive_failures >= self.limits.failure_limit {
            return Err(BackendError::CircuitOpen);
        }
        if self.requests >= self.limits.max_game_requests {
            return Err(BackendError::BudgetExhausted);
        }
        self.requests += 1;
        let started = Instant::now();
        let result = backend(request)
            .map_err(BackendError::Provider)
            .and_then(|bytes| {
                if started.elapsed() > self.limits.timeout {
                    return Err(BackendError::Timeout);
                }
                if bytes.len() > self.limits.max_response_bytes {
                    return Err(BackendError::Oversized);
                }
                let response: SelectorResponse =
                    serde_json::from_slice(&bytes).map_err(|_| BackendError::Malformed)?;
                response
                    .validate_for(request)
                    .map_err(|reason| BackendError::InvalidResponse(reason.into()))?;
                Ok(response)
            });
        match result {
            Ok(response) => {
                self.consecutive_failures = 0;
                Ok(response)
            }
            Err(error) => {
                self.consecutive_failures += 1;
                Err(error)
            }
        }
    }
}

/// The response file is intentionally only a local adapter. It returns bytes
/// unchanged for the shared strict Rust selector parser to validate.
pub fn read_response_file(path: &Path, max_bytes: usize) -> Result<Vec<u8>, String> {
    let file = File::open(path).map_err(|error| format!("{}: {error}", path.display()))?;
    let mut bytes = Vec::with_capacity(max_bytes.min(4096));
    file.take(max_bytes.saturating_add(1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|error| format!("{}: {error}", path.display()))?;
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::selector::{CandidateSummary, SELECTOR_SCHEMA_VERSION};

    fn request() -> SelectorRequest {
        SelectorRequest {
            schema_version: SELECTOR_SCHEMA_VERSION,
            turn: 2,
            side: 0,
            state_revision: 7,
            evaluation_seed: 9,
            objective: "Protect".into(),
            candidates: vec!["greedy", "lookahead", "objective"]
                .into_iter()
                .map(|id| CandidateSummary {
                    candidate_id: id.into(),
                    plan_kind: id.into(),
                    label: id.into(),
                    score: 1.0,
                    material_delta: 0.0,
                    gold_delta: 0,
                    village_delta: 0,
                    recruiter_alive: true,
                    objective_progress: 0.0,
                    opponent_response_delta: 0.0,
                    legal: true,
                    state_revision: 7,
                })
                .collect(),
        }
    }

    fn limits() -> SelectorLimits {
        SelectorLimits {
            timeout: Duration::from_millis(10),
            max_response_bytes: 128,
            max_game_requests: 2,
            failure_limit: 2,
        }
    }

    #[test]
    fn accepts_only_a_current_v1_candidate_response() {
        let mut budget = SelectorBudget::new(limits());
        let response = budget
            .invoke(&request(), |_| {
                Ok(br#"{"schema_version":1,"candidate_id":"objective"}"#.to_vec())
            })
            .unwrap();
        assert_eq!(response.candidate_id, "objective");
    }

    #[test]
    fn malformed_unknown_and_oversized_replies_are_rejected() {
        let req = request();
        let mut b = SelectorBudget::new(limits());
        assert_eq!(
            b.invoke(&req, |_| Ok(b"{".to_vec())),
            Err(BackendError::Malformed)
        );
        let mut b = SelectorBudget::new(limits());
        let unknown = br#"{"schema_version":1,"candidate_id":"invented"}"#.to_vec();
        assert!(matches!(
            b.invoke(&req, |_| Ok(unknown)),
            Err(BackendError::InvalidResponse(_))
        ));
        let mut b = SelectorBudget::new(limits());
        assert_eq!(
            b.invoke(&req, |_| Ok(vec![b' '; 129])),
            Err(BackendError::Oversized)
        );
    }

    #[test]
    fn delayed_and_provider_failures_fall_back_and_open_circuit() {
        let req = request();
        let mut b = SelectorBudget::new(limits());
        assert_eq!(
            b.invoke(&req, |_| {
                std::thread::sleep(Duration::from_millis(15));
                Ok(Vec::new())
            }),
            Err(BackendError::Timeout)
        );
        assert!(matches!(
            b.invoke(&req, |_| Err("local backend unavailable".into())),
            Err(BackendError::Provider(_))
        ));
        assert_eq!(
            b.invoke(&req, |_| Ok(Vec::new())),
            Err(BackendError::CircuitOpen)
        );
        assert_eq!(b.requests(), 2);
    }

    #[test]
    fn game_request_budget_is_charged_before_dispatch() {
        let req = request();
        let mut b = SelectorBudget::new(limits());
        for _ in 0..2 {
            let _ = b.invoke(&req, |_| Err("failure".into()));
        }
        assert_eq!(b.requests(), 2);
        assert_eq!(
            b.invoke(&req, |_| Ok(Vec::new())),
            Err(BackendError::CircuitOpen)
        );
    }

    #[test]
    fn command_request_envelope_binds_identity_and_request_hash() {
        let request = SelectorCommandRequest::new("game-1".into(), "decision-1".into(), request());
        let valid = SelectorCommandResponse {
            schema_version: COMMAND_ENVELOPE_VERSION,
            game_id: request.game_id.clone(),
            decision_id: request.decision_id.clone(),
            request_sha256: request.request_sha256.clone(),
            response: SelectorResponse {
                schema_version: SELECTOR_SCHEMA_VERSION,
                candidate_id: "objective".into(),
                reason_code: None,
            },
        };
        assert!(valid.validate_for(&request).is_ok());
        let mut stale = valid.clone();
        stale.decision_id = "decision-from-earlier-turn".into();
        assert_eq!(
            stale.validate_for(&request),
            Err("selector command response identity mismatch")
        );
        let mut wrong_hash = valid;
        wrong_hash.request_sha256 = "0".repeat(64);
        assert_eq!(
            wrong_hash.validate_for(&request),
            Err("selector command response request hash mismatch")
        );
    }

    #[cfg(unix)]
    #[test]
    fn command_deadline_kills_and_reaps_parent_and_child_processes() {
        let request = SelectorCommandRequest::new("game-1".into(), "decision-1".into(), request());
        let start = Instant::now();
        let error = invoke_command(
            Path::new("/bin/sh"),
            &["-c".into(), "sleep 30 & wait".into()],
            &request,
            Duration::from_millis(80),
            1024,
            None,
            None,
        )
        .unwrap_err();
        assert!(error.contains("local process group killed"), "{error}");
        assert!(
            start.elapsed() < Duration::from_secs(2),
            "elapsed {:?}",
            start.elapsed()
        );
        // The background process shares the command's process group and must
        // be gone by the time the adapter returns.
        let child_pids = std::process::Command::new("pgrep")
            .args(["-f", "^sleep 30$"])
            .output()
            .expect("pgrep available in unix test environment");
        assert!(
            child_pids.stdout.is_empty(),
            "lingering child: {:?}",
            child_pids.stdout
        );
    }

    #[cfg(unix)]
    #[test]
    fn command_response_is_bounded_while_subprocess_runs() {
        let request = SelectorCommandRequest::new("game-1".into(), "decision-1".into(), request());
        let error = invoke_command(
            Path::new("/bin/sh"),
            &["-c".into(), "yes x".into()],
            &request,
            Duration::from_secs(2),
            32,
            None,
            None,
        )
        .unwrap_err();
        assert!(error.contains("exceeded byte limit"), "{error}");
    }
}
