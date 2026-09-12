import io
import json
import hashlib
import http.client
import http.server
import os
import shlex
import socketserver
import subprocess
import sys
import tempfile
import threading
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


class _StreamResponse:
    headers = {}

    def __init__(self, chunks: list[bytes]):
        self.chunks = iter(chunks)

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def read1(self, size):
        try:
            return next(self.chunks)
        except StopIteration:
            return b""


def _sse(*events: str) -> bytes:
    return "".join(f"data: {event}\n\n" for event in events).encode("utf-8")


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

    def test_omitted_reasoning_effort_payload_is_byte_identical_to_default(self):
        """Item 5: the authorized retest keeps provider-default effort, so an
        omitted option must send exactly today's payload -- no new key at
        all, not even a null placeholder."""
        body = {"id": "resp-default", "model": "m1",
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        seen: dict = {}

        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read(self): return json.dumps(body).encode()

        def opener(request, timeout=None):
            seen["data"] = request.data
            return Response()

        fb.run("prompt", model="m1", max_output_tokens=99, game_id="g-default",
               request_id="r-default", sidecar_path=self.sidecar, opener=opener,
               api_key="key123")
        payload = json.loads(seen["data"])
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload, {
            "model": "m1", "messages": [{"role": "user", "content": "prompt"}],
            "stream": False, "max_completion_tokens": 99,
            "context_length_exceeded_behavior": "error"})
        rows = _read_sidecar(self.sidecar)
        self.assertIsNone(rows[-1]["requested_reasoning_effort"])
        self.assertIsNone(rows[-1]["reported_reasoning_effort"])

    def test_each_supported_reasoning_effort_is_sent_exactly_once(self):
        body = {"id": "resp-effort", "model": "m1",
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
        for effort in fb.SUPPORTED_REASONING_EFFORTS:
            with self.subTest(effort=effort):
                seen: dict = {}

                class Response:
                    headers = {}
                    def __enter__(self): return self
                    def __exit__(self, *exc): return False
                    def read(self): return json.dumps(body).encode()

                def opener(request, timeout=None, _seen=seen):
                    _seen["data"] = request.data
                    return Response()

                reply = fb.run("prompt", model="m1", max_output_tokens=99,
                               game_id="g-effort", request_id="r-effort-" + effort,
                               sidecar_path=self.sidecar, opener=opener, api_key="key123",
                               reasoning_effort=effort)
                payload = json.loads(seen["data"])
                self.assertEqual(payload["reasoning_effort"], effort)
                self.assertEqual(payload["reasoning_effort"], payload.get("reasoning_effort"))
                self.assertEqual(reply["cache"]["requested_reasoning_effort"], effort)
                # Provider response schema carries no field reporting the
                # effort actually applied (verified 2026-09-11); never claim
                # a runtime effort the provider did not report.
                self.assertIsNone(reply["cache"]["runtime_reasoning_effort"])
                rows = _read_sidecar(self.sidecar)
                self.assertEqual(rows[-1]["requested_reasoning_effort"], effort)
                self.assertIsNone(rows[-1]["reported_reasoning_effort"])

    def test_unsupported_reasoning_effort_rejected_before_any_network_call(self):
        def opener(request, timeout=None):
            raise AssertionError("an unsupported effort must never reach the network")

        with self.assertRaises(fb.UnsupportedReasoningEffort):
            fb.run("prompt", model="m1", max_output_tokens=99, game_id="g-bad",
                   request_id="r-bad", sidecar_path=self.sidecar, opener=opener,
                   api_key="key123", reasoning_effort="medium")
        # Nothing was dispatched: not even a "dispatch" sidecar line exists,
        # since the rejection happens before ModelCall allocation.
        self.assertFalse(self.sidecar.exists())

    def test_stream_payload_reasoning_effort_matches_nonstream(self):
        payload_without = fb._stream_payload("m1", "prompt", 99)
        self.assertNotIn("reasoning_effort", payload_without)
        payload_with = fb._stream_payload("m1", "prompt", 99, "low")
        self.assertEqual(payload_with["reasoning_effort"], "low")

    def test_cli_reads_reasoning_effort_from_request_context(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.json"
            context_path.write_text(json.dumps({"requested_reasoning_effort": "high"}))
            result = subprocess.run(
                [sys.executable, "-m", "tools.fireworks_backend",
                 "--usage-sidecar", str(self.sidecar),
                 "--request-context", str(context_path)],
                input="prompt", capture_output=True, text=True,
                cwd=str(Path(__file__).resolve().parents[1]),
                env={"PATH": "/usr/bin:/bin"})
            self.assertEqual(result.returncode, 1)
            self.assertIn("FIREWORKS_API_KEY", result.stderr)
            # Rejected for missing credentials, not for the effort value --
            # proves the context value was accepted as a supported setting.
            self.assertNotIn("unsupported reasoning_effort", result.stderr)

    def test_cli_rejects_unsupported_reasoning_effort_before_missing_credentials(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "tools.fireworks_backend",
             "--usage-sidecar", str(self.sidecar), "--reasoning-effort", "medium"],
            input="prompt", capture_output=True, text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
            env={"PATH": "/usr/bin:/bin"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported reasoning_effort", result.stderr)
        self.assertNotIn("FIREWORKS_API_KEY", result.stderr)

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

    def test_nonstream_incomplete_read_and_http_exception_record_partial_failure(self):
        for error, partial in (
                (http.client.IncompleteRead(b'{"choices":['), b'{"choices":['),
                (http.client.HTTPException("connection reset"), b"")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                evidence = Path(directory) / "evidence"

                class Response:
                    headers = {}
                    def __enter__(self): return self
                    def __exit__(self, *exc): return False
                    def read(self): raise error

                with self.assertRaisesRegex(RuntimeError, "request_unknown"):
                    fb.run("prompt", model="m1", max_output_tokens=99, game_id="read-error",
                           request_id="r-read-error", sidecar_path=self.sidecar,
                           opener=lambda *a, **k: Response(), api_key="key123",
                           evidence_dir=evidence)
                rows = _read_sidecar(self.sidecar)
                final = rows[-1]
                self.assertEqual(final["status"], "failed")
                self.assertEqual(final["error_code"], "transport_error")
                receipt = json.loads(next(evidence.glob("*/incomplete.json")).read_text())
                self.assertEqual(receipt["partial_bytes"], len(partial))
                self.assertEqual(receipt["partial_body"], partial.decode())

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

    def test_stream_assembles_fragmented_utf8_reasoning_and_empty_usage_chunk(self):
        prompt = "canonical prompt ✓"
        body = b": keepalive\n\n" + _sse(
            json.dumps({"id": "resp-stream", "model": "runtime-stream",
                        "choices": [{"delta": {"reasoning_content": "reason "},
                                      "finish_reason": None}]}),
            json.dumps({"choices": [{"delta": {"content": "hé"}, "finish_reason": None}],
                        }, ensure_ascii=False),
            json.dumps({"choices": [{"delta": {"content": "llo"}, "finish_reason": "stop"}]}),
            json.dumps({"choices": [], "usage": {"prompt_tokens": 7,
                                                    "completion_tokens": 4,
                                                    "total_tokens": 11}}),
            "[DONE]",
        )
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            marker = "é".encode("utf-8")
            marker_at = body.index(marker)
            split = [body[:marker_at + 1], body[marker_at + 1:marker_at + 2],
                     body[marker_at + 2:]]
            response = _StreamResponse(split)
            response.headers = {"fireworks-prompt-tokens": "8",
                                "fireworks-cached-prompt-tokens": "3"}
            reply = fb.run(prompt, model="m1", max_output_tokens=99, game_id="gs",
                           request_id="rs", sidecar_path=self.sidecar,
                           opener=lambda request, timeout=None: response, api_key="key123",
                           stream=True, evidence_dir=evidence,
                           request_context={"harness_request_id": "rs", "output_limit": 99})
            self.assertEqual(reply["text"], "héllo")
            self.assertEqual(reply["usage"], {"input_tokens": 7, "cached_input_tokens": 3,
                                               "cache_write_input_tokens": None,
                                               "output_tokens": 4, "reasoning_tokens": None,
                                               "total_tokens": 11})
            payload = json.loads(next(evidence.glob("*/payload.json")).read_text())
            self.assertTrue(payload["stream"])
            self.assertEqual(payload["stream_options"], {"include_usage": True})
            call_dir = next(evidence.iterdir())
            self.assertEqual((call_dir / "prompt.txt").read_text(), prompt)
            self.assertEqual((call_dir / "prompt.sha256").read_text().strip(),
                             hashlib.sha256(prompt.encode()).hexdigest())
            self.assertEqual(json.loads((call_dir / "request_context.json").read_text())["harness_request_id"], "rs")
            self.assertTrue((call_dir / "completed.json").is_file())
            self.assertEqual(len((call_dir / "chunks.ndjson").read_text().splitlines()), 3)
            final = _read_sidecar(self.sidecar)[-1]
            self.assertEqual(final["provider_response_id"], "resp-stream")
            self.assertTrue(any(g.startswith("conflict:input_tokens:")
                                for g in final["normalization_gaps"]))

    def test_stream_and_nonstream_have_equivalent_content_and_usage(self):
        prompt = "same canonical prompt"
        response_body = {"id": "same", "model": "m1",
                         "choices": [{"finish_reason": "stop",
                                      "message": {"content": "response ✓"}}],
                         "usage": {"prompt_tokens": 10, "completion_tokens": 3,
                                   "total_tokens": 13}}
        streamed = _sse(
            json.dumps({"id": "same", "model": "m1",
                        "choices": [{"delta": {"content": "response ✓"},
                                      "finish_reason": "stop"}]}),
            json.dumps({"choices": [], "usage": response_body["usage"]}), "[DONE]")
        with tempfile.TemporaryDirectory() as directory:
            stream_evidence = Path(directory) / "stream"
            streamed_reply = fb.run(prompt, model="m1", max_output_tokens=99, game_id="gs",
                                    request_id="rs", sidecar_path=self.sidecar,
                                    opener=lambda *a, **k: _StreamResponse([streamed]), api_key="key123",
                                    stream=True, evidence_dir=stream_evidence)
            plain_reply = fb.run(prompt, model="m1", max_output_tokens=99, game_id="gn",
                                 request_id="rn", sidecar_path=self.sidecar,
                                 opener=_fake_opener(response_body), api_key="key123")
            self.assertEqual(streamed_reply["text"], plain_reply["text"])
            self.assertEqual(streamed_reply["usage"], plain_reply["usage"])
            self.assertEqual(next(stream_evidence.glob("*/prompt.sha256")).read_text().strip(),
                             hashlib.sha256(prompt.encode()).hexdigest())

    def test_stream_failures_preserve_partial_evidence_and_never_return_text(self):
        cases = [
            ("malformed", b"data: {bad}\n\n", "stream_incomplete"),
            ("missing_done", _sse(json.dumps({"choices": [{"delta": {"content": "partial"},
                                                              "finish_reason": "stop"}]}),),
             "stream_missing_done"),
            ("missing_finish", _sse(json.dumps({"choices": [{"delta": {"content": "partial"},
                                                                "finish_reason": None}]}), "[DONE]"),
             "stream_missing_finish"),
            ("interrupted_with_usage", _sse(
                json.dumps({"choices": [{"delta": {"content": "partial"},
                                           "finish_reason": "stop"}]}),
                json.dumps({"choices": [], "usage": {"prompt_tokens": 8,
                                                        "completion_tokens": 1,
                                                        "total_tokens": 9}})),
             "stream_missing_done"),
        ]
        for name, body, expected_code in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                evidence = Path(directory) / "evidence"
                with self.assertRaisesRegex(RuntimeError, "request_unknown"):
                    fb.run("prompt", model="m1", max_output_tokens=99, game_id=name,
                           request_id=name, sidecar_path=self.sidecar,
                           opener=lambda *a, body=body, **k: _StreamResponse([body]), api_key="key123",
                           stream=True, evidence_dir=evidence,
                           retry_of_call_id="earlier" if name == "interrupted_with_usage" else None)
                call_dir = next(evidence.iterdir())
                receipt = json.loads((call_dir / "incomplete.json").read_text())
                self.assertEqual(receipt["error_code"], expected_code)
                self.assertFalse((call_dir / "completed.json").exists())
                if name == "interrupted_with_usage":
                    self.assertEqual(receipt["usage"]["prompt_tokens"], 8)
                    self.assertEqual(_read_sidecar(self.sidecar)[-1]["retry_of_call_id"], "earlier")

    def test_stream_length_is_typed_exhaustion_and_http504_is_unknown_once(self):
        body = _sse(json.dumps({"id": "length", "choices": [{"delta": {"content": "{}"},
                                                                  "finish_reason": "length"}]}),
                    json.dumps({"choices": [], "usage": {"prompt_tokens": 2,
                                                            "completion_tokens": 99,
                                                            "total_tokens": 101}}), "[DONE]")
        reply = fb.run("prompt", model="m1", max_output_tokens=99, game_id="length",
                       request_id="rl", sidecar_path=self.sidecar,
                       opener=lambda *a, **k: _StreamResponse([body]), api_key="key123", stream=True)
        self.assertEqual(reply["error"]["code"], "output_limit")
        before = len(_read_sidecar(self.sidecar))
        def fail504(request, timeout=None):
            raise urllib.error.HTTPError(fb.FIREWORKS_URL, 504, "gateway timeout", None,
                                          io.BytesIO(b"timeout"))
        with self.assertRaisesRegex(RuntimeError, "HTTP 504"):
            fb.run("prompt", model="m1", max_output_tokens=99, game_id="http504",
                   request_id="r504", sidecar_path=self.sidecar, opener=fail504,
                   api_key="key123", stream=True)
        rows = _read_sidecar(self.sidecar)
        self.assertEqual(len(rows), before + 2)
        self.assertEqual(rows[-1]["error_code"], "http_504")

    def test_stream_rejects_multiple_choices_and_nonobject_delta(self):
        cases = [
            json.dumps({"choices": [{"delta": {"content": "a"}},
                                     {"delta": {"content": "b"}}]}),
            json.dumps({"choices": [{"delta": "invalid"}]}),
        ]
        for body in cases:
            with self.subTest(body=body):
                with self.assertRaisesRegex(RuntimeError, "request_unknown"):
                    fb.run("prompt", model="m1", max_output_tokens=99, game_id="shape",
                           request_id="shape", sidecar_path=self.sidecar,
                           opener=lambda *a, body=body, **k: _StreamResponse([_sse(body)]),
                           api_key="key123", stream=True)

    def test_nonstream_rejects_multiple_choices(self):
        body = {"choices": [
            {"finish_reason": "stop", "message": {"content": "first"}},
            {"finish_reason": "stop", "message": {"content": "second"}},
        ]}
        with self.assertRaisesRegex(RuntimeError, "request_unknown"):
            fb.run("prompt", model="m1", max_output_tokens=99, game_id="multi-choice",
                   request_id="multi-choice", sidecar_path=self.sidecar,
                   opener=_fake_opener(body), api_key="key123")
        self.assertEqual(_read_sidecar(self.sidecar)[-1]["error_code"], "malformed_response")

    def test_stream_rejects_choice_data_after_finish(self):
        body = _sse(
            json.dumps({"choices": [{"delta": {"content": "["},
                                       "finish_reason": None}]}),
            json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
            json.dumps({"choices": [{"delta": {"content": "{\"action\":\"EndTurn\"}]"},
                                       "finish_reason": None}]}),
        )
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            with self.assertRaisesRegex(RuntimeError, "request_unknown"):
                fb.run("prompt", model="m1", max_output_tokens=99, game_id="late-choice",
                       request_id="late-choice", sidecar_path=self.sidecar,
                       opener=lambda *a, **k: _StreamResponse([body]), api_key="key123",
                       stream=True, evidence_dir=evidence)
            receipt = json.loads(next(evidence.glob("*/incomplete.json")).read_text())
            self.assertEqual(receipt["error_code"], "stream_incomplete")
            self.assertEqual(receipt["content"], "[")
            self.assertNotIn("EndTurn", receipt["content"])

    def test_stream_incomplete_read_is_unknown_with_partial_receipt(self):
        class Interrupted:
            headers = {}
            def __init__(self):
                self.first = True
            def __enter__(self): return self
            def __exit__(self, *exc): return False
            def read1(self, size):
                if self.first:
                    self.first = False
                    return _sse(json.dumps({"choices": [{"delta": {"content": "partial"},
                                                           "finish_reason": None}]}))
                raise http.client.IncompleteRead(b"data: {")

        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            with self.assertRaisesRegex(RuntimeError, "request_unknown"):
                fb.run("prompt", model="m1", max_output_tokens=99, game_id="read-error",
                       request_id="r-read-error", sidecar_path=self.sidecar,
                       opener=lambda *a, **k: Interrupted(), api_key="key123", stream=True,
                       evidence_dir=evidence)
            receipt = json.loads(next(evidence.glob("*/incomplete.json")).read_text())
            self.assertEqual(receipt["error_code"], "transport_error")
            self.assertEqual(receipt["content"], "partial")

    def test_stream_missing_credentials_is_blocked_without_a_physical_call(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence"
            with self.assertRaisesRegex(RuntimeError, "FIREWORKS_API_KEY"):
                fb.run("prompt", model="m1", max_output_tokens=99, game_id="blocked",
                       request_id="rb", sidecar_path=self.sidecar,
                       opener=lambda *a, **k: self.fail("network called"), api_key=None,
                       stream=True, evidence_dir=evidence)
            receipt = next(evidence.glob("*/incomplete.json"))
            self.assertFalse(json.loads(receipt.read_text())["physical_call"])


@unittest.skipUnless((Path(__file__).resolve().parents[1] /
                      "norrust_core/target/debug/greedy_driver").is_file(),
                     "requires real driver")
class FireworksStreamDriverIntegrationTests(unittest.TestCase):
    def test_real_client_streams_once_and_submits_only_complete_reply(self):
        received: list[dict] = []
        response = _sse(
            json.dumps({"id": "local-stream",
                        "choices": [{"delta": {"content": "[{\"action\":\"EndTurn\"}]"},
                                      "finish_reason": "stop"}]}),
            json.dumps({"choices": [], "usage": {"prompt_tokens": 11,
                                                    "completion_tokens": 4,
                                                    "total_tokens": 15}}), "[DONE]")

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers["Content-Length"])
                received.append(json.loads(self.rfile.read(size)))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in (response[:13], response[13:]):
                    self.wfile.write(chunk)
                    self.wfile.flush()

            def log_message(self, *args):
                pass

        server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            root = Path(__file__).resolve().parents[1]
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                log = path / "match.ndjson"
                evidence = path / "evidence"
                command = [sys.executable, "-m", "tools.llm_client",
                           "--driver", str(root / "norrust_core/target/debug/greedy_driver"),
                           "--model-command", shlex.join([sys.executable, "-m",
                                                           "tools.fireworks_backend", "--stream"]),
                           "--scenario", "big_battle_6", "--faction0", "undead",
                           "--faction1", "undead", "--llm-side", "0", "--max-turns", "1",
                           "--incremental-turns", "--disable-agenda-sweep", "--model-timeout", "10",
                           "--turn-timeout", "30", "--query-budget-seconds", "10", "--log", str(log)]
                env = dict(os.environ, PYTHONPATH=str(root), FIREWORKS_API_KEY="local-key",
                           NORRUST_FIREWORKS_URL=f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                           NORRUST_EVIDENCE_DIR=str(evidence))
                result = subprocess.run(command, cwd=root, env=env, text=True,
                                        capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0,
                                 f"rc={result.returncode} stderr={result.stderr!r} stdout={result.stdout!r} requests={len(received)} "
                                 f"log={log.read_text() if log.exists() else '<missing>'}")
                self.assertGreaterEqual(len(received), 1)
                self.assertTrue(all(request["stream"] for request in received))
                self.assertTrue(all(request["stream_options"] == {"include_usage": True}
                                    for request in received))
                records = [json.loads(line) for line in (path / "usage.ndjson").read_text().splitlines()]
                self.assertEqual(sum(record["record_kind"] == "dispatch" for record in records), len(received))
                self.assertEqual(sum(record["record_kind"] == "final" for record in records), len(received))
                self.assertEqual(len(list(evidence.glob("*/completed.json"))), len(received))
                log_rows = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertFalse(any(row.get("type") == "model_error" for row in log_rows))
                self.assertFalse(any(row.get("code") == "invalid_request" for row in log_rows))
                self.assertEqual(next(row for row in log_rows if row.get("type") == "terminal")
                                 ["model_orders"], 1)
        finally:
            server.shutdown()
            server.server_close()

    def test_real_client_discards_valid_but_incomplete_stream_and_preserves_once(self):
        for include_usage in (False, True):
            with self.subTest(include_usage=include_usage):
                received: list[dict] = []
                events = [json.dumps({"id": "local-incomplete",
                                      "choices": [{"delta": {
                                          "content": "[{\"action\":\"EndTurn\"}]"},
                                                   "finish_reason": "stop"}]})]
                if include_usage:
                    events.append(json.dumps({"choices": [], "usage": {
                        "prompt_tokens": 13, "completion_tokens": 4, "total_tokens": 17}}))
                response = _sse(*events)  # Deliberately omit data: [DONE].

                class Handler(http.server.BaseHTTPRequestHandler):
                    def do_POST(self):
                        size = int(self.headers["Content-Length"])
                        received.append(json.loads(self.rfile.read(size)))
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        self.wfile.write(response)
                        self.wfile.flush()

                    def log_message(self, *args):
                        pass

                server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    root = Path(__file__).resolve().parents[1]
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory)
                        log = path / "match.ndjson"
                        evidence = path / "evidence"
                        command = [sys.executable, "-m", "tools.llm_client",
                                   "--driver", str(root / "norrust_core/target/debug/greedy_driver"),
                                   "--model-command", shlex.join([sys.executable, "-m",
                                                                   "tools.fireworks_backend", "--stream"]),
                                   "--scenario", "big_battle_6", "--faction0", "undead",
                                   "--faction1", "undead", "--llm-side", "0", "--max-turns", "1",
                                   "--incremental-turns", "--disable-agenda-sweep", "--model-timeout", "10",
                                   "--turn-timeout", "30", "--query-budget-seconds", "10", "--log", str(log)]
                        env = dict(os.environ, PYTHONPATH=str(root), FIREWORKS_API_KEY="local-key",
                                   NORRUST_FIREWORKS_URL=f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions",
                                   NORRUST_EVIDENCE_DIR=str(evidence))
                        result = subprocess.run(command, cwd=root, env=env, text=True,
                                                capture_output=True, timeout=30)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(len(received), 1)
                        rows = [json.loads(line) for line in log.read_text().splitlines()]
                        terminal = next((row for row in rows if row.get("type") == "terminal"), None)
                        summary = terminal or next((row for row in reversed(rows)
                                                    if row.get("type") == "model_error"), {})
                        self.assertEqual(summary.get("model_orders", 0), 0,
                                         f"unexpected model order summary: {summary}")
                        self.assertFalse(any(row.get("line", {}).get("type") == "events"
                                             and row.get("line", {}).get("source") == "greedy"
                                             for row in rows if row.get("type") == "driver"))
                        records = [json.loads(line) for line in (path / "usage.ndjson").read_text().splitlines()]
                        self.assertEqual(len(records), 2)
                        self.assertEqual(records[0]["record_kind"], "dispatch")
                        self.assertEqual(records[1]["record_kind"], "final")
                        self.assertEqual(records[1]["status"], "failed")
                        self.assertEqual(records[1]["input_tokens"], 13 if include_usage else None)
                        incomplete = next(evidence.glob("*/incomplete.json"))
                        receipt = json.loads(incomplete.read_text())
                        self.assertEqual(receipt["error_code"], "stream_missing_done")
                        self.assertIn("EndTurn", receipt["content"])
                        self.assertEqual(receipt["usage"]["prompt_tokens"] if include_usage else None,
                                         13 if include_usage else None)
                finally:
                    server.shutdown()
                    server.server_close()


class ModelIdentityTests(unittest.TestCase):
    def test_verified_match(self):
        from .model_identity import classify_model_identity
        status, is_mismatch = classify_model_identity(
            "accounts/fireworks/models/qwen3p8-max",
            "accounts/fireworks/models/qwen3p8-max"
        )
        self.assertEqual(status, "verified_match")
        self.assertFalse(is_mismatch)

    def test_unverified_display_label(self):
        from .model_identity import classify_model_identity
        status, is_mismatch = classify_model_identity(
            "accounts/fireworks/models/qwen3p8-max",
            "Qwen 3.8 Max"
        )
        self.assertEqual(status, "unverified_label")
        self.assertFalse(is_mismatch)

    def test_unverified_leaf_slug(self):
        from .model_identity import classify_model_identity
        status, is_mismatch = classify_model_identity(
            "accounts/fireworks/models/qwen3p8-max",
            "qwen3p8-max"
        )
        self.assertEqual(status, "unverified_label")
        self.assertFalse(is_mismatch)

    def test_conflicting_canonical_id(self):
        from .model_identity import classify_model_identity
        status, is_mismatch = classify_model_identity(
            "accounts/fireworks/models/qwen3p8-max",
            "accounts/fireworks/models/llama-v3p3-70b-instruct"
        )
        self.assertEqual(status, "conflicting_canonical_id")
        self.assertTrue(is_mismatch)

    def test_missing_identity(self):
        from .model_identity import classify_model_identity
        status, is_mismatch = classify_model_identity(None, "qwen3p8-max")
        self.assertEqual(status, "unknown")
        self.assertFalse(is_mismatch)
        status, is_mismatch = classify_model_identity("qwen3p8-max", "")
        self.assertEqual(status, "unknown")
        self.assertFalse(is_mismatch)


if __name__ == "__main__":
    unittest.main()
