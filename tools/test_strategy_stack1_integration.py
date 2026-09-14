"""Integration tests for Stack 1: decision boundaries and bounded ineffective responses."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
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
ATTACK = {"action": "Attack", "attacker_id": 3, "defender_id": 4}


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


def act(*, finish: bool, action: dict = ATTACK) -> dict:
    return {"kind": "act", "actions": [copy.deepcopy(action)], "finish_turn": finish}


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
        import json, sys
        from pathlib import Path
        response_path = Path({str(response_file)!r})
        log_path = Path({str(prompt_log)!r})
        responses = json.loads(response_path.read_text())
        prompt = sys.stdin.read()
        with log_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({{'prompt': prompt}}) + '\\n')
        index = sum(1 for _ in log_path.read_text(encoding='utf-8').splitlines()) - 1
        response = responses[min(index, len(responses) - 1)]
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
class StrategyStack1IntegrationTests(unittest.TestCase):

    def test_contact_checkpoint_rejects_repeated_set_policy_and_stops_as_strategy_no_progress(self):
        """Two set_policy calls at contact pause produce typed interruption strategy_no_progress."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Response 0: initial policy
            # Response 1: set_policy on contact (contextual rejection 1)
            # Response 2: set_policy on contact repair (contextual rejection 2 -> terminal stop)
            responses = [policy(), policy(), policy()]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "contact-rejection.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 3)  # TERMINAL_BUDGET_INTERRUPTED

            rows = records(log)
            # Exactly 3 model prompts (initial, contact decision, contact repair)
            self.assertEqual(len(prompts(prompt_log)), 3)

            # Check decision packets: initial (policy) and contact (tactical)
            packets = [row for row in rows if row.get("type") == "decision_packet"]
            self.assertGreaterEqual(len(packets), 2)
            self.assertEqual(packets[0]["packet"]["decision_kind"], "policy")
            self.assertEqual(packets[1]["packet"]["decision_kind"], "tactical")
            self.assertEqual(packets[1]["packet"]["allowed_kinds"], ["act", "finish_turn", "resign"])

            # Check contextual rejections: exactly 2
            rejections = [row for row in rows if row.get("type") == "contextual_rejection"]
            self.assertEqual(len(rejections), 2)
            for rej in rejections:
                self.assertIn("not allowed for contact", rej["reason"])
                self.assertEqual(rej["state_revision"], 0)

            # Terminal record is budget_interrupted with code strategy_no_progress
            terminals = [row for row in rows if row.get("type") == "terminal"]
            self.assertTrue(terminals)
            self.assertEqual(terminals[-1]["reason"], "budget_interrupted")
            self.assertEqual(terminals[-1]["code"], "strategy_no_progress")

            # No policy installation occurred from the rejected policies (only the initial one)
            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 1)

            # No forwarded actions from rejected responses
            self.assertEqual(len(forwarded(rows)), 0)

    def test_contact_checkpoint_recovers_with_legal_tactical_act_after_invalid_set_policy(self):
        """Initial set_policy on contact is rejected, model repairs with act, which commits."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Response 0: initial policy
            # Response 1: set_policy on contact (contextual rejection)
            # Response 2: act(finish=True) (repaired tactical action)
            responses = [policy(), policy(), act(finish=True)]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "contact-recovery.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, result.stderr)

            rows = records(log)
            # Rejection was recorded
            rejections = [row for row in rows if row.get("type") == "contextual_rejection"]
            self.assertEqual(len(rejections), 1)

            # Repair note was recorded
            repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
            self.assertEqual(len(repairs), 1)

            # Tactical action was forwarded and committed
            batches = [row for row in forwarded(rows)
                       if any(order.get("action") == "Attack" for order in row.get("orders", []))]
            self.assertEqual(len(batches), 1)
            attack_events = [e for e in events(rows) if e.get("kind") == "attack"]
            self.assertEqual(len(attack_events), 1)

            # Decision brief for contact explicitly excluded set_policy
            call_prompts = prompts(prompt_log)
            self.assertGreaterEqual(len(call_prompts), 2)
            contact_prompt = call_prompts[1]
            self.assertIn("TACTICAL DECISION REQUIRED", contact_prompt)
            self.assertIn("Changing policy moves no units", contact_prompt)

    def test_village_policy_without_scouts_rejected_before_recruitment(self):
        """Policy targeting villages with zero scouts and zero scout recruits is rejected."""
        village_policy_no_scouts = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
            "scouts": [],
            "villages": [{"col": 5, "row": 3}],
            "rally": None,
            "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Model attempts village policy with no scouts, then another invalid policy
            responses = [policy(value=village_policy_no_scouts), policy(value=village_policy_no_scouts)]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "village-rejection.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 2)  # TERMINAL_MODEL_INVALID

            rows = records(log)
            # Policy was never installed
            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 0)

            # Repair attempted
            repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
            self.assertEqual(len(repairs), 1)
            self.assertIn("scout", str(repairs[0]["error"]).lower())

    def test_crash_resume_retains_consumed_allowance(self):
        """Consumed contextual rejection allowance is reconstructed from journal on resume."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Initial run: initial policy, then 1 invalid set_policy on contact, then killed/halted
            responses = [policy(), policy()]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "resume-test.ndjson"
            result = launch(root, log, checkpoint, backend, max_calls=2)
            # Hit max calls (2 calls made: 1 initial, 1 rejected)
            rows = records(log)
            rejections = [row for row in rows if row.get("type") == "contextual_rejection"]
            self.assertEqual(len(rejections), 1)

            # Simulate crash before terminal record: strip terminal/budget lines
            lines = [l for l in log.read_text().splitlines()
                     if '"type": "terminal"' not in l and '"type": "budget_interrupted"' not in l]
            log.write_text('\n'.join(lines) + '\n')

            # Now resume from that log with another invalid set_policy
            # Since 1 allowance was already consumed before resume, 1 more invalid response must HALT as strategy_no_progress!
            resume_responses = [policy()]
            resume_response_file = root / "responses2.json"
            resume_response_file.write_text(json.dumps(resume_responses))
            backend2 = root / "backend2.py"
            backend2.write_text(textwrap.dedent(f"""
                import json, sys
                from pathlib import Path
                response_path = Path({str(resume_response_file)!r})
                responses = json.loads(response_path.read_text())
                prompt = sys.stdin.read()
                print(json.dumps({{'text': json.dumps(responses[0], separators=(',', ':'))}}))
            """).lstrip(), encoding="utf-8")

            envelope = json.loads(checkpoint.read_text())
            cmd = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                   "--scenario", str(envelope["scenario"]), "--faction0", str(envelope["faction0"]),
                   "--faction1", str(envelope["faction1"]), "--gold", str(envelope["starting_gold"]),
                   "--seed", str(envelope["seed"]), "--llm-side", str(envelope["llm_side"]),
                   "--max-turns", "1", "--decision-mode", "strategy", "--log", str(log),
                   "--model-command", shlex.join([sys.executable, str(backend2)]),
                   "--query-budget-seconds", "20", "--turn-timeout", "45", "--model-timeout", "10",
                   "--resume-log", str(log)]
            resume_result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=70)
            self.assertEqual(resume_result.returncode, 3)  # TERMINAL_BUDGET_INTERRUPTED

            resumed_rows = records(log)
            terminals = [row for row in resumed_rows if row.get("type") == "terminal"]
            self.assertTrue(terminals)
            self.assertEqual(terminals[-1]["reason"], "budget_interrupted")
            self.assertEqual(terminals[-1]["code"], "strategy_no_progress")

    def test_aba_recurrence_at_same_revision_stops_as_strategy_no_progress(self):
        """A->B->A policy oscillation at same revision does not renew allowance and halts."""
        policy_a = {
            "reserve_gold": 300,
            "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}],
            "scouts": [], "villages": [], "rally": None, "holds": [],
        }
        policy_b = {
            "reserve_gold": 300,
            "recruits": [{"def_id": "Dark Adept", "count": 1, "role": "scout"}],
            "scouts": [], "villages": [], "rally": None, "holds": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            responses = [
                policy(value=policy_a),  # Incident A (Ghost blocked)
                policy(value=policy_b),  # Incident B (Dark Adept blocked)
                policy(value=policy_a),  # Recurrence A (Ghost blocked again, 1 correction used)
                policy(value=policy_a),  # Recurrence A again (allowance exhausted)
            ]
            checkpoint, _, backend, prompt_log = prepare(root, "blocked_objective.json", responses)
            log = root / "aba.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 3)  # TERMINAL_BUDGET_INTERRUPTED

            rows = records(log)
            recurrences = [r for r in rows if r.get("type") == "incident_recurrence"]
            self.assertEqual(len(recurrences), 2)
            for rec in recurrences:
                self.assertEqual(rec["reason"], "recruitment_blocked")

            terminals = [r for r in rows if r.get("type") == "terminal"]
            self.assertTrue(terminals)
            self.assertEqual(terminals[-1]["reason"], "budget_interrupted")
            self.assertEqual(terminals[-1]["code"], "strategy_no_progress")


if __name__ == "__main__":
    unittest.main()
