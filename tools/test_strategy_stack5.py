"""Tests for Stack 5: Honest tactical option dependencies and valid choose examples."""
from __future__ import annotations

import json
import unittest

from . import llm_client as lc
from . import strategy_decision as sd


class TestStrategyStack5(unittest.TestCase):
  def setUp(self):
    self.actor1_opts = [
      {
        "option_id": "u1-move-a",
        "actor_id": 1,
        "category": "relocation",
        "actions": [{"action": "Move", "unit_id": 1, "col": 4, "row": 5}],
      },
      {
        "option_id": "u1-move-b",
        "actor_id": 1,
        "category": "relocation",
        "actions": [{"action": "Move", "unit_id": 1, "col": 4, "row": 6}],
      },
    ]
    self.actor2_opts = [
      {
        "option_id": "u2-move-a",
        "actor_id": 2,
        "category": "relocation",
        "actions": [{"action": "Move", "unit_id": 2, "col": 7, "row": 8}],
      },
    ]

  def test_single_actor_options_produce_single_option_example(self):
    """When only one actor has options, the example must select at most one option."""
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [10],
        "actor_ids": [1],
        "options": self.actor1_opts,
      },
      revision=1,
      decision_id="dec-1",
    )
    example = sd._build_choose_example(packet)
    self.assertIsNotNone(example)
    self.assertEqual(example["kind"], "choose")
    self.assertEqual(example["decision_id"], "dec-1")
    # Must only contain 1 option (not both u1-move-a and u1-move-b)
    self.assertEqual(example["option_ids"], ["u1-move-a"])
    self.assertFalse(example["finish_turn"])

    # Ensure this example passes validate_response_context validation
    sd.validate_response_context(example, packet)

  def test_multiple_actors_compatible_options_produce_one_per_actor(self):
    """When two actors have compatible options, example selects one per actor."""
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1, 2],
        "enemy_unit_ids": [10],
        "actor_ids": [1, 2],
        "options": self.actor1_opts + self.actor2_opts,
      },
      revision=1,
      decision_id="dec-2",
    )
    example = sd._build_choose_example(packet)
    self.assertIsNotNone(example)
    self.assertEqual(example["option_ids"], ["u1-move-a", "u2-move-a"])

    sd.validate_response_context(example, packet)

  def test_conflicting_destinations_fallback_to_single_option(self):
    """When actors' options share destinations, example falls back to single option."""
    actor2_conflicting = [
      {
        "option_id": "u2-move-conflict",
        "actor_id": 2,
        "category": "relocation",
        "actions": [{"action": "Move", "unit_id": 2, "col": 4, "row": 5}],
      },
    ]
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1, 2],
        "enemy_unit_ids": [10],
        "actor_ids": [1, 2],
        "options": [self.actor1_opts[0], actor2_conflicting[0]],
      },
      revision=1,
      decision_id="dec-3",
    )
    example = sd._build_choose_example(packet)
    self.assertIsNotNone(example)
    # Both share (4, 5), so fallback to single option
    self.assertEqual(example["option_ids"], ["u1-move-a"])

  def test_choose_example_omitted_when_choose_unavailable(self):
    """When choose is not an allowed kind, no example is generated."""
    packet = sd.build_decision_packet(
      "initial_policy",
      {},
      revision=0,
      decision_id="dec-init",
    )
    self.assertNotIn("choose", packet.allowed_kinds)
    example = sd._build_choose_example(packet)
    self.assertIsNone(example)

    brief = sd.render_decision_brief(packet)
    self.assertNotIn("To choose, respond with:", brief)

  def test_final_only_choose_example_sets_finish_turn(self):
    """Final-only decision packet produces choose example with finish_turn=true."""
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [10],
        "actor_ids": [1],
        "options": self.actor1_opts,
      },
      revision=1,
      final_only=True,
      decision_id="dec-fin",
    )
    example = sd._build_choose_example(packet)
    self.assertIsNotNone(example)
    self.assertTrue(example["finish_turn"])

    sd.validate_response_context(example, packet)

  def test_option_compatibility_notes_shared_destination_and_target(self):
    """Detect shared destination and target across distinct actors."""
    options = [
      {
        "option_id": "opt-1",
        "actor_id": 1,
        "category": "attack",
        "actions": [
          {"action": "Move", "unit_id": 1, "col": 3, "row": 4},
          {"action": "Attack", "attacker_id": 1, "defender_id": 99},
        ],
      },
      {
        "option_id": "opt-2",
        "actor_id": 2,
        "category": "attack",
        "actions": [
          {"action": "Move", "unit_id": 2, "col": 3, "row": 4},
          {"action": "Attack", "attacker_id": 2, "defender_id": 99},
        ],
      },
      {
        "option_id": "opt-3",
        "actor_id": 3,
        "category": "relocation",
        "actions": [
          {"action": "Move", "unit_id": 3, "col": 8, "row": 8},
        ],
      },
    ]
    notes = sd._format_option_compatibility_notes(options)
    self.assertEqual(len(notes), 2)
    self.assertIn("Shared destination (3,4) across Actor 1, Actor 2", notes[0])
    self.assertIn("two units cannot occupy the same hex at end of turn", notes[0])
    self.assertIn("Shared target U99 across Actor 1, Actor 2", notes[1])
    self.assertIn("multi-attack is supported if target survives", notes[1])

    # In brief
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1, 2, 3],
        "enemy_unit_ids": [99],
        "actor_ids": [1, 2, 3],
        "options": options,
      },
      revision=2,
      decision_id="dec-compat",
    )
    brief = sd.render_decision_brief(packet)
    self.assertIn("Option compatibility notes:", brief)
    self.assertIn("Shared destination (3,4) across Actor 1, Actor 2", brief)
    self.assertIn("Shared target U99 across Actor 1, Actor 2", brief)

  def test_concise_engine_rejection_reports_dead_target_kill_and_absence(self):
    """Concise rejection includes target simulated kill and absence diagnostics."""
    orders = [
      {"action": "Attack", "attacker_id": 1, "defender_id": 5},
      {"action": "Attack", "attacker_id": 2, "defender_id": 5},
    ]
    # Simulated kill
    kill_validation = {
      "valid": False, "committed": False, "replay": "read_only_atomic",
      "failed_index": 1,
      "results": [
        {"ok": True},
        {
          "ok": False,
          "code": "UnitNotFound",
          "message": "target U5 was killed by earlier proposed action index 0 (zero-based); batch replay is sequential",
          "target": {
            "unit_id": 5,
            "role": "target",
            "cause": "earlier_simulated_kill",
            "earlier_action_index": 0,
            "originally_present": True,
          },
        },
      ],
    }
    kill_line = lc.concise_engine_rejection(orders, kill_validation)
    self.assertIn("index=1 action=Attack", kill_line)
    self.assertIn("target=U5", kill_line)
    self.assertIn("cause=earlier proposed action index=0 (zero-based) simulated kill; replay is sequential", kill_line)
    self.assertIn("error=UnitNotFound", kill_line)

    # Original state missing
    absent_orders = [
      {"action": "Attack", "attacker_id": 1, "defender_id": 999},
    ]
    absent_validation = {
      "valid": False, "committed": False, "replay": "read_only_atomic",
      "failed_index": 0,
      "results": [
        {
          "ok": False,
          "code": "UnitNotFound",
          "message": "target U999 was not found in the original live state",
          "target": {
            "unit_id": 999,
            "role": "target",
            "cause": "original_live_state_missing",
            "originally_present": False,
          },
        },
      ],
    }
    absent_line = lc.concise_engine_rejection(absent_orders, absent_validation)
    self.assertIn("index=0 action=Attack", absent_line)
    self.assertIn("target=U999", absent_line)
    self.assertIn("cause=original live state missing", absent_line)
    self.assertIn("error=UnitNotFound", absent_line)

  def test_delivered_briefs_choose_examples_and_driver_validation(self):
    """Extract examples from delivered prompts and validate shape and driver compatibility."""
    import re

    # 1. Contact prompt with 2 actors: extract and validate
    contact_packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1, 2],
        "enemy_unit_ids": [10],
        "actor_ids": [1, 2],
        "options": self.actor1_opts + self.actor2_opts,
      },
      revision=4,
      decision_id="dec-multi",
    )
    brief = sd.render_decision_brief(contact_packet)
    m = re.search(r"To choose, respond with: (\{.*?\})(?:\n|$)", brief)
    self.assertIsNotNone(m, "choose example must be present in brief")
    example_json = json.loads(m.group(1))
    self.assertEqual(example_json["kind"], "choose")
    self.assertEqual(example_json["decision_id"], "dec-multi")
    self.assertEqual(example_json["option_ids"], ["u1-move-a", "u2-move-a"])
    self.assertFalse(example_json["finish_turn"])
    sd.validate_response_context(example_json, contact_packet)

    # 2. Final-only prompt: extract and validate
    fin_packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [10],
        "actor_ids": [1],
        "options": self.actor1_opts,
      },
      revision=4,
      final_only=True,
      decision_id="dec-fin",
    )
    fin_brief = sd.render_decision_brief(fin_packet)
    m = re.search(r"To choose, respond with: (\{.*?\})(?:\n|$)", fin_brief)
    self.assertIsNotNone(m)
    fin_example = json.loads(m.group(1))
    self.assertTrue(fin_example["finish_turn"])
    sd.validate_response_context(fin_example, fin_packet)

    # 3. Initial policy prompt: choose example must be omitted
    init_packet = sd.build_decision_packet(
      "initial_policy",
      {},
      revision=0,
      decision_id="dec-init",
    )
    init_brief = sd.render_decision_brief(init_packet)
    self.assertNotIn("To choose, respond with:", init_brief)


if __name__ == "__main__":
  unittest.main()

