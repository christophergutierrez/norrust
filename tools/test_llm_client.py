import argparse
import hashlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import llm_client
from . import action_choices as ac
from .decision_annotations import annotation_for_response, validate_decisions
from .llm_client import (
    ENGINE_RULES,
    TERMINAL_EXIT_CODES, TERMINAL_GAMEPLAY, TERMINAL_INFRASTRUCTURE,
    TERMINAL_BUDGET_INTERRUPTED,
    TERMINAL_MODEL_INVALID, ModelReply, classify_terminal, enforce_usage,
    compact_batch_preview, compact_hex_inspection, compact_observation,
    compact_target_inspection, compact_tactical_surface, compact_spatial_map, prompt_for, query_options,
    authoritative_live_state_reminder, finalize_model_prompt,
    compact_unit_inspection, compact_draft_review, tool_followup_instruction, tool_budget_repair_prompt,
    compact_events, compact_trend, tactical_attack_coverage, build_current_turn_readiness,
    replay_accepted_progress, update_committed_progress,
    select_event_window,
    query_tactical_surface, query_validate_batch, query_preview_batch, query_bounded_comparison,
    CandidateQueryError, CANDIDATE_QUERY_ERROR_CLASSES,
    resolved_driver_hash,
    query_inspect_target, query_inspect_targets, query_inspect_hex, run,
    response_intent, compact_strategic_briefing,
    checkpoint_dir_for_log, validate_checkpoint_reference, select_resume_checkpoint,
    load_resume_checkpoint,
    validate_inspect_target_request, validate_inspect_targets_request,
    validate_inspect_hex_request, validate_orders, validate_preview_request,
    timeout_finish_orders,
)
from .response_parsing import recover_bare_tool_prefix


class FakeDriverProcess:
    def __init__(self, lines):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("".join(
            line if isinstance(line, str) else json.dumps(line) + "\n" for line in lines
        ))
        self.stderr = io.StringIO()

    def poll(self):
        return 0

    def terminate(self):
        raise AssertionError("completed driver must not be terminated")


class ClientValidationTests(unittest.TestCase):

    def test_recovery_classifies_only_a_leading_complete_tool_prefix(self):
        raw = '{"tool":"inspect_units","unit_ids":[12]} I inspected the unit.'
        with self.assertRaises(ValueError):
            llm_client.parse_action_response(raw)
        self.assertEqual(recover_bare_tool_prefix(raw), {"tool": "inspect_units", "unit_ids": [12]})
        self.assertIsNone(recover_bare_tool_prefix('Rationale {"tool":"inspect_units","unit_ids":[12]}'))
        self.assertIsNone(recover_bare_tool_prefix('{"tool": ["inspect_units"], "unit_ids":[12]} rationale'))

    def test_fenced_tool_with_extra_keys_still_uses_strict_shape_repair(self):
        fenced = "before\n```json\n{" + '"tool":"inspect_hex","col":1,"row":2,"phase":"current","intent":"oops"' + "}\n```\nafter"
        parsed = llm_client.parse_action_response(fenced)
        self.assertEqual(parsed["tool"], "inspect_hex")
        self.assertEqual(llm_client.tool_request_name(parsed), "inspect_hex")

    def test_double_malformed_inspection_repair_never_dispatches_twice(self):
        malformed = '{"tool":"inspect_hex","col":2,"row":7,"phase":"current"} rationale'
        code, records = self.run_with_orders(
            [malformed, malformed],
            [{"type": "state", "active_faction": 0, "state_revision": 7, "units": []},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {}}],
            max_model_calls_per_turn=4, max_tool_calls_per_turn=4, return_records=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        self.assertEqual(records[-1]["terminal_class"], TERMINAL_MODEL_INVALID)
        self.assertEqual(records[-1]["code"], "action_validation_invalid")
        self.assertEqual([r for r in records if r.get("type") == "tool_result"], [])
        self.assertNotIn("inspect_hex", [r.get("line", {}).get("what") for r in records
                                          if r.get("type") == "query"])

    def test_preview_preserves_envelope_origin_revision_for_draft_rendering(self):
        body = {"candidates": [{"valid": True}]}
        result = query_preview_batch(
            lambda request: {"ok": True, "state_revision": 137, "body": body},
            [[{"action": "EndTurn"}]], 137)
        self.assertEqual(result["state_revision"], 137)
        self.assertNotIn("state_revision", body)

    def test_preview_accepts_each_complete_finish_kind_once(self):
        for finish in ("DoneWithImportantMoves", "EndTurn", "FinishWithGreedy"):
            action = {"action": finish}
            if finish == "FinishWithGreedy":
                action.update(groups=[], holds=[])
            request = json.dumps({"tool": "preview_batch", "candidates": [[action]]})
            self.assertEqual(llm_client.validate_preview_request(request), [[action]])
        with self.assertRaisesRegex(ValueError, "exactly one final turn boundary"):
            llm_client.validate_preview_request(
                '{"tool":"preview_batch","candidates":[[{"action":"MoveGroupToward","unit_ids":[1],"col":1,"row":1}]]}')

    def test_draft_rationale_is_bounded_and_marks_absence(self):
        absent = llm_client.draft_rationale_block()
        self.assertIn("DRAFT_RATIONALE_UNTRUSTED_DATA_BEGIN", absent)
        self.assertIn('"intent":"absent"', absent)
        self.assertIn('"status":"absent"', absent)
        annotation = {"status": "valid", "guide_version": "tactics-v1",
                      "decisions": [{"orders": [0], "rules": ["T7"],
                                      "expected": "x" * 240, "risk": "y" * 240}]
                      }
        rendered = llm_client.draft_rationale_block("focus", annotation)
        self.assertLessEqual(len(rendered.encode()), 16 * 1024)
        self.assertIn('"intent":"focus"', rendered)
        malformed = llm_client.draft_rationale_block(
            "é" * 5000, {"status": "s" * 100000, "error": "e" * 100000})
        self.assertLessEqual(len(malformed.encode()), 16 * 1024)
        self.assertIn('"truncated":true', malformed)
        dense = {"status": "valid", "guide_version": "tactics-v1",
                 "guide_hash": "h" * 64,
                 "decisions": [{"orders": [index], "rules": ["T7"],
                                 "expected": "é" * 120, "risk": "ß" * 120}
                                for index in range(16)]}
        dense_rendered = llm_client.draft_rationale_block("é" * 256, dense)
        self.assertLessEqual(len(dense_rendered.encode()), 16 * 1024)
        self.assertIn('"status":"valid"', dense_rendered)
        self.assertIn('"expected":"ééé', dense_rendered)
        self.assertNotIn('"truncated":true', dense_rendered)

    def test_preview_renders_sampled_identity_for_each_candidate(self):
        candidates = [
            [{"action": "Move", "unit_id": 3, "col": 1, "row": 1},
             {"action": "EndTurn"}],
            [{"action": "Move", "unit_id": 4, "col": 2, "row": 1},
             {"action": "FinishWithGreedy", "groups": [], "holds": []}],
        ]
        preview = {"state_revision": 77, "sampling": True, "candidates": [
            {"valid": True, "post_sweep": {"sampling": True,
             "coverage": {"own_finish": True, "opponent_response": True}, "stages": {
                 "post_finish": {"units_detail": [{"unit_id": 3, "side": 0,
                     "position": {"col": 1, "row": 1}}]},
                 "post_opponent": {"units_detail": []}}}},
            {"valid": True, "post_sweep": {"sampling": True,
             "coverage": {"own_finish": True, "opponent_response": True}, "stages": {
                 "post_finish": {"units_detail": [{"unit_id": 4, "side": 0,
                     "position": {"col": 2, "row": 1}}]},
                 "post_opponent": {"units_detail": []}}}},
        ]}
        rendered = llm_client.compact_batch_preview(
            preview, state={"active_faction": 0, "units": [
                {"id": 3, "faction": 0, "col": 1, "row": 1},
                {"id": 4, "faction": 0, "col": 2, "row": 1}]},
            friendly_side=0, candidate_orders=candidates,
            candidate_roles=["candidate", "candidate"])
        self.assertIn("C0 identity=", rendered)
        self.assertIn("C1 identity=", rendered)
        self.assertEqual(rendered.count("role=candidate"), 2)
        self.assertNotIn("role=baseline", rendered)
        self.assertIn("C0 SAMPLED_FRIENDLY_CASUALTIES side=0 candidate_index=0", rendered)
        self.assertIn("C1 SAMPLED_FRIENDLY_CASUALTIES side=0 candidate_index=1", rendered)
        self.assertIn("casualty_ids=U3", rendered)
        self.assertIn("casualty_ids=U4", rendered)

    def test_continuity_qualifies_controlled_opponent_and_unknown_casualties(self):
        event = lambda source, unit: {
            "kind": "attack", "source": source,
            "attacker": {"unit": unit, "killed": False},
            "defender": {"unit": unit + 100, "killed": True},
        }
        summary = llm_client.format_committed_action_summary(
            [{"action": "EndTurn"}],
            [event("llm", 1), event("delegated_greedy", 2),
             event("greedy", 3), event("future", 4)], 7, 8)
        self.assertIn("controlled_casualties=U101,U102 interval=controlled_action", summary)
        self.assertIn("opponent_response_casualties=U103 interval=opponent_response", summary)
        self.assertIn("unknown_source_casualties=U104 interval=unknown", summary)
        self.assertIn("sources=delegated_greedy,llm", summary)
        self.assertIn("sources=greedy", summary)
        self.assertIn("sources=future", summary)
        self.assertNotIn("casualties=U101,U102,U103,U104", summary)

    def test_resolved_driver_hash_is_exact_executable_digest(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "driver"
            path.write_bytes(b"driver fixture\n")
            self.assertEqual(resolved_driver_hash(path), hashlib.sha256(path.read_bytes()).hexdigest())

    @staticmethod
    def annotated_orders(label, orders=None):
        orders = orders or [{"action": "EndTurn"}]
        return json.dumps({"actions": orders, "intent": label, "decisions": [
            {"orders": list(range(len(orders))), "rules": ["S1"],
             "expected": label, "risk": "Lose ground."}]})

    def run_annotation_path(self, responses, *, review=False, validations=None,
                            rejected=False, **kwargs):
        lines = [{"type": "state", "active_faction": 0, "state_revision": 7, "units": []}]
        if rejected:
            lines.append({"type": "status", "ok": True, "results": [
                {"ok": False, "code": "MoveError", "message": "blocked"}]})
        lines += [{"type": "status", "ok": True, "results": [{"ok": True}]},
                  {"type": "game_end", "reason": "max_turns"}]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=review), \
                mock.patch.object(llm_client, "query_preview_batch", return_value={"candidates": [{"valid": True}]}), \
                mock.patch.object(llm_client, "compact_draft_review", return_value=("review facts", False)), \
                mock.patch.object(llm_client, "draft_review_needed", return_value=True), \
                mock.patch.object(llm_client, "query_validate_batch", side_effect=validations), \
                mock.patch.object(llm_client, "query_inspect_hex", return_value={}):
            code, records = self.run_with_orders(responses, lines, return_records=True,
                                                validate_before_submit=validations is not None, **kwargs)
        self.assertEqual(code, 0, records[-1])
        requests = {r["request_id"]: r for r in records if r["type"] == "model_request"}
        batches = [r for r in records if r["type"] == "forwarded_orders"]
        for batch in batches:
            self.assertEqual(batch["state_revision"], 7)
            if batch["request_id"] is None:
                self.assertEqual(batch["decision_annotation"]["status"], "not_applicable")
                self.assertEqual(batch["source"], "generated_greedy")
                self.assertIsNone(batch["prompt_hash"])
                continue
            request = requests[batch["request_id"]]
            self.assertEqual(request["state_revision"], 7)
            self.assertEqual(batch["decision_annotation"], request["decision_annotation"])
            self.assertEqual(batch["prompt_hash"], hashlib.sha256(request["prompt"].encode()).hexdigest())
            self.assertEqual(batch["orders"], validate_orders(request["raw_output"], require_end_turn=False))
        return records, list(requests.values()), batches

    def test_annotations_follow_confirmed_revised_and_repaired_reviews(self):
        draft = self.annotated_orders("draft")
        for final in (self.annotated_orders("confirmed"),
                      self.annotated_orders("revised", [{"action": "DoneWithImportantMoves"}]),
                      '[{"action":"DoneWithImportantMoves"}]',
                      self.annotated_orders("concede", [{"action": "Resign"}])):
            for malformed in (False, True):
                with self.subTest(final=final, malformed=malformed):
                    replies = [draft] + (["not JSON"] if malformed else []) + [final]
                    records, requests, batches = self.run_annotation_path(replies, review=True)
                    self.assertEqual(len(requests), len(replies))
                    self.assertEqual(len(batches), 1)
                    self.assertEqual(batches[0]["request_id"], requests[-1]["request_id"])
                    self.assertEqual(requests[-1]["raw_output"], final)
                    if final.startswith('['):
                        self.assertEqual(batches[0]["decision_annotation"]["status"], "missing")
                    draft_records = [r for r in records if r.get("type") == "draft_review"]
                    if draft_records:
                        draft_record = draft_records[-1]
                        request_ids = {r["request_id"] for r in requests}
                        self.assertIn(draft_record.get("request_id"), request_ids)
                        self.assertIsInstance(draft_record.get("side_turn_id"), str)
                        decision = next(r for r in records
                                        if r.get("type") == "draft_review_decision"
                                        and r.get("review_id") == draft_record.get("review_id"))
                        self.assertEqual(decision.get("request_id"), requests[-1]["request_id"])
                        self.assertEqual(decision.get("side_turn_id"), draft_record.get("side_turn_id"))

    def test_review_prompt_carries_only_bounded_draft_rationale(self):
        draft = self.annotated_orders("draft objective")
        final = self.annotated_orders("confirmed objective")
        records, requests, _ = self.run_annotation_path([draft, final], review=True)
        review_request = requests[-1]
        self.assertIn("DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN", review_request["prompt"])
        self.assertIn("DRAFT_RATIONALE_UNTRUSTED_DATA_BEGIN", review_request["prompt"])
        self.assertIn('"intent":"draft objective"', review_request["prompt"])
        self.assertIn('"status":"valid"', review_request["prompt"])
        self.assertNotIn("hidden reasoning", review_request["prompt"])
        self.assertEqual(len(review_request["prompt"].encode()), review_request["prompt_bytes"])

    def test_review_omitting_agenda_discards_draft_stage(self):
        draft = json.dumps({
            "actions": [{"action": "EndTurn"}],
            "decisions": [{"orders": [0], "rules": ["S1"],
                           "expected": "draft", "risk": "draft risk"}],
            "agenda": {"tasks": [{"id": "draft", "goal": "draft objective",
                                    "units": [1], "status": "active"}], "holds": [2]},
        })
        for agenda in (None, [], {"tasks": [], "holds": []}):
            final = json.loads(self.annotated_orders("final"))
            if agenda is not None:
                final["agenda"] = agenda
            with self.subTest(agenda=agenda):
                records, _, _ = self.run_annotation_path([draft, json.dumps(final)], review=True)
                updates = [r for r in records if r["type"] == "agenda_update"]
                self.assertEqual([r["agenda"] for r in updates], [agenda] if isinstance(agenda, dict) else [])
                self.assertEqual([r["agenda"] for r in records if r["type"] == "agenda_proposed"],
                                 [agenda] if isinstance(agenda, dict) else [])

    def test_review_without_replacement_preserves_committed_agenda(self):
        committed = {"tasks": [{"id": "committed", "goal": "Keep watch", "units": [], "status": "active"}], "holds": []}
        draft_agenda = {"tasks": [{"id": "discarded", "goal": "Abandon watch", "units": [], "status": "active"}], "holds": []}
        first = {**json.loads(self.annotated_orders("first")), "agenda": committed}
        draft = {**json.loads(self.annotated_orders("draft")), "agenda": draft_agenda}
        for replacement in (None, []):
            final = json.loads(self.annotated_orders("final"))
            if replacement is not None:
                final["agenda"] = replacement
            lines = []
            for revision in (7, 20, 30):
                lines += [{"type": "state", "active_faction": 0, "state_revision": revision, "units": []},
                          {"type": "status", "ok": True, "results": [{"ok": True}]}]
            lines.append({"type": "game_end", "reason": "max_turns"})
            with self.subTest(replacement=replacement), \
                    mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                    mock.patch.object(llm_client, "draft_needs_preview", side_effect=[False, True, False]), \
                    mock.patch.object(llm_client, "query_preview_batch", return_value={"candidates": [{"valid": True}]}), \
                    mock.patch.object(llm_client, "compact_draft_review", return_value=("review facts", False)), \
                    mock.patch.object(llm_client, "draft_review_needed", return_value=True):
                code, records = self.run_with_orders(
                    [json.dumps(first), json.dumps(draft), json.dumps(final), self.annotated_orders("third")],
                    lines, return_records=True)
            self.assertEqual(code, 0)
            self.assertEqual([r["agenda"] for r in records if r["type"] == "agenda_update"], [committed])
            last = [r for r in records if r["type"] == "model_request"][-1]
            memory = json.loads(last["prompt"].split("MEMORY_UNTRUSTED_DATA_BEGIN:\n")[1].split("\nMEMORY_UNTRUSTED_DATA_END")[0])
            self.assertEqual(memory["agenda"], committed)

    def test_annotations_follow_tools_and_action_repairs(self):
        inspect = json.dumps({"tool": "inspect_hex", "col": 0, "row": 0, "phase": "current"})
        final = self.annotated_orders("final")
        draft = self.annotated_orders("draft")
        for kwargs, replies in (
                ({}, [inspect, final]),
                ({}, ["not JSON", final]),
                ({"rejected": True}, [draft, final]),
                ({"rejected": True}, [draft, inspect, final]),
                ({"validations": [{"valid": False}, {"valid": True}]}, [draft, final]),
                ({"validations": [{"valid": False}, {"valid": True}]}, [draft, inspect, final])):
            with self.subTest(kwargs=kwargs, replies=replies):
                records, requests, batches = self.run_annotation_path(replies, **kwargs)
                self.assertEqual(len(requests), len(replies))
                self.assertEqual(batches[-1]["request_id"], requests[-1]["request_id"])
                self.assertEqual(batches[-1]["intent"], "final")
                for request in requests:
                    if request["raw_output"] == inspect:
                        self.assertEqual(request["decision_annotation"]["status"], "not_applicable")

    def test_generated_finishes_do_not_inherit_draft_annotations(self):
        draft = self.annotated_orders("abandoned", [{"action": "Move", "unit_id": 1, "col": 1, "row": 1}])
        _, requests, batches = self.run_annotation_path(
            [draft], incremental_turns=True,
            validations=[{"valid": False, "error_code": "partial_limit"}, {"valid": True}])
        self.assertEqual(len(requests), 1)
        self.assertIsNone(batches[0]["request_id"])

    def test_engine_repair_does_not_commit_rejected_intent(self):
        first = self.annotated_orders("committed intent")
        rejected = self.annotated_orders(
            "rejected intent",
            [{"action": "Attack", "attacker_id": 1, "defender_id": 9},
             {"action": "EndTurn"}],
        )
        repaired = json.dumps([{"action": "EndTurn"}])
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 1,
             "units": []},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "state", "active_faction": 0, "state_revision": 2,
             "units": [{"id": 1, "faction": 0}]},
            {"type": "status", "ok": True,
             "results": [{"ok": False, "code": "NotAdjacent", "message": "bad"}]},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=False):
            code, records = self.run_with_orders(
                [first, rejected, repaired], lines, return_records=True)
        self.assertEqual(code, 0)
        forwarded = [r for r in records if r["type"] == "forwarded_orders"]
        self.assertEqual([r["intent"] for r in forwarded],
                         ["committed intent", "rejected intent", None])
        self.assertEqual(
            [r["intent"] for r in records if r["type"] == "intent_update"],
            ["committed intent"],
        )
        repair_request = [r for r in records if r["type"] == "model_request"][-1]
        self.assertIn("DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN", repair_request["prompt"])
        self.assertIn('"action":"Attack"', repair_request["prompt"])
        self.assertIn("DRAFT_RATIONALE_UNTRUSTED_DATA_BEGIN", repair_request["prompt"])
        self.assertIn('"intent":"rejected intent"', repair_request["prompt"])
        self.assertIn('"status":"valid"', repair_request["prompt"])

    def test_engine_repair_can_commit_its_own_intent(self):
        rejected = self.annotated_orders(
            "rejected intent",
            [{"action": "Attack", "attacker_id": 1, "defender_id": 9},
             {"action": "EndTurn"}],
        )
        repaired = self.annotated_orders("repaired intent")
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 1,
             "units": [{"id": 1, "faction": 0}]},
            {"type": "status", "ok": True,
             "results": [{"ok": False, "code": "NotAdjacent", "message": "bad"}]},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=False):
            code, records = self.run_with_orders(
                [rejected, repaired], lines, return_records=True)
        self.assertEqual(code, 0)
        forwarded = [r for r in records if r["type"] == "forwarded_orders"]
        self.assertEqual([r["intent"] for r in forwarded],
                         ["rejected intent", "repaired intent"])
        self.assertEqual(
            [r["intent"] for r in records if r["type"] == "intent_update"],
            ["repaired intent"],
        )

    def test_pre_submit_repair_does_not_commit_rejected_intent(self):
        old = self.annotated_orders("committed intent")
        rejected = self.annotated_orders("rejected intent")
        repaired = self.annotated_orders("repaired intent")
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 1,
             "units": []},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "state", "active_faction": 0, "state_revision": 2,
             "units": []},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=False), \
                mock.patch.object(
                    llm_client,
                    "query_validate_batch",
                    side_effect=[
                        {"valid": True, "failed_index": None, "results": [{"ok": True}]},
                        {"valid": False, "failed_index": 0, "results": [],
                         "error_code": "NotAdjacent", "error_message": "bad"},
                        {"valid": True, "failed_index": None, "results": [{"ok": True}]},
                    ],
                ):
            code, records = self.run_with_orders(
                [old, rejected, repaired], lines,
                validate_before_submit=True, return_records=True)
        self.assertEqual(code, 0)
        forwarded = [r for r in records if r["type"] == "forwarded_orders"]
        self.assertEqual([r["intent"] for r in forwarded],
                         ["committed intent", "repaired intent"])
        self.assertEqual(
            [r["intent"] for r in records if r["type"] == "intent_update"],
            ["committed intent", "repaired intent"],
        )
        repair_request = [r for r in records if r["type"] == "model_request"][-1]
        self.assertIn("DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN", repair_request["prompt"])
        self.assertIn("DRAFT_RATIONALE_UNTRUSTED_DATA_BEGIN", repair_request["prompt"])
        self.assertIn('"intent":"rejected intent"', repair_request["prompt"])
        self.assertIn('"status":"valid"', repair_request["prompt"])

    def test_rejected_review_repair_does_not_commit_draft_intent(self):
        old = self.annotated_orders("committed intent")
        draft = self.annotated_orders("rejected draft intent")
        repaired = self.annotated_orders("repaired intent")
        candidate_error = CandidateQueryError(
            "preview_batch", "unauthorized_unit", "dead candidate", 0)
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 1,
             "units": []},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "state", "active_faction": 0, "state_revision": 2,
             "units": []},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview",
                                  side_effect=[False, True]), \
                mock.patch.object(llm_client, "query_preview_batch",
                                  side_effect=candidate_error), \
                mock.patch.object(llm_client, "draft_review_needed", return_value=True):
            code, records = self.run_with_orders(
                [old, draft, repaired], lines, return_records=True)
        self.assertEqual(code, 0)
        forwarded = [r for r in records if r["type"] == "forwarded_orders"]
        self.assertEqual([r["intent"] for r in forwarded],
                         ["committed intent", "repaired intent"])
        self.assertEqual(
            [r["intent"] for r in records if r["type"] == "intent_update"],
            ["committed intent", "repaired intent"],
        )
        # A timeout after receiving a draft must not attach that draft to fallback.
        with mock.patch.object(llm_client.OrdersBackend, "complete", side_effect=[
                ModelReply("not JSON"), RuntimeError("model_timeout")]):
            _, requests, batches = self.run_annotation_path([], timeout_finish=True)
        self.assertEqual(len(requests), 2)
        self.assertIsNone(batches[0]["request_id"])

    def test_annotated_resignation_needs_only_one_request(self):
        _, requests, batches = self.run_annotation_path(
            [self.annotated_orders("concede", [{"action": "Resign"}])], review=True)
        self.assertEqual(len(requests), 1)
        self.assertEqual(batches[0]["decision_annotation"]["status"], "valid")

    def test_invalid_annotation_error_surfaces_once_in_the_next_prompt(self):
        # A response with an invalid decision annotation (empty risk text)
        # still executes its legal EndTurn normally. The exact validator
        # error must appear in the very next scheduled prompt as bookkeeping
        # context only, then never again -- no retry, no extra model call,
        # no change to gameplay.
        invalid_first = json.dumps({"actions": [{"action": "EndTurn"}], "decisions": [
            {"orders": [0], "rules": ["S1"], "expected": "hold", "risk": ""}]})
        ok_second = self.annotated_orders("second")
        ok_third = self.annotated_orders("third")
        lines = []
        for revision in (7, 20, 30):
            lines += [{"type": "state", "active_faction": 0, "state_revision": revision, "units": []},
                      {"type": "status", "ok": True, "results": [{"ok": True}]}]
        lines.append({"type": "game_end", "reason": "max_turns"})
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=False):
            code, records = self.run_with_orders(
                [invalid_first, ok_second, ok_third], lines, return_records=True)
        self.assertEqual(code, 0)
        requests = [r for r in records if r["type"] == "model_request"]
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[0]["decision_annotation"]["status"], "invalid")
        error = requests[0]["decision_annotation"]["error"]
        # The mistake still executed legally; only its evidence was rejected.
        batches = [r for r in records if r["type"] == "forwarded_orders"]
        self.assertEqual(batches[0]["orders"], [{"action": "EndTurn"}])
        self.assertNotIn("PRIOR_ANNOTATION_ERROR", requests[0]["prompt"])
        self.assertIn("PRIOR_ANNOTATION_ERROR", requests[1]["prompt"])
        self.assertIn(error, requests[1]["prompt"])
        # Delivered once: it must not still be present, or repeated, later.
        self.assertNotIn("PRIOR_ANNOTATION_ERROR", requests[2]["prompt"])
        # No retry and no extra model call: exactly the three canned replies
        # were consumed, one per scheduled request, and the driver saw
        # exactly three forwarded batches -- one per turn, none repeated.
        self.assertEqual(len(batches), 3)

    def test_draft_review_can_concede_without_another_review_or_validation(self):
        lines = [{"type": "state", "active_faction": 0},
                 {"type": "status", "ok": True, "what": "tactical_surface", "body": {}},
                 {"type": "status", "ok": True, "results": [{"ok": True}]},
                 {"type": "game_end", "reason": "resignation", "winner": 1, "resigned_side": 0}]
        with mock.patch.object(llm_client, "draft_needs_preview", return_value=True), \
                mock.patch.object(llm_client, "query_preview_batch", return_value={"candidates": [{"valid": True}]}), \
                mock.patch.object(llm_client, "compact_draft_review", return_value=("review", False)), \
                mock.patch.object(llm_client, "draft_review_needed", return_value=True):
            code, terminal = self.run_with_orders(
                ['[{"action":"EndTurn"}]', '[{"action":"Resign"}]'], lines, validate_before_submit=True)
        self.assertEqual(code, 0, terminal)
        self.assertEqual(terminal["reason"], "resignation")
        self.assertEqual(terminal["model_calls"], 2)

    def test_pre_submit_repair_can_resign(self):
        lines = [{"type": "state", "active_faction": 0},
                 {"type": "status", "ok": True, "what": "tactical_surface", "body": {}},
                 {"type": "status", "ok": True, "what": "validate_batch", "body":
                  {"valid": False, "failed_index": 0, "results": [{"ok": False, "code": "UnitNotFound"}]}},
                 {"type": "status", "ok": True, "what": "validate_batch", "body":
                  {"valid": True, "results": [{"ok": True}]}},
                 {"type": "status", "ok": True, "results": [{"ok": True}]},
                 {"type": "game_end", "reason": "resignation", "winner": 1, "resigned_side": 0}]
        code, terminal = self.run_with_orders(
            ['[{"action":"Attack","attacker_id":99,"defender_id":2},{"action":"EndTurn"}]',
             '[{"action":"Resign"}]'], lines, validate_before_submit=True)
        self.assertEqual(code, 0, terminal)
        self.assertEqual(terminal["reason"], "resignation")
        self.assertEqual(terminal["model_calls"], 2)

    def test_client_accepts_other_models_and_keeps_unreported_runtime_unknown(self):
        for reported_model, reported_effort in ((None, None), ("test-model", "medium")):
            with self.subTest(reported_model=reported_model):
                cache = {"requested_model": "test-model", "requested_reasoning_effort": "medium",
                         "runtime_model": reported_model, "runtime_reasoning_effort": reported_effort}
                code, terminal = self.run_with_orders(
                    ['[{"action":"EndTurn"}]'],
                    [{"type": "state", "active_faction": 0},
                     {"type": "status", "ok": True, "what": "turn_options", "body": {}},
                     {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
                     {"type": "status", "ok": True, "results": [{"ok": True}]},
                     {"type": "game_end", "reason": "max_turns"}],
                    backend_cache=cache, reasoning_effort="medium")
                self.assertEqual(code, 0, terminal)
                self.assertEqual(terminal["runtime_model"], reported_model)
                self.assertEqual(terminal["runtime_reasoning_effort"], reported_effort)
                self.assertEqual(terminal["backend_requested_model"], "test-model")

    def test_client_rejects_known_setting_mismatches(self):
        for changes in ({"runtime_model": "other-model"}, {"runtime_reasoning_effort": "low"},
                        {"requested_reasoning_effort": "low"}):
            with self.subTest(changes=changes):
                code, _ = self.run_with_orders(
                    ['[{"action":"EndTurn"}]'],
                    [{"type": "state", "active_faction": 0},
                     {"type": "status", "ok": True, "what": "turn_options", "body": {}},
                     {"type": "status", "ok": True, "what": "recruit_options", "body": {}}],
                    backend_cache={"requested_model": "test-model", "requested_reasoning_effort": "medium",
                                   **changes}, reasoning_effort="medium")
                self.assertNotEqual(code, 0)

    def test_event_window_observation_count_is_exact(self):
        first = [{"kind": "recruit", "unit": 1}]
        second = [{"kind": "move", "unit": 2}]
        current = [{"kind": "attack", "unit": 3}]
        self.assertEqual(select_event_window([first, second], current, 1), current)
        self.assertEqual(select_event_window([first, second], current, 2), second + current)
        self.assertEqual(select_event_window([first, second], current, 3), first + second + current)

    def test_compact_trend_is_bounded_and_excludes_partial_states(self):
        states = [
            {"turn": 1, "state_revision": 1, "turn_boundary": "turn", "units": [], "gold": [10, 8],
             "terrain": [{"terrain_id": "village", "owner": -1}]},
            {"turn": 1, "state_revision": 2, "turn_boundary": "partial", "units": [], "gold": [9, 8]},
            {"turn": 2, "state_revision": 3, "turn_boundary": "turn", "units": [], "gold": [8, 7],
             "terrain": [{"terrain_id": "village", "owner": 0}]},
        ]
        rendered = compact_trend(states)
        self.assertIn('"turn":1', rendered)
        self.assertIn('"turn":2', rendered)
        self.assertNotIn('"state_revision":2', rendered)
        self.assertIn('"villages":1', rendered)

    def test_current_turn_readiness_is_revision_pinned_and_explicit(self):
        readiness = build_current_turn_readiness(
            {"turn": 5, "state_revision": 18, "active_faction": 0},
            moved={7}, attacked={8}, agenda_unassigned={9}, agenda_holds={10})
        self.assertEqual(readiness, {
            "turn": 5, "state_revision": 18, "active_faction": 0,
            "moved_this_turn": [7], "attacked_this_turn": [8],
            "agenda_unassigned": [9], "agenda_holds": [10]})
        prompt = prompt_for({"turn": 5, "state_revision": 18, "units": []}, [],
                            current_turn_readiness=readiness)
        self.assertIn("current_turn_readiness", prompt)
        self.assertNotIn("whole_army_sweep", prompt)

    def test_prompt_carries_bounded_continuity_and_turn_progress(self):
        prompt = prompt_for(
            {"turn": 4, "active_faction": 0, "incremental_turns": True,
             "final_only": False, "remaining_partial_batches": 2,
             "gold": [10, 10], "cols": 1, "rows": 1, "terrain": [], "units": [],
             "turn_progress": {"moved": [3], "attacked": [4],
                                "remaining_attackers": [5, 6]}}, [], compact=True,
            continuity="assistant: hold U7 for the next frontline rotation")
        self.assertIn("TURN_PROGRESS moved=U3 attacked=U4 remaining_attackers=U5,U6", prompt)
        self.assertIn("conversation_continuity", prompt)
        self.assertIn("hold U7", prompt)
        self.assertIn("Automatic eligibility excludes recruiters, critically wounded units, and spent units", prompt)
        # T7's hold guidance was deliberately shortened: the old essay demanded a
        # job, contribution forgone and release condition for EVERY hold, which is
        # exactly the routine over-explanation stack 3 exists to stop.
        self.assertIn("Hold for a concrete purpose",
                      " ".join(prompt.split()))

    def test_compact_profiles_preserve_known_empty_and_unknown_abilities(self):
        rendered = compact_tactical_surface({"unit_types": [
            {"def_id": "Troll Whelp", "abilities": ["regenerates_8"],
             "ability_meanings": {"regenerates_8": "heals 8 HP at the start of its side's turn and cures poison"}},
            {"def_id": "Leader", "abilities": ["leadership"],
             "ability_meanings": {"leadership": "adjacent lower-level allies deal 25% more damage per level difference"}},
            {"def_id": "Empty", "abilities": []},
            {"def_id": "Unknown"},
            {"def_id": "Mystery", "abilities": ["future_ability"]},
        ], "units": []})
        self.assertIn("abilities=regenerates_8[heals 8 HP", rendered)
        self.assertIn("abilities=leadership[adjacent lower-level allies deal 25%", rendered)
        self.assertIn("TYPE Empty", rendered)
        self.assertIn("abilities=none", rendered)
        self.assertIn("TYPE Unknown", rendered)
        self.assertIn("abilities=unknown", rendered)
        self.assertIn("future_ability[meaning unknown]", rendered)

    def test_compact_observation_renders_authoritative_phase_table(self):
        rendered = compact_observation({
            "turn": 3, "active_faction": 0, "time_of_day": "Day",
            "cols": 1, "rows": 1, "terrain": [], "units": [],
            "tactical_surface": {
                "visibility": "full", "next_opponent_time_of_day": "Day",
                "next_round_time_of_day": "Dusk",
                "time_of_day_modifiers": {
                    "Dawn": {"lawful": 0, "neutral": 0, "chaotic": 0},
                    "Day": {"lawful": 25, "neutral": 0, "chaotic": -25},
                    "Dusk": {"lawful": 0, "neutral": 0, "chaotic": 0},
                    "Night": {"lawful": -25, "neutral": 0, "chaotic": 25},
                },
            },
        })
        self.assertIn("PHASE_MODIFIERS current=Day opponent=Day next_round=Dusk", rendered)
        self.assertIn("Dusk lawful=0 neutral=0 chaotic=0", rendered)
        self.assertIn("Night lawful=-25 neutral=0 chaotic=25", rendered)

    def test_progress_counts_committed_delegated_moves_and_ignores_simulation_or_opponent(self):
        moved, attacked = set(), set()
        update_committed_progress(moved, attacked, {
            "type": "events", "source": "delegated_greedy",
            "events": [{"kind": "move", "unit": 20}, {"kind": "attack",
                       "attacker": {"unit": 21}}],
        })
        update_committed_progress(moved, attacked, {
            "type": "events", "source": "greedy",
            "events": [{"kind": "move", "unit": 99}],
        })
        update_committed_progress(moved, attacked, {
            "type": "events", "source": "preview",
            "events": [{"kind": "move", "unit": 98}],
        })
        self.assertEqual(moved, {20})
        self.assertEqual(attacked, {21})
        resumed_moved, resumed_attacked = replay_accepted_progress([
            {"type": "driver", "line": {"type": "events", "source": "delegated_greedy",
             "events": [{"kind": "move", "unit": 20}]}},
            {"type": "driver", "line": {"type": "events", "source": "llm",
             "events": [{"kind": "end_turn"}]}},
            {"type": "driver", "line": {"type": "events", "source": "delegated_greedy",
             "events": [{"kind": "move", "unit": 22}]}},
        ], 0)
        self.assertEqual(resumed_moved, {22})
        self.assertEqual(resumed_attacked, set())
    def test_checkpoint_reference_confines_path_and_verifies_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "match.ckpt"
            root.mkdir()
            payload = b'{"state_revision":4,"side_turns":2}'
            path = root / "state.json"
            path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            reference = validate_checkpoint_reference(
                {"path": "state.json", "digest": digest, "state_revision": 4,
                 "side_turns": 2, "boundary": "model_decision"}, root)
            self.assertEqual(reference["absolute_path"], str(path.resolve()))
            with self.assertRaises(ValueError):
                validate_checkpoint_reference(
                    {"path": "../state.json", "digest": digest}, root)
            with self.assertRaises(ValueError):
                validate_checkpoint_reference(
                    {"path": "state.json", "digest": "0" * 64}, root)

    def test_resume_log_ignores_truncated_line_and_falls_back_to_valid_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            ckpt = checkpoint_dir_for_log(log)
            ckpt.mkdir()
            old = b'{"state_revision":1,"side_turns":1,"boundary":"model_decision"}'
            new = b'{"state_revision":2,"side_turns":2,"boundary":"post_batch"}'
            old_path, new_path = ckpt / "old.json", ckpt / "new.json"
            old_path.write_bytes(old)
            new_path.write_bytes(new)
            old_ref = {"type": "checkpoint_ref", "path": "old.json",
                       "digest": hashlib.sha256(old).hexdigest(), "state_revision": 1,
                       "side_turns": 1, "boundary": "model_decision"}
            # The newest sidecar is durable but its audit reference was lost.
            log.write_text(json.dumps(old_ref) + "\n{" )
            selected, records = select_resume_checkpoint(log)
            self.assertEqual(selected["path"], "new.json")
            self.assertTrue(selected["orphan_discovered"])
            self.assertEqual(len(records), 1)

    def test_direct_resume_checkpoint_reports_content_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.json"
            path.write_text('{"state_revision":9,"side_turns":3}')
            loaded = load_resume_checkpoint(path)
            self.assertEqual(loaded["state_revision"], 9)
            self.assertEqual(loaded["side_turns"], 3)

    def test_logged_run_wires_checkpoint_dir_and_durably_records_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "match.ndjson"
            ckpt = checkpoint_dir_for_log(log)
            payload = b'{"state_revision":1,"side_turns":0,"boundary":"model_decision"}'
            digest = hashlib.sha256(payload).hexdigest()

            class CheckpointProcess(FakeDriverProcess):
                pass

            def start(command, **kwargs):
                self.assertIn("--checkpoint-dir", command)
                self.assertIn(str(ckpt), command)
                (ckpt / "initial.json").write_bytes(payload)
                return CheckpointProcess([
                    {"type": "checkpoint", "path": "initial.json", "digest": digest,
                     "state_revision": 1, "side_turns": 0,
                     "boundary": "model_decision", "pending_opponent_turn": False},
                    {"type": "game_end", "reason": "max_turns", "winner": None},
                ])

            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b", gold=1,
                seed=2, max_turns=3, llm_side=0, turn_timeout=4, query_budget_seconds=5,
                max_queries_per_turn=6, no_recruit_macro=False, interactive_model=True,
                orders_file=None, model_command=None, model_timeout=7, log=str(log),
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None)
            with mock.patch("tools.llm_client.subprocess.Popen", side_effect=start), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                self.assertEqual(run(args), 0)
            records = [json.loads(line) for line in log.read_text().splitlines()]
            refs = [record for record in records if record["type"] == "checkpoint_ref"]
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["digest"], digest)
    def test_batched_target_inspection_is_bounded_and_compact(self):
        self.assertEqual(validate_inspect_targets_request(
            {"tool": "inspect_targets", "unit_ids": [9, 10]}), [9, 10])
        with self.assertRaises(ValueError):
            validate_inspect_targets_request({"tool": "inspect_targets", "unit_ids": [9, 9]})
        with self.assertRaises(ValueError):
            validate_inspect_targets_request({"tool": "inspect_targets", "unit_ids": []})
        requests = []
        body = {"ok": True, "body": {"targets": [
            {"target_id": 9, "hp": 20, "col": 1, "row": 2, "terrain": "flat", "attacks": []},
            {"target_id": 10, "hp": 12, "col": 3, "row": 4, "terrain": "forest", "attacks": []},
        ]}}
        result = query_inspect_targets(
            lambda request: (requests.append(request) or body), [9, 10], 3)
        self.assertEqual([target["target_id"] for target in result], [9, 10])
        self.assertEqual(requests[0]["what"], "inspect_targets")
        self.assertIn("TARGETS TARGET U9", llm_client.compact_targets_inspection(result))

    def test_action_envelope_preserves_legacy_engine_orders_and_bounds_intent(self):
        text = json.dumps({"actions": [{"action": "EndTurn"}],
                           "intent": "scouts contest villages; main advances together"})
        self.assertEqual(validate_orders(text), [{"action": "EndTurn"}])
        self.assertEqual(response_intent(text), "scouts contest villages; main advances together")
        with self.assertRaises(ValueError):
            validate_orders(json.dumps({"actions": [{"action": "EndTurn"}], "intent": "x" * 600}))

    def test_compact_strategic_briefing_reports_villages_and_formation_facts(self):
        rendered = compact_strategic_briefing({
            "active_faction": 0,
            "terrain": [
                {"col": 1, "row": 1, "terrain_id": "village", "owner": 1, "healing": 8},
                {"col": 3, "row": 1, "terrain_id": "village", "owner": 0, "healing": 8},
                {"col": 5, "row": 1, "terrain_id": "village", "healing": 8},
            ],
            "units": [
                {"id": 3, "faction": 0, "col": 2, "row": 1, "hp": 12, "max_hp": 34},
                {"id": 4, "faction": 0, "col": 2, "row": 2, "hp": 34, "max_hp": 34},
            ],
        })
        self.assertIn("VILLAGES ours=1 enemy=1 neutral=0 unknown=1", rendered)
        self.assertIn("V 1,1 owner=1 occupant=none healing=8", rendered)
        self.assertIn("FORMATION U3 hp=12/34 allies_near=1 healing=0", rendered)

    def test_compact_spatial_map_preserves_terrain_occupancy_and_odd_row_geometry(self):
        state = {
            "cols": 3, "rows": 2,
            "terrain": [
                {"col": 0, "row": 0, "terrain_id": "forest"},
                {"col": 1, "row": 0, "terrain_id": "village", "owner": -1},
                {"col": 2, "row": 0, "terrain_id": "keep"},
                {"col": 0, "row": 1, "terrain_id": "hills"},
                {"col": 1, "row": 1, "terrain_id": "castle"},
                {"col": 2, "row": 1, "terrain_id": "flat"},
            ],
            "units": [
                {"id": 2, "faction": 1, "col": 2, "row": 0},
                {"id": 11, "faction": 0, "col": 1, "row": 1},
            ],
        }
        rendered = compact_spatial_map(state)
        self.assertIn("MAP_TERRAIN", rendered)
        self.assertIn("F. V- K.", rendered)
        self.assertIn("MAP_UNITS token=faction:id .=empty", rendered)
        self.assertIn("r00 .... .... 1:02", rendered)
        self.assertIn(" r01 .... 0:11 ....", rendered)

    def test_compact_observation_includes_spatial_map_and_is_deterministic(self):
        state = {"cols": 2, "rows": 1, "terrain": [
            {"col": 0, "row": 0, "terrain_id": "forest"},
            {"col": 1, "row": 0, "terrain_id": "flat"},
        ], "units": []}
        rendered = compact_observation(state)
        self.assertIn("MAP_TERRAIN", rendered)
        self.assertIn("MAP_UNITS", rendered)
        self.assertEqual(rendered, compact_observation(dict(state)))
    def test_compact_events_preserves_facts_without_routine_json(self):
        events = [
            {"kind": "move", "source": "greedy", "unit": 9,
             "from": {"col": 4, "row": 5}, "to": {"col": 3, "row": 4}},
            {"kind": "attack", "source": "greedy",
             "attacker": {"unit": 9, "hp": 17},
             "defender": {"unit": 35, "hp": 0, "killed": True},
             "damage_to_defender": 6, "damage_to_attacker": 0},
            {"kind": "recruit", "source": "llm", "unit": 3,
             "def_id": "Skeleton", "col": 2, "row": 6, "cost": 14},
            {"kind": "gold", "source": "llm", "faction": 0,
             "delta": 6, "balance": 20},
            {"kind": "end_turn", "source": "llm", "ended_faction": 0,
             "active_faction": 1, "turn": 4},
        ]
        rendered = compact_events(events)
        self.assertIn("greedy move: U9 4,5>3,4", rendered)
        self.assertIn("greedy attack: U9>U35 dmg=6/0 hp=0/dead", rendered)
        self.assertIn("llm recruit: U3=Skeleton@2,6 cost=14", rendered)
        self.assertIn("llm gold: F0 delta=6 balance=20", rendered)
        self.assertIn("llm end_turn: F0->F1 turn=4", rendered)
        self.assertLess(len(rendered.encode()), 2048)

    def test_compact_prompt_uses_digest_and_diagnostic_prompt_keeps_raw_events(self):
        events = [{"kind": "move", "source": "greedy", "unit": 9,
                   "from": {"col": 4, "row": 5}, "to": {"col": 3, "row": 4}}]
        compact = prompt_for({}, events, compact=True)
        diagnostic = prompt_for({}, events, compact=False)
        self.assertIn('"EVENT_DIGEST', compact)
        self.assertIn('"kind":"move"', diagnostic)
        self.assertNotIn('"kind":"move"', compact)

    def test_prompt_carries_intent_as_bounded_board_memory(self):
        prompt = prompt_for({}, [], compact=True, intent="main force advances together")
        self.assertIn("previous_intent", prompt)
        self.assertIn("main force advances together", prompt)
        self.assertIn("Optional intent is memory under 512 UTF-8 bytes", prompt)

    def test_target_and_hex_renderers_keep_facts_and_empty_hex_uncertainty(self):
        target = compact_target_inspection({
            "target_id": 9, "hp": 20, "col": 4, "row": 7, "terrain": "flat",
            "attacks": [{"attacker_id": 2, "origin_col": 3, "origin_row": 7,
                         "moved": True, "forecast": {"outcome_bps": [1000, 9000, 0],
                                                       "expected_damage_tenths": [80, 20]}}],
        })
        self.assertIn("TARGET U9 hp=20 at=4,7 terrain=flat", target)
        self.assertIn("ENGAGE_STEP U2 via=3,7 exchange=(defender_killed=10%,both_survive=90%,attacker_killed=0%; expected_damage=(to_defender=8HP,attacker_retaliation=2HP))", target)
        empty = compact_hex_inspection({
            "phase": "next_opponent_turn", "visibility": "full",
            "inspection": {"col": 4, "row": 7, "occupant_id": None,
                           "attacks": [{"attacker_id": 16, "origin_col": 4,
                                        "origin_row": 5, "moved": True,
                                        "forecast": None, "max_damage": None}]},
        })
        self.assertIn("HEX 4,7 phase=next_opponent_turn visibility=full occupant=None", empty)
        self.assertIn("U16~4,5", empty)
        self.assertNotIn(" p[", empty)

    def test_recruiter_inspection_renders_destination_exposure(self):
        rendered = compact_unit_inspection({
            "unit_id": 1,
            "origins": [],
            "destination_threats": [
                {"col": 2, "row": 7, "current": True,
                 "distinct_attacker_count": 3, "max_incoming_sum": 42,
                 "lethal_attackers_needed": 2, "origins_conflict": False,
                 "focus_kill_bps": [100, 200, 300],
                 "focus_expected_damage_tenths": [10, 20, 30]},
                {"col": 1, "row": 7, "current": False,
                 "distinct_attacker_count": 0, "max_incoming_sum": 0,
                 "lethal_attackers_needed": None, "origins_conflict": False},
            ],
        })
        self.assertIn("DESTINATION_DANGER", rendered)
        self.assertIn("@2,7 direct_attackers=3 direct_max=42HP lethal_attackers_needed=2 origins_conflict=False focus_kills=(kill_by_1=1%,kill_by_2=2%,kill_by_3=3%)", rendered)
        self.assertIn("->1,7 direct_attackers=0 direct_max=0HP lethal_attackers_needed=null", rendered)

    def test_target_and_hex_requests_are_exact_and_revision_pinned(self):
        self.assertEqual(validate_inspect_target_request(
            {"tool": "inspect_target", "unit_id": 9}), 9)
        self.assertEqual(validate_inspect_hex_request(
            {"tool": "inspect_hex", "col": 4, "row": 7,
             "phase": "next_opponent_turn"}), (4, 7, "next_opponent_turn"))
        with self.assertRaises(ValueError):
            validate_inspect_hex_request(
                {"tool": "inspect_hex", "col": 4, "row": 7, "phase": "future"})
        requests = []
        exchange = lambda request: requests.append(request) or {"ok": True, "body": {}}
        query_inspect_target(exchange, 9, 3)
        query_inspect_hex(exchange, 4, 7, "current", 3)
        self.assertEqual(requests, [
            {"action": "Query", "what": "inspect_target", "state_revision": 3, "unit_id": 9},
            {"action": "Query", "what": "inspect_hex", "state_revision": 3,
             "col": 4, "row": 7, "phase": "current"},
        ])

    def test_inspect_units_request_is_exact_and_revision_pinned(self):
        self.assertEqual(ac.validate_inspect_units_request(
            {"tool": "inspect_units", "unit_ids": [7]}), [7])
        for request in (
            {"tool": "inspect_units", "unit_ids": [True]},
            {"tool": "inspect_units", "unit_ids": [-1]},
            {"tool": "inspect_units", "unit_ids": [7], "extra": 1},
        ):
            with self.assertRaises(ValueError):
                ac.validate_inspect_units_request(request)
        requests = []
        body = {"unit_id": 7, "origins": []}
        self.assertEqual(ac.query_inspect_units(
            lambda request: requests.append(request) or
            {"ok": True, "state_revision": 19, "body": body}, [7], 19), [body])
        self.assertEqual(requests, [{"action": "Query", "what": "inspect_unit",
                                    "state_revision": 19, "unit_id": 7}])

    def test_tool_followup_requires_final_actions_when_budget_is_exhausted(self):
        self.assertIn("remaining=0", tool_followup_instruction(0, 3))
        self.assertIn("Do not request another tool", tool_followup_instruction(0, 3))
        self.assertIn("remaining=0", tool_followup_instruction(2, 1))
        self.assertIn("Do not request another tool", tool_followup_instruction(2, 1))
        self.assertIn("another allowed tool", tool_followup_instruction(1, 2))

    def test_tool_request_name_rejects_non_string_tool_values(self):
        for value in ({}, [], 7, True, None):
            with self.subTest(value=value):
                self.assertIsNone(llm_client.tool_request_name({"tool": value}))

    def test_tool_budget_repair_preserves_all_tool_context(self):
        repaired = tool_budget_repair_prompt(
            "ORIGINAL", "\nTOOL_RESULT unit=7: target=9", "tool call budget exhausted",
            '{"tool":"inspect_units","unit_ids":[7]}')
        self.assertIn("ORIGINAL", repaired)
        self.assertIn("target=9", repaired)
        self.assertIn('"unit_ids":[7]', repaired)
        self.assertIn("MODEL_RESPONSE_UNTRUSTED_DATA_BEGIN", repaired)
        self.assertIn("tool call budget exhausted", repaired)
        self.assertIn("do not request another tool", repaired.lower())

    def test_followup_context_echoes_tool_request_and_preview_candidates(self):
        request = '{"tool":"preview_batch","candidates":[[{"action":"EndTurn"}]]}'
        context = ("MODEL_TOOL_REQUEST_UNTRUSTED_DATA_BEGIN:\n" + request +
                   "\nMODEL_TOOL_REQUEST_UNTRUSTED_DATA_END\n" +
                   "TOOL_RESULT_UNTRUSTED_DATA_BEGIN tool=preview_batch:\n" +
                   "PREVIEW C0 valid=True\nTOOL_RESULT_UNTRUSTED_DATA_END\n")
        self.assertIn(request, context)
        self.assertIn("PREVIEW C0", context)

    def test_compact_draft_review_reports_recruiter_danger_delta(self):
        rendered, lethal = compact_draft_review({"candidates": [{
            "valid": True,
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 34, "distinct_attacker_count": 5,
                "max_incoming_sum": 70, "lethal_attackers_needed": 3,
            }]},
        }]}, True)
        self.assertTrue(lethal)
        self.assertIn("danger_before=True danger_after=True", rendered)
        self.assertIn("R1 hp=34HP attackers=5 maximum_incoming=70HP lethal_attackers_needed=3", rendered)

    def test_compact_draft_review_preserves_null_and_absent_lethal_counts(self):
        rendered, _ = compact_draft_review({"candidates": [{
            "valid": True,
            "recruiter_threats": {"recruiters": [
                {"recruiter_id": 1, "hp": 34, "distinct_attacker_count": 1,
                 "max_incoming_sum": 10, "lethal_attackers_needed": None},
                {"recruiter_id": 2, "hp": 34, "distinct_attacker_count": 1,
                 "max_incoming_sum": 10},
            ]},
        }]}, False)
        self.assertIn("R1 hp=34HP attackers=1 maximum_incoming=10HP lethal_attackers_needed=null (unreachable under supplied maximum volleys)", rendered)
        self.assertIn("R2 hp=34HP attackers=1 maximum_incoming=10HP lethal_attackers_needed=unknown", rendered)

    def test_sampled_transition_uses_selected_candidate_and_keeps_missing_stage_unknown(self):
        state = {"active_faction": 0, "units": [
            {"id": 3, "faction": 0, "col": 1, "row": 1},
            {"id": 4, "faction": 0, "col": 2, "row": 1},
        ]}
        preview = {"state_revision": 77, "sampling": True, "candidates": [
            {"valid": True, "post_sweep": {"sampling": True,
              "coverage": {"own_finish": True, "opponent_response": True}, "stages": {
                "post_finish": {"units_detail": [
                    {"unit_id": 3, "side": 0, "position": {"col": 1, "row": 1}},
                    {"unit_id": 4, "side": 0, "position": {"col": 3, "row": 1}},
                ]},
                "post_opponent": {"units_detail": [
                    {"unit_id": 3, "side": 0, "position": {"col": 1, "row": 1}},
                ]},
            }}},
            {"valid": True, "post_sweep": {"sampling": True,
              "coverage": {"own_finish": True, "opponent_response": False}, "stages": {
                "post_finish": {"units_detail": [
                    {"unit_id": 3, "side": 0, "position": {"col": 4, "row": 1}},
                    {"unit_id": 4, "side": 0, "position": {"col": 2, "row": 1}},
                ]},
                "post_opponent": None,
            }}},
        ]}
        transition = llm_client.sampled_transition(preview, state, 0, 0)
        self.assertEqual(transition["originating_revision"], 77)
        self.assertEqual(transition["candidate_index"], 0)
        self.assertEqual(transition["opponent_casualties"]["unit_ids"], [4])
        self.assertEqual(transition["own_finish_movement"]["moved"][0]["unit_id"], 4)
        self.assertTrue(llm_client.draft_review_needed(
            preview, {}, [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
            draft_index=0, state=state, friendly_side=0))
        self.assertEqual(llm_client.sampled_transition(preview, state, 0, 1)["opponent_casualties"]["status"], "unknown")

    def test_sampled_transition_does_not_treat_empty_or_missing_opponent_as_death(self):
        base = {"state_revision": 12, "candidates": [{"valid": True, "post_sweep": {
            "sampling": True, "coverage": {"own_finish": True, "opponent_response": True}, "stages": {
                "post_finish": {"units_detail": [{"unit_id": 8, "side": 0,
                                                     "position": {"col": 1, "row": 1}}]},
                "post_opponent": {"units_detail": []},
            }}}]}
        self.assertEqual(llm_client.sampled_transition(base, friendly_side=0)["opponent_casualties"]["unit_ids"], [8])
        missing = {"state_revision": 12, "candidates": [{"valid": True, "post_sweep": {
            "sampling": True, "coverage": {"own_finish": True, "opponent_response": True}, "stages": {
                "post_finish": {"units_detail": [{"unit_id": 8, "side": 0,
                                                     "position": {"col": 1, "row": 1}}]},
                "post_opponent": None,
            }}}]}
        self.assertIsNone(llm_client.sampled_transition(missing, friendly_side=0)["opponent_casualties"]["unit_ids"])
        malformed = {"state_revision": 12, "candidates": [{"valid": True, "post_sweep": {
            "sampling": True, "coverage": {"own_finish": True, "opponent_response": True}, "stages": {
                "post_finish": {"units_detail": [{"unit_id": 8, "side": 0}]},
                "post_opponent": {"units_detail": []},
            }}}]}
        self.assertEqual(llm_client.sampled_transition(malformed, friendly_side=0)["opponent_casualties"]["status"], "unknown")

    def test_sampled_transition_does_not_treat_missing_opponent_as_death(self):
        missing = {"state_revision": 12, "candidates": [{"post_sweep": {
            "sampling": True, "stages": {
                "post_finish": {"units_detail": [{"unit_id": 8, "side": 0}]},
                "post_opponent": None,
            }}}]}
        transition = llm_client.sampled_transition(missing, friendly_side=0)
        self.assertEqual(transition["opponent_casualties"]["status"], "unknown")
        self.assertIsNone(transition["opponent_casualties"]["unit_ids"])

    def test_sampled_transition_requires_friendly_side_identity(self):
        preview = {"state_revision": 12, "candidates": [{"valid": True, "post_sweep": {
            "sampling": True, "coverage": {"own_finish": True, "opponent_response": True},
            "stages": {"post_finish": {"units_detail": [
                {"unit_id": 8, "side": 1, "position": {"col": 2, "row": 2}}]},
                "post_opponent": {"units_detail": []}}}}]}
        self.assertEqual(llm_client.sampled_transition(preview)["status"], "unknown")
        self.assertEqual(llm_client.sampled_transition(preview, friendly_side=1)["opponent_casualties"]["unit_ids"], [8])

    def test_compact_draft_review_treats_open_route_lethality_as_danger(self):
        rendered, lethal = compact_draft_review({"candidates": [{
            "valid": True,
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 3, "distinct_attacker_count": 0,
                "max_incoming_sum": 0, "lethal_attackers_needed": None,
                "open_distinct_attacker_count": 1,
                "open_max_incoming_sum": 20,
                "open_lethal_attackers_needed": 1,
            }]},
        }]}, False)
        self.assertTrue(lethal)
        self.assertIn("danger_before=False danger_after=True", rendered)
        self.assertIn("OPEN_R1 attackers=1 maximum_incoming=20HP open_lethal_attackers_needed=1", rendered)

    def test_compact_draft_review_reports_unused_attackers(self):
        rendered, lethal = compact_draft_review(
            {"candidates": [{"valid": True, "recruiter_threats": {"recruiters": []}}]},
            False,
            {"available": {3, 4}, "current": {3}, "targets": {9: {3, 4}}},
            [{"action": "Attack", "attacker_id": 3, "defender_id": 9}, {"action": "EndTurn"}],
        )
        self.assertFalse(lethal)
        self.assertIn("COVERAGE_DRAFT available=U3,U4 planned=U3 unused=U4", rendered)

    def test_handoff_audit_distinguishes_held_idle_units_and_recruitment(self):
        audit = llm_client.handoff_audit(
            {"active_faction": 0, "units": [
                {"id": 3, "faction": 0, "hp": 10, "max_hp": 10, "moved": False, "attacked": False},
                {"id": 4, "faction": 0, "hp": 2, "max_hp": 10, "moved": False, "attacked": False},
            ], "tactical_surface": {"recruitment": {
                "gold": 20, "options": [{"def_id": "Skeleton", "affordable": True}],
                "placement_hexes": [{"col": 1, "row": 1}],
            }}},
            [{"action": "FinishWithGreedy", "groups": [],
              "holds": [{"unit_id": 3, "reason": "guard"}]}],
            {"available": {3}, "current": {3}, "targets": {}},
        )
        self.assertEqual(audit["healthy_idle"], [3])
        self.assertEqual(audit["held"], [3])
        self.assertEqual(audit["actionable_idle"], [3])
        self.assertEqual(audit["affordable_recruitment"], ["Skeleton"])
        self.assertEqual(audit["trigger_reasons"], ["all_healthy_idle_held", "affordable_recruitment"])

    def test_rescue_priorities_bound_and_recruiter_first(self):
        audit = llm_client.handoff_audit(
            {"active_faction": 0, "units": [], "tactical_surface": {"recruitment": {},
             "exposure": {"units": [
                 {"unit_id": 9, "hp": 2, "max_hp": 10, "can_recruit": False,
                  "distinct_attacker_count": 1, "max_incoming_sum": 8, "lethal_attackers_needed": 1},
                 {"unit_id": 4, "hp": 3, "max_hp": 10, "can_recruit": True,
                  "distinct_attacker_count": 1, "max_incoming_sum": 5, "lethal_attackers_needed": 2},
                 {"unit_id": 8, "hp": 2, "max_hp": 10, "can_recruit": False,
                  "distinct_attacker_count": 1, "max_incoming_sum": 8, "lethal_attackers_needed": 1},
                 {"unit_id": 7, "hp": 1, "max_hp": 10, "can_recruit": False,
                  "distinct_attacker_count": 1, "max_incoming_sum": 8, "lethal_attackers_needed": 1},
             ]}}},
            [{"action": "EndTurn"}], {"available": set()})
        self.assertEqual([item["unit_id"] for item in audit["rescue_priorities"]], [4, 8, 9])
        self.assertIn("endangered_wounded_unresolved", audit["trigger_reasons"])

    def test_review_rescue_rendering_preserves_null_and_absent_lethal_counts(self):
        priorities = llm_client.rescue_priorities({"units": [
            {"unit_id": 4, "hp": 2, "max_hp": 10, "distinct_attacker_count": 1,
             "lethal_attackers_needed": None},
            {"unit_id": 5, "hp": 2, "max_hp": 10, "distinct_attacker_count": 1},
        ]})
        rendered, _ = compact_draft_review(
            {"candidates": [{"valid": True}]}, False,
            audit={"rescue_priorities": priorities})
        self.assertIn("RESCUE priorities=U4 hp=2/10 direct_attackers=1 direct_max=unknown lethal_attackers_needed=null (unreachable under supplied maximum volleys)", rendered)
        self.assertIn("U5 hp=2/10 direct_attackers=1 direct_max=unknown lethal_attackers_needed=unknown", rendered)

    def test_strategic_briefing_keeps_economy_and_deployment_facts_together(self):
        rendered = compact_strategic_briefing({
            "active_faction": 0,
            "terrain": [{"col": 1, "row": 1, "terrain_id": "village", "owner": 0}],
            "units": [],
            "tactical_surface": {
                "force": [{"side": 0, "units": 4, "recruiters": 1, "hp": 28, "max_hp": 40},
                           {"side": 1, "units": 5, "recruiters": 1, "hp": 31, "max_hp": 45}],
                "recruitment": {"gold": 22, "options": [{"def_id": "Skeleton", "affordable": True}]},
                "economy": {"next_village_income": 2, "vacatable_castles": [{"unit_id": 3}]},
            },
        })
        self.assertIn("ECONOMY own_units=4/1 enemy_units=5/1", rendered)
        self.assertIn("gold=22 income=2 affordable=Skeleton vacatable=1", rendered)

    def test_planned_attackers_counts_attack_and_all_engage_steps(self):
        self.assertEqual(
            llm_client.planned_attackers([
                {"action": "Attack", "attacker_id": 3, "defender_id": 9},
                {"action": "Engage", "target_id": 9,
                 "steps": [{"attacker_id": 4, "col": 2, "row": 3},
                            {"attacker_id": 5, "col": 3, "row": 3}]},
            ]),
            {3, 4, 5},
        )

    def test_zero_lethal_count_is_not_draft_danger(self):
        rendered, lethal = compact_draft_review({"candidates": [{
            "valid": True,
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 34, "distinct_attacker_count": 0,
                "max_incoming_sum": 0, "lethal_attackers_needed": 0,
            }]},
        }]}, False)
        self.assertFalse(lethal)
        self.assertIn("danger_after=False", rendered)

    def test_automatic_review_separates_simulated_recruiter_death_from_live_state(self):
        live = {"type": "state", "active_faction": 0, "state_revision": 130,
                "gold": [195, 11], "units": [
                    {"id": 1, "faction": 0, "hp": 48, "max_hp": 48,
                     "col": 2, "row": 7, "can_recruit": True}]}
        preview = {"state_revision": 130, "sampling": True, "candidates": [{
            "valid": True, "post_sweep": {
                "policy": "driver_greedy_one_response_v1", "evaluation_seed": 17,
                "coverage": {"own_finish": True, "opponent_response": True},
                "stages": {
                    "post_finish": {"sides": [{"side": 0, "recruiters": 1}],
                                    "units_detail": [{"unit_id": 1, "hp": 48}]},
                    "post_opponent": {"sides": [{"side": 0, "recruiters": 0}],
                                      "units_detail": []},
                },
            },
        }]}
        lines = [live, {"type": "status", "ok": True, "results": [{"ok": True}]},
                 {"type": "game_end", "reason": "max_turns"}]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=True), \
                mock.patch.object(llm_client, "draft_review_needed", return_value=True), \
                mock.patch.object(llm_client, "query_preview_batch", return_value=preview):
            code, records = self.run_with_orders(
                [self.annotated_orders("draft"), self.annotated_orders("confirm")],
                lines, return_records=True)
        self.assertEqual(code, 0)
        requests = [r for r in records if r["type"] == "model_request"]
        self.assertEqual(len(requests), 2)
        prompt = requests[-1]["prompt"]
        simulation = prompt.split("SIMULATION — NOT EXECUTED BEGIN", 1)[1]
        simulation, after = simulation.split("SIMULATION — NOT EXECUTED END", 1)
        self.assertIn("originating_revision=130 sampling=True", simulation)
        self.assertIn('POST_OPPONENT [{"recruiters":0,"side":0}]', simulation)
        self.assertNotIn("POST_OPPONENT_UNITS", simulation)
        self.assertNotIn("POST_FINISH_UNITS", simulation)
        self.assertNotIn("AUTHORITATIVE_LIVE_STATE_BEGIN", simulation)
        self.assertIn("Candidate rosters, gold, casualties, villages, and threats are hypothetical", after)
        live_reminder = after.split("AUTHORITATIVE_LIVE_STATE_BEGIN", 1)[1]
        self.assertIn("revision=130 controlled_side=0", live_reminder)
        self.assertIn("recruiters=U1 hp=48 at=2,7", live_reminder)

    def test_missing_recruiter_threats_are_unknown_not_safe(self):
        rendered, lethal = compact_draft_review({"candidates": [{"valid": True}]}, False)
        self.assertIsNone(lethal)
        self.assertIn("danger_after=unknown", rendered)
        self.assertIn("DANGER_AFTER_UNAVAILABLE", rendered)

    def test_unavailable_unit_inspection_is_a_factual_gap(self):
        def exchange(_request):
            return {"ok": False, "message": "unit is unavailable"}
        with self.assertRaises(RuntimeError) as ctx:
            ac.query_inspect_units(exchange, [5], 42)
        self.assertIn("unavailable", str(ctx.exception))

    def test_compact_batch_preview_uses_recruiter_aggregate_not_origins(self):
        rendered = compact_batch_preview({"sampling": False, "state_revision": 17, "candidates": [{
            "valid": True,
            "summary": {"gold_before": 20, "gold_after": 6, "units_before": 4, "units_after": 5},
            "forecasts": [],
            "recruiter_threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 38, "distinct_attacker_count": 3,
                "max_incoming_sum": 42, "lethal_attackers_needed": 3,
                "origins_conflict": True,
                "threats": [{"attacker_id": 9, "origin_col": 4, "origin_row": 7}],
            }]},
        }]})
        self.assertIn("C0 R1 hp=38HP attackers=3 maximum_incoming=42HP lethal_attackers_needed=3 origins_conflict=True", rendered)
        self.assertIn("SIMULATION — NOT EXECUTED BEGIN", rendered)
        self.assertIn("originating_revision=17", rendered)
        self.assertIn("SIMULATION — NOT EXECUTED END", rendered)
        self.assertIn("preview queries execute no actions", rendered)
        self.assertNotIn("origin_col", rendered)
        self.assertLess(len(rendered.encode()), 8192)

    def test_bounded_comparison_requires_driver_rollout_confirmation(self):
        sent = []
        body = {"mode": "bounded_rollout", "sampling": True, "candidates": []}
        result = query_bounded_comparison(
            lambda request: sent.append(request) or {"ok": True, "body": body},
            [[{"action": "EndTurn"}]], 4)
        self.assertEqual(result, body)
        self.assertEqual(sent[0]["mode"], "bounded_rollout")

    def test_bounded_comparison_keeps_driver_failure_typed(self):
        with self.assertRaisesRegex(RuntimeError, r"query_error: bounded_comparison: unavailable"):
            query_bounded_comparison(
                lambda request: {"ok": False, "code": "rollout_unavailable",
                                 "message": "unavailable"},
                [[{"action": "EndTurn"}]], 4)

    def test_preview_candidate_errors_are_classified_by_structured_code(self):
        candidate = [[{"action": "FinishWithGreedy", "groups": [], "holds": []}]]
        for query in (query_preview_batch, query_bounded_comparison):
            with self.subTest(query=query.__name__):
                with self.assertRaises(CandidateQueryError) as raised:
                    query(lambda request: {"ok": False, "code": "unauthorized_unit",
                                           "message": "candidate references a dead unit",
                                           "candidate_index": 1}, candidate, 286)
                error = raised.exception
                self.assertEqual(error.code, "unauthorized_unit")
                self.assertEqual(error.candidate_index, 1)
                self.assertIn("unauthorized_unit", str(error))
                self.assertEqual(error.as_dict()["query"],
                                 "preview_batch" if query is query_preview_batch else "bounded_comparison")
        self.assertEqual(CANDIDATE_QUERY_ERROR_CLASSES["unauthorized_unit"], "model_invalid")
        with self.assertRaisesRegex(RuntimeError, "query_error: bounded_comparison: unavailable"):
            query_bounded_comparison(
                lambda request: {"ok": False, "code": "new_driver_code", "message": "unavailable"},
                candidate, 286)

    def test_player_preview_candidate_gets_one_bounded_repair(self):
        preview = json.dumps({"tool": "preview_batch", "candidates": [
            [{"action": "EndTurn"}],
            [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
        ]})
        corrected = self.annotated_orders("corrected")
        code, records = self.run_with_orders(
            [preview, corrected],
            [{"type": "state", "active_faction": 0, "state_revision": 286, "units": []},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             {"type": "status", "ok": False, "what": "preview_batch",
              "code": "unauthorized_unit", "candidate_index": 1,
              "message": "FinishWithGreedy may reference only living model-side units"},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=4, return_records=True)
        self.assertEqual(code, 0)
        repair = next(record for record in records if record["type"] == "repair")
        self.assertIn("unauthorized_unit", repair["validation_error"] if "validation_error" in repair else
                      repair["raw_output"])
        repair_prompt = next(record for record in records
                             if record["type"] == "model_request" and record["sequence"] == 2)["prompt"]
        self.assertIn("DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN", repair_prompt)
        self.assertIn("ENGINE_CANDIDATE_ERROR_UNTRUSTED_DATA_BEGIN", repair_prompt)
        self.assertIn("unauthorized_unit", repair_prompt)
        self.assertIn("revision=286", repair_prompt)
        self.assertIn("corrected bare preview_batch request", repair_prompt)
        self.assertIn('"action":"EndTurn"', repair_prompt)
        forwarded = next(record for record in records if record["type"] == "forwarded_orders")
        self.assertEqual(forwarded["orders"], json.loads(corrected)["actions"])
        self.assertFalse(any(record.get("type") == "events" for record in records))

    def test_preview_repair_preserves_all_candidates_when_index_is_ambiguous(self):
        preview = json.dumps({"tool": "preview_batch", "candidates": [
            [{"action": "EndTurn"}],
            [{"action": "DoneWithImportantMoves"}],
        ]})
        corrected = self.annotated_orders("corrected")
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 286, "units": []},
            {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
            {"type": "status", "ok": False, "what": "preview_batch",
             "code": "parse", "message": "candidate validation failed"},
            {"type": "game_end", "reason": "max_turns", "winner": None},
        ]
        code, records = self.run_with_orders([preview, corrected], lines,
                                              max_model_calls_per_turn=4,
                                              return_records=True)
        self.assertEqual(code, 0)
        repair_prompt = next(r["prompt"] for r in records
                             if r["type"] == "model_request" and r["sequence"] == 2)
        self.assertIn("DRAFT_CANDIDATES_UNTRUSTED_DATA_BEGIN", repair_prompt)
        self.assertIn("do not guess which position failed", repair_prompt)
        self.assertIn('"DoneWithImportantMoves"', repair_prompt)
        self.assertNotIn("DRAFT_ACTIONS_UNTRUSTED_DATA_BEGIN", repair_prompt)

    def test_invalid_automatic_review_candidate_gets_one_repair_without_second_review(self):
        draft = self.annotated_orders("draft", [{"action": "FinishWithGreedy",
                                                  "groups": [], "holds": []}])
        corrected = self.annotated_orders("corrected")
        candidate_error = CandidateQueryError(
            "preview_batch", "unauthorized_unit",
            "FinishWithGreedy may reference only living model-side units", 1)
        with mock.patch.object(llm_client, "draft_needs_preview", return_value=True), \
                mock.patch.object(llm_client, "query_preview_batch", side_effect=candidate_error) as preview:
            code, records = self.run_with_orders(
                [draft, corrected],
                [{"type": "state", "active_faction": 0, "state_revision": 286, "units": []},
                 {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
                 {"type": "game_end", "reason": "max_turns", "winner": None}],
                max_model_calls_per_turn=4, return_records=True)
        self.assertEqual(code, 0)
        self.assertEqual(preview.call_count, 1)
        error = next(record for record in records if record["type"] == "draft_review_error")
        self.assertEqual(error["candidate_error"]["code"], "unauthorized_unit")
        repair = next(record for record in records if record["type"] == "draft_review_repair")
        self.assertIn("ENGINE_CANDIDATE_ERROR_UNTRUSTED_DATA_BEGIN", repair["raw_output"]
                      if "ENGINE_CANDIDATE_ERROR_UNTRUSTED_DATA_BEGIN" in repair["raw_output"] else
                      next(record for record in records if record["type"] == "model_request"
                           and record["sequence"] == 2)["prompt"])
        self.assertEqual(len([record for record in records if record["type"] == "draft_review"]), 0)
        forwarded = next(record for record in records if record["type"] == "forwarded_orders")
        self.assertEqual(forwarded["orders"], json.loads(corrected)["actions"])

    def test_repeated_invalid_review_candidate_is_model_invalid_with_one_attempt(self):
        draft = self.annotated_orders("draft", [{"action": "FinishWithGreedy",
                                                  "groups": [], "holds": []}])
        candidate_error = CandidateQueryError(
            "preview_batch", "unauthorized_unit", "dead unit", 1)
        with mock.patch.object(llm_client, "draft_needs_preview", return_value=True), \
                mock.patch.object(llm_client, "query_preview_batch", side_effect=candidate_error):
            code, records = self.run_with_orders(
                [draft, "not an action envelope"],
                [{"type": "state", "active_faction": 0, "state_revision": 286, "units": []},
                 {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}}],
                max_model_calls_per_turn=4, return_records=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        terminal = records[-1]
        self.assertEqual(terminal["type"], "model_error")
        self.assertEqual(terminal["reason"], TERMINAL_MODEL_INVALID)
        self.assertEqual(terminal["code"], "draft_candidate_invalid")
        self.assertEqual(terminal["model_calls"], 2)
        self.assertFalse(any(record["type"] == "forwarded_orders" for record in records))

    def test_invalid_review_candidate_respects_exhausted_model_budget(self):
        draft = self.annotated_orders("draft", [{"action": "FinishWithGreedy",
                                                  "groups": [], "holds": []}])
        candidate_error = CandidateQueryError(
            "preview_batch", "unauthorized_unit", "dead unit", 1)
        with mock.patch.object(llm_client, "draft_needs_preview", return_value=True), \
                mock.patch.object(llm_client, "query_preview_batch", side_effect=candidate_error):
            code, records = self.run_with_orders(
                [draft],
                [{"type": "state", "active_faction": 0, "state_revision": 286, "units": []},
                 {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}}],
                max_model_calls_per_turn=1, return_records=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        self.assertEqual(records[-1]["code"], "draft_candidate_invalid")
        self.assertEqual(records[-1]["model_calls"], 1)

    def test_preview_request_rejects_more_than_two_candidates(self):
        request = json.dumps({"tool": "preview_batch", "candidates": [
            [{"action": "EndTurn"}], [{"action": "EndTurn"}], [{"action": "EndTurn"}],
        ]})
        with self.assertRaisesRegex(ValueError, "one or two candidates"):
            validate_preview_request(request)

    def test_compact_batch_preview_renders_ordered_attack_sequences(self):
        rendered = compact_batch_preview({"sampling": False, "candidates": [{
            "valid": True, "summary": {}, "forecasts": [],
            "attack_sequences": [{"target_id": 7, "target_hp": 20,
                                   "attacker_ids": [3, 4], "kill_bps": 8100,
                                   "expected_damage_tenths": 176}],
        }]})
        self.assertIn("C0 OUT T7 hp=20 attackers=U3,U4 kill_probabilities=(81%) expected_damage=(17.6HP)", rendered)

    def test_compact_batch_preview_reports_typed_failure_and_assumption(self):
        rendered = compact_batch_preview({"sampling": False, "candidates": [{
            "valid": False,
            "results": [{"ok": True},
                        {"ok": False, "code": "NotAdjacent",
                         "message": "attacker is not adjacent to target"}],
            "preview_error": {"code": "conditional", "message": "later steps depend on combat"},
            "assumption": "all forecast combatants survive in place",
            "summary": {},
        }]})
        self.assertIn("C0 FAIL index=1 code=NotAdjacent", rendered)
        self.assertIn("C0 PREVIEW_ERROR code=conditional", rendered)
        self.assertIn("C0 ASSUMPTION all forecast combatants survive in place", rendered)

    def test_compact_batch_preview_reports_conditional_action_indices(self):
        rendered = compact_batch_preview({"sampling": False, "candidates": [{
            "valid": True,
            "results": [{"ok": True},
                        {"ok": True, "conditional_on_survival": True}],
            "summary": {},
        }]})
        self.assertIn("C0 CONDITIONAL action_indices=[1]", rendered)

    def test_compact_batch_preview_reports_bounded_delegation_stages(self):
        rendered = compact_batch_preview({"sampling": True, "candidates": [{
            "valid": True, "summary": {},
            "post_sweep": {
                "policy": "driver_greedy_one_response_v1",
                "evaluation_seed": 17,
                "own_event_count": 4,
                "opponent_event_count": 6,
                "coverage": {"own_finish": True, "opponent_response": True},
                "stages": {
                    "post_finish": {"sides": [{"side": 0, "units": 3}]},
                    "post_opponent": {"sides": [{"side": 0, "units": 2}]},
                },
            },
        }]})
        self.assertIn("DELEGATION policy=driver_greedy_one_response_v1", rendered)
        self.assertIn("POST_FINISH", rendered)
        self.assertIn("POST_OPPONENT", rendered)

    def test_compact_tactical_surface_renders_force_and_recruitment_facts(self):
        rendered = compact_tactical_surface({
            "units": [], "unit_types": [], "threats": {"recruiters": []},
            "recruitment": {"gold": 14, "legal_now": False,
                            "reason": "recruiter_off_keep", "placement_hexes": [],
                            "options": [{"def_id": "archer", "cost": 8, "affordable": True}]},
            "force": [{"side": 0, "units": 4, "hp": 40, "max_hp": 80,
                       "recruit_cost": 32, "low_hp": 1, "healthy_hp": 2,
                       "recruiters": 1, "recruiters_on_keep": 0}],
        })
        self.assertIn("RECRUIT g=14 legal_now=False reason=recruiter_off_keep", rendered)
        self.assertIn("FORCE F0 units=4 hp=40/80 cost=32 low=1 healthy=2 recruiter=1 keep=0", rendered)

    def test_preview_request_is_bounded_and_uses_normal_order_validation(self):
        request = json.dumps({"tool": "preview_batch", "candidates": [
            [{"action": "EndTurn"}],
            [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}, {"action": "EndTurn"}],
        ]})
        self.assertEqual(len(validate_preview_request(request)), 2)
        with self.assertRaises(ValueError):
            validate_preview_request(json.dumps({"tool": "preview_batch", "candidates": [
                [{"action": "EndTurn"}], [{"action": "EndTurn"}], [{"action": "EndTurn"}]
            ]}))

    def test_validate_batch_query_is_revision_pinned_and_preserves_orders(self):
        requests = []
        orders = [{"action": "EndTurn"}]

        def exchange(request):
            requests.append(request)
            return {"ok": True, "body": {"valid": True, "results": [{"ok": True}]}}

        self.assertEqual(query_validate_batch(exchange, orders, 17)["valid"], True)
        self.assertEqual(requests, [{"action": "Query", "what": "validate_batch",
                                    "state_revision": 17, "orders": orders}])

    def test_tactical_surface_query_is_singleton_and_revision_pinned(self):
        requests = []
        def exchange(request):
            requests.append(request)
            return {"ok": True, "body": {"units": []}}
        self.assertEqual(query_tactical_surface(exchange, 17), {"units": []})
        self.assertEqual(requests, [{"action": "Query", "what": "tactical_surface",
                                     "state_revision": 17}])

    def test_compact_tactical_surface_separates_moves_and_attacks(self):
        rendered = compact_unit_inspection({"unit_id": 5, "origins": [
            {"col": 2, "row": 7, "current": True, "movable": False,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [7100, 2500, 400],
                 "expected_damage_tenths": [210, 20]}}]}]})
        self.assertIn("COORDS=col,row", rendered)
        self.assertIn("U5 at=2,7 move_destinations=none attack_options=@>T9 exchange=(defender_killed=71%,both_survive=25%,attacker_killed=4%; expected_damage=(to_defender=21HP,attacker_retaliation=2HP))", rendered)

        rendered = compact_unit_inspection({"unit_id": 5, "origins": [
            {"col": 3, "row": 7, "current": False, "movable": True,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [7100, 2500, 400],
                 "expected_damage_tenths": [210, 20]}}]},
            {"col": 4, "row": 7, "current": False, "movable": True,
             "engagements": []}]})
        self.assertIn("U5 move_destinations=3,7|4,7 attack_options=3,7>T9 exchange=(defender_killed=71%,both_survive=25%,attacker_killed=4%; expected_damage=(to_defender=21HP,attacker_retaliation=2HP))", rendered)
        self.assertNotIn("at=3,7", rendered)

    def test_attack_coverage_groups_targets_and_current_attackers(self):
        surface = {"units": [
            {"unit_id": 3, "origins": [
                {"current": True, "engagements": [{"defender_id": 9}]},
                {"current": False, "engagements": [{"defender_id": 10}]},
            ]},
            {"unit_id": 4, "origins": [{"current": False, "engagements": [{"defender_id": 9}]}]},
            {"unit_id": 5, "origins": [{"current": False, "engagements": []}]},
        ]}
        coverage = tactical_attack_coverage(surface)
        self.assertEqual(coverage["available"], {3, 4})
        self.assertEqual(coverage["current"], {3})
        self.assertEqual(coverage["targets"], {9: {3, 4}, 10: {3}})
        rendered = compact_tactical_surface(surface)
        self.assertIn("ATTACK_COVERAGE legal_origins=U3,U4 current_origins=U3 targets=U9:U3,U4;U10:U3", rendered)

    def test_default_tactical_card_summarizes_movable_origins(self):
        rendered = compact_tactical_surface({"units": [{"unit_id": 5, "origins": [
            {"col": 2, "row": 7, "current": True, "movable": False,
             "engagements": [{"defender_id": 9, "forecast": {
                 "outcome_bps": [1000, 9000, 0], "expected_damage_tenths": [80, 20]}}]},
            {"col": 3, "row": 7, "current": False, "movable": True,
             "engagements": [{"defender_id": 10, "forecast": {
                 "outcome_bps": [0, 10000, 0], "expected_damage_tenths": [30, 0]}}]},
        ]}]})
        self.assertIn("U5 at=2,7 readiness=moved=unknown attacked=unknown move_destinations=1 attack_targets=U9,U10", rendered)
        self.assertIn("current_attack_options=T9 exchange=", rendered)
        self.assertNotIn("3,7>T10", rendered)
        self.assertIn("inspect=inspect_units", rendered)

    def test_compact_tactical_surface_renders_threat_and_economy_facts(self):
        rendered = compact_tactical_surface({
            "units": [],
            "threats": {"projected_time_of_day": "Night", "recruiters": [{
                "recruiter_id": 1, "hp": 20, "col": 2, "row": 7,
                "distinct_attacker_count": 1, "max_incoming_sum": 20,
                "lethal_attackers_needed": 1, "origins_conflict": False,
                "attacker_max_damage": [{"attacker_id": 16, "max_damage": 20}],
                "threats": [{"attacker_id": 16, "origin_col": 4, "origin_row": 7,
                             "moved": True, "max_damage": 20,
                             "forecast": {"outcome_bps": [1200, 8000, 800],
                                          "expected_damage_tenths": [150, 20]}}]}]},
            "economy": {"gold": 6, "next_village_income": 4,
                        "vacatable_castles": [{"unit_id": 8, "col": 3, "row": 7,
                                               "destinations": [{"col": 4, "row": 7}]}]},
        })
        self.assertIn("THREAT R1 hp=20HP at=2,7 projected_opponent_phase=Night attackers=1 maximum_incoming=20HP lethal_attackers_needed=1", rendered)
        self.assertIn("detail=U16:20HP", rendered)
        self.assertIn("ECONOMY gold=6 projected_village_income=4 vacatable_castles=U8@3,7>4,7", rendered)

    def test_compact_tactical_surface_renders_open_route_threats(self):
        rendered = compact_tactical_surface({
            "units": [],
            "threats": {"projected_time_of_day": "Dawn", "recruiters": [{
                "recruiter_id": 1, "hp": 3, "col": 0, "row": 12,
                "distinct_attacker_count": 0, "max_incoming_sum": 0,
                "lethal_attackers_needed": None, "origins_conflict": False,
                "attacker_max_damage": [], "threats": [],
                "open_distinct_attacker_count": 1, "open_max_incoming_sum": 20,
                "open_lethal_attackers_needed": 1, "open_origins_conflict": False,
                "open_attacker_max_damage": [{"attacker_id": 17, "max_damage": 20}],
                "open_threats": [{"attacker_id": 17, "origin_col": 0,
                                  "origin_row": 10, "moved": True, "max_damage": 20}],
            }]},
        })
        self.assertIn("OPEN_THREAT R1 movement_inclusive=true attackers=1 maximum_incoming=20HP open_lethal_attackers_needed=1", rendered)
        self.assertIn("OPEN_THREAT_HEX R1 at=0,10~ attackers=U17 maximum_damage=20HP", rendered)

    def test_compact_tactical_surface_groups_recruiter_threat_origins(self):
        rendered = compact_tactical_surface({
            "threats": {"visibility": "full", "projected_time_of_day": "Night", "recruiters": [{
                "recruiter_id": 1, "hp": 20, "col": 2, "row": 7, "terrain": "keep",
                "distinct_attacker_count": 2, "max_incoming_sum": 40,
                "lethal_attackers_needed": 1, "origins_conflict": False,
                "threats": [
                    {"attacker_id": 16, "origin_col": 4, "origin_row": 7,
                     "moved": True, "max_damage": 20},
                    {"attacker_id": 18, "origin_col": 4, "origin_row": 7,
                     "moved": True, "max_damage": 20},
                ],
            }]},
        })
        self.assertIn("terrain=keep on_keep=True", rendered)
        self.assertIn("THREAT_HEX R1 at=4,7~ attackers=U16,U18 maximum_damage=20HP", rendered)

    def test_threat_rendering_distinguishes_null_missing_zero_and_partial_exposure(self):
        rendered = compact_tactical_surface({
            "visibility": "partial",
            "units": [{"unit_id": 1}, {"unit_id": 2}, {"unit_id": 3}],
            "threats": {"recruiters": [{
                "recruiter_id": 1, "hp": 30, "distinct_attacker_count": 0,
                "max_incoming_sum": 0, "lethal_attackers_needed": None,
                "open_distinct_attacker_count": 0,
                "open_max_incoming_sum": 0,
                "open_lethal_attackers_needed": 0,
            }]},
            "exposure": {"visibility": "partial", "units": [
                {"unit_id": 1, "hp": 10, "distinct_attacker_count": 0,
                 "open_distinct_attacker_count": 0},
                {"unit_id": 2, "hp": 10, "distinct_attacker_count": 1,
                 "max_incoming_sum": 12, "lethal_attackers_needed": 2,
                 "open_distinct_attacker_count": 0},
            ]},
        })
        self.assertIn("lethal_attackers_needed=null (unreachable under supplied maximum volleys)", rendered)
        self.assertIn("open_lethal_attackers_needed=0 origins_conflict=False detail=none", rendered)
        self.assertIn("EXPOSURE_SCOPE target=current_position direct=enemy_movement_with_blockers_zoc open=enemy_movement_without_blockers_zoc visibility=partial evaluated=2 threatened=1 zero=1 missing=1", rendered)
        self.assertIn("EXPOSURE U2", rendered)
        self.assertNotIn("EXPOSURE U1", rendered)

    def test_compact_observation_is_deterministic_and_keeps_instance_facts(self):
        state = {"turn": 2, "active_faction": 0, "time_of_day": "day", "cols": 3, "rows": 2,
                 "gold": [4, 5],
                 "terrain": [{"col": 0, "row": 0, "terrain_id": "keep"}],
                 "units": [{"id": 2, "faction": 1, "def_id": "orc", "col": 0, "row": 0,
                            "hp": 7, "max_hp": 9, "moved": True, "attacked": False,
                            "xp": 1, "xp_needed": 4, "advancement_pending": False},
                           {"id": 1, "faction": 0, "def_id": "leader", "col": 1, "row": 0,
                            "hp": 10, "max_hp": 10, "moved": False, "attacked": False,
                            "xp": 0, "xp_needed": 4, "advancement_pending": True}]}
        rendered = compact_observation(state)
        self.assertEqual(rendered, compact_observation(dict(state)))
        self.assertIn("id=1", rendered)
        self.assertIn("terrain=keep", rendered)  # occupied terrain is recoverable
        self.assertIn("pending=True", rendered)
    def test_final_end_turn(self):
        self.assertEqual(validate_orders('[{"action":"Move","unit_id":1,"col":1,"row":1},{"action":"EndTurn"}]')[-1]["action"], "EndTurn")

    def test_move_group_toward_is_a_nonfinal_coordinate_action(self):
        action = {"action": "MoveGroupToward", "unit_ids": [12, 13], "col": 8, "row": 6}
        self.assertEqual(validate_orders(json.dumps([action]), require_end_turn=False), [action])
        with self.assertRaisesRegex(ValueError, "exactly one final turn boundary"):
            validate_orders(json.dumps([action]))
        for malformed in (
            {**action, "unit_ids": []},
            {**action, "unit_ids": [12, 12]},
            {**action, "unit_ids": list(range(9))},
            {**action, "unit_ids": [True]},
            {**action, "col": 2**31},
            {**action, "unexpected": 1},
        ):
            with self.subTest(malformed=malformed), self.assertRaises(ValueError):
                validate_orders(json.dumps([malformed]), require_end_turn=False)

    def test_move_group_toward_result_is_preserved_in_continuity(self):
        summary = llm_client.format_committed_action_summary(
            [{"action": "MoveGroupToward", "unit_ids": [3, 4], "col": 10, "row": 7}],
            [{"kind": "move", "unit": 3}], 4, 5,
            results=[{"ok": True, "moved": [{"unit_id": 3}],
                      "skipped": [{"unit_id": 4, "reason": "spent"}]}],
        )
        self.assertIn("MoveGroupToward([U3,U4]->10,7)", summary)
        self.assertIn("moved=U3 skipped=U4:spent", summary)

    def test_continuity_omits_unacknowledged_forwarded_batch(self):
        records = [{
            "type": "forwarded_orders", "batch_id": "game:batch:1",
            "orders": [{"action": "Move", "unit_id": 1, "col": 2, "row": 2}],
            "state_revision": 7,
        }]
        self.assertEqual(llm_client.replay_committed_continuity(records), [])

    def test_continuity_omits_rejected_forwarded_batch(self):
        records = [{
            "type": "forwarded_orders", "batch_id": "game:batch:1",
            "orders": [{"action": "Move", "unit_id": 1, "col": 2, "row": 2}],
            "state_revision": 7,
        }, {
            "type": "action_failure", "batch_id": "game:batch:1",
        }]
        self.assertEqual(llm_client.replay_committed_continuity(records), [])

    def test_continuity_accepts_successful_batch_status(self):
        records = [{
            "type": "forwarded_orders", "batch_id": "game:batch:1",
            "orders": [{"action": "Move", "unit_id": 1, "col": 2, "row": 2}],
            "state_revision": 7,
        }, {
            "type": "driver", "line": {
                "type": "status", "ok": True,
                "results": [{"ok": True}], "state_revision": 8,
            },
        }]
        continuity = llm_client.replay_committed_continuity(records)
        self.assertEqual(len(continuity), 1)
        self.assertIn("committed: Move(U1->2,2) | rev=7->8", continuity[0])

    def test_continuity_accepts_explicit_checkpoint_or_batch_commit(self):
        for proof in (
            {"type": "checkpoint_ref", "batch_id": "game:batch:1",
             "state_revision": 8},
            {"type": "batch_committed", "batch_id": "game:batch:1",
             "state_revision": 8},
        ):
            with self.subTest(proof=proof["type"]):
                records = [{
                    "type": "forwarded_orders", "batch_id": "game:batch:1",
                    "orders": [{"action": "Move", "unit_id": 1, "col": 2, "row": 2}],
                    "state_revision": 7,
                }, proof]
                continuity = llm_client.replay_committed_continuity(records)
                self.assertEqual(len(continuity), 1)
                self.assertIn("rev=7->8", continuity[0])

    def test_continuity_requires_batch_identity_for_checkpoint_or_commit(self):
        for proof_type in ("checkpoint_ref", "batch_committed"):
            with self.subTest(proof=proof_type):
                records = [{
                    "type": "forwarded_orders",
                    "orders": [{"action": "Move", "unit_id": 1, "col": 2, "row": 2}],
                    "state_revision": 7,
                }, {
                    "type": proof_type, "state_revision": 8,
                }]
                self.assertEqual(llm_client.replay_committed_continuity(records), [])

    def test_missing_final_end_turn_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Move","unit_id":1,"col":1,"row":1}]')

    def test_non_final_end_turn_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"EndTurn"},{"action":"Move"}]')

    def test_finish_with_greedy_accepts_greedy_and_toward_hex_groups(self):
        orders = validate_orders(json.dumps([
            {"action": "Move", "unit_id": 1, "col": 2, "row": 3},
            {"action": "FinishWithGreedy",
             "groups": [
                 {"mode": "greedy", "unit_ids": [2, 3]},
                 {"mode": "toward_hex", "unit_ids": [4], "col": 7, "row": 8},
             ],
             "holds": [{"unit_id": 5, "reason": "protect the wounded screen"}]},
        ]))
        self.assertEqual(orders[-1]["action"], "FinishWithGreedy")
        self.assertEqual(orders[-1]["groups"][1]["mode"], "toward_hex")

    def test_finish_with_greedy_rejects_invalid_mode_and_overlap(self):
        invalid_mode = [{"action": "FinishWithGreedy",
                         "groups": [{"mode": "random", "unit_ids": [2]}],
                         "holds": []}]
        with self.assertRaises(ValueError):
            validate_orders(json.dumps(invalid_mode))

        overlap = [{"action": "FinishWithGreedy",
                    "groups": [{"mode": "greedy", "unit_ids": [2]}],
                    "holds": [{"unit_id": 2, "reason": "hold position"}]}]
        with self.assertRaises(ValueError):
            validate_orders(json.dumps(overlap))

    def test_finish_with_greedy_reports_independent_overlap_and_reason_errors(self):
        orders = [{"action": "FinishWithGreedy",
                   "groups": [{"mode": "greedy", "unit_ids": [13]}],
                   "holds": [{"unit_id": 13, "reason": "x"},
                              {"unit_id": 45, "reason": "x" * 121}]}]
        with self.assertRaisesRegex(ValueError,
                                    r"actions\[0\]\.holds\[0\]\.unit_id.*actions\[0\]\.groups\[0\]\.unit_ids\[0\].*actions\[0\]\.holds\[1\]\.reason: 121 characters; maximum 120"):
            validate_orders(json.dumps(orders))

    def test_finish_with_greedy_reason_character_boundaries_and_non_string(self):
        for reason in ("x" * 119, "x" * 120, "é" * 120):
            orders = [{"action": "FinishWithGreedy", "groups": [],
                       "holds": [{"unit_id": 1, "reason": reason}]}]
            self.assertEqual(validate_orders(json.dumps(orders)), orders)
        with self.assertRaisesRegex(ValueError, r"actions\[0\]\.holds\[0\]\.reason: must be a string"):
            validate_orders(json.dumps([{"action": "FinishWithGreedy", "groups": [],
                                         "holds": [{"unit_id": 1, "reason": None}]}]))

    def test_finish_with_greedy_malformed_containers_report_shape_only(self):
        with self.assertRaisesRegex(ValueError, r"actions\[0\]\.groups: must be an array"):
            validate_orders(json.dumps([{"action": "FinishWithGreedy", "groups": {}, "holds": []}]))
        with self.assertRaisesRegex(ValueError, r"actions\[0\]\.holds: must be an array"):
            validate_orders(json.dumps([{"action": "FinishWithGreedy", "groups": [], "holds": {}}]))

    def test_finish_with_greedy_reports_duplicate_paths(self):
        orders = [{"action": "FinishWithGreedy",
                   "groups": [{"mode": "greedy", "unit_ids": [2, 2]}],
                   "holds": [{"unit_id": 3, "reason": "a"},
                              {"unit_id": 3, "reason": "b"}]}]
        with self.assertRaisesRegex(ValueError, r"duplicate unit ID 2.*unit_ids\[0\].*duplicate unit ID 3.*holds\[0\]"):
            validate_orders(json.dumps(orders))

    def test_missing_player_identity_is_warned_about_once_at_the_end(self):
        """A model side nobody named imports as an unknown player.

        The file transport cannot report the host's model, so without
        --player-model the catalog records no player and every viewer shows an
        unknown LLM for a game somebody did play. Warn while the operator is
        still watching rather than leaving it to be noticed in the browser.
        """
        from .llm_client import set_terminal, TERMINAL_GAMEPLAY
        import io, contextlib

        unnamed = {"llm_side": 0}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            set_terminal(unnamed, TERMINAL_GAMEPLAY)
        self.assertFalse(unnamed["player_identity_recorded"])
        self.assertIn("--player-model", stderr.getvalue())

        for key in ("requested_model", "backend_requested_model", "runtime_model"):
            named = {"llm_side": 0, key: "claude-haiku-4-5-20251001"}
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                set_terminal(named, TERMINAL_GAMEPLAY)
            self.assertTrue(named["player_identity_recorded"], key)
            self.assertEqual(stderr.getvalue(), "", f"{key} should satisfy the check")

        # An algorithm-only run has no model side to name.
        both_algorithms = {"llm_side": None}
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            set_terminal(both_algorithms, TERMINAL_GAMEPLAY)
        self.assertEqual(stderr.getvalue(), "")

    def test_prompt_states_engine_rules_locked_by_rust_fixtures(self):
        """The facts below are proven by test_documented_rule_* in game_state.rs.

        Any change must move together with those fixtures; a confidently stated
        wrong rule is worse for play than an omitted one.
        """
        prompt = prompt_for({"units": []}, [])
        self.assertIn("## Engine rules", prompt)
        for fact in (
                "melee needs distance 1, ranged needs distance 2",
                "Distance 3 or more is out of reach",
                "retaliates only with an attack of the same range",
                "must END on a free hex (else DestinationOccupied)",
                "path MAY cross hexes occupied by other units",
                "Every hex adjacent to an enemy is a zone of control",
                "Entering one ends that unit's movement",
                "Starting inside a zone of control does not restrict leaving it",
                "skirmisher ability does not currently bypass that stop rule",
                "A rejected action rolls back its whole batch",
        ):
            self.assertIn(fact, prompt)
        # The block reaches the model verbatim rather than being re-typed per call.
        self.assertIn(ENGINE_RULES, prompt)
        # Engine facts precede the match rules and the tactical guide's advice.
        self.assertLess(prompt.index("## Engine rules"), prompt.index("## Match rules"))

    def test_prompt_documents_greedy_handoff_and_recruitment_ownership(self):
        prompt = prompt_for({"units": []}, [])
        for text in (
                "DoneWithImportantMoves runs the automatic greedy sweep then ends the turn",
                "EndTurn runs the same sweep",
                "FinishWithGreedy delegates only listed group IDs",
                "Unit IDs must be unique across groups and holds",
                "it does not establish tactical safety",
                "The sweep never recruits",
        ):
            with self.subTest(text=text):
                self.assertIn(text, prompt)

    def test_timeout_finish_orders_preserves_holds_and_excludes_spent_units(self):
        state = {"units": [
            {"id": 1, "faction": 0, "moved": False, "attacked": False},
            {"id": 2, "faction": 0, "moved": True, "attacked": False},
            {"id": 3, "faction": 0, "moved": False, "attacked": True},
            {"id": 4, "faction": 0, "moved": True, "attacked": True},
            {"id": 5, "faction": 1, "moved": False, "attacked": False},
        ]}
        orders = timeout_finish_orders(
            state, 0, {"holds": [{"unit_id": 2, "reason": "guard the keep"}]})
        self.assertEqual(orders[0]["action"], "FinishWithGreedy")
        self.assertEqual(orders[0]["groups"], [{"mode": "greedy", "unit_ids": [1, 3]}])
        self.assertEqual(orders[0]["holds"], [{"unit_id": 2, "reason": "guard the keep"}])

    def test_timeout_finish_orders_can_delegate_no_units_when_all_are_protected(self):
        orders = timeout_finish_orders(
            {"units": [{"id": 1, "faction": 0, "can_recruit": True,
                         "moved": False, "attacked": False,
                         "hp": 3, "max_hp": 10}]}, 0, {})
        self.assertEqual(orders, [{"action": "FinishWithGreedy", "groups": [],
                                   "holds": [{"unit_id": 1, "reason": "protected recruiter"}]}])

    def test_done_with_important_moves_is_a_final_boundary(self):
        self.assertEqual(
            validate_orders('[{"action":"Move","unit_id":1,"col":1,"row":1},'
                            '{"action":"DoneWithImportantMoves"}]')[-1]["action"],
            "DoneWithImportantMoves")

    def test_incremental_batch_can_omit_end_turn_but_end_turn_must_be_final(self):
        self.assertEqual(
            validate_orders('[{"action":"Move","unit_id":1,"col":1,"row":1}]',
                            require_end_turn=False)[0]["action"], "Move")
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"EndTurn"},{"action":"Move"}]',
                            require_end_turn=False)

    def test_query_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Query","what":"state"},{"action":"EndTurn"}]')

    def test_strict_recruit_batch_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"RecruitBatch","def_id":"Skeleton","count":1},{"action":"EndTurn"}]', strict=True)

    def test_engage_validation_and_compact_type_profiles(self):
        orders = '[{"action":"Engage","target_id":9,"steps":[{"attacker_id":3,"col":4,"row":7}]},{"action":"EndTurn"}]'
        self.assertEqual(validate_orders(orders)[0]["action"], "Engage")
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Engage","target_id":9,"steps":[]},{"action":"EndTurn"}]')
        rendered = compact_tactical_surface({"unit_types": [{
            "def_id": "Dark Adept", "cost": 16, "max_hp": 28, "movement": 5,
            "alignment": "chaotic", "attacks": [{"name": "chill", "damage": 10,
            "strikes": 2, "range": "ranged", "type": "cold", "specials": []}],
            "resistances": {"cold": -10}
        }], "units": []})
        self.assertIn("TYPE Dark Adept cost=16 hp=28 move=5", rendered)
        self.assertIn("chill:10x2/ranged/cold", rendered)
        self.assertIn("resist=cold: takes 10% less damage", rendered)

    def test_compact_type_resistances_describe_incoming_damage_and_unknowns(self):
        rendered = compact_tactical_surface({"unit_types": [
            {"def_id": "Positive", "resistances": {"arcane": 40}},
            {"def_id": "Zero", "resistances": {"blade": 0}},
            {"def_id": "Missing"},
        ], "units": []})
        self.assertIn("resist=arcane: takes 40% more damage", rendered)
        self.assertIn("resist=blade: unchanged damage", rendered)
        self.assertIn("resist=unknown", rendered)

    def test_compact_type_profile_extends_type_line_with_terrain_costs_and_defense(self):
        rendered = compact_tactical_surface({"unit_types": [
            {"def_id": "Naga Fighter", "cost": 14, "max_hp": 33, "movement": 7,
             "movement_costs": {"hills": 3, "flat": 2, "mountains": 5},
             "defense": {"hills": 40, "flat": 30}},
            {"def_id": "Empty Overrides", "movement_costs": {}, "defense": {}},
            {"def_id": "Missing Terrain Fields"},
        ], "units": []})
        # A single TYPE line -- no second card -- carries the new facts.
        naga_line = next(line for line in rendered.splitlines() if line.startswith("TYPE Naga Fighter"))
        self.assertIn("move_costs=flat:2,hills:3,mountains:5", naga_line)
        self.assertIn("99=impassable", naga_line)
        self.assertIn("board tile's own movement_cost", naga_line)
        self.assertIn("defense=flat:30,hills:40", naga_line)
        self.assertIn("board tile's own defense", naga_line)
        # No overrides at all: an explicit "none", not a fabricated number,
        # and the fallback is still named (every terrain uses the tile).
        self.assertIn("move_costs=none (99=impassable", rendered)
        self.assertIn("defense=none (terrain not listed", rendered)
        # The field is entirely absent from the profile: unknown, not "none".
        self.assertIn("move_costs=unknown", rendered)
        self.assertIn("defense=unknown", rendered)

    def test_rejected_unit_destinations_block_marks_unavailable_or_renders_facts(self):
        no_unit = llm_client.rejected_unit_destinations_block(None, None, 338)
        self.assertIn("REJECTED_UNIT_LEGAL_DESTINATIONS unavailable reason=no_unit_identified_in_rejection", no_unit)

        no_data = llm_client.rejected_unit_destinations_block(11, None, 314)
        self.assertIn("REJECTED_UNIT_LEGAL_DESTINATIONS unavailable unit=11 "
                      "reason=no_inspection_result_in_scope", no_data)

        rendered = llm_client.rejected_unit_destinations_block(11, [
            {"col": 4, "row": 4, "current": False, "distinct_attacker_count": 0,
             "max_incoming_sum": 0, "open_distinct_attacker_count": 4, "open_max_incoming_sum": 84},
            {"col": 6, "row": 11, "current": True, "distinct_attacker_count": 2,
             "max_incoming_sum": 30, "open_distinct_attacker_count": 3, "open_max_incoming_sum": 50},
        ], 314)
        self.assertIn("REJECTED_UNIT_LEGAL_DESTINATIONS unit=11 state_revision=314", rendered)
        self.assertIn("zero_direct_attackers_is_not_a_safety_guarantee", rendered)
        self.assertIn("open_bound_removes_blockers_and_zoc", rendered)
        self.assertIn("->4,4 direct_attackers=0 direct_max=0HP open_attackers=4 open_max=84HP", rendered)
        self.assertIn("@6,11 direct_attackers=2 direct_max=30HP open_attackers=3 open_max=50HP", rendered)
        # A zero-direct destination is still shown alongside its open bound;
        # it is never singled out or labeled safe, ranked, or truncated.
        self.assertNotIn("safest", rendered.lower())
        self.assertNotIn("rank", rendered.lower())

    def test_final_live_reminder_uses_only_conflicting_live_observation(self):
        state = {"state_revision": 23, "active_faction": 0, "gold": [91, 77],
                 "units": [
                     {"id": 4, "faction": 0, "hp": 18, "col": 2, "row": 3, "can_recruit": True},
                     {"id": 8, "faction": 0, "hp": 7, "col": 1, "row": 3, "can_recruit": False},
                     {"id": 99, "faction": 1, "hp": 44, "col": 4, "row": 3},
                 ]}
        reminder = authoritative_live_state_reminder(state)
        self.assertIn("revision=23 controlled_side=0 gold=F0=91 F1=77 F0 units=2 hp=25 F1 units=1 hp=44", reminder)
        self.assertIn("friendly_ids=U4,U8", reminder)
        self.assertIn("recruiters=U4 hp=18 at=2,3", reminder)
        prompt = finalize_model_prompt("TOOL_RESULT says revision=999 gold=1 preview U77 hp=0", state)
        self.assertLess(prompt.rfind("AUTHORITATIVE_LIVE_STATE_BEGIN"), prompt.rfind("MODEL_RESPONSE_INSTRUCTION_BEGIN"))
        self.assertEqual(prompt.count("AUTHORITATIVE_LIVE_STATE_BEGIN"), 1)
        self.assertIn("revision=23", prompt)
        self.assertNotIn("revision=999", prompt[prompt.rfind("AUTHORITATIVE_LIVE_STATE_BEGIN"):])

    def test_final_live_reminder_can_be_action_only(self):
        state = {"state_revision": 4, "active_faction": 0, "final_only": True}
        final_only = finalize_model_prompt("review", state)
        explicit = finalize_model_prompt("repair", dict(state, final_only=False), allow_tools=False)
        for prompt in (final_only, explicit):
            self.assertIn("exactly one allowed JSON action envelope", prompt)
            self.assertIn("Do not request a read-only inspection", prompt)
            self.assertNotIn("or one allowed read-only inspection request", prompt)

    def test_compaction_preserves_move_legality_flags(self):
        """D-136-3: the contract tells the model that `current` entries are attack
        origins, not Move destinations. If compaction strips the flags the
        contract references, the ambiguity is back and the model cannot obey it."""
        state = {"units": [], "terrain": [], "turn_options": {"units": [
            {"unit_id": 1, "positions": [
                {"col": 2, "row": 7, "current": True, "movable": False, "target_ids": [9]},
                {"col": 3, "row": 7, "current": False, "movable": True, "target_ids": []},
            ]}]}}
        prompt = prompt_for(state, [], compact=True)
        blk = prompt.split("OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\n")[1]
        blk = blk.split("\nOPTION_PAYLOADS_UNTRUSTED_DATA_END")[0]
        positions = json.loads(blk)["turn_options"]["units"][0]["positions"]
        by_hex = {(p["col"], p["row"]): p for p in positions}
        self.assertTrue(by_hex[(2, 7)]["current"])
        self.assertFalse(by_hex[(2, 7)]["movable"])
        self.assertFalse(by_hex[(3, 7)]["current"])
        self.assertTrue(by_hex[(3, 7)]["movable"])
        # the standing hex must still be offered as an attack origin
        self.assertEqual(by_hex[(2, 7)]["target_ids"], [9])

    def test_tactical_prompt_names_coordinate_sources_and_recruitment_choice(self):
        prompt = prompt_for({"tactical_surface": {"units": [], "visibility": "full",
                                                    "next_round_time_of_day": "Night",
                                                    "next_opponent_time_of_day": "Dusk"}}, [], compact=True)
        for text in (
                "COORDS=col,row", '"tool":"inspect_units"', "Move destination", "compact R `open`",
                "RecruitBatch", "MoveGroupToward", "nonfinal", "moved/skipped", "explain deliberate saving",
                "For an uncertain attack origin, inspect the", "before retreat or deployment, inspect the specific unit",
                "Read-only inspection supplies facts", "Engage current hex is stationary, no Move",
                '"tool":"inspect_target"', '"tool":"inspect_units"'):
            with self.subTest(text=text):
                self.assertIn(text, prompt)
        self.assertIn("defender-killed, both-survive, and attacker-killed percentages", prompt)
        self.assertIn("expected damage is shown as HP", prompt)
        self.assertIn("705 bps = 7.05%", prompt)
        self.assertIn("visibility=full", prompt)
        # Both phases are shown, and the imminent opponent phase is distinct
        # from the next round's: conflating them was finding B5.
        self.assertIn("next_round_time_of_day=Night", prompt)
        self.assertIn("next_opponent_time_of_day=Dusk", prompt)
        self.assertNotIn('"origins"', prompt)
        self.assertNotIn('"outcome_bps"', prompt)
        choices_prompt = prompt_for(
            {"tactical_surface": {"units": [], "visibility": "full"}}, [],
            compact=True, action_encoding="choices", choices=[])
        self.assertIn('"choices": ["<handle>", ...]', choices_prompt)
        self.assertIn('"actions": [...', choices_prompt)
        self.assertIn("MoveGroupToward", choices_prompt)

    def test_incremental_prompt_describes_batch_observation_and_nested_indices(self):
        prompt = prompt_for(
            {"incremental_turns": True, "tactical_surface": {"units": []}}, [])
        self.assertIn("Observe after accepted batches only", prompt)
        self.assertIn("no intermediate observation", prompt)
        self.assertIn("Engage current hex is stationary, no Move", prompt)
        self.assertIn("failed_index is authored top-level index", prompt)
        self.assertIn("choice index differs", prompt)
        self.assertIn("Nested failures keep step/subaction", prompt)
        self.assertNotIn("Observe fresh state after each step", prompt)

    def test_focused_prompt_makes_bare_tools_and_incremental_intent_explicit(self):
        prompt = prompt_for(
            {"incremental_turns": True, "tactical_surface": {"units": []}}, [],
            intent="finish the wounded target before ending the turn",
            agenda={"tasks": [{"id": "finish", "goal": "Finish wounded target",
                                "units": [7], "status": "active"}], "holds": []},
            action_encoding="choices", decision_mode="focused")
        self.assertIn("Focused decisions are optional", prompt)
        self.assertIn("Bare tools: documented keys only", prompt)
        self.assertIn("focused_context", prompt)
        self.assertIn("finish the wounded target before ending the turn", prompt)
        self.assertIn("completing an operation does not end the turn", prompt)

    def test_annotation_contract_is_shared_and_matches_utf8_validator(self):
        for mode in ("batch", "focused"):
            for encoding in ("coordinates", "choices"):
                with self.subTest(mode=mode, encoding=encoding):
                    prompt = prompt_for({"incremental_turns": True}, [],
                                    decision_mode=mode,
                                    action_encoding=encoding)
                    self.assertEqual(prompt.count("Each decision group has exactly"), 1)
                    for text in ("exactly orders, rules, expected, risk",
                                 "1-4 unique guide IDs", "240 UTF-8 bytes",
                                 "16 groups and 256 references",
                                 "Tasks use exactly id, goal, units, status",
                             "units/holds are integer friendly-ID arrays"):
                        self.assertIn(text, prompt)

                    response = json.dumps({
                        "actions": [{"action": "EndTurn"}, {"action": "EndTurn"}],
                        "decisions": [{"orders": [1], "rules": ["T7"],
                                       "expected": "é" * 120,
                                       "risk": "🙂" * 60}],
                    })
                    result = annotation_for_response(
                        response, action_count=2,
                        require_full_coverage=(mode == "batch"))
                    self.assertEqual(result["status"],
                                     "valid" if mode == "focused" else "invalid")
                    self.assertEqual(validate_decisions(
                        [{"orders": [0], "rules": ["T7"],
                          "expected": "é" * 120, "risk": "🙂" * 60}],
                        1, require_full_coverage=True)[0]["orders"], [0])
                    too_long = dict(json.loads(response))
                    too_long["decisions"][0]["expected"] = "é" * 121
                    self.assertEqual(annotation_for_response(
                        json.dumps(too_long), action_count=2,
                        require_full_coverage=False)["status"], "invalid")

    def test_repair_and_followup_instructions_use_shared_annotation_contract(self):
        candidate_error = CandidateQueryError("preview_batch", "parse", "bad candidate")
        instructions = (
            tool_followup_instruction(1, 2),
            tool_budget_repair_prompt("PROMPT", "", "budget"),
            llm_client.candidate_repair_prompt(
                "PROMPT", "", [{"action": "EndTurn"}], candidate_error,
                preserve_tool=False),
        )
        for instruction in instructions:
            self.assertIn("shared annotation contract", instruction)
            self.assertNotIn("with decisions", instruction)

    def test_review_prompt_keeps_branch_difference_inside_json_fields(self):
        draft = self.annotated_orders("draft")
        final = self.annotated_orders("final")
        records, _, _ = self.run_annotation_path([draft, final], review=True)
        review_prompt = next(
            record["prompt"] for record in records
            if record["type"] == "model_request" and record["sequence"] == 2)
        self.assertIn("intent or decision expected/risk field", review_prompt)
        self.assertNotIn("State the relevant difference between the shown branches", review_prompt)

    def test_final_only_rejects_well_shaped_tool_before_engine_query(self):
        request = json.dumps({"tool": "inspect_hex", "col": 3, "row": 4,
                              "phase": "current"})
        lines = [{"type": "state", "active_faction": 0, "state_revision": 7,
                  "final_only": True, "units": []},
                 {"type": "status", "ok": True,
                  "results": [{"ok": True}]},
                 {"type": "game_end", "reason": "max_turns"}]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "query_inspect_hex") as inspect_hex:
            code, records = self.run_with_orders(
                [request, '[{"action":"DoneWithImportantMoves"}]'], lines,
                return_records=True)
        self.assertEqual(code, 0)
        inspect_hex.assert_not_called()
        self.assertFalse([r for r in records if r["type"] == "tool_result"])
        repair_request = [r for r in records if r["type"] == "model_request"][-1]
        self.assertIn("final-only response cannot request a tool", repair_request["prompt"])

    def test_repaired_tool_can_be_followed_by_another_bare_tool(self):
        malformed = json.dumps({"tool": "inspect_hex", "col": 3, "row": 4,
                                 "phase": "current", "decisions": []})
        corrected = json.dumps({"tool": "inspect_hex", "col": 3, "row": 4,
                                "phase": "current"})
        second = json.dumps({"tool": "inspect_units", "unit_ids": [7]})
        lines = [{"type": "state", "active_faction": 0, "state_revision": 7,
                  "units": [{"id": 7, "faction": 0}]},
                 {"type": "status", "ok": True,
                  "results": [{"ok": True}]},
                 {"type": "game_end", "reason": "max_turns"}]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "query_inspect_hex", return_value={"terrain": "open"}) as inspect_hex, \
                mock.patch.object(llm_client, "query_inspect_units", return_value=[]) as inspect_units:
            code, records = self.run_with_orders(
                [malformed, corrected, second,
                 '[{"action":"DoneWithImportantMoves"}]'], lines,
                return_records=True, max_model_calls_per_turn=5)
        self.assertEqual(code, 0)
        self.assertEqual(inspect_hex.call_count, 1)
        self.assertEqual(inspect_units.call_count, 1)
        self.assertEqual([r["tool"] for r in records if r["type"] == "tool_result"],
                         ["inspect_hex", "inspect_units"])
        self.assertTrue([r for r in records if r["type"] == "forwarded_orders"])

    def test_completion_audit_separates_flags_from_actual_attack_coverage(self):
        rendered = compact_observation({
            "active_faction": 0, "units": [
                {"id": 1, "faction": 0, "moved": True, "attacked": False},
                {"id": 2, "faction": 0, "moved": False, "attacked": True},
            ], "tactical_surface": {"units": [{"unit_id": 2, "origins": [
                {"current": True, "engagements": [{"defender_id": 9}]}
            ]}]}
        })
        self.assertIn("movement_remaining=U2", rendered)
        self.assertIn("attack_remaining=U1", rendered)
        self.assertIn("attack_coverage=U2", rendered)
        self.assertNotIn("ready=", rendered)

    def test_compact_observation_uses_col_row_coordinates(self):
        state = {"units": [{"id": 1, "faction": 0, "def_id": "leader",
                             "col": 3, "row": 7, "hp": 1, "max_hp": 1}],
                 "terrain": [], "tactical_surface": {"visibility": "full",
                                                        "next_round_time_of_day": "Dawn"}}
        rendered = compact_observation(state)
        self.assertIn("pos=(3,7)", rendered)
        self.assertNotIn("pos=(7,3)", rendered)

    def test_real_driver_turn_options_mark_current_and_movable_hexes(self):
        driver = Path(os.environ.get("NORRUST_TEST_DRIVER", str(
            Path(__file__).resolve().parents[1] / "norrust_core" / "target" / "debug" / "greedy_driver")))
        if not driver.exists():
            self.skipTest("greedy_driver has not been built")
        process = subprocess.Popen(
            [str(driver), "--scenario", "big_battle_6", "--faction0", "undead",
             "--faction1", "undead", "--gold", "300", "--seed", "2001",
             "--llm-side", "0", "--max-turns", "1", "--turn-timeout", "5",
             "--query-budget-seconds", "5"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        try:
            self.assertEqual(json.loads(process.stdout.readline())["type"], "protocol")
            # The opening precedes the first playable state. It is a distinct
            # record type rather than a second "state" line precisely so a
            # live client does not read it as "it is your move".
            opening = json.loads(process.stdout.readline())
            self.assertEqual(opening["type"], "game_start")
            self.assertEqual(opening["state"]["type"], "state")
            self.assertEqual(opening["side_turns"], 0)
            self.assertEqual(json.loads(process.stdout.readline())["type"], "state")
            process.stdin.write(json.dumps({"action": "Query", "what": "turn_options"}) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            positions = [position for unit in response["body"]["units"]
                         for position in unit["positions"]]
            self.assertTrue(any(position.get("current") is True and position.get("movable") is False
                                for position in positions))
            self.assertTrue(any(position.get("current") is False and position.get("movable") is True
                                for position in positions))
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()

    def test_prompt_is_canonical(self):
        state = {"units": [{"id": 2}, {"id": 1}]}
        self.assertEqual(prompt_for(state, []), prompt_for(state, []))

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"EndTurn","surprise":true}]')

    def test_advance_requires_one_selector(self):
        with self.assertRaises(ValueError):
            validate_orders('[{"action":"Advance","unit_id":1},{"action":"EndTurn"}]')

    def test_prompt_is_a_self_contained_action_contract(self):
        prompt = prompt_for({"units": []}, [],
                            {"options": [{"def_id": "Skeleton", "cost": 3,
                                           "affordable": True}],
                             "placement_hexes": [{"col": 2, "row": 4}],
                             "faction_id": "undead", "side_can_place": True,
                             "batch_macro_enabled": True})
        required = [
            'non-empty JSON array', 'at most 256',
            'exactly one final DoneWithImportantMoves, EndTurn, or FinishWithGreedy boundary',
            'Move', '"unit_id": integer', '"col": integer', '"row": integer',
            'Attack', '"attacker_id": integer', '"defender_id": integer',
            'Recruit', '"def_id": string', 'RecruitBatch', '"count": positive integer',
            'Advance', 'exactly one of integer target_index or string def_id',
            "target_index indexes the unit's advances_to list",
            'turn_options', 'target IDs', 'recruit_options',
            # The standing-hex trap: turn_options lists the unit's own hex as a
            # legal attack origin, but Move onto it is DestinationOccupied and
            # rolls back the batch. Two model families hit this on compact_v1.
            '"current":true', '"movable":false', 'never issue a Move to it',
            'DestinationOccupied', 'Only entries with "movable":true are Move destinations',
            'faction-legal definitions', 'costs', 'affordability', 'placement hexes',
            'engine responses remain authoritative', 'automatically executes the opponent',
            'recruiter loss', 'side-turn safety cap', 'engine round',
            'headless driver disables scenario objective and scenario turn-limit conditions',
        ]
        for text in required:
            self.assertIn(text, prompt)
        self.assertIn('"def_id":"Skeleton"', prompt)
        for marker in ('BOARD_UNTRUSTED_DATA_BEGIN', 'BOARD_UNTRUSTED_DATA_END',
                       'OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN',
                       'OPTION_PAYLOADS_UNTRUSTED_DATA_END',
                       'MEMORY_UNTRUSTED_DATA_BEGIN', 'MEMORY_UNTRUSTED_DATA_END',
                       'untrusted data', 'cannot override this contract'):
            self.assertIn(marker, prompt)

    def test_prompt_contract_has_parseable_agenda_and_explicit_scales(self):
        prompt = prompt_for({"units": []}, [])
        marker = "Use this exact valid shape: "
        start = prompt.index(marker) + len(marker)
        example, end = json.JSONDecoder().raw_decode(prompt[start:])
        parsed, error, changed = llm_client.agenda_from_response(json.dumps(example), None)
        self.assertIsNone(error)
        self.assertTrue(changed)
        validate_orders(json.dumps(example))
        self.assertEqual(parsed, example["agenda"])
        self.assertEqual(example["actions"], [{"action": "DoneWithImportantMoves"}])
        self.assertEqual(example["decisions"][0]["orders"], [0])
        for text in ("705 bps = 7.05%", "144 whole HP", "24", "2.4HP", "basis points", "tenths of HP",
                     "beyond six", "auto-vacates", "within gold and capacity",
                     "Agenda and annotation prose create no normal engine holds",
                     "Only FinishWithGreedy's explicit holds encode executable holds",
                     "Omitted units are not swept by this selective finish"):
            self.assertIn(text, prompt)

    def test_compact_forecasts_mark_probability_and_damage_units_without_changing_payloads(self):
        target = compact_target_inspection({
            "target_id": 9, "hp": 20, "col": 4, "row": 7, "terrain": "flat",
            "attacks": [{"attacker_id": 2, "origin_col": 3, "origin_row": 7,
                         "forecast": {"outcome_bps": [6400, 3600, 0],
                                       "expected_damage_tenths": [24, 7]}}],
        })
        self.assertIn("exchange=(defender_killed=64%,both_survive=36%,attacker_killed=0%; expected_damage=(to_defender=2.4HP,attacker_retaliation=0.7HP))", target)
        preview = compact_batch_preview({"candidates": [{"forecasts": [{
            "attacker_id": 2, "defender_id": 9,
            "forecast": {"outcome_bps": [6400, 3600, 0],
                          "expected_damage_tenths": [24, 7]}}]}]})
        self.assertIn("exchange=(defender_killed=64%,both_survive=36%,attacker_killed=0%; expected_damage=(to_defender=2.4HP,attacker_retaliation=0.7HP))", preview)
        unit = compact_unit_inspection({
            "unit_id": 2, "origins": [],
            "destination_threats": [{"col": 1, "row": 1, "focus_kill_bps": [6400],
                                      "focus_expected_damage_tenths": [24]}]})
        self.assertIn("focus_kills=(kill_by_1=64%,kill_by_2=unknown,kill_by_3=unknown) focus_expected=(damage_from_1=2.4HP", unit)
        surface = compact_tactical_surface({
            "units": [{"unit_id": 2, "origins": [{"current": True, "col": 1, "row": 1,
                "engagements": [{"defender_id": 9, "forecast": {
                    "outcome_bps": [6400, 3600, 0], "expected_damage_tenths": [24, 7]}}]}]}]})
        self.assertIn("exchange=(defender_killed=64%,both_survive=36%,attacker_killed=0%; expected_damage=(to_defender=2.4HP,attacker_retaliation=0.7HP))", surface)
        reviewed, _ = compact_draft_review({"candidates": [{"exposure": {"units": [
            {"unit_id": 2, "distinct_attacker_count": 1, "focus_kill_bps": [6400],
             "focus_expected_damage_tenths": [24]}]}}, {"exposure": {"units": [
             {"unit_id": 2, "distinct_attacker_count": 1, "focus_kill_bps": [6400],
              "focus_expected_damage_tenths": [24]}]}}]}, False)
        self.assertIn("focus_kills=(kill_by_1=64%,kill_by_2=unknown,kill_by_3=unknown) focus_expected=(damage_from_1=2.4HP", reviewed)

    def test_action_repair_explains_transactional_rollback(self):
        prompt = prompt_for({}, [])
        repair = prompt + '\nROLLBACK_NOTICE: the entire preceding action batch was rejected transactionally; no prefix action committed.'
        self.assertIn('no prefix action committed', repair)

    def test_prompt_starts_with_exact_canonical_tactical_playbook(self):
        prompt = prompt_for({}, [])
        canonical = llm_client.PLAYBOOK_PATH.read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith(canonical + "\n"))
        self.assertEqual(prompt.count(canonical), 1)

    def test_canonical_tactical_playbook_retains_core_tradeoffs(self):
        canonical = " ".join(llm_client.PLAYBOOK_PATH.read_text(encoding="utf-8").split())
        for guidance in (
            "Village ownership persists after leaving",
            "one recruit at a time",
            "Recruit a screen before deploying if needed",
            "Replacing casualties costs gold, travel time, and XP",
            "restores its new maximum HP",
            "the unit must survive combat",
            "judge the combined attack",
            "credible recovery or victory route",
        ):
            with self.subTest(guidance=guidance):
                self.assertIn(guidance, canonical)

    def test_playbook_loading_is_independent_of_working_directory(self):
        expected_path = Path(llm_client.__file__).resolve().parents[1] / \
            "docs" / "LLM_TACTICAL_PLAYBOOK.md"
        self.assertEqual(llm_client.PLAYBOOK_PATH, expected_path)
        expected = llm_client.PLAYBOOK_PATH.read_text(encoding="utf-8")
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                self.assertTrue(prompt_for({}, []).startswith(expected + "\n"))
            finally:
                os.chdir(original_cwd)

    def test_missing_playbook_has_actionable_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing-norrust-playbook.md"
            with mock.patch.object(llm_client, "PLAYBOOK_PATH", missing), \
                    self.assertRaisesRegex(
                        RuntimeError,
                        r"model_prompt_error: canonical tactical playbook is missing or unreadable.*"
                        r"restore docs/LLM_TACTICAL_PLAYBOOK\.md",
                    ):
                prompt_for({}, [])

    def test_docs_link_to_canonical_playbook_without_checklist_duplication(self):
        docs_dir = llm_client.PLAYBOOK_PATH.parent
        for name in ("LLM_CLIENT.md", "LLM_VS_ALGORITHM.md"):
            text = (docs_dir / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("[MEMORYLESS TACTICAL PLAYBOOK](LLM_TACTICAL_PLAYBOOK.md)", text)
                self.assertIn("inline near the beginning of every model", text)
                self.assertIn("does not need filesystem access", text)
                self.assertNotIn("Protect the recruiter/leader first", text)
                self.assertNotIn("Apply this every turn:", text)

    def test_prompt_defines_exactly_one_prior_recruiter_side_losing_all_recruiters(self):
        prompt = prompt_for({}, [])
        self.assertIn("exactly one side that previously had a recruiter now has none", prompt)
        self.assertNotIn("sole recruiter", prompt)

    def test_prompt_omits_disabled_recruit_macro_wording(self):
        prompt = prompt_for({}, [], {}, recruit_batch_enabled=False)
        self.assertNotIn('RecruitBatch: {"action"', prompt)

    def test_validation_enforces_scalar_types_and_positive_count(self):
        valid = '[{"action":"RecruitBatch","def_id":"Skeleton","count":1},{"action":"EndTurn"}]'
        validate_orders(valid)
        for order in [
            {"action": "Move", "unit_id": "1", "col": 1, "row": 1},
            {"action": "Recruit", "def_id": 3, "col": 1, "row": 1},
            {"action": "RecruitBatch", "def_id": "Skeleton", "count": 0},
            {"action": "RecruitBatch", "def_id": "Skeleton", "count": True},
            {"action": "Move", "unit_id": 2**32, "col": 1, "row": 1},
            {"action": "Move", "unit_id": 1, "col": 2**31, "row": 1},
            {"action": "Advance", "unit_id": 1, "target_index": -1},
        ]:
            with self.subTest(order=order), self.assertRaises(ValueError):
                validate_orders(json.dumps([order, {"action": "EndTurn"}]))

    def test_usage_metadata_rejects_wrong_type_boolean_and_negative_counts(self):
        args = argparse.Namespace(token_input_limit=None, token_output_limit=None,
                                  token_total_limit=None)
        for usage in [[], {"input_tokens": True, "output_tokens": 1},
                      {"input_tokens": -1, "output_tokens": 1},
                      {"input_tokens": 1, "output_tokens": -1}]:
            with self.subTest(usage=usage), self.assertRaises(RuntimeError):
                enforce_usage(ModelReply("[]", usage), args)

    def test_query_options_are_singleton_and_preserve_success_body(self):
        calls = []

        def exchange(request):
            calls.append(request)
            return {"type": "status", "ok": True, "what": request["what"],
                    "body": {"authoritative": request["what"]}}

        result = query_options(exchange)
        self.assertEqual([call["what"] for call in calls],
                         ["turn_options", "recruit_options"])
        self.assertEqual(result["turn_options"], {"authoritative": "turn_options"})
        self.assertEqual(result["recruit_options"], {"authoritative": "recruit_options"})
        prompt = prompt_for(result, [], result["recruit_options"])
        self.assertIn('"authoritative":"turn_options"', prompt)
        self.assertIn('"authoritative":"recruit_options"', prompt)

    def test_failure_terminal_classes_are_durable_invalid_failures(self):
        lines = [
            ("setup_error", "invalid_setup"),
            ("timeout", "turn_timeout"),
            ("eof", "driver_eof"),
            ("infrastructure_failure", "greedy_turn_failed"),
            ("unknown_reason", "mystery"),
            ("malformed_reason", None),
        ]
        for label, reason in lines:
            with self.subTest(reason=label):
                line = {"type": "game_end", "winner": None,
                        "code": "driver_code", "message": "driver message"}
                if reason is not None:
                    line["reason"] = reason
                code, terminal, fsync_calls = self.run_terminal(line)
                self.assertEqual(code, 1)
                self.assertTrue(terminal["infrastructure_invalid"])
                self.assertFalse(terminal["gameplay_valid"])
                self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
                self.assertEqual(terminal.get("reason"), reason)
                self.assertEqual(terminal["code"], "driver_code")
                self.assertEqual(terminal["message"], "driver message")
                self.assertGreaterEqual(fsync_calls, 1)

    def test_malformed_driver_json_is_durable_invalid_failure(self):
        code, terminal, fsync_calls = self.run_terminal("not json\n")
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertEqual(terminal["reason"], "infrastructure_failure")
        self.assertEqual(terminal["code"], "driver_protocol_invalid_json")
        self.assertEqual(terminal["message"], "driver emitted invalid JSON")
        self.assertEqual(terminal["raw_line"], "not json")
        self.assertGreaterEqual(fsync_calls, 1)

    def test_gameplay_and_max_turns_game_end_remain_successful(self):
        for line in [
            {"type": "game_end", "reason": "winner", "winner": 0},
            {"type": "game_end", "reason": "max_turns", "winner": None},
        ]:
            with self.subTest(reason=line["reason"]):
                code, terminal, fsync_calls = self.run_terminal(line)
                self.assertEqual(code, 0)
                self.assertFalse(terminal["infrastructure_invalid"])
                self.assertTrue(terminal["gameplay_valid"])
                self.assertEqual(terminal["terminal_class"], TERMINAL_GAMEPLAY)
                self.assertEqual(terminal["reason"], line["reason"])
                self.assertGreaterEqual(fsync_calls, 1)

    def test_embedded_terminal_state_is_recorded_as_its_own_driver_state_line(self):
        # A winning partial batch (or a win the driver detects before it
        # would otherwise print another boundary) never gets a normal
        # `type:"state"` line -- printing one there would make the live
        # protocol think the game continues and query the exiting driver.
        # The driver instead embeds the exact ending snapshot inside
        # `game_end` under `state`; the client must record that as its own
        # driver "state" line so the importer can bind the terminal to a
        # provable, exact-revision snapshot exactly like any other logged
        # state.
        embedded_state = {"type": "state", "state_revision": 12, "turn": 4,
                          "active_faction": 0, "turn_boundary": "partial", "units": []}
        line = {"type": "game_end", "reason": "winner", "winner": 0,
                "state_revision": 12, "side_turns": 6, "state": embedded_state}
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=True, orders_file=None,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess([line])
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        self.assertEqual(code, 0)
        synthetic = [r for r in records if r.get("type") == "driver"
                     and r.get("line", {}).get("type") == "state"]
        self.assertEqual(len(synthetic), 1)
        self.assertEqual(synthetic[0]["line"], embedded_state)
        # The synthetic state line must precede the terminal record so the
        # importer's "terminal is always last" assumption still holds.
        terminal_index = next(i for i, r in enumerate(records) if r.get("type") == "terminal")
        state_index = next(i for i, r in enumerate(records) if r is synthetic[0])
        self.assertLess(state_index, terminal_index)

    def test_terminal_without_an_embedded_state_records_no_synthetic_state_line(self):
        line = {"type": "game_end", "reason": "max_turns", "winner": None,
                "state_revision": 3, "side_turns": 2}
        code, records = self.run_terminal_all(line)
        self.assertEqual(code, 0)
        self.assertFalse(any(r.get("type") == "driver" and r.get("line", {}).get("type") == "state"
                             for r in records))

    def run_terminal_all(self, line):
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=True, orders_file=None,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess([line])
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records

    def test_status_ok_false_is_durable_failure_without_waiting_for_more_input(self):
        line = {"type": "status", "ok": False, "code": "unauthorized_side",
                "message": "model actions are not authorized"}
        code, terminal, _ = self.run_after_forwarded_orders(line)
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertEqual(terminal["reason"], "infrastructure_failure")
        self.assertEqual(terminal["code"], "driver_status_failure")
        self.assertEqual(terminal["message"], "driver returned a failed status")
        self.assertEqual(terminal["driver_failure"]["code"], "unauthorized_side")

    def test_status_nested_failed_result_is_durable_failure_without_waiting_for_more_input(self):
        # One canned reply only: the nested failure triggers a repair, the orders
        # file is exhausted, and the backend raises. An exhausted fixture is a
        # harness fault, so this stays infrastructure -- it does not exercise the
        # model_invalid path (see the two-reply test below).
        line = {"type": "status", "ok": True,
                "results": [{"ok": True}, {"ok": False, "code": "MoveError",
                                             "message": "invalid move"}]}
        code, terminal, _ = self.run_after_forwarded_orders(line)
        self.assertEqual(code, 1)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertIn(terminal.get("type"), {"model_error", "driver_crash", "terminal"})

    def test_classify_terminal_is_three_way(self):
        for reason in ("winner", "max_turns"):
            self.assertEqual(classify_terminal(reason), TERMINAL_GAMEPLAY)
        self.assertEqual(classify_terminal("model_invalid"), TERMINAL_MODEL_INVALID)
        for reason in ("setup_error", "timeout", "eof", "infrastructure_failure",
                       "mystery", None):
            self.assertEqual(classify_terminal(reason), TERMINAL_INFRASTRUCTURE)
        self.assertEqual(classify_terminal("budget_interrupted"), TERMINAL_BUDGET_INTERRUPTED)
        self.assertEqual(
            sorted(TERMINAL_EXIT_CODES.values()), [0, 1, 2, 3],
            "all four terminal classes must be distinguishable by exit code alone")

    def test_nested_failure_with_repair_exhausted_is_model_invalid(self):
        """The batch is rolled back and the model had its repair. That is a model
        failure, not a broken harness: it must not void the run as
        infrastructure_invalid, and it must not be recorded as gameplay."""
        end_turn = '[{"action":"EndTurn"}]'
        failure = {"type": "status", "ok": True,
                   "results": [{"ok": False, "code": "MoveError",
                                "message": "invalid move"}]}
        code, terminal = self.run_with_orders(
            [end_turn, end_turn],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "turn_options", "body": {}},
             {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
             failure,   # first rejection -> one repair is spent
             failure],  # second rejection -> budget gone
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        self.assertEqual(terminal["terminal_class"], TERMINAL_MODEL_INVALID)
        self.assertFalse(terminal["infrastructure_invalid"])
        self.assertFalse(terminal["gameplay_valid"])
        self.assertEqual(terminal["reason"], "model_invalid")
        self.assertEqual(terminal["code"], "action_batch_rejected")
        self.assertTrue(terminal["rolled_back"])
        self.assertEqual(terminal["driver_failure"]["code"], "MoveError")

    def test_pre_submit_validation_retries_until_a_valid_batch(self):
        end_turn = '[{"action":"EndTurn"}]'
        invalid = {"type": "status", "ok": True, "what": "validate_batch",
                   "body": {"valid": False, "failed_index": 0,
                             "results": [{"ok": False, "code": "MoveError",
                                          "message": "invalid move"}]}}
        valid = {"type": "status", "ok": True, "what": "validate_batch",
                 "body": {"valid": True, "failed_index": None,
                           "results": [{"ok": True}]}}
        code, terminal = self.run_with_orders(
            [end_turn, end_turn, end_turn],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             invalid, invalid, valid,
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            validate_before_submit=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_partial_limit_uses_selective_finish_instead_of_model_invalid(self):
        partial = json.dumps([{"action": "Move", "unit_id": 1, "col": 2, "row": 3}])
        limited = {"type": "status", "ok": False, "what": "validate_batch",
                   "code": "partial_limit", "message": "next batch must end the turn"}
        valid = {"type": "status", "ok": True, "what": "validate_batch",
                 "body": {"valid": True, "failed_index": None, "results": [{"ok": True}]}}
        code, terminal = self.run_with_orders(
            [partial],
            [{"type": "state", "active_faction": 0, "units": []},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             limited, valid, {"type": "game_end", "reason": "max_turns", "winner": None}],
            validate_before_submit=True, incremental_turns=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")
        self.assertEqual(terminal["partial_limit_finishes"], 1)

    def test_action_repair_can_inspect_before_returning_corrected_batch(self):
        end_turn = json.dumps([{"action": "EndTurn"}])
        inspect = json.dumps({"tool": "inspect_target", "unit_id": 9})
        invalid = {"type": "status", "ok": True, "what": "validate_batch",
                   "body": {"valid": False, "failed_index": 0,
                             "results": [{"ok": False, "code": "NotAdjacent",
                                          "message": "units are not in attack range"}]}}
        valid = {"type": "status", "ok": True, "what": "validate_batch",
                 "body": {"valid": True, "failed_index": None,
                           "results": [{"ok": True}]}}
        code, terminal = self.run_with_orders(
            [end_turn, inspect, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 4},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             invalid,
             {"type": "status", "ok": True, "what": "inspect_target",
              "body": {"target_id": 9, "hp": 20, "col": 2, "row": 2,
                       "terrain": "flat", "attacks": []}},
             valid,
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            validate_before_submit=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_action_repair_tool_request_gets_one_bounded_action_followup(self):
        invalid = json.dumps([{"action": "Attack", "attacker_id": 1, "defender_id": 9},
                              {"action": "EndTurn"}])
        tool = json.dumps({"tool": "inspect_units", "unit_ids": [1]})
        corrected = json.dumps([{"action": "EndTurn"}])
        failure = {"type": "status", "ok": True,
                   "results": [{"ok": False, "code": "NotAdjacent",
                                "message": "units are not in attack range"}]}
        success = {"type": "status", "ok": True,
                   "results": [{"ok": True}]}
        code, terminal = self.run_with_orders(
            [invalid, tool, corrected],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             failure, success,
             {"type": "game_end", "reason": "max_turns", "winner": None}],
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_preview_round_trip_forwards_model_selected_candidate(self):
        first = [{"action": "EndTurn"}]
        second = [{"action": "Move", "unit_id": 1, "col": 2, "row": 3},
                  {"action": "EndTurn"}]
        inspect_request = json.dumps({"tool": "inspect_units", "unit_ids": [1]})
        preview_request = json.dumps({"tool": "preview_batch", "candidates": [first, second]})
        with tempfile.TemporaryDirectory() as directory:
            orders_path = directory + "/orders.jsonl"
            log_path = directory + "/client.jsonl"
            with open(orders_path, "w") as orders_file:
                orders_file.write(json.dumps({"text": inspect_request}) + "\n")
                orders_file.write(json.dumps({"text": preview_request}) + "\n")
                orders_file.write(json.dumps({"text": json.dumps(second)}) + "\n")
            process = FakeDriverProcess([
                {"type": "state", "active_faction": 0, "state_revision": 7,
                 "units": [{"id": 1, "faction": 0, "hp": 20}]},
                {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
                {"type": "status", "ok": True, "what": "inspect_unit", "state_revision": 7, "body": {
                    "unit_id": 1, "origins": []}},
                {"type": "status", "ok": True, "what": "preview_batch", "body": {
                    "mode": "bounded_rollout", "sampling": True, "candidates": [
                        {"valid": True, "summary": {}, "forecasts": [], "recruiter_threats": {"recruiters": []}},
                        {"valid": True, "summary": {}, "forecasts": [], "recruiter_threats": {"recruiters": []}},
                    ]}},
                {"type": "status", "ok": True, "what": "validate_batch", "body": {
                    "valid": True, "failed_index": None, "results": [{"ok": True}, {"ok": True}]}},
                {"type": "status", "ok": True, "what": "preview_batch", "body": {
                    "sampling": False, "candidates": [{"valid": True, "summary": {
                        "affordable_recruitment_remaining": False}, "forecasts": [],
                        "recruiter_threats": {"recruiters": []}}]}},
                {"type": "game_end", "reason": "max_turns", "winner": None},
            ])
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b", gold=1,
                seed=2, max_turns=3, llm_side=0, turn_timeout=20, query_budget_seconds=5,
                max_queries_per_turn=6, no_recruit_macro=False, interactive_model=False,
                orders_file=orders_path, model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None, validate_before_submit=True,
                max_model_calls_per_turn=4, event_window_observations=1, diagnostic=False,
                decision_metrics=True,
            )
            prompts = []
            original_complete = llm_client.OrdersBackend.complete
            def capture_prompt(backend, prompt):
                prompts.append(prompt)
                return original_complete(backend, prompt)
            with mock.patch.object(llm_client.OrdersBackend, "complete", capture_prompt), \
                    mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            records = [json.loads(line) for line in Path(log_path).read_text().splitlines()]

        self.assertEqual(code, 0)
        sent = [json.loads(line) for line in process.stdin.getvalue().splitlines()]
        self.assertEqual(sent[0]["what"], "tactical_surface")
        self.assertEqual(sent[1]["what"], "inspect_unit")
        self.assertEqual(sent[2]["what"], "preview_batch")
        self.assertEqual(sent[2]["mode"], "bounded_rollout")
        self.assertEqual(sent[3]["what"], "validate_batch")
        self.assertEqual(sent[4]["what"], "preview_batch")
        self.assertEqual(sent[5], second)
        self.assertIn(inspect_request, prompts[1])
        self.assertIn(preview_request, prompts[2])
        self.assertIn(json.dumps(first), prompts[2])
        self.assertIn(json.dumps(second), prompts[2])
        self.assertEqual([record for record in records if record["type"] == "preview_selection"][0]["matched_candidate"], 1)
        self.assertEqual(len([record for record in records if record["type"] == "final_batch_preview"]), 1)

    def test_model_output_invalid_twice_is_model_invalid(self):
        """Validation failure on both the first call and the repair is the model
        failing to emit a legal batch -- classified as model, not harness."""
        code, terminal = self.run_with_orders(
            ["not a json array", "still not a json array"],
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "turn_options", "body": {}},
             {"type": "status", "ok": True, "what": "recruit_options", "body": {}}],
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_MODEL_INVALID])
        self.assertEqual(terminal["terminal_class"], TERMINAL_MODEL_INVALID)
        self.assertFalse(terminal["infrastructure_invalid"])
        self.assertFalse(terminal["gameplay_valid"])
        self.assertEqual(terminal["code"], "action_validation_invalid")

    def test_tool_budget_exhaustion_repairs_with_context(self):
        request = json.dumps({"tool": "inspect_units", "unit_ids": [1]})
        end_turn = json.dumps([{"action": "EndTurn"}])
        code, records = self.run_with_orders(
            [request, request, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 1,
              "units": [{"id": 1, "faction": 0, "hp": 20}]},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             {"type": "status", "ok": True, "what": "inspect_unit", "state_revision": 1,
              "body": {"unit_id": 1, "origins": []}},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=4,
            max_tool_calls_per_turn=1,
            return_records=True,
        )
        terminal = records[-1]
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["reason"], "max_turns")
        repair_prompt = [r["prompt"] for r in records if r["type"] == "model_request"][-1]
        self.assertIn("Return one corrected JSON action envelope", repair_prompt)
        self.assertIn("do not request another tool", repair_prompt.lower())

    def test_tool_followup_budget_emits_budget_interrupted(self):
        request = json.dumps({"tool": "inspect_units", "unit_ids": [1]})
        code, records = self.run_with_orders(
            [request],
            [{"type": "state", "active_faction": 0, "state_revision": 1,
              "units": [{"id": 1, "faction": 0, "hp": 20}]},
             {"type": "status", "ok": True, "what": "tactical_surface",
              "body": {"units": []}},
             {"type": "status", "ok": True, "what": "inspect_unit",
              "state_revision": 1, "body": {"unit_id": 1, "origins": []}}],
            max_model_calls_per_turn=1, return_records=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_BUDGET_INTERRUPTED])
        self.assertEqual(records[-1]["type"], "terminal")
        self.assertEqual(records[-1]["reason"], "budget_interrupted")
        self.assertEqual(records[-1]["code"], "model_calls_budget_exhausted")
        self.assertEqual(records[-1]["model_calls"], 1)

    def test_tool_repair_budget_emits_budget_interrupted(self):
        malformed = json.dumps({"tool": "inspect_units", "unit_ids": [1],
                                "actions": []})
        code, records = self.run_with_orders(
            [malformed],
            [{"type": "state", "active_faction": 0, "state_revision": 1,
              "units": [{"id": 1, "faction": 0, "hp": 20}]},
             {"type": "status", "ok": True, "what": "tactical_surface",
              "body": {"units": []}}],
            max_model_calls_per_turn=1, return_records=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_BUDGET_INTERRUPTED])
        self.assertEqual(records[-1]["reason"], "budget_interrupted")
        self.assertEqual(records[-1]["code"], "model_calls_budget_exhausted")

    def test_malformed_tool_with_only_last_model_call_gets_action_repair(self):
        malformed = json.dumps({"tool": "inspect_units", "unit_ids": [1],
                                "actions": []})
        end_turn = json.dumps([{"action": "EndTurn"}])
        code, records = self.run_with_orders(
            [malformed, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 1,
              "units": [{"id": 1, "faction": 0, "hp": 20}]},
             {"type": "status", "ok": True, "what": "tactical_surface",
              "body": {"units": []}},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=2, return_records=True)
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        repair_prompt = [r["prompt"] for r in records
                         if r["type"] == "model_request"][-1]
        self.assertIn("Return one corrected JSON action envelope", repair_prompt)
        self.assertIn("Do not request a read-only inspection", repair_prompt)
        self.assertNotIn("TOOL_REPAIR_INSTRUCTION", repair_prompt)
        self.assertFalse([r for r in records if r["type"] == "tool_result"])

    def test_preview_candidate_with_only_last_model_call_gets_action_repair(self):
        preview = json.dumps({"tool": "preview_batch", "candidates": [
            [{"action": "EndTurn"}],
            [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
        ]})
        corrected = self.annotated_orders("corrected")
        code, records = self.run_with_orders(
            [preview, corrected],
            [{"type": "state", "active_faction": 0, "state_revision": 286,
              "units": []},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {"units": []}},
             {"type": "status", "ok": False, "what": "preview_batch",
              "code": "unauthorized_unit", "candidate_index": 1,
              "message": "FinishWithGreedy may reference only living model-side units"},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=2, return_records=True)
        self.assertEqual(code, 0)
        repair_prompt = next(record["prompt"] for record in records
                             if record["type"] == "model_request" and record["sequence"] == 2)
        self.assertIn("Return one corrected JSON action envelope", repair_prompt)
        self.assertIn("Do not request a read-only inspection", repair_prompt)
        self.assertNotIn("TOOL_REPAIR_INSTRUCTION", repair_prompt)
        self.assertFalse([r for r in records if r["type"] == "tool_result"])

    def test_critical_draft_can_be_confirmed_after_preview(self):
        end_turn = json.dumps([{"action": "EndTurn"}])
        review_tool = json.dumps({"tool": "inspect_units", "unit_ids": [1]})
        code, terminal = self.run_with_orders(
            [end_turn, review_tool, end_turn],
            [{"type": "state", "active_faction": 0, "state_revision": 0,
              "units": [{"id": 1, "faction": 0, "can_recruit": True}]},
             {"type": "status", "ok": True, "what": "tactical_surface", "body": {
                 "threats": {"recruiters": [{"recruiter_id": 1, "lethal_attackers_needed": 1}]}}},
             {"type": "status", "ok": True, "what": "preview_batch", "body": {
                 "sampling": False, "candidates": [{"valid": True, "recruiter_threats": {
                     "recruiters": [{"recruiter_id": 1, "hp": 34,
                                     "distinct_attacker_count": 2, "max_incoming_sum": 40,
                                     "lethal_attackers_needed": 1}]}}]}},
             {"type": "status", "ok": True, "what": "validate_batch", "body": {
                 "valid": True, "failed_index": None, "results": [{"ok": True}]}},
             {"type": "game_end", "reason": "max_turns", "winner": None}],
            max_model_calls_per_turn=4,
            max_tool_calls_per_turn=2,
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_GAMEPLAY])
        self.assertEqual(terminal["draft_reviews"], 1)
        self.assertEqual(terminal["draft_confirmations"], 1)
        self.assertEqual(terminal["draft_revisions"], 0)
        self.assertEqual(terminal["draft_review_repairs"], 1)

    def test_backend_transport_failure_stays_infrastructure(self):
        """A RuntimeError from the backend is transport, not play. The model
        never emitted an illegal batch, so it must not be blamed for one."""
        code, terminal = self.run_with_orders(
            [],  # exhausted immediately: backend raises RuntimeError
            [{"type": "state", "active_faction": 0},
             {"type": "status", "ok": True, "what": "turn_options", "body": {}},
             {"type": "status", "ok": True, "what": "recruit_options", "body": {}}],
        )
        self.assertEqual(code, TERMINAL_EXIT_CODES[TERMINAL_INFRASTRUCTURE])
        self.assertEqual(terminal["terminal_class"], TERMINAL_INFRASTRUCTURE)
        self.assertTrue(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["code"], "model_backend_failure")

    def test_command_backend_retries_one_process_exit_with_same_prompt(self):
        success = subprocess.CompletedProcess(
            "model", 0, '{"text":"[{\\"action\\":\\"EndTurn\\"}]"}', "")
        failure = subprocess.CompletedProcess("model", 7, "", "temporary")
        with mock.patch("subprocess.run", side_effect=[failure, success]) as run:
            backend = llm_client.CommandBackend("model", 1)
            reply = backend.complete("same prompt")
        self.assertIn("EndTurn", reply.text)
        self.assertEqual(backend.transport_retries, 1)
        self.assertEqual(run.call_args_list[0].kwargs["input"], "same prompt")
        self.assertEqual(run.call_args_list[1].kwargs["input"], "same prompt")

    def test_command_backend_does_not_retry_uncertain_timeout(self):
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("model", 1)) as run:
            backend = llm_client.CommandBackend("model", 1)
            with self.assertRaisesRegex(RuntimeError, "model_timeout"):
                backend.complete("prompt")
        self.assertEqual(backend.transport_retries, 0)
        self.assertEqual(run.call_count, 1)

    def test_command_backend_does_not_retry_native_launch_failure(self):
        failure = subprocess.CompletedProcess("model", 2, "", "native Codex failed: bad resume flags")
        with mock.patch("subprocess.run", return_value=failure) as run:
            backend = llm_client.CommandBackend("model", 1)
            with self.assertRaisesRegex(RuntimeError, "model_backend_failure"):
                backend.complete("prompt")
        self.assertEqual(backend.transport_retries, 0)
        self.assertEqual(run.call_count, 1)

        malformed = subprocess.CompletedProcess("model", 0, "not json", "")
        with mock.patch("subprocess.run", return_value=malformed) as run:
            backend = llm_client.CommandBackend("model", 1)
            with self.assertRaises(ValueError):
                backend.complete("prompt")
        self.assertEqual(backend.transport_retries, 0)
        self.assertEqual(run.call_count, 1)

    def test_model_invalid_is_never_counted_as_gameplay_or_infrastructure(self):
        """The whole point of the third bucket: a model_invalid run is a
        completed evaluation that is neither a gameplay result nor harness
        breakage. Asserted as an invariant over all three classes."""
        end_turn = '[{"action":"EndTurn"}]'
        failure = {"type": "status", "ok": True,
                   "results": [{"ok": False, "code": "MoveError", "message": "x"}]}
        cases = [
            (TERMINAL_GAMEPLAY, [end_turn],
             [{"type": "game_end", "reason": "max_turns", "winner": None}]),
            (TERMINAL_MODEL_INVALID, [end_turn, end_turn],
             [{"type": "state", "active_faction": 0},
              {"type": "status", "ok": True, "what": "turn_options", "body": {}},
              {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
              failure, failure]),
            (TERMINAL_INFRASTRUCTURE, [end_turn],
             [{"type": "game_end", "reason": "timeout", "winner": None}]),
        ]
        for expected, orders, lines in cases:
            with self.subTest(terminal_class=expected):
                code, terminal = self.run_with_orders(orders, lines)
                self.assertEqual(terminal["terminal_class"], expected)
                self.assertEqual(code, TERMINAL_EXIT_CODES[expected])
                self.assertEqual(terminal["gameplay_valid"],
                                 expected == TERMINAL_GAMEPLAY)
                self.assertEqual(terminal["infrastructure_invalid"],
                                 expected == TERMINAL_INFRASTRUCTURE)

    def test_success_status_continues_to_game_end(self):
        status = {"type": "status", "ok": True, "results": [{"ok": True}]}
        code, terminal, _ = self.run_after_forwarded_orders(
            status, tail={"type": "game_end", "reason": "max_turns", "winner": None})
        self.assertEqual(code, 0)
        self.assertFalse(terminal["infrastructure_invalid"])
        self.assertEqual(terminal["reason"], "max_turns")

    def test_action_repair_budget_resets_each_turn(self):
        action_failure = {"type": "status", "ok": True,
                          "results": [{"ok": False, "code": "MoveError",
                                       "message": "invalid move"}]}
        lines = [
            {"type": "state", "active_faction": 0},
            {"type": "status", "ok": True, "what": "turn_options", "body": {}},
            {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
            action_failure,
            {"type": "state", "active_faction": 0},
            {"type": "status", "ok": True, "what": "turn_options", "body": {}},
            {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
            action_failure,
            {"type": "game_end", "reason": "max_turns", "winner": None},
        ]
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            orders_path = directory + "/orders.jsonl"
            with open(orders_path, "w") as orders:
                for _ in range(4):
                    orders.write('{"text":"[{\\"action\\":\\"EndTurn\\"}]"}\n')
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess(lines)
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        self.assertEqual(code, 0)
        self.assertEqual(len([record for record in records
                              if record["type"] == "action_repair"]), 2)

    def run_terminal(self, line):
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=True, orders_file=None,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess([line])
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync") as fsync:
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records[-1], fsync.call_count

    def run_with_orders(self, order_texts, driver_lines, validate_before_submit=False,
                        max_model_calls_per_turn=4, max_tool_calls_per_turn=4,
                        incremental_turns=False, backend_cache=None, reasoning_effort=None,
                        return_records=False, timeout_finish=False, resume_records=None):
        """Drive the client with N canned model replies and explicit driver output."""
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            orders_path = directory + "/orders.jsonl"
            with open(orders_path, "w") as orders:
                for text in order_texts:
                    orders.write(json.dumps({"text": text, "cache": backend_cache}) + "\n")
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
                validate_before_submit=validate_before_submit,
                incremental_turns=incremental_turns,
                max_model_calls_per_turn=max_model_calls_per_turn,
                max_tool_calls_per_turn=max_tool_calls_per_turn,
                reasoning_effort=reasoning_effort,
                timeout_finish=timeout_finish,
            )
            process = FakeDriverProcess(driver_lines)
            if resume_records is not None:
                Path(log_path).write_text("".join(json.dumps(r) + "\n" for r in resume_records))
                checkpoint_dir = checkpoint_dir_for_log(log_path)
                checkpoint_dir.mkdir()
                (checkpoint_dir / "resume.json").write_text(
                    '{"state_revision":6,"side_turns":0}')
                args.resume_log = log_path
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync"):
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records if return_records else records[-1]

    def test_resume_preserves_counters_and_unique_request_and_batch_ids(self):
        parent = [
            {"type": "metadata", "conversation_id": "same-game", "model_calls": 0},
            {"type": "model_request", "request_id": "same-game:request:4", "sequence": 4},
            {"type": "model_request", "request_id": "same-game:request:5",
             "sequence": 5, "status": "failed"},
            {"type": "forwarded_orders", "batch_id": "same-game:batch:1"},
            {"type": "model_error", "conversation_id": "same-game", "model_calls": 5,
             "model_orders": 1, "queries": 3, "draft_reviews": 1,
             "terminal_class": TERMINAL_INFRASTRUCTURE},
        ]
        lines = [
            {"type": "state", "active_faction": 0, "state_revision": 6, "units": []},
            {"type": "status", "ok": True, "results": [{"ok": True}]},
            {"type": "game_end", "reason": "max_turns"},
        ]
        with mock.patch.object(llm_client, "query_tactical_surface", return_value={}), \
                mock.patch.object(llm_client, "draft_needs_preview", return_value=False):
            code, records = self.run_with_orders(
                ['[{"action":"EndTurn"}]'], lines,
                resume_records=parent, return_records=True)
        self.assertEqual(code, 0)
        self.assertEqual(records[:len(parent)], parent)
        new = records[len(parent):]
        request = next(r for r in new if r["type"] == "model_request")
        batch = next(r for r in new if r["type"] == "forwarded_orders")
        self.assertEqual(request["request_id"], "same-game:request:6")
        self.assertEqual(batch["batch_id"], "same-game:batch:2")
        self.assertEqual(batch["request_id"], request["request_id"])
        self.assertEqual(new[-1]["model_calls"], 6)
        self.assertEqual(new[-1]["model_orders"], 2)
        self.assertEqual(new[-1]["draft_reviews"], 1)

    def test_resume_log_rejects_classified_typed_completed_outcomes(self):
        for terminal in (
                {"type": "model_error", "terminal_class": TERMINAL_MODEL_INVALID},
                {"type": "budget_interrupted"}):
            with self.subTest(terminal_type=terminal["type"]):
                parent = [
                    {"type": "metadata", "conversation_id": "typed-terminal"},
                    terminal,
                ]
                with self.assertRaisesRegex(ValueError, "completed terminal result"):
                    self.run_with_orders([], [], resume_records=parent)

    def run_after_forwarded_orders(self, action_status, tail=None):
        with tempfile.TemporaryDirectory() as directory:
            log_path = directory + "/client.jsonl"
            orders_path = directory + "/orders.jsonl"
            with open(orders_path, "w") as orders:
                orders.write('{"text":"[{\\"action\\":\\"EndTurn\\"}]"}\n')
            lines = [
                {"type": "state", "active_faction": 0},
                {"type": "status", "ok": True, "what": "turn_options", "body": {}},
                {"type": "status", "ok": True, "what": "recruit_options", "body": {}},
                action_status,
            ]
            if tail is not None:
                lines.append(tail)
            args = argparse.Namespace(
                driver="driver", scenario="scenario", faction0="a", faction1="b",
                gold=1, seed=2, max_turns=3, llm_side=0, turn_timeout=4,
                query_budget_seconds=5, max_queries_per_turn=6,
                no_recruit_macro=False, interactive_model=False, orders_file=orders_path,
                model_command=None, model_timeout=7, log=log_path,
                max_prompt_bytes=16 * 1024 * 1024, token_input_limit=None,
                token_output_limit=None, token_total_limit=None,
            )
            process = FakeDriverProcess(lines)
            with mock.patch("tools.llm_client.subprocess.Popen", return_value=process), \
                    mock.patch("tools.llm_client.source_metadata", return_value={}), \
                    mock.patch("tools.llm_client.os.fsync") as fsync:
                code = run(args)
            with open(log_path) as log:
                records = [json.loads(raw) for raw in log]
        return code, records[-1], fsync.call_count


if __name__ == "__main__":
    unittest.main()
