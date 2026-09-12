"""Turn Codex host-session evidence into detailed model-call usage records.

A player subagent can dispatch several physical inference calls (an
inspection, a publication attempt, a retry) under one native Codex host
thread while the harness only sees one request/reply exchange. This module
reads *explicit*, match-owned evidence naming exactly which host thread and
which evidence file belong to which game, and turns the host's
``token_usage_record`` entries into ``tools.model_usage.ModelCall`` rows —
the frozen ``model_calls`` contract in ``tmp/plan_token_usage.md`` (see
"Accounting contract"), owned by ``tools/model_usage.py``.

Real Codex rollout record shape (verified against a live rollout; only key
paths and integer types were inspected, never prompt/message/reasoning
content, and none of that content belongs in a fixture here):

    {"type": "token_usage_record", "ordinal": <int>, "timestamp": "<str>",
     "payload": {"response_id": ..., "session_id": ..., "thread_id": ...,
                 "turn_id": ..., "root_turn_id": ...,
                 "usage": {...six int fields...},
                 "turn_token_usage": {...same six fields, cumulative per turn...},
                 "thread_token_usage": {...same six fields, cumulative per thread...}}}

Only ``payload.usage`` is per-response evidence; ``turn_token_usage`` and
``thread_token_usage`` are running totals that happen to overlap with it
whenever a turn/thread has produced exactly one response so far. The six
source integer keys are ``input_tokens``, ``cached_input_tokens``,
``cache_write_input_tokens``, ``output_tokens``, ``reasoning_output_tokens``,
``total_tokens`` — note ``reasoning_output_tokens``, which
``tools.model_usage.CODEX_USAGE_MAP`` maps onto the contract's
``reasoning_tokens`` field.

The cumulative ``token_count`` view is not a top-level record type; it is
nested as ``{"type": "event_msg", "payload": {"type": "token_count", ...}}``.
Thread completion is marked by ``{"type": "event_msg", "payload":
{"type": "task_complete"}}`` (paired with an earlier ``task_started``).
Several other top-level types exist in real rollouts (``response_item``,
``world_state``, ``turn_context``, ``session_meta``, ``compacted``,
``inter_agent_communication_metadata``) and other ``event_msg`` payload
types (``item_completed``, ``thread_settings_applied``); none of them carry
usage in the shape this stack consumes, so they are skipped rather than
treated as errors or as evidence of anything.

Hard rules, matched to the frozen contract:

- Never scan a user's home directory or any session index for evidence. The
  caller (a launcher that actually bound the host thread to the game) must
  supply the exact evidence path and thread ID. See ``load_manifest``.
- Never ask a model to report its own identity or token usage; only recorded
  host events are read.
- Cumulative ``token_count``/``turn_token_usage``/``thread_token_usage``
  snapshots and per-response ``usage`` overlap. Only ``payload.usage`` from a
  ``token_usage_record`` becomes a call row; cumulative evidence is exposed
  separately, for reconciliation only, and is never summed with per-response
  usage or used to fabricate call rows.
- Repeated records for one response upsert that call (via
  ``model_usage.dedupe_calls``/``merge_lifecycle``); they are never counted
  twice. Conflicting usage for one response is recorded in
  ``normalization_gaps`` as ``"conflict:<field>:<old>!=<new>"``, not resolved
  by last-writer-wins.
- A ``token_usage_record`` whose payload has no ``usage`` block at all is an
  unsupported shape, reported as such, never silently turned into zeros.
- Linking a call to a harness request requires durable, proven evidence —
  see ``link_calls_via_handshake``. Everything else stays an unlinked call
  (``request_id`` is ``None``), which still counts toward game usage per the
  frozen contract. Timestamp proximity, nth-call pairing, and polling-time
  guesses are never acceptable links.

Entry point: ``collect_host_usage(manifest, request_links=None) -> list[dict]``.
"""
from __future__ import annotations

import json
import sys
import os
import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from . import model_usage

PROVIDER = "codex_native"
TRANSPORT = "codex_host_session"

class ManifestError(ValueError):
    """The binding manifest is missing, incomplete, or points at nothing real."""

@dataclass(frozen=True)
class HostUsageManifest:
    """Explicit, match-owned binding naming exactly one host thread/game.

    Every field must be supplied by whatever bound the host thread to this
    game (the launcher, or an explicit historical-collection caller). Nothing
    here is inferred, defaulted from an environment convention, or resolved
    by searching a directory of sessions.
    """

    game_id: str
    host_thread_id: str
    host_evidence_path: Path
    game_log_path: Path
    request_handshake_dir: Path

_REQUIRED_KEYS = ("game_id", "host_thread_id", "host_evidence_path",
                   "game_log_path", "request_handshake_dir")

def load_manifest(source: Mapping[str, Any] | str | Path) -> HostUsageManifest:
    """Load and validate an explicit binding manifest.

    ``source`` is either an already-parsed mapping or a path to a JSON file
    holding one. Every required key must be present and non-empty; the
    evidence and game-log paths must exist as files, and the handshake
    directory must exist as a directory. This function never globs, never
    walks a home directory, and never picks "the most recent" anything: a
    missing or ambiguous binding is a hard error, not a fallback.
    """
    if isinstance(source, (str, Path)):
        path = Path(source)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ManifestError(f"manifest {path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise ManifestError(f"manifest {path} must contain a JSON object")
        data = raw
    else:
        data = source
    missing = [key for key in _REQUIRED_KEYS if not data.get(key)]
    if missing:
        raise ManifestError(f"manifest is missing required field(s): {', '.join(missing)}")
    game_id = str(data["game_id"])
    host_thread_id = str(data["host_thread_id"])
    evidence_path = Path(str(data["host_evidence_path"]))
    game_log_path = Path(str(data["game_log_path"]))
    handshake_dir = Path(str(data["request_handshake_dir"]))
    if not evidence_path.is_file():
        raise ManifestError(f"host_evidence_path does not exist or is not a file: {evidence_path}")
    if not game_log_path.is_file():
        raise ManifestError(f"game_log_path does not exist or is not a file: {game_log_path}")
    if not handshake_dir.is_dir():
        raise ManifestError(f"request_handshake_dir does not exist or is not a directory: {handshake_dir}")
    return HostUsageManifest(game_id=game_id, host_thread_id=host_thread_id,
                              host_evidence_path=evidence_path, game_log_path=game_log_path,
                              request_handshake_dir=handshake_dir)

def _derive_call_id(thread_id: str, response_id: str | None, position: int) -> str:
    """A stable, source-derived call ID, scoped to the game via its thread.

    Preferring the response ID keeps the ID stable across restarts and across
    delayed/duplicate records for the same response. Records with no response
    ID fall back to their source position, which is equally stable because
    the same evidence file is re-read in the same order on every collection.
    """
    if response_id:
        return f"{thread_id}:{response_id}"
    return f"{thread_id}:pos{position}"

def _read_records(path: Path) -> tuple[list[tuple[int, dict[str, Any]]], list[dict[str, Any]]]:
    """Read one JSONL evidence file, tolerating a truncated final line.

    Returns ``(records, diagnostics)``. ``records`` pairs each parsed object
    with its zero-based line position, used for stable IDs and for reporting
    source positions as evidence. A line that fails to parse is never
    silently dropped: it becomes a diagnostic, and parsing continues so one
    corrupt record cannot hide the rest of the file.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[tuple[int, dict[str, Any]]] = []
    diagnostics: list[dict[str, Any]] = []
    last_index = len(lines) - 1
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            kind = "incomplete_trailing_record" if index == last_index else "malformed_record"
            diagnostics.append({"kind": kind, "position": index, "error": str(exc),
                                 "source_path": str(path), "raw": line})
            continue
        if not isinstance(value, dict):
            diagnostics.append({"kind": "malformed_record", "position": index,
                                 "error": "record is not a JSON object",
                                 "source_path": str(path), "raw": line})
            continue
        records.append((index, value))
    return records, diagnostics

def _record_thread_id(record: dict[str, Any]) -> str | None:
    payload = record.get("payload")
    if isinstance(payload, dict):
        thread_id = payload.get("thread_id")
        if thread_id is not None:
            return str(thread_id)
    return None

def _belongs_to_thread(record: dict[str, Any], thread_id: str) -> bool:
    """A record naming no thread is assumed local to this one bound file;
    a record naming a *different* thread never is. This is what keeps two
    interleaved host threads recorded in the same evidence file from
    cross-attributing calls when each is collected through its own manifest.
    """
    record_thread = _record_thread_id(record)
    if record_thread is None:
        return True
    return record_thread == thread_id

def _build_call_from_record(game_id: str, thread_id: str, call_id: str, record: dict[str, Any],
                             position: int, source_path: Path) -> model_usage.ModelCall:
    """Build one ``ModelCall`` from a single ``token_usage_record`` line.

    Repeats for the same response are folded together later by
    ``model_usage.dedupe_calls``; this function only ever describes what one
    physical line said.
    """
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    provider_response_id = payload.get("response_id")
    timestamp = record.get("timestamp")
    ended_at = timestamp if isinstance(timestamp, str) else None
    source_ref = f"{source_path}:{position}(ordinal={record.get('ordinal')})"
    usage = payload.get("usage")

    if not isinstance(usage, dict):
        # No usage block at all: an unsupported/incomplete shape, not zeros.
        return model_usage.ModelCall(
            game_id=game_id, call_id=call_id, call_role="player", provider=PROVIDER, transport=TRANSPORT,
            native_thread_id=thread_id, provider_response_id=provider_response_id,
            status="unknown", usage_source="unsupported_payload_shape",
            raw_usage_json=record, source_ref=source_ref, ended_at=ended_at,
        )

    normalized, gaps = model_usage.normalize_usage(usage, model_usage.CODEX_USAGE_MAP)
    call = model_usage.ModelCall(
        game_id=game_id, call_id=call_id, call_role="player", provider=PROVIDER, transport=TRANSPORT,
        native_thread_id=thread_id, provider_response_id=provider_response_id,
        status="completed", usage_source="token_usage_record",
        raw_usage_json=record, source_ref=source_ref, ended_at=ended_at,
        normalization_gaps=gaps,
    )
    for field, value in normalized.items():
        setattr(call, field, value)
    return call

def collect_host_usage(manifest: HostUsageManifest,
                        request_links: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Return one ``model_calls``-shaped dict per host response bound by ``manifest``.

    ``request_links`` is an optional, already-proven mapping from this
    function's ``call_id`` to a harness ``request_id`` (see
    ``link_calls_via_handshake``). Without it every call comes back unlinked
    (``request_id`` is ``None``) and still counts toward game usage per the
    frozen contract.

    Calling this twice against the same manifest and evidence file returns
    identical rows: nothing here depends on wall-clock time, set iteration
    order, or any state outside the evidence file itself. Use
    ``collect_host_usage_report`` for the same rows alongside parse
    diagnostics and cumulative reconciliation evidence.
    """
    return collect_host_usage_report(manifest, request_links)["calls"]

def collect_host_usage_report(manifest: HostUsageManifest,
                               request_links: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Like ``collect_host_usage``, plus parse diagnostics and cumulative evidence.

    Returns ``{"calls": [...], "diagnostics": [...], "cumulative_snapshots": [...],
    "thread_finalized": bool, "conflicts": {...}}``. ``diagnostics`` covers
    malformed and incomplete-trailing evidence lines. ``cumulative_snapshots``
    is the raw ``token_count`` event evidence (nested under ``event_msg``),
    present only for reconciliation (see ``reconciliation_totals``) and never
    merged into ``calls``. ``thread_finalized`` reflects whether a
    ``task_complete`` event for this thread was observed; its absence means
    collection ran against a still-open host thread, not that nothing
    happened. ``conflicts`` is ``model_usage.dedupe_calls``'s own conflict
    report, keyed by ``(game_id, call_id)``.
    """
    records, diagnostics = _read_records(manifest.host_evidence_path)
    raw_calls: list[model_usage.ModelCall] = []
    cumulative_snapshots: list[dict[str, Any]] = []
    thread_finalized = False

    for position, record in records:
        if not _belongs_to_thread(record, manifest.host_thread_id):
            continue
        record_type = record.get("type")

        if record_type == "token_usage_record":
            payload = record.get("payload")
            response_id = payload.get("response_id") if isinstance(payload, dict) else None
            call_id = _derive_call_id(manifest.host_thread_id, response_id, position)
            raw_calls.append(_build_call_from_record(
                manifest.game_id, manifest.host_thread_id, call_id, record, position,
                manifest.host_evidence_path))
            continue

        if record_type == "event_msg":
            event_payload = record.get("payload")
            event_type = event_payload.get("type") if isinstance(event_payload, dict) else None
            if event_type == "token_count":
                # Cumulative snapshot: reconciliation evidence only. Never
                # turned into a call row, never summed with per-response usage.
                cumulative_snapshots.append({"position": position, "record": record})
            elif event_type == "task_complete":
                thread_finalized = True
            # task_started, item_completed, thread_settings_applied, and any
            # other event_msg payload type carry no usage this stack consumes.
            continue

        # response_item, world_state, turn_context, session_meta, compacted,
        # inter_agent_communication_metadata, and any other unrecognized
        # top-level type are structural context only for this stack; skip
        # them rather than treat an unfamiliar type as an error.
        continue

    deduped, conflicts = model_usage.dedupe_calls(raw_calls)
    rows = [call.to_row() for call in deduped]
    for row in rows:
        if request_links and row["call_id"] in request_links:
            row["request_id"] = request_links[row["call_id"]]
            row["linkage_evidence"] = "supplied_request_link"

    return {
        "calls": rows,
        "diagnostics": diagnostics,
        "cumulative_snapshots": cumulative_snapshots,
        "thread_finalized": thread_finalized,
        "conflicts": conflicts,
    }

def is_thread_finalized(manifest: HostUsageManifest) -> bool:
    """Whether a ``task_complete`` event_msg was observed for this thread.

    Its absence means the bound host thread is still open (or the evidence
    file was captured before completion), not that the thread failed.
    """
    return collect_host_usage_report(manifest)["thread_finalized"]

def reconciliation_totals(manifest: HostUsageManifest) -> dict[str, Any]:
    """Return cumulative ``token_count`` totals for reconciliation only.

    These numbers may be used to sanity-check the sum of measured calls; the
    frozen contract forbids treating them as, or adding them to, call rows.
    The last recorded snapshot (by source position) is authoritative for a
    cumulative counter; earlier ones are retained as evidence.
    """
    report = collect_host_usage_report(manifest)
    snapshots = report["cumulative_snapshots"]
    if not snapshots:
        return {"available": False, "snapshots": []}
    last = snapshots[-1]
    last_payload = last["record"].get("payload")
    latest_info = last_payload.get("info") if isinstance(last_payload, dict) else None
    return {
        "available": True,
        "latest_position": last["position"],
        "latest_info": latest_info,
        "snapshot_count": len(snapshots),
        "snapshots": snapshots,
    }

def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None

def load_handshake_log(handshake_dir: Path) -> list[dict[str, Any]]:
    """Read ``handshake_log.ndjson`` from a file-backend request directory.

    One JSON object per served request, written by ``tools/file_backend.py``
    only after a reply was actually published. Missing or unreadable lines
    are simply skipped: an incomplete handshake log yields fewer provable
    links, never a crash and never a guessed one.
    """
    path = Path(handshake_dir) / "handshake_log.ndjson"
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records

def link_calls_via_handshake(manifest: HostUsageManifest,
                              calls: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """Derive proven ``call_id -> harness_request_id`` links from the handshake log.

    The file-backend transport blocks on one reply at a time, so at most one
    harness request is open between its recorded ``published_at`` and
    ``answered_at``. A call whose own evidence timestamp (``ended_at``, taken
    from the host record itself) falls inside exactly one such window is
    proven to belong to that request by durable, ordered evidence — not by
    timestamp proximity or by pairing the Nth call to the Nth request. A call
    with no timestamp, or one whose timestamp falls in zero or more than one
    window, is left out: it stays unlinked in ``collect_host_usage``.
    """
    if calls is None:
        calls = collect_host_usage(manifest)
    windows: list[tuple[datetime, datetime, str]] = []
    for record in load_handshake_log(manifest.request_handshake_dir):
        harness_request_id = record.get("harness_request_id")
        published = _parse_iso(record.get("published_at"))
        answered = _parse_iso(record.get("answered_at"))
        if not harness_request_id or published is None or answered is None:
            continue
        windows.append((published, answered, str(harness_request_id)))

    links: dict[str, str] = {}
    for call in calls:
        timestamp = _parse_iso(call.get("ended_at"))
        if timestamp is None:
            continue
        matches = {request_id for published, answered, request_id in windows
                   if published <= timestamp <= answered}
        if len(matches) == 1:
            links[call["call_id"]] = next(iter(matches))
    return links


def write_usage_sidecar(manifest: HostUsageManifest, destination: str | os.PathLike[str],
                        *, link: bool = True) -> dict[str, Any]:
    """Write collected host calls in the usage-sidecar format the importer reads.

    Collection deliberately produces the same record shape a live adapter writes,
    so host-collected usage travels through `tools.game_history`'s existing
    importer instead of a second, separately-drifting import path. Calls are
    written with their proven harness links when the handshake log supplies
    them; an unproven call is written unlinked rather than guessed, and still
    counts toward the game total.
    """
    calls = collect_host_usage(manifest)
    links = link_calls_via_handshake(manifest, calls) if link else {}
    for call in calls:
        if call.get("request_id") is None and call["call_id"] in links:
            call["request_id"] = links[call["call_id"]]
            call["linkage_evidence"] = "handshake_window"
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for call in calls:
            stream.write(json.dumps(dict(call, record_kind="final"), sort_keys=True) + "\n")
    return {"calls": len(calls), "linked": sum(1 for c in calls if c.get("request_id")),
            "unlinked": sum(1 for c in calls if not c.get("request_id")),
            "finalized": is_thread_finalized(manifest), "sidecar": str(path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True,
                        help="explicit match-owned binding manifest; no host session is ever scanned")
    parser.add_argument("--write-sidecar", required=True,
                        help="destination usage sidecar, normally usage.ndjson beside match.ndjson")
    parser.add_argument("--no-link", action="store_true",
                        help="skip handshake linkage and leave every call unlinked")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    result = write_usage_sidecar(manifest, args.write_sidecar, link=not args.no_link)
    if not result["finalized"]:
        print("warning: host thread has no task_complete record; collection is provisional "
              "and should be repeated after the thread finishes", file=sys.stderr)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
