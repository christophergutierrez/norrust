"""Independent offline acceptance of routing through actual client lifecycle."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from .game_history import import_game, import_usage_sidecar, open_history
from .llm_client import select_resume_checkpoint
from .model_usage import ModelCall
from .prompt_cache_report import report_sqlite

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))

BACKEND = '''import json,os,sys,time
from pathlib import Path
from tools import fireworks_backend as fb
root=Path(os.environ['CACHE_TEST_RUN'])
mode=os.environ.get('CACHE_TEST_MODE','normal')
original_run=fb.run
def opener(request,timeout=None):
    index=len(list(root.glob('wire-*.json')))
    payload=json.loads(request.data)
    (root/f'wire-{index:03d}.json').write_text(json.dumps({'body':payload,'headers':dict(request.headers)}))
    if mode=='interrupt' and index==1:
        (root/'dispatch-ready').write_text('ready')
        time.sleep(60)
    actions=([{'action':'Move','unit_id':1,'col':3,'row':7}]
             if index==0 and mode!='finish' else [{'action':'EndTurn'}])
    body={'id':root.name+str(index),'model':payload['model'],
          'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'actions':actions})}}],
          'usage':{'prompt_tokens':1000,'prompt_cache_hit_tokens':200,'completion_tokens':10,'total_tokens':1010}}
    class Response:
        headers={}
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self):return json.dumps(body).encode()
    return Response()
def run(*args,**kwargs):
    kwargs.update(opener=opener,api_key='offline-fixture-key')
    return original_run(*args,**kwargs)
fb.run=run
raise SystemExit(fb.main(['--model','fixture-model']))
'''


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class CacheReportDatabaseAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "history.sqlite"
        self.conn = open_history(self.db)
        self.conn.execute("INSERT INTO games(game_id,status,config_json,provenance_json,schema_version,artifact_path) VALUES('g','fixture','{}','{}',5,?)", (str(self.root),))

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def request(self, rid, sequence, layout="prompt_layout_v2"):
        self.conn.execute("INSERT INTO model_requests(request_id,game_id,sequence,prompt_layout_version,record_hash) VALUES(?,'g',?,?,?)", (rid, sequence, layout, rid))

    def call(self, cid, rid, input_tokens=100, cached=0, **extra):
        fields = dict(game_id="g", call_id=cid, request_id=rid, provider="fireworks",
                      transport="fireworks_chat_completions", requested_model="A",
                      prompt_layout_version="prompt_layout_v2", status="completed",
                      input_tokens=input_tokens, cached_input_tokens=cached)
        fields.update(extra)
        return ModelCall(**fields)

    def import_calls(self, calls):
        sidecar = self.root / "usage.ndjson"
        sidecar.write_text("\n".join(json.dumps(c.to_row()) for c in calls))
        import_usage_sidecar(self.conn, "g", sidecar)
        self.conn.commit()

    def test_selection_cohort_failed_usage_and_native_layout_linkage(self):
        for seq in range(1, 7):
            self.request("r" + str(seq), seq, "older" if seq == 5 else "prompt_layout_v2")
        self.import_calls([
            self.call("c1", "r1", 1000, 0), self.call("c2", "r2", 1200, 800, status="failed"),
            self.call("c3", "r3", 900, None), self.call("c4", "r4", 100000, 100000, requested_model="B"),
            self.call("c5", "r5", 200000, 200000, prompt_layout_version="older"),
            self.call("c6", "r6", 10, 0, provider="codex_native", transport="codex_host_session", prompt_layout_version=None)])
        before = self.db.read_bytes()
        result = report_sqlite(self.db, "g", model="A", layout="prompt_layout_v2")
        self.assertEqual(before, self.db.read_bytes())
        self.assertEqual(result["cache_usage"]["physical_calls"], 4)
        groups = result["cache_usage"]["groups"]
        self.assertEqual(len(groups), 2)
        api = next(g["usage"] for g in groups if g["transport"] == "fireworks_chat_completions")
        self.assertEqual(api["physical_calls"], 3)
        self.assertEqual(api["measured_input_cache_calls"], 2)
        self.assertEqual(api["input_tokens_measured_cohort"], 2200)
        self.assertEqual(api["cached_input_tokens_measured_cohort"], 800)
        self.assertEqual(api["excluded_known_input_tokens"], 900)
        self.assertEqual(api["all_calls"]["input_tokens"]["sum"], 3100)
        self.assertAlmostEqual(api["cache_ratio"], 800 / 2200)
        self.assertIn("failed", api["all_calls"]["statuses"])
        self.assertIsNone(api["all_calls"]["reasoning_tokens"]["sum"])
        self.assertIsNone(api["all_calls"]["output_tokens"]["sum"])
        self.assertIsNone(result["cache_usage"]["later_requests"])
        native = next(c for c in result["calls"] if c["call_id"] == "c6")
        self.assertEqual(native["scope"], "native_host_session")
        self.assertEqual(native["prompt_layout_source"], "linked_harness_request")

    def test_every_unordered_call_is_visible_in_unknown_order_cohort(self):
        self.request("null-sequence", None)
        self.import_calls([self.call("c1", "null-sequence"), self.call("c2", "missing-request"), self.call("c3", None)])
        result = report_sqlite(self.db, "g")["cache_usage"]
        self.assertEqual(result["physical_calls"], 3)
        self.assertEqual(result["unknown_order"]["physical_calls"], 3)
        self.assertEqual(result["groups"][0]["usage"]["unknown_order"]["physical_calls"], 3)

    def test_multiple_calls_per_request_and_input_cache_conflicts(self):
        self.request("r1", 1)
        self.import_calls([
            self.call("c1", "r1", 100, 0), self.call("c2", "r1", 100, 101),
            self.call("c3", "r1", 100, 50, normalization_gaps=["conflict:input_tokens:100!=200"])])
        usage = report_sqlite(self.db, "g")["cache_usage"]
        self.assertEqual(usage["first_request"]["physical_calls"], 3)
        self.assertEqual(usage["excluded_conflicting_input_cache_calls"], 2)
        self.assertEqual(usage["measured_input_cache_calls"], 1)
        self.assertEqual(usage["cache_ratio"], 0)

    def test_unknown_usage_and_zero_denominator_are_not_zero_hit_rates(self):
        self.request("r1", 1)
        for input_tokens, cached in ((None, None), (0, 0)):
            with self.subTest(input_tokens=input_tokens):
                self.import_calls([self.call("c1", "r1", input_tokens, cached)])
                usage = report_sqlite(self.db, "g")["cache_usage"]
                self.assertIsNone(usage["cache_ratio"])
                self.assertIsNone(usage["all_calls"]["reasoning_tokens"]["sum"])

    def test_older_catalog_optional_columns_are_unknown_without_migration(self):
        self.request("r1", 1)
        self.import_calls([self.call("c1", "r1")])
        for table, fields in (("model_calls", ("prompt_layout_version", "requested_affinity", "prompt_layout_source")),
                              ("model_requests", ("prompt_layout_version", "fixed_prefix_sha256", "fixed_prefix_bytes"))):
            for field in fields:
                self.conn.execute(f"ALTER TABLE {table} DROP COLUMN {field}")
        self.conn.commit()
        before = self.db.read_bytes()
        result = report_sqlite(self.db, "g")
        self.assertEqual(before, self.db.read_bytes())
        self.assertIsNone(result["calls"][0]["layout"])
        self.assertIsNone(result["requests"][0]["fixed_prefix_bytes"])
        self.assertEqual(result["cache_usage"]["cache_ratio"], 0)
        with self.assertRaises(KeyError):
            report_sqlite(self.db, "absent-game")
        missing = self.root / "absent.sqlite"
        with self.assertRaises(FileNotFoundError):
            report_sqlite(missing, "g")
        self.assertFalse(missing.exists())


@unittest.skipUnless(DRIVER.is_file() and hasattr(os, "killpg"), "requires real driver and POSIX process groups")
class RoutingLifecycleAcceptanceTests(unittest.TestCase):
    def test_interrupted_dispatch_resume_fresh_branch_and_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend.py"
            backend.write_text(BACKEND)

            def command(run, mode, extra=()):
                run.mkdir(exist_ok=True)
                env = dict(os.environ, CACHE_TEST_RUN=str(run), CACHE_TEST_MODE=mode,
                           NORRUST_USAGE_SIDECAR=str(run / "usage.ndjson"),
                           NORRUST_REQUEST_CONTEXT_FILE=str(run / "request_context.json"),
                           PYTHONPATH=str(ROOT))
                args = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                        "--model-command", shlex.join([sys.executable, str(backend)]),
                        "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                        "--gold", "300", "--seed", "9101", "--llm-side", "0", "--max-turns", "1",
                        "--incremental-turns", "--log", str(run / "match.ndjson"),
                        "--disable-agenda-sweep", "--query-budget-seconds", "10",
                        "--model-timeout", "10", "--turn-timeout", "30",
                        "--max-output-tokens", "99", *extra]
                return args, env

            game = root / "game"
            args, env = command(game, "interrupt")
            with (game / "interrupted.stderr").open("w") as err:
                process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                                           stderr=err, start_new_session=True)
                try:
                    deadline = time.monotonic() + 15
                    while not (game / "dispatch-ready").exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue((game / "dispatch-ready").exists(), (game / "interrupted.stderr").read_text())
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=5)
            before = records(game / "usage.ndjson")
            self.assertEqual([r["record_kind"] for r in before], ["dispatch", "final", "dispatch"])
            checkpoint, _ = select_resume_checkpoint(game / "match.ndjson")

            args, env = command(game, "normal", ["--resume-log", str(game / "match.ndjson")])
            resumed = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(resumed.returncode, 0, resumed.stderr[-3000:])
            wire = [json.loads(p.read_text()) for p in sorted(game.glob("wire-*.json"))]
            self.assertEqual(len(wire), 3)
            affinity = wire[0]["headers"]["X-session-affinity"]
            self.assertEqual({w["headers"]["X-session-affinity"] for w in wire}, {affinity})
            archive = records(game / "match.ndjson")
            requests = [r for r in archive if r.get("type") == "model_request"]
            self.assertEqual(len(requests), 2)
            self.assertEqual(wire[0]["body"]["messages"], [{"role": "user", "content": requests[0]["prompt"]}])
            self.assertEqual(wire[2]["body"]["messages"], [{"role": "user", "content": requests[1]["prompt"]}])
            for item in wire:
                self.assertEqual(item["body"]["max_completion_tokens"], 99)
                self.assertEqual(item["body"]["model"], "fixture-model")
                self.assertNotIn("user", item["body"])

            for name, mode, extra in (("fresh", "normal", []),
                                      ("branch", "finish", ["--resume-checkpoint", checkpoint["absolute_path"]])):
                destination = root / name
                args, env = command(destination, mode, extra)
                done = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
                self.assertEqual(done.returncode, 0, done.stderr[-3000:])
                other = json.loads((destination / "wire-000.json").read_text())
                self.assertNotEqual(other["headers"]["X-session-affinity"], affinity)
                if name == "fresh":
                    self.assertEqual(other["body"], wire[0]["body"])

            db = game / "history.sqlite"
            conn = open_history(db)
            try:
                game_id = import_game(conn, game / "match.ndjson")
                conn.commit()
                calls = conn.execute("SELECT call_id,requested_affinity,prompt_layout_version,source_hash FROM model_calls WHERE game_id=?", (game_id,)).fetchall()
                self.assertEqual(len(calls), 3)
                self.assertEqual(len({c[0] for c in calls}), 3)
                self.assertEqual({c[1] for c in calls}, {affinity})
                self.assertEqual({c[2] for c in calls}, {"prompt_layout_v2"})
                self.assertEqual({c[3] for c in calls}, {hashlib.sha256(w["body"]["messages"][0]["content"].encode()).hexdigest() for w in wire})
                self.assertEqual(import_game(conn, game / "match.ndjson"), game_id)
                self.assertEqual(conn.execute("SELECT count(*) FROM model_calls WHERE game_id=?", (game_id,)).fetchone()[0], 3)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                conn.commit()
            finally:
                conn.close()
            report = report_sqlite(db, game_id, model="fixture-model", layout="prompt_layout_v2")
            usage = report["cache_usage"]
            self.assertEqual(usage["physical_calls"], 3)
            self.assertEqual(usage["measured_input_cache_calls"], 2)
            self.assertAlmostEqual(usage["cache_ratio"], .2)
            self.assertIsNone(usage["all_calls"]["reasoning_tokens"]["sum"])


if __name__ == "__main__":
    unittest.main()
