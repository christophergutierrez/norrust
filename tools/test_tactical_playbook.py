"""Check canonical tactical advice reaches every prompt path without duplication."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from . import tactical_playbook
from .llm_client import prompt_for
from .routine_policy import render_policy_brief
from .strategy_decision import build_decision_packet, render_decision_brief


class SharedDoctrineTests(unittest.TestCase):
    def test_canonical_edit_reaches_batch_initial_and_contact_prompts(self):
        # A source edit must flow through every renderer, not merely match a
        # separately hard-coded copy of today's advice.
        doctrine = "Use a supported frontline and ranged counterattack."
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.md"
            path.write_text("# Tactics\n\n## Shared combat doctrine\n\n" + doctrine
                            + "\n\n## Strategy\nBatch-only instructions.\n")
            with mock.patch.object(tactical_playbook, "PLAYBOOK_PATH", path):
                packet = build_decision_packet("contact", {}, revision=1)
                for prompt in (prompt_for({}, []), render_policy_brief(0, []),
                               render_decision_brief(packet)):
                    self.assertEqual(prompt.count(doctrine), 1)
                    if "Strategy doctrine:" in prompt:
                        self.assertNotIn("Batch-only instructions.", prompt)
                        self.assertLess(prompt.index(doctrine), prompt.index("Return exactly one"))

    def test_missing_shared_doctrine_fails_instead_of_silently_omitting_tactics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.md"
            for text in ("# Tactics\n", "## Shared combat doctrine\n\n## Strategy\nOther advice"):
                path.write_text(text)
                with mock.patch.object(tactical_playbook, "PLAYBOOK_PATH", path):
                    with self.assertRaisesRegex(RuntimeError, "lacks Shared combat doctrine"):
                        render_policy_brief(0, [])

    def test_actual_shared_guidance_covers_combined_arms_without_response_schema(self):
        doctrine = tactical_playbook.load_combat_doctrine()
        for advice in ("Durable units screen", "ranged units stay close enough",
                       "enemy's actual weapons", "supported counterattack",
                       "Focus available damage", "rotate wounded units"):
            self.assertIn(advice, doctrine)
        self.assertNotIn("decision annotations", doctrine)
        self.assertNotIn("FinishWithGreedy", doctrine)


if __name__ == "__main__":
    unittest.main()
