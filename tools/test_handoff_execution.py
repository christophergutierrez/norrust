"""Real-driver handoff review checks from the archived seed 2001 boundary."""
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
FIXTURE = ROOT / "tools/fixtures/decision_positions/handoff.json"


def _checkpoint(temp: Path) -> Path:
    body = json.loads(FIXTURE.read_text(encoding="utf-8"))
    board = ROOT / "scenarios" / body["scenario"] / "board.toml"
    board_hash = hashlib.sha256(board.read_bytes()).hexdigest()
    assert board_hash == body["board_sha256"]
    body["board_path"] = str(board)
    body["save_state"]["board_path"] = str(board)
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = temp / f"{body['side_turns']}-{body['save_state']['state_revision']}-{body['boundary']}-{digest}.json"
    path.write_bytes(encoded)
    return path


def _backend(path: Path) -> None:
    path.write_text(
        "import json,sys\n"
        "prompt=sys.stdin.read()\n"
        "board=prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n',1)[1].split('\\nBOARD_UNTRUSTED_DATA_END',1)[0]\n"
        "payload=json.loads(board)\n"
        "assert all('id=%s faction=0' % unit in payload['briefing'] for unit in (1,4,5,6))\n"
        "mode=sys.argv[2]\n"
        "if 'DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN:' not in prompt:\n"
        " response={'actions':[{'action':'FinishWithGreedy','groups':[{'mode':'greedy','unit_ids':[1,5]}], 'holds':[{'unit_id':6,'reason':'guard (7,6); release when frontline advances'}]}], 'decisions':[{'orders':[0], 'rules':['S1'], 'expected':'Keep the leader and healthy force on the keep.', 'risk':'Delegating the leader could lose recruitment.'}]}\n"
        "else:\n"
        " assert 'HANDOFF boundary=selective held=U6 delegated=U1,U5 omitted=U4' in prompt\n"
        " assert 'scope=observed_friendly delegated_recruiters=U1' in prompt\n"
        " if mode=='hold': response={'actions':[{'action':'FinishWithGreedy','groups':[{'mode':'greedy','unit_ids':[5]}], 'holds':[{'unit_id':1,'reason':'hold keep until recruitment is complete'},{'unit_id':6,'reason':'guard (7,6); release when frontline advances'}]}], 'decisions':[{'orders':[0], 'rules':['S1'], 'expected':'U1 holds the keep; U6 guards (7,6); U5 joins the attack.', 'risk':'U6 forgoes its attack until the frontline advances.'}]}\n"
        " else: response={'actions':[{'action':'FinishWithGreedy','groups':[{'mode':'greedy','unit_ids':[1]},{'mode':'greedy','unit_ids':[5]}], 'holds':[{'unit_id':6,'reason':'guard (7,6); release when frontline advances'}]}], 'decisions':[{'orders':[0], 'rules':['S1'], 'expected':'Delegate the leader and healthy support.', 'risk':'The leader may leave the keep.'}]}\n"
        "with open(sys.argv[1], 'a', encoding='utf-8') as out: out.write(json.dumps({'prompt':prompt,'response':json.dumps(response)})+'\\n')\n"
        "print(json.dumps({'text':json.dumps(response)}))\n",
        encoding="utf-8",
    )


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class HandoffExecutionIntegrationTests(unittest.TestCase):
    def test_review_revises_recruiter_boundary_and_persists_final_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            checkpoint = _checkpoint(source)
            backend = root / "backend.py"
            _backend(backend)
            for mode in ("delegate", "hold"):
                log = root / f"match-{mode}.ndjson"
                captures = root / f"requests-{mode}.ndjson"
                command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                       "--model-command", shlex.join([sys.executable, str(backend), str(captures), mode]),
                       "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                       "--gold", "300", "--seed", "2001", "--llm-side", "0", "--max-turns", "15",
                       "--log", str(log), "--resume-checkpoint", str(checkpoint),
                       "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"]
                result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr[-3000:] + log.read_text()[-3000:])
                records = [json.loads(line) for line in log.read_text().splitlines()]
                exchanges = [json.loads(line) for line in captures.read_text().splitlines()]
                requests = [r for r in records if r.get("type") == "model_request"]
                self.assertEqual(len(requests), 2, "one draft and one existing review only")
                self.assertEqual(len(exchanges), 2)
                for exchange, logged in zip(exchanges, requests):
                    self.assertEqual(exchange["prompt"], logged["prompt"])
                    self.assertEqual(exchange["response"], logged["raw_output"])
                    self.assertEqual(logged["prompt"].count("AUTHORITATIVE_LIVE_STATE_BEGIN"), 1)
                    self.assertTrue(logged["prompt"].endswith("MODEL_RESPONSE_INSTRUCTION_END"))
                initial = next(r["line"] for r in records if r.get("type") == "driver"
                               and r["line"].get("type") == "state")
                self.assertEqual(initial["state_revision"], 270)
                before = {u["id"]: (u["col"], u["row"]) for u in initial["units"]}
                self.assertEqual(before[1], (2, 7))
                post = next(r for r in records if r.get("type") == "checkpoint_ref"
                            and r.get("boundary") == "postbatch")
                checkpoint_state = json.loads((log.with_suffix(".ckpt") / post["path"]).read_text())
                self.assertEqual(checkpoint_state["side_turns"], 15)
                after = {u["id"]: (u["col"], u["row"])
                         for u in checkpoint_state["save_state"]["units"]}
                self.assertEqual(after[1], (2, 5) if mode == "delegate" else before[1])
                for guard in (4, 6):
                    self.assertEqual(after[guard], before[guard])
                events = [e for r in records if r.get("type") == "driver"
                          for e in r["line"].get("events", [])]
                self.assertFalse(any(e.get("source") == "greedy" for e in events),
                                 "cap must stop before the opponent acts")
                self.assertTrue(any(e.get("kind") == "attack"
                                    and e.get("source") == "delegated_greedy"
                                    and e.get("attacker", {}).get("unit") == 5 for e in events))
                self.assertFalse(any(e.get("kind") in ("move", "vacate") and e.get("unit") in (4, 6)
                                     or e.get("kind") == "attack" and e.get("attacker", {}).get("unit") in (4, 6)
                                     for e in events))
                forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
                request = next(r for r in records if r.get("type") == "model_request" and r.get("request_id") == forwarded.get("request_id"))
                reviews = [r for r in records if r.get("type") == "draft_review"]
                self.assertTrue(reviews)
                original_orders = json.loads(exchanges[0]["response"])["actions"]
                original_digest = hashlib.sha256(json.dumps(
                    original_orders, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                self.assertEqual(reviews[-1]["original_candidate_digest"], original_digest)
                self.assertNotEqual(forwarded["orders"], original_orders)
                audit = reviews[-1]["handoff_audit"]
                self.assertEqual(audit["boundary_kind"], "selective")
                self.assertIn(1, audit["delegated_recruiters"])
                final_audit = forwarded["handoff_audit"]
                self.assertEqual(1 in final_audit["delegated_recruiters"], mode == "delegate")
                self.assertIn(5, final_audit["delegated"])
                self.assertEqual(1 in final_audit["held"], mode == "hold")
                self.assertIn(6, final_audit["held"])
                self.assertIn(4, final_audit["omitted"])
                self.assertEqual(forwarded["request_id"], request["request_id"])
                self.assertEqual(forwarded["orders"][0]["action"], "FinishWithGreedy")
                expected_groups = ([{"mode":"greedy","unit_ids":[1]},{"mode":"greedy","unit_ids":[5]}]
                                   if mode == "delegate" else [{"mode":"greedy","unit_ids":[5]}])
                self.assertEqual(forwarded["orders"][0]["groups"], expected_groups)
                if mode == "hold":
                    self.assertIn({"unit_id":1,"reason":"hold keep until recruitment is complete"}, forwarded["orders"][0]["holds"])
                self.assertIn({"unit_id":6,"reason":"guard (7,6); release when frontline advances"}, forwarded["orders"][0]["holds"])
                self.assertEqual(forwarded["decision_annotation"]["status"], "valid")
                self.assertEqual(request["request_id"], requests[-1]["request_id"])
                conn = open_history(root / f"history-{mode}.sqlite")
                try:
                    game_id = import_game(conn, log)
                    stored = conn.execute("SELECT prompt_blob,response_blob,prompt_hash,response_hash,state_revision FROM model_requests WHERE request_id=?", (request["request_id"],)).fetchone()
                    self.assertEqual(zlib.decompress(stored[0]).decode(), request["prompt"])
                    self.assertEqual(zlib.decompress(stored[1]).decode(), request["raw_output"])
                    self.assertEqual(stored[2], hashlib.sha256(request["prompt"].encode()).hexdigest())
                    self.assertEqual(stored[3], hashlib.sha256(request["raw_output"].encode()).hexdigest())
                    self.assertEqual(stored[4], 270)
                    batch = conn.execute("SELECT request_id,before_revision,submitted_orders_json FROM action_batches WHERE game_id=?", (game_id,)).fetchone()
                    self.assertEqual(batch[0], request["request_id"])
                    self.assertEqual(batch[1], 270)
                    self.assertEqual(json.loads(batch[2]), forwarded["orders"])
                    annotation = conn.execute("SELECT reasoning_blob,annotation_status FROM model_requests WHERE request_id=?",
                                              (request["request_id"],)).fetchone()
                    self.assertEqual(annotation[1], "valid")
                    self.assertEqual(json.loads(zlib.decompress(annotation[0])),
                                     forwarded["decision_annotation"])
                    self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
                finally:
                    conn.close()
