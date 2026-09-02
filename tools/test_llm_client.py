import argparse
import io
import json
import tempfile
import unittest
from unittest import mock

from .llm_client import ModelReply, enforce_usage, prompt_for, query_options, run, validate_orders


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
            'turn_options', 'current-unit positions', 'target IDs', 'recruit_options',
            'faction-legal definitions', 'costs', 'affordability', 'placement hexes',
            'engine responses remain authoritative', 'automatically executes the opponent',
            'recruiter loss', 'side-turn safety cap', 'engine round',
            'headless driver disables scenario objective and scenario turn-limit conditions',
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
                self.assertEqual(terminal.get("reason"), reason)
                self.assertEqual(terminal["code"], "driver_code")
                self.assertEqual(terminal["message"], "driver message")
                self.assertGreaterEqual(fsync_calls, 1)

    def test_malformed_driver_json_is_durable_invalid_failure(self):
        code, terminal, fsync_calls = self.run_terminal("not json\n")
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
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
                self.assertEqual(terminal["reason"], line["reason"])
                self.assertGreaterEqual(fsync_calls, 1)

    def test_status_ok_false_is_durable_failure_without_waiting_for_more_input(self):
        line = {"type": "status", "ok": False, "code": "unauthorized_side",
                "message": "model actions are not authorized"}
        code, terminal, _ = self.run_after_forwarded_orders(line)
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["reason"], "infrastructure_failure")
        self.assertEqual(terminal["code"], "driver_status_failure")
        self.assertEqual(terminal["message"], "driver returned a failed status")
        self.assertEqual(terminal["driver_failure"]["code"], "unauthorized_side")

    def test_status_nested_failed_result_is_durable_failure_without_waiting_for_more_input(self):
        line = {"type": "status", "ok": True,
                "results": [{"ok": True}, {"ok": False, "code": "MoveError",
                                             "message": "invalid move"}]}
        code, terminal, _ = self.run_after_forwarded_orders(line)
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertIn(terminal.get("type"), {"model_error", "driver_crash", "terminal"})

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
