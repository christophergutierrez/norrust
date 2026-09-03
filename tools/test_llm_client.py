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
    compact_observation, compact_tactical_surface, prompt_for, query_options,
    query_tactical_surface, query_validate_batch, query_preview_batch,
    run, validate_orders, validate_preview_request,
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
        rendered = compact_tactical_surface({"units": [{"unit_id": 5, "origins": [
            {"col": 2, "row": 7, "current": True, "movable": False,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [7100, 2500, 400],
                 "expected_damage_tenths": [210, 20]}}]}]}]})
        self.assertIn("COORDS=col,row", rendered)
        self.assertIn("U5 at=2,7 moves=- attacks=@>T9 p[7100, 2500, 400] e[210, 20]", rendered)

        rendered = compact_tactical_surface({"units": [{"unit_id": 5, "origins": [
            {"col": 3, "row": 7, "current": False, "movable": True,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [7100, 2500, 400],
                 "expected_damage_tenths": [210, 20]}}]},
            {"col": 4, "row": 7, "current": False, "movable": True,
             "engagements": []}]}]})
        self.assertIn("U5 moves=3,7|4,7 attacks=3,7>T9 p[7100, 2500, 400] e[210, 20]", rendered)
        self.assertNotIn("at=3,7", rendered)

    def test_compact_tactical_surface_renders_threat_and_economy_facts(self):
        rendered = compact_tactical_surface({
            "units": [],
            "threats": {"projected_time_of_day": "Night", "recruiters": [{
                "recruiter_id": 1, "hp": 20, "col": 2, "row": 7,
                "threats": [{"attacker_id": 16, "origin_col": 4, "origin_row": 7,
                             "moved": True, "max_damage": 20,
                             "forecast": {"outcome_bps": [1200, 8000, 800],
                                          "expected_damage_tenths": [150, 20]}}]}]},
            "economy": {"gold": 6, "next_village_income": 4,
                        "vacatable_castles": [{"unit_id": 8, "col": 3, "row": 7,
                                               "destinations": [{"col": 4, "row": 7}]}]},
        })
        self.assertIn("THREAT R1 hp=20 at=2,7 tod=Night U16@4,7~", rendered)
        self.assertIn("m20", rendered)
        self.assertIn("E g6 income=4 vacate=U8@3,7>4,7", rendered)

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
                "COORDS=col,row", "copy Move", "`moves`", "individual Recruit coordinates",
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
            "MEMORYLESS TACTICAL PLAYBOOK",
            "recruiter survival as non-negotiable",
            "on or near the keep",
            "never advance it merely to seek combat",
            "spend gold and recruit when legal",
            "Do not bank gold",
            "vacate and recruit again",
            "Recruit a mix",
            "never dump the remaining purse",
            "move non-recruiters off castle hexes",
            "do not passively wait",
            "Form a line, then fight",
            "Expect attrition",
            "Keep recruiting after the opening dump",
            "fight only from distance 2",
            "Time of day is a fight gate",
            "combined maximum damage",
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
                        max_model_calls_per_turn=4):
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
