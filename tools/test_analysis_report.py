import unittest

from tools.analysis_report import build_improvement_report, classify_findings


def archive(**overrides):
    value = {
        "archive": "match.ndjson", "coverage_status": "complete",
        "coverage_detail": {}, "record_count": 10, "reference_conflicts": [],
        "turns": {"terminal_partial_turns": [], "open_turns_at_end": []},
        "decisions": {"items": []},
        "usage": {"unknown_total_calls": 0},
    }
    value.update(overrides)
    return value


class ImprovementReportTests(unittest.TestCase):
    def test_incomplete_capture_is_unknown_not_strategy_failure(self):
        findings = classify_findings(archive(coverage_status="capture_stopped"))
        self.assertEqual(findings[0]["status"], "unknown")
        self.assertEqual(findings[0]["category"], "evidence")

    def test_truncation_and_validation_are_distinct(self):
        report = archive(decisions={"items": [{
            "decision_id": "d1", "candidates_truncated": True,
            "candidates_offered": 4, "candidate_omission": "unknown_without_offline_enumeration",
            "validations_rejected": 1, "repairs": 0,
        }]})
        codes = {item["code"] for item in classify_findings(report)}
        self.assertIn("candidate.display_truncated", codes)
        self.assertIn("candidate.coverage_unknown", codes)
        self.assertIn("execution.validation_rejection", codes)

    def test_shown_and_omitted_evaluation_have_different_findings(self):
        evaluation = {
            "best_candidate": {"candidate_id": "candidate-1", "verdict": "best among tested"},
            "candidates": [{"candidate_id": "candidate-1", "seen_by_player": False}],
        }
        codes = {item["code"] for item in classify_findings(archive(), evaluation)}
        self.assertIn("candidate.omitted_tested_alternative", codes)

        evaluation["candidates"][0]["seen_by_player"] = True
        codes = {item["code"] for item in classify_findings(archive(), evaluation)}
        self.assertIn("selection.shown_alternative", codes)
        self.assertNotIn("candidate.omitted_tested_alternative", codes)

    def test_no_evaluation_verdict_is_unknown(self):
        report = build_improvement_report(archive(), {"candidates": [], "best_candidate": None})
        finding = next(item for item in report["findings"] if item["code"] == "evaluation.no_verdict")
        self.assertEqual(finding["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
