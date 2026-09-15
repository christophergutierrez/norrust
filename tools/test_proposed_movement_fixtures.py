"""Offline checks for proposed-movement Stack 3 synthetic fixtures."""
from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
import time
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools/fixtures/proposed_movement"
DRIVER = Path(os.environ.get(
    "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
BOARD_SHA = "26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207"
MOVER_SHA = "4d43b474556b31edc8ac8fac9e9cb42b3626955347e29225b11a25e9f7834da3"
OTHER_SHA = "5988525b4d0f658ba989a42db4f8f9940c10896f21684599f948b7eb7d3b5657"

RALLY_POLICY = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": {"col": 12, "row": 7}, "holds": [1],
}
PROGRESS = {
    "recruited": [], "scout_assignments": [], "completed_villages": [],
    "scout_ids": [], "installation_id": "pol-probe", "policy_complete": False,
}


def _checkpoint(root: Path, name: str) -> Path:
    data = json.loads((FIXTURES / name).read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if hashlib.sha256(board.read_bytes()).hexdigest() != BOARD_SHA:
        raise AssertionError("maintained big_battle_6 board hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    encoded = json.dumps(data, separators=(",", ":")).encode()
    path = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    path.write_bytes(encoded)
    return path


def query_routine(checkpoint: Path, timeout: float = 15.0) -> tuple[dict, float]:
    cmd = [
        str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
        "--faction1", "undead", "--gold", "300", "--seed", "9211",
        "--llm-side", "0", "--max-turns", "6", "--incremental-turns",
        "--max-partial-batches-per-turn", "64",
        "--resume-checkpoint", str(checkpoint),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True)
    try:
        deadline = time.monotonic() + timeout
        while True:
            ready, _, _ = select.select(
                [proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                raise TimeoutError("driver produced no state line")
            msg = json.loads(proc.stdout.readline())
            if msg.get("type") == "state":
                rev = msg.get("state_revision", 0)
                break
        payload = {
            "action": "Query", "what": "routine_next", "state_revision": rev,
            "policy": RALLY_POLICY, "progress": PROGRESS,
        }
        started = time.perf_counter()
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select(
            [proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            raise TimeoutError("routine_next deadline exceeded")
        reply = json.loads(proc.stdout.readline())
        return reply, time.perf_counter() - started
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        proc.kill()
        proc.wait(timeout=5)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class ProposedMovementFixtureTests(unittest.TestCase):
    def test_fixture_hashes(self):
        self.assertEqual(
            hashlib.sha256((FIXTURES / "proposed_move_mover_exposed.json").read_bytes()).hexdigest(),
            MOVER_SHA)
        self.assertEqual(
            hashlib.sha256((FIXTURES / "proposed_move_other_friendly_exposed.json").read_bytes()).hexdigest(),
            OTHER_SHA)

    def test_mover_exposed_offers_proceed_and_safe_menu(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            checkpoint = _checkpoint(Path(td), "proposed_move_mover_exposed.json")
            times = []
            body = None
            for _ in range(3):
                reply, elapsed = query_routine(checkpoint)
                times.append(elapsed)
                self.assertTrue(reply.get("ok"), reply)
                body = reply.get("body")
                self.assertEqual(body.get("result"), "exception")
                self.assertEqual(body.get("reason"), "contact")
            evidence = body["evidence"]
            self.assertEqual(evidence.get("stage"), "proposed_destination")
            self.assertEqual(evidence.get("unit_id"), 5)
            self.assertNotIn("contact_state_key", evidence)
            self.assertNotIn("contact_actionability", evidence)
            options = evidence["options"]
            self.assertGreaterEqual(len(options), 2)
            self.assertEqual(options[0]["category"], "proceed_with_exposure")
            self.assertTrue(any(opt["category"] == "safe_alternative" for opt in options))
            self.assertLessEqual(len(options), 3)
            threats = evidence["projected_threats"]["units"]
            self.assertTrue(any(u.get("is_mover") and u.get("unit_id") == 5 for u in threats))
            self.assertLess(max(times), 10.0, times)

    def test_other_friendly_present_does_not_preempt_to_current_contact(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            checkpoint = _checkpoint(Path(td), "proposed_move_other_friendly_exposed.json")
            reply, elapsed = query_routine(checkpoint)
            self.assertTrue(reply.get("ok"), reply)
            evidence = reply["body"]["evidence"]
            self.assertEqual(evidence.get("stage"), "proposed_destination")
            ids = [u.get("unit_id") for u in evidence["projected_threats"]["units"]]
            self.assertIn(5, ids)
            self.assertNotIn(6, ids)
            self.assertLess(elapsed, 10.0)


if __name__ == "__main__":
    unittest.main()
