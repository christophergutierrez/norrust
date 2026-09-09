"""Read and export recorded games for the Love2D browser."""
from __future__ import annotations

import argparse
import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any

from .game_history import open_history
from .replay_game import build_bundle


def _catalog_rows(db: Path) -> list[dict[str, Any]]:
    with closing(open_history(db, read_only=True)) as conn:
        return _read_catalog_rows(conn, db)


def _read_catalog_rows(conn, db: Path) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT game_id,started_at,ended_at,scenario,faction0,faction1,seed,starting_gold,max_side_turns,status,"
        "winner_side,termination_reason,artifact_path,source_commit,coverage_json FROM games"
    ).fetchall()
    result = []
    for row in rows:
        (game_id, started, ended, scenario, faction0, faction1, seed, gold, cap, status, winner, reason,
         artifact, commit, coverage_json) = row
        try:
            coverage = json.loads(coverage_json) if coverage_json else {}
        except ValueError:
            coverage = {}
        players = conn.execute(
            "SELECT side,player_kind,display_name,backend,model_requested,model_reported "
            "FROM game_players WHERE game_id=? ORDER BY side", (game_id,)
        ).fetchall()
        turns = conn.execute("SELECT count(*) FROM side_turns WHERE game_id=?", (game_id,)).fetchone()[0]
        sides = []
        for side in (0, 1):
            p = next((p for p in players if p[0] == side), None)
            if p is None:
                sides.append({"side": side, "name": "Unknown", "kind": None, "model": None,
                              "faction": faction0 if side == 0 else faction1})
            else:
                _, kind, display, backend, requested, reported = p
                model = reported or requested
                name = (model or "LLM (model unavailable)") if kind == "model" else (display or backend or "Unknown")
                sides.append({"side": side, "name": name, "kind": kind, "model": model,
                              "faction": (faction0 if side == 0 else faction1)})
        result.append({"game_id": game_id, "catalog": str(db), "started_at": started, "ended_at": ended,
                       "scenario": scenario, "seed": seed, "starting_gold": gold,
                       "max_side_turns": cap, "status": status, "winner_side": winner,
                       "termination_reason": reason, "artifact_path": artifact,
                       "source_commit": commit, "indexed_boundaries": turns, "players": sides,
                       # Coverage separates the recorded engine result from how much of
                       # the timeline can actually be replayed; never a guessed ratio.
                       "replay_complete": bool(coverage.get("opening_present") and coverage.get("terminal_present")
                                               and not coverage.get("gaps")),
                       "coverage_gaps": coverage.get("gaps", [])})
    return result


def discover_catalogs(root: Path) -> tuple[list[Path], list[str]]:
    candidates = [root / ".norrust_history" / "history.sqlite"]
    candidates.extend(p for p in (root / "tmp").rglob("*.sqlite")
                      if not p.name.endswith((".backup.sqlite", ".bak.sqlite")))
    catalogs, diagnostics = [], []
    for path in sorted(set(candidates)):
        if not path.is_file():
            continue
        try:
            conn = open_history(path, read_only=True)
            try:
                conn.execute("SELECT 1 FROM games LIMIT 1").fetchone()
            finally:
                conn.close()
            catalogs.append(path)
        except Exception as exc:
            diagnostics.append(f"{path}: {exc}")
    return catalogs, diagnostics


def _sidecar(row: dict[str, Any]) -> None:
    archive = Path(row["artifact_path"])
    path = archive / "identity.json" if archive.is_dir() else archive.parent / "identity.json"
    if not path.is_file():
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        requested = value.get("requested", value) if isinstance(value, dict) else {}
        if not isinstance(requested, dict):
            return
        model = requested.get("llm_player_model") or requested.get("model_requested")
        side = requested.get("llm_side")
        if not isinstance(model, str) or not model.strip() or model.strip().lower().startswith("unknown"):
            return
        for key, field in (("game_id", "game_id"), ("seed", "seed"), ("scenario", "scenario"),
                           ("gold", "starting_gold"), ("starting_gold", "starting_gold"),
                           ("max_turns", "max_side_turns")):
            if key in requested and requested[key] != row.get(field):
                return
        for side_index in (0, 1):
            key = f"faction{side_index}"
            if key in requested and requested[key] != row["players"][side_index].get("faction"):
                return
        if type(side) is int and side in (0, 1):
            player = row["players"][side]
            if player.get("kind") == "model" and not player.get("model"):
                player["name"] = model
                player["model"] = model
                player["identity_evidence"] = "requested sidecar"
    except (OSError, ValueError, TypeError):
        return


def _played_turns(row: dict[str, Any]) -> int | float | None:
    """Read the engine's ending, never substitute imported model-boundary counts."""
    archive = Path(row["artifact_path"])
    log = archive / "match.ndjson" if archive.is_dir() else archive
    ending = None
    try:
        with log.open(encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                if not isinstance(record, dict):
                    continue
                event = record.get("line") if record.get("type") == "driver" else record
                if isinstance(event, dict) and event.get("type") == "game_end":
                    ending = event
    except (OSError, ValueError):
        return None
    if ending is None:
        return None
    # A cap ends at a boundary, possibly after just one side. The engine's
    # round counter may already point at the next, unplayed round.
    count = ending.get("side_turns")
    if type(count) is int and count >= 0:
        return count / 2
    count = ending.get("turns")
    return count if type(count) is int and count >= 0 else None


def list_games(db: str | os.PathLike[str] | None = None, limit: int = 25, offset: int = 0,
               root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    diagnostics: list[str] = []
    if root is not None:
        paths, diagnostics = discover_catalogs(Path(root).resolve())
    else:
        paths = [Path(db)] if db and Path(db).is_file() else []
        if db and not paths:
            diagnostics.append(f"history catalog does not exist: {db}")
    rows = []
    for path in paths:
        try:
            catalog_rows = _catalog_rows(path)
            for row in catalog_rows:
                _sidecar(row)
            rows.extend(catalog_rows)
        except Exception as exc:
            diagnostics.append(f"{path}: {exc}")
    if not paths and not diagnostics:
        diagnostics.append(f"history catalog does not exist: {db or root}")
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        previous = unique.get(row["game_id"])
        if previous is None or (row["indexed_boundaries"] > previous["indexed_boundaries"]):
            unique[row["game_id"]] = row
    rows = list(unique.values())
    rows.sort(key=lambda r: (r["started_at"] or "", r["game_id"]), reverse=True)
    result = {"games": rows[offset:offset + limit], "total": len(rows), "offset": offset,
              "limit": limit, "diagnostics": diagnostics}
    for row in result["games"]:
        row["played_turns"] = _played_turns(row)
    if db is not None and not paths and diagnostics:
        result["error"] = diagnostics[0]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list"); ls.add_argument("--db"); ls.add_argument("--root"); ls.add_argument("--limit", type=int, default=25); ls.add_argument("--offset", type=int, default=0)
    ex = sub.add_parser("export"); ex.add_argument("--db", required=True); ex.add_argument("--game-id", required=True); ex.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if args.command == "list":
        value = list_games(args.db, max(1, min(args.limit, 100)), max(0, args.offset), args.root)
    else:
        try:
            value = {"bundle": str(build_bundle(args.db, args.game_id, args.output))}
        except Exception as exc:
            value = {"error": str(exc)}
    print(json.dumps(value, separators=(",", ":")))
    return 0 if "error" not in value else 1


if __name__ == "__main__":
    raise SystemExit(main())
