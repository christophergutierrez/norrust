"""Decision packets, incident tracking, contextual validation and strategy briefs.

The response and execution contract is documented in docs/LLM_CLIENT.md.
This module is transport-neutral; tools.llm_client owns dispatch, durable
logging and execution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

try:
  from .routine_policy import (
    ModelResponseError,
    RoutineException,
    strategy_context,
    _strategy_contract,
    render_strategy_fixed_prefix,
    _capacity_relief_line,
    _contact_destination_line,
    _contact_proposed_options_line,
    SetPolicyResponse,
    ActResponse,
    FinishTurnResponse,
    ResignResponse,
    ChooseResponse,
  )
except ImportError:
  from tools.routine_policy import (
    ModelResponseError,
    RoutineException,
    strategy_context,
    _strategy_contract,
    render_strategy_fixed_prefix,
    _capacity_relief_line,
    _contact_destination_line,
    _contact_proposed_options_line,
    SetPolicyResponse,
    ActResponse,
    FinishTurnResponse,
    ResignResponse,
    ChooseResponse,
  )

# Canonical decision kinds
DECISION_KIND_TACTICAL = "tactical"
DECISION_KIND_POLICY = "policy"
DECISION_KIND_PROMOTION = "promotion"
DECISION_KIND_FACTS_UNAVAILABLE = "facts_unavailable"

# Closed set of allowable responses
ALLOWED_ALL = ["set_policy", "act", "finish_turn", "resign"]
ALLOWED_TACTICAL_WITH_OPTIONS = ["choose", "act", "finish_turn", "resign"]
ALLOWED_TACTICAL = ["act", "finish_turn", "resign"]
ALLOWED_PROMOTION = ["act", "resign"]
# Stack 3: a rejected proposed_destination move with a generated bounded menu
# stays decision_kind policy (set_policy/act/finish_turn/resign remain legal;
# this is not current-board contact and consumes no contact_state_key) but
# additionally permits choose over the flagged actor's offered options.
ALLOWED_POLICY_WITH_CHOOSE = ["set_policy", "act", "finish_turn", "resign", "choose"]

CONTACT_ACTIONABILITY_ACTIONABLE = "actionable"
CONTACT_ACTIONABILITY_EXHAUSTED = "exhausted"
CONTACT_ACTIONABILITY_UNKNOWN = "unknown"
CLOSURE_REASON_EXHAUSTED = "exhausted"
CLOSURE_REASON_REPEATED_CONTACT_KEY = "repeated_contact_key"
CORRECTION_KIND_SYNTAX = "syntax"
CORRECTION_KIND_CONTEXT = "context"
CORRECTION_KIND_SEMANTIC_REPEAT = "semantic_repeat"


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
  final_only: bool = False
  contact_state_key: Optional[str] = None
  closure_reason: Optional[str] = None
  # Stack 1: candidates the integrator proved LEGAL AT source_revision via the
  # real engine. Never safe, never guaranteed valid after any intervening
  # action. This module never sets this field on its own; only the integrator
  # may append an entry, and only after a successful engine validation call.
  # Each entry: {"option_ids": [str, ...], "source_revision": int, "finish_turn": bool}.
  validated_selections: list[dict[str, Any]] = field(default_factory=list)

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
      "final_only": self.final_only,
      "contact_state_key": self.contact_state_key,
      "closure_reason": self.closure_reason,
      "validated_selections": copy.deepcopy(self.validated_selections),
    }

  @classmethod
  def from_dict(cls, data: dict[str, Any]) -> DecisionPacket:
    raw_key = data.get("contact_state_key")
    raw_reason = data.get("closure_reason")
    raw_validated = data.get("validated_selections", [])
    validated_selections = (
      copy.deepcopy(raw_validated) if isinstance(raw_validated, list) else []
    )
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
      final_only=bool(data.get("final_only", False)),
      contact_state_key=raw_key if isinstance(raw_key, str) and raw_key else None,
      closure_reason=raw_reason if isinstance(raw_reason, str) and raw_reason else None,
      validated_selections=validated_selections,
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
  elif reason == "recruitment_review":
    pass
  else:
    # Generic primitives
    for k in sorted(evidence):
      if k not in ("detail", "message", "prose", "request_id", "policy_id", "installation_id"):
        v = evidence[k]
        if isinstance(v, (int, str, bool)):
          canonical[k] = v

  raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
  return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def contact_state_key_from_evidence(evidence: dict[str, Any] | None) -> Optional[str]:
  """Return the engine contact_state_key, or None when it cannot authorize closure."""
  if not isinstance(evidence, dict):
    return None
  key = evidence.get("contact_state_key")
  if isinstance(key, str) and key:
    return key
  return None


def contact_actionability_from_evidence(evidence: dict[str, Any] | None) -> str:
  """Return actionable|exhausted|unknown. Missing or invalid values are unknown."""
  if not isinstance(evidence, dict):
    return CONTACT_ACTIONABILITY_UNKNOWN
  value = evidence.get("contact_actionability")
  if value in (
    CONTACT_ACTIONABILITY_ACTIONABLE,
    CONTACT_ACTIONABILITY_EXHAUSTED,
    CONTACT_ACTIONABILITY_UNKNOWN,
  ):
    return value
  return CONTACT_ACTIONABILITY_UNKNOWN


def contact_scope_key(
  game_id: str | int,
  side_turn: str | int,
  contact_state_key: str,
) -> tuple[str, str, str]:
  """Scope a contact_state_key to (game_id, canonical controlled side-turn id, key)."""
  return (str(game_id), str(side_turn), str(contact_state_key))


def contact_closure_reason(
  evidence: dict[str, Any] | None,
  tracker: Optional["IncidentTracker"] = None,
  *,
  game_id: str | int = "",
  side_turn: int = 0,
  reason: str = "contact",
) -> Optional[str]:
  """Why this current-state contact packet must be final_only, or None.

  Exhausted actionability closes on its own. A present contact_state_key
  closes only after that key was marked consumed for a committed model
  decision this controlled side-turn. Missing keys and unknown actionability
  cannot authorize closure.
  """
  if reason != "contact" or not isinstance(evidence, dict):
    return None
  if str(evidence.get("stage", "")) != "current_state":
    return None
  if contact_actionability_from_evidence(evidence) == CONTACT_ACTIONABILITY_EXHAUSTED:
    return CLOSURE_REASON_EXHAUSTED
  key = contact_state_key_from_evidence(evidence)
  if key is None or tracker is None:
    return None
  if tracker.contact_key_consumed(game_id, side_turn, key):
    return CLOSURE_REASON_REPEATED_CONTACT_KEY
  return None


def contact_closure_required(
  evidence: dict[str, Any] | None,
  tracker: Optional["IncidentTracker"] = None,
  *,
  game_id: str | int = "",
  side_turn: int = 0,
  reason: str = "contact",
) -> bool:
  return contact_closure_reason(
    evidence, tracker, game_id=game_id, side_turn=side_turn, reason=reason,
  ) is not None


def effective_final_only(
  driver_final_only: bool,
  evidence: dict[str, Any] | None,
  tracker: Optional["IncidentTracker"] = None,
  *,
  game_id: str | int = "",
  side_turn: int = 0,
  reason: str = "contact",
) -> bool:
  """driver_final_only OR contact_closure_required. Do not mutate driver state."""
  return bool(driver_final_only) or contact_closure_required(
    evidence, tracker, game_id=game_id, side_turn=side_turn, reason=reason,
  )


def build_decision_packet(
  reason: str,
  evidence: dict[str, Any],
  revision: int,
  *,
  game_id: str | int = "",
  side_turn: int = 0,
  contact_scope: str | int | None = None,
  final_only: bool = False,
  tracker: Optional["IncidentTracker"] = None,
  allowed_kinds_override: Optional[list[str]] = None,
  decision_id: Optional[str] = None,
) -> DecisionPacket:
  """Build a structured DecisionPacket for the given reason and evidence."""
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
                  "recruitment_blocked", "recruitment_review", "no_executable_orders"):
    decision_kind = DECISION_KIND_POLICY
  else:
    decision_kind = DECISION_KIND_POLICY

  # Extract options from evidence if tactical. Keep the engine's flat array;
  # do not synthesize a grouped copy or rewrite option IDs.
  raw_options = evidence.get("options")
  options = copy.deepcopy(raw_options) if isinstance(raw_options, list) else []
  options_truncated = bool(evidence.get("options_truncated", False))

  # Determine allowed_kinds
  if allowed_kinds_override is not None:
    allowed = list(allowed_kinds_override)
  elif decision_kind == DECISION_KIND_TACTICAL:
    if options:
      allowed = list(ALLOWED_TACTICAL_WITH_OPTIONS)
    else:
      allowed = list(ALLOWED_TACTICAL)
  elif decision_kind == DECISION_KIND_PROMOTION:
    allowed = list(ALLOWED_PROMOTION)
  elif decision_kind == DECISION_KIND_FACTS_UNAVAILABLE:
    allowed = list(ALLOWED_TACTICAL)
  elif decision_kind == DECISION_KIND_POLICY and reason == "contact" and options:
    # proposed_destination (or another non-current_state contact stage) with
    # a generated bounded menu: keep every policy response legal and add
    # choose. Empty options leave ALLOWED_ALL exactly as today.
    allowed = list(ALLOWED_POLICY_WITH_CHOOSE)
  else:
    allowed = list(ALLOWED_ALL)

  incident_key = compute_incident_key(game_id, side_turn, reason, evidence)

  if decision_id:
    did = decision_id
  else:
    counter = tracker.ineffective_counts.get((side_turn, rev, incident_key), 0) if tracker is not None else 0
    did_seed = f"{side_turn}:{rev}:{reason}:{counter}:{json.dumps(evidence, sort_keys=True, default=str)}"
    did = f"dec-{hashlib.sha256(did_seed.encode('utf-8')).hexdigest()[:12]}"
  contact_key = (
    contact_state_key_from_evidence(evidence)
    if reason == "contact" and evidence.get("stage") == "current_state"
    else None
  )
  scope = contact_scope if contact_scope is not None else side_turn
  closure_reason = contact_closure_reason(
    evidence, tracker, game_id=game_id, side_turn=scope, reason=reason,
  )
  packet_final_only = bool(final_only) or closure_reason is not None
  if tracker is not None and contact_key is not None:
    tracker.observe_contact_decision(game_id, scope, contact_key)

  if reason == "threat_unavailable":
    coverage = {"facts": "unavailable", "options": "not_generated"}
  elif decision_kind == DECISION_KIND_TACTICAL:
    if evidence.get("options_empty_reason") == "exhausted_contact_no_automatic_rescue_menu":
      coverage = {"facts": "complete", "options": "not_generated"}
    else:
      coverage = {
        "facts": "complete",
        "options": "truncated" if options_truncated else "complete",
      }
  elif decision_kind == DECISION_KIND_POLICY and reason == "contact" and options:
    coverage = {
      "facts": "complete",
      "options": "truncated" if options_truncated else "complete",
    }
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
    options=options,
    coverage=coverage,
    final_only=packet_final_only,
    contact_state_key=contact_key,
    closure_reason=closure_reason,
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
  elif isinstance(response, ChooseResponse):
    kind = "choose"
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

  if kind == "choose":
    resp_did = getattr(response, "decision_id", None)
    if resp_did is None and isinstance(response, dict):
      resp_did = response.get("decision_id")
    if resp_did != packet.decision_id:
      raise ContextualResponseError(
        f"Decision ID mismatch: expected {packet.decision_id!r}, got {resp_did!r}"
      )
    resp_oids = getattr(response, "option_ids", None)
    if resp_oids is None and isinstance(response, dict):
      resp_oids = response.get("option_ids")
    if not isinstance(resp_oids, list):
      raise ContextualResponseError("choose response is missing option_ids")
    valid_opts = {
      opt["option_id"]: opt
      for opt in packet.options
      if isinstance(opt, dict) and "option_id" in opt
    }
    seen_actors: set[Any] = set()
    for option_id in resp_oids:
      if option_id not in valid_opts:
        raise ContextualResponseError(
          f"Unknown option_id {option_id!r}. Available options: {list(valid_opts)}"
        )
      actor_id = valid_opts[option_id].get("actor_id")
      if actor_id in seen_actors:
        raise ContextualResponseError(
          f"at most one option per actor_id; actor {actor_id!r} selected twice"
        )
      seen_actors.add(actor_id)
    finish_turn = getattr(response, "finish_turn", None)
    if finish_turn is None and isinstance(response, dict):
      finish_turn = response.get("finish_turn", False)
    if packet.final_only and not finish_turn:
      raise ContextualResponseError("final_only strategy choose must set finish_turn=true")

  if kind == "act":
    finish_turn = getattr(response, "finish_turn", response.get("finish_turn") if isinstance(response, dict) else False)
    if packet.final_only and not finish_turn:
      raise ContextualResponseError("final_only strategy act must set finish_turn=true")


class IncidentTracker:
  """Tracks incidents, contact-key allowance, and one shared correction budget."""

  def __init__(self) -> None:
    # revision -> set of incident_key encountered at that revision
    self.encountered_by_revision: dict[int, set[str]] = {}
    # (side_turn, revision, incident_key) -> count of ineffective responses
    self.ineffective_counts: dict[tuple[int, int, str], int] = {}
    # (side_turn, revision, incident_key) -> count of total encounters
    self.encounter_counts: dict[tuple[int, int, str], int] = {}
    # (game_id, side_turn, contact_state_key) -> issued decision-request count
    self.contact_decision_counts: dict[tuple[str, int, str], int] = {}
    # Consumed keys after a committed model decision this controlled side-turn.
    self.consumed_contact_keys: set[tuple[str, int, str]] = set()

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
    Syntax, context, and semantic-repeat share this counter.
    """
    key = (side_turn, revision, incident_key)
    return self.ineffective_counts.get(key, 0) <= 1

  def record_correction(
    self,
    side_turn: int,
    revision: int,
    incident_key: str,
    *,
    kind: str,
  ) -> int:
    """Record a syntax, context, or semantic-repeat failure.

    All kinds share the existing one-correction-per-incident counter.
    """
    _ = kind
    return self.record_ineffective(side_turn, revision, incident_key)

  def observe_contact_decision(
    self,
    game_id: str | int,
    side_turn: int,
    contact_state_key: str | None,
  ) -> int:
    """Count an issued decision request for this contact key. Does not consume it."""
    key = contact_state_key_from_evidence({"contact_state_key": contact_state_key})
    if key is None:
      return 0
    scope = contact_scope_key(game_id, side_turn, key)
    self.contact_decision_counts[scope] = self.contact_decision_counts.get(scope, 0) + 1
    return self.contact_decision_counts[scope]

  def mark_contact_key_consumed(
    self,
    game_id: str | int,
    side_turn: int,
    contact_state_key: str | None,
  ) -> None:
    """Mark a key consumed after a model response commits work.

    Successful inspections and routine independent movement must not call this.
    Missing keys are ignored and cannot authorize later closure.
    """
    key = contact_state_key_from_evidence({"contact_state_key": contact_state_key})
    if key is None:
      return
    self.consumed_contact_keys.add(contact_scope_key(game_id, side_turn, key))

  def contact_key_consumed(
    self,
    game_id: str | int,
    side_turn: int,
    contact_state_key: str | None,
  ) -> bool:
    key = contact_state_key_from_evidence({"contact_state_key": contact_state_key})
    if key is None:
      return False
    return contact_scope_key(game_id, side_turn, key) in self.consumed_contact_keys

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
        evidence = packet.get("evidence") if isinstance(packet.get("evidence"), dict) else {}
        ckey = packet.get("contact_state_key") or evidence.get("contact_state_key")
        gid = row.get("game_id", "")
        if ckey:
          self.observe_contact_decision(gid, row.get("contact_scope", st), ckey)
      elif rtype == "policy_installed":
        for st, rev, ikey in pending_incidents:
          self.observe_incident(st, rev, ikey)
        pending_incidents.clear()
      elif rtype in ("contextual_rejection", "incident_recurrence"):
        rev = row.get("state_revision", 0)
        ikey = row.get("incident_key", "")
        st = row.get("side_turn", current_side_turn)
        if ikey:
          kind = row.get("correction_kind", CORRECTION_KIND_CONTEXT)
          if rtype == "incident_recurrence":
            kind = row.get("correction_kind", CORRECTION_KIND_SEMANTIC_REPEAT)
          self.record_correction(st, rev, ikey, kind=kind)
          self.observe_incident(st, rev, ikey)
      elif rtype == "contact_key_consumed":
        st = row.get("side_turn", current_side_turn)
        self.mark_contact_key_consumed(
          row.get("game_id", ""),
          st,
          row.get("contact_state_key"),
        )


def map_batch_failure_to_option(
  options: list[dict[str, Any]],
  concatenated_actions: list[dict[str, Any]],
  failed_index: int,
) -> Optional[dict[str, Any]]:
  """Map an engine batch failure index onto the covering option_id and actor_id.

  ``options`` is the issued packet's flat option list. ``concatenated_actions``
  is the submitted action list in execution order (selected option actions,
  optionally followed by an appended no-sweep finish). ``failed_index`` is the
  engine action index. Returns ``{"option_id": ..., "actor_id": ...}`` or
  ``None`` when the index is unmapped (including an appended finish).
  """
  if (not isinstance(failed_index, int) or isinstance(failed_index, bool)
      or failed_index < 0 or not isinstance(concatenated_actions, list)):
    return None
  remaining = [opt for opt in options if isinstance(opt, dict)]
  offset = 0
  while offset < len(concatenated_actions):
    match: Optional[dict[str, Any]] = None
    match_len = 0
    for opt in remaining:
      acts = opt.get("actions")
      if not isinstance(acts, list) or not acts:
        continue
      n = len(acts)
      if concatenated_actions[offset:offset + n] == acts:
        match = opt
        match_len = n
        break
    if match is None:
      return None
    if offset <= failed_index < offset + match_len:
      return {"option_id": match.get("option_id"), "actor_id": match.get("actor_id")}
    offset += match_len
    remaining = [opt for opt in remaining if opt is not match]
  return None


def _int_fact(value: Any) -> Optional[int]:
  if isinstance(value, int) and not isinstance(value, bool):
    return value
  return None


def _format_option_exposure(
  option: dict[str, Any],
  *,
  is_recruiter: bool = False,
  recruiter_hp: Optional[tuple[int, int]] = None,
) -> str:
  """Render destination exposure. Nonzero, zero, and unknown stay distinct."""
  if "exposure" not in option:
    return ""
  exp = option.get("exposure")
  if not isinstance(exp, dict):
    return " | Exposure after this option: unknown"
  attackers = _int_fact(exp.get("distinct_attacker_count"))
  max_damage = _int_fact(exp.get("max_incoming_damage"))
  expected_tenths = _int_fact(exp.get("expected_incoming_damage_tenths"))
  if attackers is None and max_damage is None and expected_tenths is None:
    return " | Exposure after this option: unknown"
  nonzero = (
    (attackers is not None and attackers > 0)
    or (max_damage is not None and max_damage > 0)
    or (expected_tenths is not None and expected_tenths > 0)
  )
  parts: list[str] = []
  if attackers is not None:
    parts.append(f"attackers={attackers}")
  if max_damage is not None:
    parts.append(f"max incoming damage={max_damage}")
  if expected_tenths is not None:
    parts.append(f"expected incoming damage={expected_tenths / 10.0:.1f}")
  estimate = "estimates from the issuing state, not a joint-plan forecast"
  facts = ", ".join(parts)
  prefix = ""
  if is_recruiter and nonzero:
    hp_str = f" (HP {recruiter_hp[0]}/{recruiter_hp[1]})" if recruiter_hp else ""
    prefix = f" | HIGH STAKES RECRUITER DANGER: Recruiter{hp_str} exposed to enemy next turn"
  if nonzero:
    return f"{prefix} | still exposed after this option | Exposure ({estimate}): {facts}"
  return f" | Exposure after this option ({estimate}): {facts}"


def _group_options_by_actor(options: list[dict[str, Any]]) -> list[tuple[Any, list[dict[str, Any]]]]:
  groups: list[tuple[Any, list[dict[str, Any]]]] = []
  index: dict[Any, int] = {}
  for opt in options:
    if not isinstance(opt, dict):
      continue
    actor = opt.get("actor_id")
    if actor not in index:
      index[actor] = len(groups)
      groups.append((actor, [opt]))
    else:
      groups[index[actor]][1].append(opt)
  return groups


def _get_option_destinations(opt: dict[str, Any]) -> set[tuple[int, int]]:
  dests: set[tuple[int, int]] = set()
  for a in opt.get("actions", []):
    if not isinstance(a, dict):
      continue
    act_name = a.get("action")
    if act_name == "Move":
      c = a.get("col", a.get("to_col"))
      r = a.get("row", a.get("to_row"))
      if isinstance(c, int) and isinstance(r, int) and not isinstance(c, bool) and not isinstance(r, bool):
        dests.add((c, r))
    elif act_name == "Engage":
      steps = a.get("steps")
      if isinstance(steps, list) and steps:
        last = steps[-1]
        if isinstance(last, dict):
          c = last.get("col")
          r = last.get("row")
          if isinstance(c, int) and isinstance(r, int) and not isinstance(c, bool) and not isinstance(r, bool):
            dests.add((c, r))
  return dests


def _get_option_targets(opt: dict[str, Any]) -> set[int]:
  targets: set[int] = set()
  for a in opt.get("actions", []):
    if not isinstance(a, dict):
      continue
    act_name = a.get("action")
    if act_name in ("Attack", "Engage"):
      tgt = a.get("defender_id", a.get("target_id"))
      if isinstance(tgt, int) and not isinstance(tgt, bool):
        targets.add(tgt)
  return targets


def _format_option_compatibility_notes(options: list[dict[str, Any]]) -> list[str]:
  dest_actors: dict[tuple[int, int], set[Any]] = {}
  target_actors: dict[int, set[Any]] = {}
  for opt in options:
    if not isinstance(opt, dict):
      continue
    actor = opt.get("actor_id")
    for dest in _get_option_destinations(opt):
      dest_actors.setdefault(dest, set()).add(actor)
    for tgt in _get_option_targets(opt):
      target_actors.setdefault(tgt, set()).add(actor)

  notes: list[str] = []
  for (c, r), actors in sorted(dest_actors.items()):
    valid_actors = [act for act in actors if act is not None]
    if len(valid_actors) > 1:
      actors_str = ", ".join(f"Actor {act}" for act in sorted(valid_actors))
      notes.append(
        f"  - Shared destination ({c},{r}) across {actors_str}: two units cannot occupy the same "
        "hex at end of turn; subsequent move will fail unless destination is vacated."
      )

  for tgt, actors in sorted(target_actors.items()):
    valid_actors = [act for act in actors if act is not None]
    if len(valid_actors) > 1:
      actors_str = ", ".join(f"Actor {act}" for act in sorted(valid_actors))
      notes.append(
        f"  - Shared target U{tgt} across {actors_str}: multi-attack is supported if target "
        "survives, but subsequent attack will fail if target is killed earlier in batch."
      )
  return notes


def candidate_selections(packet: DecisionPacket) -> list[list[str]]:
  """Conservative candidate option_ids lists for the integrator to validate.

  Pure and read-only: this walks packet.options as issued and never touches
  the engine or marks anything validated. Returns at most FOUR lists, in
  order: (a) one greedy multi-actor list, built by walking options in their
  existing order and taking the first option per actor that shares neither a
  destination nor an attack target with an already-selected option (at most
  one option per actor), stopping once 3 options have been picked; then (b)
  the first individually offered option for each of the existing actors
  (existing actor/option priority order), taken unconditionally. Identical
  lists are deduplicated, order preserved, and actions within an option are
  never reordered. Every returned list has between 1 and 3 option_ids,
  matching the response parser's hard 1..3 `choose` limit — an unsubmittable
  candidate must never be produced or advertised.

  These destination/target filters are conservative CANDIDATE SELECTION for
  proposing a batch worth validating; they are not a new legality rule, and
  shared-target multi-attacks remain selectable via the ordinary options.
  """
  options = [opt for opt in packet.options if isinstance(opt, dict)]
  groups = _group_options_by_actor(options)

  greedy_ids: list[str] = []
  used_destinations: set[tuple[int, int]] = set()
  used_targets: set[int] = set()
  picked_actors: set[Any] = set()
  for opt in options:
    if len(greedy_ids) >= 3:
      break
    option_id = opt.get("option_id")
    if not isinstance(option_id, str):
      continue
    actor_id = opt.get("actor_id")
    if actor_id in picked_actors:
      continue
    dests = _get_option_destinations(opt)
    targets = _get_option_targets(opt)
    if dests & used_destinations or targets & used_targets:
      continue
    greedy_ids.append(option_id)
    picked_actors.add(actor_id)
    used_destinations |= dests
    used_targets |= targets

  candidates: list[list[str]] = []
  if greedy_ids:
    candidates.append(greedy_ids)

  for _actor_id, actor_opts in groups[:3]:
    for opt in actor_opts:
      option_id = opt.get("option_id")
      if isinstance(option_id, str):
        candidates.append([option_id])
        break

  deduped: list[list[str]] = []
  seen: set[tuple[str, ...]] = set()
  for candidate in candidates:
    key = tuple(candidate)
    if key in seen:
      continue
    seen.add(key)
    deduped.append(candidate)

  return deduped[:4]


def render_validated_selections(packet: DecisionPacket) -> str:
  """Compact rendering of the preferred (first) validated selection, if any.

  Validated means the integrator proved this exact ordered option_ids list
  (and finish_turn) LEGAL AT source_revision by an actual engine call. It is
  never a safety claim and never a claim of continued validity after any
  intervening action; re-validation happens again through ordinary submission.
  Returns "" when packet.validated_selections is empty.
  """
  if not packet.validated_selections:
    return ""
  first = packet.validated_selections[0]
  if not isinstance(first, dict):
    return ""
  option_ids = first.get("option_ids")
  option_ids = [str(oid) for oid in option_ids] if isinstance(option_ids, list) else []
  source_revision = first.get("source_revision")
  finish_turn = bool(first.get("finish_turn", False))
  ids_str = ", ".join(option_ids)
  return (
    f"Engine-validated selection (legal at revision {source_revision} only; "
    "not a safety claim and not guaranteed valid after any intervening action; "
    f"re-validated on submission): option_ids=[{ids_str}], finish_turn={json.dumps(finish_turn)}."
  )


def _build_choose_example(packet: DecisionPacket) -> Optional[dict[str, Any]]:
  if "choose" not in packet.allowed_kinds or not packet.options:
    return None

  if packet.validated_selections:
    first = packet.validated_selections[0]
    if isinstance(first, dict):
      option_ids = first.get("option_ids")
      valid_ids = {
        opt.get("option_id")
        for opt in packet.options
        if isinstance(opt, dict) and isinstance(opt.get("option_id"), str)
      }
      if (
        isinstance(option_ids, list)
        and option_ids
        and all(isinstance(oid, str) and oid in valid_ids for oid in option_ids)
      ):
        return {
          "kind": "choose",
          "decision_id": packet.decision_id,
          "option_ids": list(option_ids),
          "finish_turn": bool(first.get("finish_turn", packet.final_only)),
        }

  grouped = _group_options_by_actor(packet.options)
  if not grouped:
    return None

  if len(grouped) >= 2:
    actor1, opts1 = grouped[0]
    actor2, opts2 = grouped[1]
    for opt1 in opts1:
      if not (isinstance(opt1, dict) and isinstance(opt1.get("option_id"), str)):
        continue
      dest1 = _get_option_destinations(opt1)
      tgt1 = _get_option_targets(opt1)
      for opt2 in opts2:
        if not (isinstance(opt2, dict) and isinstance(opt2.get("option_id"), str)):
          continue
        dest2 = _get_option_destinations(opt2)
        tgt2 = _get_option_targets(opt2)
        if not (dest1 & dest2) and not (tgt1 & tgt2):
          return {
            "kind": "choose",
            "decision_id": packet.decision_id,
            "option_ids": [opt1["option_id"], opt2["option_id"]],
            "finish_turn": bool(packet.final_only),
          }

  first_opt = None
  for _, opts in grouped:
    for opt in opts:
      if isinstance(opt, dict) and isinstance(opt.get("option_id"), str):
        first_opt = opt
        break
    if first_opt:
      break

  if not first_opt:
    return None

  return {
    "kind": "choose",
    "decision_id": packet.decision_id,
    "option_ids": [first_opt["option_id"]],
    "finish_turn": bool(packet.final_only),
  }


def _proposed_movement_guidance(packet: DecisionPacket) -> str:
  """Address the named blocked step without advertising unavailable kinds."""
  allowed = packet.allowed_kinds
  alternatives = []
  if "choose" in allowed:
    alternatives.append("Choose an offered option")
  if "act" in allowed:
    alternatives.append("author a legal action")
  if "set_policy" in allowed:
    alternatives.append("make a policy change that addresses this step")
  parts = ["Resolve the named blocked step first."]
  if alternatives:
    if len(alternatives) == 1:
      parts.append(alternatives[0] + ".")
    else:
      parts.append(", ".join(alternatives[:-1]) + ", or " + alternatives[-1] + ".")
  parts.append("Preserve unrelated objectives unless they need to change.")
  if "choose" in allowed:
    parts.append("A risky legal option is allowed; the menu is not an instruction to take it.")
  return " ".join(parts)


def render_decision_brief(
  packet: DecisionPacket,
  *,
  state: Optional[dict[str, Any]] = None,
  recruit_options: Any = None,
  changes: Any = None,
  policy: Any = None,
  remaining: Any = None,
  progress: Any = None,
  recruitable_defs: Any = (),
) -> str:
  """Render a decision-specific brief with applicable responses."""
  prefix = render_strategy_fixed_prefix(state, recruitable_defs)

  exc_obj = (
    RoutineException(packet.reason, packet.evidence)
    if packet.reason != "initial"
    else None
  )
  context = strategy_context(
    state,
    recruit_options=recruit_options,
    remaining=remaining,
    changes=changes,
    policy=policy,
    progress=progress,
    allowed_kinds=packet.allowed_kinds,
    exception=exc_obj,
  )

  sections: list[str] = []

  # Specific Guidance
  if packet.decision_kind == DECISION_KIND_TACTICAL:
    if packet.options:
      sections.append(
        "TACTICAL DECISION REQUIRED: Enemy contact exists on the current board. Changing policy "
        "moves no units and cannot clear the current-board pause. You may choose an offered option "
        f"(`choose`), submit tactical action orders (`act`), `finish_turn`, or `resign`. "
        f"Applicable responses: {', '.join(packet.allowed_kinds)}."
      )
    else:
      sections.append(
        "TACTICAL DECISION REQUIRED: Enemy contact exists on the current board. Changing policy "
        "moves no units and cannot clear the current-board pause. You must submit tactical action "
        f"orders (`act`), `finish_turn`, or `resign`. Applicable responses: {', '.join(packet.allowed_kinds)}."
      )
      empty_reason = packet.evidence.get("options_empty_reason")
      if empty_reason == "exhausted_contact_no_automatic_rescue_menu":
        sections.append(
          "Involved units cannot act. No automatic rescue menu was generated. "
          "This does not establish that every custom legal rescue is unavailable. "
          "You may submit a custom legal rescue with `act` plus finish_turn=true, "
          "finish, or resign."
        )
      elif empty_reason == "no_executable_options":
        option_coverage = packet.coverage.get("options", "unknown")
        sections.append(
          "No eligible actor has an executable action in this bounded tactical menu. "
          "This does not establish that every custom legal action by another unit is unavailable. "
          f"Tactical option enumeration coverage is {option_coverage}."
        )
    if packet.final_only:
      closers = [kind for kind in ("act", "choose") if kind in packet.allowed_kinds]
      if closers:
        sections.append(
          "This packet is final_only: " + " and ".join(closers)
          + " must set finish_turn=true."
        )
    if packet.final_only or packet.closure_reason:
      recruiter_threats = []
      pt = packet.evidence.get("projected_threats")
      if isinstance(pt, dict) and "recruiters" in pt:
        for r in pt.get("recruiters", []):
          if isinstance(r, dict):
            recruiter_threats.append(r)
      elif isinstance(state, dict):
        exp = state.get("tactical_surface", {}).get("exposure", {})
        if isinstance(exp, dict) and "recruiters" in exp:
          for r in exp.get("recruiters", []):
            if isinstance(r, dict):
              recruiter_threats.append(r)
      for rt in recruiter_threats:
        rid = rt.get("recruiter_id", rt.get("unit_id"))
        att_cnt = rt.get("distinct_attacker_count", len(rt.get("attackers", [])))
        sections.append(
          f"RECRUITER EXPOSURE SUMMARY: Recruiter {rid} is exposed to enemy attacks on next turn "
          f"({att_cnt} projected attackers). This is informational; finish_turn leaves the unit in place."
        )
    if packet.closure_reason in (CLOSURE_REASON_EXHAUSTED, CLOSURE_REASON_REPEATED_CONTACT_KEY):
      if packet.closure_reason == CLOSURE_REASON_EXHAUSTED:
        cause = (
          "CONTACT CLOSURE: contact_actionability=exhausted; complete eligibility checks "
          "found no executable offered move or attack for involved friendly units. "
        )
      else:
        cause = (
          "CONTACT CLOSURE: this contact_state_key already received a committed model "
          "decision this controlled side-turn. Remaining exposure is not a new deliberation. "
        )
      actions = []
      if "act" in packet.allowed_kinds:
        actions.append("a custom legal rescue with `act` plus finish_turn=true")
      if "choose" in packet.allowed_kinds:
        actions.append("`choose` remaining issued options plus finish")
      if "finish_turn" in packet.allowed_kinds:
        actions.append("finish immediately")
      if "resign" in packet.allowed_kinds:
        actions.append("resign")
      action_text = ("; ".join(actions) + ". ") if actions else ""
      sections.append(
        cause
        + "This does not establish that every custom rescue is unavailable. "
        + action_text
        + "Do not recruit and request the same decision again."
      )
    sections.append(
      "If next-turn exposure of a custom destination is uncertain, use the existing "
      "destination inspection before acting."
    )
    if packet.evidence:
      trigger = packet.evidence.get("trigger", "unspecified")
      friendly = packet.evidence.get("friendly_unit_ids", [])
      enemy = packet.evidence.get("enemy_unit_ids", [])
      fact_parts = [
        f"trigger={trigger}",
        f"friendly_units={friendly}",
        f"enemy_units={enemy}",
      ]
      actor_ids = packet.evidence.get("actor_ids")
      if actor_ids is not None:
        fact_parts.append(f"actor_ids={actor_ids}")
      eligible_count = packet.evidence.get("eligible_actor_count")
      if eligible_count is not None:
        fact_parts.append(f"eligible_actor_count={eligible_count}")
      if "actors_truncated" in packet.evidence:
        fact_parts.append(
          f"actors_truncated={json.dumps(bool(packet.evidence.get('actors_truncated')))}"
        )
      if "contact_actionability" in packet.evidence:
        fact_parts.append(
          f"contact_actionability={contact_actionability_from_evidence(packet.evidence)}"
        )
      if packet.contact_state_key:
        fact_parts.append(f"contact_state_key={packet.contact_state_key}")
      sections.append("Contact facts: " + ", ".join(fact_parts))
    if packet.options:
      opt_lines = [
        "Offered tactical options, grouped by actor from the flat issued list. "
        "Each option is individually valid against the current board. "
        "Selecting several options in one choose response avoids another call per unit "
        "and executes them sequentially in listed order as an atomic batch "
        "(at most one option per actor; rollback occurs if any action fails)."
      ]
      recruiter_ids = set()
      recruiter_hps = {}
      if isinstance(state, dict):
        for u in state.get("units", []):
          if isinstance(u, dict) and u.get("can_recruit"):
            uid = u.get("id")
            if isinstance(uid, int):
              recruiter_ids.add(uid)
              recruiter_hps[uid] = (u.get("hp", 0), u.get("max_hp", u.get("hp", 0)))
      for actor_id, actor_opts in _group_options_by_actor(packet.options):
        is_rec = actor_id in recruiter_ids
        rec_hp = recruiter_hps.get(actor_id)
        actor_label = f"Actor {actor_id}" + (f" (Recruiter, HP {rec_hp[0]}/{rec_hp[1]})" if is_rec and rec_hp else "") + ":"
        opt_lines.append(actor_label)
        for opt in actor_opts:
          oid = opt.get("option_id")
          cat = opt.get("category")
          acts = opt.get("actions", [])
          act_descs = []
          for a in acts:
            if not isinstance(a, dict):
              act_descs.append(json.dumps(a))
              continue
            act_name = a.get("action")
            if act_name == "Move":
              act_descs.append(
                f"Move({a.get('unit_id')} -> ({a.get('col', a.get('to_col'))}, {a.get('row', a.get('to_row'))}))"
              )
            elif act_name == "Attack":
              att_id = a.get("attacker_id", a.get("unit_id"))
              def_id = a.get("defender_id", a.get("target_id"))
              act_descs.append(f"Attack({att_id} -> {def_id})")
            else:
              act_descs.append(json.dumps(a))
          actions_summary = "; ".join(act_descs)
          forecast_str = ""
          fc = opt.get("forecast")
          if isinstance(fc, dict):
            forecast_parts = []
            dealt = fc.get("expected_damage_dealt_tenths")
            received = fc.get("expected_damage_received_tenths")
            kill_chance = fc.get("kill_chance_bps")
            outcome = fc.get("outcome_bps")
            if isinstance(dealt, int) and not isinstance(dealt, bool):
              forecast_parts.append(f"expected damage dealt={dealt / 10.0:.1f}")
            if isinstance(received, int) and not isinstance(received, bool):
              forecast_parts.append(f"expected counter damage={received / 10.0:.1f}")
            if isinstance(kill_chance, int) and not isinstance(kill_chance, bool):
              forecast_parts.append(f"kill chance={kill_chance / 100.0:.1f}%")
            if (isinstance(outcome, list) and len(outcome) == 3
                and isinstance(outcome[2], int) and not isinstance(outcome[2], bool)):
              forecast_parts.append(f"immediate exchange attacker loss chance={outcome[2] / 100.0:.1f}%")
            if forecast_parts:
              forecast_str = " | Forecast: immediate exchange only (not enemy next-turn survival); " + "; ".join(forecast_parts) + " (estimates, not guarantees)"
          exposure_str = _format_option_exposure(opt, is_recruiter=is_rec, recruiter_hp=rec_hp)
          movement_cost = opt.get("movement_cost")
          cost_str = (f" | Cost: {movement_cost}"
                      if isinstance(movement_cost, int) and not isinstance(movement_cost, bool)
                      else "")
          opt_lines.append(
            f"  - Option {oid!r} ({cat}): [{actions_summary}]{cost_str}{forecast_str}{exposure_str}"
          )
      compat_notes = _format_option_compatibility_notes(packet.options)
      if compat_notes:
        opt_lines.append("Option compatibility notes:")
        opt_lines.extend(compat_notes)
      example = _build_choose_example(packet)
      if example is not None:
        opt_lines.append(
          "To choose, respond with: " + json.dumps(example, separators=(",", ":"))
        )
      sections.append("\n".join(opt_lines))
  elif packet.reason == "contact" and packet.evidence.get("stage") != "current_state":
    dest_line = _contact_destination_line(packet.evidence)
    if dest_line:
      sections.append(dest_line)
    options_line = _contact_proposed_options_line(packet.evidence)
    if options_line:
      sections.append(options_line)
    sections.append(_proposed_movement_guidance(packet))
    sections.append(
      "A rejected proposed routine move is not current-board contact. "
      f"Applicable responses: {', '.join(packet.allowed_kinds)}."
    )
    example = _build_choose_example(packet)
    if example is not None:
      sections.append(
        "To choose, respond with: " + json.dumps(example, separators=(",", ":"))
      )
  elif packet.reason == "recruitment_review":
    sections.append(
      "ECONOMIC RECONSIDERATION: Completed recruitment queue with unreserved gold. "
      "Request a new finite queue with `set_policy` if more units are wanted, "
      "use reserve_gold explicitly for intentional saving, or proceed with manual actions. "
      f"Applicable responses: {', '.join(packet.allowed_kinds)}."
    )
    if packet.evidence.get("current_contact", {}).get("present"):
      sections.append(
        "Notice: Remote enemy contact is present. Updating policy does not move units or clear "
        "tactical contact."
      )
  elif packet.reason == "recruitment_blocked":
    relief = _capacity_relief_line(packet.evidence)
    if relief:
      sections.append(relief)
    sections.append(
      "POLICY DECISION REQUIRED: Routine execution requires policy direction. Submit `set_policy` "
      f"to define objectives, or submit manual actions. Applicable responses: {', '.join(packet.allowed_kinds)}."
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

  guidance_text = "\n".join(sections)
  return f"{prefix}{context}\n{guidance_text}"
