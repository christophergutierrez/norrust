"""Import Norrust match archives into a small, rebuildable SQLite catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import zlib
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1
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
CREATE TABLE IF NOT EXISTS model_requests (
 request_id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(game_id), side_turn_id TEXT,
 sequence INTEGER, logical_call_id TEXT, retry_of_request_id TEXT, purpose TEXT, status TEXT,
 error_code TEXT, error_message TEXT, native_session_id TEXT, native_request_id TEXT,
 started_at TEXT, ended_at TEXT, elapsed_ms INTEGER, input_tokens INTEGER,
 cached_input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER, usage_source TEXT,
 prompt_bytes INTEGER, response_bytes INTEGER, prompt_blob BLOB, response_blob BLOB,
 prompt_hash TEXT, response_hash TEXT, payload_codec TEXT, context_complete INTEGER,
 reasoning_blob BLOB, reasoning_kind TEXT, reasoning_source TEXT,
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
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE model_requests ADD COLUMN {name} {definition}")
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

def import_game(conn: sqlite3.Connection, archive: str | os.PathLike[str],
                cohort_id: str | None = None, game_id: str | None = None) -> str:
    root = Path(archive).resolve()
    log = root if root.is_file() else root / "match.ndjson"
    records = _records(log)
    metadata = _first(records, "metadata")
    lines = _driver(records)
    states = [line for line in lines if line.get("type") == "state"]
    terminal = next((r for r in reversed(records) if r.get("type") == "terminal"), {})
    game_id = game_id or digest({"archive": str(log), "metadata": metadata})[:32]
    config = {k: metadata.get(k) for k in ("scenario", "seed", "faction0", "faction1", "gold", "first_player", "max_turns", "driver_command", "turn_format")}
    status = "complete" if terminal else "incomplete"
    with conn:
        conn.execute("""INSERT INTO games
          (game_id,cohort_id,lineage_root_id,seed,scenario,faction0,faction1,starting_gold,
          first_side,max_side_turns,started_at,ended_at,wall_ms,status,winner_side,
           termination_reason,source_commit,config_json,provenance_json,schema_version,
           artifact_path,coverage_json)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(game_id) DO UPDATE SET status=excluded.status,
          winner_side=excluded.winner_side,termination_reason=excluded.termination_reason""",
          (game_id, cohort_id, game_id, metadata.get("seed"), metadata.get("scenario"),
           metadata.get("faction0"), metadata.get("faction1"), metadata.get("gold"),
           metadata.get("first_player"), metadata.get("max_turns"), metadata.get("started_at"),
           terminal.get("ended_at"), terminal.get("wall_ms"), status, terminal.get("winner"),
           terminal.get("reason"), metadata.get("source_commit"), json.dumps(config, sort_keys=True),
           json.dumps({"archive": str(log)}, sort_keys=True), SCHEMA_VERSION, str(root), "{}"))
        linkage = _import_turns(conn, game_id, records, lines, states, terminal)
        conn.execute("UPDATE games SET coverage_json=? WHERE game_id=?",
                     (json.dumps({"state_records": len(states), **linkage}, sort_keys=True), game_id))
        for side in (0, 1):
            is_model = metadata.get("llm_side") == side
            conn.execute("""INSERT INTO game_players
              (game_id,side,player_kind,display_name,backend,model_requested,model_reported,
               reasoning_requested,reasoning_reported)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(game_id,side) DO UPDATE SET
              model_reported=excluded.model_reported,reasoning_reported=excluded.reasoning_reported""",
              (game_id, side, "model" if is_model else "algorithm",
               metadata.get("model") if is_model else "greedy",
               metadata.get("model_backend") if is_model else "greedy",
               metadata.get("model") if is_model else None,
               metadata.get("runtime_model") if is_model else None,
               metadata.get("requested_reasoning_effort") if is_model else None,
               metadata.get("runtime_reasoning_effort") if is_model else None))
        _import_requests(conn, game_id, records, linkage["record_links"])
        _import_actions(conn, game_id, records, linkage["record_links"])
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
                    start: dict[str, Any] | None, end: dict[str, Any] | None,
                    side_turn_id: str) -> str | None:
    """Return the proof used to attach a review, or None when it is ambiguous."""
    if review.get("side_turn_id") == side_turn_id:
        return "side_turn_id"
    review_side = _record_side_turn(review)
    boundary_side = _record_side_turn(boundary)
    if review_side is not None and boundary_side is not None and review_side == boundary_side:
        return "side_turn"
    review_revision = _record_revision(review)
    revisions = {_record_revision(boundary), _record_revision(start or {}),
                 _record_revision(end or {})}
    if review_revision is not None and review_revision in revisions:
        return "state_revision"
    return None


def _state_for_revision(states: list[dict[str, Any]], revision: int | None) -> dict[str, Any] | None:
    if revision is None:
        return None
    matches = [state for state in states if _record_revision(state) == revision]
    return matches[0] if len(matches) == 1 else None


def _state_before_revision(states: list[dict[str, Any]], revision: int | None) -> dict[str, Any] | None:
    """Use revision chronology only when it identifies one preceding state."""
    if revision is None:
        return None
    candidates = [state for state in states
                  if isinstance(state.get("state_revision"), int)
                  and state["state_revision"] < revision]
    if not candidates:
        return None
    highest = max(state["state_revision"] for state in candidates)
    matches = [state for state in candidates if state["state_revision"] == highest]
    return matches[0] if len(matches) == 1 else None


def _import_turns(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                  lines: list[dict[str, Any]], states: list[dict[str, Any]], terminal: dict[str, Any]) -> dict[str, Any]:
    boundaries = [r for r in records if r.get("type") == "turn_boundary" and r.get("accepted") is True]
    reviews = [r for r in records if r.get("type") == "handoff_review"]
    record_links: dict[str, str] = {}
    boundary_rows: list[tuple[dict[str, Any], str, dict[str, Any] | None, dict[str, Any] | None]] = []
    review_links: dict[int, tuple[str, str]] = {}
    linked_review_indexes: set[int] = set()
    for i, boundary in enumerate(boundaries, 1):
        side_turn_id = boundary.get("side_turn_id") or f"{game_id}:turn:{i}"
        end_revision = _record_revision(boundary)
        after = _state_for_revision(states, end_revision)
        start_revision = _number(boundary.get("start_revision"))
        before = _state_for_revision(states, start_revision)
        if before is None:
            before = _state_before_revision(states, end_revision)
        # A boundary without explicit endpoints is intentionally incomplete.
        # Never infer them from the ordinal position of a partial snapshot.
        sb, codec, sh = _state_payload(before); eb, _, eh = _state_payload(after)
        payload = {"sequence": i, "finish": boundary.get("authored_finish_kind"),
                   "start_revision": before.get("state_revision") if before else None,
                   "end_revision": after.get("state_revision") if after else None}
        candidates = []
        for review_index, review in enumerate(reviews):
            proof = _matches_review(review, boundary, before, after, side_turn_id)
            if proof is not None:
                candidates.append((review_index, review, proof))
        if len(candidates) == 1:
            review_index, review, proof = candidates[0]
            payload["handoff_review"] = review
            payload["handoff_review_link"] = proof
            review_links[review_index] = (side_turn_id, proof)
            linked_review_indexes.add(review_index)
        boundary_rows.append((boundary, side_turn_id, before, after))
        conn.execute("""INSERT INTO side_turns
          (side_turn_id,game_id,sequence,round_number,side,status,finish_kind,end_turn_emitted,
           start_revision,end_revision,start_state_blob,end_state_blob,start_state_hash,
           end_state_hash,state_codec,metrics_json,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(side_turn_id) DO UPDATE SET
          finish_kind=excluded.finish_kind,end_state_blob=excluded.end_state_blob,
          end_state_hash=excluded.end_state_hash,status=excluded.status,
          metrics_json=excluded.metrics_json""",
          (side_turn_id, game_id, i, after.get("turn") if after else None,
           before.get("active_faction", 0) if before else (boundary.get("side") or 0),
           "terminal" if terminal and i == len(boundaries) else "ended",
           boundary.get("authored_finish_kind"), int(bool(boundary.get("executed_finish_kind"))),
           before.get("state_revision") if before else None, after.get("state_revision") if after else None,
           sb, eb, sh, eh, codec,
           json.dumps({"handoff_review": payload["handoff_review"]}, sort_keys=True)
           if "handoff_review" in payload else "{}",
           digest(payload)))
        for key in ("side_turn_id", "side_turn"):
            value = boundary.get(key)
            if value is not None:
                record_links[f"{key}:{value}"] = side_turn_id
        for revision in (before.get("state_revision") if before else None,
                         after.get("state_revision") if after else None):
            if revision is not None:
                record_links[f"revision:{revision}"] = side_turn_id
    for index, review in enumerate(reviews):
        if index not in linked_review_indexes:
            review_links[index] = ("", "unavailable")
    return {"linked_reviews": len(linked_review_indexes),
            "unattached_reviews": len(reviews) - len(linked_review_indexes),
            "unresolved_turn_endpoints": sum(1 for _, _, before, after in boundary_rows
                                              if before is None or after is None),
            "record_links": record_links}

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
        conn.execute("""INSERT INTO model_requests
          (request_id,game_id,side_turn_id,sequence,status,error_message,elapsed_ms,input_tokens,cached_input_tokens,output_tokens,
           reasoning_tokens,prompt_bytes,response_bytes,prompt_blob,response_blob,prompt_hash,
           response_hash,payload_codec,raw_usage_json,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(request_id) DO NOTHING""",
          (req_id, game_id, _side_turn_for_record(record, links), record.get("sequence", index + 1), record.get("status", "completed"),
           record.get("error"), record.get("elapsed_ms"), usage.get("input_tokens"),
           usage.get("cached_input_tokens"), usage.get("output_tokens"),
           usage.get("reasoning_output_tokens"),
           record.get("prompt_bytes") or (len(prompt.encode()) if prompt else None),
           record.get("response_bytes") or (len(raw.encode()) if raw else None),
           zlib.compress(prompt.encode()) if prompt else None,
           zlib.compress(raw.encode()) if raw else None, record.get("prompt_hash"),
           hashlib.sha256(raw.encode()).hexdigest() if raw else None,
           "zlib" if prompt or raw else None, json.dumps(usage, sort_keys=True),
           digest({"request_id": req_id, "record": record})))

def _import_actions(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                    links: dict[str, str]) -> None:
    sequence = 0
    for batch_index, record in enumerate(r for r in records if r.get("type") == "forwarded_orders"):
        orders = record.get("orders")
        if not isinstance(orders, list):
            continue
        batch_id = record.get("batch_id") or f"{game_id}:batch:{batch_index + 1}"
        conn.execute("""INSERT INTO action_batches
          (batch_id,game_id,side_turn_id,sequence,source,submitted_orders_json,status,record_hash)
          VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(batch_id) DO NOTHING""",
          (batch_id, game_id, _side_turn_for_record(record, links), batch_index + 1, "model", json.dumps(orders, sort_keys=True),
           "accepted_unknown", digest({"batch_id": batch_id, "orders": orders})))
        for index, order in enumerate(orders):
            sequence += 1
            action_id = f"{batch_id}:action:{index}"
            conn.execute("""INSERT INTO actions
              (action_id,game_id,batch_id,sequence,authored_order_index,source,action_type,
               action_json,status,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(action_id) DO NOTHING""",
              (action_id, game_id, batch_id, sequence, index, "model", order.get("action"),
               json.dumps(order, sort_keys=True), "accepted_unknown",
               digest({"action_id": action_id, "order": order})))

def summarize_game(conn: sqlite3.Connection, game_id: str) -> dict[str, Any]:
    cur = conn.execute("SELECT * FROM game_summary WHERE game_id=?", (game_id,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(game_id)
    return dict(zip([d[0] for d in cur.description], row))

def list_side_turns(conn: sqlite3.Connection, game_id: str) -> list[dict[str, Any]]:
    cur = conn.execute("""SELECT side_turn_id,sequence,round_number,side,status,finish_kind,
                          start_revision,end_revision FROM side_turns
                          WHERE game_id=? ORDER BY sequence""", (game_id,))
    return [dict(zip([d[0] for d in cur.description], row)) for row in cur]

def backup_history(source: str, destination: str) -> None:
    src = open_history(source); dst = sqlite3.connect(destination)
    with dst: src.backup(dst)
    dst.close(); src.close()

def verify_history(path: str | os.PathLike[str]) -> dict[str, Any]:
    conn = open_history(path, read_only=True)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    counts = {}
    for table in ("games", "game_players", "side_turns", "model_requests",
                  "action_batches", "actions", "evaluation_runs", "decision_evaluations"):
        counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    conn.close()
    return {"integrity": integrity, "foreign_key_errors": len(foreign_keys), "counts": counts}

TABLES = ("games", "game_players", "side_turns", "model_requests",
          "action_batches", "actions", "evaluation_runs", "decision_evaluations")


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
            for table in ("actions", "action_batches", "model_requests", "side_turns", "game_players", "games"):
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
    inv = sub.add_parser("inventory"); inv.add_argument("--db", required=True)
    delete = sub.add_parser("delete"); delete.add_argument("--db", required=True)
    selector = delete.add_mutually_exclusive_group(required=True)
    selector.add_argument("--cohort"); selector.add_argument("--game-id", action="append"); selector.add_argument("--reset", action="store_true")
    delete.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    read_commands = {"inventory", "game", "turns"}
    conn = open_history(args.db, read_only=args.command in read_commands)
    if args.command == "import": value = import_game(conn, args.archive, args.cohort)
    elif args.command == "review": value = import_review(conn, args.path, args.run_id)
    elif args.command == "payload-coverage": value = evaluate_payload_coverage(conn, args.cohort)
    elif args.command == "inventory": value = inventory_history(conn)
    elif args.command == "delete": value = delete_history(conn, args.cohort, args.game_id or [], args.reset, args.compact)
    elif args.command == "game": value = summarize_game(conn, args.game_id)
    else: value = list_side_turns(conn, args.game_id)
    print(json.dumps(value, sort_keys=True, default=lambda value: value.hex() if isinstance(value, bytes) else value))
    conn.close(); return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
