"""Offline Stack 4 strategy comparison/report contract tests."""
from __future__ import annotations

import json
import tempfile
import unittest
import os
from pathlib import Path

from . import model_bakeoff
from . import strategy_comparison as strategy


class StrategyManifestTests(unittest.TestCase):
    def test_checked_in_pilot_is_exact_and_prepared(self):
        manifest = strategy.load_prepared_pilot()
        result = strategy.validate_pilot_manifest(manifest)
        self.assertTrue(result["valid"], result["mismatches"])
        self.assertEqual(manifest["status"], "prepared_not_run")
        self.assertEqual(
            [cell["strategy_treatment"] for cell in manifest["cells"]],
            ["strategy_fixed", "strategy_glm", "focused_glm"])
        self.assertEqual(manifest["pilot_limits"]["seed"], 2038)
        self.assertEqual(manifest["pilot_limits"]["completed_engine_side_turns"], 6)
        self.assertEqual(manifest["pilot_limits"]["paid_cells_max"], 2)

    def test_strategy_fixed_argv_has_no_model_backend(self):
        manifest = strategy.load_prepared_pilot()
        cell = manifest["cells"][0]
        resolved = model_bakeoff.resolve_manifest(manifest)
        cell = resolved["cells"][0]
        with tempfile.TemporaryDirectory() as directory:
            argv, _ = model_bakeoff.build_llm_client_argv(cell, Path(directory))
        self.assertIn("--strategy-policy", argv)
        self.assertNotIn("--model-command", argv)
        self.assertNotIn("--orders-file", argv)

    def test_named_strategy_treatments_do_not_enter_bakeoff_arms(self):
        resolved = model_bakeoff.resolve_manifest(strategy.load_prepared_pilot())
        self.assertTrue(model_bakeoff.check_comparison_validity(resolved)["valid"])
        report = strategy.build_strategy_report(resolved)
        self.assertIsNone(report["bakeoff"])
        self.assertEqual(report["totals"]["not_run"], 3)
        self.assertEqual([row["strategy_treatment"] for row in report["cells"]],
                         ["strategy_fixed", "strategy_glm", "focused_glm"])
        self.assertTrue(all(row["evidence_status"] == "unknown_unrun" for row in report["cells"]))

    def test_strategy_report_attributes_actual_log_sources(self):
        manifest = strategy.load_prepared_pilot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cell_dir = model_bakeoff.cell_dir_for(root, manifest["cells"][0]["id"])
            cell_dir.mkdir(parents=True)
            log = cell_dir / "match.ndjson"
            log.write_text("\n".join(json.dumps(row) for row in [
                {"type": "driver", "line": {"type": "events", "source": "routine",
                 "events": [{"kind": "recruit", "source": "routine", "unit": 50}]}},
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            result = model_bakeoff.CellRunResult(
                manifest["cells"][0]["id"], cell_dir, log, 0, "start", "end", "ok")
            report = strategy.build_strategy_report(manifest, [result])
            attribution = report["cells"][0]["source_attribution"]
            self.assertEqual(attribution["routine_event_count"], 1)
            self.assertEqual(attribution["source_label"], "recorded_archive")
            self.assertEqual(report["cells"][1]["evidence_status"], "unknown_unrun")


class OfflineMatrixTests(unittest.TestCase):
    def test_matrix_keeps_rust_dependent_cells_unknown(self):
        matrix = json.loads(strategy.OFFLINE_MATRIX_PATH.read_text())
        report = strategy.build_offline_matrix_report(matrix)
        self.assertEqual(report["denominator"], {"scheduled": 4, "observed": 0, "unknown_unrun": 4})
        self.assertEqual(report["matrix_status"], "partial_pending_rust")
        self.assertTrue(all(row["status"] == "unknown_unrun" for row in report["cases"]))

    def test_event_attribution_counts_actual_sources_only(self):
        records = [
            {"type": "forwarded_orders", "source": "routine",
             "orders": [{"action": "Recruit"}]},
            {"type": "driver", "line": {"type": "events", "source": "routine",
             "events": [{"kind": "recruit", "source": "routine", "unit": 50},
                         {"kind": "move", "source": "routine", "unit": 3}]}},
            {"type": "driver", "line": {"type": "events", "source": "llm",
             "events": [{"kind": "attack", "source": "llm", "unit": 3}]}},
            {"type": "terminal", "reason": "max_turns"},
        ]
        attribution = strategy.archive_attribution(records, synthetic=True)
        self.assertEqual(attribution["actual_event_count"], 3)
        self.assertEqual(attribution["routine_event_count"], 2)
        self.assertEqual(attribution["model_event_count"], 1)
        self.assertEqual(attribution["model_request_count"], 0)
        self.assertEqual(attribution["source_label"], "synthetic_fixture")

    def test_archive_without_terminal_stays_unknown(self):
        attribution = strategy.archive_attribution([
            {"type": "driver", "line": {"type": "events", "events": []}},
        ])
        self.assertIsNone(attribution["model_request_count"])
        self.assertEqual(attribution["evidence_status"], "unknown_truncated")

    def test_observed_matrix_row_is_labelled_synthetic(self):
        matrix = {"cases": [{"id": "case", "expected": {}}]}
        report = strategy.build_offline_matrix_report(matrix, archives={
            "case": [{"type": "terminal", "reason": "max_turns"}]
        })
        self.assertEqual(report["cases"][0]["status"], "observed")
        self.assertTrue(report["cases"][0]["attribution"]["synthetic"])

    def test_archive_deduplicates_logical_model_request_and_response(self):
        attribution = strategy.archive_attribution([
            {"type": "metadata", "usage_measured": False},
            {"type": "model_request", "request_id": "r1"},
            {"type": "model", "request_id": "r1"},
            {"type": "checkpoint_ref", "state_revision": 1},
            {"type": "terminal", "reason": "max_turns"},
        ])
        self.assertEqual(attribution["model_request_count"], 1)
        self.assertEqual(attribution["usage_coverage"], "unknown")
        self.assertEqual(attribution["evidence_status"], "unknown_coverage")

    @unittest.skipUnless(Path(os.environ.get(
        "NORRUST_TEST_DRIVER", "norrust_core/target/debug/greedy_driver")).is_file(),
        "build the actual integration driver for the executable matrix")
    def test_executable_matrix_real_driver_predicates(self):
        with tempfile.TemporaryDirectory() as td:
            report = strategy.run_offline_matrix(
                run_dir=Path(td),
                driver=os.environ.get("NORRUST_TEST_DRIVER"), timeout=45)
        self.assertEqual(report["matrix_status"], "observed")
        self.assertEqual(report["denominator"]["unknown_unrun"], 0)
        quiet = next(row for row in report["cases"] if row["case_id"] == "quiet-opening")
        self.assertTrue(quiet["policy_difference"]["satisfied"])
        travel = next(row for row in report["cases"] if row["case_id"] == "multiturn-travel")
        self.assertTrue(travel["deterministic_replay"]["same_event_digest"])
        self.assertTrue(all(run["import_idempotent"] for row in report["cases"] for run in row["runs"]))
        self.assertEqual(next(row for row in report["cases"] if row["case_id"] == "blocked-objective")
                         ["runs"][0]["exception"], "recruitment_blocked")
        self.assertEqual(next(row for row in report["cases"] if row["case_id"] == "contact")
                         ["runs"][0]["exception"], "contact")


if __name__ == "__main__":
    unittest.main()
