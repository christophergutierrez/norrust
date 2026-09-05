"""Small durable journal for one in-flight Luna request per session.

The journal deliberately knows nothing about the model transport.  Callers mark
transport milestones and append native events as they receive them.  The open
request handle owns the session lock until it is closed.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import fcntl


STATES = frozenset({"prepared", "dispatched", "completed", "interrupted", "failed", "unknown"})
TERMINAL_STATES = frozenset({"completed", "interrupted", "failed", "unknown"})
_NEXT_STATES = {
    "prepared": frozenset({"dispatched", "failed", "interrupted", "unknown"}),
    "dispatched": TERMINAL_STATES,
    "completed": frozenset(),
    "interrupted": frozenset(),
    "failed": frozenset(),
    "unknown": frozenset(),
}


class RequestConflict(RuntimeError):
    """Another process currently owns this session's request lock."""


class RequestStateError(RuntimeError):
    """A request transition or journal operation is invalid."""


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _now() -> float:
    return time.time()


def _safe_session_name(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
    return f"session-{digest}"


class RequestJournal:
    """Journal requests under ``root`` while locking one logical session."""

    def __init__(self, root: str | os.PathLike[str], session_id: str) -> None:
        if not session_id:
            raise ValueError("session_id must not be empty")
        self.root = Path(root)
        self.session_id = session_id
        self.session_dir = self.root / _safe_session_name(session_id)
        self.requests_dir = self.session_dir / "requests"
        self.lock_path = self.session_dir / "session.lock"
        self._lock_fd: int | None = None

    def __enter__(self) -> "RequestJournal":
        self.acquire()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.release()

    def acquire(self) -> None:
        if self._lock_fd is not None:
            return
        self.session_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd)
            raise RequestConflict(f"request already active for session {self.session_id}") from exc
        self._lock_fd = fd

    def release(self) -> None:
        if self._lock_fd is None:
            return
        fd, self._lock_fd = self._lock_fd, None
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def prepare(self, metadata: Mapping[str, Any] | None = None) -> "RequestHandle":
        if self._lock_fd is None:
            raise RequestStateError("acquire the session journal before preparing a request")
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(8):
            request_id = secrets.token_hex(16)
            request_dir = self.requests_dir / request_id
            try:
                request_dir.mkdir()
                break
            except FileExistsError:
                continue
        else:
            raise RequestStateError("could not allocate a unique request directory")
        record: dict[str, Any] = {
            "request_id": request_id,
            "session_id": self.session_id,
            "state": "prepared",
            "sequence": 0,
            "created_at": _now(),
            "updated_at": _now(),
            "metadata": dict(metadata or {}),
        }
        handle = RequestHandle(self, request_id, request_dir, record)
        handle._write_state()
        handle._append({"kind": "state", "state": "prepared"})
        return handle


class RequestHandle:
    """A request's durable files and validated lifecycle operations."""

    def __init__(self, journal: RequestJournal, request_id: str, request_dir: Path,
                 record: dict[str, Any]) -> None:
        self.journal = journal
        self.request_id = request_id
        self.directory = request_dir
        self.state_path = request_dir / "state.json"
        self.events_path = request_dir / "events.ndjson"
        self.record = record
        self._closed = False

    @property
    def state(self) -> str:
        return str(self.record["state"])

    def _ensure_open(self) -> None:
        if self._closed or self.journal._lock_fd is None:
            raise RequestStateError("request handle is closed")

    def _write_state(self) -> None:
        self.record["updated_at"] = _now()
        _atomic_json(self.state_path, self.record)

    def _append(self, event: Mapping[str, Any]) -> None:
        payload = {
            "request_id": self.request_id,
            "sequence": int(self.record["sequence"]),
            "at": _now(),
            **dict(event),
        }
        with self.events_path.open("ab") as stream:
            stream.write(_json_bytes(payload))
            stream.flush()
            os.fsync(stream.fileno())

    def append_event(self, event: Mapping[str, Any]) -> None:
        """Append one received transport/native event without changing state."""
        self._ensure_open()
        self._append({"kind": "native_event", "event": dict(event)})

    def transition(self, state: str, **details: Any) -> None:
        self._ensure_open()
        if state not in STATES:
            raise RequestStateError(f"unknown request state: {state}")
        if state not in _NEXT_STATES[self.state]:
            raise RequestStateError(f"cannot transition {self.state} -> {state}")
        self.record["state"] = state
        self.record["sequence"] = int(self.record["sequence"]) + 1
        self.record.update(details)
        self._write_state()
        self._append({"kind": "state", "state": state, "details": details})

    def mark_dispatched(self, **details: Any) -> None:
        self.transition("dispatched", **details)

    def complete(self, answer: str | Mapping[str, Any], **details: Any) -> None:
        self._ensure_open()
        answer_path = self.directory / "answer.json"
        _atomic_json(answer_path, answer)
        self.transition("completed", answer_path=answer_path.name, **details)

    def interrupt(self, **details: Any) -> None:
        self.transition("interrupted", **details)

    def fail(self, **details: Any) -> None:
        self.transition("failed", **details)

    def mark_unknown(self, **details: Any) -> None:
        self.transition("unknown", **details)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.journal.release()

    def __enter__(self) -> "RequestHandle":
        self._ensure_open()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()


def read_state(request_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Read a durable state snapshot for inspection or recovery code."""
    path = Path(request_dir) / "state.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RequestStateError(f"invalid request state: {path}") from exc
    if not isinstance(value, dict) or value.get("state") not in STATES:
        raise RequestStateError(f"invalid request state: {path}")
    return value
