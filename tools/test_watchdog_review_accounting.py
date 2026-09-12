import json
import tempfile
import unittest
from pathlib import Path

from .model_usage import ModelCall
from .watchdog_review import _usage_summary


class WatchdogReviewAccountingTests(unittest.TestCase):
    def test_summary_deduplicates_lifecycle_and_keeps_unknown_role(self):
        with tempfile.TemporaryDirectory() as td:
            sidecar = Path(td) / "usage.ndjson"
            player = ModelCall(game_id="g", call_id="p", call_role="player",
                               status="dispatched")
            player_final = ModelCall(game_id="g", call_id="p", call_role="player",
                                     status="completed", input_tokens=10,
                                     output_tokens=2, total_tokens=12)
            observer = ModelCall(game_id="g", call_id="o", call_role="observer",
                                 status="dispatched")
            legacy = ModelCall(game_id="g", call_id="legacy", status="dispatched")
            sidecar.write_text("\n".join(json.dumps(dict(row.to_row(), record_kind=kind))
                                         for row, kind in ((player, "dispatch"),
                                                           (player_final, "final"),
                                                           (observer, "dispatch"),
                                                           (legacy, "dispatch"))) + "\n")
            report = _usage_summary(sidecar)
            self.assertEqual(report["player"]["calls"], 1)
            self.assertEqual(report["player"]["known_tokens"], 12)
            self.assertEqual(report["observer"]["calls"], 1)
            self.assertEqual(report["unknown"]["calls"], 1)
            self.assertEqual(report["combined"]["calls"], 3)


if __name__ == "__main__":
    unittest.main()
