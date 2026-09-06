import json
import unittest
from unittest.mock import patch

from . import luna_backend


class LunaBackendTests(unittest.TestCase):
    def test_native_writer_conflict_is_retried(self):
        calls = []
        original = luna_backend._run_native_once

        def flaky(prompt, thread_id, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("thread-store conflict: already has an active writer")
            return "thread-2", "[{\"action\":\"EndTurn\"}]", [{"type": "turn.completed"}]

        luna_backend._run_native_once = flaky
        try:
            thread, answer, events = luna_backend.run_native("prompt", "thread-1", 1)
        finally:
            luna_backend._run_native_once = original
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

        with patch.object(luna_backend.subprocess, "Popen", return_value=Process()) as popen:
            thread, answer, _ = luna_backend.run_native("BOARD", "thread-1", 90)

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

        with patch.object(luna_backend.subprocess, "Popen", return_value=Process()) as popen:
            thread, _, received = luna_backend.run_native("BOARD", None, 90)
        command = popen.call_args.args[0]
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertEqual(luna_backend.completion_usage(received)["reasoning_output_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
