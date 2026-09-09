"""Offline tests for tools.model_bakeoff: no paid model calls, no live games.

The real-driver integration test below uses only deterministic local
responders (an `--orders-file` fixture), matching the offline gate's existing
convention (see tools/test_resignation.py); it is skipped when the driver has
not been built, exactly like the repository's other real-driver tests.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import game_history
from . import model_bakeoff as bakeoff

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
FIXTURE_ORDERS = ROOT / "tools/fixtures/bakeoff_end_turn.jsonl"


def _base_cell(cell_id: str, **overrides) -> dict:
    cell = {
        "id": cell_id, "scenario": "big_battle_6", "seed": 1,
        "faction0": "undead", "faction1": "undead", "llm_side": 0,
        "gold": 100, "max_turns": 2, "model": "test-responder-a",
        "backend": {"kind": "orders_file", "path": str(FIXTURE_ORDERS)},
    }
    cell.update(overrides)
    return cell


def _small_manifest(**overrides) -> dict:
    manifest = {"objective": "offline bakeoff test", "cells": [_base_cell("cell-1")]}
    manifest.update(overrides)
    return manifest


class ResolveManifestTests(unittest.TestCase):
    def test_rejects_missing_fields(self):
        with self.assertRaises(bakeoff.ManifestError):
            bakeoff.resolve_manifest({"cells": [{"id": "x"}]})

    def test_rejects_empty_or_missing_cells(self):
        with self.assertRaises(bakeoff.ManifestError):
            bakeoff.resolve_manifest({"cells": []})
        with self.assertRaises(bakeoff.ManifestError):
            bakeoff.resolve_manifest({})

    def test_rejects_duplicate_ids(self):
        manifest = _small_manifest(cells=[_base_cell("dup"), _base_cell("dup")])
        with self.assertRaises(bakeoff.ManifestError):
            bakeoff.resolve_manifest(manifest)

    def test_resolves_random_seed_once_and_records_it(self):
        manifest = _small_manifest(cells=[_base_cell("cell-1", seed="random")])
        resolved = bakeoff.resolve_manifest(manifest)
        seed = resolved["cells"][0]["seed"]
        self.assertIsInstance(seed, int)
        # Re-resolving an already-int seed must not re-roll it.
        resolved_again = bakeoff.resolve_manifest(resolved)
        self.assertEqual(resolved_again["cells"][0]["seed"], seed)

    def test_records_provenance_fingerprint(self):
        resolved = bakeoff.resolve_manifest(_small_manifest())
        provenance = resolved["cells"][0]["provenance"]
        for key in ("guide_hash", "source_commit", "requested_model"):
            self.assertIn(key, provenance)
        self.assertEqual(provenance["requested_model"], "test-responder-a")

    def test_does_not_mutate_caller_manifest(self):
        manifest = _small_manifest()
        original = json.loads(json.dumps(manifest))
        bakeoff.resolve_manifest(manifest)
        self.assertEqual(manifest, original)


class ComparisonValidityTests(unittest.TestCase):
    def _resolved_two_cells(self):
        manifest = _small_manifest(cells=[_base_cell("a"), _base_cell("b", model="test-responder-b")])
        return bakeoff.resolve_manifest(manifest)

    def test_matched_experiment_with_identical_fingerprints_is_valid(self):
        resolved = self._resolved_two_cells()
        result = bakeoff.check_comparison_validity(resolved)
        self.assertEqual(result["experiment_kind"], "matched")
        self.assertTrue(result["valid"])
        self.assertEqual(result["mismatches"], [])

    def test_matched_experiment_refuses_mismatched_guide_hash(self):
        resolved = self._resolved_two_cells()
        resolved["cells"][1]["provenance"]["guide_hash"] = "different"
        result = bakeoff.check_comparison_validity(resolved)
        self.assertFalse(result["valid"])
        self.assertTrue(any(m["field"] == "guide_hash" for m in result["mismatches"]))

    def test_matched_experiment_refuses_mismatched_scenario(self):
        resolved = self._resolved_two_cells()
        resolved["cells"][1]["scenario"] = "another_scenario"
        result = bakeoff.check_comparison_validity(resolved)
        self.assertFalse(result["valid"])
        self.assertTrue(any(m["field"] == "scenario" for m in result["mismatches"]))

    def test_baseline_candidate_permits_only_declared_field(self):
        resolved = self._resolved_two_cells()
        resolved["experiment_kind"] = "baseline_candidate"
        resolved["declared_change_field"] = "guide_hash"
        resolved["cells"][1]["provenance"]["guide_hash"] = "different"
        result = bakeoff.check_comparison_validity(resolved)
        self.assertTrue(result["valid"])

    def test_baseline_candidate_still_refuses_undeclared_mismatch(self):
        resolved = self._resolved_two_cells()
        resolved["experiment_kind"] = "baseline_candidate"
        resolved["declared_change_field"] = "guide_hash"
        resolved["cells"][1]["provenance"]["guide_hash"] = "different"
        resolved["cells"][1]["scenario"] = "another_scenario"
        result = bakeoff.check_comparison_validity(resolved)
        self.assertFalse(result["valid"])
        self.assertTrue(any(m["field"] == "scenario" for m in result["mismatches"]))

    def test_baseline_candidate_requires_declared_field(self):
        resolved = self._resolved_two_cells()
        resolved["experiment_kind"] = "baseline_candidate"
        result = bakeoff.check_comparison_validity(resolved)
        self.assertFalse(result["valid"])


class EvidenceHelperTests(unittest.TestCase):
    """Fixtures built from synthetic (not live) NDJSON records."""

    def test_villages_round5_side0_found(self):
        records = [
            {"type": "driver", "line": {"type": "state", "turn": 4, "active_faction": 1,
                                        "terrain": []}},
            {"type": "driver", "line": {"type": "state", "turn": 5, "active_faction": 0,
                                        "terrain": [
                                            {"terrain_id": "village", "owner": 0},
                                            {"terrain_id": "village", "owner": 1},
                                            {"terrain_id": "village", "owner": -1},
                                            {"terrain_id": "flat", "owner": -1},
                                        ]}},
        ]
        result = bakeoff.villages_at_round5_side0(records)
        self.assertEqual(result, {"unknown": False, "round": 5, "side0": 1, "side1": 1, "neutral": 1})

    def test_villages_round5_side0_unknown_when_missing(self):
        records = [{"type": "driver", "line": {"type": "state", "turn": 3, "active_faction": 0,
                                               "terrain": []}}]
        result = bakeoff.villages_at_round5_side0(records)
        self.assertTrue(result["unknown"])

    def test_villages_round5_side0_ignores_partial_boundary(self):
        records = [{"type": "driver", "line": {"type": "state", "turn": 5, "active_faction": 0,
                                               "turn_boundary": "partial", "terrain": [
                                                   {"terrain_id": "village", "owner": 0}]}}]
        result = bakeoff.villages_at_round5_side0(records)
        self.assertTrue(result["unknown"])

    def test_recruiter_status_from_terminal_embedded_state(self):
        records = [
            {"type": "driver", "line": {"type": "state", "units": []}},
            {"type": "terminal", "reason": "winner", "winner": 0,
             "state": {"units": [
                 {"id": 1, "faction": 0, "can_recruit": True, "hp": 20, "max_hp": 20, "col": 1, "row": 1},
                 {"id": 2, "faction": 1, "can_recruit": True, "hp": 0, "max_hp": 18, "col": 2, "row": 2},
             ]}},
        ]
        result = bakeoff.recruiter_status(records)
        self.assertFalse(result["unknown"])
        self.assertEqual(result["side0"][0]["alive"], True)
        self.assertEqual(result["side1"][0]["alive"], False)

    def test_recruiter_status_unknown_without_units(self):
        result = bakeoff.recruiter_status([{"type": "terminal", "reason": "max_turns"}])
        self.assertTrue(result["unknown"])

    def test_resignation_rationale_none_when_not_resignation(self):
        self.assertIsNone(bakeoff.resignation_rationale([], {"reason": "winner"}))

    def test_resignation_rationale_captures_decision(self):
        terminal = {"reason": "resignation", "resigned_side": 1}
        records = [{"type": "forwarded_orders", "orders": [{"action": "Resign"}],
                   "decision_annotation": {"decisions": [
                       {"rules": ["T8"], "expected": "concede", "risk": "none"}]}}]
        result = bakeoff.resignation_rationale(records, terminal)
        self.assertEqual(result["rules"], ["T8"])
        self.assertEqual(result["resigned_side"], 1)

    def test_resignation_rationale_unknown_annotation(self):
        terminal = {"reason": "resignation", "resigned_side": 0}
        records = [{"type": "forwarded_orders", "orders": [{"action": "Resign"}]}]
        result = bakeoff.resignation_rationale(records, terminal)
        self.assertIsNone(result["rules"])
        self.assertEqual(result["resigned_side"], 0)


def _cell_result(cell_id: str, cell_dir: Path, status: str = "ok") -> bakeoff.CellRunResult:
    return bakeoff.CellRunResult(cell_id, cell_dir, cell_dir / "match.ndjson", 0 if status == "ok" else 1,
                                 "2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", status)


class AggregationFixtureTests(unittest.TestCase):
    """Exercise success, draw, model_invalid, infrastructure failure,
    interrupted/not-run, absent usage, and missing round-5 evidence."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name)

    def _write_log(self, cell_id: str, records: list[dict]) -> Path:
        cell_dir = bakeoff.cell_dir_for(self.run_dir, cell_id)
        cell_dir.mkdir(parents=True, exist_ok=True)
        (cell_dir / "match.ndjson").write_text("\n".join(json.dumps(r) for r in records) + "\n")
        return cell_dir

    def test_success_cell(self):
        cell = _base_cell("win-cell", llm_side=0)
        records = [
            {"type": "metadata", "scenario": "big_battle_6"},
            {"type": "terminal", "reason": "winner", "winner": 0, "wall_ms": 1234},
        ]
        cell_dir = self._write_log("win-cell", records)
        entry = bakeoff.aggregate_cell(_cell_result("win-cell", cell_dir), cell)
        self.assertEqual(entry["terminal_class"], "gameplay")
        self.assertEqual(entry["winner"], 0)
        self.assertEqual(entry["compute"]["wall_ms"], 1234)

    def test_draw_cell_is_not_counted_as_a_win(self):
        cell = _base_cell("draw-cell", llm_side=0)
        records = [{"type": "metadata"}, {"type": "terminal", "reason": "max_turns", "winner": None}]
        cell_dir = self._write_log("draw-cell", records)
        entry = bakeoff.aggregate_cell(_cell_result("draw-cell", cell_dir), cell)
        self.assertEqual(entry["terminal_class"], "gameplay")
        self.assertIsNone(entry["winner"])
        resolved = bakeoff.resolve_manifest(_small_manifest(cells=[cell]))
        report = bakeoff.build_report(resolved, [_cell_result("draw-cell", cell_dir)])
        bucket = report["configurations"][resolved["cells"][0]["configuration"]]
        self.assertEqual(bucket["draws"], 1)
        self.assertEqual(bucket["wins"], 0)

    def test_model_invalid_cell(self):
        cell = _base_cell("bad-cell")
        records = [{"type": "metadata"}, {"type": "model_error", "terminal_class": "model_invalid",
                                          "model_calls": 2}]
        cell_dir = self._write_log("bad-cell", records)
        res = _cell_result("bad-cell", cell_dir, status="failed")
        entry = bakeoff.aggregate_cell(res, cell)
        self.assertEqual(entry["terminal_class"], "model_invalid")
        self.assertFalse(bakeoff._is_infrastructure_failure(entry))
        resolved = bakeoff.resolve_manifest(_small_manifest(cells=[cell]))
        report = bakeoff.build_report(resolved, [res])
        self.assertEqual(report["totals"]["model_invalid"], 1)
        self.assertEqual(report["totals"]["infrastructure_invalid"], 0)
        bucket = report["configurations"][resolved["cells"][0]["configuration"]]
        self.assertEqual(bucket["model_invalid"], 1)
        self.assertEqual(bucket["infrastructure_invalid"], 0)

    def test_infrastructure_failure_process_crash(self):
        cell = _base_cell("crash-cell")
        cell_dir = bakeoff.cell_dir_for(self.run_dir, "crash-cell")
        cell_dir.mkdir(parents=True, exist_ok=True)
        result = _cell_result("crash-cell", cell_dir, status="error")
        entry = bakeoff.aggregate_cell(result, cell)
        self.assertEqual(entry["terminal_class"], "not_run")
        self.assertTrue(bakeoff._is_infrastructure_failure(entry))

    def test_infrastructure_failure_unfinished_recoverable(self):
        cell = _base_cell("pipe-cell")
        records = [{"type": "metadata"}, {"type": "terminal", "reason": "driver_broken_pipe"}]
        cell_dir = self._write_log("pipe-cell", records)
        entry = bakeoff.aggregate_cell(_cell_result("pipe-cell", cell_dir), cell)
        self.assertEqual(entry["terminal_class"], "unfinished_recoverable")
        self.assertTrue(bakeoff._is_infrastructure_failure(entry))

    def test_interrupted_not_run_cell_has_no_log(self):
        cell = _base_cell("missing-cell")
        cell_dir = bakeoff.cell_dir_for(self.run_dir, "missing-cell")
        cell_dir.mkdir(parents=True, exist_ok=True)
        entry = bakeoff.aggregate_cell(_cell_result("missing-cell", cell_dir, status="error"), cell)
        self.assertEqual(entry["terminal_class"], "not_run")
        self.assertIsNone(entry["match"])

    def test_absent_usage_reports_none_not_zero(self):
        cell = _base_cell("no-usage-cell")
        records = [{"type": "metadata"}, {"type": "terminal", "reason": "winner", "winner": 0}]
        cell_dir = self._write_log("no-usage-cell", records)
        entry = bakeoff.aggregate_cell(_cell_result("no-usage-cell", cell_dir), cell)
        self.assertIsNone(entry["compute"]["usage_measured"])

    def test_missing_round5_evidence_reports_unknown_not_interpolated(self):
        cell = _base_cell("short-cell")
        records = [{"type": "metadata"},
                  {"type": "driver", "line": {"type": "state", "turn": 2, "active_faction": 0, "terrain": []}},
                  {"type": "terminal", "reason": "max_turns", "winner": None}]
        cell_dir = self._write_log("short-cell", records)
        entry = bakeoff.aggregate_cell(_cell_result("short-cell", cell_dir), cell)
        self.assertTrue(entry["villages_round5_side0"]["unknown"])

    def test_every_scheduled_cell_appears_even_when_never_run(self):
        cells = [_base_cell("ran"), _base_cell("scheduled-only", model="other")]
        resolved = bakeoff.resolve_manifest(_small_manifest(cells=cells))
        cell_dir = self._write_log("ran", [{"type": "metadata"},
                                           {"type": "terminal", "reason": "winner", "winner": 0}])
        report = bakeoff.build_report(resolved, [_cell_result("ran", cell_dir)])
        ids = [entry["cell_id"] for entry in report["cells"]]
        self.assertEqual(ids, ["ran", "scheduled-only"])
        self.assertEqual(report["totals"]["scheduled"], 2)
        self.assertEqual(report["totals"]["not_run"], 1)
        self.assertEqual(report["totals"]["infrastructure_invalid"], 0)
        # A failure/absence must never be excluded from the denominators.
        self.assertEqual(report["configurations"]["other"]["cells"], 1)
        self.assertEqual(report["configurations"]["other"]["not_run"], 1)
        self.assertEqual(report["configurations"]["other"]["infrastructure_invalid"], 0)


class BaselineLockTests(unittest.TestCase):
    def test_lock_baseline_refuses_silent_relock(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            report = {"totals": {"scheduled": 1}}
            bakeoff.lock_baseline(run_dir, report)
            with self.assertRaises(bakeoff.ManifestError):
                bakeoff.lock_baseline(run_dir, {"totals": {"scheduled": 2}})
            baseline = json.loads((run_dir / "baseline.json").read_text())
            self.assertEqual(baseline["report"]["totals"]["scheduled"], 1)

    def test_lock_baseline_force_relock(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            bakeoff.lock_baseline(run_dir, {"totals": {"scheduled": 1}})
            bakeoff.lock_baseline(run_dir, {"totals": {"scheduled": 2}}, force=True)
            baseline = json.loads((run_dir / "baseline.json").read_text())
            self.assertEqual(baseline["report"]["totals"]["scheduled"], 2)


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class RealDriverIntegrationTests(unittest.TestCase):
    """A 2-configuration x 2-side manifest run through four tiny deterministic
    responder cells (an --orders-file fixture, not a real model). Proves
    isolation, catalog import, and stable report ordering end to end."""

    def _manifest(self) -> dict:
        cells = []
        for config in ("test-responder-a", "test-responder-b"):
            for side in (0, 1):
                cells.append(_base_cell(f"{config}-side{side}", model=config, llm_side=side,
                                        configuration=config, driver=str(DRIVER)))
        return {"objective": "offline 2x2 bakeoff smoke test", "cells": cells}

    def test_four_cell_manifest_runs_imports_and_reports_stably(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            resolved = bakeoff.resolve_manifest(self._manifest())
            results = bakeoff.run_manifest(resolved, run_dir, timeout=60)
            self.assertEqual(len(results), 4)
            for result in results:
                self.assertEqual(result.status, "ok", result.error)
                self.assertTrue(result.log_path.is_file())
            imported = bakeoff.import_cells(run_dir / "catalog.sqlite", results, "bakeoff-test")
            self.assertEqual(len(imported), 4)
            conn = game_history.open_history(run_dir / "catalog.sqlite", read_only=True)
            try:
                rows = conn.execute("SELECT game_id FROM games WHERE cohort_id=?",
                                   ("bakeoff-test",)).fetchall()
            finally:
                conn.close()
            self.assertEqual(len(rows), 4)

            report = bakeoff.build_report(resolved, results)
            self.assertEqual(report["totals"]["scheduled"], 4)
            self.assertEqual(report["totals"]["completed"], 4)
            ids = [entry["cell_id"] for entry in report["cells"]]
            self.assertEqual(ids, [cell["id"] for cell in resolved["cells"]])
            self.assertTrue(report["comparison"]["valid"])

            # Reaggregation from the same results is idempotent.
            report_again = bakeoff.build_report(resolved, results)
            self.assertEqual(json.dumps(report, sort_keys=True), json.dumps(report_again, sort_keys=True))

            # A duplicate identical import stays idempotent too.
            imported_again = bakeoff.import_cells(run_dir / "catalog.sqlite", results, "bakeoff-test")
            self.assertEqual(sorted(imported_again), sorted(imported))

    def test_only_cell_runs_exactly_one_and_reruns_are_recorded_not_restarted(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            resolved = bakeoff.resolve_manifest(self._manifest())
            one_id = resolved["cells"][0]["id"]
            results = bakeoff.run_manifest(resolved, run_dir, only_cell=one_id, timeout=60)
            self.assertEqual([r.cell_id for r in results], [one_id])
            first_ended_at = results[0].ended_at
            # Running the full manifest again must not restart the already-run cell.
            results_all = bakeoff.run_manifest(resolved, run_dir, timeout=60)
            first_result = next(r for r in results_all if r.cell_id == one_id)
            self.assertEqual(first_result.ended_at, first_ended_at)


class CliSmokeTest(unittest.TestCase):
    def test_module_is_invocable_and_reports_usage_error(self):
        completed = subprocess.run([sys.executable, "-m", "tools.model_bakeoff"],
                                   cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(completed.returncode, 0)


if __name__ == "__main__":
    unittest.main()
