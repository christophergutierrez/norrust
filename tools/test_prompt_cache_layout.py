import unittest

from .llm_client import finalize_model_prompt, prompt_for, prompt_regions


class PromptLayoutTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "scenario": "fixture", "cols": 2, "rows": 2, "active_faction": 0,
            "terrain": [{"col": 0, "row": 0, "terrain_id": "village", "owner": None},
                        {"col": 1, "row": 1, "terrain_id": "flat"}],
            "units": [{"id": 2, "faction": 0, "def_id": "Scout", "col": 1, "row": 1,
                       "hp": 8, "max_hp": 10}], "turn_options": {"units": []},
            "recruit_options": {}, "tactical_surface": {"visibility": "full",
                "unit_types": [{"def_id": "Scout", "attacks": [{"name": "spear"}]}]},
        }

    def test_live_mutations_keep_fixed_prefix_and_update_afterwards(self):
        first = finalize_model_prompt(prompt_for(self.state, [], agenda={"tasks": [], "holds": []}), self.state)
        changed = dict(self.state, turn=9, gold=[3, 4], state_revision=7,
                       units=[dict(self.state["units"][0], hp=3, col=0, row=0)])
        second = finalize_model_prompt(prompt_for(changed, [], agenda={"tasks": [{"id": "x"}], "holds": []}), changed)
        self.assertEqual(prompt_regions(first)["fixed_prefix_sha256"], prompt_regions(second)["fixed_prefix_sha256"])
        self.assertIn('"hp":3', second)
        self.assertIn("V-", second)
        self.assertIn("owner", second)

    def test_geometry_and_rules_change_fixed_prefix(self):
        first = prompt_regions(finalize_model_prompt(prompt_for(self.state, []), self.state))
        changed = dict(self.state, cols=3)
        second = prompt_regions(finalize_model_prompt(prompt_for(changed, []), changed))
        self.assertNotEqual(first["fixed_prefix_sha256"], second["fixed_prefix_sha256"])

    def test_type_profiles_are_after_fixed_prefix_and_sorted_without_reordering_attacks(self):
        state = dict(self.state, tactical_surface={"unit_types": [
            {"def_id": "Z", "attacks": [{"name": "first"}, {"name": "second"}]},
            {"def_id": "A", "attacks": [{"name": "only"}]}]})
        prompt = finalize_model_prompt(prompt_for(state, []), state)
        self.assertLess(prompt.index("PROMPT_FIXED_CONTEXT_END"), prompt.index("UNIT_TYPE_DEFINITIONS_UNTRUSTED_DATA_BEGIN"))
        self.assertLess(prompt.index('"def_id":"A"'), prompt.index('"def_id":"Z"'))
        self.assertLess(prompt.index('"name":"first"'), prompt.index('"name":"second"'))

    def test_footer_preserves_appended_context_and_ignores_quoted_markers(self):
        first = finalize_model_prompt("quoted AUTHORITATIVE_LIVE_STATE_BEGIN", self.state)
        second = finalize_model_prompt(first + "\nREPAIR_ERROR: retain this", dict(self.state, state_revision=2))
        self.assertIn("REPAIR_ERROR: retain this", second)
        self.assertEqual(second.count("AUTHORITATIVE_LIVE_STATE_BEGIN"), 2)
        self.assertEqual(second.count("MODEL_RESPONSE_INSTRUCTION_BEGIN"), 1)


if __name__ == "__main__":
    unittest.main()
