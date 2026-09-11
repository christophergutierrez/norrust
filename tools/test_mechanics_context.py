import unittest

from .llm_client import (
    compact_batch_preview,
    compact_target_inspection,
    compact_tactical_surface,
    compact_unit_inspection,
    enrich_inspected_units,
    enrich_target_inspection,
    game_budget_context,
    memory_provenance,
    prompt_for,
    recover_optional_memory,
)


class ReadableMechanicsTests(unittest.TestCase):
    def test_shared_formatter_scales_raw_values_and_names_exchange_roles(self):
        forecast = {"outcome_bps": [705, 9000, 295],
                    "expected_damage_tenths": [24, 14]}
        rendered = compact_target_inspection({
            "target_id": 9, "hp": 20, "col": 1, "row": 1, "terrain": "flat",
            "attacks": [{"attacker_id": 2, "origin_col": 1, "origin_row": 0,
                         "forecast": forecast}],
        })
        self.assertIn("defender_killed=7.05%", rendered)
        self.assertIn("to_defender=2.4HP", rendered)
        self.assertIn("attacker_retaliation=1.4HP", rendered)
        self.assertNotIn("bps", rendered)
        self.assertNotIn("tenths", rendered)

    def test_focus_and_aggregate_damage_keep_distinct_names(self):
        rendered = compact_batch_preview({"candidates": [{
            "attack_sequences": [{"target_id": 7, "target_hp": 20,
                                   "attacker_ids": [3, 4], "kill_bps": 705,
                                   "expected_damage_tenths": 144}],
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 38, "distinct_attacker_count": 1,
                "max_incoming_sum": 144, "lethal_attackers_needed": None,
                "origins_conflict": False, "focus_kill_bps": [705, 8000, 0],
                "focus_expected_damage_tenths": [24, 40, 60],
            }]},
        }]})
        self.assertIn("kill_probabilities=(7.05%)", rendered)
        self.assertIn("expected_damage=(14.4HP)", rendered)
        self.assertIn("maximum_incoming=144HP", rendered)
        self.assertIn("kill_by_1=7.05%", rendered)
        self.assertIn("damage_from_1=2.4HP", rendered)
        unknown = compact_batch_preview({"candidates": [{
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 10, "distinct_attacker_count": 0,
                "max_incoming_sum": 0, "lethal_attackers_needed": None,
            }]},
        }]})
        self.assertIn("lethal_attacker_count=unknown", unknown)

    def test_readiness_does_not_turn_no_target_into_spent(self):
        rendered = compact_tactical_surface({"units": [{
            "unit_id": 5, "moved": False, "attacked": False, "origins": [],
        }]})
        self.assertIn("readiness=moved=False attacked=False", rendered)
        self.assertIn("none (no_legal_target_from_current_origin)", rendered)
        spent = compact_tactical_surface({"units": [{
            "unit_id": 5, "moved": False, "attacked": True, "origins": [],
        }]})
        self.assertIn("none (already_attacked)", spent)
        all_spent = compact_tactical_surface({"units": [
            {"unit_id": 5, "moved": True, "attacked": True, "origins": []},
            {"unit_id": 6, "moved": False, "attacked": True, "origins": []},
        ]})
        self.assertIn("ATTACK_READINESS ready=none (all attacks spent)", all_spent)

    def test_rules_state_independent_move_attack_and_six_phase_cycle(self):
        prompt = prompt_for({"units": []}, [])
        for text in (
            "one independent Move and one independent Attack",
            "Move then Attack and Attack then Move are legal",
            "Move then Attack then Move is not",
            "odd-r (col,row)",
            "six live labels in order: Dawn, Day, Day, Dusk, Night, Night",
            "no six-recruit turn cap",
        ):
            self.assertIn(text, prompt)

    def test_focused_context_pins_inspection_and_keeps_provenance_internal(self):
        prompt = prompt_for(
            {"state_revision": 12, "units": []}, [], intent="screen recruiter",
            intent_origin={"origin_turn": 3, "origin_revision": 11,
                           "origin_request_id": "r1"},
            agenda={"tasks": [], "holds": []},
            agenda_origin={"origin_turn": 3, "origin_revision": 12,
                           "origin_request_id": "r2"},
            decision_mode="focused")
        self.assertIn("two tiers", prompt)
        self.assertIn("objective_then_local_operation", prompt)
        self.assertIn("stale_revision", prompt)
        self.assertIn("global board, recruiter, economy", prompt)

    def test_budget_suffix_is_bounded_when_sidecar_usage_is_unknown(self):
        class Args:
            max_game_total_tokens = 1000
        context = game_budget_context(Args(), {
            "cumulative_game_total_tokens": 144,
            "game_token_usage_unknown_calls": 1,
            "game_token_usage_gaps": 0,
        })
        self.assertIn("known_measured_spend=144", context)
        self.assertIn("remaining_allowance=856 (upper_bound; usage_unknown)", context)
        self.assertIn("coverage=bounded_unknown", context)

    def test_provenance_without_origin_stays_unknown(self):
        self.assertEqual(memory_provenance(None, {"state_revision": 9})["status"], "unknown")

    def test_resume_memory_requires_commit_and_keeps_text_paired_with_origin(self):
        records = [
            {"type": "forwarded_orders", "batch_id": "b-a", "intent": "accepted A",
             "intent_origin": {"origin_revision": 4}},
            {"type": "batch_committed", "batch_id": "b-a"},
            {"type": "forwarded_orders", "batch_id": "b-b", "intent": "rejected B",
             "intent_origin": {"origin_revision": 5}},
            {"type": "action_failure", "batch_id": "b-b"},
            {"type": "checkpoint_ref", "batch_id": "b-c", "intent": "accepted C",
             "intent_origin": {"origin_revision": 6}},
            {"type": "batch_committed", "batch_id": "b-c"},
        ]
        recovered = recover_optional_memory(records)
        self.assertEqual(recovered["intent"], "accepted C")
        self.assertEqual(recovered["intent_origin"]["origin_revision"], 6)
        # Stop at the rejected/open proposal: a later accepted C must not mask
        # accidental publication of B merely because it was forwarded.
        rejected = recover_optional_memory(records[:4])
        self.assertEqual(rejected["intent"], "accepted A")
        self.assertEqual(rejected["intent_origin"]["origin_revision"], 4)
        unacknowledged = recover_optional_memory(records[:3])
        self.assertEqual(unacknowledged["intent"], "accepted A")
        checkpoint_before_ack = recover_optional_memory([
            {"type": "forwarded_orders", "batch_id": "b-before-ack",
             "intent": "accepted before ack",
             "intent_origin": {"origin_revision": 7}},
            {"type": "checkpoint_ref", "batch_id": "b-before-ack",
             "intent": "accepted before ack",
             "intent_origin": {"origin_revision": 7},
             "path": "match.ckpt", "digest": "checkpoint-digest"},
        ])
        self.assertEqual(checkpoint_before_ack["intent"], "accepted before ack")
        self.assertEqual(checkpoint_before_ack["intent_origin"]["origin_revision"], 7)
        self.assertEqual(recover_optional_memory([
            {"type": "forwarded_orders", "batch_id": "", "intent": "unproven",
             "intent_origin": {"origin_revision": 99}},
            {"type": "batch_committed", "batch_id": ""},
            {"type": "checkpoint_ref", "batch_id": "other", "intent": "wrong",
             "intent_origin": {"origin_revision": 98}},
            {"type": "batch_committed", "batch_id": "proven"},
        ])["intent"], "")
        missing_origin = recover_optional_memory([
            {"type": "intent_update", "intent": "old", "origin": {"origin_revision": 1}},
            {"type": "intent_update", "intent": "new"},
        ])
        self.assertIsNone(missing_origin["intent_origin"])

    def test_local_inspection_repeats_live_type_and_weapon_facts(self):
        enriched = enrich_inspected_units(
            [{"unit_id": 7, "origins": [{"current": True, "engagements": [{"defender_id": 9}]}]}],
            {"units": [{"id": 7, "def_id": "Bowman", "hp": 9, "max_hp": 12},
                       {"id": 9, "def_id": "EnemyBowman"}],
             "tactical_surface": {"unit_types": [{"def_id": "Bowman",
                                                     "attacks": [{"name": "bow", "range": 2}]},
                                                    {"def_id": "EnemyBowman",
                                                     "attacks": [{"name": "sword", "range": 1},
                                                                 {"name": "bow", "range": 2}]}]}},
        )
        rendered = compact_unit_inspection(enriched[0])
        self.assertIn("facts=type:Bowman hp:9/12", rendered)
        self.assertIn('weapons:[{"name":"bow","range":2}]', rendered)
        self.assertIn("defender_facts=type:EnemyBowman", rendered)
        target = enrich_target_inspection(
            {"target_id": 9, "attacks": []},
            {"units": [{"id": 9, "def_id": "EnemyBowman"}],
             "tactical_surface": {"unit_types": [{"def_id": "EnemyBowman",
                                                     "attacks": [{"name": "sword", "range": 1},
                                                                 {"name": "bow", "range": 2}]}]}},
        )
        target_rendered = compact_target_inspection(target)
        self.assertIn("target_facts=type:EnemyBowman", target_rendered)
        self.assertIn('"range":1', target_rendered)


if __name__ == "__main__":
    unittest.main()
