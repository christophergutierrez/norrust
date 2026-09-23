//! Small local backend helpers for the versioned Coordinated Planner selector.
//! The request and response remain the Rust selector v1 JSON contract.

use crate::selector::{SelectorRequest, SelectorResponse};
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::time::{Duration, Instant};

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
            timeout: Duration::from_secs(2),
            max_response_bytes: 4096,
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
}
