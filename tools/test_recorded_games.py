import json
import tempfile
import unittest
from pathlib import Path

from .game_history import encode_payload, open_history
from .recorded_games import list_games


class RecordedGamesTests(unittest.TestCase):
    def test_list_is_newest_first_and_contains_players(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); db = root / "history.sqlite"
            conn = open_history(db)
            with conn:
                for i, stamp in enumerate(("2026-01-01T01:00:00Z", "2026-01-02T01:00:00Z")):
                    gid = f"g{i}"
                    archive = root / gid; archive.mkdir()
                    conn.execute("INSERT INTO games(game_id,started_at,status,config_json,provenance_json,schema_version,artifact_path) VALUES(?,?,?,?,?,?,?)", (gid, stamp, "incomplete", "{}", "{}", 2, str(archive)))
                    conn.execute("INSERT INTO game_players(game_id,side,player_kind,display_name,model_requested) VALUES(?,?,?,?,?)", (gid, 0, "model", "Gemini", "gemini"))
                    conn.execute("INSERT INTO game_players(game_id,side,player_kind,display_name) VALUES(?,?,?,?)", (gid, 1, "algorithm", "Greedy"))
            conn.close()
            result = list_games(db)
            self.assertEqual([g["game_id"] for g in result["games"]], ["g1", "g0"])
            self.assertEqual(result["games"][0]["players"][0]["name"], "Gemini")

    def test_missing_catalog_is_reported(self):
        result = list_games("/no/such/catalog.sqlite")
        self.assertIn("error", result)

    def test_root_discovers_catalogs_and_reads_requested_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = root / "tmp" / "run"; run.mkdir(parents=True)
            db = run / "history.sqlite"; archive = run / "game"; archive.mkdir()
            (archive / "identity.json").write_text(json.dumps({"requested": {"llm_player_model": "Gemini", "llm_side": 0}}))
            conn = open_history(db)
            with conn:
                conn.execute("INSERT INTO games(game_id,started_at,status,config_json,provenance_json,schema_version,artifact_path) VALUES(?,?,?,?,?,?,?)", ("x", "2026-01-03", "incomplete", "{}", "{}", 2, str(archive)))
                conn.execute("INSERT INTO game_players(game_id,side,player_kind,display_name) VALUES(?,?,?,?)", ("x", 0, "model", "LLM (model unavailable)"))
            conn.close()
            result = list_games(root=root)
            self.assertEqual(result["games"][0]["players"][0]["name"], "Gemini")
            self.assertEqual(result["games"][0]["catalog"], str(db))


if __name__ == "__main__":
    unittest.main()
