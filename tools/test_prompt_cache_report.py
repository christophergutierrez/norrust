import unittest

from .prompt_cache_report import common_prefix_bytes, report_prompts


class PromptCacheReportTests(unittest.TestCase):
    def test_reports_utf8_bytes_and_adjacent_shared_prefix(self):
        result = report_prompts(["固定\nA", "固定\nB"])
        self.assertEqual(result["shared_prefix_bytes"], [len("固定\n".encode())])
        self.assertEqual(result["requests"][0]["prompt_bytes"], len("固定\nA".encode()))

    def test_empty_is_explicit(self):
        self.assertEqual(report_prompts([])["coverage"], None)


if __name__ == "__main__":
    unittest.main()
