"""Real-driver checks for the initial Stack 3 opening menu."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
import shutil

from .test_strategy_routine_stack2 import engine_events as quiet_engine_events
from .test_strategy_routine_stack2 import driver_states as quiet_driver_states
from .test_strategy_routine_stack2 import launch as quiet_launch
from .test_strategy_routine_stack2 import prepare as quiet_prepare


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = Path(os.environ.get(
    "NORRUST_OPENING_ARTIFACT_ROOT",
    ROOT / "tmp/decision-support-completion/openings"))
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def engine_events(records: list[dict]) -> list[dict]:
    result: list[dict] = []
    for record in records:
        line = record.get("line")
        if record.get("type") == "driver" and isinstance(line, dict) and line.get("type") == "events":
            result.extend(line.get("events", []))
    return result


def backend_script(path: Path, choice: str, prompt_log: Path) -> None:
    path.write_text(textwrap.dedent(f"""
        import json, os, sys
        from pathlib import Path
        prompt = sys.stdin.read()
        log = Path({str(prompt_log)!r})
        if not log.exists():
            log.write_text(json.dumps({{'bytes': len(prompt.encode()), 'prompt': prompt}}), encoding='utf-8')
        if 'OPENING_POLICY_SUGGESTIONS_BEGIN' in prompt:
            lines = prompt.splitlines()
            choice = {choice!r}
            label = next(index for index, line in enumerate(lines) if line.startswith(choice + ':'))
            response_line = next(line for line in lines[label + 1:] if 'response=' in line)
            response = json.loads(response_line.split('response=', 1)[1])
        else:
            response = {{'kind': 'finish_turn'}}
        print(json.dumps({{'text': json.dumps(response, separators=(',', ':'))}}))
    """).lstrip(), encoding="utf-8")


def seed_command(log: Path, backend: Path, *, resume_log: bool = False) -> list[str]:
    command = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER), "--scenario", "big_battle_6",
        "--faction0", "undead", "--faction1", "undead", "--gold", "300",
        "--seed", "2038", "--llm-side", "0", "--max-turns", "1",
        "--decision-mode", "strategy", "--log", str(log),
        "--model-command", f"{sys.executable} {backend}",
        "--query-budget-seconds", "60", "--turn-timeout", "120",
        "--model-timeout", "10", "--max-model-calls-per-turn", "4",
    ]
    command += ["--resume-log", str(log)] if resume_log else []
    return command


class OpeningPolicyDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DRIVER.is_file():
            raise AssertionError(f"Build the actual integration driver before running acceptance: {DRIVER}")
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    def test_seed2038_initial_prompt_selects_each_displayed_policy(self) -> None:
        for choice, expected_cost, expected_scouts in (
            ("Expansion", 260, 2), ("Concentration", 266, 1)
        ):
            with tempfile.TemporaryDirectory(prefix=f"driver-{choice.lower()}-", dir=ARTIFACT_ROOT) as temp:
                root = Path(temp)
                backend = root / "backend.py"
                prompt_path = root / "initial-prompt.json"
                log_path = root / "run.ndjson"
                backend_script(backend, choice, prompt_path)
                result = subprocess.run(seed_command(log_path, backend), cwd=ROOT, text=True,
                                        capture_output=True, timeout=180)
                self.assertEqual(result.returncode, 0,
                                 result.stderr + "\n" + (log_path.read_text()[-12000:] if log_path.exists() else ""))
                records = rows(log_path)
                prompt = json.loads(prompt_path.read_text(encoding="utf-8"))
                menu = prompt["prompt"].split("OPENING_POLICY_SUGGESTIONS_BEGIN", 1)[1]
                menu = "OPENING_POLICY_SUGGESTIONS_BEGIN" + menu.split(
                    "OPENING_POLICY_SUGGESTIONS_END", 1)[0] + "OPENING_POLICY_SUGGESTIONS_END"
                self.assertLessEqual(len(menu.encode()), 4096)
                requests = [record for record in records if record.get("type") == "model_request"]
                self.assertGreaterEqual(len(requests), 1)
                self.assertIn("OPENING_POLICY_SUGGESTIONS_BEGIN", requests[0]["prompt"])
                self.assertTrue(all("OPENING_POLICY_SUGGESTIONS_BEGIN" not in record["prompt"]
                                    for record in requests[1:]))
                installed = [record for record in records if record.get("type") == "policy_installed"]
                self.assertEqual(len(installed), 1)
                self.assertEqual(installed[0]["source_kind"], "model")
                self.assertFalse(any(record.get("type") in {
                    "model_error", "strategy_repair", "strategy_response_rejected",
                } for record in records))
                policy = installed[0]["policy"]
                cost = sum(
                    {"Vampire Bat": 13, "Ghost": 19, "Skeleton": 15}[item["def_id"]] * item["count"]
                    for item in policy["recruits"]
                )
                self.assertEqual(cost, expected_cost)
                self.assertEqual(sum(item["count"] for item in policy["recruits"]), 16)
                self.assertEqual(policy["scouts"], [])
                events = engine_events(records)
                recruits = [event for event in events if event.get("kind") == "recruit"]
                # Castle placement may leave the final queue entries pending
                # on this one-turn boundary (Concentration commits 14); the
                # policy itself is still a complete finite 16-unit request.
                self.assertGreaterEqual(len(recruits), 6)
                self.assertEqual(len({event.get("unit") for event in recruits}), len(recruits))
                self.assertEqual(sum(event.get("def_id") == "Vampire Bat" for event in recruits), expected_scouts)
                self.assertTrue(any(event.get("kind") == "move" and event.get("source") == "routine"
                                    and event.get("to") == {"col": 6, "row": 6}
                                    for event in events))

    def test_quiet_clone_runs_both_openings_through_turn_four(self) -> None:
        """Exercise committed recruits, village ownership, rally, and no re-install."""
        for fixture_name in ("expansion", "concentration"):
            with self.subTest(fixture_name=fixture_name):
                with tempfile.TemporaryDirectory(prefix=f"quiet-{fixture_name}-", dir=ARTIFACT_ROOT) as temp:
                    root = Path(temp)
                    fixture = json.loads((ROOT / "tools/fixtures/strategy_openings" /
                                          f"{fixture_name}.json").read_text())
                    policy = fixture["response"]["policy"]
                    checkpoint, policy_file, backend, prompts = quiet_prepare(root, policy)
                    counter = root / "backend-count"
                    backend.write_text(textwrap.dedent(f"""
                        import json
                        from pathlib import Path
                        count = Path({str(counter)!r})
                        calls = int(count.read_text()) if count.exists() else 0
                        count.write_text(str(calls + 1))
                        response = {{'kind': 'set_policy', 'policy': json.loads(Path({str(policy_file)!r}).read_text())}}
                        if calls:
                            response = {{'kind': 'finish_turn'}}
                        print(json.dumps({{'text': json.dumps(response, separators=(',', ':'))}}))
                    """).lstrip())
                    log = root / "quiet.ndjson"
                    result = quiet_launch(root, log, checkpoint, policy_file, backend, turns=4)
                    self.assertEqual(result.returncode, 0,
                                     result.stderr + "\n" + (log.read_text()[-12000:] if log.exists() else ""))
                    records = rows(log)
                    self.assertEqual(sum(record.get("type") == "policy_installed" for record in records), 1)
                    events = quiet_engine_events(records)
                    recruits = [event for event in events if event.get("kind") == "recruit"]
                    self.assertGreaterEqual(len(recruits), 6)
                    self.assertEqual(len({event.get("unit") for event in recruits}), len(recruits))
                    states = quiet_driver_states(records)
                    self.assertTrue(any(
                        state.get("side_turns", 99) <= 3
                        and sum(unit.get("faction") == 0 and unit.get("id") != 1
                                for unit in state.get("units", [])) >= 6
                        for state in states))
                    self.assertTrue(any(event.get("kind") == "move" and event.get("source") == "routine"
                                        and event.get("to") == {"col": 6, "row": 6}
                                        for event in events))
                    villages = {(event.get("col"), event.get("row")) for event in events
                                if event.get("kind") == "village" and event.get("owner") == 0}
                    expected_villages = {(2, 4), (5, 3)} if fixture_name == "expansion" else {(5, 3)}
                    self.assertTrue(expected_villages <= villages)
                    self.assertTrue(any(state.get("side_turns", 99) <= 4 for state in states))

    def test_displayed_expansion_resumes_from_first_committed_recruit(self) -> None:
        """A checkpoint resume preserves the opening installation and IDs."""
        with tempfile.TemporaryDirectory(prefix="resume-expansion-", dir=ARTIFACT_ROOT) as temp:
            root = Path(temp)
            backend = root / "backend.py"
            prompt_path = root / "initial-prompt.json"
            control_log = root / "control.ndjson"
            backend_script(backend, "Expansion", prompt_path)
            initial = subprocess.run(seed_command(control_log, backend), cwd=ROOT, text=True,
                                     capture_output=True, timeout=180)
            self.assertEqual(initial.returncode, 0,
                             initial.stderr + "\n" + control_log.read_text()[-12000:])
            control = rows(control_log)
            first_commit = next(index for index, record in enumerate(control)
                                if record.get("type") == "routine_progress_committed"
                                and any(effect.get("kind") == "recruited"
                                        for effect in record.get("progress_update", {}).get("effects", [])))
            crash_log = root / "resumed.ndjson"
            crash_log.write_text("\n".join(json.dumps(record) for record in control[:first_commit + 1]) + "\n")
            source_ckpt = control_log.with_suffix(".ckpt")
            target_ckpt = crash_log.with_suffix(".ckpt")
            shutil.copytree(source_ckpt, target_ckpt)
            referenced = {Path(record["path"]).name for record in control[:first_commit + 1]
                          if record.get("type") == "checkpoint_ref"}
            for saved in target_ckpt.iterdir():
                if saved.name not in referenced:
                    saved.unlink()
            resumed = subprocess.run(seed_command(crash_log, backend, resume_log=True), cwd=ROOT,
                                     text=True, capture_output=True, timeout=180)
            self.assertEqual(resumed.returncode, 0,
                             resumed.stderr + "\n" + crash_log.read_text()[-12000:])
            actual = rows(crash_log)
            self.assertEqual(sum(record.get("type") == "policy_installed" for record in actual), 1)
            expected_recruits = [event for event in engine_events(control) if event.get("kind") == "recruit"]
            actual_recruits = [event for event in engine_events(actual) if event.get("kind") == "recruit"]
            self.assertEqual(len(actual_recruits), len(expected_recruits))
            self.assertEqual(len({event.get("unit") for event in actual_recruits}), len(actual_recruits))
            self.assertEqual(
                sorted(event.get("unit") for event in actual_recruits),
                sorted(event.get("unit") for event in expected_recruits),
            )
            resumed_records = actual[first_commit + 1:]
            resumed_requests = [record for record in resumed_records if record.get("type") == "model_request"]
            self.assertTrue(all("OPENING_POLICY_SUGGESTIONS_BEGIN" not in record.get("prompt", "")
                                for record in resumed_requests))

    def test_displayed_menu_allows_a_custom_policy_override(self) -> None:
        """The menu is guidance: a valid authored policy remains executable."""
        with tempfile.TemporaryDirectory(prefix="custom-opening-", dir=ARTIFACT_ROOT) as temp:
            root = Path(temp)
            backend = root / "backend.py"
            prompt_path = root / "initial-prompt.json"
            log_path = root / "run.ndjson"
            backend_script(backend, "Expansion", prompt_path)
            backend.write_text(textwrap.dedent(f"""
                import json, sys
                from pathlib import Path
                prompt = sys.stdin.read()
                if 'OPENING_POLICY_SUGGESTIONS_BEGIN' not in prompt:
                    response = {{'kind': 'finish_turn'}}
                else:
                    response = {{'kind': 'set_policy', 'policy': {{
                        'reserve_gold': 0,
                        'recruits': [{{'def_id': 'Walking Corpse', 'count': 1, 'role': 'army'}}],
                        'scouts': [], 'villages': [], 'rally': None, 'holds': []
                    }}}}
                print(json.dumps({{'text': json.dumps(response, separators=(',', ':'))}}))
            """).lstrip())
            result = subprocess.run(seed_command(log_path, backend), cwd=ROOT, text=True,
                                    capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0,
                             result.stderr + "\n" + log_path.read_text()[-12000:])
            records = rows(log_path)
            installed = [record for record in records if record.get("type") == "policy_installed"]
            self.assertEqual(len(installed), 1)
            self.assertEqual(installed[0]["policy"]["recruits"],
                             [{"def_id": "Walking Corpse", "count": 1, "role": "army"}])
            self.assertTrue(any(event.get("kind") == "recruit" and event.get("def_id") == "Walking Corpse"
                                for event in engine_events(records)))
            self.assertFalse(any(record.get("type") in {
                "model_error", "strategy_repair", "strategy_response_rejected",
            } for record in records))


if __name__ == "__main__":
    unittest.main()
