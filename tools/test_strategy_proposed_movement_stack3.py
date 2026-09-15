"""Real-driver acceptance for proposed-destination choose menus (Stack 3)."""
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

from .test_strategy_routine_stack3 import DRIVER, ROOT, assert_success, events, forwarded, records


FIXTURES = ROOT / "tools/fixtures/proposed_movement"
BOARD_SHA = "26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207"
RALLY_POLICY = {
    "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
    "rally": {"col": 12, "row": 7}, "holds": [1],
}


def policy(value=None):
    return {"kind": "set_policy", "policy": copy.deepcopy(value or RALLY_POLICY)}


def choose(*option_ids, finish=False, decision_id="__FROM_PROMPT__"):
    return {
        "kind": "choose",
        "decision_id": decision_id,
        "option_ids": list(option_ids),
        "finish_turn": finish,
    }


def prepare(root: Path, fixture: str, responses: list[dict]) -> tuple[Path, Path, Path, Path]:
    data = json.loads((FIXTURES / fixture).read_text())
    board = ROOT / "scenarios/big_battle_6/board.toml"
    if hashlib.sha256(board.read_bytes()).hexdigest() != BOARD_SHA:
        raise AssertionError("maintained big_battle_6 board hash changed")
    data["board_path"] = str(board)
    data["save_state"]["board_path"] = str(board)
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
            ids = response.get("option_ids") or []
            if ids == ["__SAFE__"]:
                found = re.findall(r'"option_id":\\s*"(u\\d+-safe-\\d+)"', prompt)
                response["option_ids"] = [found[0]] if found else []
            if ids == ["__PROCEED__"]:
                found = re.findall(r'"option_id":\\s*"(u\\d+-proceed-\\d+)"', prompt)
                response["option_ids"] = [found[0]] if found else []
        print(json.dumps({{'text': json.dumps(response, separators=(',', ':'))}}))
    """).lstrip(), encoding="utf-8")
    return checkpoint, response_file, backend, prompt_log


def launch(root: Path, log: Path, checkpoint: Path, backend: Path) -> subprocess.CompletedProcess[str]:
    envelope = json.loads(checkpoint.read_text())
    args = [
        sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
        "--scenario", str(envelope["scenario"]), "--faction0", str(envelope["faction0"]),
        "--faction1", str(envelope["faction1"]), "--gold", str(envelope["starting_gold"]),
        "--seed", str(envelope["seed"]), "--llm-side", str(envelope["llm_side"]),
        "--max-turns", "1", "--decision-mode", "strategy", "--log", str(log),
        "--model-command", shlex.join([sys.executable, str(backend)]),
        "--query-budget-seconds", "20", "--turn-timeout", "45", "--model-timeout", "10",
        "--max-model-calls-per-turn", "8", "--resume-checkpoint", str(checkpoint),
    ]
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=70)


def packets(rows):
    return [row["packet"] for row in rows if row.get("type") == "decision_packet"]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class ProposedMovementStack3Tests(unittest.TestCase):
    def test_choose_safe_alternative_commits_once_without_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("__SAFE__"), {"kind": "finish_turn"}])
            log = root / "safe.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertFalse(any(row.get("type") == "strategy_response_repair" for row in rows))
            self.assertFalse(any(row.get("type") == "contact_key_consumed" for row in rows))
            proposed = [p for p in packets(rows)
                        if p.get("evidence", {}).get("stage") == "proposed_destination"]
            self.assertTrue(proposed)
            self.assertEqual(proposed[0]["decision_kind"], "policy")
            self.assertIn("choose", proposed[0]["allowed_kinds"])
            self.assertIn("set_policy", proposed[0]["allowed_kinds"])
            cats = [opt["category"] for opt in proposed[0]["options"]]
            self.assertIn("proceed_with_exposure", cats)
            self.assertIn("safe_alternative", cats)
            chosen = [row for row in forwarded(rows)
                      if row.get("proposal_source") == "engine_option"]
            self.assertEqual(len(chosen), 1)
            order = chosen[0]["orders"][0]
            self.assertEqual(order["action"], "Move")
            self.assertEqual(order["unit_id"], 5)
            self.assertNotEqual((order["col"], order["row"]), (9, 7))
            self.assertEqual(sum(1 for e in events(rows)
                                 if e.get("kind") == "move" and e.get("unit") == 5), 1)

    def test_choose_proceed_is_legal_and_does_not_close_contact(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("__PROCEED__", finish=True)])
            log = root / "proceed.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertFalse(any(row.get("type") == "contact_key_consumed" for row in rows))
            chosen = [row for row in forwarded(rows)
                      if row.get("proposal_source") == "engine_option"]
            self.assertEqual(len(chosen), 1)
            order = chosen[0]["orders"][0]
            self.assertEqual((order["col"], order["row"]), (9, 7))
            later = [p for p in packets(rows)
                     if p.get("evidence", {}).get("stage") == "current_state"]
            if later:
                self.assertFalse(later[0].get("final_only"))

    def test_hold_policy_prevents_the_same_proposal(self):
        held = {**copy.deepcopy(RALLY_POLICY), "holds": [1, 5]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), policy(held), {"kind": "finish_turn"}])
            log = root / "hold.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            proposed = [p for p in packets(rows)
                        if p.get("evidence", {}).get("stage") == "proposed_destination"]
            self.assertEqual(len(proposed), 1)
            self.assertFalse(any(
                row.get("type") == "forwarded_orders"
                and row.get("source") == "routine"
                and (row.get("orders") or [{}])[0].get("unit_id") == 5
                for row in rows))

    def test_stale_option_id_is_repaired_then_finish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "proposed_move_mover_exposed.json",
                [policy(), choose("u5-safe-99"), {"kind": "finish_turn"}])
            log = root / "stale.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(any(row.get("type") == "strategy_response_repair" for row in rows))
            self.assertFalse(any(row.get("proposal_source") == "engine_option"
                                 for row in forwarded(rows)))


if __name__ == "__main__":
    unittest.main()
