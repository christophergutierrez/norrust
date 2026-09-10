import json
import unittest

from .turn_agenda import compact_agenda, normalize_agenda, response_agenda


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

    def test_malformed_types_and_invalid_utf8_are_nonfatal(self):
        malformed = [
            {"tasks": [{"id": "x", "goal": "ok", "units": [], "status": []}], "holds": []},
            {"tasks": [{"id": "x", "goal": "\ud800", "units": [], "status": "pending"}], "holds": []},
            {"tasks": [{"id": "\ud800", "goal": "ok", "units": [], "status": "pending"}], "holds": []},
            {"tasks": [{"id": "x", "goal": "ok", "units": [], "status": "pending"}], "holds": {1: 2}},
            {"tasks": [], "holds": [], "extra": True},
        ]
        for value in malformed:
            with self.subTest(value=value):
                agenda, error = normalize_agenda(value)
                self.assertIsNone(agenda)
                self.assertIsInstance(error, str)
        agenda, error = response_agenda(b'{"agenda":\xff}')
        self.assertIsNone(agenda)
        self.assertIsNone(error)

    def test_annotates_agenda_with_live_unit_status(self):
        from .turn_agenda import annotate_agenda_unit_status
        agenda = {
            "tasks": [
                {"id": "capture", "goal": "Take village", "units": [1, 99], "status": "active"}
            ],
            "holds": [2]
        }
        state = {
            "units": [
                {"id": 1, "hp": 30, "max_hp": 34, "col": 5, "row": 6, "moved": True, "attacked": False},
                {"id": 2, "hp": 48, "max_hp": 48, "col": 2, "row": 7, "moved": False, "attacked": False},
            ]
        }
        annotated = annotate_agenda_unit_status(agenda, state)
        task_status = annotated["tasks"][0]["unit_status"]
        self.assertEqual(len(task_status), 2)
        # Unit 1 is alive and moved
        self.assertTrue(task_status[0]["alive"])
        self.assertEqual(task_status[0]["status"], "moved")
        self.assertEqual(task_status[0]["hp"], 30)
        # Unit 99 is not in state -> dead
        self.assertFalse(task_status[1]["alive"])
        self.assertEqual(task_status[1]["status"], "dead")
        # Check compact representation includes unit status
        compact = compact_agenda(agenda, state)
        self.assertIn("U1(acted,hp=30,pos=5,6)", compact)
        self.assertIn("U99(dead)", compact)


if __name__ == "__main__":
    unittest.main()
