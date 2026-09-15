"""Accept canonical and redundant strategy finish replies without repair."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest

from .routine_policy import CANONICAL_FINISH_TURN_JSON, NO_SWEEP_FINISH
from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, events, forwarded, launch, prepare, records,
)


def _write_usage_backend(path: Path, responses: list[dict], *, tokens: int = 300) -> None:
    path.write_text(textwrap.dedent(f"""
        import json, os, sys
        from pathlib import Path
        context = json.loads(Path(os.environ['NORRUST_REQUEST_CONTEXT_FILE']).read_text())
        root = Path(context['game_log']).parent
        counter = root / 'backend-calls.txt'
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        sidecar = root / 'usage.ndjson'
        call_id = context['conversation_id'] + ':offline:' + str(count)
        base = {{'game_id': context['conversation_id'], 'call_id': call_id,
                'request_id': context['harness_request_id'],
                'transport': 'offline_fixture', 'provider': 'offline',
                'call_role': 'player', 'status': 'dispatched',
                'record_kind': 'dispatch'}}
        final = dict(base, status='completed', record_kind='final',
                     input_tokens={tokens // 2}, output_tokens={tokens - tokens // 2},
                     total_tokens={tokens})
        with sidecar.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(base) + '\\n')
            stream.write(json.dumps(final) + '\\n')
        values = {responses!r}
        response = values[min(count - 1, len(values) - 1)]
        print(json.dumps({{'text': json.dumps(response, separators=(',', ':')),
                          'usage': {{'input_tokens': {tokens // 2},
                                     'output_tokens': {tokens - tokens // 2},
                                     'total_tokens': {tokens}}}}}))
    """).lstrip(), encoding="utf-8")


def _finish_stats(rows: list[dict]) -> tuple[int, int, int, int]:
    model_requests = [row for row in rows
                      if row.get("type") == "model_request" and row.get("status") == "completed"]
    repairs = [row for row in rows if row.get("type") == "strategy_response_repair"]
    llm_finishes = [
        row for row in forwarded(rows)
        if row.get("source") == "llm"
        and any(order.get("action") == "FinishWithGreedy" for order in row.get("orders", []))
    ]
    greedy_moves = [
        event for event in events(rows)
        if event.get("kind") in {"move", "attack", "recruit"} and event.get("source") == "greedy"
    ]
    return len(model_requests), len(repairs), len(llm_finishes), len(greedy_moves)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before real-driver tests")
class StrategyFinishNormalizationTests(unittest.TestCase):
    def _run_finish(self, root: Path, response: dict, *, cap: int | None = None,
                    turns: int = 1, resume_log: Path | None = None):
        if resume_log is None:
            checkpoint, _, backend, _ = prepare(root, "contact.json", [response])
            _write_usage_backend(backend, [response])
            log = root / "finish.ndjson"
        else:
            checkpoint = next(root.glob("checkpoint-*.json"))
            backend = root / "backend.py"
            log = resume_log
        envelope = json.loads(checkpoint.read_text())
        command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                   "--scenario", str(envelope["scenario"]), "--faction0", str(envelope["faction0"]),
                   "--faction1", str(envelope["faction1"]), "--gold", str(envelope["starting_gold"]),
                   "--seed", str(envelope["seed"]), "--llm-side", str(envelope["llm_side"]),
                   "--max-turns", str(turns), "--decision-mode", "strategy", "--log", str(log),
                   "--model-command", shlex.join([sys.executable, str(backend)]),
                   "--player-model", "offline-fixture", "--query-budget-seconds", "20",
                   "--turn-timeout", "45", "--model-timeout", "10"]
        if resume_log is None:
            command += ["--resume-checkpoint", str(checkpoint)]
        else:
            command += ["--resume-log", str(resume_log)]
        if cap is not None:
            command += ["--max-game-total-tokens", str(cap)]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=70)
        call_count = ((root / "backend-calls.txt").read_text()
                      if (root / "backend-calls.txt").exists() else None)
        usage = []
        sidecar = root / "usage.ndjson"
        if sidecar.exists():
            usage = [json.loads(line) for line in sidecar.read_text().splitlines() if line.strip()]
        return result, records(log) if log.exists() else [], call_count, usage, log

    def test_canonical_and_redundant_finish_end_turn_without_repair(self):
        for response, expect_normalized in (
            ({"kind": "finish_turn"}, False),
            ({"kind": "finish_turn", "finish_turn": True}, True),
        ):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as td:
                result, rows, call_count, usage, _ = self._run_finish(Path(td), response)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(call_count, "1")
                requests, repairs, llm_finishes, greedy = _finish_stats(rows)
                self.assertEqual(requests, 1)
                self.assertEqual(repairs, 0)
                self.assertEqual(llm_finishes, 1)
                self.assertEqual(greedy, 0)
                self.assertEqual(forwarded(rows)[0]["orders"], [NO_SWEEP_FINISH])
                normalized = [row for row in rows if row.get("type") == "strategy_response_normalized"]
                if expect_normalized:
                    self.assertEqual(len(normalized), 1)
                    self.assertEqual(normalized[0]["request_id"], [
                        row["request_id"] for row in rows
                        if row.get("type") == "model_request" and row.get("status") == "completed"
                    ][-1])
                    self.assertEqual(normalized[0]["to"], {"kind": "finish_turn"})
                else:
                    self.assertFalse(normalized)
                self.assertEqual(sum(row.get("record_kind") == "final" for row in usage), 1)
                prompts = [row.get("prompt", "") for row in rows if row.get("type") == "model_request"]
                self.assertTrue(any(CANONICAL_FINISH_TURN_JSON in prompt for prompt in prompts))
                self.assertFalse(any(row.get("type") == "strategy_response_repair" for row in rows))

    def test_invalid_finish_shapes_repair_with_canonical_object(self):
        invalid = {"kind": "finish_turn", "finish_turn": False}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            responses = [invalid, {"kind": "finish_turn"}]
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", responses)
            log = root / "invalid-finish.ndjson"
            result = launch(root, log, checkpoint, backend)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = records(log)
            self.assertEqual(sum(row.get("type") == "strategy_response_repair" for row in rows), 1)
            prompts = [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines()]
            self.assertGreaterEqual(len(prompts), 2)
            self.assertIn(CANONICAL_FINISH_TURN_JSON, prompts[1])
            self.assertFalse(any(row.get("type") == "strategy_response_normalized" for row in rows))

    def test_in_flight_overshoot_accepts_valid_finish_and_blocks_next_paid_call(self):
        with tempfile.TemporaryDirectory() as td:
            result, rows, call_count, usage, _ = self._run_finish(
                Path(td), {"kind": "finish_turn", "finish_turn": True}, cap=300, turns=3)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertEqual(call_count, "1")
        requests, repairs, llm_finishes, _greedy = _finish_stats(rows)
        self.assertEqual(requests, 1)
        self.assertEqual(repairs, 0)
        self.assertEqual(llm_finishes, 1)
        self.assertEqual(
            [row for row in forwarded(rows) if row.get("source") == "llm"][0]["orders"],
            [NO_SWEEP_FINISH])
        terminal = [row for row in rows if row.get("type") in {"terminal", "model_error"}][-1]
        self.assertEqual(terminal["code"], "max_game_total_tokens_exhausted")
        self.assertEqual(sum(row.get("record_kind") == "final" for row in usage), 1)
        self.assertTrue(any(row.get("type") == "strategy_response_normalized" for row in rows))

    def test_resume_after_commit_does_not_finish_or_charge_twice(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first, rows, call_count, usage, log = self._run_finish(
                root, {"kind": "finish_turn", "finish_turn": True})
            self.assertEqual(first.returncode, 0, first.stderr)
            lines = [line for line in log.read_text().splitlines()
                     if '"type": "terminal"' not in line and '"type": "budget_interrupted"' not in line]
            log.write_text("\n".join(lines) + "\n")
            resumed, resumed_rows, _, usage, _ = self._run_finish(
                root, {"kind": "finish_turn", "finish_turn": True}, resume_log=log)
            _requests, repairs, llm_finishes, _greedy = _finish_stats(resumed_rows)
            self.assertEqual(llm_finishes, 1, resumed.stderr)
            self.assertEqual(repairs, 0)
            self.assertEqual((root / "backend-calls.txt").read_text(), "1")
            self.assertEqual(sum(row.get("record_kind") == "final" for row in usage), 1)
            self.assertEqual(sum(row.get("type") == "strategy_response_normalized"
                                 for row in resumed_rows), 1)


if __name__ == "__main__":
    unittest.main()
