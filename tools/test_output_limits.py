"""Output exhaustion, restart safety, and real harness/SQLite acceptance."""
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from . import fireworks_backend as fb
from .game_history import import_game, open_history
from .llm_client import CommandBackend
from .output_limits import (INITIAL_OUTPUT_LIMIT, MAX_OUTPUT_LIMIT, OutputLimitExceeded,
                            OutputLimitPolicy)

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


def exhausted(limit, call_id="c"):
    return {"text": '{"actions":[{"action":"EndTurn"}]}',
            "error": {"code": "output_limit", "output_limit": limit, "call_id": call_id},
            "usage": {"input_tokens": 10, "output_tokens": limit}}


class OutputLimitTests(unittest.TestCase):
    def test_ceiling_failure_count_survives_restore_and_does_not_reset_on_success(self):
        p = OutputLimitPolicy()
        events = []
        for limit in (INITIAL_OUTPUT_LIMIT, MAX_OUTPUT_LIMIT, MAX_OUTPUT_LIMIT):
            p.record_failure(OutputLimitExceeded(exhausted(limit)))
            events.append({"type": "model_output_limit", "conversation_id": "game", "policy": p.state()})
        restored = OutputLimitPolicy.restore(events, "game", INITIAL_OUTPUT_LIMIT)
        self.assertEqual(restored.ceiling_failures, 2)
        self.assertFalse(restored.exhausted)
        restored.record_failure(OutputLimitExceeded(exhausted(MAX_OUTPUT_LIMIT)))
        self.assertTrue(restored.exhausted)
        self.assertEqual(OutputLimitPolicy.restore(events, "branch", INITIAL_OUTPUT_LIMIT).output_limit,
                         INITIAL_OUTPUT_LIMIT)

    def test_restore_recovers_final_usage_written_before_client_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.ndjson"
            calls = [{"game_id": "g", "call_id": str(i), "record_kind": "final", "status": "failed",
                      "finish_reason": "length", "output_limit": MAX_OUTPUT_LIMIT} for i in range(3)]
            path.write_text("\n".join(json.dumps(c) for c in calls + calls) + '\n{"partial":')
            p = OutputLimitPolicy.restore([], "g", INITIAL_OUTPUT_LIMIT, path)
            self.assertTrue(p.exhausted)
            self.assertEqual(p.ceiling_failures, 3)
            self.assertFalse(OutputLimitPolicy.restore([], "fresh", INITIAL_OUTPUT_LIMIT, path).exhausted)

    def test_command_backend_does_not_transport_retry_output_exhaustion(self):
        response = subprocess.CompletedProcess("fake", 0, json.dumps(exhausted(INITIAL_OUTPUT_LIMIT)), "")
        with mock.patch("subprocess.run", return_value=response) as dispatch:
            backend = CommandBackend("fake", 1)
            with self.assertRaises(OutputLimitExceeded):
                backend.complete("unaltered prompt")
            self.assertEqual(dispatch.call_count, 1)
            self.assertEqual(backend.transport_retries, 0)

    def test_mismatched_backend_limit_stops_without_advancing_policy(self):
        p = OutputLimitPolicy()
        with self.assertRaisesRegex(RuntimeError, "model_output_limit_mismatch"):
            p.record_failure(OutputLimitExceeded(exhausted(16384)))
        self.assertEqual(p.output_limit, INITIAL_OUTPUT_LIMIT)
        self.assertEqual(p.ceiling_failures, 0)

    def test_invalid_limits_and_malformed_exhaustion_are_rejected(self):
        for value in (0, -1, True, MAX_OUTPUT_LIMIT + 1, "131072"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OutputLimitPolicy(value)
        with self.assertRaises(ValueError):
            OutputLimitExceeded({"error": {"code": "output_limit", "output_limit": INITIAL_OUTPUT_LIMIT}})

    def test_adapter_context_owns_limit_timeout_and_standalone_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            context = p / "context.json"
            context.write_text(json.dumps({"output_limit": MAX_OUTPUT_LIMIT,
                "model_timeout_seconds": 3600, "retry_of_call_id": "previous",
                "game_log": str(p / "match.ndjson")}))
            with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(fb, "run", return_value={"text": "[]"}) as run:
                with mock.patch("sys.stdin", io.StringIO("canonical")), mock.patch("sys.stdout"):
                    self.assertEqual(fb.main(["--request-context", str(context)]), 0)
                self.assertEqual(run.call_args.kwargs["max_output_tokens"], MAX_OUTPUT_LIMIT)
                self.assertEqual(run.call_args.kwargs["timeout"], 3595)
                self.assertEqual(run.call_args.kwargs["retry_of_call_id"], "previous")
                self.assertEqual(run.call_args.kwargs["sidecar_path"], p / "usage.ndjson")
                run.reset_mock()
                with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                    fb.main(["--request-context", str(context), "--max-output-tokens", "16384"])
                run.assert_not_called()
                with mock.patch("sys.stdin", io.StringIO("canonical")), mock.patch("sys.stdout"):
                    self.assertEqual(fb.main([]), 0)
                self.assertEqual(run.call_args.kwargs["max_output_tokens"], INITIAL_OUTPUT_LIMIT)

    def test_truncated_valid_json_is_not_success_and_retry_link_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.ndjson"
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self):
                    return json.dumps({"model": "m", "choices": [{"finish_reason": "length",
                        "message": {"content": exhausted(1)["text"]}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": MAX_OUTPUT_LIMIT}}).encode()
            reply = fb.run("prompt", model="m", max_output_tokens=MAX_OUTPUT_LIMIT,
                           game_id="g", request_id="r", sidecar_path=path,
                           retry_of_call_id="earlier", opener=lambda *a, **kw: Response(), api_key="fake")
            self.assertEqual(reply["error"]["code"], "output_limit")
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertTrue(all(r["retry_of_call_id"] == "earlier" for r in rows))
            self.assertEqual(rows[-1]["status"], "failed")
            self.assertEqual(rows[-1]["error_code"], "output_limit")


BACKEND = '''import json,os,pathlib,sys,io,urllib.error
from tools import fireworks_backend as fb
p=pathlib.Path(os.environ['OUTPUT_TEST_RUN'])
def opener(request,timeout=None):
    body=json.loads(request.data)
    wires=p/'wire.ndjson'
    index=len(wires.read_text().splitlines()) if wires.exists() else 0
    with wires.open('a') as out:out.write(json.dumps(body)+'\\n')
    plan=json.loads((p/'responses.json').read_text())
    mode=plan[min(index,len(plan)-1)]
    if mode=='error':raise urllib.error.HTTPError(fb.FIREWORKS_URL,400,'unsupported limit',None,io.BytesIO(b'unsupported'))
    content=({'actions':[{'action':'Move','unit_id':1,'col':3,'row':7}]} if mode=='partial'
             else {'actions':[{'action':'EndTurn' if mode=='length' else 'Resign'}]})
    response={'id':str(index),'model':'different-model' if mode=='mismatch' else body['model'],
              'choices':[{'finish_reason':'length' if mode in ('length','mismatch') else 'stop',
                          'message':{'content':json.dumps(content)}}],
              'usage':{'prompt_tokens':100,'completion_tokens':body['max_completion_tokens'] if mode=='length' else 10,
                       'prompt_tokens_details':{'cached_tokens':20}}}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps(response).encode()
    return Response()
original=fb.run
def run(*a,**kw):
    kw.update(opener=opener,api_key='offline-key')
    return original(*a,**kw)
fb.run=run
raise SystemExit(fb.main(['--model','fixture']))
'''


@unittest.skipUnless(DRIVER.is_file(), "requires real driver")
class OutputLimitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.backend = self.path / "backend.py"
        self.backend.write_text(BACKEND)
        self.log = self.path / "match.ndjson"

    def tearDown(self):
        self.temp.cleanup()

    def run_game(self, responses, extra=()):
        (self.path / "responses.json").write_text(json.dumps(responses))
        command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                   "--model-command", shlex.join([sys.executable, str(self.backend)]),
                   "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                   "--gold", "300", "--seed", "9101", "--llm-side", "0", "--max-turns", "1",
                   "--incremental-turns", "--disable-agenda-sweep", "--model-timeout", "10",
                   "--turn-timeout", "30", "--query-budget-seconds", "10",
                   "--log", str(self.log), *extra]
        env = dict(os.environ, OUTPUT_TEST_RUN=str(self.path), PYTHONPATH=str(ROOT),
                   NORRUST_REQUEST_CONTEXT_FILE=str(self.path / "request_context.json"),
                   NORRUST_USAGE_SIDECAR=str(self.path / "usage.ndjson"))
        return subprocess.run(command, env=env, cwd=ROOT, capture_output=True, text=True, timeout=30)

    def records(self, name):
        return [json.loads(line) for line in (self.path / name).read_text().splitlines()]

    def test_escalation_success_preserves_prompt_and_imports_all_physical_usage(self):
        result = self.run_game(["length", "stop"])
        self.assertEqual(result.returncode, 0, result.stderr)
        wires = self.records("wire.ndjson")
        self.assertEqual([w["max_completion_tokens"] for w in wires], [INITIAL_OUTPUT_LIMIT, MAX_OUTPUT_LIMIT])
        self.assertEqual(wires[0]["messages"], wires[1]["messages"])
        self.assertEqual(wires[0]["messages"][0]["role"], "user")
        rows = self.records("match.ndjson")
        self.assertEqual(sum(r.get("type") == "forwarded_orders" for r in rows), 1)
        requests = [r for r in rows if r.get("type") == "model_request"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["usage"]["output_tokens"], INITIAL_OUTPUT_LIMIT + 10)
        db = self.path / "history.sqlite"
        conn = open_history(db)
        game = import_game(conn, self.log)
        conn.commit()
        calls = conn.execute("SELECT call_id,request_id,retry_of_call_id,output_limit FROM model_calls ORDER BY rowid").fetchall()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][2], calls[0][0])
        self.assertEqual(calls[1][1], calls[0][1])
        self.assertEqual(conn.execute("SELECT SUM(output_tokens) FROM model_calls").fetchone()[0], INITIAL_OUTPUT_LIMIT + 10)
        self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        import_game(conn, self.log)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0], 2)
        conn.close()

    def test_three_ceiling_failures_stop_even_across_requests_and_resume(self):
        result = self.run_game(["length", "length", "partial", "length", "length"])
        self.assertEqual(result.returncode, 1, result.stderr)
        wires = self.records("wire.ndjson")
        self.assertEqual([w["max_completion_tokens"] for w in wires], [INITIAL_OUTPUT_LIMIT] + [MAX_OUTPUT_LIMIT] * 4)
        rows = self.records("match.ndjson")
        self.assertEqual(sum(r.get("type") == "forwarded_orders" for r in rows), 1)
        failures = [r for r in rows if r.get("type") == "model_output_limit"]
        self.assertEqual([r["policy"]["ceiling_failures"] for r in failures], [0, 1, 2, 3])
        resumed = self.run_game(["stop"], ["--resume-log", str(self.log)])
        self.assertEqual(resumed.returncode, 1, resumed.stderr)
        self.assertEqual(len(self.records("wire.ndjson")), 5)
        self.assertIn("model_output_limit_exhausted", self.log.read_text())

    def test_explicit_spending_limit_stops_before_escalated_dispatch(self):
        result = self.run_game(["length"], ["--token-output-limit", "100"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.records("wire.ndjson")), 1)
        self.assertIn("output token limit exceeded", self.log.read_text())

    def test_provider_rejecting_large_limit_stops_without_clamping_or_transport_retry(self):
        result = self.run_game(["length", "error"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual([w["max_completion_tokens"] for w in self.records("wire.ndjson")],
                         [INITIAL_OUTPUT_LIMIT, MAX_OUTPUT_LIMIT])
        finals = [r for r in self.records("usage.ndjson") if r.get("record_kind") == "final"]
        self.assertEqual(finals[-1]["error_code"], "http_400")
        self.assertEqual(finals[-1]["retry_of_call_id"], finals[0]["call_id"])
        requests = [r for r in self.records("match.ndjson") if r.get("type") == "model_request"]
        self.assertIsNone(requests[-1].get("usage"))

    def test_runtime_identity_failure_prevents_expensive_output_retry(self):
        result = self.run_game(["mismatch"])
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.records("wire.ndjson")), 1)
        self.assertIn("runtime model mismatch", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
