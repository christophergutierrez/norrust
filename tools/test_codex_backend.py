import json
import io
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

from . import codex_backend


class CodexBackendTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"NORRUST_CODEX_MODEL": "test-model"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_model_is_required_and_effort_is_configurable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "NORRUST_CODEX_MODEL is required"):
                codex_backend.resolved_settings()
        self.assertEqual(codex_backend.resolved_settings(), ("test-model", "high"))
        with patch.dict(os.environ, {"NORRUST_CODEX_REASONING_EFFORT": "medium"}):
            self.assertEqual(codex_backend.resolved_settings(), ("test-model", "medium"))
        with patch.dict(os.environ, {"NORRUST_CODEX_REASONING_EFFORT": ""}):
            with self.assertRaisesRegex(RuntimeError, "must not be empty"):
                codex_backend.resolved_settings()

    def test_configured_model_is_recorded_without_inventing_runtime_confirmation(self):
        events = '\n'.join(json.dumps(event) for event in [
            {"type": "thread.started", "thread_id": "thread-configured"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "[]"}},
            {"type": "turn.completed"},
        ])

        class Process:
            returncode = 0
            def communicate(self, timeout):
                self.timeout = timeout
                return events, ""

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            process = Process()
            settings = {"NORRUST_CODEX_MODEL": "test-alternate-model",
                        "NORRUST_CODEX_REASONING_EFFORT": "medium",
                        "NORRUST_CODEX_SESSION_FILE": str(root / "session.json"),
                        "NORRUST_CODEX_ARTIFACT_DIR": str(root / "evidence"),
                        "NORRUST_CODEX_MATCH_ID": "test-match", "NORRUST_CODEX_TIMEOUT": "31"}
            output = io.StringIO()
            with patch.dict(os.environ, settings, clear=True), \
                    patch.object(codex_backend.sys, "stdin", io.StringIO("canonical prompt\n")), \
                    patch.object(codex_backend.subprocess, "Popen", return_value=process) as popen, \
                    redirect_stdout(output):
                self.assertEqual(codex_backend.main(), 0)
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--model") + 1], "test-alternate-model")
            self.assertEqual(command[command.index("-c") + 1], "model_reasoning_effort=medium")
            session = json.loads((root / "session.json").read_text())
            self.assertEqual(session["requested_model"], "test-alternate-model")
            self.assertEqual(session["requested_reasoning_effort"], "medium")
            cache = json.loads(output.getvalue())["cache"]
            self.assertEqual(cache["requested_model"], "test-alternate-model")
            self.assertEqual(cache["requested_reasoning_effort"], "medium")
            self.assertIsNone(cache["runtime_model"])
            self.assertIsNone(cache["runtime_reasoning_effort"])
            self.assertEqual(process.timeout, 31)
            self.assertEqual((root / "evidence" / "00001-request.txt").read_text(), "canonical prompt\n")
            result = json.loads((root / "evidence" / "00001-result.json").read_text())
            self.assertEqual(result["requested_model"], "test-alternate-model")
            self.assertEqual(result["requested_reasoning_effort"], "medium")
            journals = list((root / "evidence" / "requests").glob("session-*/requests/*/state.json"))
            self.assertEqual(len(journals), 1)
            state = json.loads(journals[0].read_text())
            self.assertEqual(state["metadata"]["requested_model"], "test-alternate-model")
            self.assertEqual(state["metadata"]["deadline_seconds"], 31)

    def test_native_writer_conflict_is_retried(self):
        calls = []
        original = codex_backend._run_native_once

        def flaky(prompt, thread_id, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("thread-store conflict: already has an active writer")
            return "thread-2", "[{\"action\":\"EndTurn\"}]", [{"type": "turn.completed"}]

        codex_backend._run_native_once = flaky
        try:
            thread, answer, events = codex_backend.run_native("prompt", "thread-1", 1)
        finally:
            codex_backend._run_native_once = original
        self.assertEqual((thread, answer), ("thread-2", "[{\"action\":\"EndTurn\"}]"))
        self.assertEqual(len(calls), 2)

    def test_resumed_thread_reapplies_read_only_policy(self):
        events = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "thread-2"}),
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "[{\"action\":\"DoneWithImportantMoves\"}]"}}),
            json.dumps({"type": "turn.completed"}),
        ])

        class Process:
            pid = 42
            returncode = 0

            def communicate(self, timeout):
                return events, ""

        with patch.object(codex_backend.subprocess, "Popen", return_value=Process()) as popen:
            thread, answer, _ = codex_backend.run_native("BOARD", "thread-1", 90)

        command = popen.call_args.args[0]
        self.assertEqual(thread, "thread-2")
        self.assertNotIn("--sandbox", command)
        self.assertNotIn("--color", command)
        self.assertIn("Do not use shell, web, files, skills, connectors, or unrelated tools.",
                      command[-1])
        self.assertIn("BOARD", command[-1])
        self.assertIn("DoneWithImportantMoves", answer)

    def test_new_thread_has_sandbox_and_bridges_completion_usage(self):
        events = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
            json.dumps({"type": "item.completed", "item": {
                "type": "agent_message", "text": "[]"}}),
            json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 10, "cached_input_tokens": 4,
                "output_tokens": 3, "reasoning_output_tokens": 2}}),
        ])

        class Process:
            pid = 42
            returncode = 0

            def communicate(self, timeout):
                return events, ""

        with patch.object(codex_backend.subprocess, "Popen", return_value=Process()) as popen:
            thread, _, received = codex_backend.run_native("BOARD", None, 90)
        command = popen.call_args.args[0]
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(codex_backend.completion_usage(received)["reasoning_output_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
