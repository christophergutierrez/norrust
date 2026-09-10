"""Import Norrust match archives into a small, rebuildable SQLite catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
import os
import sqlite3
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any, Iterable

try:
    from .model_usage import ModelCall, TOKEN_FIELDS, aggregate_calls, dedupe_calls, request_aggregate_from_legacy
except ImportError:  # pragma: no cover - direct script compatibility
    from model_usage import ModelCall, TOKEN_FIELDS, aggregate_calls, dedupe_calls, request_aggregate_from_legacy  # type: ignore

SCHEMA_VERSION = 6
# IMPORTER_VERSION guards the SNAPSHOT TIMELINE contract that tools/replay_game.py
# refuses to export against. Storing executed events did not change how a frame is
# built, so it deliberately does NOT bump: bumping it would make all previously
# catalogued games refuse to replay, and backfill-events - which only adds derived
# event rows - would not clear that. Whether a game has event evidence is reported
# by coverage_json.events_status instead. Bump this only when the timeline or the
# exported frame contract itself changes.
IMPORTER_VERSION = "s1_snapshot_v1"
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS games (
 game_id TEXT PRIMARY KEY, cohort_id TEXT, parent_game_id TEXT, lineage_root_id TEXT,
 seed INTEGER, scenario TEXT, faction0 TEXT, faction1 TEXT, starting_gold INTEGER,
 first_side INTEGER, max_side_turns INTEGER, started_at TEXT, ended_at TEXT, wall_ms INTEGER,
 status TEXT NOT NULL, winner_side INTEGER, termination_reason TEXT, failure_code TEXT,
 source_commit TEXT, dirty_patch_hash TEXT, driver_hash TEXT, prompt_hash TEXT,
 config_json TEXT NOT NULL, provenance_json TEXT NOT NULL, schema_version INTEGER NOT NULL,
 artifact_path TEXT NOT NULL, manifest_hash TEXT, import_status TEXT NOT NULL DEFAULT 'complete',
 coverage_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS game_players (
 game_id TEXT NOT NULL REFERENCES games(game_id), side INTEGER NOT NULL,
 player_kind TEXT, display_name TEXT, backend TEXT, model_requested TEXT, model_reported TEXT,
 model_evidence TEXT, reasoning_requested TEXT, reasoning_reported TEXT, reasoning_evidence TEXT,
 adapter_hash TEXT, settings_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY(game_id, side)
);
CREATE TABLE IF NOT EXISTS side_turns (
 side_turn_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id),
 sequence INTEGER NOT NULL, round_number INTEGER, side INTEGER NOT NULL, started_at TEXT,
 ended_at TEXT, wall_ms INTEGER, model_wait_ms INTEGER, engine_ms INTEGER, status TEXT NOT NULL,
 finish_kind TEXT, end_turn_emitted INTEGER, start_revision INTEGER, end_revision INTEGER,
 start_state_blob BLOB, end_state_blob BLOB, start_state_hash TEXT, end_state_hash TEXT,
 state_codec TEXT, metrics_json TEXT NOT NULL DEFAULT '{}', coverage_json TEXT NOT NULL DEFAULT '{}',
 record_hash TEXT NOT NULL, UNIQUE(game_id, sequence)
);
CREATE TABLE IF NOT EXISTS snapshots (
 snapshot_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id),
 sequence INTEGER NOT NULL, revision INTEGER, round_number INTEGER, active_side INTEGER,
 completed_side_turns INTEGER, boundary_kind TEXT NOT NULL, renderable INTEGER NOT NULL DEFAULT 0,
 state_blob BLOB, state_codec TEXT, state_hash TEXT,
 sources_json TEXT NOT NULL DEFAULT '[]', conflict_json TEXT NOT NULL DEFAULT '[]',
 record_hash TEXT NOT NULL, UNIQUE(game_id, sequence)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_game ON snapshots(game_id, sequence);
CREATE TABLE IF NOT EXISTS events (
 game_id TEXT NOT NULL REFERENCES games(game_id), event_sequence INTEGER NOT NULL,
 side_turn_id TEXT, batch_id TEXT, kind TEXT NOT NULL, source TEXT,
 event_json TEXT NOT NULL, record_sequence INTEGER NOT NULL, event_index INTEGER NOT NULL,
 record_hash TEXT NOT NULL,
 PRIMARY KEY(game_id, event_sequence),
 UNIQUE(game_id, record_sequence, event_index)
);
CREATE INDEX IF NOT EXISTS idx_events_side_turn ON events(side_turn_id);
CREATE TABLE IF NOT EXISTS model_requests (
 request_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id), side_turn_id TEXT,
 sequence INTEGER, logical_call_id TEXT, retry_of_request_id TEXT, purpose TEXT, status TEXT,
 error_code TEXT, error_message TEXT, native_session_id TEXT, native_request_id TEXT,
 started_at TEXT, ended_at TEXT, elapsed_ms INTEGER, input_tokens INTEGER,
 cached_input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER, usage_source TEXT,
 prompt_bytes INTEGER, response_bytes INTEGER, prompt_blob BLOB, response_blob BLOB,
 prompt_hash TEXT, response_hash TEXT, payload_codec TEXT, context_complete INTEGER,
 reasoning_blob BLOB, reasoning_kind TEXT, reasoning_source TEXT,
 annotation_status TEXT, state_revision INTEGER,
 prompt_layout_version TEXT, fixed_prefix_sha256 TEXT, fixed_prefix_bytes INTEGER,
 raw_usage_json TEXT, record_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_batches (
 batch_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id), side_turn_id TEXT,
 request_id TEXT, sequence INTEGER, source TEXT, contract_version TEXT,
 submitted_orders_json TEXT, status TEXT, error_code TEXT, before_revision INTEGER,
 after_revision INTEGER, order_results_json TEXT, record_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS actions (
 action_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id), side_turn_id TEXT,
 request_id TEXT, batch_id TEXT, sequence INTEGER, authored_order_index INTEGER, source TEXT,
 action_type TEXT, action_json TEXT, status TEXT, error_code TEXT, before_revision INTEGER,
 after_revision INTEGER, events_json TEXT, record_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_runs (
 evaluation_run_id TEXT PRIMARY KEY, evaluator_name TEXT, evaluator_version TEXT,
 source_commit TEXT, config_json TEXT NOT NULL, input_manifest_hash TEXT, started_at TEXT,
 completed_at TEXT, status TEXT, artifact_path TEXT
);
CREATE TABLE IF NOT EXISTS decision_evaluations (
 evaluation_run_id TEXT NOT NULL REFERENCES evaluation_runs(evaluation_run_id),
 request_id TEXT NOT NULL REFERENCES model_requests(request_id), verdict TEXT NOT NULL,
 reason_codes_json TEXT NOT NULL, metrics_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
 preferred_request_id TEXT, PRIMARY KEY(evaluation_run_id, request_id)
);
CREATE TABLE IF NOT EXISTS model_calls (
 game_id TEXT NOT NULL REFERENCES games(game_id), call_id TEXT NOT NULL,
 request_id TEXT, retry_of_call_id TEXT,
 provider TEXT, transport TEXT, native_thread_id TEXT, provider_response_id TEXT,
 requested_model TEXT, reported_model TEXT, requested_reasoning_effort TEXT,
 requested_affinity TEXT, prompt_layout_version TEXT, prompt_layout_source TEXT,
 reported_reasoning_effort TEXT, output_limit INTEGER,
 status TEXT NOT NULL, finish_reason TEXT, error_code TEXT,
 started_at TEXT, ended_at TEXT, elapsed_ms INTEGER,
 input_tokens INTEGER, cached_input_tokens INTEGER, cache_write_input_tokens INTEGER,
 output_tokens INTEGER, reasoning_tokens INTEGER, total_tokens INTEGER,
 usage_source TEXT, usage_schema_version TEXT, raw_usage_json TEXT,
 source_ref TEXT, source_hash TEXT, linkage_evidence TEXT,
 normalization_gaps_json TEXT NOT NULL DEFAULT '[]',
 record_hash TEXT NOT NULL,
 PRIMARY KEY(game_id, call_id)
);
CREATE INDEX IF NOT EXISTS idx_calls_game_request ON model_calls(game_id, request_id);
CREATE INDEX IF NOT EXISTS idx_calls_source_identity
 ON model_calls(provider, native_thread_id, provider_response_id);
CREATE INDEX IF NOT EXISTS idx_games_cohort ON games(cohort_id);
CREATE INDEX IF NOT EXISTS idx_games_commit ON games(source_commit);
CREATE INDEX IF NOT EXISTS idx_players_model ON game_players(model_reported, game_id);
CREATE INDEX IF NOT EXISTS idx_turns_game ON side_turns(game_id, sequence);
CREATE INDEX IF NOT EXISTS idx_requests_game ON model_requests(game_id, sequence);
CREATE INDEX IF NOT EXISTS idx_batches_game ON action_batches(game_id, sequence);
CREATE INDEX IF NOT EXISTS idx_actions_game ON actions(game_id, sequence);
CREATE VIEW IF NOT EXISTS game_summary AS
 SELECT g.*, count(DISTINCT st.side_turn_id) resolved_turns,
 count(DISTINCT mr.request_id) request_count, count(DISTINCT a.action_id) action_count
 FROM games g LEFT JOIN side_turns st USING(game_id)
 LEFT JOIN model_requests mr USING(game_id) LEFT JOIN actions a USING(game_id)
 GROUP BY g.game_id;
"""

def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()

def encode_payload(value: Any) -> tuple[bytes, str, str]:
    raw = canonical(value)
    return zlib.compress(raw, 6), "zlib", hashlib.sha256(raw).hexdigest()

def decode_payload(blob: bytes, codec: str = "zlib") -> Any:
    return json.loads(zlib.decompress(blob) if codec == "zlib" else blob)

def requested_identity(artifact_path: str | os.PathLike[str], expected: dict[str, Any],
                       factions: tuple[Any, Any]) -> tuple[str, int] | None:
    """Resolve a REQUESTED model identity from an archive's identity.json sidecar.

    A transport such as tools/file_backend.py cannot attach the host's model
    identity to the catalog, so an operator's sidecar is the only evidence of who
    played. It is requested identity, never reported: callers must label it as
    such and must not overwrite an identity the catalog actually recorded.

    Returns (model, llm_side) only when the sidecar names a model AND every field
    it repeats matches the catalog, so a stale or copied sidecar cannot relabel a
    different game. Shared by the browser and the replay export so the two views
    can never disagree about who played.
    """
    archive = Path(artifact_path)
    path = archive / "identity.json" if archive.is_dir() else archive.parent / "identity.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        requested = value.get("requested", value) if isinstance(value, dict) else {}
        if not isinstance(requested, dict):
            return None
        model = requested.get("llm_player_model") or requested.get("model_requested")
        side = requested.get("llm_side")
        if not isinstance(model, str) or not model.strip() or model.strip().lower().startswith("unknown"):
            return None
        for key, field in (("game_id", "game_id"), ("seed", "seed"), ("scenario", "scenario"),
                           ("gold", "starting_gold"), ("starting_gold", "starting_gold"),
                           ("max_turns", "max_side_turns")):
            if key in requested and requested[key] != expected.get(field):
                return None
        for side_index in (0, 1):
            key = f"faction{side_index}"
            if key in requested and requested[key] != factions[side_index]:
                return None
        if type(side) is int and side in (0, 1):
            return model, side
    except (OSError, ValueError, TypeError):
        return None
    return None


def open_history(path: str | os.PathLike[str], *, read_only: bool = False) -> sqlite3.Connection:
    path = Path(path)
    if read_only:
        if not path.is_file():
            raise FileNotFoundError(f"history catalog does not exist: {path}")
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    if read_only:
        return conn
    conn.executescript(SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(model_requests)")}
    for name, definition in (
        ("reasoning_blob", "BLOB"),
        ("reasoning_kind", "TEXT"),
        ("reasoning_source", "TEXT"),
        ("annotation_status", "TEXT"),
        ("state_revision", "INTEGER"),
        ("prompt_layout_version", "TEXT"),
        ("fixed_prefix_sha256", "TEXT"),
        ("fixed_prefix_bytes", "INTEGER"),
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE model_requests ADD COLUMN {name} {definition}")
    games_columns = {row[1] for row in conn.execute("PRAGMA table_info(games)")}
    if "importer_version" not in games_columns:
        conn.execute("ALTER TABLE games ADD COLUMN importer_version TEXT")
    side_turn_columns = {row[1] for row in conn.execute("PRAGMA table_info(side_turns)")}
    for name, definition in (
        ("start_snapshot_id", "TEXT"),
        ("end_snapshot_id", "TEXT"),
        ("endpoint_link_kind", "TEXT"),
    ):
        if name not in side_turn_columns:
            conn.execute(f"ALTER TABLE side_turns ADD COLUMN {name} {definition}")
    call_columns = {row[1] for row in conn.execute("PRAGMA table_info(model_calls)")}
    for name, definition in (("requested_affinity", "TEXT"),
                             ("prompt_layout_version", "TEXT"),
                             ("prompt_layout_source", "TEXT")):
        if name not in call_columns:
            conn.execute(f"ALTER TABLE model_calls ADD COLUMN {name} {definition}")
    return conn

def _records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

def _driver(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r["line"] for r in records if r.get("type") == "driver" and isinstance(r.get("line"), dict)]

def _first(records: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next((r for r in records if r.get("type") == kind), {})

def _state_payload(state: dict[str, Any] | None) -> tuple[bytes | None, str | None, str | None]:
    if not state:
        return None, None, None
    return encode_payload(state)

def _state_fingerprint(state: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(state)).hexdigest()

# Checkpoint "boundary" values map to the same coarse vocabulary used for
# accepted turn_boundary records so the two evidence kinds can be compared.
_CHECKPOINT_BOUNDARY_KIND = {
    "post_batch": "partial", "postbatch": "partial", "post-batch": "partial",
    "turn_end": "side_turn_end", "side_turn": "side_turn_end", "side_turn_end": "side_turn_end",
    "start": "opening", "initial": "opening",
}

def _dump_checkpoint_bin() -> str | None:
    """Locate the read-only `dump_checkpoint` binary, or None if unavailable.

    `NORRUST_DUMP_CHECKPOINT_BIN` takes precedence (set by the test/build
    harness, which knows Cargo's actual target directory); otherwise the
    conventional debug and release build paths are tried. A missing tool is
    not an error here -- callers report the resulting coverage gap honestly
    rather than fabricating a renderable state.
    """
    override = os.environ.get("NORRUST_DUMP_CHECKPOINT_BIN")
    if override:
        return override if Path(override).is_file() else None
    root = Path(__file__).resolve().parents[1]
    for candidate in ("target/debug/dump_checkpoint", "target/release/dump_checkpoint"):
        path = root / "norrust_core" / candidate
        if path.is_file():
            return str(path)
    return None

def _render_checkpoint_state(checkpoint_path: str) -> tuple[dict[str, Any] | None, str | None]:
    """Run the read-only checkpoint dumper and return (state, error).

    Never falls back to today's unit/terrain definitions on its own -- a
    missing historical resource surfaces as the tool's own error message, and
    a missing tool surfaces as `dump_checkpoint_unavailable`.
    """
    binary = _dump_checkpoint_bin()
    if binary is None:
        return None, "dump_checkpoint_unavailable"
    try:
        completed = subprocess.run([binary, checkpoint_path], capture_output=True,
                                   text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"dump_checkpoint_failed:{exc}"
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        return None, f"dump_checkpoint_failed:{message}"
    try:
        state = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None, "dump_checkpoint_failed:invalid JSON output"
    if not isinstance(state, dict):
        return None, "dump_checkpoint_failed:non-object output"
    return state, None

def _load_checkpoint_envelope(log: Path, reference: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and load a driver checkpoint, reusing the client's own checker.

    Returns (envelope, error). A checkpoint that fails validation (missing
    file, digest mismatch, malformed JSON) is reported as a gap, never
    silently skipped or replaced with a guess.
    """
    try:
        from .llm_client import checkpoint_dir_for_log, validate_checkpoint_reference
    except ImportError:  # pragma: no cover - direct script compatibility
        from llm_client import checkpoint_dir_for_log, validate_checkpoint_reference  # type: ignore
    try:
        return validate_checkpoint_reference(reference, checkpoint_dir_for_log(log)), None
    except ValueError as exc:
        return None, str(exc)

def _build_snapshots(log: Path, lines: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Build the authoritative, ordered snapshot collection for one game.

    Snapshots are ordered by the position their evidence first appears in the
    archive (proven execution order), not by revision number -- a resumed
    game can restart the revision counter, so sorting by revision alone would
    misorder or falsely merge resume branches.

    A checkpoint is coalesced onto an existing renderable log-state snapshot
    only when it proves the same execution state (matching revision, and
    matching completed side-turn count when both are known). Otherwise it
    becomes its own non-renderable snapshot: its identity, round, side, and
    completed-turn count still belong in the timeline and can prove a side
    turn's endpoint, but this importer has no engine-independent way to
    rebuild full unit/terrain data from a checkpoint alone, so it is never
    exported as a playback frame. That is a real, reported coverage gap
    rather than a state reconstructed from today's data files.
    """
    built: list[dict[str, Any]] = []
    by_revision: dict[int, int] = {}
    gaps: list[str] = []
    for line in lines:
        kind = line.get("type")
        if kind == "state":
            revision = _number(line.get("state_revision"))
            fingerprint = _state_fingerprint(line)
            if revision is not None and revision in by_revision:
                existing = built[by_revision[revision]]
                if existing["renderable"] and existing["state_hash"] == fingerprint:
                    existing["sources"].append({"kind": "log_state", "ref": None, "hash": fingerprint})
                    continue  # exact duplicate representation of the same moment
                if all(source["kind"] in ("checkpoint", "checkpoint_rendered")
                       for source in existing["sources"]):
                    # A checkpoint published for this exact revision arrived
                    # first (the driver writes its "model"/"partial" boundary
                    # checkpoint before printing the matching "state" line),
                    # so this is the first log evidence of its content either
                    # way. Whether or not dump_checkpoint could render it, a
                    # checkpoint-only entry's state was never proven against
                    # a real logged state -- its dump_checkpoint rendering
                    # (when available) omits the boundary-print-only fields
                    # (`type`, `winner`, `turn_boundary`, ...) a "state" log
                    # line carries, so their content hashes never match even
                    # when they are the same moment. This proven log state is
                    # that same moment, not a distinct one, as long as it
                    # doesn't contradict the checkpoint's own completed-side-
                    # turn count -- upgrade the existing (correctly sequenced)
                    # entry in place instead of appending an orphaned
                    # duplicate that would wrongly displace it from the
                    # timeline's first position.
                    completed = _record_side_turn(line)
                    if (existing["completed_side_turns"] is None or completed is None
                            or existing["completed_side_turns"] == completed):
                        existing.update({
                            "round": existing["round"] if existing["round"] is not None else _number(line.get("turn")),
                            "side": existing["side"] if existing["side"] is not None else _number(line.get("active_faction")),
                            "completed_side_turns": existing["completed_side_turns"] if existing["completed_side_turns"] is not None else completed,
                            "boundary_kind": "partial" if line.get("turn_boundary") == "partial" else "unknown",
                            "renderable": True, "state": line, "state_hash": fingerprint,
                        })
                        existing["sources"].append({"kind": "log_state", "ref": None, "hash": fingerprint})
                        continue
                # Same revision number, different content: a resume/replay
                # branch reused it. Proven distinct by content; keep both.
            built.append({
                "revision": revision, "round": _number(line.get("turn")),
                "side": _number(line.get("active_faction")),
                "completed_side_turns": _record_side_turn(line),
                "boundary_kind": "partial" if line.get("turn_boundary") == "partial" else "unknown",
                "renderable": True, "state": line, "state_hash": fingerprint,
                "sources": [{"kind": "log_state", "ref": None, "hash": fingerprint}], "conflicts": [],
            })
            if revision is not None:
                by_revision[revision] = len(built) - 1
        elif kind == "checkpoint":
            envelope, error = _load_checkpoint_envelope(log, line)
            if error is not None:
                gaps.append(f"checkpoint_unavailable:{line.get('path')}:{error}")
                continue
            revision = _number(line.get("state_revision"))
            completed = _number(line.get("side_turns"))
            boundary_kind = _CHECKPOINT_BOUNDARY_KIND.get(line.get("boundary"), "resume_checkpoint")
            matched = by_revision.get(revision) if revision is not None else None
            if matched is not None:
                existing = built[matched]
                if (existing["completed_side_turns"] is not None and completed is not None
                        and existing["completed_side_turns"] != completed):
                    note = (f"conflict:revision:{revision}: checkpoint reports {completed} "
                            f"completed side turns, log reports {existing['completed_side_turns']}")
                    existing["conflicts"].append(note)
                    gaps.append(note)
                else:
                    if existing["completed_side_turns"] is None:
                        existing["completed_side_turns"] = completed
                    existing["sources"].append({"kind": "checkpoint", "ref": line.get("path"),
                                                "hash": line.get("digest")})
                continue
            save_state = envelope.get("envelope", {}).get("save_state") if isinstance(envelope, dict) else None
            # This importer has no engine-independent way to rebuild full
            # unit/terrain data from a checkpoint on its own; when the
            # read-only dump_checkpoint tool is available, use it to render
            # the checkpoint into the same state shape a logged "state" line
            # carries, rather than leaving a provably-reached moment
            # unplayable. A missing tool, or a checkpoint whose historical
            # unit/terrain resources are gone, stays a reported gap -- never
            # silently replaced with today's data definitions.
            rendered_state, render_error = (
                _render_checkpoint_state(envelope["absolute_path"])
                if isinstance(envelope, dict) and isinstance(envelope.get("absolute_path"), str)
                else (None, "dump_checkpoint_unavailable")
            )
            renderable = rendered_state is not None
            state_hash = _state_fingerprint(rendered_state) if renderable else None
            sources = [{"kind": "checkpoint", "ref": line.get("path"), "hash": line.get("digest")}]
            if renderable:
                sources.append({"kind": "checkpoint_rendered", "ref": line.get("path"), "hash": state_hash})
            else:
                gaps.append(f"checkpoint_not_renderable:{line.get('path')}:{render_error}")
            built.append({
                "revision": revision,
                "round": (_number(rendered_state.get("turn")) if renderable
                          else (_number(save_state.get("turn")) if isinstance(save_state, dict) else None)),
                "side": (_number(rendered_state.get("active_faction")) if renderable
                         else (_number(save_state.get("active_faction")) if isinstance(save_state, dict) else None)),
                "completed_side_turns": completed, "boundary_kind": boundary_kind,
                "renderable": renderable,
                "state": rendered_state if renderable else None,
                "state_hash": state_hash,
                "sources": sources,
                "conflicts": [],
            })
            if revision is not None and revision not in by_revision:
                by_revision[revision] = len(built) - 1
    for index, snapshot in enumerate(built):
        snapshot["sequence"] = index + 1
    if built and built[0]["boundary_kind"] == "unknown":
        # The very first recorded observation is the game's opening,
        # whatever its boundary_kind would otherwise default to.
        built[0]["boundary_kind"] = "opening"
    if built:
        # Capture the opening ROLE separately, before _mark_terminal can
        # relabel this same snapshot. A game that ends before any state
        # change - a turn-one resignation, or a win on the opening
        # position - coalesces its opening and its terminal into one proven
        # state, and that snapshot is legitimately both. boundary_kind can
        # only carry one label, so the opening cannot be inferred from it.
        built[0]["is_opening"] = built[0]["boundary_kind"] == "opening"
    return built, gaps

def _mark_terminal(snapshots: list[dict[str, Any]], terminal: dict[str, Any]) -> None:
    """Attach the "terminal" boundary_kind to the game's final evidence.

    An explicit `state_revision` on the terminal record is proof enough when
    it identifies exactly one snapshot. Otherwise, since the terminal record
    is always appended after every state/checkpoint record in the archive,
    the last built snapshot is literally the final piece of evidence before
    the game ended -- not a guess from ordinal position among many
    candidates, but the one and only thing that comes right before it. This
    also covers a winning partial batch and a resignation whose terminal
    state equals the preceding one.
    """
    if not terminal or not snapshots:
        return
    explicit_revision = _number(terminal.get("state_revision"))
    if explicit_revision is not None:
        match = _snapshot_for_revision(snapshots, explicit_revision)
        if match is not None:
            match["boundary_kind"] = "terminal"
            return
    snapshots[-1]["boundary_kind"] = "terminal"

def _insert_snapshots(conn: sqlite3.Connection, game_id: str, snapshots: list[dict[str, Any]]) -> None:
    for snapshot in snapshots:
        state_blob = state_codec = state_hash = None
        if snapshot["renderable"] and snapshot["state"] is not None:
            state_blob, state_codec, _ = encode_payload(snapshot["state"])
            state_hash = snapshot["state_hash"]
        snapshot_id = f"{game_id}:snapshot:{snapshot['sequence']}"
        snapshot["snapshot_id"] = snapshot_id
        payload = {"sequence": snapshot["sequence"], "revision": snapshot["revision"],
                   "boundary_kind": snapshot["boundary_kind"], "sources": snapshot["sources"]}
        conn.execute("""INSERT INTO snapshots
          (snapshot_id,game_id,sequence,revision,round_number,active_side,completed_side_turns,
           boundary_kind,renderable,state_blob,state_codec,state_hash,sources_json,conflict_json,
           record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (snapshot_id, game_id, snapshot["sequence"], snapshot["revision"], snapshot["round"],
           snapshot["side"], snapshot["completed_side_turns"], snapshot["boundary_kind"],
           int(snapshot["renderable"]), state_blob, state_codec, state_hash,
           json.dumps(snapshot["sources"], sort_keys=True), json.dumps(snapshot["conflicts"], sort_keys=True),
           digest(payload)))

def _coverage_summary(snapshots: list[dict[str, Any]], terminal: dict[str, Any],
                      linkage: dict[str, Any]) -> dict[str, Any]:
    terminal_snapshot = next((s for s in snapshots if s["boundary_kind"] == "terminal"), None)
    gaps: list[str] = []
    conflicts: list[str] = []
    for snapshot in snapshots:
        conflicts.extend(snapshot["conflicts"])
    if terminal and terminal_snapshot is None:
        gaps.append("terminal_state_unresolved")
    if terminal_snapshot is not None and not terminal_snapshot["renderable"]:
        gaps.append(f"terminal_snapshot_not_renderable:revision:{terminal_snapshot['revision']}")
    if not snapshots:
        gaps.append("no_recorded_snapshots")
    elif not (snapshots[0].get("is_opening") and snapshots[0]["renderable"]):
        gaps.append("opening_state_not_renderable")
    if linkage["unresolved_turn_endpoints"]:
        gaps.append(f"unresolved_turn_endpoints:{linkage['unresolved_turn_endpoints']}")
    if linkage["unattached_reviews"]:
        gaps.append(f"unattached_reviews:{linkage['unattached_reviews']}")
    return {
        "opening_present": bool(snapshots) and bool(snapshots[0].get("is_opening")) and snapshots[0]["renderable"],
        "terminal_present": bool(terminal_snapshot is not None and terminal_snapshot["renderable"]),
        "snapshot_count": len(snapshots),
        "renderable_snapshot_count": sum(1 for s in snapshots if s["renderable"]),
        "linked_reviews": linkage["linked_reviews"], "unattached_reviews": linkage["unattached_reviews"],
        "unresolved_turn_endpoints": linkage["unresolved_turn_endpoints"],
        # Additive breakdown; unresolved_turn_endpoints keeps its meaning
        # (a boundary missing either end).
        "unresolved_turn_starts": linkage["unresolved_turn_starts"],
        "unresolved_turn_ends": linkage["unresolved_turn_ends"],
        "gaps": sorted(set(gaps)), "conflicts": sorted(set(conflicts)),
    }

def import_game(conn: sqlite3.Connection, archive: str | os.PathLike[str],
                cohort_id: str | None = None, game_id: str | None = None) -> str:
    root = Path(archive).resolve()
    log = root if root.is_file() else root / "match.ndjson"
    records = _records(log)
    metadata = _first(records, "metadata")
    lines = _driver(records)
    terminal = next((r for r in reversed(records) if r.get("type") == "terminal"), {})
    game_id = game_id or digest({"archive": str(log), "metadata": metadata})[:32]
    config = {k: metadata.get(k) for k in ("scenario", "seed", "faction0", "faction1", "gold", "first_player", "max_turns", "driver_command", "turn_format")}
    status = "complete" if terminal else "incomplete"
    with conn:
        # Transactionally rebuild this game's derived timeline (snapshots and
        # side_turns) from the source archive on every import. Requests,
        # batches, actions, evaluations, and reviews are never dropped here.
        conn.execute("DELETE FROM snapshots WHERE game_id=?", (game_id,))
        conn.execute("DELETE FROM side_turns WHERE game_id=?", (game_id,))
        conn.execute("""INSERT INTO games
          (game_id,cohort_id,lineage_root_id,seed,scenario,faction0,faction1,starting_gold,
          first_side,max_side_turns,started_at,ended_at,wall_ms,status,winner_side,
           termination_reason,source_commit,config_json,provenance_json,schema_version,
           artifact_path,coverage_json,importer_version)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(game_id) DO UPDATE SET status=excluded.status,
          winner_side=excluded.winner_side,termination_reason=excluded.termination_reason,
          importer_version=excluded.importer_version""",
          (game_id, cohort_id, game_id, metadata.get("seed"), metadata.get("scenario"),
           metadata.get("faction0"), metadata.get("faction1"), metadata.get("gold"),
           metadata.get("first_player"), metadata.get("max_turns"), metadata.get("started_at"),
           terminal.get("ended_at"), terminal.get("wall_ms"), status, terminal.get("winner"),
           terminal.get("reason"), metadata.get("source_commit"), json.dumps(config, sort_keys=True),
           json.dumps({"archive": str(log)}, sort_keys=True), SCHEMA_VERSION, str(root), "{}",
           IMPORTER_VERSION))
        snapshots, checkpoint_gaps = _build_snapshots(log, lines)
        _mark_terminal(snapshots, terminal)
        _insert_snapshots(conn, game_id, snapshots)
        linkage = _import_turns(conn, game_id, records, snapshots)
        coverage = _coverage_summary(snapshots, terminal, linkage)
        coverage["gaps"] = sorted(set(coverage["gaps"]) | set(checkpoint_gaps))
        conn.execute("UPDATE games SET coverage_json=? WHERE game_id=?",
                     (json.dumps(coverage, sort_keys=True), game_id))
        # Repair stale side_turn references left over from a prior import
        # whose derived side_turn IDs no longer exist, without deleting the
        # evidence rows themselves.
        for table in ("model_requests", "action_batches"):
            conn.execute(f"""UPDATE {table} SET side_turn_id=NULL
              WHERE game_id=? AND side_turn_id IS NOT NULL
              AND side_turn_id NOT IN (SELECT side_turn_id FROM side_turns WHERE game_id=?)""",
              (game_id, game_id))
        for side in (0, 1):
            is_model = metadata.get("llm_side") == side
            requested_model = next((metadata.get(key) for key in
                                    ("backend_requested_model", "requested_model", "model")
                                    if isinstance(metadata.get(key), str) and metadata.get(key)), None)
            reported_model = metadata.get("runtime_model") if isinstance(metadata.get("runtime_model"), str) else None
            conn.execute("""INSERT INTO game_players
              (game_id,side,player_kind,display_name,backend,model_requested,model_reported,
               reasoning_requested,reasoning_reported)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(game_id,side) DO UPDATE SET
              model_reported=excluded.model_reported,reasoning_reported=excluded.reasoning_reported""",
              (game_id, side, "model" if is_model else "algorithm",
               requested_model if is_model else "greedy",
               metadata.get("model_backend") if is_model else "greedy",
               requested_model if is_model else None,
               reported_model if is_model else None,
               metadata.get("requested_reasoning_effort") if is_model else None,
               metadata.get("runtime_reasoning_effort") if is_model else None))
        _import_requests(conn, game_id, records, linkage["record_links"])
        _import_actions(conn, game_id, records, linkage["record_links"])
        event_result = _import_events(conn, game_id, records, linkage["record_links"])
        coverage = json.loads(conn.execute(
            "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
        coverage["event_count"] = event_result["imported"]
        if event_result["malformed"]:
            coverage["events_status"] = "incomplete"
            coverage["gaps"] = sorted(set(coverage["gaps"]) |
                                      {f"event_malformed:{m}" for m in event_result["malformed"]})
        elif event_result["imported"] == 0:
            coverage["events_status"] = "no_event_evidence"
        else:
            coverage["events_status"] = "complete"
        usage_result = _apply_usage_calls(conn, game_id, usage_sidecar_path(root),
                                          conversation_id=metadata.get("conversation_id"))
        if usage_result["malformed"]:
            coverage["usage_status"] = "incomplete"
            coverage["gaps"] = sorted(set(coverage["gaps"]) |
                                      {f"usage_malformed:{m}" for m in usage_result["malformed"]})
        elif usage_result["imported"] == 0:
            coverage["usage_status"] = "no_usage_evidence"
        else:
            coverage["usage_status"] = "complete"
        if usage_result["conflicts"]:
            coverage["conflicts"] = sorted(set(coverage.get("conflicts", [])) |
                                           {f"usage_conflict:{k}:{v}" for k, vs in usage_result["conflicts"].items() for v in vs})
        conn.execute("UPDATE games SET coverage_json=? WHERE game_id=?",
                     (json.dumps(coverage, sort_keys=True), game_id))
    return game_id

def _number(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _record_revision(record: dict[str, Any]) -> int | None:
    return _number(record.get("state_revision"))


def _record_side_turn(record: dict[str, Any]) -> int | None:
    for key in ("side_turn", "side_turns"):
        value = _number(record.get(key))
        if value is not None:
            return value
    return None


def _matches_review(review: dict[str, Any], boundary: dict[str, Any],
                    start_revision: int | None, end_revision: int | None,
                    side_turn_id: str) -> str | None:
    """Return the proof used to attach a review, or None when it is ambiguous."""
    if review.get("side_turn_id") == side_turn_id:
        return "side_turn_id"
    review_side = _record_side_turn(review)
    boundary_side = _record_side_turn(boundary)
    if review_side is not None and boundary_side is not None and review_side == boundary_side:
        return "side_turn"
    review_revision = _record_revision(review)
    revisions = {_record_revision(boundary), start_revision, end_revision}
    if review_revision is not None and review_revision in revisions:
        return "state_revision"
    return None


def _snapshot_for_revision(snapshots: list[dict[str, Any]], revision: int | None) -> dict[str, Any] | None:
    """Find the one snapshot with an exact revision match.

    Deliberately has no "closest preceding" fallback: a resumed game can
    reuse revision numbers across branches, and a boundary without a provable
    endpoint must stay unknown rather than guess from ordinal position.
    """
    if revision is None:
        return None
    matches = [snapshot for snapshot in snapshots if snapshot["revision"] == revision]
    return matches[0] if len(matches) == 1 else None


def _endpoint_link_kind(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    found = [s for s in (before, after) if s is not None]
    if not found:
        return "unknown"
    return "evidence" if all(s["renderable"] for s in found) else "checkpoint_proof"


def _import_turns(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                  snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    boundaries = [r for r in records if r.get("type") == "turn_boundary" and r.get("accepted") is True]
    reviews = [r for r in records if r.get("type") == "handoff_review"]
    record_links: dict[str, str] = {}
    unresolved = 0
    unresolved_starts = 0
    unresolved_ends = 0
    linked_review_indexes: set[int] = set()
    closed_side_turn_ids: set[str] = set()
    for i, boundary in enumerate(boundaries, 1):
        side_turn_id = boundary.get("side_turn_id") or f"{game_id}:turn:{i}"
        end_revision = _record_revision(boundary)
        after = _snapshot_for_revision(snapshots, end_revision)
        start_revision = _number(boundary.get("start_revision"))
        before = _snapshot_for_revision(snapshots, start_revision)
        # A boundary without an exact-revision snapshot on both ends is
        # intentionally left with an unknown endpoint. Never infer one from
        # the ordinal position of a nearby partial snapshot.
        if before is None or after is None:
            unresolved += 1
        # Which END is missing is the useful distinction. An archive recorded
        # before the driver emitted start_revision has no proof of where a
        # turn began, yet every ending can still resolve. Reporting only the
        # combined count makes a fully recovered legacy timeline look as
        # broken as one with no endings at all.
        if before is None:
            unresolved_starts += 1
        if after is None:
            unresolved_ends += 1
        payload = {"sequence": i, "finish": boundary.get("authored_finish_kind"),
                   "start_revision": before["revision"] if before else None,
                   "end_revision": after["revision"] if after else None}
        candidates = []
        for review_index, review in enumerate(reviews):
            proof = _matches_review(review, boundary, payload["start_revision"], payload["end_revision"], side_turn_id)
            if proof is not None:
                candidates.append((review_index, review, proof))
        if len(candidates) == 1:
            review_index, review, proof = candidates[0]
            payload["handoff_review"] = review
            payload["handoff_review_link"] = proof
            linked_review_indexes.add(review_index)
        conn.execute("""INSERT INTO side_turns
          (side_turn_id,game_id,sequence,round_number,side,status,finish_kind,end_turn_emitted,
           start_revision,end_revision,start_snapshot_id,end_snapshot_id,endpoint_link_kind,
           metrics_json,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (side_turn_id, game_id, i, after["round"] if after else None,
           before["side"] if before is not None else (boundary.get("side") or 0),
           "terminal" if terminal_boundary(after) else "ended",
           boundary.get("authored_finish_kind"), int(bool(boundary.get("executed_finish_kind"))),
           payload["start_revision"], payload["end_revision"],
           before["snapshot_id"] if before else None, after["snapshot_id"] if after else None,
           _endpoint_link_kind(before, after),
           json.dumps({"handoff_review": payload["handoff_review"]}, sort_keys=True)
           if "handoff_review" in payload else "{}",
           digest(payload)))
        for key in ("side_turn_id", "side_turn"):
            value = boundary.get(key)
            if value is not None:
                record_links[f"{key}:{value}"] = side_turn_id
        for revision in (payload["start_revision"], payload["end_revision"]):
            if revision is not None:
                record_links[f"revision:{revision}"] = side_turn_id
        closed_side_turn_ids.add(side_turn_id)
    # A turn that opened but never reached an accepted boundary - a game that
    # failed, timed out or was interrupted mid-turn - still owns the work spent
    # inside it. Import it as an OPEN row so that usage has somewhere honest to
    # hang. An open turn is deliberately NOT a completed one: it contributes no
    # end revision, no end snapshot, and nothing that could become a replay
    # frame or inflate a completed-turn count.
    open_sequence = len(boundaries)
    for started in records:
        if started.get("type") != "side_turn_started":
            continue
        side_turn_id = started.get("side_turn_id")
        if not isinstance(side_turn_id, str) or side_turn_id in closed_side_turn_ids:
            continue
        open_sequence += 1
        start_revision = _number(started.get("start_revision"))
        before = _snapshot_for_revision(snapshots, start_revision)
        conn.execute("""INSERT INTO side_turns
          (side_turn_id,game_id,sequence,round_number,side,status,finish_kind,end_turn_emitted,
           start_revision,end_revision,start_snapshot_id,end_snapshot_id,endpoint_link_kind,
           metrics_json,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (side_turn_id, game_id, open_sequence, started.get("round"),
           started.get("side") if isinstance(started.get("side"), int) else 0,
           "open", None, 0,
           before["revision"] if before else start_revision, None,
           before["snapshot_id"] if before else None, None,
           _endpoint_link_kind(before, None),
           "{}", digest({"open_side_turn": side_turn_id})))
        record_links[f"side_turn_id:{side_turn_id}"] = side_turn_id
        closed_side_turn_ids.add(side_turn_id)

    return {"linked_reviews": len(linked_review_indexes),
            "unattached_reviews": len(reviews) - len(linked_review_indexes),
            "unresolved_turn_endpoints": unresolved,
            "unresolved_turn_starts": unresolved_starts,
            "unresolved_turn_ends": unresolved_ends,
            "record_links": record_links}


def terminal_boundary(snapshot: dict[str, Any] | None) -> bool:
    return bool(snapshot is not None and snapshot.get("boundary_kind") == "terminal")

def _side_turn_for_record(record: dict[str, Any], links: dict[str, str]) -> str | None:
    explicit = record.get("side_turn_id")
    if isinstance(explicit, str) and explicit in set(links.values()):
        return explicit
    for key in ("side_turn_id", "side_turn"):
        value = record.get(key)
        if value is not None and f"{key}:{value}" in links:
            return links[f"{key}:{value}"]
    revision = _record_revision(record)
    return links.get(f"revision:{revision}") if revision is not None else None


def _import_requests(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                     links: dict[str, str]) -> None:
    request_records = [r for r in records if r.get("type") == "model_request"]
    if not request_records:
        request_records = [r for r in records if r.get("type") == "model"]
    for index, record in enumerate(request_records):
        raw = record.get("raw_output") if isinstance(record.get("raw_output"), str) else None
        prompt = record.get("prompt") if isinstance(record.get("prompt"), str) else None
        req_id = record.get("request_id") or f"{game_id}:request:{index + 1}"
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        annotation = record.get("decision_annotation")
        if not isinstance(annotation, dict):
            annotation = {}
        annotation_status = annotation.get("status")
        if annotation_status not in {"valid", "missing", "invalid", "not_applicable"}:
            annotation_status = None
        decisions = annotation.get("decisions") if annotation_status == "valid" else []
        # Preserve the complete validated annotation object. Canonicalization
        # makes the compressed representation stable while retaining every
        # field supplied by the contract (including a null error).
        rationale_blob = (zlib.compress(canonical(annotation))
                          if annotation_status == "valid" and isinstance(decisions, list) else None)
        response_hash = (hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw is not None
                         else record.get("response_hash"))
        prompt_hash = (hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt is not None
                       else record.get("prompt_hash"))
        conn.execute("""INSERT INTO model_requests
          (request_id,game_id,side_turn_id,sequence,status,error_message,elapsed_ms,input_tokens,cached_input_tokens,output_tokens,
           reasoning_tokens,prompt_bytes,response_bytes,prompt_blob,response_blob,prompt_hash,
           response_hash,payload_codec,reasoning_blob,reasoning_kind,reasoning_source,
          annotation_status,state_revision,prompt_layout_version,fixed_prefix_sha256,fixed_prefix_bytes,raw_usage_json,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(request_id) DO NOTHING""",
          (req_id, game_id, _side_turn_for_record(record, links), record.get("sequence", index + 1), record.get("status", "completed"),
           record.get("error"), record.get("elapsed_ms"), usage.get("input_tokens"),
           usage.get("cached_input_tokens"), usage.get("output_tokens"),
           usage.get("reasoning_output_tokens"),
           record.get("prompt_bytes") or (len(prompt.encode()) if prompt else None),
           record.get("response_bytes") or (len(raw.encode()) if raw else None),
           zlib.compress(prompt.encode("utf-8")) if prompt is not None else None,
           zlib.compress(raw.encode("utf-8")) if raw is not None else None, prompt_hash,
           response_hash, "zlib" if prompt is not None or raw is not None or rationale_blob is not None else None,
           rationale_blob, "decision_annotation_v1" if rationale_blob is not None else None,
           "model_response" if rationale_blob is not None else None, annotation_status,
           _number(record.get("state_revision")), record.get("prompt_layout_version"),
           record.get("fixed_prefix_sha256"), _number(record.get("fixed_prefix_bytes")),
           json.dumps(usage, sort_keys=True),
           digest({"request_id": req_id, "record": record})))

def _import_actions(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                    links: dict[str, str]) -> None:
    sequence = 0
    for batch_index, record in enumerate(r for r in records if r.get("type") == "forwarded_orders"):
        orders = record.get("orders")
        if not isinstance(orders, list):
            continue
        batch_id = record.get("batch_id") or f"{game_id}:batch:{batch_index + 1}"
        request_id = record.get("request_id") if isinstance(record.get("request_id"), str) else None
        source = record.get("source") if isinstance(record.get("source"), str) else "model"
        conn.execute("""INSERT INTO action_batches
          (batch_id,game_id,side_turn_id,request_id,sequence,source,submitted_orders_json,status,
           before_revision,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(batch_id) DO NOTHING""",
          (batch_id, game_id, _side_turn_for_record(record, links), request_id, batch_index + 1, source,
           json.dumps(orders, sort_keys=True), "accepted_unknown",
           _number(record.get("before_revision", record.get("state_revision"))),
           digest({"batch_id": batch_id, "orders": orders, "request_id": request_id})))
        for index, order in enumerate(orders):
            sequence += 1
            action_id = f"{batch_id}:action:{index}"
            conn.execute("""INSERT INTO actions
              (action_id,game_id,batch_id,sequence,authored_order_index,source,action_type,
              action_json,status,request_id,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(action_id) DO NOTHING""",
              (action_id, game_id, batch_id, sequence, index, source, order.get("action"),
               json.dumps(order, sort_keys=True), "accepted_unknown", request_id,
               digest({"action_id": action_id, "order": order})))

def _import_events(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                   links: dict[str, str], *, strict: bool = False) -> dict[str, Any]:
    """Import every real executed driver event in original archive order.

    Reads only `type: driver` records whose `line.type == "events"` -- never
    proposed actions, preview/simulation payloads, or moves inferred from
    changed snapshots. `record_sequence` is this record's 1-based position in
    the source archive; `event_index` is 0-based within its `events` array,
    so `(game_id, record_sequence, event_index)` identifies exactly one
    logged occurrence even when its JSON payload is byte-identical to another
    at a different position -- a repeat is not a duplicate.

    Batch/side-turn linkage is attached only through explicit evidence: a
    `forwarded_orders` record names its own `batch_id` and (via `links`) its
    side turn by exact revision or ID match. Because the driver protocol is
    synchronous, the events printed for the model's own authored batch (its
    "llm" source) and any events it delegates within the same batch
    ("delegated_greedy") are the only ones attached to that batch_id -- an
    opponent's own turn (source "greedy") or any unrecognized source is never
    guessed onto a nearby batch. `event_source` prefers the event's own
    `source` field over the enclosing envelope's, in case a future driver
    mixes sources within one record; today they are always equal.

    Malformed records (a non-list `events` field, or an event missing a
    string `kind`) are never silently dropped: their source position is
    recorded in the returned `malformed` list. With `strict=True` (used by
    `backfill-events`, whose only job is this table) any malformed record
    raises so the whole transaction rolls back and prior rows are untouched;
    the default (used by full game import, which owns much more than events)
    instead imports every well-formed event and reports the game's event
    coverage as incomplete.
    """
    conn.execute("DELETE FROM events WHERE game_id=?", (game_id,))
    sequence = 0
    malformed: list[str] = []
    current_batch: dict[str, Any] | None = None
    for record_index, record in enumerate(records, 1):
        rtype = record.get("type")
        if rtype == "forwarded_orders":
            batch_id = record.get("batch_id")
            current_batch = {"batch_id": batch_id if isinstance(batch_id, str) else None,
                             "side_turn_id": _side_turn_for_record(record, links)}
            continue
        if rtype != "driver":
            continue
        line = record.get("line")
        if not isinstance(line, dict) or line.get("type") != "events":
            continue
        raw_events = line.get("events")
        if not isinstance(raw_events, list):
            malformed.append(f"record:{record_index}:events_not_list")
            continue
        envelope_source = line.get("source") if isinstance(line.get("source"), str) else None
        for event_index, event in enumerate(raw_events):
            if not isinstance(event, dict) or not isinstance(event.get("kind"), str):
                malformed.append(f"record:{record_index}:event:{event_index}:malformed_event")
                continue
            sequence += 1
            event_source = event.get("source") if isinstance(event.get("source"), str) else envelope_source
            batch_id = side_turn_id = None
            if envelope_source in ("llm", "delegated_greedy") and current_batch is not None:
                batch_id = current_batch["batch_id"]
                side_turn_id = current_batch["side_turn_id"]
            conn.execute("""INSERT INTO events
              (game_id,event_sequence,side_turn_id,batch_id,kind,source,event_json,
               record_sequence,event_index,record_hash)
              VALUES(?,?,?,?,?,?,?,?,?,?)""",
              (game_id, sequence, side_turn_id, batch_id, event["kind"], event_source,
               json.dumps(event, sort_keys=True), record_index, event_index,
               digest({"game_id": game_id, "record_sequence": record_index,
                       "event_index": event_index, "event": event})))
    if malformed and strict:
        raise ValueError(f"malformed event record(s) in {game_id}: {malformed}")
    return {"imported": sequence, "malformed": malformed}


_MODEL_CALL_COLUMNS = (
    "game_id", "call_id", "request_id", "retry_of_call_id", "provider", "transport",
    "native_thread_id", "provider_response_id", "requested_model", "reported_model",
    "requested_affinity", "prompt_layout_version", "prompt_layout_source",
    "requested_reasoning_effort", "reported_reasoning_effort", "output_limit",
    "status", "finish_reason", "error_code", "started_at", "ended_at", "elapsed_ms",
    "input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens",
    "reasoning_tokens", "total_tokens", "usage_source", "usage_schema_version",
)


def usage_sidecar_path(archive: str | os.PathLike[str]) -> Path:
    """The conventional match-owned usage sidecar path for an archive.

    `tools/fireworks_backend.py` (and any other maintained adapter) appends
    durable per-call lifecycle records here; the importer reads it read-only.
    Sibling to the archive's own directory -- never inferred from cwd or a
    launcher-specific location, so a relocated archive copy keeps its usage
    evidence alongside it.
    """
    root = Path(archive).resolve()
    directory = root if root.is_dir() else root.parent
    return directory / "usage.ndjson"


def _read_usage_sidecar(path: Path) -> tuple[list[ModelCall], list[str]]:
    """Read raw usage-sidecar lines into ModelCall records, reporting malformed lines.

    A malformed line (invalid JSON, missing game_id/call_id, or a field the
    dataclass rejects) is never silently dropped: it is reported by exact
    source position, and well-formed lines around it still import.
    """
    records: list[ModelCall] = []
    malformed: list[str] = []
    if not path.is_file():
        return records, malformed
    call_fields = set(ModelCall.__dataclass_fields__)
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(f"line:{line_number}:invalid_json")
            continue
        if not isinstance(row, dict) or not row.get("game_id") or not row.get("call_id"):
            malformed.append(f"line:{line_number}:missing_identity")
            continue
        fields = {key: value for key, value in row.items() if key in call_fields and key != "normalization_gaps"}
        gaps = row.get("normalization_gaps") or []
        try:
            call = ModelCall(**fields)
        except TypeError as exc:
            malformed.append(f"line:{line_number}:{exc}")
            continue
        call.normalization_gaps = list(gaps) if isinstance(gaps, list) else []
        records.append(call)
    return records, malformed


def _apply_usage_calls(conn: sqlite3.Connection, game_id: str,
                       sidecar_path: str | os.PathLike[str],
                       conversation_id: str | None = None) -> dict[str, Any]:
    """Rebuild this game's model_calls rows from its usage sidecar, without its own transaction.

    Called both standalone (wrapped in `with conn:` by `import_usage_sidecar`)
    and from within `import_game`'s single transaction. Deterministically
    replaces the game's prior model_calls rows -- repeated lifecycle records
    for one call_id UPSERT via `tools.model_usage.dedupe_calls`, so
    reimporting an unchanged sidecar, or one with duplicate dispatch/final
    notifications, produces identical rows rather than extra ones.
    """
    raw_records, malformed = _read_usage_sidecar(Path(sidecar_path))
    # An adapter cannot know the catalog game_id: it is derived here, at import,
    # long after the call was paid for. What the adapter does know is the match's
    # conversation_id, which the client publishes in the request context. Accept
    # either identity and rebind to the catalog id, so a sidecar written during
    # play is usable while a sidecar belonging to a DIFFERENT match is still
    # refused - the cross-game protection is the point, the binding key was not.
    accepted = {game_id} | ({conversation_id} if conversation_id else set())
    for record in raw_records:
        if record.game_id not in accepted:
            malformed.append(f"call:{record.call_id}:wrong_game:{record.game_id}")
    raw_records = [replace(r, game_id=game_id) for r in raw_records if r.game_id in accepted]
    deduped, conflicts = dedupe_calls(raw_records)
    request_layouts = {row[0]: row[1] for row in conn.execute(
        "SELECT request_id,prompt_layout_version FROM model_requests WHERE game_id=?", (game_id,))}
    for index, call in enumerate(deduped):
        if call.prompt_layout_version is None and call.request_id in request_layouts:
            layout = request_layouts[call.request_id]
            if layout is not None:
                deduped[index] = replace(call, prompt_layout_version=layout,
                                         prompt_layout_source="linked_harness_request")
    conn.execute("DELETE FROM model_calls WHERE game_id=?", (game_id,))
    for call in deduped:
        row = call.to_row()
        conn.execute(f"""INSERT INTO model_calls
          ({",".join(_MODEL_CALL_COLUMNS)},raw_usage_json,source_ref,source_hash,
           linkage_evidence,normalization_gaps_json,record_hash)
          VALUES({",".join("?" * len(_MODEL_CALL_COLUMNS))},?,?,?,?,?,?)""",
          tuple(row[k] for k in _MODEL_CALL_COLUMNS) + (
              json.dumps(call.raw_usage_json, sort_keys=True, default=str)
              if call.raw_usage_json is not None else None,
              call.source_ref, call.source_hash, call.linkage_evidence,
              json.dumps(sorted(set(call.normalization_gaps)), sort_keys=True),
              digest({"game_id": call.game_id, "call_id": call.call_id, "row": row})))
    return {"imported": len(deduped), "malformed": sorted(set(malformed)),
            "conflicts": {f"{g}:{c}": v for (g, c), v in conflicts.items()}}


def import_usage_sidecar(conn: sqlite3.Connection, game_id: str,
                         sidecar_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Standalone entry point: import one game's usage sidecar in its own transaction."""
    with conn:
        return _apply_usage_calls(conn, game_id, sidecar_path)


def _turn_links_from_db(conn: sqlite3.Connection, game_id: str) -> dict[str, str]:
    """Rebuild the revision->side_turn_id map from already-imported side_turns.

    Used by `backfill-events`, which changes only derived event rows and must
    not recompute or touch `snapshots`/`side_turns` itself.
    """
    links: dict[str, str] = {}
    for side_turn_id, start_revision, end_revision in conn.execute(
        "SELECT side_turn_id,start_revision,end_revision FROM side_turns WHERE game_id=?", (game_id,)):
        for revision in (start_revision, end_revision):
            if revision is not None:
                links[f"revision:{revision}"] = side_turn_id
    return links


def backfill_events(conn: sqlite3.Connection, game_ids: Iterable[str] = (),
                    all_games: bool = False) -> dict[str, Any]:
    """Import event rows for already-catalogued games, one transaction each.

    Resolves each game's source archive from its stored `artifact_path`,
    preserving the catalog's own game ID rather than importing a relocated
    path as a second game. A missing/unreadable archive or a malformed event
    record fails only that game (its prior event rows, if any, are left
    exactly as they were); other selected games are unaffected. Zero observed
    events for an available archive is reported honestly and is never treated
    as evidence of a fully captured execution.
    """
    ids = ([row[0] for row in conn.execute("SELECT game_id FROM games ORDER BY game_id")]
          if all_games else list(dict.fromkeys(game_ids)))
    imported: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    total_events = 0
    for game_id in ids:
        row = conn.execute("SELECT artifact_path FROM games WHERE game_id=?", (game_id,)).fetchone()
        if row is None:
            unavailable.append({"game_id": game_id, "reason": "unknown_game_id"})
            continue
        root = Path(row[0])
        log = root if root.is_file() else root / "match.ndjson"
        if not log.is_file():
            unavailable.append({"game_id": game_id, "reason": f"archive_missing:{log}"})
            continue
        try:
            records = _records(log)
        except (OSError, json.JSONDecodeError) as exc:
            unavailable.append({"game_id": game_id, "reason": f"archive_unreadable:{exc}"})
            continue
        links = _turn_links_from_db(conn, game_id)
        try:
            with conn:
                result = _import_events(conn, game_id, records, links, strict=True)
        except ValueError as exc:
            failed.append({"game_id": game_id, "reason": str(exc)})
            continue
        imported.append({"game_id": game_id, "event_count": result["imported"],
                         "no_event_evidence": result["imported"] == 0})
        total_events += result["imported"]
    return {"attempted": len(ids), "imported": imported, "unavailable": unavailable,
            "failed": failed, "total_events": total_events}


def summarize_game(conn: sqlite3.Connection, game_id: str) -> dict[str, Any]:
    cur = conn.execute("SELECT * FROM game_summary WHERE game_id=?", (game_id,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(game_id)
    return dict(zip([d[0] for d in cur.description], row))

def list_side_turns(conn: sqlite3.Connection, game_id: str) -> list[dict[str, Any]]:
    cur = conn.execute("""SELECT side_turn_id,sequence,round_number,side,status,finish_kind,
                          start_revision,end_revision,start_snapshot_id,end_snapshot_id,
                          endpoint_link_kind FROM side_turns
                          WHERE game_id=? ORDER BY sequence""", (game_id,))
    return [dict(zip([d[0] for d in cur.description], row)) for row in cur]

def _load_calls(conn: sqlite3.Connection, game_id: str) -> list[ModelCall]:
    columns = list(_MODEL_CALL_COLUMNS) + ["raw_usage_json", "source_ref", "source_hash",
                                           "linkage_evidence", "normalization_gaps_json"]
    cur = conn.execute(f"SELECT {','.join(columns)} FROM model_calls WHERE game_id=? ORDER BY rowid",
                       (game_id,))
    calls = []
    for row in cur:
        values = dict(zip(columns, row))
        gaps = json.loads(values.pop("normalization_gaps_json") or "[]")
        raw_usage = values.pop("raw_usage_json")
        values["raw_usage_json"] = json.loads(raw_usage) if raw_usage is not None else None
        call = ModelCall(**values)
        call.normalization_gaps = gaps
        calls.append(call)
    return calls


def _usage_by_turn(conn: sqlite3.Connection, game_id: str,
                   calls: list[Any]) -> dict[str, Any]:
    """Group measured usage by side turn, keeping open turns visible.

    A call reaches a turn only through its request's proven side-turn link;
    there is no second, independently maintained turn link per call. A call
    with no proven request, or a request with no proven turn, is reported as
    unassigned rather than being attached to a nearby turn - it still counts in
    the game total, and it lowers attribution coverage, which is the honest
    signal that some spending could not be placed.

    Completed and open turns are reported separately. Averaging an interrupted
    turn's usage into completed-turn figures would quietly distort both.
    """
    turn_of_request = {row[0]: row[1] for row in conn.execute(
        "SELECT request_id, side_turn_id FROM model_requests "
        "WHERE game_id=? AND side_turn_id IS NOT NULL", (game_id,))}
    turn_status = {row[0]: row[1] for row in conn.execute(
        "SELECT side_turn_id, status FROM side_turns WHERE game_id=?", (game_id,))}
    grouped: dict[str, list[Any]] = {}
    unassigned: list[Any] = []
    for call in calls:
        side_turn_id = turn_of_request.get(call.request_id) if call.request_id else None
        (grouped.setdefault(side_turn_id, []) if side_turn_id else unassigned).append(call)
    turns = []
    for side_turn_id, members in sorted(grouped.items()):
        turns.append({"side_turn_id": side_turn_id,
                      "status": turn_status.get(side_turn_id, "unknown"),
                      "call_ids": sorted(c.call_id for c in members),
                      "detail": aggregate_calls(members)})
    linked = sum(len(m) for m in grouped.values())
    return {"game_id": game_id, "group_by": "turn",
            "completed_turns": [t for t in turns if t["status"] not in ("open", "unknown")],
            "open_turns": [t for t in turns if t["status"] == "open"],
            "unassigned": {"call_ids": sorted(c.call_id for c in unassigned),
                           "detail": aggregate_calls(unassigned)},
            "attribution_coverage": {
                "linked_calls": linked, "unassigned_calls": len(unassigned),
                "total_calls": len(calls),
                # Deliberately None rather than 1.0 for a game with no calls:
                # no evidence is not full coverage.
                "linked_fraction": (linked / len(calls)) if calls else None}}


def query_usage(conn: sqlite3.Connection, game_id: str, group_by: str = "game") -> dict[str, Any]:
    """Query measured model-call usage for one game, grouped as the contract requires.

    `group_by="call"` lists every detailed row with per-field coverage;
    `"request"` groups detailed calls under their harness request and
    surfaces any historical `request_aggregate` (from `model_requests`'s own
    usage columns) purely for reconciliation -- it is never summed into the
    detailed total; `"game"` reports one measured aggregate across all
    calls plus which requests have only an aggregate-only historical total
    and how many calls carry no request link. Reports do not compute a
    combined total when detail and aggregate both exist for a request; that
    would double count or hide a genuine disagreement.
    """
    if group_by not in ("call", "request", "game", "turn"):
        raise ValueError(f"unknown group_by: {group_by!r}")
    if conn.execute("SELECT 1 FROM games WHERE game_id=?", (game_id,)).fetchone() is None:
        raise KeyError(game_id)
    calls = _load_calls(conn, game_id)
    if group_by == "turn":
        return _usage_by_turn(conn, game_id, calls)
    request_legacy: dict[str, dict[str, Any]] = {}
    for request_id, input_tokens, cached, output, reasoning in conn.execute(
        """SELECT request_id,input_tokens,cached_input_tokens,output_tokens,reasoning_tokens
           FROM model_requests WHERE game_id=?""", (game_id,)):
        legacy_usage = {"input_tokens": input_tokens, "cached_input_tokens": cached,
                        "output_tokens": output, "reasoning_tokens": reasoning}
        if any(value is not None for value in legacy_usage.values()):
            request_legacy[request_id] = request_aggregate_from_legacy(legacy_usage)

    if group_by == "call":
        return {"game_id": game_id, "group_by": "call",
                "calls": [call.to_row() for call in calls],
                "coverage": aggregate_calls(calls)}

    by_request: dict[str | None, list[ModelCall]] = {}
    for call in calls:
        by_request.setdefault(call.request_id, []).append(call)

    if group_by == "request":
        requests: list[dict[str, Any]] = []
        for request_id in sorted(by_request, key=lambda value: (value is None, value)):
            group = by_request[request_id]
            entry: dict[str, Any] = {"request_id": request_id, "detail": aggregate_calls(group),
                                     "call_ids": [call.call_id for call in group]}
            if request_id is not None and request_id in request_legacy:
                entry["request_aggregate"] = request_legacy[request_id]
                entry["note"] = "request_aggregate is reconciliation-only, never added to detail"
            requests.append(entry)
        for request_id, aggregate in request_legacy.items():
            if request_id not in by_request:
                requests.append({"request_id": request_id, "detail": None,
                                 "request_aggregate": aggregate,
                                 "note": "no detailed calls for this request; historical aggregate only"})
        return {"game_id": game_id, "group_by": "request", "requests": requests}

    aggregate_only_request_ids = sorted(
        rid for rid in request_legacy if rid not in by_request or not by_request.get(rid))
    return {"game_id": game_id, "group_by": "game", "measured": aggregate_calls(calls),
            "call_count": len(calls),
            "aggregate_only_request_ids": aggregate_only_request_ids,
            "unassigned_calls": len(by_request.get(None, []))}


def _format_usage_report(value: dict[str, Any]) -> str:
    """Human-readable usage output built from the same query helper as --json.

    Labels every partial total explicitly -- a field missing from even one
    call in its group is never printed as if it were a complete measurement.
    """
    def field_line(field: str, info: dict[str, Any]) -> str:
        label = "measured" if info["fully_measured"] else "PARTIAL"
        return (f"  {field}: sum={info['sum']} ({label}; "
                f"{info['known_calls']}/{info['known_calls'] + info['unknown_calls']} calls known)")

    lines = [f"game_id: {value['game_id']} (group_by={value['group_by']})"]
    if value["group_by"] == "call":
        lines.append(f"calls: {len(value['calls'])}")
        for call in value["calls"]:
            lines.append(f"  {call['call_id']}: status={call['status']} "
                        f"input={call['input_tokens']} cached={call['cached_input_tokens']} "
                        f"output={call['output_tokens']} reasoning={call['reasoning_tokens']} "
                        f"total={call['total_tokens']} finish_reason={call['finish_reason']}")
        lines.append("coverage:")
        for field in TOKEN_FIELDS:
            lines.append(field_line(field, value["coverage"][field]))
    elif value["group_by"] == "request":
        for entry in value["requests"]:
            lines.append(f"request {entry['request_id']}:")
            if entry["detail"] is not None:
                for field in TOKEN_FIELDS:
                    lines.append(field_line(field, entry["detail"][field]))
            if "request_aggregate" in entry:
                lines.append(f"  request_aggregate (reconciliation only): "
                            f"{entry['request_aggregate']['tokens']}")
                lines.append(f"  note: {entry['note']}")
    else:
        for field in TOKEN_FIELDS:
            lines.append(field_line(field, value["measured"][field]))
        lines.append(f"call_count: {value['call_count']}")
        if value["aggregate_only_request_ids"]:
            lines.append(f"aggregate_only requests (no call detail): {value['aggregate_only_request_ids']}")
        if value["unassigned_calls"]:
            lines.append(f"unassigned calls (no request_id): {value['unassigned_calls']}")
    return "\n".join(lines)


def backup_history(source: str, destination: str) -> None:
    src = open_history(source); dst = sqlite3.connect(destination)
    with dst: src.backup(dst)
    dst.close(); src.close()

def verify_history(path: str | os.PathLike[str]) -> dict[str, Any]:
    conn = open_history(path, read_only=True)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    counts = {}
    for table in ("games", "game_players", "side_turns", "snapshots", "events", "model_requests",
                  "model_calls", "action_batches", "actions", "evaluation_runs", "decision_evaluations"):
        counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    dangling_event_side_turns = conn.execute("""SELECT count(*) FROM events e
      WHERE e.side_turn_id IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM side_turns st WHERE st.side_turn_id=e.side_turn_id)""").fetchone()[0]
    dangling_event_batches = conn.execute("""SELECT count(*) FROM events e
      WHERE e.batch_id IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM action_batches b WHERE b.batch_id=e.batch_id)""").fetchone()[0]
    dangling_call_requests = conn.execute("""SELECT count(*) FROM model_calls c
      WHERE c.request_id IS NOT NULL
      AND NOT EXISTS(SELECT 1 FROM model_requests r WHERE r.request_id=c.request_id AND r.game_id=c.game_id)""").fetchone()[0]
    cross_game_calls = conn.execute("""SELECT count(*) FROM model_calls c
      WHERE c.request_id IS NOT NULL
      AND EXISTS(SELECT 1 FROM model_requests r WHERE r.request_id=c.request_id AND r.game_id<>c.game_id)""").fetchone()[0]
    conn.close()
    return {"integrity": integrity, "foreign_key_errors": len(foreign_keys), "counts": counts,
            "dangling_event_side_turn_links": dangling_event_side_turns,
            "dangling_event_batch_links": dangling_event_batches,
            "dangling_call_request_links": dangling_call_requests,
            "cross_game_call_links": cross_game_calls}

TABLES = ("games", "game_players", "side_turns", "snapshots", "events", "model_requests",
          "model_calls", "action_batches", "actions", "evaluation_runs", "decision_evaluations")


def inventory_history(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return a compact inventory suitable for a deletion dry run."""
    cohorts = [dict(zip(("cohort_id", "games"), row)) for row in conn.execute(
        "SELECT cohort_id,count(*) FROM games GROUP BY cohort_id ORDER BY cohort_id")]
    return {"counts": {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                        for table in TABLES}, "cohorts": cohorts}


def delete_history(conn: sqlite3.Connection, cohort_id: str | None = None,
                   game_ids: Iterable[str] = (), reset: bool = False,
                   compact: bool = False) -> dict[str, Any]:
    """Delete an exact selection and optionally compact the SQLite file."""
    ids = tuple(dict.fromkeys(game_ids))
    if reset and (cohort_id or ids):
        raise ValueError("choose exactly one of --reset, --cohort, or --game-id")
    if not reset and not cohort_id and not ids:
        raise ValueError("a deletion selector is required")
    if reset:
        selected = [row[0] for row in conn.execute("SELECT game_id FROM games")]
    elif cohort_id:
        selected = [row[0] for row in conn.execute(
            "SELECT game_id FROM games WHERE cohort_id=?", (cohort_id,))]
    else:
        selected = list(ids)
        existing = {row[0] for row in conn.execute(
            "SELECT game_id FROM games WHERE game_id IN (%s)" % ",".join("?" * len(selected)), selected)} if selected else set()
        missing = sorted(set(selected) - existing)
        if missing:
            raise KeyError(f"unknown game IDs: {missing}")
    selected = tuple(selected)
    placeholders = ",".join("?" * len(selected))
    before = inventory_history(conn)
    with conn:
        request_ids = [row[0] for row in conn.execute(
            f"SELECT request_id FROM model_requests WHERE game_id IN ({placeholders})", selected)] if selected else []
        eval_ids = [row[0] for row in conn.execute(
            "SELECT DISTINCT evaluation_run_id FROM decision_evaluations WHERE request_id IN (%s) OR preferred_request_id IN (%s)"
            % (",".join("?" * len(request_ids)), ",".join("?" * len(request_ids))), request_ids + request_ids)] if request_ids else []
        if request_ids:
            conn.execute("DELETE FROM decision_evaluations WHERE request_id IN (%s) OR preferred_request_id IN (%s)" %
                         (placeholders_for(request_ids), placeholders_for(request_ids)), request_ids + request_ids)
        if selected:
            for table in ("events", "model_calls", "actions", "action_batches", "model_requests",
                          "side_turns", "snapshots", "game_players", "games"):
                conn.execute(f"DELETE FROM {table} WHERE game_id IN ({placeholders})", selected)
        for run_id in eval_ids:
            if conn.execute("SELECT 1 FROM decision_evaluations WHERE evaluation_run_id=? LIMIT 1", (run_id,)).fetchone() is None:
                conn.execute("DELETE FROM evaluation_runs WHERE evaluation_run_id=?", (run_id,))
    if compact:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    after = inventory_history(conn)
    return {"deleted_game_ids": list(selected), "evaluation_runs_considered": eval_ids,
            "before": before, "after": after, "compacted": compact}


def placeholders_for(values: Iterable[Any]) -> str:
    return ",".join("?" * len(tuple(values)))

def import_review(conn: sqlite3.Connection, path: str | os.PathLike[str],
                  evaluation_run_id: str, evaluator_version: str = "review_v1") -> int:
    """Import explicit review JSONL without changing immutable game records."""
    rows = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    with conn:
        conn.execute("""INSERT INTO evaluation_runs
          (evaluation_run_id,evaluator_name,evaluator_version,config_json,status)
          VALUES(?, 'review', ?, '{}', 'complete') ON CONFLICT(evaluation_run_id) DO NOTHING""",
          (evaluation_run_id, evaluator_version))
        for row in rows:
            conn.execute("""INSERT INTO decision_evaluations
              (evaluation_run_id,request_id,verdict,reason_codes_json,metrics_json,evidence_json,
               preferred_request_id) VALUES(?,?,?,?,?,?,?)
              ON CONFLICT(evaluation_run_id,request_id) DO UPDATE SET verdict=excluded.verdict,
              reason_codes_json=excluded.reason_codes_json,metrics_json=excluded.metrics_json,
              evidence_json=excluded.evidence_json,preferred_request_id=excluded.preferred_request_id""",
              (evaluation_run_id, row["request_id"], row["verdict"],
               json.dumps(row.get("reason_codes", []), sort_keys=True),
               json.dumps(row.get("metrics", {}), sort_keys=True),
               json.dumps(row.get("evidence", {}), sort_keys=True),
               row.get("preferred_request_id")))
    return len(rows)

def evaluate_payload_coverage(conn: sqlite3.Connection, cohort_id: str | None = None) -> str:
    """Record whether indexed model requests retain both prompt and response payloads.

    This is an evidence inventory, not a quality or strategy evaluation.
    """
    run_id = f"payload_coverage_v1:{int(__import__('time').time())}"
    with conn:
        conn.execute("""INSERT INTO evaluation_runs
          (evaluation_run_id,evaluator_name,evaluator_version,config_json,status)
          VALUES(?, 'payload_coverage', '1', ?, 'running')""",
          (run_id, json.dumps({"cohort": cohort_id}, sort_keys=True)))
        query = "SELECT r.request_id,r.response_blob,r.prompt_blob FROM model_requests r"
        params: tuple[Any, ...] = ()
        if cohort_id is not None:
            query += " JOIN games g ON g.game_id=r.game_id WHERE g.cohort_id=?"
            params = (cohort_id,)
        for request_id, response, prompt in conn.execute(query, params):
            covered = prompt is not None and response is not None
            conn.execute("""INSERT INTO decision_evaluations
              (evaluation_run_id,request_id,verdict,reason_codes_json,metrics_json,evidence_json)
              VALUES(?,?,?,?,?,?)""",
              (run_id, request_id, "coverage" if covered else "unknown",
               json.dumps(["payloads_present" if covered else "missing_payload"]),
               "{}", json.dumps({"evaluator": "payload_coverage_v1"})))
        conn.execute("""UPDATE evaluation_runs SET completed_at=datetime('now'),status='complete'
                      WHERE evaluation_run_id=?""", (run_id,))
    return run_id

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import"); imp.add_argument("--db", required=True); imp.add_argument("archive"); imp.add_argument("--cohort")
    review = sub.add_parser("review"); review.add_argument("--db", required=True); review.add_argument("--run-id", required=True); review.add_argument("path")
    coverage = sub.add_parser("payload-coverage"); coverage.add_argument("--db", required=True); coverage.add_argument("--cohort")
    show = sub.add_parser("game"); show.add_argument("--db", required=True); show.add_argument("game_id")
    turns = sub.add_parser("turns"); turns.add_argument("--db", required=True); turns.add_argument("game_id")
    usage = sub.add_parser("usage"); usage.add_argument("--db", required=True); usage.add_argument("game_id")
    usage.add_argument("--group-by", choices=("call", "request", "game", "turn"), default="game")
    usage.add_argument("--json", action="store_true")
    inv = sub.add_parser("inventory"); inv.add_argument("--db", required=True)
    backfill = sub.add_parser("backfill-events"); backfill.add_argument("--db", required=True)
    backfill_selector = backfill.add_mutually_exclusive_group(required=True)
    backfill_selector.add_argument("--game-id", action="append")
    backfill_selector.add_argument("--all", action="store_true")
    delete = sub.add_parser("delete"); delete.add_argument("--db", required=True)
    selector = delete.add_mutually_exclusive_group(required=True)
    selector.add_argument("--cohort"); selector.add_argument("--game-id", action="append"); selector.add_argument("--reset", action="store_true")
    delete.add_argument("--compact", action="store_true")
    backfill_usage_parser = sub.add_parser("backfill-usage")
    backfill_usage_parser.add_argument("--db", required=True)
    backfill_usage_parser.add_argument("--manifest", required=True)
    usage_selector = backfill_usage_parser.add_mutually_exclusive_group(required=True)
    usage_selector.add_argument("--game-id", action="append")
    usage_selector.add_argument("--all", action="store_true")
    backfill_usage_parser.add_argument("--execute", action="store_true",
        help="actually write model_calls rows; without this flag, report what would be imported")
    compare_usage_parser = sub.add_parser("compare-usage")
    compare_usage_parser.add_argument("--db", required=True)
    compare_usage_parser.add_argument("--game-id", action="append", required=True)
    compare_usage_parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    read_commands = {"inventory", "game", "turns", "usage", "compare-usage"}
    conn = open_history(args.db, read_only=args.command in read_commands)
    exit_code = 0
    if args.command == "import": value = import_game(conn, args.archive, args.cohort)
    elif args.command == "review": value = import_review(conn, args.path, args.run_id)
    elif args.command == "payload-coverage": value = evaluate_payload_coverage(conn, args.cohort)
    elif args.command == "inventory": value = inventory_history(conn)
    elif args.command == "delete": value = delete_history(conn, args.cohort, args.game_id or [], args.reset, args.compact)
    elif args.command == "game": value = summarize_game(conn, args.game_id)
    elif args.command == "usage":
        value = query_usage(conn, args.game_id, args.group_by)
        if not args.json:
            print(_format_usage_report(value))
            conn.close(); return exit_code
    elif args.command == "backfill-events":
        value = backfill_events(conn, args.game_id or [], args.all)
        if value["unavailable"] or value["failed"]:
            exit_code = 1
    elif args.command == "backfill-usage":
        from .usage_backfill import backfill_usage
        value = backfill_usage(conn, args.game_id or [], args.manifest, args.all, args.execute)
        if value["unavailable"] or value["failed"]:
            exit_code = 1
    elif args.command == "compare-usage":
        from .usage_backfill import compare_usage, _format_compare_report
        value = compare_usage(conn, args.game_id)
        if not args.json:
            print(_format_compare_report(value))
            conn.close(); return exit_code
    else: value = list_side_turns(conn, args.game_id)
    print(json.dumps(value, sort_keys=True, default=lambda value: value.hex() if isinstance(value, bytes) else value))
    conn.close(); return exit_code

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
