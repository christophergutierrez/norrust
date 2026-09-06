"""Real-driver execution and prompt/catalog regressions for the player contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zlib

from .game_history import import_game, open_history

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


def annotated(agenda):
    return {"actions": [{"action": "EndTurn"}], "agenda": agenda,
            "decisions": [{"orders": [0], "rules": ["S1"],
                           "expected": "Delegate eligible routine units.",
                           "risk": "Delegated units may lose their positions."}]}


def run_client(root, response, max_turns=1):
    backend = root / "backend.py"
    backend.write_text(
        "import json,sys\n"
        "prompt=sys.stdin.read()\n"
        "assert 'BOARD_UNTRUSTED_DATA_BEGIN:' in prompt\n"
        f"print(json.dumps({{'text': {json.dumps(response)!r}}}))\n")
    log = root / "match.ndjson"
    result = subprocess.run(
        [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
         "--model-command", shlex.join([sys.executable, str(backend)]),
         "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
         "--gold", "300", "--seed", "9211", "--llm-side", "0", "--max-turns", str(max_turns),
         "--log", str(log), "--query-budget-seconds", "10", "--model-timeout", "10",
         "--turn-timeout", "30"], cwd=ROOT, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(result.stderr[-2000:] + log.read_text()[-2000:])
    return log, [json.loads(line) for line in log.read_text().splitlines()]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class PlayerContractIntegrationTests(unittest.TestCase):
    def _driver(self, *extra):
        return subprocess.Popen(
            [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
             "--faction1", "undead", "--gold", "300", "--seed", "9211",
             "--llm-side", "0", *extra],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)

    @staticmethod
    def _send(process, value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    @staticmethod
    def _until(process, kind):
        records = []
        while True:
            line = process.stdout.readline()
            if not line:
                raise AssertionError("driver EOF while waiting for " + kind)
            record = json.loads(line)
            records.append(record)
            if record.get("type") == kind:
                return record, records

    def test_real_preview_recruitment_is_read_only_and_replacement_is_submitted(self):
        """A real driver preview may differ from the only batch that commits."""
        process = self._driver("--max-turns", "1")
        try:
            initial, _ = self._until(process, "state")
            revision = initial["state_revision"]
            candidates = [
                [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 1},
                 {"action": "EndTurn"}],
                [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 2},
                 {"action": "EndTurn"}],
            ]
            query = {"action": "Query", "what": "preview_batch",
                     "state_revision": revision, "phase": "final",
                     "mode": "forecast", "candidates": candidates}
            self._send(process, query)
            first, _ = self._until(process, "status")
            self.assertTrue(first["ok"], first)
            body = first["body"]
            self.assertFalse(body["sampling"])
            self.assertEqual(body["coverage"]["forecast"], "conditional_pre_finish")
            self.assertEqual([c["summary"]["gold_after"] for c in body["candidates"]], [285, 270])
            self.assertEqual([c["summary"]["units_after"] for c in body["candidates"]], [3, 4])
            self.assertEqual(first["state_revision"], revision)

            # Repeat the read-only query: no preview branch may alter revision,
            # gold, or the authoritative roster.
            self._send(process, query)
            repeated, _ = self._until(process, "status")
            self.assertTrue(repeated["ok"], repeated)
            self.assertEqual(repeated["state_revision"], revision)
            self.assertEqual(repeated["body"], body)

            replacement = [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 2},
                           {"action": "EndTurn"}]
            self._send(process, replacement)
            terminal, records = self._until(process, "game_end")
            self.assertEqual(terminal["reason"], "max_turns")
            events = [event for record in records for event in record.get("events", [])]
            recruits = [event for event in events if event.get("kind") == "recruit"]
            self.assertEqual(len(recruits), 2)
            self.assertEqual({event["unit"] for event in recruits}, {3, 4})
            self.assertFalse(any(event.get("unit") == 5 for event in recruits))
            self.assertEqual(sum(event.get("kind") == "vacate" for event in events), 0)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_sampled_continuation_does_not_mutate_state_before_standalone_resignation(self):
        """A sampled continuation is evidence only; Resign remains immediate."""
        process = self._driver("--max-turns", "50", "--incremental-turns")
        try:
            initial, _ = self._until(process, "state")
            revision = initial["state_revision"]
            sampled = {"action": "Query", "what": "preview_batch",
                       "state_revision": revision, "phase": "final",
                       "mode": "bounded_rollout",
                       "candidates": [[{"action": "EndTurn"}]]}
            self._send(process, sampled)
            preview, preview_records = self._until(process, "status")
            self.assertTrue(preview["ok"], preview)
            body = preview["body"]
            self.assertTrue(body["sampling"])
            self.assertEqual(body["coverage"]["forecast"], "bounded_rollout")
            candidate = body["candidates"][0]
            self.assertEqual(candidate["observation_stage"], "post_opponent_response")
            self.assertTrue(candidate["post_sweep"]["sampling"])
            # Query output contains hypothetical post-sweep facts, but no
            # events/state record was committed and the revision is unchanged.
            self.assertEqual(preview["state_revision"], revision)
            self.assertFalse(any(record.get("type") == "events" for record in preview_records))

            self._send(process, [{"action": "Resign"}])
            terminal, records = self._until(process, "game_end")
            self.assertEqual(terminal["reason"], "resignation")
            self.assertEqual(terminal["winner"], 1)
            self.assertEqual(terminal["resigned_side"], 0)
            self.assertEqual(terminal["side_turns"], 0)
            self.assertEqual(terminal["state_revision"], revision)
            self.assertFalse(any(record.get("type") == "events" for record in records))
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_recruitment_validation_and_selective_finish_change_real_state(self):
        process = subprocess.Popen(
            [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
             "--gold", "300", "--seed", "9211", "--llm-side", "0", "--max-turns", "1",
             "--incremental-turns", "--turn-timeout", "10"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def send(value):
            process.stdin.write(json.dumps(value) + "\n")
            process.stdin.flush()
        def until(kind):
            records = []
            while True:
                line = process.stdout.readline()
                self.assertTrue(line, "driver EOF")
                record = json.loads(line)
                records.append(record)
                if record["type"] == kind:
                    return record, records
        def query(what, **fields):
            send({"action": "Query", "what": what, **fields})
            result, _ = until("status")
            self.assertTrue(result["ok"], result)
            return result
        try:
            initial, _ = until("state")
            recruitment = query("recruit_options")
            self.assertEqual(len(recruitment["body"]["placement_hexes"]), 6)
            cost = next(o["cost"] for o in recruitment["body"]["options"] if o["def_id"] == "Skeleton")
            surface = query("tactical_surface")
            orders = [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 12}]
            for _ in range(2):
                validation = query("validate_batch", orders=orders, state_revision=initial["state_revision"])
                self.assertTrue(validation["body"]["valid"], validation)
                self.assertEqual(validation["state_revision"], initial["state_revision"])
                self.assertEqual(query("tactical_surface"), surface)
                self.assertEqual(query("recruit_options"), recruitment)
            send(orders)
            recruited, records = until("state")
            self.assertEqual(recruited["gold"], [initial["gold"][0] - 12 * cost, initial["gold"][1]])
            friendly = [u for u in recruited["units"] if u["faction"] == 0]
            self.assertEqual(len(friendly), 13)
            self.assertEqual(sum(u["def_id"] == "Skeleton" for u in friendly), 12)
            events = [e for r in records for e in r.get("events", [])]
            self.assertEqual(sum(e["kind"] == "recruit" for e in events), 12)
            self.assertEqual(sum(e["kind"] == "vacate" for e in events), 6)
            eligible = [u for u in friendly if not u["can_recruit"] and not u["moved"] and not u["attacked"]]
            self.assertGreaterEqual(len(eligible), 3)
            held, delegated, omitted = eligible[:3]
            send([{"action": "FinishWithGreedy", "groups": [{"mode": "greedy", "unit_ids": [delegated["id"]]}],
                   "holds": [{"unit_id": held["id"], "reason": "preserve screen"}]}])
            terminal, records = until("game_end")
            self.assertEqual(terminal["reason"], "max_turns")
            events = [e for r in records for e in r.get("events", [])]
            moves = [e for e in events if e["kind"] in {"move", "vacate"}]
            self.assertTrue(any(e["unit"] == delegated["id"] for e in moves))
            self.assertFalse(any(e["unit"] in {held["id"], omitted["id"]} for e in moves))
            # At cap 1 the opponent never acts. Replay the actual moves to
            # establish the held/omitted positions at the model finish.
            positions = {u["id"]: (u["col"], u["row"]) for u in friendly}
            for move in moves:
                positions[move["unit"]] = (move["to"]["col"], move["to"]["row"])
            self.assertEqual(positions[held["id"]], (held["col"], held["row"]))
            self.assertEqual(positions[omitted["id"]], (omitted["col"], omitted["row"]))
            self.assertNotEqual(positions[delegated["id"]], (delegated["col"], delegated["row"]))
            self.assertFalse(any(e.get("faction") == 1 and e["kind"] == "recruit" for e in events))
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()

    def test_malformed_agenda_does_not_add_repair_calls(self):
        valid = {"tasks": [], "holds": []}
        for malformed in ([], {"tasks": [{"id": "x", "goal": "keep", "units": [], "status": []}], "holds": []},
                          {"tasks": [{"id": "\ud800", "goal": "keep", "units": [], "status": "active"}], "holds": []}):
            with self.subTest(agenda=malformed), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                (root / "valid").mkdir(); (root / "invalid").mkdir()
                _, baseline = run_client(root / "valid", annotated(valid))
                _, records = run_client(root / "invalid", annotated(malformed))
                self.assertTrue(any(r["type"] == "agenda_error" for r in records))
                self.assertFalse(any(r["type"] == "agenda_update" for r in records))
                self.assertFalse(any("repair" in r["type"] for r in records))
                self.assertEqual(sum(r["type"] == "model_request" for r in records),
                                 sum(r["type"] == "model_request" for r in baseline))
                batches = [r for r in records if r["type"] == "forwarded_orders"]
                self.assertEqual(len(batches), 1)
                self.assertEqual(batches[0]["orders"], annotated(valid)["actions"])
                self.assertEqual(batches[0]["decision_annotation"]["status"], "valid")

    def test_accepted_agenda_reaches_next_prompt_and_idempotent_catalog(self):
        agenda = {"tasks": [{"id": "keep_watch", "goal": "Maintain watch", "units": [1], "status": "active"}], "holds": [1]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log, records = run_client(root, annotated(agenda), max_turns=3)
            updates = [r for r in records if r["type"] == "agenda_update"]
            self.assertTrue(updates)
            self.assertEqual(updates[0]["agenda"], agenda)
            requests = [r for r in records if r["type"] == "model_request" and r["status"] == "completed"]
            boards = [json.loads(r["prompt"].split("BOARD_UNTRUSTED_DATA_BEGIN:\n", 1)[1].split("\nBOARD_UNTRUSTED_DATA_END", 1)[0]) for r in requests]
            self.assertNotIn("agenda", boards[0])
            # Strictly later revision excludes an initial draft review echo.
            next_turn = [board for r, board in zip(requests, boards) if r["state_revision"] > requests[0]["state_revision"]]
            self.assertTrue(next_turn)
            self.assertEqual(next_turn[0]["agenda"], {"tasks": agenda["tasks"], "holds": []})
            conn = open_history(root / "history.sqlite")
            conn.row_factory = sqlite3.Row
            try:
                game_id = import_game(conn, log)
                for r in requests:
                    stored = conn.execute("SELECT * FROM model_requests WHERE request_id=?", (r["request_id"],)).fetchone()
                    self.assertEqual(zlib.decompress(stored["prompt_blob"]).decode(), r["prompt"])
                    self.assertEqual(zlib.decompress(stored["response_blob"]).decode(), r["raw_output"])
                    self.assertEqual(stored["prompt_hash"], hashlib.sha256(r["prompt"].encode()).hexdigest())
                    self.assertEqual(stored["response_hash"], hashlib.sha256(r["raw_output"].encode()).hexdigest())
                    self.assertEqual(stored["prompt_bytes"], len(r["prompt"].encode()))
                    self.assertEqual(stored["response_bytes"], len(r["raw_output"].encode()))
                    self.assertEqual(stored["annotation_status"], r["decision_annotation"]["status"])
                    self.assertEqual(json.loads(zlib.decompress(stored["reasoning_blob"])), r["decision_annotation"])
                for r in (r for r in records if r["type"] == "forwarded_orders"):
                    batch = conn.execute("SELECT * FROM action_batches WHERE request_id=?", (r["request_id"],)).fetchone()
                    self.assertEqual(batch["before_revision"], r["state_revision"])
                    self.assertEqual(json.loads(batch["submitted_orders_json"]), r["orders"])
                    self.assertEqual([a[0] for a in conn.execute("SELECT request_id FROM actions WHERE batch_id=?", (batch["batch_id"],))], [r["request_id"]])
                tables = ("games", "game_players", "side_turns", "model_requests",
                          "action_batches", "actions")
                before = {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in tables}
                for _ in range(2):
                    import_game(conn, log, game_id=game_id)
                    self.assertEqual(before, {t: conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in tables})
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()
