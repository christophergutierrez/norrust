"""Real-driver proofs that exhausted contact has no automatic helper menu."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from .test_strategy_proposed_movement_stack3 import launch, policy, prepare as prepare_pm
from .test_strategy_routine_stack3 import DRIVER, ROOT, assert_success, events, forwarded, records


FIXTURES = ROOT / "tools/fixtures/decision_relevance"
EXHAUSTED = "exhausted_leader.json"
EXHAUSTED_SHA = "0d117c3b65535d2c11632b29e2b62f6f6c4a8eb302e79b5e6f02dbd9bf9d653d"
HOLD_RECRUITER = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": None, "holds": [1],
}


def prepare_exhausted(root: Path, responses: list[dict]):
    data = json.loads((FIXTURES / EXHAUSTED).read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
    encoded = json.dumps(data, separators=(",", ":")).encode()
    checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    checkpoint.write_bytes(encoded)
    _, response_file, backend, prompt_log = prepare_pm(
        root, "proposed_move_mover_exposed.json", responses)
    # Reuse the scripted backend; overwrite checkpoint to the exhausted position.
    return checkpoint, response_file, backend, prompt_log


def tactical_packets(rows):
    return [row["packet"] for row in rows if row.get("type") == "decision_packet"
            and row.get("packet", {}).get("decision_kind") == "tactical"]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class ExhaustedContactMenuTests(unittest.TestCase):
    def test_fixture_hash(self):
        self.assertEqual(
            hashlib.sha256((FIXTURES / EXHAUSTED).read_bytes()).hexdigest(),
            EXHAUSTED_SHA)

    def test_exhausted_leader_has_no_helper_menu_and_finish_completes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare_exhausted(
                root, [policy(HOLD_RECRUITER), {"kind": "finish_turn"}])
            log = root / "finish.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            packets = tactical_packets(records(log))
            self.assertEqual(len(packets), 1)
            evidence = packets[0]["evidence"]
            self.assertEqual(evidence.get("contact_actionability"), "exhausted")
            self.assertEqual(
                evidence.get("options_empty_reason"),
                "exhausted_contact_no_automatic_rescue_menu")
            self.assertEqual(packets[0]["coverage"]["options"], "not_generated")
            self.assertTrue(packets[0]["final_only"])
            self.assertNotIn("choose", packets[0]["allowed_kinds"])
            self.assertEqual(evidence.get("actor_ids"), [])
            self.assertFalse(packets[0]["options"])
            prompt = json.loads(prompt_log.read_text().splitlines()[1])["prompt"]
            self.assertNotIn("u1-relocate", prompt)
            self.assertIn("No automatic rescue menu was generated", prompt)
            self.assertNotIn("impossible", prompt.lower())
            instruction = prompt[prompt.rfind("STRATEGY_RESPONSE_INSTRUCTION_BEGIN"):
                                 prompt.rfind("STRATEGY_RESPONSE_INSTRUCTION_END")]
            self.assertNotIn("choose", instruction)

    def test_custom_leader_move_plus_finish_is_model_authored(self):
        act = {
            "kind": "act",
            "actions": [{"action": "Move", "unit_id": 1, "col": 3, "row": 7}],
            "finish_turn": True,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare_exhausted(
                root, [policy(HOLD_RECRUITER), act])
            log = root / "custom.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            moves = [e for e in events(rows)
                     if e.get("kind") == "move" and e.get("unit") == 1]
            self.assertEqual(len(moves), 1)
            llm = [row for row in forwarded(rows) if row.get("source") == "llm"]
            self.assertTrue(llm)

    def test_illegal_custom_action_is_rejected_atomically(self):
        act = {
            "kind": "act",
            "actions": [{"action": "Move", "unit_id": 1, "col": 9, "row": 7}],
            "finish_turn": True,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare_exhausted(
                root, [policy(HOLD_RECRUITER), act, {"kind": "finish_turn"}])
            log = root / "illegal.ndjson"
            result = launch(root, log, checkpoint, backend)
            rows = records(log)
            self.assertTrue(any(row.get("type") in
                                ("strategy_response_repair", "action_failure",
                                 "strategy_batch_validation")
                                for row in rows), rows[:8])
            self.assertFalse(any(e.get("kind") == "move" and e.get("unit") == 1
                                 for e in events(rows)))


if __name__ == "__main__":
    unittest.main()
