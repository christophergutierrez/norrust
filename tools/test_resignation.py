"""Verify resignation through the real client, driver, report, and catalog."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .game_history import import_game, open_history
from .llm_client import prompt_for, validate_orders, validate_preview_request
from .match_report import classify


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


class ResignationTests(unittest.TestCase):
    def test_resignation_contract_and_prompt(self):
        for incremental in (False, True):
            self.assertEqual(validate_orders('[{"action":"Resign"}]', require_end_turn=not incremental),
                             [{"action": "Resign"}])
            for orders in ([{"action": "Resign", "side": 1}],
                           [{"action": "Resign"}, {"action": "Resign"}],
                           [{"action": "EndTurn"}, {"action": "Resign"}],
                           [{"action": "Resign"}, {"action": "EndTurn"}]):
                with self.subTest(orders=orders, incremental=incremental), self.assertRaises(ValueError):
                    validate_orders(json.dumps(orders), require_end_turn=not incremental)
        prompt = prompt_for({"units": []}, [])
        self.assertIn('[{"action":"Resign"}]', prompt)
        normalized = " ".join(prompt.split())
        self.assertIn("A material deficit in units, gold, villages, or position alone is not proof", normalized)
        self.assertIn("do not resign merely for being behind", normalized)
        with self.assertRaisesRegex(ValueError, "cannot be previewed"):
            validate_preview_request('{"tool":"preview_batch","candidates":[[{"action":"Resign"}]]}')

    @unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
    def test_resignation_ends_after_one_model_call_and_is_preserved_in_history(self):
        for side in (0, 1):
            for incremental in (False, True):
                with self.subTest(side=side, incremental=incremental), tempfile.TemporaryDirectory() as td:
                    directory = Path(td)
                    fixture = directory / "orders.jsonl"
                    fixture.write_text(json.dumps({"text": '[{"action":"Resign"}]'}) + "\n")
                    log = directory / "match.ndjson"
                    command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
                               "--orders-file", str(fixture), "--llm-side", str(side),
                               "--max-turns", "50", "--log", str(log), "--decision-metrics"]
                    if incremental:
                        command.append("--incremental-turns")
                    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    records = [json.loads(line) for line in log.read_text().splitlines()]
                    terminal = records[-1]
                    self.assertEqual(terminal["reason"], "resignation")
                    self.assertEqual(terminal["winner"], 1 - side)
                    self.assertEqual(terminal["resigned_side"], side)
                    self.assertEqual(terminal["terminal_class"], "gameplay")
                    self.assertTrue(terminal["gameplay_valid"])
                    self.assertFalse(terminal["infrastructure_invalid"])
                    self.assertEqual(terminal["model_calls"], 1)
                    self.assertEqual(terminal["side_turns"], side)
                    self.assertFalse(any(r["type"] in {"draft_review", "handoff_review", "batch_validation",
                                                       "final_batch_preview", "turn_boundary"} for r in records))
                    forwarded = next(i for i, r in enumerate(records) if r["type"] == "forwarded_orders")
                    self.assertFalse(any(r["type"] == "driver" and r["line"]["type"] in {"state", "events"}
                                         for r in records[forwarded + 1:]))
                    report = classify(records)
                    self.assertEqual(report["terminal_class"], "gameplay")
                    self.assertEqual(report["completed_side_turns"], side)
                    self.assertEqual(report["resigned_side"], side)
                    self.assertEqual(report["model_end_turns"], 0)
                    self.assertEqual(report["model_turns"], 0)
                    self.assertFalse(report["accounting_mismatch"])
                    conn = open_history(directory / "history.sqlite")
                    try:
                        game_id = import_game(conn, directory)
                        self.assertEqual(conn.execute(
                            "SELECT status,winner_side,termination_reason FROM games WHERE game_id=?",
                            (game_id,)).fetchone(), ("complete", 1 - side, "resignation"))
                        self.assertEqual(conn.execute("SELECT action_type FROM actions").fetchall(), [("Resign",)])
                        self.assertEqual(conn.execute("SELECT count(*) FROM side_turns").fetchone()[0], 0)
                    finally:
                        conn.close()
                    before_resume = log.read_bytes()
                    resumed = subprocess.run(command + ["--resume-log", str(log)], cwd=ROOT,
                                             capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(resumed.returncode, 0)
                    self.assertIn("completed terminal result", resumed.stderr)
                    self.assertEqual(log.read_bytes(), before_resume)
