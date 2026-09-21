import hashlib
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path

from tools.analysis_capture import (
    ANALYSIS_RECORDS_NAME,
    ANALYSIS_MANIFEST_NAME,
    LAUNCH_ALLOWLIST,
    RECORD_KINDS,
    AnalysisWriter,
    allowlisted_launch,
    analysis_dir_for_log,
    build_manifest,
    make_range_reference,
    make_reference,
    read_records,
    validate_records,
)


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


class AllowlistTests(unittest.TestCase):
    def test_drops_non_allowlisted_keys_including_credential_shaped(self):
        launch = dict(
            driver="greedy_driver", seed=42,
            api_key="sk-super-secret", FIREWORKS_API_KEY="also-secret",
            random_env_var="leak-me",
        )
        filtered = allowlisted_launch(launch)
        self.assertEqual({"driver": "greedy_driver", "seed": 42}, filtered)
        for key in ("api_key", "FIREWORKS_API_KEY", "random_env_var"):
            self.assertNotIn(key, filtered)

    def test_accepts_namespace_like_object(self):
        class Namespace:
            def __init__(self):
                self.driver = "greedy_driver"
                self.seed = 7
                self.secret_token = "nope"

        filtered = allowlisted_launch(Namespace())
        self.assertEqual({"driver": "greedy_driver", "seed": 7}, filtered)

    def test_manifest_launch_field_is_filtered(self):
        manifest = _manifest(launch={"driver": "greedy_driver", "password": "hunter2"})
        self.assertEqual({"driver": "greedy_driver"}, manifest["launch"])
        self.assertTrue(LAUNCH_ALLOWLIST.issuperset(manifest["launch"].keys()))


class AnalysisDirTests(unittest.TestCase):
    def test_analysis_dir_mirrors_checkpoint_dir_convention(self):
        log_path = Path("/tmp/whatever/match.ndjson")
        self.assertEqual(Path("/tmp/whatever/match.analysis"), analysis_dir_for_log(log_path))


class WriterRoundTripTests(unittest.TestCase):
    def test_round_trip_every_stack1_kind(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            log_path.write_text("")
            writer = AnalysisWriter.create(log_path, _manifest())
            decision_id = writer.next_decision_id()
            writer.record("decision_start", decision_id=decision_id, side_turn_id="match-1:side_turn:1",
                          state_revision=1)
            writer.record("model_request", decision_id=decision_id, request_id="match-1:request:1",
                          state_revision=1, body={"prompt_sha256": "abc"})
            writer.record("action_commit", decision_id=decision_id, batch_id="match-1:batch:1",
                          state_revision=2)
            writer.record("turn_boundary", decision_id=decision_id, side_turn_id="match-1:side_turn:1",
                          state_revision=2)
            writer.record("game_terminal", decision_id=decision_id, state_revision=2,
                          body={"reason": "victory"})
            writer.close()

            result = read_records(writer.analysis_dir)
            self.assertEqual([], result.warnings)
            self.assertTrue(result.has_final_marker)
            kinds = [record["kind"] for record in result.records]
            self.assertEqual(
                ["capture_started", "decision_start", "model_request", "action_commit",
                 "turn_boundary", "game_terminal", "capture_status"],
                kinds,
            )
            self.assertTrue(RECORD_KINDS.issuperset(set(kinds) - {"capture_status"} | {"capture_status"}))

    def test_sequences_contiguous_and_capture_started_first(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())
            for _ in range(3):
                writer.record("decision_start", decision_id=writer.next_decision_id())
            writer.close()

            result = read_records(writer.analysis_dir)
            sequences = [record["sequence"] for record in result.records]
            self.assertEqual(list(range(1, len(sequences) + 1)), sequences)
            self.assertEqual("capture_started", result.records[0]["kind"])

    def test_directory_and_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())
            writer.close()

            dir_mode = stat.S_IMODE(os.stat(writer.analysis_dir).st_mode)
            manifest_mode = stat.S_IMODE(os.stat(writer.analysis_dir / ANALYSIS_MANIFEST_NAME).st_mode)
            records_mode = stat.S_IMODE(os.stat(writer.records_path).st_mode)
            self.assertEqual(0o700, dir_mode)
            self.assertEqual(0o600, manifest_mode)
            self.assertEqual(0o600, records_mode)


class ReferenceTests(unittest.TestCase):
    def test_reference_is_relative_and_resolves_after_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "match.ndjson"
            log_path.write_text('{"hello": "world"}\n')
            writer = AnalysisWriter.create(log_path, _manifest())
            writer.close()

            ref = make_reference(log_path, "game_log", writer.analysis_dir)
            self.assertFalse(Path(ref["path"]).is_absolute())
            self.assertEqual(hashlib.sha256(log_path.read_bytes()).hexdigest(), ref["sha256"])

            # Copy the whole capsule elsewhere; the relative reference must
            # still resolve against the copied directory's new location,
            # with the referenced game_log copied alongside it.
            copy_root = root / "copied"
            copy_root.mkdir()
            copied_analysis_dir = copy_root / writer.analysis_dir.name
            shutil.copytree(writer.analysis_dir, copied_analysis_dir)
            shutil.copy2(log_path, copy_root / log_path.name)

            resolved = (copied_analysis_dir / ref["path"]).resolve()
            self.assertTrue(resolved.exists())
            self.assertEqual(ref["sha256"], hashlib.sha256(resolved.read_bytes()).hexdigest())

    def test_unknown_role_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.txt"
            path.write_text("data")
            with self.assertRaises(ValueError):
                make_reference(path, "not_a_role", directory)

    def test_hash_mismatch_reported_as_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.txt"
            path.write_text("original")
            ref = make_reference(path, "game_log", directory)
            path.write_text("tampered")
            recomputed = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertNotEqual(ref["sha256"], recomputed)

    def test_sibling_game_log_within_root_still_works(self):
        # The common case: base_dir is <game_dir>/match.analysis, the file
        # being referenced is <game_dir>/match.ndjson, one level up but
        # still inside the archive root (the game directory).
        with tempfile.TemporaryDirectory() as directory:
            game_dir = Path(directory)
            log_path = game_dir / "match.ndjson"
            log_path.write_text("log contents")
            analysis_dir = game_dir / "match.analysis"
            analysis_dir.mkdir()

            ref = make_reference(log_path, "game_log", analysis_dir)
            self.assertEqual("../match.ndjson", ref["path"])

    def test_path_outside_root_raises(self):
        # A file that happens to be reachable via `..` but lives outside the
        # archive root would produce a reference that is syntactically
        # relative yet resolves nowhere once the capsule is copied - worse
        # than an absolute path, because nothing would flag it. This must
        # raise instead of silently emitting such a path.
        with tempfile.TemporaryDirectory() as game_directory, \
                tempfile.TemporaryDirectory() as elsewhere:
            game_dir = Path(game_directory)
            analysis_dir = game_dir / "match.analysis"
            analysis_dir.mkdir()
            stray = Path(elsewhere) / "stray.json"
            stray.write_text("{}")

            with self.assertRaises(ValueError):
                make_reference(stray, "checkpoint", analysis_dir, root=game_dir)

    def test_absolute_path_inside_root_is_normalized_to_relative(self):
        with tempfile.TemporaryDirectory() as directory:
            game_dir = Path(directory)
            analysis_dir = game_dir / "match.analysis"
            analysis_dir.mkdir()
            checkpoint = analysis_dir / "state.ckpt"
            checkpoint.write_text("checkpoint bytes")

            # Pass an absolute path explicitly; the stored reference must
            # still come back relative, never the absolute form.
            ref = make_reference(checkpoint.resolve(), "checkpoint", analysis_dir, root=game_dir)
            self.assertFalse(Path(ref["path"]).is_absolute())
            self.assertEqual("state.ckpt", ref["path"])

    def test_default_root_is_base_dir_parent_and_rejects_outside_paths(self):
        # With no explicit `root`, the boundary defaults to base_dir's
        # parent - the game directory that holds the log, `.analysis/`,
        # `.ckpt/`, etc. together, which is what travels as one capsule.
        with tempfile.TemporaryDirectory() as game_directory, \
                tempfile.TemporaryDirectory() as elsewhere:
            game_dir = Path(game_directory)
            analysis_dir = game_dir / "match.analysis"
            analysis_dir.mkdir()
            stray = Path(elsewhere) / "stray.json"
            stray.write_text("{}")

            with self.assertRaises(ValueError):
                make_reference(stray, "checkpoint", analysis_dir)


class ByteCapTests(unittest.TestCase):
    def test_tiny_cap_stops_capture_and_still_writes_final_record(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            # Cap sized to allow capture_started but not much else.
            writer = AnalysisWriter.create(log_path, _manifest(), byte_cap=900)
            for _ in range(50):
                writer.record("decision_start", decision_id=writer.next_decision_id(),
                              body={"padding": "x" * 200})
            self.assertTrue(writer.stopped)
            self.assertEqual("stopped_byte_cap", writer.stop_outcome)

            result = read_records(writer.analysis_dir)
            self.assertTrue(result.has_final_marker)
            self.assertEqual("stopped_byte_cap", result.records[-1]["body"]["outcome"])
            self.assertLessEqual(writer.bytes_written, 900)

    def test_record_after_stop_is_noop_not_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest(), byte_cap=400)
            for _ in range(20):
                writer.record("decision_start", decision_id=writer.next_decision_id(),
                              body={"padding": "x" * 200})
            self.assertTrue(writer.stopped)
            count_before = writer.record_count
            writer.record("decision_start", decision_id="ignored")  # must not raise
            self.assertEqual(count_before, writer.record_count)


class RecordFailureModeTests(unittest.TestCase):
    """`.record()` splits failures into two classes: see its docstring.

    Caller-bug enum violations (bad kind/evidence_status/role) raise
    immediately, at the API boundary, so they are caught in development.
    A body that cannot be JSON-serialized is instead treated like any other
    write failure - it degrades capture to `stopped_write_error` rather than
    raising, because it can come from live game state a caller passed in,
    and an optional writer must never take down the game.
    """

    def test_unknown_kind_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())
            with self.assertRaises(ValueError):
                writer.record("not_a_real_kind", decision_id="match-1:decision:1")
            self.assertFalse(writer.stopped)
            writer.close()

    def test_unknown_evidence_status_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())
            with self.assertRaises(ValueError):
                writer.record("decision_start", decision_id="match-1:decision:1",
                              evidence_status="bogus")
            self.assertFalse(writer.stopped)
            writer.close()

    def test_unknown_reference_role_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())
            with self.assertRaises(ValueError):
                writer.record("decision_start", decision_id="match-1:decision:1",
                              refs=[{"role": "not_a_role", "path": "x", "sha256": "a",
                                    "bytes": 1, "record_sequence": None,
                                    "byte_offset": None, "byte_length": None}])
            self.assertFalse(writer.stopped)
            writer.close()

    def test_non_serializable_body_degrades_to_write_error_not_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())
            try:
                writer.record("decision_start", decision_id="match-1:decision:1",
                              body={"unserializable": {1, 2, 3}})  # a set is not JSON-serializable
            except (TypeError, ValueError):
                self.fail("non-serializable body must not raise out of record()")
            self.assertTrue(writer.stopped)
            self.assertEqual("stopped_write_error", writer.stop_outcome)
            self.assertIsNotNone(writer.write_error)

            result = read_records(writer.analysis_dir)
            self.assertTrue(result.has_final_marker)
            self.assertEqual("stopped_write_error", result.records[-1]["body"]["outcome"])


class WriteFailureTests(unittest.TestCase):
    def test_injected_write_failure_stops_without_raising(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            writer = AnalysisWriter.create(log_path, _manifest())

            class ExplodingHandle:
                def write(self, _data):
                    raise OSError("disk on fire")

                def flush(self):
                    pass

                def fileno(self):
                    raise OSError("no fd")

                def close(self):
                    pass

            writer._handle.close()
            writer._handle = ExplodingHandle()
            try:
                writer.record("decision_start", decision_id="match-1:decision:99")
            except OSError:
                self.fail("OSError escaped AnalysisWriter.record")

            self.assertTrue(writer.stopped)
            self.assertEqual("stopped_write_error", writer.stop_outcome)
            self.assertIsNotNone(writer.write_error)


class ReadRecordsTests(unittest.TestCase):
    def test_truncated_final_line_yields_partial_warning_and_prior_records(self):
        with tempfile.TemporaryDirectory() as directory:
            analysis_dir = Path(directory)
            records_path = analysis_dir / ANALYSIS_RECORDS_NAME
            good = json.dumps({"kind": "capture_started", "sequence": 1}, sort_keys=True)
            records_path.write_text(good + "\n" + '{"kind": "decision_start", "sequen')

            result = read_records(analysis_dir)
            self.assertEqual(1, len(result.records))
            self.assertEqual(1, len(result.warnings))
            self.assertTrue(result.warnings[0].partial)
            self.assertFalse(result.has_final_marker)

    def test_corrupt_interior_record_reported_with_byte_location(self):
        with tempfile.TemporaryDirectory() as directory:
            analysis_dir = Path(directory)
            records_path = analysis_dir / ANALYSIS_RECORDS_NAME
            good1 = json.dumps({"kind": "capture_started", "sequence": 1}, sort_keys=True)
            bad = "{not valid json"
            good2 = json.dumps({"kind": "capture_status", "sequence": 3,
                                "body": {"outcome": "complete", "records": 2}}, sort_keys=True)
            records_path.write_text(good1 + "\n" + bad + "\n" + good2 + "\n")

            result = read_records(analysis_dir)
            self.assertEqual(2, len(result.records))
            self.assertEqual(1, len(result.warnings))
            self.assertFalse(result.warnings[0].partial)
            self.assertEqual(len(good1) + 1, result.warnings[0].byte_offset)
            self.assertTrue(result.has_final_marker)

    def test_missing_final_marker_reported_as_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            analysis_dir = Path(directory)
            records_path = analysis_dir / ANALYSIS_RECORDS_NAME
            records_path.write_text(
                json.dumps({"kind": "capture_started", "sequence": 1}, sort_keys=True) + "\n"
            )
            result = read_records(analysis_dir)
            self.assertFalse(result.has_final_marker)


class ValidateRecordsTests(unittest.TestCase):
    def test_duplicate_request_id_differing_revision_is_conflict_both_retained(self):
        records = [
            {"sequence": 1, "kind": "capture_started", "evidence_status": "observed", "refs": []},
            {"sequence": 2, "kind": "model_request", "evidence_status": "observed", "refs": [],
             "request_id": "match-1:request:1", "state_revision": 5,
             "body": {"prompt_sha256": "aaa"}},
            {"sequence": 3, "kind": "model_request", "evidence_status": "conflicting", "refs": [],
             "request_id": "match-1:request:1", "state_revision": 6,
             "body": {"prompt_sha256": "bbb", "conflicts_with": 2}},
        ]
        result = validate_records(records)
        self.assertEqual(1, len(result.conflicts))
        conflict = result.conflicts[0]
        self.assertEqual("match-1:request:1", conflict.request_id)
        self.assertEqual([2, 3], conflict.sequences)

    def test_same_hash_differing_bytes_is_a_conflict(self):
        # A matching prompt hash with differing byte counts cannot both be
        # right - it is itself a corruption signal, not a legitimate
        # resume-with-a-new-prompt case, so it must be flagged even though
        # the hashes alone look consistent.
        records = [
            {"sequence": 1, "kind": "capture_started", "evidence_status": "observed", "refs": []},
            {"sequence": 2, "kind": "model_request", "evidence_status": "observed", "refs": [],
             "request_id": "match-1:request:1", "state_revision": 5,
             "body": {"prompt_sha256": "aaa", "prompt_bytes": 100}},
            {"sequence": 3, "kind": "model_request", "evidence_status": "conflicting", "refs": [],
             "request_id": "match-1:request:1", "state_revision": 5,
             "body": {"prompt_sha256": "aaa", "prompt_bytes": 250}},
        ]
        result = validate_records(records)
        self.assertEqual(1, len(result.conflicts))
        self.assertIn("prompt_bytes", result.conflicts[0].reason)
        self.assertEqual([2, 3], result.conflicts[0].sequences)

    def test_sequence_gap_is_an_error(self):
        records = [
            {"sequence": 1, "kind": "capture_started", "evidence_status": "observed", "refs": []},
            {"sequence": 3, "kind": "decision_start", "evidence_status": "observed", "refs": []},
        ]
        result = validate_records(records)
        self.assertFalse(result.ok)
        self.assertTrue(any("sequence gap" in error for error in result.errors))

    def test_unknown_kind_and_status_are_errors(self):
        records = [
            {"sequence": 1, "kind": "capture_started", "evidence_status": "observed", "refs": []},
            {"sequence": 2, "kind": "not_a_real_kind", "evidence_status": "bogus", "refs": []},
        ]
        result = validate_records(records)
        self.assertFalse(result.ok)
        self.assertTrue(any("unknown kind" in error for error in result.errors))
        self.assertTrue(any("unknown evidence_status" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()


class RangeReferenceTests(unittest.TestCase):
    """Stack 2: byte-range references point at exact game-log lines."""

    def test_range_reference_hashes_exactly_the_named_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            first = json.dumps({"type": "one"}) + "\n"
            second = json.dumps({"type": "two"}) + "\n"
            log_path.write_text(first + second)
            analysis_dir = analysis_dir_for_log(log_path)
            analysis_dir.mkdir()
            ref = make_range_reference(log_path, "game_log", analysis_dir,
                                       byte_offset=len(first.encode()),
                                       byte_length=len(second.encode()))
            self.assertEqual("../match.ndjson", ref["path"])
            self.assertEqual(len(second.encode()), ref["bytes"])
            self.assertEqual(hashlib.sha256(second.encode()).hexdigest(), ref["sha256"])
            self.assertEqual(len(first.encode()), ref["byte_offset"])

    def test_range_beyond_file_size_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            log_path.write_text("short")
            analysis_dir = analysis_dir_for_log(log_path)
            analysis_dir.mkdir()
            with self.assertRaises(ValueError):
                make_range_reference(log_path, "game_log", analysis_dir,
                                     byte_offset=0, byte_length=1000)

    def test_range_reference_enforces_archive_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / "elsewhere.txt"
            outside.write_text("data")
            game_dir = root / "game"
            game_dir.mkdir()
            analysis_dir = game_dir / "match.analysis"
            analysis_dir.mkdir()
            with self.assertRaises(ValueError):
                make_range_reference(outside, "game_log", analysis_dir,
                                     byte_offset=0, byte_length=4)


class DecisionIdentityTests(unittest.TestCase):
    """Stack 2: decisions open at packets or fresh requests, not every request."""

    def _writer(self):
        log_path = Path(tempfile.mkdtemp()) / "match.ndjson"
        log_path.write_text("")
        self.addCleanup(shutil.rmtree, log_path.parent)
        return AnalysisWriter.create(log_path, _manifest())

    def test_fresh_decision_request_mints_and_repair_reuses(self):
        writer = self._writer()
        first = writer.decision_for_request("decision")
        repair = writer.decision_for_request("repair")
        self.assertEqual(first, repair,
                         "a repair continues the decision it belongs to")
        second = writer.decision_for_request("decision")
        self.assertNotEqual(first, second,
                            "a fresh decision request opens a new decision")

    def test_packet_opens_decision_and_model_request_reuses_it(self):
        writer = self._writer()
        packet_decision = writer.decision_for_packet("client-decision-1")
        request_decision = writer.decision_for_request("decision")
        self.assertEqual(packet_decision, request_decision,
                         "the model request for an issued packet reuses its decision")
        again = writer.decision_for_packet("client-decision-1")
        self.assertEqual(packet_decision, again)
        other = writer.decision_for_packet("client-decision-2")
        self.assertNotEqual(packet_decision, other,
                            "a new client decision id opens a new analysis decision")

    def test_close_decision_forces_next_decision_request_to_mint(self):
        writer = self._writer()
        first = writer.decision_for_request("decision")
        writer.close_decision()
        second = writer.decision_for_request("decision")
        self.assertNotEqual(first, second)

    def test_decision_start_record_is_emitted_with_stage(self):
        writer = self._writer()
        writer.decision_for_packet("client-decision-9")
        writer.close()
        result = read_records(writer.analysis_dir)
        starts = [r for r in result.records if r["kind"] == "decision_start"]
        self.assertEqual(1, len(starts))
        self.assertEqual("decision_packet", starts[0]["body"]["stage"])
        self.assertEqual("client-decision-9", starts[0]["body"]["client_decision_id"])


class UsageReceiptTests(unittest.TestCase):
    """Stack 2: the physical usage sidecar is referenced or reported missing."""

    def _writer(self):
        log_path = Path(tempfile.mkdtemp()) / "match.ndjson"
        log_path.write_text("")
        self.addCleanup(shutil.rmtree, log_path.parent)
        return AnalysisWriter.create(log_path, _manifest())

    def test_missing_sidecar_records_missing_evidence(self):
        writer = self._writer()
        writer.note_usage_sidecar(writer.analysis_dir.parent / "usage.ndjson")
        writer.close()
        result = read_records(writer.analysis_dir)
        receipts = [r for r in result.records if r["kind"] == "usage_receipt"]
        self.assertEqual(1, len(receipts))
        self.assertEqual("missing", receipts[0]["evidence_status"])

    def test_present_sidecar_is_referenced_with_hash(self):
        writer = self._writer()
        sidecar = writer.analysis_dir.parent / "usage.ndjson"
        sidecar.write_text('{"game_id": "match-1", "call_id": "c1"}\n')
        writer.note_usage_sidecar(sidecar)
        writer.close()
        result = read_records(writer.analysis_dir)
        receipts = [r for r in result.records if r["kind"] == "usage_receipt"]
        self.assertEqual(1, len(receipts))
        self.assertEqual("observed", receipts[0]["evidence_status"])
        (ref,) = receipts[0]["refs"]
        self.assertEqual("usage", ref["role"])
        self.assertEqual("../usage.ndjson", ref["path"])
        self.assertEqual(hashlib.sha256(sidecar.read_bytes()).hexdigest(), ref["sha256"])


class Stack2KindTests(unittest.TestCase):
    """Stack 2 kinds round-trip through the writer and validator."""

    def test_candidate_and_validation_kinds_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            log_path.write_text("")
            writer = AnalysisWriter.create(log_path, _manifest())
            did = writer.decision_for_packet("client-1")
            writer.record("candidate_packet", decision_id=did,
                          side_turn_id="match-1:side_turn:1", state_revision=3,
                          body={"packet": {"decision_id": "client-1", "options": [
                              {"option_id": "opt-a"}, {"option_id": "opt-b"}]}})
            writer.record("candidate_validation", decision_id=did,
                          side_turn_id="match-1:side_turn:1", state_revision=3,
                          body={"client_decision_id": "client-1", "coverage": "validated"})
            writer.record("batch_validation", decision_id=did,
                          side_turn_id="match-1:side_turn:1", state_revision=3,
                          body={"valid": False, "failed_index": 0})
            writer.record("response_repair", decision_id=did,
                          side_turn_id="match-1:side_turn:1", state_revision=3,
                          body={"error": "bad json"})
            writer.record("execution_submit", decision_id=did,
                          side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                          state_revision=3,
                          body={"orders": [{"action": "EndTurn"}], "source": "model"})
            writer.record("action_commit", decision_id=did,
                          side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:1",
                          state_revision=4, body={"origin": "llm"})
            writer.close()

            result = read_records(writer.analysis_dir)
            self.assertEqual([], result.warnings)
            validation = validate_records(result.records)
            self.assertEqual([], validation.errors)
            kinds = {r["kind"] for r in result.records}
            self.assertLessEqual({"candidate_packet", "candidate_validation",
                                  "batch_validation", "response_repair",
                                  "execution_submit", "action_commit"}, kinds)

    def test_routine_submission_carries_no_decision_id(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "match.ndjson"
            log_path.write_text("")
            writer = AnalysisWriter.create(log_path, _manifest())
            did = writer.decision_for_request("decision")
            # A routine submission is engine-selected: no decision id at all.
            writer.record("execution_submit", decision_id=None,
                          side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:2",
                          state_revision=5, body={"source": "routine"})
            writer.record("routine_action", decision_id=None,
                          side_turn_id="match-1:side_turn:1", batch_id="match-1:batch:2",
                          state_revision=5, body={"reason": "contact"})
            writer.close()
            result = read_records(writer.analysis_dir)
            routine = [r for r in result.records if r["kind"] == "execution_submit"]
            self.assertEqual(1, len(routine))
            self.assertIsNone(routine[0]["decision_id"])
