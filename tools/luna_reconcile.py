"""Conservative reconciliation of a Luna request with client evidence.

This module is deliberately read-only.  It does not repair a journal, replay an
answer, or submit a driver request.  It answers the narrower question needed by
the supervisor: what durable outcome can be proved from the request journal,
the client log, and the linked checkpoint?
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .luna_request_journal import STATES, read_state


COMPLETED_UNCONSUMED = "completed_unconsumed"
CONSUMED_UNCOMMITTED = "consumed_uncommitted"
COMMITTED = "committed"
INTERRUPTED = "interrupted"
UNKNOWN = "unknown"

ACTIVE_STATES = frozenset({"prepared", "dispatched"})
RESTARTABLE = frozenset({INTERRUPTED, COMPLETED_UNCONSUMED})


@dataclass(frozen=True)
class Reconciliation:
    """The strongest state proved by the available durable evidence."""

    state: str
    request_id: str | None
    reason: str
    safe_to_restart: bool
    answer_path: str | None = None
    checkpoint_path: str | None = None
    checkpoint_digest: str | None = None

    @property
    def stop(self) -> bool:
        return not self.safe_to_restart


class ReconciliationError(ValueError):
    """Input evidence is malformed or contradictory."""


def _dicts(values: Iterable[Any]) -> list[dict[str, Any]]:
    return [value for value in values if isinstance(value, dict)]


def _request_id(value: Mapping[str, Any]) -> str | None:
    for key in ("request_id", "llm_request_id", "request", "requestId"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
        if isinstance(candidate, dict):
            nested = _request_id(candidate)
            if nested:
                return nested
    return None


def _related(record: Mapping[str, Any], request_id: str) -> bool:
    return _request_id(record) == request_id


def _read_records(records: Iterable[Mapping[str, Any]] | str | Path) -> list[dict[str, Any]]:
    if isinstance(records, (str, Path)):
        path = Path(records)
        if not path.exists():
            return []
        result: list[dict[str, Any]] = []
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                if index == len(lines) - 1:
                    continue
                raise ReconciliationError(f"invalid client log record at line {index + 1}") from exc
            if isinstance(value, dict):
                result.append(value)
        return result
    return _dicts(records)


def _answer_exists(request_dir: Path, state: Mapping[str, Any]) -> bool:
    answer_name = state.get("answer_path")
    if not isinstance(answer_name, str) or not answer_name:
        return False
    answer = (request_dir / answer_name).resolve()
    try:
        answer.relative_to(request_dir.resolve())
    except ValueError:
        return False
    return answer.is_file()


def _checkpoint_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkpoint_evidence(
    records: list[dict[str, Any]],
    state: Mapping[str, Any],
    checkpoint_dir: str | Path | None,
) -> tuple[bool, str | None, str | None, str]:
    """Return (valid, path, digest, reason) for a request-linked checkpoint."""
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    expected_digest = next(
        (metadata.get(key) for key in ("checkpoint_digest", "commit_checkpoint_digest")
         if isinstance(metadata.get(key), str)), None)
    expected_path = next(
        (metadata.get(key) for key in ("checkpoint_path", "commit_checkpoint_path")
         if isinstance(metadata.get(key), str)), None)
    candidates = [record for record in records if record.get("type") == "checkpoint_ref"
                  and (_related(record, str(state["request_id"]))
                       or (expected_digest and record.get("digest") == expected_digest)
                       or (expected_path and record.get("path") == expected_path))]
    if expected_digest is None and expected_path is None and not candidates:
        return False, None, None, "no checkpoint linked to request"
    if not candidates:
        return False, expected_path, expected_digest, "linked checkpoint record is missing"
    record = candidates[-1]
    path_name = record.get("path") or expected_path
    digest = record.get("digest") or expected_digest
    if not isinstance(path_name, str) or not isinstance(digest, str):
        return False, None, None, "checkpoint link is incomplete"
    if checkpoint_dir is None:
        return False, path_name, digest, "checkpoint cannot be verified without its directory"
    path = (Path(checkpoint_dir) / path_name).resolve()
    try:
        path.relative_to(Path(checkpoint_dir).resolve())
        actual = _checkpoint_digest(path)
    except (OSError, ValueError):
        return False, path_name, digest, "checkpoint is unavailable"
    if actual.lower() != digest.lower():
        return False, path_name, digest, "checkpoint digest mismatch"
    if expected_digest and actual.lower() != expected_digest.lower():
        return False, path_name, digest, "request checkpoint digest mismatch"
    return True, path_name, actual, "checkpoint verified"


def _has_consumed(records: list[dict[str, Any]], request_id: str) -> bool:
    consumed_types = {"request_consumed", "reply_consumed", "model_consumed", "answer_consumed"}
    for record in records:
        if not _related(record, request_id):
            continue
        if record.get("type") in consumed_types or record.get("consumed") is True:
            return True
    return False


def _has_commit(records: list[dict[str, Any]], request_id: str) -> bool:
    commit_types = {"request_committed", "batch_committed", "action_batch_committed",
                    "accepted_batch", "commit", "checkpoint_commit"}
    for record in records:
        if not _related(record, request_id):
            continue
        if record.get("type") in commit_types or record.get("committed") is True:
            return True
    return False


def reconcile_request(
    state: Mapping[str, Any] | str | Path,
    client_records: Iterable[Mapping[str, Any]] | str | Path = (),
    checkpoint_dir: str | Path | None = None,
    request_dir: str | Path | None = None,
) -> Reconciliation:
    """Reconcile one journal state using only explicit durable evidence.

    A completed answer is restartable only when its answer file exists and no
    consumption or commit has been recorded.  An interrupted request is safe
    only when the journal says cleanup was verified.  Active, failed, unknown,
    and contradictory requests always stop.
    """
    if isinstance(state, (str, Path)):
        state_path = Path(state)
        # The journal reader accepts a request directory; callers commonly
        # have the durable state.json path instead.
        journal = read_state(state_path if state_path.is_dir() else state_path.parent)
        request_dir = request_dir or state_path.parent
    else:
        journal = dict(state)
    request_id = journal.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return Reconciliation(UNKNOWN, None, "request identity is missing", False)
    journal_state = journal.get("state")
    if journal_state not in STATES:
        return Reconciliation(UNKNOWN, request_id, "journal state is invalid", False)
    records = _read_records(client_records)
    metadata = journal.get("metadata") if isinstance(journal.get("metadata"), dict) else {}
    if journal_state in ACTIVE_STATES:
        return Reconciliation(UNKNOWN, request_id, "request is active", False)
    if journal_state == "unknown":
        return Reconciliation(UNKNOWN, request_id, "journal marked request unknown", False)
    if journal_state == "failed":
        return Reconciliation(UNKNOWN, request_id, "failed request has no safe replay rule", False)
    if journal_state == "interrupted":
        cleanup = journal.get("cleanup_verified", metadata.get("cleanup_verified"))
        if cleanup is True and not journal.get("answer_path"):
            return Reconciliation(INTERRUPTED, request_id, "cleanup verified before answer", True)
        return Reconciliation(UNKNOWN, request_id, "interrupted request is not proven clean", False)

    if request_dir is None:
        return Reconciliation(UNKNOWN, request_id, "completed request directory is unknown", False)
    if not _answer_exists(Path(request_dir), journal):
        return Reconciliation(UNKNOWN, request_id, "completed answer is missing", False)
    consumed = _has_consumed(records, request_id)
    committed = _has_commit(records, request_id)
    checkpoint_ok, checkpoint_path, checkpoint_digest, checkpoint_reason = _checkpoint_evidence(
        records, journal, checkpoint_dir)
    if committed:
        if not checkpoint_ok:
            return Reconciliation(UNKNOWN, request_id, checkpoint_reason, False,
                                  journal.get("answer_path"), checkpoint_path, checkpoint_digest)
        return Reconciliation(COMMITTED, request_id, "accepted batch and checkpoint verified", False,
                              journal.get("answer_path"), checkpoint_path, checkpoint_digest)
    if consumed:
        return Reconciliation(CONSUMED_UNCOMMITTED, request_id,
                              "answer consumed without a committed batch", False,
                              journal.get("answer_path"), checkpoint_path, checkpoint_digest)
    if metadata.get("checkpoint_digest") or metadata.get("checkpoint_path"):
        return Reconciliation(UNKNOWN, request_id, checkpoint_reason, False,
                              journal.get("answer_path"), checkpoint_path, checkpoint_digest)
    return Reconciliation(COMPLETED_UNCONSUMED, request_id, "answer persisted and unconsumed", True,
                          journal.get("answer_path"))


def reconcile_journal(
    journal_root: str | Path,
    session_id: str,
    client_records: Iterable[Mapping[str, Any]] | str | Path = (),
    checkpoint_dir: str | Path | None = None,
) -> Reconciliation:
    """Reconcile the newest request for a session; no request means unknown."""
    from .luna_request_journal import _safe_session_name

    requests = Path(journal_root) / _safe_session_name(session_id) / "requests"
    if not requests.is_dir():
        return Reconciliation(UNKNOWN, None, "no request journal exists", False)
    candidates = []
    for directory in requests.iterdir():
        if directory.is_dir() and (directory / "state.json").is_file():
            candidates.append(directory)
    if not candidates:
        return Reconciliation(UNKNOWN, None, "no request exists", False)
    latest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    return reconcile_request(latest / "state.json", client_records, checkpoint_dir)


def restart_decision(result: Reconciliation) -> tuple[bool, str]:
    """Return the supervisor's conservative restart decision."""
    if result.state == INTERRUPTED:
        return True, "proven interrupted request"
    if result.state == COMPLETED_UNCONSUMED:
        return True, "safe completed answer can be replayed"
    return False, f"stop: {result.state}: {result.reason}"
