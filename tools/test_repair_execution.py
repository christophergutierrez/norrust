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
