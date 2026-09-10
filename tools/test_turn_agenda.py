import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .turn_agenda import compact_agenda, normalize_agenda, response_agenda

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "norrust_core/tests/fixtures/s2_deterministic_duel"
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER",
                             ROOT / "norrust_core/target/debug/greedy_driver"))


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



def _reply(actions, agenda=None):
    envelope = {"actions": actions,
                "decisions": [{"orders": list(range(len(actions))), "rules": ["T0"],
                               "expected": "progress", "risk": "none"}]}
    if agenda is not None:
        envelope["agenda"] = agenda
    return json.dumps({"text": json.dumps(envelope)})


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
@unittest.skipUnless(FIXTURE_ROOT.is_dir(), "s2_deterministic_duel fixture is missing")
class RejectedAgendaFeedbackTests(unittest.TestCase):
    """A refused agenda must not silently erase the player's objective.

    Observed in a real GLM game: four agendas were rejected for having two
    active tasks, the archive recorded `agenda_error`, and nothing reached the
    next prompt. The player lost its working objective without being told, and
    kept proposing the same invalid shape.
    """

    def test_rejected_agenda_is_explained_and_prior_objective_survives(self):
        active_a = {"tasks": [{"id": "hold-left", "goal": "hold the left flank",
                               "units": [], "status": "active"}], "holds": []}
        two_active = {"tasks": [{"id": "one", "goal": "a", "units": [], "status": "active"},
                                {"id": "two", "goal": "b", "units": [], "status": "active"}],
                      "holds": []}
        replacement = {"tasks": [{"id": "push", "goal": "push the centre",
                                  "units": [], "status": "active"}], "holds": []}
        end = [{"action": "EndTurn"}]
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            orders = directory / "orders.jsonl"
            orders.write_text("\n".join([
                _reply(end, active_a), _reply(end, two_active), _reply(end, replacement),
                _reply(end), _reply(end),
            ]) + "\n", encoding="utf-8")
            log = directory / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--orders-file", str(orders), "--scenario", "duel",
                       "--faction0", "fragile", "--faction1", "fragile", "--gold", "0",
                       "--seed", "42", "--llm-side", "0", "--max-turns", "8",
                       "--log", str(log), "--query-budget-seconds", "10",
                       "--model-timeout", "10", "--turn-timeout", "30"]
            env = dict(os.environ, NORRUST_TEST_ROOT_DIR=str(FIXTURE_ROOT))
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                    text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])
            records = [json.loads(line) for line in log.read_text().splitlines()]

        errors = [r for r in records if r.get("type") == "agenda_error"]
        updates = [r for r in records if r.get("type") == "agenda_update"]
        prompts = [r["prompt"] for r in records
                   if r.get("type") == "model_request" and r.get("prompt")]
        forwarded = [r for r in records if r.get("type") == "forwarded_orders"]

        # The refusal names the constraint and the agenda it kept.
        self.assertEqual(len(errors), 1)
        self.assertIn("at most one active task", errors[0]["message"])
        self.assertEqual(errors[0]["retained_task_ids"], ["hold-left"])

        # A committed first, C replaced it: the invalid B never became memory.
        self.assertEqual([[task["id"] for task in u["agenda"]["tasks"]] for u in updates],
                         [["hold-left"], ["push"]])

        # The player was actually told, in a later request, and told once.
        rejected = [i for i, text in enumerate(prompts) if "AGENDA_REJECTED" in text]
        self.assertEqual(len(rejected), 1, "expected exactly one delivery, not a transcript")
        self.assertIn("at most one active task", prompts[rejected[0]])
        self.assertIn("hold-left", prompts[rejected[0]])

        # Bookkeeping failure costs no gameplay: every batch still executed,
        # and no extra model call was spent correcting metadata.
        self.assertEqual(len(forwarded), 4)
        self.assertEqual(len(prompts), 4)


if __name__ == "__main__":
    unittest.main()
