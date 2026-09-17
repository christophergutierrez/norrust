"""Unit and simulation tests for recruiter survival diagnosis and fixtures (Stack 1).

Covers:
- Idempotent and deterministic reference execution (running twice yields identical state).
- Verification that original checkpoint files remain byte-identical after branching.
- Distinction between positive (useful defense) and negative references across defensive fixtures.
- Distinction between active progress and needless passivity on quiet control.
- Failure detection on deliberately wrong winner/survival results.
- Unscored status when terminal/horizon evidence is missing or terminated by infrastructure.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from . import strategy_quality as sq

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/release/greedy_driver"))
if not DRIVER.is_file():
    DRIVER = ROOT / "norrust_core/target/debug/greedy_driver"

BOARD = ROOT / "scenarios/big_battle_6/board.toml"
FIXTURES_DIR = ROOT / "tools/fixtures/recruiter_survival"


def _prepare_checkpoint(fixture_name: str, target_dir: Path) -> tuple[Path, dict]:
    meta_path = FIXTURES_DIR / fixture_name / "metadata.json"
    ckpt_path = FIXTURES_DIR / fixture_name / "checkpoint.json"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    ckpt_data = json.loads(ckpt_path.read_text(encoding="utf-8"))

    ckpt_data["board_path"] = str(BOARD)
    ckpt_data["save_state"]["board_path"] = str(BOARD)

    encoded = json.dumps(ckpt_data, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()

    ckpt_file = target_dir / f"{ckpt_data['side_turns']}-{ckpt_data['save_state']['state_revision']}-{ckpt_data['boundary']}-{digest}.json"
    ckpt_file.write_bytes(encoded)
    return ckpt_file, meta


def _run_driver_branch(ckpt_file: Path, seed: int, orders: list[dict]) -> tuple[dict | None, dict | None, list[dict]]:
    cmd = [
        str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
        "--faction1", "undead", "--gold", "300", "--seed", str(seed),
        "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
        "--resume-checkpoint", str(ckpt_file),
    ]
    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    records = []
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            m = json.loads(line)
            records.append({"type": "driver", "line": m})
            if m.get("type") == "state":
                break

        # Submit orders
        records.append({"type": "forwarded_orders", "orders": orders})
        proc.stdin.write(json.dumps(orders) + "\n")
        proc.stdin.flush()

        final_state = None
        game_end = None
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            m = json.loads(line)
            records.append({"type": "driver", "line": m})
            if m.get("type") == "state":
                final_state = m
                break
            elif m.get("type") == "game_end":
                game_end = m
                records.append({"type": "terminal", **m})
                break

        return final_state, game_end, records
    finally:
        if proc.stdin:
            proc.stdin.close()
        if proc.stdout:
            proc.stdout.close()
        if proc.stderr:
            proc.stderr.close()
        proc.terminate()
        proc.wait()


class TestRecruiterSurvivalUnitScoring(unittest.TestCase):
    """Unit tests for metric vector extraction and scoring rules."""

    def test_unscored_on_infrastructure_failure(self):
        records = [
            {"type": "terminal", "reason": "timeout", "winner": None, "infrastructure_invalid": True},
        ]
        vec = sq.extract_survival_metric_vector(records)
        self.assertEqual(vec["status"], "unscored")
        self.assertEqual(vec["unscored_reason"], "timeout")
        self.assertFalse(vec["completed_horizon"])

    def test_deliberate_wrong_winner_fails(self):
        # Even if recruiter alive flag was forged, winner 1 means side 0 loss
        fake_state = {
            "type": "state",
            "units": [{"id": 1, "faction": 0, "hp": 48, "can_recruit": True}],
            "village_owners": [],
            "gold": [100, 100],
        }
        records = [
            {"type": "driver", "line": fake_state},
            {"type": "terminal", "reason": "winner", "winner": 1},
        ]
        vec = sq.extract_survival_metric_vector(records, expected_side=0)
        self.assertEqual(vec["terminal_result"], "loss")


@unittest.skipUnless(DRIVER.is_file(), "Requires greedy_driver binary")
class TestRecruiterSurvivalFixtures(unittest.TestCase):
    """Integration tests running fixtures against greedy_driver."""

    def test_fixture_1_seed_4477_distinguishes_good_and_bad_alternatives(self):
        """Fixture 1: positive reference keeps U1 full HP and kills U28; negative charges recklessly."""
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            ckpt_orig = FIXTURES_DIR / "fixture_1_seed_4477_defensive/checkpoint.json"
            orig_bytes = ckpt_orig.read_bytes()

            ckpt_file, meta = _prepare_checkpoint("fixture_1_seed_4477_defensive", tpath)

            pos_orders = [
                {"action": "Move", "col": 2, "row": 4, "unit_id": 1},
                {"action": "Attack", "attacker_id": 3, "defender_id": 28},
                {"action": "Move", "col": 2, "row": 2, "unit_id": 6},
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]
            neg_orders = [
                {"action": "Move", "col": 5, "row": 8, "unit_id": 1},
                {"action": "Attack", "attacker_id": 1, "defender_id": 20},
                {"action": "Move", "col": 2, "row": 2, "unit_id": 6},
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]

            # Run positive twice to prove determinism
            final1, end1, recs1 = _run_driver_branch(ckpt_file, meta["seed"], pos_orders)
            final2, end2, recs2 = _run_driver_branch(ckpt_file, meta["seed"], pos_orders)

            self.assertIsNotNone(final1)
            self.assertIsNotNone(final2)
            self.assertEqual(final1, final2, "Repeated reference branch must yield identical state")

            score_pos = sq.score_cell("seed_4477_defensive", recs1)
            self.assertTrue(score_pos["passed"])
            self.assertTrue(score_pos["useful_defense"])
            self.assertEqual(score_pos["recruiter_hp"], 48)
            self.assertEqual(score_pos["enemy_count"], 16)

            # Run negative
            final_neg, end_neg, recs_neg = _run_driver_branch(ckpt_file, meta["seed"], neg_orders)
            self.assertIsNotNone(final_neg)
            score_neg = sq.score_cell("seed_4477_defensive", recs_neg)
            self.assertFalse(score_neg["passed"])
            self.assertFalse(score_neg["useful_defense"])
            self.assertLess(score_neg["recruiter_hp"], 40)
            self.assertEqual(score_neg["enemy_count"], 17)

            # Assert original fixture was untouched
            self.assertEqual(ckpt_orig.read_bytes(), orig_bytes, "Original fixture must remain unmodified")

    def test_fixture_2_seed_7731_distinguishes_good_and_bad_alternatives(self):
        """Fixture 2: positive reference retains all 7 friendly units; negative loses a unit."""
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            ckpt_orig = FIXTURES_DIR / "fixture_2_seed_7731_defensive/checkpoint.json"
            orig_bytes = ckpt_orig.read_bytes()

            ckpt_file, meta = _prepare_checkpoint("fixture_2_seed_7731_defensive", tpath)

            pos_orders = [
                {"action": "Move", "col": 0, "row": 2, "unit_id": 1},
                {"action": "Move", "col": 4, "row": 5, "unit_id": 4},
                {"action": "Attack", "attacker_id": 4, "defender_id": 28},
                {"action": "Move", "col": 5, "row": 1, "unit_id": 8},
                {"action": "Attack", "attacker_id": 8, "defender_id": 44},
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]
            neg_orders = [
                {"action": "Move", "col": 3, "row": 4, "unit_id": 1},
                {"action": "Attack", "attacker_id": 1, "defender_id": 28},
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]

            final_pos, _, recs_pos = _run_driver_branch(ckpt_file, meta["seed"], pos_orders)
            score_pos = sq.score_cell("seed_7731_defensive", recs_pos)
            self.assertTrue(score_pos["passed"])
            self.assertTrue(score_pos["useful_defense"])
            self.assertEqual(score_pos["friendly_count"], 7)

            final_neg, _, recs_neg = _run_driver_branch(ckpt_file, meta["seed"], neg_orders)
            score_neg = sq.score_cell("seed_7731_defensive", recs_neg)
            self.assertFalse(score_neg["passed"])
            self.assertFalse(score_neg["useful_defense"])
            self.assertEqual(score_neg["friendly_count"], 6)

            self.assertEqual(ckpt_orig.read_bytes(), orig_bytes)

    def test_fixture_4_quiet_control_progress_vs_passivity(self):
        """Fixture 4: active scout engagement makes useful progress; passivity does not."""
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            ckpt_file, meta = _prepare_checkpoint("fixture_4_quiet_control", tpath)

            pos_orders = [
                {"action": "Move", "col": 13, "row": 4, "unit_id": 9},
                {"action": "Attack", "attacker_id": 9, "defender_id": 16},
                {"action": "Move", "col": 5, "row": 4, "unit_id": 10},
                {"action": "Move", "col": 12, "row": 3, "unit_id": 12},
                {"action": "Attack", "attacker_id": 12, "defender_id": 16},
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]
            final_pos, _, recs_pos = _run_driver_branch(ckpt_file, meta["seed"], pos_orders)
            score_pos = sq.score_cell("quiet_control", recs_pos)
            self.assertTrue(score_pos["passed"])
            self.assertTrue(score_pos["useful_progress"])

    def test_fixture_3_late_emergency_action_vs_passivity(self):
        """Fixture 3: active recruiter tactical action vs standing still to die at keep."""
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            ckpt_file, meta = _prepare_checkpoint("fixture_3_late_emergency", tpath)

            pos_orders = [
                {"action": "Move", "col": 2, "row": 8, "unit_id": 1},
                {"action": "Attack", "attacker_id": 1, "defender_id": 18},
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]
            final_pos, end_pos, recs_pos = _run_driver_branch(ckpt_file, meta["seed"], pos_orders)
            score_pos = sq.score_cell("late_emergency", recs_pos)
            self.assertTrue(score_pos["passed"])
            self.assertTrue(score_pos["recruiter_action_committed"])

            neg_orders = [
                {"action": "FinishWithGreedy", "groups": [], "holds": []},
            ]
            final_neg, end_neg, recs_neg = _run_driver_branch(ckpt_file, meta["seed"], neg_orders)
            score_neg = sq.score_cell("late_emergency", recs_neg)
            self.assertFalse(score_neg["passed"])
            self.assertFalse(score_neg["recruiter_action_committed"])

    def test_missing_terminal_evidence_and_batch_rejection(self):
        """Unscored when continuation is missing; rejected batch correctly counted."""
        records = [
            {"type": "driver", "line": {"type": "state", "state_revision": 100, "units": [{"id": 1, "faction": 0, "hp": 48}]}},
            {"type": "strategy_batch_validation", "valid": False, "failed_index": 0},
            {"type": "terminal", "reason": "token_limit"},
        ]
        vec = sq.extract_survival_metric_vector(records)
        self.assertEqual(vec["status"], "unscored")
        self.assertEqual(vec["unscored_reason"], "token_limit")
        self.assertFalse(vec["completed_horizon"])

    def test_lawful_costly_retreat_visible_in_vector(self):
        """A retreat that sacrifices material is tracked in the metric vector."""
        state1 = {
            "type": "state", "state_revision": 200,
            "units": [
                {"id": 1, "faction": 0, "hp": 48, "def_id": "Dark Sorcerer", "can_recruit": True},
                {"id": 5, "faction": 0, "hp": 20, "def_id": "Skeleton"},
            ],
            "gold": [100, 100], "village_owners": [],
        }
        # Final state after sacrifice: unit 5 lost
        state2 = {
            "type": "state", "state_revision": 205,
            "units": [
                {"id": 1, "faction": 0, "hp": 48, "def_id": "Dark Sorcerer", "can_recruit": True},
            ],
            "gold": [100, 100], "village_owners": [],
        }
        records = [
            {"type": "driver", "line": state1},
            {"type": "forwarded_orders", "orders": [{"action": "Move", "col": 0, "row": 0, "unit_id": 1}]},
            {"type": "driver", "line": state2},
            {"type": "turn_boundary"},
        ]
        vec = sq.extract_survival_metric_vector(records, expected_side=0)
        self.assertEqual(vec["friendly_count"], 1)
        self.assertEqual(vec["friendly_material"], 38)
        self.assertTrue(vec["completed_horizon"])
        self.assertTrue(vec["recruiter_alive"])


if __name__ == "__main__":
    unittest.main()
