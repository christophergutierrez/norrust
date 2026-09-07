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

from .game_history import decode_payload, open_history

BUNDLE_VERSION = 1


def _archive_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bundle(db: str | os.PathLike[str], game_id: str,
                 output: str | os.PathLike[str]) -> Path:
    """Write a relocatable replay bundle for *game_id* and return its path."""
    conn = open_history(db, read_only=True)
    game = conn.execute("SELECT * FROM games WHERE game_id=?", (game_id,)).fetchone()
    if game is None:
        raise KeyError(f"unknown game_id: {game_id}")
    columns = [item[1] for item in conn.execute("PRAGMA table_info(games)")]
    metadata = dict(zip(columns, game))
    archive = Path(metadata["artifact_path"])
    log = archive if archive.is_file() else archive / "match.ndjson"
    if not log.is_file():
        raise FileNotFoundError(f"game archive does not exist: {log}")
    players = [dict(zip(("side", "player_kind", "display_name", "backend", "model_requested", "model_reported"), row))
               for row in conn.execute(
                   "SELECT side,player_kind,display_name,backend,model_requested,model_reported "
                   "FROM game_players WHERE game_id=? ORDER BY side", (game_id,))]
    rows = conn.execute(
        "SELECT sequence,side,start_revision,end_revision,start_state_blob,end_state_blob,state_codec "
        "FROM side_turns WHERE game_id=? ORDER BY sequence", (game_id,)).fetchall()
    frames: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sequence, side, start_rev, end_rev, start_blob, end_blob, codec in rows:
        for boundary, revision, blob in (("start", start_rev, start_blob), ("end", end_rev, end_blob)):
            if blob is None:
                continue
            state = decode_payload(blob, codec or "zlib")
            fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            frames.append({"index": len(frames), "sequence": sequence, "side": side,
                           "boundary": boundary, "state_revision": revision,
                           "state": state})
    if not frames:
        conn.close()
        raise ValueError(f"game {game_id} has no usable recorded state snapshots")
    if frames[0]["boundary"] != "start" or frames[0]["sequence"] != 1:
        conn.close()
        raise ValueError(f"game {game_id} has no provable starting snapshot")
    bundle = {
        "version": BUNDLE_VERSION,
        "game_id": game_id,
        "players": players,
        "metadata": {key: metadata.get(key) for key in
                      ("scenario", "seed", "faction0", "faction1", "starting_gold",
                       "first_side", "max_side_turns", "status", "winner_side",
                      "termination_reason", "source_commit", "coverage_json")},
        "provenance": {"catalog": str(Path(db).resolve()), "archive": str(log.resolve()),
                       "archive_sha256": _archive_hash(log)},
        "frames": frames,
    }
    bundle["metadata"]["players"] = players
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
