import json
import tempfile
import unittest
from pathlib import Path

from . import collect_model_usage as cmu
from . import model_usage

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]

def manifest_dict(name: str) -> dict:
    """Load a checked-in manifest fixture, resolving its repo-root-relative paths."""
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    for key in ("host_evidence_path", "game_log_path", "request_handshake_dir"):
        raw[key] = str(REPO_ROOT / raw[key])
    return raw

class LoadManifestTests(unittest.TestCase):
    def test_valid_manifest_loads(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        self.assertEqual(manifest.game_id, "game-three-calls")
        self.assertEqual(manifest.host_thread_id, "thread-solo")
        self.assertTrue(manifest.host_evidence_path.is_file())
        self.assertTrue(manifest.game_log_path.is_file())
        self.assertTrue(manifest.request_handshake_dir.is_dir())

    def test_missing_field_is_rejected(self):
        data = manifest_dict("hostusage_manifest_three_calls.json")
        del data["host_thread_id"]
        with self.assertRaisesRegex(cmu.ManifestError, "host_thread_id"):
            cmu.load_manifest(data)

    def test_nonexistent_evidence_path_is_rejected(self):
        data = manifest_dict("hostusage_manifest_three_calls.json")
        data["host_evidence_path"] = str(REPO_ROOT / "tools/fixtures/does_not_exist.jsonl")
        with self.assertRaisesRegex(cmu.ManifestError, "host_evidence_path"):
            cmu.load_manifest(data)

    def test_handshake_dir_must_be_a_directory(self):
        data = manifest_dict("hostusage_manifest_three_calls.json")
        data["request_handshake_dir"] = str(REPO_ROOT / "tools/fixtures/hostusage_game_log.ndjson")
        with self.assertRaisesRegex(cmu.ManifestError, "request_handshake_dir"):
            cmu.load_manifest(data)

    def test_malformed_json_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "manifest.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(cmu.ManifestError, "not valid JSON"):
                cmu.load_manifest(path)

class CollectHostUsageTests(unittest.TestCase):
    def test_three_physical_responses_become_three_unlinked_calls(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        calls = cmu.collect_host_usage(manifest)
        self.assertEqual(len(calls), 3)
        response_ids = {call["provider_response_id"] for call in calls}
        self.assertEqual(response_ids, {"resp-inspect-1", "resp-tool-2", "resp-publish-3"})
        for call in calls:
            self.assertIsNone(call["request_id"])
            self.assertEqual(call["game_id"], "game-three-calls")
            self.assertEqual(call["native_thread_id"], "thread-solo")
            self.assertEqual(call["provider"], "codex_native")
            self.assertEqual(call["status"], "completed")
            self.assertIn(call["status"], model_usage.CALL_STATUSES)
            self.assertEqual(call["usage_source"], "token_usage_record")
            self.assertEqual(call["normalization_gaps"], [])
        by_response = {call["provider_response_id"]: call for call in calls}
        # reasoning_output_tokens on the wire maps to reasoning_tokens in the contract.
        self.assertEqual(by_response["resp-publish-3"]["input_tokens"], 260)
        self.assertEqual(by_response["resp-publish-3"]["output_tokens"], 60)
        self.assertEqual(by_response["resp-publish-3"]["reasoning_tokens"], 12)
        self.assertEqual(by_response["resp-publish-3"]["total_tokens"], 332)
        # call IDs are stable and distinct.
        ids = {call["call_id"] for call in calls}
        self.assertEqual(len(ids), 3)

    def test_cumulative_snapshots_and_turn_thread_totals_never_become_a_call_or_are_summed(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        report = cmu.collect_host_usage_report(manifest)
        calls = report["calls"]
        self.assertEqual(len(calls), 3)  # the three token_count event_msg lines add no calls.
        self.assertEqual(len(report["cumulative_snapshots"]), 3)
        totals = cmu.reconciliation_totals(manifest)
        self.assertTrue(totals["available"])
        self.assertEqual(totals["latest_info"]["total_token_usage"]["total_tokens"], 722)
        measured_total = sum(call["total_tokens"] for call in calls)
        self.assertEqual(measured_total, 150 + 240 + 332)
        # Each token_usage_record also carries turn_token_usage/thread_token_usage
        # (running totals) alongside its own per-response usage; only the
        # per-response usage is reflected in a call row.
        self.assertEqual(len(calls), 3)

    def test_task_complete_marks_the_thread_finalized(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        self.assertTrue(cmu.is_thread_finalized(manifest))

    def test_absent_task_complete_means_still_open_not_failed(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_conflict.json"))
        self.assertFalse(cmu.is_thread_finalized(manifest))

    def test_idempotent_recollection_yields_identical_rows(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        first = cmu.collect_host_usage(manifest)
        second = cmu.collect_host_usage(manifest)
        self.assertEqual(first, second)

    def test_two_host_threads_collected_separately_have_zero_cross_attribution(self):
        manifest_a = cmu.load_manifest(manifest_dict("hostusage_manifest_thread_a.json"))
        manifest_b = cmu.load_manifest(manifest_dict("hostusage_manifest_thread_b.json"))
        calls_a = cmu.collect_host_usage(manifest_a)
        calls_b = cmu.collect_host_usage(manifest_b)
        # Each thread's own two responses, and nothing from the other
        # thread's identified responses (the shared threadless record is
        # checked separately below).
        self.assertEqual({call["provider_response_id"] for call in calls_a},
                          {"resp-a-1", "resp-a-2", "resp-ambiguous-1"})
        self.assertEqual({call["provider_response_id"] for call in calls_b},
                          {"resp-b-1", "resp-b-2", "resp-ambiguous-1"})
        for call in calls_a:
            self.assertEqual(call["game_id"], "game-a")
            self.assertEqual(call["native_thread_id"], "thread-aaa")
        for call in calls_b:
            self.assertEqual(call["game_id"], "game-b")
            self.assertEqual(call["native_thread_id"], "thread-bbb")
        # "resp-ambiguous-1" carries no thread_id at all, so neither binding
        # can rule it out: it surfaces in both collections (each scoped to
        # its own game_id/thread_id) rather than being silently dropped from
        # either. Nothing here merges those two rows into one call, and each
        # is a distinct, game-scoped call_id.
        self.assertEqual(len(calls_a), 3)
        self.assertEqual(len(calls_b), 3)
        ambiguous_a = next(c for c in calls_a if c["provider_response_id"] == "resp-ambiguous-1")
        ambiguous_b = next(c for c in calls_b if c["provider_response_id"] == "resp-ambiguous-1")
        self.assertEqual(ambiguous_a["game_id"], "game-a")
        self.assertEqual(ambiguous_b["game_id"], "game-b")
        self.assertNotEqual(ambiguous_a["call_id"], ambiguous_b["call_id"])

    def test_incomplete_trailing_record_is_diagnosed_not_dropped_silently(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_incomplete_trailing.json"))
        report = cmu.collect_host_usage_report(manifest)
        self.assertEqual(len(report["calls"]), 1)
        self.assertEqual(report["calls"][0]["provider_response_id"], "resp-full-1")
        diagnosis = [d for d in report["diagnostics"] if d["kind"] == "incomplete_trailing_record"]
        self.assertEqual(len(diagnosis), 1)
        self.assertIn("resp-trailing-2", diagnosis[0]["raw"])

    def test_conflicting_usage_is_flagged_via_normalization_gaps_not_last_writer_wins(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_conflict.json"))
        report = cmu.collect_host_usage_report(manifest)
        calls = report["calls"]
        self.assertEqual(len(calls), 1)
        call = calls[0]
        # The first recorded usage is retained rather than silently replaced
        # by the later, disagreeing one; the disagreement is surfaced as a
        # normalization gap in model_usage's own "conflict:field:old!=new" shape.
        self.assertEqual(call["input_tokens"], 100)
        conflict_gaps = [gap for gap in call["normalization_gaps"] if gap.startswith("conflict:")]
        self.assertTrue(any("input_tokens:100!=999" in gap for gap in conflict_gaps), conflict_gaps)
        self.assertIn((call["game_id"], call["call_id"]), report["conflicts"])

    def test_delayed_final_usage_is_picked_up_after_an_earlier_empty_usage_record(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_delayed_final.json"))
        calls = cmu.collect_host_usage(manifest)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        # The first record for this response carries an empty usage dict (no
        # keys at all yet); every token field stays unknown until the
        # delayed final record supplies the real numbers, with no conflict
        # since nothing measured disagreed.
        self.assertEqual(call["status"], "completed")
        self.assertEqual(call["output_tokens"], 33)
        self.assertEqual(call["reasoning_tokens"], 9)
        self.assertEqual(call["total_tokens"], 82)
        self.assertEqual([g for g in call["normalization_gaps"] if g.startswith("conflict:")], [])

    def test_missing_usage_block_is_reported_unsupported_not_guessed_as_zero(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_unsupported_schema.json"))
        calls = cmu.collect_host_usage(manifest)
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["usage_source"], "unsupported_payload_shape")
        self.assertEqual(call["status"], "unknown")
        for field in model_usage.TOKEN_FIELDS:
            self.assertIsNone(call[field])
        self.assertIsNotNone(call["raw_usage_json"])

    def test_request_links_are_applied_only_when_explicitly_supplied(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        calls = cmu.collect_host_usage(manifest)
        publish_call = next(c for c in calls if c["provider_response_id"] == "resp-publish-3")
        linked = cmu.collect_host_usage(
            manifest, request_links={publish_call["call_id"]: "harness-request-7"})
        linked_publish = next(c for c in linked if c["provider_response_id"] == "resp-publish-3")
        self.assertEqual(linked_publish["request_id"], "harness-request-7")
        self.assertEqual(linked_publish["linkage_evidence"], "supplied_request_link")
        others = [c for c in linked if c["provider_response_id"] != "resp-publish-3"]
        self.assertTrue(all(c["request_id"] is None for c in others))

    def test_rows_use_worker_a_field_names(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        call = cmu.collect_host_usage(manifest)[0]
        for field in ("game_id", "call_id", "request_id", "retry_of_call_id", "provider",
                      "transport", "native_thread_id", "provider_response_id",
                      "requested_model", "reported_model", "requested_reasoning_effort",
                      "reported_reasoning_effort", "output_limit", "status", "finish_reason",
                      "error_code", "started_at", "ended_at", "elapsed_ms", "usage_source",
                      "usage_schema_version", "raw_usage_json", "source_ref", "source_hash",
                      "linkage_evidence", "normalization_gaps"):
            self.assertIn(field, call)
        for field in model_usage.TOKEN_FIELDS:
            self.assertIn(field, call)
        self.assertEqual(call["usage_schema_version"], model_usage.USAGE_SCHEMA_VERSION)

class LinkCallsViaHandshakeTests(unittest.TestCase):
    def test_call_inside_exactly_one_published_answered_window_is_linked(self):
        with tempfile.TemporaryDirectory() as raw:
            handshake_dir = Path(raw)
            (handshake_dir / "handshake_log.ndjson").write_text(
                json.dumps({"harness_request_id": "req-1",
                            "published_at": "2026-01-01T00:00:00Z",
                            "answered_at": "2026-01-01T00:00:01.500Z"}) + "\n",
                encoding="utf-8")
            manifest = cmu.HostUsageManifest(
                game_id="g", host_thread_id="thread-solo",
                host_evidence_path=FIXTURES / "hostusage_rollout_three_calls.jsonl",
                game_log_path=FIXTURES / "hostusage_game_log.ndjson",
                request_handshake_dir=handshake_dir)
            calls = cmu.collect_host_usage(manifest)
            links = cmu.link_calls_via_handshake(manifest, calls)
            inspect_call = next(c for c in calls if c["provider_response_id"] == "resp-inspect-1")
            self.assertEqual(links[inspect_call["call_id"]], "req-1")
            # Only the response whose own timestamp falls in this window is linked.
            other_calls = [c for c in calls if c["provider_response_id"] != "resp-inspect-1"]
            self.assertTrue(all(c["call_id"] not in links for c in other_calls))

    def test_no_handshake_log_leaves_everything_unlinked(self):
        manifest = cmu.load_manifest(manifest_dict("hostusage_manifest_three_calls.json"))
        links = cmu.link_calls_via_handshake(manifest)
        self.assertEqual(links, {})

    def test_ambiguous_or_absent_timestamp_never_guesses_a_link(self):
        with tempfile.TemporaryDirectory() as raw:
            handshake_dir = Path(raw)
            # Two overlapping windows: a call timestamp inside both is
            # provably ambiguous, not resolved by picking either one.
            with (handshake_dir / "handshake_log.ndjson").open("w", encoding="utf-8") as stream:
                stream.write(json.dumps({"harness_request_id": "req-1",
                                          "published_at": "2026-01-01T00:00:00Z",
                                          "answered_at": "2026-01-01T00:00:05Z"}) + "\n")
                stream.write(json.dumps({"harness_request_id": "req-2",
                                          "published_at": "2026-01-01T00:00:00Z",
                                          "answered_at": "2026-01-01T00:00:05Z"}) + "\n")
            manifest = cmu.HostUsageManifest(
                game_id="g", host_thread_id="thread-solo",
                host_evidence_path=FIXTURES / "hostusage_rollout_three_calls.jsonl",
                game_log_path=FIXTURES / "hostusage_game_log.ndjson",
                request_handshake_dir=handshake_dir)
            calls = cmu.collect_host_usage(manifest)
            links = cmu.link_calls_via_handshake(manifest, calls)
            self.assertEqual(links, {})

class RollbackAndScanningGuardTests(unittest.TestCase):
    def test_load_manifest_never_scans_a_directory_for_a_binding(self):
        # There is no glob/search entry point at all: the only way to name
        # evidence is the four explicit manifest fields.
        import inspect
        source = inspect.getsource(cmu)
        self.assertNotIn("glob(", source)
        self.assertNotIn("iterdir(", source)
        self.assertNotIn("os.walk", source)
        self.assertNotIn("home()", source)
        self.assertNotIn("Path.home", source)

if __name__ == "__main__":
    unittest.main()
