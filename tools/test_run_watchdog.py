import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from .run_watchdog import (EvidenceError, MAX_RECORD_SIZE, RepetitionDetector,
                            RunWatchdog, _NDJSONCursor, read_run_evidence, run_status)


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
            self.assertIsInstance(second["recent_actions"][-1]["revision"], int)
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

    def test_large_complete_records_are_indexed_without_false_gaps_or_retained_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            records = []
            for size, revision in ((70_000, 70), (560_000, 560)):
                records.append(json.dumps({"type": "driver", "line": {
                    "type": "state", "state_revision": revision, "turn": revision},
                    "payload": "x" * size}, separators=(",", ":")))
            records.append(json.dumps({"type": "terminal", "reason": "max_turns"}))
            source = ("\n".join(records) + "\n").encode()
            log.write_bytes(source)
            watchdog = RunWatchdog(log, "large", clock=FakeClock(), poll_interval=0)
            status = watchdog.poll()
            self.assertEqual(status["stage"], "terminal")
            self.assertEqual(status["revision"], 560)
            self.assertFalse(any("invalid" in event or "oversized" in event
                                 for event in status["coverage_events"]))
            self.assertEqual(len(watchdog._records), 3)
            self.assertTrue(all("payload" not in record for record in watchdog._records))
            expected_offset = 0
            for original in (item.encode() + b"\n" for item in records):
                entry = next(item for item in watchdog._index.values()
                             if item["start"] == expected_offset)
                self.assertEqual(entry["end"], expected_offset + len(original))
                self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
                evidence = watchdog.read_evidence(entry["evidence_id"], limit=64)
                self.assertEqual(evidence["data"], original[:64].decode())
                expected_offset += len(original)

    def test_large_partial_line_completes_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            record = json.dumps({"type": "driver", "line": {
                "type": "state", "state_revision": 701},
                "payload": "z" * 70_000}, separators=(",", ":")).encode() + b"\n"
            split = 12_345
            log.write_bytes(record[:split])
            first = RunWatchdog(log, "large-partial", clock=FakeClock(), poll_interval=0)
            first.poll()
            self.assertEqual(first._cursors[log.name].buffer, record[:split])
            second = RunWatchdog(log, "large-partial", clock=FakeClock(), poll_interval=0)
            with log.open("ab") as stream:
                stream.write(record[split:])
            self.assertEqual(second.poll(force=True)["revision"], 701)
            self.assertEqual(len(second._records), 1)

    def test_oversized_partial_record_resumes_after_restart_and_indexes_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            oversized = b"{" + b"x" * (MAX_RECORD_SIZE + 100)
            log.write_bytes(oversized)
            first = RunWatchdog(log, "oversized", clock=FakeClock(), poll_interval=0)
            first.poll()
            self.assertTrue(first._cursors[log.name].discarding)
            self.assertEqual(first._cursors[log.name].buffer, b"")
            second = RunWatchdog(log, "oversized", clock=FakeClock(), poll_interval=0)
            with log.open("ab") as stream:
                stream.write(b"}\n")
                stream.write(json.dumps({"type": "driver", "line": {
                    "type": "state", "state_revision": 99}}).encode() + b"\n")
            status = second.poll(force=True)
            self.assertEqual(status["revision"], 99)
            self.assertFalse(any("invalid_record" in event for event in status["coverage_events"]))
            gaps = [entry for entry in second._index.values() if entry["kind"] == "coverage_gap"]
            self.assertEqual(len(gaps), 1)
            evidence = second.read_evidence(gaps[0]["evidence_id"], limit=32)
            self.assertEqual(evidence["bytes_read"], 32)
            self.assertTrue(evidence["truncated"])

    def test_oversized_record_with_newline_and_following_valid_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            valid = json.dumps({"type": "driver", "line": {
                "type": "state", "state_revision": 123}}).encode() + b"\n"
            log.write_bytes(b"x" * (MAX_RECORD_SIZE + 100) + b"\n" + valid)
            watchdog = RunWatchdog(log, "oversized-same-poll", clock=FakeClock(), poll_interval=0)
            status = watchdog.poll()
            self.assertEqual(status["revision"], 123)
            self.assertFalse(any("invalid_record" in event for event in status["coverage_events"]))
            self.assertEqual(len([entry for entry in watchdog._index.values()
                                  if entry["kind"] == "coverage_gap"]), 1)

    def test_truncation_while_discarding_resets_and_reads_new_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_bytes(b"x" * (MAX_RECORD_SIZE + 100))
            clock = FakeClock()
            watchdog = RunWatchdog(log, "discard-truncate", clock=clock, poll_interval=0)
            watchdog.poll()
            self.assertTrue(watchdog._cursors[log.name].discarding)
            log.write_bytes(json.dumps({"type": "driver", "line": {
                "type": "state", "state_revision": 88}}).encode() + b"\n")
            status = watchdog.poll(force=True)
            self.assertEqual(status["revision"], 88)
            self.assertTrue(any("truncated" in event for event in status["coverage_events"]))

    def test_distinct_large_tool_requests_do_not_share_compacted_alert_signature(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            rows = []
            rows.append({"type": "driver", "line": {"type": "state", "state_revision": 4}})
            for suffix in ("one", "two", "three"):
                rows.append({"type": "tool_result", "tool": "inspect_target",
                             "request": {"description": "a" * 600 + suffix}})
            rows.extend({"type": "model_error", "code": "distinct", "message": "error-" + str(i)}
                        for i in range(2))
            log.write_text("".join(json.dumps(row) + "\n" for row in rows))
            watchdog = RunWatchdog(log, "request-signatures", clock=FakeClock(), poll_interval=0)
            status = watchdog.poll()
            self.assertFalse(any(alert["kind"] == "repeated_tool_request"
                                 for alert in status["alerts"]))
            self.assertEqual(len(watchdog._tool_requests), 3)
            with log.open("a") as stream:
                repeated = json.dumps(rows[1]) + "\n"
                stream.write(repeated)
                stream.write(repeated)
            status = watchdog.poll(force=True)
            self.assertTrue(any(alert["kind"] == "repeated_tool_request"
                                for alert in status["alerts"]))
            retained_errors = [row for row in watchdog._records if row["type"] == "model_error"]
            self.assertEqual([row["code"] for row in retained_errors], ["distinct", "distinct"])
            self.assertEqual([row["message"] for row in retained_errors], ["error-0", "error-1"])

    def test_truncation_resets_partial_cursor_and_malformed_json_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "match.ndjson"
            log.write_bytes(b'{"type":"metadata"')
            clock = FakeClock()
            watchdog = RunWatchdog(log, "truncate", clock=clock, poll_interval=0)
            self.assertEqual(watchdog.poll()["stage"], "unknown")
            with log.open("ab") as stream:
                stream.write(b"}\n")
            self.assertEqual(watchdog.poll(force=True)["stage"], "starting")
            log.write_bytes(b"not-json\n")
            status = watchdog.poll(force=True)
            self.assertTrue(any("truncated" in event for event in status["coverage_events"]))
            self.assertTrue(any("invalid_record" in event for event in status["coverage_events"]))

    def test_boundary_sized_cursor_record_is_complete_and_next_line_survives(self):
        raw = b'{"type":"x","payload":"' + b"a" * 5 + b'"}\n'
        self.assertEqual(len(raw) - 1, 30)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.ndjson"
            path.write_bytes(raw + b'{"type":"next"}\n')
            cursor = _NDJSONCursor()
            seen = []
            errors = cursor.consume(path, lambda start, end, value, digest:
                                    seen.append((start, end, value, digest)),
                                    io_chunk=7, max_record_size=len(raw) - 1)
            self.assertEqual(errors, [])
            self.assertEqual([value for _, _, value, _ in seen],
                             [raw, b'{"type":"next"}\n'])


if __name__ == "__main__":
    unittest.main()
