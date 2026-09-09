import json
import tempfile
import unittest
from pathlib import Path

from .game_history import import_game, open_history
from .replay_game import build_bundle


def _write_log(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


class ReplayExportTests(unittest.TestCase):
    def test_export_builds_frames_from_the_snapshot_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "archive"; archive.mkdir()
            log = archive / "match.ndjson"
            state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                     "terrain": [], "units": [], "state_revision": 0}
            state1 = dict(state0, active_faction=1, state_revision=1)
            _write_log(log, [
                {"type": "metadata", "faction0": "undead", "faction1": "undead"},
                {"type": "driver", "line": state0},
                {"type": "turn_boundary", "accepted": True, "start_revision": 0, "state_revision": 1,
                 "authored_finish_kind": "explicit_done"},
                {"type": "driver", "line": state1},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ])
            db = root / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, archive)
            conn.execute("UPDATE game_players SET display_name='undead' WHERE game_id=? AND side=0", (game_id,))
            conn.commit(); conn.close()
            bundle_path = build_bundle(db, game_id, root / "out" / "replay.json")
            bundle = json.loads(bundle_path.read_text())
            self.assertEqual(bundle["game_id"], game_id)
            self.assertEqual([f["revision"] for f in bundle["frames"]], [0, 1])
            self.assertEqual(bundle["frames"][0]["boundary_kind"], "opening")
            self.assertEqual(bundle["frames"][-1]["boundary_kind"], "terminal")
            self.assertTrue(bundle["coverage"]["opening_present"])
            self.assertTrue(bundle["coverage"]["terminal_present"])
            self.assertEqual(bundle["players"][0]["display_name"], "undead")

    def test_unknown_game_fails(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.sqlite"
            conn = open_history(db); conn.close()
            with self.assertRaises(KeyError):
                build_bundle(db, "nope", Path(td) / "x")

    def test_stale_pre_snapshot_catalog_row_is_an_actionable_diagnostic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "archive"; archive.mkdir()
            (archive / "match.ndjson").write_text('{"type":"metadata"}\n', encoding="utf-8")
            db = root / "history.sqlite"
            conn = open_history(db)
            with conn:
                conn.execute("""INSERT INTO games(game_id,status,config_json,provenance_json,
                    schema_version,artifact_path) VALUES(?,?,?,?,?,?)""",
                    ("legacy", "complete", "{}", "{}", 2, str(archive)))
            conn.close()
            with self.assertRaisesRegex(ValueError, "Reimport it"):
                build_bundle(db, "legacy", root / "x")



class RequestedIdentityTests(unittest.TestCase):
    """A transport that cannot report the host's model leaves the catalog's
    identity columns NULL. The browser reads an operator's identity.json sidecar
    to fill that in; the replay export must resolve it through the same helper,
    or the two views disagree about who played the same game.
    """

    def _game(self, root: Path, sidecar: dict | None):
        archive = root / "archive"; archive.mkdir()
        log = archive / "match.ndjson"
        state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                  "terrain": [], "units": [], "state_revision": 0}
        state1 = dict(state0, active_faction=1, state_revision=1)
        _write_log(log, [
            {"type": "metadata", "faction0": "undead", "faction1": "undead", "seed": 7,
             "llm_side": 0},
            {"type": "driver", "line": state0},
            {"type": "turn_boundary", "accepted": True, "start_revision": 0, "state_revision": 1,
             "authored_finish_kind": "explicit_done"},
            {"type": "driver", "line": state1},
            {"type": "terminal", "reason": "winner", "winner": 0},
        ])
        if sidecar is not None:
            (archive / "identity.json").write_text(json.dumps(sidecar), encoding="utf-8")
        db = root / "history.sqlite"
        conn = open_history(db)
        game_id = import_game(conn, log)
        conn.close()
        return db, game_id

    def _side0(self, db, game_id, root):
        bundle = json.loads(Path(build_bundle(str(db), game_id, root / "b.json")).read_text())
        return next(p for p in bundle["metadata"]["players"] if p["side"] == 0)

    def test_sidecar_supplies_requested_identity_and_labels_it_as_requested(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db, game_id = self._game(root, {"requested": {
                "llm_player_model": "claude-haiku-4-5-20251001", "llm_side": 0,
                "seed": 7, "faction0": "undead", "faction1": "undead"}})
            player = self._side0(db, game_id, root)
            self.assertEqual(player["model_requested"], "claude-haiku-4-5-20251001")
            # Requested, never promoted to reported.
            self.assertIsNone(player["model_reported"])
            self.assertEqual(player.get("identity_evidence"), "requested sidecar")

    def test_requested_model_in_the_archive_needs_no_sidecar(self):
        """--player-model records identity into the archive itself.

        This is the path that does not depend on a side file surviving next to
        the log, and it is what the importer already reads into
        game_players.model_requested.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); archive = root / "archive"; archive.mkdir()
            log = archive / "match.ndjson"
            state0 = {"type": "state", "turn": 1, "active_faction": 0, "cols": 2, "rows": 2,
                      "terrain": [], "units": [], "state_revision": 0}
            state1 = dict(state0, active_faction=1, state_revision=1)
            _write_log(log, [
                {"type": "metadata", "faction0": "undead", "faction1": "undead", "seed": 7,
                 "llm_side": 0, "requested_model": "claude-haiku-4-5-20251001"},
                {"type": "driver", "line": state0},
                {"type": "turn_boundary", "accepted": True, "start_revision": 0,
                 "state_revision": 1, "authored_finish_kind": "explicit_done"},
                {"type": "driver", "line": state1},
                {"type": "terminal", "reason": "winner", "winner": 0},
            ])
            db = root / "history.sqlite"
            conn = open_history(db)
            game_id = import_game(conn, log)
            conn.close()
            self.assertFalse((archive / "identity.json").exists(), "no sidecar in this case")
            player = self._side0(db, game_id, root)
            self.assertEqual(player["model_requested"], "claude-haiku-4-5-20251001")
            # Recorded identity is requested, not host-attested.
            self.assertIsNone(player["model_reported"])
            self.assertNotIn("identity_evidence", player)

    def test_a_sidecar_that_contradicts_the_catalog_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db, game_id = self._game(root, {"requested": {
                "llm_player_model": "some-other-model", "llm_side": 0,
                "seed": 999, "faction0": "undead", "faction1": "undead"}})
            player = self._side0(db, game_id, root)
            self.assertIsNone(player["model_requested"],
                              "a sidecar naming a different seed must not relabel this game")

    def test_no_sidecar_leaves_identity_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db, game_id = self._game(root, None)
            player = self._side0(db, game_id, root)
            self.assertIsNone(player["model_requested"])
            self.assertNotIn("identity_evidence", player)

    def test_browser_and_replay_report_the_same_player(self):
        from .recorded_games import list_games
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db, game_id = self._game(root, {"requested": {
                "llm_player_model": "claude-haiku-4-5-20251001", "llm_side": 0,
                "seed": 7, "faction0": "undead", "faction1": "undead"}})
            from_replay = self._side0(db, game_id, root)["model_requested"]
            row = next(g for g in list_games(str(db))["games"] if g["game_id"] == game_id)
            from_browser = next(p for p in row["players"] if p["side"] == 0)["model"]
            self.assertEqual(from_replay, from_browser)


if __name__ == "__main__":
    unittest.main()
