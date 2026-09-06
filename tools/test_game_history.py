import json
import tempfile
import unittest
from pathlib import Path

from .game_history import (backup_history, decode_payload, encode_payload, import_game,
                           delete_history, inventory_history, list_side_turns, open_history,
                           summarize_game, verify_history)

class GameHistoryTests(unittest.TestCase):
    def test_payload_round_trip(self):
        value = {"units": [{"id": 1, "hp": 20}], "active": 0}
        blob, codec, digest = encode_payload(value)
        self.assertEqual(decode_payload(blob, codec), value)
        self.assertEqual(len(digest), 64)

    def test_import_is_idempotent_and_lists_turns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            rows = [
                {"type": "metadata", "seed": 9, "scenario": "test", "faction0": "a", "faction1": "b", "gold": 10, "first_player": 0, "source_commit": "abc"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0, "units": []}},
                {"type": "turn_boundary", "accepted": True, "authored_finish_kind": "explicit_done", "start_revision": 0, "state_revision": 1},
                {"type": "handoff_review", "version": 1, "state_revision": 0,
                 "outcome": "confirmed", "trigger_reasons": ["affordable_recruitment"],
                 "audit": {"gold": 20}},
                {"type": "driver", "line": {"type": "state", "state_revision": 1, "turn": 1, "active_faction": 1, "units": []}},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, "cohort")
            import_game(conn, root, "cohort", game_id)
            self.assertEqual(summarize_game(conn, game_id)["resolved_turns"], 1)
            self.assertEqual(list_side_turns(conn, game_id)[0]["finish_kind"], "explicit_done")
            metrics = conn.execute("SELECT metrics_json FROM side_turns WHERE game_id=?", (game_id,)).fetchone()[0]
            self.assertIn("affordable_recruitment", metrics)
            self.assertEqual(conn.execute("SELECT count(*) FROM games").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM side_turns").fetchone()[0], 1)
            backup = root / "backup.sqlite"
            conn.close()
            backup_history(str(root / "history.sqlite"), str(backup))
            self.assertEqual(verify_history(backup)["integrity"], "ok")

    def test_partial_snapshots_are_not_paired_by_ordinal_position(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            rows = [
                {"type": "metadata", "seed": 3, "scenario": "test", "faction0": "a", "faction1": "b", "gold": 10, "first_player": 0},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "state", "state_revision": 5, "turn": 1, "active_faction": 0, "turn_boundary": "partial"}},
                {"type": "turn_boundary", "accepted": True, "start_revision": 0, "state_revision": 10,
                 "side_turn_id": "turn-a", "side": 0, "authored_finish_kind": "explicit_done"},
                {"type": "handoff_review", "side_turn_id": "turn-a", "state_revision": 10, "outcome": "confirmed"},
            ]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, "cohort")
            turn = list_side_turns(conn, game_id)[0]
            self.assertEqual(turn["start_revision"], 0)
            self.assertIsNone(turn["end_revision"])
            coverage = json.loads(conn.execute("SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["linked_reviews"], 1)
            self.assertEqual(coverage["unresolved_turn_endpoints"], 1)
            metrics = json.loads(conn.execute("SELECT metrics_json FROM side_turns WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(metrics["handoff_review"]["side_turn_id"], "turn-a")

    def test_delete_exact_cohort_preserves_other_games_and_compacts(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            with conn:
                for game, cohort in (("bad1", "bad"), ("good1", "good")):
                    conn.execute("""INSERT INTO games(game_id,cohort_id,status,config_json,
                        provenance_json,schema_version,artifact_path) VALUES(?,?,?,?,?,?,?)""",
                                 (game, cohort, "complete", "{}", "{}", 1, "."))
                    conn.execute("""INSERT INTO model_requests(request_id,game_id,sequence,status,
                        record_hash) VALUES(?,?,?,?,?)""", (game + ":r", game, 1, "failed", "h"))
            result = delete_history(conn, cohort_id="bad", compact=True)
            self.assertEqual(result["deleted_game_ids"], ["bad1"])
            self.assertEqual(conn.execute("SELECT count(*) FROM games").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT game_id FROM games").fetchone()[0], "good1")
            self.assertEqual(verify_history(Path(td) / "history.sqlite")["foreign_key_errors"], 0)
            with self.assertRaises(KeyError):
                delete_history(conn, game_ids=["missing"])
            self.assertEqual(inventory_history(conn)["counts"]["games"], 1)

if __name__ == "__main__":
    unittest.main()
