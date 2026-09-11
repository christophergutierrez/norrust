"""Offline end-to-end checks for focused inspection context and budget retries."""
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


ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get(
    "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))


FOCUSED_BACKEND = r'''import json, os, pathlib, sys
path = pathlib.Path(os.environ["FOCUSED_PROMPTS"])
prompt = sys.stdin.read()
index = len(path.read_text().splitlines()) if path.exists() else 0
with path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"prompt": prompt}) + "\n")
if index == 0:
    response = {"tool": "inspect_units", "unit_ids": [1]}
elif index == 1:
    response = {"actions": [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 1}],
                "decisions": [{"orders": [0], "rules": ["T0"],
                               "expected": "recruit one unit", "risk": "gold"}]}
else:
    response = {"actions": [{"action": "Resign"}],
                "decisions": [{"orders": [0], "rules": ["T0"],
                               "expected": "end the offline fixture", "risk": "none"}]}
print(json.dumps({"text": json.dumps(response, separators=(",", ":"))}))
'''


OUTPUT_RETRY_BACKEND = r'''import json, os, pathlib, sys
context = json.loads(pathlib.Path(os.environ["NORRUST_REQUEST_CONTEXT_FILE"]).read_text())
path = pathlib.Path(os.environ["OUTPUT_RETRY_PROMPTS"])
prompt = sys.stdin.read()
index = len(path.read_text().splitlines()) if path.exists() else 0
with path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"prompt": prompt}) + "\n")
root = pathlib.Path(context["game_log"]).parent
call_id = context["conversation_id"] + ":physical:" + str(index + 1)
usage = ({"input_tokens": 100, "output_tokens": 131072, "total_tokens": 131172}
          if index == 0 else {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110})
sidecar = {"game_id": context["conversation_id"], "call_id": call_id,
           "request_id": context["harness_request_id"], "transport": "offline_fixture",
           "provider": "offline", "status": "dispatched", "record_kind": "dispatch"}
with (root / "usage.ndjson").open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(sidecar) + "\n")
    final = dict(sidecar, **usage, record_kind="final")
    if index == 0:
        final.update(status="failed", error_code="output_limit", finish_reason="length")
    else:
        final.update(status="completed", finish_reason="stop")
    stream.write(json.dumps(final) + "\n")
if index == 0:
    print(json.dumps({"error": {"code": "output_limit", "output_limit": 131072,
                                 "call_id": call_id}, "usage": usage}))
elif index == 1:
    response = {"actions": [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 1}],
                "decisions": [{"orders": [0], "rules": ["T0"],
                               "expected": "recruit after output retry", "risk": "gold"}]}
    print(json.dumps({"text": json.dumps(response, separators=(",", ":")), "usage": usage}))
else:
    response = {"actions": [{"action": "Resign"}],
                "decisions": [{"orders": [0], "rules": ["T0"],
                               "expected": "end after output retry", "risk": "none"}]}
    print(json.dumps({"text": json.dumps(response, separators=(",", ":")), "usage": usage}))
'''


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class FocusedContextDriverTests(unittest.TestCase):
    def test_inspection_followup_is_revision_pinned_and_expires_after_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend.py"
            backend.write_text(FOCUSED_BACKEND)
            prompt_log = root / "prompts.ndjson"
            log = root / "match.ndjson"
            result = subprocess.run(
                [sys.executable, "-m", "tools.llm_client",
                 "--driver", str(DRIVER),
                 "--model-command", shlex.join([sys.executable, str(backend)]),
                 "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "100", "--seed", "9211",
                 "--llm-side", "0", "--max-turns", "1", "--incremental-turns",
                 "--decision-mode", "focused", "--max-partial-batches-per-turn", "5",
                 "--disable-agenda-sweep", "--player-model", "offline-fixture",
                 "--log", str(log), "--query-budget-seconds", "10",
                 "--model-timeout", "10", "--turn-timeout", "30"],
                cwd=ROOT, capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONPATH": str(ROOT),
                     "FOCUSED_PROMPTS": str(prompt_log)},
            )
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            prompts = [item["prompt"] for item in records(prompt_log)]
            self.assertEqual(len(prompts), 3)

            first, followup, after_partial = prompts
            self.assertNotIn("FOCUSED_LOCAL_CONTEXT_BEGIN", first)
            self.assertEqual(followup.count("FOCUSED_LOCAL_CONTEXT_BEGIN"), 1)
            self.assertIn("FOCUSED_LOCAL_CONTEXT_BEGIN revision=0 tool=inspect_units selected=[1]", followup)
            self.assertIn("facts=type:Dark Sorcerer hp:48/48", followup)
            self.assertIn('weapons:[{"damage":4,"name":"staff"', followup)
            self.assertIn("move_destinations=", followup)
            self.assertIn("attack_options=", followup)
            self.assertNotIn("FOCUSED_LOCAL_CONTEXT_BEGIN", after_partial)
            self.assertIn("revision=1 controlled_side=0", after_partial)

            rows = records(log)
            requests = [row for row in rows if row.get("type") == "model_request"]
            self.assertEqual(len(requests), 3)
            self.assertEqual(
                [row["raw_output"] for row in requests],
                [json.dumps({"tool": "inspect_units", "unit_ids": [1]}, separators=(",", ":")),
                 json.dumps({"actions": [{"action": "RecruitBatch", "def_id": "Skeleton", "count": 1}],
                             "decisions": [{"orders": [0], "rules": ["T0"],
                                            "expected": "recruit one unit", "risk": "gold"}]}, separators=(",", ":")),
                 json.dumps({"actions": [{"action": "Resign"}],
                             "decisions": [{"orders": [0], "rules": ["T0"],
                                            "expected": "end the offline fixture", "risk": "none"}]}, separators=(",", ":"))],
            )
            query_names = [row["line"].get("what") for row in rows if row.get("type") == "query"]
            self.assertEqual(query_names.count("inspect_unit"), 1)
            self.assertNotIn("inspect_target", query_names)
            self.assertNotIn("inspect_targets", query_names)
            self.assertEqual(
                [row["orders"][0]["action"] for row in rows if row.get("type") == "forwarded_orders"],
                ["RecruitBatch", "Resign"],
            )

    def test_output_limit_retry_reuses_exact_prompt_and_budget_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend.py"
            backend.write_text(OUTPUT_RETRY_BACKEND)
            prompt_log = root / "prompts.ndjson"
            log = root / "match.ndjson"
            result = subprocess.run(
                [sys.executable, "-m", "tools.llm_client",
                 "--driver", str(DRIVER),
                 "--model-command", shlex.join([sys.executable, str(backend)]),
                 "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "100", "--seed", "9211",
                 "--llm-side", "0", "--max-turns", "1", "--incremental-turns",
                 "--decision-mode", "focused", "--disable-agenda-sweep",
                 "--player-model", "offline-fixture", "--max-game-total-tokens", "1000000",
                 "--log", str(log), "--query-budget-seconds", "10",
                 "--model-timeout", "10", "--turn-timeout", "30"],
                cwd=ROOT, capture_output=True, text=True, timeout=60,
                env={**os.environ, "PYTHONPATH": str(ROOT),
                     "OUTPUT_RETRY_PROMPTS": str(prompt_log)},
            )
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            prompts = [item["prompt"] for item in records(prompt_log)]
            self.assertEqual(len(prompts), 3)
            self.assertEqual(prompts[0].encode(), prompts[1].encode())
            self.assertEqual(hashlib.sha256(prompts[0].encode()).hexdigest(),
                             hashlib.sha256(prompts[1].encode()).hexdigest())
            budget = (
                "GAME_BUDGET_CONTEXT_BEGIN\n"
                "configured_ceiling=1000000 known_measured_spend=0 "
                "remaining_allowance=1000000 (upper_bound; usage_unknown) "
                "coverage=bounded_unknown unknown_calls=0 sidecar_gaps=0\n"
                "GAME_BUDGET_CONTEXT_END\n"
            )
            self.assertIn(budget, prompts[0])
            self.assertEqual(prompts[0].count("GAME_BUDGET_CONTEXT_BEGIN"), 1)
            self.assertIn(
                "known_measured_spend=131282 remaining_allowance=868718 coverage=measured",
                prompts[2],
            )
            self.assertNotEqual(prompts[0], prompts[2])
            rows = records(log)
            self.assertEqual(sum(row.get("type") == "model_output_limit" for row in rows), 1)
            completed = [row for row in rows if row.get("type") == "model_request"
                         and row.get("status") == "completed"]
            self.assertEqual(len(completed), 2)
            self.assertEqual(completed[0]["prompt_bytes"], len(prompts[0].encode()))
            self.assertEqual(completed[1]["prompt_bytes"], len(prompts[2].encode()))
            usage_rows = records(root / "usage.ndjson")
            self.assertEqual(len(usage_rows), 6)
            self.assertEqual(
                sum(row.get("total_tokens", 0) for row in usage_rows if row.get("record_kind") == "final"),
                131392,
            )


if __name__ == "__main__":
    unittest.main()
