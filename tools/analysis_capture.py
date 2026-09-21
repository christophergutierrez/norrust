#!/usr/bin/env python3
"""Optional evidence capture for offline game analysis.

This module is a SEPARATE, best-effort sidecar. It never shares a file with
the main audit log written by `tools/llm_client.py` (`record()`/`durable()`),
and a failure here must never interrupt ordinary gameplay: any write error or
byte-cap exhaustion stops capture quietly and lets the game continue. The
frozen field names, enums and lifecycle rules below come from
`tmp/analysis-exec/CONTRACT.md`; this module implements that contract and
must not redesign it independently.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ANALYSIS_SCHEMA_VERSION = 1
ANALYSIS_DIR_SUFFIX = ".analysis"        # <logstem>.analysis/
ANALYSIS_RECORDS_NAME = "analysis.ndjson"
ANALYSIS_MANIFEST_NAME = "manifest.json"

# Stack-1 (minimal) record kinds. Later stacks extend this set; they must not
# redefine any of these names.
RECORD_KINDS = frozenset({
    "capture_started",
    "decision_start",
    "model_request",
    "action_commit",
    "turn_boundary",
    "game_terminal",
    "capture_status",
})

# Stack-2 record kinds: the complete passive decision trace. A user can see
# what the player was offered, what it selected, what failed, and what
# actually executed, including repair attempts. Every kind is mirrored from a
# game-log record the client already wrote (deviation 001), except
# `stage_timing` and `usage_receipt`, which the client records directly from
# facts it measures or owns.
STACK2_RECORD_KINDS = frozenset({
    "candidate_packet",      # what the player was offered (options, coverage, truncation)
    "candidate_validation",  # engine-validated selections for a packet
    "model_response",        # what the player answered (raw output, usage, cache)
    "model_failure",         # a model/backend error before a response existed
    "response_repair",       # repair attempts, incl. strategy recovery outcomes
    "batch_validation",      # pre-submit validation results (valid AND invalid)
    "validation_rejection",  # a driver-rejected batch after submission
    "execution_submit",      # proposed/forwarded orders, incl. routine and repair
    "routine_action",        # routine progress, independent moves, exceptions
    "policy_change",         # policy installation (model or fixed file)
    "resource_event",        # recruitment review resolution
    "finish_event",          # why a finish was forced (timeout, partial limit)
    "physical_retry",        # transport retries and output-limit retries
    "stage_timing",          # monotonic stage spans around one model request
    "usage_receipt",         # reference to the physical usage sidecar
})

RECORD_KINDS = frozenset(RECORD_KINDS | STACK2_RECORD_KINDS)

# Frozen across all stacks.
EVIDENCE_STATUSES = frozenset({
    "observed",
    "derived",
    "sampled",
    "missing",
    "conflicting",
    "not_applicable",
})

# Reports only, distinct from evidence status.
COVERAGE_STATUSES = frozenset({
    "complete",
    "capture_disabled",
    "capture_stopped",
    "unsupported_analysis",
    "empty_result",
})

REFERENCE_ROLES = frozenset({
    "prompt",
    "checkpoint",
    "response",
    "request_context",
    "usage",
    "game_log",
    "artifact",
})

# Exhaustive. Anything else is dropped, never `dict(os.environ)`, never a
# credential. See CONTRACT.md "launch allowlist".
LAUNCH_ALLOWLIST = frozenset({
    "driver",
    "scenario",
    "faction0",
    "faction1",
    "gold",
    "seed",
    "llm_side",
    "max_turns",
    "decision_mode",
    "action_encoding",
    "model_timeout",
    "max_output_tokens",
    "reasoning_effort",
    "analysis_capture",
})

DEFAULT_BYTE_CAP = 64 * 1024 * 1024

# Conservative headroom for the final `capture_status` record: its own body is
# small and fixed-shape, so a flat reservation is simpler than measuring it
# freshly on every write and just as safe.
FINAL_RECORD_RESERVE_BYTES = 512


def analysis_dir_for_log(log_path: str | os.PathLike[str]) -> Path:
    """Return the sidecar directory associated with an audit log.

    Mirrors `checkpoint_dir_for_log` in `tools/llm_client.py`: `.ckpt`,
    `.watchdog` and `.analysis` are siblings of the log, all computed by
    replacing the log's suffix, so they stay co-located under any logstem.
    """
    return Path(log_path).with_suffix(ANALYSIS_DIR_SUFFIX)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def allowlisted_launch(namespace_or_dict: Any) -> dict[str, Any]:
    """Filter launch parameters through `LAUNCH_ALLOWLIST`.

    Accepts either a mapping or an `argparse.Namespace`-like object (anything
    exposing `vars()`), so callers can pass parsed CLI args directly. Nothing
    outside the allowlist survives - this is the only path a manifest's
    `launch` field is built through, so it is structurally impossible to leak
    an environment dump or a credential-shaped key through it.
    """
    if isinstance(namespace_or_dict, dict):
        source = namespace_or_dict
    else:
        source = vars(namespace_or_dict)
    return {key: source[key] for key in LAUNCH_ALLOWLIST if key in source}


def make_reference(path: str | os.PathLike[str], role: str, base_dir: str | os.PathLike[str], *,
                    root: Optional[str | os.PathLike[str]] = None,
                    record_sequence: Optional[int] = None, byte_offset: Optional[int] = None,
                    byte_length: Optional[int] = None) -> dict[str, Any]:
    """Build a frozen reference object pointing at an evidence artifact.

    `path` is hashed and sized as given, then stored RELATIVE to `base_dir`
    (the `<logstem>.analysis/` directory) so a copied capsule - the whole
    analysis directory moved elsewhere - still resolves its references
    without rewriting them.

    A relative path is only portable if it stays inside the archive it will
    be copied with. `root` names that archive boundary and defaults to
    `base_dir`'s parent (the game directory, which holds the log, the
    `.analysis/` sidecar, `.ckpt/`, etc. - everything a capsule copy takes
    along together). `../match.ndjson` from `base_dir` is the intended common
    case and stays legal because it resolves inside `root`. A path outside
    `root` - e.g. a stray absolute tmp path - would emit a `../../...`
    reference that is syntactically relative but resolves nowhere once the
    capsule is copied elsewhere, which is worse than an absolute path because
    nothing flags it; that case raises `ValueError` instead of being written
    silently.
    """
    if role not in REFERENCE_ROLES:
        raise ValueError(f"unknown reference role: {role!r}")
    target = Path(path).resolve()
    base = Path(base_dir).resolve()
    archive_root = Path(root).resolve() if root is not None else base.parent
    payload = target.read_bytes()
    try:
        target.relative_to(archive_root)
    except ValueError:
        raise ValueError(
            f"reference path {target} escapes archive root {archive_root}; "
            "a relative path to it would not survive copying the analysis "
            "directory elsewhere") from None
    relative = os.path.relpath(target, base)
    return {
        "role": role,
        "path": relative,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "record_sequence": record_sequence,
        "byte_offset": byte_offset,
        "byte_length": byte_length,
    }


def make_range_reference(path: str | os.PathLike[str], role: str, base_dir: str | os.PathLike[str], *,
                         byte_offset: int, byte_length: int,
                        root: Optional[str | os.PathLike[str]] = None) -> dict[str, Any]:
    """Build a frozen reference to a BYTE RANGE of an evidence artifact.

    Stack 2 uses this to point at the exact game-log line a mirrored fact
    came from, so the sidecar never duplicates prompt or response bytes that
    the durable log already holds: the reference carries the line's byte
    offset, length and sha256, and a reader can verify the range without
    trusting the rest of the file. Semantics (deviation 002): when
    `byte_offset`/`byte_length` are non-null, `sha256` and `bytes` describe
    the RANGE, not the whole file. The archive-root rule is identical to
    `make_reference`.
    """
    if role not in REFERENCE_ROLES:
        raise ValueError(f"unknown reference role: {role!r}")
    if not isinstance(byte_offset, int) or byte_offset < 0:
        raise ValueError("byte_offset must be a non-negative integer")
    if not isinstance(byte_length, int) or byte_length <= 0:
        raise ValueError("byte_length must be a positive integer")
    target = Path(path).resolve()
    base = Path(base_dir).resolve()
    archive_root = Path(root).resolve() if root is not None else base.parent
    try:
        target.relative_to(archive_root)
    except ValueError:
        raise ValueError(
            f"reference path {target} escapes archive root {archive_root}; "
            "a relative path to it would not survive copying the analysis "
            "directory elsewhere") from None
    with target.open("rb") as stream:
        stream.seek(byte_offset)
        payload = stream.read(byte_length)
    if len(payload) != byte_length:
        raise ValueError(
            f"reference range [{byte_offset}, {byte_offset + byte_length}) exceeds "
            f"the size of {target}")
    return {
        "role": role,
        "path": os.path.relpath(target, base),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": byte_length,
        "record_sequence": None,
        "byte_offset": byte_offset,
        "byte_length": byte_length,
    }


def build_manifest(*, conversation_id: str, game_log: str, source_commit: str,
                    driver_hash: str, data_hash: str, scenario_hash: str,
                    canonical_prompt_hash: str, fixed_prefix_sha256: str,
                    game_seed: Any, controlled_side: Any,
                    opponent_identity: dict[str, Any],
                    launch: Any,
                    dirty_patch_hash: Optional[str] = None,
                    treatment: Optional[dict[str, Any]] = None,
                    limits: Optional[dict[str, Any]] = None,
                    capture_enabled: bool = True,
                    byte_cap: int = DEFAULT_BYTE_CAP,
                    capture_kinds: Optional[list[str]] = None,
                    parent_game_id: Optional[str] = None,
                    parent_checkpoint_sha256: Optional[str] = None,
                    lineage_root_id: Optional[str] = None,
                    provenance_gaps: Optional[dict[str, str]] = None,
                    created_at: Optional[str] = None) -> dict[str, Any]:
    """Build the frozen `manifest.json` payload.

    `launch` is always run through `allowlisted_launch` here - callers cannot
    bypass the allowlist by pre-filtering and passing a dict of their own
    choosing that happens to look safe.

    `provenance_gaps` names any manifest field left null and says WHY, so an
    unpopulated hash reads as a known limit rather than as a bug or as an
    assertion that the input was empty. A field that cannot be computed
    without a query the capture is forbidden to make belongs here; it does
    not get a fabricated value.
    """
    return {
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "created_at": created_at or _utcnow_iso(),
        "conversation_id": conversation_id,
        "game_log": game_log,
        "source_commit": source_commit,
        "dirty_patch_hash": dirty_patch_hash,
        "driver_hash": driver_hash,
        "data_hash": data_hash,
        "scenario_hash": scenario_hash,
        "canonical_prompt_hash": canonical_prompt_hash,
        "fixed_prefix_sha256": fixed_prefix_sha256,
        "treatment": treatment or {},
        "game_seed": game_seed,
        "controlled_side": controlled_side,
        "opponent_identity": opponent_identity,
        "limits": limits or {},
        "capture": {
            "enabled": capture_enabled,
            "byte_cap": byte_cap,
            "kinds": list(capture_kinds) if capture_kinds else [],
        },
        "launch": allowlisted_launch(launch),
        "resume": {
            "parent_game_id": parent_game_id,
            "parent_checkpoint_sha256": parent_checkpoint_sha256,
            "lineage_root_id": lineage_root_id,
        },
        "provenance_gaps": dict(provenance_gaps or {}),
    }


class AnalysisWriter:
    """Append-only writer for `<logstem>.analysis/analysis.ndjson`.

    Every failure mode here degrades to "capture stops, gameplay continues":
    a byte-cap breach or an `OSError` marks the writer stopped and further
    `.record()` calls become no-ops, never exceptions. The only thing a
    caller must still do is call `.close()` when the game ends normally, so
    the `capture_status` final marker gets written while there is still
    budget reserved for it.
    """

    def __init__(self, analysis_dir: Path, records_path: Path, handle: Any,
                 conversation_id: str, byte_cap: int):
        self.analysis_dir = analysis_dir
        self.records_path = records_path
        self.log_path: Optional[Path] = None
        self._handle = handle
        self.conversation_id = conversation_id
        self.byte_cap = byte_cap
        self.bytes_written = 0
        self.record_count = 0
        self.sequence = 0
        self.stopped = False
        self.stop_outcome: Optional[str] = None
        self.write_error: Optional[str] = None
        self._decision_sequence = 0
        self._decision_open = False
        self._decision_client_id: Optional[str] = None
        self._closed = False

    @classmethod
    def create(cls, log_path: str | os.PathLike[str], manifest: dict[str, Any], *,
               byte_cap: Optional[int] = DEFAULT_BYTE_CAP) -> "AnalysisWriter":
        """Create the sidecar directory and open it for writing.

        A `byte_cap` of None means "not configured" and falls back to the
        default; an explicit cap is used as given.  (Passing None explicitly
        must not silently disable the cap: `None - reserve` would raise deep
        inside the writer and, through the client's broad except, quietly
        turn capture off for the whole game.)

        The directory is created mode 0o700 and both files mode 0o600 -
        evidence capsules may carry prompts and reasoning traces, so they get
        the same restrictive permissions as other harness sidecars. The
        `capture_started` record is emitted as sequence 1, carrying the
        manifest's own sha256 in `refs` so a reader can detect a manifest
        that was edited after the fact.
        """
        analysis_dir = analysis_dir_for_log(log_path)
        analysis_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(analysis_dir, 0o700)

        manifest_path = analysis_dir / ANALYSIS_MANIFEST_NAME
        manifest_payload = json.dumps(manifest, sort_keys=True)
        manifest_path.write_text(manifest_payload, encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        manifest_sha256 = hashlib.sha256(manifest_payload.encode("utf-8")).hexdigest()

        records_path = analysis_dir / ANALYSIS_RECORDS_NAME
        handle = open(records_path, "a", encoding="utf-8")
        os.chmod(records_path, 0o600)

        conversation_id = manifest.get("conversation_id", "match")
        effective_cap = byte_cap if isinstance(byte_cap, int) and byte_cap > 0 else DEFAULT_BYTE_CAP
        writer = cls(analysis_dir, records_path, handle, conversation_id, effective_cap)
        writer.log_path = Path(log_path)
        writer._write_record({
            "kind": "capture_started",
            "decision_id": None,
            "side_turn_id": None,
            "request_id": None,
            "batch_id": None,
            "call_id": None,
            "state_revision": None,
            "evidence_status": "observed",
            "refs": [{"role": "artifact", "path": ANALYSIS_MANIFEST_NAME,
                      "sha256": manifest_sha256, "bytes": len(manifest_payload.encode("utf-8")),
                      "record_sequence": None, "byte_offset": None, "byte_length": None}],
            "body": {},
        })
        return writer

    def next_decision_id(self) -> str:
        """Mint the next `decision_id`, counted independently of `request_id`.

        A search-only decision (no model request at all) still needs a
        stable identity, so this counter never derives from
        `request_sequence`.
        """
        self._decision_sequence += 1
        return f"{self.conversation_id}:decision:{self._decision_sequence}"

    @property
    def current_decision_id(self) -> Optional[str]:
        """The decision most recently minted, or None before the first one.

        Turn boundaries, action commits and terminals are not themselves
        decisions, but they are evidence ABOUT the decision in flight, so they
        carry its id when one exists.  Before any decision has been minted the
        honest answer is None -- never a fabricated or back-dated id.
        """
        if self._decision_sequence == 0:
            return None
        return f"{self.conversation_id}:decision:{self._decision_sequence}"

    # -- Stack 2: decision identity without a model request ------------------
    #
    # Stack 1 minted a decision on every mirrored `model_request`. Stack 2
    # instruments the candidate path properly: a decision packet opens a
    # decision (strategy mode), a fresh purpose="decision" request opens one
    # (batch/focused mode), and repairs, reviews, follow-ups and tool rounds
    # REUSE the decision they belong to instead of minting a new identity for
    # the same choice point.

    def _mint_decision(self, start_body: dict[str, Any],
                       side_turn_id: Optional[str] = None,
                       state_revision: Optional[int] = None) -> str:
        """Mint a decision id and emit its `decision_start` record."""
        decision_id = self.next_decision_id()
        self._decision_open = True
        self._decision_client_id = start_body.get("client_decision_id")
        self.record("decision_start", decision_id=decision_id,
                    side_turn_id=side_turn_id, state_revision=state_revision,
                    body=dict(start_body))
        return decision_id

    def decision_for_request(self, purpose: Optional[str],
                             side_turn_id: Optional[str] = None,
                             state_revision: Optional[int] = None) -> Optional[str]:
        """Return the decision a model request belongs to, minting if needed.

        A repair, review or inspection follow-up continues the decision in
        flight. A fresh `decision` request reuses the current decision only
        when a decision packet opened it (strategy mode); otherwise it starts
        a new one. Returns None only when capture has stopped.
        """
        if self.stopped:
            return None
        if self._decision_open and (self._decision_client_id is not None
                                    or purpose != "decision"):
            return self.current_decision_id
        return self._mint_decision({"stage": "model_request", "purpose": purpose},
                                   side_turn_id=side_turn_id, state_revision=state_revision)

    def decision_for_packet(self, client_decision_id: Optional[str],
                            side_turn_id: Optional[str] = None,
                            state_revision: Optional[int] = None) -> Optional[str]:
        """Return the decision a candidate packet opens, minting if needed.

        The client's own packet decision id (a different id space from the
        analysis decision id) is recorded in the `decision_start` body so the
        two can be cross-referenced without being conflated. A packet with a
        NEW client decision id always opens a new analysis decision: a
        recovery packet or an incident recurrence is a new choice point even
        though no turn boundary separates them.
        """
        if self.stopped:
            return None
        if (self._decision_open and client_decision_id is not None
                and self._decision_client_id == client_decision_id):
            return self.current_decision_id
        return self._mint_decision(
            {"stage": "decision_packet", "client_decision_id": client_decision_id},
            side_turn_id=side_turn_id, state_revision=state_revision)

    def close_decision(self) -> None:
        """Mark the current decision closed (turn boundary or terminal)."""
        self._decision_open = False

    def note_usage_sidecar(self, sidecar_path: str | os.PathLike[str]) -> None:
        """Record the authoritative physical usage receipts for this game.

        The usage sidecar is append-only and written by the backend during
        play, so its hash is pinned once here, at game end; a receipt that
        changes afterwards is a visible conflict, not a silent pass. A game
        with no sidecar records `missing` evidence rather than implying zero
        usage.
        """
        if self.stopped or self._closed:
            return
        path = Path(sidecar_path)
        if not path.is_file():
            self.record("usage_receipt", decision_id=self.current_decision_id,
                        evidence_status="missing",
                        body={"reason": "no physical usage sidecar was written"})
            return
        try:
            ref = make_reference(path, "usage", self.analysis_dir)
        except (OSError, ValueError) as exc:
            self.record("usage_receipt", decision_id=self.current_decision_id,
                        evidence_status="missing",
                        body={"reason": f"usage sidecar unreadable: {exc}"})
            return
        self.record("usage_receipt", decision_id=self.current_decision_id,
                    refs=[ref],
                    body={"note": "hash pinned at game end; the sidecar is the "
                                  "authoritative physical-call receipt"})

    def record(self, kind: str, *, decision_id: str, side_turn_id: Optional[str] = None,
               request_id: Optional[str] = None, batch_id: Optional[str] = None,
               call_id: Optional[str] = None, state_revision: Optional[int] = None,
               evidence_status: str = "observed", refs: Optional[list[dict[str, Any]]] = None,
               body: Optional[dict[str, Any]] = None) -> None:
        """Append one record. A no-op once capture has stopped.

        Two distinct failure classes are handled differently on purpose:

        - An unrecognized `kind`, `evidence_status`, or reference `role` is a
          CALLER BUG - the caller wrote the wrong literal - and raises
          `ValueError` immediately, at this API boundary, so it is caught in
          tests and development rather than silently degrading capture.
        - A `body`/`refs` payload that LOOKS like valid Python but cannot be
          JSON-serialized (e.g. a caller accidentally passed a set, or a
          live object instead of its serialized form) is treated the same as
          any other write failure: capture stops with `stopped_write_error`
          and this call returns normally. That data-shape problem can arise
          from live game state a caller passed in, not just a static
          programming mistake, and the contract requires an optional writer
          failure to never interrupt gameplay.
        """
        if self.stopped or self._closed:
            return
        if kind not in RECORD_KINDS:
            raise ValueError(f"unknown record kind: {kind!r}")
        if evidence_status not in EVIDENCE_STATUSES:
            raise ValueError(f"unknown evidence status: {evidence_status!r}")
        refs = refs or []
        for ref in refs:
            role = ref.get("role")
            if role not in REFERENCE_ROLES:
                raise ValueError(f"unknown reference role: {role!r}")
        self._write_record({
            "kind": kind,
            "decision_id": decision_id,
            "side_turn_id": side_turn_id,
            "request_id": request_id,
            "batch_id": batch_id,
            "call_id": call_id,
            "state_revision": state_revision,
            "evidence_status": evidence_status,
            "refs": refs,
            "body": body or {},
        })

    def _write_record(self, partial: dict[str, Any]) -> None:
        """Assign the next sequence, serialize and append one NDJSON line.

        Byte-cap accounting always reserves `FINAL_RECORD_RESERVE_BYTES` for
        the eventual `capture_status` record: a write that would leave less
        than that headroom stops capture BEFORE writing the offending
        record, so the reservation is never eaten by the record that tripped
        it.

        A body that cannot be JSON-serialized is treated as a write failure,
        not a caller bug: it stops capture (`stopped_write_error`) instead of
        raising, per `.record`'s failure-class split above.
        """
        self.sequence += 1
        obj = {
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
            "sequence": self.sequence,
            "recorded_at": _utcnow_iso(),
            "conversation_id": self.conversation_id,
            **partial,
        }
        try:
            line = json.dumps(obj, sort_keys=True) + "\n"
        except (TypeError, ValueError) as exc:
            self.sequence -= 1
            self.write_error = str(exc)
            self._stop("stopped_write_error")
            return
        line_bytes = len(line.encode("utf-8"))
        is_final = partial.get("kind") == "capture_status"
        budget = self.byte_cap if is_final else self.byte_cap - FINAL_RECORD_RESERVE_BYTES
        if self.bytes_written + line_bytes > budget:
            self.sequence -= 1  # this record was never written; do not burn its sequence
            self._stop("stopped_byte_cap")
            return
        try:
            self._handle.write(line)
            self._handle.flush()
        except OSError as exc:
            self.sequence -= 1
            self.write_error = str(exc)
            self._stop("stopped_write_error")
            return
        self.bytes_written += line_bytes
        self.record_count += 1

    def _stop(self, outcome: str) -> None:
        """Mark capture stopped and best-effort write the final marker.

        Never propagates: an analysis writer is optional infrastructure, and
        the contract is explicit that a write failure must let ordinary
        gameplay continue.
        """
        if self.stopped:
            return
        self.stopped = True
        self.stop_outcome = outcome
        try:
            self.close(outcome=outcome)
        except OSError as exc:
            self.write_error = self.write_error or str(exc)

    def close(self, outcome: str = "complete") -> None:
        """Write the final `capture_status` record and close the file.

        Idempotent: a second call is a no-op. This is the only path that
        writes a `capture_status` record, whether called by a normal
        game-end, or internally by `_stop` after a cap or write failure.
        """
        if self._closed:
            return
        self._closed = True
        self.sequence += 1
        obj = {
            "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
            "sequence": self.sequence,
            "kind": "capture_status",
            "recorded_at": _utcnow_iso(),
            "conversation_id": self.conversation_id,
            "decision_id": None,
            "side_turn_id": None,
            "request_id": None,
            "batch_id": None,
            "call_id": None,
            "state_revision": None,
            "evidence_status": "observed",
            "refs": [],
            "body": {"outcome": outcome, "records": self.record_count},
        }
        line = json.dumps(obj, sort_keys=True) + "\n"
        try:
            self._handle.write(line)
            self._handle.flush()
            self.bytes_written += len(line.encode("utf-8"))
            self.record_count += 1
            os.fsync(self._handle.fileno())
        except OSError as exc:
            self.write_error = self.write_error or str(exc)
        finally:
            try:
                self._handle.close()
            except OSError as exc:
                self.write_error = self.write_error or str(exc)


@dataclass
class ReadWarning:
    """One problem found while reading `analysis.ndjson`."""
    byte_offset: int
    message: str
    partial: bool = False


@dataclass
class ReadResult:
    """Result of `read_records`."""
    records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[ReadWarning] = field(default_factory=list)
    has_final_marker: bool = False


def read_records(analysis_dir: str | os.PathLike[str]) -> ReadResult:
    """Read back `analysis.ndjson`, distinguishing truncation from corruption.

    A truncated FINAL line (the process died mid-write) yields every good
    record before it plus a partial warning. Corruption in a COMPLETE
    interior record - a line that parses as neither valid JSON nor a
    trailing partial write - is reported with its byte offset rather than
    silently skipped, per the contract's import rules. Absence of a
    `capture_status` record at the end means "crashed, evidence incomplete";
    callers must check `has_final_marker`.
    """
    records_path = Path(analysis_dir) / ANALYSIS_RECORDS_NAME
    result = ReadResult()
    raw = records_path.read_bytes()
    lines = raw.split(b"\n")
    # split() on a well-formed file (every line newline-terminated) leaves a
    # trailing empty element; drop it so it is not mistaken for a truncated
    # final line.
    if lines and lines[-1] == b"":
        lines.pop()
    offset = 0
    for index, raw_line in enumerate(lines):
        is_last = index == len(lines) - 1
        try:
            text = raw_line.decode("utf-8")
            obj = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if is_last:
                result.warnings.append(ReadWarning(
                    byte_offset=offset, message=f"truncated final record: {exc}", partial=True))
            else:
                result.warnings.append(ReadWarning(
                    byte_offset=offset, message=f"corrupt interior record: {exc}", partial=False))
            offset += len(raw_line) + 1
            continue
        if not isinstance(obj, dict):
            result.warnings.append(ReadWarning(
                byte_offset=offset, message="record is not a JSON object", partial=False))
            offset += len(raw_line) + 1
            continue
        result.records.append(obj)
        if obj.get("kind") == "capture_status":
            result.has_final_marker = True
        offset += len(raw_line) + 1
    return result


@dataclass
class ValidationConflict:
    """A request-identity conflict between two `model_request` records."""
    request_id: str
    sequences: list[int]
    reason: str


@dataclass
class ValidationResult:
    """Result of `validate_records`."""
    ok: bool
    errors: list[str] = field(default_factory=list)
    conflicts: list[ValidationConflict] = field(default_factory=list)


def validate_records(records: list[dict[str, Any]]) -> ValidationResult:
    """Validate sequencing, enum membership, ordering, and request identity.

    Checks: sequences are contiguous starting at 1; `capture_started` is the
    first record; every `kind` and `evidence_status` is a recognized enum
    member; and any two `model_request` records that share a `request_id`
    but disagree on `state_revision` or prompt hash are surfaced as a
    conflict - both records are reported, neither is discarded, matching the
    contract's "never merge on matching revision" rule.
    """
    errors: list[str] = []
    if not records:
        return ValidationResult(ok=False, errors=["no records"])

    if records[0].get("kind") != "capture_started":
        errors.append("first record is not capture_started")

    expected_sequence = 1
    for obj in records:
        sequence = obj.get("sequence")
        if sequence != expected_sequence:
            errors.append(f"sequence gap: expected {expected_sequence}, found {sequence!r}")
        expected_sequence = (sequence if isinstance(sequence, int) else expected_sequence) + 1

        kind = obj.get("kind")
        if kind not in RECORD_KINDS:
            errors.append(f"sequence {sequence}: unknown kind {kind!r}")

        evidence_status = obj.get("evidence_status")
        if evidence_status not in EVIDENCE_STATUSES:
            errors.append(f"sequence {sequence}: unknown evidence_status {evidence_status!r}")

        for ref in obj.get("refs") or []:
            role = ref.get("role") if isinstance(ref, dict) else None
            if role not in REFERENCE_ROLES:
                errors.append(f"sequence {sequence}: unknown reference role {role!r}")

    conflicts: list[ValidationConflict] = []
    by_request_id: dict[str, list[dict[str, Any]]] = {}
    for obj in records:
        if obj.get("kind") != "model_request":
            continue
        request_id = obj.get("request_id")
        if not isinstance(request_id, str):
            continue
        by_request_id.setdefault(request_id, []).append(obj)

    for request_id, group in by_request_id.items():
        if len(group) < 2:
            continue
        revisions = {obj.get("state_revision") for obj in group}
        prompt_hashes = {
            (obj.get("body") or {}).get("prompt_sha256")
            for obj in group
        }
        # A matching hash with differing byte counts cannot both be right -
        # that is not a legitimate resume-with-a-new-prompt case, it is
        # itself evidence of corruption somewhere upstream, so it is flagged
        # even when `prompt_hashes` alone would look consistent.
        prompt_byte_counts = {
            (obj.get("body") or {}).get("prompt_bytes")
            for obj in group
        }
        reasons = []
        if len(revisions) > 1:
            reasons.append("differing state_revision")
        if len(prompt_hashes) > 1:
            reasons.append("differing prompt hash")
        if len(prompt_hashes) == 1 and len(prompt_byte_counts) > 1:
            reasons.append("matching prompt hash but differing prompt_bytes (corruption signal)")
        if reasons:
            conflicts.append(ValidationConflict(
                request_id=request_id,
                sequences=[obj.get("sequence") for obj in group],
                reason="; ".join(reasons) + " for shared request_id",
            ))

    return ValidationResult(ok=not errors, errors=errors, conflicts=conflicts)
