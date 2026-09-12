#!/usr/bin/env python3
"""Run llm_client with bounded recovery from process/infrastructure failure."""
from __future__ import annotations

import argparse
import json
import os
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
except ImportError:  # Direct ``python tools/llm_supervisor.py`` invocation.
    from request_recovery import reconcile_request, reconcile_journal
    from request_journal import _safe_session_name
    from run_watchdog import RunWatchdog


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
    return _terminal_record(_records(log))


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
        poll_interval: float = 0.1) -> int:
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
    watchdog = watchdog or RunWatchdog(log)
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
            # Popen keeps the supervisor responsive while a provider call is
            # open. The watchdog itself throttles evidence reads to its
            # configured five-second cadence; polling process state more
            # often keeps hard completion/recovery behavior unchanged.
            environment = os.environ.copy()
            # These paths belong to this run. Inherited host/session values
            # must not redirect evidence to another game's directory.
            environment["NORRUST_WATCHDOG_RUN_ID"] = watchdog.run_id
            environment["NORRUST_WATCHDOG_DIR"] = str(watchdog.run_directory)
            environment["NORRUST_EVIDENCE_DIR"] = str(watchdog.evidence_dir)
            environment["NORRUST_REQUEST_CONTEXT_FILE"] = str(log.parent / "request_context.json")
            try:
                watchdog.poll(force=True)
            except Exception as exc:
                _append(log, {"type": "supervisor_watchdog_error", "message": str(exc)})
            try:
                child = subprocess.Popen(invocation, env=environment)
            except OSError:
                raise
            while child.poll() is None:
                try:
                    watchdog.poll()
                except Exception as exc:
                    _append(log, {"type": "supervisor_watchdog_error", "message": str(exc)})
                time.sleep(max(0.01, min(float(poll_interval), 1.0)))
            completed = child
            try:
                watchdog.poll(force=True)
            except Exception as exc:
                _append(log, {"type": "supervisor_watchdog_error", "message": str(exc)})
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
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--max-restarts", type=int, default=3)
    parser.add_argument("--request-state", type=Path,
                        help="durable model request state used to authorize recovery")
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
    return run(command, args.log, args.max_restarts, args.request_state)


if __name__ == "__main__":
    raise SystemExit(main())
