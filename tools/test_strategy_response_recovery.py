"""Strict strategy-response recovery against the real driver boundary."""
from __future__ import annotations

import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import unittest

from .llm_client import MAX_STRATEGY_RECOVERED_SUFFIX_BYTES, decode_strategy_response
from .test_strategy_routine_stack3 import (
    ATTACK, DRIVER, EMPTY_POLICY, ROOT, events, prepare, records,
)


def _write_backend(path: Path, responses: list[str], *, output_limit_first: bool = False) -> None:
    path.write_text(textwrap.dedent(f"""
        import json, os
        from pathlib import Path
        context = json.loads(Path(os.environ['NORRUST_REQUEST_CONTEXT_FILE']).read_text())
        root = Path(context['game_log']).parent
        counter = root / 'backend-calls.txt'
        count = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(count))
        if {output_limit_first!r} and count == 1:
            print(json.dumps({{'error': {{'code': 'output_limit',
                                          'output_limit': 131072,
                                          'call_id': 'fixture-output-limit'}}}}))
        else:
            values = {responses!r}
            index = count - 2 if {output_limit_first!r} else count - 1
            print(json.dumps({{'text': values[min(index, len(values) - 1)]}}))
    """).lstrip(), encoding='utf-8')


def _launch(log: Path, checkpoint: Path, backend: Path) -> subprocess.CompletedProcess[str]:
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
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                          timeout=70)


def _policy_text() -> str:
    return json.dumps({'kind': 'set_policy', 'policy': EMPTY_POLICY}, separators=(',', ':'))


def _act_text(*, suffix: str = '') -> str:
    response = {'kind': 'act', 'actions': [ATTACK], 'finish_turn': True}
    return json.dumps(response, separators=(',', ':')) + suffix


class StrategyResponseRecoveryUnitTests(unittest.TestCase):
    def test_only_bounded_plain_suffix_is_recovered(self):
        decoded, suffix = decode_strategy_response(_act_text(suffix='\nDone.'))
        self.assertEqual(decoded['kind'], 'act')
        self.assertEqual(suffix, 'Done.')
        self.assertIsNone(decode_strategy_response(_act_text())[1])
        bad = (
            _act_text(suffix='{"kind":"finish_turn"}'),
            _act_text(suffix='\n```text```'),
            _act_text(suffix='\ntrue'),
            _act_text(suffix='\n' + ('x' * (MAX_STRATEGY_RECOVERED_SUFFIX_BYTES + 1))),
            'preamble ' + _act_text(),
            '[{"kind":"act"}] trailing',
            '{"kind":"act"',
        )
        for value in bad:
            with self.subTest(value=value[-40:]), self.assertRaises(json.JSONDecodeError):
                decode_strategy_response(value)


@unittest.skipUnless(DRIVER.is_file(), 'build greedy_driver before real-driver tests')
class StrategyResponseRecoveryDriverTests(unittest.TestCase):
    def _run(self, response: str, *, output_limit_first: bool = False,
             responses_after: list[str] | None = None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, _, backend, _ = prepare(root, 'contact.json', [])
            values = [_policy_text(), response]
            if responses_after:
                values.extend(responses_after)
            _write_backend(backend, values, output_limit_first=output_limit_first)
            log = root / 'strategy.ndjson'
            result = _launch(log, checkpoint, backend)
            call_count = ((root / 'backend-calls.txt').read_text()
                          if (root / 'backend-calls.txt').exists() else None)
            return result, records(log), call_count

    def test_trailing_prose_executes_once_without_repair(self):
        result, rows, call_count = self._run(_act_text(suffix='\nI will now end this turn.'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(call_count, '2')
        self.assertEqual(sum(row.get('type') == 'strategy_response_recovered' for row in rows), 1)
        self.assertFalse(any(row.get('type') == 'strategy_response_repair' for row in rows))
        model = [row for row in rows if row.get('type') == 'model_request'
                 and row.get('status') == 'completed'][-1]
        recovery = [row for row in rows if row.get('type') == 'strategy_response_recovered'][-1]
        self.assertEqual(recovery['request_id'], model['request_id'])
        self.assertEqual(recovery['prompt_hash'], model['prompt_hash'])
        self.assertEqual(model['raw_output'], _act_text(suffix='\nI will now end this turn.'))
        attacks = [event for event in events(rows) if event.get('kind') == 'attack']
        self.assertEqual(len(attacks), 1)

    def test_clean_json_is_unchanged(self):
        result, rows, call_count = self._run(_act_text())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(call_count, '2')
        self.assertFalse(any(row.get('type') == 'strategy_response_recovered' for row in rows))
        self.assertFalse(any(row.get('type') == 'strategy_response_repair' for row in rows))

    def test_multiple_json_malformed_schema_and_illegal_actions_repair(self):
        cases = (
            _act_text(suffix=' {"kind":"finish_turn"}'),
            '{"kind":"act"',
            '{"kind":"act","actions":[],"finish_turn":false}',
            '{"kind":"act","actions":[{"action":"EndTurn"}],"finish_turn":false}',
        )
        for invalid in cases:
            with self.subTest(invalid=invalid):
                result, rows, call_count = self._run(
                    invalid, responses_after=['{"kind":"finish_turn"}'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(call_count, '3')
                self.assertFalse(any(row.get('type') == 'strategy_response_recovered' for row in rows))
                self.assertEqual(sum(row.get('type') == 'strategy_response_repair' for row in rows), 1)
                self.assertFalse(any(event.get('kind') == 'attack' for event in events(rows)))

    def test_recovered_objects_still_use_schema_and_engine_validation(self):
        cases = (
            '{"kind":"act","actions":[],"finish_turn":false}\ninvalid shape note',
            '{"kind":"act","actions":[{"action":"EndTurn"}],"finish_turn":false}\nillegal action note',
        )
        for invalid in cases:
            with self.subTest(invalid=invalid):
                result, rows, call_count = self._run(
                    invalid, responses_after=['{"kind":"finish_turn"}'])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(call_count, '3')
                self.assertEqual(sum(row.get('type') == 'strategy_response_recovered'
                                     for row in rows), 1)
                self.assertEqual(sum(row.get('type') == 'strategy_response_repair'
                                     for row in rows), 1)
                self.assertFalse(any(event.get('kind') in {'attack', 'move', 'recruit'}
                                     for event in events(rows)))

    def test_provider_output_limit_retry_is_not_json_recovery(self):
        result, rows, call_count = self._run(
            '{"kind":"finish_turn"}', output_limit_first=True,
            responses_after=['{"kind":"finish_turn"}'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(call_count, '3')
        self.assertFalse(any(row.get('type') == 'strategy_response_recovered' for row in rows))
        self.assertTrue(any(row.get('type') == 'model_output_limit' for row in rows))


if __name__ == '__main__':
    unittest.main()
