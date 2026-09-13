"""Stack 2 cross-layer checks: real client/driver, scripted policy, real catalog."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

from .game_history import import_game, open_history

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tools/fixtures/strategy_routine'
DRIVER = Path(os.environ.get('NORRUST_TEST_DRIVER', ROOT / 'norrust_core/target/debug/greedy_driver'))


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def engine_events(rows):
    return [event for r in rows if r.get('type') == 'driver'
            and r.get('line', {}).get('type') == 'events'
            for event in r['line'].get('events', [])]


def driver_states(rows):
    result = []
    boundaries = {r['state_revision']: r['side_turns'] for r in rows
                  if r.get('type') == 'checkpoint_ref'
                  and 'state_revision' in r and 'side_turns' in r}
    boundaries.update({r['line']['state_revision']: r['line']['side_turns']
                       for r in rows if r.get('type') == 'driver'
                       and r.get('line', {}).get('type') == 'game_end'
                       and 'state_revision' in r['line'] and 'side_turns' in r['line']})
    for r in rows:
        if r.get('type') != 'driver':
            continue
        line = r.get('line', {})
        if line.get('type') == 'state':
            snapshot = dict(line)
            if line['state_revision'] in boundaries:
                snapshot['side_turns'] = boundaries[line['state_revision']]
            result.append(snapshot)
        elif line.get('type') == 'game_end' and isinstance(line.get('state'), dict):
            final = dict(line['state'])
            final.setdefault('side_turns', line.get('side_turns'))
            result.append(final)
    return result


def prepare(root, policy=None):
    data = json.loads((FIXTURES / 'quiet.json').read_text())
    board = ROOT / 'scenarios/big_battle_6/board.toml'
    if not board.is_file():
        board = ROOT / 'scenarios/big_battle_6/board.json'
    if not board.is_file():
        raise AssertionError('Resolve the maintained scenario board path; do not bypass its hash')
    if hashlib.sha256(board.read_bytes()).hexdigest() != data['board_sha256']:
        raise AssertionError('Fixture board hash changed')
    data['board_path'] = str(board)
    data['save_state']['board_path'] = str(board)
    encoded = json.dumps(data).encode()
    checkpoint = root / ('checkpoint-' + hashlib.sha256(encoded).hexdigest() + '.json')
    checkpoint.write_bytes(encoded)
    policy = policy or json.loads((FIXTURES / 'quiet_policy.json').read_text())
    policy_file = root / 'policy.json'
    policy_file.write_text(json.dumps(policy))
    prompt_log = root / 'backend-calls.ndjson'
    backend = root / 'backend.py'
    backend.write_text(
        'import json,sys\nfrom pathlib import Path\n'
        f'p=Path({str(policy_file)!r});log=Path({str(prompt_log)!r})\n'
        'prompt=sys.stdin.read()\n'
        'with log.open("a") as f:f.write(json.dumps({"prompt":prompt})+"\\n")\n'
        'print(json.dumps({"text":json.dumps({"kind":"set_policy","policy":json.loads(p.read_text())})}))\n')
    return checkpoint, policy_file, backend, prompt_log


def launch(root, log, checkpoint, policy_file, backend, *, fixed=False, turns=6, resume=False):
    args = [sys.executable, '-m', 'tools.llm_client', '--driver', str(DRIVER),
            '--scenario', 'big_battle_6', '--faction0', 'undead', '--faction1', 'undead',
            '--gold', '300', '--seed', '9211', '--llm-side', '0', '--max-turns', str(turns),
            '--decision-mode', 'strategy', '--log', str(log),
            '--query-budget-seconds', '60', '--turn-timeout', '120', '--model-timeout', '30']
    args += ['--resume-log', str(log)] if resume else ['--resume-checkpoint', str(checkpoint)]
    if fixed:
        args += ['--strategy-policy', str(policy_file)]
    else:
        args += ['--model-command', shlex.join([sys.executable, str(backend)])]
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, timeout=150)


@unittest.skipUnless(DRIVER.is_file(), 'Build the actual driver; a skipped case is not acceptance')
class StrategyRoutineStack2Tests(unittest.TestCase):
    def assert_run_ok(self, result, log):
        self.assertEqual(result.returncode, 0, result.stderr + log.read_text()[-12000:])

    def test_three_quiet_turns_one_policy_real_capture_and_catalog(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy, backend, prompts = prepare(root)
            log = root / 'game.ndjson'
            self.assert_run_ok(launch(root, log, checkpoint, policy, backend), log)
            rows = records(log)
            self.assertEqual(len(records(prompts)), 1)
            self.assertEqual(sum(r.get('type') == 'policy_installed' for r in rows), 1)
            events = engine_events(rows)
            recruits = [e for e in events if e.get('kind') == 'recruit']
            self.assertEqual(len(recruits), 6)
            states = driver_states(rows)
            self.assertEqual(states[-1]['side_turns'], 6)
            # No automatic combat, no enemy recruitment, no recruiter movement.
            self.assertFalse(any(e.get('kind') == 'attack' for e in events))
            self.assertFalse(any(e.get('kind') in ('move', 'vacate') and e.get('unit') == 1 for e in events))
            db = root / 'history.sqlite'
            conn = open_history(db)
            try:
                game_id = import_game(conn, log)
                tables = ('games', 'side_turns', 'snapshots', 'events', 'model_requests', 'model_calls', 'action_batches')
                counts = lambda: {t: conn.execute(f'SELECT count(*) FROM {t} WHERE game_id=?', (game_id,)).fetchone()[0] for t in tables}
                before = counts()
                import_game(conn, log)
                self.assertEqual(before, counts())
                self.assertEqual(conn.execute('SELECT count(*) FROM model_requests WHERE game_id=?', (game_id,)).fetchone()[0], 1)
                self.assertGreater(conn.execute("SELECT count(*) FROM events WHERE game_id=? AND source='routine'", (game_id,)).fetchone()[0], 6)
                self.assertEqual(conn.execute("SELECT count(*) FROM events WHERE game_id=? AND source='llm'", (game_id,)).fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT count(*) FROM side_turns WHERE game_id=? AND side=0 AND ended_at IS NOT NULL", (game_id,)).fetchone()[0], 3)
            finally:
                conn.close()
            # Actual village ownership must be present at the final boundary.
            terrain = {(t['col'], t['row']): t for t in states[-1]['terrain']}
            for pos in ((2, 4), (5, 3), (6, 11)):
                self.assertEqual(terrain[pos]['owner'], 0)
            # Mid-turn arrival does not claim ownership. There must be a partial
            # state with scouts on villages before ownership flips at a finish.
            partial = [s for s in states if s.get('turn_boundary') == 'partial' and s.get('side_turns') == 0]
            self.assertTrue(partial)
            self.assertTrue(all(t.get('owner') != 0 for s in partial for t in s.get('terrain', []) if (t['col'], t['row']) in ((2, 4), (5, 3), (6, 11))))

    def test_fixed_policy_executes_same_routine_without_backend_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy, backend, prompts = prepare(root)
            log = root / 'fixed.ndjson'
            self.assert_run_ok(launch(root, log, checkpoint, policy, backend, fixed=True), log)
            rows = records(log)
            self.assertFalse(prompts.exists())
            self.assertFalse(any(r.get('type') == 'model_request' for r in rows))
            self.assertEqual(driver_states(rows)[-1]['side_turns'], 6)
            self.assertEqual(sum(e.get('kind') == 'recruit' for e in engine_events(rows)), 6)

    def test_completed_policy_is_adopted_after_finish_acknowledgement(self):
        policy = {'reserve_gold': 0, 'recruits': [], 'scouts': [],
                  'villages': [], 'rally': None, 'holds': []}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy_file, backend, prompts = prepare(root, policy)
            log = root / 'completed.ndjson'
            result = launch(root, log, checkpoint, policy_file, backend,
                            fixed=True, turns=1)
            self.assert_run_ok(result, log)
            rows = records(log)
            completed = [r for r in rows if r.get('type') == 'routine_progress_committed'
                         and {'kind': 'policy_completed'} in r['progress_update']['effects']]
            self.assertEqual(len(completed), 1)
            self.assertTrue(any(r.get('type') == 'turn_boundary'
                                and r.get('accepted') for r in rows))
            self.assertFalse(prompts.exists())

    def test_repeated_definition_queue_binds_only_actual_scout_recruits(self):
        policy = {'reserve_gold': 0, 'recruits': [
            {'def_id': 'Ghost', 'count': 2, 'role': 'scout'},
            {'def_id': 'Ghost', 'count': 2, 'role': 'army'}],
            'scouts': [], 'villages': [{'col': 2, 'row': 4}, {'col': 5, 'row': 3}],
            'rally': None, 'holds': []}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy_file, backend, prompts = prepare(root, policy)
            log = root / 'repeated.ndjson'
            self.assert_run_ok(launch(root, log, checkpoint, policy_file, backend, turns=1), log)
            rows = records(log)
            recruits = [e for e in engine_events(rows) if e.get('kind') == 'recruit']
            self.assertEqual(len(recruits), 4)
            committed = [r for r in rows if r.get('type') == 'routine_progress_committed']
            effects = [e for r in committed for e in r['progress_update']['effects']]
            per_queue = {q: [e['unit_id'] for e in effects if e.get('kind') == 'recruited' and e['queue_index'] == q] for q in (0, 1)}
            self.assertEqual([len(per_queue[q]) for q in (0, 1)], [2, 2])
            self.assertTrue(set(per_queue[0]).isdisjoint(per_queue[1]))
            assigned = {e['unit_id'] for e in effects if e.get('kind') == 'scout_assigned'}
            self.assertEqual(assigned, set(per_queue[0]))
            self.assertEqual(len(records(prompts)), 1)


    def _replay_cut(self, *, after_finish=False, duplicate=False, omit_progress=False,
                    before_ack=False, destroy_proposal=False):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint, policy, backend, prompts = prepare(root)
            control_log = root / 'control.ndjson'
            self.assert_run_ok(launch(root, control_log, checkpoint, policy, backend), control_log)
            control = records(control_log)
            crash_log = root / 'crash.ndjson'
            self.assert_run_ok(launch(root, crash_log, checkpoint, policy, backend), crash_log)
            rows = records(crash_log)
            finishes = {r['batch_id'] for r in rows if r.get('type') == 'forwarded_orders'
                        and r.get('orders', [{}])[0].get('action') == 'FinishWithGreedy'}
            candidates = [(i, r) for i, r in enumerate(rows) if r.get('type') == 'routine_progress_committed'
                          and ((r.get('batch_id') in finishes) if after_finish else
                               any(e.get('kind') == 'recruited' for e in r.get('progress_update', {}).get('effects', [])))]
            self.assertTrue(candidates, 'No actual committed routine step for the required boundary')
            cut, chosen = candidates[0]
            if before_ack:
                cut = next(i for i, r in enumerate(rows)
                           if r.get('type') == 'checkpoint_ref'
                           and r.get('batch_id') == chosen['batch_id'])
            surviving = rows[:cut + (0 if omit_progress else 1)]
            if destroy_proposal:
                for r in surviving:
                    if r.get('batch_id') == chosen['batch_id']:
                        r.pop('progress_update', None)
            if duplicate:
                surviving.append(chosen)
            crash_log.write_text('\n'.join(json.dumps(r) for r in surviving) + '\n')
            referenced = {Path(r['path']).name for r in surviving if r.get('type') == 'checkpoint_ref'}
            for saved in crash_log.with_suffix('.ckpt').iterdir():
                if saved.name not in referenced:
                    saved.unlink()
            resumed = launch(root, crash_log, checkpoint, policy, backend, resume=True)
            if destroy_proposal:
                self.assertNotEqual(resumed.returncode, 0)
                terminal = [r for r in records(crash_log) if r.get('type') == 'terminal'][-1]
                self.assertEqual(terminal.get('action_boundary_status'), 'unknown')
                return
            if omit_progress:
                # Either reconstruct from durable pending evidence, or refuse
                # unknown progress. Never quietly reset the policy counters.
                if resumed.returncode != 0:
                    terminal = [r for r in records(crash_log) if r.get('type') == 'terminal'][-1]
                    self.assertEqual(terminal.get('action_boundary_status'), 'unknown')
                    return
            self.assert_run_ok(resumed, crash_log)
            actual = records(crash_log)
            # A crash before the event envelope loses that historical event;
            # checkpoint proof recovers state/progress without fabricating events.
            expected_recorded_recruits = 5 if before_ack and not after_finish else 6
            self.assertEqual(sum(e.get('kind') == 'recruit' for e in engine_events(actual)),
                             expected_recorded_recruits)
            if before_ack:
                self.assertTrue(any(r.get('recovered_from_checkpoint') for r in actual))
            want_state, got_state = driver_states(control)[-1], driver_states(actual)[-1]
            self.assertEqual(got_state['side_turns'], 6)
            self.assertEqual(got_state['gold'], want_state['gold'])
            self.assertEqual(sorted(got_state['units'], key=lambda u: u['id']),
                             sorted(want_state['units'], key=lambda u: u['id']))
            self.assertEqual(got_state['terrain'], want_state['terrain'])

    def test_duplicate_real_committed_recruit_on_resume_is_not_reexecuted(self):
        self._replay_cut(duplicate=True)

    def test_capture_finish_checkpoint_resume_preserves_actual_ownership(self):
        self._replay_cut(after_finish=True)

    def test_checkpoint_before_recruit_ack_recovers_actual_id_and_counts(self):
        self._replay_cut(before_ack=True)

    def test_checkpoint_before_finish_ack_recovers_capture(self):
        self._replay_cut(before_ack=True, after_finish=True)

    def test_checkpoint_without_proposal_reports_unknown(self):
        self._replay_cut(before_ack=True, destroy_proposal=True)

    def test_missing_committed_progress_reconstructs_or_explicitly_refuses(self):
        self._replay_cut(omit_progress=True)


if __name__ == '__main__':
    unittest.main()
