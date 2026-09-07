import json
import tempfile
import unittest
from pathlib import Path

from .game_history import encode_payload, open_history
from .replay_game import build_bundle


class ReplayExportTests(unittest.TestCase):
    def test_export_resolves_id_and_deduplicates_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "archive"; archive.mkdir()
            log = archive / "match.ndjson"
            log.write_text('{"type":"metadata","scenario":"demo"}\n', encoding="utf-8")
            db = root / "history.sqlite"
            conn = open_history(db)
            with conn:
                conn.execute("INSERT INTO games(game_id,status,config_json,provenance_json,schema_version,artifact_path,faction0,faction1) VALUES(?,?,?,?,?,?,?,?)",
                             ("game-1", "complete", "{}", "{}", 2, str(archive), "undead", "undead"))
                conn.execute("INSERT INTO game_players(game_id,side,player_kind,display_name,backend,model_requested) VALUES(?,?,?,?,?,?)",
                             ("game-1", 0, "model", "undead", "test", "fixture"))
                state0 = {"turn": 1, "active_faction": 0, "cols": 2, "rows": 2, "terrain": [], "units": []}
                state1 = dict(state0, active_faction=1)
                blob0, codec, _ = encode_payload(state0); blob1, _, _ = encode_payload(state1)
                conn.execute("INSERT INTO side_turns(side_turn_id,game_id,sequence,side,status,start_revision,end_revision,start_state_blob,end_state_blob,state_codec,record_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                             ("t1", "game-1", 1, 0, "complete", 0, 1, blob0, blob1, codec, "h"))
            conn.close()
            bundle_path = build_bundle(db, "game-1", root / "out" / "replay.json")
            bundle = json.loads(bundle_path.read_text())
            self.assertEqual(bundle["version"], 1)
            self.assertEqual(bundle["game_id"], "game-1")
            self.assertEqual([f["state_revision"] for f in bundle["frames"]], [0, 1])
            self.assertEqual(bundle["players"][0]["display_name"], "undead")

    def test_unknown_game_fails(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db); conn.close()
            with self.assertRaises(KeyError):
                build_bundle(db, "nope", Path(td) / "x")


if __name__ == "__main__":
    unittest.main()
