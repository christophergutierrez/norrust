import json
from pathlib import Path
import tempfile
import unittest
from tools.self_play_dataset import features, read_game, split_for_seed


class DatasetTests(unittest.TestCase):
    def test_missing_terminal_is_not_a_loss(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'game.ndjson'
            p.write_text(json.dumps({'type':'metadata','schema_version':1})+'\n')
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                read_game(p)

    def test_missing_boundary_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'game.ndjson'
            p.write_text('\n'.join(map(json.dumps, [
                {'type':'metadata','schema_version':1},
                {'type':'snapshot','phase':'opening','step':0},
                {'type':'terminal','reason':'winner','winner':0,'side_turns_executed':1}])))
            with self.assertRaisesRegex(ValueError, 'boundary'):
                read_game(p)

    def test_features_exclude_rng_and_outcome(self):
        state={'units':[{'id':1,'def_id':'a','faction':0,'hp':5,'max_hp':20,'can_recruit':True}],
               'village_owners':[[2,3,0]],'gold':[10,20],'rng_state':123,'winner':0}
        f=features(state,0,{'a':{'cost':40}})
        self.assertEqual(f['hp_material'],10)
        self.assertEqual(f['wounded'],1)
        self.assertEqual(f['villages'],1)
        self.assertNotIn('rng_state',f)
        self.assertNotIn('winner',f)
        self.assertEqual(features(state,1,{'a':{'cost':40}})['recruiter_alive'],False)

    def test_seed_split_independent_of_game_variant(self):
        self.assertEqual(split_for_seed(81),split_for_seed(81))
        self.assertTrue({split_for_seed(i) for i in range(100)} == {'train','validation','test'})

    def test_capped_export_preserves_unknown_outcome_and_raw_state(self):
        import sqlite3
        from tools.self_play_dataset import build
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            definitions = root/'definitions'
            definitions.mkdir()
            games = root/'games'
            games.mkdir()
            state = dict(units=[], village_owners=[], gold=[300,300], turn=1,
                         active_faction=0, rng_state=981)
            meta = dict(type='metadata', schema_version=1, input_seed=5, first=0,
                        algorithms=['greedy-look-ahead','greedy'], scenario='test',
                        factions=['undead','undead'], starting_gold=[300,300])
            rows = [meta]
            for phase,step in [('opening',0),('after_recruitment',0),('after_turn',1)]:
                rows.append(dict(type='snapshot',phase=phase,step=step,state=state,recruits=[0,0]))
            rows.append(dict(type='terminal',reason='safety_cap',winner=None,side_turns_executed=1))
            (games/'game-00001.ndjson').write_text('\n'.join(map(json.dumps,rows)))
            report=build(games,root/'output',definitions)
            self.assertEqual(report['by_first_side']['0']['capped'],1)
            exported=[json.loads(line) for line in (root/'output/positions.jsonl').read_text().splitlines()]
            self.assertEqual(len(exported),6)
            self.assertTrue(all(row['outcome'] is None for row in exported))
            self.assertTrue(all('rng_state' not in row['features'] for row in exported))
            with sqlite3.connect(root/'output/dataset.sqlite') as db:
                self.assertEqual(json.loads(db.execute('select state_json from snapshots limit 1').fetchone()[0])['rng_state'],981)
            with self.assertRaises(FileExistsError):
                build(games,root/'output',definitions)

    def test_real_recorder_preserves_result_and_refuses_overwrite(self):
        import os
        import subprocess
        repo=Path(__file__).resolve().parents[1]
        driver=Path(os.environ.get('NORRUST_TEST_DRIVER', repo/'norrust_core/target/release/greedy_driver'))
        binary=driver.with_name('self-play')
        if not binary.exists():
            self.skipTest('Build self-play before recorder integration check')
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'recording'
            command=[str(binary),'--team1','undead','--team2','undead',
                     '--ai1','greedy-look-ahead','--ai2','greedy','--games','1',
                     '--threads','1','--seed','912','--gold','250','--second-gold','0',
                     '--first','team2','--max-turns','1','--verbose']
            plain=subprocess.run(command,cwd=repo,capture_output=True,text=True,check=True)
            recorded=subprocess.run(command+['--record-dir',str(output)],cwd=repo,capture_output=True,text=True,check=True)
            self.assertEqual(plain.stdout,recorded.stdout)
            meta,end,states=read_game(output/'game-00001.ndjson')
            self.assertEqual(meta['starting_gold'],[250,250])
            self.assertEqual(meta['first'],1)
            self.assertEqual(end['reason'],'safety_cap')
            self.assertEqual(len(states),9)
            original=(output/'game-00001.ndjson').read_bytes()
            failed=subprocess.run(command+['--record-dir',str(output)],cwd=repo,capture_output=True,text=True)
            self.assertNotEqual(failed.returncode,0)
            self.assertEqual((output/'game-00001.ndjson').read_bytes(),original)

    def test_review_swings_exclude_recruitment_purchase(self):
        from tools.self_play_dataset import build
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); definitions=root/'defs'; definitions.mkdir()
            (definitions/'unit.toml').write_text('id="a"\ncost=40\n')
            games=root/'games'; games.mkdir()
            base=dict(units=[],village_owners=[],gold=[40,40],turn=1,active_faction=0)
            unit=dict(id=1,def_id='a',faction=0,hp=20,max_hp=20,can_recruit=False)
            recruited=dict(base,units=[unit],gold=[0,40])
            wounded=dict(base,units=[dict(unit,hp=10)],gold=[0,40],active_faction=1)
            meta=dict(type='metadata',schema_version=1,input_seed=5,first=0,
                      algorithms=['greedy-look-ahead','greedy'],scenario='test',
                      factions=['undead','undead'],starting_gold=[40,40])
            rows=[meta]
            for phase,step,state in [('opening',0,base),('after_recruitment',0,recruited),('after_turn',1,wounded)]:
                rows.append(dict(type='snapshot',phase=phase,step=step,state=state,recruits=[1,0]))
            rows.append(dict(type='terminal',reason='safety_cap',winner=None,side_turns_executed=1))
            (games/'game-00001.ndjson').write_text('\n'.join(map(json.dumps,rows)))
            result=build(games,root/'output',definitions)
            swings=result['largest_early_material_swings']
            self.assertEqual(len(swings),1)
            self.assertEqual(swings[0]['hp_material_delta_change'],-20)
