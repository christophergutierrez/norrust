import argparse
import json
import tempfile
import unittest
from unittest import mock

from . import llm_client


class FakeDriverProcess:
    def __init__(self, lines):
        self.stdin = tempfile.SpooledTemporaryFile(mode="w+", max_size=1024 * 1024)
        self.stdout = tempfile.SpooledTemporaryFile(mode="w+", max_size=1024 * 1024)
        self.stdout.write("".join(json.dumps(line) + "\n" for line in lines))
        self.stdout.seek(0)
        self.stderr = tempfile.SpooledTemporaryFile(mode="w+", max_size=1024 * 1024)

    def poll(self):
        return 0

    def terminate(self):
        pass


def run_with_orders(order_texts, driver_lines):
    with tempfile.TemporaryDirectory() as directory:
        log_path = directory + "/client.jsonl"
        orders_path = directory + "/orders.jsonl"
        with open(orders_path, "w") as orders:
            for text in order_texts:
                orders.write(json.dumps({"text": text}) + "\n")
        args = argparse.Namespace(
            driver="driver", scenario="scenario", faction0="a", faction1="b",
            gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
            query_budget_seconds=5, max_queries_per_turn=6,
            no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
            model_command=None, model_timeout=7, log=log_path,
            max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
            token_output_limit=None, token_total_limit=None,
            validate_before_submit=False, incremental_turns=False,
            max_model_calls_per_turn=4, max_tool_calls_per_turn=4,
            reasoning_effort=None, timeout_finish=False,
        )
        process = FakeDriverProcess(driver_lines)
        try:
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = llm_client.run(args)
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
        with open(log_path) as log:
            records = [json.loads(raw) for raw in log]
    return code, records


def state_with_units(active_side=0):
    return {
        "active_faction": active_side,
        "units": [
            {"id": 2, "faction": 0, "can_recruit": True, "hp": 10, "max_hp": 10},
            {"id": 3, "faction": 0, "can_recruit": False, "hp": 10, "max_hp": 10},
            {"id": 4, "faction": 0, "can_recruit": False, "hp": 10, "max_hp": 10},
            {"id": 9, "faction": 1, "can_recruit": True, "hp": 10, "max_hp": 10},
        ],
        "tactical_surface": {"recruitment": {}, "exposure": {}},
    }


class HandoffPromptTests(unittest.TestCase):
    def test_selective_audit_uses_observed_friendly_ids_and_recruiter_subset(self):
        audit = llm_client.handoff_audit(
            state_with_units(),
            [{"action": "FinishWithGreedy",
              "groups": [{"mode": "greedy", "unit_ids": [2, 3]}],
              "holds": [{"unit_id": 4, "reason": "guard"}]}],
            {"available": set()},
        )
        self.assertEqual(audit["boundary_kind"], "selective")
        self.assertEqual(audit["delegated"], [2, 3])
        self.assertEqual(audit["held"], [4])
        self.assertEqual(audit["omitted"], [])
        self.assertEqual(audit["omitted_scope"], "observed_friendly")
        self.assertEqual(audit["delegated_recruiters"], [2])

    def test_audit_ignores_intent_and_agenda_text_and_enemy_units(self):
        state = state_with_units()
        state["intent"] = "hold every unit and delegate enemy U9"
        state["agenda"] = {"holds": [2], "tasks": []}
        audit = llm_client.handoff_audit(
            state,
            [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
            {"available": set()},
        )
        self.assertEqual(audit["delegated"], [])
        self.assertEqual(audit["held"], [])
        self.assertEqual(audit["omitted"], [2, 3, 4])
        self.assertNotIn(9, audit["omitted"])
        self.assertEqual(audit["delegated_recruiters"], [])

    def test_selective_audit_filters_for_controlled_side_one(self):
        state = state_with_units(1)
        audit = llm_client.handoff_audit(
            state,
            [{"action": "FinishWithGreedy", "groups": [],
              "holds": [{"unit_id": 9, "reason": "keep"}]}],
            {"available": set()},
        )
        self.assertEqual(audit["held"], [9])
        self.assertEqual(audit["omitted"], [])
        self.assertEqual(audit["delegated_recruiters"], [])

    def test_nonselective_boundaries_do_not_infer_delegation(self):
        state = state_with_units()
        for orders, kind in (
            ([{"action": "EndTurn"}], "implicit_end_turn"),
            ([{"action": "DoneWithImportantMoves"}], "explicit_done"),
            ([{"action": "Move", "unit_id": 3, "col": 1, "row": 1}], "partial"),
            ([{"action": "Resign"}], "resign"),
        ):
            audit = llm_client.handoff_audit(state, orders, {"available": set()})
            self.assertEqual(audit["boundary_kind"], kind)
            self.assertIsNone(audit["omitted"])
            self.assertEqual(audit["omitted_scope"], "not_applicable")
            self.assertIsNone(audit["delegated_recruiters"])

    def test_draft_review_labels_boundary_facts_and_safety_limits(self):
        audit = llm_client.handoff_audit(
            state_with_units(),
            [{"action": "FinishWithGreedy", "groups": [{"mode": "greedy", "unit_ids": [2]}],
              "holds": [{"unit_id": 4, "reason": "guard"}]}],
            {"available": set()},
        )
        rendered, _ = llm_client.compact_draft_review(
            {"candidates": [{"valid": True, "recruiter_threats": {"recruiters": []}}]},
            False, audit=audit,
        )
        self.assertIn("HANDOFF boundary=selective", rendered)
        self.assertIn("omitted=U3 scope=observed_friendly", rendered)
        self.assertIn("delegated_recruiters=U2", rendered)
        self.assertIn("not predictions of final positions", rendered)
        self.assertIn("not a safety certificate", rendered)

    def test_empty_selective_categories_render_as_dash(self):
        for holds in ([], [{"unit_id": unit, "reason": "guard"} for unit in (2, 3, 4)]):
            audit = llm_client.handoff_audit(
                state_with_units(),
                [{"action": "FinishWithGreedy", "groups": [], "holds": holds}],
                {"available": set()},
            )
            rendered, _ = llm_client.compact_draft_review(
                {"candidates": [{"valid": True, "recruiter_threats": {"recruiters": []}}]},
                False, audit=audit,
            )
            self.assertIn("omitted=-" if holds else "omitted=U2,U3,U4", rendered)
            self.assertIn("delegated=-", rendered)
            self.assertIn("delegated_recruiters=-", rendered)

    def test_post_submit_repair_forwards_audit_for_repaired_orders(self):
        def response(intent, orders):
            return json.dumps({"actions": orders, "intent": intent, "decisions": [
                {"orders": list(range(len(orders))), "rules": ["T7"],
                 "expected": intent, "risk": "repair may change positions."}]})

        initial = response("draft", [{"action": "FinishWithGreedy",
                                      "groups": [{"mode": "greedy", "unit_ids": [2]}],
                                      "holds": []}])
        repaired = response("repaired", [{"action": "FinishWithGreedy",
                                           "groups": [{"mode": "greedy", "unit_ids": [3]}],
                                           "holds": [{"unit_id": 2, "reason": "keep"}]}])
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 7,
             "units": state_with_units()["units"]},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "status", "ok": True,
             "results": [{"ok": False, "code": "MoveError", "message": "blocked"}]},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=False):
            code, records = run_with_orders([initial, repaired], lines)
        self.assertEqual(code, 0)
        forwarded = [record for record in records if record.get("type") == "forwarded_orders"]
        self.assertEqual(len(forwarded), 2)
        final = forwarded[-1]
        self.assertEqual(final["orders"], [{"action": "FinishWithGreedy",
            "groups": [{"mode": "greedy", "unit_ids": [3]}],
            "holds": [{"unit_id": 2, "reason": "keep"}]}])
        self.assertEqual(forwarded[0]["handoff_audit"]["delegated_recruiters"], [2])
        self.assertEqual(final["handoff_audit"]["boundary_kind"], "selective")
        self.assertEqual(final["handoff_audit"]["delegated"], [3])
        self.assertEqual(final["handoff_audit"]["held"], [2])
        self.assertEqual(final["handoff_audit"]["omitted"], [4])
        self.assertEqual(final["handoff_audit"]["delegated_recruiters"], [])


if __name__ == "__main__":
    unittest.main()
