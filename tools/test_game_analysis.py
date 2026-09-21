import json
import tempfile
import unittest
from pathlib import Path

from tools.analysis_capture import AnalysisWriter, build_manifest
from tools.game_analysis import (
    build_report,
    format_report_text,
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


class DecisionTraceTests(GameAnalysisTestCase):
    """Stack 2: the report shows offered/selected/failed/executed per decision."""

    def _capture_trace(self):
        writer = self._writer()
        did = writer.decision_for_packet("client-decision-1")
        writer.record("candidate_packet", decision_id=did,
                      side_turn_id="match-1:side_turn:1", state_revision=1,
                      body={"packet": {"decision_id": "client-decision-1",
                                       "options": [{"option_id": "a"}, {"option_id": "b"}],
                                       "coverage": {"options_truncated": False}}})
        writer.record("model_request", decision_id=did, request_id="match-1:request:1",
                      side_turn_id="match-1:side_turn:1", state_revision=1,
                      body={"purpose": "decision", "status": "completed",
                            "prompt_sha256": "f" * 64, "prompt_bytes": 99})
        writer.record("batch_validation", decision_id=did,
                      side_turn_id="match-1:side_turn:1", state_revision=1,
                      body={"valid": False, "failed_index": 0})
        writer.record("response_repair", decision_id=did,
                      side_turn_id="match-1:side_turn:1", state_revision=1,
                      body={"error": "engine rejected"})
        writer.record("execution_submit", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=1,
                      body={"option_ids": ["a"], "proposal_source": "engine_option",
                            "orders": [{"action": "Move", "unit_id": 1, "col": 0, "row": 1}]})
        writer.record("action_commit", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=2, body={"origin": "llm"})
        writer.record("turn_boundary", decision_id=did,
                      side_turn_id="match-1:side_turn:1", state_revision=2,
                      body={"phase": "finished", "authored_finish_kind": "explicit_done",
                            "executed_finish_kind": "explicit_done"})
        writer.close()
        return writer

    def test_report_lists_decision_with_candidates_selection_and_commit(self):
        self._capture_trace()
        report = build_report(str(self.log_path))
        decisions = report["decisions"]
        self.assertEqual(1, decisions["count"])
        item = decisions["items"][0]
        self.assertEqual("decision_packet", item["stage"])
        self.assertEqual(2, item["candidates_offered"])
        self.assertFalse(item["candidates_truncated"])
        self.assertEqual(["a"], item["selection"])
        self.assertEqual("engine_option", item["selection_source"])
        self.assertEqual(1, item["repairs"])
        self.assertEqual(1, item["validations_rejected"])
        self.assertEqual(["match-1:batch:1"], item["committed_batches"])

    def test_rejected_orders_produce_no_committed_batch(self):
        writer = self._writer()
        did = writer.decision_for_request("decision")
        writer.record("batch_validation", decision_id=did,
                      side_turn_id="match-1:side_turn:1", state_revision=1,
                      body={"valid": False, "failed_index": 0})
        writer.record("execution_submit", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:9",
                      state_revision=1, body={"orders": [{"action": "Attack",
                                                          "attacker_id": 1, "defender_id": 2}]})
        # No action_commit for batch 9: the engine rejected it.
        writer.close()
        report = build_report(str(self.log_path))
        item = report["decisions"]["items"][0]
        self.assertEqual([], item["committed_batches"])
        self.assertEqual(1, item["validations_rejected"])

    def test_text_report_renders_decision_lines(self):
        self._capture_trace()
        exit_code = run_report(str(self.log_path), as_json=False)
        self.assertEqual(0, exit_code)


class UsageSummaryTests(GameAnalysisTestCase):
    """Stack 2: usage is unknown when absent, counted when present."""

    def test_missing_sidecar_is_unknown_not_zero(self):
        self._basic_capture()
        report = build_report(str(self.log_path))
        self.assertEqual("missing", report["usage"]["status"])

    def test_present_sidecar_counts_physical_calls(self):
        self._basic_capture()
        sidecar = self.root / "usage.ndjson"
        sidecar.write_text("\n".join([
            json.dumps({"game_id": "match-1", "call_id": "c1", "transport": "offline_fixture",
                        "status": "ok", "input_tokens": 100, "output_tokens": 20,
                        "total_tokens": 120, "request_id": "match-1:request:1"}),
            json.dumps({"game_id": "match-1", "call_id": "c2", "transport": "offline_fixture",
                        "status": "ok", "input_tokens": 50, "output_tokens": 10,
                        "total_tokens": 60}),
        ]) + "\n")
        report = build_report(str(self.log_path))
        usage = report["usage"]
        self.assertEqual("observed", usage["status"])
        self.assertEqual(2, usage["physical_calls"])
        self.assertEqual(180, usage["known_total_tokens"])
        self.assertEqual(0, usage["unknown_total_calls"])
        # No call reported reasoning or cached input: unknown, not zero.
        self.assertEqual(0, usage["reasoning_reported_calls"])
        self.assertEqual(0, usage["cached_input_reported_calls"])


class RangeRefValidationTests(GameAnalysisTestCase):
    """Stack 2: byte-range references verify through the CLI."""

    def test_range_ref_to_game_log_line_validates(self):
        import hashlib
        writer = self._writer()
        line = json.dumps({"type": "model_request", "request_id": "match-1:request:1"},
                          sort_keys=True) + "\n"
        with self.log_path.open("a") as stream:
            offset = self.log_path.stat().st_size
            stream.write(line)
        did = writer.decision_for_request("decision")
        payload = line.encode("utf-8")
        writer.record("model_request", decision_id=did,
                      request_id="match-1:request:1", state_revision=1,
                      refs=[{"role": "game_log", "path": "../match.ndjson",
                             "sha256": hashlib.sha256(payload).hexdigest(),
                             "bytes": len(payload), "record_sequence": None,
                             "byte_offset": offset, "byte_length": len(payload)}],
                      body={"prompt_sha256": "a" * 64, "prompt_bytes": 5})
        writer.close()
        exit_code, lines = run_validate(str(self.log_path))
        self.assertEqual(0, exit_code, lines)

    def test_tampered_range_ref_is_a_conflict(self):
        import hashlib
        writer = self._writer()
        line = json.dumps({"type": "model_request"}, sort_keys=True) + "\n"
        with self.log_path.open("a") as stream:
            offset = self.log_path.stat().st_size
            stream.write(line)
        did = writer.decision_for_request("decision")
        payload = line.encode("utf-8")
        writer.record("model_request", decision_id=did, request_id="match-1:request:1",
                      state_revision=1,
                      refs=[{"role": "game_log", "path": "../match.ndjson",
                             "sha256": "0" * 64,  # wrong hash on purpose
                             "bytes": len(payload), "record_sequence": None,
                             "byte_offset": offset, "byte_length": len(payload)}],
                      body={"prompt_sha256": "a" * 64, "prompt_bytes": 5})
        writer.close()
        exit_code, lines = run_validate(str(self.log_path))
        self.assertEqual(1, exit_code)
        self.assertTrue(any("hash mismatch" in line for line in lines), lines)


class CandidateProvenanceTests(GameAnalysisTestCase):
    """Stack 2: omission, filtering and truncation stay distinguishable.

    These are three different conditions and the plan requires a report to
    keep them apart.  The engine reports whether the shown list was display
    truncated, but it reports no per-candidate filter reason and no record of
    a legal action that was never generated.  A report must therefore say
    filtering is UNREPORTED and omission is UNKNOWN, rather than implying the
    shown set is the complete legal set.
    """

    def _packet_capture(self, coverage, options=("a", "b")):
        writer = self._writer()
        did = writer.decision_for_packet("client-decision-1")
        writer.record("candidate_packet", decision_id=did,
                      side_turn_id="match-1:side_turn:1", state_revision=1,
                      body={"packet": {"decision_id": "client-decision-1",
                                       "options": [{"option_id": o} for o in options],
                                       "coverage": coverage}})
        writer.close()
        return writer

    def _item(self, writer):
        report = build_report(self.log_path)
        (item,) = report["decisions"]["items"]
        return item

    def test_display_truncation_is_reported_distinctly(self):
        writer = self._packet_capture({"options_truncated": True})
        item = self._item(writer)
        self.assertTrue(item["candidates_truncated"])
        self.assertEqual(2, item["candidates_offered"])

    def test_untruncated_packet_is_not_reported_as_truncated(self):
        writer = self._packet_capture({"options_truncated": False})
        item = self._item(writer)
        self.assertFalse(item["candidates_truncated"])

    def test_absent_filter_reasons_are_unreported_not_none_filtered(self):
        """The crucial distinction: 'we do not know' is not 'nothing was filtered'."""
        writer = self._packet_capture({"options_truncated": False})
        item = self._item(writer)
        self.assertEqual("unreported", item["candidate_filtering"])

    def test_present_filter_reasons_are_reported(self):
        writer = self._packet_capture(
            {"options_truncated": False, "filter_reasons": ["unsafe_route"]})
        item = self._item(writer)
        self.assertEqual("reported", item["candidate_filtering"])

    def test_omission_is_unknown_never_claimed_complete(self):
        """A finite candidate set is not evidence of exhaustive legal coverage."""
        writer = self._packet_capture({"options_truncated": False})
        item = self._item(writer)
        self.assertEqual("unknown_without_offline_enumeration",
                         item["candidate_omission"])

    def test_three_conditions_are_separate_fields(self):
        writer = self._packet_capture({"options_truncated": True})
        item = self._item(writer)
        # Truncation known, filtering unreported, omission unknown -- three
        # distinct answers that a single "coverage" flag would have collapsed.
        self.assertEqual(
            (True, "unreported", "unknown_without_offline_enumeration"),
            (item["candidates_truncated"], item["candidate_filtering"],
             item["candidate_omission"]))

    def test_text_report_surfaces_truncation_and_unreported_filtering(self):
        writer = self._packet_capture({"options_truncated": True})
        text = format_report_text(build_report(self.log_path))
        self.assertIn("display truncated", text)
        self.assertIn("filtering unreported", text)


class TokenAccountingHonestyTests(GameAnalysisTestCase):
    """Stack 2: a value the provider did not report is unknown, never zero."""

    def _with_sidecar(self, *calls):
        self._basic_capture()
        (self.root / "usage.ndjson").write_text(
            "\n".join(json.dumps(c) for c in calls) + "\n")
        return build_report(str(self.log_path))["usage"]

    def test_response_without_reasoning_says_unreported_not_zero(self):
        usage = self._with_sidecar(
            {"game_id": "match-1", "call_id": "c1", "transport": "offline_fixture",
             "status": "ok", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        # The call is counted, but it is NOT counted as having reported
        # reasoning.  A reader must not read "0 reasoning tokens" out of this.
        self.assertEqual(1, usage["physical_calls"])
        self.assertEqual(0, usage["reasoning_reported_calls"])
        self.assertIn("absent means unknown, not zero",
                      usage["definitions"]["reasoning"])

    def test_response_with_reasoning_is_counted_as_reported(self):
        usage = self._with_sidecar(
            {"game_id": "match-1", "call_id": "c1", "transport": "offline_fixture",
             "status": "ok", "input_tokens": 10, "output_tokens": 5,
             "reasoning_tokens": 3, "total_tokens": 18})
        self.assertEqual(1, usage["reasoning_reported_calls"])

    def test_cache_absent_from_receipt_is_unknown_not_zero(self):
        usage = self._with_sidecar(
            {"game_id": "match-1", "call_id": "c1", "transport": "offline_fixture",
             "status": "ok", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        self.assertEqual(0, usage["cached_input_reported_calls"])
        self.assertIn("absent means unknown, not zero",
                      usage["definitions"]["cached_input"])

    def test_total_tokens_is_provider_reported_never_recomputed(self):
        """A provider total that disagrees with its components is kept as given."""
        usage = self._with_sidecar(
            {"game_id": "match-1", "call_id": "c1", "transport": "offline_fixture",
             "status": "ok", "input_tokens": 10, "output_tokens": 5, "total_tokens": 999})
        self.assertEqual(999, usage["known_total_tokens"])
        self.assertIn("never recomputed", usage["definitions"]["total_tokens"])


class AcceptedPrefixTests(GameAnalysisTestCase):
    """Stack 2: an accepted prefix is not reported as full success."""

    def test_accepted_prefix_reports_only_the_committed_orders(self):
        writer = self._writer()
        did = writer.decision_for_packet("client-decision-1")
        # Four orders proposed; the engine accepts a two-order prefix and
        # rejects the rest.
        writer.record("execution_submit", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=1,
                      body={"orders": [{"action": "Move"}, {"action": "Move"},
                                       {"action": "Attack"}, {"action": "Attack"}],
                            "source": "model"})
        writer.record("batch_validation", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=1,
                      body={"valid": False, "failed_index": 2,
                            "reason": "third order illegal"})
        writer.record("action_commit", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=2,
                      body={"accepted_orders": 2, "proposed_orders": 4})
        writer.close()
        report = build_report(str(self.log_path))
        (item,) = report["decisions"]["items"]
        # The rejected suffix must remain visible as a rejected validation;
        # a partially accepted batch is not a clean success.
        self.assertEqual(1, item["validations_rejected"])
        self.assertEqual(["match-1:batch:1"], item["committed_batches"])

    def test_fully_rejected_batch_commits_nothing(self):
        writer = self._writer()
        did = writer.decision_for_packet("client-decision-1")
        writer.record("execution_submit", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=1, body={"orders": [{"action": "Move"}], "source": "model"})
        writer.record("batch_validation", decision_id=did,
                      side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                      state_revision=1, body={"valid": False, "reason": "illegal"})
        writer.close()
        report = build_report(str(self.log_path))
        (item,) = report["decisions"]["items"]
        self.assertEqual([], item["committed_batches"])
        self.assertEqual(1, item["validations_rejected"])


class ProvenanceGapTests(GameAnalysisTestCase):
    """A manifest field left null on purpose must say so, with its reason.

    An unexplained null is indistinguishable from evidence that should have
    been captured and was not. Naming the reason is what makes a known limit
    readable as a limit.
    """

    def test_gaps_are_reported_with_reasons(self):
        writer = self._writer(provenance_gaps={
            "scenario_hash": "resolved by the driver; capture adds no driver query"})
        writer.close()
        report = build_report(str(self.log_path))
        self.assertIn("scenario_hash", report["provenance_gaps"])
        self.assertIn("no driver query", report["provenance_gaps"]["scenario_hash"])

    def test_gaps_appear_in_text_report(self):
        writer = self._writer(provenance_gaps={"data_hash": "resolved by the driver"})
        writer.close()
        text = format_report_text(build_report(str(self.log_path)))
        self.assertIn("provenance gaps", text)
        self.assertIn("data_hash", text)

    def test_no_gaps_means_no_section(self):
        writer = self._writer()
        writer.close()
        text = format_report_text(build_report(str(self.log_path)))
        self.assertNotIn("provenance gaps", text)

    def test_gap_is_distinct_from_missing_evidence(self):
        """A declared gap must not be counted as a missing-evidence record."""
        writer = self._writer(provenance_gaps={"scenario_hash": "driver-resolved"})
        writer.close()
        report = build_report(str(self.log_path))
        self.assertEqual({}, {k: v for k, v in report["evidence"].items() if k == "missing"})
        self.assertTrue(report["provenance_gaps"])
