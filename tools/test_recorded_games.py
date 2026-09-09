import json
import tempfile
import unittest
from pathlib import Path

from .game_history import open_history
from .recorded_games import _played_turns, _sidecar, list_games


class RecordedGamesTests(unittest.TestCase):
    def test_played_turns_uses_engine_ending_not_model_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "match.ndjson"
            row = {"artifact_path": td, "indexed_boundaries": 12}
            for event, expected in (
                ({"type": "game_end", "reason": "winner", "turns": 13}, 13),
                ({"type": "game_end", "turns": 26, "side_turns": 50}, 25),
                ({"type": "game_end", "turns": 26, "side_turns": 49}, 24.5),
                ({"type": "game_end", "turns": True}, None),
                ({"type": "turn_boundary", "turns": 12}, None),
            ):
                log.write_text(json.dumps({"type": "driver", "line": event}) + "\n")
                self.assertEqual(_played_turns(row), expected)
                self.assertEqual(_played_turns({"artifact_path": str(log)}), expected)
            log.write_text('{"partial":')
            self.assertIsNone(_played_turns(row))
            log.unlink()
            self.assertIsNone(_played_turns(row))

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
            self.assertEqual(result["games"][0]["players"][0]["name"], "gemini")
            self.assertIsNone(result["games"][0]["played_turns"])
            (root / "g1" / "match.ndjson").write_text(json.dumps({
                "type": "driver", "line": {"type": "game_end", "turns": 16, "side_turns": 30}
            }) + "\n")
            self.assertEqual(list_games(db, limit=1)["games"][0]["played_turns"], 15)

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
            # One malformed identity must not discard every game in this catalog.
            (archive / "identity.json").write_text('{"requested": []}')
            result = list_games(root=root)
            self.assertEqual(len(result["games"]), 1)
            self.assertEqual(result["diagnostics"], [])

    def test_sidecar_rejects_wrong_identity_and_preserves_catalog_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def row(kind="model", model=None):
                return {"artifact_path": td, "game_id": "game", "seed": 7,
                        "scenario": "demo", "starting_gold": 50, "max_side_turns": 50,
                        "players": [{"kind": kind, "model": model, "name": model or "Unknown", "faction": "undead"},
                                    {"kind": "algorithm", "model": None, "name": "Greedy", "faction": "rebels"}]}
            for value in (
                {"requested": []}, {"requested": None},
                {"llm_side": 0, "model_requested": 123},
                {"llm_side": 0, "model_requested": "unknown (host unavailable)"},
                {"llm_side": True, "model_requested": "wrong"},
                {"llm_side": 1, "model_requested": "wrong"},
                {"llm_side": 0, "model_requested": "wrong", "seed": 8},
                {"llm_side": 0, "model_requested": "wrong", "faction0": "rebels"},
                {"llm_side": 0, "model_requested": "wrong", "game_id": "another"},
            ):
                with self.subTest(value=value):
                    (root / "identity.json").write_text(json.dumps(value))
                    game = row(); _sidecar(game)
                    self.assertIsNone(game["players"][0]["model"])
                    self.assertIsNone(game["players"][1]["model"])
            (root / "identity.json").write_text(json.dumps({"llm_side": 0, "model_requested": "Requested", "seed": 7}))
            game = row(); _sidecar(game)
            self.assertEqual(game["players"][0]["name"], "Requested")
            self.assertEqual(game["players"][0]["identity_evidence"], "requested sidecar")
            game = row(model="Recorded"); _sidecar(game)
            self.assertEqual(game["players"][0]["model"], "Recorded")

    def test_runtime_model_beats_transport_display_name(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            with conn:
                conn.execute("INSERT INTO games(game_id,status,config_json,provenance_json,schema_version,artifact_path,faction0,faction1) VALUES(?,?,?,?,?,?,?,?)", ("g", "incomplete", "{}", "{}", 2, td, "undead", "rebels"))
                conn.execute("INSERT INTO game_players(game_id,side,player_kind,display_name,model_requested,model_reported) VALUES(?,?,?,?,?,?)", ("g", 0, "model", "command", "Requested", "Runtime"))
            conn.close()
            game = list_games(db)["games"][0]
            self.assertEqual(game["players"][0]["name"], "Runtime")
            self.assertEqual(game["players"][1]["faction"], "rebels")
            self.assertNotIn("side_turns", game)  # indexed boundaries are not game duration


if __name__ == "__main__":
    unittest.main()
