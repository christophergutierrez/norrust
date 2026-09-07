import json
import unittest

from .llm_client import compact_observation, prompt_for, validate_orders


class PromotionPromptTests(unittest.TestCase):
    def test_compact_board_preserves_pending_friendly_choices_and_state(self):
        state = {
            "active_faction": 0,
            "units": [
                {"id": 1, "faction": 0, "advancement_pending": True,
                 "advances_to": ["Elvish\u0020Archer", "Elvish Fighter"]},
                {"id": 2, "faction": 0, "advancement_pending": True,
                 "advances_to": []},
                {"id": 3, "faction": 0, "advancement_pending": True},
                {"id": 4, "faction": 0, "advancement_pending": False,
                 "advances_to": ["ShouldNotBeShown"]},
                {"id": 5, "faction": 1, "advancement_pending": True,
                 "advances_to": ["EnemyChoice"]},
            ],
        }

        rendered = compact_observation(state)

        self.assertIn('id=1 faction=0', rendered)
        self.assertIn('pending=True advances_to=["Elvish Archer","Elvish Fighter"]', rendered)
        self.assertIn('pending=True advances_to=[]', rendered)
        self.assertIn('id=3 faction=0', rendered)
        self.assertIn('pending=True advances_to=missing', rendered)
        self.assertIn('id=4 faction=0', rendered)
        self.assertNotIn('ShouldNotBeShown', rendered)
        self.assertNotIn('EnemyChoice', rendered)

    def test_prompt_has_complete_advance_forms_and_pending_instructions(self):
        prompt = prompt_for({"active_faction": 0, "units": []}, [])

        self.assertIn(
            'Advance by index: {"action":"Advance","unit_id": integer,"target_index": integer}',
            prompt,
        )
        self.assertIn(
            'Advance by definition: {"action":"Advance","unit_id": integer,"def_id": string}',
            prompt,
        )
        self.assertIn("advancement_pending=true", prompt)
        self.assertIn("advances_to=missing", prompt)
        self.assertIn("advances_to=[]", prompt)
        self.assertIn("Do not invent a target or advance a non-pending unit", prompt)

    def test_both_advance_selectors_are_valid_action_forms(self):
        for selector in ({"target_index": 0}, {"def_id": "Elvish Archer"}):
            orders = validate_orders(json.dumps([
                {"action": "Advance", "unit_id": 1, **selector},
                {"action": "EndTurn"}]))
            self.assertEqual(orders[0]["action"], "Advance")

    def test_canonical_compact_and_diagnostic_prompts_retain_choices_for_side_one(self):
        state = {"active_faction": 1, "units": [
            {"id": 13, "faction": 1, "advancement_pending": True,
             "advances_to": ["Bone Shooter", "Soulless"]}],
            "tactical_surface": {"units": []}}
        for compact in (True, False):
            with self.subTest(compact=compact):
                prompt = prompt_for(state, [], compact=compact)
                body = json.loads(prompt.split("BOARD_UNTRUSTED_DATA_BEGIN:\n")[1]
                                  .split("\nBOARD_UNTRUSTED_DATA_END")[0])
                if compact:
                    self.assertIn('pending=True advances_to=["Bone Shooter","Soulless"]',
                                  body["briefing"])
                else:
                    self.assertEqual(body["units"], state["units"])


if __name__ == "__main__":
    unittest.main()
