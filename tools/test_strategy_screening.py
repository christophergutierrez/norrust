"""Screening must measure outcomes equally for choose and custom-act players."""
import copy
import unittest

from .strategy_screening import score_cell, summarize


def archive(*, position=(2, 7), hit=False, selected=False, finished=True):
    units = [{'id': 1, 'hp': 48, 'col': position[0], 'row': position[1]},
             {'id': 4, 'hp': 5 if hit else 8, 'col': 11, 'row': 7}]
    events = ([{'kind': 'attack', 'source': 'llm', 'defender': {'unit': 4, 'killed': False}}]
              if hit else [{'kind': 'move', 'source': 'llm', 'unit': 1}])
    rows = [{'type': 'driver', 'line': {'type': 'events', 'events': events}},
            {'type': 'driver', 'line': {'type': 'state', 'units': units}}]
    if selected:
        rows.insert(0, {'type': 'forwarded_orders', 'option_id': 'relocate_1'})
    if finished:
        rows.append({'type': 'terminal', 'terminal_class': 'gameplay', 'reason': 'max_turns'})
    return rows


class ScreeningTests(unittest.TestCase):
    def test_custom_attack_and_option_score_equally(self):
        case = {'position_id': 'favorable-tactical-attack', 'target_id': 4, 'initial_target_hp': 8}
        a = score_cell(case, archive(hit=True))
        b = score_cell(case, archive(hit=True, selected=True))
        self.assertTrue(a['passed'])
        self.assertEqual(a, b)
        self.assertFalse(score_cell(case, archive(selected=True))['passed'])

    def test_relocation_label_does_not_prove_lower_exposure(self):
        case = {'position_id': 'withdrawal', 'target_id': 4, 'initial_target_hp': 8,
                'actor_id': 1, 'lower_exposure_endpoints': [[0, 7]]}
        self.assertFalse(score_cell(case, archive(selected=True))['passed'])
        self.assertTrue(score_cell(case, archive(position=(0, 7)))['passed'])
        changed = archive(position=(0, 7))
        changed[0]['line']['events'].append({'kind': 'recruit', 'source': 'routine', 'unit': 9})
        self.assertFalse(score_cell(case, changed)['passed'])

    def test_missing_policy_packet_is_unknown(self):
        case = {'position_id': 'favorable-tactical-attack', 'target_id': 4, 'initial_target_hp': 8}
        rows = archive(hit=True)
        rows.insert(0, {'type': 'policy_installed'})
        score = score_cell(case, rows)
        self.assertEqual(score['unknown_policy_installations'], 1)
        self.assertEqual(score['invalid_policy_installations'], 0)

    def test_truncated_archive_cannot_pass(self):
        case = {'position_id': 'favorable-tactical-attack', 'target_id': 4, 'initial_target_hp': 8}
        score = score_cell(case, archive(hit=True, finished=False))
        self.assertIsNone(score['useful_action'])
        self.assertFalse(score['passed'])

    def test_resigning_after_damage_is_not_successful_completion(self):
        case = {'position_id': 'favorable-tactical-attack', 'target_id': 4, 'initial_target_hp': 8}
        rows = archive(hit=True)
        rows[-1]['reason'] = 'resignation'
        self.assertFalse(score_cell(case, rows)['passed'])

    def test_missing_or_duplicate_cells_cannot_complete_screen(self):
        self.assertEqual(summarize([])['status'], 'incomplete')
        score = {'terminal_present': True, 'passed': True, 'invalid_policy_installations': 0,
                 'max_ineffective_responses': 0, 'recruiter_alive': True,
                 'unknown_policy_installations': 0}
        cells = [{'treatment': t, 'position_id': str(i // 2), 'repetition': i % 2,
                  'total_tokens': 100 if t == 'baseline' else 50, 'score': copy.deepcopy(score)}
                 for t in ('baseline', 'candidate') for i in range(8)]
        self.assertEqual(summarize(cells)['status'], 'passed')
        cells[-1] = copy.deepcopy(cells[-2])
        self.assertEqual(summarize(cells)['status'], 'incomplete')

    def test_failed_cells_remain_in_token_median(self):
        score = {'terminal_present': True, 'passed': True, 'invalid_policy_installations': 0,
                 'max_ineffective_responses': 0, 'recruiter_alive': True,
                 'unknown_policy_installations': 0}
        cells = [{'treatment': t, 'position_id': str(i), 'repetition': 1,
                  'total_tokens': 100, 'score': copy.deepcopy(score)}
                 for t in ('baseline', 'candidate') for i in range(8)]
        for row in cells[-2:]:
            row['score']['passed'] = False
            row['total_tokens'] = 1000
        report = summarize(cells)
        self.assertEqual(report['successes']['candidate'], 6)
        self.assertEqual(report['median_total_tokens']['candidate'], 100)
        self.assertEqual(report['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
