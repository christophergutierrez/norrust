"""Physical-call budget regressions through the real client and driver."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from .game_token_budget import measured_game_budget

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get('NORRUST_TEST_DRIVER', ROOT / 'norrust_core/target/debug/greedy_driver'))

BACKEND = '''import json, os, sys
from pathlib import Path
context = json.loads(Path(os.environ['NORRUST_REQUEST_CONTEXT_FILE']).read_text())
root = Path(context['game_log']).parent
counter = root / 'calls.txt'
n = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(n))
mode = sys.argv[1]
limit = context['output_limit']
usage = {'input_tokens': 200, 'output_tokens': 100, 'total_tokens': 300}
call_id = context['conversation_id'] + ':physical:' + str(n)
record = {'game_id': context['conversation_id'], 'call_id': call_id,
          'request_id': context['harness_request_id'], 'transport': 'offline_fixture',
          'provider': 'offline', 'status': 'dispatched', 'record_kind': 'dispatch'}
if mode != 'missing':
    with (root / 'usage.ndjson').open('a') as f:
        f.write(json.dumps(record) + '\\n')
        record.update(usage, status='completed', record_kind='final')
        f.write(json.dumps(record) + '\\n')
reply = {'text': json.dumps({'actions': [{'action':'EndTurn'}]}), 'usage': usage}
if mode == 'exhausted':
    reply['error'] = {'code':'output_limit', 'output_limit':limit, 'call_id':call_id}
if mode == 'crash' and n == 2:
    print('request_unknown: simulated provider failure', file=sys.stderr)
    sys.exit(1)
print(json.dumps(reply))
'''

class BudgetEvidenceTests(unittest.TestCase):
    def test_dispatch_final_duplicates_retry_and_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'usage.ndjson'
            base = {'game_id':'g', 'call_id':'a', 'request_id':'r',
                    'transport':'fireworks_chat_completions', 'status':'dispatched'}
            final = dict(base, status='failed', total_tokens=300)
            retry = dict(final, call_id='b', status='completed', total_tokens=400)
            p.write_text('\n'.join(map(json.dumps, [base, final, final, retry])))
            value = measured_game_budget(p, 'g', {'r'})
            self.assertEqual(value['cumulative_game_total_tokens'], 700)
            self.assertTrue(value['game_token_limit_enforced'])
            # Simulates a crash after dispatch, before a usage response. The
            # unknown spend persists across a fresh reader/restart.
            with p.open('a') as f:
                f.write('\n' + json.dumps(dict(base, call_id='c', request_id='s')))
            value = measured_game_budget(p, 'g', {'r','s'})
            self.assertEqual(value['cumulative_game_total_tokens'], 700)
            self.assertFalse(value['game_token_limit_enforced'])
            self.assertEqual(value['game_token_usage_unknown_calls'], 1)
            # Branches are new games, never charged their parent's future calls.
            self.assertEqual(measured_game_budget(p, 'branch', set())['cumulative_game_total_tokens'], 0)

    def test_missing_fields_and_host_usage_cannot_certify_online_cap(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'usage.ndjson'
            for payload in ({'input_tokens':100, 'output_tokens':50}, {'total_tokens':True},
                            {'total_tokens':-1}, {'total_tokens':150,'transport':'codex_native'}):
                record = dict(game_id='g', call_id='a', request_id='r', status='completed',
                              transport='fireworks_chat_completions')
                record.update(payload)
                p.write_text(json.dumps(record))
                self.assertFalse(measured_game_budget(p,'g',{'r'})['game_token_limit_enforced'])

@unittest.skipUnless(DRIVER.is_file(), 'build greedy_driver before real-driver tests')
class MaxGameTotalTokensTests(unittest.TestCase):
    def run_client(self, root, mode, cap=500, resume=False, turns=5):
        backend = root / 'backend.py'; backend.write_text(BACKEND)
        log = root / 'match.ndjson'
        cmd = [sys.executable, '-m', 'tools.llm_client', '--driver', str(DRIVER),
               '--scenario', 'big_battle_6', '--seed', '1', '--max-turns', str(turns),
               '--decision-mode','focused','--max-game-total-tokens', str(cap),
               '--model-command',shlex.join([sys.executable,str(backend),mode]),
               '--player-model','offline-fixture','--log',str(log),
               '--model-timeout','10','--turn-timeout','30','--query-budget-seconds','10']
        if resume: cmd += ['--resume-log',str(log)]
        result = subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=60)
        records = [json.loads(x) for x in log.read_text().splitlines()]
        terminal = next((r for r in reversed(records) if r.get('type') in ('terminal','model_error')), {})
        return result, terminal

    def test_at_most_one_call_overshoot(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); result,terminal=self.run_client(root,'normal')
            self.assertEqual(result.returncode,3,result.stderr)
            self.assertEqual(terminal['code'],'max_game_total_tokens_exhausted')
            self.assertEqual(terminal['cumulative_game_total_tokens'],600)
            self.assertTrue(terminal['game_token_limit_enforced'])
            self.assertEqual((root/'calls.txt').read_text(),'2')

    def test_output_limit_retry_is_counted_once_and_stops(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); result,terminal=self.run_client(root,'exhausted',cap=500)
            self.assertEqual(result.returncode,3,result.stderr)
            self.assertEqual(terminal['code'],'max_game_total_tokens_exhausted')
            self.assertEqual(terminal['cumulative_game_total_tokens'],600)
            self.assertEqual((root/'calls.txt').read_text(),'2')

    def test_replies_without_physical_evidence_are_unenforced(self):
        with tempfile.TemporaryDirectory() as td:
            result,terminal=self.run_client(Path(td),'missing',turns=1)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertFalse(terminal['game_token_limit_enforced'])
            self.assertGreater(terminal['game_token_usage_gaps'],0)

    def test_restart_counts_failed_call_sidecar_before_next_dispatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); result,terminal=self.run_client(root,'crash')
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(terminal['cumulative_game_total_tokens'],600)
            result,terminal=self.run_client(root,'normal',resume=True)
            self.assertEqual(result.returncode,3,result.stderr)
            self.assertEqual(terminal['code'],'max_game_total_tokens_exhausted')
            self.assertEqual(terminal['cumulative_game_total_tokens'],600)
            self.assertEqual((root/'calls.txt').read_text(),'2')

if __name__=='__main__': unittest.main()
