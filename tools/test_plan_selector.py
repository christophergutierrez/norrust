import dataclasses
from pathlib import Path
import unittest

from tools.plan_selector import (
    FallbackReason, FakeSelector, MAX_PROMPT_BYTES, PromptTooLarge,
    SelectorEnvelope, SelectorMode, SelectorRequest, build_selector_prompt,
    parse_candidate_response, select_candidate,
)


FIXTURES = Path(__file__).parent / "fixtures" / "selector_stack2"
SCENARIOS = ("opening", "large_army", "close_tradeoff", "recruiter_danger")


def load_request(name: str) -> SelectorRequest:
    return SelectorRequest.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


class PlanSelectorTests(unittest.TestCase):
    def test_four_rust_request_fixtures_have_complete_bounded_prompts(self):
        for name in SCENARIOS:
            with self.subTest(scenario=name):
                request = load_request(name)
                prompt = build_selector_prompt(request)
                self.assertLessEqual(len(prompt.encode("utf-8")), MAX_PROMPT_BYTES)
                self.assertIn(f"controlled side: {request.side}", prompt)
                self.assertIn("opponent_response_delta", prompt)
                self.assertIn("material_delta and gold_delta are net changes", prompt)
                self.assertNotIn("terrain", prompt.lower())
                self.assertNotIn("history", prompt.lower())
                for candidate in request.candidates:
                    self.assertIn(candidate.candidate_id, prompt)

    def test_candidate_order_does_not_change_prompt_or_baseline(self):
        request = load_request("close_tradeoff")
        reversed_request = dataclasses.replace(request, candidates=tuple(reversed(request.candidates)))
        self.assertEqual(build_selector_prompt(request), build_selector_prompt(reversed_request))
        original = select_candidate(request=request, mode=SelectorMode.DETERMINISTIC)
        reversed_result = select_candidate(request=reversed_request, mode=SelectorMode.DETERMINISTIC)
        self.assertEqual(original.selected_id, reversed_result.selected_id)
        self.assertEqual(original.selected_id, "lookahead")

    def test_prompt_uses_exact_utf8_bound_and_rejects_oversize(self):
        request = load_request("opening")
        low, high = 0, MAX_PROMPT_BYTES * 2
        while low < high:
            middle = (low + high + 1) // 2
            candidate = dataclasses.replace(request, objective="x" * middle)
            try:
                fits = len(build_selector_prompt(candidate).encode("utf-8")) <= MAX_PROMPT_BYTES
            except PromptTooLarge:
                fits = False
            if fits:
                low = middle
            else:
                high = middle - 1
        exact = dataclasses.replace(request, objective="x" * low)
        self.assertEqual(len(build_selector_prompt(exact).encode("utf-8")), MAX_PROMPT_BYTES)
        oversize = dataclasses.replace(request, objective="x" * (low + 1))
        with self.assertRaises(PromptTooLarge):
            build_selector_prompt(oversize)

    def test_response_parser_rejects_duplicates_wrappers_and_bad_ids(self):
        self.assertEqual(parse_candidate_response(
            '{"schema_version":1,"candidate_id":"greedy","reason_code":"ok"}',
            ("greedy", "lookahead")), "greedy")
        bad = (
            '{"schema_version":1,"schema_version":1,"candidate_id":"greedy"}',
            '{"schema_version":1,"candidate_id":"greedy","actions":[]}',
            '{"schema_version":1,"candidate_id":"invented"}',
            '{"schema_version":1,"candidate_id":"greedy","reason_code":"' + "x" * 33 + '"}',
            '{"schema_version":1,"candidate_id":"greedy","response":{"action":"x"}}',
        )
        for response in bad:
            with self.subTest(response=response):
                with self.assertRaises((ValueError, LookupError)):
                    parse_candidate_response(response, ("greedy", "lookahead"))

    def test_identity_envelope_preserves_bridge_fields(self):
        request = load_request("opening")
        envelope = SelectorEnvelope.from_json(
            '{"schema_version":1,"game_id":"game-7","decision_id":"d-3",'
            '"request_sha256":"' + "a" * 64 + '","request":' + request.to_json() + '}'
        )
        response = envelope.response_json('{"schema_version":1,"candidate_id":"lookahead"}')
        self.assertEqual(response, '{"decision_id":"d-3","game_id":"game-7",'
                                   '"request_sha256":"' + "a" * 64 + '","response":'
                                   '{"candidate_id":"lookahead","schema_version":1},"schema_version":1}')

    def test_model_selection_sends_canonical_prompt_and_only_current_id(self):
        request = load_request("recruiter_danger")
        backend = FakeSelector(candidate_id="lookahead")
        result = select_candidate(request=request, mode=SelectorMode.MODEL, backend=backend)
        self.assertEqual(result.selected_id, "lookahead")
        self.assertTrue(result.request_used)
        self.assertEqual(backend.calls, 1)
        self.assertEqual(backend.last_prompt, build_selector_prompt(request))

    def test_invalid_request_never_reaches_backend(self):
        request = load_request("opening")
        duplicate = dataclasses.replace(request, candidates=(request.candidates[0], request.candidates[0]))
        backend = FakeSelector(candidate_id="greedy")
        result = select_candidate(request=duplicate, mode=SelectorMode.MODEL, backend=backend)
        self.assertEqual(result.fallback_reason, FallbackReason.INVALID_REQUEST)
        self.assertEqual(backend.calls, 0)


if __name__ == "__main__":
    unittest.main()
