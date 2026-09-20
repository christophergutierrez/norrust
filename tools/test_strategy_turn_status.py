"""Tests for Strategy Resilience Stack 3: Turn-wide priorities and finish consequences.

Verifies:
1. Turn-status block size is bounded (<= 900 UTF-8 bytes).
2. 18-eligible-actor / 3-menu-actor fixture shows menu truncation and whole-turn finish semantics.
3. Exhausted, held, immobile, move-only, attack-only, and ready units have truthful labels.
4. Missing roster or fields yield 'unknown', never 0.
5. Policy deficits and recruitment status are reported honestly across changing contact packets.
6. Early route/economy exceptions include turn-status and finish consequences.
7. Fixed-prefix bytes and SHA-256 remain invariant under volatile turn facts.
"""
from __future__ import annotations

import copy
import json
import unittest

from . import strategy_decision as sd
from .routine_policy import (
    compute_army_action_facts,
    render_turn_status_block,
    render_strategy_fixed_prefix,
)
from .llm_client import (
    finalize_strategy_prompt,
    prompt_regions,
)


class StrategyTurnStatusTests(unittest.TestCase):

    def setUp(self):
        self.maxDiff = None
        self.recruitable_defs = ("Dark Adept", "Skeleton", "Vampire Bat")

    def _sample_state(self, num_friendly: int = 18) -> dict:
        units = [
            {
                "id": 1,
                "faction": 0,
                "def_id": "Dark Sorcerer",
                "col": 2,
                "row": 7,
                "hp": 48,
                "max_hp": 48,
                "moved": False,
                "attacked": False,
                "movement": 5,
                "can_recruit": True,
            }
        ]
        for i in range(2, num_friendly + 1):
            units.append({
                "id": i,
                "faction": 0,
                "def_id": "Skeleton",
                "col": 2 + (i % 5),
                "row": 6 + (i // 5),
                "hp": 30,
                "max_hp": 30,
                "moved": False,
                "attacked": False,
                "movement": 5,
                "can_recruit": False,
            })
        units.append({
            "id": 99,
            "faction": 1,
            "def_id": "Spearman",
            "col": 8,
            "row": 8,
            "hp": 36,
            "max_hp": 36,
            "moved": False,
            "attacked": False,
            "movement": 5,
            "can_recruit": False,
        })
        return {
            "scenario": "big_battle_6",
            "cols": 24,
            "rows": 18,
            "active_faction": 0,
            "state_revision": 25,
            "turn": 4,
            "time_of_day": "dawn",
            "gold": [140, 100],
            "terrain": [
                {"col": 2, "row": 7, "terrain_id": "keep", "owner": 0},
                {"col": 2, "row": 6, "terrain_id": "castle", "owner": 0},
                {"col": 3, "row": 6, "terrain_id": "castle", "owner": 0},
                {"col": 2, "row": 4, "terrain_id": "village", "owner": 0},
                {"col": 5, "row": 3, "terrain_id": "village", "owner": 1},
                {"col": 6, "row": 11, "terrain_id": "village", "owner": -1},
            ],
            "units": units,
        }

    def test_block_size_under_900_bytes(self):
        """Turn-status block must be <= 900 UTF-8 bytes."""
        state = self._sample_state(18)
        evidence = {
            "stage": "current_state",
            "trigger": "attack",
            "friendly_unit_ids": [2, 3, 4],
            "enemy_unit_ids": [99],
            "actor_ids": [2, 3, 4],
            "eligible_actor_count": 18,
            "actors_truncated": True,
            "threatened_recruiter": {
                "recruiter_id": 1,
                "hp": 34,
                "max_hp": 48,
                "distinct_attacker_count": 2,
            },
            "options": [
                {"option_id": "u2-opt-1", "actor_id": 2, "actions": []},
            ],
        }
        packet = sd.build_decision_packet("contact", evidence, revision=25, decision_id="dec-1")
        policy = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Dark Adept", "count": 2, "role": "army"}],
            "scouts": [2],
            "villages": [{"col": 5, "row": 3}, {"col": 6, "row": 11}],
            "rally": None,
            "holds": [1],
        }
        block = render_turn_status_block(packet, state=state, policy=policy)
        encoded = block.encode("utf-8")
        self.assertLessEqual(len(encoded), 900, f"Block exceeded 900 bytes ({len(encoded)} bytes)")

    def test_18_eligible_and_3_menu_actors_truncation_and_finish_consequences(self):
        """18 eligible actors with 3 menu actors shows truncation and does not present 3 as entire army."""
        state = self._sample_state(18)
        evidence = {
            "stage": "current_state",
            "trigger": "attack",
            "friendly_unit_ids": [2, 3, 4],
            "enemy_unit_ids": [99],
            "actor_ids": [2, 3, 4],
            "eligible_actor_count": 18,
            "actors_truncated": True,
            "options": [
                {"option_id": "u2-opt-1", "actor_id": 2, "actions": []},
            ],
        }
        packet = sd.build_decision_packet("contact", evidence, revision=25, decision_id="dec-2")
        brief = sd.render_decision_brief(packet, state=state, recruitable_defs=self.recruitable_defs)

        self.assertIn("TURN STATUS & PRIORITIES:", brief)
        self.assertIn("Tactical menu actors: 3 offered in options; 18 engine-eligible actors", brief)
        self.assertIn("15 eligible actors omitted from this bounded menu", brief)
        # Verify 3 actors are NOT presented as the whole army
        self.assertIn("Army action flags:", brief)
        self.assertIn("(+10 omitted)", brief)  # 18 total units - 8 displayed = 10 omitted
        # Verify finish consequences
        self.assertIn("finish_turn=true ends your whole side's turn immediately with no tactical sweep", brief)
        self.assertIn("finish_turn=false continues the turn with a fresh decision if other work or actors remain", brief)

    def test_truthful_unit_actionability_labels(self):
        """Exhausted, held, immobile, move-only, attack-only and ready units are classified correctly."""
        units = [
            # Ready
            {"id": 10, "faction": 0, "moved": False, "attacked": False, "movement": 5, "hp": 30},
            # Move-only (attack spent)
            {"id": 11, "faction": 0, "moved": False, "attacked": True, "movement": 5, "hp": 30},
            # Attack-only (movement spent)
            {"id": 12, "faction": 0, "moved": True, "attacked": False, "movement": 0, "hp": 30},
            # Immobile (movement 0, unmoved, unattacked)
            {"id": 13, "faction": 0, "moved": False, "attacked": False, "movement": 0, "hp": 30},
            # Held (in policy holds)
            {"id": 14, "faction": 0, "moved": False, "attacked": False, "movement": 5, "hp": 30},
            # Exhausted (both moved and attacked)
            {"id": 15, "faction": 0, "moved": True, "attacked": True, "movement": 0, "hp": 30},
            # Dead unit (should be ignored)
            {"id": 16, "faction": 0, "moved": False, "attacked": False, "movement": 5, "hp": 0},
        ]
        state = {"units": units, "active_faction": 0}
        policy = {"holds": [14]}
        facts = compute_army_action_facts(state, policy=policy)

        self.assertEqual(facts["status"], "known")
        self.assertEqual(facts["ready"], 1)
        self.assertEqual(facts["move_only"], 1)
        self.assertEqual(facts["attack_only"], 1)
        self.assertEqual(facts["immobile"], 1)
        self.assertEqual(facts["held"], 1)
        self.assertEqual(facts["exhausted"], 1)
        # Units with unused action flags: 10 (ready), 11 (move-only), 12 (attack-only), 13 (immobile) = 4
        self.assertEqual(facts["total_unused"], 4)
        self.assertEqual(facts["unused_action_ids"], [10, 11, 12, 13])
        self.assertEqual(facts["omitted_count"], 0)

    def test_missing_coverage_reports_unknown_not_zero(self):
        """Missing unit roster or active faction yields 'unknown', never zero."""
        facts_no_state = compute_army_action_facts(None)
        self.assertEqual(facts_no_state["status"], "unknown")
        self.assertEqual(facts_no_state["ready"], "unknown")
        self.assertEqual(facts_no_state["total_unused"], "unknown")

        facts_no_faction = compute_army_action_facts({"units": []})
        self.assertEqual(facts_no_faction["status"], "unknown")

        block = render_turn_status_block(
            sd.build_decision_packet("initial", {}, revision=0),
            state=None,
        )
        self.assertIn("friendly unit roster/status unknown", block)

    def test_policy_scout_capacity_deficit_visible(self):
        """Scout capacity deficit is clearly exposed in routine policy state."""
        state = self._sample_state(5)
        packet = sd.build_decision_packet("no_executable_orders", {
            "cause": "scout_capacity_exhausted",
            "required_assignments": 2,
            "scout_capacity": 0,
        }, revision=30)
        policy = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
            "scouts": [],
            "villages": [{"col": 5, "row": 3}, {"col": 6, "row": 11}],
            "rally": None,
            "holds": [],
        }
        progress = {
            "installation_id": "pol-test",
            "recruited": [],
            "scout_ids": [],
            "scout_assignments": [],
            "completed_villages": [],
            "policy_complete": False,
        }
        brief = sd.render_decision_brief(packet, state=state, policy=policy, progress=progress, recruitable_defs=self.recruitable_defs)
        self.assertIn("capacity deficit:", brief.lower())
        self.assertIn("2 unassigned villages require scouts, but available capacity is 0", brief)

    def test_early_exceptions_contain_turn_status_and_finish_consequences(self):
        """Non-combat early exceptions (e.g. recruitment_blocked, unsafe_route) include turn-status block."""
        state = self._sample_state(5)
        for reason in ("recruitment_blocked", "recruitment_review", "unsafe_route", "invalid_assignment"):
            packet = sd.build_decision_packet(reason, {"cause": "test_cause"}, revision=31)
            brief = sd.render_decision_brief(packet, state=state, recruitable_defs=self.recruitable_defs)
            self.assertIn("TURN STATUS & PRIORITIES:", brief, f"Missing status block in {reason}")
            self.assertIn("Finish consequences:", brief, f"Missing finish consequences in {reason}")

    def test_final_only_packet_notes_finish_requirement(self):
        """Final-only packets explicitly state that actions must set finish_turn=true."""
        state = self._sample_state(5)
        packet = sd.build_decision_packet(
            "contact",
            {"stage": "current_state", "actor_ids": [2], "eligible_actor_count": 1, "options": []},
            revision=32,
            final_only=True,
        )
        brief = sd.render_decision_brief(packet, state=state, recruitable_defs=self.recruitable_defs)
        self.assertIn("final-only", brief.lower())
        self.assertIn("actions must set finish_turn=true", brief)

    def test_fixed_prefix_invariant_with_status_block(self):
        """Volatile turn status does not leak into or alter the fixed cacheable prefix."""
        state1 = self._sample_state(5)
        state2 = copy.deepcopy(state1)
        state2["gold"] = [35, 100]
        state2["units"][1]["hp"] = 12

        packet1 = sd.build_decision_packet("contact", {"stage": "current_state", "options": []}, revision=10)
        packet2 = sd.build_decision_packet("contact", {"stage": "current_state", "options": []}, revision=11)

        brief1 = sd.render_decision_brief(packet1, state=state1, recruitable_defs=self.recruitable_defs)
        brief2 = sd.render_decision_brief(packet2, state=state2, recruitable_defs=self.recruitable_defs)

        prompt1 = finalize_strategy_prompt(brief1, state1, packet=packet1)
        prompt2 = finalize_strategy_prompt(brief2, state2, packet=packet2)

        regions1 = prompt_regions(prompt1)
        regions2 = prompt_regions(prompt2)

        self.assertEqual(regions1["fixed_prefix_bytes"], regions2["fixed_prefix_bytes"])
        self.assertEqual(regions1["fixed_prefix_sha256"], regions2["fixed_prefix_sha256"])


if __name__ == "__main__":
    unittest.main()
