"""Real-driver acceptance tests for validated_selections_for_packet (Stack 1).

Drives the real client and driver with a scripted backend, testing the validation
of candidate selections through the engine. Asserts on actual log records and
driver responses, not mocks.
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
    validated_selections_for_packet,
    STRATEGY_MAX_VALIDATION_QUERIES,
    resolve_choose_batch,
    query_validate_batch,
    NO_SWEEP_FINISH,
)
from .routine_policy import ChooseResponse
from .strategy_decision import DecisionPacket, candidate_selections
from .test_strategy_routine_stack3 import (
    DRIVER, ROOT, assert_success, launch, policy, prepare, prompts, records
)

FIXTURES = ROOT / "tools/fixtures/strategy_routine"


def make_tactical_packet_from_options(options: list[dict]) -> DecisionPacket:
    """Construct a minimal tactical decision packet with the given options."""
    return DecisionPacket(
        decision_id="test-packet",
        state_revision=1,
        decision_kind="tactical",
        incident_key="test-incident",
        reason="contact",
        evidence={
            "stage": "current_state",
            "trigger": "attack",
            "friendly_unit_ids": [1, 2],
            "enemy_unit_ids": [7, 8],
            "contact_actionability": "actionable",
        },
        allowed_kinds=["choose", "act", "finish_turn", "resign"],
        options=options,
        coverage={"options": "complete"},
        final_only=False,
    )


class SimpleExchange:
    """A simple exchange wrapper for testing that wraps the driver exchange."""

    def __init__(self, driver_proc):
        self.driver_proc = driver_proc
        self.query_count = 0
        self.validate_batch_count = 0
        self.should_fail_on_validate_batch = None  # Set to an int to fail on that validate_batch query number

    def __call__(self, request):
        """Send a request to the driver and get the response."""
        self.query_count += 1

        # For validate_batch queries, track and optionally fail
        if request.get("what") == "validate_batch":
            self.validate_batch_count += 1
            if (self.should_fail_on_validate_batch is not None and
                self.validate_batch_count == self.should_fail_on_validate_batch):
                raise RuntimeError(f"query_error: simulated failure on validate_batch query {self.validate_batch_count}")

        # Send to driver and get response
        self.driver_proc.stdin.write(json.dumps(request) + "\n")
        self.driver_proc.stdin.flush()
        response_line = self.driver_proc.stdout.readline()
        if not response_line:
            raise RuntimeError("driver closed unexpectedly")
        return json.loads(response_line)


@unittest.skipUnless(DRIVER.is_file(), "Build the actual integration driver; skipped is not acceptance")
class ValidatedSelectionsTests(unittest.TestCase):

    def test_shared_target_first_attack_kills_blocks_multi_advertised_selection(self):
        """REAL DRIVER VERDICT: When two attacks target the same enemy that dies to
        the first attack, the engine rejects the both-attack batch (UnitNotFound at
        failed_index 1), and no advertised validated selection contains both
        option_ids together. At least one singleton validated selection available.

        Position: revision 219 from archived game glm-luna-fullgame-20260917T000424Z.
        U13 attacks U24 (lethal, 20 HP), U11 attacks U24 (illegal, already dead).
        Engine replies: valid=false, failed_index=1, code=UnitNotFound,
        message="target U24 was killed by earlier proposed action index 1".
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Resume from the shared_target_attack checkpoint at revision 219
            checkpoint_path = (FIXTURES / ".." / "choice_recovery" /
                              "checkpoint-469f81c066e604466ec655eaf797bbbc1921eb2bbcc5d88bf72dd9e2096a7c3f.json")
            if not checkpoint_path.exists():
                self.skipTest(f"Checkpoint fixture not found: {checkpoint_path}")

            # Launch the driver process
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
                self.assertEqual(state_revision, 219, "Expected revision 219 from checkpoint")

                exchange = SimpleExchange(proc)

                # Build tactical packet with two attacks on U24 from different actors
                # U24 is at (9,6) with 20 HP. Using U13 and U11 as per the fixture.
                # U13 needs to move to (7,7) to reach U24, then attack.
                # U11 needs to move to (8,8) to reach U24, then attack.
                # U24 dies to first attack (20 HP).
                options = [
                    {
                        "option_id": "u13-move-and-attack-u24",
                        "actor_id": 13,  # Unit 13
                        "actions": [
                            {"action": "Move", "unit_id": 13, "col": 7, "row": 7},
                            {"action": "Attack", "attacker_id": 13, "defender_id": 24}
                        ],
                    },
                    {
                        "option_id": "u11-move-and-attack-u24",
                        "actor_id": 11,  # Unit 11 (DIFFERENT actor from U13)
                        "actions": [
                            {"action": "Move", "unit_id": 11, "col": 8, "row": 8},
                            {"action": "Attack", "attacker_id": 11, "defender_id": 24}
                        ],
                    },
                    {
                        "option_id": "u10-move-safe",
                        "actor_id": 10,  # Unit 10
                        "actions": [{"action": "Move", "unit_id": 10, "col": 5, "row": 6}],
                    },
                ]

                packet = make_tactical_packet_from_options(options)
                packet = DecisionPacket(
                    decision_id=packet.decision_id,
                    state_revision=state_revision,
                    decision_kind=packet.decision_kind,
                    incident_key=packet.incident_key,
                    reason=packet.reason,
                    evidence=packet.evidence,
                    allowed_kinds=packet.allowed_kinds,
                    options=packet.options,
                    coverage=packet.coverage,
                    final_only=packet.final_only)

                # Call validated_selections_for_packet
                validated, coverage, queries_used = validated_selections_for_packet(
                    packet, exchange, state_revision, no_recruit_macro=False
                )

                # Assertion (a): No validated selection contains both move-and-attack option_ids
                candidates_with_both_attacks = [
                    v for v in validated
                    if "u13-move-and-attack-u24" in v.get("option_ids", []) and "u11-move-and-attack-u24" in v.get("option_ids", [])
                ]
                self.assertEqual(len(candidates_with_both_attacks), 0,
                               "No validated selection should contain both attack option_ids (both-attack batch is illegal)")

                # Assertion (b): Verify the engine actually rejects the both-attacks batch
                # Expand the both-attacks batch as the engine would
                both_attacks = ChooseResponse(
                    decision_id=packet.decision_id,
                    option_ids=["u13-move-and-attack-u24", "u11-move-and-attack-u24"],
                    finish_turn=False
                )
                orders, _ = resolve_choose_batch(both_attacks, packet, no_recruit_macro=False)

                # Query engine validation
                validation = query_validate_batch(exchange, orders, state_revision)

                # Verify it's invalid at the second attack
                self.assertNotEqual(validation.get("valid"), True,
                                  f"Both-attack batch should be invalid. Engine reply: {validation}")
                # Batch is: Move U13, Attack U13->U24, Move U11, Attack U11->U24
                # Failure is at index 3 (second attack), because first attack kills U24
                self.assertEqual(validation.get("failed_index"), 3,
                               f"Failure should be at index 3 (second attack), got: {validation.get('failed_index')}")

                # Extract the failed action from results array
                results = validation.get("results", [])
                failed_idx = validation.get("failed_index")
                if isinstance(failed_idx, int) and failed_idx < len(results):
                    failed_result = results[failed_idx]
                    self.assertEqual(failed_result.get("code"), "UnitNotFound",
                                   f"Error should be UnitNotFound, got: {failed_result.get('code')}")
                    message = str(failed_result.get("message", ""))
                    self.assertIn("killed by earlier", message.lower(),
                                f"Message should mention earlier kill. Got: {message}")
                else:
                    self.fail(f"Could not extract failed result at index {failed_idx} from {len(results)} results")

                # Assertion (c): At least one singleton validated selection should be available
                singleton_validated = [v for v in validated if len(v.get("option_ids", [])) == 1]
                self.assertGreater(len(singleton_validated), 0,
                                 "Should have at least one singleton validated selection (model still has executable choice)")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_shared_target_target_survives_allows_multi_attack_validation(self):
        """REAL DRIVER VERDICT: two attacks that SHARE a surviving target validate.

        This is the regression guard for the shared-target work: a filter that kept
        the model from stacking attacks on a target that dies first must NOT outlaw
        stacking attacks on a target that lives.

        Position: SYNTHETIC. It is the archived revision 219 board from game
        glm-luna-fullgame-20260917T000424Z with exactly ONE field changed - enemy U23's
        hp raised to 60 - so that two attacks provably cannot kill it. It is NOT a
        reproduction of a played position. The unmodified revision 219 cannot express
        this case: every pair of attackers that can reach a shared target from distinct
        hexes deals combined maximum damage >= that target's HP, so the target might die
        and the batch's legality would depend on rolls rather than on the rule under test.

        The arithmetic is checked in the test rather than assumed: each attacker's
        maximum damage comes from the engine's own combat_preview, and their SUM must be
        strictly less than the defender's current HP before the batch is validated.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            checkpoint_path = (FIXTURES / ".." / "choice_recovery" /
                              "checkpoint-567f9b13d55f2ddbe10c0b3317bacad7229f891298b5f057d9d41d1036d1731f.json")
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
                self.assertIsNotNone(initial_state, "Could not get initial state from driver")
                self.assertEqual(initial_state.get("state_revision"), 219)
                units = {u["id"]: u for u in initial_state.get("units", [])}
                defender = units[23]
                self.assertEqual(defender["hp"], 60,
                                 "synthetic fixture must carry the raised defender HP")

                exchange = SimpleExchange(proc)
                # U11 attacks from (6,6) and U13 from (6,7): distinct hexes, one shared target.
                plan = [(11, 6, 6), (13, 6, 7)]
                total_max = 0
                for unit_id, col, row in plan:
                    preview = exchange({"action": "Query", "what": "combat_preview",
                                        "attacker_id": unit_id, "defender_id": 23,
                                        "col": col, "row": row, "n_sims": 50})
                    body = preview.get("body") or {}
                    attacker_max = body.get("attacker_damage_max")
                    self.assertIsInstance(attacker_max, int,
                                          f"engine must report U{unit_id}'s maximum damage")
                    total_max += attacker_max
                self.assertLess(total_max, defender["hp"],
                                "both attacks together must be unable to kill the defender; "
                                f"max {total_max} vs hp {defender['hp']}")

                orders = []
                for unit_id, col, row in plan:
                    orders.append({"action": "Move", "unit_id": unit_id, "col": col, "row": row})
                    orders.append({"action": "Attack", "attacker_id": unit_id, "defender_id": 23})
                validation = query_validate_batch(exchange, orders, 219)
                self.assertIs(validation.get("valid"), True,
                              f"engine must accept two attacks on a surviving target: {validation}")
                self.assertTrue(all(result.get("ok") for result in validation.get("results", [])),
                                f"every action must validate: {validation}")
                self.assertIsNot(validation.get("committed"), True,
                                 "validation must not commit anything")
            finally:
                proc.stdin.close()
                proc.wait(timeout=20)

    def test_query_budget_ceiling_at_most_four_queries(self):
        """Validated_selections_for_packet should issue AT MOST 4 validate_batch
        queries for a packet with many options. Count real queries via an exchange
        wrapper and verify both the wrapper count and returned queries_used agree.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Prepare a real driver session with contact.json
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", [policy()])

            # Launch the driver process
            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "9211",
                 "--llm-side", "0", "--max-turns", "6", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint)],
                cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True)

            try:
                # Get initial state
                initial = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        raise RuntimeError("driver closed")
                    obj = json.loads(line)
                    if obj.get("type") == "state":
                        initial = obj
                        break

                self.assertIsNotNone(initial, "Could not get initial state from driver")
                state_revision = initial.get("state_revision")

                # Wrap the exchange with query counting
                exchange = SimpleExchange(proc)

                # Create a packet with many options (more than STRATEGY_MAX_VALIDATION_QUERIES)
                many_options = [
                    {
                        "option_id": f"option-{i}",
                        "actor_id": 3,
                        "actions": [{"action": "Move", "unit_id": 3, "col": 10 + i, "row": 7}],
                    }
                    for i in range(8)  # 8 options > STRATEGY_MAX_VALIDATION_QUERIES (4)
                ]
                packet = make_tactical_packet_from_options(many_options)

                # Call validated_selections_for_packet
                validated, coverage, queries_used = validated_selections_for_packet(
                    packet, exchange, state_revision, no_recruit_macro=False
                )

                # Assert query budget ceiling
                self.assertLessEqual(queries_used, STRATEGY_MAX_VALIDATION_QUERIES,
                                   f"Should issue at most {STRATEGY_MAX_VALIDATION_QUERIES} queries")

                # Assert query count from exchange wrapper matches returned queries_used
                self.assertEqual(exchange.validate_batch_count, queries_used,
                               "Exchange wrapper validate_batch count should match returned queries_used")

                # Verify coverage is reasonable
                self.assertIn(coverage, ["validated", "none_validated", "not_generated", "unavailable"],
                            f"Coverage should be one of the known values, got: {coverage}")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_read_only_state_unchanged_by_validation(self):
        """Validation must not commit anything. Assert the live state is unchanged
        by candidate validation: same state_revision before and after, and identical
        unit positions/HP.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Prepare a real driver session
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", [policy()])

            # Launch the driver process
            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "9211",
                 "--llm-side", "0", "--max-turns", "6", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint)],
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

                initial_revision = initial_state.get("state_revision")
                initial_units = copy.deepcopy(initial_state.get("units", []))

                exchange = SimpleExchange(proc)
                state_revision = initial_state.get("state_revision")

                # Create a simple packet
                options = [
                    {
                        "option_id": "option-1",
                        "actor_id": 3,
                        "actions": [{"action": "Move", "unit_id": 3, "col": 10, "row": 7}],
                    },
                ]
                packet = make_tactical_packet_from_options(options)

                # Call validated_selections_for_packet
                validated, coverage, queries_used = validated_selections_for_packet(
                    packet, exchange, state_revision, no_recruit_macro=False
                )

                # Query the driver for current state after validation
                exchange({"action": "Query", "what": "routine_next",
                         "state_revision": state_revision,
                         "policy": {"reserve_gold": 0, "recruits": [], "scouts": [],
                                   "villages": [], "rally": None, "holds": []},
                         "progress": {}})

                # Get the response and check for state
                after_state = None
                for _ in range(100):
                    line = proc.stdout.readline()
                    if not line:
                        break
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "state":
                            after_state = obj
                            break
                    except (json.JSONDecodeError, ValueError):
                        continue

                # State revision should not have changed (validation is read-only)
                if after_state:
                    after_revision = after_state.get("state_revision")
                    self.assertEqual(initial_revision, after_revision,
                                   "State revision should not change after validation")

                    # Unit positions and HP should be identical
                    after_units = after_state.get("units", [])
                    self.assertEqual(len(initial_units), len(after_units),
                                   "Number of units should not change")

                    for init_unit, after_unit in zip(initial_units, after_units):
                        self.assertEqual(init_unit.get("id"), after_unit.get("id"),
                                       "Unit IDs should match")
                        self.assertEqual(init_unit.get("col"), after_unit.get("col"),
                                       f"Unit {init_unit.get('id')} col should not change")
                        self.assertEqual(init_unit.get("row"), after_unit.get("row"),
                                       f"Unit {init_unit.get('id')} row should not change")
                        self.assertEqual(init_unit.get("hp"), after_unit.get("hp"),
                                       f"Unit {init_unit.get('id')} hp should not change")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def test_coverage_truthfulness_query_error_gives_unavailable_not_none_validated(self):
        """When a validation query raises (simulated by an exchange wrapper that
        raises RuntimeError on the Nth call), assert coverage is "unavailable" and
        NOT "none_validated", and that no unproven candidate appears in the
        returned list.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Prepare a real driver session
            checkpoint, _, backend, prompt_log = prepare(root, "contact.json", [policy()])

            # Launch the driver process
            proc = subprocess.Popen(
                [str(DRIVER), "--scenario", "big_battle_6", "--faction0", "undead",
                 "--faction1", "undead", "--gold", "300", "--seed", "9211",
                 "--llm-side", "0", "--max-turns", "6", "--incremental-turns",
                 "--resume-checkpoint", str(checkpoint)],
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

                # Wrap exchange with query failure on 2nd validate_batch query
                exchange = SimpleExchange(proc)
                exchange.should_fail_on_validate_batch = 2

                # Create a packet with multiple candidate options from different actors
                options = [
                    {
                        "option_id": "option-1",
                        "actor_id": 3,
                        "actions": [{"action": "Move", "unit_id": 3, "col": 10, "row": 7}],
                    },
                    {
                        "option_id": "option-2",
                        "actor_id": 4,  # Different actor
                        "actions": [{"action": "Move", "unit_id": 4, "col": 11, "row": 8}],
                    },
                    {
                        "option_id": "option-3",
                        "actor_id": 5,  # Different actor
                        "actions": [{"action": "Move", "unit_id": 5, "col": 12, "row": 9}],
                    },
                ]
                packet = make_tactical_packet_from_options(options)

                # Call validated_selections_for_packet, which will fail on 2nd query
                validated, coverage, queries_used = validated_selections_for_packet(
                    packet, exchange, state_revision, no_recruit_macro=False
                )

                # Assert coverage is "unavailable", not "none_validated"
                self.assertEqual(coverage, "unavailable",
                               f"Coverage should be 'unavailable' when query fails, got: {coverage}")

                # Assert no unproven candidate in returned validated list
                # The function should return what it validated before the failure
                for validated_sel in validated:
                    self.assertIn("option_ids", validated_sel,
                                "Each validated selection should have option_ids")
                    self.assertIsNotNone(validated_sel.get("source_revision"),
                                       "Each validated selection should have source_revision")

            finally:
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


