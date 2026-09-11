import argparse
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import llm_client


class _Driver:
    def __init__(self, lines):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(json.dumps(line) + "\n" for line in lines))
        self.stderr = io.StringIO()

    def poll(self):
        return 0

    def terminate(self):
        pass


def _args(orders_file, log_file, prompt_cap):
    return argparse.Namespace(
        driver="driver", scenario="scenario", faction0="a", faction1="b",
        gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
        query_budget_seconds=5, max_queries_per_turn=6,
        no_recruit_macro=False, interactive_model=False,
        orders_file=str(orders_file), model_command=None, model_timeout=7,
        log=str(log_file), max_prompt_bytes=prompt_cap,
        token_input_limit=None, token_output_limit=None, token_total_limit=None,
        validate_before_submit=False, incremental_turns=False,
        max_model_calls_per_turn=4, max_tool_calls_per_turn=4,
        reasoning_effort=None, timeout_finish=False, decision_mode="batch",
        action_encoding="coordinates", max_partial_batches_per_turn=3,
        disable_agenda_sweep=True, diagnostic=False, decision_metrics=False,
        event_window_observations=1, max_game_total_tokens=None,
        player_model=None, max_output_tokens=131072,
    )


def _run_case(replies, lines, prompt_cap):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        orders_file = root / "orders.jsonl"
        log_file = root / "client.jsonl"
        orders_file.write_text(
            "".join(json.dumps({"text": reply}) + "\n" for reply in replies),
            encoding="utf-8",
        )
        process = _Driver(lines)
        prompts = []
        original_complete = llm_client.OrdersBackend.complete

        def capture_prompt(backend, prompt):
            prompts.append(prompt)
            return original_complete(backend, prompt)

        args = _args(orders_file, log_file, prompt_cap)
        with mock.patch.object(llm_client, "subprocess") as subprocess_module, \
                mock.patch.object(llm_client.OrdersBackend, "complete", capture_prompt), \
                mock.patch.object(llm_client, "source_metadata", return_value={}), \
                mock.patch.object(llm_client, "query_tactical_surface", return_value={}):
            subprocess_module.Popen.return_value = process
            code = llm_client.run(args)
        records = [json.loads(line) for line in log_file.read_text().splitlines()]
        return code, records, prompts


class FinalPromptCapTests(unittest.TestCase):
    @staticmethod
    def state():
        return {"type": "state", "active_faction": 0,
                "state_revision": 7, "units": []}

    @staticmethod
    def one_action_lines():
        return [
            FinalPromptCapTests.state(),
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]

    def test_final_delivery_cap_is_inclusive_and_one_less_blocks_backend(self):
        reply = '[{"action":"EndTurn"}]'
        code, records, prompts = _run_case(
            [reply], self.one_action_lines(), 16 * 1024 * 1024)
        self.assertEqual(code, 0)
        self.assertEqual(len(prompts), 1)
        delivered_bytes = len(prompts[0].encode())
        model_request = next(record for record in records
                             if record.get("type") == "model_request"
                             and record.get("status") == "completed")
        model = next(record for record in records if record.get("type") == "model")
        self.assertEqual(model_request["prompt_bytes"], delivered_bytes)
        self.assertEqual(model["prompt_bytes"], delivered_bytes)
        self.assertEqual(model_request["prompt_hash"], hashlib.sha256(
            prompts[0].encode()).hexdigest())

        inclusive_code, _, inclusive_prompts = _run_case(
            [reply], self.one_action_lines(), delivered_bytes)
        self.assertEqual(inclusive_code, 0)
        self.assertEqual(len(inclusive_prompts), 1)

        blocked_code, blocked_records, blocked_prompts = _run_case(
            [reply], self.one_action_lines(), delivered_bytes - 1)
        self.assertEqual(blocked_code, llm_client.TERMINAL_EXIT_CODES[
            llm_client.TERMINAL_INFRASTRUCTURE])
        self.assertEqual(blocked_prompts, [])
        preflight = next(record for record in blocked_records
                         if record.get("type") == "preflight_error")
        self.assertEqual(preflight["code"], "prompt_too_large")
        self.assertGreater(preflight["bytes"], preflight["limit"])

    def test_inspection_followup_cap_includes_budget_suffix_and_blocks_dispatch(self):
        inspect = json.dumps({"tool": "inspect_hex", "col": 0,
                              "row": 0, "phase": "current"})
        action = '[{"action":"EndTurn"}]'
        lines = [
            self.state(),
            {"type": "status", "ok": True, "what": "inspect_hex", "body": {}},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        code, records, prompts = _run_case(
            [inspect, action], lines, 16 * 1024 * 1024)
        self.assertEqual(code, 0)
        self.assertEqual(len(prompts), 2)
        followup_bytes = len(prompts[1].encode())
        self.assertIn("GAME_BUDGET_CONTEXT_BEGIN", prompts[1])
        followup = next(record for record in records
                        if record.get("type") == "tool_followup")
        self.assertEqual(followup["prompt_bytes"], followup_bytes)
        for request, prompt in zip(
                [record for record in records if record.get("type") == "model_request"
                 and record.get("status") == "completed"], prompts):
            self.assertEqual(request["prompt_bytes"], len(prompt.encode()))
            self.assertEqual(request["prompt_hash"], hashlib.sha256(
                prompt.encode()).hexdigest())

        blocked_code, blocked_records, blocked_prompts = _run_case(
            [inspect, action], lines, followup_bytes - 1)
        self.assertEqual(blocked_code, llm_client.TERMINAL_EXIT_CODES[
            llm_client.TERMINAL_INFRASTRUCTURE])
        self.assertEqual(len(blocked_prompts), 1)
        preflight = next(record for record in blocked_records
                         if record.get("type") == "preflight_error")
        self.assertEqual(preflight["code"], "prompt_too_large")
        self.assertGreater(preflight["bytes"], preflight["limit"])


if __name__ == "__main__":
    unittest.main()
