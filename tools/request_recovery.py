"""Conservative reconciliation of a model request with client evidence.

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

try:
    from .request_journal import STATES, read_state
except ImportError:  # Direct script execution compatibility.
    from request_journal import STATES, read_state


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
    batch_id: str | None = None
    source_revision: int | None = None
    side_turns: int | None = None
    pending_opponent_turn: bool | None = None

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
    request_id = str(state["request_id"])
    batch_id = metadata.get("batch_id")
    source_revision = metadata.get("source_revision")
    candidates = [record for record in records if record.get("type") == "checkpoint_ref"
                  and (_related(record, request_id)
                       or (batch_id and record.get("batch_id") == batch_id)
                       or (expected_digest and record.get("digest") == expected_digest)
                       or (expected_path and record.get("path") == expected_path)
                       # A checkpoint notification may be lost after the
                       # driver publishes it.  The pre-submit revision and
                       # batch identity are then the only client evidence.
                       or (isinstance(source_revision, int)
                           and isinstance(record.get("state_revision"), int)
                           and record.get("state_revision") > source_revision
                           and record.get("pending_opponent_turn") is True))]
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
    # A linked checkpoint must expose the state needed to resume safely.  Old
    # checkpoints are still accepted when no linkage metadata was requested.
    for key in ("state_revision", "side_turns", "boundary", "pending_opponent_turn"):
        if key in record and key not in {"boundary", "pending_opponent_turn"}:
            if not isinstance(record[key], int):
                return False, path_name, actual, f"checkpoint {key} is invalid"
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


def _has_submitted(records: list[dict[str, Any]], request_id: str) -> bool:
    for record in records:
        if _related(record, request_id) and (
                record.get("type") in {"request_submitted", "batch_submitted"}
                or record.get("submitted") is True):
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
    consumed = _has_consumed(records, request_id) or journal.get("consumed") is True
    submitted = _has_submitted(records, request_id) or journal.get("submitted") is True
    committed = _has_commit(records, request_id) or journal.get("committed") is True
    checkpoint_ok, checkpoint_path, checkpoint_digest, checkpoint_reason = _checkpoint_evidence(
        records, journal, checkpoint_dir)
    if committed:
        if not checkpoint_ok:
            return Reconciliation(UNKNOWN, request_id, checkpoint_reason, False,
                                  journal.get("answer_path"), checkpoint_path, checkpoint_digest)
        # A committed batch is safe to continue from its checkpoint; the
        # supervisor must resume the following boundary without replaying it.
        return Reconciliation(COMMITTED, request_id, "accepted batch and checkpoint verified", True,
                              journal.get("answer_path"), checkpoint_path, checkpoint_digest,
                              metadata.get("batch_id"), metadata.get("source_revision"),
                              metadata.get("side_turns"), metadata.get("pending_opponent_turn"))
    if consumed:
        if submitted:
            return Reconciliation(UNKNOWN, request_id,
                                  "answer was consumed and submitted without a verified commit", False,
                                  journal.get("answer_path"), checkpoint_path, checkpoint_digest,
                                  metadata.get("batch_id"), metadata.get("source_revision"),
                                  metadata.get("side_turns"), metadata.get("pending_opponent_turn"))
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
    from .request_journal import _safe_session_name

    requests = Path(journal_root) / _safe_session_name(session_id) / "requests"
    if not requests.is_dir():
        return Reconciliation(UNKNOWN, None, "no request journal exists", False)
    candidates = []
    for directory in requests.iterdir():
        if directory.is_dir() and (directory / "state.json").is_file():
            candidates.append(directory)
    if not candidates:
        return Reconciliation(UNKNOWN, None, "no request exists", False)
    # Creation sequence is stable across copied filesystems; mtime is not.
    def order(path: Path) -> tuple[int, float, str]:
        try:
            state = read_state(path)
            sequence = int(state.get("sequence", 0))
            created = float(state.get("created_at", 0))
        except (OSError, ValueError, TypeError):
            sequence, created = -1, -1
        return sequence, created, path.name
    candidates.sort(key=order)
    active = [path for path in candidates
              if read_state(path).get("state") in ACTIVE_STATES]
    if len(active) > 1:
        return Reconciliation(UNKNOWN, None, "multiple active requests exist", False)
    latest = candidates[-1]
    return reconcile_request(latest / "state.json", client_records, checkpoint_dir,
                             request_dir=latest)


def recoverable_answer(journal_root: str | Path, session_id: str,
                       prompt_hash: str, client_records: Iterable[Mapping[str, Any]] = ()) -> tuple[dict[str, Any], Path] | None:
    """Return a matching completed answer that the client has not consumed.

    Prompt identity is checked before reuse.  The journal state and answer file
    are both required; an active, consumed, committed, or mismatched request is
    never replayed.
    """
    from .request_journal import _safe_session_name, read_state
    requests = Path(journal_root) / _safe_session_name(session_id) / "requests"
    if not requests.is_dir():
        return None
    candidates: list[tuple[float, Path, dict[str, Any]]] = []
    for directory in requests.iterdir():
        if not directory.is_dir() or not (directory / "state.json").is_file():
            continue
        try:
            state = read_state(directory)
            metadata = state.get("metadata", {})
            if state.get("state") != "completed" or not isinstance(metadata, dict):
                continue
            if metadata.get("prompt_sha256") != prompt_hash:
                continue
            answer_path = directory / str(state.get("answer_path", ""))
            if not answer_path.is_file():
                continue
            related = _read_records(client_records)
            if (_has_consumed(related, str(state.get("request_id")))
                    or state.get("consumed") is True
                    or state.get("committed") is True):
                continue
            candidates.append((float(state.get("created_at", 0)), directory, state))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    if not candidates:
        return None
    _, directory, state = max(candidates, key=lambda item: (item[0], item[1].name))
    answer = json.loads((directory / str(state["answer_path"])).read_text(encoding="utf-8"))
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        return None
    return answer, directory / "state.json"


def restart_decision(result: Reconciliation) -> tuple[bool, str]:
    """Return the supervisor's conservative restart decision."""
    if result.state == INTERRUPTED:
        return True, "proven interrupted request"
    if result.state == COMPLETED_UNCONSUMED:
        return True, "safe completed answer can be replayed"
    return False, f"stop: {result.state}: {result.reason}"
