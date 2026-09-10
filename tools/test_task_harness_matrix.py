"""Offline 24-cell Stack 4 acceptance through the real driver."""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from . import game_history
from . import model_bakeoff

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))

@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running matrix acceptance")
class TaskHarnessMatrixTests(unittest.TestCase):
    def test_checked_in_matrix_is_the_runnable_24_cell_design(self):
        checked_in = json.loads((ROOT / "tools/fixtures/task_harness/matrix.json").read_text())
        cells = checked_in["cells"]
        expected = {f"{family}-v{variant}-{arm}"
                    for family in ("opening_deployment", "competing_villages",
                                   "recruiter_defense", "coordinated_combat")
                    for variant in (1, 2) for arm in ("A", "B", "C")}
        self.assertEqual({c["id"] for c in cells}, expected)
        self.assertEqual(len(cells), 24)
        self.assertEqual({c["backend"]["kind"] for c in cells}, {"command"})
        self.assertEqual({c["model"] for c in cells}, {"offline-fixture"})
        self.assertEqual({c["position_family"] for c in cells},
                         {"opening_deployment", "competing_villages",
                          "recruiter_defense", "coordinated_combat"})
        for family in {c["position_family"] for c in cells}:
            for variant in (1, 2):
                self.assertEqual({c["arm"] for c in cells
                                  if c["position_family"] == family and c["variant"] == variant},
                                 {"A", "B", "C"})

    def test_all_24_isolated_cells_run_import_and_report(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            manifest = json.loads((ROOT / "tools/fixtures/task_harness/matrix.json").read_text())
            resolved = model_bakeoff.resolve_manifest(manifest)
            self.assertTrue(model_bakeoff.check_comparison_validity(resolved)["valid"])
            self.assertEqual(len(resolved["cells"]), 24)
            results = model_bakeoff.run_manifest(resolved, run_dir, timeout=60)
            self.assertEqual(len(results), 24)
            self.assertTrue(all(result.status == "ok" for result in results),
                            [result.error for result in results if result.status != "ok"])
            self.assertEqual(len({result.cell_dir for result in results}), 24)
            self.assertTrue(all(result.log_path.is_file() for result in results))

            cohort = "offline-matrix"
            imported = model_bakeoff.import_cells(run_dir / "catalog.sqlite", results, cohort)
            self.assertEqual(len(imported), 24)
            conn = game_history.open_history(run_dir / "catalog.sqlite", read_only=True)
            try:
                self.assertEqual(conn.execute("SELECT count(*) FROM games WHERE cohort_id=?",
                                              (cohort,)).fetchone()[0], 24)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()
            report = model_bakeoff.build_report(resolved, results,
                                                catalog_path=run_dir / "catalog.sqlite",
                                                cohort_id=cohort)
            self.assertEqual(report["totals"]["scheduled"], 24)
            self.assertEqual(report["totals"]["completed"], 24)
            self.assertTrue(all(cell["objective_success"] is True for cell in report["cells"]), report["cells"])
            self.assertTrue(all(cell["task_success"] is True for cell in report["cells"]), report["cells"])
            self.assertTrue(all(cell["useful_action_achieved"] is True for cell in report["cells"]), report["cells"])
            self.assertTrue(all(cell["action_encoding"] == "choices" and cell["telemetry"]["handle_choices_used"] > 0
                                for cell in report["cells"] if cell["arm"] == "C"), report["cells"])
            # Import rewrites SQLite pages. Idempotence concerns evidence and
            # logical results, not the database file's physical page layout.
            def counts():
                conn = game_history.open_history(run_dir / "catalog.sqlite", read_only=True)
                try:
                    return {table: conn.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                            for table in ('games', 'model_calls', 'model_requests', 'side_turns',
                                          'snapshots', 'events', 'action_batches', 'actions')}
                finally:
                    conn.close()

            def archive_hashes():
                return {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                        for result in results for path in result.cell_dir.rglob('*') if path.is_file()}

            before_counts, before_archives = counts(), archive_hashes()
            model_bakeoff.import_cells(run_dir / "catalog.sqlite", results, cohort)
            self.assertEqual(before_counts, counts())
            self.assertEqual(before_archives, archive_hashes())
            again = model_bakeoff.build_report(resolved, results,
                                                catalog_path=run_dir / "catalog.sqlite",
                                                cohort_id=cohort)
            self.assertEqual(json.dumps(report, sort_keys=True), json.dumps(again, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
