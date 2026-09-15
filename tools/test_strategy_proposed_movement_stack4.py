"""Stack 4 offline proofs for proposed-movement screening.

Real client, real driver, fake transport. Synthetic usage is not model
evaluation. Intentional risky proceed is covered by Stack 3 and is not
movement-task success.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from . import model_bakeoff as bakeoff
from .game_history import import_game, open_history
from .test_strategy_proposed_movement_stack3 import (
    FIXTURES, RALLY_POLICY, choose, launch, policy, prepare,
)
from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, events, forwarded, records,
)


MOVER_SHA = "4d43b474556b31edc8ac8fac9e9cb42b3626955347e29225b11a25e9f7834da3"
OTHER_SHA = "5988525b4d0f658ba989a42db4f8f9940c10896f21684599f948b7eb7d3b5657"
MANIFEST = FIXTURES / "fireworks_candidate_manifest.json"
START = (8, 7)
PROCEED = (9, 7)
SAFE_HEXES = ((8, 5), (8, 6))


def last_installed_policy(rows):
    installed = [row for row in rows if row.get("type") == "policy_installed"]
    return installed[-1]["policy"] if installed else None


def unit_end_hex(rows, unit_id, default):
    hexes = []
    for e in events(rows):
        if e.get("kind") != "move" or e.get("unit") != unit_id:
            continue
        dest = e.get("to") if isinstance(e.get("to"), dict) else e
        hexes.append((dest.get("col"), dest.get("row")))
    return hexes[-1] if hexes else default


def movement_task_addressed(rows, unit_id=5, start=START, safe=SAFE_HEXES):
    """Safe stop or justified policy change. Finish-in-place is not success."""
    policy_now = last_installed_policy(rows) or {}
    holds = policy_now.get("holds") or []
    rally = policy_now.get("rally") or {}
    rally_hex = (rally.get("col"), rally.get("row")) if isinstance(rally, dict) else None
    if unit_id in holds:
        return True
    if rally_hex not in (None, (12, 7)):
        return True
    return unit_end_hex(rows, unit_id, start) in safe


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class ProposedMovementStack4Tests(unittest.TestCase):
    def test_manifest_checkpoint_hashes_and_cell_order(self):
        payload = json.loads(MANIFEST.read_text())
        self.assertEqual(payload["status"], "prepared_not_run")
        self.assertEqual(
            payload["cell_order"],
            ["pm-safe-baseline", "pm-safe-candidate",
             "pm-bystander-baseline", "pm-bystander-candidate"])
        by_id = {cell["id"]: cell for cell in payload["cells"]}
        self.assertEqual(list(by_id), payload["cell_order"])
        mover = (FIXTURES / "proposed_move_mover_exposed.json").read_bytes()
        other = (FIXTURES / "proposed_move_other_friendly_exposed.json").read_bytes()
        self.assertEqual(hashlib.sha256(mover).hexdigest(), MOVER_SHA)
        self.assertEqual(hashlib.sha256(other).hexdigest(), OTHER_SHA)
        for cell_id in ("pm-safe-baseline", "pm-safe-candidate"):
            self.assertEqual(by_id[cell_id]["checkpoint_sha256"], MOVER_SHA)
        for cell_id in ("pm-bystander-baseline", "pm-bystander-candidate"):
            self.assertEqual(by_id[cell_id]["checkpoint_sha256"], OTHER_SHA)
        for cell in payload["cells"]:
            self.assertEqual(cell["success_predicate"], {
                "recruiter_alive": True,
                "completed_side_turns_at_least": 1,
            })
            self.assertNotIn("useful_action", cell)

    def test_units_within_accepts_either_safe_hex_and_rejects_start(self):
        records_safe = [{
            "type": "terminal", "reason": "max_turns",
            "state": {"units": [
                {"id": 1, "col": 2, "row": 7, "hp": 48, "faction": 0, "can_recruit": True},
                {"id": 5, "col": 8, "row": 5, "hp": 34, "faction": 0},
            ], "terrain": [], "village_owners": []},
        }]
        pred = {"units_within": [{"unit_id": 5, "positions": [
            {"col": 8, "row": 5}, {"col": 8, "row": 6},
        ]}]}
        self.assertTrue(bakeoff.evaluate_objective(records_safe, pred, llm_side=0))
        records_start = copy.deepcopy(records_safe)
        records_start[0]["state"]["units"][1]["col"] = 8
        records_start[0]["state"]["units"][1]["row"] = 7
        self.assertFalse(bakeoff.evaluate_objective(records_start, pred, llm_side=0))
        self.assertIsNone(bakeoff.evaluate_objective(records_safe, {"units_within": []}, llm_side=0))
        with self.assertRaises(bakeoff.ManifestError):
            bakeoff.evaluate_objective(
                records_safe, {"units_within": [{"unit_id": 5, "positions": []}]}, llm_side=0)
        with self.assertRaises(bakeoff.ManifestError):
            bakeoff.evaluate_objective(records_safe, {"not_a_predicate": True}, llm_side=0)

    def test_finish_in_place_is_legal_and_not_movement_task_success(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), {"kind": "finish_turn"}])
            log = root / "noop.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertFalse(any(row.get("proposal_source") == "engine_option"
                                 for row in forwarded(rows)))
            self.assertEqual(sum(1 for e in events(rows)
                                 if e.get("kind") == "move" and e.get("unit") == 5), 0)
            self.assertFalse(movement_task_addressed(rows))
            self.assertFalse(any(row.get("type") == "contact_key_consumed" for row in rows))

    def test_choose_safe_is_movement_task_success_and_imports(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("__SAFE__"), {"kind": "finish_turn"}])
            log = root / "safe.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(movement_task_addressed(rows))
            self.assertIn(unit_end_hex(rows, 5, START), SAFE_HEXES)
            self.assertNotEqual(unit_end_hex(rows, 5, START), PROCEED)
            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                self.assertTrue(game_id)
                imported = conn.execute(
                    "SELECT status FROM games WHERE game_id=?", (game_id,)).fetchone()
                self.assertIsNotNone(imported)
                usage = conn.execute(
                    "SELECT count(*) FROM model_calls WHERE game_id=?", (game_id,)).fetchone()[0]
                self.assertEqual(usage, 0)
            finally:
                conn.close()

    def test_hold_policy_is_movement_task_success(self):
        held = {**copy.deepcopy(RALLY_POLICY), "holds": [1, 5]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), policy(held), {"kind": "finish_turn"}])
            log = root / "hold.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(movement_task_addressed(rows))
            self.assertEqual(unit_end_hex(rows, 5, START), START)

    def test_stale_choose_repairs_then_second_invalid_stops(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("u5-safe-99"), choose("u5-safe-98")])
            log = root / "invalid.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            rows = records(log)
            self.assertTrue(any(row.get("type") == "strategy_response_repair" for row in rows))
            self.assertFalse(movement_task_addressed(rows))

    def test_resume_after_safe_choose_does_not_repeat_the_move(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("__SAFE__", finish=True)])
            log = root / "resume.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            first_moves = sum(1 for e in events(records(log))
                              if e.get("kind") == "move" and e.get("unit") == 5)
            self.assertEqual(first_moves, 1)
            kept = [line for line in log.read_text().splitlines()
                    if '"type": "terminal"' not in line
                    and '"type": "budget_interrupted"' not in line]
            log.write_text("\n".join(kept) + "\n")
            resume_backend = root / "resume_backend.py"
            resume_backend.write_text(
                "import json,sys\nprint(json.dumps({'text': json.dumps("
                "{'kind':'finish_turn'})}))\n",
                encoding="utf-8")
            envelope = json.loads(checkpoint.read_text())
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--scenario", str(envelope["scenario"]),
                "--faction0", str(envelope["faction0"]),
                "--faction1", str(envelope["faction1"]),
                "--gold", str(envelope["starting_gold"]),
                "--seed", str(envelope["seed"]),
                "--llm-side", str(envelope["llm_side"]),
                "--max-turns", "1", "--decision-mode", "strategy",
                "--log", str(log),
                "--model-command",
                shlex.join([sys.executable, str(resume_backend)]),
                "--query-budget-seconds", "20", "--turn-timeout", "45",
                "--model-timeout", "10", "--resume-log", str(log),
            ]
            resumed = subprocess.run(
                cmd, cwd=ROOT, text=True, capture_output=True, timeout=70)
            assert_success(self, resumed, log)
            rows = records(log)
            self.assertEqual(sum(1 for e in events(rows)
                                 if e.get("kind") == "move" and e.get("unit") == 5), 1)
            self.assertTrue(movement_task_addressed(rows))

    def test_bystander_fixture_still_names_the_mover(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_other_friendly_exposed.json",
                [policy(), {"kind": "finish_turn"}])
            log = root / "bystander.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            proposed = [row["packet"] for row in rows
                        if row.get("type") == "decision_packet"
                        and row.get("packet", {}).get("evidence", {}).get("stage")
                        == "proposed_destination"]
            self.assertTrue(proposed)
            ids = [u.get("unit_id") for u in
                   proposed[0]["evidence"]["projected_threats"]["units"]]
            self.assertIn(5, ids)
            self.assertNotIn(6, ids)
            self.assertNotIn("contact_state_key", proposed[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
