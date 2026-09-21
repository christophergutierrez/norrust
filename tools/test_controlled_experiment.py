import unittest

from tools.controlled_experiment import (
    TREATMENTS, aggregate_results, build_manifest, select_llm_candidate,
    select_search_candidate, validate_manifest,
)


class ControlledExperimentTests(unittest.TestCase):
    def test_manifest_is_three_way_and_provider_free(self):
        manifest = build_manifest(scenarios=("s",), seeds=(1, 2), sides=(0, 1))
        self.assertEqual(len(manifest["cells"]), 12)
        self.assertEqual(tuple(manifest["treatments"]), TREATMENTS)
        self.assertTrue(validate_manifest(manifest)["valid"])
        self.assertTrue(all(c["provider_allowed"] is False for c in manifest["cells"]))

    def test_search_selector_is_deterministic_and_legal(self):
        candidates = [
            {"candidate_id": "bad", "legal": False, "mean_score": 99, "index": 0},
            {"candidate_id": "a", "legal": True, "mean_score": 2, "index": 1},
            {"candidate_id": "b", "legal": True, "mean_score": 2, "index": 2},
        ]
        self.assertEqual(select_search_candidate(candidates), "a")
        self.assertIsNone(select_search_candidate([]))

    def test_llm_selector_cannot_issue_unlisted_orders(self):
        self.assertEqual(select_llm_candidate(["a", "b"], "b")["selected_id"], "b")
        result = select_llm_candidate(["a", "b"], "custom-orders", fallback_id="a")
        self.assertFalse(result["valid"])
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["selected_id"], "a")

    def test_failures_and_unrun_cells_are_not_losses(self):
        manifest = build_manifest(scenarios=("s",), seeds=(1,), sides=(0,))
        results = [
            {"cell_id": manifest["cells"][0]["id"], "status": "completed", "outcome": "win"},
            {"cell_id": manifest["cells"][1]["id"], "status": "failed", "outcome": None},
        ]
        report = aggregate_results(manifest, results)
        for treatment, summary in report["summary"].items():
            self.assertEqual(summary["scheduled"], 1)
            self.assertEqual(summary["wins_scheduled"], 1 if treatment == "current_player" else 0)
        self.assertEqual(report["summary"]["search_only"]["operational_failures"], 1)
        self.assertEqual(report["summary"]["llm_search"]["unrun"], 1)


if __name__ == "__main__":
    unittest.main()
