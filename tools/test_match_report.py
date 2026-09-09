import unittest

from .match_report import aggregate_publication, classify
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
            "explicit_done": 1, "implicit_end_turn": 1, "selective": 0, "timeout": 0,
            "forced_partial_limit": 0})
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

    def test_partial_limit_finish_is_not_model_awareness(self):
        report = classify([
            {"type": "metadata", "finish_telemetry_available": True},
            {"type": "partial_limit_finish", "state_revision": 8},
            {"type": "turn_boundary", "accepted": True, "state_revision": 8,
             "authored_finish_kind": "selective", "executed_finish_kind": "selective"},
            {"type": "turn_boundary", "accepted": True, "state_revision": 9,
             "authored_finish_kind": "explicit_done", "executed_finish_kind": "explicit_done"},
        ])
        self.assertEqual(report["forced_partial_limit_finishes"], 1)
        self.assertEqual(report["awareness_numerator"], 1)
        self.assertEqual(report["awareness_denominator"], 2)
        self.assertEqual(report["awareness_rate"], 0.5)

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

    def test_decision_annotation_coverage_uses_final_submissions(self):
        valid = {"status": "valid", "decisions": [{"orders": [0], "rules": ["S1", "T1"]}]}
        report = classify([
            {"type": "model_request", "request_id": "tool", "decision_annotation": {"status": "not_applicable"}},
            {"type": "model_request", "request_id": "discarded", "decision_annotation": valid},
            {"type": "forwarded_orders", "request_id": "r1", "orders": [{"action": "Move"}],
             "decision_annotation": valid},
            {"type": "forwarded_orders", "request_id": "r2", "orders": [{"action": "Done"}],
             "decision_annotation": {"status": "missing", "decisions": []}},
            {"type": "forwarded_orders", "request_id": "r3", "orders": [{"action": "Move"}],
             "decision_annotation": {"status": "invalid", "decisions": [], "error": "bad"}},
            {"type": "forwarded_orders", "source": "generated_greedy", "orders": [{"action": "Move"}]},
            {"type": "forwarded_orders", "request_id": "inapplicable", "orders": [{"action": "EndTurn"}],
             "decision_annotation": {"status": "not_applicable"}},
        ])
        self.assertEqual(report["decision_annotations"], {
            "submitted_batches": 3, "valid_batches": 1, "missing_batches": 1,
            "invalid_batches": 1, "coverage": 1 / 3, "rule_counts": {"S1": 1, "T1": 1}})

    def test_decision_annotation_coverage_is_null_without_submissions(self):
        report = classify([{"type": "metadata"},
                           {"type": "forwarded_orders", "source": "generated_greedy",
                            "orders": [{"action": "Move"}]}])
        self.assertEqual(report["decision_annotations"]["coverage"], None)
        self.assertEqual(report["decision_annotations"]["submitted_batches"], 0)

    def test_publication_attempts_is_unknown_without_a_validation_log(self):
        report = classify([{"type": "metadata"}])
        self.assertIsNone(report["publication_attempts"])

    def test_publication_attempts_distinguishes_first_attempt_repaired_and_unresolved(self):
        summary = aggregate_publication([
            {"request_id": "r1", "timestamp": 1, "status": "valid"},
            {"request_id": "r2", "timestamp": 1, "status": "invalid"},
            {"request_id": "r2", "timestamp": 2, "status": "valid"},
            {"request_id": "r3", "timestamp": 1, "status": "invalid"},
            {"request_id": "r3", "timestamp": 2, "status": "invalid"},
        ])
        self.assertEqual(summary, {
            "requests": 3, "first_attempt_valid": 1, "repaired": 1,
            "unresolved": 1, "total_attempts": 5})

    def test_publication_attempts_terminal_failure_visible_with_no_later_prompt(self):
        # Only one attempt was ever recorded for this request and it never
        # published; this must stay visible as unresolved rather than being
        # dropped for lack of a later prompt in the match log.
        summary = aggregate_publication([
            {"request_id": "only", "timestamp": 1, "status": "invalid", "error": "bad"},
        ])
        self.assertEqual(summary["unresolved"], 1)
        self.assertEqual(summary["requests"], 1)

    def test_publication_attempts_orders_by_timestamp_not_log_order(self):
        # A first-attempt success recorded after an unrelated later-timestamped
        # entry in file order must not be miscounted as repaired.
        summary = aggregate_publication([
            {"request_id": "r1", "timestamp": 5, "status": "valid"},
            {"request_id": "r1", "timestamp": 1, "status": "valid"},
        ])
        self.assertEqual(summary["first_attempt_valid"], 1)
        self.assertEqual(summary["repaired"], 0)

    def test_publication_attempts_included_alongside_final_annotations(self):
        valid = {"status": "valid", "decisions": [{"orders": [0], "rules": ["T8"]}]}
        report = classify(
            [{"type": "forwarded_orders", "request_id": "r1", "orders": [{"action": "EndTurn"}],
              "decision_annotation": valid}],
            publication_records=[{"request_id": "r1", "timestamp": 1, "status": "valid"}])
        self.assertEqual(report["decision_annotations"]["valid_batches"], 1)
        self.assertEqual(report["publication_attempts"], {
            "requests": 1, "first_attempt_valid": 1, "repaired": 0,
            "unresolved": 0, "total_attempts": 1})


if __name__ == "__main__":
    unittest.main()
