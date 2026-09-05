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

    def test_new_telemetry_counts_only_accepted_boundaries(self):
        report = classify([
            {"type": "metadata", "finish_telemetry_available": True},
            {"type": "turn_boundary", "accepted": True,
             "authored_finish_kind": "explicit_done", "executed_finish_kind": "explicit_done",
             "delegated_unit_ids": [3], "protected_unit_ids": [4]},
            {"type": "turn_boundary", "accepted": False,
             "authored_finish_kind": "implicit_end_turn", "executed_finish_kind": "implicit_end_turn"},
            {"type": "turn_boundary", "accepted": True,
             "authored_finish_kind": "implicit_end_turn", "executed_finish_kind": "implicit_end_turn",
             "delegated_unit_ids": [5]},
            {"type": "driver", "line": {"type": "events", "events": [
                {"kind": "move", "source": "delegated_greedy", "unit": 3},
                {"kind": "attack", "source": "delegated_greedy",
                 "attacker": {"unit": 3, "killed": False},
                 "defender": {"unit": 9, "killed": True}},
                {"kind": "end_turn", "source": "delegated_greedy"},
                {"kind": "end_turn", "source": "greedy"},
            ]}},
            {"type": "driver", "line": {"type": "game_end", "side_turns": 2}},
            {"type": "terminal", "terminal_class": "gameplay"},
        ])
        self.assertTrue(report["finish_telemetry_available"])
        self.assertEqual(report["finish_counts"], {
            "explicit_done": 1, "implicit_end_turn": 1, "selective": 0, "timeout": 0})
        self.assertEqual(report["awareness_numerator"], 1)
        self.assertEqual(report["awareness_denominator"], 2)
        self.assertEqual(report["awareness_rate"], 0.5)
        self.assertEqual(report["delegated"], {
            "units": 2, "moves": 1, "attacks": 1, "kills": 1,
            "villages": 0, "end_turns": 1})
        self.assertEqual(report["completed_side_turns"], 2)
        self.assertEqual(report["protected_units"], 1)
        self.assertIsNone(report["protected_recruiters"])
        self.assertTrue(report["accounting_mismatch"])

    def test_historical_logs_mark_finish_awareness_unavailable(self):
        report = classify([
            {"type": "driver", "line": {"type": "state", "side_turns": 1}},
            {"type": "driver", "line": {"type": "events", "events": [
                {"kind": "end_turn", "source": "llm"}]}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner"},
        ])
        self.assertFalse(report["finish_telemetry_available"])
        self.assertIsNone(report["awareness_rate"])
        self.assertIsNone(report["finish_counts"])


if __name__ == "__main__":
    unittest.main()
