"""Integration tests for Stack 2: small executable tactical choices."""
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

from .game_history import import_game, open_history

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


def choose(option_id: str, *, finish: bool = False, decision_id: str = "__FROM_PROMPT__") -> dict:
    return {
        "kind": "choose",
        "decision_id": decision_id,
        "option_id": option_id,
        "finish_turn": finish,
    }


def act(actions: list[dict], *, finish: bool = False) -> dict:
    return {
        "kind": "act",
        "actions": copy.deepcopy(actions),
        "finish_turn": finish,
    }


def prepare(root: Path, fixture: str, responses: list[dict], *, accepted: int | None = None,
            maximum: int | None = None) -> tuple[Path, Path, Path, Path]:
    data = json.loads((STACK3 / fixture).read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if not board.is_file():
        board = ROOT / "scenarios/big_battle_6/board.json"
    if not board.is_file() or hashlib.sha256(board.read_bytes()).hexdigest() != BOARD_SHA:
        raise AssertionError("maintained big_battle_6 board is absent or hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
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
            match = re.search(r'"decision_id": "([^"]+)"', prompt)
            if match:
                response["decision_id"] = match.group(1)
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


def prompts(path: Path) -> list[str]:
    return [row["prompt"] for row in records(path)]


@unittest.skipUnless(DRIVER.is_file(), "Build greedy_driver before integration tests")
class StrategyStack2IntegrationTests(unittest.TestCase):

    def test_query_determinism_and_resource_bounds(self):
        """20 repeated routine_next queries return identical options under 10s and <= 8 KiB."""
        for fixture_name in ("contact.json", "recruiter_danger.json"):
            with self.subTest(fixture=fixture_name):
                data = json.loads((STACK3 / fixture_name).read_text())
                board = ROOT / "scenarios/big_battle_6/board.toml"
                if not board.is_file():
                    board = ROOT / "scenarios/big_battle_6/board.json"
                data["board_path"] = str(board)
                data["save_state"]["board_path"] = str(board)

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

                        query = {
                            "action": "Query",
                            "what": "routine_next",
                            "policy": EMPTY_POLICY,
                            "progress": {
                                "stage": "recruiting",
                                "recruit_index": 0,
                                "village_index": 0,
                                "scouts": {},
                                "holds": [],
                                "effects": [],
                            },
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
                            self.assertEqual(body.get("result"), "exception")
                            evidence = body.get("evidence", {})
                            self.assertIn("options", evidence)

                            # Option payload size bound: <= 8 KiB (8192 bytes)
                            options_json = json.dumps(evidence["options"], separators=(",", ":"))
                            self.assertLessEqual(
                                len(options_json.encode("utf-8")),
                                8192,
                                f"Option JSON exceeds 8 KiB on {fixture_name}: {len(options_json)} bytes"
                            )
                            # Option count bound: <= 4 options
                            self.assertLessEqual(len(evidence["options"]), 4)

                            # Every individual query must complete under 10s deadline
                            self.assertLess(dt, 10.0, f"Query {i} took too long: {dt}s")

                            if baseline_body is None:
                                baseline_body = body
                            else:
                                # Verify strict determinism: identical results
                                self.assertEqual(body, baseline_body)

                        # Log elapsed times
                        total_time = sum(elapsed_times)
                        max_time = max(elapsed_times)
                        avg_time = total_time / len(elapsed_times)
                        # Every query must finish under a 10-second query deadline
                        self.assertLess(max_time, 10.0, f"Query exceeded 10s deadline on {fixture_name}: {max_time}s")

                    finally:
                        proc.stdin.close()
                        proc.stdout.close()
                        proc.terminate()
                        proc.wait()

    def test_choose_attack_option_executes_with_attribution(self):
        """Model choose response expands and executes attack with proposal_source attribution."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Response 0: initial policy
            # Response 1: choose attack_1
            # Response 2: finish_turn
            responses = [
                policy(),
                choose("attack_1", finish=False),
                {"kind": "finish_turn"},
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "choose-attack.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, f"Launch failed with code {result.returncode}: {result.stderr}")

            rows = records(log)

            # Check decision packet
            packets = [r for r in rows if r.get("type") == "decision_packet"]
            self.assertGreaterEqual(len(packets), 2)
            tactical_pkt = packets[1]["packet"]
            self.assertEqual(tactical_pkt["decision_kind"], "tactical")
            self.assertIn("choose", tactical_pkt["allowed_kinds"])
            self.assertIn(tactical_pkt["coverage"]["options"], ("complete", "truncated"))
            opt_ids = [opt["option_id"] for opt in tactical_pkt["options"]]
            self.assertIn("attack_1", opt_ids)

            # Check forwarded orders
            fwds = forwarded(rows)
            self.assertGreaterEqual(len(fwds), 1)
            attack_fwd = fwds[0]
            self.assertEqual(attack_fwd["source"], "llm")
            self.assertEqual(attack_fwd["proposal_source"], "engine_option")
            self.assertEqual(attack_fwd["option_id"], "attack_1")
            self.assertEqual(attack_fwd["decision_id"], tactical_pkt["decision_id"])

            # Attack action is present in the forwarded orders
            attack_order = next((o for o in attack_fwd["orders"] if o.get("action") == "Attack"), None)
            self.assertIsNotNone(attack_order)
            self.assertEqual(attack_order["attacker_id"], 3)
            self.assertEqual(attack_order["defender_id"], 4)

            # Check request_submitted linkage
            submitted_reqs = [r for r in rows if r.get("type") == "request_submitted" and r.get("option_id") == "attack_1"]
            self.assertEqual(len(submitted_reqs), 1)
            self.assertEqual(submitted_reqs[0]["proposal_source"], "engine_option")
            self.assertEqual(submitted_reqs[0]["decision_id"], tactical_pkt["decision_id"])

            # Check attack event executed on the board
            attack_evs = [e for e in events(rows) if e.get("kind") == "attack"]
            self.assertEqual(len(attack_evs), 1)

    def test_choose_relocation_option_in_recruiter_danger(self):
        """Threatened recruiter receives withdrawal option and successfully executes relocation."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            responses = [
                policy(),
                choose("relocate_1", finish=True),
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "recruiter_danger.json", responses)
            log = root / "choose-relocate.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, f"Launch failed with code {result.returncode}: {result.stderr}")

            rows = records(log)

            # Check decision packet
            packets = [r for r in rows if r.get("type") == "decision_packet"]
            self.assertGreaterEqual(len(packets), 2)
            tactical_pkt = packets[1]["packet"]
            self.assertEqual(tactical_pkt["decision_kind"], "tactical")
            self.assertEqual(tactical_pkt["evidence"]["primary_actor_id"], 1)

            # Relocation option exists
            reloc_opts = [opt for opt in tactical_pkt["options"] if opt.get("category") == "relocation"]
            self.assertTrue(reloc_opts, "Expected at least one relocation option for threatened recruiter")
            reloc_1 = reloc_opts[0]
            self.assertEqual(reloc_1["option_id"], "relocate_1")
            self.assertIn("exposure", reloc_1)

            # Check forwarded orders
            fwds = forwarded(rows)
            self.assertGreaterEqual(len(fwds), 1)
            reloc_fwd = fwds[0]
            self.assertEqual(reloc_fwd["proposal_source"], "engine_option")
            self.assertEqual(reloc_fwd["option_id"], "relocate_1")
            self.assertEqual(reloc_fwd["orders"][0]["action"], "Move")
            self.assertEqual(reloc_fwd["orders"][0]["unit_id"], 1)

            # Check move event executed
            move_evs = [e for e in events(rows) if e.get("kind") == "move" and e.get("unit") == 1]
            self.assertEqual(len(move_evs), 1)

    def test_stale_decision_id_and_unknown_option_rejections(self):
        """Stale decision_id and unknown option_id are rejected contextually and allow repair."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            responses = [
                policy(),
                choose("attack_1", finish=False, decision_id="dec-stale-1111"),
                choose("attack_unknown_999", finish=False),
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "stale-decision.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 3)

            rows = records(log)
            rejections = [r for r in rows if r.get("type") == "contextual_rejection"]
            self.assertEqual(len(rejections), 2)
            self.assertIn("mismatch", rejections[0]["reason"].lower())
            self.assertIn("unknown option_id", rejections[1]["reason"].lower())

    def test_custom_legal_action_escape(self):
        """Model can submit a custom legal action not present in the options menu."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            custom_move = {"action": "Move", "unit_id": 1, "col": 1, "row": 7}
            responses = [
                policy(),
                act([custom_move], finish=True),
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "custom-action.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, f"Custom action launch failed: {result.stderr}")

            rows = records(log)
            fwds = forwarded(rows)
            self.assertGreaterEqual(len(fwds), 1)
            custom_fwd = fwds[0]
            self.assertEqual(custom_fwd["source"], "llm")
            self.assertIsNone(custom_fwd.get("proposal_source"))
            self.assertEqual(custom_fwd["orders"][0]["action"], "Move")
            self.assertEqual(custom_fwd["orders"][0]["unit_id"], 1)

            # Move executed
            move_evs = [e for e in events(rows) if e.get("kind") == "move" and e.get("unit") == 1]
            self.assertEqual(len(move_evs), 1)

    def test_catalog_import_idempotence_and_attribution(self):
        """An option-driven game imports into SQLite catalog with correct attribution and idempotence."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            responses = [
                policy(),
                choose("attack_1", finish=True),
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "catalog-game.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0)

            catalog_db = root / "test_catalog.sqlite"
            # First import
            conn = open_history(catalog_db)
            game_id1 = import_game(conn, log)
            self.assertTrue(isinstance(game_id1, str) and bool(game_id1))

            # Verify action batches and actions were recorded with source == 'llm'
            batches = conn.execute("SELECT batch_id, source FROM action_batches").fetchall()
            self.assertGreaterEqual(len(batches), 1)
            for _, src in batches:
                self.assertEqual(src, "llm")

            actions = conn.execute("SELECT action_id, action_type, source FROM actions").fetchall()
            self.assertGreaterEqual(len(actions), 1)
            for _, act_type, src in actions:
                self.assertEqual(src, "llm")

            # Second import: re-import must be idempotent
            game_id2 = import_game(conn, log)
            self.assertEqual(game_id1, game_id2)

            batches2 = conn.execute("SELECT batch_id, source FROM action_batches").fetchall()
            self.assertEqual(len(batches), len(batches2))
            conn.close()


if __name__ == "__main__":
    unittest.main()
