import unittest

from .model_usage import ModelCall
from .prompt_cache_report import _cache_usage, common_prefix_bytes, report_prompts


class PromptCacheReportTests(unittest.TestCase):
    def test_reports_utf8_bytes_and_adjacent_shared_prefix(self):
        result = report_prompts(["固定\nA", "固定\nB"])
        self.assertEqual(result["shared_prefix_bytes"], [len("固定\n".encode())])
        self.assertEqual(result["requests"][0]["prompt_bytes"], len("固定\nA".encode()))

    def test_empty_is_explicit(self):
        self.assertEqual(report_prompts([])["coverage"], None)

    def test_cache_ratio_uses_only_valid_input_cache_cohort(self):
        def call(name, input_tokens, cached, **kwargs):
            return ModelCall(game_id="g", call_id=name, input_tokens=input_tokens,
                             cached_input_tokens=cached, **kwargs)
        result = _cache_usage([
            call("a", 1000, 0), call("b", 1200, 800),
            call("c", 900, None),
        ])
        self.assertEqual(result["physical_calls"], 3)
        self.assertEqual(result["measured_input_cache_calls"], 2)
        self.assertEqual(result["excluded_unknown_input_or_cache_calls"], 1)
        self.assertEqual(result["input_tokens_measured_cohort"], 2200)
        self.assertEqual(result["cached_input_tokens_measured_cohort"], 800)
        self.assertAlmostEqual(result["cache_ratio"], 800 / 2200)
        self.assertEqual(result["all_calls"]["input_tokens"]["sum"], 3100)

    def test_conflicting_calls_are_excluded_but_known_input_remains_covered(self):
        calls = [
            ModelCall(game_id="g", call_id="ok", input_tokens=100, cached_input_tokens=0),
            ModelCall(game_id="g", call_id="bad", input_tokens=100, cached_input_tokens=101),
            ModelCall(game_id="g", call_id="conflict", input_tokens=100,
                      cached_input_tokens=50, normalization_gaps=["conflict:input_tokens:100!=200"]),
        ]
        result = _cache_usage(calls)
        self.assertEqual(result["excluded_conflicting_input_cache_calls"], 2)
        self.assertEqual(result["excluded_known_input_tokens"], 200)


if __name__ == "__main__":
    unittest.main()
