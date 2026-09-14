"""Decision packet routing, incident tracking, contextual validation, and briefs.

This module implements the decision routing and contextual validation layer for
strategy-mode play (Stack 1 of docs/plans/strategy-decision-boundaries.md).
It is self-contained and transport-neutral. tools/llm_client.py owns dispatch,
durable logging, and execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

try:
  from .routine_policy import (
    ModelResponseError,
    RoutineException,
    strategy_context,
    _strategy_contract,
    SetPolicyResponse,
    ActResponse,
    FinishTurnResponse,
    ResignResponse,
  )
except ImportError:
  from tools.routine_policy import (
    ModelResponseError,
    RoutineException,
    strategy_context,
    _strategy_contract,
    SetPolicyResponse,
    ActResponse,
    FinishTurnResponse,
    ResignResponse,
  )

# Canonical decision kinds
DECISION_KIND_TACTICAL = "tactical"
DECISION_KIND_POLICY = "policy"
DECISION_KIND_PROMOTION = "promotion"
DECISION_KIND_FACTS_UNAVAILABLE = "facts_unavailable"

# Closed set of allowable responses
ALLOWED_ALL = ["set_policy", "act", "finish_turn", "resign"]
ALLOWED_TACTICAL = ["act", "finish_turn", "resign"]
ALLOWED_PROMOTION = ["act", "resign"]


class ContextualResponseError(ModelResponseError):
  """A model response violated the decision context rules (e.g. set_policy on contact)."""


@dataclass(frozen=True)
class DecisionPacket:
  """Durable decision packet issued to the model."""

  decision_id: str
  state_revision: int
  decision_kind: str
  incident_key: str
  reason: str
  evidence: dict[str, Any]
  allowed_kinds: list[str]
  options: list[dict[str, Any]]
  coverage: dict[str, str]

  def to_dict(self) -> dict[str, Any]:
    return {
      "decision_id": self.decision_id,
      "state_revision": self.state_revision,
      "decision_kind": self.decision_kind,
      "incident_key": self.incident_key,
      "reason": self.reason,
      "evidence": copy.deepcopy(self.evidence),
      "allowed_kinds": list(self.allowed_kinds),
      "options": copy.deepcopy(self.options),
      "coverage": copy.deepcopy(self.coverage),
    }

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> DecisionPacket:
    return cls(
      decision_id=str(data["decision_id"]),
      state_revision=int(data["state_revision"]),
      decision_kind=str(data["decision_kind"]),
      incident_key=str(data["incident_key"]),
      reason=str(data["reason"]),
      evidence=copy.deepcopy(data.get("evidence", {})),
      allowed_kinds=list(data.get("allowed_kinds", [])),
      options=copy.deepcopy(data.get("options", [])),
      coverage=copy.deepcopy(data.get("coverage", {})),
    )


def compute_incident_key(
  game_id: str | int,
  side_turn: int,
  reason: str,
  evidence: dict[str, Any],
) -> str:
  """Compute a canonical incident key hash.

  incident_key excludes policy/install IDs, request IDs, remaining budgets,
  prose, and option ordering. It canonicalizes reason, stage/cause, and the
  affected unit/target/destination IDs or coordinates.
  Current-state contact identifies the sorted involved units/targets, not a rally point.
  Includes the game and controlled side-turn identity when tracking a repeated incident.
  """
  canonical: dict[str, Any] = {
    "game_id": str(game_id),
    "side_turn": int(side_turn),
    "reason": str(reason),
  }

  if reason == "contact":
    stage = str(evidence.get("stage", ""))
    canonical["stage"] = stage
    if stage == "current_state":
      canonical["friendly_unit_ids"] = sorted(int(x) for x in evidence.get("friendly_unit_ids", []))
      canonical["enemy_unit_ids"] = sorted(int(x) for x in evidence.get("enemy_unit_ids", []))
      if "trigger" in evidence:
        canonical["trigger"] = str(evidence["trigger"])
    else:
      # proposed movement contact
      if "unit_id" in evidence:
        canonical["unit_id"] = int(evidence["unit_id"])
      dest = evidence.get("destination")
      if isinstance(dest, dict):
        canonical["destination"] = (dest.get("col"), dest.get("row"))
      elif isinstance(dest, (list, tuple)):
        canonical["destination"] = tuple(dest)
  elif reason == "promotion_pending":
    canonical["unit_ids"] = sorted(int(x) for x in evidence.get("unit_ids", []))
  elif reason in ("unsafe_route", "route_unavailable", "invalid_assignment", "no_executable_orders"):
    if "cause" in evidence:
      canonical["cause"] = str(evidence["cause"])
    if "unit_id" in evidence:
      canonical["unit_id"] = int(evidence["unit_id"])
    village = evidence.get("village")
    if isinstance(village, dict):
      canonical["village"] = (village.get("col"), village.get("row"))
    elif isinstance(village, (list, tuple)):
      canonical["village"] = tuple(village)
    villages = evidence.get("villages")
    if isinstance(villages, list):
      norm_villages = []
      for v in villages:
        if isinstance(v, dict):
          norm_villages.append((v.get("col"), v.get("row")))
        elif isinstance(v, (list, tuple)):
          norm_villages.append(tuple(v))
      canonical["villages"] = sorted(norm_villages)
    target = evidence.get("target")
    if isinstance(target, dict):
      canonical["target"] = (target.get("col"), target.get("row"))
    elif isinstance(target, (list, tuple)):
      canonical["target"] = tuple(target)
  elif reason == "threat_unavailable":
    canonical["stage"] = str(evidence.get("stage", ""))
  elif reason in ("initial", "objectives_complete"):
    if "policy_complete" in evidence:
      canonical["policy_complete"] = bool(evidence["policy_complete"])
  else:
    # Generic primitives
    for k in sorted(evidence):
      if k not in ("detail", "message", "prose", "request_id", "policy_id", "installation_id"):
        v = evidence[k]
        if isinstance(v, (int, str, bool)):
          canonical[k] = v

  raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_decision_packet(
  reason: str,
  evidence: dict[str, Any],
  revision: int,
  *,
  game_id: str | int = "",
  side_turn: int = 0,
  final_only: bool = False,
  allowed_kinds_override: Optional[list[str]] = None,
  decision_id: Optional[str] = None,
) -> DecisionPacket:
  """Build a structured DecisionPacket for the given reason and evidence."""
  did = decision_id or f"dec-{uuid.uuid4().hex[:12]}"
  rev = int(revision)

  # Route decision_kind
  if reason in ("initial", "objectives_complete"):
    decision_kind = DECISION_KIND_POLICY
  elif reason == "contact":
    if evidence.get("stage") == "current_state":
      decision_kind = DECISION_KIND_TACTICAL
    else:
      decision_kind = DECISION_KIND_POLICY
  elif reason == "promotion_pending":
    decision_kind = DECISION_KIND_PROMOTION
  elif reason == "threat_unavailable":
    decision_kind = DECISION_KIND_FACTS_UNAVAILABLE
  elif reason in ("route_unavailable", "unsafe_route", "invalid_assignment",
                  "recruitment_blocked", "no_executable_orders"):
    decision_kind = DECISION_KIND_POLICY
  else:
    decision_kind = DECISION_KIND_POLICY

  # Determine allowed_kinds
  if allowed_kinds_override is not None:
    allowed = list(allowed_kinds_override)
  elif decision_kind == DECISION_KIND_TACTICAL:
    allowed = list(ALLOWED_TACTICAL)
  elif decision_kind == DECISION_KIND_PROMOTION:
    allowed = list(ALLOWED_PROMOTION)
  elif decision_kind == DECISION_KIND_FACTS_UNAVAILABLE:
    allowed = list(ALLOWED_TACTICAL)
  else:
    allowed = list(ALLOWED_ALL)

  incident_key = compute_incident_key(game_id, side_turn, reason, evidence)

  if reason == "threat_unavailable":
    coverage = {"facts": "unavailable", "options": "not_generated"}
  else:
    coverage = {"facts": "complete", "options": "not_generated"}

  return DecisionPacket(
    decision_id=did,
    state_revision=rev,
    decision_kind=decision_kind,
    incident_key=incident_key,
    reason=reason,
    evidence=copy.deepcopy(evidence),
    allowed_kinds=allowed,
    options=[],
    coverage=coverage,
  )


def validate_response_context(response: Any, packet: DecisionPacket) -> None:
  """Validate that the parsed model response is permitted for the active decision packet."""
  if isinstance(response, SetPolicyResponse):
    kind = "set_policy"
  elif isinstance(response, ActResponse):
    kind = "act"
  elif isinstance(response, FinishTurnResponse):
    kind = "finish_turn"
  elif isinstance(response, ResignResponse):
    kind = "resign"
  elif isinstance(response, dict):
    kind = response.get("kind")
  else:
    kind = getattr(response, "kind", None)

  if not kind:
    raise ContextualResponseError("model response is missing 'kind'")
  if kind not in packet.allowed_kinds:
    raise ContextualResponseError(
      f"Response kind {kind!r} is not allowed for {packet.reason} ({packet.decision_kind}). "
      f"Applicable responses: {', '.join(packet.allowed_kinds)}."
    )


class IncidentTracker:
  """Tracks incidents and bounds ineffective responses per revision and incident."""

  def __init__(self) -> None:
    # revision -> set of incident_key encountered at that revision
    self.encountered_by_revision: dict[int, set[str]] = {}
    # (side_turn, revision, incident_key) -> count of ineffective responses
    self.ineffective_counts: dict[tuple[int, int, str], int] = {}
    # (side_turn, revision, incident_key) -> count of total encounters
    self.encounter_counts: dict[tuple[int, int, str], int] = {}

  def observe_incident(self, side_turn: int, revision: int, incident_key: str) -> bool:
    """Record encountering an incident at (side_turn, revision).

    Returns True if this is the first time this incident_key has been
    encountered at this revision, False if it was encountered before (e.g. A->B->A).
    """
    key = (side_turn, revision, incident_key)
    self.encounter_counts[key] = self.encounter_counts.get(key, 0) + 1
    if revision not in self.encountered_by_revision:
      self.encountered_by_revision[revision] = set()
    is_first = incident_key not in self.encountered_by_revision[revision]
    self.encountered_by_revision[revision].add(incident_key)
    return is_first

  def has_encountered_at_revision(self, revision: int, incident_key: str) -> bool:
    """Return True if this incident_key was previously encountered at this revision."""
    return incident_key in self.encountered_by_revision.get(revision, set())

  def record_ineffective(self, side_turn: int, revision: int, incident_key: str) -> int:
    """Record an ineffective response (contextual rejection or reproduced incident).

    Returns the new count of ineffective responses for this incident at this revision.
    """
    key = (side_turn, revision, incident_key)
    self.ineffective_counts[key] = self.ineffective_counts.get(key, 0) + 1
    return self.ineffective_counts[key]

  def can_attempt_correction(self, side_turn: int, revision: int, incident_key: str) -> bool:
    """Check if at most one corrective follow-up has been consumed.

    At a fixed side-turn, revision, and incident, permit at most one corrective follow-up.
    Count == 1 allows the 1 correction. Count > 1 exceeds the allowance.
    """
    key = (side_turn, revision, incident_key)
    return self.ineffective_counts.get(key, 0) <= 1

  def reconstruct_from_journal(self, rows: list[dict[str, Any]]) -> None:
    """Reconstruct consumed allowances and encountered incidents from journal records."""
    current_side_turn = 0
    pending_incidents: list[tuple[int, int, str]] = []

    for row in rows:
      rtype = row.get("type")
      if rtype == "driver":
        line = row.get("line", {})
        if line.get("type") == "state":
          s = line.get("state", {})
          current_side_turn = s.get("turn", current_side_turn)
      elif rtype == "decision_packet":
        packet = row.get("packet", {})
        rev = packet.get("state_revision", 0)
        ikey = packet.get("incident_key", "")
        st = row.get("side_turn", current_side_turn)
        if ikey:
          pending_incidents.append((st, rev, ikey))
      elif rtype == "policy_installed":
        for st, rev, ikey in pending_incidents:
          self.observe_incident(st, rev, ikey)
        pending_incidents.clear()
      elif rtype in ("contextual_rejection", "incident_recurrence"):
        rev = row.get("state_revision", 0)
        ikey = row.get("incident_key", "")
        st = row.get("side_turn", current_side_turn)
        if ikey:
          self.record_ineffective(st, rev, ikey)
          self.observe_incident(st, rev, ikey)


def render_decision_brief(
  packet: DecisionPacket,
  *,
  state: Optional[dict[str, Any]] = None,
  recruit_options: Any = None,
  changes: Any = None,
  policy: Any = None,
  remaining: Any = None,
  recruitable_defs: Any = (),
) -> str:
  """Render a decision-specific brief with applicable responses."""
  sections: list[str] = [_strategy_contract(recruitable_defs)]

  # Specific Guidance
  if packet.decision_kind == DECISION_KIND_TACTICAL:
    sections.append(
      "TACTICAL DECISION REQUIRED: Enemy contact exists on the current board. Changing policy "
      "moves no units and cannot clear the current-board pause. You must submit tactical action "
      f"orders (`act`), `finish_turn`, or `resign`. Applicable responses: {', '.join(packet.allowed_kinds)}."
    )
    if packet.evidence:
      trigger = packet.evidence.get("trigger", "unspecified")
      friendly = packet.evidence.get("friendly_unit_ids", [])
      enemy = packet.evidence.get("enemy_unit_ids", [])
      sections.append(
        f"Contact facts: trigger={trigger}, friendly_units={friendly}, enemy_units={enemy}"
      )
  elif packet.reason in ("unsafe_route", "route_unavailable"):
    sections.append(
      "ROUTE / OBJECTIVE DECISION REQUIRED: A proposed routine movement encounters an obstacle, "
      "enemy contact, or danger. Replacing the policy objective (`set_policy`) can prevent this "
      f"proposed step. Applicable responses: {', '.join(packet.allowed_kinds)}."
    )
  elif packet.decision_kind == DECISION_KIND_PROMOTION:
    sections.append(
      "PROMOTION REQUIRED: A unit advancement is pending. Submit `act` containing the required "
      "legal advancement before dependent work can proceed, or `resign`. Do not submit finish_turn or set_policy. "
      f"Applicable responses: {', '.join(packet.allowed_kinds)}."
    )
  elif packet.decision_kind == DECISION_KIND_FACTS_UNAVAILABLE:
    sections.append(
      "FACTS UNAVAILABLE: Threat calculations could not be completed. Submit manual actions (`act`), "
      f"`finish_turn`, or `resign`. Applicable responses: {', '.join(packet.allowed_kinds)}."
    )
  else:
    sections.append(
      "POLICY DECISION REQUIRED: Routine execution requires policy direction. Submit `set_policy` "
      f"to define objectives, or submit manual actions. Applicable responses: {', '.join(packet.allowed_kinds)}."
    )

  # Append context block
  exc_obj = (
    RoutineException(packet.reason, packet.evidence)
    if packet.reason != "initial"
    else None
  )
  sections.append(
    strategy_context(
      state,
      recruit_options=recruit_options,
      remaining=remaining,
      changes=changes,
      policy=policy,
      allowed_kinds=packet.allowed_kinds,
      exception=exc_obj,
    )
  )

  return "\n".join(sections)
