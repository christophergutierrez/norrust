"""Guard comparison provenance and final-state evidence before launching trials."""
import copy
import unittest
from . import model_bakeoff as b


def matrix():
    return b.resolve_manifest({'experiment_kind':'bakeoff','cells':[
        {'id':a,'arm':a,'match_group':'position1','scenario':'big_battle_6','gold':300,
         'max_turns':2,'seed':42,'faction0':'undead','faction1':'undead','llm_side':0,
         'model':'fixture','backend':{'kind':'command','command':'fixture'},
         'decision_mode':'batch' if a=='A' else 'focused',
         'action_encoding':'choices' if a=='C' else 'coordinates','incremental_turns':True}
        for a in 'ABC']})

class ComparisonContractTests(unittest.TestCase):
    def test_mode_budget_forwarding_and_isolated_context(self):
        from pathlib import Path
        manifest=matrix(); argv,env=b.build_llm_client_argv(manifest['cells'][2],Path('/tmp/cell-C'))
        self.assertEqual(argv[argv.index('--max-partial-batches-per-turn')+1],'64')
        self.assertEqual(env['NORRUST_REQUEST_CONTEXT_FILE'],'/tmp/cell-C/request_context.json')
        self.assertEqual(env['NORRUST_USAGE_SIDECAR'],'/tmp/cell-C/usage.ndjson')

    def test_all_frozen_settings_checked_within_matched_position(self):
        self.assertTrue(b.check_comparison_validity(matrix())['valid'])
        for key,value in [('model','different'),('seed',99),('llm_side',1),
                          ('backend',{'kind':'file'}),('budgets',{'max_game_total_tokens':100})]:
            manifest=matrix(); manifest['cells'][1][key]=value
            self.assertFalse(b.check_comparison_validity(manifest)['valid'],key)
        manifest=matrix();manifest['cells'].pop()
        self.assertFalse(b.check_comparison_validity(manifest)['valid'])
        manifest=matrix();manifest['cells'][2]['max_partial_batches_per_turn']=3
        self.assertFalse(b.check_comparison_validity(manifest)['valid'])

    def test_terminal_snapshot_and_conjunctive_objective(self):
        opening={'units':[{'id':1,'faction':0,'hp':20,'can_recruit':True,'col':2,'row':7},
                          {'id':2,'faction':1,'hp':10,'col':3,'row':7}]}
        final=copy.deepcopy(opening);final['units'].pop();final['units'][0]['col']=3
        final['village_owners']=[[3,7,0]]
        records=[{'type':'driver','line':{'type':'state',**opening}},
                 {'type':'driver','line':{'type':'game_end','side_turns':2,'state':final}}]
        predicate={'recruiter_alive':True,'absent_units':[2],
                   'units_at':[{'unit_id':1,'col':3,'row':7}],
                   'owned_villages':[{'col':3,'row':7,'owner':0}],
                   'completed_side_turns_at_least':2}
        self.assertTrue(b.evaluate_objective(records,predicate))
        predicate['alive_units']=[2]
        self.assertFalse(b.evaluate_objective(records,predicate))

    def test_unknown_objective_does_not_become_success(self):
        self.assertIsNone(b.evaluate_objective([],{'recruiter_alive':True}))
        self.assertIsNone(b.evaluate_objective([],{}))

    def test_saved_manifest_cannot_launch_against_changed_source(self):
        from pathlib import Path
        import tempfile
        manifest = matrix()
        manifest['cells'][0]['provenance']['source_commit'] = 'different-build'
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(b.ManifestError, 'source_commit changed'):
                b.run_cell(manifest['cells'][0], Path(td))
            self.assertEqual(list(Path(td).iterdir()), [])
