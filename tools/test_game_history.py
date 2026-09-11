import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import zlib
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .game_history import (IMPORTER_VERSION, SCHEMA, backup_history, decode_payload, encode_payload,
                           import_game, delete_history, import_usage_sidecar, inventory_history,
                           list_side_turns, main as game_history_main, open_history, query_usage,
                           summarize_game, usage_sidecar_path, verify_history)
from .model_usage import ModelCall

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
            conn.close()

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
            conn.close()

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


def _write_fake_dump_checkpoint(directory: Path, script: str) -> Path:
    """Write an executable standing in for the real `dump_checkpoint` binary."""
    path = directory / "fake_dump_checkpoint.py"
    path.write_text(f"#!{sys.executable}\n{script}\n")
    path.chmod(0o755)
    return path


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

    def test_valid_checkpoint_without_dump_tool_stays_a_reported_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            save_state = {"state_revision": 9, "turn": 5, "active_faction": 0, "_side_turns": 2}
            ref = _write_checkpoint(root, "ck1.json", save_state)
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "checkpoint", **ref}},
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            from . import game_history
            with mock.patch.object(game_history, "_dump_checkpoint_bin", return_value=None):
                conn = open_history(root / "history.sqlite")
                game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any(g.startswith("checkpoint_not_renderable:ck1.json:dump_checkpoint_unavailable")
                                for g in coverage["gaps"]))
            row = conn.execute(
                "SELECT renderable,state_blob FROM snapshots WHERE game_id=? AND revision=9",
                (game_id,)).fetchone()
            self.assertEqual(row, (0, None))
            conn.close()

    def test_checkpoint_rendered_by_the_dump_tool_becomes_a_playable_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            save_state = {"state_revision": 9, "turn": 5, "active_faction": 1, "_side_turns": 2}
            ref = _write_checkpoint(root, "ck1.json", save_state)
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "checkpoint", **ref}},
                {"type": "terminal", "reason": "max_turns", "state_revision": 9},
            ]) + "\n")
            fake_state = {"state_revision": 9, "turn": 5, "active_faction": 1, "units": [], "gold": [10, 12]}
            fake = _write_fake_dump_checkpoint(root, f"""
import json, sys
print(json.dumps({fake_state!r}))
""")
            with mock.patch.dict(os.environ, {"NORRUST_DUMP_CHECKPOINT_BIN": str(fake)}):
                conn = open_history(root / "history.sqlite")
                game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertFalse(any(g.startswith("checkpoint_not_renderable") for g in coverage["gaps"]))
            self.assertTrue(coverage["terminal_present"])
            row = conn.execute(
                "SELECT renderable,round_number,active_side,state_blob,state_codec FROM snapshots "
                "WHERE game_id=? AND revision=9", (game_id,)).fetchone()
            self.assertEqual((row[0], row[1], row[2]), (1, 5, 1))
            self.assertEqual(decode_payload(row[3], row[4]), fake_state)
            conn.close()

    def test_dump_tool_failure_on_a_valid_checkpoint_is_a_reported_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            save_state = {"state_revision": 9, "turn": 5, "active_faction": 0, "_side_turns": 2}
            ref = _write_checkpoint(root, "ck1.json", save_state)
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "checkpoint", **ref}},
                {"type": "terminal", "reason": "max_turns"},
            ]) + "\n")
            fake = _write_fake_dump_checkpoint(root, """
import sys
sys.stderr.write("restore checkpoint state: unit definition not found: Ghost Knight")
sys.exit(1)
""")
            with mock.patch.dict(os.environ, {"NORRUST_DUMP_CHECKPOINT_BIN": str(fake)}):
                conn = open_history(root / "history.sqlite")
                game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            gap = next(g for g in coverage["gaps"] if g.startswith("checkpoint_not_renderable:ck1.json"))
            self.assertIn("unit definition not found", gap)
            row = conn.execute(
                "SELECT renderable FROM snapshots WHERE game_id=? AND revision=9",
                (game_id,)).fetchone()
            self.assertEqual(row, (0,))
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

    def test_winning_partial_batch_terminal_state_becomes_a_provable_snapshot(self):
        # A partial batch that wins never gets a normal `type:"state"` line
        # from the driver (the live protocol would misread it as "keep
        # playing"); the client instead records the embedded terminal state
        # as its own synthetic "state" driver record ahead of "terminal".
        # This must resolve to a fully covered, terminal_present game with no
        # unresolved boundary, exactly like a normal EndTurn finish.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "state", "state_revision": 4, "turn": 1,
                 "active_faction": 0, "turn_boundary": "partial", "winner": 0}},
                {"type": "terminal", "reason": "winner", "winner": 0, "state_revision": 4},
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(coverage["opening_present"])
            self.assertTrue(coverage["terminal_present"])
            self.assertEqual(coverage["gaps"], [])
            row = conn.execute(
                "SELECT boundary_kind,renderable FROM snapshots WHERE game_id=? AND revision=4",
                (game_id,)).fetchone()
            self.assertEqual(row, ("terminal", 1))
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


def _write_minimal_game(root: Path, *, request_records=(), terminal=None) -> Path:
    log = root / "match.ndjson"
    records = [{"type": "metadata"}, *request_records,
               terminal or {"type": "terminal", "reason": "max_turns"}]
    log.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return log


def _sidecar_row(**overrides) -> dict:
    row = ModelCall(game_id="g", call_id="c").to_row()
    row.pop("normalization_gaps")
    row["normalization_gaps"] = []
    row.update(overrides)
    return row


class ModelCallUsageTests(unittest.TestCase):
    """Stack 1 acceptance: usage-sidecar import into `model_calls` and the
    `usage` query/CLI, covering the plan's frozen accounting contract."""

    def test_failed_inference_retains_exact_counts_no_actions_no_winner(self):
        """input=5881, output=16384, reasoning=16384, total=22265, empty
        content, finish_reason=length: client stops normally for an
        inference failure, but SQLite/CLI retain the exact counts."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root, terminal={"type": "terminal", "reason": "model_backend_failure"})
            (root / "usage.ndjson").write_text("\n".join(json.dumps(row) for row in [
                _sidecar_row(game_id="g1", call_id="c1", status="dispatched",
                            provider="fireworks", record_kind="dispatch"),
                _sidecar_row(game_id="g1", call_id="c1", status="failed", finish_reason="length",
                            provider="fireworks", input_tokens=5881, output_tokens=16384,
                            reasoning_tokens=16384, total_tokens=22265, record_kind="final"),
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g1")
            row = conn.execute("""SELECT status,finish_reason,input_tokens,output_tokens,
                reasoning_tokens,total_tokens FROM model_calls WHERE game_id=? AND call_id='c1'""",
                (game_id,)).fetchone()
            self.assertEqual(row, ("failed", "length", 5881, 16384, 16384, 22265))
            report = query_usage(conn, game_id, "game")
            self.assertEqual(report["measured"]["input_tokens"]["sum"], 5881)
            self.assertEqual(report["measured"]["output_tokens"]["sum"], 16384)
            self.assertEqual(report["measured"]["total_tokens"]["sum"], 22265)
            self.assertEqual(conn.execute("SELECT count(*) FROM actions WHERE game_id=?",
                                          (game_id,)).fetchone()[0], 0)
            self.assertIsNone(conn.execute("SELECT winner_side FROM games WHERE game_id=?",
                                           (game_id,)).fetchone()[0])
            conn.close()

    def test_successful_reply_retains_cache_and_unfamiliar_field_no_double_counting(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            raw_usage = {"input_tokens": 100, "cached_input_tokens": 30, "output_tokens": 50,
                        "provider_extension": {"speculative_tokens": 7}}
            (root / "usage.ndjson").write_text(json.dumps(_sidecar_row(
                game_id="g2", call_id="c1", status="completed", provider="codex",
                input_tokens=100, cached_input_tokens=30, output_tokens=50,
                raw_usage_json=raw_usage)) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g2")
            for _ in range(2):  # reimport must not double count
                import_game(conn, root, game_id="g2")
            self.assertEqual(conn.execute("SELECT count(*) FROM model_calls WHERE game_id=?",
                                          (game_id,)).fetchone()[0], 1)
            report = query_usage(conn, game_id, "call")
            call = report["calls"][0]
            self.assertEqual(call["cached_input_tokens"], 30)
            self.assertEqual(call["raw_usage_json"]["provider_extension"], {"speculative_tokens": 7})
            conn.close()

    def test_explicit_retry_creates_second_call_duplicates_do_not(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            (root / "usage.ndjson").write_text("\n".join(json.dumps(row) for row in [
                _sidecar_row(game_id="g3", call_id="c1", status="dispatched"),
                _sidecar_row(game_id="g3", call_id="c1", status="dispatched"),  # duplicate notification
                _sidecar_row(game_id="g3", call_id="c1", status="failed", error_code="timeout"),
                _sidecar_row(game_id="g3", call_id="c2", retry_of_call_id="c1", status="completed",
                            input_tokens=10, output_tokens=5),
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g3")
            rows = conn.execute("SELECT call_id,status FROM model_calls WHERE game_id=? ORDER BY call_id",
                                (game_id,)).fetchall()
            self.assertEqual(rows, [("c1", "failed"), ("c2", "completed")])
            import_game(conn, root, game_id="g3")  # reimport: still exactly two calls
            self.assertEqual(conn.execute("SELECT count(*) FROM model_calls WHERE game_id=?",
                                          (game_id,)).fetchone()[0], 2)
            conn.close()

    def test_refused_before_dispatch_is_zero_calls_lost_dispatch_is_one_unknown_call(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            # A locally blocked request never reaches a provider: no sidecar
            # line is written for it at all, so it owns zero calls.
            (root / "usage.ndjson").write_text(json.dumps(_sidecar_row(
                game_id="g4", call_id="lost-1", status="dispatched")) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g4")
            rows = conn.execute("SELECT call_id,status,input_tokens FROM model_calls WHERE game_id=?",
                                (game_id,)).fetchall()
            self.assertEqual(rows, [("lost-1", "dispatched", None)])
            conn.close()

    def test_conflict_fixture_exposes_disagreement_without_last_writer_wins(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            (root / "usage.ndjson").write_text("\n".join(json.dumps(row) for row in [
                _sidecar_row(game_id="g5", call_id="c1", status="completed", input_tokens=10),
                _sidecar_row(game_id="g5", call_id="c1", status="completed", input_tokens=99),
            ]) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g5")
            input_tokens, gaps_json = conn.execute(
                "SELECT input_tokens,normalization_gaps_json FROM model_calls WHERE game_id=?",
                (game_id,)).fetchone()
            self.assertEqual(input_tokens, 10)  # retained, not overwritten by the later value
            self.assertTrue(any("conflict" in g for g in json.loads(gaps_json)))
            conn.close()

    def test_pre_feature_catalog_retains_request_aggregate_without_inventing_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root, request_records=[
                {"type": "model_request", "request_id": "req-1",
                 "usage": {"input_tokens": 500, "output_tokens": 120}},
            ])
            # No usage.ndjson sidecar at all -- a pre-feature archive.
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g6")
            self.assertEqual(conn.execute("SELECT count(*) FROM model_calls WHERE game_id=?",
                                          (game_id,)).fetchone()[0], 0)
            report = query_usage(conn, game_id, "request")
            entry = next(e for e in report["requests"] if e["request_id"] == "req-1")
            self.assertEqual(entry["detail"], None)
            self.assertEqual(entry["request_aggregate"]["kind"], "request_aggregate")
            self.assertEqual(entry["request_aggregate"]["tokens"]["input_tokens"], 500)
            # The preserved request row itself is untouched.
            self.assertEqual(conn.execute(
                "SELECT input_tokens FROM model_requests WHERE request_id='req-1'").fetchone()[0], 500)
            conn.close()

    def test_usage_sidecar_path_convention_is_sibling_to_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(usage_sidecar_path(root), root.resolve() / "usage.ndjson")
            log = root / "match.ndjson"
            log.write_text("{}\n")
            self.assertEqual(usage_sidecar_path(log), root.resolve() / "usage.ndjson")

    def test_malformed_sidecar_line_reported_not_dropped_silently(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            (root / "usage.ndjson").write_text(
                "not json\n" + json.dumps(_sidecar_row(game_id="g7", call_id="c1")) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g7")
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["usage_status"], "incomplete")
            self.assertTrue(any(g.startswith("usage_malformed:") for g in coverage["gaps"]))
            self.assertEqual(conn.execute("SELECT count(*) FROM model_calls WHERE game_id=?",
                                          (game_id,)).fetchone()[0], 1)
            conn.close()

    def test_verify_inventory_delete_cover_model_calls(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            (root / "usage.ndjson").write_text(json.dumps(_sidecar_row(
                game_id="g8", call_id="c1", status="completed", input_tokens=1)) + "\n")
            db = root / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, root, game_id="g8")
            conn.close()
            self.assertEqual(verify_history(db)["counts"]["model_calls"], 1)
            self.assertEqual(verify_history(db)["dangling_call_request_links"], 0)
            conn = open_history(db)
            self.assertEqual(inventory_history(conn)["counts"]["model_calls"], 1)
            delete_history(conn, game_ids=[game_id])
            self.assertEqual(conn.execute("SELECT count(*) FROM model_calls").fetchone()[0], 0)
            conn.close()

    def test_import_usage_sidecar_standalone_entry_point(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_minimal_game(root)
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="g9")
            sidecar = root / "external_usage.ndjson"
            sidecar.write_text(json.dumps(_sidecar_row(
                game_id="g9", call_id="c1", status="completed", output_tokens=42)) + "\n")
            result = import_usage_sidecar(conn, "g9", sidecar)
            self.assertEqual(result["imported"], 1)
            self.assertEqual(conn.execute(
                "SELECT output_tokens FROM model_calls WHERE game_id=?", (game_id,)).fetchone()[0], 42)
            conn.close()


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", Path(__file__).resolve().parents[1]
                             / "norrust_core/target/debug/greedy_driver"))
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "norrust_core/tests/fixtures/s2_deterministic_duel"
OFFLINE_RESPONDER = Path(__file__).resolve().parent / "fixtures" / "usage_offline_responder.py"


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
@unittest.skipUnless(FIXTURE_ROOT.is_dir(), "s2_deterministic_duel fixture is missing")
class RealDriverUsageIntegrationTests(unittest.TestCase):
    """A real-driver game played by a synthetic offline `--model-command`
    responder, with usage collected through the maintained sidecar
    convention -- no network, no credentials. Reuses the fixture/pattern
    from tools/test_s2_deterministic_endings.py."""

    def test_short_offline_game_imports_reimports_and_queries_usage(self):
        import subprocess
        import sys

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "match.ndjson"
            sidecar = root / "usage.ndjson"
            command = (f"{sys.executable} {OFFLINE_RESPONDER}")
            args = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                   "--model-command", command, "--scenario", "duel",
                   "--faction0", "fragile", "--faction1", "fragile", "--gold", "0",
                   "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                   "--log", str(log), "--query-budget-seconds", "10", "--model-timeout", "10",
                   "--turn-timeout", "30"]
            env = dict(os.environ, NORRUST_TEST_ROOT_DIR=str(FIXTURE_ROOT),
                      NORRUST_USAGE_SIDECAR=str(sidecar), NORRUST_FIXTURE_GAME_ID="offline-usage-1")
            root_dir = Path(__file__).resolve().parents[1]
            result = subprocess.run(args, cwd=root_dir, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:])
            self.assertTrue(sidecar.is_file(), "offline responder must have written a usage sidecar")

            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="offline-usage-1")
            calls_first = conn.execute(
                "SELECT call_id,status,input_tokens,output_tokens FROM model_calls WHERE game_id=? ORDER BY call_id",
                (game_id,)).fetchall()
            self.assertTrue(calls_first, "expected at least one imported model call")
            for call_id, status, *_ in calls_first:
                self.assertEqual(status, "completed")

            # Reimport with identical results (idempotent).
            import_game(conn, root, game_id="offline-usage-1")
            calls_second = conn.execute(
                "SELECT call_id,status,input_tokens,output_tokens FROM model_calls WHERE game_id=? ORDER BY call_id",
                (game_id,)).fetchall()
            self.assertEqual(calls_first, calls_second)

            report = query_usage(conn, game_id, "game")
            self.assertEqual(report["call_count"], len(calls_first))
            verification = verify_history(root / "history.sqlite")
            self.assertEqual(verification["integrity"], "ok")
            self.assertEqual(verification["foreign_key_errors"], 0)
            self.assertEqual(verification["dangling_call_request_links"], 0)
            self.assertEqual(verification["cross_game_call_links"], 0)
            conn.close()

    def test_partial_completed_then_open_turn_provider_failure_is_fully_attributed(self):
        """Real driver: two partials and a finished turn precede an open failure."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "partial_then_fail.py"
            backend.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "context = json.loads(Path(os.environ['NORRUST_REQUEST_CONTEXT_FILE']).read_text())\n"
                "root = Path(context['game_log']).parent\n"
                "counter = root / 'request_count'\n"
                "step = int(counter.read_text()) + 1 if counter.is_file() else 1\n"
                "counter.write_text(str(step))\n"
                "sidecar = root / 'usage.ndjson'\n"
                "call_id = context['conversation_id'] + ':physical:' + str(step)\n"
                "base = {'game_id': context['conversation_id'], 'call_id': call_id,\n"
                "        'request_id': context['harness_request_id'], 'provider': 'offline',\n"
                "        'transport': 'real_driver_fixture', 'status': 'dispatched',\n"
                "        'record_kind': 'dispatch'}\n"
                "with sidecar.open('a', encoding='utf-8') as out:\n"
                "    out.write(json.dumps(base) + '\\n')\n"
                "    if step <= 3:\n"
                "        final = dict(base, status='completed', record_kind='final',\n"
                "                     input_tokens=100 + step, output_tokens=10,\n"
                "                     reasoning_tokens=5, total_tokens=115 + step)\n"
                "        out.write(json.dumps(final) + '\\n')\n"
                "prompt = sys.stdin.read()\n"
                "if step >= 4:\n"
                "    print('request_unknown: simulated provider EOF', file=sys.stderr)\n"
                "    raise SystemExit(9)\n"
                "if step == 1:\n"
                "    actions = [{'action': 'Recruit', 'def_id': 'Skeleton Archer', 'col': 2, 'row': 6}]\n"
                "elif step == 2:\n"
                "    board = prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nBOARD_UNTRUSTED_DATA_END', 1)[0]\n"
                "    briefing = json.loads(board).get('briefing', '')\n"
                "    recruited = next(line for line in briefing.splitlines()\n"
                "                     if line.strip().startswith('id=') and 'pos=(2,6)' in line\n"
                "                     and 'faction=0' in line)\n"
                "    unit_id = int(recruited.split()[0].split('=')[1])\n"
                "    actions = [{'action': 'Move', 'unit_id': unit_id, 'col': 2, 'row': 5}]\n"
                "else:\n"
                "    actions = [{'action': 'EndTurn'}]\n"
                "reply = {'actions': actions, 'intent': 'fixture progress',\n"
                "         'decisions': [{'orders': [0], 'rules': ['T0'],\n"
                "                         'expected': 'fixture progress', 'risk': 'none'}]}\n"
                "print(json.dumps({'text': json.dumps(reply)}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            command = shlex.join([sys.executable, str(backend)])
            args = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                    "--model-command", command, "--scenario", "big_battle_6",
                    "--faction0", "undead", "--faction1", "undead", "--gold", "14",
                    "--seed", "42", "--llm-side", "0", "--max-turns", "3",
                    "--incremental-turns", "--decision-mode", "focused", "--log", str(log),
                    "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertNotEqual(result.returncode, 0, result.stderr)
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertGreaterEqual(sum(
                1 for r in records if r.get("type") == "driver"
                and r.get("line", {}).get("turn_boundary") == "partial"), 2)
            self.assertEqual(len([r for r in records if r.get("type") == "turn_boundary"]), 1)
            self.assertEqual(len(requests), 4)
            self.assertTrue(all(isinstance(r.get("side_turn_id"), str) for r in requests))
            terminal = next(r for r in reversed(records)
                            if r.get("type") in {"terminal", "model_error"})
            self.assertEqual(terminal["terminal_class"], "infrastructure")
            self.assertEqual(terminal["code"], "model_backend_failure")
            self.assertIsInstance(terminal.get("state_revision"), int)
            self.assertIsInstance(terminal.get("ended_at"), str)
            self.assertGreater(terminal.get("wall_ms", 0), 0)

            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, log, game_id=terminal["conversation_id"])
            request_rows = conn.execute(
                "SELECT count(*),count(side_turn_id) FROM model_requests WHERE game_id=?",
                (game_id,)).fetchone()
            call_rows = conn.execute(
                "SELECT count(*),sum(input_tokens),sum(output_tokens),sum(reasoning_tokens),sum(total_tokens) "
                "FROM model_calls WHERE game_id=?", (game_id,)).fetchone()
            self.assertEqual(request_rows, (4, 4))
            self.assertEqual(call_rows, (4, 306, 30, 15, 351))
            self.assertEqual(conn.execute(
                "SELECT status FROM side_turns WHERE game_id=? ORDER BY sequence", (game_id,)
            ).fetchall(), [("ended",), ("open",)])
            game = conn.execute(
                "SELECT status,failure_code,ended_at,wall_ms,coverage_json FROM games WHERE game_id=?",
                (game_id,)).fetchone()
            self.assertEqual(game[:4], ("complete", "model_backend_failure", terminal["ended_at"], terminal["wall_ms"]))
            coverage = json.loads(game[4])
            self.assertEqual(coverage["terminal_class"], "infrastructure")
            self.assertEqual(coverage["terminal_state_revision"], terminal["state_revision"])
            self.assertEqual(coverage["linked_requests"], 4)
            self.assertEqual(coverage["unassigned_requests"], 0)
            self.assertEqual(coverage["usage_status"], "partial")
            self.assertEqual(coverage["usage_measured"], "partial")
            counts = {table: conn.execute(
                f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)).fetchone()[0]
                      for table in ("snapshots", "events", "model_requests", "model_calls", "side_turns")}
            usage = conn.execute(
                "SELECT call_id,status,input_tokens FROM model_calls WHERE game_id=? ORDER BY call_id",
                (game_id,)).fetchall()
            import_game(conn, log, game_id=game_id)
            import_game(conn, log, game_id=game_id)
            self.assertEqual({table: conn.execute(
                f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)).fetchone()[0]
                              for table in counts}, counts)
            self.assertEqual(conn.execute(
                "SELECT call_id,status,input_tokens FROM model_calls WHERE game_id=? ORDER BY call_id",
                (game_id,)).fetchall(), usage)
            verification = verify_history(root / "history.sqlite")
            self.assertEqual(verification["integrity"], "ok")
            self.assertEqual(verification["dangling_call_request_links"], 0)
            self.assertEqual(verification["dangling_event_side_turn_links"], 0)
            self.assertEqual(verification["foreign_key_errors"], 0)
            conn.close()



class UsageSidecarBindingTests(unittest.TestCase):
    """An adapter cannot know the catalog game_id: it is derived at import.

    It does know the match's conversation_id, which the client publishes in the
    request context. Binding on that keeps the cross-game protection while making
    a sidecar written during play actually importable.
    """

    def _archive(self, root, conversation_id, sidecar_game_ids):
        archive = root / "archive"; archive.mkdir()
        log = archive / "match.ndjson"
        state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                  "terrain": [], "units": [], "state_revision": 0}
        state1 = dict(state0, active_faction=1, state_revision=1)
        rows = [
            {"type": "metadata", "faction0": "undead", "faction1": "undead", "seed": 7,
             "llm_side": 0, "conversation_id": conversation_id},
            {"type": "driver", "line": state0},
            {"type": "turn_boundary", "accepted": True, "start_revision": 0,
             "state_revision": 1, "authored_finish_kind": "explicit_done"},
            {"type": "driver", "line": state1},
            {"type": "terminal", "reason": "winner", "winner": 0},
        ]
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        lines = []
        for index, gid in enumerate(sidecar_game_ids):
            lines.append(json.dumps({
                "game_id": gid, "call_id": f"c{index}", "provider": "offline",
                "transport": "model-command", "status": "completed",
                "input_tokens": 10, "output_tokens": 2, "record_kind": "final"}))
        (archive / "usage.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log

    def _import(self, root, conversation_id, sidecar_game_ids):
        log = self._archive(root, conversation_id, sidecar_game_ids)
        conn = open_history(root / "history.sqlite")
        game_id = import_game(conn, log)
        calls = conn.execute("SELECT call_id FROM model_calls WHERE game_id=?", (game_id,)).fetchall()
        coverage = json.loads(conn.execute(
            "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
        conn.close()
        return game_id, [c[0] for c in calls], coverage

    def test_a_sidecar_written_under_the_conversation_id_is_imported(self):
        with tempfile.TemporaryDirectory() as td:
            _, calls, coverage = self._import(Path(td), "conv-abc", ["conv-abc"])
            self.assertEqual(calls, ["c0"])
            self.assertEqual(coverage.get("usage_status"), "complete")

    def test_a_sidecar_from_a_different_match_is_still_refused(self):
        with tempfile.TemporaryDirectory() as td:
            _, calls, coverage = self._import(Path(td), "conv-abc", ["conv-somebody-else"])
            self.assertEqual(calls, [], "another match's usage must never be attributed here")
            self.assertTrue(any("wrong_game" in g for g in coverage.get("gaps", [])), coverage)



class HostUsageIntegrationTests(unittest.TestCase):
    """Stack 2 headline: several host inference calls for ONE harness request.

    Collection writes the same sidecar shape a live adapter writes, so
    host-collected usage travels through the ordinary importer rather than a
    second import path that could drift from it.
    """

    def test_three_host_calls_for_one_request_aggregate_from_the_calls(self):
        from .collect_model_usage import load_manifest, write_usage_sidecar
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "archive"; archive.mkdir()
            # Own handshake directory: the shared fixture dir is deliberately
            # empty, because another test asserts that absent handshake evidence
            # leaves every call unlinked.
            handshake = Path(td) / "handshake"; handshake.mkdir()
            (handshake / "handshake_log.ndjson").write_text(json.dumps({
                "harness_request_id": "game-three-calls:request:1",
                "request_id": "000001-aa", "conversation_id": "game-three-calls",
                "side": 0, "side_turn_id": "game-three-calls:turn:1", "state_revision": 0,
                "published_at": "2026-01-01T00:00:00Z",
                "answered_at": "2026-01-01T00:00:04Z"}) + "\n", encoding="utf-8")
            manifest = load_manifest({
                "game_id": "game-three-calls", "host_thread_id": "thread-solo",
                "host_evidence_path": str(root / "tools/fixtures/hostusage_rollout_three_calls.jsonl"),
                "game_log_path": str(root / "tools/fixtures/hostusage_game_log.ndjson"),
                "request_handshake_dir": str(handshake)})
            state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                      "terrain": [], "units": [], "state_revision": 0}
            state1 = dict(state0, active_faction=1, state_revision=1)
            rows = [
                {"type": "metadata", "faction0": "undead", "faction1": "undead", "seed": 7,
                 "llm_side": 0, "conversation_id": "game-three-calls"},
                {"type": "driver", "line": state0},
                {"type": "model_request", "request_id": "game-three-calls:request:1",
                 "status": "completed", "state_revision": 0, "sequence": 1},
                {"type": "turn_boundary", "accepted": True, "start_revision": 0,
                 "state_revision": 1, "authored_finish_kind": "explicit_done"},
                {"type": "driver", "line": state1},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ]
            log = archive / "match.ndjson"
            log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
            summary = write_usage_sidecar(manifest, archive / "usage.ndjson")
            self.assertEqual(summary["calls"], 3)
            self.assertEqual(summary["linked"], 3, "handshake windows must prove all three")
            self.assertTrue(summary["finalized"], "fixture thread has task_complete")

            conn = open_history(Path(td) / "history.sqlite")
            game_id = import_game(conn, log)
            calls = conn.execute(
                "SELECT call_id,request_id,input_tokens,output_tokens,reasoning_tokens,total_tokens "
                "FROM model_calls WHERE game_id=? ORDER BY call_id", (game_id,)).fetchall()
            conn.close()

        self.assertEqual(len(calls), 3)
        self.assertEqual({c[1] for c in calls}, {"game-three-calls:request:1"})
        # The request total is computed FROM the calls. The rollout's per-turn and
        # per-thread cumulative blocks describe the same spending and must not be
        # added on top of them.
        self.assertEqual(sum(c[2] for c in calls), 580)
        self.assertEqual(sum(c[3] for c in calls), 115)
        self.assertEqual(sum(c[4] for c in calls), 27)
        self.assertEqual(sum(c[5] for c in calls), 722)



class OpenSideTurnTests(unittest.TestCase):
    """A turn that opened but never closed still owns what was spent inside it.

    Opening a turn must not look like completing one: no end revision, no replay
    frame, no completed-turn count.
    """

    def _failed_opening(self, td):
        archive = Path(td) / "archive"; archive.mkdir()
        state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                  "terrain": [], "units": [], "state_revision": 0}
        rows = [
            {"type": "metadata", "faction0": "undead", "faction1": "undead", "seed": 7,
             "llm_side": 0, "conversation_id": "conv-open"},
            {"type": "driver", "line": state0},
            {"type": "side_turn_started", "side_turn_id": "conv-open:side_turn:1",
             "side": 0, "round": 1, "start_revision": 0},
            {"type": "model_request", "request_id": "conv-open:request:1",
             "status": "failed", "state_revision": 0, "sequence": 1},
            # No accepted turn_boundary: the game died inside its first turn.
            {"type": "model_error", "code": "action_batch_rejected",
             "terminal_class": "model_invalid"},
        ]
        log = archive / "match.ndjson"
        log.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        (archive / "usage.ndjson").write_text(json.dumps({
            "game_id": "conv-open", "call_id": "c1", "provider": "offline",
            "transport": "model-command", "status": "failed",
            "request_id": "conv-open:request:1",
            "input_tokens": 5881, "output_tokens": 16384, "reasoning_tokens": 16384,
            "total_tokens": 22265, "finish_reason": "length",
            "record_kind": "final"}) + "\n", encoding="utf-8")
        return log

    def test_failed_opening_owns_its_usage_on_an_open_turn(self):
        with tempfile.TemporaryDirectory() as td:
            log = self._failed_opening(td)
            conn = open_history(Path(td) / "history.sqlite")
            game_id = import_game(conn, log)
            turns = conn.execute(
                "SELECT side_turn_id,status,start_revision,end_revision,end_snapshot_id "
                "FROM side_turns WHERE game_id=?", (game_id,)).fetchall()
            calls = conn.execute(
                "SELECT input_tokens,output_tokens,reasoning_tokens,total_tokens "
                "FROM model_calls WHERE game_id=?", (game_id,)).fetchall()
            conn.close()

            self.assertEqual(len(turns), 1)
            side_turn_id, status, start, end, end_snapshot = turns[0]
            self.assertEqual(side_turn_id, "conv-open:side_turn:1")
            self.assertEqual(status, "open")
            self.assertEqual(start, 0)
            # Open is not completed: nothing that could be read as an ending.
            self.assertIsNone(end)
            self.assertIsNone(end_snapshot)
            # The failed call's usage survives in full, exactly as measured.
            self.assertEqual(calls, [(5881, 16384, 16384, 22265)])

    def test_an_open_turn_adds_no_replay_frame(self):
        from .replay_game import build_bundle
        with tempfile.TemporaryDirectory() as td:
            log = self._failed_opening(td)
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, log)
            frames_expected = conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE game_id=? AND renderable=1",
                (game_id,)).fetchone()[0]
            conn.close()
            bundle = json.loads(Path(build_bundle(str(db), game_id, Path(td) / "b.json")).read_text())
            self.assertEqual(len(bundle["frames"]), frames_expected)


class IncrementalAttributionTests(unittest.TestCase):
    """Stack 3 acceptance: explicit context identity owns partial/open work."""

    def _archive(self, root: Path, *, conflicting: bool = False) -> Path:
        archive = root / "archive"
        (archive / "provider" / "requests" / "one").mkdir(parents=True)
        (archive / "provider" / "requests" / "two").mkdir(parents=True)
        state0 = {"type": "state", "turn": 1, "active_faction": 0,
                  "cols": 2, "rows": 2, "terrain": [], "units": [],
                  "state_revision": 0}
        state1 = dict(state0, state_revision=1, turn_boundary="partial")
        state2 = dict(state0, state_revision=2, active_faction=1)
        rows = [
            {"type": "metadata", "conversation_id": "incremental",
             "faction0": "undead", "faction1": "undead", "seed": 7,
             "llm_side": 0},
            {"type": "driver", "line": state0},
            {"type": "side_turn_started", "side_turn_id": "incremental:side_turn:1",
             "side": 0, "round": 1, "start_revision": 0},
            {"type": "model_request", "request_id": "incremental:request:1",
             "status": "completed", "state_revision": 0, "sequence": 1},
            {"type": "driver", "line": state1},
            {"type": "model_request", "request_id": "incremental:request:2",
             "status": "completed", "state_revision": 1, "sequence": 2},
            {"type": "turn_boundary", "accepted": True,
             "side_turn_id": "incremental:side_turn:1", "side": 0,
             "start_revision": 0, "state_revision": 2,
             "authored_finish_kind": "explicit_done"},
            {"type": "driver", "line": state2},
            {"type": "side_turn_started", "side_turn_id": "incremental:side_turn:2",
             "side": 0, "round": 2, "start_revision": 2},
            {"type": "model_request", "request_id": "incremental:request:3",
             "status": "failed", "state_revision": 2, "sequence": 3,
             "error_code": "model_request_uncertain"},
            {"type": "model_error", "terminal_class": "infrastructure",
             "reason": "infrastructure_failure", "code": "model_backend_failure",
             "ended_at": "2026-01-01T00:00:03Z", "wall_ms": 3000,
             "state_revision": 2},
        ]
        (archive / "match.ndjson").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        contexts = [
            ("one", "incremental:request:1", "incremental:side_turn:1", 0),
            ("two", "incremental:request:2", "incremental:side_turn:1", 1),
            ("bad", "incremental:request:3",
             "foreign:side_turn:9" if conflicting else "incremental:side_turn:2", 2),
        ]
        for name, request_id, side_turn_id, revision in contexts:
            directory = archive / "provider" / "requests" / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "request_context.json").write_text(json.dumps({
                "harness_request_id": request_id, "conversation_id": "incremental",
                "side": 0, "side_turn_id": side_turn_id,
                "state_revision": revision}), encoding="utf-8")
        (archive / "usage.ndjson").write_text(json.dumps({
            "game_id": "incremental", "call_id": "call-1", "request_id": "incremental:request:3",
            "provider": "offline", "transport": "fixture", "status": "failed",
            "error_code": "timeout", "record_kind": "final"}) + "\n", encoding="utf-8")
        return archive

    def test_contexts_link_intermediate_and_open_requests_and_reimport(self):
        with tempfile.TemporaryDirectory() as td:
            archive = self._archive(Path(td))
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, archive, game_id="incremental-game")
            self.assertEqual(conn.execute(
                "SELECT count(*),count(side_turn_id) FROM model_requests WHERE game_id=?",
                (game_id,)).fetchone(), (3, 3))
            self.assertEqual(conn.execute(
                "SELECT status,ended_at,failure_code FROM games WHERE game_id=?", (game_id,)
            ).fetchone(), ("complete", "2026-01-01T00:00:03Z", "model_backend_failure"))
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["linked_requests"], 3)
            self.assertEqual(coverage["unassigned_requests"], 0)
            self.assertEqual(coverage["usage_status"], "partial")
            before = conn.execute(
                "SELECT request_id,side_turn_id FROM model_requests ORDER BY sequence").fetchall()
            import_game(conn, archive, game_id=game_id)
            self.assertEqual(conn.execute("SELECT count(*) FROM model_requests").fetchone()[0], 3)
            self.assertEqual(conn.execute(
                "SELECT request_id,side_turn_id FROM model_requests ORDER BY sequence").fetchall(), before)
            conn.close()

    def test_foreign_context_identity_stays_unassigned(self):
        with tempfile.TemporaryDirectory() as td:
            archive = self._archive(Path(td), conflicting=True)
            conn = open_history(Path(td) / "history.sqlite")
            game_id = import_game(conn, archive, game_id="incremental-conflict")
            row = conn.execute(
                "SELECT side_turn_id FROM model_requests WHERE request_id='incremental:request:3'"
            ).fetchone()
            self.assertIsNone(row[0])
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["unassigned_requests"], 1)
            self.assertTrue(any("foreign_side_turn" in gap for gap in coverage["gaps"]))
            conn.close()


class ForeignIdentitySafetyTests(unittest.TestCase):
    """Foreign request identities remain visible but never become links."""

    @staticmethod
    def _archive(root: Path, conversation: str, request_id: str) -> Path:
        archive = root / conversation
        archive.mkdir()
        rows = [
            {"type": "metadata", "conversation_id": conversation, "llm_side": 0},
            {"type": "driver", "line": {"type": "state", "state_revision": 0,
             "turn": 1, "active_faction": 0}},
            {"type": "model_request", "request_id": request_id,
             "state_revision": 0, "status": "completed"},
            {"type": "terminal", "reason": "max_turns"},
        ]
        (archive / "match.ndjson").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return archive

    def test_foreign_request_is_unassigned_and_foreign_call_is_counted_unlinked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = self._archive(root, "first", "shared-request")
            second = self._archive(root, "second", "shared-request")
            (second / "usage.ndjson").write_text(json.dumps(_sidecar_row(
                game_id="second", call_id="call-2", request_id="shared-request",
                status="completed", input_tokens=7, output_tokens=3)) + "\n",
                encoding="utf-8")
            conn = open_history(root / "history.sqlite")
            import_game(conn, first, game_id="first-game")
            game_id = import_game(conn, second, game_id="second-game")
            request_coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual((request_coverage["request_count"],
                              request_coverage["linked_requests"],
                              request_coverage["unassigned_requests"]), (1, 0, 1))
            self.assertTrue(any("belongs_to:first-game" in gap
                                for gap in request_coverage["gaps"]))
            call = conn.execute(
                "SELECT request_id,input_tokens,output_tokens,linkage_evidence,"
                "normalization_gaps_json FROM model_calls WHERE game_id=?", (game_id,)
            ).fetchone()
            self.assertIsNone(call[0])
            self.assertEqual(call[1:3], (7, 3))
            self.assertIn("request_link:shared-request:belongs_to:first-game", call[3])
            self.assertIn("request_link:shared-request:belongs_to:first-game", call[4])
            self.assertTrue(any("usage_conflict" in conflict
                                and "shared-request" in conflict
                                for conflict in request_coverage["conflicts"]))
            verification = verify_history(root / "history.sqlite")
            self.assertEqual(verification["dangling_call_request_links"], 0)
            self.assertEqual(verification["cross_game_call_links"], 0)
            conn.close()

    def test_explicit_foreign_side_turn_has_conflict_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "archive"
            root.mkdir()
            rows = [
                {"type": "metadata", "conversation_id": "foreign-turn", "llm_side": 0},
                {"type": "driver", "line": {"type": "state", "state_revision": 0,
                 "turn": 1, "active_faction": 0}},
                {"type": "side_turn_started", "side_turn_id": "known-turn",
                 "side": 0, "start_revision": 0},
                {"type": "model_request", "request_id": "foreign-request",
                 "side_turn_id": "foreign-turn:9", "state_revision": 0},
                {"type": "terminal", "reason": "max_turns"},
            ]
            (root / "match.ndjson").write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            conn = open_history(Path(td) / "history.sqlite")
            game_id = import_game(conn, root, game_id="foreign-turn-game")
            self.assertIsNone(conn.execute(
                "SELECT side_turn_id FROM model_requests WHERE request_id='foreign-request'"
            ).fetchone()[0])
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["unassigned_requests"], 1)
            self.assertTrue(any("foreign_side_turn:foreign-turn:9" in gap
                                for gap in coverage["gaps"]))
            conn.close()

    def test_actions_backfill_from_request_identity_and_reject_conflicts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"type": "metadata", "conversation_id": "link-game", "llm_side": 0},
                {"type": "driver", "line": {"type": "state", "state_revision": 0,
                 "turn": 1, "active_faction": 0}},
                {"type": "side_turn_started", "side_turn_id": "turn-a",
                 "side": 0, "start_revision": 0},
                {"type": "side_turn_started", "side_turn_id": "turn-b",
                 "side": 0, "start_revision": 0},
                {"type": "model_request", "request_id": "req-a",
                 "side_turn_id": "turn-a", "state_revision": 0},
                {"type": "forwarded_orders", "request_id": "req-a", "batch_id": "batch-a",
                 "state_revision": 0, "orders": [{"action": "EndTurn"}]},
                {"type": "forwarded_orders", "request_id": "req-a", "batch_id": "batch-b",
                 "side_turn_id": "foreign-turn", "state_revision": 0,
                 "orders": [{"action": "EndTurn"}]},
                {"type": "forwarded_orders", "request_id": "foreign-request", "batch_id": "batch-c",
                 "side_turn_id": "turn-a", "state_revision": 0,
                 "orders": [{"action": "EndTurn"}]},
                {"type": "terminal", "reason": "max_turns"},
            ]
            (root / "match.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="link-game")
            self.assertEqual(conn.execute(
                "SELECT side_turn_id FROM action_batches WHERE batch_id='batch-a'" ).fetchone()[0], "turn-a")
            self.assertEqual(conn.execute(
                "SELECT side_turn_id FROM actions WHERE action_id='batch-a:action:0'" ).fetchone()[0], "turn-a")
            self.assertIsNone(conn.execute(
                "SELECT side_turn_id FROM action_batches WHERE batch_id='batch-b'" ).fetchone()[0])
            self.assertIsNone(conn.execute(
                "SELECT side_turn_id FROM action_batches WHERE batch_id='batch-c'" ).fetchone()[0])
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any("foreign_or_invalid_side_turn" in value
                                for value in coverage["conflicts"]))
            self.assertTrue(any("foreign_or_unknown_request" in value
                                for value in coverage["conflicts"]))
            before = conn.execute("SELECT side_turn_id FROM actions ORDER BY action_id").fetchall()
            import_game(conn, root, game_id=game_id)
            self.assertEqual(before, conn.execute(
                "SELECT side_turn_id FROM actions ORDER BY action_id").fetchall())
            conn.close()

    def test_review_coverage_retains_raw_draft_identity_without_fabrication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review_id = "draft-only"
            rows = [
                {"type": "metadata"},
                {"type": "draft_review", "review_id": review_id, "call": 2,
                 "original_candidate_digest": "a" * 64, "prompt_hash": "b" * 64},
                {"type": "draft_review_decision", "review_id": review_id,
                 "outcome": "confirmed", "revision": 0},
                {"type": "terminal", "reason": "max_turns"},
            ]
            (root / "match.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            reviews = coverage["review_coverage"]
            self.assertEqual(reviews["raw"], 1)
            self.assertEqual([entry["review_id"] for entry in reviews["raw_reviews"]], [review_id])
            self.assertEqual([entry["review_id"] for entry in reviews["raw_decisions"]], [review_id])
            self.assertEqual(reviews["imported"], 1)
            self.assertEqual(reviews["linked"], 0)
            self.assertEqual(reviews["missing"], [review_id])
            self.assertEqual(reviews["not_normalized"], [review_id])
            conn.close()

    def test_driver_sidecar_requires_source_and_archive_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata", "source_commit": "commit-a"}) + "\n" +
                           json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            digest = "a" * 64
            (root / "launch.json").write_text(json.dumps({
                "source_commit": "commit-a", "argv": ["--log", str(log)],
                "driver_sha256": digest}))
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="provenance")
            self.assertEqual(conn.execute(
                "SELECT driver_hash FROM games WHERE game_id=?", (game_id,)).fetchone()[0], digest)
            log.write_text(json.dumps({"type": "metadata", "source_commit": "commit-b"}) + "\n" +
                           json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            import_game(conn, root, game_id=game_id)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any("source_commit_mismatch" in gap for gap in coverage["gaps"]))
            self.assertEqual(conn.execute(
                "SELECT driver_hash FROM games WHERE game_id=?", (game_id,)).fetchone()[0], digest)
            conn.close()

    def test_driver_hash_conflicts_remain_visible_and_known_hash_is_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata", "source_commit": "commit-a",
                                       "driver_hash": "b" * 64}) + "\n" +
                           json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            (root / "launch.json").write_text(json.dumps({
                "source_commit": "commit-a", "argv": ["--log", str(log)],
                "driver_sha256": "c" * 64}))
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="hash-conflict")
            self.assertEqual(conn.execute(
                "SELECT driver_hash FROM games WHERE game_id=?", (game_id,)).fetchone()[0], "b" * 64)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any("hash_conflict" in gap for gap in coverage["gaps"]))
            conn.close()

    def test_reimport_refreshes_provenance_source_when_hash_was_initially_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata", "source_commit": "commit-a"}) + "\n" +
                           json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="late-provenance")
            self.assertIsNone(conn.execute(
                "SELECT driver_hash FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            digest = "d" * 64
            (root / "launch.json").write_text(json.dumps({
                "source_commit": "commit-a", "argv": ["--log", str(log)],
                "driver_sha256": digest}))
            import_game(conn, root, game_id=game_id)
            value = conn.execute(
                "SELECT driver_hash,provenance_json FROM games WHERE game_id=?", (game_id,)).fetchone()
            self.assertEqual(value[0], digest)
            self.assertEqual(json.loads(value[1])["driver_hash_source"], "launch_sidecar")
            conn.close()

    def test_driver_sidecar_without_archive_source_is_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n" +
                           json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            (root / "launch.json").write_text(json.dumps({
                "source_commit": "commit-a", "argv": ["--log", str(log)],
                "driver_sha256": "e" * 64}))
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="unknown-source")
            self.assertIsNone(conn.execute(
                "SELECT driver_hash FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertTrue(any("source_commit_mismatch" in gap for gap in coverage["gaps"]))
            conn.close()

    def test_review_explicit_turn_must_match_validated_request_turn(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prompt_hash = "f" * 64
            rows = [
                {"type": "metadata", "conversation_id": "review-game", "llm_side": 0},
                {"type": "driver", "line": {"type": "state", "state_revision": 0,
                 "turn": 1, "active_faction": 0}},
                {"type": "side_turn_started", "side_turn_id": "turn-a",
                 "side": 0, "start_revision": 0},
                {"type": "model_request", "request_id": "req-review",
                 "side_turn_id": "turn-a", "state_revision": 0,
                 "prompt_hash": prompt_hash},
                {"type": "draft_review", "review_id": "review-a",
                 "request_id": "req-review", "side_turn_id": "foreign-turn",
                 "prompt_hash": prompt_hash},
                {"type": "draft_review_decision", "review_id": "review-a",
                 "request_id": "req-review", "side_turn_id": "foreign-turn",
                 "outcome": "confirmed"},
                {"type": "terminal", "reason": "max_turns"},
            ]
            (root / "match.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="review-game")
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            reviews = coverage["review_coverage"]
            self.assertEqual(reviews["linked"], 0)
            self.assertEqual(reviews["missing"], ["review-a"])
            self.assertEqual(reviews["raw_reviews"][0]["link_status"], "conflict")
            conn.close()

    def test_review_without_identity_is_imported_but_not_counted_linked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"type": "metadata"},
                {"type": "draft_review", "prompt_hash": "a" * 64},
                {"type": "draft_review_decision", "outcome": "confirmed"},
                {"type": "terminal", "reason": "max_turns"},
            ]
            (root / "match.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            reviews = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])["review_coverage"]
            self.assertEqual(reviews["imported"], 1)
            self.assertEqual(reviews["linked"], 0)
            self.assertEqual(reviews["missing_review_id_count"], 1)
            self.assertEqual(reviews["raw_reviews"][0]["link_status"], "missing")
            conn.close()

    def test_repaired_review_decision_accepts_valid_repair_request_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"type": "metadata", "conversation_id": "repair-game", "llm_side": 0},
                {"type": "driver", "line": {"type": "state", "state_revision": 0,
                 "turn": 1, "active_faction": 0}},
                {"type": "side_turn_started", "side_turn_id": "turn-a",
                 "side": 0, "start_revision": 0},
                {"type": "model_request", "request_id": "req-draft",
                 "side_turn_id": "turn-a", "state_revision": 0, "prompt_hash": "a" * 64},
                {"type": "model_request", "request_id": "req-repair",
                 "side_turn_id": "turn-a", "state_revision": 0, "prompt_hash": "b" * 64},
                {"type": "draft_review", "review_id": "review-good",
                 "request_id": "req-draft", "prompt_hash": "a" * 64},
                {"type": "draft_review_repair", "review_id": "review-good",
                 "request_id": "req-repair", "side_turn_id": "turn-a",
                 "prompt_hash": "b" * 64},
                {"type": "draft_review_decision", "review_id": "review-good",
                 "request_id": "req-repair", "side_turn_id": "turn-a", "outcome": "repaired"},
                {"type": "draft_review", "review_id": "review-bad",
                 "request_id": "req-draft", "prompt_hash": "a" * 64},
                {"type": "draft_review_repair", "review_id": "review-bad",
                 "request_id": "foreign-request", "side_turn_id": "turn-a",
                 "prompt_hash": "z" * 64},
                {"type": "draft_review_decision", "review_id": "review-bad",
                 "request_id": "foreign-request", "side_turn_id": "turn-a", "outcome": "repaired"},
                {"type": "terminal", "reason": "max_turns"},
            ]
            (root / "match.ndjson").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root, game_id="repair-game")
            reviews = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])["review_coverage"]
            self.assertEqual(reviews["linked"], 2)
            decisions = {d["review_id"]: d["identity_status"] for d in reviews["raw_decisions"]}
            self.assertEqual(decisions["review-good"], "linked")
            self.assertEqual(decisions["review-bad"], "conflict")
            self.assertEqual(reviews["decision_identity_conflicts"], ["review-bad"])
            conn.close()


FIREWORKS_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "backfill_fireworks_ok" / "requests"


class BackfillUsageAndCompareUsageCliTests(unittest.TestCase):
    """CLI wiring for Stack 3's `backfill-usage` and `compare-usage` commands.

    tools/usage_backfill.py owns the actual logic and its own thorough test
    suite (tools/test_usage_backfill.py); this only proves the two
    subcommands are wired into game_history's argparse dispatch correctly,
    including the read/write mode and exit-code contract shared with
    backfill-events.
    """

    def _catalog_with_game(self, root: Path, game_id: str) -> Path:
        log = root / "match.ndjson"
        log.write_text("\n".join(json.dumps(r) for r in [
            {"type": "metadata", "seed": 1, "scenario": "cli-fixture",
             "faction0": "undead", "faction1": "undead", "gold": 0, "first_player": 0},
            {"type": "terminal", "reason": "max_turns"},
        ]) + "\n", encoding="utf-8")
        db = root / "history.sqlite"
        conn = open_history(db)
        import_game(conn, root, game_id=game_id)
        conn.close()
        return db

    def test_backfill_usage_cli_dry_run_then_execute(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._catalog_with_game(root, "cli-g1")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"games": {"cli-g1": {
                "kind": "fireworks_requests", "requests_dir": str(FIREWORKS_FIXTURE_ROOT)}}}),
                encoding="utf-8")

            code = game_history_main(["backfill-usage", "--db", str(db), "--manifest", str(manifest),
                                      "--game-id", "cli-g1"])
            self.assertEqual(code, 0)
            conn = open_history(db, read_only=True)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id='cli-g1'").fetchone()[0], 0)
            conn.close()

            code = game_history_main(["backfill-usage", "--db", str(db), "--manifest", str(manifest),
                                      "--game-id", "cli-g1", "--execute"])
            self.assertEqual(code, 0)
            conn = open_history(db, read_only=True)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM model_calls WHERE game_id='cli-g1'").fetchone()[0], 2)
            conn.close()

    def test_backfill_usage_cli_nonzero_exit_on_unavailable_game(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._catalog_with_game(root, "cli-g2")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"games": {"cli-g2": {
                "kind": "fireworks_requests", "requests_dir": str(FIREWORKS_FIXTURE_ROOT)}}}),
                encoding="utf-8")
            code = game_history_main(["backfill-usage", "--db", str(db), "--manifest", str(manifest),
                                      "--game-id", "cli-g2", "--game-id", "never-catalogued", "--execute"])
            self.assertEqual(code, 1)

    def test_compare_usage_cli_json_and_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = self._catalog_with_game(root, "cli-g3")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"games": {"cli-g3": {
                "kind": "fireworks_requests", "requests_dir": str(FIREWORKS_FIXTURE_ROOT)}}}),
                encoding="utf-8")
            self.assertEqual(game_history_main(["backfill-usage", "--db", str(db), "--manifest", str(manifest),
                                                "--game-id", "cli-g3", "--execute"]), 0)

            # compare-usage never writes: the same read-only path other read
            # commands use, so it must succeed against a read-only handle.
            with mock.patch("sys.stdout", new=__import__("io").StringIO()) as out:
                code = game_history_main(["compare-usage", "--db", str(db), "--game-id", "cli-g3", "--json"])
                self.assertEqual(code, 0)
                payload = json.loads(out.getvalue())
                self.assertEqual(payload["games"][0]["game_id"], "cli-g3")

            with mock.patch("sys.stdout", new=__import__("io").StringIO()) as out:
                code = game_history_main(["compare-usage", "--db", str(db), "--game-id", "cli-g3"])
                self.assertEqual(code, 0)
                self.assertIn("cli-g3", out.getvalue())


if __name__ == "__main__":
    unittest.main()
