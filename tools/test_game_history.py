import json
import tempfile
import unittest
from pathlib import Path

from .game_history import decode_payload, encode_payload, import_game, list_side_turns, open_history, summarize_game

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
                {"type": "turn_boundary", "accepted": True, "authored_finish_kind": "explicit_done", "state_revision": 1},
                {"type": "driver", "line": {"type": "state", "state_revision": 1, "turn": 1, "active_faction": 1, "units": []}},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, "cohort")
            import_game(conn, root, "cohort", game_id)
            self.assertEqual(summarize_game(conn, game_id)["resolved_turns"], 1)
            self.assertEqual(list_side_turns(conn, game_id)[0]["finish_kind"], "explicit_done")
            self.assertEqual(conn.execute("SELECT count(*) FROM games").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM side_turns").fetchone()[0], 1)

if __name__ == "__main__":
    unittest.main()
