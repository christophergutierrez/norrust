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

def open_history(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
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
           first_side,max_side_turns,status,winner_side,termination_reason,source_commit,
           config_json,provenance_json,schema_version,artifact_path,coverage_json)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(game_id) DO UPDATE SET status=excluded.status,
          winner_side=excluded.winner_side,termination_reason=excluded.termination_reason""",
          (game_id, cohort_id, game_id, metadata.get("seed"), metadata.get("scenario"),
           metadata.get("faction0"), metadata.get("faction1"), metadata.get("gold"),
           metadata.get("first_player"), metadata.get("max_turns"), status, terminal.get("winner"),
           terminal.get("reason"), metadata.get("source_commit"), json.dumps(config, sort_keys=True),
           json.dumps({"archive": str(log)}, sort_keys=True), SCHEMA_VERSION, str(root),
           json.dumps({"state_records": len(states)})))
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
        _import_turns(conn, game_id, records, lines, states, terminal)
        _import_requests(conn, game_id, records)
        _import_actions(conn, game_id, records)
    return game_id

def _import_turns(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]],
                  lines: list[dict[str, Any]], states: list[dict[str, Any]], terminal: dict[str, Any]) -> None:
    boundaries = [r for r in records if r.get("type") == "turn_boundary" and r.get("accepted") is True]
    for i, boundary in enumerate(boundaries, 1):
        before = states[i - 1] if i - 1 < len(states) else None
        after = states[i] if i < len(states) else before
        sb, codec, sh = _state_payload(before); eb, _, eh = _state_payload(after)
        payload = {"sequence": i, "finish": boundary.get("authored_finish_kind"),
                   "start_revision": before.get("state_revision") if before else None,
                   "end_revision": after.get("state_revision") if after else None}
        conn.execute("""INSERT INTO side_turns
          (side_turn_id,game_id,sequence,round_number,side,status,finish_kind,end_turn_emitted,
           start_revision,end_revision,start_state_blob,end_state_blob,start_state_hash,
           end_state_hash,state_codec,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(side_turn_id) DO UPDATE SET
          finish_kind=excluded.finish_kind,end_state_blob=excluded.end_state_blob,
          end_state_hash=excluded.end_state_hash,status=excluded.status""",
          (f"{game_id}:turn:{i}", game_id, i, after.get("turn") if after else None,
           before.get("active_faction", 0) if before else None,
           "terminal" if terminal and i == len(boundaries) else "ended",
           boundary.get("authored_finish_kind"), int(bool(boundary.get("executed_finish_kind"))),
           before.get("state_revision") if before else None, after.get("state_revision") if after else None,
           sb, eb, sh, eh, codec, digest(payload)))

def _import_requests(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]]) -> None:
    request_records = [r for r in records if r.get("type") == "model_request"]
    if not request_records:
        request_records = [r for r in records if r.get("type") == "model"]
    for index, record in enumerate(request_records):
        raw = record.get("raw_output") if isinstance(record.get("raw_output"), str) else None
        prompt = record.get("prompt") if isinstance(record.get("prompt"), str) else None
        req_id = record.get("request_id") or f"{game_id}:request:{index + 1}"
        usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
        conn.execute("""INSERT INTO model_requests
          (request_id,game_id,sequence,status,error_message,elapsed_ms,input_tokens,cached_input_tokens,output_tokens,
           reasoning_tokens,prompt_bytes,response_bytes,prompt_blob,response_blob,prompt_hash,
           response_hash,payload_codec,raw_usage_json,record_hash)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(request_id) DO NOTHING""",
          (req_id, game_id, record.get("sequence", index + 1), record.get("status", "completed"),
           record.get("error"), record.get("elapsed_ms"), usage.get("input_tokens"),
           usage.get("cached_input_tokens"), usage.get("output_tokens"),
           usage.get("reasoning_output_tokens"), len(prompt.encode()) if prompt else None,
           record.get("prompt_bytes") or (len(prompt.encode()) if prompt else None),
           record.get("response_bytes") or (len(raw.encode()) if raw else None),
           zlib.compress(prompt.encode()) if prompt else None,
           zlib.compress(raw.encode()) if raw else None, record.get("prompt_hash"),
           hashlib.sha256(raw.encode()).hexdigest() if raw else None,
           "zlib" if prompt or raw else None, json.dumps(usage, sort_keys=True),
           digest({"request_id": req_id, "record": record})))

def _import_actions(conn: sqlite3.Connection, game_id: str, records: list[dict[str, Any]]) -> None:
    sequence = 0
    for batch_index, record in enumerate(r for r in records if r.get("type") == "forwarded_orders"):
        orders = record.get("orders")
        if not isinstance(orders, list):
            continue
        batch_id = record.get("batch_id") or f"{game_id}:batch:{batch_index + 1}"
        conn.execute("""INSERT INTO action_batches
          (batch_id,game_id,sequence,source,submitted_orders_json,status,record_hash)
          VALUES(?,?,?,?,?,?,?) ON CONFLICT(batch_id) DO NOTHING""",
          (batch_id, game_id, batch_index + 1, "model", json.dumps(orders, sort_keys=True),
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
    conn = sqlite3.connect(path)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    counts = {}
    for table in ("games", "game_players", "side_turns", "model_requests",
                  "action_batches", "actions", "evaluation_runs", "decision_evaluations"):
        counts[table] = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    conn.close()
    return {"integrity": integrity, "foreign_key_errors": len(foreign_keys), "counts": counts}

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

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import"); imp.add_argument("--db", required=True); imp.add_argument("archive"); imp.add_argument("--cohort")
    review = sub.add_parser("review"); review.add_argument("--db", required=True); review.add_argument("--run-id", required=True); review.add_argument("path")
    show = sub.add_parser("game"); show.add_argument("--db", required=True); show.add_argument("game_id")
    turns = sub.add_parser("turns"); turns.add_argument("--db", required=True); turns.add_argument("game_id")
    args = parser.parse_args(argv)
    conn = open_history(args.db)
    if args.command == "import": value = import_game(conn, args.archive, args.cohort)
    elif args.command == "review": value = import_review(conn, args.path, args.run_id)
    elif args.command == "game": value = summarize_game(conn, args.game_id)
    else: value = list_side_turns(conn, args.game_id)
    print(json.dumps(value, sort_keys=True, default=lambda value: value.hex() if isinstance(value, bytes) else value))
    conn.close(); return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
