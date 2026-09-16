"""Tests for Stack 4: Recruiter attack danger beyond immediate exchange."""
from __future__ import annotations

import copy
import json
import unittest

from . import strategy_decision as sd


class TestStrategyStack4(unittest.TestCase):
  def setUp(self):
    self.recruiter_id = 1
    self.recruiter_unit = {
      "id": self.recruiter_id,
      "faction": 0,
      "def_id": "Dark Sorcerer",
      "hp": 48,
      "max_hp": 48,
      "can_recruit": True,
      "abilities": ["Leader"],
    }
    self.regular_unit = {
      "id": 5,
      "faction": 0,
      "def_id": "Skeleton",
      "hp": 30,
      "max_hp": 30,
      "can_recruit": False,
    }

  def test_forecast_labels_immediate_exchange_and_loss_chance(self):
    """Combat forecast is explicitly labeled for immediate exchange only."""
    opt = {
      "option_id": "u1-attack-1",
      "actor_id": self.recruiter_id,
      "category": "attack",
      "actions": [
        {"action": "Move", "unit_id": 1, "col": 6, "row": 6},
        {"action": "Attack", "attacker_id": 1, "defender_id": 10},
      ],
      "forecast": {
        "expected_damage_dealt_tenths": 180,
        "expected_damage_received_tenths": 40,
        "kill_chance_bps": 7500,
        "outcome_bps": [7500, 2500, 0],
      },
      "exposure": {
        "distinct_attacker_count": 4,
        "max_incoming_damage": 52,
        "expected_incoming_damage_tenths": 140,
      },
      "movement_cost": 3,
    }
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [10],
        "actor_ids": [1],
        "eligible_actor_count": 1,
        "options": [opt],
      },
      revision=10,
    )
    state = {
      "units": [self.recruiter_unit],
    }
    brief = sd.render_decision_brief(packet, state=state)

    # 1. Forecast is explicitly labeled as immediate exchange only
    self.assertIn("Forecast: immediate exchange only (not enemy next-turn survival);", brief)
    self.assertIn("expected damage dealt=18.0", brief)
    self.assertIn("immediate exchange attacker loss chance=0.0%", brief)

    # 2. High stakes recruiter danger is visibly highlighted beside the option
    self.assertIn("HIGH STAKES RECRUITER DANGER: Recruiter (HP 48/48) exposed to enemy next turn", brief)
    self.assertIn("still exposed after this option", brief)
    self.assertIn("attackers=4", brief)
    self.assertIn("max incoming damage=52", brief)
    self.assertIn("expected incoming damage=14.0", brief)

  def test_safe_recruiter_option_has_no_high_stakes_danger(self):
    """A recruiter option with 0 projected attackers does not trigger high stakes danger."""
    opt = {
      "option_id": "u1-relocate-1",
      "actor_id": self.recruiter_id,
      "category": "relocation",
      "actions": [{"action": "Move", "unit_id": 1, "col": 2, "row": 7}],
      "movement_cost": 1,
      "exposure": {
        "distinct_attacker_count": 0,
        "max_incoming_damage": 0,
        "expected_incoming_damage_tenths": 0,
      },
    }
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [10],
        "actor_ids": [1],
        "eligible_actor_count": 1,
        "options": [opt],
      },
      revision=10,
    )
    state = {"units": [self.recruiter_unit]}
    brief = sd.render_decision_brief(packet, state=state)
    self.assertNotIn("HIGH STAKES RECRUITER DANGER", brief)
    self.assertNotIn("still exposed after this option", brief)
    self.assertIn("Exposure after this option", brief)
    self.assertIn("attackers=0", brief)

  def test_non_recruiter_exposed_option_does_not_claim_recruiter_danger(self):
    """An exposed non-recruiter unit option does not display recruiter danger."""
    opt = {
      "option_id": "u5-attack-1",
      "actor_id": 5,
      "category": "attack",
      "actions": [{"action": "Attack", "attacker_id": 5, "defender_id": 10}],
      "forecast": {
        "expected_damage_dealt_tenths": 100,
        "expected_damage_received_tenths": 50,
        "kill_chance_bps": 5000,
        "outcome_bps": [5000, 3000, 2000],
      },
      "exposure": {
        "distinct_attacker_count": 2,
        "max_incoming_damage": 20,
        "expected_incoming_damage_tenths": 120,
      },
    }
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [5],
        "enemy_unit_ids": [10],
        "actor_ids": [5],
        "eligible_actor_count": 1,
        "options": [opt],
      },
      revision=10,
    )
    state = {"units": [self.regular_unit]}
    brief = sd.render_decision_brief(packet, state=state)
    self.assertNotIn("HIGH STAKES RECRUITER DANGER", brief)
    self.assertIn("still exposed after this option", brief)

  def test_finish_decision_prominently_summarizes_recruiter_exposure(self):
    """When final_only is true, any proven recruiter exposure is prominently summarized."""
    packet = sd.build_decision_packet(
      "contact",
      {
        "stage": "current_state",
        "trigger": "attack",
        "friendly_unit_ids": [1],
        "enemy_unit_ids": [10],
        "projected_threats": {
          "recruiters": [
            {
              "recruiter_id": 1,
              "distinct_attacker_count": 3,
              "attackers": [10, 11, 12],
            }
          ]
        },
      },
      revision=10,
      final_only=True,
    )
    state = {"units": [self.recruiter_unit]}
    brief = sd.render_decision_brief(packet, state=state)
    self.assertIn("RECRUITER EXPOSURE SUMMARY: Recruiter 1 is exposed to enemy attacks on next turn (3 projected attackers).", brief)
    self.assertIn("This is informational; finish_turn leaves the unit in place.", brief)


if __name__ == "__main__":
  unittest.main()
