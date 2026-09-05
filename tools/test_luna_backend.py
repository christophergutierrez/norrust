import json
import unittest
from unittest.mock import patch

from . import luna_backend


class LunaBackendTests(unittest.TestCase):
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
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn("Do not use shell, web, files, skills, connectors, or unrelated tools.",
                      command[-1])
        self.assertIn("BOARD", command[-1])
        self.assertIn("DoneWithImportantMoves", answer)


if __name__ == "__main__":
    unittest.main()
