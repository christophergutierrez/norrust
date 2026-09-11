import unittest

from .llm_client import (
    compact_batch_preview,
    compact_target_inspection,
    compact_tactical_surface,
    compact_unit_inspection,
    prompt_for,
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


if __name__ == "__main__":
    unittest.main()
