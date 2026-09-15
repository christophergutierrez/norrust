"""Real-driver acceptance for strategy village scout capacity (proposed-movement Stack 1).

Drives the real client and driver with a scripted backend. Asserts on actual
log records and engine events, not on mocks.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .test_strategy_routine_stack2 import FIXTURES as QUIET_FIXTURES
from .test_strategy_routine_stack2 import prepare as prepare_quiet
from .test_strategy_routine_stack3 import DRIVER, ROOT, assert_success, events, launch, policy, prompts, records

VILLAGES_FOUR = [{"col": 2, "row": 4}, {"col": 5, "row": 3}, {"col": 6, "row": 11}, {"col": 18, "row": 10}]
VILLAGES_TWO = [{"col": 2, "row": 4}, {"col": 5, "row": 3}]

UNDER_CAPACITY = {
    "reserve_gold": 0,
    "recruits": [{"def_id": "Vampire Bat", "count": 2, "role": "scout"},
                 {"def_id": "Skeleton", "count": 2, "role": "army"}],
    "scouts": [], "villages": VILLAGES_FOUR, "rally": None, "holds": [],
}
CORRECTED = {**copy.deepcopy(UNDER_CAPACITY), "villages": copy.deepcopy(VILLAGES_TWO)}
ALL_OWNED_ZERO_SCOUTS = {
    "reserve_gold": 0,
    "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
    "scouts": [], "villages": copy.deepcopy(VILLAGES_TWO), "rally": None, "holds": [],
}
CAPACITY_RULE = "stays assigned after capture until the policy is replaced"


def sequence_backend(backend: Path, prompt_log: Path, replies: list[dict]) -> None:
    """Overwrite the prepared backend: reply N answers call N; the last repeats."""
    backend.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        f"lp=Path({str(prompt_log)!r})\n"
        f"replies={replies!r}\n"
        "p=sys.stdin.read()\n"
        "with lp.open('a') as f:f.write(json.dumps({'prompt':p})+'\\n')\n"
        "n=sum(1 for line in lp.read_text().splitlines() if line.strip())\n"
        "resp=replies[min(n,len(replies))-1]\n"
        "print(json.dumps({'text':json.dumps(resp)}))\n",
        encoding="utf-8")


def prepare_owned(root: Path, owners: list[list[int]]) -> tuple[Path, Path, Path]:
    """quiet.json boundary with explicit village ownership, built like prepare_quiet."""
    data = json.loads((QUIET_FIXTURES / "quiet.json").read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if not board.is_file():
        board = ROOT / "scenarios/big_battle_6/board.json"
    if hashlib.sha256(board.read_bytes()).hexdigest() != data["board_sha256"]:
        raise AssertionError("Fixture board hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    data["save_state"]["village_owners"] = copy.deepcopy(owners)
    encoded = json.dumps(data).encode()
    checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    checkpoint.write_bytes(encoded)
    return checkpoint, root / "backend.py", root / "backend-calls.ndjson"


def first_index(rows: list[dict], predicate) -> int | None:
    return next((i for i, row in enumerate(rows) if predicate(row)), None)


def is_recruit_row(row: dict) -> bool:
    return (row.get("type") == "driver" and row.get("line", {}).get("type") == "events"
            and any(e.get("kind") == "recruit" for e in row["line"].get("events", [])))


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests; skipped is not acceptance")
class ScoutCapacityIntegrationTests(unittest.TestCase):

    def test_under_capacity_rejected_before_install_then_corrected_policy_executes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare_quiet(root, CORRECTED)
            sequence_backend(backend, prompt_log, [policy(value=UNDER_CAPACITY), policy(value=CORRECTED)])
            log = root / "capacity.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, maximum=64)
            assert_success(self, result, log)
            rows = records(log)

            repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
            self.assertEqual(len(repairs), 1, repairs)
            self.assertIn("required_assignments=4 scout_capacity=2", str(repairs[0].get("error")))

            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 1, installed)
            self.assertEqual(installed[0]["policy"]["villages"], VILLAGES_TWO)

            repair_at = first_index(rows, lambda r: r.get("type") == "strategy_response_repair")
            install_at = first_index(rows, lambda r: r.get("type") == "policy_installed")
            recruit_at = first_index(rows, is_recruit_row)
            self.assertIsNotNone(recruit_at, "corrected policy must actually recruit")
            # Nothing was installed or recruited before the under-capacity reply was rejected.
            self.assertLess(repair_at, install_at)
            self.assertLess(repair_at, recruit_at)
            self.assertTrue(any(e.get("kind") == "recruit" for e in events(rows)))

            self.assertIn(CAPACITY_RULE, prompts(prompt_log)[0])

    def test_all_owned_villages_with_zero_scouts_installs_without_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, backend, prompt_log = prepare_owned(root, [[2, 4, 0], [5, 3, 0]])
            sequence_backend(backend, prompt_log, [policy(value=ALL_OWNED_ZERO_SCOUTS), {"kind": "finish_turn"}])
            log = root / "all-owned.ndjson"
            result = launch(root, log, checkpoint, backend, turns=1, maximum=64)
            assert_success(self, result, log)
            rows = records(log)
            self.assertEqual([r for r in rows if r.get("type") == "strategy_response_repair"], [])
            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 1, installed)
            self.assertEqual(installed[0]["policy"]["scouts"], [])
            self.assertEqual(installed[0]["policy"]["villages"], VILLAGES_TWO)


if __name__ == "__main__":
    unittest.main()
