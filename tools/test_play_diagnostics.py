"""Tests for the factual play diagnostics computed against restored state.

These drive `tools/play_diagnostics.py` with synthetic query responses
shaped like the real `greedy_driver.rs` query bodies (`turn_options`,
`recruit_options`, `tactical_surface.recruitment`, `inspect_unit`), and with
synthetic event/state snapshots shaped like `norrust_core/src/events.rs`.
No driver subprocess and no model are involved.
"""
from __future__ import annotations

import unittest

from . import play_diagnostics as diag


class LegalRemainingOpportunitiesTests(unittest.TestCase):
    def test_unused_flag_without_useful_action_is_not_a_missed_opportunity(self):
        # Unit 7 is eligible (present in turn_options at all means it has an
        # unused move-or-attack flag) but every reachable position has no
        # attackable target and no village to capture.
        turn_options = {"units": [{
            "unit_id": 7,
            "positions": [
                {"col": 3, "row": 3, "current": True, "movable": False, "target_ids": []},
                {"col": 4, "row": 3, "current": False, "movable": True, "target_ids": []},
                {"col": 2, "row": 3, "current": False, "movable": True, "target_ids": []},
            ],
        }]}
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=[])
        self.assertEqual(result["units_with_opportunity"], [])
        self.assertEqual(len(result["units_without_useful_action"]), 1)
        self.assertEqual(result["units_without_useful_action"][0]["unit_id"], 7)
        self.assertEqual(
            result["units_without_useful_action"][0]["reason"],
            "no_attack_or_capture_reachable")

    def test_unit_with_reachable_attack_is_reported_as_opportunity(self):
        turn_options = {"units": [{
            "unit_id": 9,
            "positions": [
                {"col": 5, "row": 5, "current": True, "movable": False, "target_ids": [21]},
            ],
        }]}
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=[])
        self.assertEqual(len(result["units_with_opportunity"]), 1)
        self.assertEqual(result["units_with_opportunity"][0]["unit_id"], 9)
        self.assertEqual(
            result["units_with_opportunity"][0]["attack_positions"][0]["target_ids"], [21])
        self.assertEqual(result["units_without_useful_action"], [])

    def test_unit_with_reachable_village_capture_is_reported_as_opportunity(self):
        turn_options = {"units": [{
            "unit_id": 3,
            "positions": [
                {"col": 1, "row": 1, "current": True, "movable": False, "target_ids": []},
                {"col": 1, "row": 2, "current": False, "movable": True, "target_ids": []},
            ],
        }]}
        villages = [{"col": 1, "row": 2, "owner": 1}]
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=villages)
        self.assertEqual(len(result["units_with_opportunity"]), 1)
        self.assertEqual(
            result["units_with_opportunity"][0]["capture_positions"],
            [{"col": 1, "row": 2, "before_owner": 1}])

    def test_own_village_is_not_a_capture_opportunity(self):
        turn_options = {"units": [{
            "unit_id": 3,
            "positions": [
                {"col": 1, "row": 2, "current": False, "movable": True, "target_ids": []},
            ],
        }]}
        villages = [{"col": 1, "row": 2, "owner": 0}]  # already ours
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=villages)
        self.assertEqual(result["units_with_opportunity"], [])

    def test_missing_villages_marks_capture_coverage_unknown_not_absent(self):
        turn_options = {"units": [{
            "unit_id": 3,
            "positions": [{"col": 1, "row": 2, "current": False, "movable": True, "target_ids": []}],
        }]}
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=None)
        record = result["units_without_useful_action"][0]
        self.assertEqual(record["village_capture_coverage"], diag.UNKNOWN)

    def test_enumeration_cap_is_reported_and_coverage_marked_incomplete(self):
        turn_options = {"units": [
            {"unit_id": i, "positions": []} for i in range(5)
        ]}
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=[], unit_enumeration_cap=5)
        self.assertEqual(result["coverage"]["enumeration_cap"], 5)
        self.assertFalse(result["coverage"]["complete"])
        self.assertIn("cap", result["coverage"]["note"])

    def test_no_cap_and_full_list_reports_complete_coverage(self):
        turn_options = {"units": []}
        result = diag.legal_remaining_opportunities(
            turn_options, None, active_faction=0, villages=[])
        self.assertTrue(result["coverage"]["complete"])
        self.assertIsNone(result["coverage"]["enumeration_cap"])

    def test_missing_turn_options_reports_missing_evidence_not_zero(self):
        result = diag.legal_remaining_opportunities(None, None, active_faction=0)
        self.assertEqual(result["evidence_status"], diag.EVIDENCE_MISSING)
        self.assertEqual(result["recruitment_opportunity"], diag.UNKNOWN)

    def test_recruit_options_opportunity_requires_affordable_and_placeable(self):
        turn_options = {"units": []}
        recruit_options = {
            "side_can_place": True,
            "placement_hexes": [{"col": 0, "row": 0}],
            "options": [{"def_id": "swordsman", "cost": 20, "affordable": True},
                        {"def_id": "knight", "cost": 100, "affordable": False}],
        }
        result = diag.legal_remaining_opportunities(
            turn_options, recruit_options, active_faction=0, villages=[])
        self.assertTrue(result["recruitment_opportunity"]["is_opportunity"])
        self.assertEqual(result["recruitment_opportunity"]["affordable_options"], ["swordsman"])

    def test_recruit_options_not_placeable_is_not_an_opportunity(self):
        turn_options = {"units": []}
        recruit_options = {
            "side_can_place": False,
            "placement_hexes": [],
            "options": [{"def_id": "swordsman", "cost": 20, "affordable": True}],
        }
        result = diag.legal_remaining_opportunities(
            turn_options, recruit_options, active_faction=0, villages=[])
        self.assertFalse(result["recruitment_opportunity"]["is_opportunity"])


class CandidateActorCoverageTests(unittest.TestCase):
    def test_live_unit_with_opportunity_omitted_from_candidates_is_reported(self):
        turn_options = {"units": [
            {"unit_id": 1, "positions": [{"col": 0, "row": 0, "current": True,
                                           "movable": False, "target_ids": [55]}]},
            {"unit_id": 2, "positions": [{"col": 1, "row": 0, "current": True,
                                           "movable": False, "target_ids": [56]}]},
        ]}
        result = diag.candidate_actor_coverage([1], turn_options)
        omitted_ids = [r["unit_id"] for r in result["omitted_live_units_with_opportunity"]]
        self.assertEqual(omitted_ids, [2])
        # Must never claim exhaustiveness.
        self.assertEqual(result["coverage_status"], "finite_candidate_coverage_only")
        self.assertNotIn("exhaustive", result["coverage_status"])

    def test_all_opportunities_shown_still_reports_finite_not_exhaustive(self):
        turn_options = {"units": [
            {"unit_id": 1, "positions": [{"col": 0, "row": 0, "current": True,
                                           "movable": False, "target_ids": [55]}]},
        ]}
        result = diag.candidate_actor_coverage([1], turn_options)
        self.assertEqual(result["omitted_live_units_with_opportunity"], [])
        self.assertEqual(result["coverage_status"], "finite_candidate_coverage_only")

    def test_missing_turn_options_is_unsupported_analysis(self):
        result = diag.candidate_actor_coverage([1], None)
        self.assertEqual(result["coverage_status"], "unsupported_analysis")
        self.assertEqual(result["omitted_live_units_with_opportunity"], diag.UNKNOWN)


class RecruitmentQueueStatusTests(unittest.TestCase):
    def test_intentional_saving_is_distinguished_from_stalled_queue(self):
        # Legal to recruit, nothing committed, but an explicit reserve
        # policy says the queue is intentionally saving.
        body = {"gold": 500, "reason": "none", "legal_now": True, "options": []}
        result = diag.recruitment_queue_status(
            body, committed_spending=0, reserve_policy={"target": "knight", "target_cost": 500})
        self.assertEqual(result["queue_status"], "unblocked_reserved_by_policy")
        self.assertTrue(result["intent_known"])
        self.assertNotEqual(result["queue_status"], "blocked")

    def test_unreported_non_recruitment_is_never_called_stalled_without_evidence(self):
        # Same facts as above but with NO reserve policy: the honest report
        # is "no recruit committed, intent unknown" -- never "stalled".
        body = {"gold": 500, "reason": "none", "legal_now": True, "options": []}
        result = diag.recruitment_queue_status(body, committed_spending=0, reserve_policy=None)
        self.assertEqual(result["queue_status"], "unblocked_no_recruit_committed")
        self.assertFalse(result["intent_known"])
        self.assertNotIn("stalled", result["queue_status"])

    def test_actually_blocked_queue_reports_blocked_with_reason(self):
        body = {"gold": 5, "reason": "insufficient_gold", "legal_now": False, "options": []}
        result = diag.recruitment_queue_status(body, committed_spending=0)
        self.assertEqual(result["queue_status"], "blocked")
        self.assertEqual(result["blocker_reason"], "insufficient_gold")

    def test_recruit_committed_reports_recruit_committed(self):
        body = {"gold": 100, "reason": "none", "legal_now": True, "options": []}
        result = diag.recruitment_queue_status(body, committed_spending=20)
        self.assertEqual(result["queue_status"], "unblocked_recruit_committed")

    def test_missing_body_reports_unknown_never_zero(self):
        result = diag.recruitment_queue_status(None)
        self.assertEqual(result["gold_available"], diag.UNKNOWN)
        self.assertEqual(result["committed_spending"], diag.UNKNOWN)
        self.assertEqual(result["blocker_reason"], diag.UNKNOWN)
        self.assertNotEqual(result["gold_available"], 0)


class SupportGeometryTests(unittest.TestCase):
    def test_straight_line_proximity_alone_does_not_report_protected(self):
        destination_threats = [{"col": 4, "row": 4, "current": True, "cost": 0, "threats": []}]
        friendly = [{"unit_id": 99, "col": 4, "row": 5}]
        result = diag.support_geometry(destination_threats, friendly_positions=friendly)
        proximity = result["friendly_proximity"][0]
        self.assertTrue(proximity["heuristic"])
        self.assertEqual(proximity["method"], "straight_line_hex_distance")
        self.assertNotIn("protected", proximity)
        self.assertIn("does not establish", proximity["note"])

    def test_legal_path_cost_is_reported_as_observed_not_heuristic(self):
        destination_threats = [{"col": 4, "row": 4, "current": False, "cost": 3, "threats": [12]}]
        result = diag.support_geometry(destination_threats)
        entry = result["destinations"][0]
        self.assertEqual(entry["cost"], 3)
        self.assertEqual(entry["evidence_status"], diag.EVIDENCE_OBSERVED)

    def test_missing_destination_threats_is_missing_evidence(self):
        result = diag.support_geometry(None)
        self.assertEqual(result["evidence_status"], diag.EVIDENCE_MISSING)
        self.assertEqual(result["friendly_proximity"], diag.UNKNOWN)

    def test_no_friendly_positions_supplied_reports_unknown_not_unprotected(self):
        destination_threats = [{"col": 4, "row": 4, "current": True, "cost": 0}]
        result = diag.support_geometry(destination_threats, friendly_positions=None)
        self.assertEqual(result["friendly_proximity"], diag.UNKNOWN)


class VillagesAndMaterialTests(unittest.TestCase):
    def test_village_transition_links_to_exact_event(self):
        initial_state = {"terrain": [{"col": 2, "row": 2, "terrain_id": "village", "owner": 1}]}
        final_state = {"terrain": [{"col": 2, "row": 2, "terrain_id": "village", "owner": 0}]}
        events = [
            {"kind": "move", "unit": 5},
            {"kind": "village", "col": 2, "row": 2, "owner": 0},
        ]
        result = diag.villages_and_material(initial_state, final_state, events)
        self.assertEqual(len(result["village_transitions"]), 1)
        transition = result["village_transitions"][0]
        self.assertEqual(transition["before"], 1)
        self.assertEqual(transition["after"], 0)
        self.assertEqual(transition["linked_events"], [{"event_index": 1, "kind": "village"}])
        self.assertEqual(transition["evidence_status"], diag.EVIDENCE_OBSERVED)

    def test_death_links_to_exact_attack_event(self):
        events = [
            {"kind": "attack",
             "attacker": {"unit": 1, "hp": 10, "xp": 2, "killed": False, "poisoned": False, "slowed": False},
             "defender": {"unit": 2, "hp": 0, "xp": 0, "killed": True, "poisoned": False, "slowed": False},
             "damage_to_defender": 10, "damage_to_attacker": 0},
        ]
        result = diag.villages_and_material(None, None, events)
        self.assertEqual(len(result["deaths"]), 1)
        death = result["deaths"][0]
        self.assertEqual(death["unit_id"], 2)
        self.assertEqual(death["role"], "defender")
        self.assertEqual(death["event_index"], 0)

    def test_no_state_snapshots_reports_material_changes_unknown(self):
        result = diag.villages_and_material(None, None, [])
        self.assertEqual(result["material_changes"], diag.UNKNOWN)

    def test_material_changes_computed_when_both_states_present(self):
        initial_state = {"units": [{"id": 1, "faction": 0}, {"id": 2, "faction": 1}]}
        final_state = {"units": [{"id": 1, "faction": 0}]}
        result = diag.villages_and_material(initial_state, final_state, [])
        self.assertEqual(result["material_changes"], {"units_lost": [2], "units_gained": []})


class BehavioralPatternsTests(unittest.TestCase):
    def test_repeatedly_inactive_unit_is_flagged(self):
        records = [
            {"unit_id": 4, "acted": False},
            {"unit_id": 4, "acted": False},
            {"unit_id": 4, "acted": False},
        ]
        result = diag.behavioral_patterns(records, inactivity_threshold=3)
        self.assertIn(4, result["repeatedly_inactive_units"])

    def test_single_inactive_decision_is_not_flagged(self):
        records = [{"unit_id": 4, "acted": False}]
        result = diag.behavioral_patterns(records, inactivity_threshold=3)
        self.assertEqual(result["repeatedly_inactive_units"], [])

    def test_repair_loop_detected(self):
        records = [{"repair_attempted": True, "repair_succeeded": False}]
        result = diag.behavioral_patterns(records)
        self.assertEqual(len(result["repair_loops"]), 1)

    def test_near_exhausted_budget_detected(self):
        records = [{"budget_remaining": 1, "budget_total": 20}]
        result = diag.behavioral_patterns(records)
        self.assertEqual(len(result["near_exhausted_decision_budgets"]), 1)

    def test_empty_records_reports_missing_evidence(self):
        result = diag.behavioral_patterns([])
        self.assertEqual(result["evidence_status"], diag.EVIDENCE_MISSING)


class CostAndPromptMetricsTests(unittest.TestCase):
    def test_missing_metric_reports_unknown_never_zero(self):
        records = [{"prompt_bytes": None}]
        result = diag.cost_and_prompt_metrics(records)
        self.assertEqual(result["prompt_bytes"]["total"], diag.UNKNOWN)
        self.assertNotEqual(result["prompt_bytes"]["total"], 0)
        self.assertEqual(result["cost"]["total"], diag.UNKNOWN)

    def test_partial_known_values_report_partial_sum_with_counts(self):
        records = [{"prompt_bytes": 100}, {"prompt_bytes": None}, {"prompt_bytes": 50}]
        result = diag.cost_and_prompt_metrics(records)
        total = result["prompt_bytes"]["total"]
        self.assertEqual(total["sum_of_known"], 150)
        self.assertEqual(total["known_count"], 2)
        self.assertEqual(total["total_count"], 3)

    def test_cost_per_completed_side_turn_uses_supplied_denominator(self):
        records = [{"cost": 0.5}, {"cost": 0.5}]
        result = diag.cost_and_prompt_metrics(records, completed_side_turns=2)
        self.assertEqual(result["cost"]["total"], 1.0)
        self.assertEqual(result["cost"]["per_completed_side_turn"], 0.5)

    def test_missing_denominator_reports_rate_unknown(self):
        records = [{"cost": 0.5}]
        result = diag.cost_and_prompt_metrics(records, completed_side_turns=None)
        self.assertEqual(result["cost"]["per_completed_side_turn"], diag.UNKNOWN)

    def test_cache_accounting_pulled_from_usage_field(self):
        records = [{"usage": {"cache_read_tokens": 100, "cache_write_tokens": 50}}]
        result = diag.cost_and_prompt_metrics(records)
        self.assertEqual(result["cache_accounting"]["cache_read_tokens_total"], 100)
        self.assertEqual(result["cache_accounting"]["cache_write_tokens_total"], 50)

    def test_no_records_is_missing_evidence(self):
        result = diag.cost_and_prompt_metrics([])
        self.assertEqual(result["evidence_status"], diag.EVIDENCE_MISSING)


class QueryFnProtocolTests(unittest.TestCase):
    def test_query_body_returns_observed_on_ok_true_with_dict_body(self):
        def query_fn(payload):
            self.assertEqual(payload["what"], "turn_options")
            return {"ok": True, "body": {"units": []}}
        body, status = diag._query_body(query_fn, {"what": "turn_options"})
        self.assertEqual(body, {"units": []})
        self.assertEqual(status, diag.EVIDENCE_OBSERVED)

    def test_query_body_returns_missing_on_ok_false(self):
        def query_fn(payload):
            return {"ok": False, "code": "stale_state"}
        body, status = diag._query_body(query_fn, {"what": "turn_options"})
        self.assertIsNone(body)
        self.assertEqual(status, diag.EVIDENCE_MISSING)

    def test_query_body_returns_missing_on_exception(self):
        def query_fn(payload):
            raise RuntimeError("driver closed")
        body, status = diag._query_body(query_fn, {"what": "turn_options"})
        self.assertIsNone(body)
        self.assertEqual(status, diag.EVIDENCE_MISSING)


if __name__ == "__main__":
    unittest.main()
