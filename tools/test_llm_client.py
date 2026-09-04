import argparse
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import llm_client
from .llm_client import (
    TERMINAL_EXIT_CODES, TERMINAL_GAMEPLAY, TERMINAL_INFRASTRUCTURE,
    TERMINAL_MODEL_INVALID, ModelReply, classify_terminal, enforce_usage,
    compact_batch_preview, compact_hex_inspection, compact_observation,
    compact_target_inspection, compact_tactical_surface, prompt_for, query_options,
    compact_unit_inspection, compact_draft_review, tool_followup_instruction, tool_budget_repair_prompt,
    compact_events, tactical_attack_coverage,
    query_tactical_surface, query_validate_batch, query_preview_batch,
    query_inspect_unit, query_inspect_target, query_inspect_hex, run,
    validate_inspect_unit_request, validate_inspect_target_request,
    validate_inspect_hex_request, validate_orders, validate_preview_request,
)


class FakeDriverProcess:
    def __init__(self, lines):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(
            line if isinstance(line, str) else json.dumps(line) + "\n" for line in lines
        ))
        self.stderr = io.StringIO()

    def poll(self):
        return 0

    def terminate(self):
        raise AssertionError("completed driver must not be terminated")


class ClientValidationTests(unittest.TestCase):
    def test_compact_events_preserves_facts_without_routine_json(self):
        events = [
            {"kind": "move", "source": "greedy", "unit": 9,
             "from": {"col": 4, "row": 5}, "to": {"col": 3, "row": 4}},
            {"kind": "attack", "source": "greedy",
             "attacker": {"unit": 9, "hp": 17},
             "defender": {"unit": 35, "hp": 0, "killed": True},
             "damage_to_defender": 6, "damage_to_attacker": 0},
            {"kind": "recruit", "source": "llm", "unit": 3,
             "def_id": "Skeleton", "col": 2, "row": 6, "cost": 14},
            {"kind": "gold", "source": "llm", "faction": 0,
             "delta": 6, "balance": 20},
            {"kind": "end_turn", "source": "llm", "ended_faction": 0,
             "active_faction": 1, "turn": 4},
        ]
        rendered = compact_events(events)
        self.assertIn("greedy move: U9 4,5>3,4", rendered)
        self.assertIn("greedy attack: U9>U35 dmg=6/0 hp=0/dead", rendered)
        self.assertIn("llm recruit: U3=Skeleton@2,6 cost=14", rendered)
        self.assertIn("llm gold: F0 delta=6 balance=20", rendered)
        self.assertIn("llm end_turn: F0->F1 turn=4", rendered)
        self.assertLess(len(rendered.encode()), 2048)

    def test_compact_prompt_uses_digest_and_diagnostic_prompt_keeps_raw_events(self):
        events = [{"kind": "move", "source": "greedy", "unit": 9,
                   "from": {"col": 4, "row": 5}, "to": {"col": 3, "row": 4}}]
        compact = prompt_for({}, events, compact=True)
        diagnostic = prompt_for({}, events, compact=False)
        self.assertIn('"EVENT_DIGEST', compact)
        self.assertIn('"kind":"move"', diagnostic)
        self.assertNotIn('"kind":"move"', compact)

    def test_target_and_hex_renderers_keep_facts_and_empty_hex_uncertainty(self):
        target = compact_target_inspection({
            "target_id": 9, "hp": 20, "col": 4, "row": 7, "terrain": "flat",
            "attacks": [{"attacker_id": 2, "origin_col": 3, "origin_row": 7,
                         "moved": True, "forecast": {"outcome_bps": [1000, 9000, 0],
                                                       "expected_damage_tenths": [80, 20]}}],
        })
        self.assertIn("TARGET U9 hp=20 at=4,7 terrain=flat", target)
        self.assertIn("U2~3,7 p[1000, 9000, 0]", target)
        empty = compact_hex_inspection({
            "phase": "next_opponent_turn", "visibility": "full",
            "inspection": {"col": 4, "row": 7, "occupant_id": None,
                           "attacks": [{"attacker_id": 16, "origin_col": 4,
                                        "origin_row": 5, "moved": True,
                                        "forecast": None, "max_damage": None}]},
        })
        self.assertIn("HEX 4,7 phase=next_opponent_turn visibility=full occupant=None", empty)
        self.assertIn("U16~4,5", empty)
        self.assertNotIn(" p[", empty)

    def test_recruiter_inspection_renders_destination_exposure(self):
        rendered = compact_unit_inspection({
            "unit_id": 1,
            "origins": [],
            "destination_threats": [
                {"col": 2, "row": 7, "current": True,
                 "distinct_attacker_count": 3, "max_incoming_sum": 42,
                 "lethal_attackers_needed": 2, "origins_conflict": False},
                {"col": 1, "row": 7, "current": False,
                 "distinct_attacker_count": 0, "max_incoming_sum": 0,
                 "lethal_attackers_needed": None, "origins_conflict": False},
            ],
        })
        self.assertIn("DESTINATION_DANGER", rendered)
        self.assertIn("@2,7 a3 m42 lethal_n=2", rendered)
        self.assertIn("->1,7 a0 m0 lethal_n=None", rendered)

    def test_target_and_hex_requests_are_exact_and_revision_pinned(self):
        self.assertEqual(validate_inspect_target_request(
            {"tool": "inspect_target", "unit_id": 9}), 9)
        self.assertEqual(validate_inspect_hex_request(
            {"tool": "inspect_hex", "col": 4, "row": 7,
             "phase": "next_opponent_turn"}), (4, 7, "next_opponent_turn"))
        with self.assertRaises(ValueError):
            validate_inspect_hex_request(
                {"tool": "inspect_hex", "col": 4, "row": 7, "phase": "future"})
        requests = []
        exchange = lambda request: requests.append(request) or {"ok": True, "body": {}}
        query_inspect_target(exchange, 9, 3)
        query_inspect_hex(exchange, 4, 7, "current", 3)
        self.assertEqual(requests, [
            {"action": "Query", "what": "inspect_target", "state_revision": 3, "unit_id": 9},
            {"action": "Query", "what": "inspect_hex", "state_revision": 3,
             "col": 4, "row": 7, "phase": "current"},
        ])

    def test_inspect_unit_request_is_exact_and_revision_pinned(self):
        self.assertEqual(validate_inspect_unit_request({"tool": "inspect_unit", "unit_id": 7}), 7)
        for request in (
            {"tool": "inspect_unit", "unit_id": True},
            {"tool": "inspect_unit", "unit_id": -1},
            {"tool": "inspect_unit", "unit_id": 7, "extra": 1},
        ):
            with self.assertRaises(ValueError):
                validate_inspect_unit_request(request)
        requests = []
        body = {"unit_id": 7, "origins": []}
        self.assertEqual(query_inspect_unit(lambda request: requests.append(request) or
                                            {"ok": True, "body": body}, 7, 19), body)
        self.assertEqual(requests, [{"action": "Query", "what": "inspect_unit",
                                    "state_revision": 19, "unit_id": 7}])

    def test_tool_followup_requires_final_actions_when_budget_is_exhausted(self):
        self.assertIn("remaining=0", tool_followup_instruction(0, 3))
        self.assertIn("Do not request another tool", tool_followup_instruction(0, 3))
        self.assertIn("remaining=0", tool_followup_instruction(2, 1))
        self.assertIn("Do not request another tool", tool_followup_instruction(2, 1))
        self.assertIn("another allowed tool", tool_followup_instruction(1, 2))

    def test_tool_budget_repair_preserves_all_tool_context(self):
        repaired = tool_budget_repair_prompt(
            "ORIGINAL", "\nTOOL_RESULT unit=7: target=9", "tool call budget exhausted",
            '{"tool":"inspect_unit","unit_id":7}')
        self.assertIn("ORIGINAL", repaired)
        self.assertIn("target=9", repaired)
        self.assertIn('"unit_id":7', repaired)
        self.assertIn("MODEL_RESPONSE_UNTRUSTED_DATA_BEGIN", repaired)
        self.assertIn("tool call budget exhausted", repaired)
        self.assertIn("do not request another tool", repaired.lower())

    def test_followup_context_echoes_tool_request_and_preview_candidates(self):
        request = '{"tool":"preview_batch","candidates":[[{"action":"EndTurn"}]]}'
        context = ("MODEL_TOOL_REQUEST_UNTRUSTED_DATA_BEGIN:\n" + request +
                   "\nMODEL_TOOL_REQUEST_UNTRUSTED_DATA_END\n" +
                   "TOOL_RESULT_UNTRUSTED_DATA_BEGIN tool=preview_batch:\n" +
                   "PREVIEW C0 valid=True\nTOOL_RESULT_UNTRUSTED_DATA_END\n")
        self.assertIn(request, context)
        self.assertIn("PREVIEW C0", context)

    def test_compact_draft_review_reports_recruiter_danger_delta(self):
        rendered, lethal = compact_draft_review({"candidates": [{
            "valid": True,
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 34, "distinct_attacker_count": 5,
                "max_incoming_sum": 70, "lethal_attackers_needed": 3,
            }]},
        }]}, True)
        self.assertTrue(lethal)
        self.assertIn("danger_before=True danger_after=True", rendered)
        self.assertIn("R1 hp=34 attackers=5 max_sum=70 lethal_n=3", rendered)

    def test_compact_draft_review_reports_unused_attackers(self):
        rendered, lethal = compact_draft_review(
            {"candidates": [{"valid": True, "recruiter_threats": {"recruiters": []}}]},
            False,
            {"available": {3, 4}, "current": {3}, "targets": {9: {3, 4}}},
            [{"action": "Attack", "unit_id": 3, "target_id": 9}, {"action": "EndTurn"}],
        )
        self.assertFalse(lethal)
        self.assertIn("COVERAGE_DRAFT available=U3,U4 planned=U3 unused=U4", rendered)

    def test_compact_batch_preview_uses_recruiter_aggregate_not_origins(self):
        rendered = compact_batch_preview({"sampling": False, "candidates": [{
            "valid": True,
            "summary": {"gold_before": 20, "gold_after": 6, "units_before": 4, "units_after": 5},
            "forecasts": [],
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 38, "distinct_attacker_count": 3,
                "max_incoming_sum": 42, "lethal_attackers_needed": 3,
                "origins_conflict": True,
                "threats": [{"attacker_id": 9, "origin_col": 4, "origin_row": 7}],
            }]},
        }]})
        self.assertIn("C0 R1 hp=38 attackers=3 max_sum=42 lethal_n=3 conflicts=True", rendered)
        self.assertNotIn("origin_col", rendered)
        self.assertLess(len(rendered.encode()), 8192)

    def test_preview_request_is_bounded_and_uses_normal_order_validation(self):
        request = json.dumps({"tool": "preview_batch", "candidates": [
            [{"action": "EndTurn"}],
            [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}, {"action": "EndTurn"}],
        ]})
        self.assertEqual(len(validate_preview_request(request)), 2)
        with self.assertRaises(ValueError):
            validate_preview_request(json.dumps({"tool": "preview_batch", "candidates": [
                [{"action": "EndTurn"}], [{"action": "EndTurn"}], [{"action": "EndTurn"}]
            ]}))

    def test_validate_batch_query_is_revision_pinned_and_preserves_orders(self):
        requests = []
        orders = [{"action": "EndTurn"}]

        def exchange(request):
            requests.append(request)
            return {"ok": True, "body": {"valid": True, "results": [{"ok": True}]}}

        self.assertEqual(query_validate_batch(exchange, orders, 17)["valid"], True)
        self.assertEqual(requests, [{"action": "Query", "what": "validate_batch",
                                    "state_revision": 17, "orders": orders}])

    def test_tactical_surface_query_is_singleton_and_revision_pinned(self):
        requests = []
        def exchange(request):
            requests.append(request)
            return {"ok": True, "body": {"units": []}}
        self.assertEqual(query_tactical_surface(exchange, 17), {"units": []})
        self.assertEqual(requests, [{"action": "Query", "what": "tactical_surface",
                                     "state_revision": 17}])

    def test_compact_tactical_surface_separates_moves_and_attacks(self):
        rendered = compact_unit_inspection({"unit_id": 5, "origins": [
            {"col": 2, "row": 7, "current": True, "movable": False,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [7100, 2500, 400],
                 "expected_damage_tenths": [210, 20]}}]}]})
        self.assertIn("COORDS=col,row", rendered)
        self.assertIn("U5 at=2,7 moves=- attacks=@>T9 p[7100, 2500, 400] e[210, 20]", rendered)

        rendered = compact_unit_inspection({"unit_id": 5, "origins": [
            {"col": 3, "row": 7, "current": False, "movable": True,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [7100, 2500, 400],
                 "expected_damage_tenths": [210, 20]}}]},
            {"col": 4, "row": 7, "current": False, "movable": True,
             "engagements": []}]})
        self.assertIn("U5 moves=3,7|4,7 attacks=3,7>T9 p[7100, 2500, 400] e[210, 20]", rendered)
        self.assertNotIn("at=3,7", rendered)

    def test_attack_coverage_groups_targets_and_current_attackers(self):
        surface = {"units": [
            {"unit_id": 3, "origins": [
                {"current": True, "engagements": [{"defender_id": 9}]},
                {"current": False, "engagements": [{"defender_id": 10}]},
            ]},
            {"unit_id": 4, "origins": [{"current": False, "engagements": [{"defender_id": 9}]}]},
            {"unit_id": 5, "origins": [{"current": False, "engagements": []}]},
        ]}
        coverage = tactical_attack_coverage(surface)
        self.assertEqual(coverage["available"], {3, 4})
        self.assertEqual(coverage["current"], {3})
        self.assertEqual(coverage["targets"], {9: {3, 4}, 10: {3}})
        rendered = compact_tactical_surface(surface)
        self.assertIn("COVERAGE available=U3,U4 current=U3 targets=U9:U3,U4;U10:U3", rendered)

    def test_default_tactical_card_summarizes_movable_origins(self):
        rendered = compact_tactical_surface({"units": [{"unit_id": 5, "origins": [
            {"col": 2, "row": 7, "current": True, "movable": False,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [1000, 9000, 0], "expected_damage_tenths": [80, 20]}}]},
            {"col": 3, "row": 7, "current": False, "movable": True,
             "engagements": [{"defender_id": 10, "forecast": {
                 "outcome_bps": [0, 10000, 0], "expected_damage_tenths": [30, 0]}}]},
        ]}]})
        self.assertIn("U5 at=2,7 move_n=1 targets=U9,U10", rendered)
        self.assertIn("current_attacks=T9", rendered)
        self.assertNotIn("3,7>T10", rendered)
        self.assertIn("inspect=inspect_unit", rendered)

    def test_compact_tactical_surface_renders_threat_and_economy_facts(self):
        rendered = compact_tactical_surface({
            "units": [],
            "threats": {"projected_time_of_day": "Night", "recruiters": [{
                "recruiter_id": 1, "hp": 20, "col": 2, "row": 7,
                "distinct_attacker_count": 1, "max_incoming_sum": 20,
                "lethal_attackers_needed": 1, "origins_conflict": False,
                "attacker_max_damage": [{"attacker_id": 16, "max_damage": 20}],
                "threats": [{"attacker_id": 16, "origin_col": 4, "origin_row": 7,
                             "moved": True, "max_damage": 20,
                             "forecast": {"outcome_bps": [1200, 8000, 800],
                                          "expected_damage_tenths": [150, 20]}}]}]},
            "economy": {"gold": 6, "next_village_income": 4,
                        "vacatable_castles": [{"unit_id": 8, "col": 3, "row": 7,
                                               "destinations": [{"col": 4, "row": 7}]}]},
        })
        self.assertIn("THREAT R1 hp=20 at=2,7 tod=Night attackers=1 max_sum=20 lethal_n=1", rendered)
        self.assertIn("detail=U16:m20", rendered)
        self.assertIn("E g6 income=4 vacate=U8@3,7>4,7", rendered)

    def test_compact_tactical_surface_groups_recruiter_threat_origins(self):
        rendered = compact_tactical_surface({
            "threats": {"visibility": "full", "projected_time_of_day": "Night", "recruiters": [{
                "recruiter_id": 1, "hp": 20, "col": 2, "row": 7, "terrain": "keep",
                "distinct_attacker_count": 2, "max_incoming_sum": 40,
                "lethal_attackers_needed": 1, "origins_conflict": False,
                "threats": [
                    {"attacker_id": 16, "origin_col": 4, "origin_row": 7,
                     "moved": True, "max_damage": 20},
                    {"attacker_id": 18, "origin_col": 4, "origin_row": 7,
                     "moved": True, "max_damage": 20},
                ],
            }]},
        })
        self.assertIn("terrain=keep on_keep=True", rendered)
        self.assertIn("THREAT_HEX R1 at=4,7~ attackers=U16,U18 max=20", rendered)

    def test_compact_observation_is_deterministic_and_keeps_instance_facts(self):
        state = {"turn": 2, "active_faction": 0, "time_of_day": "day", "cols": 3, "rows": 2,
                 "gold": [4, 5],
                 "terrain": [{"col": 0, "row": 0, "terrain_id": "keep"}],
                 "units": [{"id": 2, "faction": 1, "def_id": "orc", "col": 0, "row": 0,
                            "hp": 7, "max_hp": 9, "moved": True, "attacked": False,
                            "xp": 1, "xp_needed": 4, "advancement_pending": False},
                           {"id": 1, "faction": 0, "def_id": "leader", "col": 1, "row": 0,
                            "hp": 10, "max_hp": 10, "moved": False, "attacked": False,
                            "xp": 0, "xp_needed": 4, "advancement_pending": True}]}
        rendered = compact_observation(state)
        self.assertEqual(rendered, compact_observation(dict(state)))
        self.assertIn("id=1", rendered)
        self.assertIn("terrain=keep", rendered)  # occupied terrain is recoverable
        self.assertIn("pending=True", rendered)
    def test_final_end_turn(self):
        self.assertEqual(validate_orders('[{"action":"Move","unit_id":1,"col":1,"row":1},{"action":"EndTurn"}]')[-1]["action"], "EndTurn")

    def test_missing_final_end_turn_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Move","unit_id":1,"col":1,"row":1}]')

    def test_non_final_end_turn_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"EndTurn"},{"action":"Move"}]')

    def test_query_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Query","what":"state"},{"action":"EndTurn"}]')

    def test_strict_recruit_batch_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"RecruitBatch","def_id":"Skeleton","count":1},{"action":"EndTurn"}]', strict=True)

    def test_engage_validation_and_compact_type_profiles(self):
        orders = '[{"action":"Engage","target_id":9,"steps":[{"attacker_id":3,"col":4,"row":7}]},{"action":"EndTurn"}]'
        self.assertEqual(validate_orders(orders)[0]["action"], "Engage")
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Engage","target_id":9,"steps":[]},{"action":"EndTurn"}]')
        rendered = compact_tactical_surface({"unit_types": [{
            "def_id": "Dark Adept", "cost": 16, "max_hp": 28, "movement": 5,
            "alignment": "chaotic", "attacks": [{"name": "chill", "damage": 10,
            "strikes": 2, "range": "ranged", "type": "cold", "specials": []}],
            "resistances": {"cold": -10}
        }], "units": []})
        self.assertIn("TYPE Dark Adept cost=16 hp=28 move=5", rendered)
        self.assertIn("chill:10x2/ranged/cold", rendered)
        self.assertIn("resist=cold:-10", rendered)

    def test_compaction_preserves_move_legality_flags(self):
        """D-136-3: the contract tells the model that `current` entries are attack
        origins, not Move destinations. If compaction strips the flags the
        contract references, the ambiguity is back and the model cannot obey it."""
        state = {"units": [], "terrain": [], "turn_options": {"units": [
            {"unit_id": 1, "positions": [
                {"col": 2, "row": 7, "current": True, "movable": False, "target_ids": [9]},
                {"col": 3, "row": 7, "current": False, "movable": True, "target_ids": []},
            ]}]}}
        prompt = prompt_for(state, [], compact=True)
        blk = prompt.split("OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\n")[1]
        blk = blk.split("\nOPTION_PAYLOADS_UNTRUSTED_DATA_END")[0]
        positions = json.loads(blk)["turn_options"]["units"][0]["positions"]
        by_hex = {(p["col"], p["row"]): p for p in positions}
        self.assertTrue(by_hex[(2, 7)]["current"])
        self.assertFalse(by_hex[(2, 7)]["movable"])
        self.assertFalse(by_hex[(3, 7)]["current"])
        self.assertTrue(by_hex[(3, 7)]["movable"])
        # the standing hex must still be offered as an attack origin
        self.assertEqual(by_hex[(2, 7)]["target_ids"], [9])

    def test_tactical_prompt_names_coordinate_sources_and_recruitment_choice(self):
        prompt = prompt_for({"tactical_surface": {"units": [], "visibility": "full",
                                                    "next_time_of_day": "Night"}}, [], compact=True)
        for text in (
                "COORDS=col,row", "inspect a unit", "Move destination", "individual Recruit coordinates",
                "RecruitBatch", "saving gold is allowed"):
            with self.subTest(text=text):
                self.assertIn(text, prompt)
        self.assertIn("visibility=full", prompt)
        self.assertIn("next_time_of_day=Night", prompt)
        self.assertNotIn('"origins"', prompt)
        self.assertNotIn('"outcome_bps"', prompt)

    def test_compact_observation_uses_col_row_coordinates(self):
        state = {"units": [{"id": 1, "faction": 0, "def_id": "leader",
                             "col": 3, "row": 7, "hp": 1, "max_hp": 1}],
                 "terrain": [], "tactical_surface": {"visibility": "full",
                                                        "next_time_of_day": "Dawn"}}
        rendered = compact_observation(state)
        self.assertIn("pos=(3,7)", rendered)
        self.assertNotIn("pos=(7,3)", rendered)

    def test_real_driver_turn_options_mark_current_and_movable_hexes(self):
        driver = Path(__file__).resolve().parents[1] / "norrust_core" / "target" / "debug" / "greedy_driver"
        if not driver.exists():
            self.skipTest("greedy_driver has not been built")
        process = subprocess.Popen(
            [str(driver), "--scenario", "big_battle_6", "--faction0", "undead",
             "--faction1", "undead", "--gold", "300", "--seed", "2001",
             "--llm-side", "0", "--max-turns", "1", "--turn-timeout", "5",
             "--query-budget-seconds", "5"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(json.loads(process.stdout.readline())["type"], "protocol")
            self.assertEqual(json.loads(process.stdout.readline())["type"], "state")
            process.stdin.write(json.dumps({"action": "Query", "what": "turn_options"}) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            positions = [position for unit in response["body"]["units"]
                         for position in unit["positions"]]
            self.assertTrue(any(position.get("current") is True and position.get("movable") is False
                                for position in positions))
            self.assertTrue(any(position.get("current") is False and position.get("movable") is True
                                for position in positions))
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()

    def test_prompt_is_canonical(self):
        state = {"units": [{"id": 2}, {"id": 1}]}
        self.assertEqual(prompt_for(state, []), prompt_for(state, []))

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"EndTurn","surprise":true}]')

    def test_advance_requires_one_selector(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Advance","unit_id":1},{"action":"EndTurn"}]')

    def test_prompt_is_a_self_contained_action_contract(self):
        prompt = prompt_for({"units": []}, [],
                            {"options": [{"def_id": "Skeleton", "cost": 3,
                                           "affordable": True}],
                             "placement_hexes": [{"col": 2, "row": 4}],
                             "faction_id": "undead", "side_can_place": True,
                             "batch_macro_enabled": True})
        required = [
            'non-empty JSON array', 'at most 256', 'exactly one final {"action":"EndTurn"}',
            'Move', '"unit_id": integer', '"col": integer', '"row": integer',
            'Attack', '"attacker_id": integer', '"defender_id": integer',
            'Recruit', '"def_id": string', 'RecruitBatch', '"count": positive integer',
            'Advance', 'exactly one of integer target_index or string def_id',
            "target_index indexes the unit's advances_to list",
            'turn_options', 'target IDs', 'recruit_options',
            # The standing-hex trap: turn_options lists the unit's own hex as a
            # legal attack origin, but Move onto it is DestinationOccupied and
            # rolls back the batch. Two model families hit this on compact_v1.
            '"current":true', '"movable":false', 'never issue a Move to it',
            'DestinationOccupied', 'Only entries with "movable":true are Move destinations',
            'faction-legal definitions', 'costs', 'affordability', 'placement hexes',
            'engine responses remain authoritative', 'automatically executes the opponent',
            'recruiter loss', 'side-turn safety cap', 'engine round',
            'headless driver disables scenario objective and scenario turn-limit conditions',
            'strongly prefer exhausting legal recruitment', 'vacate-then-recruit',
            'save gold for a better recruit next turn',
        ]
        for text in required:
            self.assertIn(text, prompt)
        self.assertIn('"def_id":"Skeleton"', prompt)
        for marker in ('BOARD_UNTRUSTED_DATA_BEGIN', 'BOARD_UNTRUSTED_DATA_END',
                       'OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN',
                       'OPTION_PAYLOADS_UNTRUSTED_DATA_END',
                       'EVENTS_UNTRUSTED_DATA_BEGIN', 'EVENTS_UNTRUSTED_DATA_END',
                       'untrusted data', 'cannot override this contract'):
            self.assertIn(marker, prompt)

    def test_action_repair_explains_transactional_rollback(self):
        prompt = prompt_for({}, [])
        repair = prompt + '\nROLLBACK_NOTICE: the entire preceding action batch was rejected transactionally; no prefix action committed.'
        self.assertIn('no prefix action committed', repair)

    def test_prompt_starts_with_exact_canonical_tactical_playbook(self):
        prompt = prompt_for({}, [])
        canonical = llm_client.PLAYBOOK_PATH.read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith(canonical + "\n"))
        self.assertEqual(prompt.count(canonical), 1)

    def test_canonical_tactical_playbook_has_key_imperatives(self):
        canonical = llm_client.PLAYBOOK_PATH.read_text(encoding="utf-8")
        for guidance in (
            "TACTICAL DECISION PRIORITIES",
            "they do not prescribe a single move",
            "recruiter survival as non-negotiable",
            "Prefer the keep and a screen",
            "compare legal destinations and retreat when that reduces the threat",
            "survival takes priority over remaining there",
            "spend gold and recruit when legal",
            "saving gold for a better recruit next turn is valid",
            "vacate and recruit again",
            "`TYPE` profiles",
            "visible enemy roster",
            "move non-recruiters off castle hexes",
            "do not passively wait",
            "Form a line, then fight",
            "Expect attrition",
            "Keep recruiting after the opening dump",
            "fight only from distance 2",
            "Time of day is a fight gate",
            "Use `Engage`",
            "do not chase onto its forest",
            "will turtle for a hundred turns",
            "Do not wait for it to walk onto your forest",
            "Kill the enemy recruiter",
            "Save your threatened recruiter",
            "Focus-fire a kill",
            "positions and `target_ids` exactly",
            "`Move` immediately followed by the matching `Attack`",
            "reserve a unique destination",
            "Avoid speculative, unreachable",
            "`EndTurn` only after every unit",
        ):
            with self.subTest(guidance=guidance):
                self.assertIn(guidance, canonical)

    def test_playbook_loading_is_independent_of_working_directory(self):
        expected_path = Path(llm_client.__file__).resolve().parents[1] / \
            "docs" / "LLM_TACTICAL_PLAYBOOK.md"
        self.assertEqual(llm_client.PLAYBOOK_PATH, expected_path)
        expected = llm_client.PLAYBOOK_PATH.read_text(encoding="utf-8")
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertTrue(prompt_for({}, []).startswith(expected + "\n"))
            finally:
                os.chdir(original_cwd)

    def test_missing_playbook_has_actionable_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-norrust-playbook.md"
            with mock.patch.object(llm_client, "PLAYBOOK_PATH", missing), \
                    self.assertRaisesRegex(
                        RuntimeError,
                        r"model_prompt_error: canonical tactical playbook is missing or unreadable.*"
                        r"restore docs/LLM_TACTICAL_PLAYBOOK\.md",
                    ):
                prompt_for({}, [])

    def test_docs_link_to_canonical_playbook_without_checklist_duplication(self):
        docs_dir = llm_client.PLAYBOOK_PATH.parent
        for name in ("LLM_CLIENT.md", "LLM_VS_ALGORITHM.md"):
            text = (docs_dir / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("[MEMORYLESS TACTICAL PLAYBOOK](LLM_TACTICAL_PLAYBOOK.md)", text)
                self.assertIn("inline near the beginning of every model", text)
                self.assertIn("does not need filesystem access", text)
                self.assertNotIn("Protect the recruiter/leader first", text)
                self.assertNotIn("Apply this every turn:", text)

    def test_prompt_defines_exactly_one_prior_recruiter_side_losing_all_recruiters(self):
        prompt = prompt_for({}, [])
        self.assertIn("exactly one side that previously had a recruiter now has none", prompt)
        self.assertNotIn("sole recruiter", prompt)

    def test_prompt_omits_disabled_recruit_macro_wording(self):
        prompt = prompt_for({}, [], {}, recruit_batch_enabled=False)
        self.assertNotIn('RecruitBatch', prompt)

    def test_validation_enforces_scalar_types_and_positive_count(self):
        valid = '[{"action":"RecruitBatch","def_id":"Skeleton","count":1},{"action":"EndTurn"}]'
        validate_orders(valid)
        for order in [
            {"action": "Move", "unit_id": "1", "col": 1, "row": 1},
            {"action": "Recruit", "def_id": 3, "col": 1, "row": 1},
            {"action": "RecruitBatch", "def_id": "Skeleton", "count": 0},
            {"action": "RecruitBatch", "def_id": "Skeleton", "count": True},
            {"action": "Move", "unit_id": 2**32, "col": 1, "row": 1},
            {"action": "Move", "unit_id": 1, "col": 2**31, "row": 1},
            {"action": "Advance", "unit_id": 1, "target_index": -1},
        ]:
            with self.subTest(order=order), self.assertRaises(ValueError):
                validate_orders(json.dumps([order, {"action": "EndTurn"}]))

    def test_usage_metadata_rejects_wrong_type_boolean_and_negative_counts(self):
        args = argparse.Namespace(token_input_limit=None, token_output_limit=None,
                                  token_total_limit=None)
        for usage in [[], {"input_tokens": True, "output_tokens": 1},
                      {"input_tokens": -1, "output_tokens": 1},
                      {"input_tokens": 1, "output_tokens": -1}]:
            with self.subTest(usage=usage), self.assertRaises(RuntimeError):
                enforce_usage(ModelReply("[]", usage), args)

    def test_query_options_are_singleton_and_preserve_success_body(self):
        calls = []

        def exchange(request):
            calls.append(request)
            return {"type": "status", "ok": True, "what": request["what"],
                    "body": {"authoritative": request["what"]}}

        result = query_options(exchange)
        self.assertEqual([call["what"] for call in calls],
                         ["turn_options", "recruit_options"])
        self.assertEqual(result["turn_options"], {"authoritative": "turn_options"})
        self.assertEqual(result["recruit_options"], {"authoritative": "recruit_options"})
        prompt = prompt_for(result, [], result["recruit_options"])
        self.assertIn('"authoritative":"turn_options"', prompt)
        self.assertIn('"authoritative":"recruit_options"', prompt)

    def test_failure_terminal_classes_are_durable_invalid_failures(self):
        lines = [
            ("setup_error", "invalid_setup"),
            ("timeout", "turn_timeout"),
            ("eof", "driver_eof"),
            ("infrastructure_failure", "greedy_turn_failed"),
            ("unknown_reason", "mystery"),
            ("malformed_reason", None),
        ]
        for label, reason in lines:
            with self.subTest(reason=label):
                line = {"type": "game_end", "winner": None,
                        "code": "driver_code", "message": "driver message"}
                if reason is not None:
                    line["reason"] = reason
                code, terminal, fsync_calls = self.run_terminal(line)
                self.assertEqual(code, 1)
                self.assertTrue(terminal["infrastructure_invalid"])
                self.assertFalse(terminal["gameplay_valid"])
                self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
                self.assertEqual(terminal.get("reason"), reason)
                self.assertEqual(terminal["code"], "driver_code")
                self.assertEqual(terminal["message"], "driver message")
                self.assertGreaterEqual(fsync_calls, 1)

    def test_malformed_driver_json_is_durable_invalid_failure(self):
        code, terminal, fsync_calls = self.run_terminal("not json\n")
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertEqual(terminal["reason"], "infrastructure_failure")
        self.assertEqual(terminal["code"], "driver_protocol_invalid_json")
        self.assertEqual(terminal["message"], "driver emitted invalid JSON")
        self.assertEqual(terminal["raw_line"], "not json")
        self.assertGreaterEqual(fsync_calls, 1)

    def test_gameplay_and_max_turns_game_end_remain_successful(self):
        for line in [
            {"type": "game_end", "reason": "winner", "winner": 0},
            {"type": "game_end", "reason": "max_turns", "winner": None},
        ]:
            with self.subTest(reason=line["reason"]):
                code, terminal, fsync_calls = self.run_terminal(line)
                self.assertEqual(code, 0)
                self.assertFalse(terminal["infrastructure_invalid"])
                self.assertTrue(terminal["gameplay_valid"])
                self.assertEqual(terminal["terminal_class"], TERMINAL_GAMEPLAY)
                self.assertEqual(terminal["reason"], line["reason"])
                self.assertGreaterEqual(fsync_calls, 1)

    def test_status_ok_false_is_durable_failure_without_waiting_for_more_input(self):
        line = {"type": "status", "ok": False, "code": "unauthorized_side",
                "message": "model actions are not authorized"}
        code, terminal, _ = self.run_after_forwarded_orders(line)
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertEqual(terminal["reason"], "infrastructure_failure")
        self.assertEqual(terminal["code"], "driver_status_failure")
        self.assertEqual(terminal["message"], "driver returned a failed status")
        self.assertEqual(terminal["driver_failure"]["code"], "unauthorized_side")

    def test_status_nested_failed_result_is_durable_failure_without_waiting_for_more_input(self):
        # One canned reply only: the nested failure triggers a repair, the orders
        # file is exhausted, and the backend raises. An exhausted fixture is a
        # harness fault, so this stays infrastructure -- it does not exercise the
        # model_invalid path (see the two-reply test below).
        line = {"type": "status", "ok": True,
                "results": [{"ok": True}, {"ok": False, "code": "MoveError",
                                             "message": "invalid move"}]}
        code, terminal, _ = self.run_after_forwarded_orders(line)
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertIn(terminal.get("type"), {"model_error", "driver_crash", "terminal"})

    def test_classify_terminal_is_three_way(self):
        for reason in ("winner", "max_turns"):
            self.assertEqual(classify_terminal(reason), TERMINAL_GAMEPLAY)
        self.assertEqual(classify_terminal("model_invalid"), TERMINAL_MODEL_INVALID)
        for reason in ("setup_error", "timeout", "eof", "infrastructure_failure",
                       "mystery", None):
            self.assertEqual(classify_terminal(reason), TERMINAL_INFRASTRUCTURE)
        self.assertEqual(
            sorted(TERMINAL_EXIT_CODES.values()), [0, 1, 2],
            "the three classes must be distinguishable by exit code alone")

    def test_nested_failure_with_repair_exhausted_is_model_invalid(self):
        """The batch is rolled back and the model had its repair. That is a model
        failure, not a broken harness: it must not void the run as
        infrastructure_invalid, and it must not be recorded as gameplay."""
        end_turn = '[{"action":"EndTurn"}]'
        failure = {"type": "status", "ok": True,
                   "results": [{"ok": False, "code": "MoveError",
                                "message": "invalid move"}]}
        code, terminal = self.run_with_orders(
            [end_turn, end_turn],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "turn_options", "body": {}},
             {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
             failure,   # first rejection -> one repair is spent
             failure],  # second rejection -> budget gone
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        self.assertEqual(terminal["terminal_class"], TERMINAL_MODEL_INVALID)
        self.assertFalse(terminal["infrastructure_invalid"])
        self.assertFalse(terminal["gameplay_valid"])
        self.assertEqual(terminal["reason"], "model_invalid")
        self.assertEqual(terminal["code"], "action_batch_rejected")
        self.assertTrue(terminal["rolled_back"])
        self.assertEqual(terminal["driver_failure"]["code"], "MoveError")

    def test_pre_submit_validation_retries_until_a_valid_batch(self):
        end_turn = '[{"action":"EndTurn"}]'
        invalid = {"type": "status", "ok": True, "what": "validate_batch",
                   "body": {"valid": False, "failed_index": 0,
                             "results": [{"ok": False, "code": "MoveError",
                                          "message": "invalid move"}]}}
        valid = {"type": "status", "ok": True, "what": "validate_batch",
                 "body": {"valid": True, "failed_index": None,
                           "results": [{"ok": True}]}}
        code, terminal = self.run_with_orders(
            [end_turn, end_turn, end_turn],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             invalid, invalid, valid,
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            validate_before_submit=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_action_repair_can_inspect_before_returning_corrected_batch(self):
        end_turn = json.dumps([{"action": "EndTurn"}])
        inspect = json.dumps({"tool": "inspect_target", "unit_id": 9})
        invalid = {"type": "status", "ok": True, "what": "validate_batch",
                   "body": {"valid": False, "failed_index": 0,
                             "results": [{"ok": False, "code": "NotAdjacent",
                                          "message": "units are not in attack range"}]}}
        valid = {"type": "status", "ok": True, "what": "validate_batch",
                 "body": {"valid": True, "failed_index": None,
                           "results": [{"ok": True}]}}
        code, terminal = self.run_with_orders(
            [end_turn, inspect, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 4},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             invalid,
             {"type": "status", "ok": True, "what": "inspect_target",
              "body": {"target_id": 9, "hp": 20, "col": 2, "row": 2,
                       "terrain": "flat", "attacks": []}},
             valid,
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            validate_before_submit=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_preview_round_trip_forwards_model_selected_candidate(self):
        first = [{"action": "EndTurn"}]
        second = [{"action": "Move", "unit_id": 1, "col": 2, "row": 3},
                  {"action": "EndTurn"}]
        inspect_request = json.dumps({"tool": "inspect_unit", "unit_id": 1})
        preview_request = json.dumps({"tool": "preview_batch", "candidates": [first, second]})
        with tempfile.TemporaryDirectory() as directory:
            orders_path = directory + "/orders.jsonl"
            log_path = directory + "/client.jsonl"
            with open(orders_path, "w") as orders_file:
                orders_file.write(json.dumps({"text": inspect_request}) + "\n")
                orders_file.write(json.dumps({"text": preview_request}) + "\n")
                orders_file.write(json.dumps({"text": json.dumps(second)}) + "\n")
            process = FakeDriverProcess([
                {"type": "state", "active_faction": 0, "state_revision": 7},
                {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
                {"type": "status", "ok": True, "what": "inspect_unit", "body": {
                    "unit_id": 1, "origins": []}},
                {"type": "status", "ok": True, "what": "preview_batch", "body": {
                    "sampling": False, "candidates": [
                        {"valid": True, "summary": {}, "forecasts": [], "recruiter_threats": {"recruiters": []}},
                        {"valid": True, "summary": {}, "forecasts": [], "recruiter_threats": {"recruiters": []}},
                    ]}},
                {"type": "status", "ok": True, "what": "validate_batch", "body": {
                    "valid": True, "failed_index": None, "results": [{"ok": True}, {"ok": True}]}},
                {"type": "status", "ok": True, "what": "preview_batch", "body": {
                    "sampling": False, "candidates": [{"valid": True, "summary": {
                        "affordable_recruitment_remaining": False}, "forecasts": [],
                        "recruiter_threats": {"recruiters": []}}]}},
                {"type": "game_end", "reason": "max_turns", "winner": None},
            ])
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b", gold=1,
                seed=2, max_turns=3, llm_side=0, turn_timeout=20, query_budget_seconds=5,
                max_queries_per_turn=6, no_recruit_macro=False, interactive_model=False,
                orders_file=orders_path, model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None, validate_before_submit=True,
                max_model_calls_per_turn=4, event_window_observations=1, diagnostic=False,
                decision_metrics=True,
            )
            prompts = []
            original_complete = llm_client.OrdersBackend.complete
            def capture_prompt(backend, prompt):
                prompts.append(prompt)
                return original_complete(backend, prompt)
            with mock.patch.object(llm_client.OrdersBackend, "complete", capture_prompt), \
                    mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            records = [json.loads(line) for line in Path(log_path).read_text().splitlines()]

        self.assertEqual(code, 0)
        sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(sent[0]["what"], "tactical_surface")
        self.assertEqual(sent[1]["what"], "inspect_unit")
        self.assertEqual(sent[2]["what"], "preview_batch")
        self.assertEqual(sent[3]["what"], "validate_batch")
        self.assertEqual(sent[4]["what"], "preview_batch")
        self.assertEqual(sent[5], second)
        self.assertIn(inspect_request, prompts[1])
        self.assertIn(preview_request, prompts[2])
        self.assertIn(json.dumps(first), prompts[2])
        self.assertIn(json.dumps(second), prompts[2])
        self.assertEqual([record for record in records if record["type"] == "preview_selection"][0]["matched_candidate"], 1)
        self.assertEqual(len([record for record in records if record["type"] == "final_batch_preview"]), 1)

    def test_model_output_invalid_twice_is_model_invalid(self):
        """Validation failure on both the first call and the repair is the model
        failing to emit a legal batch -- classified as model, not harness."""
        code, terminal = self.run_with_orders(
            ["not a json array", "still not a json array"],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "turn_options", "body": {}},
             {"type": "status", "ok": True, "what": "recruit_options", "body": {}}],
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        self.assertEqual(terminal["terminal_class"], TERMINAL_MODEL_INVALID)
        self.assertFalse(terminal["infrastructure_invalid"])
        self.assertFalse(terminal["gameplay_valid"])
        self.assertEqual(terminal["code"], "action_validation_invalid")

    def test_tool_budget_exhaustion_repairs_with_context(self):
        request = json.dumps({"tool": "inspect_unit", "unit_id": 1})
        end_turn = json.dumps([{"action": "EndTurn"}])
        code, terminal = self.run_with_orders(
            [request, request, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 1},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             {"type": "status", "ok": True, "what": "inspect_unit",
              "body": {"unit_id": 1, "origins": []}},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=4,
            max_tool_calls_per_turn=1,
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_critical_draft_can_be_confirmed_after_preview(self):
        end_turn = json.dumps([{"action": "EndTurn"}])
        review_tool = json.dumps({"tool": "inspect_unit", "unit_id": 1})
        code, terminal = self.run_with_orders(
            [end_turn, review_tool, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 0,
              "units": [{"id": 1, "faction": 0, "can_recruit": True}]},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {
                 "threats": {"recruiters": [{"recruiter_id": 1, "lethal_attackers_needed": 1}]}}},
             {"type": "status", "ok": True, "what": "preview_batch", "body": {
                 "sampling": False, "candidates": [{"valid": True, "recruiter_threats": {
                     "recruiters": [{"recruiter_id": 1, "hp": 34,
                                     "distinct_attacker_count": 2, "max_incoming_sum": 40,
                                     "lethal_attackers_needed": 1}]}}]}},
             {"type": "status", "ok": True, "what": "validate_batch", "body": {
                 "valid": True, "failed_index": None, "results": [{"ok": True}]}},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=4,
            max_tool_calls_per_turn=2,
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["draft_reviews"], 1)
        self.assertEqual(terminal["draft_confirmations"], 1)
        self.assertEqual(terminal["draft_revisions"], 0)
        self.assertEqual(terminal["draft_review_repairs"], 1)

    def test_backend_transport_failure_stays_infrastructure(self):
        """A RuntimeError from the backend is transport, not play. The model
        never emitted an illegal batch, so it must not be blamed for one."""
        code, terminal = self.run_with_orders(
            [],  # exhausted immediately: backend raises RuntimeError
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "turn_options", "body": {}},
             {"type": "status", "ok": True, "what": "recruit_options", "body": {}}],
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_INFRASTRUCTURE])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["code"], "model_backend_failure")

    def test_model_invalid_is_never_counted_as_gameplay_or_infrastructure(self):
        """The whole point of the third bucket: a model_invalid run is a
        completed evaluation that is neither a gameplay result nor harness
        breakage. Asserted as an invariant over all three classes."""
        end_turn = '[{"action":"EndTurn"}]'
        failure = {"type": "status", "ok": True,
                   "results": [{"ok": False, "code": "MoveError", "message": "x"}]}
        cases = [
            (TERMINAL_GAMEPLAY, [end_turn],
             [{"type": "game_end", "reason": "max_turns", "winner": None}]),
            (TERMINAL_MODEL_INVALID, [end_turn, end_turn],
             [{"type": "state", "active_faction": 0},
              {"type": "status", "ok": True, "what": "turn_options", "body": {}},
              {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
              failure, failure]),
            (TERMINAL_INFRASTRUCTURE, [end_turn],
             [{"type": "game_end", "reason": "timeout", "winner": None}]),
        ]
        for expected, orders, lines in cases:
            with self.subTest(terminal_class=expected):
                code, terminal = self.run_with_orders(orders, lines)
                self.assertEqual(terminal["terminal_class"], expected)
                self.assertEqual(code, TERMINAL_EXIT_CODES[expected])
                self.assertEqual(terminal["gameplay_valid"],
                                 expected == TERMINAL_GAMEPLAY)
                self.assertEqual(terminal["infrastructure_invalid"],
                                 expected == TERMINAL_INFRASTRUCTURE)

    def test_success_status_continues_to_game_end(self):
        status = {"type": "status", "ok": True, "results": [{"ok": True}]}
        code, terminal, _ = self.run_after_forwarded_orders(
            status, tail={"type": "game_end", "reason": "max_turns", "winner": None})
        self.assertEqual(code, 0)
        self.assertFalse(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_action_repair_budget_resets_each_turn(self):
        action_failure = {"type": "status", "ok": True,
                          "results": [{"ok": False, "code": "MoveError",
                                       "message": "invalid move"}]}
        lines = [
            {"type": "state", "active_faction": 0},
            {"type": "status", "ok": True, "what": "turn_options", "body": {}},
            {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
            action_failure,
            {"type": "state", "active_faction": 0},
            {"type": "status", "ok": True, "what": "turn_options", "body": {}},
            {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
            action_failure,
            {"type": "game_end", "reason": "max_turns", "winner": None},
        ]
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            orders_path = directory + "/orders.jsonl"
            with open(orders_path, "w") as orders:
                for _ in range(4):
                    orders.write('{"text":"[{\\"action\\":\\"EndTurn\\"}]"}\n')
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess(lines)
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        self.assertEqual(code, 0)
        self.assertEqual(len([record for record in records
                              if record["type"] == "action_repair"]), 2)

    def run_terminal(self, line):
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=True, orders_file=None,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess([line])
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync") as fsync:
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records[-1], fsync.call_count

    def run_with_orders(self, order_texts, driver_lines, validate_before_submit=False,
                        max_model_calls_per_turn=4, max_tool_calls_per_turn=4):
        """Drive the client with N canned model replies and explicit driver output."""
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            orders_path = directory + "/orders.jsonl"
            with open(orders_path, "w") as orders:
                for text in order_texts:
                    orders.write(json.dumps({"text": text}) + "\n")
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
                validate_before_submit=validate_before_submit,
                max_model_calls_per_turn=max_model_calls_per_turn,
                max_tool_calls_per_turn=max_tool_calls_per_turn,
            )
            process = FakeDriverProcess(driver_lines)
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records[-1]

    def run_after_forwarded_orders(self, action_status, tail=None):
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            orders_path = directory + "/orders.jsonl"
            with open(orders_path, "w") as orders:
                orders.write('{"text":"[{\\"action\\":\\"EndTurn\\"}]"}\n')
            lines = [
                {"type": "state", "active_faction": 0},
                {"type": "status", "ok": True, "what": "turn_options", "body": {}},
                {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
                action_status,
            ]
            if tail is not None:
                lines.append(tail)
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess(lines)
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync") as fsync:
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records[-1], fsync.call_count


if __name__ == "__main__":
    unittest.main()
