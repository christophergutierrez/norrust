import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .watchdog_replay import replay_cases
from .watchdog_review import review


FIXTURES = Path(__file__).parent / "fixtures" / "watchdog_stack4"


class WatchdogReplayTests(unittest.TestCase):
    def setUp(self):
        self.cases = json.loads((FIXTURES / "cases.json").read_text())["cases"]

    def test_fake_replay_persists_each_case_and_respects_call_ceiling(self):
        with tempfile.TemporaryDirectory() as output:
            result = replay_cases(self.cases, output, fake=True)
            self.assertEqual(result["model_evaluation"], {"status": "not_run", "network_calls": 0})
            self.assertLessEqual(result["metrics"]["observer_calls"], 36)
            self.assertEqual(result["metrics"]["cases"], 12)
            for case in self.cases:
                root = Path(output) / case["case_id"]
                for name in ("case.ndjson", "status.ndjson", "case.watchdog/observer-state.json",
                             "observer_payloads.ndjson", "observer_receipts.ndjson",
                             "usage.ndjson", "report.json"):
                    self.assertTrue((root / name).is_file(), name)
                self.assertTrue((root / "case.evidence").is_dir())

    def test_read_only_review_matches_fake_usage_roles_and_artifacts(self):
        with tempfile.TemporaryDirectory() as output:
            replay = replay_cases(self.cases, output, fake=True)
            reviewed_calls = 0
            for item in replay["cases"]:
                root = Path(output) / item["case"]
                packet = review(root / "case.ndjson")
                self.assertEqual(packet["model_evaluation"]["status"], "offline_fake")
                self.assertEqual(packet["usage"]["observer"]["calls"], item["metrics"]["observer_calls"])
                self.assertEqual(packet["usage"]["player"]["status"], "unknown")
                self.assertTrue(packet["coverage"]["evidence_index"])
                reviewed_calls += packet["usage"]["observer"]["calls"]
            self.assertEqual(reviewed_calls, replay["metrics"]["observer_calls"])

    def test_backend_input_does_not_include_expected_labels(self):
        # The replay API accepts timelines only for execution. expected is
        # consulted after controller execution and never enters the payload.
        with tempfile.TemporaryDirectory() as output:
            replay_cases(self.cases, output, fake=True)
            for case in self.cases:
                payloads = (Path(output) / case["case_id"] / "observer_payloads.ndjson").read_text()
                self.assertNotIn('"expected"', payloads)
                self.assertNotIn(case.get("label_reason", ""), payloads)

    def test_stream_windows_do_not_release_future_chunks(self):
        case = next(item for item in self.cases if item["case_id"] == "recover_wire_boilerplate")
        with tempfile.TemporaryDirectory() as output:
            result = replay_cases([case], output, fake=True)
            root = Path(output) / case["case_id"]
            statuses = [json.loads(line) for line in (root / "status.ndjson").read_text().splitlines()]
            # Bytes become visible only as each chunk is appended; completed
            # replay evidence remains available on disk for later review.
            self.assertEqual([item["received_stream_bytes"] for item in statuses[:2]], [len(case["stream_chunks"][0].encode()), sum(len(x.encode()) for x in case["stream_chunks"])])
            payloads = [json.loads(line) for line in (root / "observer_payloads.ndjson").read_text().splitlines()]
            self.assertTrue(payloads)
            self.assertNotIn("Useful plan beta", json.dumps(payloads[0]))
            self.assertEqual(result["metrics"]["observer_calls"], 3)

    def test_historical_excerpt_is_released_only_after_completion(self):
        case = next(item for item in self.cases if item["case_id"] == "healthy_long_planning")
        with tempfile.TemporaryDirectory() as output:
            replay_cases([case], output, fake=True)
            statuses = [json.loads(line) for line in
                        (Path(output) / case["case_id"] / "status.ndjson").read_text().splitlines()]
            self.assertTrue(all(item["received_stream_bytes"] == 0 for item in statuses[:4]))
            self.assertGreater(statuses[4]["received_stream_bytes"], 0)

    def test_fake_decisions_exercise_validated_inspect_stop_path(self):
        with tempfile.TemporaryDirectory() as output:
            result = replay_cases(self.cases, output, fake=True)
            reports = {item["case"]: item for item in result["cases"]}
            persistent = reports["failure_reasoning_loop"]["metrics"]
            self.assertTrue(persistent["raw_stop_recommendation"])
            self.assertTrue(persistent["validated_would_stop"])
            receipts = [json.loads(line) for line in
                        (Path(output) / "failure_reasoning_loop" / "observer_receipts.ndjson").read_text().splitlines()]
            self.assertEqual([item["decision"]["decision"] for item in receipts], ["continue", "inspect", "stop"])
            self.assertTrue(persistent["observed_stop"])
            self.assertTrue(persistent["validated_would_stop"])
            self.assertFalse(persistent["missed_loop"])
            self.assertTrue(receipts[-1]["decision"]["evidence_ids"])
            self.assertGreaterEqual(persistent["observer_calls"], 2)
            self.assertLessEqual(max(item["metrics"]["observer_calls"] for item in result["cases"]), 3)
            healthy = next(item for item in result["cases"] if item["case"] == "healthy_long_planning")
            self.assertGreater(healthy["metrics"]["observer_calls"], 0)

    def test_detection_delay_uses_recorded_alert_time(self):
        with tempfile.TemporaryDirectory() as output:
            result = replay_cases(self.cases, output, fake=True)
            report = next(item for item in result["cases"] if item["case"] == "failure_reasoning_loop")
            self.assertEqual(report["metrics"]["first_alert_at_seconds"], 1.0)
            self.assertEqual(report["metrics"]["detection_delay_seconds"], 300.0)

    def test_manifest_records_dated_price_ceiling_without_authorizing_paid_calls(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        evaluation = manifest["evaluation"]
        self.assertFalse(evaluation["paid_launch_authorized"])
        self.assertEqual(evaluation["rates"]["checked_date"], "2026-09-12")
        self.assertEqual(evaluation["rates"]["source"], "https://developers.openai.com/api/docs/models/gpt-5.4-nano")
        self.assertEqual(evaluation["worst_case_usd_no_cache"], 0.0525312)

    def test_cli_is_offline_and_reports_detection_metrics(self):
        with tempfile.TemporaryDirectory() as output:
            command = [sys.executable, "-m", "tools.watchdog_replay", "--fake",
                       "--manifest", str(FIXTURES / "manifest.json"),
                       "--output-dir", output]
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
            payload = json.loads(completed.stdout)
            self.assertIn("false_stops", payload["metrics"])
            self.assertEqual(payload["model_evaluation"]["status"], "not_run")
            self.assertTrue((Path(output) / "failure_reasoning_loop" / "report.json").is_file())


if __name__ == "__main__":
    unittest.main()
