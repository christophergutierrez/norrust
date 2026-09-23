"""Stack 5 tests for paired Coordinated Planner selector evaluation."""
from __future__ import annotations

import unittest

from . import algorithm_strength as strength
from . import coordinated_selector_evaluation as evaluation


class CoordinatedSelectorEvaluationTests(unittest.TestCase):
    def test_screen_is_32_matched_cells_balanced_across_opponents(self):
        schedule = evaluation.build_schedule()
        self.assertEqual(len(schedule), 32)
        self.assertEqual({opponent: sum(c["opponent"] == opponent for c in schedule)
                          for opponent in strength.DEFAULT_OPPONENTS},
                         {"greedy": 16, "greedy-look-ahead": 16})
        for cell in schedule:
            self.assertEqual(cell["controlled_algorithm"], "coordinated")
            self.assertEqual(cell["recruit1_policy"], "first-affordable")
            self.assertEqual(cell["recruit2_policy"], "first-affordable")
            self.assertEqual(cell["threads"], 1)
        self.assertEqual(len({c["seed"] for c in schedule}), 32)

    def test_treatments_share_game_settings_and_fake_selector_is_local(self):
        cell = evaluation.build_schedule()[0]
        base = evaluation.command_for(cell, "coordinated-baseline", __import__("pathlib").Path("self-play"),
                                      __import__("pathlib").Path("trace"))
        fake = evaluation.command_for(cell, "coordinated-llm", __import__("pathlib").Path("self-play"),
                                      __import__("pathlib").Path("trace"))
        self.assertEqual(fake[:-2], base)
        self.assertEqual(fake[-2:], ["--selector-candidate", "objective"])
        self.assertNotIn("--model-command", fake)

    def test_report_keeps_unrun_cells_and_summarizes_selector_accounting(self):
        schedule = evaluation.build_schedule()
        cell = schedule[0]
        decision = {"selector_invoked": True, "baseline_candidate_id": "greedy",
                    "selected_candidate_id": "objective", "fallback_reason": None,
                    "response_status": "selected", "score_margin": 1.5,
                    "latency_ms": None, "cost_microusd": None}
        rows = [
            {"pair_id": cell["pair_id"], "treatment": "coordinated-baseline",
             "status": "completed", "outcome": "win", "opponent": cell["opponent"],
             "faction": cell["faction"], "controlled_side": cell["controlled_side"],
             "seed": cell["seed"], "decisions": [], "decision_count": 0},
            {"pair_id": cell["pair_id"], "treatment": "coordinated-llm",
             "status": "completed", "outcome": "loss", "opponent": cell["opponent"],
             "faction": cell["faction"], "controlled_side": cell["controlled_side"],
             "seed": cell["seed"], "decisions": [decision], "decision_count": 1},
        ]
        report = evaluation.build_report(schedule, rows)
        llm = report["summary"]["coordinated-llm"]
        self.assertEqual(report["scheduled_paired_games"], 64)
        self.assertEqual(llm["wins"], 0)
        self.assertEqual(llm["losses"], 1)
        self.assertEqual(llm["unrun"], 31)
        self.assertEqual(llm["selector_invocations"], 1)
        self.assertEqual(llm["disagreement_count"], 1)
        self.assertEqual(llm["fallback_count"], 0)
        self.assertEqual(llm["latency_ms_mean"], None)
        self.assertEqual(llm["cost_microusd_total"], 0)
        self.assertEqual(report["status"], "incomplete")

    def test_trace_rejects_selector_candidate_not_in_current_telemetry(self):
        cell = evaluation.build_schedule()[0]
        engine = {"raw_seed": cell["seed"], "effective_seed": strength._mix_seed(cell["seed"]),
                  "scenario": cell["scenario"], "factions": [cell["faction"]] * 2,
                  "algorithms": strength._expected_algorithms(cell),
                  "recruitment_policies": [cell["recruit1_policy"], cell["recruit2_policy"]],
                  "first_side": 0, "second_gold": 0, "side_turn_cap": cell["max_side_turns"],
                  "starting_gold": [cell["gold"]] * 2, "completed_side_turns": 1,
                  "winner_side": cell["controlled_side"], "termination_reason": "winner"}
        telemetry = {"selector_invoked": True, "candidates": [{"candidate_id": "greedy"}],
                     "selected_candidate_id": "unknown", "fallback_reason": None,
                     "response_status": "selected"}
        trace = [{"type": "metadata", "input_seed": cell["seed"]},
                 {"type": "coordinated_decision", "side": cell["controlled_side"],
                  "telemetry": telemetry},
                 {"type": "terminal", "side_turns_executed": 1}]
        with self.assertRaisesRegex(ValueError, "absent from telemetry"):
            evaluation.validate_trace(cell, "coordinated-llm", engine, trace)

    def test_trace_accepts_rust_accepted_status_and_checks_fallback_evidence(self):
        cell = evaluation.build_schedule()[0]
        engine = {"raw_seed": cell["seed"], "effective_seed": strength._mix_seed(cell["seed"]),
                  "scenario": cell["scenario"], "factions": [cell["faction"]] * 2,
                  "algorithms": strength._expected_algorithms(cell),
                  "recruitment_policies": [cell["recruit1_policy"], cell["recruit2_policy"]],
                  "first_side": 0, "second_gold": 0, "side_turn_cap": cell["max_side_turns"],
                  "starting_gold": [cell["gold"]] * 2, "completed_side_turns": 1,
                  "winner_side": cell["controlled_side"], "termination_reason": "winner"}
        telemetry = {"selector_invoked": True,
                     "candidates": [{"candidate_id": "greedy"}, {"candidate_id": "objective"}],
                     "baseline_candidate_id": "greedy", "selected_candidate_id": "objective",
                     "fallback_reason": None, "response_status": "accepted"}
        trace = [{"type": "metadata", "input_seed": cell["seed"]},
                 {"type": "coordinated_decision", "side": cell["controlled_side"],
                  "telemetry": telemetry},
                 {"type": "terminal", "side_turns_executed": 1}]
        result = evaluation.validate_trace(cell, "coordinated-llm", engine, trace)
        self.assertEqual(result["decision_count"], 1)

        telemetry.update({"selected_candidate_id": "objective", "fallback_reason": "timeout",
                          "response_status": "error"})
        with self.assertRaisesRegex(ValueError, "deterministic baseline"):
            evaluation.validate_trace(cell, "coordinated-llm", engine, trace)
        telemetry.update({"selected_candidate_id": "greedy", "response_status": "accepted"})
        with self.assertRaisesRegex(ValueError, "fallback has unexplained status"):
            evaluation.validate_trace(cell, "coordinated-llm", engine, trace)

    def test_trace_rejects_selector_in_baseline_treatment(self):
        cell = evaluation.build_schedule()[0]
        engine = {"raw_seed": cell["seed"], "effective_seed": strength._mix_seed(cell["seed"]),
                  "scenario": cell["scenario"], "factions": [cell["faction"]] * 2,
                  "algorithms": strength._expected_algorithms(cell),
                  "recruitment_policies": [cell["recruit1_policy"], cell["recruit2_policy"]],
                  "first_side": 0, "second_gold": 0, "side_turn_cap": cell["max_side_turns"],
                  "starting_gold": [cell["gold"]] * 2, "completed_side_turns": 1,
                  "winner_side": cell["controlled_side"], "termination_reason": "winner"}
        trace = [{"type": "metadata", "input_seed": cell["seed"]},
                 {"type": "coordinated_decision", "side": cell["controlled_side"],
                  "telemetry": {"selector_invoked": True}},
                 {"type": "terminal", "side_turns_executed": 1}]
        with self.assertRaisesRegex(ValueError, "baseline treatment invoked selector"):
            evaluation.validate_trace(cell, "coordinated-baseline", engine, trace)


if __name__ == "__main__":
    unittest.main()
