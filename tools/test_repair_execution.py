"""Real-driver repair regression from the frozen seed 2002 revision-338 boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
import zlib

from .game_history import import_game, open_history

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
FIXTURE = ROOT / "tools/fixtures/decision_positions/revision-338"
SEED_2001_FIXTURE = ROOT / "tools/fixtures/decision_positions/revision-286"


def _checkpoint(temp: Path) -> Path:
    body = json.loads((FIXTURE / "checkpoint.json").read_text(encoding="utf-8"))
    board = ROOT / "scenarios" / body["scenario"] / "board.toml"
    assert hashlib.sha256(board.read_bytes()).hexdigest() == body["board_sha256"]
    body["board_path"] = str(board)
    body["save_state"]["board_path"] = str(board)
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = temp / f"{body['side_turns']}-{body['save_state']['state_revision']}-{body['boundary']}-{digest}.json"
    path.write_bytes(encoded)
    return path


def _backend(path: Path, invalid: str, captures: Path) -> None:
    corrected = {
        "actions": [
            {"action": "Attack", "attacker_id": 7, "defender_id": 24},
            {"action": "FinishWithGreedy", "groups": [], "holds": []},
        ],
        "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                       "expected": "Attack the supplied adjacent target, then finish without delegation.",
                       "risk": "The attack may leave U7 exposed to retaliation."}],
    }
    path.write_text(
        "import json,sys\n"
        "prompt=sys.stdin.read()\n"
        f"capture={str(captures)!r}\n"
        "with open(capture, 'a', encoding='utf-8') as out: out.write(json.dumps({'prompt':prompt})+'\\n')\n"
        f"count=sum(1 for _ in open(capture, encoding='utf-8'))\n"
        f"response={invalid!r} if count == 1 else {json.dumps(corrected, ensure_ascii=False)!r}\n"
        "print(json.dumps({'text':response}))\n",
        encoding="utf-8",
    )


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class RepairExecutionIntegrationTests(unittest.TestCase):
    def test_real_driver_recovers_unfenced_inspection_rationale_before_action(self):
        """Strict execution rejects rationale, while repair preserves lookup capability."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            malformed = '{"tool":"inspect_units","unit_ids":[7]} I inspected the unit.'
            corrected = '{"tool":"inspect_units","unit_ids":[7]}'
            action = '[{"action":"EndTurn"}]'
            backend.write_text(
                "import json,sys\n"
                f"capture={str(captures)!r}\n"
                "prompt=sys.stdin.read()\n"
                "with open(capture,'a',encoding='utf-8') as f: f.write(json.dumps({'prompt':prompt})+'\\n')\n"
                "n=sum(1 for _ in open(capture,encoding='utf-8'))\n"
                f"reply={malformed!r} if n==1 else ({corrected!r} if n==2 else {action!r})\n"
                "print(json.dumps({'text':reply}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client",
                       "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--incremental-turns", "--decision-mode", "focused", "--log", str(log),
                       "--resume-checkpoint", str(checkpoint), "--query-budget-seconds", "10",
                       "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:] + log.read_text()[-4000:])
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual([r["raw_output"] for r in requests[:3]], [malformed, corrected, action])
            self.assertIn("not valid JSON", requests[1]["prompt"])
            self.assertIn("pending inspect_units operation", requests[1]["prompt"])
            tool_results = [r for r in records if r.get("type") == "tool_result"]
            self.assertEqual(len(tool_results), 1)
            self.assertEqual(tool_results[0]["request"], {"tool": "inspect_units", "unit_ids": [7]})
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(forwarded[0]["orders"], [{"action": "EndTurn"}])

    def test_real_driver_samples_casualty_once_then_confirms_and_imports_review(self):
        """A sampled casualty drives one review without an extra warning query."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            draft = json.dumps({
                "actions": [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
                "decisions": [{"orders": [0], "rules": ["T7"],
                               "expected": "Finish after the current position.",
                               "risk": "The sampled opponent response may remove a unit."}],
            })
            backend.write_text(
                "import json,sys\n"
                f"capture={str(captures)!r}\n"
                "prompt=sys.stdin.read()\n"
                "with open(capture,'a',encoding='utf-8') as f: f.write(json.dumps({'prompt':prompt})+'\\n')\n"
                f"print(json.dumps({{'text':{draft!r}}}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client",
                       "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--incremental-turns", "--decision-mode", "focused", "--log", str(log),
                       "--resume-checkpoint", str(checkpoint), "--query-budget-seconds", "10",
                       "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:] + log.read_text()[-4000:])
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            reviews = [r for r in records if r.get("type") == "draft_review"]
            self.assertEqual(len(requests), 2, "draft plus exactly one client review call")
            self.assertEqual(len(reviews), 1)
            self.assertIn("SAMPLED_TRANSITION candidate_index=1 friendly_side=0 originating_revision=338 interval=own_finish_to_opponent_response status=known",
                          requests[1]["prompt"])
            review_body = reviews[0]["body"]
            self.assertEqual(review_body["state_revision"], 338)
            self.assertTrue(review_body["candidates"][1]["valid"])
            self.assertIsNone(review_body["candidates"][1]["exposure"])
            self.assertNotEqual(review_body["candidates"][1]["post_sweep"]["stages"]["post_finish"]["state_revision"], 338)
            self.assertIn("SAMPLED_FRIENDLY_CASUALTIES side=0 candidate_index=1 originating_revision=338 interval=own_finish_to_opponent_response status=known casualty_ids=U19", requests[1]["prompt"])
            self.assertEqual(reviews[0]["handoff_audit"].get("trigger_reasons"), [])
            self.assertIn("SIMULATION", requests[1]["prompt"])
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 1)
            self.assertEqual(forwarded[0]["state_revision"], 338)
            self.assertEqual(forwarded[0]["orders"], json.loads(draft)["actions"])
            terminal = next(r for r in records if r.get("type") == "terminal")
            # The automatic warning's bounded preview is internal to the
            # handoff record, so it does not emit a player tool-result event.
            # Pin the query sequence for this fixture: tactical surface, one
            # bounded preview, and final validation only.
            self.assertEqual([r["line"].get("what") for r in records if r.get("type") == "query"],
                             ["tactical_surface", "preview_batch", "validate_batch"])
            self.assertEqual(terminal["queries"], 3)
            self.assertEqual(terminal["draft_reviews"], 1)
            self.assertEqual(terminal["draft_confirmations"], 1)
            self.assertEqual(terminal["draft_revisions"], 0)

            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                coverage = json.loads(conn.execute(
                    "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
                self.assertEqual(coverage["review_coverage"]["raw"], 1)
                self.assertEqual(coverage["review_coverage"]["linked"], 1)
                self.assertEqual(coverage["review_coverage"]["raw_decisions"][0]["identity_status"], "linked")
                counts = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM model_requests WHERE game_id=?), "
                    "(SELECT COUNT(*) FROM action_batches WHERE game_id=?), "
                    "(SELECT COUNT(*) FROM side_turns WHERE game_id=?)",
                    (game_id, game_id, game_id)).fetchone()
                import_game(conn, log, game_id=game_id)
                coverage_again = json.loads(conn.execute(
                    "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
                counts_again = conn.execute(
                    "SELECT (SELECT COUNT(*) FROM model_requests WHERE game_id=?), "
                    "(SELECT COUNT(*) FROM action_batches WHERE game_id=?), "
                    "(SELECT COUNT(*) FROM side_turns WHERE game_id=?)",
                    (game_id, game_id, game_id)).fetchone()
                self.assertEqual(coverage_again["review_coverage"], coverage["review_coverage"])
                self.assertEqual(counts_again, counts)
            finally:
                conn.close()

    def test_real_driver_samples_casualty_then_replaces_from_original_revision(self):
        """A changed review response validates and forwards at the live revision."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            draft = json.dumps({
                "actions": [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
                "decisions": [{"orders": [0], "rules": ["T7"],
                               "expected": "Finish after the current position.",
                               "risk": "The sampled opponent response may remove a unit."}],
            })
            replacement = json.dumps({
                "actions": [{"action": "DoneWithImportantMoves"}],
                "decisions": [{"orders": [0], "rules": ["T7"],
                               "expected": "Stop after the important moves.",
                               "risk": "The remaining units wait for the next turn."}],
            })
            backend.write_text(
                "import json,sys\n"
                f"capture={str(captures)!r}\n"
                "prompt=sys.stdin.read()\n"
                "with open(capture,'a',encoding='utf-8') as f: f.write(json.dumps({'prompt':prompt})+'\\n')\n"
                "n=sum(1 for _ in open(capture,encoding='utf-8'))\n"
                f"reply={draft!r} if n == 1 else {replacement!r}\n"
                "print(json.dumps({'text':reply}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client",
                       "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--incremental-turns", "--decision-mode", "focused", "--log", str(log),
                       "--resume-checkpoint", str(checkpoint), "--query-budget-seconds", "10",
                       "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:] + log.read_text()[-4000:])
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual([r["raw_output"] for r in requests], [draft, replacement])
            reviews = [r for r in records if r.get("type") == "draft_review"]
            self.assertEqual(len(reviews), 1)
            decision = next(r for r in records if r.get("type") == "draft_review_decision")
            self.assertEqual(decision["outcome"], "revised")
            self.assertEqual(decision["revision"], 1)
            forwarded_records = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded_records), 1)
            forwarded = forwarded_records[0]
            self.assertEqual(forwarded["orders"], json.loads(replacement)["actions"])
            self.assertEqual(forwarded["state_revision"], 338)
            self.assertEqual(forwarded["request_id"], requests[1]["request_id"])
            self.assertEqual([r["line"].get("what") for r in records if r.get("type") == "query"],
                             ["tactical_surface", "preview_batch", "validate_batch"])
            terminal = next(r for r in records if r.get("type") == "terminal")
            self.assertEqual(terminal["draft_revisions"], 1)
            self.assertEqual(terminal["draft_confirmations"], 0)
            self.assertNotEqual(reviews[0]["body"]["candidates"][1]["post_sweep"]["stages"]["post_finish"]["state_revision"],
                                forwarded["state_revision"])
            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                coverage = json.loads(conn.execute(
                    "SELECT coverage_json FROM games WHERE game_id=?", (game_id,)).fetchone()[0])
                self.assertEqual(coverage["review_coverage"]["linked"], 1)
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM action_batches WHERE game_id=?", (game_id,)).fetchone()[0], 1)
                self.assertEqual(conn.execute(
                    "SELECT COUNT(*) FROM model_requests WHERE game_id=?", (game_id,)).fetchone()[0], 2)
            finally:
                conn.close()

    def test_real_driver_repairs_bare_preview_then_executes_partial_combat(self):
        """Tool metadata errors keep the comparison alive through its result."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            malformed = json.dumps({
                "tool": "preview_batch",
                "candidates": [[{"action": "Attack", "attacker_id": 7, "defender_id": 24},
                                {"action": "EndTurn"}]],
                "decisions": [], "intent": "compare before acting",
            })
            corrected = json.dumps({
                "tool": "preview_batch",
                "candidates": [[{"action": "Attack", "attacker_id": 7, "defender_id": 24},
                                {"action": "EndTurn"}]],
            })
            partial = json.dumps({
                "actions": [{"action": "Attack", "attacker_id": 7, "defender_id": 24}],
                "decisions": [{"orders": [0], "rules": ["T3.3"],
                               "expected": "Commit the inspected attack.",
                               "risk": "The target may survive retaliation."}],
            })
            finish = json.dumps({
                "actions": [{"action": "DoneWithImportantMoves"}],
                "decisions": [{"orders": [0], "rules": ["T7"],
                               "expected": "Finish after the engagement result.",
                               "risk": "Routine units may reposition."}],
            })
            backend.write_text(
                "import json,sys\n"
                f"capture={str(captures)!r}\n"
                "prompt=sys.stdin.read()\n"
                "with open(capture,'a',encoding='utf-8') as f: f.write(json.dumps({'prompt':prompt})+'\\n')\n"
                "n=sum(1 for _ in open(capture,encoding='utf-8'))\n"
                f"reply={malformed!r} if n==1 else ({corrected!r} if n==2 else ({partial!r} if n==3 else {finish!r}))\n"
                "print(json.dumps({'text':reply}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client",
                       "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--incremental-turns", "--decision-mode", "focused", "--log", str(log),
                       "--resume-checkpoint", str(checkpoint), "--query-budget-seconds", "10",
                       "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-4000:] + log.read_text()[-4000:])
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual([r["raw_output"] for r in requests[:4]], [malformed, corrected, partial, finish])
            self.assertIn("unknown key(s): decisions", requests[1]["prompt"])
            self.assertIn("bare JSON tool request", requests[1]["prompt"])
            self.assertIn('"tool":"preview_batch"', requests[2]["prompt"])
            previews = [r for r in records if r.get("type") == "batch_preview"]
            self.assertEqual(len(previews), 1)
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(forwarded[0]["orders"], json.loads(partial)["actions"])
            self.assertEqual(forwarded[-1]["orders"], json.loads(finish)["actions"])
            events = [e for r in records if r.get("type") == "driver"
                      for e in r.get("line", {}).get("events", [])]
            self.assertTrue(any(e.get("kind") == "attack" and
                                e.get("attacker", {}).get("unit") == 7 and
                                e.get("defender", {}).get("unit") == 24 for e in events))

    def test_revision_338_repair_aggregates_errors_and_executes_corrected_batch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            invalid = (FIXTURE / "failed-response.json").read_text(encoding="utf-8").strip()
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            _backend(backend, invalid, captures)
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--log", str(log), "--resume-checkpoint", str(checkpoint),
                       "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual(len(requests), 3, "initial response, one repair, and existing draft review")
            self.assertEqual(requests[0]["raw_output"], invalid)
            self.assertEqual(requests[1]["state_revision"], 338)
            self.assertEqual(requests[0]["state_revision"], 338)
            self.assertEqual(requests[0]["prompt_hash"], hashlib.sha256(requests[0]["prompt"].encode()).hexdigest())
            self.assertIn("actions[3].holds[3].unit_id", requests[1]["prompt"])
            self.assertIn("actions[3].groups[0].unit_ids[4]", requests[1]["prompt"])
            self.assertIn("actions[3].holds[7].reason: 121 characters; maximum 120", requests[1]["prompt"])
            self.assertEqual(requests[1]["raw_output"], json.dumps({
                "actions": [{"action": "Attack", "attacker_id": 7, "defender_id": 24},
                             {"action": "FinishWithGreedy", "groups": [], "holds": []}],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack the supplied adjacent target, then finish without delegation.",
                               "risk": "The attack may leave U7 exposed to retaliation."}],
            }, ensure_ascii=False))
            self.assertEqual(requests[2]["raw_output"], requests[1]["raw_output"])
            self.assertEqual(len([r for r in records if r.get("type") == "repair"]), 1)
            forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
            self.assertEqual(forwarded["request_id"], requests[2]["request_id"])
            self.assertEqual(forwarded["state_revision"], 338)
            self.assertEqual(forwarded["orders"], json.loads(json.dumps({
                "actions": [{"action": "Attack", "attacker_id": 7, "defender_id": 24},
                             {"action": "FinishWithGreedy", "groups": [], "holds": []}]}))["actions"])
            initial = next(r["line"] for r in records if r.get("type") == "driver"
                           and r["line"].get("type") == "state")
            self.assertEqual(initial["state_revision"], 338)
            post = next(r for r in records if r.get("type") == "checkpoint_ref" and r.get("boundary") == "postbatch")
            post_state = json.loads((log.with_suffix(".ckpt") / post["path"]).read_text())
            self.assertEqual(post_state["save_state"]["state_revision"], 340)
            self.assertEqual(post_state["side_turns"], 15)
            events = [e for r in records if r.get("type") == "driver"
                      for e in r.get("line", {}).get("events", [])]
            self.assertTrue(any(e.get("kind") == "attack" and e.get("attacker", {}).get("unit") == 7
                                and e.get("defender", {}).get("unit") == 24 for e in events))
            self.assertEqual(forwarded["orders"][-1]["action"], "FinishWithGreedy")
            self.assertFalse(any(r.get("type") == "forwarded_orders" and r.get("request_id") == requests[0]["request_id"]
                                 for r in records))
            self.assertEqual(len([r for r in records if r.get("type") == "model_request"]), 3)

            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                stored = conn.execute("SELECT prompt_blob,response_blob,prompt_hash,response_hash,state_revision FROM model_requests WHERE request_id=?",
                                      (requests[2]["request_id"],)).fetchone()
                self.assertEqual(zlib.decompress(stored[0]).decode(), requests[2]["prompt"])
                self.assertEqual(zlib.decompress(stored[1]).decode(), requests[2]["raw_output"])
                self.assertEqual(stored[2], hashlib.sha256(requests[2]["prompt"].encode()).hexdigest())
                self.assertEqual(stored[3], hashlib.sha256(requests[2]["raw_output"].encode()).hexdigest())
                self.assertEqual(stored[4], 338)
                batch = conn.execute("SELECT request_id,before_revision,after_revision,submitted_orders_json FROM action_batches WHERE game_id=?",
                                     (game_id,)).fetchone()
                self.assertEqual(batch[0], requests[2]["request_id"])
                self.assertEqual(batch[1], 338)
                self.assertIsNone(batch[2])
                self.assertEqual(json.loads(batch[3]), forwarded["orders"])
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()

    def test_engine_validation_repair_can_inspect_units_before_corrected_batch(self):
        """(Stack 4) The pre-submission engine-validation repair loop can use
        `inspect_units` -- the same friendly group-inspection tool the normal
        path uses -- without resetting budgets or silently ending play.

        This exercises the player-facing group tool inside the
        `validate_before_submit` repair loop.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            # Schema-valid but engine-illegal: U18 (12,8) and U44 (15,4) are not adjacent.
            not_adjacent = json.dumps({
                "actions": [
                    {"action": "Attack", "attacker_id": 18, "defender_id": 44},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack a distant enemy and finish without delegation.",
                               "risk": "The attacker is not adjacent; this is expected to be rejected."}],
            })
            inspect_units_request = json.dumps({"tool": "inspect_units", "unit_ids": [1, 3, 4, 5, 6, 7, 8, 10]})
            corrected = json.dumps({
                "actions": [
                    {"action": "Attack", "attacker_id": 7, "defender_id": 24},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack the supplied adjacent target, then finish without delegation.",
                               "risk": "The attack may leave U7 exposed to retaliation."}],
            })
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "count = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                f"if count == 1:\n"
                f"    resp = {not_adjacent!r}\n"
                f"elif count == 2:\n"
                f"    resp = {inspect_units_request!r}\n"
                f"else:\n"
                f"    resp = {corrected!r}\n"
                "print(json.dumps({'text': resp}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--log", str(log), "--resume-checkpoint", str(checkpoint),
                       # Fanning out eight `inspect_unit` driver queries on this
                       # 28-unit board costs several seconds each; the query
                       # budget and turn timeout must both be raised well above
                       # a single-inspection turn's defaults, or the driver
                       # subprocess is killed for exceeding --turn-timeout
                       # mid-fan-out (a broken pipe, not a validation failure).
                       "--query-budget-seconds", "60", "--model-timeout", "10", "--turn-timeout", "120"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=150)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

            # The first (engine-illegal) submission was rejected, never forwarded.
            validations = [r for r in records if r.get("type") == "batch_validation"]
            self.assertTrue(any(v.get("valid") is False for v in validations))
            self.assertTrue(any(v.get("valid") is True for v in validations))

            # Exactly one player tool allowance was spent inspecting all eight
            # units, from inside the repair loop -- the same accounting as the
            # normal path, no separate/reset budget.
            terminal = next(r for r in records if r.get("type") == "terminal")
            self.assertEqual(terminal.get("tool_calls_by_name", {}).get("inspect_units"), 1)

            # Pin the accounting asymmetry: fanning out to eight units costs
            # eight underlying driver queries (real query time, each one on
            # this 28-unit board expensive enough to need the widened budget
            # above) even though it only ever charges the ONE player tool
            # allowance asserted above. A player planning against a tight
            # turn/query budget must not assume one tool call is one unit of
            # driver work.
            inspect_unit_queries = [
                r for r in records if r.get("type") == "query"
                and isinstance(r.get("line", {}).get("body"), dict)
                and "destination_threats" in r["line"]["body"]
            ]
            self.assertEqual(len(inspect_unit_queries), 8)

            # The repair loop kept running (it did not silently end play) and
            # the corrected batch is what actually committed.
            repairs = [r for r in records if r.get("type") == "action_repair"]
            self.assertGreaterEqual(len(repairs), 2)
            forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
            self.assertEqual(forwarded["orders"], json.loads(corrected)["actions"])
            events = [e for r in records if r.get("type") == "driver"
                      for e in r.get("line", {}).get("events", [])]
            self.assertTrue(any(e.get("kind") == "attack" and e.get("attacker", {}).get("unit") == 7
                                and e.get("defender", {}).get("unit") == 24 for e in events))
            self.assertFalse(any(e.get("attacker", {}).get("unit") == 18 for e in events))

    def test_pre_submit_repair_surfaces_rejected_units_own_legal_destinations(self):
        """(Stack A) A pre-submit rejection naming a unit that was already
        inspected this turn gets that unit's own revision-pinned legal
        destinations echoed back in the repair prompt, honestly labeled
        direct/open threat scope. This reproduces the shape of the archived
        revision-314 Grunt U11 case: the model is given its own unit's real
        legal options instead of only the bare rejection.

        The same flow also exercises the two explicit "unavailable" markers:
        a rejection naming a unit that was never inspected this turn, and a
        rejection (an unparseable repair reply) that names no unit at all.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            # Step 1: schema-valid but engine-illegal (U18/U44 not adjacent).
            # No unit has been inspected yet, so the repair for this rejection
            # must say so explicitly rather than omitting the block.
            not_adjacent = json.dumps({
                "actions": [
                    {"action": "Attack", "attacker_id": 18, "defender_id": 44},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack a distant enemy and finish without delegation.",
                               "risk": "The attacker is not adjacent; this is expected to be rejected."}],
            })
            # Step 2: an unparseable repair reply names no unit at all.
            unparseable = "not json at all, no tool, no actions"
            # Step 3: inspect the friendly group including U7 -- this is the
            # existing player-facing group tool, spent inside the repair loop.
            inspect_units_request = json.dumps({"tool": "inspect_units", "unit_ids": [1, 3, 4, 5, 6, 7, 8, 10]})
            # Step 4: a new engine-illegal batch naming U7 (nonexistent
            # defender). U7 was just inspected in step 3 at the same
            # (unchanged) revision, so its real destinations must be echoed.
            illegal_attack_by_7 = json.dumps({
                "actions": [
                    {"action": "Attack", "attacker_id": 7, "defender_id": 999},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack a nonexistent defender.",
                               "risk": "none; expected to be rejected."}],
            })
            corrected = json.dumps({
                "actions": [
                    {"action": "Attack", "attacker_id": 7, "defender_id": 24},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack the supplied adjacent target, then finish without delegation.",
                               "risk": "The attack may leave U7 exposed to retaliation."}],
            })
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "count = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                f"if count == 1:\n"
                f"    resp = {not_adjacent!r}\n"
                f"elif count == 2:\n"
                f"    resp = {unparseable!r}\n"
                f"elif count == 3:\n"
                f"    resp = {inspect_units_request!r}\n"
                f"elif count == 4:\n"
                f"    resp = {illegal_attack_by_7!r}\n"
                f"else:\n"
                f"    resp = {corrected!r}\n"
                "print(json.dumps({'text': resp}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--log", str(log), "--resume-checkpoint", str(checkpoint),
                       "--query-budget-seconds", "60", "--model-timeout", "10", "--turn-timeout", "120"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=150)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual(
                [r["raw_output"] for r in requests],
                [not_adjacent, unparseable, inspect_units_request, illegal_attack_by_7, corrected])

            # Step 1's rejection named U18, never inspected: explicit marker.
            self.assertIn(
                "REJECTED_UNIT_LEGAL_DESTINATIONS unavailable unit=18 reason=no_inspection_result_in_scope",
                requests[1]["prompt"])
            # Step 2's unparseable reply names no unit: the other explicit marker.
            self.assertIn(
                "REJECTED_UNIT_LEGAL_DESTINATIONS unavailable reason=no_unit_identified_in_rejection",
                requests[2]["prompt"])
            # Step 4's rejection named U7, inspected in step 3 at the same
            # (unchanged) revision 338: its real legal destinations are
            # echoed, direct/open threat scope named honestly, no safety claim.
            destinations_prompt = requests[4]["prompt"]
            self.assertIn("REJECTED_UNIT_LEGAL_DESTINATIONS unit=7 state_revision=338", destinations_prompt)
            self.assertIn("zero_direct_attackers_is_not_a_safety_guarantee", destinations_prompt)
            self.assertIn("open_bound_removes_blockers_and_zoc", destinations_prompt)
            self.assertNotIn("REJECTED_UNIT_LEGAL_DESTINATIONS unavailable unit=7", destinations_prompt)
            self.assertRegex(destinations_prompt, r"REJECTED_UNIT_LEGAL_DESTINATIONS[^\n]*\n[^\n]*direct_attackers=")

            # The corrected batch still committed; the repair loop kept
            # running through the unparseable reply and the tool call.
            forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
            self.assertEqual(forwarded["orders"], json.loads(corrected)["actions"])
            events = [e for r in records if r.get("type") == "driver"
                      for e in r.get("line", {}).get("events", [])]
            self.assertTrue(any(e.get("kind") == "attack" and e.get("attacker", {}).get("unit") == 7
                                and e.get("defender", {}).get("unit") == 24 for e in events))

    def test_revision_286_invalid_preview_draft_is_repaired_and_executes(self):
        """The archived dead-U21 preview is model-invalid feedback, not infra."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = root / "checkpoint.json"
            body = json.loads((SEED_2001_FIXTURE / "checkpoint.json").read_text())
            board = ROOT / "scenarios" / body["scenario"] / "board.toml"
            self.assertEqual(hashlib.sha256(board.read_bytes()).hexdigest(), body["board_sha256"])
            body["board_path"] = str(board)
            body["save_state"]["board_path"] = str(board)
            checkpoint_payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            checkpoint = root / (
                f"{body['side_turns']}-{body['save_state']['state_revision']}-"
                f"{body['boundary']}-{hashlib.sha256(checkpoint_payload).hexdigest()}.json")
            checkpoint.write_bytes(checkpoint_payload)
            failed = json.loads((SEED_2001_FIXTURE / "failed-response.json").read_text())
            preview = json.dumps({"tool": "preview_batch", "candidates": [
                [{"action": "EndTurn"}], failed["actions"]
            ]}, separators=(",", ":"))
            corrected = json.dumps({
                "actions": [{"action": "Move", "unit_id": 22, "col": 10, "row": 5},
                            {"action": "EndTurn"}],
                "decisions": [{"orders": [0, 1], "rules": ["T3.2", "T7"],
                               "expected": "Move the wounded unit to the supplied rear hex, then finish.",
                               "risk": "The retreat gives up one attack opportunity."}],
            }, separators=(",", ":"))
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            backend.write_text(
                "import json,sys\n"
                "prompt=sys.stdin.read()\n"
                f"capture={str(captures)!r}\n"
                "try: count=sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "except FileNotFoundError: count=0\n"
                "with open(capture, 'a', encoding='utf-8') as out: out.write(json.dumps({'prompt':prompt})+'\\n')\n"
                f"reply={preview!r} if count == 0 else {corrected!r}\n"
                "print(json.dumps({'text':reply}))\n",
                encoding="utf-8")
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2001", "--llm-side", "0", "--max-turns", "11",
                       "--log", str(log), "--resume-checkpoint", str(checkpoint),
                       "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual(len(requests), 3)
            self.assertEqual(requests[0]["raw_output"], preview)
            self.assertIn("unauthorized_unit", requests[1]["prompt"])
            self.assertIn("revision=286", requests[1]["prompt"])
            self.assertIn('"unit_ids":[4,5,6,12,13,14,21,44]', requests[1]["prompt"])
            self.assertEqual(requests[2]["raw_output"], corrected)
            error = next(r for r in records if r.get("type") == "repair")
            self.assertEqual(error["validation_error"].split(":", 2)[0], "candidate_error")
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            corrected_orders = json.loads(corrected)["actions"]
            self.assertTrue(any(r["orders"] == corrected_orders for r in forwarded))
            events = [e for r in records if r.get("type") == "driver"
                      for e in r.get("line", {}).get("events", [])]
            self.assertTrue(any(e.get("kind") == "move" and e.get("unit") == 22
                                and e.get("source") == "llm" for e in events))
            self.assertFalse(any(e.get("unit") == 21 for e in events))
            terminal = next(r for r in records if r.get("type") == "terminal")
            self.assertEqual(terminal["reason"], "max_turns")
            self.assertEqual(terminal["side_turns"], 11)

    def test_candidate_a_error_a_then_candidate_b_error_b_then_candidate_c_executes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = _checkpoint(root)
            invalid_a = (FIXTURE / "failed-response.json").read_text(encoding="utf-8").strip()
            # Candidate B has a different error: attacking nonexistent defender 999
            invalid_b = json.dumps({
                "actions": [
                    {"action": "Attack", "attacker_id": 7, "defender_id": 999},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack invalid defender.",
                               "risk": "none"}],
            })
            # Candidate C is legal and wrapped in prose + code fence
            legal_c_body = {
                "actions": [
                    {"action": "Attack", "attacker_id": 7, "defender_id": 24},
                    {"action": "FinishWithGreedy", "groups": [], "holds": []},
                ],
                "decisions": [{"orders": [0, 1], "rules": ["T3.3", "T7"],
                               "expected": "Attack the supplied adjacent target, then finish without delegation.",
                               "risk": "The attack may leave U7 exposed to retaliation."}],
            }
            legal_c_text = (
                "Here is the plan for turn 15:\n```json\n"
                + json.dumps(legal_c_body, indent=2)
                + "\n```\nExecuting now."
            )
            captures = root / "requests.ndjson"
            backend = root / "backend.py"
            backend.write_text(
                "import json,sys\n"
                "prompt=sys.stdin.read()\n"
                f"capture={str(captures)!r}\n"
                "with open(capture, 'a', encoding='utf-8') as out: out.write(json.dumps({'prompt':prompt})+'\\n')\n"
                "count=sum(1 for _ in open(capture, encoding='utf-8'))\n"
                f"if count == 1:\n"
                f"    resp = {invalid_a!r}\n"
                f"elif count == 2:\n"
                f"    resp = {invalid_b!r}\n"
                f"else:\n"
                f"    resp = {legal_c_text!r}\n"
                "print(json.dumps({'text': resp}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                       "--log", str(log), "--resume-checkpoint", str(checkpoint),
                       "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])

            # 1. Verify captured prompts
            captured = [json.loads(line) for line in captures.read_text().splitlines()]
            self.assertGreaterEqual(len(captured), 3)
            prompt_repair_1 = captured[1]["prompt"]
            prompt_repair_2 = captured[2]["prompt"]

            # Prompt repair 1 contains candidate A error A
            self.assertIn("actions[3].holds[3].unit_id", prompt_repair_1)
            self.assertIn("MODEL_RESPONSE_UNTRUSTED_DATA_BEGIN", prompt_repair_1)

            # Prompt repair 2 contains candidate B error B, NOT candidate A
            self.assertIn("DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN", prompt_repair_2)
            self.assertIn('"defender_id":999', prompt_repair_2.replace(" ", ""))
            self.assertNotIn("actions[3].holds[3].unit_id", prompt_repair_2)
            self.assertIn("ENGINE_ACTION_ERROR", prompt_repair_2)

            # 2. Verify driver execution: committed C exactly once
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 1)
            self.assertEqual(forwarded[0]["orders"], legal_c_body["actions"])

            # Events: attack 7 -> 24 executed
            events = [e for r in records if r.get("type") == "driver"
                      for e in r.get("line", {}).get("events", [])]
            self.assertTrue(any(e.get("kind") == "attack" and e.get("attacker", {}).get("unit") == 7
                                and e.get("defender", {}).get("unit") == 24 for e in events))
            # No phantom events from A or B
            self.assertFalse(any(e.get("defender", {}).get("unit") == 999 for e in events))

            # 3. Post-batch checkpoint and restart verification
            post = next(r for r in records if r.get("type") == "checkpoint_ref" and r.get("boundary") == "postbatch")
            post_ckpt_path = log.with_suffix(".ckpt") / post["path"]
            self.assertTrue(post_ckpt_path.exists())

            # Simulate restart from this postbatch checkpoint with a clean mock backend
            restart_captures = root / "restart_requests.ndjson"
            restart_backend = root / "restart_backend.py"
            restart_backend.write_text(
                "import json,sys\n"
                "prompt=sys.stdin.read()\n"
                f"capture={str(restart_captures)!r}\n"
                "with open(capture, 'a', encoding='utf-8') as out: out.write(json.dumps({'prompt':prompt})+'\\n')\n"
                "print(json.dumps({'text': json.dumps([{'action': 'EndTurn'}])}))\n",
                encoding="utf-8",
            )
            restart_log = root / "restart_match.ndjson"
            restart_cmd = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                           "--model-command", shlex.join([sys.executable, str(restart_backend)]),
                           "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                           "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "18",
                           "--log", str(restart_log), "--resume-checkpoint", str(post_ckpt_path),
                           "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"]
            res2 = subprocess.run(restart_cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res2.returncode, 0, res2.stderr[-3000:] + restart_log.read_text()[-3000:])
            restart_captured = [json.loads(line) for line in restart_captures.read_text().splitlines()]
            restart_first_prompt = restart_captured[0]["prompt"]
            # It sees committed C in continuity summary, not A or B
            self.assertIn("Attack(U7->U24)", restart_first_prompt)
            self.assertNotIn("defender=999", restart_first_prompt)
            self.assertNotIn("holds[3]", restart_first_prompt)

            # 4. History double import check
            conn = open_history(root / "history.sqlite")
            try:
                g1 = import_game(conn, log)
                g2 = import_game(conn, log)
                self.assertEqual(g1, g2)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()
