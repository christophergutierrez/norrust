"""Offline tests for the milestone 6 evaluation manifest/analysis module.

No test here contacts a paid model. `glmeval_synthetic_archive_success.ndjson`
and `glmeval_synthetic_archive_failure.ndjson` are small hand-written
records shaped like real `tools.llm_client` NDJSON logs, used only to
exercise `analyze_cell_archive`'s offline metric extraction -- they are not
recorded model evidence and must never be cited as a performance result.
"""
from __future__ import annotations

import unittest
import tempfile
import json
from pathlib import Path

from . import glm_eval_manifest as geval
from . import match_report
from . import model_bakeoff

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tools/fixtures"


class BuildTreatmentManifestTests(unittest.TestCase):
    def _build(self, treatment="stack2_contract_memory"):
        return geval.build_treatment_manifest(
            treatment=treatment, model="accounts/fireworks/models/glm-5p3-flash",
            backend_command="python3 -m tools.fireworks_backend --model accounts/fireworks/models/glm-5p3-flash",
            source_commit="deadbeef", worktree_path="/tmp/glm-eval-stack2",
            position_family="recruiter_defense", position=1)

    def test_one_position_cohort_has_two_trials(self):
        manifest = self._build()
        cells = manifest["cells"]
        self.assertEqual(len(cells), 2)
        self.assertEqual({c["trial"] for c in cells}, {1, 2})
        self.assertEqual({c["position_family"] for c in cells}, {"recruiter_defense"})
        self.assertEqual({c["position"] for c in cells}, {1})

    def test_required_budgets_and_timeout_present(self):
        manifest = self._build()
        for cell in manifest["cells"]:
            self.assertEqual(cell["budgets"]["max_game_total_tokens"], 250000)
            self.assertEqual(cell["budgets"]["turn_timeout"], 1800)
            self.assertNotIn("turn_timeout", cell)
            self.assertIsInstance(cell["max_turns"], int)

    def test_unknown_treatment_rejected(self):
        with self.assertRaises(geval.ManifestSpecError):
            geval.build_treatment_manifest(
                treatment="not_a_treatment", model="m", backend_command="cmd",
                source_commit="c", worktree_path="/tmp/x",
                position_family="opening_deployment", position=1)

    def test_choices_without_focused_rejected(self):
        with self.assertRaises(geval.ManifestSpecError):
            geval.build_treatment_manifest(
                treatment="stack2_contract_memory", model="m", backend_command="cmd",
                source_commit="c", worktree_path="/tmp/x",
                position_family="opening_deployment", position=1,
                decision_mode="batch", action_encoding="choices")

    def test_validate_position_pairs_passes_on_fresh_build(self):
        manifest = self._build()
        self.assertEqual(geval.validate_position_pairs(manifest), [])

    def test_validate_position_pairs_catches_drifted_repeat(self):
        manifest = self._build()
        manifest["cells"][1]["seed"] = 999999
        mismatches = geval.validate_position_pairs(manifest)
        self.assertTrue(any(m.get("field") == "seed" for m in mismatches))

    def test_validate_position_pairs_catches_backend_trial_drift(self):
        manifest = self._build()
        manifest["cells"][1]["backend"]["env"]["TRIAL"] = "2"
        mismatches = geval.validate_position_pairs(manifest)
        self.assertTrue(any(m.get("field") == "backend" for m in mismatches))

    def test_validate_rejects_cross_position_cohort(self):
        manifest = self._build()
        manifest["cells"][1]["position"] = 2
        mismatches = geval.validate_position_pairs(manifest)
        self.assertTrue(any(m.get("field") == "position" for m in mismatches))

    def test_three_treatments_share_every_frozen_field_except_provenance(self):
        manifests = {t: self._build(t) for t in geval.TREATMENTS}
        frozen = ("scenario", "seed", "faction0", "faction1", "llm_side", "gold", "max_turns",
                 "checkpoint_fixture", "success_predicate", "useful_action", "model", "decision_mode",
                 "action_encoding", "budgets")
        by_position = {t: {c["id"]: c for c in m["cells"]} for t, m in manifests.items()}
        ids = set(by_position[geval.TREATMENTS[0]])
        for cell_id in ids:
            baseline = by_position[geval.TREATMENTS[0]][cell_id]
            for treatment in geval.TREATMENTS[1:]:
                other = by_position[treatment][cell_id]
                for field in frozen:
                    self.assertEqual(baseline[field], other[field],
                                     f"{field} differs for {cell_id} between treatments")

    def test_all_positions_are_separate_runner_valid_cohorts(self):
        manifests = geval.build_all_treatment_manifests(
            treatment="stack2_contract_memory", model="m", backend_command="cmd",
            source_commit="c", worktree_path="/tmp/x")
        self.assertEqual(len(manifests), 8)
        self.assertTrue(all(geval.validate_position_pairs(m) == [] for m in manifests))

    def test_resolved_treatments_keep_backend_frozen(self):
        manifests = [geval.build_treatment_manifest(
            treatment=treatment, model="m", backend_command="cmd",
            source_commit=f"{index:040d}", worktree_path=f"/tmp/{treatment}",
            position_family="opening_deployment", position=1)
                     for index, treatment in enumerate(geval.TREATMENTS, 1)]
        resolved = [model_bakeoff.resolve_manifest(manifest) for manifest in manifests]
        self.assertTrue(all(model_bakeoff.check_comparison_validity(item)["valid"] for item in resolved))
        self.assertEqual(resolved[0]["cells"][0]["backend"], resolved[1]["cells"][0]["backend"])
        self.assertNotIn("GLM_EVAL_TREATMENT", resolved[0]["cells"][0]["backend"]["env"])

    def test_real_runner_and_sqlite_physical_calls(self):
        """Exercise the maintained driver, importer, and model_calls schema."""
        manifest = geval.build_treatment_manifest(
            treatment="stack2_contract_memory", model="offline-fixture",
            backend_command="python3 tools/fixtures/task_harness/scripted_responder.py",
            source_commit="c2e2118a66651c51f36de7684a198aeb9c7d22e3",
            worktree_path=str(ROOT), position_family="opening_deployment", position=1)
        for cell in manifest["cells"]:
            cell["backend"]["env"].update(TASK_HARNESS_FAMILY="opening_deployment", TASK_HARNESS_VARIANT="1")
        with tempfile.TemporaryDirectory(prefix="glm-eval-run-") as temp:
            run_dir = Path(temp) / "run"
            resolved = model_bakeoff.resolve_manifest(manifest)
            self.assertTrue(model_bakeoff.check_comparison_validity(resolved)["valid"])
            results = model_bakeoff.run_manifest(resolved, run_dir)
            self.assertEqual([result.status for result in results], ["ok", "ok"])
            cohort = "offline-glm-eval"
            model_bakeoff.import_cells(run_dir / "catalog.sqlite", results, cohort)
            cell = resolved["cells"][0]
            game_id = f"{cohort}:{cell['id']}"
            records = match_report.load_records(results[0].log_path)
            analyzed = geval.analyze_cell_archive(records, cell,
                catalog_path=run_dir / "catalog.sqlite", game_id=game_id)
            self.assertIsInstance(analyzed["model_calls"], int)
            self.assertEqual(analyzed["usage_coverage"], "complete")
            self.assertTrue(analyzed["task_success"])


class AnalyzeCellArchiveTests(unittest.TestCase):
    def _cell(self, position=1, max_turns=18):
        return {
            "id": f"recruiter_defense-p{position}-t1", "position_family": "recruiter_defense",
            "position": position, "trial": 1, "llm_side": 0, "max_turns": max_turns,
            "success_predicate": {"recruiter_alive": True, "alive_units": [1],
                                  "absent_units": [38], "completed_side_turns_at_least": 18},
            "useful_action": {"kind": "attack"},
        }

    def test_success_archive_reports_success_and_no_premature_finish(self):
        records = match_report.load_records(FIXTURES / "glmeval_synthetic_archive_success.ndjson")
        result = geval.analyze_cell_archive(records, self._cell())
        self.assertTrue(result["task_success"])
        self.assertTrue(result["recruiter_survival"])
        self.assertFalse(result["premature_finish"])
        self.assertEqual(result["invalid_actions"], 1)
        self.assertEqual(result["rejected_agendas"], 1)
        self.assertEqual(result["inspections"], 1)
        self.assertEqual(result["driver_inspection_queries"], 1)
        self.assertEqual(result["repairs"], 0)
        self.assertEqual(result["model_calls"], "unknown_not_imported")
        self.assertTrue(result["useful_action_achieved"])
        self.assertIsNone(result["time_to_first_useful_committed_action_seconds"])

    def test_failure_archive_reports_failure_premature_finish_and_invalid_action(self):
        records = match_report.load_records(FIXTURES / "glmeval_synthetic_archive_failure.ndjson")
        result = geval.analyze_cell_archive(records, self._cell())
        self.assertFalse(result["task_success"])
        self.assertFalse(result["recruiter_survival"])
        self.assertTrue(result["premature_finish"])
        self.assertEqual(result["invalid_actions"], 1)
        self.assertEqual(result["model_calls"], "unknown_not_imported")

    def test_usage_omitted_reports_explicit_unknown_not_zero(self):
        records = match_report.load_records(FIXTURES / "glmeval_synthetic_archive_success.ndjson")
        result = geval.analyze_cell_archive(records, self._cell())
        self.assertEqual(result["total_tokens"], "unknown_not_imported")
        self.assertEqual(result["known_cost"], "unknown_not_imported")

    def test_injected_usage_shape_is_not_accepted(self):
        records = match_report.load_records(FIXTURES / "glmeval_synthetic_archive_success.ndjson")
        result = geval.analyze_cell_archive(records, self._cell())
        self.assertEqual(result["total_tokens"], "unknown_not_imported")
        self.assertEqual(result["model_calls"], "unknown_not_imported")

    def test_inspection_counter_uses_metadata_for_group_and_repair_shapes(self):
        """One grouped normal result plus a repair query counts two tools."""
        records = [
            {"type": "metadata", "tool_calls_by_name": {"inspect_targets": 1,
                                                            "inspect_unit": 1}},
            {"type": "query", "line": {"type": "status", "ok": True,
                                          "what": "inspect_targets", "body":
                                          {"targets": [{} for _ in range(8)]}}},
            {"type": "tool_result", "tool": "inspect_targets", "body":
             {"targets": [{} for _ in range(8)]}},
            {"type": "action_repair", "validation_error": "invalid action"},
            # The repair's driver query is recorded, but this failed repair
            # has no tool_result record.  It still counts through metadata.
            {"type": "query", "line": {"type": "status", "ok": False,
                                          "what": "inspect_unit", "code": "parse"}},
            {"type": "terminal", "tool_calls_by_name": {"inspect_targets": 1,
                                                            "inspect_unit": 1}},
        ]
        result = geval.analyze_cell_archive(records, self._cell())
        self.assertEqual(result["inspections"], 2)
        self.assertEqual(result["driver_inspection_queries"], 2)
        self.assertEqual(result["repairs"], 1)
        self.assertEqual(result["repairs_coverage"], "complete")

    def test_inspection_count_is_unknown_without_cumulative_metadata(self):
        result = geval.analyze_cell_archive(
            [{"type": "query", "line": {"type": "status", "what": "inspect_unit"}}],
            self._cell())
        self.assertIsNone(result["inspections"])
        self.assertEqual(result["driver_inspection_queries"], 1)
        self.assertEqual(result["repairs_coverage"], "observed_truncated")


class CrossTreatmentReportTests(unittest.TestCase):
    def _complete_entry(self, family, position, trial, reasoning_tokens=100):
        fingerprint = {field: "fixed" for field in geval._FROZEN_FIELDS}
        fingerprint.update({"backend": {"kind": "command", "command": "offline"},
                             "checkpoint_sha256": None, "transport_fingerprint": "transport"})
        return {
            "position_family": family, "position": position, "trial": trial,
            "task_success": True, "reasoning_tokens": reasoning_tokens,
            "usage_coverage": "complete", "unassigned_calls": 0,
            "aggregate_only_request_ids": [],
            "field_coverage": {"reasoning_tokens": {"fully_measured": True}},
            "invalid_actions": 0, "premature_finish": False,
            "recruiter_survival": True, "frozen_fingerprint": fingerprint,
            "treatment_fingerprint": {"source_commit": "source", "guide_hash": "guide",
                                       "driver_hash": "driver"},
        }

    def test_join_keys_by_family_position_trial(self):
        stack2 = [{"cell_id": "opening_deployment-p1-t1", "position_family": "opening_deployment",
                  "position": 1, "trial": 1, "task_success": True, "reasoning_tokens": 5000}]
        stack3 = [{"cell_id": "opening_deployment-p1-t1", "position_family": "opening_deployment",
                  "position": 1, "trial": 1, "task_success": True, "reasoning_tokens": 3000}]
        report = geval.cross_treatment_report({"stack2_contract_memory": stack2, "stack3_stopping_rule": stack3})
        self.assertEqual(len(report["rows"]), 16)
        row = next(row for row in report["rows"] if row["position_family"] == "opening_deployment" and row["position"] == 1 and row["trial"] == 1)
        self.assertEqual(row["stack2_contract_memory"]["reasoning_tokens"], 5000)
        self.assertEqual(row["stack3_stopping_rule"]["reasoning_tokens"], 3000)

    def test_missing_cell_in_one_treatment_reported_as_none_not_dropped(self):
        stack2 = [{"cell_id": "x", "position_family": "opening_deployment", "position": 1,
                  "trial": 1, "task_success": True, "reasoning_tokens": 1}]
        report = geval.cross_treatment_report({"stack2_contract_memory": stack2, "stack3_stopping_rule": []})
        row = next(row for row in report["rows"] if row["position_family"] == "opening_deployment" and row["position"] == 1 and row["trial"] == 1)
        self.assertIsNone(row["stack3_stopping_rule"])
        self.assertEqual(report["denominator"]["scheduled_cells"], 16)
        self.assertFalse(report["manifest_integrity"])

    def test_missing_all_cells_cannot_promote_from_eight_pairs(self):
        entries = []
        for family, position, trial in geval.EXPECTED_KEYS[:8]:
            entries.append({"position_family": family, "position": position, "trial": trial,
                            "task_success": True, "reasoning_tokens": 100,
                            "usage_coverage": "complete", "unassigned_calls": 0,
                            "aggregate_only_request_ids": [],
                            "field_coverage": {"reasoning_tokens": {"fully_measured": True}},
                            "invalid_actions": 0, "premature_finish": False,
                            "recruiter_survival": True,
                            "frozen_fingerprint": {"backend": {}, "transport_fingerprint": "x"}})
        report = geval.cross_treatment_report({"a": entries, "b": entries})
        self.assertFalse(report["comparisons"][0]["promotion_eligible"])
        self.assertFalse(report["manifest_integrity"])

    def test_new_defense_recruiter_loss_fails_pair_gate(self):
        entries = []
        for family, position, trial in geval.EXPECTED_KEYS:
            entry = {"position_family": family, "position": position, "trial": trial,
                     "task_success": True, "reasoning_tokens": 100,
                     "usage_coverage": "complete", "unassigned_calls": 0,
                     "aggregate_only_request_ids": [],
                     "field_coverage": {"reasoning_tokens": {"fully_measured": True}},
                     "invalid_actions": 0, "premature_finish": False,
                     "recruiter_survival": True,
                     "frozen_fingerprint": {"backend": {}, "transport_fingerprint": "x"}}
            entries.append(entry)
        candidate = [dict(entry) for entry in entries]
        for entry in candidate:
            if entry["position_family"] == "recruiter_defense":
                entry["recruiter_survival"] = False
        report = geval.cross_treatment_report({"a": entries, "b": candidate})
        self.assertFalse(report["comparisons"][0]["checks"]["candidate_recruiter_loss_not_increased_in_defense"])

    def test_unknown_transport_fingerprint_blocks_promotion(self):
        entries = []
        for family, position, trial in geval.EXPECTED_KEYS:
            entries.append({"position_family": family, "position": position, "trial": trial,
                            "task_success": True, "reasoning_tokens": 100,
                            "usage_coverage": "complete", "unassigned_calls": 0,
                            "aggregate_only_request_ids": [],
                            "field_coverage": {"reasoning_tokens": {"fully_measured": True}},
                            "invalid_actions": 0, "premature_finish": False,
                            "recruiter_survival": True,
                            "frozen_fingerprint": {"backend": {}, "transport_fingerprint": None}})
        report = geval.cross_treatment_report({"a": entries, "b": entries})
        self.assertTrue(report["fingerprint_unknown"])
        self.assertFalse(report["comparisons"][0]["promotion_eligible"])

    def test_missing_frozen_fingerprint_blocks_otherwise_eligible_promotion(self):
        predecessor = [self._complete_entry(*key, reasoning_tokens=100)
                       for key in geval.EXPECTED_KEYS]
        candidate = [self._complete_entry(*key, reasoning_tokens=50)
                     for key in geval.EXPECTED_KEYS]
        candidate[0].pop("frozen_fingerprint")
        report = geval.cross_treatment_report({"a": predecessor, "b": candidate})
        self.assertTrue(any(item["key"] == geval.EXPECTED_KEYS[0]
                            and "frozen_fingerprint" in item["fields"]
                            for item in report["fingerprint_unknown"]))
        self.assertFalse(report["manifest_integrity"])
        self.assertFalse(report["comparisons"][0]["promotion_eligible"])

    def test_malformed_frozen_fingerprint_is_unknown(self):
        predecessor = [self._complete_entry(*key) for key in geval.EXPECTED_KEYS]
        candidate = [self._complete_entry(*key) for key in geval.EXPECTED_KEYS]
        candidate[0]["frozen_fingerprint"] = []
        report = geval.cross_treatment_report({"a": predecessor, "b": candidate})
        self.assertTrue(any(item["key"] == geval.EXPECTED_KEYS[0]
                            and item["fields"] == ["frozen_fingerprint"]
                            for item in report["fingerprint_unknown"]))
        self.assertFalse(report["manifest_integrity"])
        self.assertFalse(report["comparisons"][0]["promotion_eligible"])

    def test_unexpected_schedule_key_is_reported_and_blocks_promotion(self):
        predecessor = [self._complete_entry(*key, reasoning_tokens=100)
                       for key in geval.EXPECTED_KEYS]
        candidate = [self._complete_entry(*key, reasoning_tokens=50)
                     for key in geval.EXPECTED_KEYS]
        unexpected = self._complete_entry("opening_deployment", 1, 3, reasoning_tokens=50)
        predecessor.append(unexpected)
        report = geval.cross_treatment_report({"a": predecessor, "b": candidate})
        self.assertEqual(report["unexpected_keys"]["a"], [("opening_deployment", 1, 3)])
        self.assertFalse(report["manifest_integrity"])
        self.assertFalse(report["comparisons"][0]["promotion_eligible"])


if __name__ == "__main__":
    unittest.main()
