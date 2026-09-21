"""Index self-play boundary trajectories for analysis, without inventing action labels.

Usage: python3 -m tools.self_play_dataset RUN_ROOT --output NEW_DIRECTORY
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics
import tomllib


def features(state, side, definitions):
    units = [u for u in state['units'] if u['faction'] == side]
    leaders = [u for u in units if u['can_recruit']]
    return {
        'units': len(units),
        'composition': {name: sum(u['def_id'] == name for u in units) for name in sorted({u['def_id'] for u in units})},
        'material': sum(definitions[u['def_id']]['cost'] for u in units),
        'hp_material': sum(definitions[u['def_id']]['cost'] * u['hp'] / max(1, u['max_hp']) for u in units),
        'hp': sum(u['hp'] for u in units),
        'wounded': sum(u['hp'] < u['max_hp'] * .3 for u in units),
        'villages': sum(v[2] == side for v in state['village_owners']),
        'gold': state['gold'][side],
        'recruiter_alive': bool(leaders),
        'recruiter_hp': sum(u['hp'] for u in leaders),
    }


def read_game(path):
    with path.open() as source:
        records = [json.loads(line) for line in source]
    if not records or records[0].get('type') != 'metadata' or records[0].get('schema_version') != 1:
        raise ValueError(f'{path}: invalid metadata')
    if records[-1].get('type') != 'terminal':
        raise ValueError(f'{path}: incomplete game')
    meta, terminal = records[0], records[-1]
    middle = records[1:-1]
    unsupported = [r.get('type') for r in middle
                   if r.get('type') not in ('snapshot', 'actions')]
    if unsupported:
        raise ValueError(f'{path}: unexpected record inside trajectory')
    # Action records are optional evidence between boundaries. They do not
    # create additional dataset positions; coverage remains explicit in the
    # action record and metadata.
    snapshots = [r for r in middle if r.get('type') == 'snapshot']
    count = terminal['side_turns_executed']
    expected = [('opening', 0)]
    for step in range(count):
        expected += [('after_recruitment', step), ('after_turn', step + 1)]
    if [(r.get('phase'), r.get('step')) for r in snapshots] != expected:
        raise ValueError(f'{path}: broken boundary sequence')
    if terminal['reason'] not in ('winner', 'safety_cap'):
        raise ValueError(f'{path}: unknown terminal reason')
    if (terminal['reason'] == 'winner') != (terminal.get('winner') in (0, 1)):
        raise ValueError(f'{path}: contradictory outcome')
    return meta, terminal, snapshots


def split_for_seed(seed):
    # Both initiative variants, and every state from either game, stay together.
    bucket = int(hashlib.sha256(str(seed).encode()).hexdigest()[:8], 16) % 10
    return 'test' if bucket >= 8 else 'validation' if bucket == 7 else 'train'


def build(root, output, definitions_dir=None):
    repo = Path(__file__).resolve().parents[1]
    definitions = {}
    definitions_dir = definitions_dir or repo / 'data/units'
    for path in definitions_dir.rglob('*.toml'):
        definition = tomllib.loads(path.read_text())
        definitions[definition['id']] = definition
    paths = sorted(root.rglob('game-*.ndjson'))
    if not paths:
        raise ValueError('No trajectories found')
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(output / 'dataset.sqlite')
    db.executescript('''
      CREATE TABLE games (game_id TEXT PRIMARY KEY, input_seed INTEGER, split TEXT,
        first_side INTEGER, winner INTEGER, reason TEXT, turns INTEGER, archive TEXT, sha256 TEXT, metadata_json TEXT);
      CREATE TABLE positions (game_id TEXT, sequence INTEGER, side INTEGER, phase TEXT,
        step INTEGER, turn INTEGER, algorithm TEXT, outcome INTEGER, features_json TEXT,
        PRIMARY KEY(game_id, sequence, side));
      CREATE TABLE snapshots (game_id TEXT, sequence INTEGER, state_json TEXT,
        PRIMARY KEY(game_id, sequence));
    ''')
    results = []
    landmarks = []
    reversals = []
    seen = set()
    with (output / 'positions.jsonl').open('w') as exported:
        for path in paths:
            meta, end, snapshots = read_game(path)
            if meta['algorithms'] != ['greedy-look-ahead', 'greedy']:
                raise ValueError('Analysis requires lookahead on side 0 and greedy on side 1')
            identity = (meta['input_seed'], meta['first'], tuple(meta['algorithms']), meta['scenario'], tuple(meta['factions']), tuple(meta['starting_gold']))
            if identity in seen:
                raise ValueError(f'Duplicate game configuration: {identity}')
            seen.add(identity)
            game_id = str(path.relative_to(root))
            split = split_for_seed(meta['input_seed'])
            db.execute('INSERT INTO games VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (game_id, meta['input_seed'], split, meta['first'], end['winner'], end['reason'],
                        snapshots[-1]['state']['turn'], str(path.resolve()), hashlib.sha256(path.read_bytes()).hexdigest(), json.dumps(meta)))
            seen_landmarks = set()
            previous_delta = None
            for seq, record in enumerate(snapshots):
                state = record['state']
                if record['phase'] in ('after_recruitment', 'after_turn'):
                    delta = features(state, 0, definitions)['hp_material'] - features(state, 1, definitions)['hp_material']
                    if record['phase'] == 'after_turn' and previous_delta is not None and state['turn'] <= 20:
                        reversals.append(dict(game_id=game_id, sequence=seq, turn=state['turn'],
                            hp_material_delta_change=delta-previous_delta, winner=end['winner']))
                    previous_delta = delta
                if record['phase'] == 'after_turn' and state['active_faction'] == meta['first']:
                    for target in (5, 10, 20):
                        if state['turn'] == target and target not in seen_landmarks:
                            seen_landmarks.add(target)
                            left = features(state, 0, definitions)
                            right = features(state, 1, definitions)
                            landmarks.append(dict(game_id=game_id, turn=target, winner=end['winner'],
                                material_delta=left['hp_material']-right['hp_material'],
                                village_delta=left['villages']-right['villages'],
                                recruit_delta=record['recruits'][0]-record['recruits'][1]))
                db.execute('INSERT INTO snapshots VALUES (?,?,?)', (game_id, seq, json.dumps(state)))
                for side in (0, 1):
                    f = features(state, side, definitions)
                    f['recruits'] = record['recruits'][side]
                    # Outcomes are labels only, excluded from the input features.
                    outcome = None if end['winner'] is None else int(end['winner'] == side)
                    row = dict(game_id=game_id, sequence=seq, side=side, phase=record['phase'], step=record['step'],
                               turn=state['turn'], algorithm=meta['algorithms'][side], outcome=outcome, features=f, split=split)
                    db.execute('INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?)',
                               (game_id, seq, side, record['phase'], record['step'], state['turn'],
                                meta['algorithms'][side], outcome, json.dumps(f)))
                    exported.write(json.dumps(row) + '\n')
            results.append(dict(game_id=game_id, first=meta['first'], winner=end['winner'],
                                turns=snapshots[-1]['state']['turn'], snapshots=len(snapshots), split=split,
                                factions=meta['factions'], gold=meta['starting_gold']))
    db.commit()
    summary = {'games': len(results), 'snapshots': sum(r['snapshots'] for r in results),
               'by_first_side': {str(side): {'games': sum(r['first'] == side for r in results),
                   'lookahead_wins': sum(r['first'] == side and r['winner'] == 0 for r in results),
                   'greedy_wins': sum(r['first'] == side and r['winner'] == 1 for r in results),
                   'capped': sum(r['first'] == side and r['winner'] is None for r in results)} for side in (0, 1)},
               'turn_counter_median': statistics.median(r['turns'] for r in results),
               'turn_counter_max': max(r['turns'] for r in results),
               'splits': {s: sum(r['split'] == s for r in results) for s in ('train', 'validation', 'test')},
               'coverage': 'state boundaries only; no action sequence or counterfactual labels',
               'review_status': 'unreviewed observational data; not approved imitation targets'}
    strata = {}
    for row in results:
        key = f"{row['factions'][0]} vs {row['factions'][1]}, gold {row['gold']}, first {row['first']}"
        counts = strata.setdefault(key, {'games': 0, 'lookahead_wins': 0, 'greedy_wins': 0, 'capped': 0})
        counts['games'] += 1
        counts['lookahead_wins' if row['winner'] == 0 else 'greedy_wins' if row['winner'] == 1 else 'capped'] += 1
    summary['strata'] = strata
    summary['largest_early_material_swings'] = sorted(reversals, key=lambda r: abs(r['hp_material_delta_change']), reverse=True)[:20]
    summary['definitions_sha256'] = {str(p.relative_to(definitions_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in sorted(definitions_dir.rglob('*.toml'))}
    summary['landmark_associations'] = []
    for turn in (5, 10, 20):
        for feature in ('material_delta', 'village_delta', 'recruit_delta'):
            for sign, predicate in [('ahead', lambda x: x > 0), ('tied', lambda x: x == 0), ('behind', lambda x: x < 0)]:
                rows = [r for r in landmarks if r['turn'] == turn and predicate(r[feature])]
                summary['landmark_associations'].append(dict(turn=turn, feature=feature,
                    lookahead_status=sign, games=len(rows), lookahead_wins=sum(r['winner']==0 for r in rows),
                    greedy_wins=sum(r['winner']==1 for r in rows), capped=sum(r['winner'] is None for r in rows)))
    summary['association_limitations'] = 'Descriptive only; mixed factions/gold, paired seeds, and survival to landmark confound these associations.'
    (output / 'landmarks.json').write_text(json.dumps(landmarks, indent=2) + '\n')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    db.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--definitions', type=Path, help='Archived unit definitions directory; defaults to current checkout')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.output, args.definitions), indent=2))


if __name__ == '__main__':
    main()
