"""Strategy-mode budget and provider failures at the real driver boundary."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest

from .test_strategy_routine_stack3 import (
    BLOCKED_POLICY,
    DRIVER,
    ROOT,
    prepare,
    records,
)


def _write_backend(path: Path, *, mode: str) -> None:
    """Write a provider-free command backend with durable physical evidence."""
    path.write_text(textwrap.dedent(f"""
        import json, os, sys
        from pathlib import Path

        context = json.loads(Path(os.environ['NORRUST_REQUEST_CONTEXT_FILE']).read_text())
        root = Path(context['game_log']).parent
        counter = root / 'backend-calls.txt'
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        if {mode!r} == 'provider_error':
            print('simulated provider failure', file=sys.stderr)
            raise SystemExit(1)

        sidecar = root / 'usage.ndjson'
        call_id = context['conversation_id'] + ':offline:' + str(count)
        base = {{'game_id': context['conversation_id'], 'call_id': call_id,
                'request_id': context['harness_request_id'],
                'transport': 'offline_fixture', 'provider': 'offline',
                'call_role': 'player', 'status': 'dispatched',
                'record_kind': 'dispatch'}}
        final = dict(base, status='completed', record_kind='final',
                     input_tokens=200, output_tokens=100, total_tokens=300)
        with sidecar.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(base) + '\\n')
            stream.write(json.dumps(final) + '\\n')
        response = {{'kind': 'set_policy', 'policy': {BLOCKED_POLICY!r}}}
        print(json.dumps({{'text': json.dumps(response, separators=(',', ':')),
                          'usage': {{'input_tokens': 200, 'output_tokens': 100,
                                     'total_tokens': 300}}}}))
    """).lstrip(), encoding='utf-8')


def _launch(log: Path, checkpoint: Path, backend: Path, *, cap: int | None = None,
            env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    envelope = json.loads(checkpoint.read_text())
    command = [sys.executable, '-m', 'tools.llm_client', '--driver', str(DRIVER),
               '--scenario', str(envelope['scenario']), '--faction0', str(envelope['faction0']),
               '--faction1', str(envelope['faction1']), '--gold', str(envelope['starting_gold']),
               '--seed', str(envelope['seed']), '--llm-side', str(envelope['llm_side']),
               '--max-turns', '1', '--decision-mode', 'strategy', '--log', str(log),
               '--model-command', shlex.join([sys.executable, str(backend)]),
               '--player-model', 'offline-fixture', '--query-budget-seconds', '20',
               '--turn-timeout', '45', '--model-timeout', '10',
               '--resume-checkpoint', str(checkpoint)]
    if cap is not None:
        command += ['--max-game-total-tokens', str(cap)]
    return subprocess.run(command, cwd=ROOT, env=env, text=True,
                          capture_output=True, timeout=70)


@unittest.skipUnless(DRIVER.is_file(), 'build greedy_driver before real-driver tests')
class StrategyBudgetBoundaryTests(unittest.TestCase):
    def test_pre_dispatch_game_cap_writes_terminal_and_stops_backend(self):
        """A measured first response blocks the next strategy request durably."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, 'blocked_objective.json', [], accepted=0, maximum=3)
            _write_backend(backend, mode='budget')
            log = root / 'budget.ndjson'
            result = _launch(log, checkpoint, backend, cap=300)

            self.assertEqual(result.returncode, 3, result.stderr + '\\n' +
                             (log.read_text() if log.exists() else ''))
            rows = records(log)
            terminal = [row for row in rows
                        if row.get('type') in {'terminal', 'model_error'}][-1]
            self.assertEqual(terminal['terminal_class'], 'budget_interrupted')
            self.assertEqual(terminal['code'], 'max_game_total_tokens_exhausted')
            self.assertIsNone(terminal.get('winner'))
            self.assertEqual(terminal['cumulative_game_total_tokens'], 300)
            self.assertTrue(any(row.get('type') == 'budget_interrupted'
                                and row.get('code') == 'max_game_total_tokens_exhausted'
                                for row in rows))
            self.assertEqual((root / 'backend-calls.txt').read_text(), '1')
            requests = [row for row in rows if row.get('type') == 'model_request']
            self.assertEqual([row.get('status') for row in requests], ['completed', 'failed'])
            self.assertIn('max_game_total_tokens_exhausted', requests[-1].get('error', ''))
            self.assertTrue(any(row.get('type') == 'policy_installed'
                                and row.get('source_kind') == 'model' for row in rows))
            self.assertTrue(any(row.get('type') == 'routine_exception'
                                and row.get('reason') == 'recruitment_blocked' for row in rows))
            self.assertTrue(requests[0].get('side_turn_id'))
            self.assertEqual(requests[0].get('side_turn_id'), requests[1].get('side_turn_id'))
            usage = [json.loads(line) for line in (root / 'usage.ndjson').read_text().splitlines()]
            self.assertEqual(sum(row.get('record_kind') == 'final' for row in usage), 1)
            self.assertEqual(usage[-1]['total_tokens'], 300)
            self.assertNotIn('Traceback', result.stderr)

    def test_strategy_provider_failure_is_typed_and_durable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(
                root, 'contact.json', [], accepted=0, maximum=3)
            _write_backend(backend, mode='provider_error')
            log = root / 'provider-error.ndjson'
            result = _launch(log, checkpoint, backend)

            self.assertEqual(result.returncode, 1, result.stderr + '\\n' +
                             (log.read_text() if log.exists() else ''))
            rows = records(log)
            terminal = [row for row in rows
                        if row.get('type') in {'terminal', 'model_error'}][-1]
            self.assertEqual(terminal['terminal_class'], 'infrastructure')
            self.assertEqual(terminal['code'], 'model_backend_failure')
            self.assertIsNone(terminal.get('winner'))
            self.assertTrue(any(row.get('type') == 'model_error'
                                and row.get('code') == 'model_backend_failure'
                                for row in rows))
            self.assertEqual((root / 'backend-calls.txt').read_text(), '2')
            self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
