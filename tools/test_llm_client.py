import json
import unittest

from .llm_client import validate_orders, prompt_for


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


if __name__ == "__main__":
    unittest.main()
