"""Treatment-neutral scoring for the bounded strategy screening.

This module does not launch models. Inputs are committed driver evidence and
catalog usage. Engine-option selection alone is never tactical success.
"""
from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any

from . import match_report, model_bakeoff


def score_cell(case: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    state = model_bakeoff._final_state(records)
    terminal = match_report.terminal_record(records)
    terminal_present = bool(terminal)
    units = {u['id']: u for u in (state or {}).get('units', [])}
    events = [e for r in records if r.get('type') == 'driver'
              and isinstance(r.get('line'), dict) and r['line'].get('type') == 'events'
              for e in r['line'].get('events', [])]
    controlled = [e for e in events if e.get('source') in ('llm', 'model', 'routine', 'delegated_greedy')]
    target_id = case.get('target_id')
    target_hits = [e for e in controlled if e.get('kind') == 'attack'
                   and isinstance(e.get('defender'), dict)
                   and e['defender'].get('unit') == target_id]
    target = units.get(target_id)
    target_damaged = bool(target_hits) and (
        (target is not None and target.get('hp', case['initial_target_hp']) < case['initial_target_hp'])
        or any(e['defender'].get('killed') is True for e in target_hits))
    recruiter = units.get(case.get('recruiter_id', 1))
    recruiter_alive = (recruiter.get('hp', 0) > 0) if recruiter is not None else (
        False if state is not None else None)
    ended = (terminal_present and match_report.classify(records).get('terminal_class') == 'gameplay'
             and terminal.get('reason') in ('max_turns', 'winner'))
    position = case['position_id']
    if position in ('favorable-tactical-attack', 'repeated-current-contact'):
        useful = target_damaged
    elif position == 'independent-scout-movement':
        scout = units.get(case['scout_id'])
        useful = bool(scout and [scout.get('col'), scout.get('row')] == case['scout_goal']) and target_damaged
    elif position == 'withdrawal':
        actor = units.get(case['actor_id'])
        # These endpoints are pinned before launch by the engine's projected
        # threat calculation. Its proof applies only if other actors did not
        # move, attack, die, or get recruited in this one-turn fixture.
        scene_changed = any(e.get('kind') in ('attack', 'recruit', 'death', 'advance')
                            or (e.get('kind') == 'move' and e.get('unit') != case['actor_id'])
                            for e in events)
        useful = bool(actor and not scene_changed and
                      [actor.get('col'), actor.get('row')] in case['lower_exposure_endpoints'])
    else:
        raise ValueError(f'Unsupported screening position: {position}')

    packet = None
    invalid_installs = 0
    unknown_installs = 0
    ineffective = Counter()
    for row in records:
        if row.get('type') == 'decision_packet':
            packet = row.get('packet', {})
        elif row.get('type') == 'policy_installed':
            if not packet or not isinstance(packet.get('allowed_kinds'), list):
                unknown_installs += 1
            elif 'set_policy' not in packet['allowed_kinds']:
                invalid_installs += 1
        if row.get('type') in ('contextual_rejection', 'incident_recurrence'):
            ineffective[(row.get('side_turn_id', row.get('side_turn')),
                         row.get('state_revision'), row.get('incident_key'))] += 1
    return {'terminal_present': terminal_present, 'gameplay_completed': ended,
            'recruiter_alive': recruiter_alive,
            'useful_action': useful if terminal_present and state is not None else None,
            'passed': bool(ended and useful and recruiter_alive),
            'invalid_policy_installations': invalid_installs,
            'unknown_policy_installations': unknown_installs,
            'max_ineffective_responses': max(ineffective.values(), default=0)}


def summarize(cells: list[dict[str, Any]], *, expected_per_treatment: int = 8) -> dict[str, Any]:
    groups = {t: [c for c in cells if c['treatment'] == t] for t in ('baseline', 'candidate')}
    complete = all(len(g) == expected_per_treatment for g in groups.values())
    keys = {t: [(c['position_id'], c['repetition']) for c in g] for t, g in groups.items()}
    complete = complete and all(len(set(k)) == len(k) for k in keys.values())
    complete = complete and set(keys['baseline']) == set(keys['candidate'])
    complete = complete and all(c.get('total_tokens') is not None and
                                c['score']['terminal_present'] for c in cells)
    counts = {t: sum(c['score']['passed'] for c in g) for t, g in groups.items()}
    medians = {t: median([c['total_tokens'] for c in g]) if g and
               all(c.get('total_tokens') is not None for c in g) else None for t, g in groups.items()}
    targets = {
        'complete': complete,
        'useful_actions': counts['candidate'] >= 6 and counts['candidate'] >= counts['baseline'],
        'token_reduction': (medians['candidate'] <= .75 * medians['baseline'])
                          if complete else None,
        'no_invalid_policy_installations': all(c['score']['invalid_policy_installations'] == 0 and
                                               c['score'].get('unknown_policy_installations') == 0
                                               for c in groups['candidate']) if complete else None,
        'bounded_ineffective_responses': all(c['score']['max_ineffective_responses'] <= 2
                                            for c in groups['candidate']) if complete else None,
        'recruiters_survived': all(c['score']['recruiter_alive'] is True
                                   for c in groups['candidate']) if complete else None,
    }
    return {'status': 'passed' if all(v is True for v in targets.values()) else
            ('failed' if complete else 'incomplete'), 'targets': targets,
            'successes': counts, 'median_total_tokens': medians, 'cells': cells,
            'note': 'Illegal/stale/duplicate execution and independent-move safety require the offline gates too.'}
