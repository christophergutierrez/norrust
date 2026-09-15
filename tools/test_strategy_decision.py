"""Unit tests for tools/strategy_decision.py (Stack 1)."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from . import strategy_decision as sd


class DecisionRoutingTests(unittest.TestCase):
  def test_current_state_contact_routes_to_tactical_without_set_policy(self):
    evidence = {
      "stage": "current_state",
      "trigger": "attack",
      "friendly_unit_ids": [3],
      "enemy_unit_ids": [7],
      "coverage": "complete",
    }
    packet = sd.build_decision_packet("contact", evidence, revision=64)
    self.assertEqual(packet.decision_kind, sd.DECISION_KIND_TACTICAL)
    self.assertNotIn("set_policy", packet.allowed_kinds)
    self.assertEqual(packet.allowed_kinds, ["act", "finish_turn", "resign"])
    self.assertEqual(packet.coverage["facts"], "complete")

    # Contextual validation rejects set_policy
    with self.assertRaises(sd.ContextualResponseError):
      sd.validate_response_context(SimpleNamespace(kind="set_policy"), packet)

    # Contextual validation accepts act, finish_turn, resign
    sd.validate_response_context(SimpleNamespace(kind="act"), packet)
    sd.validate_response_context(SimpleNamespace(kind="finish_turn"), packet)
    sd.validate_response_context(SimpleNamespace(kind="resign"), packet)

  def test_proposed_move_contact_routes_to_policy_with_set_policy(self):
    evidence = {
      "stage": "proposed_destination",
      "unit_id": 2,
      "destination": {"col": 4, "row": 3},
    }
    packet = sd.build_decision_packet("contact", evidence, revision=12)
    self.assertEqual(packet.decision_kind, sd.DECISION_KIND_POLICY)
    self.assertIn("set_policy", packet.allowed_kinds)
    sd.validate_response_context(SimpleNamespace(kind="set_policy"), packet)

  def test_promotion_pending_routes_to_promotion_without_finish_turn(self):
    evidence = {"unit_ids": [5]}
    packet = sd.build_decision_packet("promotion_pending", evidence, revision=10)
    self.assertEqual(packet.decision_kind, sd.DECISION_KIND_PROMOTION)
    self.assertEqual(packet.allowed_kinds, ["act", "resign"])
    self.assertNotIn("finish_turn", packet.allowed_kinds)
    self.assertNotIn("set_policy", packet.allowed_kinds)

    with self.assertRaises(sd.ContextualResponseError):
      sd.validate_response_context(SimpleNamespace(kind="finish_turn"), packet)
    with self.assertRaises(sd.ContextualResponseError):
      sd.validate_response_context(SimpleNamespace(kind="set_policy"), packet)
    sd.validate_response_context(SimpleNamespace(kind="act"), packet)
    sd.validate_response_context(SimpleNamespace(kind="resign"), packet)

  def test_initial_policy_allowed_kinds(self):
    evidence = {"policy_complete": True}
    packet = sd.build_decision_packet("initial", evidence, revision=0)
    self.assertEqual(packet.allowed_kinds, ["set_policy", "act", "finish_turn", "resign"])

  def test_incident_key_canonicalization_ignores_prose_and_ids(self):
    ev1 = {
      "stage": "current_state",
      "friendly_unit_ids": [3, 1],
      "enemy_unit_ids": [7, 5],
      "trigger": "attack",
      "prose": "some explanation",
      "request_id": "req-1",
    }
    ev2 = {
      "stage": "current_state",
      "friendly_unit_ids": [1, 3],
      "enemy_unit_ids": [5, 7],
      "trigger": "attack",
      "prose": "different explanation",
      "request_id": "req-2",
    }
    k1 = sd.compute_incident_key("g1", 1, "contact", ev1)
    k2 = sd.compute_incident_key("g1", 1, "contact", ev2)
    self.assertEqual(k1, k2)

    # Different units produce different keys
    ev3 = {**ev1, "enemy_unit_ids": [9]}
    k3 = sd.compute_incident_key("g1", 1, "contact", ev3)
    self.assertNotEqual(k1, k3)


class IncidentTrackerTests(unittest.TestCase):
  def test_ineffective_allowance_bounds_to_one_correction(self):
    tracker = sd.IncidentTracker()
    side_turn = 1
    revision = 64
    incident_key = "key-A"

    # First encounter
    is_first = tracker.observe_incident(side_turn, revision, incident_key)
    self.assertTrue(is_first)
    self.assertTrue(tracker.can_attempt_correction(side_turn, revision, incident_key))

    # First ineffective response consumed
    tracker.record_ineffective(side_turn, revision, incident_key)
    # Correction allowed (exactly 1 consumed)
    self.assertTrue(tracker.can_attempt_correction(side_turn, revision, incident_key))

    # Second ineffective response consumed
    tracker.record_ineffective(side_turn, revision, incident_key)
    # Allowance exhausted!
    self.assertFalse(tracker.can_attempt_correction(side_turn, revision, incident_key))

  def test_aba_loop_at_same_revision_does_not_renew_allowance(self):
    tracker = sd.IncidentTracker()
    side_turn = 1
    revision = 64

    # Encounter A, consume 1 ineffective response
    self.assertTrue(tracker.observe_incident(side_turn, revision, "key-A"))
    tracker.record_ineffective(side_turn, revision, "key-A")

    # Change to B
    self.assertTrue(tracker.observe_incident(side_turn, revision, "key-B"))

    # Return to A at unchanged revision
    is_first = tracker.observe_incident(side_turn, revision, "key-A")
    self.assertFalse(is_first, "A was already seen at revision 64")
    # A already consumed its 1 ineffective response!
    tracker.record_ineffective(side_turn, revision, "key-A")
    self.assertFalse(tracker.can_attempt_correction(side_turn, revision, "key-A"))

  def test_reconstruct_from_journal_restores_consumed_allowance(self):
    tracker = sd.IncidentTracker()
    rows = [
      {"type": "decision_packet", "side_turn": 1, "packet": {"state_revision": 64, "incident_key": "k1"}},
      {"type": "contextual_rejection", "side_turn": 1, "state_revision": 64, "incident_key": "k1"},
    ]
    tracker.reconstruct_from_journal(rows)
    self.assertTrue(tracker.can_attempt_correction(1, 64, "k1"))
    # Next ineffective response in this session will exhaust it
    tracker.record_ineffective(1, 64, "k1")
    self.assertFalse(tracker.can_attempt_correction(1, 64, "k1"))


class TacticalOptionsTests(unittest.TestCase):
  def setUp(self):
    self.sample_options = [
      {
        "option_id": "u1-attack-1",
        "category": "attack",
        "actor_id": 1,
        "actions": [{"action": "Attack", "attacker_id": 1, "defender_id": 5}],
        "forecast": {
          "kill_chance_bps": 6500,
          "expected_damage_dealt_tenths": 120,
          "expected_damage_received_tenths": 30,
          "outcome_bps": [6500, 2000, 1500],
        },
        "coverage": "complete",
      },
      {
        "option_id": "u1-relocate-1",
        "category": "relocation",
        "actor_id": 1,
        "actions": [{"action": "Move", "unit_id": 1, "col": 4, "row": 3}],
        "movement_cost": 2,
        "exposure": {
          "distinct_attacker_count": 3,
          "max_incoming_damage": 48,
          "expected_incoming_damage_tenths": 84,
        },
        "coverage": "complete",
      },
    ]
    self.multi_actor_options = [
      {
        "option_id": "u6-relocate-2",
        "category": "relocation",
        "actor_id": 6,
        "actions": [{"action": "Move", "unit_id": 6, "col": 8, "row": 2}],
        "movement_cost": 3,
        "exposure": {
          "distinct_attacker_count": 2,
          "max_incoming_damage": 12,
          "expected_incoming_damage_tenths": 40,
        },
      },
      {
        "option_id": "u7-relocate-1",
        "category": "relocation",
        "actor_id": 7,
        "actions": [{"action": "Move", "unit_id": 7, "col": 9, "row": 1}],
        "movement_cost": 1,
        "exposure": {
          "distinct_attacker_count": 0,
          "max_incoming_damage": 0,
          "expected_incoming_damage_tenths": 0,
        },
      },
      {
        "option_id": "u4-relocate-1",
        "category": "relocation",
        "actor_id": 4,
        "actions": [{"action": "Move", "unit_id": 4, "col": 3, "row": 5}],
        "exposure": None,
      },
    ]

  def test_tactical_decision_with_options_includes_choose(self):
    evidence = {
      "stage": "current_state",
      "trigger": "attack",
      "friendly_unit_ids": [1],
      "enemy_unit_ids": [5],
      "actor_ids": [1],
      "eligible_actor_count": 1,
      "actors_truncated": False,
      "options": self.sample_options,
      "options_truncated": False,
    }
    packet = sd.build_decision_packet("contact", evidence, revision=42)
    self.assertEqual(packet.decision_kind, sd.DECISION_KIND_TACTICAL)
    self.assertEqual(packet.allowed_kinds, ["choose", "act", "finish_turn", "resign"])
    self.assertEqual(packet.coverage["options"], "complete")
    self.assertEqual(len(packet.options), 2)
    self.assertEqual(packet.options[0]["option_id"], "u1-attack-1")
    self.assertEqual(packet.evidence["actor_ids"], [1])
    self.assertNotIn("primary_actor_id", packet.evidence)

  def test_tactical_decision_truncated_options_coverage(self):
    evidence = {
      "stage": "current_state",
      "trigger": "exposure",
      "friendly_unit_ids": [1],
      "enemy_unit_ids": [5],
      "options": self.sample_options,
      "options_truncated": True,
    }
    packet = sd.build_decision_packet("contact", evidence, revision=42)
    self.assertEqual(packet.coverage["options"], "truncated")

  def test_tactical_decision_without_options_excludes_choose(self):
    evidence = {
      "stage": "current_state",
      "trigger": "attack",
      "friendly_unit_ids": [1],
      "enemy_unit_ids": [5],
      "options": [],
    }
    packet = sd.build_decision_packet("contact", evidence, revision=42)
    self.assertEqual(packet.allowed_kinds, ["act", "finish_turn", "resign"])
    self.assertNotIn("choose", packet.allowed_kinds)

  def test_empty_options_reason_reaches_brief_without_changing_coverage(self):
    evidence = {
      "stage": "current_state",
      "trigger": "exposure",
      "friendly_unit_ids": [5, 6],
      "actor_ids": [],
      "eligible_actor_count": 2,
      "actors_truncated": False,
      "options": [],
      "options_truncated": False,
      "options_empty_reason": "no_executable_options",
      "coverage": "complete",
    }
    packet = sd.build_decision_packet("contact", evidence, revision=98)
    brief = sd.render_decision_brief(
      packet,
      state={"state_revision": 98, "units": []},
    )

    self.assertEqual(packet.coverage["options"], "complete")
    self.assertEqual(packet.evidence["options_empty_reason"], "no_executable_options")
    self.assertIn('"options_empty_reason":"no_executable_options"', brief)
    self.assertIn('"friendly_unit_ids":[5,6]', brief)
    self.assertIn("No eligible actor has an executable action", brief)
    self.assertIn("option enumeration coverage is complete", brief)
    self.assertNotIn("primary_actor", brief)
    self.assertIn("destination inspection", brief)

  def test_choose_response_validation_success(self):
    packet = sd.build_decision_packet(
      "contact",
      {"stage": "current_state", "options": self.sample_options},
      revision=42,
      decision_id="dec-1234",
    )
    resp = SimpleNamespace(
      kind="choose", decision_id="dec-1234", option_ids=["u1-attack-1"], finish_turn=False)
    sd.validate_response_context(resp, packet)
    sd.validate_response_context(
      SimpleNamespace(
        kind="choose",
        decision_id="dec-1234",
        option_ids=["u6-relocate-2", "u7-relocate-1"],
        finish_turn=False,
      ),
      sd.build_decision_packet(
        "contact",
        {"stage": "current_state", "options": self.multi_actor_options},
        revision=42,
        decision_id="dec-1234",
      ),
    )

  def test_choose_response_decision_id_mismatch(self):
    packet = sd.build_decision_packet(
      "contact",
      {"stage": "current_state", "options": self.sample_options},
      revision=42,
      decision_id="dec-1234",
    )
    resp = SimpleNamespace(
      kind="choose", decision_id="dec-stale", option_ids=["u1-attack-1"], finish_turn=False)
    with self.assertRaises(sd.ContextualResponseError) as ctx:
      sd.validate_response_context(resp, packet)
    self.assertIn("Decision ID mismatch", str(ctx.exception))

  def test_choose_response_unknown_option_id(self):
    packet = sd.build_decision_packet(
      "contact",
      {"stage": "current_state", "options": self.sample_options},
      revision=42,
      decision_id="dec-1234",
    )
    resp = SimpleNamespace(
      kind="choose", decision_id="dec-1234", option_ids=["attack_999"], finish_turn=False)
    with self.assertRaises(sd.ContextualResponseError) as ctx:
      sd.validate_response_context(resp, packet)
    self.assertIn("Unknown option_id", str(ctx.exception))

  def test_choose_response_rejects_two_options_for_one_actor(self):
    packet = sd.build_decision_packet(
      "contact",
      {"stage": "current_state", "options": self.sample_options},
      revision=42,
      decision_id="dec-1234",
    )
    resp = SimpleNamespace(
      kind="choose",
      decision_id="dec-1234",
      option_ids=["u1-attack-1", "u1-relocate-1"],
      finish_turn=False,
    )
    with self.assertRaises(sd.ContextualResponseError) as ctx:
      sd.validate_response_context(resp, packet)
    self.assertIn("at most one option per actor_id", str(ctx.exception))

  def test_choose_response_disallowed_when_no_options(self):
    packet = sd.build_decision_packet(
      "contact",
      {"stage": "current_state", "options": []},
      revision=42,
      decision_id="dec-1234",
    )
    resp = SimpleNamespace(
      kind="choose", decision_id="dec-1234", option_ids=["u1-attack-1"], finish_turn=False)
    with self.assertRaises(sd.ContextualResponseError):
      sd.validate_response_context(resp, packet)

  def test_final_only_enforcement(self):
    packet = sd.build_decision_packet(
      "contact",
      {"stage": "current_state", "options": self.sample_options},
      revision=42,
      decision_id="dec-1234",
      final_only=True,
    )
    # Choose with finish_turn=False fails
    with self.assertRaises(sd.ContextualResponseError):
      sd.validate_response_context(
        SimpleNamespace(
          kind="choose", decision_id="dec-1234", option_ids=["u1-attack-1"], finish_turn=False),
        packet,
      )
    # Choose with finish_turn=True succeeds
    sd.validate_response_context(
      SimpleNamespace(
        kind="choose", decision_id="dec-1234", option_ids=["u1-attack-1"], finish_turn=True),
      packet,
    )
    # Act with finish_turn=False fails
    with self.assertRaises(sd.ContextualResponseError):
      sd.validate_response_context(
        SimpleNamespace(kind="act", actions=[], finish_turn=False),
        packet,
      )
    # Act with finish_turn=True succeeds
    sd.validate_response_context(
      SimpleNamespace(kind="act", actions=[], finish_turn=True),
      packet,
    )

  def test_render_decision_brief_displays_options(self):
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [5],
        "actor_ids": [1],
        "eligible_actor_count": 1,
        "actors_truncated": False,
        "options": self.sample_options,
      },
      revision=42,
      decision_id="dec-abc",
    )
    brief = sd.render_decision_brief(packet)
    self.assertIn("grouped by actor", brief)
    self.assertIn("avoids another call per unit", brief)
    self.assertIn("Actor 1:", brief)
    self.assertIn("Option 'u1-attack-1'", brief)
    self.assertIn("Option 'u1-relocate-1'", brief)
    self.assertIn("Forecast:", brief)
    self.assertIn("expected damage dealt=12.0", brief)
    self.assertIn("attacker loss chance=15.0%", brief)
    self.assertIn("still exposed after this option", brief)
    self.assertIn("attackers=3", brief)
    self.assertIn("expected incoming damage=8.4", brief)
    self.assertIn("not a joint-plan forecast", brief)
    self.assertIn("Cost: 2", brief)
    self.assertIn('"kind":"choose"', brief)
    self.assertIn('"decision_id":"dec-abc"', brief)
    self.assertIn('"option_ids":["u1-attack-1","u1-relocate-1"]', brief)
    self.assertIn("actor_ids=[1]", brief)
    self.assertIn("eligible_actor_count=1", brief)
    self.assertIn("actors_truncated=false", brief)
    self.assertNotIn("primary_actor", brief)
    self.assertIn("destination inspection", brief)

  def test_render_groups_actors_and_distinguishes_zero_unknown_exposure(self):
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "exposure",
        "friendly_unit_ids": [6, 7, 4, 9],
        "enemy_unit_ids": [2],
        "actor_ids": [6, 7, 4],
        "eligible_actor_count": 4,
        "actors_truncated": True,
        "options": self.multi_actor_options,
      },
      revision=42,
      decision_id="dec-issued",
    )
    brief = sd.render_decision_brief(packet)
    self.assertIn("Actor 6:", brief)
    self.assertIn("Actor 7:", brief)
    self.assertIn("Actor 4:", brief)
    self.assertIn("still exposed after this option", brief)
    self.assertIn("attackers=2", brief)
    self.assertIn("Exposure after this option (estimates from the issuing state, not a joint-plan forecast): attackers=0", brief)
    self.assertIn("Exposure after this option: unknown", brief)
    self.assertIn("actors_truncated=true", brief)
    self.assertIn("eligible_actor_count=4", brief)
    self.assertIn(
      '{"kind":"choose","decision_id":"dec-issued","option_ids":["u6-relocate-2","u7-relocate-1"],"finish_turn":false}',
      brief,
    )

  def test_map_batch_failure_to_option(self):
    options = self.multi_actor_options
    concatenated = (
      options[0]["actions"]
      + options[1]["actions"]
      + [{"action": "FinishWithGreedy", "groups": [], "holds": []}]
    )
    self.assertEqual(
      sd.map_batch_failure_to_option(options, concatenated, 0),
      {"option_id": "u6-relocate-2", "actor_id": 6},
    )
    self.assertEqual(
      sd.map_batch_failure_to_option(options, concatenated, 1),
      {"option_id": "u7-relocate-1", "actor_id": 7},
    )
    self.assertIsNone(sd.map_batch_failure_to_option(options, concatenated, 2))
    two_action = [
      {
        "option_id": "u1-attack-1",
        "actor_id": 1,
        "actions": [
          {"action": "Move", "unit_id": 1, "col": 4, "row": 3},
          {"action": "Attack", "attacker_id": 1, "defender_id": 5},
        ],
      },
      {
        "option_id": "u2-relocate-1",
        "actor_id": 2,
        "actions": [{"action": "Move", "unit_id": 2, "col": 1, "row": 1}],
      },
    ]
    concat = two_action[0]["actions"] + two_action[1]["actions"]
    self.assertEqual(
      sd.map_batch_failure_to_option(two_action, concat, 1),
      {"option_id": "u1-attack-1", "actor_id": 1},
    )
    self.assertEqual(
      sd.map_batch_failure_to_option(two_action, concat, 2),
      {"option_id": "u2-relocate-1", "actor_id": 2},
    )


if __name__ == "__main__":
  unittest.main()
