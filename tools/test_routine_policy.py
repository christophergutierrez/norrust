"""Contract tests for tools/routine_policy.py and its Stack 1 wiring into
tools/llm_client.py.

Per the plan (docs/plans/strategy-and-routine-execution.md, "Stack 1"), the
Rust `routine_next` driver query does not exist yet in this worktree. Every
test here drives the client contract with a scripted/faked exchange and
backend rather than a live model or the real Rust routine executor. Tests
that will only pass once the Rust half lands are marked explicitly below.
"""
from __future__ import annotations

import json
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
        normalized = rp.validate_stack1_policy(valid_stack1_policy(), make_context())
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

    def test_stack1_scope_rejects_nonempty_future_fields_explicitly(self):
        base = valid_stack1_policy()
        nonempty_scouts = {**base, "scouts": [2]}
        nonempty_villages = {**base, "villages": [{"col": 2, "row": 4}]}
        nonempty_holds = {**base, "holds": [3]}
        nonnull_rally = {**base, "rally": {"col": 1, "row": 1}}
        for name, policy in (("scouts", nonempty_scouts), ("villages", nonempty_villages),
                             ("holds", nonempty_holds), ("rally", nonnull_rally)):
            with self.subTest(field=name):
                # Each individually passes generic validation...
                normalized = rp.validate_policy(policy, make_context())
                # ...but Stack 1 explicitly rejects it, never silently drops it.
                with self.assertRaisesRegex(rp.PolicyValidationError, "not supported in Stack 1"):
                    rp.enforce_stack1_scope(normalized)
                with self.assertRaises(rp.PolicyValidationError):
                    rp.validate_stack1_policy(policy, make_context())


class ModelResponseParsingTests(unittest.TestCase):
    def test_valid_kinds_parse(self):
        self.assertIsInstance(
            rp.parse_model_response({"kind": "set_policy", "policy": valid_stack1_policy()}),
            rp.SetPolicyResponse)
        self.assertIsInstance(
            rp.parse_model_response({"kind": "act", "actions": [{"action": "Move", "unit_id": 1}],
                                     "finish_turn": True}),
            rp.ActResponse)
        self.assertIsInstance(rp.parse_model_response({"kind": "finish_turn"}), rp.FinishTurnResponse)
        self.assertIsInstance(rp.parse_model_response({"kind": "resign"}), rp.ResignResponse)

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
        })

    def test_parse_routine_result_forms(self):
        action = rp.parse_routine_result({
            "result": "action", "action": {"action": "Recruit"},
            "progress_update": {"recruited": [{"def_id": "Skeleton", "done": 1}]},
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
    def test_progress_adopted_only_after_committed_submit(self):
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        # The routine_next query proposes a recruit; the exchange's Submit
        # call is what proves commitment.
        script = [
            {"ok": True, "body": {
                "result": "action",
                "action": {"action": "Recruit", "def_id": "Skeleton", "col": 1, "row": 1},
                "progress_update": {"installation_id": installation.installation_id,
                                    "recruited": [{"def_id": "Skeleton", "done": 1}]},
                "reason": "recruit"}},
            {"ok": True, "body": {"state_revision": 42}},
            {"ok": True, "body": {"result": "finish", "reason": "no_remaining_routine_steps"}},
            {"ok": True, "body": {"state_revision": 43}},
        ]
        exchange = FakeExchange(script)
        outcome = rp.run_scripted_strategy_turn(
            exchange=exchange, request_model=lambda brief: (_ for _ in ()).throw(
                AssertionError("model should not be called on a quiet committed path")),
            context=make_context(), installation=installation, progress=progress,
            state_revision=41)
        self.assertEqual(outcome.status, "finished")
        self.assertEqual(outcome.committed_actions, 1)
        self.assertEqual(progress.recruited.get("Skeleton"), 1)
        # One recruit envelope, then the automatic no-sweep boundary. No model
        # call happens between the last routine step and the finish.
        self.assertEqual(call_kinds(exchange),
                         ["Query:routine_next", "Envelope:Recruit",
                          "Query:routine_next", "Envelope:FinishWithGreedy"])
        finish = exchange.calls[-1]["orders"][0]
        self.assertEqual(finish, {"action": "FinishWithGreedy", "groups": [], "holds": []})

    def test_progress_not_adopted_when_submit_is_rejected(self):
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        script = [
            {"ok": True, "body": {
                "result": "action",
                "action": {"action": "Recruit", "def_id": "Skeleton", "col": 1, "row": 1},
                "progress_update": {"installation_id": installation.installation_id,
                                    "recruited": [{"def_id": "Skeleton", "done": 1}]},
                "reason": "recruit"}},
            {"ok": False, "message": "stale revision"},
        ]
        exchange = FakeExchange(script)
        with self.assertRaises(RuntimeError):
            rp.run_scripted_strategy_turn(
                exchange=exchange, request_model=lambda brief: None,
                context=make_context(), installation=installation, progress=progress,
                state_revision=41)
        self.assertEqual(progress.recruited, {})

    def test_finite_queue_not_rebought_after_resume(self):
        installation = rp.install_policy(
            {**valid_stack1_policy(), "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}]})
        # Simulate a resumed session: progress already shows the full count
        # committed, serialized and reloaded exactly as persistence would.
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        progress.commit_action({"recruited": [{"def_id": "Skeleton", "done": 2}]})
        serialized = progress.to_query_progress()
        reloaded = rp.RoutineProgress.from_query_progress(serialized)
        self.assertEqual(reloaded.remaining(installation.policy), [])

        # A duplicated committed update must not double-count (monotonic).
        reloaded.commit_action({"recruited": [{"def_id": "Skeleton", "done": 2}]})
        self.assertEqual(reloaded.recruited["Skeleton"], 2)

        script = [{"ok": True, "body": {"result": "finish", "reason": "no_remaining_routine_steps"}},
                  {"ok": True, "body": {"state_revision": 101}}]
        exchange = FakeExchange(script)
        outcome = rp.run_scripted_strategy_turn(
            exchange=exchange, request_model=lambda brief: (_ for _ in ()).throw(
                AssertionError("no exception should occur; queue is already complete")),
            context=make_context(), installation=installation, progress=reloaded,
            state_revision=100)
        self.assertEqual(outcome.status, "finished")
        self.assertEqual(outcome.committed_actions, 0)
        self.assertEqual(reloaded.recruited["Skeleton"], 2)
        # The resumed turn buys nothing: it queries once and finishes. No
        # Recruit envelope is ever submitted.
        self.assertEqual(call_kinds(exchange),
                         ["Query:routine_next", "Envelope:FinishWithGreedy"])


class ContactHandlingTests(unittest.TestCase):
    def test_contact_ends_run_explicitly_with_no_model_call(self):
        installation = rp.install_policy(valid_stack1_policy())
        progress = rp.RoutineProgress.fresh(installation.installation_id)
        script = [{"ok": True, "body": {"result": "exception", "reason": "contact",
                                        "evidence": {"unit_id": 7}}}]
        exchange = FakeExchange(script)
        backend = FakeBackend([])
        with self.assertRaises(rp.RoutineUnsupportedException) as ctx:
            rp.run_scripted_strategy_turn(
                exchange=exchange, request_model=backend, context=make_context(),
                installation=installation, progress=progress, state_revision=5)
        self.assertEqual(ctx.exception.reason, "contact")
        self.assertEqual(backend.calls, 0)

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


if __name__ == "__main__":
    unittest.main()
