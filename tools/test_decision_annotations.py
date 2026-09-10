import json
import unittest

from .decision_annotations import annotation_for_response, validate_decisions


class DecisionAnnotationTests(unittest.TestCase):
    def test_valid_groups_and_omission(self):
        value = validate_decisions([
            {"orders": [0, 1], "rules": ["S1", "T1"], "expected": "advance", "risk": "exposure"},
            {"orders": [], "rules": ["T7"], "expected": "Hold U9 to protect the keep", "risk": "lose tempo"},
        ], 2)
        self.assertEqual(value[0]["orders"], [0, 1])

    def test_rejects_bad_coverage_ids_duplicates_and_bounds(self):
        base = {"rules": ["S1"], "expected": "x", "risk": "y"}
        for orders in ([0, 0], [2], []):
            with self.assertRaises(ValueError):
                validate_decisions([{**base, "orders": orders}], 1)
        with self.assertRaises(ValueError):
            validate_decisions([{**base, "orders": [0], "rules": [{"bad": 1}]}], 1)
        with self.assertRaises(ValueError):
            validate_decisions([{**base, "orders": [0], "rules": ["NOPE"]}], 1)

    def test_utf8_limit_and_statuses(self):
        actions = [{"action": "EndTurn"}]
        too_long = "é" * 121
        response = {"actions": actions, "decisions": [{"orders": [0], "rules": ["S1"],
                    "expected": too_long, "risk": "x"}]}
        self.assertEqual(annotation_for_response(json.dumps(response), action_count=1)["status"], "invalid")
        self.assertEqual(annotation_for_response(json.dumps(actions))["status"], "missing")
        self.assertEqual(annotation_for_response('{"tool":"inspect_unit"}')["status"], "not_applicable")

    def test_rejects_group_and_reference_bounds(self):
        group = {"orders": [], "rules": ["S1"], "expected": "x", "risk": "y"}
        with self.assertRaises(ValueError):
            validate_decisions([group] * 17, 0)
        groups = [{**group, "orders": list(range(257))}]
        with self.assertRaises(ValueError):
            validate_decisions(groups, 257)
        self.assertEqual(len(validate_decisions([{**group, "orders": list(range(256))}], 256)[0]["orders"]), 256)

    def test_malformed_annotations_are_invalid_without_raising(self):
        group = {"orders": [0], "rules": ["S1"], "expected": "effect", "risk": "risk"}
        malformed = [None, {}, [None], [dict(group, extra="bad")],
                     [{k: v for k, v in group.items() if k != "risk"}],
                     [group, group]]
        for key, values in {
                "orders": (None, 0, [True], [-1], [1], [0.0], ["0"], [[]]),
                "rules": (None, "S1", [], ["S1", "S1"], ["S1", "S2", "T1", "T2", "T3"], [[]], [False]),
                "expected": (None, 42, "", "é" * 121, "\ud800"),
                "risk": ([], "", "x" * 241)}.items():
            malformed += [[dict(group, **{key: value})] for value in values]
        for decisions in malformed:
            with self.subTest(decisions=decisions):
                result = annotation_for_response(json.dumps({"actions": [{"action": "EndTurn"}], "decisions": decisions}))
                self.assertEqual(result["status"], "invalid")
                self.assertEqual(result["decisions"], [])
                self.assertTrue(result["error"])
                self.assertLessEqual(len(result["error"].encode()), 240)
        exact = dict(group, expected="é" * 120, risk="x" * 240)
        self.assertEqual(validate_decisions([exact] + [dict(group, orders=[])] * 15, 1)[0], exact)

    def test_guide_labels_match_the_accepted_rule_ids(self):
        import re
        from .decision_annotations import RULE_IDS, GUIDE_VERSION, guide_hash
        from .llm_client import load_tactical_playbook
        guide = load_tactical_playbook()
        labels = re.findall(r'\*\*([ST]\d(?:\.\d)?)(?:\.| —)', guide)
        self.assertEqual(set(labels), RULE_IDS)
        self.assertEqual(len(labels), len(RULE_IDS))
        self.assertIn(GUIDE_VERSION, guide)
        response = {"actions": [{"action": "EndTurn"}], "decisions": [
            {"orders": [0], "rules": ["T7"], "expected": "End turn", "risk": "Exposure"}]}
        annotation = annotation_for_response(json.dumps(response), guide_text=guide)
        self.assertEqual(annotation["guide_hash"], guide_hash(guide))

    def test_consequential_only_partial_coverage_allowed(self):
        # In focused mode (require_full_coverage=False), annotating only a subset of actions is valid
        response = {
            "actions": [
                {"action": "Move", "unit_id": 1, "col": 1, "row": 1},
                {"action": "Move", "unit_id": 2, "col": 2, "row": 2},
                {"action": "Attack", "attacker_id": 1, "defender_id": 3},
            ],
            "decisions": [
                {"orders": [2], "rules": ["T1"], "expected": "Attack defender", "risk": "Counterattack"}
            ]
        }
        # Default (batch mode) requires full coverage -> invalid
        batch_res = annotation_for_response(json.dumps(response), action_count=3, require_full_coverage=True)
        self.assertEqual(batch_res["status"], "invalid")
        # Focused mode allows partial coverage -> valid
        focused_res = annotation_for_response(json.dumps(response), action_count=3, require_full_coverage=False)
        self.assertEqual(focused_res["status"], "valid")
        self.assertEqual(len(focused_res["decisions"]), 1)

    def test_choices_envelope_and_mutual_exclusivity(self):
        valid_choices = {
            "choices": ["c_1_abc1234"],
            "decisions": [{"orders": [0], "rules": ["T1"], "expected": "move", "risk": "none"}]
        }
        res = annotation_for_response(json.dumps(valid_choices))
        self.assertEqual(res["status"], "valid")
        self.assertEqual(len(res["decisions"]), 1)

        # Mutually exclusive: cannot contain both actions and choices
        both = {
            "actions": [{"action": "EndTurn"}],
            "choices": ["c_1_abc1234"],
            "decisions": [{"orders": [0], "rules": ["T0"], "expected": "done", "risk": "none"}]
        }
        res_both = annotation_for_response(json.dumps(both))
        self.assertEqual(res_both["status"], "invalid")
        self.assertIn("cannot contain both actions and choices", res_both["error"])

        # Neither actions nor choices
        neither = {"decisions": [{"orders": [], "rules": ["T0"], "expected": "x", "risk": "y"}]}
        res_neither = annotation_for_response(json.dumps(neither))
        self.assertEqual(res_neither["status"], "invalid")
        self.assertIn("must contain actions or choices", res_neither["error"])


if __name__ == "__main__":
    unittest.main()
