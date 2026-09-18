"""Real-driver coverage for castle-capacity relief diagnostics and travel."""
from __future__ import annotations

import copy
import hashlib
import json
import select
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, events, forwarded, records,
)
from .test_strategy_stack1_integration import launch, policy, prepare


CASTLE_HEXES = [
    (1, 6), (2, 6), (3, 6), (1, 7), (3, 7), (1, 8), (2, 8), (3, 8),
]
ARCHIVE_18 = ROOT / "tools/fixtures/strategy_recruitment_stack2/revision_18/checkpoint.json"


def materialize_archive_checkpoint(source: Path, destination: Path) -> Path:
    data = json.loads(source.read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if not board.is_file() or hashlib.sha256(board.read_bytes()).hexdigest() != data["board_sha256"]:
        raise AssertionError("maintained big_battle_6 board is absent or hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    encoded = json.dumps(data, separators=(",", ":")).encode()
    checkpoint = destination.with_name(
        f"0-18-partial-{hashlib.sha256(encoded).hexdigest()}.json")
    checkpoint.write_bytes(encoded)
    return checkpoint
POLICY_18 = {
    "holds": [],
    "rally": {"col": 12, "row": 7},
    "recruits": [
        {"count": 2, "def_id": "Vampire Bat", "role": "scout"},
        {"count": 8, "def_id": "Skeleton", "role": "army"},
        {"count": 4, "def_id": "Skeleton Archer", "role": "army"},
        {"count": 4, "def_id": "Dark Adept", "role": "army"},
    ],
    "reserve_gold": 0,
    "scouts": [],
    "villages": [
        {"col": 2, "row": 4}, {"col": 5, "row": 3},
        {"col": 6, "row": 11}, {"col": 18, "row": 10},
    ],
}
PROGRESS_18 = {
    "recruited": [
        {"queue_index": 0, "done": 2},
        {"queue_index": 1, "done": 8},
        {"queue_index": 2, "done": 1},
    ],
    "scout_assignments": [
        {"unit_id": 3, "col": 2, "row": 4},
        {"unit_id": 4, "col": 5, "row": 3},
    ],
    "completed_villages": [],
    "scout_ids": [3, 4],
    "installation_id": "pol-f9e40b5964e9",
    "policy_complete": False,
}


def skeleton(unit_id: int, col: int, row: int, *, moved: bool = False) -> dict:
    return {
        "id": unit_id, "def_id": "Skeleton", "faction": 0, "col": col, "row": row,
        "hp": 34, "max_hp": 34, "xp": 0, "xp_needed": 39,
        "advancement_pending": False, "moved": moved, "attacked": False,
        "poisoned": False, "slowed": False, "abilities": ["submerge"],
        "level": 1, "can_recruit": False,
    }


def packed_castle(start_id: int = 10) -> list[dict]:
    return [skeleton(start_id + index, col, row)
            for index, (col, row) in enumerate(CASTLE_HEXES)]


def query_driver(checkpoint: Path, payload: dict, timeout: float = 15.0) -> dict:
    cmd = [
        str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
        "--faction1", "undead", "--gold", "300", "--seed", "2038",
        "--llm-side", "0", "--max-turns", "6", "--incremental-turns",
        "--max-partial-batches-per-turn", "64",
        "--resume-checkpoint", str(checkpoint),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True)
    try:
        deadline = time.monotonic() + timeout
        while True:
            ready, _, _ = select.select(
                [proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                raise TimeoutError("driver produced no state line")
            line = proc.stdout.readline()
            if not line:
                raise RuntimeError("driver closed stdout")
            msg = json.loads(line)
            if msg.get("type") == "state":
                break
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select(
            [proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            raise TimeoutError("routine_next deadline exceeded")
        return json.loads(proc.stdout.readline())
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        proc.kill()
        proc.wait(timeout=5)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class RecruitmentCapacityReliefTests(unittest.TestCase):
    def test_no_rally_blocked_names_capacity_relief(self):
        recruit = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
            "scouts": [], "villages": [], "rally": None, "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "blocked_objective.json",
                [policy(value=recruit), {"kind": "finish_turn"}],
                extra_units=packed_castle())
            log = root / "no-rally.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            blocked = [row for row in rows if row.get("type") == "routine_exception"
                       and row.get("reason") == "recruitment_blocked"]
            self.assertTrue(blocked)
            evidence = blocked[0].get("evidence") or {}
            self.assertEqual(evidence.get("cause"), "no_placement_hex")
            self.assertEqual(evidence.get("capacity_relief", {}).get("status"), "no_rally")
            self.assertIsNone(evidence.get("capacity_relief", {}).get("rally"))
            self.assertFalse(any(
                event.get("action") == "Move" and event.get("unit_id") == 1
                for event in events(rows)))
            prompts = [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines()
                       if line.strip()]
            self.assertTrue(any("No rally is installed" in text for text in prompts[1:]))

    def test_held_castle_units_are_ineligible(self):
        units = packed_castle()
        holds = [unit["id"] for unit in units]
        recruit = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
            "scouts": [], "villages": [], "rally": {"col": 12, "row": 7},
            "holds": holds,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "blocked_objective.json",
                [policy(value=recruit), {"kind": "finish_turn"}],
                extra_units=units)
            log = root / "held.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            blocked = [row for row in records(log) if row.get("type") == "routine_exception"
                       and row.get("reason") == "recruitment_blocked"]
            self.assertTrue(blocked)
            relief = (blocked[0].get("evidence") or {}).get("capacity_relief") or {}
            self.assertEqual(relief.get("status"), "no_eligible_unit")
            self.assertEqual(relief.get("eligible_unit_ids"), [])

    def test_safe_rally_travel_recruits_without_a_second_model_call(self):
        recruit = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
            "scouts": [], "villages": [], "rally": {"col": 12, "row": 7},
            "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "blocked_objective.json",
                [policy(value=recruit), {"kind": "finish_turn"}],
                extra_units=packed_castle())
            log = root / "travel.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            moves = [row for row in forwarded(rows)
                     if row.get("source") == "routine"
                     and (row.get("orders") or [{}])[0].get("action") == "Move"]
            recruits = [row for row in forwarded(rows)
                        if row.get("source") == "routine"
                        and (row.get("orders") or [{}])[0].get("action") == "Recruit"]
            self.assertGreaterEqual(len(moves), 1)
            self.assertGreaterEqual(len(recruits), 2)
            self.assertEqual(len(prompt_log.read_text().splitlines()), 1)
            self.assertFalse(any(row.get("type") == "routine_exception" for row in rows))

    def test_jammed_shortest_path_still_travels_and_recruits(self):
        occupiers = [skeleton(40 + index, col, 7, moved=True)
                     for index, col in enumerate(range(4, 9))]
        recruit = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
            "scouts": [], "villages": [], "rally": {"col": 12, "row": 7},
            "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "blocked_objective.json",
                [policy(value=recruit), {"kind": "finish_turn"}],
                extra_units=packed_castle() + occupiers)
            log = root / "jammed.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            recruits = [row for row in forwarded(rows)
                        if row.get("source") == "routine"
                        and (row.get("orders") or [{}])[0].get("action") == "Recruit"]
            self.assertGreaterEqual(len(recruits), 1)
            self.assertEqual(len(prompt_log.read_text().splitlines()), 1)

    def test_archive_revision_18_now_steps_toward_rally(self):
        # Trial 7's recorded policy listed four villages for two scout recruits,
        # which scout-capacity validation now stops (see the test below). Keep
        # the castle-capacity relief coverage on the same checkpoint and progress
        # with a satisfiable policy: only the two villages already assigned.
        policy = copy.deepcopy(POLICY_18)
        policy["villages"] = [{"col": 2, "row": 4}, {"col": 5, "row": 3}]
        times = []
        body = None
        with tempfile.TemporaryDirectory() as td:
            checkpoint = materialize_archive_checkpoint(ARCHIVE_18, Path(td) / "checkpoint.json")
            for _ in range(3):
                started = time.perf_counter()
                reply = query_driver(checkpoint, {
                    "action": "Query", "what": "routine_next",
                    "state_revision": 18, "policy": policy, "progress": PROGRESS_18,
                })
                times.append(time.perf_counter() - started)
                self.assertTrue(reply.get("ok"), reply)
                body = reply.get("body")
                self.assertEqual(body.get("result"), "action")
                self.assertEqual(body.get("reason"), "castle_capacity")
                self.assertEqual(body.get("action", {}).get("action"), "Move")
                self.assertIn(body.get("action", {}).get("unit_id"), [9, 10, 11, 12, 13, 14])
        self.assertLess(max(times), 10.0, times)

    def test_archive_revision_18_recorded_policy_now_stops_on_scout_capacity(self):
        # Both scout recruits are committed and assigned, so villages (6,11) and
        # (18,10) can never receive a scout under this installation.
        with tempfile.TemporaryDirectory() as td:
            checkpoint = materialize_archive_checkpoint(ARCHIVE_18, Path(td) / "checkpoint.json")
            reply = query_driver(checkpoint, {
                "action": "Query", "what": "routine_next",
                "state_revision": 18, "policy": POLICY_18, "progress": PROGRESS_18,
            })
        self.assertTrue(reply.get("ok"), reply)
        body = reply.get("body")
        self.assertEqual(body.get("result"), "exception")
        self.assertEqual(body.get("reason"), "no_executable_orders")
        evidence = body.get("evidence", {})
        self.assertEqual(evidence.get("cause"), "scout_capacity_exhausted")
        self.assertEqual(evidence.get("required_assignments"), 2)
        self.assertEqual(evidence.get("scout_capacity"), 0)


if __name__ == "__main__":
    unittest.main()
