import json
import tempfile
import unittest
from pathlib import Path

from .game_history import import_game, open_history
from .replay_game import build_bundle


def _write_log(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class ReplayExportTests(unittest.TestCase):
    def test_export_builds_frames_from_the_snapshot_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "archive"; archive.mkdir()
            log = archive / "match.ndjson"
            state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                     "terrain": [], "units": [], "state_revision": 0}
            state1 = dict(state0, active_faction=1, state_revision=1)
            _write_log(log, [
                {"type": "metadata", "faction0": "undead", "faction1": "undead"},
                {"type": "driver", "line": state0},
                {"type": "turn_boundary", "accepted": True, "start_revision": 0, "state_revision": 1,
                 "authored_finish_kind": "explicit_done"},
                {"type": "driver", "line": state1},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ])
            db = root / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, archive)
            conn.execute("UPDATE game_players SET display_name='undead' WHERE game_id=? AND side=0", (game_id,))
            conn.commit(); conn.close()
            bundle_path = build_bundle(db, game_id, root / "out" / "replay.json")
            bundle = json.loads(bundle_path.read_text())
            self.assertEqual(bundle["game_id"], game_id)
            self.assertEqual([f["revision"] for f in bundle["frames"]], [0, 1])
            self.assertEqual(bundle["frames"][0]["boundary_kind"], "opening")
            self.assertEqual(bundle["frames"][-1]["boundary_kind"], "terminal")
            self.assertTrue(bundle["coverage"]["opening_present"])
            self.assertTrue(bundle["coverage"]["terminal_present"])
            self.assertEqual(bundle["players"][0]["display_name"], "undead")

    def test_unknown_game_fails(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db); conn.close()
            with self.assertRaises(KeyError):
                build_bundle(db, "nope", Path(td) / "x")

    def test_stale_pre_snapshot_catalog_row_is_an_actionable_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "archive"; archive.mkdir()
            (archive / "match.ndjson").write_text('{"type":"metadata"}\n', encoding="utf-8")
            db = root / "history.sqlite"
            conn = open_history(db)
            with conn:
                conn.execute("""INSERT INTO games(game_id,status,config_json,provenance_json,
                    schema_version,artifact_path) VALUES(?,?,?,?,?,?)""",
                    ("legacy", "complete", "{}", "{}", 2, str(archive)))
            conn.close()
            with self.assertRaisesRegex(ValueError, "Reimport it"):
                build_bundle(db, "legacy", root / "x")


if __name__ == "__main__":
    unittest.main()
