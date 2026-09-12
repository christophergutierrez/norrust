import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import watchdog_replay
from .watchdog_observer import FakeObserverBackend, ObserverTransportError
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

    def test_total_transport_failure_is_not_reported_as_a_clean_evaluation(self):
        # Reproduces an exhausted-credit run: every observer call raises, so no
        # model judgment exists. Zero validated stops must not read as zero
        # false stops, and a persistent case must not read as a missed loop.
        def explode(_payload):
            raise ObserverTransportError("observer transport failed: Too Many Requests")

        with tempfile.TemporaryDirectory() as output:
            with mock.patch.object(watchdog_replay, "FireworksObserverBackend",
                                   lambda **_kwargs: FakeObserverBackend(explode)):
                result = replay_cases(self.cases, output, fake=False,
                                      model="accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b")
            evaluation = result["model_evaluation"]
            self.assertEqual(evaluation["status"], "failed")
            self.assertEqual(evaluation["verdicts"], 0)
            self.assertGreater(evaluation["failures"], 0)
            self.assertEqual(evaluation["cases_without_judgment"], 12)
            self.assertIn("ObserverTransportError", evaluation["failure_reasons"])
            metrics = result["metrics"]
            self.assertEqual(metrics["cases_scored"], 0)
            self.assertIsNone(metrics["false_stops"])
            self.assertIsNone(metrics["missed_loops"])
            self.assertEqual(metrics["observer_verdicts"], 0)
            persistent = next(item["metrics"] for item in result["cases"]
                              if item["case"] == "failure_reasoning_loop")
            self.assertFalse(persistent["scored"])
            self.assertIsNone(persistent["missed_loop"])
            self.assertIsNone(persistent["false_stop"])
            self.assertEqual(persistent["observer_verdicts"], 0)

    def test_later_failed_inspection_is_partial_and_missed_loop_unknown(self):
        responses = [
            {"decision": "continue", "reason_code": "ok", "evidence_ids": [], "explanation": "fixture"},
            {"decision": "inspect", "reason_code": "check", "evidence_ids": [], "explanation": "fixture"},
            ObserverTransportError("transport failed"),
        ]
        case = {"case_id": "partial-inspection", "expected": "stop",
                "timeline": [{"type": "status", "alerts": [{"identity": "same"}]},
                             {"type": "status", "alerts": [{"identity": "same"}]}],
                "stream_chunks": ["evidence"]}

        def respond(_payload):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        backend = FakeObserverBackend(respond)
        with tempfile.TemporaryDirectory() as output:
            result = replay_cases([case], output, fake=False, backend=backend)
            metrics = result["cases"][0]["metrics"]
            self.assertTrue(metrics["judgment_observed"])
            self.assertEqual(metrics["last_outcome"], "failure")
            self.assertIsNone(metrics["missed_loop"])
            self.assertEqual(result["model_evaluation"]["status"], "partial")
            self.assertIsNone(result["metrics"]["missed_loops"])

    def test_fake_run_scores_every_case_and_keeps_integer_rates(self):
        with tempfile.TemporaryDirectory() as output:
            result = replay_cases(self.cases, output, fake=True)
            metrics = result["metrics"]
            self.assertEqual(metrics["cases_scored"], 12)
            self.assertEqual(metrics["cases_without_judgment"], 0)
            self.assertEqual(metrics["false_stops"], 0)
            self.assertEqual(metrics["missed_loops"], 1)
            self.assertEqual(metrics["observer_failures"], 0)
            self.assertEqual(metrics["observer_verdicts"], metrics["observer_calls"])
            self.assertTrue(all(item["metrics"]["scored"] for item in result["cases"]))

    def test_manifest_records_dated_price_ceiling_without_legacy_authorization_flag(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_text())
        evaluation = manifest["evaluation"]
        self.assertNotIn("paid_launch_authorized", evaluation)
        self.assertEqual(evaluation["rates"]["checked_date"], "2026-09-12")
        self.assertEqual(evaluation["rates"]["source"], "https://docs.fireworks.ai/serverless/pricing")
        self.assertEqual(evaluation["worst_case_usd_no_cache"], 0.0113664)

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

    def test_model_cli_routes_through_bounded_evaluation_entrypoint(self):
        with tempfile.TemporaryDirectory() as output:
            with mock.patch("tools.watchdog_evaluation.evaluate",
                            return_value={"model_evaluation": {"status": "failed"}}) as evaluate:
                rc = watchdog_replay.main([
                    "--model", "accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b",
                    "--manifest", str(FIXTURES / "manifest.json"),
                    "--output-dir", output])
            self.assertEqual(rc, 0)
            evaluate.assert_called_once()

    def test_journal_gap_keeps_replay_aggregate_partial(self):
        result = {"case": "one", "status": {"stage": "active"},
                  "metrics": {"scored": True, "false_stop": False,
                              "missed_loop": None, "detection_delay_seconds": None,
                              "observer_calls": 1, "observer_verdicts": 1,
                              "observer_failures": 0, "observer_failure_reasons": {},
                              "evidence_gaps": {"unreadable_journal_entry": 1},
                              "coverage_complete": False, "usage_coverage": {}},
                  "model_evaluation": {"status": "completed"}}
        with tempfile.TemporaryDirectory() as output:
            with mock.patch.object(watchdog_replay, "replay_case", return_value=result):
                aggregate = replay_cases([{"case_id": "one"}], output, fake=False)
            self.assertEqual(aggregate["model_evaluation"]["status"], "partial")


if __name__ == "__main__":
    unittest.main()
