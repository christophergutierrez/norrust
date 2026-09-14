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


if __name__ == "__main__":
  unittest.main()
