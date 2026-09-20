"""Pure contract checks for Stack 3 opening suggestions."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from .opening_policy import build_opening_policies, render_opening_policy_menu
from .routine_policy import ValidationContext, render_policy_brief, validate_routine_policy
from .strategy_decision import build_decision_packet, render_decision_brief


VILLAGES = [(2, 4), (5, 3), (6, 11), (17, 2), (18, 10), (21, 9)]


def opening_state() -> dict:
    return {
        "active_faction": 0,
        "turn": 1,
        "state_revision": 0,
        "cols": 24,
        "rows": 14,
        "gold": [300, 300],
        "factions": [{"side": 0, "id": "undead"}, {"side": 1, "id": "undead"}],
        "units": [
            {"id": 1, "faction": 0, "col": 2, "row": 7, "can_recruit": True},
            {"id": 2, "faction": 1, "col": 21, "row": 6, "can_recruit": True},
        ],
        "terrain": [{"terrain_id": "village", "col": col, "row": row, "owner": -1}
                    for col, row in VILLAGES],
    }


def context() -> ValidationContext:
    return ValidationContext(
        recruitable_defs=frozenset({"Vampire Bat", "Ghost", "Skeleton", "Dark Adept"}),
        friendly_unit_ids=frozenset({1}),
        recruiter_ids=frozenset({1}),
        village_coords=frozenset(VILLAGES),
        board_bounds=(24, 14),
        owned_village_coords=frozenset(),
    )


def options() -> dict:
    return {
        "side_can_place": True,
        "placement_hexes": [{"col": 2, "row": 6}],
        "options": [
            {"def_id": "Vampire Bat", "cost": 13, "affordable": True},
            {"def_id": "Ghost", "cost": 19, "affordable": True},
            {"def_id": "Skeleton", "cost": 15, "affordable": True},
            {"def_id": "Dark Adept", "cost": 16, "affordable": True},
        ],
    }


class OpeningPolicyTests(unittest.TestCase):
    def test_two_complete_policies_use_live_costs_and_validate(self) -> None:
        policies = build_opening_policies(opening_state(), context(), options())
        self.assertEqual([item["label"] for item in policies], ["Expansion", "Concentration"])
        self.assertEqual([item["recruit_cost"] for item in policies], [296, 298])
        self.assertEqual([item["reserve_gold"] for item in policies], [0, 0])
        for item in policies:
            self.assertGreaterEqual(item["recruit_cost"], 285)
            self.assertLessEqual(item["recruit_cost"], 300)
            self.assertEqual(item["reserve_gold"], 0)
            response = item["response"]
            self.assertEqual(response["kind"], "set_policy")
            policy = response["policy"]
            self.assertEqual(policy["scouts"], [])
            validate_routine_policy(policy, context())

            # Combined arms constraints:
            da_count = sum(r["count"] for r in policy["recruits"] if r["def_id"] == "Dark Adept")
            self.assertGreaterEqual(da_count, 6)
            frontline_count = sum(r["count"] for r in policy["recruits"] if r["def_id"] in {"Skeleton", "Ghost", "Ghoul"})
            self.assertGreaterEqual(frontline_count, 8)
            scout_count = sum(r["count"] for r in policy["recruits"] if r["role"] == "scout")
            self.assertEqual(scout_count, len(policy["villages"]))

        fixture_root = Path(__file__).resolve().parent / "fixtures/strategy_openings"
        fixture_policies = [
            json.loads((fixture_root / name).read_text())["response"]
            for name in ("expansion.json", "concentration.json")
        ]
        self.assertEqual([item["response"] for item in policies], fixture_policies)

    def test_cost_below_ninety_five_percent_suppresses_menu(self) -> None:
        cheap_options = copy.deepcopy(options())
        for opt in cheap_options["options"]:
            opt["cost"] = 5  # Queue would cost much less than 285 gold
        self.assertEqual(build_opening_policies(opening_state(), context(), cheap_options), [])

    def test_custom_deliberate_reserve_still_validates(self) -> None:
        custom_policy = {
            "reserve_gold": 100,
            "recruits": [
                {"def_id": "Skeleton", "count": 4, "role": "army"},
                {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
            ],
            "scouts": [],
            "villages": [{"col": 5, "row": 3}],
            "rally": {"col": 6, "row": 6},
            "holds": [],
        }
        normalized = validate_routine_policy(custom_policy, context())
        self.assertEqual(normalized["reserve_gold"], 100)

    def test_unknown_or_unsupported_facts_suppress_menu(self) -> None:
        missing_options = copy.deepcopy(options())
        missing_options["options"] = [missing_options["options"][0]]
        self.assertEqual(build_opening_policies(opening_state(), context(), missing_options), [])

        for field, value in (("cost", None), ("affordable", False)):
            unavailable_ranged = copy.deepcopy(options())
            unavailable_ranged["options"][-1][field] = value
            self.assertEqual(build_opening_policies(opening_state(), context(), unavailable_ranged), [])

        unknown_ownership = opening_state()
        unknown_ownership["terrain"][0].pop("owner")
        self.assertEqual(build_opening_policies(unknown_ownership, context(), options()), [])

        low_gold = opening_state()
        low_gold["gold"][0] = 299
        self.assertEqual(build_opening_policies(low_gold, context(), options()), [])

        later_state = opening_state()
        later_state["turn"] = 2
        self.assertEqual(build_opening_policies(later_state, context(), options()), [])
        revised_state = opening_state()
        revised_state["state_revision"] = 1
        self.assertEqual(build_opening_policies(revised_state, context(), options()), [])

    def test_menu_is_compact_and_contains_copy_ready_responses(self) -> None:
        menu = render_opening_policy_menu(build_opening_policies(opening_state(), context(), options()))
        self.assertLessEqual(len(menu.encode("utf-8")), 4096)
        self.assertIn("OPENING_POLICY_SUGGESTIONS_BEGIN", menu)
        self.assertIn('"kind":"set_policy"', menu)
        self.assertIn('"scouts":[]', menu)
        self.assertIn('"reserve_gold":0', menu)
        self.assertIn("Reserve is for explicit saving objectives", menu)

    def test_empty_menu_is_explicitly_unavailable(self) -> None:
        menu = render_opening_policy_menu([])
        self.assertIn("unavailable", menu)
        self.assertNotIn("OPENING_POLICY_SUGGESTIONS_BEGIN", menu)

    def test_fixed_prefix_and_custom_path_are_unchanged_by_volatile_menu(self) -> None:
        initial = render_policy_brief(
            0, ["Ghost", "Skeleton"], state=opening_state(),
            recruit_options=options(), validation_context=context())
        changed = opening_state()
        changed["gold"] = [299, 300]
        changed["state_revision"] = 1
        unavailable = render_policy_brief(
            0, ["Ghost", "Skeleton"], state=changed,
            recruit_options=options(), validation_context=context())
        marker = "STRATEGY_FIXED_PREFIX_END\n"
        self.assertEqual(initial.split(marker, 1)[0], unavailable.split(marker, 1)[0])
        initial_menu = initial.split("OPENING_POLICY_SUGGESTIONS_BEGIN", 1)[1]
        initial_menu = "OPENING_POLICY_SUGGESTIONS_BEGIN" + initial_menu.split(
            "OPENING_POLICY_SUGGESTIONS_END", 1)[0] + "OPENING_POLICY_SUGGESTIONS_END"
        self.assertLessEqual(len(initial_menu.encode()), 4096)

        custom = render_policy_brief(0, ["Ghost"], state=opening_state(), recruit_options=options())
        self.assertNotIn("OPENING_POLICY_SUGGESTIONS_BEGIN", custom)

    def test_tactical_brief_never_includes_opening_menu(self) -> None:
        packet = build_decision_packet(
            "contact",
            {"stage": "current_state", "trigger": "attack", "friendly_unit_ids": [1],
             "enemy_unit_ids": [2], "coverage": "complete"},
            revision=1)
        brief = render_decision_brief(packet, state=opening_state(), recruit_options=options())
        self.assertNotIn("OPENING_POLICY_SUGGESTIONS_BEGIN", brief)


if __name__ == "__main__":
    unittest.main()
