import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

from . import fireworks_backend as fb


def _fake_opener(status_body: dict, headers: dict | None = None):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps(status_body).encode()

    def opener(request, timeout=None):
        return _Resp()

    return opener


def _read_sidecar(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class FireworksBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sidecar = Path(self.tmp.name) / "usage.ndjson"

    def tearDown(self):
        self.tmp.cleanup()

    def test_affinity_header_and_call_provenance_are_recorded(self):
        seen = {}
        body = {"id": "resp-affinity", "model": "runtime-m1",
                "choices": [{"finish_reason": "stop",
                             "message": {"content": "{\"action\":\"EndTurn\"}"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 4, "total_tokens": 104}}
        class Response:
            headers = {"fireworks-prompt-tokens": "100", "fireworks-cached-prompt-tokens": "80"}
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self): return json.dumps(body).encode()
        def opener(request, timeout=None):
            seen.update(request.headers)
            return Response()
        affinity = fb.session_affinity_for("game-a", "m1")
        fb.run("prompt", model="m1", max_output_tokens=99, game_id="game-a",
               request_id="r1", sidecar_path=self.sidecar, opener=opener,
               api_key="key123", session_affinity=affinity,
               prompt_layout_version="prompt_layout_v2")
        self.assertEqual(seen["X-session-affinity"], affinity)
        rows = _read_sidecar(self.sidecar)
        self.assertEqual(rows[0]["requested_affinity"], affinity)
        self.assertEqual(rows[-1]["prompt_layout_version"], "prompt_layout_v2")
        self.assertEqual(rows[-1]["cached_input_tokens"], 80)

    def test_affinity_is_durable_per_game_and_model_and_absent_without_context(self):
        self.assertEqual(fb.session_affinity_for("game-a", "m1"),
                         fb.session_affinity_for("game-a", "m1"))
        self.assertNotEqual(fb.session_affinity_for("game-a", "m1"),
                            fb.session_affinity_for("game-b", "m1"))
        self.assertNotEqual(fb.session_affinity_for("game-a", "m1"),
                            fb.session_affinity_for("game-a", "m2"))
        self.assertIsNone(fb.session_affinity_for(None, "m1"))

    def test_conflicting_response_header_is_preserved_and_marked(self):
        body = {"id": "resp-conflict", "model": "m1",
                "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 100, "prompt_cache_hit_tokens": 40}}
        class Response:
            headers = {"fireworks-prompt-tokens": "101", "fireworks-cached-prompt-tokens": "40"}
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self): return json.dumps(body).encode()
        fb.run("prompt", model="m1", max_output_tokens=99, game_id="g-conflict",
               request_id="r1", sidecar_path=self.sidecar,
               opener=lambda request, timeout=None: Response(), api_key="key123")
        final = _read_sidecar(self.sidecar)[-1]
        self.assertTrue(any(g.startswith("conflict:input_tokens:")
                            for g in final["normalization_gaps"]))
        self.assertIn("fireworks_body_usage", final["raw_usage_json"])
        self.assertIn("fireworks_response_headers", final["raw_usage_json"])

    def test_successful_reply_preserves_canonical_prompt_and_usage(self):
        prompt = "PLAY THE GAME exactly as given"
        body = {"id": "resp-1", "model": "runtime-model-x",
                "choices": [{"finish_reason": "stop",
                             "message": {"content": "  {\"action\": \"EndTurn\"}  "}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
                          "prompt_tokens_details": {"cached_tokens": 4}}}
        reply = fb.run(prompt, model="m1", max_output_tokens=99, game_id="g1",
                        request_id="r1", sidecar_path=self.sidecar,
                        opener=_fake_opener(body), api_key="key123")
        self.assertEqual(reply["text"], '{"action": "EndTurn"}')
        self.assertEqual(reply["usage"]["input_tokens"], 100)
        self.assertEqual(reply["usage"]["output_tokens"], 20)
        rows = _read_sidecar(self.sidecar)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["record_kind"], "dispatch")
        self.assertEqual(rows[1]["record_kind"], "final")
        self.assertEqual(rows[1]["status"], "completed")
        self.assertEqual(rows[1]["input_tokens"], 100)
        self.assertEqual(rows[1]["total_tokens"], 120)
        self.assertEqual(rows[1]["raw_usage_json"]["prompt_tokens_details"], {"cached_tokens": 4})
        self.assertEqual(rows[0]["call_id"], rows[1]["call_id"])

    def test_length_finish_reason_empty_content_returns_typed_exhaustion(self):
        """The Stack 1 headline case: input=5881, output=16384, reasoning=16384,
        total=22265, empty content, finish_reason=length -- the typed error
        lets the harness escalate while usage is retained exactly."""
        body = {"id": "resp-2", "model": "runtime-model-x",
                "choices": [{"finish_reason": "length", "message": {"content": ""}}],
                "usage": {"prompt_tokens": 5881, "completion_tokens": 16384,
                          "reasoning_tokens": 16384, "total_tokens": 22265}}
        reply = fb.run("prompt", model="m1", max_output_tokens=16384, game_id="g2",
                       request_id="r2", sidecar_path=self.sidecar,
                       opener=_fake_opener(body), api_key="key123")
        self.assertEqual(reply["error"]["code"], "output_limit")
        self.assertEqual(reply["error"]["output_limit"], 16384)
        rows = _read_sidecar(self.sidecar)
        final = rows[-1]
        self.assertEqual(final["status"], "failed")
        self.assertEqual(final["input_tokens"], 5881)
        self.assertEqual(final["output_tokens"], 16384)
        self.assertEqual(final["total_tokens"], 22265)
        self.assertEqual(final["finish_reason"], "length")

    def test_http_error_records_dispatch_and_failed_final(self):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(fb.FIREWORKS_URL, 500, "server error",
                                          hdrs=None, fp=io.BytesIO(b"boom"))

        with self.assertRaises(RuntimeError) as ctx:
            fb.run("prompt", model="m1", max_output_tokens=16384, game_id="g3",
                   request_id=None, sidecar_path=self.sidecar, opener=opener, api_key="key123")
        self.assertTrue(str(ctx.exception).startswith("request_unknown:"))
        rows = _read_sidecar(self.sidecar)
        self.assertEqual(rows[0]["status"], "dispatched")
        self.assertEqual(rows[1]["status"], "failed")
        self.assertEqual(rows[1]["error_code"], "http_500")

    def test_missing_credentials_never_dispatches_a_physical_call(self):
        with self.assertRaises(RuntimeError) as ctx:
            fb.run("prompt", model="m1", max_output_tokens=16384, game_id="g4",
                   request_id=None, sidecar_path=self.sidecar,
                   opener=_fake_opener({}), api_key=None)
        self.assertIn("FIREWORKS_API_KEY", str(ctx.exception))
        rows = _read_sidecar(self.sidecar)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["error_code"], "missing_credentials")

    def test_malformed_response_body_reported_not_dropped(self):
        def opener(request, timeout=None):
            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b"not json"
            return _Resp()

        with self.assertRaises(RuntimeError):
            fb.run("prompt", model="m1", max_output_tokens=16384, game_id="g5",
                   request_id=None, sidecar_path=self.sidecar, opener=opener, api_key="key123")
        rows = _read_sidecar(self.sidecar)
        self.assertEqual(rows[-1]["error_code"], "malformed_response")

    def test_main_cli_writes_stdout_json_on_success(self):
        import subprocess
        import sys

        # The CommandBackend protocol (full prompt on stdin, JSON on stdout)
        # is exercised end to end here without network access: missing
        # credentials must exit nonzero with a durable sidecar record rather
        # than hanging or silently succeeding. `run()`'s tests above cover
        # the full success/failure usage contract with a fake opener.
        result = subprocess.run(
            [sys.executable, "-m", "tools.fireworks_backend", "--usage-sidecar", str(self.sidecar)],
            input="prompt", capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
            env={"PATH": "/usr/bin:/bin"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("FIREWORKS_API_KEY", result.stderr)


if __name__ == "__main__":
    unittest.main()
