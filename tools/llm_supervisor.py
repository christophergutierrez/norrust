#!/usr/bin/env python3
"""Run llm_client with bounded recovery from process/infrastructure failure."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import signal
import subprocess
import sys
import time
import uuid
import fcntl
from pathlib import Path

try:
    from .request_recovery import reconcile_request, reconcile_journal
    from .request_journal import _safe_session_name
    from .run_watchdog import RunWatchdog
    from .watchdog_stop import accept_stop, read_stop, resolve_stop, stop_run, validate_stop_request
    from .llm_client import classify_terminal, TERMINAL_GAMEPLAY
except ImportError:  # Direct ``python tools/llm_supervisor.py`` invocation.
    from request_recovery import reconcile_request, reconcile_journal
    from request_journal import _safe_session_name
    from run_watchdog import RunWatchdog
    from watchdog_stop import accept_stop, read_stop, resolve_stop, stop_run, validate_stop_request
    from llm_client import classify_terminal, TERMINAL_GAMEPLAY
STOP_EXIT_CODE = 4
STOP_GRACE_SECONDS = 5.0


@dataclass
class ProcessCleanup:
    """Evidence about a supervisor-owned process-tree cleanup."""

    attempted: bool
    graceful: bool
    forced: bool
    remaining_pids: list[int]
    elapsed_seconds: float


def _descendants(root_pid: int) -> set[int]:
    """Return descendants using Linux proc evidence, without shelling out."""
    parents: dict[int, int] = {}
    proc_root = Path("/proc")
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            # comm may contain spaces; fields before the final ')' are not
            # safe to split. After it, field 0 is state and field 1 is ppid.
            fields = raw[raw.rfind(")") + 2:].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            continue
    result: set[int] = set()
    frontier = [root_pid]
    while frontier:
        parent = frontier.pop()
        children = [pid for pid, ppid in parents.items() if ppid == parent]
        for child in children:
            if child not in result:
                result.add(child)
                frontier.append(child)
    return result


def _proc_starttime(pid: int) -> str | None:
    """Return Linux's PID identity component to avoid killing a reused PID."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = raw[raw.rfind(")") + 2:].split()
        if fields[0] == "Z":
            # A zombie has no running process to cancel. Its PID can remain
            # visible until the parent reaps it, so do not report it as a
            # surviving owned process during bounded cleanup.
            return None
        return fields[19]
    except (OSError, IndexError):
        return None


def terminate_process_tree(process: subprocess.Popen, grace_seconds: float = STOP_GRACE_SECONDS,
                           poll_interval: float = 0.05) -> ProcessCleanup:
    """Terminate only the child's session/process tree, then force it boundedly.

    The supervisor starts the client with ``start_new_session=True``. The
    process group catches ordinary nested shells and provider children; the
    descendant pass also catches a child that deliberately calls ``setsid``.
    """
    started = time.monotonic()
    root_pid = process.pid
    try:
        pgid = os.getpgid(root_pid)
    except ProcessLookupError:
        pgid = None
    owned = {root_pid} | _descendants(root_pid)
    identities = {pid: _proc_starttime(pid) for pid in owned}

    def survivors() -> set[int]:
        return {pid for pid, identity in identities.items()
                if identity is not None and _proc_starttime(pid) == identity}

    def reap_root() -> None:
        if process.poll() is not None:
            try:
                process.wait(timeout=0)
            except subprocess.TimeoutExpired:
                pass

    if pgid is not None and pgid > 1 and pgid != os.getpgrp():
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for pid in sorted(owned):
        if pid == process.pid:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = started + max(0.0, float(grace_seconds))
    while survivors() and time.monotonic() < deadline:
        reap_root()
        time.sleep(min(max(0.001, poll_interval), max(0.001, deadline - time.monotonic())))
    graceful = not survivors()
    forced = False
    if survivors():
        forced = True
        try:
            if pgid is not None and pgid > 1 and pgid != os.getpgrp():
                os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for pid in sorted(survivors()):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # A parent may have exited while a detached child is still scheduled.
        # Allow a small bounded margin for SIGKILL to become observable.
        force_deadline = time.monotonic() + max(0.1, min(1.0, float(grace_seconds) + 0.1))
        while survivors() and time.monotonic() < force_deadline:
            reap_root()
            time.sleep(min(max(0.001, poll_interval),
                           max(0.001, force_deadline - time.monotonic())))
    reap_root()
    try:
        process.wait(timeout=max(1.0, grace_seconds + 1.0))
    except subprocess.TimeoutExpired:
        # The caller records this as incomplete cleanup; never block forever.
        pass
    remaining = sorted(survivors())
    return ProcessCleanup(True, graceful, forced, remaining, time.monotonic() - started)


def _stop_effective(intent: dict | None) -> bool:
    return isinstance(intent, dict) and (
        intent.get("status") == "accepted" or
        intent.get("resolution") in {"cancelled", "cancelled_by_client"})


def _watchdog_validation(log: Path, intent: dict) -> tuple[bool, str]:
    """Revalidate an intent against the latest persisted progress packet."""
    watchdog = log.parent / f"{log.stem}.watchdog"
    state_path = watchdog / "state.json"
    journal_path = watchdog / "journal.ndjson"
    state: dict = {}
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            state = value
    except (OSError, ValueError, json.JSONDecodeError):
        state = {}
    latest: dict = {}
    observed_packet: dict | None = None
    try:
        for raw in journal_path.read_text(encoding="utf-8").splitlines():
            value = json.loads(raw)
            if isinstance(value, dict) and value.get("type") == "status" and isinstance(value.get("status"), dict):
                latest = value["status"]
                if latest.get("observation_sequence") == intent.get("observed_sequence"):
                    observed_packet = latest
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    terminal = _last_terminal(log)
    if terminal is not None and _terminal_class(terminal) == "gameplay":
        return False, "natural_completion_wins"
    evidence_index = {item.get("evidence_id") for item in state.get("index", [])
                      if isinstance(item, dict) and isinstance(item.get("evidence_id"), str)}
    evidence = intent.get("evidence_ids") or []
    reason = str(intent.get("reason_code", ""))
    # Explicit operator stops may intentionally have no incident evidence.
    if not evidence and not (reason.startswith("manual") or reason.startswith("operator")):
        return False, "stale_evidence"
    if any(item not in evidence_index for item in evidence):
        return False, "stale_evidence"
    current = latest.get("observation_sequence", state.get("observation_sequence"))
    valid, why = validate_stop_request(
        intent, run_id=state.get("run_id") or intent.get("run_id"), active=terminal is None,
        current_sequence=current if isinstance(current, int) else None,
        terminal=terminal,
        evidence_validator=lambda item: item in evidence_index,
        # A semantic recommendation is tied to the exact packet that supplied
        # its evidence. A later packet can show that the suspected incident
        # cleared even when the observation counter advanced normally.
        # Recorder packets advance while the observer's investigation is in
        # flight. The controller has already fenced progress/incident
        # identity; requiring byte-exact sequence here would reject every
        # valid asynchronous recommendation.
        require_current_sequence=False)
    if not valid:
        return False, why
    if observed_packet is None and evidence:
        return False, "stale_observation"
    if evidence and observed_packet is not None:
        if _progress_identity(observed_packet) != _progress_identity(latest):
            return False, "stale_progress"
        if _incident_identity(observed_packet) != _incident_identity(latest):
            return False, "stale_incident"
    # Evidence belongs to the observed incident. A growing stream replaces
    # the latest packet's excerpt without invalidating an immutable older
    # range; progress and incident identity were revalidated above.
    if evidence and observed_packet:
        packet_text = json.dumps(observed_packet, sort_keys=True)
        if not all(item in packet_text for item in evidence):
            return False, "stale_incident"
    if not latest and evidence:
        return False, "watchdog_status_unavailable"
    return True, "validated"


def _progress_identity(packet: dict) -> tuple:
    committed = packet.get("committed_action")
    if isinstance(committed, dict):
        committed = (committed.get("batch_id"), committed.get("revision"))
    request = packet.get("current_request")
    if isinstance(request, dict):
        request = (request.get("harness_request_id"), request.get("request_id"))
    return (packet.get("revision"), packet.get("last_completed_turn"), committed, request)


def _incident_identity(packet: dict) -> tuple[str, ...]:
    alerts = packet.get("alerts")
    if not isinstance(alerts, list):
        return ()
    return tuple(sorted({alert.get("identity") for alert in alerts
                         if isinstance(alert, dict) and isinstance(alert.get("identity"), str)}))


def _run_attempt(command: list[str], log: Path, *, poll_interval: float = 0.1,
                grace_seconds: float = STOP_GRACE_SECONDS,
                watchdog: RunWatchdog | None = None,
                environment: dict[str, str] | None = None,
                observer_poller=None) -> tuple[subprocess.CompletedProcess, dict | None, ProcessCleanup | None]:
    """Run one attempt with a responsive stop poll and owned process session."""
    intent = read_stop(log)
    if isinstance(intent, dict) and intent.get("status") == "pending":
        valid, why = _watchdog_validation(log, intent)
        if valid:
            intent = accept_stop(log, details={"validation": why})
        else:
            resolve_stop(log, why if why == "natural_completion_wins" else f"stale_{why}")
            _append(log, {"type": "stop_ignored", "request_id": intent.get("request_id"),
                          "reason": why})
            intent = None
    if _stop_effective(intent):
        return subprocess.CompletedProcess(command, STOP_EXIT_CODE), intent, None
    # Every supervised child gets its own session so cleanup covers shells and
    # descendants. A watchdog is passed to the child through environment
    # variables; polling remains recording-only and cannot accept a stop.
    process = subprocess.Popen(command, start_new_session=True, env=environment)
    while process.poll() is None:
        if watchdog is not None:
            try:
                packet = watchdog.poll()
                if observer_poller is not None:
                    observer_poller(packet)
            except Exception as exc:
                _append(log, {"type": "supervisor_watchdog_error", "message": str(exc)})
        intent = read_stop(log)
        if isinstance(intent, dict) and intent.get("status") == "pending":
            valid, why = _watchdog_validation(log, intent)
            if valid:
                intent = accept_stop(log, details={"validation": why})
            else:
                resolve_stop(log, why if why == "natural_completion_wins" else f"stale_{why}")
                _append(log, {"type": "stop_ignored", "request_id": intent.get("request_id"),
                              "reason": why})
                intent = None
        if _stop_effective(intent):
            cleanup = terminate_process_tree(process, grace_seconds, poll_interval / 2)
            return subprocess.CompletedProcess(command, STOP_EXIT_CODE), intent, cleanup
        time.sleep(max(0.01, poll_interval))
    return subprocess.CompletedProcess(command, process.returncode), None, None


def _checkpoint_evidence(log: Path) -> dict | None:
    """Return only a checkpoint referenced and digest-validated by the log."""
    directory = log.with_suffix(".ckpt").resolve()
    if not directory.is_dir() or directory.is_symlink():
        return None
    for record in reversed(_records(log)):
        if record.get("type") != "checkpoint_ref":
            continue
        relative = record.get("path")
        expected = record.get("digest")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            continue
        path = (directory / relative).resolve()
        try:
            path.relative_to(directory)
            payload = path.read_bytes()
        except (OSError, ValueError):
            continue
        actual = __import__("hashlib").sha256(payload).hexdigest()
        if not isinstance(expected, str) or actual != expected:
            continue
        return {"path": path.relative_to(directory).as_posix(), "sha256": actual,
                "bytes": len(payload),
                **{key: record[key] for key in
                   ("state_revision", "side_turns", "boundary") if key in record}}
    return None


def _action_boundary_status(log: Path) -> str:
    """Classify the last forwarded batch when the child is killed externally."""
    records = _records(log)
    forwarded = next((record for record in reversed(records)
                     if record.get("type") == "forwarded_orders" and record.get("batch_id")), None)
    if forwarded is None:
        return "none"
    batch_id = forwarded.get("batch_id")
    if any(record.get("type") == "batch_committed" and record.get("batch_id") == batch_id
           for record in records):
        return "committed"
    return "unknown"


def _append_observer_terminal(log: Path, intent: dict, cleanup: ProcessCleanup | None) -> None:
    """Record cancellation when the client was killed before its own fence."""
    records = _records(log)
    existing_terminal = _last_terminal(log)
    if isinstance(existing_terminal, dict) and _terminal_class(existing_terminal) == "gameplay":
        return
    if isinstance(existing_terminal, dict) and _terminal_class(existing_terminal) == "observer_interrupted":
        return
    metadata = next((dict(record) for record in reversed(records)
                     if record.get("type") == "metadata"), {})
    context = {}
    context_path = log.parent / "request_context.json"
    try:
        value = json.loads(context_path.read_text(encoding="utf-8"))
        if isinstance(value, dict):
            context = {key: value.get(key) for key in
                       ("harness_request_id", "request_sequence", "state_revision",
                        "native_request_id", "dispatched_at") if key in value}
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    details = {
        "type": "observer_interrupted", "terminal_class": "observer_interrupted",
        "infrastructure_invalid": False, "gameplay_valid": False,
        "winner": None, "winner_side": None, "reason": "observer_interrupted",
        "code": intent.get("reason_code"), "stop_request_id": intent.get("request_id"),
        "stop_reason_code": intent.get("reason_code"),
        "evidence_ids": intent.get("evidence_ids", []),
        "observed_sequence": intent.get("observed_sequence"),
        "final_proven_checkpoint": _checkpoint_evidence(log),
        "action_boundary_status": _action_boundary_status(log),
        "cancellation_status": ("complete" if cleanup and not cleanup.remaining_pids else "unknown"),
        "remote_cancellation": "unknown", "coverage_status": "unknown",
        "cleanup": (None if cleanup is None else cleanup.__dict__), **context}
    metadata.update(details)
    _append(log, details)
    _append(log, {**metadata, "type": "terminal"})


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


def _terminal_class(record: dict | None) -> str | None:
    """Classify explicit budget evidence for supervisor reporting.

    Older clients stamped a budget stop as model-invalid. The supervisor must
    preserve the stop and report its corrected class; it must never turn it
    into a recoverable infrastructure restart.
    """
    if not isinstance(record, dict):
        return None
    if record.get("type") == "budget_interrupted":
        return "budget_interrupted"
    reason = record.get("reason") or record.get("termination_reason")
    code = record.get("code") or record.get("failure_code") or record.get("error_code")
    if reason == "budget_interrupted" or code in {"max_game_total_tokens_exhausted",
                                                  "model_calls_budget_exhausted"}:
        return "budget_interrupted"
    value = record.get("terminal_class")
    return value if isinstance(value, str) else None


def _has_checkpoint(log: Path) -> bool:
    directory = log.with_suffix(".ckpt")
    return any(path.is_file() and path.suffix == ".json" for path in directory.glob("*.json"))


def _last_terminal(log: Path) -> dict | None:
    records = _records(log)
    terminal = _terminal_record(records)
    natural = _game_end_terminal(records)
    # A driver game_end is authoritative even if a SIGTERM lets the client
    # append an infrastructure diagnostic before the supervisor observes the
    # accepted stop. Preserve the engine result as the natural race winner.
    if natural is not None and (natural.get("terminal_class") == TERMINAL_GAMEPLAY
                                or terminal is None
                                or _terminal_class(terminal) in {"infrastructure", None}):
        return natural
    return terminal


def _game_end_terminal(records: list[dict]) -> dict | None:
    for record in reversed(records):
        line = record.get("line") if record.get("type") == "driver" else record
        if isinstance(line, dict) and line.get("type") == "game_end":
            reason = line.get("reason")
            terminal_class = classify_terminal(reason)
            return {"type": "derived_game_end", "terminal_class": terminal_class,
                    "winner": line.get("winner") if terminal_class == TERMINAL_GAMEPLAY else None,
                    "reason": reason,
                    "code": (line.get("code") or line.get("failure_code")
                             or line.get("error_code"))}
    return None


def _terminal_record(records: list[dict]) -> dict | None:
    """Return the newest maintained or legacy terminal evidence.

    Current clients normally pair a typed budget/model failure with a
    ``terminal`` record, but older and interrupted paths can leave only the
    typed failure.  Letting that record fall through as ``terminal is None``
    would authorize reconciliation and a resume when the outcome is already
    final.
    """
    terminal = next((record for record in reversed(records)
                     if record.get("type") in {
                         "terminal", "budget_interrupted", "model_error", "checkpoint_error",
                     }), None)
    if terminal is not None and terminal.get("type") in {"model_error", "checkpoint_error"}:
        # Older client failure paths durably wrote model_error without a
        # separate terminal record. Treat only the latest such record as
        # terminal evidence; ordinary model/driver records must never trigger
        # a resume.
        return {"terminal_class": _terminal_class(terminal) or
                ("infrastructure" if terminal.get("type") == "checkpoint_error" else None),
                "type": "derived_terminal", "source_type": terminal.get("type"),
                "reason": terminal.get("reason"), "code": terminal.get("code")}
    if terminal is not None:
        return terminal
    return terminal


def _append(log: Path, value: dict) -> None:
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _journal_state_from_environment() -> Path | None:
    root = os.environ.get("NORRUST_CODEX_JOURNAL_ROOT")
    session = os.environ.get("NORRUST_CODEX_MATCH_ID")
    if not root or not session:
        artifact = os.environ.get("NORRUST_CODEX_ARTIFACT_DIR")
        if artifact:
            root, session = str(Path(artifact) / "requests"), os.environ.get("NORRUST_CODEX_MATCH_ID")
    if not root or not session:
        return None
    requests = Path(root) / _safe_session_name(session) / "requests"
    candidates = [p / "state.json" for p in requests.iterdir()
                  if p.is_dir() and (p / "state.json").is_file()] if requests.is_dir() else []
    if not candidates:
        return None
    def order(path: Path) -> tuple[int, float, str]:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            return int(state.get("sequence", 0)), float(state.get("created_at", 0)), path.parent.name
        except (OSError, ValueError, TypeError):
            return -1, -1, path.parent.name
    return max(candidates, key=order)


def _supervisor_state_path(log: Path) -> Path:
    return log.with_suffix(".supervisor.json")


def _watchdog_for_log(log: Path) -> RunWatchdog:
    """Open the recorder without replacing a progress worker's run UUID."""
    state_path = log.parent / f"{log.stem}.watchdog" / "state.json"
    run_id = None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("run_id"), str):
            run_id = state["run_id"]
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    if run_id is None:
        intent = read_stop(log)
        if intent is not None:
            run_id = intent["run_id"]
    return RunWatchdog(log, run_id=run_id)


def _write_state(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _attempt_records(log: Path, start: int) -> list[dict]:
    return _records(log)[start:]


def run(command: list[str], log: Path, max_restarts: int,
        request_state: Path | None = None, *, watchdog: RunWatchdog | None = None,
        poll_interval: float = 0.1, watchdog_mode: str = "off",
        watchdog_model: str = "gpt-5.4-nano", observer_backend=None,
        observer_clock=None, observer_max_calls: int = 20) -> int:
    if watchdog_mode not in {"off", "observe", "enforce"}:
        raise ValueError("watchdog_mode must be off, observe, or enforce")
    log.parent.mkdir(parents=True, exist_ok=True)
    lock_path = log.with_suffix(".supervisor.lock")
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(lock_fd)
        _append(log, {"type": "supervisor_error", "code": "active_supervisor",
                      "message": str(exc)})
        return 1
    state_path = _supervisor_state_path(log)
    watchdog = watchdog or _watchdog_for_log(log)
    observer_holder = {"controller": None}

    def poll_observer(packet):
        if watchdog_mode == "off":
            return
        controller = observer_holder["controller"]
        if controller is None:
            try:
                from .watchdog_integration import WatchdogIdentityError, attach_observer
                from .watchdog_observer import OpenAIObserverBackend
            except ImportError:
                from watchdog_integration import WatchdogIdentityError, attach_observer
                from watchdog_observer import OpenAIObserverBackend
            try:
                backend = observer_backend
                if backend is None:
                    backend = OpenAIObserverBackend(model=watchdog_model)
                controller = attach_observer(
                    watchdog, log, backend=backend, mode=watchdog_mode,
                    stop=lambda run_id, reason, evidence, sequence: stop_run(
                        log, reason, list(evidence), sequence), clock=observer_clock,
                    max_calls=observer_max_calls)
            except WatchdogIdentityError:
                # Metadata/request context may not have been written yet.
                # Retry on the next recorder packet; no provider call exists.
                return
            observer_holder["controller"] = controller
        controller.poll(packet)

    def close_observer():
        controller = observer_holder.get("controller")
        if controller is not None:
            controller.close(wait=False)
            observer_holder["controller"] = None
    try:
        try:
            supervisor_state = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(supervisor_state, dict):
                raise ValueError("supervisor state is not an object")
        except FileNotFoundError:
            supervisor_state = {"version": 1, "restarts": 0, "failure_counts": {}}
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _append(log, {"type": "supervisor_error", "code": "state_unavailable",
                          "message": str(exc)})
            return 1
        discovered_state = request_state or _journal_state_from_environment()
        journal_root = os.environ.get("NORRUST_CODEX_JOURNAL_ROOT")
        if not journal_root and os.environ.get("NORRUST_CODEX_ARTIFACT_DIR"):
            os.environ["NORRUST_CODEX_JOURNAL_ROOT"] = str(
                Path(os.environ["NORRUST_CODEX_ARTIFACT_DIR"]) / "requests")
        while True:
            attempt = int(supervisor_state.get("attempts", 0)) + 1
            attempt_id = f"attempt-{attempt}-{uuid.uuid4().hex[:12]}"
            start = len(_records(log))
            _append(log, {"type": "supervisor_attempt_start", "attempt": attempt,
                          "attempt_id": attempt_id, "log_offset": start})
            os.environ["NORRUST_CODEX_ATTEMPT_ID"] = attempt_id
            invocation = command if attempt == 1 else command + ["--resume-log", str(log)]
            environment = os.environ.copy()
            # These paths belong to this run. Inherited host/session values
            # must not redirect evidence to another game's directory.
            environment["NORRUST_WATCHDOG_RUN_ID"] = watchdog.run_id
            environment["NORRUST_WATCHDOG_DIR"] = str(watchdog.run_directory)
            environment["NORRUST_EVIDENCE_DIR"] = str(watchdog.evidence_dir)
            environment["NORRUST_REQUEST_CONTEXT_FILE"] = str(log.parent / "request_context.json")
            try:
                packet = watchdog.poll(force=True)
                poll_observer(packet)
            except Exception as exc:
                _append(log, {"type": "supervisor_watchdog_error", "message": str(exc)})
            completed, stop_intent, cleanup = _run_attempt(
                invocation, log, watchdog=watchdog, environment=environment,
                poll_interval=poll_interval, observer_poller=poll_observer)
            try:
                packet = watchdog.poll(force=True)
                poll_observer(packet)
            except Exception as exc:
                _append(log, {"type": "supervisor_watchdog_error", "message": str(exc)})
            if stop_intent is None:
                # The child can finish between its last poll and this return;
                # preserve a natural winner even when the intent arrived in
                # that narrow post-exit window.
                late_intent = read_stop(log)
                late_terminal = _last_terminal(log)
                if isinstance(late_intent, dict) and isinstance(late_terminal, dict):
                    late_reason = ("natural_completion_wins"
                                   if _terminal_class(late_terminal) == "gameplay"
                                   else "terminal_already_recorded")
                    resolve_stop(log, late_reason)
                    _append(log, {"type": "stop_ignored", "request_id": late_intent.get("request_id"),
                                  "reason": late_reason})
            if stop_intent is not None:
                # A gameplay terminal established by the child wins a stop
                # request that arrived at the same boundary. The intent stays
                # recorded, with an explicit ignored resolution for audit.
                terminal_after_cleanup = _last_terminal(log)
                if isinstance(terminal_after_cleanup, dict) and _terminal_class(terminal_after_cleanup) == "gameplay":
                    resolve_stop(log, "natural_completion_wins")
                    _append(log, {"type": "stop_ignored", "request_id": stop_intent.get("request_id"),
                                  "reason": "natural_completion_wins"})
                    completed = subprocess.CompletedProcess(invocation, 0)
                else:
                    _append_observer_terminal(log, stop_intent, cleanup)
                    resolve_stop(log, "cancelled", details={
                        "cleanup": None if cleanup is None else cleanup.__dict__})
                    return STOP_EXIT_CODE
            new_records = _attempt_records(log, start + 1)
            terminal = _terminal_record(new_records)
            terminal_class = _terminal_class(terminal)
            budget_stop = terminal_class == "budget_interrupted"
            recoverable_exit = (not budget_stop and
                                (completed.returncode < 0 or
                                 terminal_class == "infrastructure" or terminal is None))
            discovered_state = discovered_state or _journal_state_from_environment()
            reconciliation = None
            if recoverable_exit:
                if discovered_state is None:
                    reason = "no match-owned request journal was discoverable"
                else:
                    try:
                        reconciliation = reconcile_request(
                            discovered_state, log,
                            checkpoint_dir=log.with_suffix(".ckpt"))
                        reason = reconciliation.reason
                    except (OSError, ValueError) as exc:
                        reason = f"reconciliation error: {exc}"
                if reconciliation is None:
                    safe = False
                    rec_state = "unknown"
                    request_id = None
                else:
                    safe = reconciliation.safe_to_restart
                    rec_state = reconciliation.state
                    request_id = reconciliation.request_id
                _append(log, {"type": "supervisor_reconciliation", "attempt": attempt,
                              "attempt_id": attempt_id, "state": rec_state,
                              "safe_to_restart": safe, "reason": reason,
                              "request_id": request_id})
            else:
                safe, rec_state, reason = False, "terminal", "terminal outcome"
            outcome = {"type": "supervisor_attempt_outcome", "attempt": attempt,
                       "attempt_id": attempt_id, "returncode": completed.returncode,
                       "terminal_class": terminal_class, "terminal": terminal,
                       "recovery_state": rec_state, "recovery_decision": "restart" if safe else "stop",
                       "reason": reason}
            _append(log, outcome)
            supervisor_state["attempts"] = attempt
            supervisor_state["last_attempt_id"] = attempt_id
            supervisor_state["last_outcome"] = outcome
            _write_state(state_path, supervisor_state)
            if not recoverable_exit or not safe:
                return completed.returncode
            if not _has_checkpoint(log):
                _append(log, {"type": "supervisor_error", "code": "checkpoint_unavailable",
                              "attempt": attempt, "message": "safe recovery has no checkpoint"})
                return completed.returncode
            key = f"{terminal.get('code') if terminal else ('signal' if completed.returncode < 0 else 'no_terminal')}:{rec_state}:{getattr(reconciliation, 'source_revision', None)}"
            failures = supervisor_state.setdefault("failure_counts", {})
            failures[key] = int(failures.get(key, 0)) + 1
            if (int(supervisor_state.get("restarts", 0)) >= min(max_restarts, 3)
                    or failures[key] > 2):
                _append(log, {"type": "supervisor_error", "code": "restart_limit",
                              "attempt": attempt, "failure_key": key,
                              "count": failures[key]})
                _write_state(state_path, supervisor_state)
                return completed.returncode
            supervisor_state["restarts"] = int(supervisor_state.get("restarts", 0)) + 1
            _write_state(state_path, supervisor_state)
            _append(log, {"type": "supervisor_restart", "attempt": attempt,
                          "attempt_id": attempt_id, "restart": supervisor_state["restarts"],
                          "reason": reason, "failure_key": key})
            time.sleep(min(0.25, 0.05 * supervisor_state["restarts"]))
    finally:
        close_observer()
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--request-state", type=Path,
                        help="durable model request state used to authorize recovery")
    parser.add_argument("--watchdog-mode", choices=("off", "observe", "enforce"), default="off",
                        help="bounded observer mode (default: off)")
    parser.add_argument("--watchdog-model", default="gpt-5.4-nano",
                        help="observer model (used only when watchdog mode is enabled)")
    parser.add_argument("--watchdog-max-calls", type=int, default=20,
                        help="observer physical-call cap (default: 20; offline evals may use 3)")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="client command after --")
    args = parser.parse_args(argv)
    if args.max_restarts < 0:
        parser.error("--max-restarts must be non-negative")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a client command is required after --")
    if "--log" not in command:
        parser.error("the client command must include --log")
    if args.watchdog_max_calls < 1 or args.watchdog_max_calls > 20:
        parser.error("--watchdog-max-calls must be between 1 and 20")
    return run(command, args.log, args.max_restarts, args.request_state,
               watchdog_mode=args.watchdog_mode, watchdog_model=args.watchdog_model,
               observer_max_calls=args.watchdog_max_calls)


if __name__ == "__main__":
    raise SystemExit(main())
