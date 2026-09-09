import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from .game_history import (IMPORTER_VERSION, SCHEMA, backup_history, decode_payload, encode_payload,
                           import_game, delete_history, inventory_history, list_side_turns, open_history,
                           summarize_game, verify_history)

FIXTURE = Path(__file__).parent / "fixtures" / "s1_sample_game"

class GameHistoryTests(unittest.TestCase):
    def test_existing_catalog_migrates_annotation_columns(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.sqlite"
            legacy = sqlite3.connect(path)
            legacy.executescript(SCHEMA.replace(" annotation_status TEXT, state_revision INTEGER,\n", ""))
            legacy.commit(); legacy.close()
            conn = open_history(path)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(model_requests)")}
            self.assertTrue({"annotation_status", "state_revision", "reasoning_blob"} <= columns)
            log = Path(td) / "match.ndjson"
            log.write_text('\n'.join(json.dumps(row) for row in [
                {"type": "metadata"},
                {"type": "model_request", "request_id": "old-request", "prompt_hash": "known-hash"},
                {"type": "terminal", "reason": "max_turns"},
            ]) + '\n')
            import_game(conn, log)
            self.assertEqual(conn.execute(
                "SELECT annotation_status,state_revision,reasoning_blob,prompt_blob,prompt_hash FROM model_requests"
            ).fetchone(), (None, None, None, None, "known-hash"))
            conn.close()

    def test_read_only_uri_preserves_filename_and_cannot_write(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("catalog#copy.sqlite", "catalog?mode=rwc.sqlite",
                         "catalog%23copy.sqlite", "catalog ü space.sqlite"):
                with self.subTest(name=name):
                    path = root / name
                    open_history(path).close()
                    before = {p.name: p.read_bytes() for p in root.iterdir()}
                    with closing(open_history(path, read_only=True)) as conn:
                        self.assertEqual(Path(conn.execute("PRAGMA database_list").fetchone()[2]), path)
                        self.assertEqual(inventory_history(conn)["counts"]["games"], 0)
                        with self.assertRaises(sqlite3.OperationalError):
                            conn.execute("CREATE TABLE should_not_exist (id INTEGER)")
                    self.assertEqual(verify_history(path)["integrity"], "ok")
                    self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)

    def test_read_only_catalog_access_never_creates_missing_database(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "missing.sqlite"
            with self.assertRaises(FileNotFoundError):
                open_history(path, read_only=True)
            with self.assertRaises(FileNotFoundError):
                verify_history(path)
            self.assertFalse(path.exists())

    def test_payload_round_trip(self):
        value = {"units": [{"id": 1, "hp": 20}], "active": 0}
        blob, codec, digest = encode_payload(value)
        self.assertEqual(decode_payload(blob, codec), value)
        self.assertEqual(len(digest), 64)

    def test_import_is_idempotent_and_lists_turns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            rows = [
                {"type": "metadata", "seed": 9, "scenario": "test", "faction0": "a", "faction1": "b", "gold": 10, "first_player": 0, "source_commit": "abc"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0, "units": []}},
                {"type": "turn_boundary", "accepted": True, "authored_finish_kind": "explicit_done", "start_revision": 0, "state_revision": 1},
                {"type": "handoff_review", "version": 1, "state_revision": 0,
                 "outcome": "confirmed", "trigger_reasons": ["affordable_recruitment"],
                 "audit": {"gold": 20}},
                {"type": "driver", "line": {"type": "state", "state_revision": 1, "turn": 1, "active_faction": 1, "units": []}},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, "cohort")
            import_game(conn, root, "cohort", game_id)
            self.assertEqual(summarize_game(conn, game_id)["resolved_turns"], 1)
            self.assertEqual(list_side_turns(conn, game_id)[0]["finish_kind"], "explicit_done")
            metrics = conn.execute("SELECT metrics_json FROM side_turns WHERE game_id=?", (game_id,)).fetchone()[0]
            self.assertIn("affordable_recruitment", metrics)
            self.assertEqual(conn.execute("SELECT count(*) FROM games").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM side_turns").fetchone()[0], 1)
            backup = root / "backup.sqlite"
            conn.close()
            backup_history(str(root / "history.sqlite"), str(backup))
            self.assertEqual(verify_history(backup)["integrity"], "ok")

    def test_partial_snapshots_are_not_paired_by_ordinal_position(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            rows = [
                {"type": "metadata", "seed": 3, "scenario": "test", "faction0": "a", "faction1": "b", "gold": 10, "first_player": 0},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "state", "state_revision": 5, "turn": 1, "active_faction": 0, "turn_boundary": "partial"}},
                {"type": "turn_boundary", "accepted": True, "start_revision": 0, "state_revision": 10,
                 "side_turn_id": "turn-a", "side": 0, "authored_finish_kind": "explicit_done"},
                {"type": "handoff_review", "side_turn_id": "turn-a", "state_revision": 10, "outcome": "confirmed"},
            ]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, "cohort")
            turn = list_side_turns(conn, game_id)[0]
            self.assertEqual(turn["start_revision"], 0)
            self.assertIsNone(turn["end_revision"])
            coverage = json.loads(conn.execute("SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["linked_reviews"], 1)
            self.assertEqual(coverage["unresolved_turn_endpoints"], 1)
            metrics = json.loads(conn.execute("SELECT metrics_json FROM side_turns WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(metrics["handoff_review"]["side_turn_id"], "turn-a")

    def test_annotations_and_explicit_request_links_survive_reimport(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            annotation = {"status": "valid", "guide_version": "tactics-v1",
                          "guide_hash": "g" * 64, "decisions": [
                              {"orders": [0], "rules": ["S1"], "expected": "Hold.", "risk": "Exposure."}],
                          "error": None}
            rows = [
                {"type": "metadata", "seed": 4, "scenario": "test", "faction0": "a", "faction1": "b"},
                {"type": "driver", "line": {"type": "state", "state_revision": 4, "turn": 1, "active_faction": 0}},
                {"type": "model_request", "request_id": "req-1", "state_revision": 4,
                 "prompt": "exact prompt", "raw_output": "exact response", "decision_annotation": annotation},
                {"type": "forwarded_orders", "request_id": "req-1", "state_revision": 4,
                 "batch_id": "batch-1", "orders": [{"action": "DoneWithImportantMoves"}],
                 "decision_annotation": annotation},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            row = conn.execute("""SELECT prompt_blob,response_blob,prompt_hash,response_hash,reasoning_blob,
                                       reasoning_kind,reasoning_source,annotation_status,state_revision,payload_codec
                                  FROM model_requests""").fetchone()
            self.assertEqual(zlib.decompress(row[0]).decode("utf-8"), "exact prompt")
            self.assertEqual(zlib.decompress(row[1]).decode("utf-8"), "exact response")
            self.assertEqual(decode_payload(row[4]), annotation)
            self.assertEqual(row[5:10], ("decision_annotation_v1", "model_response", "valid", 4, "zlib"))
            self.assertEqual(conn.execute("SELECT request_id,before_revision FROM action_batches").fetchone(), ("req-1", 4))
            self.assertEqual(conn.execute("SELECT request_id FROM actions").fetchone()[0], "req-1")
            before = conn.execute("SELECT prompt_blob,response_blob,reasoning_blob FROM model_requests").fetchone()
            import_game(conn, root, game_id=game_id)
            self.assertEqual(conn.execute("SELECT count(*) FROM model_requests").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT prompt_blob,response_blob,reasoning_blob FROM model_requests").fetchone(), before)
            conn.close()

    def test_nonvalid_annotations_do_not_create_rationale(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            rows = [{"type": "metadata"},
                    {"type": "model_request", "request_id": "r", "prompt": "p", "raw_output": "x",
                     "decision_annotation": {"status": "invalid", "error": "bad", "decisions": []}},
                    {"type": "forwarded_orders", "request_id": "r", "orders": [{"action": "Done"}]},
                    {"type": "terminal", "reason": "max_turns"}]
            log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            conn = open_history(root / "history.sqlite"); import_game(conn, root)
            self.assertEqual(conn.execute("SELECT annotation_status,reasoning_blob FROM model_requests").fetchone(), ("invalid", None))
            conn.close()

    def test_delete_exact_cohort_preserves_other_games_and_compacts(self):
        with tempfile.TemporaryDirectory() as td:
            conn = open_history(Path(td) / "history.sqlite")
            with conn:
                for game, cohort in (("bad1", "bad"), ("good1", "good")):
                    conn.execute("""INSERT INTO games(game_id,cohort_id,status,config_json,
                        provenance_json,schema_version,artifact_path) VALUES(?,?,?,?,?,?,?)""",
                                 (game, cohort, "complete", "{}", "{}", 1, "."))
                    conn.execute("""INSERT INTO model_requests(request_id,game_id,sequence,status,
                        record_hash) VALUES(?,?,?,?,?)""", (game + ":r", game, 1, "failed", "h"))
            result = delete_history(conn, cohort_id="bad", compact=True)
            self.assertEqual(result["deleted_game_ids"], ["bad1"])
            self.assertEqual(conn.execute("SELECT count(*) FROM games").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT game_id FROM games").fetchone()[0], "good1")
            self.assertEqual(verify_history(Path(td) / "history.sqlite")["foreign_key_errors"], 0)
            with self.assertRaises(KeyError):
                delete_history(conn, game_ids=["missing"])
            self.assertEqual(inventory_history(conn)["counts"]["games"], 1)

def _write_checkpoint(archive: Path, filename: str, save_state: dict) -> dict:
    """Write a real checkpoint sidecar and return its driver-log reference."""
    ckpt_dir = archive / "match.ckpt"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    envelope = {"version": 1, "save_state": save_state, "side_turns": save_state.get("_side_turns", 0),
               "boundary": save_state.get("_boundary", "turn_end")}
    payload = json.dumps(envelope).encode()
    digest = hashlib.sha256(payload).hexdigest()
    (ckpt_dir / filename).write_bytes(payload)
    return {"path": filename, "digest": digest, "state_revision": save_state.get("state_revision"),
            "side_turns": save_state.get("_side_turns"), "boundary": save_state.get("_boundary", "turn_end")}


class S1SnapshotTimelineTests(unittest.TestCase):
    """Covers the S1 data contract: an authoritative per-game snapshot
    timeline, evidence-only endpoint linking, and honest coverage gaps."""

    def test_tracked_fixture_produces_the_expected_ordered_distinct_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, FIXTURE, "s1-fixture")
            rows = conn.execute(
                "SELECT sequence,revision,boundary_kind,renderable FROM snapshots WHERE game_id=? ORDER BY sequence",
                (game_id,)).fetchall()
            self.assertEqual([r[1] for r in rows], [0, 1, 2, 3, 4, 5])
            self.assertEqual(rows[0][2], "opening")
            self.assertEqual(rows[1][2], "partial")
            self.assertEqual(rows[-1][2], "terminal")  # winning partial, no turn_boundary record
            self.assertTrue(all(r[3] for r in rows))
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(coverage["opening_present"])
            self.assertTrue(coverage["terminal_present"])
            self.assertEqual(coverage["unresolved_turn_endpoints"], 0)
            self.assertEqual(coverage["linked_reviews"], 1)
            turns = list_side_turns(conn, game_id)
            self.assertEqual([t["start_revision"] for t in turns], [0, 2])
            self.assertEqual([t["end_revision"] for t in turns], [2, 4])
            conn.close()

    def test_reimport_is_idempotent_and_preserves_review_link_and_snapshot_ids(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, FIXTURE)
            before_snapshots = conn.execute(
                "SELECT snapshot_id,revision,state_hash FROM snapshots WHERE game_id=? ORDER BY sequence",
                (game_id,)).fetchall()
            before_turns = conn.execute(
                "SELECT side_turn_id,start_snapshot_id,end_snapshot_id FROM side_turns WHERE game_id=? ORDER BY sequence",
                (game_id,)).fetchall()
            import_game(conn, FIXTURE, game_id=game_id)
            after_snapshots = conn.execute(
                "SELECT snapshot_id,revision,state_hash FROM snapshots WHERE game_id=? ORDER BY sequence",
                (game_id,)).fetchall()
            after_turns = conn.execute(
                "SELECT side_turn_id,start_snapshot_id,end_snapshot_id FROM side_turns WHERE game_id=? ORDER BY sequence",
                (game_id,)).fetchall()
            self.assertEqual(before_snapshots, after_snapshots)
            self.assertEqual(before_turns, after_turns)
            conn.close()

    def test_duplicate_representation_is_coalesced_not_doubled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            state = {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": state},
                {"type": "driver", "line": dict(state)},  # exact duplicate observation
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM snapshots WHERE game_id=?", (game_id,)).fetchone()[0], 1)
            conn.close()

    def test_repeated_looking_later_state_is_kept_distinct(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                # A resume branch reuses revision 0 with genuinely different content.
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 5, "active_faction": 1}},
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            rows = conn.execute("SELECT count(*) FROM snapshots WHERE game_id=?", (game_id,)).fetchone()[0]
            self.assertEqual(rows, 2)
            conn.close()

    def test_missing_checkpoint_is_a_reported_gap_not_a_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "checkpoint", "path": "missing.json",
                 "digest": "0" * 64, "state_revision": 9, "side_turns": 2, "boundary": "turn_end"}},
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any(g.startswith("checkpoint_unavailable:missing.json") for g in coverage["gaps"]))
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM snapshots WHERE game_id=?", (game_id,)).fetchone()[0], 1)
            conn.close()

    def test_corrupt_checkpoint_digest_is_a_reported_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            save_state = {"state_revision": 9, "turn": 5, "active_faction": 0, "_side_turns": 2}
            ref = _write_checkpoint(root, "ck1.json", save_state)
            ref["digest"] = "f" * 64  # corrupt: does not match the file's real digest
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "checkpoint", **ref}},
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any("checkpoint_unavailable" in g for g in coverage["gaps"]))
            conn.close()

    def test_resume_conflict_between_checkpoint_and_log_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            save_state = {"state_revision": 3, "turn": 2, "active_faction": 1, "_side_turns": 9}
            ref = _write_checkpoint(root, "ck2.json", save_state)
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 3, "turn": 2,
                 "active_faction": 1, "side_turns": 2}},
                {"type": "driver", "line": {"type": "checkpoint", **ref}},  # claims 9 completed side turns
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any(c.startswith("conflict:revision:3") for c in coverage["conflicts"]))
            # The conflicting checkpoint count never silently overwrites the log's.
            self.assertEqual(conn.execute(
                "SELECT completed_side_turns FROM snapshots WHERE game_id=? AND revision=3",
                (game_id,)).fetchone()[0], 2)
            conn.close()

    def test_complete_game_with_missing_ending_stays_an_incomplete_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "state", "state_revision": 1, "turn": 3, "active_faction": 1}},
                # No terminal record: the archive itself never proves an ending.
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(coverage["opening_present"])
            self.assertFalse(coverage["terminal_present"])
            self.assertEqual(conn.execute(
                "SELECT status FROM games WHERE game_id=?", (game_id,)).fetchone()[0], "incomplete")
            conn.close()

    def test_resignation_terminal_state_may_equal_the_preceding_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "turn_boundary", "accepted": True, "side_turn_id": "t1", "side": 0,
                 "start_revision": 0, "state_revision": 1, "authored_finish_kind": "resign"},
                {"type": "driver", "line": {"type": "state", "state_revision": 1, "turn": 1, "active_faction": 1}},
                {"type": "terminal", "reason": "resignation", "winner": 1, "resigned_side": 0},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            terminal_snapshot = conn.execute(
                "SELECT snapshot_id FROM snapshots WHERE game_id=? AND boundary_kind='terminal'",
                (game_id,)).fetchone()[0]
            end_snapshot = conn.execute(
                "SELECT end_snapshot_id FROM side_turns WHERE game_id=?", (game_id,)).fetchone()[0]
            self.assertEqual(terminal_snapshot, end_snapshot)
            conn.close()

    def test_importer_version_is_recorded_for_the_stale_export_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, FIXTURE)
            self.assertEqual(conn.execute(
                "SELECT importer_version FROM games WHERE game_id=?", (game_id,)).fetchone()[0],
                IMPORTER_VERSION)
            conn.close()


if __name__ == "__main__":
    unittest.main()
