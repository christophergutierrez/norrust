"""End-to-end decision-annotation checks.

These tests deliberately use the checked-in Rust driver and the public client
entry point.  The backend is a tiny deterministic model substitute: it receives
the real prompt and returns one annotated batch, so the assertions cover the
prompt/log/SQLite boundaries rather than parser helpers in isolation.
"""
from __future__ import annotations

import json
import os
import hashlib
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from .game_history import import_game, open_history
from .game_training_export import export
from .match_report import classify
from .decision_annotations import guide_hash


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core" / "target" / "debug" / "greedy_driver"))


def _backend(path: Path, response: object) -> None:
    """Write a backend that proves it received a substantial canonical prompt."""
    payload = json.dumps(response, ensure_ascii=False)
    path.write_text(
        "import json,sys\n"
        "prompt=sys.stdin.read()\n"
        "assert len(prompt)>1000\n"
        f"print(json.dumps({{'text': {payload!r}, 'usage': {{'input_tokens': 1, 'output_tokens': 1}}}}))\n",
        encoding="utf-8",
    )


def _run(root: Path, response: object) -> tuple[Path, int]:
    backend = root / "backend.py"
    log = root / "match.ndjson"
    _backend(backend, response)
    if not DRIVER.is_file():
        raise unittest.SkipTest("build greedy_driver before running integration tests")
    command = [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
               "--model-command", f"{sys.executable} {backend}",
               "--scenario", "big_battle_6", "--faction0", "undead",
               "--faction1", "undead", "--gold", "300", "--seed", "9101",
               "--llm-side", "0", "--max-turns", "1", "--log", str(log),
               "--disable-agenda-sweep", "--query-budget-seconds", "10",
               "--model-timeout", "10", "--turn-timeout", "30"]
    result = subprocess.run(command, cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=45)
    return log, result.returncode


class DecisionAnnotationIntegrationTests(unittest.TestCase):
    def test_real_driver_valid_annotation_reaches_catalog_and_export(self):
        response = {"actions": [{"action": "Move", "unit_id": 1, "col": 3, "row": 7},
                                 {"action": "EndTurn"}],
                    "decisions": [{"orders": [0, 1], "rules": ["S1"],
                                   "expected": "Preserve the force while the opponent closes.",
                                   "risk": "A passive turn can surrender ground."}]}
        with tempfile.TemporaryDirectory() as td:
            log, code = _run(Path(td), response)
            self.assertEqual(code, 0, Path(log).read_text()[-1000:])
            records = [json.loads(line) for line in log.read_text().splitlines()]
            forwarded = next(r for r in records if r.get("type") == "forwarded_orders")
            request = next(r for r in records if r.get("type") == "model_request"
                           and r.get("request_id") == forwarded.get("request_id"))
            self.assertGreater(request.get("prompt_bytes", 0), 1000)
            self.assertEqual(forwarded["orders"], response["actions"])
            self.assertIsInstance(forwarded.get("request_id"), str)
            self.assertEqual(forwarded["request_id"], request["request_id"])
            annotation = forwarded["decision_annotation"]
            self.assertEqual(annotation, request["decision_annotation"])
            self.assertEqual(annotation.get("status"), "valid")
            self.assertEqual(annotation["decisions"][0]["rules"], ["S1"])
            self.assertIsInstance(annotation.get("guide_hash"), str)
            self.assertEqual(annotation["guide_hash"], guide_hash(Path(ROOT / "docs" / "LLM_TACTICAL_PLAYBOOK.md").read_text(encoding="utf-8")))
            self.assertIn((ROOT / "docs/LLM_TACTICAL_PLAYBOOK.md").read_text(), request["prompt"])
            states = [r["line"] for r in records if r.get("type") == "driver"
                      and isinstance(r.get("line"), dict) and r["line"].get("type") == "state"]
            self.assertTrue(states and isinstance(states[0].get("state_revision"), int))
            self.assertEqual(request["state_revision"], states[0]["state_revision"])
            events = [event for r in records if r.get("type") == "driver"
                      and isinstance(r.get("line"), dict) and r["line"].get("type") == "events"
                      for event in r["line"].get("events", [])]
            self.assertTrue(any(event.get("kind") == "move" and event.get("unit") == 1 for event in events))
            report = classify(records)
            self.assertEqual(report.get("decision_annotations", {}).get("coverage"), 1.0)

            conn = open_history(Path(td) / "history.sqlite")
            game_id = import_game(conn, log)
            row = conn.execute("SELECT request_id, prompt_blob, response_blob, annotation_status, state_revision, reasoning_blob, reasoning_kind FROM model_requests WHERE request_id=?", (request["request_id"],)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], request["request_id"])
            self.assertTrue(row[1] and row[2] and row[5])
            self.assertEqual(row[3], "valid")
            self.assertEqual(row[6], "decision_annotation_v1")
            batch = conn.execute("SELECT request_id,before_revision FROM action_batches WHERE game_id=?", (game_id,)).fetchone()
            self.assertEqual(batch[0], request["request_id"])
            action = conn.execute("SELECT request_id,authored_order_index,before_revision,after_revision FROM actions WHERE game_id=? ORDER BY authored_order_index", (game_id,)).fetchall()
            self.assertEqual([row[0] for row in action], [request["request_id"]] * 2)
            self.assertEqual([row[1] for row in action], [0, 1])
            self.assertEqual(batch[1], forwarded["state_revision"])
            self.assertEqual(batch[1], states[0]["state_revision"])
            self.assertEqual(json.loads(conn.execute("SELECT submitted_orders_json FROM action_batches WHERE game_id=?", (game_id,)).fetchone()[0]), response["actions"])
            action_json = [json.loads(row[0]) for row in conn.execute("SELECT action_json FROM actions WHERE game_id=? ORDER BY authored_order_index", (game_id,))]
            self.assertEqual(action_json, response["actions"])
            stored_request = conn.execute("SELECT prompt_blob,response_blob,prompt_hash,response_hash,state_revision FROM model_requests WHERE request_id=?", (request["request_id"],)).fetchone()
            self.assertEqual(zlib.decompress(stored_request[0]).decode(), request["prompt"])
            self.assertEqual(zlib.decompress(stored_request[1]).decode(), request["raw_output"])
            self.assertEqual(stored_request[2], hashlib.sha256(request["prompt"].encode()).hexdigest())
            self.assertEqual(stored_request[3], hashlib.sha256(request["raw_output"].encode()).hexdigest())
            self.assertEqual(stored_request[4], batch[1])
            counts_before = [conn.execute(f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)).fetchone()[0]
                             for table in ("model_requests", "action_batches", "actions")]
            import_game(conn, log, game_id=game_id)
            import_game(conn, log, game_id=game_id)
            counts_after = [conn.execute(f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)).fetchone()[0]
                            for table in ("model_requests", "action_batches", "actions")]
            self.assertEqual(counts_before, counts_after)
            self.assertEqual(conn.execute(
                "SELECT prompt_blob,response_blob,prompt_hash,response_hash,state_revision FROM model_requests WHERE request_id=?",
                (request["request_id"],)).fetchone(), stored_request)
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.execute("INSERT INTO evaluation_runs(evaluation_run_id,config_json) VALUES('approved','{}')")
            conn.execute("INSERT INTO decision_evaluations(evaluation_run_id,request_id,verdict,reason_codes_json,metrics_json,evidence_json) VALUES('approved',?,'approve','[]','{}','{}')", (request["request_id"],))
            out = export(conn, str(Path(td) / "export"), "approved", rationale=True)
            self.assertEqual(out["count"], 1)
            exported = [json.loads(line) for line in (Path(td) / "export" / "train.jsonl").read_text().splitlines()]
            if not exported:
                exported = [json.loads(line) for split in ("validation", "test") for line in (Path(td) / "export" / f"{split}.jsonl").read_text().splitlines()]
            self.assertEqual(exported[0]["rationale"], json.dumps(annotation, sort_keys=True, separators=(",", ":")))
            conn.close()

    def test_missing_and_invalid_annotations_execute_without_invented_rationale(self):
        for response, expected_status in (
                ([{"action": "EndTurn"}], "missing"),
                ({"actions": [{"action": "EndTurn"}], "decisions":
                 [{"orders": [0], "rules": [{"bad": True}], "expected": "x", "risk": "y"}]}, "invalid")):
            with self.subTest(expected_status=expected_status), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                log, code = _run(root, response)
                self.assertEqual(code, 0, Path(log).read_text()[-1000:])
                records = [json.loads(line) for line in log.read_text().splitlines()]
                requests = [r for r in records if r.get("type") == "model_request"]
                self.assertLessEqual(len(requests), 2)
                self.assertFalse(any(r["type"] in {"repair", "action_repair", "draft_review_repair"}
                                     for r in records))
                self.assertTrue(all(r.get("status") == "completed" for r in requests))
                forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
                self.assertEqual(len(forwarded), 1)
                self.assertEqual(forwarded[0]["decision_annotation"]["status"], expected_status)
                report = classify(records)
                annotations = report["decision_annotations"]
                self.assertEqual(annotations[f"{expected_status}_batches"], 1)
                self.assertEqual(annotations["valid_batches"], 0)
                self.assertEqual(annotations["coverage"], 0.0)
                conn = open_history(root / "history.sqlite")
                game_id = import_game(conn, log)
                row = conn.execute("SELECT annotation_status, reasoning_blob FROM model_requests WHERE request_id=?", (forwarded[0]["request_id"],)).fetchone()
                self.assertEqual(row[0], expected_status)
                self.assertIsNone(row[1])
                conn.execute("INSERT INTO evaluation_runs(evaluation_run_id,config_json) VALUES('negative','{}')")
                conn.execute("INSERT INTO decision_evaluations(evaluation_run_id,request_id,verdict,reason_codes_json,metrics_json,evidence_json) VALUES('negative',?,'approve','[]','{}','{}')", (forwarded[0]["request_id"],))
                self.assertEqual(export(conn, str(root / "export"), "negative", rationale=True)["count"], 0)
                conn.close()


if __name__ == "__main__":
    unittest.main()
