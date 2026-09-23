import dataclasses
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.plan_selector import (
    FallbackReason, FakeSelector, MAX_PROMPT_BYTES, PromptTooLarge,
    SelectorEnvelope, SelectorMode, SelectorRequest, build_selector_prompt,
    parse_candidate_response, run_selector_envelope, select_candidate,
)


FIXTURES = Path(__file__).parent / "fixtures" / "selector_stack2"
SCENARIOS = ("opening", "large_army", "close_tradeoff", "recruiter_danger")


def load_request(name: str) -> SelectorRequest:
    return SelectorRequest.from_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def opening_envelope() -> SelectorEnvelope:
    return SelectorEnvelope("game-7", "decision-3", "a" * 64, load_request("opening"))


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

    def test_fireworks_selector_dispatches_once_with_exact_profile_and_prompt(self):
        envelope = opening_envelope()
        seen = {}

        def fake_run(prompt, **kwargs):
            seen["prompt"] = prompt
            seen["kwargs"] = kwargs
            return {"text": '{"schema_version":1,"candidate_id":"lookahead"}'}

        result = run_selector_envelope(
            envelope, model="accounts/fireworks/models/glm-5p3-flash",
            reasoning_effort="low", fireworks_run=fake_run,
        )
        self.assertTrue(result.dispatched)
        self.assertIsNone(result.fallback_reason)
        self.assertEqual(result.selected_id, "lookahead")
        self.assertEqual(seen["prompt"], build_selector_prompt(envelope.request))
        self.assertEqual(seen["kwargs"]["model"], "accounts/fireworks/models/glm-5p3-flash")
        self.assertEqual(seen["kwargs"]["reasoning_effort"], "low")
        self.assertEqual(seen["kwargs"]["max_output_tokens"], 2048)
        self.assertEqual(seen["kwargs"]["timeout"], 60.0)
        self.assertEqual(seen["kwargs"]["request_id"], "decision-3")
        self.assertTrue(seen["kwargs"]["stream"])
        self.assertEqual(json.loads(result.envelope)["response"]["candidate_id"], "lookahead")

    def test_length_and_transport_errors_fallback_after_one_dispatch(self):
        envelope = opening_envelope()
        calls = []

        def limited(prompt, **kwargs):
            calls.append((prompt, kwargs))
            return {"text": "partial", "error": {"code": "output_limit"}}

        limited_result = run_selector_envelope(
            envelope, model="accounts/fireworks/models/deepseek-v4-flash-0731",
            reasoning_effort="low", fireworks_run=limited,
        )
        self.assertEqual(len(calls), 1)
        self.assertTrue(limited_result.dispatched)
        self.assertEqual(limited_result.fallback_reason, "output_limit")
        self.assertEqual(limited_result.selected_id, "greedy")

        def broken(prompt, **kwargs):
            calls.append((prompt, kwargs))
            raise RuntimeError("request_unknown: test")

        broken_result = run_selector_envelope(
            envelope, model="accounts/fireworks/models/deepseek-v4-flash-0731",
            reasoning_effort="low", fireworks_run=broken,
        )
        self.assertEqual(len(calls), 2)
        self.assertTrue(broken_result.dispatched)
        self.assertIn("request_unknown", broken_result.fallback_reason)
        self.assertEqual(broken_result.selected_id, "greedy")

    def test_unsupported_profile_is_rejected_before_dispatch(self):
        calls = []
        result = run_selector_envelope(
            opening_envelope(), model="accounts/fireworks/models/unknown",
            reasoning_effort="low", fireworks_run=lambda *args, **kwargs: calls.append(1),
        )
        self.assertFalse(result.dispatched)
        self.assertEqual(calls, [])
        self.assertEqual(result.selected_id, "greedy")

    def test_cli_uses_mocked_transport_and_emits_one_identity_envelope(self):
        envelope = opening_envelope()
        seen = []

        def fake_run(prompt, **kwargs):
            seen.append((prompt, kwargs))
            return {"text": '{"schema_version":1,"candidate_id":"objective"}'}

        input_line = json.dumps({
            "schema_version": 1, "game_id": envelope.game_id,
            "decision_id": envelope.decision_id,
            "request_sha256": envelope.request_sha256,
            "request": envelope.request.to_dict(),
        }, separators=(",", ":")) + "\n"
        output = io.StringIO()
        with patch("tools.plan_selector.fireworks_backend.run", fake_run), \
             patch("sys.stdin", io.StringIO(input_line)), patch("sys.stdout", output):
            self.assertEqual(__import__("tools.plan_selector", fromlist=["main"]).main([]), 0)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], build_selector_prompt(envelope.request))
        response = json.loads(output.getvalue())
        self.assertEqual(response["game_id"], envelope.game_id)
        self.assertEqual(response["decision_id"], envelope.decision_id)
        self.assertEqual(response["request_sha256"], envelope.request_sha256)
        self.assertEqual(response["response"]["candidate_id"], "objective")


if __name__ == "__main__":
    unittest.main()
