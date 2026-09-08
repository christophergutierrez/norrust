"""Read and export recorded games for the Love2D browser."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .game_history import open_history
from .replay_game import build_bundle


def _catalog_rows(db: Path) -> list[dict[str, Any]]:
    conn = open_history(db, read_only=True)
    rows = conn.execute(
        "SELECT game_id,started_at,ended_at,scenario,seed,starting_gold,max_side_turns,status,"
        "winner_side,termination_reason,artifact_path,source_commit FROM games"
    ).fetchall()
    result = []
    for row in rows:
        game_id, started, ended, scenario, seed, gold, cap, status, winner, reason, artifact, commit = row
        players = conn.execute(
            "SELECT side,player_kind,display_name,backend,model_requested,model_reported "
            "FROM game_players WHERE game_id=? ORDER BY side", (game_id,)
        ).fetchall()
        turns = conn.execute(
            "SELECT count(*) FROM side_turns WHERE game_id=? AND status IN ('complete','completed')",
            (game_id,),
        ).fetchone()[0]
        sides = []
        for side in (0, 1):
            p = next((p for p in players if p[0] == side), None)
            if p is None:
                sides.append({"side": side, "name": "Unknown", "kind": None, "model": None})
            else:
                _, kind, display, backend, requested, reported = p
                model = reported or requested
                name = display or model or ("LLM (model unavailable)" if kind == "model" else backend) or "Unknown"
                sides.append({"side": side, "name": name, "kind": kind, "model": model})
        result.append({"game_id": game_id, "started_at": started, "ended_at": ended,
                       "scenario": scenario, "seed": seed, "starting_gold": gold,
                       "max_side_turns": cap, "status": status, "winner_side": winner,
                       "termination_reason": reason, "artifact_path": artifact,
                       "source_commit": commit, "side_turns": turns, "players": sides})
    conn.close()
    return result


def list_games(db: str | os.PathLike[str], limit: int = 25, offset: int = 0) -> dict[str, Any]:
    path = Path(db)
    if not path.is_file():
        return {"games": [], "total": 0, "error": f"history catalog does not exist: {path}"}
    try:
        rows = _catalog_rows(path)
    except Exception as exc:
        return {"games": [], "total": 0, "error": f"could not read history catalog: {exc}"}
    rows.sort(key=lambda r: (r["started_at"] or "", r["game_id"]), reverse=True)
    return {"games": rows[offset:offset + limit], "total": len(rows), "offset": offset,
            "limit": limit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list"); ls.add_argument("--db", required=True); ls.add_argument("--limit", type=int, default=25); ls.add_argument("--offset", type=int, default=0)
    ex = sub.add_parser("export"); ex.add_argument("--db", required=True); ex.add_argument("--game-id", required=True); ex.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "list":
        value = list_games(args.db, max(1, min(args.limit, 100)), max(0, args.offset))
    else:
        try:
            value = {"bundle": str(build_bundle(args.db, args.game_id, args.output))}
        except Exception as exc:
            value = {"error": str(exc)}
    print(json.dumps(value, separators=(",", ":")))
    return 0 if "error" not in value else 1


if __name__ == "__main__":
    raise SystemExit(main())
