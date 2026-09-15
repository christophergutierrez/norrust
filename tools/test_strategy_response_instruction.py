"""Stack 1: delivered strategy prompts match the issued decision packet."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import strategy_decision as sd
from .llm_client import (
    finalize_strategy_prompt, format_allowed_kinds, strategy_live_state_footer,
)
from .test_strategy_proposed_movement_stack3 import choose, launch, policy, prepare
from .test_strategy_routine_stack3 import DRIVER, assert_success, records


def instruction(prompt: str) -> str:
    start = prompt.rfind("STRATEGY_RESPONSE_INSTRUCTION_BEGIN")
    end = prompt.rfind("STRATEGY_RESPONSE_INSTRUCTION_END")
    if start < 0 or end < 0 or end <= start:
        raise AssertionError("missing strategy response instruction")
    return prompt[start:end]


def footer_count(prompt: str) -> int:
    return prompt.count("STRATEGY_RESPONSE_INSTRUCTION_BEGIN")


class FooterUnitTests(unittest.TestCase):
    def test_format_allowed_kinds(self):
        self.assertEqual(format_allowed_kinds(["act"]), "act")
        self.assertEqual(format_allowed_kinds(["act", "resign"]), "act or resign")
        self.assertEqual(
            format_allowed_kinds(["set_policy", "act", "finish_turn", "resign"]),
            "set_policy, act, finish_turn, or resign")

    def test_proposed_destination_footer_includes_choose_not_as_global_union(self):
        packet = sd.build_decision_packet(
            "contact",
            {"stage": "proposed_destination", "options": [
                {"option_id": "u5-safe-1", "actor_id": 5, "actions": []}]},
            revision=1, decision_id="dec-1")
        text = strategy_live_state_footer({"state_revision": 1}, packet=packet)
        self.assertIn("choose", instruction("x\n" + text))
        self.assertIn("set_policy", text)
        self.assertIn('"final_only":false', text)

    def test_initial_policy_footer_omits_choose(self):
        packet = sd.build_decision_packet("initial", {}, revision=0)
        text = strategy_live_state_footer({}, packet=packet)
        body = instruction("x\n" + text)
        self.assertNotIn("choose", body)
        self.assertIn("set_policy", body)

    def test_promotion_footer_omits_finish_and_choose(self):
        packet = sd.build_decision_packet("promotion_pending", {"unit_ids": [5]}, revision=2)
        body = instruction("x\n" + strategy_live_state_footer({}, packet=packet))
        self.assertNotIn("choose", body)
        self.assertNotIn('{"kind":"finish_turn"}', body)
        self.assertIn("act or resign", body)
        self.assertIn("finish_turn may be true or false on act", body)

    def test_empty_menu_contact_footer_omits_choose(self):
        packet = sd.build_decision_packet(
            "contact",
            {"stage": "current_state", "options": []},
            revision=4)
        body = instruction("x\n" + strategy_live_state_footer({}, packet=packet))
        self.assertNotIn("choose", body)
        self.assertIn("act, finish_turn, or resign", body)

    def test_final_only_requires_true_on_act_and_choose(self):
        packet = sd.build_decision_packet(
            "contact",
            {"stage": "current_state",
             "contact_actionability": "exhausted",
             "contact_state_key": "k1",
             "options": [{"option_id": "u1-relocate-1", "actor_id": 1, "actions": []}]},
            revision=5, final_only=True)
        text = strategy_live_state_footer({}, packet=packet)
        self.assertTrue(packet.final_only)
        self.assertIn("final_only requires finish_turn true", text)
        self.assertIn('"final_only":true', text)

    def test_finalize_requires_packet_and_replaces_stale_footer(self):
        first = sd.build_decision_packet("initial", {}, revision=0)
        second = sd.build_decision_packet("promotion_pending", {"unit_ids": [1]}, revision=1)
        once = finalize_strategy_prompt("BRIEF", {"state_revision": 0}, packet=first)
        twice = finalize_strategy_prompt(
            "BRIEF\nREPAIR keep this", {"state_revision": 1}, packet=second)
        self.assertEqual(footer_count(twice), 1)
        self.assertIn("REPAIR keep this", twice)
        self.assertIn("act or resign", instruction(twice))
        self.assertNotIn("set_policy", instruction(twice))
        with self.assertRaises(RuntimeError):
            finalize_strategy_prompt("BRIEF", {}, packet=None)

    def test_quoted_untrusted_footer_is_left_intact(self):
        packet = sd.build_decision_packet("initial", {}, revision=0)
        quoted = (
            "before\n_UNTRUSTED_DATA_BEGIN\n"
            "STRATEGY_LIVE_STATE_BEGIN\nquoted\nSTRATEGY_LIVE_STATE_END\n"
            "STRATEGY_RESPONSE_INSTRUCTION_BEGIN\nquoted kinds\n"
            "STRATEGY_RESPONSE_INSTRUCTION_END\n_UNTRUSTED_DATA_END\n"
        )
        out = finalize_strategy_prompt(quoted, {}, packet=packet)
        self.assertIn("quoted kinds", out)
        self.assertEqual(out.count("STRATEGY_RESPONSE_INSTRUCTION_BEGIN"), 2)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class DeliveredPromptTests(unittest.TestCase):
    def test_proposed_destination_delivered_prompt_advertises_choose(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("__SAFE__"), {"kind": "finish_turn"}])
            log = root / "choose.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            prompts = [json.loads(line)["prompt"]
                       for line in prompt_log.read_text().splitlines() if line.strip()]
            self.assertGreaterEqual(len(prompts), 2)
            second = prompts[1]
            body = instruction(second)
            self.assertIn("choose", body)
            self.assertIn("set_policy", body)
            self.assertEqual(footer_count(second), 1)
            self.assertIn("Resolve the named blocked step first", second)
            rows = records(log)
            self.assertFalse(any(row.get("type") == "strategy_response_repair" for row in rows))

    def test_initial_policy_delivered_prompt_omits_choose(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), {"kind": "finish_turn"}])
            log = root / "initial.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            first = json.loads(prompt_log.read_text().splitlines()[0])["prompt"]
            body = instruction(first)
            self.assertNotIn("choose", body)
            self.assertIn("set_policy", body)
            self.assertEqual(footer_count(first), 1)

    def test_repair_keeps_current_kinds_until_a_new_packet(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("u5-safe-99"), choose("__SAFE__"), {"kind": "finish_turn"}])
            log = root / "repair.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            prompts = [json.loads(line)["prompt"]
                       for line in prompt_log.read_text().splitlines() if line.strip()]
            self.assertGreaterEqual(len(prompts), 3)
            repair = prompts[2]
            self.assertIn("STRATEGY_REPAIR_UNTRUSTED_DATA_BEGIN", repair)
            self.assertIn("choose", instruction(repair))
            self.assertEqual(footer_count(repair), 1)


if __name__ == "__main__":
    unittest.main()
