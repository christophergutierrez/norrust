import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .watchdog_evaluation import _is_quota_failure, evaluate
from .watchdog_observer import FakeObserverBackend, ObserverTransportError


def _decision(kind="continue"):
    return {"decision": kind, "reason_code": "fixture",
            "evidence_ids": [], "explanation": "offline fixture"}


class WatchdogEvaluationTests(unittest.TestCase):
    def test_fake_evaluation_skips_paid_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            result = evaluate([{"case_id": "one", "expected": "continue", "timeline": []}],
                              td, fake=True)
            self.assertEqual(result["preflight"]["status"], "skipped_fake")
            self.assertEqual(result["preflight"]["dispatches"], 0)
            self.assertEqual(result["evaluation"]["physical_calls"], 1)

    def test_preflight_failure_attempts_one_call_and_no_cases(self):
        def explode(_payload):
            raise ObserverTransportError("insufficient credit", status=402,
                                          provider_code="insufficient_credit")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: FakeObserverBackend(explode)):
                result = evaluate([{"case_id": "one", "expected": "continue", "timeline": []},
                                   {"case_id": "two", "expected": "stop", "timeline": []}], td)
            self.assertEqual(result["preflight"]["status"], "failed")
            self.assertEqual(result["preflight"]["dispatches"], 1)
            self.assertEqual(result["evaluation"]["attempted_cases"], 0)
            self.assertEqual(result["evaluation"]["unattempted_cases"], 2)
            self.assertEqual(result["model_evaluation"]["network_calls"], 1)
            self.assertEqual(result["model_evaluation"]["failures"], 1)
            self.assertEqual(result["model_evaluation"]["verdicts"], 0)
            self.assertIn("insufficient_credit", result["model_evaluation"]["failure_reasons"])
            self.assertEqual(result["preflight"]["call"]["status"], "failed")
            self.assertIsNotNone(result["preflight"]["request"])
            self.assertEqual(result["cases"][0]["metrics"]["unattempted_reason"],
                             "confirmed_exhausted_credit")

    def test_generic_429_is_not_classified_as_exhausted_credit(self):
        def explode(_payload):
            raise ObserverTransportError("rate limited", status=429)
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: FakeObserverBackend(explode)):
                result = evaluate([{"case_id": "one", "timeline": []}], td)
            self.assertFalse(result["preflight"]["error"]["quota_exhausted"])
            self.assertEqual(result["cases"][0]["metrics"]["unattempted_reason"],
                             "preflight_failed")

    def test_model_configuration_failure_stops_later_cases(self):
        def explode(_payload):
            raise ObserverTransportError("unsupported model", status=422,
                                          provider_code="unsupported_model")
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: FakeObserverBackend(explode)):
                result = evaluate([{"case_id": "one", "timeline": []},
                                   {"case_id": "two", "timeline": []}], td)
            self.assertTrue(result["preflight"]["error"]["authorization_or_config"])
            self.assertEqual(result["cases"][1]["metrics"]["unattempted_reason"],
                             "authorization_or_config_failure")

    def test_explicit_credit_message_on_429_is_exhausted_but_generic_quota_is_not(self):
        self.assertTrue(_is_quota_failure(ObserverTransportError(
            "billing: insufficient credit", status=429)))
        self.assertFalse(_is_quota_failure(ObserverTransportError(
            "account quota is temporarily unavailable", status=429)))

    def test_preflight_receipt_usage_is_measured_with_dated_cost_helper(self):
        backend = FakeObserverBackend([{
            "decision": _decision("continue"),
            "response": {"id": "receipt-1",
                          "model": "accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b",
                          "usage": {"prompt_tokens": 381, "prompt_cache_hit_tokens": 0,
                                    "completion_tokens": 1, "total_tokens": 382}},
        }])
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: backend):
                result = evaluate([], td)
            usage = result["model_evaluation"]["usage"]
            self.assertEqual(usage["calls"], 1)
            self.assertGreater(usage["input_tokens"]["sum"], 0)
            self.assertEqual(result["model_evaluation"]["cost"]["coverage"], "complete")

    def test_auth_failure_in_first_case_stops_later_cases(self):
        seen = [0]

        def responses(_payload):
            seen[0] += 1
            if seen[0] > 1:
                raise ObserverTransportError("invalid API key", status=401,
                                              provider_code="invalid_api_key")
            return _decision("continue")

        backend = FakeObserverBackend(responses)
        cases = [{"case_id": "one", "expected": "continue",
                  "timeline": [{"type": "status", "alerts": [{"identity": "a"}]}]},
                 {"case_id": "two", "expected": "continue", "timeline": []}]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: backend):
                result = evaluate(cases, td)
            self.assertEqual(seen[0], 2)
            self.assertEqual(result["cases"][1]["metrics"]["unattempted_reason"],
                             "authorization_or_config_failure")

    def test_quota_failure_in_first_case_stops_with_one_physical_failure(self):
        seen = [0]

        def responses(_payload):
            seen[0] += 1
            if seen[0] > 1:
                raise ObserverTransportError("insufficient credit", status=429)
            return _decision("continue")

        backend = FakeObserverBackend(responses)
        cases = [{"case_id": "one", "expected": "continue",
                  "timeline": [{"type": "status", "alerts": [{"identity": "a"}]}]}]
        cases.extend({"case_id": f"later-{i}", "timeline": []} for i in range(11))
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: backend):
                result = evaluate(cases, td)
            self.assertEqual(seen[0], 2)
            self.assertEqual(result["evaluation"]["physical_calls"], 2)
            self.assertEqual(result["model_evaluation"]["failures"], 1)
            self.assertEqual(result["model_evaluation"]["failure_reasons"],
                             {"ObserverTransportError": 1})
            self.assertEqual(result["cases"][0]["model_evaluation"]["status"], "failed")
            self.assertEqual(sum(item["status"]["stage"] == "not_attempted"
                                 for item in result["cases"]), 11)

    def test_successful_preflight_then_cases_use_one_shared_cap(self):
        backend = FakeObserverBackend([_decision("continue")])
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: backend):
                result = evaluate([{"case_id": "one", "expected": "continue", "timeline": []}], td)
            self.assertEqual(result["preflight"]["status"], "passed")
            self.assertEqual(result["model_evaluation"]["verdicts"], 2)
            self.assertEqual(result["evaluation"]["attempted_cases"], 1)
            self.assertLessEqual(result["evaluation"]["physical_calls"], 37)
            self.assertTrue((Path(td) / "preflight.json").is_file())
            self.assertTrue((Path(td) / "report.json").is_file())

    def test_global_cap_includes_preflight_and_stops_dispatching(self):
        backend = FakeObserverBackend([_decision("continue")])
        cases = [{"case_id": f"case-{i}", "expected": "continue",
                  "timeline": [{"type": "status", "alerts": [{"identity": f"a-{i}"}]}]}
                 for i in range(40)]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("tools.watchdog_evaluation.FireworksObserverBackend",
                            lambda **_kwargs: backend):
                result = evaluate(cases, td)
            self.assertEqual(result["evaluation"]["physical_calls"], 37)
            self.assertGreater(result["evaluation"]["unattempted_cases"], 0)

    def test_output_directory_reuse_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "old.json").write_text(json.dumps({}))
            with self.assertRaises(FileExistsError):
                evaluate([], td, fake=True)


if __name__ == "__main__":
    unittest.main()
