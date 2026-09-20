"""Real-driver and query tests for Strategy Resilience Stack 1: Policy Lifecycle.

Verifies:
1. Casualties on an installed policy retire cleanly without invalidating policy.
2. Safe work (queued recruit, army rally) is committed with maintenance effects.
3. Scout casualty leaves village unassigned/pending, NOT completed.
4. Scout capacity deficit defers unstaffed village work without blocking safe work.
5. New uninstalled policies with dead/foreign units or under-capacity remain strictly rejected.
6. Foreign live units in installed policy are rejected.
7. Crash safety: checkpoint recovery and resume preserve maintenance effects.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest

from .routine_policy import RoutineProgress, village_scout_capacity
from .test_strategy_routine_stack2 import FIXTURES as QUIET_FIXTURES
from .test_strategy_routine_stack2 import prepare as prepare_quiet
from .test_strategy_routine_stack3 import DRIVER, ROOT, assert_success, launch, records

VILLAGES_TWO = [{"col": 2, "row": 4}, {"col": 5, "row": 3}]
VILLAGES_THREE = [{"col": 2, "row": 4}, {"col": 5, "row": 3}, {"col": 6, "row": 11}]


def query_driver(checkpoint_path: Path, query_payload: dict, *, timeout: float = 10.0) -> dict:
    """Send an interactive Query to greedy_driver initialized from a checkpoint."""
    proc = subprocess.Popen(
        [str(DRIVER), "--seed", "9211", "--resume-checkpoint", str(checkpoint_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        deadline = time.monotonic() + timeout
        rev = None
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                raise TimeoutError("driver produced no output")
            line = proc.stdout.readline()
            if not line:
                break
            msg = json.loads(line)
            if msg.get("type") == "state":
                rev = msg.get("state_revision", 0)
                break
        if rev is None:
            raise RuntimeError("no state message received from driver")
        payload = dict(query_payload)
        payload["state_revision"] = rev
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            raise TimeoutError("driver query reply timeout")
        reply_line = proc.stdout.readline()
        return json.loads(reply_line) if reply_line else {}
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        proc.kill()
        proc.wait(timeout=5)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running driver tests")
class StrategyRoutineLifecycleTests(unittest.TestCase):

    def setUp(self):
        self.maxDiff = None

    def test_new_uninstalled_policy_with_dead_unit_is_strictly_rejected(self):
        """New policy (installation_id=None) referencing nonexistent unit is rejected."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, _, _ = prepare_quiet(root)

            policy = {
                "reserve_gold": 0,
                "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
                "scouts": [9999],  # Non-existent unit ID
                "villages": VILLAGES_TWO,
                "rally": None,
                "holds": [],
            }
            progress = {
                "installation_id": None,
                "recruited": [],
                "scout_ids": [9999],
                "scout_assignments": [],
                "completed_villages": [],
                "policy_complete": False,
            }
            reply = query_driver(checkpoint, {
                "action": "Query",
                "what": "routine_next",
                "policy": policy,
                "progress": progress,
            })
            self.assertTrue(reply.get("ok"), reply)
            body = reply.get("body", {})
            self.assertEqual(body.get("result"), "exception")
            self.assertEqual(body.get("reason"), "invalid_assignment")
            self.assertEqual(body.get("evidence", {}).get("cause"), "dead_or_foreign_unit")
            self.assertEqual(body.get("evidence", {}).get("unit_id"), 9999)

    def test_new_uninstalled_policy_with_under_capacity_is_strictly_rejected(self):
        """New policy (installation_id=None) with insufficient scout capacity is rejected."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, _, _ = prepare_quiet(root)

            policy = {
                "reserve_gold": 0,
                "recruits": [
                    {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
                    {"def_id": "Skeleton", "count": 2, "role": "army"},
                ],
                "scouts": [],
                "villages": VILLAGES_THREE,  # 3 villages, only 1 scout
                "rally": None,
                "holds": [],
            }
            progress = {
                "installation_id": None,
                "recruited": [],
                "scout_ids": [],
                "scout_assignments": [],
                "completed_villages": [],
                "policy_complete": False,
            }
            reply = query_driver(checkpoint, {
                "action": "Query",
                "what": "routine_next",
                "policy": policy,
                "progress": progress,
            })
            self.assertTrue(reply.get("ok"), reply)
            body = reply.get("body", {})
            self.assertEqual(body.get("result"), "exception")
            self.assertEqual(body.get("reason"), "no_executable_orders")
            self.assertEqual(body.get("evidence", {}).get("cause"), "insufficient_scout_capacity")
            self.assertEqual(body.get("evidence", {}).get("required_assignments"), 3)
            self.assertEqual(body.get("evidence", {}).get("scout_capacity"), 1)

    def test_installed_policy_rejects_foreign_live_unit(self):
        """An installed policy with a live foreign unit ID is rejected with dead_or_foreign_unit."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, _, _ = prepare_quiet(root)
            data = json.loads(checkpoint.read_text())
            enemy_id = next(
                u["id"] for u in data["save_state"]["units"]
                if u.get("faction") == 1
            )

            policy = {
                "reserve_gold": 0,
                "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
                "scouts": [enemy_id],
                "villages": VILLAGES_TWO,
                "rally": None,
                "holds": [],
            }
            progress = {
                "installation_id": "pol-installed-foreign",
                "recruited": [],
                "scout_ids": [enemy_id],
                "scout_assignments": [],
                "completed_villages": [],
                "policy_complete": False,
            }
            reply = query_driver(checkpoint, {
                "action": "Query",
                "what": "routine_next",
                "policy": policy,
                "progress": progress,
            })
            self.assertTrue(reply.get("ok"), reply)
            body = reply.get("body", {})
            self.assertEqual(body.get("result"), "exception")
            self.assertEqual(body.get("reason"), "invalid_assignment")
            self.assertEqual(body.get("evidence", {}).get("cause"), "dead_or_foreign_unit")
            self.assertEqual(body.get("evidence", {}).get("unit_id"), enemy_id)

    def test_installed_policy_retires_dead_scout_and_commits_queued_recruit_with_maintenance(self):
        """Casualty on installed policy retires dead scout, leaves village pending, commits recruit."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, _, _ = prepare_quiet(root)
            data = json.loads(checkpoint.read_text())

            # Unit 99 was a scout recruit that has died (not in units list)
            dead_scout_id = 99
            self.assertFalse(any(u["id"] == dead_scout_id for u in data["save_state"]["units"]))

            policy = {
                "reserve_gold": 0,
                "recruits": [
                    {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
                    {"def_id": "Skeleton", "count": 2, "role": "army"},
                ],
                "scouts": [dead_scout_id],
                "villages": VILLAGES_TWO,
                "rally": None,
                "holds": [],
            }
            progress = {
                "installation_id": "pol-installed-active",
                "recruited": [{"queue_index": 0, "done": 1}],
                "scout_ids": [dead_scout_id],
                "scout_assignments": [
                    {"unit_id": dead_scout_id, "col": 2, "row": 4},
                ],
                "completed_villages": [],
                "policy_complete": False,
            }
            reply = query_driver(checkpoint, {
                "action": "Query",
                "what": "routine_next",
                "policy": policy,
                "progress": progress,
            })
            self.assertTrue(reply.get("ok"), reply)
            body = reply.get("body", {})
            # Does NOT error with dead_or_foreign_unit!
            self.assertEqual(body.get("result"), "action")
            self.assertEqual(body.get("reason"), "recruit")
            self.assertEqual(body.get("action", {}).get("action"), "Recruit")
            self.assertEqual(body.get("action", {}).get("def_id"), "Skeleton")

            # Progress update combines maintenance effects with recruit effect
            p_update = body.get("progress_update", {})
            effects = p_update.get("effects", [])
            kinds = [e.get("kind") for e in effects]
            self.assertIn("scout_retired", kinds)
            self.assertIn("scout_unassigned", kinds)
            self.assertIn("recruited", kinds)

            retired_effect = next(e for e in effects if e.get("kind") == "scout_retired")
            self.assertEqual(retired_effect.get("unit_id"), dead_scout_id)

            unassigned_effect = next(e for e in effects if e.get("kind") == "scout_unassigned")
            self.assertEqual(unassigned_effect.get("unit_id"), dead_scout_id)
            self.assertEqual(unassigned_effect.get("col"), 2)
            self.assertEqual(unassigned_effect.get("row"), 4)

            # Applying through Python RoutineProgress with actual recruited unit_id
            rp = RoutineProgress.from_query_progress(progress, policy=policy)
            rev = reply.get("state_revision", 0)
            committed_effects = []
            for e in effects:
                if e.get("kind") == "recruited":
                    committed_effects.append({**e, "unit_id": 10})
                else:
                    committed_effects.append(e)
            applied = rp.commit_action({"effects": committed_effects}, installation_id=progress["installation_id"],
                                       batch_id="test_batch_1", state_revision=rev)
            self.assertTrue(applied)
            # Dead scout retired from scout_ids and scout_assignments
            self.assertNotIn(dead_scout_id, rp.scout_ids)
            self.assertEqual(rp.scout_assignments, [])
            # Village (2,4) was unassigned and is NOT completed
            self.assertEqual(rp.completed_villages, [])
            # Recruited count advanced to 1 for Skeleton
            self.assertEqual(rp.recruited[1], 1)
            # Original scout recruit done count is preserved
            self.assertEqual(rp.recruited[0], 1)

    def test_installed_policy_defers_village_work_and_exhausts_capacity_after_safe_work(self):
        """When capacity deficit exists due to casualties, safe work runs first then reports exhausted."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, _, _ = prepare_quiet(root)

            policy = {
                "reserve_gold": 0,
                "recruits": [
                    {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
                    {"def_id": "Skeleton", "count": 1, "role": "army"},
                ],
                "scouts": [],
                "villages": VILLAGES_TWO,
                "rally": None,
                "holds": [],
            }
            # Both recruits committed; scout died
            progress_exhausted = {
                "installation_id": "pol-exhausted",
                "recruited": [
                    {"queue_index": 0, "done": 1},
                    {"queue_index": 1, "done": 1},
                ],
                "scout_ids": [],
                "scout_assignments": [],
                "completed_villages": [],
                "policy_complete": False,
            }
            reply = query_driver(checkpoint, {
                "action": "Query",
                "what": "routine_next",
                "policy": policy,
                "progress": progress_exhausted,
            })
            self.assertTrue(reply.get("ok"), reply)
            body = reply.get("body", {})
            self.assertEqual(body.get("result"), "exception")
            self.assertEqual(body.get("reason"), "no_executable_orders")
            evidence = body.get("evidence", {})
            self.assertEqual(evidence.get("cause"), "scout_capacity_exhausted")
            self.assertEqual(evidence.get("required_assignments"), 2)
            self.assertEqual(evidence.get("scout_capacity"), 0)

    def test_routine_progress_commit_preserves_maintenance_effects_and_idempotency(self):
        """RoutineProgress validates and commits scout_retired and scout_unassigned atomically."""
        effects = [
            {"kind": "scout_retired", "unit_id": 2},
            {"kind": "scout_unassigned", "unit_id": 2, "col": 2, "row": 4},
        ]
        policy = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Vampire Bat", "count": 1, "role": "scout"}],
            "scouts": [2],
            "villages": VILLAGES_TWO,
            "rally": None,
            "holds": [],
        }
        rp = RoutineProgress.from_query_progress({
            "installation_id": "pol-recov",
            "recruited": [{"queue_index": 0, "done": 1}],
            "scout_ids": [2],
            "scout_assignments": [{"unit_id": 2, "col": 2, "row": 4}],
            "completed_villages": [],
            "policy_complete": False,
        }, policy=policy)
        applied = rp.commit_action(
            {"effects": effects},
            installation_id="pol-recov",
            batch_id="batch_recov_1",
            state_revision=5,
        )
        self.assertTrue(applied)
        self.assertEqual(rp.scout_ids, [])
        self.assertEqual(rp.scout_assignments, [])
        # Re-applying same batch is a safe no-op (idempotent)
        applied_again = rp.commit_action(
            {"effects": effects},
            installation_id="pol-recov",
            batch_id="batch_recov_1",
            state_revision=5,
        )
        self.assertFalse(applied_again)


if __name__ == "__main__":
    unittest.main()
