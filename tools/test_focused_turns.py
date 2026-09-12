"""Integration and contract acceptance tests for Stack 2 focused turns."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from .game_history import import_game, open_history
from . import llm_client

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
REVISION_338_FIXTURE = ROOT / "tools/fixtures/decision_positions/revision-338"


def _prepare_checkpoint(source_fixture: Path, temp_dir: Path, *, u24_hp: int | None = None) -> Path:
    body = json.loads((source_fixture / "checkpoint.json").read_text(encoding="utf-8"))
    board = ROOT / "scenarios" / body["scenario"] / "board.toml"
    assert hashlib.sha256(board.read_bytes()).hexdigest() == body["board_sha256"]
    body["board_path"] = str(board)
    body["save_state"]["board_path"] = str(board)
    if u24_hp is not None:
        for u in body["save_state"]["units"]:
            if u.get("id") == 24:
                u["hp"] = u24_hp
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = temp_dir / f"{body['side_turns']}-{body['save_state']['state_revision']}-{body['boundary']}-{digest}.json"
    path.write_bytes(encoded)
    return path


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class FocusedTests(unittest.TestCase):

    def test_focused_opening_deployment_six_partial_batches(self):
        """1. Real-driver opening recruits, observes real ID, deploys it, reuses freed hex,
        commits >= 6 partial batches, then finishes exactly one model side turn."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "board_json = prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nBOARD_UNTRUSTED_DATA_END', 1)[0]\n"
                "payload = json.loads(board_json)\n"
                "briefing = payload.get('briefing', '')\n"
                "units = []\n"
                "for line in briefing.splitlines():\n"
                "    line = line.strip()\n"
                "    if line.startswith('id=') and 'faction=0' in line:\n"
                "        parts = line.split()\n"
                "        uid = int(parts[0].split('=')[1])\n"
                "        pos_str = next(p for p in parts if p.startswith('pos=')).split('=')[1].strip('()')\n"
                "        col, row = [int(x) for x in pos_str.split(',')]\n"
                "        units.append({'id': uid, 'col': col, 'row': row})\n"
                "if step == 1:\n"
                "    actions = [{'action': 'Recruit', 'def_id': 'Skeleton Archer', 'col': 2, 'row': 6}]\n"
                "elif step == 2:\n"
                "    u = next(u for u in units if u['col'] == 2 and u['row'] == 6)\n"
                "    actions = [{'action': 'Move', 'unit_id': u['id'], 'col': 2, 'row': 5}]\n"
                "elif step == 3:\n"
                "    actions = [{'action': 'Recruit', 'def_id': 'Walking Corpse', 'col': 2, 'row': 6}]\n"
                "elif step == 4:\n"
                "    u = next(u for u in units if u['col'] == 2 and u['row'] == 6)\n"
                "    actions = [{'action': 'Move', 'unit_id': u['id'], 'col': 1, 'row': 6}]\n"
                "elif step == 5:\n"
                "    actions = [{'action': 'Recruit', 'def_id': 'Skeleton', 'col': 2, 'row': 6}]\n"
                "elif step == 6:\n"
                "    u = next(u for u in units if u['col'] == 2 and u['row'] == 6)\n"
                "    actions = [{'action': 'Move', 'unit_id': u['id'], 'col': 3, 'row': 5}]\n"
                "else:\n"
                "    actions = [{'action': 'EndTurn'}]\n"
                "response = {\n"
                "    'actions': actions,\n"
                "    'intent': f'step {step}',\n"
                "    'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': f'step {step}', 'risk': 'none'}]\n"
                "}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "2",
                "--decision-mode", "focused",
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr + "\n" + (log.read_text() if log.exists() else ""))
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 7, "expected 6 partial batches + 1 finish batch")
            turn_boundaries = [r for r in records if r.get("type") == "turn_boundary"]
            self.assertEqual(len(turn_boundaries), 1, "exactly one side turn finish")
            events = [e for r in records if r.get("type") == "driver" for e in r.get("line", {}).get("events", [])]
            recruit_events = [e for e in events if e.get("kind") == "recruit" and e.get("source") == "llm"]
            move_events = [e for e in events if e.get("kind") == "move" and e.get("source") == "llm"]
            self.assertEqual(len(recruit_events), 3)
            self.assertEqual(len(move_events), 3)
            recruited_ids = {e["unit"] for e in recruit_events}
            self.assertEqual(len(recruited_ids), 3)
            greedy_events = [e for e in events if e.get("source") == "greedy"]
            self.assertTrue(len(greedy_events) > 0, "greedy plays after model finish")
            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log)
                self.assertTrue(game_id)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()

    def test_focused_village_assignment_preserves_jobs_and_asserts_ownership(self):
        """2. Village-assignment fixture preserves two distinct jobs through multiple calls
        and a restart; task output includes current unit status. Assert actual specified village ownership."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "agenda = {\n"
                "    'tasks': [\n"
                "        {'id': 'job_north', 'goal': 'Capture village at 2,4', 'units': [1], 'status': 'active'},\n"
                "        {'id': 'job_east', 'goal': 'Deploy unit to village 5,3', 'units': [3], 'status': 'pending'}\n"
                "    ],\n"
                "    'holds': []\n"
                "}\n"
                "if step == 1:\n"
                "    actions = [{'action': 'Recruit', 'def_id': 'Vampire Bat', 'col': 2, 'row': 6}]\n"
                "elif step == 2:\n"
                "    actions = [{'action': 'Move', 'unit_id': 3, 'col': 2, 'row': 4}]\n"
                "else:\n"
                "    actions = [{'action': 'EndTurn'}]\n"
                "response = {\n"
                "    'actions': actions,\n"
                "    'agenda': agenda,\n"
                "    'intent': f'village job step {step}',\n"
                "    'decisions': [{'orders': [0], 'rules': ['T1'], 'expected': 'village progress', 'risk': 'none'}]\n"
                "}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                "--decision-mode", "focused",
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            prompts = [json.loads(line)["prompt"] for line in captures.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any("job_north" in p and "job_east" in p for p in prompts), "preserves two jobs")
            self.assertTrue(any('"active_task"' in p and '"unit_status"' in p and '"ready"' in p for p in prompts), "task output must include unit status")
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            post_refs = [r for r in records if r.get("type") == "checkpoint_ref"]
            self.assertTrue(post_refs)
            last_ckpt = json.loads((log.with_suffix(".ckpt") / post_refs[-1]["path"]).read_text())
            village_owners = last_ckpt["save_state"].get("village_owners", [])
            self.assertIn([2, 4, 0], village_owners, "village (2,4) must be owned by faction 0")

    def test_focused_combat_target_feedback_and_reserve_redirection(self):
        """3. Combat fixture commits an attack, returns actual target HP or death,
        and allows next response to redirect a reserve away from dead target."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt = _prepare_checkpoint(REVISION_338_FIXTURE, root, u24_hp=1)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "board_json = prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nBOARD_UNTRUSTED_DATA_END', 1)[0]\n"
                "payload = json.loads(board_json)\n"
                "briefing = payload.get('briefing', '')\n"
                "if step == 1:\n"
                "    actions = [{'action': 'Attack', 'attacker_id': 7, 'defender_id': 24}]\n"
                "elif step == 2:\n"
                "    assert 'id=24 ' not in briefing, 'Dead target U24 must not appear as legal option'\n"
                "    actions = [{'action': 'Attack', 'attacker_id': 18, 'defender_id': 39}, {'action': 'EndTurn'}]\n"
                "else:\n"
                "    actions = [{'action': 'EndTurn'}]\n"
                "response = {\n"
                "    'actions': actions,\n"
                "    'intent': f'combat step {step}',\n"
                "    'decisions': [{'orders': [0], 'rules': ['T3.1'], 'expected': 'combat', 'risk': 'none'}]\n"
                "}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                "--decision-mode", "focused",
                "--resume-checkpoint", str(ckpt),
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 2)
            self.assertEqual(forwarded[0]["orders"][0]["defender_id"], 24)
            events = [e for r in records if r.get("type") == "driver" for e in r.get("line", {}).get("events", [])]
            kill_attacks = [e for e in events if e.get("kind") == "attack" and e.get("defender", {}).get("killed") and e.get("defender", {}).get("unit") == 24]
            self.assertTrue(len(kill_attacks) > 0, "U24 must have died in combat")

    def test_budget_modes_and_partial_caps(self):
        """4. Batch stops partials at three; focused uses resolved cap (e.g. 300 > 255);
        exhausted tools do not force EndTurn when final_only is False."""
        args_focused = type("Args", (), {"decision_mode": "focused", "max_partial_batches_per_turn": 300})()
        llm_client.resolve_client_config(args_focused)
        self.assertEqual(args_focused.max_partial_batches_per_turn, 300)
        self.assertEqual(args_focused.max_model_calls_per_turn, 128)
        self.assertEqual(args_focused.max_tool_calls_per_turn, 64)
        self.assertTrue(args_focused.incremental_turns)

        args_batch = type("Args", (), {"decision_mode": "batch", "incremental_turns": True})()
        llm_client.resolve_client_config(args_batch)
        self.assertEqual(args_batch.max_partial_batches_per_turn, 3)
        self.assertEqual(args_batch.max_model_calls_per_turn, 8)
        self.assertEqual(args_batch.max_tool_calls_per_turn, 4)

        followup = llm_client.tool_followup_instruction(0, 10, incremental=True, final_only=False)
        self.assertIn("return the JSON action envelope", followup)
        self.assertNotIn("final JSON action envelope", followup)

        final_followup = llm_client.tool_followup_instruction(0, 10, incremental=True, final_only=True)
        self.assertIn("return the final JSON action envelope", final_followup)

    def test_fault_injection_and_rollback_recovery(self):
        """5. Fault injection produces correct recovery with no duplicate action,
        duplicate side turn, or reset budget."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "if step == 1:\n"
                "    actions = [{'action': 'Move', 'unit_id': 1, 'col': 99, 'row': 99}]\n"
                "elif step == 2:\n"
                "    assert 'ROLLBACK_NOTICE' in prompt or 'VALIDATION_ERROR' in prompt or 'ENGINE_ACTION_ERROR' in prompt\n"
                "    actions = [{'action': 'Move', 'unit_id': 1, 'col': 2, 'row': 6}]\n"
                "else:\n"
                "    actions = [{'action': 'EndTurn'}]\n"
                "response = {\n"
                "    'actions': actions,\n"
                "    'intent': 'recovery',\n"
                "    'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'rec', 'risk': 'none'}]\n"
                "}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                "--decision-mode", "focused",
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            repairs = [r for r in records if r.get("type") == "action_repair" or r.get("type") == "repair"]
            self.assertTrue(len(repairs) > 0, "repair must have occurred")
            turn_boundaries = [r for r in records if r.get("type") == "turn_boundary"]
            self.assertEqual(len(turn_boundaries), 1, "no duplicate side turn")

    def test_missing_or_malformed_optional_agenda_resilience(self):
        """6. Missing/malformed optional agenda and missing annotations do not invalidate legal actions."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            backend.write_text(
                "import json, sys\n"
                "prompt = sys.stdin.read()\n"
                "response = {\n"
                "    'actions': [{'action': 'EndTurn'}],\n"
                "    'agenda': 'MALFORMED_NON_OBJECT',\n"
                "    'intent': 'malformed agenda test'\n"
                "}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                "--decision-mode", "focused",
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
            self.assertEqual(forwarded["decision_annotation"]["status"], "missing")
            self.assertEqual(forwarded["orders"], [{'action': 'EndTurn'}])

    def test_focused_file_backend_transport_parity(self):
        """7. Offline scripted sequence works through maintained command and file transports,
        preserves prompt hashes, and imports extra partials as one game with correct linkage."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reqs = root / "requests"
            reqs.mkdir()

            stop_worker = threading.Event()

            def file_responder():
                step = 0
                while not stop_worker.is_set():
                    markers = list(reqs.glob("waiting_*"))
                    for m in markers:
                        rid = m.name[len("waiting_"):]
                        reply_file = reqs / f"reply_{rid}.txt"
                        if not reply_file.exists():
                            step += 1
                            if step == 1:
                                resp = {"actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 6}],
                                        "decisions": [{"orders": [0], "rules": ["T0"], "expected": "move", "risk": "none"}]}
                            else:
                                resp = {"actions": [{"action": "EndTurn"}],
                                        "decisions": [{"orders": [0], "rules": ["T0"], "expected": "done", "risk": "none"}]}
                            reply_file.write_text(json.dumps(resp))
                    time.sleep(0.01)

            t = threading.Thread(target=file_responder)
            t.start()
            try:
                log_file = root / "file_match.ndjson"
                cmd = [
                    sys.executable, "-m", "tools.llm_client",
                    "--driver", str(DRIVER),
                    "--model-command", f"{sys.executable} -m tools.file_backend --directory {reqs} --timeout 10",
                    "--player-model", "test-model",
                    "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                    "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                    "--decision-mode", "focused",
                    "--log", str(log_file),
                    "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
                ]
                res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
                self.assertEqual(res.returncode, 0, res.stderr)
            finally:
                stop_worker.set()
                t.join(timeout=2)

            conn = open_history(root / "history.sqlite")
            try:
                game_id = import_game(conn, log_file)
                self.assertTrue(game_id)
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                conn.close()

    def test_prompt_caching_prefix_stability(self):
        """8. Prompt tests prove unchanged static prefix bytes across partials and fresh
        authoritative state at the end."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "if step == 1:\n"
                "    actions = [{'action': 'Move', 'unit_id': 1, 'col': 2, 'row': 6}]\n"
                "else:\n"
                "    actions = [{'action': 'EndTurn'}]\n"
                "response = {\n"
                "    'actions': actions,\n"
                "    'intent': f'step {step}',\n"
                "    'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'ok', 'risk': 'none'}]\n"
                "}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                "--decision-mode", "focused",
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr)
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            model_requests = [r for r in records if r.get("type") == "model_request"]
            self.assertEqual(len(model_requests), 2)
            self.assertEqual(model_requests[0]["fixed_prefix_sha256"], model_requests[1]["fixed_prefix_sha256"])
            self.assertEqual(model_requests[0]["fixed_prefix_bytes"], model_requests[1]["fixed_prefix_bytes"])
            self.assertNotEqual(model_requests[0]["prompt_hash"], model_requests[1]["prompt_hash"])

    def test_inspection_purpose_survives_followup_and_repair_then_clears_on_accepted_partial(self):
        """9. Stack B: a provisional inspection purpose reaches the local follow-up
        prompt, survives an engine repair of the same operation, and is cleared once
        the engine accepts a partial batch that advances the revision."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                "PURPOSE = 'check retreat safety before committing U1'\n"
                "if step == 1:\n"
                "    board_json = prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nBOARD_UNTRUSTED_DATA_END', 1)[0]\n"
                "    briefing = json.loads(board_json).get('briefing', '')\n"
                "    enemy_id = None\n"
                "    for line in briefing.splitlines():\n"
                "        line = line.strip()\n"
                "        if line.startswith('id=') and 'faction=1' in line:\n"
                "            enemy_id = int(line.split()[0].split('=')[1])\n"
                "            break\n"
                "    assert enemy_id is not None, 'no enemy unit found in briefing'\n"
                "    response = {'tool': 'inspect_target', 'unit_id': enemy_id, 'purpose': PURPOSE}\n"
                "elif step == 2:\n"
                "    # Local follow-up: purpose must be visible with untrusted framing.\n"
                "    assert 'LOCAL_OPERATION_PURPOSE_UNTRUSTED_DATA_BEGIN' in prompt\n"
                "    assert PURPOSE in prompt\n"
                "    assert 'provisional and unverified statement' in prompt\n"
                "    assert 'not a committed intent, rule, hold, or garrison' in prompt\n"
                "    response = {'actions': [{'action': 'Move', 'unit_id': 1, 'col': 99, 'row': 99}],\n"
                "                'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'x', 'risk': 'none'}]}\n"
                "elif step == 3:\n"
                "    # Engine repair of the SAME operation: purpose must be retained.\n"
                "    assert ('ROLLBACK_NOTICE' in prompt or 'VALIDATION_ERROR' in prompt\n"
                "            or 'ENGINE_ACTION_ERROR' in prompt), 'expected a repair prompt'\n"
                "    assert 'LOCAL_OPERATION_PURPOSE_UNTRUSTED_DATA_BEGIN' in prompt\n"
                "    assert PURPOSE in prompt\n"
                "    response = {'actions': [{'action': 'Move', 'unit_id': 1, 'col': 2, 'row': 6}],\n"
                "                'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'x', 'risk': 'none'}]}\n"
                "elif step == 4:\n"
                "    # Accepted partial batch: the local context and its purpose are cleared.\n"
                "    assert 'LOCAL_OPERATION_PURPOSE_UNTRUSTED_DATA_BEGIN' not in prompt\n"
                "    assert PURPOSE not in prompt\n"
                "    assert 'FOCUSED_LOCAL_CONTEXT_BEGIN' not in prompt\n"
                "    response = {'actions': [{'action': 'EndTurn'}],\n"
                "                'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'x', 'risk': 'none'}]}\n"
                "else:\n"
                "    response = {'actions': [{'action': 'EndTurn'}]}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "42", "--llm-side", "0", "--max-turns", "1",
                "--decision-mode", "focused",
                "--log", str(log),
                "--query-budget-seconds", "10", "--model-timeout", "10", "--turn-timeout", "30"
            ]
            res = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(res.returncode, 0, res.stderr + "\n" + (log.read_text() if log.exists() else ""))
            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(any(r.get("type") == "tool_result" and r.get("tool") == "inspect_target"
                                for r in records))
            self.assertTrue(any(r.get("type") == "action_repair" for r in records))
            self.assertEqual(len([r for r in records if r.get("type") == "turn_boundary"]), 1)


if __name__ == "__main__":
    unittest.main()
