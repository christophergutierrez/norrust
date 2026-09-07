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
        self.assertLessEqual(len(self.guide.encode("utf-8")), 11019)
        for rule_id in RULE_IDS:
            self.assertRegex(self.guide, rf"\*\*{re.escape(rule_id)}(?:\.\*\*|\s—)")

    def test_exact_guide_is_in_canonical_prompt(self):
        self.assertEqual(load_tactical_playbook(), self.guide)
        prompt = prompt_for({}, [])
        self.assertIn(self.guide, prompt)

    def test_maintained_examples_use_real_parsers(self):
        snippets = re.findall(r"`([^`]+)`", self.guide)
        actions = [s for s in snippets if s.lstrip().startswith(("{", "["))
                   and ('"action"' in s or '"actions"' in s)]
        self.assertGreaterEqual(len(actions), 3)
        # The complete agenda example is maintained in the canonical client
        # contract, rather than duplicated in the shorter tactical guide.
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


if __name__ == "__main__":
    unittest.main()
