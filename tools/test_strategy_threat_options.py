"""Tests for threatened recruiter choices during invalid-assignment decisions (Stack 2).

Verifies engine enrichment of invalid_assignment policy exceptions when a live
friendly recruiter is threatened, option generation and caps, contextual
response validation, decision brief rendering, and real-driver commitment.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .routine_policy import ChooseResponse, SetPolicyResponse, parse_model_response
from .strategy_decision import (
    ALLOWED_ALL,
    ALLOWED_POLICY_WITH_CHOOSE,
    ContextualResponseError,
    DecisionPacket,
    build_decision_packet,
    render_decision_brief,
    validate_response_context,
)

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get(
    "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/release/greedy_driver"
))
if not DRIVER.is_file():
    DRIVER = ROOT / "norrust_core/target/debug/greedy_driver"

HISTORICAL_CKPT = ROOT / "tmp/glm-luna-fullgame-20260917T042432Z/recording/glm-luna-fullgame/match.ckpt/28-479-model-0cccd5a53a02b5d1c151cf3b9b57bec2aeaf70af8b22252563be73d31a5c5796.json"


class TestStrategyThreatDecisionPacket(unittest.TestCase):
    """Unit tests for decision packet routing, validation, and rendering."""

    def test_invalid_assignment_threatened_recruiter_allows_choose(self):
        evidence = {
            "cause": "dead_or_foreign_unit",
            "unit_id": 40,
            "threatened_recruiter": {
                "recruiter_id": 1,
                "hp": 27,
                "max_hp": 48,
                "distinct_attacker_count": 8,
                "open_distinct_attacker_count": 0,
                "max_incoming_damage": 34,
                "expected_incoming_damage_tenths": 210,
            },
            "actor_ids": [1],
            "eligible_actor_count": 1,
            "actors_truncated": False,
            "options": [
                {
                    "option_id": "u1-relocate-1",
                    "category": "relocation",
                    "actor_id": 1,
                    "target_id": None,
                    "actions": [{"action": "Move", "unit_id": 1, "col": 0, "row": 11}],
                    "movement_cost": 5,
                    "destination": {"col": 0, "row": 11},
                    "forecast": None,
                    "exposure": {
                        "distinct_attacker_count": 3,
                        "max_incoming_damage": 20,
                        "expected_incoming_damage_tenths": 120,
                    },
                    "coverage": "complete",
                }
            ],
            "options_truncated": False,
        }
        packet = build_decision_packet("invalid_assignment", evidence, 479, game_id="test", side_turn=28)
        self.assertEqual(packet.decision_kind, "policy")
        self.assertEqual(packet.reason, "invalid_assignment")
        self.assertIn("choose", packet.allowed_kinds)
        self.assertEqual(packet.allowed_kinds, ALLOWED_POLICY_WITH_CHOOSE)
        self.assertEqual(packet.coverage["options"], "complete")
        self.assertEqual(len(packet.options), 1)

        # Contextual validation accepts choose with valid option_id
        valid_choose = ChooseResponse(decision_id=packet.decision_id, option_ids=["u1-relocate-1"], finish_turn=False)
        validate_response_context(valid_choose, packet)

        # Rejects unknown option_id
        invalid_choose = ChooseResponse(decision_id=packet.decision_id, option_ids=["unknown-opt"], finish_turn=False)
        with self.assertRaises(ContextualResponseError):
            validate_response_context(invalid_choose, packet)

        # Policy responses remain valid
        validate_response_context(SetPolicyResponse(policy={"villages": [], "holds": []}), packet)

        # Brief rendering
        brief = render_decision_brief(packet)
        self.assertIn("THREATENED RECRUITER", brief)
        self.assertIn("Recruiter 1", brief)
        self.assertIn("HP 27/48", brief)
        self.assertIn("8 distinct attackers", brief)
        self.assertIn("Editing assignments moves no unit", brief)
        self.assertIn("does not repair the installed policy", brief)
        self.assertIn("u1-relocate-1", brief)
        self.assertIn("To choose, respond with:", brief)
        self.assertIn("choose", brief)

    def test_invalid_assignment_exhausted_recruiter_no_choose(self):
        evidence = {
            "cause": "dead_or_foreign_unit",
            "unit_id": 40,
            "threatened_recruiter": {
                "recruiter_id": 1,
                "hp": 10,
                "max_hp": 48,
                "distinct_attacker_count": 4,
                "open_distinct_attacker_count": 0,
                "max_incoming_damage": 25,
                "expected_incoming_damage_tenths": 150,
            },
            "actor_ids": [],
            "eligible_actor_count": 0,
            "actors_truncated": False,
            "options": [],
            "options_truncated": False,
            "options_empty_reason": "exhausted_recruiter_no_tactical_options",
        }
        packet = build_decision_packet("invalid_assignment", evidence, 479, game_id="test", side_turn=28)
        self.assertEqual(packet.decision_kind, "policy")
        self.assertNotIn("choose", packet.allowed_kinds)
        self.assertEqual(packet.allowed_kinds, ALLOWED_ALL)
        self.assertEqual(packet.coverage["options"], "not_generated")

        # Choose is rejected
        choose = ChooseResponse(decision_id=packet.decision_id, option_ids=[], finish_turn=False)
        with self.assertRaises(ContextualResponseError):
            validate_response_context(choose, packet)

        brief = render_decision_brief(packet)
        self.assertIn("has no executable movement or attack actions", brief)
        self.assertIn("No tactical menu was generated", brief)
        self.assertNotIn("To choose, respond with:", brief)

    def test_invalid_assignment_safe_recruiter_no_threat_menu(self):
        evidence = {"cause": "dead_or_foreign_unit", "unit_id": 40}
        packet = build_decision_packet("invalid_assignment", evidence, 479, game_id="test", side_turn=28)
        self.assertNotIn("choose", packet.allowed_kinds)
        self.assertEqual(packet.options, [])
        brief = render_decision_brief(packet)
        self.assertIn("Policy assignment failed (dead_or_foreign_unit for unit 40)", brief)
        self.assertNotIn("THREATENED RECRUITER", brief)


@unittest.skipUnless(DRIVER.is_file(), "Requires compiled greedy_driver")
class TestStrategyThreatOptionsDriver(unittest.TestCase):
    """Integration tests running against the real Rust driver."""

    @unittest.skipUnless(HISTORICAL_CKPT.is_file(), "Requires historical checkpoint 479")
    def test_revision_479_historical_enrichment_and_choose_commit(self):
        """Historical checkpoint 479 must produce an enriched invalid_assignment packet,

        and choosing a tactical option must commit the move while leaving policy unchanged.
        """
        from .llm_client import resolve_choose_batch

        with tempfile.TemporaryDirectory() as td:
            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(HISTORICAL_CKPT)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True
            )
            try:
                # Read initial messages until turn/state
                rev = None
                for _ in range(50):
                    line = proc.stdout.readline()
                    if not line:
                        break
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        rev = obj.get("state_revision", 0)
                        break

                self.assertIsNotNone(rev, "Driver should output state with revision")

                policy = {
                    "holds": [6, 38, 39, 40],
                    "rally": {"col": 1, "row": 7},
                    "recruits": [],
                    "reserve_gold": 58,
                    "scouts": [],
                    "villages": [],
                }
                # Query routine_next
                proc.stdin.write(json.dumps({
                    "action": "Query", "what": "routine_next", "state_revision": rev,
                    "policy": policy, "progress": {},
                }) + "\n")
                proc.stdin.flush()

                resp_line = proc.stdout.readline()
                resp = json.loads(resp_line)
                body = resp.get("body", {})

                self.assertEqual(body.get("result"), "exception")
                self.assertEqual(body.get("reason"), "invalid_assignment")
                ev = body.get("evidence", {})
                self.assertEqual(ev.get("cause"), "dead_or_foreign_unit")
                self.assertEqual(ev.get("unit_id"), 40)

                # Threat facts for recruiter 1
                tr = ev.get("threatened_recruiter")
                self.assertIsNotNone(tr, "threatened_recruiter must be present")
                self.assertEqual(tr.get("recruiter_id"), 1)
                self.assertEqual(tr.get("hp"), 27)
                self.assertEqual(tr.get("distinct_attacker_count"), 8)

                # Options attached
                options = ev.get("options", [])
                self.assertGreater(len(options), 0, "must attach tactical options for threatened recruiter")
                self.assertLessEqual(len(options), 4, "options must be capped at 4")
                self.assertEqual(ev.get("actor_ids"), [1])

                # Packet building from this evidence permits choose
                packet = build_decision_packet("invalid_assignment", ev, rev, game_id="hist", side_turn=28)
                self.assertIn("choose", packet.allowed_kinds)

                # Selecting choose executes move orders and leaves policy unchanged
                chosen_opt = packet.options[0]
                choose_resp = ChooseResponse(
                    decision_id=packet.decision_id,
                    option_ids=[chosen_opt["option_id"]],
                    finish_turn=False,
                )
                validate_response_context(choose_resp, packet)
                orders, _ = resolve_choose_batch(choose_resp, packet, no_recruit_macro=False)
                self.assertEqual(orders, chosen_opt["actions"])

                # Submit orders to driver
                proc.stdin.write(json.dumps(orders) + "\n")
                proc.stdin.flush()

                # Read until new state
                new_rev = None
                for _ in range(50):
                    line = proc.stdout.readline()
                    if not line:
                        break
                    msg = json.loads(line)
                    if msg.get("type") == "state":
                        new_rev = msg.get("state_revision")
                        break

                self.assertIsNotNone(new_rev, "Driver should output state after action execution")
                self.assertGreater(new_rev, rev)

                # Query routine_next again on new revision with the same policy
                proc.stdin.write(json.dumps({
                    "action": "Query", "what": "routine_next", "state_revision": new_rev,
                    "policy": policy, "progress": {},
                }) + "\n")
                proc.stdin.flush()

                next_resp = json.loads(proc.stdout.readline())
                next_body = next_resp.get("body", {})
                self.assertEqual(next_body.get("result"), "exception")
                self.assertEqual(next_body.get("reason"), "invalid_assignment")
                self.assertEqual(next_body.get("evidence", {}).get("cause"), "dead_or_foreign_unit")
                self.assertEqual(next_body.get("evidence", {}).get("unit_id"), 40)
            finally:
                if proc.stdin:
                    proc.stdin.close()
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
                proc.terminate()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
