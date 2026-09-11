"""Unit tests for deterministic action choices encoding and resolution."""
from __future__ import annotations

import json
import unittest
from typing import Any

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


class InspectUnitsRequestValidationTests(unittest.TestCase):
    """Stack 4: structural validation of the `inspect_units` friendly batch tool."""

    def test_single_id_accepted(self):
        self.assertEqual(
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": [12]}),
            [12],
        )

    def test_eight_ids_accepted(self):
        ids = list(range(1, 9))
        self.assertEqual(
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": ids}),
            ids,
        )

    def test_wrong_tool_name_rejected(self):
        with self.assertRaises(ValueError):
            ac.validate_inspect_units_request({"tool": "inspect_unit", "unit_ids": [1]})

    def test_extra_field_rejected(self):
        with self.assertRaises(ValueError):
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": [1], "extra": True})

    def test_empty_list_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": []})
        self.assertIn("1 to 8", str(ctx.exception))

    def test_nine_ids_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": list(range(9))})
        self.assertIn("1 to 8", str(ctx.exception))

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": [12, 12]})
        self.assertIn("unique", str(ctx.exception))

    def test_malformed_ids_rejected(self):
        for bad in ([1, "2"], [1, True], [1, -1], [1, 2**32], [1, None], "not-a-list"):
            with self.assertRaises(ValueError):
                ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": bad})

    def test_not_a_list_rejected(self):
        with self.assertRaises(ValueError):
            ac.validate_inspect_units_request({"tool": "inspect_units", "unit_ids": 12})


class _ScriptedExchange:
    """A fake driver `exchange` callable that replays scripted responses by unit_id.

    Response bodies mirror the exact shapes greedy_driver.rs's `inspect_unit`
    query produces, so tests here exercise the real driver contract without
    spawning a subprocess.
    """

    def __init__(self, by_unit_id: dict[int, dict[str, Any]], calls: list[int] | None = None) -> None:
        self.by_unit_id = by_unit_id
        self.calls = calls if calls is not None else []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(request["unit_id"])
        return self.by_unit_id[request["unit_id"]]


def _ok_inspection(unit_id: int, revision: int) -> dict[str, Any]:
    return {
        "ok": True,
        "state_revision": revision,
        "body": {
            "unit_id": unit_id,
            "origins": [
                {"col": 1, "row": 1, "current": True, "movable": False, "engagements": []},
                {"col": 2, "row": 1, "current": False, "movable": True, "engagements": []},
            ],
        },
    }


def _dead_inspection(unit_id: int) -> dict[str, Any]:
    return {"ok": False, "code": "UnitNotFound", "message": "unit is unavailable"}


def _enemy_inspection() -> dict[str, Any]:
    return {"ok": False, "code": "unauthorized_unit",
            "message": "only model-side units may be inspected"}


def _stale_inspection() -> dict[str, Any]:
    return {"ok": False, "code": "stale_state",
            "message": "requested state revision is no longer current", "state_revision": 999}


class QueryInspectUnitsFanOutTests(unittest.TestCase):
    """Stack 4: bounded Python fan-out over the existing single-unit driver query."""

    def test_eight_units_one_query_per_unit_in_order(self):
        ids = list(range(1, 9))
        exchange = _ScriptedExchange({uid: _ok_inspection(uid, 5) for uid in ids})
        results = ac.query_inspect_units(exchange, ids, 5)
        self.assertEqual(exchange.calls, ids)
        self.assertEqual([r["unit_id"] for r in results], ids)

    def test_single_id_works_through_same_interface(self):
        exchange = _ScriptedExchange({12: _ok_inspection(12, 5)})
        results = ac.query_inspect_units(exchange, [12], 5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["unit_id"], 12)

    def test_dead_unit_aborts_whole_request(self):
        exchange = _ScriptedExchange({
            12: _ok_inspection(12, 5),
            13: _dead_inspection(13),
        })
        with self.assertRaises(ValueError) as ctx:
            ac.query_inspect_units(exchange, [12, 13], 5)
        self.assertIn("13", str(ctx.exception))
        self.assertIn("unit is unavailable", str(ctx.exception))

    def test_enemy_unit_aborts_whole_request(self):
        exchange = _ScriptedExchange({
            12: _ok_inspection(12, 5),
            24: _enemy_inspection(),
        })
        with self.assertRaises(ValueError) as ctx:
            ac.query_inspect_units(exchange, [12, 24], 5)
        self.assertIn("24", str(ctx.exception))
        self.assertIn("only model-side units may be inspected", str(ctx.exception))

    def test_stale_revision_aborts_whole_request(self):
        exchange = _ScriptedExchange({12: _stale_inspection()})
        with self.assertRaises(RuntimeError) as ctx:
            ac.query_inspect_units(exchange, [12], 338)
        self.assertIn("no longer current", str(ctx.exception))

    def test_successful_reply_with_wrong_revision_aborts_whole_request(self):
        exchange = _ScriptedExchange({12: _ok_inspection(12, 6)})
        with self.assertRaises(RuntimeError) as ctx:
            ac.query_inspect_units(exchange, [12], 5)
        self.assertIn("revision mismatch", str(ctx.exception))

    def test_no_calls_for_ids_after_a_hard_failure(self):
        # Enemy id 24 is queried second; id 30 must never be queried because the
        # whole request is aborted -- no partial success dressed up as a full result.
        calls: list[int] = []
        exchange = _ScriptedExchange({12: _ok_inspection(12, 5), 24: _enemy_inspection(),
                                       30: _ok_inspection(30, 5)}, calls=calls)
        with self.assertRaises(ValueError):
            ac.query_inspect_units(exchange, [12, 24, 30], 5)
        self.assertEqual(calls, [12, 24])

    def test_member_preflight_rejects_enemy_and_dead_before_query(self):
        state = {"units": [
            {"id": 12, "faction": 0, "hp": 20},
            {"id": 24, "faction": 1, "hp": 20},
            {"id": 13, "faction": 0, "hp": 0},
        ]}
        calls: list[int] = []
        exchange = _ScriptedExchange({}, calls=calls)
        for bad_id in (24, 13):
            with self.subTest(bad_id=bad_id), self.assertRaises(ValueError):
                ac.validate_friendly_inspect_units([12, bad_id], state, 0)
            self.assertEqual(calls, [])


class ExtractUnitsInspectionChoicesTests(unittest.TestCase):
    """Stack 4: union choice handles from a grouped inspection, deduplicated by handle."""

    def test_choices_from_multiple_units_are_grouped_and_unioned(self):
        results = [
            {"unit_id": 12, "origins": [{"col": 2, "row": 6, "current": False, "movable": True, "engagements": []}]},
            {"unit_id": 13, "origins": [{"col": 3, "row": 6, "current": False, "movable": True, "engagements": []}]},
        ]
        choices = ac.extract_units_inspection_choices(results, "g1", 5)
        self.assertEqual(len(choices), 2)
        self.assertEqual({c.metadata["unit_id"] for c in choices}, {12, 13})
        for choice in choices:
            self.assertEqual(ac.parse_handle(choice.handle)[0], 5)

    def test_unavailable_unit_contributes_no_choices(self):
        results = [
            {"available": False, "unit_id": 13, "reason": "unit is unavailable"},
            {"unit_id": 12, "origins": [{"col": 2, "row": 6, "current": False, "movable": True, "engagements": []}]},
        ]
        choices = ac.extract_units_inspection_choices(results, "g1", 5)
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].metadata["unit_id"], 12)

    def test_duplicate_handles_across_units_are_deduplicated(self):
        # Two identical per-unit inspection bodies for the same unit_id would
        # otherwise produce the same canonical key/handle; the union must not
        # register it twice.
        unit_body = {"unit_id": 12, "origins": [{"col": 2, "row": 6, "current": False, "movable": True, "engagements": []}]}
        choices = ac.extract_units_inspection_choices([unit_body, dict(unit_body)], "g1", 5)
        self.assertEqual(len(choices), 1)


if __name__ == "__main__":
    unittest.main()
