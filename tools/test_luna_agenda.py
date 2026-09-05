import json
import unittest

from .luna_agenda import compact_agenda, normalize_agenda, response_agenda


class AgendaTests(unittest.TestCase):
    def test_normalizes_full_replacement_and_deduplicates_units(self):
        agenda, error = normalize_agenda({
            "tasks": [{"id": "fight", "goal": "Kill U9", "units": [3, 3, 5], "status": "active"},
                      {"id": "village", "goal": "Take east village", "units": [8], "status": "pending"}],
            "holds": [12, 12],
        })
        self.assertIsNone(error)
        self.assertEqual(agenda["tasks"][0]["units"], [3, 5])
        self.assertEqual(agenda["holds"], [12])
        self.assertIn("AGENDA tasks=", compact_agenda(agenda))

    def test_rejects_duplicate_ids_and_multiple_active_tasks(self):
        base = {"id": "x", "goal": "job", "units": [], "status": "active"}
        agenda, error = normalize_agenda({"tasks": [base, dict(base)], "holds": []})
        self.assertIsNone(agenda)
        self.assertIn("unique", error)
        agenda, error = normalize_agenda({"tasks": [base, {**base, "id": "y"}], "holds": []})
        self.assertIsNone(agenda)
        self.assertIn("active", error)

    def test_malformed_optional_agenda_is_reported_without_action_failure(self):
        agenda, error = response_agenda(json.dumps({"actions": [{"action": "EndTurn"}],
                                                     "agenda": {"tasks": "bad", "holds": []}}))
        self.assertIsNone(agenda)
        self.assertIn("tasks", error)


if __name__ == "__main__":
    unittest.main()
