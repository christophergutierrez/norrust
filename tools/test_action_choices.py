"""Unit tests for deterministic action choices encoding and resolution."""
from __future__ import annotations

import json
import unittest

from . import action_choices as ac


class ActionChoicesTests(unittest.TestCase):

    def test_handle_format_and_determinism(self):
        h1 = ac.make_handle("game1", 42, "Move:1:2:3")
        h2 = ac.make_handle("game1", 42, "Move:1:2:3")
        self.assertEqual(h1, h2)
        parsed = ac.parse_handle(h1)
        self.assertIsNotNone(parsed)
        rev, token = parsed
        self.assertEqual(rev, 42)
        self.assertEqual(len(token), 8)

        # Different revision produces different handle
        h3 = ac.make_handle("game1", 43, "Move:1:2:3")
        self.assertNotEqual(h1, h3)
        self.assertEqual(ac.parse_handle(h3)[0], 43)

        # Different game produces different handle
        h4 = ac.make_handle("game2", 42, "Move:1:2:3")
        self.assertNotEqual(h1, h4)

        # Malformed handles
        self.assertIsNone(ac.parse_handle("invalid"))
        self.assertIsNone(ac.parse_handle("c_abc_12345678"))
        self.assertIsNone(ac.parse_handle("c_42_xyz"))

    def test_recruitment_choices(self):
        recruit_opts = {
            "placement_hexes": [{"col": 2, "row": 6}, {"col": 3, "row": 6}],
            "options": [
                {"def_id": "Skeleton", "cost": 15, "affordable": True},
                {"def_id": "Ghost", "cost": 19, "affordable": False},
            ]
        }
        choices = ac.extract_recruitment_choices(recruit_opts, "g1", 10)
        # 1 affordable unit * 2 hexes = 2 choices
        self.assertEqual(len(choices), 2)
        self.assertTrue(all(c.category == "recruit" for c in choices))
        self.assertEqual(choices[0].actions, [{"action": "Recruit", "def_id": "Skeleton", "col": 2, "row": 6}])
        self.assertEqual(choices[1].actions, [{"action": "Recruit", "def_id": "Skeleton", "col": 3, "row": 6}])

    def test_turn_options_move_standing_attack_and_move_attack(self):
        turn_opts = {
            "units": [
                {
                    "unit_id": 1,
                    "positions": [
                        {"col": 2, "row": 7, "current": True, "movable": False, "target_ids": [24]},
                        {"col": 2, "row": 6, "current": False, "movable": True, "target_ids": []},
                        {"col": 3, "row": 7, "current": False, "movable": True, "target_ids": [39]},
                    ]
                }
            ]
        }
        choices = ac.extract_turn_options_choices(turn_opts, "g1", 10)
        self.assertEqual(len(choices), 4)

        # 1: standing attack from (2,7) onto U24
        standing = next(c for c in choices if c.category == "attack")
        self.assertEqual(standing.actions, [{"action": "Attack", "attacker_id": 1, "defender_id": 24}])
        self.assertIn("from (2,7)", standing.description)

        # 2: plain move to (2,6)
        plain_move = next(c for c in choices if c.category == "move" and c.metadata.get("col") == 2)
        self.assertEqual(plain_move.actions, [{"action": "Move", "unit_id": 1, "col": 2, "row": 6}])

        # 3: move-and-attack to (3,7) attacking U39
        move_attack = next(c for c in choices if c.category == "move_attack")
        self.assertEqual(move_attack.actions, [
            {"action": "Move", "unit_id": 1, "col": 3, "row": 7},
            {"action": "Attack", "attacker_id": 1, "defender_id": 39}
        ])

    def test_advancement_choices(self):
        units = [
            {"id": 1, "advancement_pending": True, "advances_to": ["Lich", "Necromancer"]},
            {"id": 2, "advancement_pending": False, "advances_to": ["Lich"]},
        ]
        choices_both = ac.extract_advancement_choices(units, "g1", 10, selector_style="both")
        self.assertEqual(len(choices_both), 4)

        # target_index selector
        idx_choices = ac.extract_advancement_choices(units, "g1", 10, selector_style="target_index")
        self.assertEqual(len(idx_choices), 2)
        self.assertEqual(idx_choices[0].actions, [{"action": "Advance", "unit_id": 1, "target_index": 0}])
        self.assertEqual(idx_choices[1].actions, [{"action": "Advance", "unit_id": 1, "target_index": 1}])

        # def_id selector
        def_choices = ac.extract_advancement_choices(units, "g1", 10, selector_style="def_id")
        self.assertEqual(len(def_choices), 2)
        self.assertEqual(def_choices[0].actions, [{"action": "Advance", "unit_id": 1, "def_id": "Lich"}])
        self.assertEqual(def_choices[1].actions, [{"action": "Advance", "unit_id": 1, "def_id": "Necromancer"}])

    def test_inspection_choices_cover_all_options_without_heuristics(self):
        inspection = {
            "unit_id": 5,
            "origins": [
                {"col": 10, "row": 5, "current": True, "movable": False, "engagements": [{"target_id": 20}]},
                {"col": 11, "row": 5, "current": False, "movable": True, "engagements": [{"target_id": 20}, {"target_id": 21}]},
                {"col": 10, "row": 6, "current": False, "movable": True, "engagements": []},
            ]
        }
        choices = ac.extract_inspection_choices(inspection, "g1", 5)
        # standing attack (1) + move to (11,5) (1) + 2 move-attacks from (11,5) (2) + move to (10,6) (1) = 5
        self.assertEqual(len(choices), 5)
        categories = [c.category for c in choices]
        self.assertEqual(categories.count("attack"), 1)
        self.assertEqual(categories.count("move"), 2)
        self.assertEqual(categories.count("move_attack"), 2)

    def test_registry_resolution_and_stale_unknown_handling(self):
        reg = ac.ChoiceRegistry(game_id="game_test")
        reg.sync_revision(100)

        c1 = ac.Choice(handle=ac.make_handle("game_test", 100, "Move:1:2:3"),
                       description="Move U1 to (2,3)",
                       actions=[{"action": "Move", "unit_id": 1, "col": 2, "row": 3}],
                       category="move")
        c2 = ac.Choice(handle=ac.make_handle("game_test", 100, "Attack:1:2:3:9"),
                       description="Attack U9 with U1",
                       actions=[{"action": "Attack", "attacker_id": 1, "defender_id": 9}],
                       category="attack")
        reg.register_all([c1, c2])

        # Successful resolution
        actions, mapping, resolved = reg.resolve([c1.handle, c2.handle], current_revision=100)
        self.assertEqual(len(actions), 2)
        self.assertEqual(mapping, [0, 1])
        self.assertEqual(actions[0]["action"], "Move")
        self.assertEqual(actions[1]["action"], "Attack")

        # Expansion mapping for multi-action choice (e.g. move-attack)
        c_combo = ac.Choice(
            handle=ac.make_handle("game_test", 100, "MoveAttack:2:4:5:8"),
            description="Move and attack",
            actions=[{"action": "Move", "unit_id": 2, "col": 4, "row": 5},
                     {"action": "Attack", "attacker_id": 2, "defender_id": 8}],
            category="move_attack"
        )
        reg.register(c_combo)
        actions, mapping, _ = reg.resolve([c1.handle, c_combo.handle], current_revision=100)
        self.assertEqual(len(actions), 3)
        self.assertEqual(mapping, [0, 1, 1])  # choice 0 -> action 0; choice 1 -> action 1 and 2

        # Stale handle error (observed at revision 99)
        stale_handle = ac.make_handle("game_test", 99, "Move:1:2:3")
        with self.assertRaises(ValueError) as ctx:
            reg.resolve([stale_handle], current_revision=100)
        self.assertIn("stale_choice_handle", str(ctx.exception))

        # Unknown handle error (same revision, but never exposed)
        unknown_handle = ac.make_handle("game_test", 100, "Move:99:99:99")
        with self.assertRaises(ValueError) as ctx:
            reg.resolve([unknown_handle], current_revision=100)
        self.assertIn("unknown_choice_handle", str(ctx.exception))

        # Malformed handle error
        with self.assertRaises(ValueError) as ctx:
            reg.resolve(["bad_handle"], current_revision=100)
        self.assertIn("malformed_choice_handle", str(ctx.exception))

        # Revision change clears exposed set
        reg.sync_revision(101)
        self.assertEqual(len(reg.exposed), 0)

    def test_tactical_surface_and_available_choices(self):
        surface = {
            "recruitment": {
                "placement_hexes": [{"col": 2, "row": 6}],
                "options": [{"def_id": "Skeleton", "cost": 15, "affordable": True}],
            },
            "units": [
                {
                    "unit_id": 1,
                    "origins": [
                        {"col": 3, "row": 5, "current": True, "engagements": [{"defender_id": 20}]},
                        {"col": 4, "row": 5, "current": False, "movable": True, "engagements": [{"defender_id": 20}]},
                    ]
                }
            ]
        }
        choices = ac.extract_tactical_surface_choices(surface, "g1", 1)
        # 1 recruit + 1 standing attack (non-current is not exposed in tactical surface overview)
        self.assertEqual(len(choices), 2)
        categories = {c.category for c in choices}
        self.assertEqual(categories, {"recruit", "attack"})

        state = {
            "tactical_surface": surface,
            "units": [{"id": 1, "advancement_pending": True, "advances_to": ["Lich"]}],
        }
        all_choices = ac.extract_available_choices(state, "g1", 1)
        # 1 recruit + 1 standing attack + 2 advancement choices (both index and def_id)
        self.assertEqual(len(all_choices), 4)


if __name__ == "__main__":
    unittest.main()
