import unittest

from .match_report import aggregate_publication, classify, load_records
from .llm_client import replay_accepted_progress


class ReportTests(unittest.TestCase):
    def test_recovery_acceptance_is_not_reported_as_commit(self):
        report = classify([
            {"type": "strategy_recovery_outcome", "outcome": "accepted"},
            {"type": "terminal", "terminal_class": "infrastructure_failure",
             "strategy_recovery_dispatched": 1, "strategy_recovery_committed": 0,
             "strategy_recovery_rejected": 0, "strategy_recovery_unavailable": 0},
        ])
        self.assertEqual(report["strategy_recovery"]["dispatched"], 1)
        self.assertEqual(report["strategy_recovery"]["committed"], 0)

    def test_historical_recovery_counters_are_unknown(self):
        report = classify([{"type": "terminal", "terminal_class": "model_invalid"}])
        self.assertTrue(all(value is None for value in report["strategy_recovery"].values()))

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

    def test_historical_budget_stop_is_not_a_model_fault_or_winner(self):
        report = classify([{"type": "terminal", "terminal_class": "model_invalid",
                            "reason": "budget_interrupted",
                            "code": "max_game_total_tokens_exhausted", "winner": 0}])
        self.assertEqual(report["terminal_class"], "budget_interrupted")
        self.assertIsNone(report["winner"])

    def test_type_only_budget_stop_is_not_unfinished_or_a_winner(self):
        report = classify([{"type": "budget_interrupted", "winner": 1}])
        self.assertEqual(report["terminal_class"], "budget_interrupted")
        self.assertIsNone(report["winner"])

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

    def test_controlled_finish_ownership_includes_routine_model_and_delegated(self):
        # Strategy can finish through the deterministic routine (including an
        # empty FinishWithGreedy), while ordinary and delegated model paths
        # use their own committed event sources.  The opponent's greedy
        # boundary must remain on its separate axis.
        events = [
            {"kind": "end_turn", "source": "routine", "ended_faction": 0,
             "active_faction": 1},
            {"kind": "end_turn", "source": "model", "ended_faction": 0,
             "active_faction": 1},
            {"kind": "end_turn", "source": "delegated_greedy", "ended_faction": 0,
             "active_faction": 1},
            {"kind": "end_turn", "source": "greedy", "ended_faction": 1,
             "active_faction": 0},
        ]
        report = classify([
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            *[
                {"type": "turn_boundary", "accepted": True,
                 "side": 0, "authored_finish_kind": "selective",
                 "executed_finish_kind": "selective"}
                for _ in range(3)
            ],
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "side_turns": 4}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "max_turns"},
        ])
        self.assertEqual(report["model_end_turns"], 3)
        self.assertEqual(report["opponent_end_turns"], 1)
        self.assertEqual(report["unknown_end_turns"], 0)
        self.assertFalse(report["accounting_mismatch"])

    def test_end_turn_source_falls_back_to_envelope_and_conflicts_stay_unknown(self):
        report = classify([
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "turn_boundary", "accepted": True, "side": 0,
             "authored_finish_kind": "selective", "executed_finish_kind": "selective"},
            {"type": "driver", "line": {"type": "events", "source": "routine",
                "events": [{"kind": "end_turn", "ended_faction": 0,
                             "active_faction": 1}]}},
            # The source says controlled while the ending faction says
            # opponent.  Retain the event in the total, but do not guess its
            # ownership to satisfy the boundary count.
            {"type": "driver", "line": {"type": "events", "source": "routine",
                "events": [{"kind": "end_turn", "ended_faction": 1,
                             "active_faction": 0}]}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "max_turns"},
        ])
        self.assertEqual(report["model_end_turns"], 1)
        self.assertEqual(report["opponent_end_turns"], 0)
        self.assertEqual(report["unknown_end_turns"], 1)
        self.assertFalse(report["accounting_mismatch"])

    def test_missing_controlled_finish_still_reports_mismatch(self):
        report = classify([
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "turn_boundary", "accepted": True, "side": 0,
             "authored_finish_kind": "selective", "executed_finish_kind": "selective"},
            {"type": "turn_boundary", "accepted": True, "side": 0,
             "authored_finish_kind": "selective", "executed_finish_kind": "selective"},
            {"type": "driver", "line": {"type": "events", "source": "routine",
                "events": [{"kind": "end_turn", "ended_faction": 0,
                             "active_faction": 1}]}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "max_turns"},
        ])
        self.assertEqual(report["model_end_turns"], 1)
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

    def test_strategy_repairs_and_physical_calls_counted(self):
        records = [
            {"type": "metadata", "llm_side": 0},
            {"type": "model", "call": 1},
            {"type": "model", "call": 2},
            {"type": "strategy_response_repair", "error": "engine rejected strategy act: destination occupied"},
            {"type": "model", "call": 3},
            {"type": "strategy_response_repair", "error": "unit not found"},
            {"type": "strategy_batch_validation", "valid": False},
            {"type": "strategy_batch_validation", "valid": False},
        ]
        records.extend({"type": "model", "call": i} for i in range(4, 12))
        records.append({"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1})
        report = classify(records)
        self.assertEqual(report["repairs"], 2)
        self.assertEqual(report["strategy_repairs"], 2)
        self.assertEqual(report["rejected_strategy_proposals"], 2)
        self.assertEqual(report["physical_calls"], 11)
        self.assertEqual(report["model_calls"], 11)
        self.assertEqual(report["terminal_class"], "gameplay")
        self.assertEqual(report["repair_breakdown"], {"engine_rejection": 2})

    def test_terminal_partial_side_turn_opponent_winner_explained(self):
        events = []
        for turn in range(1, 7):
            events.append({"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1, "turn": turn})
            if turn < 6:
                events.append({"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0, "turn": turn})
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "side_turns": 12, "winner": 1}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1},
        ]
        report = classify(records)
        self.assertFalse(report["accounting_mismatch"])
        self.assertEqual(report["completed_engine_turns"], 11)
        self.assertEqual(report["completed_model_turns"], 6)
        self.assertEqual(report["completed_opponent_turns"], 5)
        self.assertEqual(report["terminal_partial_side_turn"], {
            "side_turn": 12,
            "side": 1,
            "owner": "opponent",
            "reason": "winner",
        })

    def test_terminal_partial_side_turn_controlled_winner_explained(self):
        events = []
        for turn in range(1, 6):
            events.append({"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1, "turn": turn})
            events.append({"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0, "turn": turn})
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "side_turns": 11, "winner": 0}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 0},
        ]
        report = classify(records)
        self.assertFalse(report["accounting_mismatch"])
        self.assertEqual(report["completed_engine_turns"], 10)
        self.assertEqual(report["completed_model_turns"], 5)
        self.assertEqual(report["completed_opponent_turns"], 5)
        self.assertEqual(report["terminal_partial_side_turn"], {
            "side_turn": 11,
            "side": 0,
            "owner": "controlled",
            "reason": "winner",
        })

    def test_missing_or_duplicate_boundaries_still_raise_mismatch(self):
        events = [
            {"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1, "turn": 1},
            {"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0, "turn": 1},
        ]
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "side_turns": 8, "winner": 1}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1},
        ]
        report = classify(records)
        self.assertTrue(report["accounting_mismatch"])
        self.assertIn("terminal_side_turns_vs_generated_end_turns", report["accounting_mismatch_reasons"])

    def test_winner_without_driver_side_turns_reports_partial_not_completed(self):
        # This is the shape real archives actually have: the driver only puts
        # an authoritative `side_turns` total on `game_end` when the game
        # reaches max_turns. On a winner termination the final side turn
        # never produces an end_turn transition, so `game_end` carries no
        # `side_turns` field at all (only `turns`). The final, unfinished
        # side turn must be reported as a terminal partial, not folded into
        # completed_side_turns.
        events = [
            {"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1},
            {"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0},
            {"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1},
            {"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0},
            {"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1},
        ]
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "reason": "winner", "turns": 3, "winner": 1}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1},
        ]
        report = classify(records)
        self.assertEqual(report["completed_engine_turns"], 5)
        self.assertEqual(report["completed_side_turns"], 5)
        self.assertEqual(report["terminal_partial_side_turn"], {
            "side_turn": 6,
            "side": 1,
            "owner": "opponent",
            "reason": "winner",
        })

    def test_clean_max_turns_finish_without_winner_is_unchanged(self):
        # Mirrors the one sampled archive with no winner: the driver reports
        # an authoritative side_turns total on game_end, and every side turn
        # it counts actually completed. No terminal partial turn exists.
        events = [
            {"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1},
            {"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0},
        ]
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "reason": "max_turns", "turns": 1, "side_turns": 2}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "max_turns"},
        ]
        report = classify(records)
        self.assertIsNone(report["winner"])
        self.assertEqual(report["completed_engine_turns"], 2)
        self.assertEqual(report["completed_side_turns"], 2)
        self.assertIsNone(report["terminal_partial_side_turn"])

    def test_no_winner_and_no_driver_side_turns_reports_no_partial(self):
        # A non-winner termination (e.g. infrastructure failure) with no
        # authoritative driver total must not be misread as a partial
        # winning turn -- there is no winner to attribute it to.
        events = [
            {"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1},
            {"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0},
        ]
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "terminal", "terminal_class": "infrastructure_failure", "reason": "model_error"},
        ]
        report = classify(records)
        self.assertIsNone(report["winner"])
        self.assertEqual(report["completed_engine_turns"], 2)
        self.assertEqual(report["completed_side_turns"], 2)
        self.assertIsNone(report["terminal_partial_side_turn"])

    def test_repair_discrepancy_reported(self):
        records = [
            {"type": "metadata", "repairs": 0},
            {"type": "strategy_response_repair", "error": "syntax error"},
            {"type": "terminal", "terminal_class": "gameplay"},
        ]
        report = classify(records)
        self.assertEqual(report["repairs"], 1)
        self.assertEqual(report["repair_discrepancy"], {
            "metadata_repairs": 0,
            "proven_repairs": 1,
        })

    def test_recruiter_move_followed_by_death_reports_committed_destination(self):
        records = [
            {"type": "metadata", "llm_side": 0},
            {"type": "driver", "line": {"type": "state", "units": [{"id": 1, "faction": 0, "can_recruit": True, "col": 1, "row": 8, "hp": 27}]}},
            {"type": "driver", "line": {"type": "events", "source": "llm", "events": [
                {"kind": "move", "unit": 1, "from": {"col": 1, "row": 8}, "to": {"col": 0, "row": 11}}
            ]}},
            {"type": "driver", "line": {"type": "events", "source": "greedy", "events": [
                {"kind": "attack", "attacker": {"unit": 23}, "defender": {"unit": 1, "hp": 0, "killed": True}, "damage_to_defender": 14}
            ]}},
            {"type": "driver", "line": {"type": "state", "units": []}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1},
        ]
        report = classify(records)
        outcome = report["recruiter_outcome"]
        self.assertTrue(outcome["death_proven"])
        self.assertFalse(outcome["alive"])
        self.assertEqual(outcome["death_location"], {"col": 0, "row": 11})
        self.assertEqual(outcome["last_proven_live_position"], {"col": 0, "row": 11})
        self.assertEqual(outcome["last_committed_model_action"], {
            "action": "Move", "unit_id": 1, "col": 0, "row": 11
        })

    def test_recruiter_absent_without_death_linkage_returns_unknown_location(self):
        records = [
            {"type": "metadata", "llm_side": 0},
            {"type": "driver", "line": {"type": "state", "units": [{"id": 1, "faction": 0, "can_recruit": True, "col": 1, "row": 8, "hp": 27}]}},
            # Recruiter simply absent in subsequent state with no witnessed lethal event
            {"type": "driver", "line": {"type": "state", "units": []}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1},
        ]
        report = classify(records)
        outcome = report["recruiter_outcome"]
        self.assertFalse(outcome["death_proven"])
        self.assertIsNone(outcome["death_location"])

    def test_simulated_death_from_validate_batch_produces_no_live_death_record(self):
        records = [
            {"type": "metadata", "llm_side": 0},
            {"type": "driver", "line": {"type": "state", "units": [{"id": 1, "faction": 0, "can_recruit": True, "col": 2, "row": 7, "hp": 48}]}},
            # Simulated query replay with death in query type
            {"type": "query", "line": {"type": "events", "events": [{"kind": "death", "unit": 1}]}},
            {"type": "strategy_batch_validation", "valid": False, "validation": {"committed": False}},
            {"type": "terminal", "terminal_class": "gameplay"},
        ]
        report = classify(records)
        outcome = report["recruiter_outcome"]
        self.assertFalse(outcome["death_proven"])
        self.assertTrue(outcome["alive"])
        self.assertEqual(outcome["last_proven_live_hp"], 48)

    def test_strategy_choose_with_zero_generic_choice_handles_still_counts_as_choose(self):
        records = [
            {"type": "model_request", "request_id": "req-1", "raw_output": '{"kind": "choose", "option_ids": ["opt-1"], "finish_turn": true}'},
            {"type": "strategy_validated_selections", "decision_id": "dec-1", "selections": [{"option_ids": ["opt-1"], "finish_turn": True}]},
            {"type": "forwarded_orders", "batch_id": "b-1", "request_id": "req-1", "decision_id": "dec-1", "option_ids": ["opt-1"], "orders": []},
            {"type": "batch_committed", "batch_id": "b-1"},
            {"type": "terminal", "terminal_class": "gameplay", "handle_choices_used": 0},
        ]
        report = classify(records)
        sc = report["strategy_choices"]
        self.assertEqual(sc["response_kinds"], {"choose": 1})
        self.assertEqual(sc["submitted_option_selections"], 1)
        self.assertEqual(sc["committed_option_batches"], 1)
        self.assertEqual(sc["recommendation_adoption"]["committed_exact_matches"], 1)

    def test_rejected_and_duplicated_records_cannot_inflate_committed_counts(self):
        records = [
            {"type": "model_request", "request_id": "req-1", "raw_output": '{"kind": "choose", "option_ids": ["opt-1"], "finish_turn": false}'},
            {"type": "strategy_validated_selections", "decision_id": "dec-1", "selections": [{"option_ids": ["opt-1"], "finish_turn": False}]},
            # Uncommitted forwarded_orders (e.g. rolled back or rejected)
            {"type": "forwarded_orders", "batch_id": "b-rejected", "request_id": "req-1", "decision_id": "dec-1", "option_ids": ["opt-1"], "orders": []},
            {"type": "terminal", "terminal_class": "gameplay"},
        ]
        report = classify(records)
        sc = report["strategy_choices"]
        self.assertEqual(sc["committed_option_batches"], 0)
        self.assertEqual(sc["recommendation_adoption"]["committed_option_id_matches"], 0)

    def test_terminal_partial_turn_fixture_counts(self):
        events = []
        for turn in range(1, 16):
            events.append({"kind": "end_turn", "source": "model", "ended_faction": 0, "active_faction": 1, "turn": turn})
            if turn < 15:
                events.append({"kind": "end_turn", "source": "greedy", "ended_faction": 1, "active_faction": 0, "turn": turn})
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "driver", "line": {"type": "events", "events": events}},
            {"type": "driver", "line": {"type": "game_end", "side_turns": 30, "winner": 1}},
            {"type": "terminal", "terminal_class": "gameplay", "reason": "winner", "winner": 1},
        ]
        report = classify(records)
        self.assertFalse(report["accounting_mismatch"])
        self.assertEqual(report["completed_model_turns"], 15)
        self.assertEqual(report["completed_opponent_turns"], 14)
        self.assertEqual(report["completed_engine_turns"], 29)
        self.assertEqual(report["completed_side_turns"], 29)
        self.assertEqual(report["resolved_side_turns"], 30)
        self.assertEqual(report["terminal_partial_side_turn"], {
            "side_turn": 30,
            "side": 1,
            "owner": "opponent",
            "reason": "winner",
        })

    def test_known_no_sweep_finish_produces_zero_generated_delegated_tactical_actions(self):
        records = [
            {"type": "metadata", "llm_side": 0, "finish_telemetry_available": True},
            {"type": "turn_boundary", "accepted": True, "authored_finish_kind": "FinishWithGreedy",
             "executed_finish_kind": "FinishWithGreedy", "delegated_unit_ids": []},
            {"type": "driver", "line": {"type": "events", "events": [
                {"kind": "end_turn", "source": "delegated_greedy"}
            ]}},
            {"type": "terminal", "terminal_class": "gameplay"},
        ]
        report = classify(records)
        self.assertEqual(report["delegated_tactical_actions"], 0)
        self.assertFalse(report["tactical_delegation_occurred"])

    def test_primary_game_reprocessing_matches_expected_facts(self):
        import hashlib
        from pathlib import Path
        fixture_root = Path(__file__).resolve().parents[1] / "tools/fixtures/strategy_match_report"
        log_path = fixture_root / "primary_reduced.ndjson"
        provenance = (fixture_root / "README.md").read_text()
        self.assertIn(
            "fd771d5c4bfd163cbe4592fe1c761ac8a9fa14b570ff7fb81a07b65ae114b5e8",
            provenance,
            "Original archive hash must remain recorded in fixture provenance",
        )
        actual_hash = hashlib.sha256(log_path.read_bytes()).hexdigest()
        self.assertEqual(
            actual_hash,
            "2745a3ee212865b42ad49f868009b98bf89c427178927af2def0598128f316e6",
            "Reduced fixture hash must be stable",
        )

        records = load_records(log_path)
        report = classify(records)
        sc = report["strategy_choices"]
        self.assertEqual(sc["response_kinds"], {"set_policy": 4, "choose": 29, "finish_turn": 2, "act": 1})
        self.assertEqual(sc["submitted_option_selections"], 29)
        self.assertEqual(sc["committed_option_batches"], 28)
        self.assertEqual(sc["recommendation_adoption"]["issued_menus_with_validated_selections"], 28)
        self.assertEqual(sc["recommendation_adoption"]["committed_option_id_matches"], 2)
        self.assertEqual(sc["recommendation_adoption"]["committed_exact_matches"], 1)
        self.assertEqual(sc["recommendation_adoption"]["custom_combinations"], 26)
        self.assertEqual(sc["recommendation_adoption"]["unresolved_linkage"], 0)

        # Recruiter outcome and death at (0, 11)
        ro = report["recruiter_outcome"]
        self.assertTrue(ro["death_proven"])
        self.assertFalse(ro["alive"])
        self.assertEqual(ro["death_location"], {"col": 0, "row": 11})
        self.assertEqual(ro["last_committed_model_action"], {"action": "Move", "col": 0, "row": 11, "unit_id": 1})

        # Decisive decisions
        dd = report["decisive_decisions"]
        self.assertIsNotNone(dd["first_rejected_choice"])
        self.assertEqual(dd["first_rejected_choice"]["turn"], 9)
        self.assertIsNotNone(dd["last_recruiter_action"])
        self.assertEqual(dd["last_recruiter_action"]["action"]["col"], 0)
        self.assertEqual(dd["last_recruiter_action"]["action"]["row"], 11)


if __name__ == "__main__":
    unittest.main()
