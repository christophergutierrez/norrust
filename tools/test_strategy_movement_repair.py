"""Real-driver acceptance tests for movement_repair_menu (Stack 2).

Tests the movement repair options generation and validation against the real engine,
using a scripted backend. Asserts on actual driver responses, not mocks.

Tests cover:
1. REPRODUCTION: menu offers exactly two endpoints in the correct order
2. EVERY ADVERTISED ENDPOINT IS EXECUTABLE: validate each option through the engine
3. READ-ONLY: state_revision and unit positions/HP unchanged before/after
4. QUERY BOUND: at most 4 queries issued (1 inspect + 3 validate)
5. ALREADY MOVED: returns no options when unit has moved
6. FOREIGN/DEAD ACTOR: returns None for units not on llm_side
7. BUDGET EXHAUSTION MID-MENU: gracefully degrades when budget exhausted
8. NON-MOVE REJECTION: Attack rejections return None
9. RENDERING: text output names options, shows exposure, never says "safe"
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from .llm_client import (
    EngineBatchRejected,
    movement_repair_menu,
    STRATEGY_MAX_REPAIR_VALIDATIONS,
    query_validate_batch,
    QueryBudgetExhausted,
)
from .strategy_decision import (
    movement_repair_options,
    render_movement_repair_options,
)
from .test_strategy_routine_stack3 import DRIVER, ROOT

FIXTURES = ROOT / "tools/fixtures/choice_recovery"


class SimpleExchange:
    """Exchange wrapper for testing that tracks query counts."""

    def __init__(self, driver_proc):
        self.driver_proc = driver_proc
        self.query_count = 0
        self.validate_batch_count = 0
        self.inspect_unit_count = 0
        self.budget_limit_on_validate_batch = None  # int: answer that validate_batch with query_limit

    def __call__(self, request):
        """Send a request to the driver and get the response."""
        self.query_count += 1

        # Track specific query types
        if request.get("what") == "validate_batch":
            self.validate_batch_count += 1
            if (self.budget_limit_on_validate_batch is not None and
                self.validate_batch_count == self.budget_limit_on_validate_batch):
                # Engine's real response when budget is spent
                return {"type": "status", "ok": False, "code": "query_limit",
                        "message": "query limit exceeded"}
        elif request.get("what") == "inspect_unit":
            self.inspect_unit_count += 1

        # Send to driver and get response
        self.driver_proc.stdin.write(json.dumps(request) + "\n")
        self.driver_proc.stdin.flush()
        response_line = self.driver_proc.stdout.readline()
        if not response_line:
            raise RuntimeError("driver closed unexpectedly")
        return json.loads(response_line)


@unittest.skipUnless(DRIVER.is_file(), "Build the actual integration driver; skipped is not acceptance")
class MovementRepairMenuTests(unittest.TestCase):

    def test_reproduction_menu_offers_exactly_two_endpoints_in_order(self):
        """REAL DRIVER VERDICT: U42 at (4,9) with 6/31 HP fails to reach (4,7) with
        DestinationUnreachable at failed_index 0.

        The repair menu offers exactly two legal endpoints:
        1. (5,10) cost 2 distance 3, 9 attackers, max damage 84
        2. (5,8) cost 1 distance 1, 13 attackers, max damage 110

        The order is FROZEN by exposure precedence: fewer attackers (9 < 13) wins,
        neither the original (4,7) nor the repair guess (3,9) appears.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                # Get initial state
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state, "Could not get initial state from driver")
                state_revision = initial_state.get("state_revision")
                self.assertIsInstance(state_revision, int)

                units = {u["id"]: u for u in initial_state.get("units", [])}
                u42 = units.get(42)
                self.assertIsNotNone(u42, "U42 must be in the state")
                self.assertEqual((u42.get("col"), u42.get("row")), (4, 9),
                               f"U42 should be at (4,9), got ({u42.get('col')},{u42.get('row')})")
                self.assertEqual(u42.get("hp"), 6, f"U42 should have 6 HP, got {u42.get('hp')}")

                exchange = SimpleExchange(proc)

                # Query the engine directly to verify the rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, state_revision)
                self.assertNotEqual(validation.get("valid"), True,
                                  f"Move to (4,7) must fail: {validation}")
                self.assertEqual(validation.get("failed_index"), 0,
                               f"Failure at index 0 expected, got {validation.get('failed_index')}")
                results = validation.get("results", [])
                self.assertGreater(len(results), 0, "Results array must be present")
                self.assertEqual(results[0].get("code"), "DestinationUnreachable",
                               f"Error code should be DestinationUnreachable, got {results[0].get('code')}")

                # Build rejection object as the engine would report it
                rejection = EngineBatchRejected(
                    message=f"Move failed: {results[0].get('code')}",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )
                self.assertIsNotNone(rejection.failed_move, "failed_move must be set")
                self.assertEqual(rejection.actor_id, 42)

                # Generate the repair menu
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                self.assertIsNotNone(menu, "Menu must be generated for a Move rejection")

                # Assert exactly two options
                options = menu.get("options", [])
                self.assertEqual(len(options), 2,
                               f"Should offer exactly 2 endpoints, got {len(options)}: {[o.get('option_id') for o in options]}")

                # Verify order: (5,10) before (5,8)
                first = options[0]
                second = options[1]
                first_dest = first.get("destination", {})
                second_dest = second.get("destination", {})

                self.assertEqual((first_dest.get("col"), first_dest.get("row")), (5, 10),
                               f"First option should be (5,10), got ({first_dest.get('col')},{first_dest.get('row')})")
                self.assertEqual((second_dest.get("col"), second_dest.get("row")), (5, 8),
                               f"Second option should be (5,8), got ({second_dest.get('col')},{second_dest.get('row')})")

                # Verify neither (4,7) nor (3,9) appear
                offered_dests = {(o.get("destination", {}).get("col"), o.get("destination", {}).get("row"))
                                for o in options}
                self.assertNotIn((4, 7), offered_dests, "Original destination (4,7) must not appear")
                self.assertNotIn((3, 9), offered_dests, "Repair guess (3,9) must not appear")

                # Verify exposure data
                first_exp = first.get("exposure", {})
                second_exp = second.get("exposure", {})
                self.assertEqual(first_exp.get("distinct_attacker_count"), 9,
                               f"First option should have 9 attackers, got {first_exp.get('distinct_attacker_count')}")
                self.assertEqual(second_exp.get("distinct_attacker_count"), 13,
                               f"Second option should have 13 attackers, got {second_exp.get('distinct_attacker_count')}")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_every_advertised_endpoint_is_executable(self):
        """Validate that each advertised option executes successfully through
        query_validate_batch at the same state_revision."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                exchange = SimpleExchange(proc)

                # Build and validate the rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, state_revision)

                rejection = EngineBatchRejected(
                    message=f"Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Generate the menu
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                self.assertIsNotNone(menu)

                # Validate each advertised option
                for option in menu.get("options", []):
                    actions = option.get("actions", [])
                    self.assertIsInstance(actions, list)
                    self.assertGreater(len(actions), 0, f"Option {option.get('option_id')} must have actions")

                    # Query validation at the fixed state_revision
                    verdict = query_validate_batch(exchange, copy.deepcopy(actions), state_revision)
                    self.assertIs(verdict.get("valid"), True,
                                f"Option {option.get('option_id')} must be valid; verdict={verdict}")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_read_only_state_unchanged(self):
        """State revision and unit positions/HP must be identical before and after
        generating the repair menu. Assertions are UNCONDITIONAL."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)

                initial_revision = initial_state.get("state_revision")
                initial_units = copy.deepcopy(initial_state.get("units", []))
                initial_by_id = {u["id"]: u for u in initial_units}

                exchange = SimpleExchange(proc)

                # Build rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, initial_revision)
                rejection = EngineBatchRejected(
                    message="Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=initial_revision
                )

                # Generate menu
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)

                # Query state after menu generation
                after = exchange({"action": "Query", "what": "state"})
                self.assertTrue(after.get("ok"), f"state query must succeed: {after}")
                after_state = after.get("body") or {}
                after_revision = after_state.get("state_revision")
                after_units = after_state.get("units", [])

                # UNCONDITIONAL assertions on state revision
                self.assertEqual(initial_revision, after_revision,
                               "state_revision must be unchanged after menu generation")

                # UNCONDITIONAL assertions on units
                after_by_id = {u["id"]: u for u in after_units}
                self.assertEqual(len(initial_by_id), len(after_by_id),
                               "unit count must not change")

                for unit_id, before_unit in initial_by_id.items():
                    self.assertIn(unit_id, after_by_id,
                                f"unit {unit_id} must still be present")
                    after_unit = after_by_id[unit_id]
                    self.assertEqual(before_unit.get("col"), after_unit.get("col"),
                                   f"unit {unit_id} col must be unchanged")
                    self.assertEqual(before_unit.get("row"), after_unit.get("row"),
                                   f"unit {unit_id} row must be unchanged")
                    self.assertEqual(before_unit.get("hp"), after_unit.get("hp"),
                                   f"unit {unit_id} hp must be unchanged")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_query_bound_at_most_four_queries(self):
        """Building the menu issues ONE inspect_unit plus AT MOST 3 validate_batch
        queries. Assert both exchange wrapper count and menu['validations_used']."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                exchange = SimpleExchange(proc)

                # Build rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, state_revision)
                rejection = EngineBatchRejected(
                    message="Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Reset query counts before generating menu
                exchange.inspect_unit_count = 0
                exchange.validate_batch_count = 0

                # Generate menu
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                self.assertIsNotNone(menu)

                # Assert query counts
                self.assertEqual(exchange.inspect_unit_count, 1,
                               f"Must issue exactly 1 inspect_unit query, got {exchange.inspect_unit_count}")
                self.assertLessEqual(exchange.validate_batch_count, STRATEGY_MAX_REPAIR_VALIDATIONS,
                                   f"Must issue at most {STRATEGY_MAX_REPAIR_VALIDATIONS} validate_batch queries, got {exchange.validate_batch_count}")

                # Assert menu reports the same count
                self.assertEqual(menu.get("validations_used"), exchange.validate_batch_count,
                               f"Menu validations_used must match actual count: {menu.get('validations_used')} vs {exchange.validate_batch_count}")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_already_moved_returns_no_options(self):
        """When unit has already moved (moved=True), menu returns no options
        with unavailable_reason 'already_moved', NOT 'no_legal_endpoints'."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                # Modify the state: mark U42 as already moved
                modified_state = copy.deepcopy(initial_state)
                units = modified_state.get("units", [])
                for unit in units:
                    if unit.get("id") == 42:
                        unit["moved"] = True

                exchange = SimpleExchange(proc)

                # Build rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, state_revision)
                rejection = EngineBatchRejected(
                    message="Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Generate menu with modified state
                menu = movement_repair_menu(rejection, exchange, modified_state, llm_side=0)
                self.assertIsNotNone(menu)

                # Assert no options and correct unavailable_reason
                self.assertEqual(len(menu.get("options", [])), 0,
                               "Menu must have no options when unit has moved")
                self.assertEqual(menu.get("unavailable_reason"), "already_moved",
                               f"unavailable_reason must be 'already_moved', got {menu.get('unavailable_reason')}")
                self.assertNotEqual(menu.get("unavailable_reason"), "no_legal_endpoints",
                                  "Must NOT claim 'no_legal_endpoints' when unit has moved")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_foreign_actor_returns_none(self):
        """A rejection naming a unit on the opponent's side (faction != llm_side)
        yields None, so the caller keeps the ordinary repair."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                # Find a unit on faction 1 (opponent)
                units = {u["id"]: u for u in initial_state.get("units", [])}
                faction1_unit = None
                for uid, u in units.items():
                    if u.get("faction") == 1:
                        faction1_unit = uid
                        break
                self.assertIsNotNone(faction1_unit, "Must have a unit on faction 1")

                exchange = SimpleExchange(proc)

                # Build a rejection for the foreign unit
                orders = [{"action": "Move", "unit_id": faction1_unit, "col": 4, "row": 7}]
                # We don't validate this - just construct the rejection manually
                validation = {"valid": False, "failed_index": 0, "results": [{"ok": False, "code": "DestinationUnreachable"}]}
                rejection = EngineBatchRejected(
                    message="Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Generate menu with llm_side=0 (opponent unit should return None)
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                self.assertIsNone(menu, "Menu must be None for a foreign unit")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_budget_exhaustion_mid_menu(self):
        """When budget is exhausted on the 2nd validate_batch, the menu still returns,
        advertises only endpoints validated before the failure, and never raises."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                exchange = SimpleExchange(proc)
                # Set budget limit to trigger on 2nd validate_batch
                exchange.budget_limit_on_validate_batch = 2

                # Build rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, state_revision)
                rejection = EngineBatchRejected(
                    message="Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Reset counts
                exchange.validate_batch_count = 0

                # Generate menu - should NOT raise
                try:
                    menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                except QueryBudgetExhausted:
                    self.fail("movement_repair_menu must not raise QueryBudgetExhausted; it should catch and degrade gracefully")

                self.assertIsNotNone(menu)

                # Menu should only advertise endpoints validated before budget exhaustion
                options = menu.get("options", [])
                # First validate_batch succeeds (cost 2 endpoint)
                # Second validate_batch fails with query_limit
                # So we should have at most 1 advertised endpoint
                self.assertLessEqual(len(options), 1,
                                   f"Should have at most 1 validated endpoint before budget exhaustion, got {len(options)}")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_non_move_rejection_returns_none(self):
        """An EngineBatchRejected whose failed action is an Attack (not a Move)
        returns None from movement_repair_menu, so existing non-movement repairs
        remain untouched."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                exchange = SimpleExchange(proc)

                # Build a rejection for an Attack (not a Move)
                orders = [{"action": "Attack", "attacker_id": 42, "defender_id": 99}]
                validation = {"valid": False, "failed_index": 0, "results": [{"ok": False, "code": "UnitNotFound"}]}
                rejection = EngineBatchRejected(
                    message="Attack failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Verify it's not a Move
                self.assertIsNone(rejection.failed_move, "Rejection must not be a Move")

                # Generate menu - should return None
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                self.assertIsNone(menu, "Menu must be None for non-Move rejections")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_rendering_text_format(self):
        """Rendered text names each option id and destination, shows exposure numbers,
        says the whole failed batch is replaced, and NEVER contains 'safe'."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            checkpoint_path = FIXTURES / "checkpoint-d98880407c973fb2059d6e67a1bf9a5a2dfe2c59bd92a27b423e30425548ff59.json"
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "4477",
                 "--llm-side", "0", "--max-turns", "120", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint_path)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                initial_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial_state = obj
                        break

                self.assertIsNotNone(initial_state)
                state_revision = initial_state.get("state_revision")

                exchange = SimpleExchange(proc)

                # Build rejection
                orders = [{"action": "Move", "unit_id": 42, "col": 4, "row": 7}]
                validation = query_validate_batch(exchange, orders, state_revision)
                rejection = EngineBatchRejected(
                    message="Move failed",
                    orders=orders,
                    validation=validation,
                    state_revision=state_revision
                )

                # Generate menu
                menu = movement_repair_menu(rejection, exchange, initial_state, llm_side=0)
                self.assertIsNotNone(menu)

                # Render the text
                text = render_movement_repair_options(menu, requested_col=4, requested_row=7)
                self.assertIsInstance(text, str)

                # Assert structure requirements
                self.assertIn("MOVEMENT REPAIR", text, "Text must mention MOVEMENT REPAIR")
                self.assertIn("replaces the entire failed batch", text,
                            "Text must state the entire batch is replaced")

                # Assert each option is named with its id and destination
                for option in menu.get("options", []):
                    option_id = option.get("option_id")
                    dest = option.get("destination", {})
                    dest_col = dest.get("col")
                    dest_row = dest.get("row")
                    self.assertIn(option_id, text,
                                f"Text must contain option id {option_id}")
                    # Check for destination coordinates in some form
                    self.assertIn(f"({dest_col},{dest_row})", text,
                                f"Text must contain destination ({dest_col},{dest_row})")

                # Assert exposure numbers are shown
                self.assertIn("attackers=", text, "Text must show attacker counts")

                # Assert NO "safe" word anywhere
                self.assertNotIn("safe", text.lower(), "Text must never use the word 'safe'")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    unittest.main()
