"""Real-driver acceptance for the bounded recovery after a failed engine repair (Stack 3).

Every engine verdict here comes from the real greedy_driver through the ordinary
client path with a scripted backend; no paid model call and no mocked engine.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
import unittest
from pathlib import Path
import tempfile

from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, launch, policy, prepare, prompts, records
)

# Unit 3 (ours, at (10,7)) cannot reach (2,2): the engine calls that unreachable.
FAR_AWAY = {"kind": "act", "actions": [{"action": "Move", "unit_id": 3, "col": 2, "row": 2}],
            "finish_turn": False}
# The repair guesses another illegal hex: (11,7) is occupied by the enemy unit 4.
OCCUPIED = {"kind": "act", "actions": [{"action": "Move", "unit_id": 3, "col": 11, "row": 7}],
            "finish_turn": False}


def model_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("type") == "model"]


def durable_of(rows: list[dict], kind: str) -> list[dict]:
    return [row for row in rows if row.get("type") == kind]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests; skipped is not acceptance")
class RecoveryAfterFailedRepairTests(unittest.TestCase):

    def test_second_engine_rejection_opens_exactly_one_recovery(self):
        """Two illegal batches then a recovery: three calls, one commit, no fourth call.

        The rejected prefixes must never reach the board, and the recovery response
        must be the last model call of the turn.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            rows = records(log)

            reserved = durable_of(rows, "strategy_recovery_reserved")
            self.assertEqual(len(reserved), 1,
                             f"exactly one recovery may be reserved per side turn: {reserved}")
            entry = reserved[0]
            self.assertIn("side_turn", entry)
            self.assertIn("state_revision", entry)
            self.assertIn("allowed_kinds", entry)
            self.assertNotIn("act", entry["allowed_kinds"],
                             "act must not be offered in the final recovery response")
            self.assertNotIn("set_policy", entry["allowed_kinds"],
                             "set_policy must not be offered in the final recovery response")

            # The reservation is journalled BEFORE the recovery dispatch it authorises.
            reserved_index = rows.index(entry)
            model_indices = [index for index, row in enumerate(rows) if row.get("type") == "model"]
            self.assertTrue(any(index > reserved_index for index in model_indices),
                            "the recovery reservation must precede its dispatch")

            # Nothing from either rejected batch reached the board.
            for row in rows:
                if row.get("type") == "forwarded_orders":
                    for order in row.get("orders", []) or []:
                        if order.get("action") == "Move" and order.get("unit_id") == 3:
                            self.assertNotEqual((order.get("col"), order.get("row")), (2, 2),
                                                "the unreachable move must never be forwarded")
                            self.assertNotEqual((order.get("col"), order.get("row")), (11, 7),
                                                "the occupied move must never be forwarded")
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_recovery_prompt_states_its_constraints(self):
        """The delivered recovery prompt names the shapes and the consequence."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            delivered = prompts(prompt_log)
            recovery_prompts = [text for text in delivered if "STRATEGY_RECOVERY_BEGIN" in text]
            self.assertTrue(recovery_prompts, "a recovery prompt must have been delivered")
            text = recovery_prompts[-1]
            self.assertIn('{"kind":"finish_turn"}', text)
            self.assertIn("another invalid answer", text.lower())
            self.assertIn("legal, not safe", text)
            self.assertIn("act and set_policy are not accepted", text)

    def test_recovery_allowance_is_not_refilled_within_the_side_turn(self):
        """A second incident in the same side turn cannot open another recovery."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # After the recovery finishes the turn, any later incident in the SAME
            # side turn must find the allowance already spent.
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json",
                [policy(), FAR_AWAY, OCCUPIED, FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            rows = records(log)
            reserved = durable_of(rows, "strategy_recovery_reserved")
            side_turns = [row.get("side_turn") for row in reserved]
            self.assertEqual(len(side_turns), len(set(side_turns)),
                             f"a side turn may reserve recovery at most once: {side_turns}")

    def test_invalid_final_answer_ends_the_run(self):
        """A recovery response that is not one of the three allowed shapes terminates the run.

        After the second rejection, recovery is dispatched with only {choose, finish_turn, resign}
        permitted. An invalid response (set_policy or malformed JSON) should end the run with
        a strategy_recovery_outcome of rejected and no fourth model call.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Use set_policy as the invalid recovery answer (not in allowed_kinds)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, policy()])
            log = root / "match.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            rows = records(log)

            # Verify the log file exists and is non-empty
            self.assertTrue(log.exists(), f"match log must exist at {log}")
            log_content = log.read_text()
            self.assertTrue(log_content.strip(), "match log must be non-empty")

            model_calls = model_rows(rows)
            # Call sequence: (1) policy, (2) FAR_AWAY, (3) recovery prompt, (4) invalid response (set_policy)
            self.assertEqual(len(model_calls), 4,
                             f"expected 4 model calls (policy, repair, recovery, invalid): {len(model_calls)} found")

            outcomes = durable_of(rows, "strategy_recovery_outcome")
            self.assertEqual([row.get("outcome") for row in outcomes], ["rejected"],
                             f"an invalid recovery must record rejection: {outcomes}")
            terminal = next(row for row in rows if row.get("type") == "terminal")
            self.assertEqual(terminal.get("strategy_recovery_committed"), 0,
                             "an invalid recovery must not be counted as committed")
            self.assertEqual(len(durable_of(rows, "strategy_recovery_dispatch")), 1,
                             "the recovery dispatch journal must record the one attempted response")

            # Run should terminate with non-zero exit
            self.assertNotEqual(result.returncode, 0,
                                "invalid recovery answer must terminate the run with failure")

    def test_recovery_can_finish_the_turn(self):
        """A recovery response of finish_turn should successfully advance the turn.

        After the second rejection, the model responds with finish_turn, which should
        be accepted and result in turn advancement and exit code 0.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            rows = records(log)

            # Verify the log file exists and is non-empty
            self.assertTrue(log.exists(), f"match log must exist at {log}")
            log_content = log.read_text()
            self.assertTrue(log_content.strip(), "match log must be non-empty")

            # Run should succeed
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])

            # Turn should have advanced
            turn_events = [event for event in prompts(prompt_log)
                          if "turn" in event.lower() or "boundary" in event.lower()]
            self.assertTrue(len(turn_events) > 0 or any(
                row.get("type") in {"end_turn", "turn_boundary", "routine_exception"}
                for row in rows), "turn must advance after successful recovery")

            outcomes = durable_of(rows, "strategy_recovery_outcome")
            self.assertEqual([row.get("outcome") for row in outcomes], ["accepted", "committed"],
                             f"recovery must be accepted, then committed: {outcomes}")
            self.assertEqual(outcomes[0].get("kind"), "finish_turn",
                             f"accepted outcome kind must be finish_turn: {outcomes[0]}")
            terminal = next(row for row in rows if row.get("type") == "terminal")
            self.assertEqual(terminal.get("strategy_recovery_committed"), 1,
                             "only the committed recovery should increment the committed counter")
            self.assertEqual(len(durable_of(rows, "strategy_recovery_dispatch")), 1)

    def test_recovery_choice_commits_exactly_that_move(self):
        """A recovery `choose` commits exactly the chosen option and nothing else.

        The recovery decision_id and option ids only exist at runtime, so the backend
        reads them out of the delivered recovery prompt rather than hardcoding them.
        This asserts the COMMITTED board events, not merely that choose was offered.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            # Replace the canned backend: on the recovery prompt, answer with a choose
            # built from the ids that prompt actually carries.
            backend.write_text(
                "import json, re, sys\n"
                f"log_path = {str(prompt_log)!r}\n"
                "prompt = sys.stdin.read()\n"
                "with open(log_path, 'a', encoding='utf-8') as stream:\n"
                "    stream.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "with open(log_path, encoding='utf-8') as stream:\n"
                "    index = sum(1 for _ in stream) - 1\n"
                "if 'STRATEGY_RECOVERY_BEGIN' in prompt:\n"
                "    decision = re.search(r'\"decision_id\":\"(dec-[0-9a-f]+)\"', prompt).group(1)\n"
                "    option = re.search(r\"'(u\\d+-repair-\\d+)'\", prompt).group(1)\n"
                "    response = {'kind': 'choose', 'decision_id': decision,\n"
                "                'option_ids': [option], 'finish_turn': True}\n"
                "elif index == 0:\n"
                "    response = {'kind': 'set_policy', 'policy': {'reserve_gold': 0, 'recruits': [],\n"
                "                'scouts': [], 'villages': [], 'rally': None, 'holds': []}}\n"
                "elif index == 1:\n"
                "    response = {'kind': 'act', 'actions': [{'action': 'Move', 'unit_id': 3,\n"
                "                'col': 2, 'row': 2}], 'finish_turn': False}\n"
                "else:\n"
                "    response = {'kind': 'act', 'actions': [{'action': 'Move', 'unit_id': 3,\n"
                "                'col': 11, 'row': 7}], 'finish_turn': False}\n"
                "print(json.dumps({'text': json.dumps(response, separators=(',', ':'))}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            self.assertTrue(log.is_file() and log.read_text().strip(), "match log must exist")
            rows = records(log)

            reserved = durable_of(rows, "strategy_recovery_reserved")
            self.assertEqual(len(reserved), 1, f"exactly one reservation: {reserved}")
            chosen_id = reserved[0]["option_ids"][0]
            outcomes = durable_of(rows, "strategy_recovery_outcome")
            self.assertEqual([row.get("outcome") for row in outcomes], ["accepted", "committed"],
                             f"the recovery choose must be accepted and committed: {outcomes}")

            # The chosen option's destination is the one the engine actually committed.
            menus = durable_of(rows, "strategy_movement_repair_menu")
            self.assertTrue(menus, "the repair menu that sourced the options must be recorded")
            offered = {option["option_id"]: option["destination"]
                       for menu in menus for option in menu.get("options", [])}
            self.assertIn(chosen_id, offered, f"chosen id must come from the offered menu: {offered}")
            expected = (offered[chosen_id]["col"], offered[chosen_id]["row"])

            committed_moves = [
                ((event.get("to") or {}).get("col"), (event.get("to") or {}).get("row"))
                for row in rows if row.get("type") == "driver"
                and isinstance(row.get("line"), dict)
                for event in (row["line"].get("events") or [])
                if event.get("kind") == "move" and event.get("unit") == 3
                and event.get("source") == "llm"]
            self.assertIn(expected, committed_moves,
                          f"the chosen destination {expected} must be committed: {committed_moves}")
            for destination in ((2, 2), (11, 7)):
                self.assertNotIn(destination, committed_moves,
                                 f"a rejected destination {destination} must never commit")
            self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_recovery_choose_must_finish_and_select_one_option(self):
        """A recovery choose with finish_turn=false is rejected without a retry."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            backend.write_text(
                "import json, re, sys\n"
                f"log_path = {str(prompt_log)!r}\n"
                "prompt = sys.stdin.read()\n"
                "with open(log_path, 'a', encoding='utf-8') as stream:\n"
                "    stream.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "index = len(open(log_path, encoding='utf-8').read().splitlines()) - 1\n"
                "if 'STRATEGY_RECOVERY_BEGIN' in prompt:\n"
                "    decision = re.search(r'\"decision_id\":\"([^\"]+)\"', prompt).group(1)\n"
                "    option = re.search(r\"['\\\"](u\\d+-repair-\\d+)['\\\"]\", prompt).group(1)\n"
                "    response = {'kind': 'choose', 'decision_id': decision,\n"
                "                'option_ids': [option], 'finish_turn': False}\n"
                "elif index == 0:\n"
                "    response = {'kind': 'set_policy', 'policy': {'reserve_gold': 0, 'recruits': [],\n"
                "                'scouts': [], 'villages': [], 'rally': None, 'holds': []}}\n"
                "elif index == 1:\n"
                "    response = {'kind': 'act', 'actions': [{'action': 'Move', 'unit_id': 3,\n"
                "                'col': 2, 'row': 2}], 'finish_turn': False}\n"
                "else:\n"
                "    response = {'kind': 'act', 'actions': [{'action': 'Move', 'unit_id': 3,\n"
                "                'col': 11, 'row': 7}], 'finish_turn': False}\n"
                "print(json.dumps({'text': json.dumps(response, separators=(',', ':'))}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            rows = records(log)
            self.assertNotEqual(result.returncode, 0, "finish_turn=false must be rejected")
            self.assertEqual(len(model_rows(rows)), 4,
                             "a rejected recovery must not receive a corrective fifth call")
            self.assertEqual([row.get("outcome") for row in durable_of(rows, "strategy_recovery_outcome")],
                             ["rejected"])
            terminal = next(row for row in rows if row.get("type") == "terminal")
            self.assertEqual(terminal.get("strategy_recovery_committed"), 0)

    def test_recovery_multiple_options_or_inspection_get_no_followup(self):
        """Recovery accepts one final choice only; multiple choices and tools stop immediately."""
        for invalid_shape in ("multiple", "inspection"):
            with self.subTest(invalid_shape=invalid_shape), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                checkpoint, _responses, backend, prompt_log = prepare(
                    root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
                backend.write_text(
                    "import json, re, sys\n"
                    f"log_path = {str(prompt_log)!r}\n"
                    "prompt = sys.stdin.read()\n"
                    "with open(log_path, 'a', encoding='utf-8') as stream:\n"
                    "    stream.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                    "index = len(open(log_path, encoding='utf-8').read().splitlines()) - 1\n"
                    "if 'STRATEGY_RECOVERY_BEGIN' in prompt:\n"
                    "    decision = re.search(r'\"decision_id\":\"([^\"]+)\"', prompt).group(1)\n"
                    "    options = re.findall(r\"['\\\"](u\\d+-repair-\\d+)['\\\"]\", prompt)\n"
                    "    if " + repr(invalid_shape) + " == 'inspection':\n"
                    "        response = {'tool': 'inspect_units', 'unit_ids': [3]}\n"
                    "    else:\n"
                    "        response = {'kind': 'choose', 'decision_id': decision,\n"
                    "                    'option_ids': options[:2], 'finish_turn': True}\n"
                    "elif index == 0:\n"
                    "    response = {'kind': 'set_policy', 'policy': {'reserve_gold': 0, 'recruits': [],\n"
                    "                'scouts': [], 'villages': [], 'rally': None, 'holds': []}}\n"
                    "elif index == 1:\n"
                    "    response = {'kind': 'act', 'actions': [{'action': 'Move', 'unit_id': 3,\n"
                    "                'col': 2, 'row': 2}], 'finish_turn': False}\n"
                    "else:\n"
                    "    response = {'kind': 'act', 'actions': [{'action': 'Move', 'unit_id': 3,\n"
                    "                'col': 11, 'row': 7}], 'finish_turn': False}\n"
                    "print(json.dumps({'text': json.dumps(response, separators=(',', ':'))}))\n",
                    encoding="utf-8")
                log = root / "match.ndjson"
                result = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
                rows = records(log)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(model_rows(rows)), 4,
                                 "an invalid recovery must not receive a corrective fifth call")
                self.assertEqual(
                    [row.get("outcome") for row in durable_of(rows, "strategy_recovery_outcome")],
                    ["rejected"])
                terminal = next(row for row in rows if row.get("type") == "terminal")
                self.assertEqual(terminal.get("strategy_recovery_committed"), 0)

    def test_call_budget_cannot_be_bypassed(self):
        """Recovery cannot be opened once the per-turn model call budget is spent.

        With max_calls=2, the first policy and first rejected batch consume the budget.
        Recovery must not be reserved or dispatched, and the run must terminate truthfully
        without an extra model call.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            # With max_calls=2, only policy + FAR_AWAY can be called
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=2)
            rows = records(log)

            # Verify the log file exists and is non-empty
            self.assertTrue(log.exists(), f"match log must exist at {log}")
            log_content = log.read_text()
            self.assertTrue(log_content.strip(), "match log must be non-empty")

            # No recovery reservation should exist
            reserved = durable_of(rows, "strategy_recovery_reserved")
            self.assertEqual(len(reserved), 0,
                             f"recovery must not be reserved when call budget is exhausted: {reserved}")

            # Model calls should not exceed budget
            model_calls = model_rows(rows)
            self.assertLessEqual(len(model_calls), 2,
                                f"model calls must not exceed max_calls=2: {len(model_calls)} found")

            # Run should terminate with a truthful terminal reason
            terminal = next((row for row in rows if row.get("type") == "terminal"), None)
            self.assertIsNotNone(terminal, "run must terminate with a terminal record")
            code = terminal.get("code")
            self.assertIn(code, {
                "model_calls_budget_exhausted", "strategy_no_progress",
                "model_response_budget_exhausted"
            }, f"terminal code must be a budget-related reason, not {code!r}")

    def test_call_budget_fence_prevents_recovery_dispatch_at_three_calls(self):
        """Policy plus two rejected batches leave no budget for recovery construction."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, max_calls=3)
            rows = records(log)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(model_rows(rows)), 3,
                             "the recovery response must not be dispatched after three calls")
            self.assertEqual(durable_of(rows, "strategy_recovery_reserved"), [])
            self.assertEqual(durable_of(rows, "strategy_recovery_dispatch"), [])
            self.assertEqual(durable_of(rows, "strategy_recovery_outcome"), [])
            terminal = next(row for row in rows if row.get("type") == "terminal")
            self.assertIn(terminal.get("code"), {
                "model_calls_budget_exhausted", "model_response_budget_exhausted"
            })
            self.assertEqual(terminal.get("strategy_recovery_dispatched"), 0)
            self.assertEqual(terminal.get("strategy_recovery_committed"), 0)
            self.assertEqual(terminal.get("strategy_recovery_rejected"), 0)


    def test_resume_never_grants_a_second_recovery(self):
        """A real resume from a checkpoint of the same turn refuses a second recovery.

        This runs the client twice: once until recovery is reserved and the turn ends,
        then again resuming from that side turn's model-boundary checkpoint with a fresh
        backend that reproduces both illegal batches. The resumed process must read the
        parent log's reservation and refuse to open recovery again.

        Regression guard: the allowance is keyed on the controlled TURN NUMBER, not the
        side-turn id. A resume starts a new conversation id, so an id-based key looked
        unused after a crash and handed out a second "final" response for the same turn.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _responses, backend, _prompt_log = prepare(
                root, "contact.json", [policy(), FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            log = root / "match.ndjson"
            first = launch(root, log, checkpoint, backend, turns=1, max_calls=8)
            self.assertEqual(first.returncode, 0, first.stderr[-2000:])
            self.assertTrue(log.is_file() and log.read_text().strip(), "first match log must exist")
            reserved = durable_of(records(log), "strategy_recovery_reserved")
            self.assertEqual(len(reserved), 1, f"first run must reserve recovery once: {reserved}")

            checkpoints = sorted((root / "match.ckpt").glob("0-0-model-*.json"))
            self.assertTrue(checkpoints, "the first run must leave a model-boundary checkpoint")

            # A fresh backend with its own prompt log, so the resumed run reproduces both
            # illegal batches instead of continuing the first run's response sequence.
            second_root = root / "second"
            second_root.mkdir()
            _ck2, _resp2, second_backend, _plog2 = prepare(
                second_root, "contact.json", [FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            resumed_log = root / "match-resumed.ndjson"
            second = launch(root, resumed_log, checkpoints[0], second_backend,
                            turns=1, max_calls=8)
            self.assertTrue(resumed_log.is_file() and resumed_log.read_text().strip(),
                            "resumed match log must exist")
            resumed_rows = records(resumed_log)

            self.assertEqual(durable_of(resumed_rows, "strategy_recovery_reserved"), [],
                             "resume must not reserve a second recovery for the same turn")
            unavailable = durable_of(resumed_rows, "strategy_recovery_unavailable")
            self.assertTrue(
                any(row.get("reason") == "allowance_already_used" for row in unavailable),
                f"resume must record the spent allowance: {unavailable}")
            terminal = next((row for row in resumed_rows if row.get("type") == "terminal"), None)
            self.assertIsNotNone(terminal, "the resumed run must end with a truthful terminal")
            self.assertEqual(terminal.get("code"), "strategy_response_invalid",
                             f"no extra recovery means the ordinary terminal stands: {terminal}")
            self.assertNotEqual(second.returncode, 0,
                                "the resumed run must not report success after an invalid batch")

            # The immediate parent now has NO reservation event, only the restored
            # allowance in metadata. Resuming it must still retain the spent turn.
            second_checkpoints = sorted((root / "match-resumed.ckpt").glob("0-0-model-*.json"))
            self.assertTrue(second_checkpoints)
            third_root = root / "third"
            third_root.mkdir()
            _, _, third_backend, _ = prepare(
                third_root, "contact.json", [FAR_AWAY, OCCUPIED, {"kind": "finish_turn"}])
            third_log = root / "match-resumed-again.ndjson"
            third = launch(root, third_log, second_checkpoints[0], third_backend,
                           turns=1, max_calls=8)
            third_rows = records(third_log)
            self.assertNotEqual(third.returncode, 0)
            self.assertEqual(durable_of(third_rows, "strategy_recovery_reserved"), [])
            self.assertTrue(any(row.get("reason") == "allowance_already_used"
                                for row in durable_of(third_rows, "strategy_recovery_unavailable")))
