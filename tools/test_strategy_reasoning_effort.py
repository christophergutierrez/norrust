"""Integration and boundary tests for strategy reasoning effort (Stack 1).

Verifies the end-to-end manifest -> client request context -> backend -> usage sidecar ->
SQLite import path for explicit reasoning_effort ('low', 'max', omitted), and verifies
that the three comparison positions reach identical canonical prompts on their target
decision boundaries.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest

from .game_history import import_game, open_history
from .llm_client import select_resume_checkpoint
from .test_strategy_routine_stack3 import DRIVER, ROOT, assert_success, events, forwarded, records


BOARD_FILE = ROOT / "scenarios/big_battle_6/board.toml"
BOARD_SHA = "26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207"

FIXTURE_ORDINARY = ROOT / "tools/fixtures/contact_efficiency/three_actors.json"
FIXTURE_DIFFICULT = ROOT / "tools/fixtures/strategy_decisions/difficult_contact.json"
FIXTURE_EXHAUSTED = ROOT / "tools/fixtures/decision_relevance/exhausted_leader.json"

DEFAULT_POLICY = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": None, "holds": [1],
}


def bootstrap_fixture(root: Path, fixture_path: Path, policy_obj: dict | None = None,
                      *, max_turns: int = 6) -> tuple[Path, Path, Path]:
    """Bootstrap a fixture using --strategy-policy.
    Returns (prepared_checkpoint, setup_log, resumed_model_checkpoint)."""
    data = json.loads(fixture_path.read_text())
    data["board_path"] = str(BOARD_FILE)
    data["save_state"]["board_path"] = str(BOARD_FILE)
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ckpt_path = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    ckpt_path.write_bytes(encoded)

    pol_file = root / "bootstrap-policy.json"
    pol_file.write_text(json.dumps(policy_obj or DEFAULT_POLICY))

    setup_log = root / "setup.ndjson"
    cmd = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--scenario", "big_battle_6",
        "--faction0", "undead", "--faction1", "undead",
        "--gold", "300", "--seed", str(data["seed"]),
        "--llm-side", "0", "--max-turns", str(max_turns),
        "--decision-mode", "strategy",
        "--strategy-policy", str(pol_file),
        "--resume-checkpoint", str(ckpt_path),
        "--log", str(setup_log),
    ]
    subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    ck_entry, _ = select_resume_checkpoint(setup_log)
    resumed_ckpt = Path(ck_entry["absolute_path"])
    return ckpt_path, setup_log, resumed_ckpt


def create_logging_backend(root: Path, response: dict, name: str = "backend") -> tuple[Path, Path]:
    """Creates a backend that records prompt text and context metadata."""
    calls_log = root / f"{name}-calls.ndjson"
    backend = root / f"{name}.py"
    backend.write_text(textwrap.dedent(f"""
        import json, os, sys
        from pathlib import Path
        prompt = sys.stdin.read()
        ctx_path = os.environ.get("NORRUST_REQUEST_CONTEXT_FILE")
        ctx = json.loads(Path(ctx_path).read_text()) if ctx_path and Path(ctx_path).exists() else {{}}
        entry = {{"prompt": prompt, "context": ctx}}
        with open({str(calls_log)!r}, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\\n")
        resp = {json.dumps(response)}
        print(json.dumps({{"text": json.dumps(resp)}}))
    """).lstrip(), encoding="utf-8")
    return calls_log, backend


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class StrategyReasoningEffortIntegrationTests(unittest.TestCase):
    def test_fixture_hashes(self):
        self.assertTrue(FIXTURE_ORDINARY.is_file())
        self.assertTrue(FIXTURE_DIFFICULT.is_file())
        self.assertTrue(FIXTURE_EXHAUSTED.is_file())
        self.assertEqual(hashlib.sha256(BOARD_FILE.read_bytes()).hexdigest(), BOARD_SHA)

    def test_bakeoff_reasoning_effort_flows_to_context_log_and_sqlite(self):
        """reasoning_effort in bakeoff cell reaches request context, game log, and SQLite."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, resumed_ckpt = bootstrap_fixture(root, FIXTURE_EXHAUSTED, DEFAULT_POLICY, max_turns=6)
            calls_log, backend = create_logging_backend(root, {"kind": "finish_turn"})

            manifest = {
                "experiment_kind": "matched",
                "cells": [{
                    "id": "effort-low-cell",
                    "scenario": "big_battle_6",
                    "seed": 9211,
                    "faction0": "undead",
                    "faction1": "undead",
                    "gold": 300,
                    "llm_side": 0,
                    "max_turns": 6,
                    "model": "fake-model",
                    "driver": str(DRIVER),
                    "checkpoint": str(resumed_ckpt),
                    "reasoning_effort": "low",
                    "decision_mode": "strategy",
                    "action_encoding": "coordinates",
                    "incremental_turns": True,
                    "pricing": {
                        "date": "2026-09-15",
                        "rates": {
                            "input_per_million": 0.15,
                            "cached_input_per_million": 0.03,
                            "output_per_million": 0.5,
                            "reasoning_included_in_output": True,
                        },
                    },
                    "budgets": {
                        "max_game_total_tokens": 10000,
                        "turn_timeout": 30,
                        "model_timeout": 10,
                    },
                    "backend": {"kind": "command", "command": shlex.join([sys.executable, str(backend)])},
                }],
            }
            mpath = root / "manifest.json"
            mpath.write_text(json.dumps(manifest))
            run_dir = root / "run"
            cmd = [
                sys.executable, "-m", "tools.model_bakeoff", "run", str(mpath),
                "--run-dir", str(run_dir),
                "--cohort", "effort-test-cohort",
            ]
            r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, f"Bakeoff failed:\n{r.stderr}\n{r.stdout}")

            # 1. Request context recorded "low"
            calls = [json.loads(l) for l in calls_log.read_text().splitlines()]
            self.assertTrue(calls)
            self.assertEqual(calls[0]["context"].get("requested_reasoning_effort"), "low")

            # 2. Match log recorded "low" in metadata record
            match_log = run_dir / "effort-low-cell" / "match.ndjson"
            rows = [json.loads(l) for l in match_log.read_text().splitlines()]
            meta = next(r for r in rows if r.get("type") == "metadata")
            self.assertEqual(meta.get("requested_reasoning_effort"), "low")

            # 3. SQLite catalog has reasoning_requested='low' and reported as None in game_players table
            db_path = run_dir / "catalog.sqlite"
            conn = open_history(db_path)
            try:
                row = conn.execute(
                    "SELECT reasoning_requested, reasoning_reported FROM game_players WHERE side=0"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row[0], "low")
                self.assertIsNone(row[1])  # reported effort remains unknown unless provider reports it
            finally:
                conn.close()

    def test_fireworks_backend_cli_and_context_precedence(self):
        """Fireworks backend enforces precedence and rejects unsupported values."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sidecar = root / "usage.json"
            ctx_file = root / "ctx.json"

            # 1. Conflict between CLI flag and context -> error
            ctx_file.write_text(json.dumps({"requested_reasoning_effort": "low"}))
            res = subprocess.run(
                [sys.executable, "-m", "tools.fireworks_backend",
                 "--usage-sidecar", str(sidecar),
                 "--request-context", str(ctx_file),
                 "--reasoning-effort", "max"],
                input="prompt", capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("configure --reasoning-effort on llm_client", res.stderr)

            # 2. Unsupported reasoning effort (e.g. medium) -> rejected before network
            ctx_file.write_text(json.dumps({"requested_reasoning_effort": "medium"}))
            res = subprocess.run(
                [sys.executable, "-m", "tools.fireworks_backend",
                 "--usage-sidecar", str(sidecar),
                 "--request-context", str(ctx_file)],
                input="prompt", capture_output=True, text=True, cwd=ROOT)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("unsupported reasoning_effort", res.stderr)

    def test_three_comparison_positions_canonical_prompts_pair_exactly(self):
        """All three comparison positions reach target boundaries with byte-identical prompts for low vs max."""
        positions = [
            ("ordinary", FIXTURE_ORDINARY, 6),
            ("difficult", FIXTURE_DIFFICULT, 6),
            ("exhausted", FIXTURE_EXHAUSTED, 6),
        ]

        for name, fix_path, max_turns in positions:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                _, _, resumed_ckpt = bootstrap_fixture(root, fix_path, DEFAULT_POLICY, max_turns=max_turns)

                prompts_by_effort = {}
                for effort in ("low", "max"):
                    log_file = root / f"preflight_{effort}.ndjson"
                    call_log, backend = create_logging_backend(root, {"kind": "finish_turn"}, name=f"backend_{effort}")

                    envelope = json.loads(resumed_ckpt.read_text())
                    args = [
                        sys.executable, "-m", "tools.llm_client",
                        "--driver", str(DRIVER),
                        "--scenario", "big_battle_6",
                        "--faction0", "undead", "--faction1", "undead",
                        "--gold", "300", "--seed", str(envelope["seed"]),
                        "--llm-side", "0", "--max-turns", str(max_turns),
                        "--decision-mode", "strategy",
                        "--reasoning-effort", effort,
                        "--resume-checkpoint", str(resumed_ckpt),
                        "--model-command", shlex.join([sys.executable, str(backend)]),
                        "--log", str(log_file),
                        "--query-budget-seconds", "60",
                        "--turn-timeout", "90",
                        "--model-timeout", "10",
                    ]
                    r = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=120)
                    assert_success(self, r, log_file)

                    rows = records(log_file)
                    pkts = [row["packet"] for row in rows if row.get("type") == "decision_packet"]
                    self.assertTrue(pkts, f"No packets for {name} ({effort})")
                    first_pkt = pkts[0]
                    self.assertEqual(first_pkt["reason"], "contact", f"{name}: expected reason contact")

                    calls = [json.loads(l) for l in call_log.read_text().splitlines()]
                    self.assertTrue(calls)
                    prompts_by_effort[effort] = calls[0]["prompt"]

                # Assert that canonical prompts for 'low' and 'max' are 100% byte-identical
                self.assertEqual(
                    prompts_by_effort["low"],
                    prompts_by_effort["max"],
                    f"Canonical prompt drift between low and max for position {name}"
                )


if __name__ == "__main__":
    unittest.main()
