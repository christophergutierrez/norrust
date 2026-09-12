#!/usr/bin/env python3
"""Durable, idempotent stop intents for bounded watchdog runs.

The watchdog writes an intent before the supervisor sends a signal.  This
module deliberately does not signal processes: the supervisor owns process
groups and is the only component allowed to resolve an intent.  Keeping the
two operations separate makes a crash between persistence and cancellation
observable and prevents a resumed client from silently forgetting a stop.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid
from typing import Any, Callable, Mapping


STOP_VERSION = 1
STOP_SUFFIX = ".stop.json"
STOP_LOCK_SUFFIX = ".stop.lock"
WATCHDOG_DIRECTORY_SUFFIX = ".watchdog"
MAX_EVIDENCE_IDS = 32
MAX_EVIDENCE_ID_LENGTH = 256
MAX_REASON_LENGTH = 96
_SAFE_REASON = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")


class StopError(ValueError):
    """A malformed or unusable stop intent."""


class StopFileError(StopError):
    """The durable stop sidecar cannot be parsed safely."""


class StopIntentConflict(StopError):
    """A caller attempted to overwrite an existing stop intent."""


def _safe_component(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise StopError("run_id must be a non-empty string of at most 256 characters")
    if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
        raise StopError("run_id must be a single path-safe identifier")
    return value


def stop_path_for_log(log_path: str | os.PathLike[str]) -> Path:
    """Return the stop sidecar in the recorder's run-owned directory."""
    path = Path(log_path)
    stem = path.name[:-len(".ndjson")] if path.name.endswith(".ndjson") else path.stem
    return path.parent / f"{stem}{WATCHDOG_DIRECTORY_SUFFIX}" / "stop.json"


def _run_id_for_log(log_path: Path) -> str:
    """Recover the persisted recorder UUID when the caller supplies a log."""
    state = log_path.parent / f"{log_path.stem}{WATCHDOG_DIRECTORY_SUFFIX}" / "state.json"
    try:
        value = json.loads(state.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("run_id"), str):
            return _validate_run_id(value["run_id"])
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    # A stop created before launch establishes a unique run identity.
    existing = _read(stop_path_for_log(log_path))
    return existing["run_id"] if existing is not None else uuid.uuid4().hex


def _path_for_run(run_id: str | os.PathLike[str], root: str | os.PathLike[str] | None = None) -> Path:
    value = str(run_id)
    candidate = Path(value)
    # A supervisor/client passes its actual log path.  Accept a run directory
    # too, which is useful to the status module and keeps IDs out of paths.
    if candidate.suffix == ".ndjson" or (candidate.exists() and candidate.is_file()):
        return stop_path_for_log(candidate)
    if candidate.exists() and candidate.is_dir():
        state = candidate / "state.json"
        try:
            value = json.loads(state.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("log_path"), str):
                return stop_path_for_log(candidate.parent / value["log_path"])
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return candidate / "stop.json"
    safe = _safe_component(value)
    base = Path(root or os.environ.get("NORRUST_WATCHDOG_ROOT", ".watchdog"))
    # RunWatchdog stores the canonical UUID in <log>.watchdog/state.json. Scan
    # only that operator-selected parent so an ID cannot resolve to an
    # arbitrary path outside the run's evidence root.
    if base.is_dir():
        try:
            for state in base.glob(f"*{WATCHDOG_DIRECTORY_SUFFIX}/state.json"):
                value_from_state = json.loads(state.read_text(encoding="utf-8"))
                if isinstance(value_from_state, dict) and value_from_state.get("run_id") == safe:
                    return state.parent / "stop.json"
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    return base / safe / (safe + STOP_SUFFIX)


def _validate_run_id(value: Any) -> str:
    return _safe_component(value)


def _validate_reason(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_REASON_LENGTH or not _SAFE_REASON.fullmatch(value):
        raise StopError("reason_code must match [A-Za-z0-9][A-Za-z0-9_.:-]{0,95}")
    return value


def _validate_sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StopError("observed_sequence must be a non-negative integer")
    return value


def _validate_evidence_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_EVIDENCE_IDS:
        raise StopError(f"evidence_ids must be a list of at most {MAX_EVIDENCE_IDS} items")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item or len(item) > MAX_EVIDENCE_ID_LENGTH:
            raise StopError("evidence_ids must contain non-empty bounded strings")
        if item in seen:
            raise StopError("evidence_ids must not contain duplicates")
        seen.add(item)
        result.append(item)
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _intent_digest_body(value: Mapping[str, Any]) -> dict[str, Any]:
    """Fields immutable across pending/accepted/resolved lifecycle states."""
    return {key: value.get(key) for key in
            ("version", "run_id", "request_id", "reason_code", "evidence_ids",
             "observed_sequence", "created_at", "superseded") if key in value}


def _read(path: Path) -> dict[str, Any] | None:
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StopFileError(f"cannot read stop intent: {path}") from exc
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StopFileError(f"stop intent is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise StopFileError("stop intent must be a JSON object")
    if value.get("version") != STOP_VERSION or value.get("status") not in {"pending", "accepted", "resolved"}:
        raise StopFileError("unsupported stop intent version or status")
    _validate_run_id(value.get("run_id"))
    _validate_reason(value.get("reason_code"))
    _validate_sequence(value.get("observed_sequence"))
    _validate_evidence_ids(value.get("evidence_ids"))
    if not isinstance(value.get("request_id"), str) or not value["request_id"]:
        raise StopFileError("stop intent has no request_id")
    claimed = value.get("intent_sha256")
    if claimed is not None:
        if not isinstance(claimed, str) or claimed != _digest(_intent_digest_body(value)):
            raise StopFileError("stop intent integrity check failed")
    return value


def read_stop(run_id: str | os.PathLike[str], *, root: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """Read a stop intent, returning ``None`` when no intent exists."""
    return _read(_path_for_run(run_id, root))


def _write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The file itself is durable on platforms without directory fsync.
            pass
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _locked(path: Path):
    lock = path.with_name(path.name + STOP_LOCK_SUFFIX)
    lock.parent.mkdir(parents=True, exist_ok=True)
    stream = lock.open("a+")
    fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
    return stream


def stop_run(run_id: str | os.PathLike[str], reason_code: str,
             evidence_ids: list[str] | None, observed_sequence: int,
             *, root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Persist one stop intent atomically and return its durable envelope.

    Existing pending or resolved intents are returned unchanged.  This makes
    retries safe even when the original caller never received its response;
    a second reason or evidence list can never replace the first decision.
    """
    path = _path_for_run(run_id, root)
    run_path = Path(str(run_id))
    run_value = (_run_id_for_log(run_path) if run_path.suffix == ".ndjson"
                 else Path(str(run_id)).name)
    run_value = _validate_run_id(run_value)
    reason = _validate_reason(reason_code)
    sequence = _validate_sequence(observed_sequence)
    evidence = _validate_evidence_ids(evidence_ids)
    with _locked(path) as lock:
        existing = _read(path)
        superseded: dict[str, Any] | None = None
        if existing is not None:
            if existing.get("status") == "resolved" and str(existing.get("resolution", "")).startswith("stale"):
                # A stale recommendation is evidence that one incident was
                # rejected, not a permanent veto on a later incident. Retain
                # the old envelope in bounded history before allocating a new
                # request identity.
                superseded = {key: existing.get(key) for key in
                              ("request_id", "reason_code", "evidence_ids",
                               "observed_sequence", "created_at", "resolution",
                               "resolved_at") if key in existing}
                existing = None
            else:
                return existing
        intent = {
            "version": STOP_VERSION,
            "status": "pending",
            "run_id": run_value,
            "request_id": uuid.uuid4().hex,
            "reason_code": reason,
            "evidence_ids": evidence,
            "observed_sequence": sequence,
            "created_at": _utc_now(),
        }
        if superseded is not None:
            intent["superseded"] = superseded
        intent["intent_sha256"] = _digest(_intent_digest_body(intent))
        _write_atomic(path, intent)
        lock.flush()
        return intent


def resolve_stop(run_id: str | os.PathLike[str], outcome: str, *, details: Mapping[str, Any] | None = None,
                 root: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """Durably resolve an intent as cancelled, stale, or naturally ignored."""
    if not isinstance(outcome, str) or not outcome or not _SAFE_REASON.fullmatch(outcome):
        raise StopError("stop resolution must be a safe reason code")
    path = _path_for_run(run_id, root)
    with _locked(path) as lock:
        intent = _read(path)
        if intent is None:
            return None
        if intent.get("status") == "resolved":
            return intent
        result = dict(intent)
        result.update({"status": "resolved", "resolution": outcome, "resolved_at": _utc_now()})
        if details:
            if not isinstance(details, Mapping):
                raise StopError("stop resolution details must be an object")
            result["resolution_details"] = dict(details)
        result["resolution_sha256"] = _digest(result)
        _write_atomic(path, result)
        lock.flush()
        return result


def accept_stop(run_id: str | os.PathLike[str], *, details: Mapping[str, Any] | None = None,
                root: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """Mark a validated pending request as signal-authorized, idempotently."""
    path = _path_for_run(run_id, root)
    with _locked(path) as lock:
        intent = _read(path)
        if intent is None:
            return None
        if intent.get("status") == "resolved":
            return intent
        if intent.get("status") == "accepted":
            return intent
        result = dict(intent, status="accepted", accepted_at=_utc_now())
        if details:
            if not isinstance(details, Mapping):
                raise StopError("stop acceptance details must be an object")
            result["acceptance_details"] = dict(details)
        result["acceptance_sha256"] = _digest(result)
        _write_atomic(path, result)
        lock.flush()
        return result


def validate_stop_request(request: Mapping[str, Any], *, run_id: str | None = None,
                          active: bool = True, current_sequence: int | None = None,
                          terminal: Mapping[str, Any] | None = None,
                          evidence_validator: Callable[[str], bool] | None = None,
                          require_current_sequence: bool = False) -> tuple[bool, str]:
    """Validate freshness and ownership immediately before signalling.

    The evidence module may provide ``evidence_validator`` for indexed IDs.
    Sequence advancement alone does not make immutable evidence stale; callers
    can require an exact packet match when their policy needs that stricter
    fence.  A natural gameplay terminal always wins the race.
    """
    if not isinstance(request, Mapping):
        return False, "malformed_stop_request"
    try:
        requested_run = _validate_run_id(request.get("run_id"))
        _validate_reason(request.get("reason_code"))
        observed = _validate_sequence(request.get("observed_sequence"))
        evidence = _validate_evidence_ids(request.get("evidence_ids"))
    except StopError:
        return False, "malformed_stop_request"
    if run_id is not None and requested_run != _validate_run_id(run_id):
        return False, "foreign_run"
    if not active:
        return False, "run_inactive"
    if isinstance(terminal, Mapping) and terminal.get("terminal_class") == "gameplay":
        return False, "natural_completion_wins"
    if current_sequence is not None:
        if not isinstance(current_sequence, int) or current_sequence < observed:
            return False, "stale_observation"
        if require_current_sequence and current_sequence != observed:
            return False, "stale_observation"
    if evidence_validator is not None:
        try:
            if any(not evidence_validator(item) for item in evidence):
                return False, "stale_evidence"
        except Exception:
            return False, "evidence_unavailable"
    return True, "validated"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    request = sub.add_parser("request")
    request.add_argument("--run-id", required=True)
    request.add_argument("--reason-code", required=True)
    request.add_argument("--evidence-id", action="append", default=[])
    request.add_argument("--observed-sequence", required=True, type=int)
    request.add_argument("--root")
    read = sub.add_parser("read")
    read.add_argument("--run-id", required=True)
    read.add_argument("--root")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--run-id", required=True)
    resolve.add_argument("--outcome", required=True)
    resolve.add_argument("--root")
    args = parser.parse_args(argv)
    if args.command == "request":
        result = stop_run(args.run_id, args.reason_code, args.evidence_id,
                          args.observed_sequence, root=args.root)
    elif args.command == "read":
        result = read_stop(args.run_id, root=args.root)
    else:
        result = resolve_stop(args.run_id, args.outcome, root=args.root)
    print(json.dumps(result, sort_keys=True))
    return 0 if result is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
