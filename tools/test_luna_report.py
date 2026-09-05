import unittest

from .luna_report import classify
from .llm_client import replay_accepted_progress


class ReportTests(unittest.TestCase):
    def test_progress_replay_resets_only_at_accepted_end_turn(self):
        moved, attacked = replay_accepted_progress([
            {"type": "driver", "line": {"type": "events", "source": "llm", "events": [
                {"kind": "move", "unit": 3}, {"kind": "attack", "attacker": {"unit": 4}}]}},
            {"type": "driver", "line": {"type": "events", "source": "greedy", "events": [
                {"kind": "move", "unit": 99}]}},
            {"type": "driver", "line": {"type": "events", "source": "llm", "events": [
                {"kind": "end_turn"}]}},
            {"type": "driver", "line": {"type": "events", "source": "llm", "events": [
                {"kind": "move", "unit": 8}]}},
        ], 0)
        self.assertEqual(moved, {8})
        self.assertEqual(attacked, set())

    def test_model_error_is_incomplete_model_failure(self):
        report = classify([{"type": "model_error", "terminal_class": "model_invalid",
                           "model_calls": 8}])
        self.assertEqual(report["terminal_class"], "model_invalid")
        self.assertEqual(report["model_calls"], 8)

    def test_accepted_attack_death_uses_unit_ownership(self):
        report = classify([
            {"type": "driver", "line": {"type": "state", "units": [
                {"id": 1, "faction": 0}, {"id": 2, "faction": 1}]}},
            {"type": "driver", "line": {"type": "events", "events": [{
                "kind": "attack", "source": "llm",
                "attacker": {"unit": 1, "killed": False},
                "defender": {"unit": 2, "killed": True}}]}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "max_turns"},
        ])
        self.assertEqual(report["deaths_by_faction"], {"1": 1})
        self.assertEqual(report["attacks_by_source"], {"llm": 1})


if __name__ == "__main__":
    unittest.main()
