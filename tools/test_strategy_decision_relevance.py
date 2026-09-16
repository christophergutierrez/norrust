"""Offline fixture bootstrap and boundary tests for strategy decision relevance (Stack 3).

Verifies that target decision boundaries (proposed destination and exhausted contact)
can be bootstrapped via fixed policy with zero model calls and zero board actions,
and that resumed execution reaches the target stage on the very first packet
without falling back to initial policy selection.
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

FIXTURE_PM = ROOT / "tools/fixtures/proposed_movement/proposed_move_mover_exposed.json"
FIXTURE_PM_SHA = "4d43b474556b31edc8ac8fac9e9cb42b3626955347e29225b11a25e9f7834da3"

FIXTURE_EXHAUSTED = ROOT / "tools/fixtures/decision_relevance/exhausted_leader.json"
FIXTURE_EXHAUSTED_SHA = "0d117c3b65535d2c11632b29e2b62f6f6c4a8eb302e79b5e6f02dbd9bf9d653d"

RALLY_POLICY = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": {"col": 12, "row": 7}, "holds": [1],
}

HOLD_RECRUITER_POLICY = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": None, "holds": [1],
}


def bootstrap_fixture(root: Path, fixture_path: Path, policy_obj: dict) -> tuple[Path, Path, Path]:
    """Bootstrap a fixture using --strategy-policy.
    Returns (prepared_checkpoint, setup_log, resumed_model_checkpoint)."""
    data = json.loads(fixture_path.read_text())
    data["board_path"] = str(BOARD_FILE)
    data["save_state"]["board_path"] = str(BOARD_FILE)
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ckpt_path = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    ckpt_path.write_bytes(encoded)

    pol_file = root / "bootstrap-policy.json"
    pol_file.write_text(json.dumps(policy_obj))

    setup_log = root / "setup.ndjson"
    cmd = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--scenario", "big_battle_6",
        "--faction0", "undead", "--faction1", "undead",
        "--gold", "300", "--seed", str(data["seed"]),
        "--llm-side", "0", "--max-turns", "1",
        "--decision-mode", "strategy",
        "--strategy-policy", str(pol_file),
        "--resume-checkpoint", str(ckpt_path),
        "--log", str(setup_log),
    ]
    subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    ck_entry, _ = select_resume_checkpoint(setup_log)
    resumed_ckpt = Path(ck_entry["absolute_path"])
    return ckpt_path, setup_log, resumed_ckpt


def create_scripted_backend(root: Path, responses: list[dict]) -> tuple[Path, Path, Path]:
    """Creates a scripted backend that logs prompts and returns sequential JSON responses."""
    resp_file = root / "responses.json"
    resp_file.write_text(json.dumps(responses))
    prompt_log = root / "backend-calls.ndjson"
    backend = root / "backend.py"
    backend.write_text(textwrap.dedent(f"""
        import json, re, sys
        from pathlib import Path
        responses = json.loads(Path({str(resp_file)!r}).read_text())
        log_path = Path({str(prompt_log)!r})
        prompt = sys.stdin.read()
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({{"prompt": prompt}}) + "\\n")
        idx = sum(1 for _ in log_path.read_text(encoding="utf-8").splitlines()) - 1
        raw = responses[min(idx, len(responses) - 1)]
        resp = dict(raw)
        if resp.get("kind") == "choose" and resp.get("decision_id") == "__FROM_PROMPT__":
            issued = [m for m in re.findall(r'"decision_id":\\s*"([^"]+)"', prompt) if m != "dec-issued"]
            if issued:
                resp["decision_id"] = issued[-1]
            ids = resp.get("option_ids") or []
            if ids == ["__SAFE__"]:
                found = re.findall(r'"option_id":\\s*"(u\\d+-safe-\\d+)"', prompt)
                resp["option_ids"] = [found[0]] if found else []
            elif ids == ["__PROCEED__"]:
                found = re.findall(r'"option_id":\\s*"(u\\d+-proceed-\\d+)"', prompt)
                resp["option_ids"] = [found[0]] if found else []
        print(json.dumps({{"text": json.dumps(resp, separators=(",", ":"))}}))
    """).lstrip(), encoding="utf-8")
    return resp_file, prompt_log, backend


def launch_resumed(root: Path, log: Path, checkpoint: Path, backend: Path,
                   *, seed: int = 9211) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--scenario", "big_battle_6",
        "--faction0", "undead", "--faction1", "undead",
        "--gold", "300", "--seed", str(seed),
        "--llm-side", "0", "--max-turns", "1",
        "--decision-mode", "strategy",
        "--log", str(log),
        "--resume-checkpoint", str(checkpoint),
        "--model-command", shlex.join([sys.executable, str(backend)]),
        "--query-budget-seconds", "20",
        "--turn-timeout", "45",
        "--model-timeout", "10",
        "--max-model-calls-per-turn", "8",
    ]
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=70)


def packets(rows: list[dict]) -> list[dict]:
    return [row["packet"] for row in rows if row.get("type") == "decision_packet"]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class StrategyDecisionRelevanceOfflineTests(unittest.TestCase):
    def test_fixture_and_board_hashes(self):
        self.assertEqual(hashlib.sha256(BOARD_FILE.read_bytes()).hexdigest(), BOARD_SHA)
        self.assertEqual(hashlib.sha256(FIXTURE_PM.read_bytes()).hexdigest(), FIXTURE_PM_SHA)
        self.assertEqual(hashlib.sha256(FIXTURE_EXHAUSTED.read_bytes()).hexdigest(), FIXTURE_EXHAUSTED_SHA)

    def test_bootstrap_proposed_movement_reaches_proposed_destination(self):
        """Proposed move fixture with fixed policy reaches proposed_destination without initial policy prompt."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, setup_log, resumed_ckpt = bootstrap_fixture(root, FIXTURE_PM, RALLY_POLICY)

            setup_rows = records(setup_log)
            # 0 model calls during bootstrap
            self.assertFalse(any(r.get("type") in ("model", "model_request") for r in setup_rows))
            # Policy installed
            self.assertTrue(any(r.get("type") == "policy_installed" for r in setup_rows))

            # Resumed checkpoint is at model boundary
            env = json.loads(resumed_ckpt.read_text())
            self.assertEqual(env.get("boundary"), "model")
            self.assertFalse(env.get("accepted_partial_batches"))

            # Fake preflight with finish_turn
            _, prompt_log, backend = create_scripted_backend(root, [{"kind": "finish_turn"}])
            run_log = root / "preflight.ndjson"
            result = launch_resumed(root, run_log, resumed_ckpt, backend)
            assert_success(self, result, run_log)

            pkts = packets(records(run_log))
            self.assertTrue(pkts)
            first = pkts[0]
            self.assertEqual(first["reason"], "contact")
            self.assertEqual(first["evidence"].get("stage"), "proposed_destination")
            self.assertIn("choose", first["allowed_kinds"])
            self.assertIn("set_policy", first["allowed_kinds"])
            self.assertIn("act", first["allowed_kinds"])
            self.assertIn("finish_turn", first["allowed_kinds"])
            self.assertGreaterEqual(len(first["options"]), 1)

            # Footer prompt confirms choose is advertised
            prompts = [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines()]
            self.assertTrue(prompts)
            self.assertIn("choose", prompts[0])
            self.assertIn("Resolve the named blocked step first", prompts[0])

    def test_bootstrap_exhausted_leader_reaches_empty_contact_menu(self):
        """Exhausted leader fixture reaches exhausted contact menu with no choose kind."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, setup_log, resumed_ckpt = bootstrap_fixture(root, FIXTURE_EXHAUSTED, HOLD_RECRUITER_POLICY)

            setup_rows = records(setup_log)
            self.assertFalse(any(r.get("type") in ("model", "model_request") for r in setup_rows))
            self.assertTrue(any(r.get("type") == "policy_installed" for r in setup_rows))

            env = json.loads(resumed_ckpt.read_text())
            self.assertEqual(env.get("boundary"), "model")

            # Fake preflight with finish_turn
            _, prompt_log, backend = create_scripted_backend(root, [{"kind": "finish_turn"}])
            run_log = root / "preflight.ndjson"
            result = launch_resumed(root, run_log, resumed_ckpt, backend)
            assert_success(self, result, run_log)

            pkts = packets(records(run_log))
            self.assertTrue(pkts)
            first = pkts[0]
            self.assertEqual(first["reason"], "contact")
            self.assertEqual(first["evidence"].get("stage"), "current_state")
            self.assertEqual(first["evidence"].get("contact_actionability"), "exhausted")
            self.assertEqual(first["evidence"].get("options_empty_reason"),
                             "exhausted_contact_no_automatic_rescue_menu")
            self.assertEqual(first["coverage"]["options"], "not_generated")
            self.assertNotIn("choose", first["allowed_kinds"])
            self.assertIn("act", first["allowed_kinds"])
            self.assertIn("finish_turn", first["allowed_kinds"])
            self.assertEqual(first["options"], [])

            prompts = [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines()]
            self.assertTrue(prompts)
            self.assertNotIn("u1-relocate", prompts[0])
            self.assertIn("No automatic rescue menu was generated", prompts[0])
            self.assertNotIn("impossible", prompts[0].lower())
            instruction = prompts[0][prompts[0].rfind("STRATEGY_RESPONSE_INSTRUCTION_BEGIN"):
                                     prompts[0].rfind("STRATEGY_RESPONSE_INSTRUCTION_END")]
            self.assertNotIn("choose", instruction)

    def test_scripted_choose_safe_alternative_on_resumed_fixture(self):
        """Resumed proposed destination accepts scripted choose and commits once."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, resumed_ckpt = bootstrap_fixture(root, FIXTURE_PM, RALLY_POLICY)

            responses = [
                {"kind": "choose", "decision_id": "__FROM_PROMPT__", "option_ids": ["__SAFE__"], "finish_turn": True}
            ]
            _, _, backend = create_scripted_backend(root, responses)
            run_log = root / "choose_safe.ndjson"
            result = launch_resumed(root, run_log, resumed_ckpt, backend)
            assert_success(self, result, run_log)

            rows = records(run_log)
            chosen = [r for r in forwarded(rows) if r.get("proposal_source") == "engine_option"]
            self.assertEqual(len(chosen), 1)
            order = chosen[0]["orders"][0]
            self.assertEqual(order["unit_id"], 5)
            self.assertNotEqual((order["col"], order["row"]), (9, 7))

    def test_scripted_custom_action_plus_finish_on_exhausted_contact(self):
        """Resumed exhausted contact accepts custom legal unit move plus finish."""
        act_response = {
            "kind": "act",
            "actions": [{"action": "Move", "unit_id": 1, "col": 3, "row": 7}],
            "finish_turn": True,
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, resumed_ckpt = bootstrap_fixture(root, FIXTURE_EXHAUSTED, HOLD_RECRUITER_POLICY)

            _, _, backend = create_scripted_backend(root, [act_response])
            run_log = root / "custom_act.ndjson"
            result = launch_resumed(root, run_log, resumed_ckpt, backend)
            assert_success(self, result, run_log)

            rows = records(run_log)
            moves = [e for e in events(rows) if e.get("kind") == "move" and e.get("unit") == 1]
            self.assertEqual(len(moves), 1)
            llm_fwd = [r for r in forwarded(rows) if r.get("source") == "llm"]
            self.assertTrue(llm_fwd)

    def test_catalog_import_idempotence(self):
        """Games run from resumed fixtures import cleanly and idempotently into SQLite."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, resumed_ckpt = bootstrap_fixture(root, FIXTURE_PM, RALLY_POLICY)

            responses = [{"kind": "finish_turn"}]
            _, _, backend = create_scripted_backend(root, responses)
            run_log = root / "import_test.ndjson"
            result = launch_resumed(root, run_log, resumed_ckpt, backend)
            assert_success(self, result, run_log)

            db_path = root / "history.sqlite"
            conn = open_history(db_path)
            try:
                gid1 = import_game(conn, run_log, cohort_id="test_cohort", game_id="test_cohort:pm_game")
                self.assertEqual(gid1, "test_cohort:pm_game")
                counts1 = {
                    table: conn.execute(f"SELECT count(*) FROM {table} WHERE game_id=?", (gid1,)).fetchone()[0]
                    for table in ("events", "side_turns", "model_requests", "action_batches")
                }
                gid2 = import_game(conn, run_log, cohort_id="test_cohort", game_id="test_cohort:pm_game")
                self.assertEqual(gid2, gid1)
                counts2 = {
                    table: conn.execute(f"SELECT count(*) FROM {table} WHERE game_id=?", (gid1,)).fetchone()[0]
                    for table in ("events", "side_turns", "model_requests", "action_batches")
                }
                self.assertEqual(counts1, counts2)
            finally:
                conn.close()

    def test_model_bakeoff_with_resumed_checkpoint_field(self):
        """model_bakeoff handles cell checkpoint field preserving the companion journal."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, _, resumed_ckpt = bootstrap_fixture(root, FIXTURE_PM, RALLY_POLICY)

            _, _, backend = create_scripted_backend(root, [{"kind": "finish_turn"}])

            manifest = {
                "experiment_kind": "matched",
                "cells": [{
                    "id": "bakeoff-pm-cell",
                    "scenario": "big_battle_6",
                    "seed": 9211,
                    "faction0": "undead",
                    "faction1": "undead",
                    "gold": 300,
                    "llm_side": 0,
                    "max_turns": 1,
                    "model": "fake-model",
                    "driver": str(DRIVER),
                    "checkpoint": str(resumed_ckpt),
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
            run_dir = root / "bakeoff_run"
            cmd = [
                sys.executable, "-m", "tools.model_bakeoff", "run", str(mpath),
                "--run-dir", str(run_dir),
                "--cohort", "test-bakeoff-cohort",
            ]
            r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, f"Bakeoff run failed:\n{r.stderr}\n{r.stdout}")

            cell_log = run_dir / "bakeoff-pm-cell" / "match.ndjson"
            self.assertTrue(cell_log.is_file())
            pkts = packets(records(cell_log))
            self.assertTrue(pkts)
            self.assertEqual(pkts[0]["reason"], "contact")
            self.assertEqual(pkts[0]["evidence"].get("stage"), "proposed_destination")


if __name__ == "__main__":
    unittest.main()
