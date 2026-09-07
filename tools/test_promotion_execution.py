"""Restore an archived promotion boundary and execute the client's choice."""
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
FIXTURE = ROOT / "tools/fixtures/decision_positions/promotion.json"


def _checkpoint(temp: Path) -> Path:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = ROOT / "scenarios" / body["scenario"] / "board.toml"
    board_hash = hashlib.sha256(board.read_bytes()).hexdigest()
    assert board_hash == body["board_sha256"]
    body["board_path"] = str(board)
    body["save_state"]["board_path"] = str(board)
    body["board_sha256"] = board_hash
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = temp / f"{body['side_turns']}-{body['save_state']['state_revision']}-{body['boundary']}-{digest}.json"
    path.write_bytes(encoded)
    return path


def _backend(path: Path, prompt_capture: Path) -> None:
    path.write_text(
        "import json,sys\n"
        "prompt=sys.stdin.read()\n"
        f"open({str(prompt_capture)!r}, 'w', encoding='utf-8').write(prompt)\n"
        "assert 'id=13 faction=0 def=Skeleton Archer' in prompt\n"
        "assert 'Bone Shooter' in prompt\n"
        "board=json.loads(prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n',1)[1].split('\\nBOARD_UNTRUSTED_DATA_END',1)[0])\n"
        "line=next(x for x in board['briefing'].splitlines() if 'id=13 faction=0 def=Skeleton Archer' in x)\n"
        "choices=line.split('advances_to=',1)[-1]\n"
        "assert json.loads(choices) == ['Bone Shooter']\n"
        "print(json.dumps({'text': json.dumps({'actions': [\n"
        " {'action':'Advance','unit_id':13,'def_id':json.loads(choices)[0]},\n"
        " {'action':'FinishWithGreedy','groups':[],'holds':[]}], 'decisions':[{'orders':[0,1], 'rules':['S1'],\n"
        " 'expected':'Promote the pending archer using the supplied engine choice.',\n"
        " 'risk':'Delaying the advance leaves the unit pending.'}]})}))\n",
        encoding="utf-8",
    )


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class PromotionExecutionIntegrationTests(unittest.TestCase):
    def test_restored_pending_unit_uses_prompt_choice_and_persists_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            checkpoint = _checkpoint(source)
            backend = root / "backend.py"
            prompt_file = root / "prompt.txt"
            _backend(backend, prompt_file)
            log = root / "match.ndjson"
            command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend)]),
                       "--scenario", "big_battle_6", "--faction0", "undead",
                       "--faction1", "undead", "--gold", "300", "--seed", "2003",
                       "--llm-side", "0", "--max-turns", "17", "--log", str(log),
                       "--resume-checkpoint", str(checkpoint), "--query-budget-seconds", "10",
                       "--model-timeout", "10", "--turn-timeout", "30"]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])
            prompt = prompt_file.read_text(encoding="utf-8")
            board = json.loads(prompt.split("BOARD_UNTRUSTED_DATA_BEGIN:\n", 1)[1].split("\nBOARD_UNTRUSTED_DATA_END", 1)[0])
            self.assertIn('pending=True advances_to=["Bone Shooter"]', board["briefing"])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
            request = next(r for r in records if r.get("type") == "model_request"
                           and r.get("request_id") == forwarded.get("request_id"))
            self.assertEqual(prompt, request["prompt"])
            self.assertEqual(sum(r.get("type") == "forwarded_orders" for r in records), 1)
            initial = next(r["line"] for r in records if r.get("type") == "driver"
                           and r["line"].get("type") == "state")
            pending = next(u for u in initial["units"] if u["id"] == 13)
            self.assertTrue(pending["advancement_pending"])
            self.assertEqual(pending["advances_to"], ["Bone Shooter"])
            self.assertEqual(initial["state_revision"], 383)
            self.assertEqual(request["state_revision"], 383)
            self.assertEqual(forwarded["state_revision"], 383)
            self.assertEqual(forwarded["orders"][0], {"action": "Advance", "unit_id": 13, "def_id": "Bone Shooter"})
            self.assertEqual(forwarded["decision_annotation"]["status"], "valid")
            post = next(r for r in records if r.get("type") == "checkpoint_ref"
                        and r.get("boundary") == "postbatch")
            post_state = json.loads((log.with_suffix(".ckpt") / post["path"]).read_text())
            promoted = next(u for u in post_state["save_state"]["units"] if u.get("id") == 13)
            self.assertEqual(promoted["def_id"], "Bone Shooter")
            self.assertEqual(promoted["level"], 2)
            self.assertFalse(promoted["advancement_pending"])
            self.assertEqual(post_state["save_state"]["state_revision"], 385)
            events = [e for r in records if r.get("type") == "driver"
                      for e in (r.get("line", {}).get("events", []) if isinstance(r.get("line"), dict) else [])]
            self.assertTrue(any(e.get("kind") == "advance" and e.get("unit") == 13 for e in events))
            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                stored = conn.execute("SELECT prompt_blob,response_blob,prompt_hash,response_hash,state_revision FROM model_requests WHERE request_id=?", (request["request_id"],)).fetchone()
                self.assertEqual(zlib.decompress(stored[0]).decode(), request["prompt"])
                self.assertEqual(zlib.decompress(stored[1]).decode(), request["raw_output"])
                self.assertEqual(stored[2], hashlib.sha256(request["prompt"].encode()).hexdigest())
                self.assertEqual(stored[3], hashlib.sha256(request["raw_output"].encode()).hexdigest())
                self.assertEqual(stored[4], 383)
                batch = conn.execute("SELECT request_id,before_revision,after_revision,submitted_orders_json FROM action_batches WHERE game_id=?", (game_id,)).fetchone()
                self.assertEqual(batch[0], request["request_id"])
                self.assertEqual(batch[1], 383)
                self.assertIsNone(batch[2])
                self.assertEqual(json.loads(batch[3]), forwarded["orders"])
                actions = conn.execute("SELECT action_type,before_revision,after_revision FROM actions WHERE game_id=? AND request_id=? ORDER BY authored_order_index", (game_id, request["request_id"])).fetchall()
                self.assertEqual([row[0] for row in actions], ["Advance", "FinishWithGreedy"])
                self.assertEqual(actions[0][1:], (None, None))
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()
