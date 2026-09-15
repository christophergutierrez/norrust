"""Integration tests for Stack 3: continue conservative independent movement during contact."""
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
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools/fixtures/strategy_routine"
STACK3 = FIXTURES / "stack3"
DRIVER = Path(os.environ.get(
    "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
BOARD_SHA = "26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207"

EMPTY_POLICY = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": None, "holds": [],
}


def records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def events(rows: list[dict]) -> list[dict]:
    return [event for row in rows if row.get("type") == "driver"
            and row.get("line", {}).get("type") == "events"
            for event in row["line"].get("events", [])]


def forwarded(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("type") == "forwarded_orders"]


def policy(kind: str = "set_policy", value: dict | None = None) -> dict:
    return {"kind": kind, "policy": copy.deepcopy(value or EMPTY_POLICY)}


def choose(*option_ids: str, finish: bool = False, decision_id: str = "__FROM_PROMPT__") -> dict:
    return {
        "kind": "choose",
        "decision_id": decision_id,
        "option_ids": list(option_ids),
        "finish_turn": finish,
    }


def act(actions: list[dict], *, finish: bool = False) -> dict:
    return {
        "kind": "act",
        "actions": copy.deepcopy(actions),
        "finish_turn": finish,
    }


def prepare(root: Path, fixture: str, responses: list[dict], *,
            extra_units: list[dict] | None = None,
            accepted: int | None = None,
            maximum: int | None = None) -> tuple[Path, Path, Path, Path]:
    data = json.loads((STACK3 / fixture).read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if not board.is_file():
        board = ROOT / "scenarios/big_battle_6/board.json"
    if not board.is_file() or hashlib.sha256(board.read_bytes()).hexdigest() != BOARD_SHA:
        raise AssertionError("maintained big_battle_6 board is absent or hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)

    if extra_units:
        for u in extra_units:
            data["save_state"]["units"].append(copy.deepcopy(u))
            data["save_state"]["next_unit_id"] = max(data["save_state"]["next_unit_id"], u["id"] + 1)
        data["next_id"] = data["save_state"]["next_unit_id"]

    if accepted is not None:
        data["accepted_partial_batches"] = accepted
    if maximum is not None:
        data["max_partial_batches_per_turn"] = maximum
    encoded = json.dumps(data, separators=(",", ":")).encode()
    checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
    checkpoint.write_bytes(encoded)
    response_file = root / "responses.json"
    response_file.write_text(json.dumps(responses))
    prompt_log = root / "backend-calls.ndjson"
    backend = root / "backend.py"
    backend.write_text(textwrap.dedent(f"""
        import json, re, sys
        from pathlib import Path
        response_path = Path({str(response_file)!r})
        log_path = Path({str(prompt_log)!r})
        responses = json.loads(response_path.read_text())
        prompt = sys.stdin.read()
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({{'prompt': prompt}}) + '\\n')
        index = sum(1 for _ in log_path.read_text(encoding='utf-8').splitlines()) - 1
        raw_response = responses[min(index, len(responses) - 1)]
        response = dict(raw_response)
        if response.get("kind") == "choose" and response.get("decision_id") == "__FROM_PROMPT__":
            issued = [m for m in re.findall(r'"decision_id":\\s*"([^"]+)"', prompt) if m != "dec-issued"]
            if issued:
                response["decision_id"] = issued[-1]
        print(json.dumps({{'text': json.dumps(response, separators=(',', ':'))}}))
    """).lstrip(), encoding="utf-8")
    return checkpoint, response_file, backend, prompt_log


def launch(root: Path, log: Path, checkpoint: Path, backend: Path, *, turns: int = 1,
           max_calls: int = 8, maximum: int | None = None,
           driver_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    envelope = json.loads(checkpoint.read_text())
    args = [sys.executable, "-m", "tools.llm_client", "--driver", str(driver_path or DRIVER),
            "--scenario", str(envelope["scenario"]), "--faction0", str(envelope["faction0"]),
            "--faction1", str(envelope["faction1"]), "--gold", str(envelope["starting_gold"]),
            "--seed", str(envelope["seed"]), "--llm-side", str(envelope["llm_side"]),
            "--max-turns", str(turns),
            "--decision-mode", "strategy", "--log", str(log),
            "--model-command", shlex.join([sys.executable, str(backend)]),
            "--query-budget-seconds", "20", "--turn-timeout", "45", "--model-timeout", "10",
            "--max-model-calls-per-turn", str(max_calls)]
    if maximum is not None:
        args += ["--max-partial-batches-per-turn", str(maximum)]
    args += ["--resume-checkpoint", str(checkpoint)]
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=70)


class TestStrategyStack3Integration(unittest.TestCase):
    def test_independent_scout_move_commits_before_model_call(self):
        """Threatened non-recruiter plus distant scout: scout moves without model call, then tactical packet."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Distant scout at (2, 5) heading to village at (1, 1).
            # Skeleton 3 at (10, 7) in contact with enemy Skeleton 4 at (11, 7).
            extra_scout = {
                "id": 5, "def_id": "Ghost", "name": "Ghost", "level": 1, "faction": 0,
                "hp": 18, "max_hp": 18, "movement": 7, "col": 2, "row": 5,
                "moved": False, "attacked": False, "can_recruit": False,
                "advancement_pending": False, "slowed": False, "poisoned": False,
                "xp": 0, "xp_needed": 30, "abilities": ["skirmisher"],
            }
            init_policy = {
                "reserve_gold": 0, "recruits": [], "scouts": [5],
                "villages": [{"col": 2, "row": 4}],
                "rally": None, "holds": [],
            }
            responses = [
                policy("set_policy", init_policy),
                choose("u3-attack-1", finish=True),
            ]
            checkpoint, _, backend, prompt_log = prepare(
                root, "contact.json", responses, extra_units=[extra_scout],
            )
            log = root / "stack3-scout.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, f"Launch failed:\n{result.stderr}\n{result.stdout}")

            rows = records(log)

            # 1. An independent_routine_move was logged with objective and tactical hashes
            indep_rows = [r for r in rows if r.get("type") == "independent_routine_move"]
            self.assertEqual(len(indep_rows), 1, "Exactly one independent scout move should be logged")
            indep = indep_rows[0]
            self.assertEqual(indep["action"]["unit_id"], 5)
            self.assertEqual(indep["policy_objective"]["type"], "village")
            self.assertEqual(indep["coverage"], "complete")
            self.assertTrue(len(indep["pre_tactical_hash"]) > 0)
            self.assertTrue(len(indep["post_tactical_hash"]) > 0)
            self.assertTrue(len(indep["deferred_incident_key"]) > 0)

            # 2. Forwarded orders sequence:
            # First order is scout move from source "routine"
            # Second order is model attack option from source "llm" with proposal_source "engine_option"
            f_rows = forwarded(rows)
            self.assertGreaterEqual(len(f_rows), 2)
            self.assertEqual(f_rows[0]["source"], "routine")
            self.assertEqual(f_rows[0]["orders"][0]["unit_id"], 5)

            llm_fwd = [r for r in f_rows if r.get("source") == "llm"]
            self.assertEqual(len(llm_fwd), 1)
            self.assertEqual(llm_fwd[0]["proposal_source"], "engine_option")

    def test_recruiter_danger_preempts_distant_movement(self):
        """Recruiter danger issues contact decision immediately without distant movement."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            extra_scout = {
                "id": 5, "def_id": "Ghost", "name": "Ghost", "level": 1, "faction": 0,
                "hp": 18, "max_hp": 18, "movement": 7, "col": 15, "row": 5,
                "moved": False, "attacked": False, "can_recruit": False,
                "advancement_pending": False, "slowed": False, "poisoned": False,
                "xp": 0, "xp_needed": 30, "abilities": ["skirmisher"],
            }
            init_policy = {
                "reserve_gold": 0, "recruits": [], "scouts": [5],
                "villages": [{"col": 2, "row": 4}],
                "rally": None, "holds": [],
            }
            responses = [
                policy("set_policy", init_policy),
                choose("u1-relocate-1", finish=True),
            ]
            checkpoint, _, backend, prompt_log = prepare(
                root, "recruiter_danger.json", responses, extra_units=[extra_scout],
            )
            log = root / "recruiter-danger.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, f"Launch failed:\n{result.stderr}\n{result.stdout}")

            rows = records(log)
            indep_rows = [r for r in rows if r.get("type") == "independent_routine_move"]
            self.assertEqual(len(indep_rows), 0, "No independent scout move should occur when recruiter is in danger")

            # Check that recruiter contact decision was issued immediately
            f_rows = forwarded(rows)
            self.assertEqual(len(f_rows), 1)
            self.assertEqual(f_rows[0]["source"], "llm")
            self.assertEqual(f_rows[0]["proposal_source"], "engine_option")
            self.assertEqual(f_rows[0]["orders"][0]["unit_id"], 1)

    def test_query_determinism_and_resource_bounds_20_iterations(self):
        """20 repeated routine_next queries on contact state: determinism, <10s deadline."""
        extra_scout = {
            "id": 5, "def_id": "Ghost", "name": "Ghost", "level": 1, "faction": 0,
            "hp": 18, "max_hp": 18, "movement": 7, "col": 2, "row": 5,
            "moved": False, "attacked": False, "can_recruit": False,
            "advancement_pending": False, "slowed": False, "poisoned": False,
            "xp": 0, "xp_needed": 30, "abilities": ["skirmisher"],
        }
        data = json.loads((STACK3 / "contact.json").read_text())
        board = ROOT / "scenarios/big_battle_6/board.toml"
        if not board.is_file():
            board = ROOT / "scenarios/big_battle_6/board.json"
        data["board_path"] = str(board)
        data["save_state"]["board_path"] = str(board)
        data["save_state"]["units"].append(extra_scout)
        data["save_state"]["next_unit_id"] = 6
        data["next_id"] = 6

        encoded = json.dumps(data, separators=(",", ":")).encode()
        with tempfile.TemporaryDirectory() as td:
            ckpt_path = Path(td) / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
            ckpt_path.write_bytes(encoded)

            cmd = [
                str(DRIVER),
                "--scenario", "big_battle_6",
                "--faction0", "undead",
                "--faction1", "undead",
                "--gold", "300",
                "--seed", "9211",
                "--max-turns", "6",
                "--llm-side", "0",
                "--incremental-turns",
                "--max-partial-batches-per-turn", "64",
                "--resume-checkpoint", str(ckpt_path),
            ]

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            try:
                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break
                    msg = json.loads(line)
                    if msg.get("type") == "state":
                        break

                policy_obj = {
                    "reserve_gold": 0, "recruits": [], "scouts": [5],
                    "villages": [{"col": 2, "row": 4}],
                    "rally": None, "holds": [],
                }
                progress_obj = {
                    "installation_id": "inst_1",
                    "completed_villages": [],
                    "scout_assignments": [],
                    "recruited": [],
                    "scout_ids": [5],
                    "policy_complete": False,
                }

                query = {
                    "action": "Query",
                    "what": "routine_next",
                    "policy": policy_obj,
                    "progress": progress_obj,
                    "state_revision": 0,
                }
                query_str = json.dumps(query) + "\n"

                baseline_body = None
                elapsed_times = []

                for i in range(20):
                    t0 = time.perf_counter()
                    proc.stdin.write(query_str)
                    proc.stdin.flush()

                    reply_line = proc.stdout.readline()
                    dt = time.perf_counter() - t0
                    elapsed_times.append(dt)

                    msg = json.loads(reply_line)
                    self.assertTrue(msg.get("ok"), f"Query failed on iteration {i}: {msg}")
                    body = msg.get("body", {})
                    self.assertEqual(body.get("result"), "action")
                    self.assertIn("independent_move", body)

                    # Individual query under 10s deadline
                    self.assertLess(dt, 10.0, f"Query {i} took too long: {dt}s")

                    if baseline_body is None:
                        baseline_body = body
                    else:
                        self.assertEqual(body, baseline_body)

                max_time = max(elapsed_times)
                avg_time = sum(elapsed_times) / len(elapsed_times)
                self.assertLess(max_time, 10.0)
                print(f"\n[Stack 3] 20 queries completed: avg={avg_time:.4f}s, max={max_time:.4f}s (< 10.0s deadline)")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.terminate()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
