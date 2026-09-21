"""Unit tests for tools.strategy_consequences."""
from __future__ import annotations

import json
import copy
import unittest

from .strategy_consequences import (
    extract_candidate_consequences,
    format_consequences_comparison,
)


class StrategyConsequencesTests(unittest.TestCase):

    def _sample_preview_body(self) -> dict:
        return {
            "mode": "forecast",
            "phase": "final",
            "bounded_rollout": False,
            "state_revision": 5,
            "coverage": {
                "forecast": "conditional_pre_finish",
                "delegated_sweep": "unavailable",
                "threats": "pre_finish",
                "post_sweep": "unavailable",
            },
            "candidates": [
                {
                    "valid": True,
                    "assumption": "all forecast combatants survive in place",
                    "summary": {
                        "gold_before": 100,
                        "gold_after": 85,
                        "units_before": 3,
                        "units_after": 3,
                        "recruiters": [{"unit_id": 1, "hp": 30}],
                        "affordable_recruitment_remaining": True,
                    },
                    "forecasts": [
                        {
                            "attacker_id": 2,
                            "defender_id": 5,
                            "forecast": {
                                "outcome_bps": [3000, 6500, 500],
                                "expected_damage_tenths": [125, 40],
                            },
                        }
                    ],
                    "recruiter_threats": {
                        "recruiters": [
                            {
                                "recruiter_id": 1,
                                "hp": 30,
                                "distinct_attacker_count": 1,
                                "max_incoming_sum": 9,
                                "lethal_attackers_needed": None,
                                "origins_conflict": False,
                                "open_distinct_attacker_count": 2,
                                "open_max_incoming_sum": 18,
                                "open_lethal_attackers_needed": 3,
                                "open_origins_conflict": True,
                            }
                        ]
                    },
                    "exposure": {
                        "units": [
                            {
                                "unit_id": 2,
                                "hp": 22,
                                "col": 5,
                                "row": 6,
                                "distinct_attacker_count": 1,
                                "max_incoming_sum": 10,
                                "lethal_attackers_needed": 2,
                                "open_distinct_attacker_count": 1,
                                "open_max_incoming_sum": 10,
                                "open_lethal_attackers_needed": 2,
                            }
                        ]
                    },
                }
            ],
        }

    def test_extract_complete_consequences(self):
        body = self._sample_preview_body()
        cons = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(cons["coverage"], "complete")
        self.assertEqual(cons["forecast_phase"], "final")
        self.assertEqual(cons["assumption"], "all forecast combatants survive in place")
        self.assertEqual(cons["gold_change"], -15)

        # Attacks
        self.assertEqual(len(cons["attacks"]), 1)
        att = cons["attacks"][0]
        self.assertEqual(att["attacker_id"], 2)
        self.assertEqual(att["target_id"], 5)
        self.assertEqual(att["defender_killed"], "30%")
        self.assertEqual(att["both_survive"], "65%")
        self.assertEqual(att["attacker_killed"], "5%")
        self.assertEqual(att["expected_damage_to_defender"], "12.5HP")
        self.assertEqual(att["attacker_retaliation"], "4HP")

        # Recruiter exposure
        rec = cons["recruiter_exposure"]
        self.assertIsNotNone(rec)
        self.assertEqual(rec["recruiter_id"], 1)
        self.assertEqual(rec["hp"], "30HP")
        self.assertEqual(rec["direct_attackers"], "1")
        self.assertEqual(rec["direct_max"], "9HP")
        self.assertEqual(rec["direct_lethal_needed"], "null (unreachable under supplied maximum volleys)")
        self.assertEqual(rec["open_attackers"], "2")
        self.assertEqual(rec["open_max"], "18HP")
        self.assertEqual(rec["open_lethal_needed"], "3")

        # Friendly exposure
        self.assertEqual(len(cons["friendly_exposure"]), 1)
        u = cons["friendly_exposure"][0]
        self.assertEqual(u["unit_id"], 2)
        self.assertEqual(u["hp"], "22HP")
        self.assertEqual(u["direct_attackers"], "1")

    def test_extract_missing_gold_yields_partial_coverage(self):
        body = self._sample_preview_body()
        del body["candidates"][0]["summary"]
        cons = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(cons["coverage"], "partial")
        self.assertEqual(cons["gold_change"], "unknown")
        self.assertIn("gold_change", cons["missing"])

    def test_missing_fields_are_unknown_while_authoritative_empty_is_none(self):
        body = self._sample_preview_body()
        candidate = body["candidates"][0]
        for field in ("forecasts", "recruiter_threats", "exposure"):
            candidate.pop(field)
        missing = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(missing["coverage"], "partial")
        self.assertEqual(missing["field_coverage"]["attacks"], "unknown")
        self.assertEqual(missing["field_coverage"]["recruiter_exposure"], "unknown")
        self.assertEqual(missing["field_coverage"]["friendly_exposure"], "unknown")
        rendered = format_consequences_comparison(
            [{"option_ids": ["a"], "consequences": missing}], "d", 5)
        self.assertIn("attack forecasts: unknown", rendered)
        self.assertIn("recruiter exposure: unknown", rendered)
        self.assertIn("friendly unit exposure: unknown", rendered)
        self.assertNotIn("attack forecasts: none", rendered)
        self.assertNotIn("recruiter exposure: none", rendered)
        self.assertNotIn("friendly unit exposure: none", rendered)

        empty = self._sample_preview_body()
        empty["candidates"][0]["forecasts"] = []
        empty["candidates"][0]["recruiter_threats"] = {"recruiters": []}
        empty["candidates"][0]["exposure"] = {"units": []}
        known_empty = extract_candidate_consequences(empty, 0, expected_revision=5)
        self.assertEqual(known_empty["coverage"], "complete")
        rendered_empty = format_consequences_comparison(
            [{"option_ids": ["a"], "consequences": known_empty}], "d", 5)
        self.assertIn("attack forecasts: none", rendered_empty)
        self.assertIn("recruiter exposure: none", rendered_empty)
        self.assertIn("friendly unit exposure: none", rendered_empty)

    def test_forecast_envelope_requires_scope_revision_and_candidate_validity(self):
        body = self._sample_preview_body()
        for mutation, reason in (
            (lambda b: b.pop("state_revision"), "forecast_revision_missing"),
            (lambda b: b.pop("mode"), "forecast_mode_invalid"),
            (lambda b: b.pop("coverage"), "forecast_coverage_missing"),
        ):
            malformed = copy.deepcopy(body)
            mutation(malformed)
            result = extract_candidate_consequences(malformed, 0, expected_revision=5)
            self.assertEqual(result["coverage"], "unavailable")
            self.assertEqual(result["reason"], reason)
        malformed = copy.deepcopy(body)
        malformed["candidates"][0].pop("valid")
        result = extract_candidate_consequences(malformed, 0, expected_revision=5)
        self.assertEqual(result["reason"], "candidate_validity_missing")

    def test_invalid_metrics_and_truncated_coverage_never_become_none(self):
        body = self._sample_preview_body()
        candidate = body["candidates"][0]
        candidate["forecasts"] = [{}]
        candidate["recruiter_threats"] = {"recruiters": [{"recruiter_id": 1, "hp": 30}]}
        candidate["exposure"] = {"units": [{"unit_id": 2, "hp": 22,
                                               "distinct_attacker_count": 0}]}
        body["coverage"]["threats"] = "truncated"
        result = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(result["field_coverage"]["attacks"], "unknown")
        self.assertEqual(result["field_coverage"]["recruiter_exposure"], "unknown")
        self.assertEqual(result["field_coverage"]["friendly_exposure"], "partial")
        rendered = format_consequences_comparison(
            [{"option_ids": ["partial"], "consequences": result}], "d", 5)
        self.assertIn("coverage incomplete", rendered)
        self.assertNotIn("recruiter exposure: none", rendered)
        self.assertNotIn("friendly unit exposure: none", rendered)

    def test_missing_recruiter_metric_is_partial_not_none(self):
        body = self._sample_preview_body()
        del body["candidates"][0]["recruiter_threats"]["recruiters"][0][
            "open_max_incoming_sum"]
        result = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(result["coverage"], "partial")
        self.assertEqual(result["field_coverage"]["recruiter_exposure"], "partial")
        rendered = format_consequences_comparison(
            [{"option_ids": ["damaged"], "consequences": result}], "d", 5)
        self.assertIn("Projected recruiter exposure", rendered)
        self.assertNotIn("recruiter exposure: none", rendered)

    def test_invalid_threat_counts_and_forecast_elements_stay_uncertain(self):
        missing_count = self._sample_preview_body()
        recruiter = missing_count["candidates"][0]["recruiter_threats"]["recruiters"][0]
        del recruiter["open_distinct_attacker_count"]
        result = extract_candidate_consequences(missing_count, 0, expected_revision=5)
        self.assertEqual(result["field_coverage"]["recruiter_exposure"], "partial")

        invalid_count = self._sample_preview_body()
        invalid_count["candidates"][0]["exposure"]["units"][0][
            "distinct_attacker_count"] = True
        result = extract_candidate_consequences(invalid_count, 0, expected_revision=5)
        self.assertEqual(result["field_coverage"]["friendly_exposure"], "partial")

        invalid_forecast = self._sample_preview_body()
        forecast = invalid_forecast["candidates"][0]["forecasts"][0]["forecast"]
        forecast["outcome_bps"] = [None, None, None]
        forecast["expected_damage_tenths"] = [None, None]
        result = extract_candidate_consequences(invalid_forecast, 0, expected_revision=5)
        self.assertEqual(result["field_coverage"]["attacks"], "partial")
        rendered = format_consequences_comparison(
            [{"option_ids": ["invalid"], "consequences": result}], "d", 5)
        self.assertIn("unknown", rendered)

    def test_partial_empty_lists_are_unknown(self):
        body = self._sample_preview_body()
        candidate = body["candidates"][0]
        candidate["forecasts"] = []
        candidate["recruiter_threats"] = {"recruiters": []}
        candidate["exposure"] = {"units": []}
        body["coverage"]["forecast"] = "truncated"
        body["coverage"]["threats"] = "partial"
        result = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(result["coverage"], "partial")
        rendered = format_consequences_comparison(
            [{"option_ids": ["partial-empty"], "consequences": result}], "d", 5)
        self.assertIn("attack forecasts: unknown", rendered)
        self.assertIn("recruiter exposure: unknown", rendered)
        self.assertIn("friendly unit exposure: unknown", rendered)

    def test_formatter_bounds_long_multibyte_cards_and_keeps_choose_json(self):
        body = self._sample_preview_body()
        base = extract_candidate_consequences(body, 0, expected_revision=5)
        noisy = copy.deepcopy(base)
        noisy["assumption"] = "条件付き " * 4
        noisy["attacks"] = noisy["attacks"] * 5
        noisy["friendly_exposure"] = noisy["friendly_exposure"] * 8
        rendered = format_consequences_comparison(
            [
                {"option_ids": ["card-a"], "finish_turn": False, "consequences": noisy},
                {"option_ids": ["card-b"], "finish_turn": True, "consequences": noisy},
            ],
            "decision",
            5,
        )
        self.assertLessEqual(len(rendered.encode("utf-8")), 3072)
        self.assertIn('"option_ids":["card-a"]', rendered)
        self.assertIn('"option_ids":["card-b"]', rendered)
        self.assertIn("Consequences: complete", rendered)
        self.assertIn("Current live state revision is 5.", rendered)

    def test_pathological_ids_use_bounded_fallback_without_clipping(self):
        huge = "雪" * 4000
        rendered = format_consequences_comparison(
            [{"option_ids": [huge], "consequences": {"coverage": "complete"}}],
            "decision",
            5,
        )
        self.assertLessEqual(len(rendered.encode("utf-8")), 3072)
        self.assertIn("existing engine-validated legal menu", rendered)
        self.assertNotIn(huge, rendered)

    def test_stale_state_revision_invalidates_consequences(self):
        body = self._sample_preview_body()
        cons = extract_candidate_consequences(body, 0, expected_revision=6)
        self.assertEqual(cons["coverage"], "unavailable")
        self.assertEqual(cons["reason"], "stale_state_revision")

    def test_candidate_validation_failure_marks_unavailable_with_error(self):
        body = self._sample_preview_body()
        body["candidates"][0]["valid"] = False
        body["candidates"][0]["preview_error"] = {"code": "unit_not_found", "message": "target died"}
        cons = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(cons["coverage"], "unavailable")
        self.assertIn("target died", cons["reason"])

    def test_candidate_index_out_of_bounds_marks_unavailable(self):
        body = self._sample_preview_body()
        cons = extract_candidate_consequences(body, 2, expected_revision=5)
        self.assertEqual(cons["coverage"], "unavailable")

    def test_format_consequences_comparison_neutral_and_bounded(self):
        body = self._sample_preview_body()
        c1 = extract_candidate_consequences(body, 0, expected_revision=5)
        c2 = dict(c1, gold_change=0, assumption="none")

        selections = [
            {"option_ids": ["opt-1"], "finish_turn": False, "consequences": c1},
            {"option_ids": ["opt-2", "opt-3"], "finish_turn": True, "consequences": c2},
        ]

        rendered = format_consequences_comparison(selections, "dec-42", 5)

        # Header and simulation label
        self.assertIn("SIMULATION — NOT EXECUTED", rendered)
        self.assertIn("Estimates are conditional on engine forecast assumptions", rendered)

        # Neutral ordering
        self.assertIn("Selection 1 (option_ids=['opt-1'], finish_turn=false):", rendered)
        self.assertIn("Selection 2 (option_ids=['opt-2', 'opt-3'], finish_turn=true):", rendered)

        # Prohibit biased editorial words
        for biased in ("best", "safe", "preferred", "recommended", "optimal"):
            self.assertNotIn(biased, rendered.lower())

        # Submit-ready choose responses present
        self.assertIn('To choose this selection: {"kind":"choose","decision_id":"dec-42","option_ids":["opt-1"],"finish_turn":false}', rendered)
        self.assertIn('To choose this selection: {"kind":"choose","decision_id":"dec-42","option_ids":["opt-2","opt-3"],"finish_turn":true}', rendered)

        # Live revision reminder
        self.assertIn("Current live state revision is 5.", rendered)

        # Length bound < 3 KiB UTF-8
        self.assertLess(len(rendered.encode("utf-8")), 3072)

    def test_format_consequences_empty_when_no_consequences(self):
        selections = [
            {"option_ids": ["opt-1"], "finish_turn": False},
        ]
        rendered = format_consequences_comparison(selections, "dec-42", 5)
        self.assertEqual(rendered, "")

    def test_partial_preview_pure_relocation_consequences_known(self):
        body = self._sample_preview_body()
        body["phase"] = "partial"
        cand = body["candidates"][0]
        cand["forecasts"] = []
        cand["assumption"] = "none"
        cand["summary"]["gold_after"] = cand["summary"]["gold_before"]
        cons = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(cons["coverage"], "complete")
        self.assertEqual(cons["forecast_phase"], "partial")
        self.assertEqual(cons["assumption"], "none")
        self.assertEqual(cons["assumptions"], "none")
        self.assertEqual(cons["gold_change"], 0)
        self.assertEqual(cons["attacks"], [])
        self.assertEqual(cons["field_coverage"]["recruiter_exposure"], "known")
        self.assertEqual(cons["field_coverage"]["friendly_exposure"], "known")
        self.assertIsNotNone(cons["recruiter_exposure"])
        self.assertEqual(cons["recruiter_exposure"]["recruiter_id"], 1)

    def test_partial_preview_relocation_plus_attacks_consequences_known(self):
        body = self._sample_preview_body()
        body["phase"] = "partial"
        cons = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(cons["coverage"], "complete")
        self.assertEqual(cons["forecast_phase"], "partial")
        self.assertEqual(cons["assumption"], "all forecast combatants survive in place")
        self.assertEqual(cons["assumptions"], "all forecast combatants survive in place")
        self.assertEqual(len(cons["attacks"]), 1)
        self.assertEqual(cons["field_coverage"]["recruiter_exposure"], "known")
        self.assertEqual(cons["field_coverage"]["friendly_exposure"], "known")

    def test_invalid_candidate_partial_preview_never_displays_known_safety(self):
        body = self._sample_preview_body()
        body["phase"] = "partial"
        cand = body["candidates"][0]
        cand["valid"] = False
        cand["recruiter_threats"] = None
        cand["exposure"] = None
        cand["preview_error"] = {"code": "destination_occupied", "message": "destination occupied"}
        cons = extract_candidate_consequences(body, 0, expected_revision=5)
        self.assertEqual(cons["coverage"], "unavailable")
        self.assertIsNone(cons["recruiter_exposure"])
        self.assertEqual(cons["friendly_exposure"], [])
        self.assertEqual(cons["field_coverage"]["recruiter_exposure"], "unknown")
        self.assertEqual(cons["field_coverage"]["friendly_exposure"], "unknown")


if __name__ == "__main__":
    unittest.main()
