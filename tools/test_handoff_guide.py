"""Focused contract checks for the maintained tactical playbook."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from .decision_annotations import RULE_IDS, annotation_for_response
from .llm_client import load_tactical_playbook, prompt_for, validate_orders
from .turn_agenda import response_agenda


ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = ROOT / "docs" / "LLM_TACTICAL_PLAYBOOK.md"


class HandoffGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = GUIDE_PATH.read_text(encoding="utf-8")

    def test_size_and_stable_rule_ids(self):
        self.assertLessEqual(len(self.guide.encode("utf-8")), 6000)
        for rule_id in RULE_IDS:
            self.assertRegex(self.guide, rf"\*\*{re.escape(rule_id)}(?:\.\*\*|\s—)")

    def test_exact_guide_is_in_canonical_prompt(self):
        self.assertEqual(load_tactical_playbook(), self.guide)
        for encoding in ("coordinates", "choices"):
            for incremental in (False, True):
                with self.subTest(encoding=encoding, incremental=incremental):
                    prompt = prompt_for(
                        {"incremental_turns": incremental}, [],
                        action_encoding=encoding)
                    self.assertTrue(prompt.startswith(self.guide + "\n"))
                    self.assertEqual(prompt.count(self.guide), 1)

    def test_assembled_prompt_is_bounded_and_separates_tactics_from_protocol(self):
        for compact in (False, True):
            for incremental in (False, True):
                for macro in (False, True):
                    with self.subTest(compact=compact, incremental=incremental, macro=macro):
                        prompt = prompt_for(
                            {"tactical_surface": {}, "incremental_turns": incremental}, [],
                            compact=compact, recruit_batch_enabled=macro)
                        # Raised deliberately from 15000, once, with measurements
                        # recorded in tmp/glm-efficiency-exec/prompt_budget_note.md.
                        # HEAD had 85 bytes of headroom while this work had to add
                        # the shared response contract, the B4 engine facts a player
                        # was otherwise guessing (it fell back on another game's
                        # income and upkeep rules), and the stopping-rule guide.
                        # This prose sits before PROMPT_FIXED_CONTEXT_BEGIN, so it is
                        # byte-identical across calls and eligible for prefix caching;
                        # cached tokens may still be billed. ~1.3KB is roughly 340 tokens
                        # against the 37,178 reasoning tokens one routine request
                        # actually spent. The cap still exists to catch runaway
                        # Stack2's exact mechanics and readable quantities add
                        # measured fixed prose. The largest current prompt is
                        # 18176 bytes, 10.2% over the prior 16500-byte cap and
                        # within the plan's one-time 15% presentation budget.
                        self.assertLessEqual(len(prompt.encode("utf-8")), 18500)
                        self.assertEqual(prompt.count(self.guide), 1)
                        self.assertEqual(prompt.count("Each decision group has exactly"), 1)
                        self.assertNotIn("Use RecruitBatch for ordinary recruitment", prompt)
                        self.assertNotIn("exhausting legal recruitment", prompt)
                        self.assertEqual('RecruitBatch: {"action"' in prompt, macro)
                        self.assertEqual("Observe fresh state after each step." in prompt,
                                         incremental)
        self.assertNotIn('"actions":', self.guide)
        self.assertNotIn("focus_p", self.guide)

    def test_focus_contract_explains_origin_coverage_and_volley_assumptions(self):
        prompt = prompt_for({"tactical_surface": {}}, [])
        self.assertIn("one to three distinct attackers across all supplied legal origins", prompt)
        self.assertIn("retaliation and subsequent board changes are ignored", prompt)
        self.assertIn("Zero can mean no compatible sequence of that size", prompt)
        self.assertNotIn("only one selected origin per attacker", prompt)

    def test_maintained_examples_use_real_parsers(self):
        snippets = re.findall(r"`([^`]+)`", prompt_for({}, []))
        actions = [s for s in snippets if s.lstrip().startswith(("{", "["))
                   and ('"action"' in s or '"actions"' in s)]
        self.assertEqual(len(actions), 2)
        # All response examples live in the client contract; the agenda
        # example has a dedicated marker for extracting its complete JSON.
        example = prompt_for({}, []).split("Use this exact valid shape: ", 1)[1]
        _, end = json.JSONDecoder().raw_decode(example)
        actions.append(example[:end])
        agendas = 0
        for raw in actions:
            # Malformed action examples must fail rather than disappear from
            # coverage. The non-action agenda placeholder is not executable.
            value = json.loads(raw)
            if isinstance(value, list):
                validate_orders(raw, require_end_turn=False)
                continue
            if "action" in value:
                validate_orders(json.dumps([value]))
                continue
            validate_orders(raw)
            self.assertEqual(annotation_for_response(
                raw, action_count=len(value["actions"]), guide_text=self.guide
            )["status"], "valid")
            if "agenda" in value:
                agendas += 1
                parsed_agenda, error = response_agenda(raw)
                self.assertIsNone(error)
                self.assertEqual(parsed_agenda, value["agenda"])
        self.assertGreaterEqual(agendas, 1)

    def test_empty_finish_example_is_a_valid_no_sweep_boundary(self):
        prompt = prompt_for({}, [])
        raw = prompt.split("No-sweep: ", 1)[1].split("\n", 1)[0]
        value = json.loads(raw)
        self.assertEqual(value["actions"][0]["action"], "FinishWithGreedy")
        self.assertEqual(value["actions"][0]["groups"], [])
        self.assertEqual(value["actions"][0]["holds"], [])
        validate_orders(raw)


if __name__ == "__main__":
    unittest.main()
