"""Export a cataloged Norrust game and open it in the read-only Love2D viewer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .game_history import IMPORTER_VERSION, decode_payload, open_history

BUNDLE_VERSION = 2


def _archive_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bundle(db: str | os.PathLike[str], game_id: str,
                 output: str | os.PathLike[str]) -> Path:
    """Write a relocatable replay bundle for *game_id* and return its path.

    Frames come from the game's authoritative `snapshots` timeline, not from
    a pair of blobs per side turn. Only renderable snapshots become frames;
    non-renderable evidence (identity-only, e.g. a standalone checkpoint)
    still contributes to the reported coverage gaps.
    """
    conn = open_history(db, read_only=True)
    game = conn.execute("SELECT * FROM games WHERE game_id=?", (game_id,)).fetchone()
    if game is None:
        conn.close()
        raise KeyError(f"unknown game_id: {game_id}")
    columns = [item[1] for item in conn.execute("PRAGMA table_info(games)")]
    metadata = dict(zip(columns, game))
    if metadata.get("importer_version") != IMPORTER_VERSION:
        conn.close()
        raise ValueError(
            f"game {game_id} was catalogued by importer "
            f"{metadata.get('importer_version') or 'a pre-snapshot schema'}, not {IMPORTER_VERSION}. "
            "Reimport it (python3 -m tools.game_history import --db "
            f"{db} <archive>) before replay; this viewer refuses to fall back "
            "to the old per-side-turn export.")
    archive = Path(metadata["artifact_path"])
    log = archive if archive.is_file() else archive / "match.ndjson"
    if not log.is_file():
        raise FileNotFoundError(f"game archive does not exist: {log}")
    players = [dict(zip(("side", "player_kind", "display_name", "backend", "model_requested", "model_reported"), row))
               for row in conn.execute(
                   "SELECT side,player_kind,display_name,backend,model_requested,model_reported "
                   "FROM game_players WHERE game_id=? ORDER BY side", (game_id,))]
    rows = conn.execute(
        "SELECT sequence,revision,round_number,active_side,completed_side_turns,boundary_kind,"
        "renderable,state_blob,state_codec FROM snapshots WHERE game_id=? ORDER BY sequence",
        (game_id,)).fetchall()
    frames: list[dict[str, Any]] = []
    for sequence, revision, round_number, side, completed, boundary_kind, renderable, blob, codec in rows:
        if not renderable or blob is None:
            continue
        state = decode_payload(blob, codec or "zlib")
        frames.append({"index": len(frames), "sequence": sequence, "revision": revision,
                       "round": round_number, "side": side, "completed_side_turns": completed,
                       "boundary_kind": boundary_kind, "state": state})
    if not frames:
        conn.close()
        raise ValueError(f"game {game_id} has no usable recorded state snapshots")
    if frames[0]["boundary_kind"] != "opening":
        conn.close()
        raise ValueError(f"game {game_id} has no provable starting snapshot")
    coverage = json.loads(metadata.get("coverage_json") or "{}")
    bundle = {
        "version": BUNDLE_VERSION,
        "game_id": game_id,
        "players": players,
        "metadata": {key: metadata.get(key) for key in
                      ("scenario", "seed", "faction0", "faction1", "starting_gold",
                       "first_side", "max_side_turns", "status", "winner_side",
                      "termination_reason", "source_commit")},
        "coverage": coverage,
        "provenance": {"catalog": str(Path(db).resolve()), "archive": str(log.resolve()),
                       "archive_sha256": _archive_hash(log)},
        "frames": frames,
    }
    bundle["metadata"]["players"] = players
    bundle["metadata"]["coverage"] = coverage
    conn.close()
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    return destination


def launch(game_id: str, db: str, love: str = "love") -> int:
    with tempfile.TemporaryDirectory(prefix=f"norrust-replay-{game_id}-") as directory:
        bundle = build_bundle(db, game_id, Path(directory) / "replay.json")
        root = Path(__file__).resolve().parents[1]
        return subprocess.run([love, str(root / "norrust_love"), "--", "--replay-bundle", str(bundle)],
                              check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game_id")
    parser.add_argument("--db", default=".norrust_history/history.sqlite")
    parser.add_argument("--export", metavar="PATH", help="export without launching Love2D")
    parser.add_argument("--love", default="love")
    args = parser.parse_args(argv)
    if args.export:
        print(build_bundle(args.db, args.game_id, args.export))
        return 0
    return launch(args.game_id, args.db, args.love)


if __name__ == "__main__":
    raise SystemExit(main())
