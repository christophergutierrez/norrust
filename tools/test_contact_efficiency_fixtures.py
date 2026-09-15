"""Offline fake-transport checks for contact-efficiency Stack 4 fixtures."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, launch, policy, prepare, records,
)

FIXTURES = ROOT / "tools/fixtures/contact_efficiency"
BOARD_SHA = "26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207"


def _checkpoint(root: Path, name: str) -> Path:
    data = json.loads((FIXTURES / name).read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if hashlib.sha256(board.read_bytes()).hexdigest() != BOARD_SHA:
        raise AssertionError("maintained big_battle_6 board hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    encoded = json.dumps(data, separators=(",", ":")).encode()
    checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    checkpoint.write_bytes(encoded)
    return checkpoint


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class ContactEfficiencyFixtureTests(unittest.TestCase):
    def test_three_actors_fixture_hashes_and_finishes(self):
        raw = (FIXTURES / "three_actors.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "5ec39016249e00ab97344fb78c284f0e6e71c3af5d32010179f154924d373925")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root, "three_actors.json")
            _, _, backend, _ = prepare(root, "contact.json", [policy(), {"kind": "finish_turn"}])
            log = root / "three.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            packets = [row["packet"] for row in records(log)
                       if row.get("type") == "decision_packet"
                       and row.get("packet", {}).get("decision_kind") == "tactical"]
            self.assertGreaterEqual(len(packets[0]["evidence"]["actor_ids"]), 3)

    def test_exhausted_helper_is_final_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root, "exhausted_helper.json")
            _, _, backend, _ = prepare(root, "contact.json", [policy(), {"kind": "finish_turn"}])
            log = root / "exhausted.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            packets = [row["packet"] for row in records(log)
                       if row.get("type") == "decision_packet"
                       and row.get("packet", {}).get("decision_kind") == "tactical"]
            self.assertEqual(packets[0]["evidence"]["contact_actionability"], "exhausted")
            self.assertTrue(packets[0]["final_only"])


if __name__ == "__main__":
    unittest.main()
