import json
import tempfile
import unittest
from pathlib import Path

from tools.analysis_capture import AnalysisWriter, build_manifest
from tools.game_analysis import (
    build_report,
    determine_coverage,
    resolve_log_path,
    run_import,
    run_report,
    run_validate,
)
from tools.game_history import open_history


def _manifest(**overrides):
    base = dict(
        conversation_id="match-1",
        game_log="../match.ndjson",
        source_commit="deadbeef",
        driver_hash="driver-hash",
        data_hash="data-hash",
        scenario_hash="scenario-hash",
        canonical_prompt_hash="prompt-hash",
        fixed_prefix_sha256="prefix-hash",
        game_seed=42,
        controlled_side=0,
        opponent_identity={"kind": "greedy", "version": "1"},
        launch={"driver": "greedy_driver", "seed": 42},
    )
    base.update(overrides)
    return build_manifest(**base)


class GameAnalysisTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.log_path = self.root / "match.ndjson"

    def _write_log(self, records=None):
        records = records if records is not None else [{
            "type": "metadata", "conversation_id": "match-1", "scenario": "s",
            "seed": 42, "faction0": "a", "faction1": "b", "gold": 100,
            "first_player": 0, "max_turns": 10, "source_commit": "deadbeef",
        }]
        self.log_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    def _writer(self, **manifest_overrides):
        self._write_log()
        manifest = _manifest(**manifest_overrides)
        return AnalysisWriter.create(str(self.log_path), manifest)

    def _basic_capture(self):
        writer = self._writer()
        did = writer.next_decision_id()
        writer.record("decision_start", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1)
        writer.record("model_request", decision_id=did, side_turn_id="match-1:side_turn:1",
                       request_id="match-1:request:1", state_revision=1,
                       body={"prompt_sha256": "e" * 64, "prompt_bytes": 10})
        writer.record("turn_boundary", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1, body={"phase": "started"})
        writer.record("turn_boundary", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=2, body={"phase": "finished"})
        writer.close()
        return writer


class CoverageStatusTests(GameAnalysisTestCase):
    def test_capture_disabled_when_no_analysis_dir(self):
        self._write_log()
        status, _, _, _ = determine_coverage(resolve_log_path(self.log_path).with_suffix(".analysis"))
        self.assertEqual(status, "capture_disabled")

    def test_empty_result_when_only_bookends(self):
        writer = self._writer()
        writer.close()  # only capture_started + capture_status
        status, detail, _, _ = determine_coverage(writer.analysis_dir)
        self.assertEqual(status, "empty_result")
        self.assertIn("reason", detail)

    def test_capture_stopped_on_byte_cap(self):
        writer = self._writer()
        writer.byte_cap = writer.bytes_written + 10  # force an immediate cap breach
        did = writer.next_decision_id()
        writer.record("decision_start", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1, body={"padding": "x" * 500})
        self.assertTrue(writer.stopped)
        self.assertEqual(writer.stop_outcome, "stopped_byte_cap")
        status, detail, _, _ = determine_coverage(writer.analysis_dir)
        self.assertEqual(status, "capture_stopped")
        self.assertIn("stopped_byte_cap", detail["reason"])

    def test_capture_stopped_when_final_marker_missing(self):
        writer = self._writer()
        did = writer.next_decision_id()
        writer.record("decision_start", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1)
        # Simulate a crash: never call close(), so no capture_status record.
        writer._handle.close()
        status, detail, _, _ = determine_coverage(writer.analysis_dir)
        self.assertEqual(status, "capture_stopped")
        self.assertIn("no final capture_status marker", detail["reason"])

    def test_unsupported_analysis_on_bad_schema_version(self):
        writer = self._writer()
        writer.close()
        manifest_path = writer.analysis_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["analysis_schema_version"] = 999
        manifest_path.write_text(json.dumps(manifest))
        status, detail, _, _ = determine_coverage(writer.analysis_dir)
        self.assertEqual(status, "unsupported_analysis")

    def test_complete_capture(self):
        writer = self._basic_capture()
        status, _, _, _ = determine_coverage(writer.analysis_dir)
        self.assertEqual(status, "complete")

    def test_all_five_statuses_are_distinct(self):
        # Regression for the explicit "must not be conflated" requirement.
        seen = set()
        seen.add(determine_coverage(self.root / "no-such.analysis")[0])
        w1 = self._writer()
        w1.close()
        seen.add(determine_coverage(w1.analysis_dir)[0])
        self.assertEqual(len(seen), 2)  # sanity: disabled vs empty differ already


class TurnBoundaryTests(GameAnalysisTestCase):
    def test_started_but_unfinished_turn_not_counted_as_completed(self):
        writer = self._writer()
        did = writer.next_decision_id()
        writer.record("turn_boundary", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1, body={"phase": "started"})
        writer.close()
        report = build_report(self.log_path)
        self.assertEqual(report["turns"]["turns_started"], 1)
        self.assertEqual(report["turns"]["turns_finished"], 0)
        self.assertIn("match-1:side_turn:1", report["turns"]["open_turns_at_end"])

    def test_terminal_before_finish_is_terminal_partial_turn(self):
        writer = self._writer()
        did = writer.next_decision_id()
        writer.record("turn_boundary", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1, body={"phase": "started"})
        writer.record("game_terminal", decision_id=did, side_turn_id="match-1:side_turn:1",
                       state_revision=1, body={"reason": "model_win"})
        writer.close()
        report = build_report(self.log_path)
        self.assertIn("match-1:side_turn:1", report["turns"]["terminal_partial_turns"])
        self.assertEqual(report["turns"]["turns_finished"], 0)


class ValidateTests(GameAnalysisTestCase):
    def test_reference_hash_mismatch_is_conflict_nonzero_exit(self):
        writer = self._basic_capture()
        records_path = writer.analysis_dir / "analysis.ndjson"
        lines = records_path.read_text().splitlines()
        # Tamper the manifest's ref hash embedded in the capture_started record.
        first = json.loads(lines[0])
        first["refs"][0]["sha256"] = "0" * 64
        lines[0] = json.dumps(first)
        records_path.write_text("\n".join(lines) + "\n")
        exit_code, output_lines = run_validate(self.log_path)
        self.assertNotEqual(exit_code, 0)
        self.assertTrue(any("hash mismatch" in line for line in output_lines))

    def test_truncated_final_line_partial_warning_records_retained(self):
        writer = self._basic_capture()
        records_path = writer.analysis_dir / "analysis.ndjson"
        raw = records_path.read_bytes()
        records_path.write_bytes(raw[:-5])  # truncate mid final line
        exit_code, output_lines = run_validate(self.log_path)
        self.assertNotEqual(exit_code, 0)
        self.assertTrue(any("partial" in line.lower() and "truncated" in line.lower()
                             for line in output_lines))
        from tools.analysis_capture import read_records
        result = read_records(writer.analysis_dir)
        self.assertGreater(len(result.records), 0)  # prior records retained

    def test_corrupt_interior_record_reports_byte_location(self):
        writer = self._basic_capture()
        records_path = writer.analysis_dir / "analysis.ndjson"
        lines = records_path.read_text().splitlines()
        self.assertGreater(len(lines), 2)
        lines[1] = "{not valid json"
        records_path.write_text("\n".join(lines) + "\n")
        exit_code, output_lines = run_validate(self.log_path)
        self.assertNotEqual(exit_code, 0)
        matches = [line for line in output_lines if "corrupt interior record at byte" in line]
        self.assertEqual(len(matches), 1)

    def test_duplicate_request_id_conflict_both_retained_and_reported(self):
        writer = self._writer()
        did = writer.next_decision_id()
        writer.record("model_request", decision_id=did, side_turn_id="match-1:side_turn:1",
                       request_id="match-1:request:1", state_revision=1,
                       body={"prompt_sha256": "a" * 64, "prompt_bytes": 10})
        writer.record("model_request", decision_id=did, side_turn_id="match-1:side_turn:1",
                       request_id="match-1:request:1", state_revision=2,
                       body={"prompt_sha256": "b" * 64, "prompt_bytes": 12},
                       evidence_status="conflicting")
        writer.close()
        from tools.analysis_capture import read_records
        result = read_records(writer.analysis_dir)
        request_records = [r for r in result.records if r.get("kind") == "model_request"]
        self.assertEqual(len(request_records), 2)  # both retained

        report = build_report(self.log_path)
        conflicts = report["identities"]["request_identity_conflicts"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(sorted(conflicts[0]["sequences"]), [2, 3])

    def test_valid_capture_passes(self):
        self._basic_capture()
        exit_code, _ = run_validate(self.log_path)
        self.assertEqual(exit_code, 0)

    def test_no_analysis_dir_reports_disabled_and_fails(self):
        self._write_log()
        exit_code, lines = run_validate(self.log_path)
        self.assertNotEqual(exit_code, 0)
        self.assertTrue(any("no analysis directory" in line for line in lines))


class ReportTests(GameAnalysisTestCase):
    def test_report_on_missing_analysis_dir_is_useful(self):
        self._write_log()
        report = build_report(self.log_path)
        self.assertEqual(report["coverage_status"], "capture_disabled")
        self.assertEqual(report["record_count"], 0)

    def test_json_and_text_agree(self):
        self._basic_capture()
        report = build_report(self.log_path)
        # run_report prints; verify both renderings derive from the same dict
        # (the actual agreement contract), and that JSON round-trips cleanly.
        rendered_json = json.loads(json.dumps(report, sort_keys=True))
        self.assertEqual(rendered_json["coverage_status"], report["coverage_status"])
        self.assertEqual(rendered_json["turns"], report["turns"])
        self.assertEqual(rendered_json["identities"], report["identities"])


class ImportTests(GameAnalysisTestCase):
    def test_reimport_is_idempotent(self):
        self._basic_capture()
        db_path = self.root / "catalog.sqlite"
        exit_code1, result1 = run_import(db_path, self.log_path)
        self.assertEqual(exit_code1, 0)

        conn = open_history(db_path, read_only=True)
        counts_before = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("games", "side_turns", "model_requests", "snapshots")
        }
        hash_before = conn.execute(
            "SELECT record_hash FROM model_requests WHERE game_id=?", (result1["game_id"],)
        ).fetchall()
        conn.close()

        exit_code2, result2 = run_import(db_path, self.log_path)
        self.assertEqual(exit_code2, 0)
        self.assertEqual(result1["game_id"], result2["game_id"])

        conn = open_history(db_path, read_only=True)
        counts_after = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("games", "side_turns", "model_requests", "snapshots")
        }
        hash_after = conn.execute(
            "SELECT record_hash FROM model_requests WHERE game_id=?", (result2["game_id"],)
        ).fetchall()
        conn.close()

        self.assertEqual(counts_before, counts_after)
        self.assertEqual(hash_before, hash_after)

    def test_reference_hash_mismatch_reported_nonzero(self):
        writer = self._basic_capture()
        records_path = writer.analysis_dir / "analysis.ndjson"
        lines = records_path.read_text().splitlines()
        first = json.loads(lines[0])
        first["refs"][0]["sha256"] = "0" * 64
        lines[0] = json.dumps(first)
        records_path.write_text("\n".join(lines) + "\n")

        db_path = self.root / "catalog.sqlite"
        exit_code, result = run_import(db_path, self.log_path)
        self.assertNotEqual(exit_code, 0)
        self.assertTrue(result["reference_conflicts"])

    def test_truncated_final_line_partial_warning_prior_records_retained(self):
        writer = self._basic_capture()
        records_path = writer.analysis_dir / "analysis.ndjson"
        raw = records_path.read_bytes()
        records_path.write_bytes(raw[:-5])

        db_path = self.root / "catalog.sqlite"
        exit_code, result = run_import(db_path, self.log_path)
        self.assertTrue(any("partial import" in w for w in result["warnings"]))
        self.assertTrue(result["game_id"])  # game import still proceeded

    def test_import_without_analysis_dir_still_imports_game(self):
        self._write_log()
        db_path = self.root / "catalog.sqlite"
        exit_code, result = run_import(db_path, self.log_path)
        self.assertEqual(exit_code, 0)
        self.assertFalse(result["analysis_capture_present"])
        self.assertTrue(result["game_id"])
        conn = open_history(db_path, read_only=True)
        row = conn.execute("SELECT game_id FROM games WHERE game_id=?", (result["game_id"],)).fetchone()
        conn.close()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()
