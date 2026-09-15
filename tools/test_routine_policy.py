"""Contract tests for routine policy validation, progress and client wiring.

Scripted exchanges and backends exercise the client contract without a paid
model. Real-driver execution is covered by the strategy integration suites.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from . import llm_client
from . import routine_policy as rp

ROOT = Path(__file__).resolve().parents[1]


def make_context(**overrides):
    defaults = dict(
        recruitable_defs=frozenset({"Skeleton", "Ghost"}),
        friendly_unit_ids=frozenset({1, 2, 3}),
        recruiter_ids=frozenset({1}),
        village_coords=frozenset({(2, 4), (5, 3)}),
        board_bounds=(20, 20),
    )
    defaults.update(overrides)
    return rp.ValidationContext(**defaults)


def valid_stack1_policy():
    return {
        "reserve_gold": 60,
        "recruits": [{"def_id": "Skeleton", "count": 6, "role": "army"}],
        "scouts": [],
        "villages": [],
        "rally": None,
        "holds": [],
    }


class FakeExchange:
    """Records every call; scripts a fixed sequence of routine_next/Submit replies."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if not self.script:
            raise AssertionError("FakeExchange script exhausted")
        return self.script.pop(0)


def call_kinds(exchange):
    """Name each exchange call by its actual wire shape.

    A routine submission is a bare envelope with an "orders" key and NO
    "action" key -- the driver distinguishes it from a single ordinary order
    exactly that way, so a test that looks for action=="Submit" would pass
    against a shape the driver rejects.
    """
    kinds = []
    for call in exchange.calls:
        if call.get("action") == "Query":
            kinds.append(f"Query:{call.get('what')}")
        elif "orders" in call and "action" not in call:
            assert call["origin"] == "routine", call
            actions = [order["action"] for order in call["orders"]]
            kinds.append("Envelope:" + ",".join(actions))
        else:
            kinds.append(f"Other:{call!r}")
    return kinds


class FakeBackend:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def __call__(self, brief):
        self.calls += 1
        return self.replies.pop(0)


class PolicyValidationTests(unittest.TestCase):
    def test_valid_policy_accepted(self):
        normalized = rp.validate_routine_policy(valid_stack1_policy(), make_context())
        self.assertEqual(normalized["reserve_gold"], 60)
        self.assertEqual(normalized["recruits"],
                         [{"def_id": "Skeleton", "count": 6, "role": "army"}])
        self.assertEqual(normalized["scouts"], [])
        self.assertIsNone(normalized["rally"])

    def test_invalid_shapes_rejected_with_no_mutation(self):
        never_called = FakeExchange([])
        cases = {
            "missing_recruits": {"reserve_gold": 0},
            "unknown_top_key": {**valid_stack1_policy(), "bogus": 1},
            "negative_reserve": {**valid_stack1_policy(), "reserve_gold": -1},
            "non_int_reserve": {**valid_stack1_policy(), "reserve_gold": "60"},
            "too_many_recruits": {**valid_stack1_policy(),
                                  "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}] * 9},
            "recruit_count_zero": {**valid_stack1_policy(),
                                   "recruits": [{"def_id": "Skeleton", "count": 0, "role": "army"}]},
            "recruit_count_too_high": {**valid_stack1_policy(),
                                       "recruits": [{"def_id": "Skeleton", "count": 33, "role": "army"}]},
            "recruit_bad_role": {**valid_stack1_policy(),
                                 "recruits": [{"def_id": "Skeleton", "count": 1, "role": "tank"}]},
            "recruit_unrecruitable_def": {**valid_stack1_policy(),
                                          "recruits": [{"def_id": "Dragon", "count": 1, "role": "army"}]},
            "recruit_extra_key": {**valid_stack1_policy(),
                                  "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army", "extra": 1}]},
            "scouts_not_list": {**valid_stack1_policy(), "scouts": "1"},
            "scouts_duplicate": {**valid_stack1_policy(), "scouts": [2, 2]},
            "scouts_unknown_unit": {**valid_stack1_policy(), "scouts": [999]},
            "scouts_is_recruiter": {**valid_stack1_policy(), "scouts": [1]},
            "villages_too_many": {**valid_stack1_policy(),
                                  "villages": [{"col": 2, "row": 4}, {"col": 5, "row": 3},
                                               {"col": 0, "row": 0}, {"col": 1, "row": 1}, {"col": 1, "row": 2}]},
            "villages_unknown_coord": {**valid_stack1_policy(), "villages": [{"col": 9, "row": 9}]},
            "villages_duplicate": {**valid_stack1_policy(),
                                   "villages": [{"col": 2, "row": 4}, {"col": 2, "row": 4}]},
            "rally_out_of_bounds": {**valid_stack1_policy(), "rally": {"col": 999, "row": 0}},
            "rally_bad_shape": {**valid_stack1_policy(), "rally": {"col": 1}},
            "holds_overlap_scouts": {**valid_stack1_policy(), "scouts": [2], "holds": [2]},
            "holds_duplicate": {**valid_stack1_policy(), "holds": [3, 3]},
            "holds_unknown_unit": {**valid_stack1_policy(), "holds": [999]},
            "not_an_object": ["nope"],
        }
        for name, policy in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(rp.PolicyValidationError):
                    rp.validate_policy(policy, make_context())
        # No case above should have touched an exchange/driver.
        self.assertEqual(never_called.calls, [])

    def test_stack2_enables_previously_scoped_fields(self):
        # Stack 1 rejected any of these as non-empty via enforce_stack1_scope
        # (removed in Stack 2 -- see test_routine_policy history). Stack 2
        # accepts them through validate_policy/validate_routine_policy
        # directly, with no separate scope gate to apply afterward.
        base = valid_stack1_policy()
        nonempty_scouts = {**base, "scouts": [2]}
        nonempty_villages = {**base, "scouts": [2], "villages": [{"col": 2, "row": 4}]}
        nonempty_holds = {**base, "holds": [3]}
        nonnull_rally = {**base, "rally": {"col": 1, "row": 1}}
        for name, policy in (("scouts", nonempty_scouts), ("villages", nonempty_villages),
                             ("holds", nonempty_holds), ("rally", nonnull_rally)):
            with self.subTest(field=name):
                normalized = rp.validate_routine_policy(policy, make_context())
                self.assertEqual(normalized.get(name), policy[name])
        self.assertFalse(hasattr(rp, "enforce_stack1_scope"))

    def test_village_policy_requires_scout_or_scout_recruit(self):
        context = make_context()
        base = valid_stack1_policy()
        with self.assertRaisesRegex(
                rp.PolicyValidationError,
                r"policy village workload exceeds scout capacity: "
                r"required_assignments=1 scout_capacity=0"
                r".*village ownership unknown: every listed village counted as pending"
                r".*a scout assigned to a listed village stays assigned after capture "
                r"until policy replacement; reduce pending villages, name eligible scouts "
                r"explicitly, or request more scout-role recruits"):
            rp.validate_policy({**base, "villages": [{"col": 2, "row": 4}], "scouts": []}, context)

        with_recruit = {
            **base,
            "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}],
            "villages": [{"col": 2, "row": 4}],
            "scouts": [],
        }
        self.assertIsNotNone(rp.validate_policy(with_recruit, context))

        with_scout = {
            **base,
            "villages": [{"col": 2, "row": 4}],
            "scouts": [2],
        }
        self.assertIsNotNone(rp.validate_policy(with_scout, context))

        with self.assertRaisesRegex(rp.PolicyValidationError, r"\[2\]"):
            rp.validate_policy(
                {**base, "villages": [{"col": 2, "row": 4}], "scouts": []},
                context, known_live_scout_ids=[2])
        err = None
        try:
            rp.validate_policy(
                {**base, "villages": [{"col": 2, "row": 4}], "scouts": []},
                context, known_live_scout_ids=None)
        except rp.PolicyValidationError as exc:
            err = str(exc)
        self.assertIsNotNone(err)
        self.assertNotIn("known live prior scout", err)

    def test_coordinate_feedback_names_field_and_canonical_shape(self):
        context = make_context()
        base = valid_stack1_policy()
        import re
        with self.assertRaisesRegex(rp.PolicyValidationError,
                                    r"policy.villages\[0\].*" + re.escape(rp.CANONICAL_COORD_JSON)):
            rp.validate_policy({**base, "villages": [[2, 4]]}, context)
        with self.assertRaisesRegex(rp.PolicyValidationError,
                                    r"policy.rally.*" + re.escape(rp.CANONICAL_COORD_JSON)):
            rp.validate_policy({**base, "rally": True}, context)
        ok = rp.validate_policy(
            {**base, "scouts": [2], "villages": [{"col": 2, "row": 4}],
             "rally": {"col": 8, "row": 6}}, context)
        self.assertEqual(ok["villages"], [{"col": 2, "row": 4}])
        self.assertEqual(ok["rally"], {"col": 8, "row": 6})

    def test_effective_scout_ids_filters_dead_and_unknown_roster(self):
        policy = {**valid_stack1_policy(), "scouts": []}
        progress = rp.RoutineProgress.fresh("pol-1", policy)
        progress.scout_ids = [5, 9]
        state = {
            "active_faction": 0,
            "units": [
                {"id": 1, "faction": 0, "can_recruit": True},
                {"id": 5, "faction": 0},
                {"id": 9, "faction": 1},
            ],
        }
        self.assertEqual(rp.effective_scout_ids(policy, progress, state), [5])
        self.assertIsNone(rp.effective_scout_ids(policy, progress, {"units": "missing"}))
        self.assertIsNone(rp.effective_scout_ids(policy, None, state))
        self.assertIn(rp.CANONICAL_COORD_JSON, rp._strategy_contract())
        self.assertIn("Syntax examples, not recommended objectives", rp._strategy_contract())

    def test_scouts_recruiters_excluded_and_bound_checked_before_execution(self):
        # An existing recruiter can never be named as a scout.
        with self.assertRaisesRegex(rp.PolicyValidationError, "cannot be a recruiter"):
            rp.validate_policy({**valid_stack1_policy(), "scouts": [1]}, make_context())
        # Existing scouts (2, 3) plus 7 new scout recruits = 9 > 8: rejected
        # before any execution, per plan section 4 ("reject a larger policy
        # before any execution").
        context = make_context(friendly_unit_ids=frozenset({1, 2, 3}))
        over_budget = {
            "reserve_gold": 0,
            "recruits": [{"def_id": "Ghost", "count": 7, "role": "scout"}],
            "scouts": [2, 3], "villages": [], "rally": None, "holds": [],
        }
        with self.assertRaisesRegex(rp.PolicyValidationError, "exceed 8"):
            rp.validate_policy(over_budget, context)
        # Exactly at the boundary (2 existing + 6 new == 8) is accepted.
        at_budget = {**over_budget,
                     "recruits": [{"def_id": "Ghost", "count": 6, "role": "scout"}]}
        normalized = rp.validate_policy(at_budget, context)
        self.assertEqual(normalized["scouts"], [2, 3])

    def test_held_ids_cannot_overlap_scouts(self):
        with self.assertRaisesRegex(rp.PolicyValidationError, "overlaps a scout"):
            rp.validate_policy(
                {**valid_stack1_policy(), "scouts": [2], "holds": [2]}, make_context())


class ModelResponseParsingTests(unittest.TestCase):
    def test_valid_kinds_parse(self):
        self.assertIsInstance(
            rp.parse_model_response({"kind": "set_policy", "policy": valid_stack1_policy()}),
            rp.SetPolicyResponse)
        self.assertIsInstance(
            rp.parse_model_response({"kind": "act", "actions": [{"action": "Move", "unit_id": 1}],
                                     "finish_turn": True}),
            rp.ActResponse)
        self.assertIsInstance(
            rp.parse_model_response({"kind": "choose", "decision_id": "dec-1",
                                     "option_ids": ["opt-1"], "finish_turn": False}),
            rp.ChooseResponse)
        self.assertIsInstance(rp.parse_model_response({"kind": "finish_turn"}), rp.FinishTurnResponse)
        self.assertIsInstance(rp.parse_model_response({"kind": "resign"}), rp.ResignResponse)

    def test_redundant_finish_turn_true_normalizes_without_second_path(self):
        parsed = rp.parse_model_response({"kind": "finish_turn", "finish_turn": True})
        self.assertIsInstance(parsed, rp.FinishTurnResponse)
        self.assertTrue(rp.is_redundant_finish_turn({"kind": "finish_turn", "finish_turn": True}))
        self.assertFalse(rp.is_redundant_finish_turn({"kind": "finish_turn"}))
        self.assertEqual(rp.CANONICAL_FINISH_TURN_JSON, '{"kind":"finish_turn"}')

    def test_finish_turn_rejects_false_null_types_payloads_and_unknown_keys(self):
        cases = (
            {"kind": "finish_turn", "finish_turn": False},
            {"kind": "finish_turn", "finish_turn": None},
            {"kind": "finish_turn", "finish_turn": 1},
            {"kind": "finish_turn", "finish_turn": "true"},
            {"kind": "finish_turn", "actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 3}]},
            {"kind": "finish_turn", "extra": True},
            {"kind": "finish_turn", "finish_turn": True, "extra": True},
        )
        for obj in cases:
            with self.subTest(obj=obj):
                with self.assertRaises(rp.ModelResponseError) as raised:
                    rp.parse_model_response(obj)
                self.assertIn(rp.CANONICAL_FINISH_TURN_JSON, str(raised.exception))
                self.assertFalse(rp.is_redundant_finish_turn(obj))

    def test_malformed_finish_repair_guidance_includes_canonical_object(self):
        obj = {"kind": "finish_turn", "finish_turn": False}
        with self.assertRaises(rp.ModelResponseError) as raised:
            rp.parse_model_response(obj)
        guidance = rp.strategy_repair_guidance(raised.exception, obj)
        self.assertIn(rp.CANONICAL_FINISH_TURN_JSON, guidance)
        self.assertIn("invalid", guidance)

    def test_strategy_contract_shows_canonical_finish_and_boolean_owner(self):
        contract = rp._strategy_contract()
        self.assertIn(rp.CANONICAL_FINISH_TURN_JSON, contract)
        self.assertIn("finish_turn boolean belongs to act and choose", contract)
        self.assertIn(
            '{"kind":"choose","decision_id":"dec-issued",'
            '"option_ids":["u6-relocate-2","u7-relocate-1"],"finish_turn":false}',
            contract,
        )
        self.assertEqual(rp.CHOOSE_KEYS, {"kind", "decision_id", "option_ids", "finish_turn"})
        self.assertEqual(rp.STRATEGY_RESPONSE_SHAPES["choose"], rp.CHOOSE_KEYS)

    def test_choose_response_parsing(self):
        valid = {
            "kind": "choose",
            "decision_id": "dec-123",
            "option_ids": ["u6-relocate-2", "u7-relocate-1"],
            "finish_turn": False,
        }
        res = rp.parse_model_response(valid)
        self.assertIsInstance(res, rp.ChooseResponse)
        self.assertEqual(res.decision_id, "dec-123")
        self.assertEqual(res.option_ids, ["u6-relocate-2", "u7-relocate-1"])
        self.assertFalse(res.finish_turn)

        res2 = rp.parse_model_response({**valid, "finish_turn": True})
        self.assertTrue(res2.finish_turn)

        single = rp.parse_model_response({**valid, "option_ids": ["u6-relocate-2"]})
        self.assertEqual(single.option_ids, ["u6-relocate-2"])

        for key in ("decision_id", "option_ids", "finish_turn"):
            bad = dict(valid)
            del bad[key]
            with self.subTest(missing=key):
                with self.assertRaises(rp.ModelResponseError):
                    rp.parse_model_response(bad)

        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "extra": 1})

        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "decision_id": ""})
        with self.assertRaisesRegex(rp.ModelResponseError, "option_id is not accepted"):
            rp.parse_model_response({
                "kind": "choose",
                "decision_id": "dec-123",
                "option_id": "u6-relocate-2",
                "finish_turn": False,
            })
        with self.assertRaisesRegex(rp.ModelResponseError, "option_id is not accepted"):
            rp.parse_model_response({**valid, "option_id": "u6-relocate-2"})
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "option_ids": []})
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "option_ids": ["a", "b", "c", "d"]})
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "option_ids": ["u6-relocate-2", "u6-relocate-2"]})
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "option_ids": [""]})
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "option_ids": "u6-relocate-2"})

        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "finish_turn": "true"})

        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({**valid, "origin": "routine"})

    def test_origin_rejected_everywhere_it_could_hide(self):
        cases = [
            {"kind": "set_policy", "policy": valid_stack1_policy(), "origin": "routine"},
            {"kind": "set_policy", "policy": {**valid_stack1_policy(), "origin": "routine"}},
            {"kind": "act", "actions": [{"action": "Move", "unit_id": 1, "origin": "routine"}],
             "finish_turn": False},
            {"kind": "act", "actions": [{"action": "Move", "unit_id": 1}],
             "finish_turn": False, "origin": "routine"},
        ]
        for index, obj in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaisesRegex(rp.ModelResponseError, "origin"):
                    rp.parse_model_response(obj)

    def test_decisions_key_rejected(self):
        obj = {"kind": "finish_turn", "decisions": []}
        with self.assertRaisesRegex(rp.ModelResponseError, "decisions"):
            rp.parse_model_response(obj)

    def test_act_rejects_embedded_boundary_action(self):
        obj = {"kind": "act", "actions": [{"action": "EndTurn"}], "finish_turn": True}
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response(obj)

    def test_act_actions_bounds(self):
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({"kind": "act", "actions": [], "finish_turn": True})
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({"kind": "act",
                                     "actions": [{"action": "Move", "unit_id": i} for i in range(17)],
                                     "finish_turn": True})

    def test_unknown_kind_rejected(self):
        with self.assertRaises(rp.ModelResponseError):
            rp.parse_model_response({"kind": "bogus"})


class OrdersEnvelopeTests(unittest.TestCase):
    def test_envelope_always_sets_routine_origin(self):
        orders = [{"action": "Recruit", "def_id": "Skeleton", "col": 1, "row": 1}]
        envelope = rp.build_orders_envelope(orders, source_state_revision=41)
        self.assertEqual(envelope["origin"], "routine")
        self.assertEqual(envelope["source_state_revision"], 41)
        self.assertEqual(envelope["orders"], orders)

    def test_envelope_ignores_any_attempted_override(self):
        # build_orders_envelope's signature has no way to set a different
        # origin at all -- this documents that it is not merely defaulted.
        envelope = rp.build_orders_envelope([], 1)
        self.assertEqual(envelope["origin"], "routine")


class RoutineQueryContractTests(unittest.TestCase):
    def test_build_routine_query_matches_frozen_shape(self):
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        query = rp.build_routine_query(41, installation.policy, progress)
        self.assertEqual(query["action"], "Query")
        self.assertEqual(query["what"], "routine_next")
        self.assertEqual(query["state_revision"], 41)
        self.assertEqual(query["policy"], installation.policy)
        self.assertEqual(query["progress"], {
            "recruited": [], "scout_assignments": [], "completed_villages": [],
            "scout_ids": [], "installation_id": installation.installation_id,
            "policy_complete": False,
        })

    def test_parse_routine_result_forms(self):
        action = rp.parse_routine_result({
            "result": "action", "action": {"action": "Recruit"},
            "progress_update": {"effects": [{"kind": "recruited", "queue_index": 0}]},
            "reason": "recruit"})
        self.assertIsInstance(action, rp.RoutineActionResult)
        self.assertEqual(rp.parse_routine_result(
            {"result": "finish", "reason": "no_remaining_routine_steps"}), "finish")
        exc = rp.parse_routine_result({"result": "exception", "reason": "contact", "evidence": {}})
        self.assertIsInstance(exc, rp.RoutineException)
        self.assertEqual(exc.reason, "contact")
        with self.assertRaises(ValueError):
            rp.parse_routine_result({"result": "finish", "reason": "wrong"})
        with self.assertRaises(ValueError):
            rp.parse_routine_result({"result": "bogus"})


class ProgressAdoptionTests(unittest.TestCase):
    def _installation(self):
        policy = {"reserve_gold": 0,
                  "recruits": [{"def_id": "Ghost", "count": 2, "role": "scout"},
                               {"def_id": "Ghost", "count": 2, "role": "army"}],
                  "scouts": [], "villages": [{"col": 2, "row": 4}],
                  "rally": {"col": 8, "row": 8}, "holds": []}
        return rp.install_policy(policy)

    def _commit(self, progress, installation, batch, effects, revision):
        return progress.commit_action({"effects": effects},
                                       installation_id=installation.installation_id,
                                       batch_id=batch, state_revision=revision)

    def test_duplicate_real_recruit_step_is_noop(self):
        installation = self._installation()
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        effect = {"kind": "recruited", "queue_index": 0, "unit_id": 47}
        self.assertTrue(self._commit(progress, installation, "b1", [effect], 7))
        self.assertFalse(self._commit(progress, installation, "b1", [effect], 7))
        self.assertEqual(progress.recruited, {0: 1})
        self.assertEqual(progress.scout_ids, [47])
        self.assertEqual(progress.last_proven_revision, 7)

    def test_duplicate_survives_serialization_and_later_commit(self):
        installation = self._installation()
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        effect = {"kind": "recruited", "queue_index": 0, "unit_id": 47}
        self._commit(progress, installation, "b1", [effect], 7)
        self._commit(progress, installation, "b2", [{"kind": "recruited", "queue_index": 1, "unit_id": 48}], 8)
        reloaded = rp.RoutineProgress.from_runtime_record(progress.to_runtime_record(), installation.policy)
        self.assertFalse(self._commit(reloaded, installation, "b1", [effect], 7))
        self.assertEqual(reloaded.recruited, {0: 1, 1: 1})
        self.assertEqual(reloaded.scout_ids, [47])
        self.assertEqual(reloaded.last_proven_revision, 8)

    def test_distinct_batches_with_identical_content_count_twice(self):
        installation = self._installation()
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        effect = {"kind": "recruited", "queue_index": 0, "unit_id": 47}
        self._commit(progress, installation, "b1", [effect], 1)
        self._commit(progress, installation, "b2", [effect | {"unit_id": 48}], 2)
        self.assertEqual(progress.recruited, {0: 2})
        self.assertEqual(progress.scout_ids, [47, 48])

    def test_conflict_foreign_and_proposal_rejected_without_mutation(self):
        installation = self._installation()
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        with self.assertRaises(ValueError):
            progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 0,
                                                   "unit_id": 47}]},
                                   installation_id="other", batch_id="b1", state_revision=3)
        with self.assertRaises(ValueError):
            progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 0}]},
                                   installation_id=installation.installation_id, batch_id="b1", state_revision=3)
        self.assertEqual(progress.recruited, {})
        self._commit(progress, installation, "b1", [{"kind": "recruited", "queue_index": 0, "unit_id": 47}], 3)
        before = progress.to_runtime_record()
        with self.assertRaises(ValueError):
            self._commit(progress, installation, "b1", [{"kind": "recruited", "queue_index": 0, "unit_id": 49}], 4)
        self.assertEqual(progress.to_runtime_record(), before)

    def test_assignments_use_standard_fields_and_finish_proof(self):
        installation = self._installation()
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        self._commit(progress, installation, "b1", [{"kind": "recruited", "queue_index": 0, "unit_id": 47}], 1)
        self._commit(progress, installation, "b2", [{"kind": "scout_assigned", "unit_id": 47, "col": 2, "row": 4}], 2)
        self._commit(progress, installation, "b3", [{"kind": "completed_village", "col": 2, "row": 4}], 3)
        self.assertEqual(progress.scout_assignments, [{"unit_id": 47, "col": 2, "row": 4}])
        self.assertFalse(progress.policy_complete)
        self.assertEqual(progress.to_query_progress()["recruited"], [{"queue_index": 0, "done": 1}])
        self.assertNotIn("applied_steps", progress.to_query_progress())

    def test_repeated_definition_entries_keep_independent_remaining_counts(self):
        installation = self._installation()
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        self._commit(progress, installation, "b1", [{"kind": "recruited", "queue_index": 0, "unit_id": 47}], 1)
        self.assertEqual(progress.remaining(installation.policy), [
            {"queue_index": 0, "def_id": "Ghost", "role": "scout", "remaining": 1},
            {"queue_index": 1, "def_id": "Ghost", "role": "army", "remaining": 2}])


class ContactHandlingTests(unittest.TestCase):
    def test_contact_reaches_model_exception_path(self):
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        script = [{"ok": True, "body": {"result": "exception", "reason": "contact",
                                        "evidence": {"unit_id": 7}}}]
        exchange = FakeExchange(script)
        backend = FakeBackend([{"kind": "finish_turn"}])
        outcome = rp.run_scripted_strategy_turn(
            exchange=exchange, request_model=backend, context=make_context(),
            installation=installation, progress=progress, state_revision=5)
        self.assertEqual(outcome.status, "finished")
        self.assertEqual(outcome.reason, "model_finish_turn")
        self.assertEqual(backend.calls, 1)

    def test_non_contact_exception_calls_model_and_replaces_policy(self):
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        script = [
            {"ok": True, "body": {"result": "exception", "reason": "recruitment_blocked",
                                  "evidence": {}}},
            {"ok": True, "body": {"result": "finish", "reason": "no_remaining_routine_steps"}},
        ]
        exchange = FakeExchange(script)
        backend = FakeBackend([{"kind": "finish_turn"}])
        outcome = rp.run_scripted_strategy_turn(
            exchange=exchange, request_model=backend, context=make_context(),
            installation=installation, progress=progress, state_revision=5)
        self.assertEqual(outcome.status, "finished")
        self.assertEqual(outcome.reason, "model_finish_turn")
        self.assertEqual(backend.calls, 1)

    def test_new_stack2_exception_codes_call_model_not_unsupported(self):
        # Plan section 5: "The Rust side will now raise unsafe_route,
        # invalid_assignment, and objectives_complete in addition to Stack
        # 1's set. Handle them in the client loop's exception path." None of
        # Each reaches the model through the ordinary exception path exactly
        # like recruitment_blocked already does above.
        for reason in ("unsafe_route", "route_unavailable", "invalid_assignment", "objectives_complete"):
            with self.subTest(reason=reason):
                self.assertIn(reason, rp.ROUTINE_EXCEPTION_CODES)
                installation = rp.install_policy(valid_stack1_policy())
                progress = rp.RoutineProgress.fresh(installation.installation_id)
                script = [
                    {"ok": True, "body": {"result": "exception", "reason": reason, "evidence": {}}},
                    {"ok": True, "body": {"result": "finish", "reason": "no_remaining_routine_steps"}},
                ]
                exchange = FakeExchange(script)
                backend = FakeBackend([{"kind": "finish_turn"}])
                outcome = rp.run_scripted_strategy_turn(
                    exchange=exchange, request_model=backend, context=make_context(),
                    installation=installation, progress=progress, state_revision=5)
                self.assertEqual(outcome.status, "finished")
                self.assertEqual(backend.calls, 1)

    def test_objectives_complete_does_not_block_current_turn_finish(self):
        # "objectives_complete is deferred by the engine until a no-sweep
        # finish has committed and must not prevent the current turn from
        # finishing." From the client's perspective this means: when it
        # does arrive, a model finish_turn response still finishes cleanly
        # -- no special-cased blocking logic sits between the exception and
        # the boundary.
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        script = [
            {"ok": True, "body": {"result": "exception", "reason": "objectives_complete",
                                  "evidence": {}}},
        ]
        exchange = FakeExchange(script)
        backend = FakeBackend([{"kind": "finish_turn"}])
        outcome = rp.run_scripted_strategy_turn(
            exchange=exchange, request_model=backend, context=make_context(),
            installation=installation, progress=progress, state_revision=5)
        self.assertEqual(outcome.status, "finished")
        self.assertEqual(outcome.reason, "model_finish_turn")
        self.assertEqual(backend.calls, 1)
        self.assertEqual(call_kinds(exchange), ["Query:routine_next"])


class ScoutAssignmentPersistenceTests(unittest.TestCase):
    """Actual-vs-predicted scout ids and assignment/objective round-trips."""

    def test_actual_scout_id_adopted_never_predicted(self):
        policy = {**valid_stack1_policy(),
                  "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}]}
        installation = rp.install_policy(policy)
        progress = rp.RoutineProgress.fresh(installation.installation_id, policy)
        progress.commit_action(
            {"effects": [{"kind": "recruited", "queue_index": 0, "unit_id": 47}]},
            installation_id=installation.installation_id, batch_id="b1", state_revision=10)
        self.assertEqual(progress.scout_ids, [47])
        self.assertEqual(progress.recruited[0], 1)
        self.assertEqual(progress.last_proven_revision, 10)

    def test_scout_assignments_and_completed_villages_round_trip(self):
        policy = {**valid_stack1_policy(), "villages": [{"col": 2, "row": 4}]}
        installation = rp.install_policy(policy)
        progress = rp.RoutineProgress.fresh(installation.installation_id, policy)
        progress.scout_ids.append(2)
        progress.commit_action({"effects": [{"kind": "scout_assigned", "unit_id": 2,
                                               "col": 2, "row": 4}]},
                               installation_id=installation.installation_id, batch_id="b1", state_revision=20)
        progress.commit_action({"effects": [{"kind": "completed_village", "col": 2, "row": 4}]},
                               installation_id=installation.installation_id, batch_id="b2", state_revision=21)
        serialized = progress.to_runtime_record()
        reloaded = rp.RoutineProgress.from_runtime_record(serialized, policy)
        self.assertEqual(reloaded.scout_ids, [2])
        self.assertEqual(reloaded.scout_assignments, progress.scout_assignments)
        self.assertEqual(reloaded.completed_villages, progress.completed_villages)
        self.assertEqual(reloaded.last_proven_revision, 21)
        # Round-tripping again (e.g. a second resume) is stable.
        twice = rp.RoutineProgress.from_query_progress(reloaded.to_query_progress())
        self.assertEqual(twice.scout_assignments, progress.scout_assignments)

    def test_reassigning_a_scout_supersedes_not_duplicates(self):
        # A scout's original village target became invalid and it was
        # reassigned; the stale assignment for the same scout id must not
        # linger alongside the new one.
        policy = {**valid_stack1_policy(), "villages": [{"col": 2, "row": 4}, {"col": 5, "row": 3}]}
        installation = rp.install_policy(policy)
        progress = rp.RoutineProgress.fresh(installation.installation_id, policy)
        progress.scout_ids.append(10)
        progress.commit_action({"effects": [{"kind": "scout_assigned", "unit_id": 10,
                                               "col": 2, "row": 4}]},
                               installation_id=installation.installation_id, batch_id="b1", state_revision=1)
        progress.commit_action({"effects": [{"kind": "scout_assigned", "unit_id": 10,
                                               "col": 5, "row": 3}]},
                               installation_id=installation.installation_id, batch_id="b2", state_revision=2)
        self.assertEqual(progress.scout_assignments,
                         [{"unit_id": 10, "col": 5, "row": 3}])

    def test_restart_preserves_assignments_remaining_counts_and_scout_ids(self):
        """Restart/branch preserves valid assignments and remaining queue
        counts, including newly recruited scout ids (plan section "Stack 2")."""
        installation = rp.install_policy({
            "reserve_gold": 10,
            "recruits": [{"def_id": "Ghost", "count": 3, "role": "scout"},
                        {"def_id": "Skeleton", "count": 4, "role": "army"}],
            "scouts": [], "villages": [{"col": 2, "row": 4}], "rally": None, "holds": [],
        })
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        # Two of three scouts recruited and assigned; one Skeleton recruited.
        progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 0, "unit_id": 20}]},
                               installation_id=installation.installation_id, batch_id="b1", state_revision=1)
        progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 0, "unit_id": 21}]},
                               installation_id=installation.installation_id, batch_id="b2", state_revision=2)
        progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 1, "unit_id": 22}]},
                               installation_id=installation.installation_id, batch_id="b3", state_revision=3)
        progress.commit_action({"effects": [{"kind": "scout_assigned", "unit_id": 20,
                                               "col": 2, "row": 4}]},
                               installation_id=installation.installation_id, batch_id="b4", state_revision=4)

        # Simulate a restart/branch: serialize and reload exactly as the
        # checkpoint-ref metadata / RoutineProgress persistence would.
        reloaded = rp.RoutineProgress.from_runtime_record(progress.to_runtime_record(), installation.policy)

        self.assertEqual(sorted(reloaded.scout_ids), [20, 21])
        self.assertEqual(reloaded.scout_assignments, progress.scout_assignments)
        remaining = {(entry["queue_index"], entry["role"]): entry["remaining"]
                    for entry in reloaded.remaining(installation.policy)}
        self.assertEqual(remaining, {(0, "scout"): 1, (1, "army"): 3})
        self.assertEqual(reloaded.last_proven_revision, 4)

class UnreconstructableProgressTests(unittest.TestCase):
    """Plan section 6: an advanced checkpoint with no matching progress record
    interrupts explicitly rather than resuming or resetting."""

    def test_no_pending_batch_is_reconstructable(self):
        self.assertIsNone(rp.find_unreconstructable_routine_batch([]))
        records = [
            {"type": "policy_installed", "installation_id": "pol-1"},
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b1",
             "orders": [{"action": "Recruit"}]},
            {"type": "routine_progress_committed", "installation_id": "pol-1"},
            {"type": "batch_committed", "batch_id": "b1"},
        ]
        self.assertIsNone(rp.find_unreconstructable_routine_batch(records))

    def test_finish_or_resign_batch_needs_no_progress_record(self):
        records = [
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b1",
             "orders": [{"action": "FinishWithGreedy", "groups": [], "holds": []}]},
            {"type": "batch_committed", "batch_id": "b1"},
        ]
        self.assertIsNone(rp.find_unreconstructable_routine_batch(records))

    def test_uncommitted_batch_is_safely_dropped_not_flagged(self):
        # The batch was submitted but the driver never checkpointed it (no
        # batch_committed): safe to treat as never having happened.
        records = [
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b1",
             "orders": [{"action": "Recruit"}]},
        ]
        self.assertIsNone(rp.find_unreconstructable_routine_batch(records))

    def test_committed_batch_with_no_progress_record_is_unreconstructable(self):
        # The exact crash window: checkpoint/batch_committed durable, but the
        # process died before routine_progress_committed was written.
        records = [
            {"type": "policy_installed", "installation_id": "pol-1"},
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b2",
             "orders": [{"action": "Recruit", "def_id": "Ghost"}]},
            {"type": "batch_committed", "batch_id": "b2"},
        ]
        self.assertEqual(rp.find_unreconstructable_routine_batch(records), "b2")

    def test_checkpoint_before_batch_commit_is_also_commitment_proof(self):
        records = [
            {"type": "policy_installed", "installation_id": "pol-1"},
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b3",
             "orders": [{"action": "Recruit", "def_id": "Ghost"}]},
            {"type": "checkpoint_ref", "batch_id": "b3", "path": "x.json",
             "digest": "0" * 64},
        ]
        self.assertEqual(rp.find_unreconstructable_routine_batch(records), "b3")

    def test_pending_checkpoint_preserves_proposal_and_finish_identity(self):
        records = [
            {"type": "policy_installed", "installation_id": "pol-1"},
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b4",
             "installation_id": "pol-1", "routine_finish": True,
             "progress_update": {"effects": [{"kind": "policy_completed"}]},
             "pre_step_unit_ids": [1, 2], "orders": [{"action": "FinishWithGreedy"}]},
            {"type": "checkpoint_ref", "batch_id": "b4", "path": "y.json",
             "digest": "1" * 64, "state_revision": 12},
        ]
        pending = rp.pending_routine_commit(records)
        self.assertIsNotNone(pending)
        self.assertEqual(pending["batch_id"], "b4")
        self.assertTrue(pending["routine_finish"])
        self.assertEqual(pending["progress_update"]["effects"][0]["kind"], "policy_completed")
        self.assertEqual(pending["pre_step_unit_ids"], [1, 2])

    def test_new_installation_clears_a_stale_pending_batch(self):
        # A policy replacement discards all previous progress -- a batch
        # pending under the superseded installation is moot once a fresh
        # set_policy lands, even if it was never confirmed.
        records = [
            {"type": "forwarded_orders", "source": "routine", "batch_id": "b1",
             "orders": [{"action": "Recruit"}]},
            {"type": "batch_committed", "batch_id": "b1"},
            {"type": "policy_installed", "installation_id": "pol-2"},
        ]
        self.assertIsNone(rp.find_unreconstructable_routine_batch(records))


class PolicyReplacementCancelsPriorStateTests(unittest.TestCase):
    def test_replacement_via_exception_discards_old_holds_and_assignments(self):
        installation = rp.install_policy({
            **valid_stack1_policy(),
            "holds": [3], "villages": [{"col": 2, "row": 4}],
        })
        progress = rp.RoutineProgress.fresh(installation.installation_id, installation.policy)
        progress.scout_ids.append(2)
        progress.commit_action({"effects": [{"kind": "scout_assigned", "unit_id": 2,
                                               "col": 2, "row": 4}]},
                               installation_id=installation.installation_id, batch_id="b1", state_revision=1)
        self.assertEqual(progress.scout_assignments, [
            {"unit_id": 2, "col": 2, "row": 4}])

        replacement_policy = {
            "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [],
            "rally": None, "holds": [],
        }
        script = [
            {"ok": True, "body": {"result": "exception", "reason": "invalid_assignment",
                                  "evidence": {}}},
            {"ok": True, "body": {"result": "finish", "reason": "no_remaining_routine_steps"}},
            {"ok": True, "body": {"state_revision": 6}},
        ]
        exchange = FakeExchange(script)
        backend = FakeBackend([{"kind": "set_policy", "policy": replacement_policy}])
        outcome = rp.run_scripted_strategy_turn(
            exchange=exchange, request_model=backend, context=make_context(),
            installation=installation, progress=progress, state_revision=5)
        self.assertEqual(outcome.status, "finished")
        # run_scripted_strategy_turn's local `installation`/`progress` are
        # rebound to the fresh pair on set_policy -- the caller's original
        # `progress` object (asserted above to hold the old hold/assignment)
        # is not mutated by the replacement, matching "a policy replacement
        # ... cancels old holds/orders". The caller must discard it and read
        # the fresh installation id from the next durable policy_installed
        # record instead, exactly as install_policy()'s docstring specifies.
        self.assertEqual(progress.scout_assignments, [
            {"unit_id": 2, "col": 2, "row": 4}])

    def test_replacement_never_replayed_merely_because_client_resumed(self):
        # "The client never replays a replacement merely because it
        # resumed." Resuming replays committed progress into a
        # RoutineProgress for the LATEST installed policy only (see
        # llm_client's resume handling: only records after the newest
        # policy_installed contribute). This directly exercises that
        # reconstruction rule at the RoutineProgress level.
        first = rp.install_policy(valid_stack1_policy())
        second = rp.install_policy(
            {**valid_stack1_policy(), "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}]})
        # Progress committed under the second (current) installation only.
        progress = rp.RoutineProgress.fresh(second.installation_id, second.policy)
        progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 0,
                                               "unit_id": 5}]},
                               installation_id=second.installation_id, batch_id="b1", state_revision=1)
        with self.assertRaises(ValueError):
            # A progress_update stamped for a superseded installation must
            # never be adopted into the current one.
            progress.commit_action({"effects": [{"kind": "recruited", "queue_index": 0,
                                                  "unit_id": 6}]},
                                   installation_id=first.installation_id, batch_id="b2", state_revision=2)
        self.assertEqual(progress.recruited, {0: 1})


class ClientCliWiringTests(unittest.TestCase):
    def test_strategy_mode_defaults_resolved(self):
        args = type("Args", (), {"decision_mode": "strategy"})()
        llm_client.resolve_client_config(args)
        self.assertTrue(args.incremental_turns)
        self.assertEqual(args.max_partial_batches_per_turn, 64)
        self.assertEqual(args.max_model_calls_per_turn, 8)
        self.assertEqual(args.max_queries_per_turn, 256)

    def test_strategy_mode_keeps_validated_overrides(self):
        args = type("Args", (), {"decision_mode": "strategy",
                                 "max_partial_batches_per_turn": 10,
                                 "max_queries_per_turn": 50})()
        llm_client.resolve_client_config(args)
        self.assertEqual(args.max_partial_batches_per_turn, 10)
        self.assertEqual(args.max_queries_per_turn, 50)

    def test_focused_operation_limit_with_strategy_raises_explicitly(self):
        args = type("Args", (), {"decision_mode": "strategy",
                                 "focused_max_operations_per_decision": 1})()
        with self.assertRaisesRegex(ValueError, "strategy"):
            llm_client.resolve_client_config(args)

    def test_strategy_policy_requires_strategy_mode(self):
        args = type("Args", (), {"decision_mode": "batch", "strategy_policy": "x.json"})()
        with self.assertRaisesRegex(ValueError, "--strategy-policy requires"):
            llm_client.resolve_client_config(args)

    def test_batch_and_focused_defaults_unaffected(self):
        args_batch = type("Args", (), {"decision_mode": "batch"})()
        llm_client.resolve_client_config(args_batch)
        self.assertEqual(args_batch.max_partial_batches_per_turn, 3)
        args_focused = type("Args", (), {"decision_mode": "focused"})()
        llm_client.resolve_client_config(args_focused)
        self.assertEqual(args_focused.max_partial_batches_per_turn, 64)
        self.assertEqual(args_focused.max_model_calls_per_turn, 128)


class StrategyPolicyFixedInstallTests(unittest.TestCase):
    def test_load_checked_in_policy_zero_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps({"kind": "set_policy", "policy": valid_stack1_policy()}))
            policy = rp.load_checked_in_policy(str(path), make_context())
            self.assertEqual(policy["recruits"][0]["def_id"], "Skeleton")

    def test_load_checked_in_policy_rejects_bad_kind(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps({"kind": "act", "policy": valid_stack1_policy()}))
            with self.assertRaises(rp.PolicyValidationError):
                rp.load_checked_in_policy(str(path), make_context())

    def test_static_recruitable_defs_includes_known_units(self):
        defs = rp.static_recruitable_defs(str(ROOT / "data" / "units"))
        self.assertIn("Skeleton", defs)

    # NOTE: --strategy-policy now actually plays the game against the real
    # driver (Stack 1's gap-closing requirement) instead of validating and
    # exiting before any subprocess starts. That behavior needs the built
    # `greedy_driver` binary, so its real-driver coverage -- zero model
    # responses/usage rows, actual recruitment, terminal on the first
    # unresolved exception -- lives in tools/test_strategy_integration.py
    # (guarded the same way as tools/test_movement_integration.py). What
    # remains testable without a driver process is the argparse/dispatch
    # validation, covered below.

    def test_cli_rejects_strategy_policy_with_model_backend_flags(self):
        result = subprocess.run(
            [sys.executable, "-m", "tools.llm_client",
             "--decision-mode", "strategy", "--strategy-policy", "nope.json",
             "--model-command", "echo hi"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strategy-policy", result.stderr)

    def test_cli_rejects_strategy_policy_without_strategy_mode(self):
        result = subprocess.run(
            [sys.executable, "-m", "tools.llm_client",
             "--decision-mode", "batch", "--strategy-policy", "nope.json"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strategy-policy", result.stderr)

    def test_cli_rejects_focused_limit_combined_with_strategy(self):
        result = subprocess.run(
            [sys.executable, "-m", "tools.llm_client",
             "--decision-mode", "strategy", "--orders-file", "nope.jsonl",
             "--focused-max-operations-per-decision", "1"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strategy", result.stderr)


class CapacityReliefBriefTests(unittest.TestCase):
    def test_no_route_endpoint_names_rally_and_policy_change(self):
        exception = rp.RoutineException(
            reason="recruitment_blocked",
            evidence={
                "cause": "no_placement_hex",
                "def_id": "Skeleton",
                "capacity_relief": {
                    "status": "no_route_endpoint",
                    "rally": {"col": 12, "row": 7},
                    "eligible_unit_ids": [10, 11],
                    "checked_unit_ids": [10, 11],
                    "coverage": "complete",
                },
            },
        )
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("rally 12,7", brief)
        self.assertIn("10,11", brief)
        self.assertIn("Changing the rally", brief)
        self.assertNotIn("unreachable", brief.lower())

    def test_unknown_relief_is_not_unsafe_or_unreachable(self):
        exception = rp.RoutineException(
            reason="recruitment_blocked",
            evidence={
                "cause": "no_placement_hex",
                "capacity_relief": {
                    "status": "unknown",
                    "rally": {"col": 8, "row": 6},
                    "eligible_unit_ids": [4],
                    "checked_unit_ids": [4],
                    "coverage": "complete",
                },
            },
        )
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("unknown", brief)
        self.assertNotIn("unsafe", brief.lower())
        self.assertNotIn("unreachable", brief.lower())

    def test_no_rally_names_absence(self):
        exception = rp.RoutineException(
            reason="recruitment_blocked",
            evidence={
                "cause": "no_placement_hex",
                "capacity_relief": {
                    "status": "no_rally",
                    "rally": None,
                    "eligible_unit_ids": [9],
                    "checked_unit_ids": [],
                    "coverage": "complete",
                },
            },
        )
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("No rally is installed", brief)
        self.assertIn("9", brief)


class VillageScoutCapacityBriefTests(unittest.TestCase):
    def test_policy_brief_states_the_scout_retention_rule(self):
        brief = rp.render_policy_brief(0, ["Skeleton"])
        self.assertIn(
            "Each scout assigned to a listed village stays assigned after capture "
            "until the policy is replaced, so provide at least as many scouts "
            "(explicit IDs plus scout-role recruit counts) as listed villages you "
            "do not already own.",
            brief)

    def test_exception_brief_reports_village_scout_capacity_fact(self):
        state = {
            "state_revision": 5, "turn": 1, "active_faction": 0,
            "cols": 20, "rows": 20,
            "terrain": [
                {"col": 2, "row": 4, "terrain_id": "village", "owner": 0},
                {"col": 5, "row": 3, "terrain_id": "village", "owner": 1},
            ],
            "units": [
                {"id": 1, "faction": 0, "can_recruit": True},
                {"id": 3, "faction": 0, "can_recruit": False},
            ],
        }
        policy = {**valid_stack1_policy(), "scouts": [3],
                  "villages": [{"col": 2, "row": 4}, {"col": 5, "row": 3}]}
        progress = rp.RoutineProgress.fresh("pol-1", policy)
        exception = rp.RoutineException(reason="contact", evidence={})
        brief = rp.render_exception_brief(exception, [], state=state, policy=policy, progress=progress)
        marker = "STRATEGY_CONTEXT_UNTRUSTED_DATA_BEGIN"
        facts_line = brief.split(marker, 1)[1]
        facts = json.loads([line for line in facts_line.splitlines() if line.startswith("{")][0])
        # (2,4) is owned by the controlled side; (5,3) is not and has no
        # assigned scout beyond unit 3, which is already the sole eligible
        # scout accounted for.
        self.assertEqual(facts["village_scout_capacity"],
                         {"required_assignments": 1, "scout_capacity": 1})

    def test_village_scout_capacity_fact_unknown_without_owner_field(self):
        state = {
            "state_revision": 5, "turn": 1, "active_faction": 0,
            "cols": 20, "rows": 20,
            "terrain": [{"col": 2, "row": 4, "terrain_id": "village"}],  # no "owner"
            "units": [{"id": 1, "faction": 0, "can_recruit": True}],
        }
        policy = {**valid_stack1_policy(), "villages": [{"col": 2, "row": 4}]}
        progress = rp.RoutineProgress.fresh("pol-1", policy)
        exception = rp.RoutineException(reason="contact", evidence={})
        brief = rp.render_exception_brief(exception, [], state=state, policy=policy, progress=progress)
        marker = "STRATEGY_CONTEXT_UNTRUSTED_DATA_BEGIN"
        facts_line = brief.split(marker, 1)[1]
        facts = json.loads([line for line in facts_line.splitlines() if line.startswith("{")][0])
        self.assertEqual(facts["village_scout_capacity"], "unknown")


class InvalidStructureStillRejectsAlongsideCapacityTests(unittest.TestCase):
    """Structural rejections (coords/IDs/holds) fire independent of capacity,
    including when the same policy would otherwise pass or fail the new
    state-aware village/scout capacity rule."""

    def test_bad_coordinate_shape_rejects_even_with_sufficient_capacity(self):
        context = make_context()
        base = valid_stack1_policy()
        with self.assertRaisesRegex(rp.PolicyValidationError, "must be an object"):
            rp.validate_policy(
                {**base, "villages": [[2, 4]], "scouts": [2]}, context)

    def test_unknown_unit_id_rejects_even_with_no_villages(self):
        context = make_context()
        base = valid_stack1_policy()
        with self.assertRaisesRegex(rp.PolicyValidationError, "not an existing friendly unit id"):
            rp.validate_policy({**base, "scouts": [999]}, context)
        with self.assertRaisesRegex(rp.PolicyValidationError, "not an existing friendly unit id"):
            rp.validate_policy({**base, "holds": [999]}, context)

    def test_hold_overlapping_scout_rejects_even_when_villages_all_owned(self):
        # All-owned villages with zero required assignments would otherwise
        # pass capacity; the hold/scout overlap check must still fire.
        context = make_context(owned_village_coords=frozenset({(2, 4)}))
        base = valid_stack1_policy()
        with self.assertRaisesRegex(rp.PolicyValidationError, "overlaps a scout"):
            rp.validate_policy(
                {**base, "villages": [{"col": 2, "row": 4}], "scouts": [2], "holds": [2]},
                context)


def _load_scout_capacity_fixture():
    path = ROOT / "tools" / "fixtures" / "proposed_movement" / "scout_capacity_cases.json"
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    expected_digest = "77c199c2c2bfe1d382e9c35056546aac221b919207aaeaee170183f9753fc998"
    if digest != expected_digest:
        raise AssertionError(
            f"scout_capacity_cases.json sha256 mismatch: got {digest}, "
            f"expected {expected_digest} (fixture must never be edited by a worker)")
    return json.loads(data)


class HeldScoutExcludedFromCapacityTests(unittest.TestCase):
    """policy.holds must exclude a scout from capacity, matching Rust's
    parse_policy filter on policy.holds (integration review follow-up)."""

    def _capacity(self, *, holds):
        policy = {
            "scouts": [],
            "villages": [{"col": 6, "row": 11}],
            "recruits": [{"def_id": "Vampire Bat", "count": 1, "role": "scout"}],
            "holds": holds,
        }
        progress = {
            "recruited": [{"queue_index": 0, "done": 1}],
            "scout_ids": [3],
            "scout_assignments": [],
            "completed_villages": [],
        }
        return rp.village_scout_capacity(
            policy, progress,
            owned_village_coords=frozenset(),
            live_friendly_ids=frozenset({1, 3}),
            recruiter_ids=frozenset({1}),
        )

    def test_held_scout_excluded_from_capacity(self):
        result = self._capacity(holds=[3])
        self.assertEqual(result["required_assignments"], 1)
        self.assertEqual(result["scout_capacity"], 0)

    def test_same_scout_counts_when_not_held(self):
        result = self._capacity(holds=[])
        self.assertEqual(result["required_assignments"], 1)
        self.assertEqual(result["scout_capacity"], 1)


class ScoutCapacityFixtureTests(unittest.TestCase):
    """Shared Python/Rust agreement cases (Stack 1 frozen contract)."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = _load_scout_capacity_fixture()

    def _context_for(self, case):
        units = case["units"]
        friendly_ids = frozenset(u["id"] for u in units)
        recruiter_ids = frozenset(u["id"] for u in units if u.get("recruiter"))
        village_coords = frozenset((v["col"], v["row"]) for v in case["villages"])
        owned = case["owned"]
        owned_village_coords = (
            None if owned is None else frozenset((v["col"], v["row"]) for v in owned))
        def_ids = frozenset(entry["def_id"] for entry in case["policy"]["recruits"])
        return rp.ValidationContext(
            recruitable_defs=def_ids,
            friendly_unit_ids=friendly_ids,
            recruiter_ids=recruiter_ids,
            village_coords=village_coords,
            board_bounds=None,
            owned_village_coords=owned_village_coords,
        )

    def _policy_dict(self, case):
        return {
            "reserve_gold": 0,
            "recruits": case["policy"]["recruits"],
            "scouts": case["policy"]["scouts"],
            "villages": case["villages"],
            "rally": None,
            "holds": case["policy"].get("holds", []),
        }

    def test_python_capacity_helper_cases(self):
        for case in self.fixture["cases"]:
            if "python_capacity_helper" not in case["applies"]:
                continue
            with self.subTest(case=case["name"]):
                units = case["units"]
                live_friendly_ids = frozenset(u["id"] for u in units)
                recruiter_ids = frozenset(u["id"] for u in units if u.get("recruiter"))
                owned = case["owned"]
                owned_village_coords = (
                    None if owned is None else frozenset((v["col"], v["row"]) for v in owned))
                policy = {"scouts": case["policy"]["scouts"],
                          "villages": case["villages"],
                          "recruits": case["policy"]["recruits"],
                          "holds": case["policy"].get("holds", [])}
                result = rp.village_scout_capacity(
                    policy, case["progress"],
                    owned_village_coords=owned_village_coords,
                    live_friendly_ids=live_friendly_ids,
                    recruiter_ids=recruiter_ids,
                )
                expected = case["expected"]
                self.assertEqual(result["required_assignments"], expected["required_assignments"])
                self.assertEqual(result["scout_capacity"], expected["scout_capacity"])
                self.assertEqual(result["ownership_known"], expected.get("ownership_known", True))

    def test_python_validation_cases(self):
        for case in self.fixture["cases"]:
            if "python_validation" not in case["applies"]:
                continue
            with self.subTest(case=case["name"]):
                context = self._context_for(case)
                policy = self._policy_dict(case)
                expected = case["expected"]
                if expected["ok"]:
                    normalized = rp.validate_routine_policy(policy, context)
                    self.assertIsNotNone(normalized)
                else:
                    with self.assertRaisesRegex(
                            rp.PolicyValidationError,
                            re.escape(expected["python_error_contains"])):
                        rp.validate_routine_policy(policy, context)


class ProposedDestinationContactBriefTests(unittest.TestCase):
    """Stack 2: the causal line for rejected contact/proposed_destination moves.

    Evidence shape and field names are frozen in
    tmp/proposed-movement-exec/STACK2-CONTRACT.md.
    """

    def _frozen_evidence(self):
        return {
            "stage": "proposed_destination", "unit_id": 8, "destination": {"col": 10, "row": 8},
            "proposed_action": {"action": "Move", "unit_id": 8, "col": 10, "row": 8},
            "objective": {"kind": "rally", "target": {"col": 10, "row": 7}},
            "projected_threats": {
                "projected_time_of_day": "Day",
                "units": [{
                    "unit_id": 9, "is_mover": False, "hp": 31, "col": 10, "row": 7,
                    "attacker_ids_any_view": [21, 23, 24, 25],
                    "occupied": {
                        "distinct_attacker_count": 4, "max_incoming_sum": 28,
                        "lethal_attackers_needed": None, "origins_conflict": False,
                        "focus_kill_bps": [0, 0, 0],
                        "focus_expected_damage_tenths": [60, 110, 150],
                    },
                    "open": {
                        "distinct_attacker_count": 4, "max_incoming_sum": 28,
                        "lethal_attackers_needed": None, "origins_conflict": False,
                    },
                    "views": "both",
                }],
                "recruiters": [],
            },
            "coverage": {"facts": "complete", "units_listed": 1, "units_omitted": 0},
        }

    def test_frozen_wire_example_non_mover_exposed(self):
        exception = rp.RoutineException(reason="contact", evidence=self._frozen_evidence())
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("Proposed routine move U8 -> (10,8) toward rally (10,7)", brief)
        self.assertIn("U9 (not the mover)", brief)
        self.assertIn("occupied attackers=4 max_sum=28HP", brief)
        self.assertIn("not proven jointly achievable", brief)
        self.assertIn("null (unreachable under supplied maximum volleys)", brief)
        self.assertIn("focus=(damage_from_1=6HP,damage_from_2=11HP,damage_from_3=15HP)", brief)
        self.assertIn("open attackers=4 max_sum=28HP", brief)
        self.assertIn("attackers(any view)=21,23,24,25", brief)

    def test_mover_exposed_has_no_non_mover_note(self):
        evidence = self._frozen_evidence()
        evidence["projected_threats"]["units"][0]["unit_id"] = 8
        evidence["projected_threats"]["units"][0]["is_mover"] = True
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("U8 occupied attackers=4", brief)
        self.assertNotIn("(not the mover)", brief)

    def test_recruiter_exposed_named_and_not_duplicated(self):
        evidence = self._frozen_evidence()
        evidence["projected_threats"]["units"] = []
        # Engine shape (routine.rs projected_recruiter_json): per-view facts nest
        # under occupied/open like units, attacker_max_damage sits inside each
        # view, and recruiters carry no attacker_ids_any_view.
        evidence["projected_threats"]["recruiters"] = [{
            "recruiter_id": 3, "hp": 40, "col": 5, "row": 5,
            "occupied": {
                "distinct_attacker_count": 2, "max_incoming_sum": 20,
                "lethal_attackers_needed": 2, "origins_conflict": False,
                "attacker_max_damage": [{"attacker_id": 11, "max_damage": 10},
                                         {"attacker_id": 12, "max_damage": 10}],
                "focus_kill_bps": [0, 2500, 0], "focus_expected_damage_tenths": [70, 140, 0],
            },
            "open": {
                "distinct_attacker_count": 1, "max_incoming_sum": 10,
                "lethal_attackers_needed": None, "origins_conflict": False,
                "attacker_max_damage": [{"attacker_id": 11, "max_damage": 10}],
            },
            "views": "both",
        }]
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("Recruiter U3 occupied attackers=2 max_sum=20HP", brief)
        self.assertIn("U11:10HP", brief)
        self.assertIn("open attackers=1 max_sum=10HP", brief)
        self.assertNotIn("attackers(any view)", brief)
        self.assertEqual(brief.count("Recruiter U3"), 1)

    def test_open_only_view_is_labelled(self):
        evidence = self._frozen_evidence()
        evidence["projected_threats"]["units"][0]["views"] = "open_only"
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("(open-only)", brief)
        self.assertNotIn("occupied attackers", brief)

    def test_occupied_only_view_is_labelled(self):
        evidence = self._frozen_evidence()
        evidence["projected_threats"]["units"][0]["views"] = "occupied_only"
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("(occupied-only)", brief)
        self.assertNotIn("open attackers", brief)

    def test_missing_forecast_slots_stay_unknown_not_zero(self):
        evidence = self._frozen_evidence()
        evidence["projected_threats"]["units"][0]["occupied"]["focus_expected_damage_tenths"] = None
        del evidence["projected_threats"]["units"][0]["occupied"]["lethal_attackers_needed"]
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("focus=(unknown)", brief)
        self.assertIn("lethal=unknown", brief)
        self.assertNotIn("focus=(damage_from_1=0HP", brief)

    def test_null_objective_target_reads_unknown_target(self):
        evidence = self._frozen_evidence()
        evidence["objective"]["target"] = None
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("toward rally unknown target", brief)

    def test_units_omitted_reported(self):
        evidence = self._frozen_evidence()
        evidence["coverage"]["units_omitted"] = 2
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertIn("2 unit(s) omitted", brief)

    def test_legacy_minimal_evidence_unchanged(self):
        evidence = {"stage": "proposed_destination", "unit_id": 8, "destination": {"col": 10, "row": 8}}
        exception = rp.RoutineException(reason="contact", evidence=evidence)
        brief = rp.render_exception_brief(exception, [])
        self.assertNotIn("Proposed routine move", brief)
        self.assertIn("Routine execution paused on a typed engine exception", brief)

    def test_non_contact_reason_unaffected(self):
        exception = rp.RoutineException(reason="promotion_pending", evidence={"stage": "proposed_destination"})
        brief = rp.render_exception_brief(exception, [])
        self.assertNotIn("Proposed routine move", brief)


# ---------------------------------------------------------------------------
# The real-driver Stack 1 gate (scripted policy recruits and finishes with
# zero further backend calls; two-turn recruitment without double-buying;
# no auto-vacate/held/recruiter movement/attack/sweep; crash-after-commit-
# before-ack resume parity; routine-labelled events, playable snapshots, and
# idempotent catalog import) lives in tools/test_strategy_integration.py,
# against the real built `greedy_driver` binary -- this file exercises the
# Python-only contract (validation, progress, response parsing) with a
# scripted FakeExchange/backend and needs no driver process.
# ---------------------------------------------------------------------------


class ProposedDestinationRealOutputRenderingTests(unittest.TestCase):
    """Render actual Rust routine_next evidence, not a hand-built packet."""

    FIXTURE = Path(__file__).parent / "fixtures" / "proposed_movement" / "rev125_proposed_destination_evidence.json"

    def test_trial8_revision125_real_evidence_renders_causal_line(self):
        data = json.loads(self.FIXTURE.read_text())
        line = rp._contact_destination_line(data["evidence"])
        self.assertIn("Proposed routine move U8 -> (10,8) toward rally (10,7)", line)
        self.assertIn("projected, not current board", line)
        self.assertIn("U8 occupied attackers=5", line)
        self.assertNotIn("U8 (not the mover)", line)
        self.assertIn("open attackers=5", line)
        self.assertIn("attackers(any view)=21,23,24,25,31", line)
        self.assertIn("not proven jointly achievable", line)
        self.assertNotIn("unknown", line)

    def test_real_evidence_carries_no_contact_closure_keys(self):
        evidence = json.loads(self.FIXTURE.read_text())["evidence"]
        self.assertNotIn("contact_state_key", evidence)
        self.assertNotIn("contact_actionability", evidence)

    def test_recruiter_exposure_uses_nested_engine_shape(self):
        evidence = {
            "stage": "proposed_destination", "unit_id": 5, "destination": {"col": 3, "row": 4},
            "proposed_action": {"action": "Move", "unit_id": 5, "col": 3, "row": 4},
            "objective": {"kind": "castle_capacity", "target": {"col": 8, "row": 6}},
            "projected_threats": {"projected_time_of_day": "Day", "units": [], "recruiters": [{
                "recruiter_id": 1, "hp": 48, "col": 2, "row": 7,
                "occupied": {"distinct_attacker_count": 2, "max_incoming_sum": 17,
                             "lethal_attackers_needed": None, "origins_conflict": False,
                             "attacker_max_damage": [{"attacker_id": 21, "max_damage": 9},
                                                     {"attacker_id": 23, "max_damage": 8}],
                             "focus_kill_bps": [0, 0, 0], "focus_expected_damage_tenths": [55, 90, 0]},
                "open": {"distinct_attacker_count": 0, "max_incoming_sum": 0,
                         "lethal_attackers_needed": None, "origins_conflict": False,
                         "attacker_max_damage": []},
                "views": "occupied_only"}]},
            "coverage": {"facts": "complete", "units_listed": 0, "units_omitted": 0}}
        line = rp._contact_destination_line(evidence)
        self.assertIn("Recruiter U1 occupied attackers=2 max_sum=17HP", line)
        self.assertIn("max_single_attacker_damage=(U21:9HP,U23:8HP)", line)
        self.assertIn("(occupied-only)", line)
        self.assertNotIn("attackers(any view)", line)


if __name__ == "__main__":
    unittest.main()
