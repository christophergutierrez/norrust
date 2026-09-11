"""End-to-end coverage for the nonfinal MoveGroupToward action."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import unittest

from .game_history import import_game, open_history

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class MovementIntegrationTests(unittest.TestCase):
    def test_recruit_move_recruit_finish_stays_one_turn_and_reimports(self):
        for encoding in ("coordinates", "choices"):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                backend = root / "backend.py"
                prompt_log = root / "prompts.ndjson"
                # The client starts a fresh command process for each request. The
                # authoritative revision in the prompt therefore selects the
                # next scripted operation without carrying hidden model state.
                backend.write_text(
                    "import json,re,sys\n"
                    "prompt=sys.stdin.read()\n"
                    "with open(__import__('os').environ['MOVEMENT_PROMPT_LOG'],'a') as stream: stream.write(json.dumps({'prompt':prompt})+'\\n')\n"
                    "match=re.search(r'accepted_partials=(\\d+)', prompt)\n"
                    "revision=int(match.group(1)) if match else -1\n"
                    "if 'final_only=True' in prompt: revision=4\n"
                    "responses={\n"
                    " 0:{'actions':[{'action':'RecruitBatch','def_id':'Skeleton','count':1}]},\n"
                    " 1:{'actions':[{'action':'MoveGroupToward','unit_ids':[3],'col':3,'row':7}]},\n"
                    " 2:{'actions':[{'action':'RecruitBatch','def_id':'Skeleton','count':1}]},\n"
                    " 3:{'actions':[{'action':'MoveGroupToward','unit_ids':[3],'col':10,'row':7}]},\n"
                    " 4:{'actions':[{'action':'FinishWithGreedy','groups':[],'holds':[]}]},\n"
                    "}\n"
                    "response=responses[revision]\n"
                    "response['decisions']=[{'orders':[0],'rules':['T0'],'expected':'perform the next legal step','risk':'the action changes the live position'}]\n"
                    "print(json.dumps({'text':json.dumps(response,separators=(',',':'))}))\n"
                )
                log = root / "match.ndjson"
                result = subprocess.run(
                    [
                        sys.executable, "-m", "tools.llm_client",
                        "--driver", str(DRIVER),
                        "--model-command", shlex.join([sys.executable, str(backend)]),
                        "--scenario", "big_battle_6", "--faction0", "undead",
                        "--faction1", "undead", "--gold", "100", "--seed", "9211",
                    "--llm-side", "0", "--max-turns", "1", "--incremental-turns",
                    "--max-partial-batches-per-turn", "5",
                    "--action-encoding", encoding,
                        "--log", str(log), "--query-budget-seconds", "10",
                        "--model-timeout", "10", "--turn-timeout", "30",
                    ],
                    cwd=ROOT, capture_output=True, text=True, timeout=60,
                    env={**os.environ, "MOVEMENT_PROMPT_LOG": str(prompt_log)},
                )
                self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
                records = [json.loads(line) for line in log.read_text().splitlines()]
                forwarded = [record for record in records if record.get("type") == "forwarded_orders"]
                self.assertEqual(
                    [record["orders"][0]["action"] for record in forwarded],
                    ["RecruitBatch", "MoveGroupToward", "RecruitBatch", "MoveGroupToward", "FinishWithGreedy"],
                )
                self.assertEqual({record["decision_annotation"]["status"] for record in forwarded}, {"valid"})

                move_batch = forwarded[3]["batch_id"]
                # The driver event line does not duplicate batch_id, so select by
                # source and the event's authored index; the move macro is the
                # only delegated event before the explicit final finish.
                move_events = [
                    event for record in records
                    if record.get("type") == "driver"
                    and record.get("line", {}).get("type") == "events"
                    and record.get("line", {}).get("source") == "delegated_greedy"
                    for event in record["line"]["events"]
                    if event.get("delegated_order_index") == 0 and event.get("kind") == "move"
                ]
                self.assertEqual(len(move_events), 1)
                self.assertNotIn("attack", {event["kind"] for event in move_events})
                self.assertNotIn("end_turn", {event["kind"] for event in move_events})

                all_events = [
                    event for record in records
                    if record.get("type") == "driver"
                    and record.get("line", {}).get("type") == "events"
                    for event in record["line"].get("events", [])
                ]
                self.assertFalse(any(record.get("line", {}).get("source") == "greedy"
                                     for record in records if record.get("type") == "driver"))
                self.assertEqual(sum(event.get("kind") == "recruit" for event in all_events), 2)
                self.assertEqual(sum(event.get("kind") == "move" for event in all_events), 1)
                prompts = [json.loads(line)["prompt"] for line in prompt_log.read_text().splitlines()]
                self.assertTrue(
                    any("skipped=U3:no_improving_destination" in prompt for prompt in prompts),
                    "the next canonical prompt must carry the committed per-unit skip result",
                )
                self.assertTrue(
                    any("TURN_PROGRESS moved=U3" in prompt for prompt in prompts),
                    "a committed delegated movement macro must count in live progress",
                )

                db = root / "history.sqlite"
                conn = open_history(db)
                try:
                    game_id = import_game(conn, log)
                    actions = conn.execute(
                        "SELECT authored_order_index,action_type FROM actions WHERE game_id=? ORDER BY sequence",
                        (game_id,),
                    ).fetchall()
                    self.assertEqual(
                        actions,
                    [(0, "RecruitBatch"), (0, "MoveGroupToward"),
                     (0, "RecruitBatch"), (0, "MoveGroupToward"),
                     (0, "FinishWithGreedy")],
                    )
                    event_row = conn.execute(
                        "SELECT source,batch_id,event_json FROM events WHERE game_id=? AND kind='move'",
                        (game_id,),
                    ).fetchone()
                    self.assertEqual(event_row[0], "delegated_greedy")
                    self.assertEqual(event_row[1], move_batch)
                    self.assertEqual(json.loads(event_row[2])["delegated_order_index"], 0)
                    before = conn.execute(
                        "SELECT count(*),max(event_sequence) FROM events WHERE game_id=?",
                        (game_id,),
                    ).fetchone()
                    import_game(conn, log, game_id=game_id)
                    self.assertEqual(
                        conn.execute(
                            "SELECT count(*),max(event_sequence) FROM events WHERE game_id=?",
                            (game_id,),
                        ).fetchone(),
                        before,
                    )
                finally:
                    conn.close()
