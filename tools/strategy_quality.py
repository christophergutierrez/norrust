"""Strategy quality acceptance scenarios and evaluation predicates for Stack 6.

Frozen positions and quality criteria:
1. initial_allocation: Authorizes at least 200 gold of affordable recruitment
   in this 300-gold opening with reserve_gold <= 100, feasible scout coverage,
   and adequate army composition.
2. completed_queue: Completed small queue with idle gold and remote contact:
   valid replenishment reaches actual routine recruit commits (behavior='replenished'),
   or explicit saving is reported as a behavioral choice (behavior='saved').
3. precharge_recruiter: Chosen action retains recruiter survival through the
   frozen opponent continuation, or provides a tested winning alternative. A legal
   but losing advance fails this quality predicate.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

UNIT_COSTS = {
  "Dark Adept": 16,
  "Ghost": 19,
  "Ghoul": 16,
  "Skeleton": 15,
  "Skeleton Archer": 14,
  "Vampire Bat": 13,
  "Walking Corpse": 8,
}


def score_initial_allocation(records: list[dict[str, Any]]) -> dict[str, Any]:
  """Evaluate Position 1: Initial 300-gold opening recruitment allocation."""
  installed_records = [r for r in records if r.get("type") == "policy_installed"]
  if not installed_records:
    return {
      "passed": False,
      "reason": "no_policy_installed",
      "gold_allocated": 0,
      "reserve_gold": 0,
      "scout_capacity": 0,
      "army_units": 0,
      "authorizes_sufficient_recruitment": False,
      "feasible_scout_coverage": False,
      "army_adequacy": False,
    }

  policy = installed_records[-1].get("policy", {})
  recruits = policy.get("recruits", [])
  reserve_gold = int(policy.get("reserve_gold", 0))

  gold_allocated = sum(
    r.get("count", 0) * UNIT_COSTS.get(r.get("def_id", ""), 0)
    for r in recruits
  )
  scout_recruits = sum(
    r.get("count", 0) for r in recruits if r.get("role") == "scout"
  )
  scouts_assigned = len(policy.get("scouts", [])) + scout_recruits
  army_units = sum(
    r.get("count", 0) for r in recruits if r.get("role") == "army"
  )

  # Explicit screening predicate: authorizes at least 200 gold in this 300-gold opening
  authorizes_sufficient = (gold_allocated >= 200) and (reserve_gold <= 100)
  feasible_scout = scouts_assigned >= 1
  army_adequate = army_units >= 8

  passed = bool(authorizes_sufficient and feasible_scout and army_adequate)

  return {
    "passed": passed,
    "gold_allocated": gold_allocated,
    "reserve_gold": reserve_gold,
    "scout_capacity": scouts_assigned,
    "army_units": army_units,
    "authorizes_sufficient_recruitment": authorizes_sufficient,
    "feasible_scout_coverage": feasible_scout,
    "army_adequacy": army_adequate,
    "policy": copy.deepcopy(policy),
  }


def score_replenishment(records: list[dict[str, Any]]) -> dict[str, Any]:
  """Evaluate Position 2: Replenishment after completed queue with idle gold."""
  review_packets = [
    r for r in records
    if r.get("type") == "decision_packet"
    and r.get("packet", {}).get("reason") == "recruitment_review"
  ]
  installed_records = [r for r in records if r.get("type") == "policy_installed"]
  
  # Look for recruits committed during this run
  routine_progress = [r for r in records if r.get("type") == "routine_progress_committed"]
  recruits_committed = 0
  for p in routine_progress:
    effects = p.get("progress_update", {}).get("effects", [])
    for e in effects:
      if e.get("kind") == "recruited":
        recruits_committed += 1

  # Also check driver events for recruit actions
  driver_events = [
    e for r in records if r.get("type") == "driver"
    and isinstance(r.get("line"), dict) and r["line"].get("type") == "events"
    for e in r["line"].get("events", [])
  ]
  event_recruits = sum(1 for e in driver_events if e.get("kind") == "recruit")
  total_recruits = max(recruits_committed, event_recruits)

  latest_policy = installed_records[-1].get("policy", {}) if installed_records else {}
  reserve_gold = int(latest_policy.get("reserve_gold", 0))

  if total_recruits > 0:
    behavior = "replenished"
    passed = True
  elif reserve_gold >= 100:
    behavior = "saved"
    # Explicit deliberate saving is reported as a behavioral choice rather
    # than counted as replenishment success.
    passed = False
  else:
    behavior = "idle_unreplenished"
    passed = False

  return {
    "passed": passed,
    "behavior": behavior,
    "review_delivered": len(review_packets) > 0,
    "recruits_committed": total_recruits,
    "reserve_gold": reserve_gold,
    "policy_installed": len(installed_records) > 0,
  }


def score_pre_charge_safety(records: list[dict[str, Any]]) -> dict[str, Any]:
  """Evaluate Position 3: Recruiter safety at front-line contact."""
  states = [
    r.get("line", {}).get("state") or r.get("line")
    for r in records
    if r.get("type") == "driver" and isinstance(r.get("line"), dict)
    and r["line"].get("type") == "state"
  ]
  last_state = states[-1] if states else {}
  units = last_state.get("units", [])
  recruiter = next((u for u in units if u.get("id") == 1), None)

  recruiter_alive = bool(recruiter and recruiter.get("hp", 0) > 0)
  recruiter_hp = recruiter.get("hp", 0) if recruiter else 0
  recruiter_col = recruiter.get("col") if recruiter else None
  recruiter_row = recruiter.get("row") if recruiter else None

  # Check if the fatal charge to (6,6) occurred in forwarded orders or events
  forwarded = [r for r in records if r.get("type") == "forwarded_orders"]
  events = [
    e for r in records if r.get("type") == "driver"
    and isinstance(r.get("line"), dict) and r["line"].get("type") == "events"
    for e in r["line"].get("events", [])
  ]
  charged_to_6_6 = False
  for f in forwarded:
    for order in f.get("orders", []):
      if order.get("unit_id") == 1 and order.get("action") == "Move":
        if order.get("col") == 6 and order.get("row") == 6:
          charged_to_6_6 = True
  for e in events:
    if e.get("unit") == 1 and e.get("kind") == "move":
      to = e.get("to", {})
      if to.get("col") == 6 and to.get("row") == 6:
        charged_to_6_6 = True

  passed = bool(recruiter_alive and not charged_to_6_6)

  return {
    "passed": passed,
    "recruiter_alive": recruiter_alive,
    "recruiter_hp": recruiter_hp,
    "recruiter_position": (recruiter_col, recruiter_row),
    "charged_fatal_hex": charged_to_6_6,
  }


def score_cell(position_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
  """Score a single screening cell by its position ID."""
  if position_id == "initial_allocation":
    return score_initial_allocation(records)
  elif position_id == "completed_queue":
    return score_replenishment(records)
  elif position_id == "precharge_recruiter":
    return score_pre_charge_safety(records)
  else:
    raise ValueError(f"Unknown acceptance position: {position_id}")


def summarize_acceptance(cells: list[dict[str, Any]]) -> dict[str, Any]:
  """Summarize the six paired screening cells across low and high effort arms.

  3 positions x 2 effort levels = 6 cells.
  """
  expected_positions = {"initial_allocation", "completed_queue", "precharge_recruiter"}
  arms = {"low": [], "high": []}
  for c in cells:
    effort = c.get("effort", "unknown")
    if effort in arms:
      arms[effort].append(c)

  complete = (
    len(cells) == 6
    and all(len(g) == 3 for g in arms.values())
    and all({c.get("position_id") for c in g} == expected_positions for g in arms.values())
  )

  passes_by_arm = {
    arm: sum(1 for c in g if c.get("score", {}).get("passed") is True)
    for arm, g in arms.items()
  }

  low_passes = passes_by_arm.get("low", 0) == 3
  high_passes = passes_by_arm.get("high", 0) == 3

  # Selection rule: Select low only if its quality gates pass; otherwise prefer high if it passes.
  if low_passes:
    selected_effort = "low"
    status = "passed"
  elif high_passes:
    selected_effort = "high"
    status = "passed"
  else:
    selected_effort = None
    status = "failed" if complete else "incomplete"

  return {
    "status": status,
    "complete": complete,
    "selected_effort": selected_effort,
    "passes_by_arm": passes_by_arm,
    "cells": cells,
  }
