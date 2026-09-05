import unittest

from .luna_report import classify


class ReportTests(unittest.TestCase):
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
