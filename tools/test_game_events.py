"""Tests for the executed-event timeline: import, backfill, and catalog
maintenance for the `events` table (see docs/GAME_HISTORY.md).

Reuses tools/test_game_history.py's inline-archive style. The deterministic
production-path test at the bottom follows the pattern in
tools/test_s2_deterministic_endings.py: it runs the real client/driver with a
canned --orders-file responder (no model provider) and imports the resulting
archive, rather than only asserting against hand-built JSON.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .game_history import (SCHEMA, backfill_events, delete_history, import_game, inventory_history,
                           main, open_history, verify_history)


def _write(root: Path, rows: list[dict]) -> Path:
    log = root / "match.ndjson"
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return log


def _mixed_rows() -> list[dict]:
    return [
        {"type": "metadata", "seed": 1, "scenario": "mix", "faction0": "a", "faction1": "b",
         "gold": 10, "first_player": 0},
        {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1,
                                    "active_faction": 0, "note": "opening"}},
        # A preview/simulation payload under a non-driver record type, and a
        # driver line whose type is not "events" -- neither must contribute rows.
        {"type": "preview_orders", "events": [{"kind": "move", "unit": 999}]},
        {"type": "driver", "line": {"type": "status", "ok": True,
                                    "events": [{"kind": "move", "unit": 998}]}},
        {"type": "forwarded_orders", "batch_id": "batch-engage", "request_id": "req-1",
         "state_revision": 0, "orders": [{"action": "Engage", "unit_id": 5, "target_id": 6}]},
        {"type": "driver", "line": {"type": "events", "source": "llm", "events": [
            {"kind": "move", "unit": 5, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}, "source": "llm"},
            {"kind": "attack",
             "attacker": {"unit": 5, "hp": 8, "xp": 0, "killed": False, "poisoned": False, "slowed": False},
             "defender": {"unit": 6, "hp": 0, "xp": 0, "killed": True, "poisoned": False, "slowed": False},
             "damage_to_defender": 10, "damage_to_attacker": 2, "source": "llm"},
        ]}},
        {"type": "turn_boundary", "accepted": True, "side_turn_id": "turn-model-1", "side": 0,
         "start_revision": 0, "state_revision": 1, "authored_finish_kind": "engage_only"},
        {"type": "driver", "line": {"type": "state", "state_revision": 1, "turn": 1, "active_faction": 1}},
        # Opponent's own (unbatched) turn: never attached to a nearby model batch.
        {"type": "driver", "line": {"type": "events", "source": "greedy", "events": [
            {"kind": "move", "unit": 7, "from": {"col": 1, "row": 1}, "to": {"col": 1, "row": 0}},
            {"kind": "heal", "unit": 7, "amount": 4, "hp": 10, "reason": "regenerate"},
        ]}},
        {"type": "turn_boundary", "accepted": True, "side_turn_id": "turn-greedy-1", "side": 1,
         "start_revision": 1, "state_revision": 2, "authored_finish_kind": "ai_finished"},
        {"type": "driver", "line": {"type": "state", "state_revision": 2, "turn": 2, "active_faction": 0}},
        # A second model batch: authored recruit, then FinishWithGreedy delegation.
        {"type": "forwarded_orders", "batch_id": "batch-finish", "request_id": "req-2",
         "state_revision": 2, "orders": [{"action": "Recruit", "def_id": "x", "col": 0, "row": 0},
                                         {"action": "FinishWithGreedy"}]},
        {"type": "driver", "line": {"type": "events", "source": "llm", "events": [
            {"kind": "recruit", "unit": 9, "def_id": "x", "faction": 0, "col": 0, "row": 0, "cost": 5},
        ]}},
        {"type": "driver", "line": {"type": "events", "source": "delegated_greedy", "events": [
            {"kind": "move", "unit": 9, "from": {"col": 0, "row": 0}, "to": {"col": 0, "row": 1}},
            {"kind": "village", "col": 0, "row": 1, "owner": 0},
        ]}},
        {"type": "turn_boundary", "accepted": True, "side_turn_id": "turn-model-2", "side": 0,
         "start_revision": 2, "state_revision": 3, "authored_finish_kind": "finish_with_greedy"},
        {"type": "driver", "line": {"type": "state", "state_revision": 3, "turn": 2, "active_faction": 1}},
        # An unfamiliar future event/source kind: preserved, never guessed onto a batch.
        {"type": "driver", "line": {"type": "events", "source": "mystery_driver", "events": [
            {"kind": "mystery_effect", "unit": 42, "note": "unseen future kind"},
        ]}},
        {"type": "terminal", "reason": "max_turns"},
    ]


class MixedFixtureImportTests(unittest.TestCase):
    def _import(self, td: str):
        root = Path(td)
        _write(root, _mixed_rows())
        conn = open_history(root / "history.sqlite")
        game_id = import_game(conn, root)
        return conn, game_id

    def test_imported_count_matches_sum_of_source_events_arrays_and_preview_contributes_zero(self):
        with tempfile.TemporaryDirectory() as td:
            conn, game_id = self._import(td)
            rows = conn.execute(
                "SELECT event_sequence,kind,source,batch_id,side_turn_id,record_sequence,event_index,event_json "
                "FROM events WHERE game_id=? ORDER BY event_sequence", (game_id,)).fetchall()
            self.assertEqual(len(rows), 8)  # 2+2+1+2+1, preview/status contribute nothing
            self.assertEqual([r[1] for r in rows],
                             ["move", "attack", "move", "heal", "recruit", "move", "village", "mystery_effect"])
            conn.close()

    def test_ordering_and_decoded_payloads_match_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            conn, game_id = self._import(td)
            rows = conn.execute(
                "SELECT event_json FROM events WHERE game_id=? ORDER BY event_sequence", (game_id,)).fetchall()
            expected = []
            for record in _mixed_rows():
                if record.get("type") != "driver":
                    continue
                line = record["line"]
                if line.get("type") != "events":
                    continue
                expected.extend(line["events"])
            self.assertEqual([json.loads(r[0]) for r in rows], expected)
            conn.close()

    def test_batch_and_side_turn_links_resolve_only_through_explicit_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            conn, game_id = self._import(td)
            # Fetched positionally since "move" repeats across three sources.
            ordered = conn.execute(
                "SELECT kind,source,batch_id,side_turn_id FROM events WHERE game_id=? ORDER BY event_sequence",
                (game_id,)).fetchall()
            kinds = [r[0] for r in ordered]
            self.assertEqual(kinds, ["move", "attack", "move", "heal", "recruit", "move", "village", "mystery_effect"])
            move1, attack1, move2, heal1, recruit1, move3, village1, mystery1 = ordered
            # llm-authored Engage batch: explicit batch_id, side turn resolved
            # via the forwarded_orders' own state_revision matching a proven
            # turn boundary endpoint.
            self.assertEqual(move1[2:], ("batch-engage", "turn-model-1"))
            self.assertEqual(attack1[2:], ("batch-engage", "turn-model-1"))
            self.assertEqual(attack1[1], "llm")
            # Greedy's own (unbatched) turn: never attached to a nearby model batch.
            self.assertEqual(move2[1:], ("greedy", None, None))
            self.assertEqual(heal1[1:], ("greedy", None, None))
            # FinishWithGreedy: authored and delegated events share the batch_id
            # but keep distinct, non-collapsed source attribution.
            self.assertEqual(recruit1[1:], ("llm", "batch-finish", "turn-model-2"))
            self.assertEqual(move3[1:], ("delegated_greedy", "batch-finish", "turn-model-2"))
            self.assertEqual(village1[1:], ("delegated_greedy", "batch-finish", "turn-model-2"))
            # Unfamiliar source: preserved verbatim, never guessed onto a batch.
            self.assertEqual(mystery1[1:], ("mystery_driver", None, None))
            conn.close()

    def test_unresolved_side_turn_link_stays_null_while_batch_id_is_explicit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "forwarded_orders", "batch_id": "b1", "state_revision": 0, "orders": [{"action": "Done"}]},
                {"type": "driver", "line": {"type": "events", "source": "llm",
                    "events": [{"kind": "move", "unit": 1, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}}]}},
                {"type": "terminal", "reason": "max_turns"},
            ]
            _write(root, rows)
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            row = conn.execute("SELECT batch_id,side_turn_id FROM events WHERE game_id=?", (game_id,)).fetchone()
            self.assertEqual(row, ("b1", None))
            conn.close()

    def test_identical_payloads_at_two_positions_both_survive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            event = {"kind": "gold", "faction": 0, "delta": -5, "balance": 45, "reason": "recruit"}
            rows = [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "events", "source": "greedy", "events": [dict(event)]}},
                {"type": "driver", "line": {"type": "events", "source": "greedy", "events": [dict(event)]}},
                {"type": "terminal", "reason": "max_turns"},
            ]
            _write(root, rows)
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            got = conn.execute(
                "SELECT record_sequence,event_index,event_json FROM events WHERE game_id=? ORDER BY event_sequence",
                (game_id,)).fetchall()
            self.assertEqual(len(got), 2)
            self.assertNotEqual(got[0][0], got[1][0])  # different source positions
            self.assertEqual(json.loads(got[0][2]), event)
            self.assertEqual(json.loads(got[1][2]), event)
            conn.close()

    def test_reimport_is_identical_and_append_only_adds_new_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_rows = [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "events", "source": "greedy",
                    "events": [{"kind": "move", "unit": 1, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}}]}},
            ]
            log = _write(root, base_rows + [{"type": "terminal", "reason": "max_turns"}])
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            before = conn.execute(
                "SELECT event_sequence,kind,record_sequence,event_index FROM events WHERE game_id=? ORDER BY event_sequence",
                (game_id,)).fetchall()
            import_game(conn, root, game_id=game_id)
            after_reimport = conn.execute(
                "SELECT event_sequence,kind,record_sequence,event_index FROM events WHERE game_id=? ORDER BY event_sequence",
                (game_id,)).fetchall()
            self.assertEqual(before, after_reimport)
            # Append-only growth: one more driver events record before terminal.
            grown_rows = base_rows + [
                {"type": "driver", "line": {"type": "events", "source": "greedy",
                    "events": [{"kind": "heal", "unit": 1, "amount": 3, "hp": 13, "reason": "regenerate"}]}},
                {"type": "terminal", "reason": "max_turns"},
            ]
            _write(root, grown_rows)
            import_game(conn, root, game_id=game_id)
            after_growth = conn.execute(
                "SELECT event_sequence,kind,record_sequence,event_index FROM events WHERE game_id=? ORDER BY event_sequence",
                (game_id,)).fetchall()
            self.assertEqual(after_growth[:len(before)], before)
            self.assertEqual(len(after_growth), len(before) + 1)
            self.assertEqual(after_growth[-1][1], "heal")
            conn.close()

    def test_malformed_event_record_is_reported_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rows = [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "events", "source": "greedy",
                    "events": [{"kind": "move", "unit": 1, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}}]}},
                {"type": "driver", "line": {"type": "events", "source": "greedy", "events": "not-a-list"}},
                {"type": "driver", "line": {"type": "events", "source": "greedy", "events": [{"unit": 5}]}},  # no kind
                {"type": "terminal", "reason": "max_turns"},
            ]
            _write(root, rows)
            conn = open_history(root / "history.sqlite")
            game_id = import_game(conn, root)
            # The one well-formed event is still imported.
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM events WHERE game_id=?", (game_id,)).fetchone()[0], 1)
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["events_status"], "incomplete")
            self.assertTrue(any(g.startswith("event_malformed:") for g in coverage["gaps"]))
            conn.close()


class OldSchemaAndMaintenanceTests(unittest.TestCase):
    def test_legacy_catalog_gains_the_events_table_on_open(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "legacy.sqlite"
            import sqlite3
            legacy = sqlite3.connect(path)
            legacy.executescript(SCHEMA.split("CREATE TABLE IF NOT EXISTS events")[0])
            legacy.commit(); legacy.close()
            conn = open_history(path)
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("events", tables)
            root = Path(td)
            _write(root, [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "events", "source": "greedy",
                    "events": [{"kind": "gold", "faction": 0, "delta": 1, "balance": 11, "reason": "village"}]}},
                {"type": "terminal", "reason": "max_turns"},
            ])
            game_id = import_game(conn, root)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM events WHERE game_id=?", (game_id,)).fetchone()[0], 1)
            conn.close()

    def test_deleting_one_game_cleans_its_events_without_touching_another(self):
        with tempfile.TemporaryDirectory() as td:
            root1, root2 = Path(td) / "g1", Path(td) / "g2"
            root1.mkdir(); root2.mkdir()
            for root, unit in ((root1, 1), (root2, 2)):
                _write(root, [
                    {"type": "metadata"},
                    {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                    {"type": "driver", "line": {"type": "events", "source": "greedy",
                        "events": [{"kind": "move", "unit": unit, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}}]}},
                    {"type": "terminal", "reason": "max_turns"},
                ])
            conn = open_history(Path(td) / "history.sqlite")
            g1 = import_game(conn, root1)
            g2 = import_game(conn, root2)
            self.assertEqual(conn.execute("SELECT count(*) FROM events").fetchone()[0], 2)
            delete_history(conn, game_ids=[g1])
            self.assertEqual(conn.execute("SELECT count(*) FROM events WHERE game_id=?", (g1,)).fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM events WHERE game_id=?", (g2,)).fetchone()[0], 1)
            verification = verify_history(Path(td) / "history.sqlite")
            self.assertEqual(verification["dangling_event_side_turn_links"], 0)
            self.assertEqual(verification["dangling_event_batch_links"], 0)
            conn.close()

    def test_inventory_reports_the_events_table(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write(root, [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "driver", "line": {"type": "events", "source": "greedy",
                    "events": [{"kind": "move", "unit": 1, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}}]}},
                {"type": "terminal", "reason": "max_turns"},
            ])
            conn = open_history(root / "history.sqlite")
            import_game(conn, root)
            self.assertEqual(inventory_history(conn)["counts"]["events"], 1)
            conn.close()


class BackfillEventsTests(unittest.TestCase):
    def _seed_game(self, root: Path, kind: str = "move") -> None:
        _write(root, [
            {"type": "metadata"},
            {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
            {"type": "driver", "line": {"type": "events", "source": "greedy",
                "events": [{"kind": kind, "unit": 1, "from": {"col": 0, "row": 0}, "to": {"col": 1, "row": 0}}]
                          if kind == "move" else
                          [{"kind": kind, "faction": 0, "delta": 1, "balance": 1, "reason": "village"}]}},
            {"type": "terminal", "reason": "max_turns"},
        ])

    def test_backfill_multiple_games_handles_missing_archive_and_malformed_record_idempotently(self):
        with tempfile.TemporaryDirectory() as td:
            good_root = Path(td) / "good"; good_root.mkdir()
            missing_root = Path(td) / "missing"; missing_root.mkdir()
            malformed_root = Path(td) / "malformed"; malformed_root.mkdir()
            self._seed_game(good_root)
            self._seed_game(missing_root)
            self._seed_game(malformed_root)
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            good_id = import_game(conn, good_root, game_id="good-game")
            missing_id = import_game(conn, missing_root, game_id="missing-game")
            malformed_id = import_game(conn, malformed_root, game_id="malformed-game")
            # Simulate these games not yet having been backfilled.
            for game_id in (good_id, missing_id, malformed_id):
                conn.execute("DELETE FROM events WHERE game_id=?", (game_id,))
            conn.commit()
            # missing: archive disappears entirely.
            (missing_root / "match.ndjson").unlink()
            # malformed: archive gains an unreadable event record.
            (malformed_root / "match.ndjson").write_text(
                json.dumps({"type": "metadata"}) + "\n"
                + json.dumps({"type": "driver", "line": {"type": "events", "source": "greedy",
                                                         "events": "broken"}}) + "\n"
                + json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            result = backfill_events(conn, [good_id, missing_id, malformed_id])
            self.assertEqual(result["attempted"], 3)
            self.assertEqual([g["game_id"] for g in result["imported"]], [good_id])
            self.assertEqual(result["imported"][0]["event_count"], 1)
            self.assertEqual([g["game_id"] for g in result["unavailable"]], [missing_id])
            self.assertEqual([g["game_id"] for g in result["failed"]], [malformed_id])
            # A prior failure must not remove existing (pre-backfill) rows; here
            # there were none pre-backfill, so it must still be none, not a
            # partial/garbage row.
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM events WHERE game_id=?", (malformed_id,)).fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM events WHERE game_id=?", (missing_id,)).fetchone()[0], 0)
            # Repeating is idempotent for the games that can succeed.
            result2 = backfill_events(conn, [good_id])
            self.assertEqual(result2["imported"][0]["event_count"], 1)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM events WHERE game_id=?", (good_id,)).fetchone()[0], 1)
            conn.close()

    def test_backfill_does_not_replace_valid_prior_rows_on_a_later_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "game"; root.mkdir()
            self._seed_game(root)
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, root, game_id="stable-game")
            before = conn.execute(
                "SELECT event_sequence,kind,event_json FROM events WHERE game_id=?", (game_id,)).fetchall()
            self.assertEqual(len(before), 1)
            # Corrupt the archive after a successful import; a later backfill
            # attempt must fail without touching the rows already recorded.
            (root / "match.ndjson").write_text(
                json.dumps({"type": "metadata"}) + "\n"
                + json.dumps({"type": "driver", "line": {"type": "events", "source": "greedy",
                                                         "events": "broken"}}) + "\n"
                + json.dumps({"type": "terminal", "reason": "max_turns"}) + "\n")
            result = backfill_events(conn, [game_id])
            self.assertEqual(result["failed"][0]["game_id"], game_id)
            after = conn.execute(
                "SELECT event_sequence,kind,event_json FROM events WHERE game_id=?", (game_id,)).fetchall()
            self.assertEqual(before, after)
            conn.close()

    def test_backfill_reports_zero_events_honestly_not_as_full_capture_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "no-events"; root.mkdir()
            _write(root, [
                {"type": "metadata"},
                {"type": "driver", "line": {"type": "state", "state_revision": 0, "turn": 1, "active_faction": 0}},
                {"type": "terminal", "reason": "max_turns"},
            ])
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, root)
            result = backfill_events(conn, [game_id])
            self.assertEqual(result["imported"][0]["event_count"], 0)
            self.assertTrue(result["imported"][0]["no_event_evidence"])
            coverage = json.loads(conn.execute(
                "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
            self.assertEqual(coverage["events_status"], "no_event_evidence")
            conn.close()

    def test_cli_backfill_events_returns_nonzero_when_a_selected_game_is_unavailable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "game"; root.mkdir()
            self._seed_game(root)
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, root, game_id="known-game")
            conn.close()
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code_ok = main(["backfill-events", "--db", str(db), "--game-id", game_id])
            self.assertEqual(code_ok, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                code_bad = main(["backfill-events", "--db", str(db), "--game-id", "not-a-real-game"])
            self.assertEqual(code_bad, 1)

    def test_backfill_all_selects_every_catalogued_game(self):
        with tempfile.TemporaryDirectory() as td:
            root1 = Path(td) / "g1"; root1.mkdir()
            root2 = Path(td) / "g2"; root2.mkdir()
            self._seed_game(root1)
            self._seed_game(root2, kind="gold")
            db = Path(td) / "history.sqlite"
            conn = open_history(db)
            g1 = import_game(conn, root1, game_id="g1")
            g2 = import_game(conn, root2, game_id="g2")
            for game_id in (g1, g2):
                conn.execute("DELETE FROM events WHERE game_id=?", (game_id,))
            conn.commit()
            result = backfill_events(conn, all_games=True)
            self.assertEqual(result["attempted"], 2)
            self.assertEqual(sorted(g["game_id"] for g in result["imported"]), ["g1", "g2"])
            conn.close()


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
FIXTURE_ROOT = ROOT / "norrust_core/tests/fixtures/s2_deterministic_duel"


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
@unittest.skipUnless(FIXTURE_ROOT.is_dir(), "s2_deterministic_duel fixture is missing")
class DeterministicDriverEventImportTests(unittest.TestCase):
    """Runs the real client/driver (no model provider) and proves the events
    returned by an SQL query after import match what the driver actually
    emitted in the archive -- the production path, not only hand-built JSON.
    """

    def test_real_driver_attack_and_end_turn_events_round_trip_through_import(self):
        with tempfile.TemporaryDirectory() as td:
            directory = Path(td)
            orders_path = directory / "orders.jsonl"
            orders_path.write_text(json.dumps({"text": json.dumps(
                [{"action": "Attack", "attacker_id": 1, "defender_id": 2}, {"action": "EndTurn"}])}) + "\n")
            log = directory / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                      "--orders-file", str(orders_path), "--scenario", "duel",
                      "--faction0", "lethal", "--faction1", "fragile", "--gold", "0",
                      "--seed", "42", "--llm-side", "0", "--max-turns", "50",
                      "--log", str(log), "--query-budget-seconds", "10", "--model-timeout", "10",
                      "--turn-timeout", "30"]
            env = dict(os.environ, NORRUST_TEST_ROOT_DIR=str(FIXTURE_ROOT))
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])

            expected_kinds = []
            for line in log.read_text().splitlines():
                record = json.loads(line)
                if record.get("type") != "driver":
                    continue
                inner = record["line"]
                if inner.get("type") != "events":
                    continue
                expected_kinds.extend(event["kind"] for event in inner["events"])
            self.assertIn("attack", expected_kinds)  # sanity: the driver really emitted one

            old_test_root = os.environ.get("NORRUST_TEST_ROOT_DIR")
            os.environ["NORRUST_TEST_ROOT_DIR"] = str(FIXTURE_ROOT)
            try:
                conn = open_history(directory / "history.sqlite")
                game_id = import_game(conn, log)
            finally:
                if old_test_root is None:
                    os.environ.pop("NORRUST_TEST_ROOT_DIR", None)
                else:
                    os.environ["NORRUST_TEST_ROOT_DIR"] = old_test_root
            imported_kinds = [row[0] for row in conn.execute(
                "SELECT kind FROM events WHERE game_id=? ORDER BY event_sequence", (game_id,)).fetchall()]
            self.assertEqual(imported_kinds, expected_kinds)
            conn.close()



class EventStorageDoesNotInvalidatePlaybackTests(unittest.TestCase):
    """Storing events must not make already-catalogued games unplayable.

    tools/replay_game.py refuses to export a game whose importer_version does
    not match, so bumping that constant for an additive events table would make
    every existing catalog refuse to replay - and backfill-events, which only
    writes derived event rows, would not clear it. Event presence belongs in
    coverage, not in the timeline's version guard.
    """

    def test_importer_version_still_guards_only_the_timeline_contract(self):
        from .game_history import IMPORTER_VERSION
        self.assertEqual(
            IMPORTER_VERSION, "s1_snapshot_v1",
            "bumping IMPORTER_VERSION for an events-only change makes every "
            "previously imported game refuse to replay; report event presence "
            "through coverage_json.events_status instead")

    def test_replay_export_accepts_a_catalog_imported_before_events_existed(self):
        from . import game_history
        from .replay_game import build_bundle
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            log = _write(Path(td), _mixed_rows())
            conn = game_history.open_history(db)
            game_id = game_history.import_game(conn, log)
            # Simulate a catalog written before the events table existed at all.
            conn.execute("DELETE FROM events WHERE game_id=?", (game_id,))
            conn.commit()
            conn.close()
            bundle = build_bundle(str(db), game_id, Path(td) / "bundle.json")
            self.assertTrue(Path(bundle).is_file(),
                            "a game with no event rows must still export frames")


if __name__ == "__main__":
    unittest.main()
