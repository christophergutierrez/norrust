"""Stack 3 strategy contract checks against the real driver.

The model is a tiny scripted subprocess.  The engine, query budget, action
validation, checkpoints, and history importer remain real.  These tests are
kept separate from Stack 2 so a Stack 3 runtime can be integrated and gated
without changing the older fixture coverage.
"""
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
BLOCKED_POLICY = {
    "reserve_gold": 300,
    "recruits": [{"def_id": "Ghost", "count": 1, "role": "army"}],
    "scouts": [], "villages": [], "rally": None, "holds": [],
}
REPLACEMENT_POLICY = {
    "reserve_gold": 0,
    "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
    "scouts": [], "villages": [], "rally": {"col": 20, "row": 0}, "holds": [],
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


def query_mutating_driver(root: Path, *, missing_threat: bool = False,
                          stale_inspection: bool = False) -> Path:
    """Return a transparent driver proxy that only mutates query replies.

    It never plans or executes actions.  This is used for unavailable/stale
    transport predicates while all state transitions remain in the real Rust
    driver process.
    """
    proxy = root / "driver_proxy.py"
    proxy.write_text(textwrap.dedent(f"""
        #!/usr/bin/env python3
        import json, subprocess, sys, threading
        child = subprocess.Popen([{str(DRIVER)!r}] + sys.argv[1:], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def forward_input():
            for line in sys.stdin:
                child.stdin.write(line)
                child.stdin.flush()
        threading.Thread(target=forward_input, daemon=True).start()
        for raw in child.stdout:
            try:
                row = json.loads(raw)
                what = row.get('what')
                if {bool(missing_threat)!r} and what == 'routine_next' and row.get('ok'):
                    body = row.get('body')
                    if isinstance(body, dict):
                        evidence = body.get('evidence')
                        if isinstance(evidence, dict):
                            evidence.pop('threats', None)
                            evidence['threats'] = 'unknown'
                if {bool(stale_inspection)!r} and what in {{'inspect_target', 'inspect_targets', 'inspect_hex'}} and row.get('ok'):
                    row['state_revision'] = -1
                print(json.dumps(row, separators=(',', ':')), flush=True)
            except Exception:
                print(raw, end='', flush=True)
    """).lstrip(), encoding="utf-8")
    proxy.chmod(0o755)
    return proxy


def assert_success(test: unittest.TestCase, result: subprocess.CompletedProcess[str], log: Path) -> None:
    test.assertEqual(result.returncode, 0,
                     result.stderr + "\n" + (log.read_text()[-16000:] if log.exists() else ""))


def prompts(path: Path) -> list[str]:
    return [row["prompt"] for row in records(path)]


@unittest.skipUnless(DRIVER.is_file(), "Build the actual integration driver; skipped is not acceptance")
class StrategyRoutineStack3Tests(unittest.TestCase):

    def test_contact_attack_and_finish_is_one_ordinary_batch(self):
        responses = [policy(), act(finish=True)]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "contact.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            self.assertEqual(len(prompts(prompt_log)), 2)
            attack_batches = [row for row in forwarded(rows)
                              if any(order.get("action") == "Attack" for order in row.get("orders", []))]
            self.assertEqual(len(attack_batches), 1)
            batch = attack_batches[0]
            self.assertEqual(batch.get("source"), "llm")
            self.assertEqual(batch["orders"][0], ATTACK)
            self.assertEqual(batch["orders"][-1].get("action"), "FinishWithGreedy")
            attack_events = [event for event in events(rows) if event.get("kind") == "attack"]
            self.assertEqual(len(attack_events), 1)
            self.assertEqual(attack_events[0].get("source"), "llm")
            self.assertFalse(any(row.get("batch_id") == batch.get("batch_id")
                                 for row in rows if row.get("type") == "routine_progress_committed"))
            self.assertTrue(any(row.get("type") == "routine_exception"
                                and row.get("reason") == "contact" for row in rows))
            self.assertTrue(batch.get("request_id"))
            self.assertTrue(batch.get("side_turn_id"))
            self.assertTrue(any(row.get("type") == "checkpoint_ref"
                                and row.get("state_revision") == batch.get("state_revision")
                                for row in rows))
            db = root / "history.sqlite"
            conn = open_history(db)
            try:
                game_id = import_game(conn, log)
                counts = {table: conn.execute(
                    f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)).fetchone()[0]
                          for table in ("events", "side_turns", "model_requests", "action_batches")}
                import_game(conn, log)
                self.assertEqual(counts, {table: conn.execute(
                    f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)).fetchone()[0]
                                          for table in counts})
            finally:
                conn.close()

    def test_ordinary_act_false_is_accepted_without_hidden_finish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, "contact.json", [policy(), act(finish=False), {"kind": "finish_turn"}])
            log = root / "ordinary-act.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            batches = [row for row in forwarded(rows)
                       if any(order.get("action") == "Attack" for order in row.get("orders", []))]
            self.assertEqual(len(batches), 1)
            self.assertEqual([order.get("action") for order in batches[0]["orders"]], ["Attack"])
            self.assertEqual(sum(event.get("kind") == "attack" for event in events(rows)), 1)
            self.assertFalse(any(order.get("action") == "FinishWithGreedy"
                                 for order in batches[0]["orders"]))

    def test_final_only_requires_finish_and_allows_one_repair(self):
        bad = {"kind": "act", "actions": [copy.deepcopy(ATTACK)], "finish_turn": False}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(root, "contact.json",
                                                [policy(), bad, act(finish=True)],
                                                accepted=3, maximum=3)
            log = root / "final-only.ndjson"
            result = launch(root, log, checkpoint, backend, maximum=3)
            assert_success(self, result, log)
            rows = records(log)
            batches = [row for row in forwarded(rows)
                       if any(order.get("action") == "Attack" for order in row.get("orders", []))]
            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0]["orders"][-1].get("action"), "FinishWithGreedy")
            repairs = [row for row in rows if row.get("type") in {"action_repair", "strategy_response_repair"}]
            self.assertEqual(len(repairs), 1)
            self.assertEqual(sum(event.get("kind") == "attack" for event in events(rows)), 1)

    def test_final_only_nonlethal_army_exposure_still_asks_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "contact.json", [policy(), {"kind": "finish_turn"}],
                accepted=3, maximum=3)
            data = json.loads(checkpoint.read_text())
            # Recruiters are distant and safe; this soldier cannot attack
            # again, but the adjacent enemy can attack it on its next activation.
            soldier = next(u for u in data["save_state"]["units"] if u["id"] == 3)
            soldier.update(moved=True, attacked=True)
            encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
            checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
            checkpoint.write_bytes(encoded)
            log = root / "final-only-army-exposure.ndjson"
            result = launch(root, log, checkpoint, backend, maximum=3)
            assert_success(self, result, log)
            rows = records(log)
            self.assertEqual(len(prompts(prompt_log)), 2)
            self.assertTrue(any(r.get("type") == "routine_exception"
                                and r.get("reason") == "contact" for r in rows))
            self.assertFalse(any(e.get("kind") == "attack" and e.get("source") == "llm"
                                 for e in events(rows)))
            self.assertTrue(all(r.get("source") == "llm" and r.get("request_id")
                                for r in forwarded(rows)))

    def test_explicit_finish_and_resign_are_forwarded(self):
        for response, expected in (({"kind": "finish_turn"}, "FinishWithGreedy"),
                                   ({"kind": "resign"}, "Resign")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                checkpoint, _, backend, _ = prepare(root, "contact.json",
                                                    [policy(), response])
                log = root / (expected + ".ndjson")
                result = launch(root, log, checkpoint, backend)
                assert_success(self, result, log)
                rows = records(log)
                self.assertTrue(any(order.get("action") == expected
                                    for row in forwarded(rows) for order in row.get("orders", [])))

    def test_exception_fixtures_expose_promotion_danger_and_reserve(self):
        cases = (("promotion.json", EMPTY_POLICY, "promotion_pending", "promotion"),
                 ("recruiter_danger.json", EMPTY_POLICY, "contact", "recruiter"),
                 ("blocked_objective.json", BLOCKED_POLICY, "recruitment_blocked", "reserve"))
        for fixture, installed, reason, label in cases:
            with self.subTest(fixture=fixture):
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    response = ({"kind": "act", "actions": [{"action": "Advance", "unit_id": 13, "target_index": 0}], "finish_turn": True}
                                if fixture == "promotion.json" else {"kind": "finish_turn"})
                    checkpoint, _, backend, prompt_log = prepare(
                        root, fixture, [policy(value=installed), response])
                    log = root / (label + ".ndjson")
                    result = launch(root, log, checkpoint, backend)
                    assert_success(self, result, log)
                    rows = records(log)
                    self.assertTrue(any(row.get("type") == "routine_exception"
                                        and row.get("reason") == reason for row in rows))
                    text = "\n".join(prompts(prompt_log)).lower()
                    if fixture == "promotion.json":
                        self.assertIn("13", text)
                    elif fixture == "recruiter_danger.json":
                        self.assertIn("recruiter", text)
                        state = [u for row in rows if row.get("type") == "driver"
                                 and row.get("line", {}).get("type") == "state"
                                 for u in row["line"].get("units", []) if u.get("id") == 1]
                        self.assertTrue(state)
                        self.assertEqual((state[-1]["col"], state[-1]["row"]), (2, 7))
                    else:
                        self.assertIn("reserve", text)
                        self.assertIn("gold", text)
                    self.assertFalse(any(event.get("kind") == "recruit" for event in events(rows)))

    def test_policy_replacement_drops_old_queue_and_keeps_installation_provenance(self):
        old = {"reserve_gold": 300,
               "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"},
                             {"def_id": "Ghost", "count": 1, "role": "army"}],
               "scouts": [], "villages": [], "rally": None, "holds": []}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(
                root, "blocked_objective.json",
                [policy(value=old), policy(value=REPLACEMENT_POLICY), {"kind": "finish_turn"}])
            log = root / "replacement.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            rows = records(log)
            installed = [row for row in rows if row.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 2)
            ids = [row.get("installation_id") for row in installed]
            self.assertEqual(len(set(ids)), 2)
            progress = [row for row in rows if row.get("type") == "routine_progress_committed"]
            self.assertTrue(all(row.get("installation_id") == ids[-1] for row in progress))
            self.assertGreaterEqual(len(prompts(prompt_log)), 2)
            self.assertTrue(any(row.get("type") == "routine_exception"
                                and row.get("reason") == "recruitment_blocked" for row in rows))

    def test_unchanged_set_policy_exception_is_capped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            responses = [policy(), policy(), policy(), policy(), policy(), policy()]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "unchanged.ndjson"
            result = launch(root, log, checkpoint, backend, max_calls=3)
            self.assertNotEqual(result.returncode, 0)
            rows = records(log)
            self.assertLessEqual(len(prompts(prompt_log)), 3)
            exceptions = [row for row in rows if row.get("type") == "routine_exception"]
            self.assertGreaterEqual(len(exceptions), 1)
            revisions = {row.get("state_revision") for row in exceptions}
            self.assertEqual(len(revisions), 1)
            terminal = [row for row in rows if row.get("type") == "terminal"]
            self.assertTrue(terminal)
            self.assertIn(terminal[-1].get("code"), {
                "model_calls_budget_exhausted", "strategy_no_progress",
                "model_response_budget_exhausted"})

    def test_strategy_prompt_is_compact_revision_pinned_and_has_no_annotations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", [policy(), act(finish=True)])
            log = root / "prompt.ndjson"
            result = launch(root, log, checkpoint, backend)
            assert_success(self, result, log)
            prompt_text = "\n".join(prompts(prompt_log))
            lowered = prompt_text.lower()
            for required in ("state_revision", "map", "gold", "threat", "live_state"):
                self.assertIn(required, lowered)
            # Contact is a real two-sided fixture: a dimensions-only map card
            # or friendly-only state card does not satisfy the contract.
            for fact in ("10,7", "11,7", "21,6", "id=2", "id=4",
                         "recruiter", "exposure", "skeleton"):
                self.assertIn(fact, lowered)
            for forbidden in ('"decisions"', "agenda", "citation", "annotation"):
                self.assertNotIn(forbidden, lowered)
            rows = records(log)
            self.assertFalse(any(row.get("type") == "decision_annotation" for row in rows))
            model_records = [row for row in rows if row.get("type") == "model_request"]
            self.assertEqual(len(model_records), len(prompts(prompt_log)))
            for row, prompt in zip(model_records, prompts(prompt_log)):
                self.assertEqual(row.get("prompt_bytes"), len(prompt.encode()))

    def test_missing_threat_reply_stays_unknown_and_does_not_auto_finish(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proxy = query_mutating_driver(root, missing_threat=True)
            checkpoint, _, backend, prompt_log = prepare(
                root, "contact.json", [policy(), {"kind": "finish_turn"}])
            log = root / "unknown-threat.ndjson"
            result = launch(root, log, checkpoint, backend, driver_path=proxy)
            # Before P removes the Stack 2 contact compatibility termination,
            # this is an intentional failing acceptance predicate.
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(any(row.get("type") == "routine_exception"
                                and row.get("reason") == "contact" for row in rows))
            prompt_text = "\n".join(prompts(prompt_log)).lower()
            self.assertIn("unknown", prompt_text)
            self.assertFalse(any(event.get("kind") in {"move", "recruit"}
                                 for event in events(rows)))

    def test_stale_inspection_clears_local_projection_before_plain_act(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proxy = query_mutating_driver(root, stale_inspection=True)
            responses = [policy(), {"tool": "inspect_target", "unit_id": 4,
                                    "purpose": "check current target"},
                         act(finish=False), {"kind": "finish_turn"}]
            checkpoint, _, backend, _ = prepare(root, "contact.json", responses)
            log = root / "stale-inspection.ndjson"
            result = launch(root, log, checkpoint, backend, driver_path=proxy)
            assert_success(self, result, log)
            rows = records(log)
            self.assertTrue(any(row.get("type") == "tool_result"
                                and row.get("tool") == "inspect_target" for row in rows))
            self.assertTrue(any("stale" in json.dumps(row).lower()
                                for row in rows if row.get("type") in {"tool_result", "repair", "model_request"}))
            # The prior inspection is not an action gate: after it is cleared,
            # this still-legal coordinate action is accepted exactly once.
            self.assertEqual(sum(event.get("kind") == "attack" for event in events(rows)), 1)

    def test_stale_routine_query_is_rejected_without_engine_mutation(self):
        """Exercise the real driver's revision-pinned read boundary.

        The client-side inspection cache test is owned by the Stack 3 runtime;
        this driver smoke check fixes the wire predicate and catches a stale
        response accidentally becoming an executable fact.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = json.loads((STACK3 / "contact.json").read_text())
            board = ROOT / "scenarios/big_battle_6/board.toml"
            data["board_path"] = str(board)
            data["save_state"]["board_path"] = str(board)
            encoded = json.dumps(data, separators=(",", ":")).encode()
            checkpoint = root / ("checkpoint-" + hashlib.sha256(encoded).hexdigest() + ".json")
            checkpoint.write_bytes(encoded)
            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "9211",
                 "--llm-side", "0", "--max-turns", "1", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)
            try:
                initial = json.loads(proc.stdout.readline())
                while initial.get("type") != "state":
                    initial = json.loads(proc.stdout.readline())
                self.assertEqual(initial.get("type"), "state")
                proc.stdin.write(json.dumps({"action": "Query", "what": "routine_next",
                                              "state_revision": initial["state_revision"] + 1,
                                              "policy": EMPTY_POLICY, "progress": {}}) + "\n")
                proc.stdin.flush()
                reply = json.loads(proc.stdout.readline())
                self.assertFalse(reply.get("ok"))
                self.assertEqual(reply.get("code"), "stale_state")
                self.assertEqual(reply.get("state_revision"), initial["state_revision"])
            finally:
                proc.kill()
                proc.wait(timeout=5)
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
