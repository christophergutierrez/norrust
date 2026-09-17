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

import shlex
import sqlite3
import sys

from . import build_survival_packet, game_history, model_bakeoff, strategy_quality as sq

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


    def test_bakeoff_recruiter_survival_full_pipeline(self):
        """Full pipeline: launch -> response -> continuation -> score -> import -> packet."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "run"
            catalog = root / "catalog.sqlite"
            responses_path = root / "responses.json"
            responses_path.write_text(json.dumps([{"kind": "finish_turn"}]))

            backend_cmd = (
                f"{sys.executable} -m tools.fixtures.strategy_decisions.fake_transport "
                f"--responses {responses_path}"
            )

            manifest = {
                "experiment_kind": "recruiter_survival",
                "cells": [
                    {
                        "id": "cell-f1-low",
                        "position_id": "fixture_1_seed_4477_defensive",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 14,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "low",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "pricing": {
                            "date": "2026-09-17",
                            "rates": {
                                "input_per_million": 0.15,
                                "cached_input_per_million": 0.03,
                                "output_per_million": 0.5,
                                "reasoning_included_in_output": True,
                            },
                        },
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_cmd},
                    },
                    {
                        "id": "cell-f1-high",
                        "position_id": "fixture_1_seed_4477_defensive",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 14,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "high",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "pricing": {
                            "date": "2026-09-17",
                            "rates": {
                                "input_per_million": 0.15,
                                "cached_input_per_million": 0.03,
                                "output_per_million": 0.5,
                                "reasoning_included_in_output": True,
                            },
                        },
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_cmd},
                    },
                ],
            }

            resolved = model_bakeoff.resolve_manifest(manifest)
            validity = model_bakeoff.check_comparison_validity(resolved)
            self.assertTrue(validity["valid"], f"Manifest invalid: {validity.get('mismatches')}")

            results = model_bakeoff.run_manifest(resolved, run_dir, timeout=60)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(r.status == "ok" for r in results))

            # Import to catalog
            imported1 = model_bakeoff.import_cells(catalog, results, "test-cohort")
            self.assertEqual(len(imported1), 2)

            # Idempotence: re-import produces identical list without error or row duplication
            imported2 = model_bakeoff.import_cells(catalog, results, "test-cohort")
            self.assertEqual(imported1, imported2)

            conn = game_history.open_history(catalog, read_only=True)
            try:
                games_count = conn.execute("SELECT count(*) FROM games").fetchone()[0]
                self.assertEqual(games_count, 2)
            finally:
                conn.close()

            # Build report
            report = model_bakeoff.build_report(resolved, results, catalog_path=catalog, cohort_id="test-cohort")
            self.assertEqual(report["totals"]["scheduled"], 2)
            self.assertEqual(report["totals"]["completed"], 2)
            self.assertIsNotNone(report["recruiter_survival"])
            self.assertIn("fixture_1_seed_4477_defensive", report["recruiter_survival"]["positions"])

            # Generate evidence packet
            build_survival_packet.generate_packet(run_dir, catalog_path=catalog)
            self.assertTrue((run_dir / "evidence-index.json").is_file())
            self.assertTrue((run_dir / "decisions.jsonl").is_file())
            self.assertTrue((run_dir / "scores.json").is_file())
            self.assertTrue((run_dir / "review-packet.json").is_file())

            scores = json.loads((run_dir / "scores.json").read_text())
            self.assertIn("cell-f1-low", scores)
            self.assertIn("cell-f1-high", scores)
            self.assertEqual(scores["cell-f1-low"]["status"], "scored")

    def test_fake_transport_missing_usage_and_provider_error(self):
        """Missing usage is preserved without zero-guessing; provider error records failed cell."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # 1. Missing usage
            resp_missing = root / "resp_missing.json"
            resp_missing.write_text(json.dumps([{"kind": "finish_turn", "omit_usage": True}]))
            backend_missing = f"{sys.executable} -m tools.fixtures.strategy_decisions.fake_transport --responses {resp_missing}"

            manifest_missing = {
                "experiment_kind": "recruiter_survival",
                "cells": [
                    {
                        "id": "cell-missing-usage-low",
                        "position_id": "fixture_1_seed_4477_defensive",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 14,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "low",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_missing},
                    },
                    {
                        "id": "cell-missing-usage-high",
                        "position_id": "fixture_1_seed_4477_defensive",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 14,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "high",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_missing},
                    },
                ],
            }
            resolved_missing = model_bakeoff.resolve_manifest(manifest_missing)
            res_missing = model_bakeoff.run_manifest(resolved_missing, root / "run_missing", timeout=30)
            self.assertTrue(all(r.status == "ok" for r in res_missing))

            # 2. Provider error
            resp_error = root / "resp_error.json"
            resp_error.write_text(json.dumps([{"exit_code": 1}]))
            backend_error = f"{sys.executable} -m tools.fixtures.strategy_decisions.fake_transport --responses {resp_error}"

            manifest_error = {
                "experiment_kind": "recruiter_survival",
                "cells": [
                    {
                        "id": "cell-error-low",
                        "position_id": "fixture_1_seed_4477_defensive",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 14,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "low",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_error},
                    },
                    {
                        "id": "cell-error-high",
                        "position_id": "fixture_1_seed_4477_defensive",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 14,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "high",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_error},
                    },
                ],
            }
            resolved_error = model_bakeoff.resolve_manifest(manifest_error)
            res_error = model_bakeoff.run_manifest(resolved_error, root / "run_error", timeout=30)
            self.assertTrue(all(r.status == "failed" for r in res_error))

    def test_partial_turn_checkpoint_execution(self):
        """Fixture 4 with allow_partial_turn_checkpoint executes and scores cleanly."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run_dir = root / "run"
            responses_path = root / "responses.json"
            responses_path.write_text(json.dumps([{"kind": "finish_turn"}]))
            backend_cmd = f"{sys.executable} -m tools.fixtures.strategy_decisions.fake_transport --responses {responses_path}"

            manifest = {
                "experiment_kind": "recruiter_survival",
                "cells": [
                    {
                        "id": "cell-f4-low",
                        "position_id": "fixture_4_quiet_control",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_4_quiet_control/checkpoint.json",
                        "allow_partial_turn_checkpoint": True,
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 6,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "low",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_cmd},
                    },
                    {
                        "id": "cell-f4-high",
                        "position_id": "fixture_4_quiet_control",
                        "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_4_quiet_control/checkpoint.json",
                        "allow_partial_turn_checkpoint": True,
                        "scenario": "big_battle_6",
                        "seed": 4477,
                        "faction0": "undead",
                        "faction1": "undead",
                        "gold": 300,
                        "llm_side": 0,
                        "max_turns": 6,
                        "model": "fake-model",
                        "driver": str(DRIVER),
                        "reasoning_effort": "high",
                        "decision_mode": "strategy",
                        "action_encoding": "coordinates",
                        "incremental_turns": True,
                        "budgets": {
                            "max_game_total_tokens": 150000,
                            "max_model_calls_per_turn": 3,
                            "turn_timeout": 30,
                            "model_timeout": 10,
                        },
                        "backend": {"kind": "command", "command": backend_cmd},
                    },
                ],
            }

            resolved = model_bakeoff.resolve_manifest(manifest)
            results = model_bakeoff.run_manifest(resolved, run_dir, timeout=30)
            self.assertTrue(all(r.status == "ok" for r in results))
            report = model_bakeoff.build_report(resolved, results)
            self.assertEqual(report["totals"]["completed"], 2)


if __name__ == "__main__":
    unittest.main()
