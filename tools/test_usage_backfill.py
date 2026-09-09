import json
import tempfile
import unittest
from pathlib import Path

from .game_history import import_game, open_history, query_usage, verify_history
from .usage_backfill import (
    BackfillManifestError, UsageBackfillUnavailable, backfill_one_game, backfill_usage,
    collect_fireworks_calls, compare_usage, load_backfill_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_minimal_game(root: Path, game_id: str) -> Path:
    log = root / "match.ndjson"
    log.write_text("\n".join(json.dumps(r) for r in [
        {"type": "metadata", "seed": 1, "scenario": "backfill-fixture",
         "faction0": "undead", "faction1": "undead", "gold": 0, "first_player": 0},
        {"type": "terminal", "reason": "max_turns"},
    ]) + "\n", encoding="utf-8")
    return log


def _catalog_with_game(root: Path, game_id: str):
    _write_minimal_game(root, game_id)
    conn = open_history(root / "history.sqlite")
    import_game(conn, root, game_id=game_id)
    return conn


def _write_manifest(root: Path, games: dict) -> Path:
    path = root / "manifest.json"
    path.write_text(json.dumps({"games": games}), encoding="utf-8")
    return path


class ManifestLoadingTests(unittest.TestCase):
    def test_missing_manifest_raises(self):
        with self.assertRaises(BackfillManifestError):
            load_backfill_manifest("/nonexistent/manifest.json")

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(BackfillManifestError):
                load_backfill_manifest(path)

    def test_entry_missing_kind_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_manifest(Path(td), {"g1": {"requests_dir": "x"}})
            with self.assertRaises(BackfillManifestError):
                load_backfill_manifest(path)

    def test_valid_manifest_round_trips(self):
        with tempfile.TemporaryDirectory() as td:
            path = _write_manifest(Path(td), {"g1": {"kind": "fireworks_requests", "requests_dir": "x"}})
            manifest = load_backfill_manifest(path)
            self.assertEqual(manifest["games"]["g1"]["kind"], "fireworks_requests")


class FireworksArchiveParsingTests(unittest.TestCase):
    """Real preserved-archive shape verified against actual game evidence:
    request.json/response.json/receipt.json + reply.json|error.json under one
    attempt directory per response. Fixtures here are fabricated content in
    the same shape -- no real prompt/response text."""

    def test_two_fully_measured_completed_calls(self):
        calls, diagnostics = collect_fireworks_calls("g", FIXTURES / "backfill_fireworks_ok" / "requests")
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(c.status == "completed" for c in calls))
        self.assertEqual(sorted(c.input_tokens for c in calls), [100, 200])
        self.assertEqual(sorted(c.output_tokens for c in calls), [40, 55])
        self.assertEqual(sorted(c.reasoning_tokens for c in calls), [10, 15])
        self.assertEqual(sorted(c.total_tokens for c in calls), [140, 255])
        # Stable, source-derived identity: distinct provider response ids.
        self.assertEqual(len({c.call_id for c in calls}), 2)

    def test_failed_reply_retains_exact_usage_deepseek_shaped(self):
        calls, diagnostics = collect_fireworks_calls("g", FIXTURES / "backfill_fireworks_failed" / "requests")
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call.status, "failed")
        self.assertEqual(call.finish_reason, "length")
        self.assertEqual((call.input_tokens, call.output_tokens, call.reasoning_tokens, call.total_tokens),
                         (5881, 16384, 16384, 22265))
        self.assertIsNotNone(call.error_code)

    def test_partial_usage_has_unmeasured_reasoning_field(self):
        calls, diagnostics = collect_fireworks_calls("g", FIXTURES / "backfill_fireworks_partial" / "requests")
        self.assertEqual(diagnostics, [])
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual((call.input_tokens, call.output_tokens, call.total_tokens), (300, 70, 370))
        self.assertIsNone(call.reasoning_tokens)  # never guessed

    def test_malformed_response_json_reported_not_dropped_silently(self):
        calls, diagnostics = collect_fireworks_calls("g", FIXTURES / "backfill_fireworks_malformed" / "requests")
        self.assertEqual(calls, [])
        self.assertTrue(any("response.json" in d for d in diagnostics))

    def test_missing_requests_dir_is_unavailable(self):
        with self.assertRaises(UsageBackfillUnavailable):
            collect_fireworks_calls("g", FIXTURES / "backfill_fireworks_does_not_exist" / "requests")

    def test_conflicting_response_ids_across_two_directories(self):
        from .model_usage import dedupe_calls
        calls, diagnostics = collect_fireworks_calls("g", FIXTURES / "backfill_fireworks_conflict" / "requests")
        self.assertEqual(len(calls), 2)  # two source files
        deduped, conflicts = dedupe_calls(calls)
        self.assertEqual(len(deduped), 1)  # same provider response id -> one call
        self.assertTrue(conflicts, "disagreeing usage for the same response id must be flagged")
        # Retained value is the FIRST one encountered, never last-writer-wins.
        self.assertEqual(deduped[0].input_tokens, 50)


class BackfillOneGameTests(unittest.TestCase):
    def test_unknown_game_id_is_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            result = backfill_one_game(conn, "no-such-game",
                                       {"kind": "fireworks_requests",
                                        "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")})
            self.assertEqual(result["status"], "unavailable")
            conn.close()

    def test_dry_run_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "gk1")
            result = backfill_one_game(conn, "gk1",
                                       {"kind": "fireworks_requests",
                                        "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")},
                                       execute=False)
            self.assertEqual(result["status"], "imported")
            self.assertTrue(result["dry_run"])
            self.assertEqual(result["calls_after"], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM model_calls WHERE game_id='gk1'").fetchone()[0], 0)
            conn.close()

    def test_execute_writes_and_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "gk2")
            entry = {"kind": "fireworks_requests",
                    "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")}
            first = backfill_one_game(conn, "gk2", entry, execute=True)
            self.assertEqual(first["status"], "imported")
            rows_first = conn.execute(
                "SELECT call_id,input_tokens,output_tokens FROM model_calls WHERE game_id='gk2' ORDER BY call_id"
            ).fetchall()
            self.assertEqual(len(rows_first), 2)
            second = backfill_one_game(conn, "gk2", entry, execute=True)
            self.assertEqual(second["status"], "imported")
            rows_second = conn.execute(
                "SELECT call_id,input_tokens,output_tokens FROM model_calls WHERE game_id='gk2' ORDER BY call_id"
            ).fetchall()
            self.assertEqual(rows_first, rows_second)  # stable IDs, no duplicate spending
            verification = verify_history(root / "history.sqlite")
            self.assertEqual(verification["integrity"], "ok")
            self.assertEqual(verification["cross_game_call_links"], 0)
            conn.close()

    def test_additive_merge_preserves_previously_imported_calls(self):
        """A call already in model_calls (e.g. from Stack 1/2 live collection)
        that backfill's source does not name again must survive backfill."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "gk3")
            (root / "usage.ndjson").write_text(json.dumps({
                "game_id": "gk3", "call_id": "pre-existing-call", "provider": "offline",
                "status": "completed", "input_tokens": 7, "output_tokens": 3,
                "record_kind": "final"}) + "\n", encoding="utf-8")
            from .game_history import import_usage_sidecar
            import_usage_sidecar(conn, "gk3", root / "usage.ndjson")
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id='gk3'").fetchone()[0], 1)

            entry = {"kind": "fireworks_requests",
                    "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")}
            result = backfill_one_game(conn, "gk3", entry, execute=True)
            self.assertEqual(result["status"], "imported")
            call_ids = {row[0] for row in conn.execute(
                "SELECT call_id FROM model_calls WHERE game_id='gk3'")}
            self.assertIn("pre-existing-call", call_ids)
            self.assertEqual(len(call_ids), 3)  # 1 pre-existing + 2 newly backfilled
            conn.close()

    def test_malformed_source_fails_without_destroying_existing_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "gk4")
            good_entry = {"kind": "fireworks_requests",
                         "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")}
            backfill_one_game(conn, "gk4", good_entry, execute=True)
            before = conn.execute(
                "SELECT call_id,input_tokens FROM model_calls WHERE game_id='gk4' ORDER BY call_id").fetchall()
            self.assertEqual(len(before), 2)

            bad_entry = {"kind": "fireworks_requests",
                        "requests_dir": str(FIXTURES / "backfill_fireworks_malformed" / "requests")}
            result = backfill_one_game(conn, "gk4", bad_entry, execute=True)
            self.assertEqual(result["status"], "failed")
            after = conn.execute(
                "SELECT call_id,input_tokens FROM model_calls WHERE game_id='gk4' ORDER BY call_id").fetchall()
            self.assertEqual(before, after)  # rollback: prior rows untouched
            conn.close()


class BackfillUsageBatchTests(unittest.TestCase):
    def test_all_is_scoped_to_manifest_mapped_games_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "mapped-game")
            _catalog_with_game(root, "unmapped-game")  # catalogued but NOT in the manifest
            manifest = _write_manifest(root, {"mapped-game": {
                "kind": "fireworks_requests",
                "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")}})
            report = backfill_usage(conn, manifest_path=manifest, all_games=True, execute=False)
            self.assertEqual(report["attempted"], 1)
            self.assertEqual([g["game_id"] for g in report["imported"]], ["mapped-game"])
            conn.close()

    def test_mixed_batch_available_unavailable_malformed_conflicting_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "g-ok")
            _catalog_with_game(root, "g-malformed")
            _catalog_with_game(root, "g-conflict")
            _catalog_with_game(root, "g-partial")
            # g-unavailable is intentionally never imported into the catalog.
            manifest = _write_manifest(root, {
                "g-ok": {"kind": "fireworks_requests",
                        "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")},
                "g-malformed": {"kind": "fireworks_requests",
                               "requests_dir": str(FIXTURES / "backfill_fireworks_malformed" / "requests")},
                "g-conflict": {"kind": "fireworks_requests",
                              "requests_dir": str(FIXTURES / "backfill_fireworks_conflict" / "requests")},
                "g-partial": {"kind": "fireworks_requests",
                             "requests_dir": str(FIXTURES / "backfill_fireworks_partial" / "requests")},
                "g-unavailable": {"kind": "fireworks_requests",
                                  "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")},
            })
            report = backfill_usage(conn, game_ids=["g-ok", "g-malformed", "g-conflict", "g-partial",
                                                     "g-unavailable"],
                                    manifest_path=manifest, execute=True)
            self.assertEqual(report["attempted"], 5)
            statuses = {g["game_id"]: "imported" for g in report["imported"]}
            statuses.update({g["game_id"]: "unavailable" for g in report["unavailable"]})
            statuses.update({g["game_id"]: "failed" for g in report["failed"]})
            self.assertEqual(statuses["g-ok"], "imported")
            self.assertEqual(statuses["g-malformed"], "failed")
            self.assertEqual(statuses["g-conflict"], "imported")
            self.assertEqual(statuses["g-partial"], "imported")
            self.assertEqual(statuses["g-unavailable"], "unavailable")
            # Independent games: the good ones actually landed rows despite failures elsewhere.
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id='g-ok'").fetchone()[0], 2)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id='g-malformed'").fetchone()[0], 0)
            conflict_entry = next(g for g in report["imported"] if g["game_id"] == "g-conflict")
            self.assertTrue(conflict_entry["conflicts"])
            conn.close()

    def test_backfill_usage_requires_selection_without_all(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = open_history(root / "history.sqlite")
            manifest = _write_manifest(root, {})
            with self.assertRaises(ValueError):
                backfill_usage(conn, manifest_path=manifest)
            conn.close()


class BackfillHostSessionTests(unittest.TestCase):
    """Reuses Stack 2's collector fixtures -- three physical host responses
    for one harness request, already exercised in test_game_history.py."""

    def test_host_session_kind_produces_three_detailed_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = _catalog_with_game(root, "host-game")
            entry = {
                "kind": "host_session",
                "host_thread_id": "thread-solo",
                "host_evidence_path": str(REPO_ROOT / "tools/fixtures/hostusage_rollout_three_calls.jsonl"),
                "game_log_path": str(REPO_ROOT / "tools/fixtures/hostusage_game_log.ndjson"),
                "request_handshake_dir": str(REPO_ROOT / "tools/fixtures/hostusage_handshake"),
            }
            result = backfill_one_game(conn, "host-game", entry, execute=True)
            self.assertEqual(result["status"], "imported")
            self.assertEqual(result["calls_after"], 3)
            rows = conn.execute(
                "SELECT provider,native_thread_id FROM model_calls WHERE game_id='host-game'").fetchall()
            self.assertTrue(all(p == "codex_native" for p, _ in rows))
            conn.close()


class CompareUsageTests(unittest.TestCase):
    def _game_with_calls(self, root, game_id):
        conn = _catalog_with_game(root, game_id)
        backfill_one_game(conn, game_id,
                          {"kind": "fireworks_requests",
                           "requests_dir": str(FIXTURES / "backfill_fireworks_ok" / "requests")},
                          execute=True)
        return conn

    def test_requires_explicit_selection(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            with self.assertRaises(ValueError):
                compare_usage(conn, [])
            conn.close()

    def test_unknown_game_id_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            result = compare_usage(conn, ["nope"])
            self.assertEqual(result["games"][0]["status"], "unknown_game_id")
            conn.close()

    def test_no_ranking_or_score_field_present(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = self._game_with_calls(root, "cmp-1")
            result = compare_usage(conn, ["cmp-1"])
            game = result["games"][0]
            self.assertNotIn("ranking", game)
            self.assertNotIn("score", game)
            self.assertIn("cross-model tokenizers differ", result["note"])
            conn.close()

    def test_percentiles_reported_with_included_excluded_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root, "cmp-2")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="cmp-2")
            (root / "usage.ndjson").write_text("\n".join(json.dumps(row) for row in [
                {"game_id": game_id, "call_id": "c1", "request_id": "r1", "status": "completed",
                 "output_tokens": 40, "record_kind": "final"},
                {"game_id": game_id, "call_id": "c2", "request_id": "r2", "status": "completed",
                 "output_tokens": 55, "record_kind": "final"},
                # A third request with unmeasured output must be EXCLUDED, not
                # zeroed, from the percentile -- and counted as excluded.
                {"game_id": game_id, "call_id": "c3", "request_id": "r3", "status": "completed",
                 "input_tokens": 12, "record_kind": "final"},
            ]) + "\n", encoding="utf-8")
            from .game_history import import_usage_sidecar
            import_usage_sidecar(conn, game_id, root / "usage.ndjson")
            result = compare_usage(conn, [game_id])
            game = result["games"][0]
            output_stats = game["per_request"]["output_tokens"]
            self.assertEqual(output_stats["included_count"], 2)
            self.assertEqual(output_stats["excluded_count"], 1)
            self.assertEqual(output_stats["median"], 47.5)  # 40 and 55
            self.assertEqual(output_stats["max"], 55)
            conn.close()

    def test_open_turn_usage_kept_separate_from_completed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "archive"; archive.mkdir()
            log = archive / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata", "faction0": "undead", "faction1": "undead", "seed": 1,
                 "llm_side": 0, "conversation_id": "cmp-open"},
                {"type": "driver", "line": {"type": "state", "turn": 1, "active_faction": 0,
                                            "cols": 2, "rows": 2, "terrain": [], "units": [],
                                            "state_revision": 0}},
                {"type": "side_turn_started", "side_turn_id": "cmp-open:side_turn:1",
                 "side": 0, "round": 1, "start_revision": 0},
                {"type": "model_request", "request_id": "cmp-open:request:1",
                 "side_turn_id": "cmp-open:side_turn:1",
                 "status": "failed", "state_revision": 0, "sequence": 1},
                {"type": "model_error", "code": "action_batch_rejected"},
            ]) + "\n", encoding="utf-8")
            (archive / "usage.ndjson").write_text(json.dumps({
                "game_id": "cmp-open", "call_id": "c1", "provider": "offline", "status": "failed",
                "request_id": "cmp-open:request:1", "input_tokens": 5881, "output_tokens": 16384,
                "reasoning_tokens": 16384, "total_tokens": 22265, "record_kind": "final"}) + "\n",
                encoding="utf-8")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, log, game_id="cmp-open")
            result = compare_usage(conn, [game_id])
            game = result["games"][0]
            self.assertEqual(len(game["open_turns"]), 1)
            self.assertEqual(game["per_completed_side_turn"]["count"], 0)
            self.assertEqual(game["failed_calls"]["count"], 1)
            self.assertEqual(game["failed_calls"]["detail"]["output_tokens"]["sum"], 16384)
            conn.close()


if __name__ == "__main__":
    unittest.main()
