"""Integration and contract acceptance tests for Stack 3 action choices."""
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

from .game_history import import_game, open_history
from . import action_choices as ac

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
REVISION_338_FIXTURE = ROOT / "tools/fixtures/decision_positions/revision-338"


def _prepare_checkpoint(source_fixture: Path, temp_dir: Path, *, u24_hp: int | None = None, u1_advance: bool = False) -> Path:
    body = json.loads((source_fixture / "checkpoint.json").read_text(encoding="utf-8"))
    board = ROOT / "scenarios" / body["scenario"] / "board.toml"
    assert hashlib.sha256(board.read_bytes()).hexdigest() == body["board_sha256"]
    body["board_path"] = str(board)
    body["save_state"]["board_path"] = str(board)
    if u24_hp is not None:
        for u in body["save_state"]["units"]:
            if u.get("id") == 24:
                u["hp"] = u24_hp
    if u1_advance:
        for u in body["save_state"]["units"]:
            if u.get("id") == 1:
                u["advancement_pending"] = True
                u["advances_to"] = ["Lich", "Necromancer"]
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    digest = hashlib.sha256(encoded).hexdigest()
    path = temp_dir / f"{body['side_turns']}-{body['save_state']['state_revision']}-{body['boundary']}-{digest}.json"
    path.write_bytes(encoded)
    return path


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class ActionChoicesIntegrationTests(unittest.TestCase):

    def test_choices_recruitment_and_move_via_handles(self):
        """1. Recruit and move via opaque handles through real prompt/tool loop."""
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
                "    # Extract recruitment choice from OPTION_PAYLOADS\n"
                "    opt_json = prompt.split('OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nOPTION_PAYLOADS_UNTRUSTED_DATA_END', 1)[0]\n"
                "    options = json.loads(opt_json)\n"
                "    choices = options.get('choices', [])\n"
                "    recruit_c = next(c for c in choices if c.get('category') == 'recruit' and c.get('def_id') == 'Skeleton Archer' and c.get('col') == 2 and c.get('row') == 6)\n"
                "    response = {'choices': [recruit_c['handle']], 'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'recruit', 'risk': 'none'}]}\n"
                "elif step == 2:\n"
                "    # Inspect new unit at (2,6)\n"
                "    board_json = prompt.split('BOARD_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nBOARD_UNTRUSTED_DATA_END', 1)[0]\n"
                "    payload = json.loads(board_json)\n"
                "    briefing = payload.get('briefing', '')\n"
                "    new_uid = None\n"
                "    for line in briefing.splitlines():\n"
                "        if 'pos=(2,6)' in line and 'faction=0' in line:\n"
                "            new_uid = int(line.split()[0].split('=')[1])\n"
                "    response = {'tool': 'inspect_units', 'unit_ids': [new_uid]}\n"
                "elif step == 3:\n"
                "    # Tool followup contains CHOICES in prompt tool result\n"
                "    lines = prompt.splitlines()\n"
                "    choices_line = next(l for l in lines if l.startswith('CHOICES '))\n"
                "    # Extract first move handle\n"
                "    handle = choices_line.split('CHOICES ', 1)[1].split(':', 1)[0].strip()\n"
                "    response = {'choices': [handle], 'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'deploy', 'risk': 'none'}]}\n"
                "else:\n"
                "    response = {'actions': [{'action': 'EndTurn'}], 'decisions': [{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}]}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "2",
                "--incremental-turns",
                "--decision-mode", "focused",
                "--action-encoding", "choices",
                "--log", str(log),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(res.returncode, 0, f"llm_client failed: {res.stderr}\n{res.stdout}")

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 3)

            # Step 1: Recruit via choice
            self.assertEqual(forwarded[0]["action_encoding"], "choices")
            self.assertFalse(forwarded[0]["coordinate_fallback"])
            self.assertEqual(len(forwarded[0]["authored_choices"]), 1)
            self.assertTrue(forwarded[0]["authored_choices"][0].startswith("c_0_"))
            self.assertEqual(forwarded[0]["orders"][0]["action"], "Recruit")

            # Step 2: Move via choice
            self.assertEqual(forwarded[1]["action_encoding"], "choices")
            self.assertFalse(forwarded[1]["coordinate_fallback"])
            self.assertEqual(len(forwarded[1]["authored_choices"]), 1)
            self.assertTrue(forwarded[1]["authored_choices"][0].startswith("c_1_"))
            self.assertEqual(forwarded[1]["orders"][0]["action"], "Move")

            # Step 3: EndTurn via coordinate fallback
            self.assertEqual(forwarded[2]["action_encoding"], "coordinates")
            self.assertTrue(forwarded[2]["coordinate_fallback"])
            self.assertIsNone(forwarded[2]["authored_choices"])
            self.assertEqual(forwarded[2]["orders"][0]["action"], "EndTurn")

            # Verify terminal metadata
            terminal = next(r for r in records if r.get("type") == "terminal")
            self.assertEqual(terminal["handle_choices_used"], 2)
            self.assertEqual(terminal["coordinate_fallbacks"], 1)
            self.assertEqual(terminal["choice_actions_expanded"], 2)

    def test_choices_attack_and_move_attack(self):
        """2. Standing attack produces only Attack; move-attack produces Move+Attack."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt = _prepare_checkpoint(REVISION_338_FIXTURE, root, u24_hp=8)
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
                "    # Standing attack choice for U18 is already in OPTION_PAYLOADS\n"
                "    opt_json = prompt.split('OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nOPTION_PAYLOADS_UNTRUSTED_DATA_END', 1)[0]\n"
                "    options = json.loads(opt_json)\n"
                "    choices = options.get('choices', [])\n"
                "    atk = next(c for c in choices if c.get('category') == 'attack' and c.get('unit_id') == 18 and c.get('target_id') == 24)\n"
                "    response = {'choices': [atk['handle']], 'decisions': [{'orders': [0], 'rules': ['T2'], 'expected': 'standing attack', 'risk': 'none'}]}\n"
                "elif step == 2:\n"
                "    # Inspect U17 for move-attack\n"
                "    response = {'tool': 'inspect_units', 'unit_ids': [17]}\n"
                "elif step == 3:\n"
                "    lines = prompt.splitlines()\n"
                "    choices_line = next(l for l in lines if l.startswith('CHOICES '))\n"
                "    items = choices_line.split('CHOICES ', 1)[1].split('; ')\n"
                "    # Find move-and-attack item\n"
                "    ma_item = next(it for it in items if 'and attack' in it)\n"
                "    handle = ma_item.split(':', 1)[0].strip()\n"
                "    response = {'choices': [handle], 'decisions': [{'orders': [0], 'rules': ['T2'], 'expected': 'move attack', 'risk': 'none'}]}\n"
                "else:\n"
                "    response = {'actions': [{'action': 'DoneWithImportantMoves'}], 'decisions': [{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}]}\n"
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
                "--incremental-turns",
                "--decision-mode", "focused",
                "--action-encoding", "choices",
                "--resume-checkpoint", str(ckpt),
                "--log", str(log),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(res.returncode, 0, f"llm_client failed: {res.stderr}\n{res.stdout}")

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 3)

            # Step 1: Standing attack contains ONLY Attack (no move to own hex)
            self.assertEqual(forwarded[0]["orders"], [{"action": "Attack", "attacker_id": 18, "defender_id": 24}])
            self.assertEqual(forwarded[0]["expansion_mapping"], [0])

            # Step 2: Move-attack contains Move then Attack, expansion_mapping has two entries pointing to choice 0
            self.assertEqual(len(forwarded[1]["orders"]), 2)
            self.assertEqual(forwarded[1]["orders"][0]["action"], "Move")
            self.assertEqual(forwarded[1]["orders"][1]["action"], "Attack")
            self.assertEqual(forwarded[1]["expansion_mapping"], [0, 0])

    def test_choices_advancement_both_selectors(self):
        """2b. Advancement supports both target_index and def_id selectors."""
        for selector in ("target_index", "def_id"):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                ckpt = _prepare_checkpoint(REVISION_338_FIXTURE, root, u1_advance=True)
                backend = root / "backend.py"
                captures = root / "captures.ndjson"
                backend.write_text(
                    f"import json, sys\n"
                    f"capture = sys.argv[1]\n"
                    f"prompt = sys.stdin.read()\n"
                    f"with open(capture, 'a', encoding='utf-8') as f:\n"
                    f"    f.write(json.dumps({{'prompt': prompt}}) + '\\n')\n"
                    f"step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                    f"if step == 1:\n"
                    f"    opt_json = prompt.split('OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nOPTION_PAYLOADS_UNTRUSTED_DATA_END', 1)[0]\n"
                    f"    options = json.loads(opt_json)\n"
                    f"    choices = options.get('choices', [])\n"
                    f"    adv = next(c for c in choices if c.get('category') == 'advance' and c.get('unit_id') == 1 and c.get('selector') == '{selector}' and c.get('def_id') == 'Lich')\n"
                    f"    response = {{'choices': [adv['handle']], 'decisions': [{{'orders': [0], 'rules': ['T0'], 'expected': 'advance', 'risk': 'none'}}]}}\n"
                    f"else:\n"
                    f"    response = {{'actions': [{{'action': 'DoneWithImportantMoves'}}], 'decisions': [{{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}}]}}\n"
                    f"print(json.dumps({{'text': json.dumps(response)}}))\n",
                    encoding="utf-8",
                )
                log = root / f"match_{selector}.ndjson"
                cmd = [
                    sys.executable, "-m", "tools.llm_client",
                    "--driver", str(DRIVER),
                    "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                    "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                    "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                    "--incremental-turns",
                    "--decision-mode", "focused",
                    "--action-encoding", "choices",
                    "--resume-checkpoint", str(ckpt),
                    "--log", str(log),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
                self.assertEqual(res.returncode, 0, f"advance ({selector}) failed: {res.stderr}\n{res.stdout}")
                records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
                forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
                self.assertEqual(forwarded[0]["orders"][0]["action"], "Advance")
                if selector == "target_index":
                    self.assertEqual(forwarded[0]["orders"][0]["target_index"], 0)
                    self.assertNotIn("def_id", forwarded[0]["orders"][0])
                else:
                    self.assertEqual(forwarded[0]["orders"][0]["def_id"], "Lich")
                    self.assertNotIn("target_index", forwarded[0]["orders"][0])

    def test_handle_validation_stale_unknown_cross_game_malformed(self):
        """3. Stale, unknown, cross-game, malformed handles and mixing actions/choices fail validation."""
        reg = ac.ChoiceRegistry(game_id="game_alpha")
        reg.sync_revision(10)
        c = ac.Choice(handle=ac.make_handle("game_alpha", 10, "Move:1:2:3"),
                      description="Move", actions=[{"action": "Move", "unit_id": 1, "col": 2, "row": 3}],
                      category="move")
        reg.register(c)

        # Valid
        acts, _, _ = reg.resolve([c.handle], current_revision=10)
        self.assertEqual(len(acts), 1)

        # Stale handle from rev 9
        stale = ac.make_handle("game_alpha", 9, "Move:1:2:3")
        with self.assertRaises(ValueError) as ctx:
            reg.resolve([stale], current_revision=10)
        self.assertIn("stale_choice_handle", str(ctx.exception))

        # Unknown handle (rev 10, but not registered)
        unknown = ac.make_handle("game_alpha", 10, "Move:9:9:9")
        with self.assertRaises(ValueError) as ctx:
            reg.resolve([unknown], current_revision=10)
        self.assertIn("unknown_choice_handle", str(ctx.exception))

        # Cross-game handle (same rev, but different game_id token)
        cross_game = ac.make_handle("game_beta", 10, "Move:1:2:3")
        with self.assertRaises(ValueError) as ctx:
            reg.resolve([cross_game], current_revision=10)
        self.assertIn("unknown_choice_handle", str(ctx.exception))

        # Malformed handle
        with self.assertRaises(ValueError) as ctx:
            reg.resolve(["not_a_valid_handle"], current_revision=10)
        self.assertIn("malformed_choice_handle", str(ctx.exception))

    def test_destination_collision_rollback_and_repair(self):
        """4. Two choices with shared destination roll back together; legal replacement commits."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt = _prepare_checkpoint(REVISION_338_FIXTURE, root)
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
                "    response = {'tool': 'inspect_units', 'unit_ids': [8, 3]}\n"
                "elif step == 2:\n"
                "    response = {'tool': 'inspect_units', 'unit_ids': [8, 3]}\n"
                "elif step == 3:\n"
                "    lines = prompt.splitlines()\n"
                "    choices_lines = [l for l in lines if l.startswith('CHOICES ')]\n"
                "    u8_items = choices_lines[0].split('CHOICES ', 1)[1].split('; ')\n"
                "    u3_items = choices_lines[1].split('CHOICES ', 1)[1].split('; ')\n"
                "    u8_moves = {it.split(': Move U8 to ')[1].split(' and')[0]: it.split(':', 1)[0] for it in u8_items if ': Move U8 to ' in it}\n"
                "    u3_moves = {it.split(': Move U3 to ')[1].split(' and')[0]: it.split(':', 1)[0] for it in u3_items if ': Move U3 to ' in it}\n"
                "    common_dest = next(dest for dest in u8_moves if dest in u3_moves)\n"
                "    with open(capture + '.choice', 'w') as sf:\n"
                "        sf.write(u8_moves[common_dest])\n"
                "    response = {'choices': [u8_moves[common_dest], u3_moves[common_dest]],\n"
                "                'decisions': [{'orders': [0, 1], 'rules': ['T0'], 'expected': 'collide', 'risk': 'collision'}]}\n"
                "elif step == 4:\n"
                "    handle = open(capture + '.choice').read().strip()\n"
                "    response = {'choices': [handle], 'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'single move', 'risk': 'none'}]}\n"
                "else:\n"
                "    response = {'actions': [{'action': 'DoneWithImportantMoves'}], 'decisions': [{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}]}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match_collision.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                "--incremental-turns",
                "--decision-mode", "focused",
                "--action-encoding", "choices",
                "--resume-checkpoint", str(ckpt),
                "--log", str(log),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(res.returncode, 0, f"collision test failed: {res.stderr}\n{res.stdout}")

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            validations = [r for r in records if r.get("type") == "batch_validation"]
            failed_validations = [v for v in validations if v.get("valid") is False]
            self.assertEqual(len(failed_validations), 1)
            results = failed_validations[0].get("results", [])
            self.assertTrue(any(r.get("code") == "DestinationOccupied" or r.get("error") == "DestinationOccupied" for r in results))

            # Verify the repaired batch was forwarded and accepted
            repairs = [r for r in records if r.get("type") == "action_repair"]
            self.assertEqual(len(repairs), 1)

    def test_inspect_units_group_in_one_response(self):
        """6. (Stack 4) Inspect eight friendly units in one tool call, then submit a
        legal partial move batch built from the returned grouped options.

        This exercises the player-facing group tool through the real driver.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt = _prepare_checkpoint(REVISION_338_FIXTURE, root)
            backend = root / "backend.py"
            captures = root / "captures.ndjson"
            friendly_ids = [1, 3, 4, 5, 6, 7, 8, 10]
            backend.write_text(
                "import json, sys\n"
                "capture = sys.argv[1]\n"
                "prompt = sys.stdin.read()\n"
                "with open(capture, 'a', encoding='utf-8') as f:\n"
                "    f.write(json.dumps({'prompt': prompt}) + '\\n')\n"
                "step = sum(1 for _ in open(capture, encoding='utf-8'))\n"
                f"friendly_ids = {friendly_ids!r}\n"
                "if step == 1:\n"
                "    response = {'tool': 'inspect_units', 'unit_ids': friendly_ids}\n"
                "elif step == 2:\n"
                "    lines = prompt.splitlines()\n"
                "    choices_lines = [l for l in lines if l.startswith('CHOICES ')]\n"
                "    move_item = None\n"
                "    for cl in choices_lines:\n"
                "        for item in cl.split('CHOICES ', 1)[1].split('; '):\n"
                "            if ': Move U' in item and ' and attack' not in item:\n"
                "                move_item = item\n"
                "                break\n"
                "        if move_item:\n"
                "            break\n"
                "    with open(capture + '.coords_meta', 'w') as sf:\n"
                "        sf.write(json.dumps({'choices_line_count': len(choices_lines)}))\n"
                "    if move_item is not None:\n"
                "        handle = move_item.split(':', 1)[0].strip()\n"
                "        response = {'choices': [handle], 'decisions': [{'orders': [0], 'rules': ['T0'], 'expected': 'move', 'risk': 'none'}]}\n"
                "    else:\n"
                "        response = {'actions': [{'action': 'DoneWithImportantMoves'}], 'decisions': [{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}]}\n"
                "else:\n"
                "    response = {'actions': [{'action': 'DoneWithImportantMoves'}], 'decisions': [{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}]}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match_inspect_units.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                "--incremental-turns",
                "--decision-mode", "focused",
                "--action-encoding", "choices",
                "--resume-checkpoint", str(ckpt),
                "--log", str(log),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(res.returncode, 0, f"inspect_units test failed: {res.stderr}\n{res.stdout}")

            meta = json.loads((captures.with_suffix(captures.suffix + ".coords_meta")).read_text(encoding="utf-8"))
            # Grouped by unit: more than one unit's CHOICES line appeared from a
            # single inspect_units tool call covering all eight friendly ids.
            self.assertGreater(meta["choices_line_count"], 1)

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
            self.assertEqual(len(forwarded), 2)
            self.assertEqual(forwarded[0]["orders"][0]["action"], "Move")
            self.assertIn(forwarded[0]["orders"][0]["unit_id"], friendly_ids)
            self.assertEqual(forwarded[1]["orders"][0]["action"], "DoneWithImportantMoves")

            terminal = next(r for r in records if r.get("type") == "terminal")
            # Exactly one player tool allowance was spent inspecting all eight units.
            self.assertEqual(terminal.get("tool_calls_by_name", {}).get("inspect_units"), 1)
            self.assertNotIn("inspect_unit", terminal.get("tool_calls_by_name", {}))

            # Pin the accounting asymmetry: one tool allowance, but eight real
            # underlying driver queries (bounded Python fan-out over the
            # existing single-unit query, not a new batched Rust query). A
            # player planning against a tight query budget must not assume
            # one tool call is one unit of driver work -- see the query-budget
            # note on the repair-loop equivalent of this test.
            inspect_unit_queries = [
                r for r in records if r.get("type") == "query"
                and isinstance(r.get("line", {}).get("body"), dict)
                and "destination_threats" in r["line"]["body"]
            ]
            self.assertEqual(len(inspect_unit_queries), len(friendly_ids))

    def test_catalog_import_and_idempotence(self):
        """5. Reimport of choices game into SQLite catalog is idempotent."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ckpt = _prepare_checkpoint(REVISION_338_FIXTURE, root)
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
                "    opt_json = prompt.split('OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\\n', 1)[1].split('\\nOPTION_PAYLOADS_UNTRUSTED_DATA_END', 1)[0]\n"
                "    options = json.loads(opt_json)\n"
                "    choices = options.get('choices', [])\n"
                "    atk = next(c for c in choices if c.get('category') == 'attack')\n"
                "    response = {'choices': [atk['handle']], 'decisions': [{'orders': [0], 'rules': ['T2'], 'expected': 'atk', 'risk': 'none'}]}\n"
                "else:\n"
                "    response = {'actions': [{'action': 'DoneWithImportantMoves'}], 'decisions': [{'orders': [0], 'rules': ['T7'], 'expected': 'done', 'risk': 'none'}]}\n"
                "print(json.dumps({'text': json.dumps(response)}))\n",
                encoding="utf-8",
            )
            log = root / "match_catalog.ndjson"
            cmd = [
                sys.executable, "-m", "tools.llm_client",
                "--driver", str(DRIVER),
                "--model-command", shlex.join([sys.executable, str(backend), str(captures)]),
                "--scenario", "big_battle_6", "--faction0", "undead", "--faction1", "undead",
                "--gold", "300", "--seed", "2002", "--llm-side", "0", "--max-turns", "15",
                "--incremental-turns",
                "--decision-mode", "focused",
                "--action-encoding", "choices",
                "--resume-checkpoint", str(ckpt),
                "--log", str(log),
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            self.assertEqual(res.returncode, 0, f"catalog run failed: {res.stderr}\n{res.stdout}")

            db_path = root / "catalog.db"
            with open_history(db_path) as conn:
                gid1 = import_game(conn, log)
                self.assertTrue(gid1)

                # Reimport should be idempotent
                gid2 = import_game(conn, log)
                self.assertEqual(gid1, gid2)

                batches = conn.execute("SELECT COUNT(*) FROM action_batches WHERE game_id=?", (gid1,)).fetchone()[0]
                self.assertEqual(batches, 2)
                row = conn.execute("SELECT status, termination_reason FROM games WHERE game_id=?", (gid1,)).fetchone()
                self.assertEqual(row[0], "complete")
                self.assertEqual(row[1], "max_turns")

            records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            terminal = next(r for r in records if r.get("type") == "terminal")
            self.assertEqual(terminal["action_encoding"], "choices")
            self.assertEqual(terminal["handle_choices_used"], 1)
            self.assertEqual(terminal["coordinate_fallbacks"], 1)


if __name__ == "__main__":
    unittest.main()
