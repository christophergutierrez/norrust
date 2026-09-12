import base64
import json
import tempfile
import unittest
from pathlib import Path

from .run_watchdog import EvidenceError, RepetitionDetector, RunWatchdog, read_run_evidence, run_status


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class WatchdogTests(unittest.TestCase):
    def test_incremental_status_and_evidence_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            clock = FakeClock()
            watchdog = RunWatchdog(log, "run-a", clock=clock, poll_interval=5)
            with log.open("wb") as stream:
                stream.write(b'{"type":"metadata","scenario":"fixture"}\n')
                stream.flush()
            first = watchdog.poll()
            self.assertEqual(first["stage"], "starting")
            self.assertEqual(first["observation_sequence"], 1)
            evidence_id = first["recent_actions"]
            self.assertEqual(first["revision"], None)
            with log.open("ab") as stream:
                stream.write(b'{"type":"driver","line":{"type":"state","state_revision":4,"turn":2}}\n')
                stream.write(b'{"type":"forwarded_orders","batch_id":"b1","orders":[{"action":"hold"}],"state_revision":4}\n')
                stream.write(b'{"type":"batch_committed","batch_id":"b1","state_revision":4}\n')
            clock.advance(5)
            second = watchdog.poll()
            self.assertEqual(second["revision"], 4)
            self.assertEqual(second["committed_action"]["batch_id"], "b1")
            ref = second["committed_action"]["evidence_id"]
            result = watchdog.read_evidence(ref, 0, 2048)
            self.assertIn("batch_committed", result["data"])
            self.assertEqual(run_status("run-a")["run_id"], "run-a")
            self.assertEqual(read_run_evidence("run-a", ref, limit=12)["bytes_read"], 12)

    def test_partial_utf8_and_incomplete_record_waits_for_newline(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            clock = FakeClock()
            watchdog = RunWatchdog(log, "partial", clock=clock)
            with log.open("wb") as stream:
                stream.write(b'{"type":"metadata","note":"caf\xc3')
            self.assertEqual(watchdog.poll()["stage"], "unknown")
            with log.open("ab") as stream:
                stream.write(b'\xa9"}\n')
            clock.advance(5)
            self.assertEqual(watchdog.poll()["stage"], "starting")

    def test_regular_schedule_and_cooldown_alert(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            clock = FakeClock()
            watchdog = RunWatchdog(log, "schedule", clock=clock, regular_interval=300,
                                   cooldown=60, poll_interval=0)
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            self.assertFalse(watchdog.poll()["regular_check_eligible"])
            clock.advance(1)
            self.assertFalse(watchdog.poll()["regular_check_eligible"])
            watchdog._raise_alert({"kind": "test", "identity": "one"}, clock())
            watchdog._raise_alert({"kind": "test", "identity": "two"}, clock())
            self.assertTrue(watchdog._alerts[-1]["coalesced"])
            clock.advance(298)
            self.assertFalse(watchdog.poll()["regular_check_eligible"])
            clock.advance(1)
            self.assertTrue(watchdog.poll()["regular_check_eligible"])

    def test_repetition_ignores_json_punctuation_and_alerts_meaningful_text_once(self):
        detector = RepetitionDetector(min_passage=32, window=256)
        text = "The northern guard retreats toward the river crossing with supplies. "
        self.assertEqual(detector.feed(text), [])
        alerts = detector.feed("prefix " + text)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(detector.feed(text), [])
        self.assertGreaterEqual(detector.counts[alerts[0]["identity"]], 1)
        punctuation = "{}[],: \"tool\" {}[],: \"tool\" "
        self.assertEqual(RepetitionDetector(min_passage=16, window=128).feed(punctuation), [])

    def test_repetition_requires_rejected_action_and_same_revision_tool_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            records = [{"type": "driver", "line": {"type": "state", "state_revision": 4}},
                       {"type": "batch_validation", "valid": True}]
            records.extend({"type": "batch_validation", "valid": False,
                            "failed_index": 0, "orders": [{"action": "move"}]}
                           for _ in range(3))
            records.extend({"type": "tool_result", "tool": "inspect_target",
                            "request": {"unit_id": 1}}
                           for _ in range(3))
            log.write_text("".join(json.dumps(record) + "\n" for record in records))
            watchdog = RunWatchdog(log, "repeat", clock=FakeClock(), poll_interval=0)
            status = watchdog.poll()
            kinds = {alert["kind"] for alert in status["alerts"]}
            self.assertIn("repeated_rejected_action", kinds)
            self.assertIn("repeated_tool_request", kinds)

    def test_missing_usage_unknown_and_stream_bytes_not_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            evidence = root / "evidence"
            chunk_dir = evidence / "call-1"
            chunk_dir.mkdir(parents=True)
            data = b"received output but no usage receipt"
            (chunk_dir / "chunks.ndjson").write_text(json.dumps({
                "sequence": 0, "data_b64": base64.b64encode(data).decode()
            }) + "\n")
            clock = FakeClock()
            watchdog = RunWatchdog(log, "usage", evidence_dir=evidence, clock=clock)
            status = watchdog.poll()
            self.assertEqual(status["received_stream_bytes"], len(data))
            self.assertEqual(status["usage_coverage"]["status"], "unknown")

    def test_stream_evidence_returns_decoded_model_delta_with_raw_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            evidence = root / "evidence" / "call-1"
            evidence.mkdir(parents=True)
            payload = ("data: " + json.dumps({"choices": [{"delta": {
                "content": "The northern guard advances toward the river crossing with supplies."
            }}]}) + "\n\n").encode()
            (evidence / "chunks.ndjson").write_text(json.dumps({
                "sequence": 0, "data_b64": base64.b64encode(payload).decode()
            }) + "\n")
            watchdog = RunWatchdog(log, "stream", evidence_dir=root / "evidence",
                                   clock=FakeClock())
            status = watchdog.poll()
            ref = next(identifier for identifier in status["evidence_ids"]
                       if identifier.startswith("artifact:"))
            result = watchdog.read_evidence(ref, limit=2048)
            self.assertIn("northern guard", result["data"])
            self.assertEqual(result["derived"], "stream_content_reasoning")
            self.assertGreater(result["raw_bytes"], result["bytes_read"])

    def test_changed_range_foreign_traversal_and_oversized_reads_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            watchdog = RunWatchdog(log, "secure", clock=FakeClock())
            status = watchdog.poll()
            index = next(iter(watchdog._index.values()))
            ref = index["evidence_id"]
            log.write_text("tampered\n")
            with self.assertRaises(EvidenceError):
                watchdog.read_evidence(ref)
            with self.assertRaises(EvidenceError):
                watchdog.read_evidence("foreign:ref")
            with self.assertRaises(EvidenceError):
                watchdog.read_evidence(ref, limit=2049)

    def test_restart_uses_persisted_cursor_and_projection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "driver", "line": {
                "type": "state", "state_revision": 9, "turn": 4}}) + "\n")
            first = RunWatchdog(log, "restart", clock=FakeClock(), poll_interval=0)
            self.assertEqual(first.poll()["revision"], 9)
            second = RunWatchdog(log, "restart", clock=FakeClock(), poll_interval=0)
            self.assertEqual(second.status()["revision"], 9)
            self.assertEqual(second.poll(force=True)["revision"], 9)
            self.assertEqual(len(second._records), 0)

    def test_oversized_static_artifact_is_bounded_before_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            checkpoint = log.with_suffix(".ckpt")
            checkpoint.mkdir()
            (checkpoint / "huge.json").write_bytes(b"x" * (MAX_STATIC := 64 * 1024 * 16 + 1))
            watchdog = RunWatchdog(log, "bounded", clock=FakeClock())
            status = watchdog.poll()
            self.assertTrue(any("oversized" in event for event in status["coverage_events"]))


if __name__ == "__main__":
    unittest.main()
