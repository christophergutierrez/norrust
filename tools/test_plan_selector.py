import json
import unittest

from tools.plan_selector import (
    FallbackReason, FakeSelector, GameRequestBudget, SelectorMode,
    parse_candidate_response, select_candidate,
)


IDS = ("greedy", "lookahead", "objective")


class PlanSelectorTests(unittest.TestCase):
    def test_fake_selects_only_configured_current_candidate(self):
        backend = FakeSelector(candidate_id="objective")
        result = select_candidate(
            mode=SelectorMode.MODEL, candidate_ids=IDS, baseline_id="lookahead",
            decision_id="turn-1", state_revision="rev-5", backend=backend,
        )
        self.assertEqual(result.selected_id, "objective")
        self.assertFalse(result.used_fallback)
        self.assertEqual(backend.calls, 1)
        self.assertEqual(backend.last_request.candidate_ids, IDS)

    def test_parser_rejects_malformed_unknown_and_untrusted_extra_fields(self):
        valid = json.dumps({"schema_version": 1, "candidate_id": "greedy"})
        self.assertEqual(parse_candidate_response(valid, IDS), "greedy")
        for bad in (
            "{", '{"schema_version":2,"candidate_id":"greedy"}',
            '{"schema_version":true,"candidate_id":"greedy"}',
            '{"schema_version":1,"candidate_id":"greedy","actions":[]}',
            '{"schema_version":1,"candidate_id":4}',
        ):
            with self.subTest(response=bad), self.assertRaises(ValueError):
                parse_candidate_response(bad, IDS)
        with self.assertRaises(LookupError):
            parse_candidate_response('{"schema_version":1,"candidate_id":"Move"}', IDS)

    def test_all_fake_failure_modes_fall_back_with_explicit_reason(self):
        cases = (
            (FakeSelector(behavior="malformed"), FallbackReason.MALFORMED_RESPONSE),
            (FakeSelector(behavior="unknown"), FallbackReason.UNKNOWN_CANDIDATE),
            (FakeSelector(behavior="timeout"), FallbackReason.TIMEOUT),
            (FakeSelector(behavior="error"), FallbackReason.PROVIDER_ERROR),
            (FakeSelector(delay_seconds=0.02), FallbackReason.TIMEOUT),
        )
        for backend, reason in cases:
            with self.subTest(reason=reason):
                result = select_candidate(
                    mode=SelectorMode.MODEL, candidate_ids=IDS, baseline_id="lookahead",
                    decision_id="turn-1", state_revision="rev-5", backend=backend,
                    timeout_seconds=0.001 if backend.delay_seconds else 1,
                )
                self.assertEqual(result.selected_id, "lookahead")
                self.assertEqual(result.fallback_reason, reason)
                self.assertTrue(result.request_used)
                self.assertEqual(backend.calls, 1)

    def test_disabled_and_deterministic_modes_make_no_model_call(self):
        backend = FakeSelector(candidate_id="objective")
        for mode in (SelectorMode.DISABLED, SelectorMode.DETERMINISTIC):
            result = select_candidate(
                mode=mode, candidate_ids=IDS, baseline_id="lookahead",
                decision_id="turn-1", state_revision="rev-5", backend=backend,
            )
            self.assertEqual(result.selected_id, "lookahead")
            self.assertFalse(result.request_used)
        self.assertEqual(backend.calls, 0)

    def test_budget_is_per_game_and_failed_call_consumes_one_request(self):
        budget = GameRequestBudget(maximum=1)
        first = select_candidate(
            mode=SelectorMode.MODEL, candidate_ids=IDS, baseline_id="lookahead",
            decision_id="turn-1", state_revision="rev-5",
            backend=FakeSelector(behavior="error"), budget=budget,
        )
        self.assertEqual(first.fallback_reason, FallbackReason.PROVIDER_ERROR)
        second_backend = FakeSelector(candidate_id="objective")
        second = select_candidate(
            mode=SelectorMode.MODEL, candidate_ids=IDS, baseline_id="lookahead",
            decision_id="turn-2", state_revision="rev-6", backend=second_backend,
            budget=budget,
        )
        self.assertEqual(second.fallback_reason, FallbackReason.BUDGET_EXHAUSTED)
        self.assertEqual(second.selected_id, "lookahead")
        self.assertEqual(second_backend.calls, 0)
        self.assertEqual(budget.used, 1)

    def test_invalid_candidate_set_never_reaches_fake_backend(self):
        backend = FakeSelector(candidate_id="invented")
        result = select_candidate(
            mode=SelectorMode.MODEL, candidate_ids=("greedy", "greedy"),
            baseline_id="greedy", decision_id="turn-1", state_revision="rev-5",
            backend=backend,
        )
        self.assertEqual(result.fallback_reason, FallbackReason.INVALID_CANDIDATES)
        self.assertEqual(backend.calls, 0)


if __name__ == "__main__":
    unittest.main()
