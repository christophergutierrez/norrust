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

from .llm_client import prompt_regions


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


SCENARIO_BACKEND = r'''import json, os, pathlib, sys
scenario = os.environ["FOCUSED_SCENARIO"]
path = pathlib.Path(os.environ["FOCUSED_PROMPTS"])
prompt = sys.stdin.read()
index = len(path.read_text().splitlines()) if path.exists() else 0
with path.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({"prompt": prompt}) + "\n")
inspect = {"tool": "inspect_units", "unit_ids": [1]}
preview = {"tool": "preview_batch", "candidates": [[{"action": "EndTurn"}]]}
if scenario == "preview":
    response = inspect if index == 0 else preview if index == 1 else {"actions": [{"action": "Resign"}]}
elif scenario == "unavailable":
    response = inspect if index == 0 else ({"tool": "inspect_target", "unit_id": 999999}
                                           if index == 1 else {"actions": [{"action": "Resign"}]})
elif scenario == "rollback":
    response = (inspect if index == 0 else
                {"actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 7}]} if index == 1 else
                inspect if index == 2 else {"actions": [{"action": "EndTurn"}]})
elif scenario == "rollback_unavailable":
    response = (inspect if index == 0 else
                {"actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 7}]} if index == 1 else
                {"tool": "inspect_target", "unit_id": 999999} if index == 2 else
                {"actions": [{"action": "EndTurn"}]})
else:  # malformed action repair while a local inspection is active
    response = (inspect if index == 0 else
                {"actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 7}]} if index == 1 else
                {"actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 7}]} if index == 2 else
                {"actions": [{"action": "EndTurn"}]})
print(json.dumps({"text": json.dumps(response, separators=(",", ":"))}))
'''


def records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class FocusedContextDriverTests(unittest.TestCase):
    def run_scenario(self, scenario: str) -> tuple[list[dict], list[dict]]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend.py"
            backend.write_text(SCENARIO_BACKEND)
            prompt_log = root / "prompts.ndjson"
            log = root / "match.ndjson"
            result = subprocess.run(
                [sys.executable, "-m", "tools.llm_client", "--driver", str(DRIVER),
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
                     "FOCUSED_PROMPTS": str(prompt_log), "FOCUSED_SCENARIO": scenario},
            )
            self.assertEqual(result.returncode, 0, result.stderr + log.read_text())
            return records(prompt_log), records(log)

    def test_local_preview_followup_keeps_actual_preview_result(self):
        prompts, rows = self.run_scenario("preview")
        self.assertEqual(len(prompts), 3)
        preview_prompt = prompts[2]["prompt"]
        self.assertEqual(preview_prompt.count("FOCUSED_LOCAL_CONTEXT_BEGIN"), 1)
        self.assertIn("TOOL_RESULT_UNTRUSTED_DATA_BEGIN tool=preview_batch", preview_prompt)
        self.assertIn("SIMULATION", preview_prompt)
        self.assertEqual(sum(row.get("type") == "batch_preview" for row in rows), 1)

    def test_unavailable_new_inspection_clears_old_local_view(self):
        prompts, rows = self.run_scenario("unavailable")
        self.assertEqual(len(prompts), 3)
        first_local, unavailable = prompts[1]["prompt"], prompts[2]["prompt"]
        self.assertIn("FOCUSED_LOCAL_CONTEXT_BEGIN", first_local)
        self.assertNotIn("FOCUSED_LOCAL_CONTEXT_BEGIN", unavailable)
        self.assertIn("TARGET unavailable", unavailable)
        self.assertEqual(sum(row.get("available") is False for row in rows
                             if row.get("type") == "focused_context"), 1)

    def test_validation_rollback_reinspection_reuses_live_revision(self):
        prompts, rows = self.run_scenario("rollback")
        self.assertEqual(len(prompts), 4)
        self.assertEqual([prompt["prompt"].count("FOCUSED_LOCAL_CONTEXT_BEGIN")
                          for prompt in prompts], [0, 1, 1, 1])
        local_prompts = [item["prompt"] for item in prompts[1:]]
        self.assertTrue(all("revision=0" in item for item in local_prompts))
        self.assertEqual(sum(row.get("tool") == "inspect_units" for row in rows
                             if row.get("type") == "tool_result"), 2)
        self.assertEqual([row["orders"][0]["action"] for row in rows
                          if row.get("type") == "forwarded_orders"], ["EndTurn"])

    def test_validation_unavailable_reinspection_clears_local_view(self):
        prompts, rows = self.run_scenario("rollback_unavailable")
        self.assertEqual(len(prompts), 4)
        self.assertEqual([prompt["prompt"].count("FOCUSED_LOCAL_CONTEXT_BEGIN")
                          for prompt in prompts], [0, 1, 1, 0])
        self.assertIn("TARGET unavailable", prompts[3]["prompt"])
        self.assertEqual(sum(row.get("available") is False for row in rows
                             if row.get("type") == "focused_context"), 1)
        self.assertEqual([row["orders"][0]["action"] for row in rows
                          if row.get("type") == "forwarded_orders"], ["EndTurn"])

    def test_action_repairs_do_not_reappend_stale_inspection_copies(self):
        prompts, rows = self.run_scenario("malformed")
        self.assertEqual(len(prompts), 4)
        for item in prompts[1:]:
            prompt = item["prompt"]
            self.assertEqual(prompt.count("FOCUSED_LOCAL_CONTEXT_BEGIN"), 1)
            self.assertEqual(prompt.count("MODEL_TOOL_REQUEST_UNTRUSTED_DATA_BEGIN"), 0)
        self.assertEqual(sum(row.get("type") == "action_repair" for row in rows), 2)
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
            self.assertIn("LOCAL_LIVE_ROWS_UNTRUSTED_DATA_BEGIN", followup)
            self.assertIn('"id":1', followup)
            self.assertIn('"position":[2,7]', followup)
            self.assertIn('"moved":false', followup)
            self.assertIn("LOCAL_VILLAGES_UNTRUSTED_DATA_BEGIN", followup)
            self.assertIn("move_destinations=", followup)
            self.assertIn("attack_options=", followup)
            self.assertIn('"local_guardrails"', followup)
            self.assertIn('"pending_promotions"', followup)
            self.assertIn('"local_execution"', followup)
            self.assertEqual(prompt_regions(first)["fixed_prefix_sha256"],
                             prompt_regions(followup)["fixed_prefix_sha256"])
            # The old path resent the full prompt and appended the same raw
            # inspection result. Use the recorded rendered-result bytes plus
            # the actual request/block framing to model that exact dynamic
            # shape, with the same followup instruction on both prompts.
            rows = records(log)
            inspection_bytes = next(row["result_bytes"] for row in rows
                                    if row.get("type") == "tool_result"
                                    and row.get("tool") == "inspect_units")
            request_text = json.dumps(
                {"tool": "inspect_units", "unit_ids": [1]}, separators=(",", ":"))
            rendered_placeholder = "x" * inspection_bytes
            old_tool_context = (
                "\nMODEL_TOOL_REQUEST_UNTRUSTED_DATA_BEGIN:\n" + request_text +
                "\nMODEL_TOOL_REQUEST_UNTRUSTED_DATA_END\n" +
                "TOOL_RESULT_UNTRUSTED_DATA_BEGIN tool=inspect_units\n" +
                rendered_placeholder + "\nTOOL_RESULT_UNTRUSTED_DATA_END\n")
            instruction_start = followup.index("\nBUDGETS ")
            same_followup_instruction = followup[instruction_start:]
            # Strip the initial dispatch's budget/footer before reusing the
            # followup's suffix. Counting both would exaggerate the savings.
            full_base = first.split("\nGAME_BUDGET_CONTEXT_BEGIN\n", 1)[0]
            legacy_followup = full_base + old_tool_context + same_followup_instruction
            self.assertEqual(legacy_followup.count("AUTHORITATIVE_LIVE_STATE_BEGIN"), 1)
            self.assertEqual(legacy_followup.count("GAME_BUDGET_CONTEXT_BEGIN"), 1)
            legacy_bytes = len(legacy_followup.encode())
            self.assertLess(len(followup.encode()), legacy_bytes,
                            "local=%d legacy_full_followup=%d (rendered_result=%d)" %
                            (len(followup.encode()), legacy_bytes, inspection_bytes))
            self.assertNotIn('"tactical_surface"', followup[followup.index("BOARD_UNTRUSTED_DATA_BEGIN:"):])
            self.assertNotIn("FOCUSED_LOCAL_CONTEXT_BEGIN", after_partial)
            self.assertIn("revision=1 controlled_side=0", after_partial)

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
