"""Cross-layer recorder acceptance using a real client and offline provider."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest import mock

from .llm_supervisor import run
from .run_watchdog import RunWatchdog, run_status


class RecorderIntegrationTests(unittest.TestCase):
    def test_flat_usage_and_read_only_current_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_text('{"type":"metadata"}\n')
            usage = root / "usage.ndjson"
            final = {"record_kind": "final", "call_id": "one", "total_tokens": 12,
                     "input_tokens": 10, "output_tokens": 2}
            usage.write_text(json.dumps(final) + "\n" + json.dumps(final) + "\n"
                             + json.dumps({"record_kind": "dispatch", "call_id": "two"}) + "\n")
            recorder = RunWatchdog(log)
            packet = recorder.poll()
            self.assertFalse(packet["degraded"])
            self.assertEqual(packet["usage_coverage"]["status"], "partial_unknown")
            self.assertEqual(packet["usage_coverage"]["measured_total_tokens"], 12)
            self.assertEqual(packet["usage_coverage"]["unknown_records"], 1)
            saved = recorder.state_path.read_bytes()
            self.assertEqual(run_status(str(recorder.watchdog_dir)), packet)
            self.assertEqual(recorder.state_path.read_bytes(), saved)
            self.assertEqual(RunWatchdog(log).run_id, recorder.run_id)

    def test_real_client_stream_is_observed_before_reply_and_prompt_is_unchanged(self):
        driver = Path(os.environ.get("NORRUST_TEST_DRIVER", "norrust_core/target/debug/greedy_driver")).resolve()
        if not driver.is_file():
            self.skipTest("build greedy_driver or run tools.fast_check")
        ids = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                log = root / "match.ndjson"
                recorder = RunWatchdog(log, poll_interval=0.02)
                ids.append(recorder.run_id)
                command = [sys.executable, "-m", "tools.llm_client", "--driver", str(driver),
                           "--log", str(log), "--max-turns", "2", "--model-command",
                           shlex.join([sys.executable, "-m", "tools.fixtures.watchdog_stream_player"])]
                with mock.patch.dict(os.environ, {
                    "NORRUST_REQUEST_CONTEXT_FILE": str(root / "foreign-context.json"),
                    "NORRUST_EVIDENCE_DIR": str(root / "foreign-evidence"),
                    "NORRUST_WATCHDOG_RUN_ID": "foreign-run",
                }):
                    self.assertEqual(run(command, log, 0, watchdog=recorder, poll_interval=0.01), 0)
                self.assertFalse((root / "foreign-context.json").exists())
                self.assertFalse((root / "foreign-evidence").exists())
                packets = [json.loads(line)["status"] for line in recorder.journal_path.read_text().splitlines()
                           if json.loads(line).get("type") == "status"]
                live = [packet for packet in packets if packet.get("current_request")
                        and packet["received_stream_bytes"] > 0]
                self.assertTrue(live, "stream must be visible during the open provider call")
                self.assertTrue(all(packet["stage"] != "terminal" for packet in live))
                self.assertEqual(recorder.status()["stage"], "terminal")
                self.assertEqual(recorder.status()["usage_coverage"]["measured_total_tokens"], 120)
                evidence = next(recorder.evidence_dir.glob("*/prompt.txt"))
                context = json.loads((evidence.parent / "request_context.json").read_text())
                self.assertEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(), context["prompt_sha256"])
                self.assertFalse(any(root.glob("*observer*")), "recording has no observer calls")
        self.assertNotEqual(*ids, "isolated match.ndjson games need distinct run IDs")


if __name__ == "__main__":
    unittest.main()
