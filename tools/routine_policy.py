"""Strategy-mode policy validation, routine progress, exceptions and rendering.

This module implements the client half of the frozen `routine_next` contract
described in `docs/plans/strategy-and-routine-execution.md` (sections 3-6,
"Stack 1" and "Stack 2"). It is deliberately self-contained: it does not
import ``tools.llm_client`` so the two modules can be developed and tested in
isolation by separate workers. ``tools/llm_client.py`` imports from here.

Stack 2 enables the remaining policy fields (``scouts``, ``villages``,
``rally``, ``holds``) that Stack 1 kept scoped to empty/null. The full
per-field bounds in ``validate_policy`` (distinct existing friendly ids, at
most 8 scouts including new-scout-recruit totals, at most 4 villages, one
in-bounds rally or null, held ids excluded from scouts) are enforced exactly
as before; only the additional Stack-1-only scope gate (``enforce_stack1_scope``)
has been removed. Model invocation remains provider-neutral; Stack 3 supplies
compact strategy prompts and the tactical exception path.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# --------------------------------------------------------------------------
# Constants from the frozen contract (plan section 4).
# --------------------------------------------------------------------------

MAX_RECRUIT_ENTRIES = 8
MIN_RECRUIT_COUNT = 1
MAX_RECRUIT_COUNT = 32
MAX_SCOUTS = 8
MAX_VILLAGES = 4
RECRUIT_ROLES = ("scout", "army")

SET_POLICY_KEYS = {"kind", "policy"}
POLICY_FIELDS = {"reserve_gold", "recruits", "scouts", "villages", "rally", "holds"}
RECRUIT_ENTRY_FIELDS = {"def_id", "count", "role"}
ACT_KEYS = {"kind", "actions", "finish_turn"}
CHOOSE_KEYS = {"kind", "decision_id", "option_ids", "finish_turn"}
FINISH_TURN_KEYS = {"kind"}
FINISH_TURN_REDUNDANT_KEYS = {"kind", "finish_turn"}
RESIGN_KEYS = {"kind"}
RESPONSE_KINDS = ("set_policy", "act", "choose", "finish_turn", "resign")
CANONICAL_FINISH_TURN = {"kind": "finish_turn"}
CANONICAL_FINISH_TURN_JSON = json.dumps(CANONICAL_FINISH_TURN, separators=(",", ":"))
STRATEGY_RESPONSE_SHAPES = {
    "set_policy": SET_POLICY_KEYS,
    "act": ACT_KEYS,
    "choose": CHOOSE_KEYS,
    "finish_turn": FINISH_TURN_KEYS,
    "resign": RESIGN_KEYS,
}

# The closed set of typed exceptions the routine_next contract can raise.
# "unsafe_route", "invalid_assignment" and "objectives_complete" are Stack 2
# additions (plan section 5/"New exception codes"). "objectives_complete" is
# deferred by the engine until a no-sweep finish has committed, so by the
# time the client observes it, it never blocks the current turn from
# finishing -- it is handled like any other exception once it arrives.
ROUTINE_EXCEPTION_CODES = frozenset({
    "contact", "threat_unavailable", "promotion_pending",
    "recruitment_blocked", "no_executable_orders",
    "unsafe_route", "route_unavailable", "invalid_assignment", "objectives_complete",
})
ROUTINE_ORIGIN = "routine"

# The only boundary routine execution may submit. Verified in
# greedy_driver.rs::finish_with_greedy_empty_groups_and_holds_performs_no_sweep
# to move/engage nothing. Plain EndTurn DOES sweep -- never use it here.
NO_SWEEP_FINISH = {"action": "FinishWithGreedy", "groups": [], "holds": []}


class PolicyValidationError(ValueError):
    """A policy or model response failed strict contract validation.

    Raising this must never have mutated engine state, persisted progress,
    or a policy installation. Callers must validate fully before any of
    those side effects occur.
    """


class ModelResponseError(ValueError):
    """A model response violated the strict discriminated-union contract."""


def _require_keys(obj: dict[str, Any], allowed: set[str], required: set[str], where: str) -> None:
    if not isinstance(obj, dict):
        raise PolicyValidationError(f"{where} must be an object")
    extra = set(obj) - allowed
    if extra:
        raise PolicyValidationError(
            f"{where} has unknown key(s): {', '.join(sorted(str(k) for k in extra))}")
    missing = required - set(obj)
    if missing:
        raise PolicyValidationError(
            f"{where} is missing required key(s): {', '.join(sorted(missing))}")


def _require_int(value: Any, where: str, *, minimum: Optional[int] = None,
                  maximum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyValidationError(f"{where} must be an integer")
    if minimum is not None and value < minimum:
        raise PolicyValidationError(f"{where} must be >= {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise PolicyValidationError(f"{where} must be <= {maximum}, got {value}")
    return value


CANONICAL_VILLAGE_COORD = {"col": 2, "row": 4}
CANONICAL_RALLY_COORD = {"col": 8, "row": 6}
CANONICAL_COORD_JSON = json.dumps(CANONICAL_VILLAGE_COORD, separators=(",", ":"))
CANONICAL_RALLY_JSON = json.dumps(CANONICAL_RALLY_COORD, separators=(",", ":"))


def _require_coord(value: Any, where: str, bounds: Optional[tuple[int, int]] = None) -> tuple[int, int]:
    shape = (
        f"{where} must be an object {CANONICAL_COORD_JSON} with integer col and row "
        "(zero-based offsets); arrays are not accepted"
    )
    if not isinstance(value, dict):
        raise PolicyValidationError(f"{shape}; got {type(value).__name__}")
    extra = set(value) - {"col", "row"}
    missing = {"col", "row"} - set(value)
    if extra or missing:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unknown " + ", ".join(sorted(str(k) for k in extra)))
        raise PolicyValidationError(f"{shape}; {'; '.join(detail)}")
    col = _require_int(value["col"], f"{where}.col", minimum=0)
    row = _require_int(value["row"], f"{where}.row", minimum=0)
    if bounds is not None:
        max_col, max_row = bounds
        if not (0 <= col < max_col and 0 <= row < max_row):
            raise PolicyValidationError(f"{where} is out of bounds for 0<=col<{max_col}, 0<=row<{max_row}")
    return (col, row)


@dataclass(frozen=True)
class ValidationContext:
    """Board/roster facts a policy is checked against.

    Stack 1 only strictly needs ``recruitable_defs``; the other fields exist
    so Stack 2 can reuse this same validator without a new schema registry.
    """
    recruitable_defs: frozenset[str] = field(default_factory=frozenset)
    friendly_unit_ids: frozenset[int] = field(default_factory=frozenset)
    recruiter_ids: frozenset[int] = field(default_factory=frozenset)
    village_coords: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    board_bounds: Optional[tuple[int, int]] = None


def validate_policy(policy: Any, context: ValidationContext, *,
                    known_live_scout_ids: Optional[list[int]] = None) -> dict[str, Any]:
    """Validate a ``set_policy.policy`` object per the frozen contract.

    Returns a normalized (deep-copied, key-order-independent) policy dict on
    success. Raises ``PolicyValidationError`` on any violation, before any
    caller-visible side effect. As of Stack 2 this is the full validator for
    every field -- ``scouts``, ``villages``, ``rally`` and ``holds`` are
    enforced here directly; there is no separate scope gate to apply
    afterward.
    """
    _require_keys(policy, POLICY_FIELDS, {"reserve_gold", "recruits"}, "policy")
    reserve_gold = _require_int(policy["reserve_gold"], "policy.reserve_gold", minimum=0)

    recruits_in = policy["recruits"]
    if not isinstance(recruits_in, list):
        raise PolicyValidationError("policy.recruits must be a list")
    if len(recruits_in) > MAX_RECRUIT_ENTRIES:
        raise PolicyValidationError(
            f"policy.recruits must have at most {MAX_RECRUIT_ENTRIES} entries")
    recruits: list[dict[str, Any]] = []
    for index, entry in enumerate(recruits_in):
        where = f"policy.recruits[{index}]"
        _require_keys(entry, RECRUIT_ENTRY_FIELDS, RECRUIT_ENTRY_FIELDS, where)
        def_id = entry["def_id"]
        if not isinstance(def_id, str) or not def_id:
            raise PolicyValidationError(f"{where}.def_id must be a non-empty string")
        if def_id not in context.recruitable_defs:
            raise PolicyValidationError(f"{where}.def_id is not recruitable: {def_id!r}")
        count = _require_int(entry["count"], f"{where}.count",
                              minimum=MIN_RECRUIT_COUNT, maximum=MAX_RECRUIT_COUNT)
        role = entry["role"]
        if role not in RECRUIT_ROLES:
            raise PolicyValidationError(f"{where}.role must be one of {RECRUIT_ROLES}")
        recruits.append({"def_id": def_id, "count": count, "role": role})

    scouts_in = policy.get("scouts", [])
    if not isinstance(scouts_in, list):
        raise PolicyValidationError("policy.scouts must be a list")
    if len(set(scouts_in)) != len(scouts_in):
        raise PolicyValidationError("policy.scouts must not contain duplicates")
    if len(scouts_in) > MAX_SCOUTS:
        raise PolicyValidationError(f"policy.scouts must have at most {MAX_SCOUTS} entries")
    scouts: list[int] = []
    for index, unit_id in enumerate(scouts_in):
        where = f"policy.scouts[{index}]"
        uid = _require_int(unit_id, where)
        if uid not in context.friendly_unit_ids:
            raise PolicyValidationError(f"{where} is not an existing friendly unit id: {uid}")
        if uid in context.recruiter_ids:
            raise PolicyValidationError(f"{where} cannot be a recruiter: {uid}")
        scouts.append(uid)
    new_scout_requests = sum(r["count"] for r in recruits if r["role"] == "scout")
    if len(scouts) + new_scout_requests > MAX_SCOUTS:
        raise PolicyValidationError(
            f"existing scouts plus requested new scouts exceed {MAX_SCOUTS}")

    villages_in = policy.get("villages", [])
    if not isinstance(villages_in, list):
        raise PolicyValidationError("policy.villages must be a list")
    if len(villages_in) > MAX_VILLAGES:
        raise PolicyValidationError(f"policy.villages must have at most {MAX_VILLAGES} entries")
    villages: list[dict[str, int]] = []
    seen_villages: set[tuple[int, int]] = set()
    for index, coord in enumerate(villages_in):
        where = f"policy.villages[{index}]"
        pair = _require_coord(coord, where, context.board_bounds)
        if pair in seen_villages:
            raise PolicyValidationError(f"{where} duplicates another village coordinate")
        if context.village_coords and pair not in context.village_coords:
            raise PolicyValidationError(f"{where} is not an existing village coordinate")
        seen_villages.add(pair)
        villages.append({"col": pair[0], "row": pair[1]})

    if villages and len(scouts) == 0 and new_scout_requests == 0:
        message = (
            "policy with villages must specify at least one scout or scout-role recruit"
        )
        if known_live_scout_ids:
            message += (
                "; known live prior scout ids you may explicitly retain: "
                + json.dumps(list(known_live_scout_ids), separators=(",", ":"))
                + " (not the only legal scouts)"
            )
        raise PolicyValidationError(message)

    rally_in = policy.get("rally")
    rally: Optional[dict[str, int]] = None
    if rally_in is not None:
        pair = _require_coord(rally_in, "policy.rally", context.board_bounds)
        rally = {"col": pair[0], "row": pair[1]}

    holds_in = policy.get("holds", [])
    if not isinstance(holds_in, list):
        raise PolicyValidationError("policy.holds must be a list")
    if len(set(holds_in)) != len(holds_in):
        raise PolicyValidationError("policy.holds must not contain duplicates")
    holds: list[int] = []
    scout_set = set(scouts)
    for index, unit_id in enumerate(holds_in):
        where = f"policy.holds[{index}]"
        uid = _require_int(unit_id, where)
        if uid not in context.friendly_unit_ids:
            raise PolicyValidationError(f"{where} is not an existing friendly unit id: {uid}")
        if uid in scout_set:
            raise PolicyValidationError(f"{where} overlaps a scout id: {uid}")
        holds.append(uid)

    return {
        "reserve_gold": reserve_gold,
        "recruits": recruits,
        "scouts": scouts,
        "villages": villages,
        "rally": rally,
        "holds": holds,
    }


def validate_routine_policy(policy: Any, context: ValidationContext, *,
                            known_live_scout_ids: Optional[list[int]] = None) -> dict[str, Any]:
    """Validate a ``set_policy.policy`` object against the full Stack 2 contract.

    Stack 1 additionally applied ``enforce_stack1_scope`` here to reject any
    non-empty ``scouts``/``villages``/``holds`` or non-null ``rally``. Stack 2
    enables those fields (plan section "Stack 2": "Enable the remaining
    policy fields"), so this is the single validation entry point for a
    routine policy installation.
    """
    return validate_policy(policy, context, known_live_scout_ids=known_live_scout_ids)


def effective_scout_ids(
    policy: Any,
    progress: Any,
    state: Optional[dict[str, Any]],
) -> list[int] | None:
    """Live scout IDs from installed policy plus committed progress.

    Returns None when roster or progress proof is missing (unknown, not empty).
    Filters to currently live friendlies on the authoritative roster.
    """
    if not isinstance(state, dict) or not isinstance(state.get("units"), list):
        return None
    progress_ids: list[int] | None = None
    if isinstance(progress, RoutineProgress):
        progress_ids = list(progress.scout_ids)
    elif isinstance(progress, dict) and "scout_ids" in progress:
        raw = progress.get("scout_ids")
        if not isinstance(raw, list):
            return None
        progress_ids = [item for item in raw if isinstance(item, int) and not isinstance(item, bool)]
    if progress_ids is None:
        return None
    policy_ids: list[int] = []
    if isinstance(policy, dict) and isinstance(policy.get("scouts"), list):
        policy_ids = [item for item in policy["scouts"]
                      if isinstance(item, int) and not isinstance(item, bool)]
    active = state.get("active_faction")
    live_friendly: set[int] = set()
    for unit in state["units"]:
        if not isinstance(unit, dict) or unit.get("faction") != active:
            continue
        unit_id = unit.get("id")
        if isinstance(unit_id, int) and not isinstance(unit_id, bool):
            live_friendly.add(unit_id)
    ordered: list[int] = []
    seen: set[int] = set()
    for unit_id in policy_ids + progress_ids:
        if unit_id in seen or unit_id not in live_friendly:
            continue
        seen.add(unit_id)
        ordered.append(unit_id)
    return ordered


# --------------------------------------------------------------------------
# Policy installation.
# --------------------------------------------------------------------------

def new_installation_id() -> str:
    """A durable internal installation id. The model never invents this."""
    return f"pol-{uuid.uuid4().hex[:12]}"


@dataclass
class PolicyInstallation:
    """A durably recorded policy installation, linked to its source request.

    A valid installation must be durably recorded before its first routine
    step (plan section 4). ``source_request_id`` links replay/attribution to
    the originating model request (or, for a fixed policy, to the checked-in
    file path) without inventing a synthetic model request.
    """
    installation_id: str
    policy: dict[str, Any]
    source_request_id: Optional[str] = None
    source_kind: str = "model"  # "model" or "fixed_file"

    def to_record(self) -> dict[str, Any]:
        return {
            "installation_id": self.installation_id,
            "policy": copy.deepcopy(self.policy),
            "source_request_id": self.source_request_id,
            "source_kind": self.source_kind,
        }


def install_policy(policy: dict[str, Any], *, source_request_id: Optional[str] = None,
                    source_kind: str = "model") -> PolicyInstallation:
    """Create a fresh installation. Replaces any previous installation's
    orders, assignments and remaining counts (the caller discards the old
    ``PolicyInstallation``/``RoutineProgress`` pair and starts a new one)."""
    return PolicyInstallation(
        installation_id=new_installation_id(),
        policy=copy.deepcopy(policy),
        source_request_id=source_request_id,
        source_kind=source_kind,
    )


# --------------------------------------------------------------------------
# Committed progress.
# --------------------------------------------------------------------------

@dataclass
class RoutineProgress:
    """Committed progress for one policy installation.

    Mirrors the ``progress`` object in the frozen ``routine_next`` query.
    Only ``commit_action`` (proven by the checkpoint acknowledgement path)
    may mutate ``recruited``/``scout_ids``/``scout_assignments``/
    ``completed_villages``/``last_proven_revision``. A ``progress_update``
    proposed by a query result is a proposal only, held by the caller until
    commitment is proven.

    ``last_proven_revision`` is the state revision at which the most recent
    commit was proven (plan section 6). It is persisted by
    ``to_runtime_record`` alongside the applied-step ledger, while
    ``to_query_progress`` deliberately exposes planning facts only.
    """
    installation_id: str
    # Counts are keyed by immutable policy queue index.  Definition ids are
    # deliberately absent from this map: two entries may request the same
    # definition with different roles.
    recruited: dict[int, int] = field(default_factory=dict)
    scout_assignments: list[dict[str, Any]] = field(default_factory=list)
    completed_villages: list[dict[str, Any]] = field(default_factory=list)
    scout_ids: list[int] = field(default_factory=list)
    policy_complete: bool = False
    last_proven_revision: Optional[int] = None
    # Recovery metadata only.  This is intentionally omitted by
    # ``to_query_progress`` so the planner never sees commit bookkeeping.
    applied_steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    policy: Optional[dict[str, Any]] = field(default=None, repr=False, compare=False)

    @classmethod
    def fresh(cls, installation_id: str, policy: Optional[dict[str, Any]] = None) -> "RoutineProgress":
        initial_scouts = list(policy.get("scouts", [])) if isinstance(policy, dict) else []
        return cls(installation_id=installation_id, scout_ids=initial_scouts,
                   policy=copy.deepcopy(policy) if policy is not None else None)

    def to_query_progress(self) -> dict[str, Any]:
        """Render the ``progress`` field of a ``routine_next`` query."""
        return {
            "recruited": [{"queue_index": queue_index, "done": done}
                          for queue_index, done in sorted(self.recruited.items())],
            "scout_assignments": copy.deepcopy(self.scout_assignments),
            "completed_villages": copy.deepcopy(self.completed_villages),
            "scout_ids": list(self.scout_ids),
            "installation_id": self.installation_id,
            "policy_complete": self.policy_complete,
        }

    def to_runtime_record(self) -> dict[str, Any]:
        """Serialize query progress plus recovery-only commit metadata."""
        record = self.to_query_progress()
        record["last_proven_revision"] = self.last_proven_revision
        record["applied_steps"] = copy.deepcopy(self.applied_steps)
        return record

    @classmethod
    def from_query_progress(cls, data: dict[str, Any],
                            policy: Optional[dict[str, Any]] = None) -> "RoutineProgress":
        if not isinstance(data, dict) or not isinstance(data.get("installation_id"), str):
            raise ValueError("progress is missing installation_id")
        recruited: dict[int, int] = {}
        for entry in data.get("recruited", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("queue_index"), int):
                raise ValueError("progress.recruited entries require queue_index")
            recruited[entry["queue_index"]] = int(entry["done"])
        return cls(
            installation_id=data["installation_id"],
            recruited=recruited,
            scout_assignments=copy.deepcopy(data.get("scout_assignments", [])),
            completed_villages=copy.deepcopy(data.get("completed_villages", [])),
            scout_ids=list(data.get("scout_ids", [])),
            last_proven_revision=data.get("last_proven_revision"),
            policy_complete=bool(data.get("policy_complete", False)),
            applied_steps=copy.deepcopy(data.get("applied_steps", {})),
            policy=copy.deepcopy(policy),
        )

    @classmethod
    def from_runtime_record(cls, data: dict[str, Any],
                            policy: Optional[dict[str, Any]] = None) -> "RoutineProgress":
        return cls.from_query_progress(data, policy=policy)

    def remaining(self, policy: dict[str, Any]) -> list[dict[str, Any]]:
        """The finite queue entries not yet fully recruited.

        A recruit ``count`` is a finite total for the policy installation,
        not a per-turn buy; this never re-issues an already-committed count.
        """
        remaining = []
        for queue_index, recruit in enumerate(policy.get("recruits", [])):
            done = self.recruited.get(queue_index, 0)
            left = recruit["count"] - done
            if left > 0:
                remaining.append({"queue_index": queue_index, "def_id": recruit["def_id"],
                                  "role": recruit["role"], "remaining": left})
        return remaining

    def _validate_effects(self, effects: Any) -> list[dict[str, Any]]:
        if not isinstance(effects, list):
            raise ValueError("committed progress requires an effects array")
        if self.policy is None:
            # A recovered record can still be safely replayed structurally,
            # but queue bounds/roles require the installation policy.
            queue_len = None
        else:
            queue_len = len(self.policy.get("recruits", []))
        normalized: list[dict[str, Any]] = []
        for index, effect in enumerate(effects):
            if not isinstance(effect, dict) or not isinstance(effect.get("kind"), str):
                raise ValueError(f"effects[{index}] must be an object with kind")
            kind = effect["kind"]
            if kind == "recruited":
                if set(effect) != {"kind", "queue_index", "unit_id"}:
                    raise ValueError("recruited effect requires queue_index and actual unit_id")
                queue_index = effect["queue_index"]
                unit_id = effect["unit_id"]
                if (isinstance(queue_index, bool) or not isinstance(queue_index, int)
                        or queue_index < 0 or (queue_len is not None and queue_index >= queue_len)):
                    raise ValueError("recruited effect has invalid queue_index")
                if isinstance(unit_id, bool) or not isinstance(unit_id, int) or unit_id <= 0:
                    raise ValueError("recruited effect requires a positive actual unit_id")
                normalized.append({"kind": kind, "queue_index": queue_index, "unit_id": unit_id})
            elif kind == "scout_assigned":
                if set(effect) != {"kind", "unit_id", "col", "row"}:
                    raise ValueError("scout_assigned effect requires unit_id, col and row")
                if any(isinstance(effect[key], bool) or not isinstance(effect[key], int)
                       for key in ("unit_id", "col", "row")):
                    raise ValueError("scout_assigned coordinates and unit_id must be integers")
                normalized.append({key: effect[key] for key in ("kind", "unit_id", "col", "row")})
            elif kind == "completed_village":
                if set(effect) != {"kind", "col", "row"}:
                    raise ValueError("completed_village effect requires col and row")
                if any(isinstance(effect[key], bool) or not isinstance(effect[key], int)
                       for key in ("col", "row")):
                    raise ValueError("completed_village coordinates must be integers")
                normalized.append({key: effect[key] for key in ("kind", "col", "row")})
            elif kind == "policy_completed":
                if set(effect) != {"kind"}:
                    raise ValueError("policy_completed effect has unknown fields")
                normalized.append({"kind": kind})
            else:
                raise ValueError(f"unknown committed progress effect: {kind!r}")
        return normalized

    def commit_action(self, committed_update: dict[str, Any], *, installation_id: str,
                      batch_id: str, state_revision: int) -> bool:
        """Adopt a proposed ``progress_update`` after the action commits.

        This is the ONLY method that mutates persisted progress. Callers
        must only invoke it after the corresponding action has passed the
        existing driver/checkpoint acknowledgement protocol -- never merely
        because a query proposed it. This is the crash-safety requirement.

        The batch identity and state revision are mandatory.  Duplicate
        identity/payload/revision is a no-op; reusing identity with different
        evidence is a conflict.  All validation happens before mutation.
        """
        if installation_id != self.installation_id:
            raise ValueError("committed progress belongs to a foreign installation")
        if not isinstance(batch_id, str) or not batch_id:
            raise ValueError("committed progress requires batch_id")
        if isinstance(state_revision, bool) or not isinstance(state_revision, int) or state_revision < 0:
            raise ValueError("committed progress requires a non-negative state_revision")
        if not isinstance(committed_update, dict) or set(committed_update) != {"effects"}:
            raise ValueError("committed progress requires exactly an effects array")
        effects = self._validate_effects(committed_update["effects"])
        digest = hashlib.sha256(json.dumps(effects, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        prior = self.applied_steps.get(batch_id)
        if prior is not None:
            if prior.get("digest") == digest and prior.get("state_revision") == state_revision:
                return False
            raise ValueError("committed batch_id was reused with conflicting progress evidence")
        if self.last_proven_revision is not None and state_revision < self.last_proven_revision:
            raise ValueError("committed progress state_revision moved backwards")

        # Validate cross-effect relationships before changing any field.
        known_scouts = set(self.scout_ids)
        recruited_in_batch: dict[int, int] = {}
        recruited_ids = set()
        for effect in effects:
            if effect["kind"] == "recruited":
                if self.policy is None:
                    raise ValueError("recruited progress requires the installation policy")
                queue_index, unit_id = effect["queue_index"], effect["unit_id"]
                if unit_id in recruited_ids or unit_id in self.scout_ids:
                    raise ValueError("recruited effect repeats an actual unit_id")
                recruited_ids.add(unit_id)
                recruited_in_batch[queue_index] = recruited_in_batch.get(queue_index, 0) + 1
                if self.policy is not None:
                    entry = self.policy["recruits"][queue_index]
                    if self.recruited.get(queue_index, 0) + recruited_in_batch[queue_index] > entry["count"]:
                        raise ValueError("committed recruitment exceeds the policy queue count")
                    if entry["role"] == "scout":
                        known_scouts.add(unit_id)
        for effect in effects:
            if effect["kind"] == "scout_assigned" and effect["unit_id"] not in known_scouts:
                raise ValueError("scout_assigned effect references an unknown scout")
            elif effect["kind"] == "scout_assigned" and self.policy is not None:
                if {"col": effect["col"], "row": effect["row"]} not in self.policy.get("villages", []):
                    raise ValueError("scout_assigned effect references an unselected village")
            elif effect["kind"] == "completed_village" and self.policy is not None:
                if {"col": effect["col"], "row": effect["row"]} not in self.policy.get("villages", []):
                    raise ValueError("completed_village effect references an unselected village")
        if any(effect["kind"] == "policy_completed" for effect in effects) and self.policy is not None:
            if self.remaining(self.policy):
                # Include this batch's recruit effects when determining whether
                # completion is proven at the same boundary.
                remaining_after = [entry for entry in self.remaining(self.policy)
                                   if self.recruited.get(entry["queue_index"], 0)
                                   + recruited_in_batch.get(entry["queue_index"], 0) < self.policy["recruits"][entry["queue_index"]]["count"]]
                if remaining_after:
                    raise ValueError("policy_completed requires all recruitment objectives complete")

        # Apply atomically after every check succeeded.
        for effect in effects:
            kind = effect["kind"]
            if kind == "recruited":
                queue_index, unit_id = effect["queue_index"], effect["unit_id"]
                self.recruited[queue_index] = self.recruited.get(queue_index, 0) + 1
                if self.policy["recruits"][queue_index]["role"] == "scout":
                    if unit_id not in self.scout_ids:
                        self.scout_ids.append(unit_id)
            elif kind == "scout_assigned":
                self.scout_assignments = [a for a in self.scout_assignments
                                          if a.get("unit_id") != effect["unit_id"]]
                self.scout_assignments.append({"unit_id": effect["unit_id"],
                                               "col": effect["col"], "row": effect["row"]})
            elif kind == "completed_village":
                if not any(v.get("col") == effect["col"] and v.get("row") == effect["row"]
                           for v in self.completed_villages):
                    self.completed_villages.append({"col": effect["col"], "row": effect["row"]})
            elif kind == "policy_completed":
                self.policy_complete = True
        self.last_proven_revision = state_revision
        self.applied_steps[batch_id] = {"digest": digest, "state_revision": state_revision}
        return True


# --------------------------------------------------------------------------
# routine_next query construction.
# --------------------------------------------------------------------------

def build_routine_query(state_revision: int, policy: dict[str, Any],
                         progress: RoutineProgress) -> dict[str, Any]:
    """Build the frozen ``routine_next`` driver query."""
    return {
        "action": "Query",
        "what": "routine_next",
        "state_revision": state_revision,
        "policy": copy.deepcopy(policy),
        "progress": progress.to_query_progress(),
    }


@dataclass
class RoutineException:
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoutineActionResult:
    action: dict[str, Any]
    progress_update: dict[str, Any]
    reason: str
    independent_move: Optional[dict[str, Any]] = None


@dataclass
class RoutineFinishResult:
    progress_update: dict[str, Any]
    reason: str = "no_remaining_routine_steps"

    def __eq__(self, other: Any) -> bool:
        # Keep the small historical sentinel comparison useful to callers
        # while carrying finish-boundary proof effects for Stack 2.
        return other == "finish" or (
            isinstance(other, RoutineFinishResult)
            and self.progress_update == other.progress_update
            and self.reason == other.reason)


def parse_routine_result(body: dict[str, Any]) -> Any:
    """Parse the ``body.result`` of a ``routine_next`` reply.

    Returns a ``RoutineActionResult``, the string ``"finish"``, or a
    ``RoutineException``. Raises ``ValueError`` for a malformed reply; the
    driver contract, not this parser, is the source of truth for what a
    well-formed reply looks like, but the client must not trust an
    unrecognized shape.
    """
    if not isinstance(body, dict) or "result" not in body:
        raise ValueError("routine_next reply is missing result")
    kind = body["result"]
    if kind == "action":
        if "action" not in body or "progress_update" not in body or "reason" not in body:
            raise ValueError("routine_next action result is missing required fields")
        return RoutineActionResult(
            action=body["action"],
            progress_update=body["progress_update"],
            reason=body["reason"],
            independent_move=body.get("independent_move"),
        )
    if kind == "finish":
        if body.get("reason") not in {"no_remaining_routine_steps", "objectives_complete"}:
            raise ValueError("routine_next finish result has an unexpected reason")
        update = body.get("progress_update", {"effects": []})
        if not isinstance(update, dict) or set(update) != {"effects"}:
            raise ValueError("routine_next finish progress_update must contain effects only")
        return RoutineFinishResult(progress_update=update)
    if kind == "exception":
        if "reason" not in body:
            raise ValueError("routine_next exception result is missing reason")
        return RoutineException(reason=body["reason"], evidence=body.get("evidence", {}))
    raise ValueError(f"routine_next reply has unknown result kind: {kind!r}")


def find_unreconstructable_routine_batch(parent_records: list[dict[str, Any]]) -> Optional[str]:
    """Detect a routine batch the checkpoint proves committed with no progress record.

    Plan section 6: "If the checkpoint has advanced but its matching policy
    progress cannot be reconstructed, interrupt with explicit unknown
    action-boundary status. Do not reset to the original recruitment list."

    A routine submission's engine-side commitment (a durable ``checkpoint_ref``
    record, mirrored by a ``batch_committed`` record carrying the same
    ``batch_id``) is written strictly *before* the corresponding
    ``routine_progress_committed`` confirmation of what that step actually
    changed (see the client's checkpoint handling: the checkpoint is proof of
    engine-side commitment; the progress update is only adopted, and its
    confirmation record only written, immediately afterward). A crash in
    exactly that window leaves a batch with proven engine commitment but no
    record of the progress it produced -- replaying the checkpoint's routine
    action would double-apply it (its cause is already reflected in engine
    state), and simply ignoring it would silently under-count a completed
    step. Neither is safe, so this is surfaced as unreconstructable instead.

    A later ``policy_installed`` record clears any earlier pending batch: a
    fresh installation discards all previous orders, assignments and
    remaining counts (plan section 4), so a batch pending under a
    *superseded* installation is moot.

    Returns the ``batch_id`` of the unreconstructable routine batch, or
    ``None`` if none exists (either no routine batch is pending, or the
    pending one never proved committed and can simply be dropped -- a
    submission that crashed before its checkpoint is safe to treat as never
    having happened, matching "a duplicate pending step is never applied
    twice" without needing special handling here).
    """
    pending_batch_id: Optional[str] = None
    for record in parent_records:
        if record.get("type") == "forwarded_orders" and record.get("source") == "routine":
            orders = record.get("orders") or []
            is_boundary = any(isinstance(order, dict)
                              and order.get("action") in ("FinishWithGreedy", "Resign")
                              for order in orders)
            pending_batch_id = None if is_boundary else record.get("batch_id")
        elif record.get("type") in ("routine_progress_committed", "policy_installed"):
            pending_batch_id = None
    if pending_batch_id is None:
        return None
    # ``checkpoint_ref`` is emitted before the acknowledgement and before the
    # legacy ``batch_committed`` marker.  It is therefore the authoritative
    # commitment proof for a process that dies in that small window.
    committed_batch_ids = {r.get("batch_id") for r in parent_records
                           if r.get("type") in ("batch_committed", "checkpoint_ref")}
    return pending_batch_id if pending_batch_id in committed_batch_ids else None


def pending_routine_commit(parent_records: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Return the latest checkpoint-proven routine proposal awaiting adoption.

    The returned record is the durable ``checkpoint_ref`` itself.  Stack 2
    callers use its persisted ``progress_update`` and pre-step identity to
    reconstruct a commit from the checkpoint's authoritative state.  A
    proposal without a checkpoint is deliberately absent: it may have been
    rejected or never reached the engine and is safe to discard on resume.
    Finish batches are included because their ``policy_completed`` effect also
    needs a durable progress record, while the older unreconstructable helper
    intentionally excludes them from interruption checks.
    """
    installed: Optional[str] = None
    pending: Optional[dict[str, Any]] = None
    for record in parent_records:
        kind = record.get("type")
        if kind == "policy_installed":
            installed = record.get("installation_id")
            pending = None
        elif kind == "forwarded_orders" and record.get("source") == ROUTINE_ORIGIN:
            pending = None
            if isinstance(record.get("batch_id"), str):
                pending = {
                    "batch_id": record["batch_id"],
                    "installation_id": record.get("installation_id", installed),
                    "progress_update": record.get("progress_update"),
                    "routine_finish": bool(record.get("routine_finish", False)),
                    "pre_step_unit_ids": record.get("pre_step_unit_ids"),
                    "pre_step_village_owners": record.get("pre_step_village_owners"),
                }
        elif kind == "checkpoint_ref" and pending is not None:
            if record.get("batch_id") == pending.get("batch_id"):
                result = dict(record)
                for key in ("installation_id", "progress_update", "routine_finish",
                            "pre_step_unit_ids", "pre_step_village_owners"):
                    if key in pending and key not in result:
                        result[key] = pending[key]
                if "routine_finish" in result:
                    result["finish"] = bool(result["routine_finish"])
                pending = result
        elif kind == "routine_progress_committed":
            if pending is not None and record.get("batch_id") == pending.get("batch_id"):
                pending = None
    return pending if isinstance(pending, dict) and pending.get("type") == "checkpoint_ref" else None


# --------------------------------------------------------------------------
# Internal orders envelope.
# --------------------------------------------------------------------------

def build_orders_envelope(orders: list[dict[str, Any]], source_state_revision: int) -> dict[str, Any]:
    """Construct the internal orders envelope.

    Only client code ever calls this. ``origin`` is always set to
    ``"routine"`` here, unconditionally -- a caller cannot override it, and
    a model response is never consulted for this value. This is the
    enforcement point for "a model response must never be able to set
    origin".
    """
    return {"orders": copy.deepcopy(orders), "origin": ROUTINE_ORIGIN,
            "source_state_revision": source_state_revision}


def _scan_for_origin_key(value: Any, path: str = "$") -> Optional[str]:
    """Recursively find a forbidden ``origin`` key anywhere in a model reply."""
    if isinstance(value, dict):
        if "origin" in value:
            return f"{path}.origin"
        for key, sub in value.items():
            found = _scan_for_origin_key(sub, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, sub in enumerate(value):
            found = _scan_for_origin_key(sub, f"{path}[{index}]")
            if found:
                return found
    return None


# --------------------------------------------------------------------------
# Model response parsing (strict discriminated union on "kind").
# --------------------------------------------------------------------------

@dataclass
class SetPolicyResponse:
    policy: dict[str, Any]


@dataclass
class ActResponse:
    actions: list[dict[str, Any]]
    finish_turn: bool


@dataclass
class ChooseResponse:
    decision_id: str
    option_ids: list[str]
    finish_turn: bool = False


@dataclass
class FinishTurnResponse:
    pass


@dataclass
class ResignResponse:
    pass


def is_redundant_finish_turn(obj: Any) -> bool:
    """True for the one accepted extra-field finish shape, before normalization."""
    return (
        isinstance(obj, dict)
        and obj.get("kind") == "finish_turn"
        and set(obj) == FINISH_TURN_REDUNDANT_KEYS
        and obj.get("finish_turn") is True
    )


def _finish_turn_parse_error(obj: dict[str, Any]) -> str:
    canonical = f"canonical finish object is {CANONICAL_FINISH_TURN_JSON}"
    extra = set(obj) - FINISH_TURN_KEYS
    if extra == {"finish_turn"}:
        value = obj.get("finish_turn")
        if value is False:
            return (
                "standalone finish_turn must omit finish_turn or set it to JSON "
                f"boolean true, not false; {canonical}"
            )
        return (
            "standalone finish_turn extra field must be the JSON boolean true; "
            f"{canonical}"
        )
    if extra:
        return (
            f"response has unknown key(s): {', '.join(sorted(str(key) for key in extra))}; "
            f"{canonical}"
        )
    return f"malformed finish_turn response; {canonical}"


def _parse_finish_turn_response(obj: dict[str, Any]) -> FinishTurnResponse:
    keys = set(obj)
    if keys == FINISH_TURN_KEYS or is_redundant_finish_turn(obj):
        return FinishTurnResponse()
    raise ModelResponseError(_finish_turn_parse_error(obj))


def strategy_repair_guidance(error: BaseException, decoded: Any | None = None) -> str:
    """Kind-specific repair text generated from the shared response-shape table."""
    message = f"The previous response was invalid: {error}."
    kind = decoded.get("kind") if isinstance(decoded, dict) else None
    if kind == "finish_turn":
        message += f" The canonical finish object is {CANONICAL_FINISH_TURN_JSON}."
    elif kind in STRATEGY_RESPONSE_SHAPES:
        allowed = ",".join(sorted(STRATEGY_RESPONSE_SHAPES[kind]))
        message += f" A valid {kind} response uses exactly these keys: {allowed}."
    message += " Return one corrected strategy response now with only the defined fields."
    return message


def parse_model_response(obj: Any) -> Any:
    """Strictly parse a model response into one of the response forms.

    Raises ``ModelResponseError`` for anything outside the exact contract,
    including an embedded ``origin`` key anywhere in the payload -- a model
    response must never be able to set that field (plan section 5).
    """
    if not isinstance(obj, dict):
        raise ModelResponseError("model response must be a JSON object")
    origin_path = _scan_for_origin_key(obj)
    if origin_path is not None:
        raise ModelResponseError(
            f"model response must not set 'origin' (found at {origin_path}); "
            "origin is set only by client code constructing the orders envelope")
    if "decisions" in obj:
        raise ModelResponseError(
            "strategy mode responses must not contain 'decisions'; that is the "
            "old full-annotation array and is absent from this mode")
    kind = obj.get("kind")
    if kind not in RESPONSE_KINDS:
        raise ModelResponseError(
            f"response 'kind' must be one of {RESPONSE_KINDS}, got {kind!r}")
    try:
        if kind == "set_policy":
            _require_keys(obj, SET_POLICY_KEYS, SET_POLICY_KEYS, "response")
            if not isinstance(obj["policy"], dict):
                raise ModelResponseError("response.policy must be an object")
            return SetPolicyResponse(policy=obj["policy"])
        if kind == "act":
            _require_keys(obj, ACT_KEYS, ACT_KEYS, "response")
            actions = obj["actions"]
            if not isinstance(actions, list) or not (1 <= len(actions) <= 16):
                raise ModelResponseError("response.actions must have between 1 and 16 entries")
            for index, action in enumerate(actions):
                if not isinstance(action, dict):
                    raise ModelResponseError(f"response.actions[{index}] must be an object")
                action_kind = action.get("action")
                if action_kind in ("Resign", "EndTurn", "FinishWithGreedy", "DoneWithImportantMoves"):
                    raise ModelResponseError(
                        f"response.actions[{index}] must not embed a boundary/resign action: {action_kind!r}")
            finish_turn = obj["finish_turn"]
            if not isinstance(finish_turn, bool):
                raise ModelResponseError("response.finish_turn must be a boolean")
            return ActResponse(actions=list(actions), finish_turn=finish_turn)
        if kind == "choose":
            if "option_id" in obj:
                raise ModelResponseError(
                    "response.option_id is not accepted; use option_ids with 1 to 3 distinct issued IDs")
            _require_keys(obj, CHOOSE_KEYS, CHOOSE_KEYS, "response")
            decision_id = obj["decision_id"]
            if not isinstance(decision_id, str) or not decision_id.strip():
                raise ModelResponseError("response.decision_id must be a non-empty string")
            option_ids = obj["option_ids"]
            if not isinstance(option_ids, list):
                raise ModelResponseError("response.option_ids must be a list")
            if not (1 <= len(option_ids) <= 3):
                raise ModelResponseError("response.option_ids must contain 1 to 3 entries")
            parsed_ids: list[str] = []
            for index, option_id in enumerate(option_ids):
                if not isinstance(option_id, str) or not option_id.strip():
                    raise ModelResponseError(
                        f"response.option_ids[{index}] must be a non-empty string")
                parsed_ids.append(option_id)
            if len(set(parsed_ids)) != len(parsed_ids):
                raise ModelResponseError("response.option_ids must be distinct")
            finish_turn = obj["finish_turn"]
            if not isinstance(finish_turn, bool):
                raise ModelResponseError("response.finish_turn must be a boolean")
            return ChooseResponse(
                decision_id=decision_id, option_ids=parsed_ids, finish_turn=finish_turn)
        if kind == "finish_turn":
            return _parse_finish_turn_response(obj)
        # kind == "resign"
        _require_keys(obj, RESIGN_KEYS, RESIGN_KEYS, "response")
        return ResignResponse()
    except PolicyValidationError as exc:
        raise ModelResponseError(str(exc)) from exc


# --------------------------------------------------------------------------
# Fixed-policy install (Stack 4's ``strategy_fixed`` treatment; the flag is
# wired now per Stack 1 scope). Reading the file creates no request or
# usage row and starts no backend.
# --------------------------------------------------------------------------

def static_recruitable_defs(units_dir: str = "data/units") -> frozenset[str]:
    """Enumerate unit definition ids known to the static content tree.

    This is a Stack 1 approximation for ``--strategy-policy``'s pre-flight
    check only: it answers "does this unit definition exist at all", not the
    engine-authoritative "is it recruitable right now for this faction/
    leader/castle" -- that remains the driver's ``recruit_options`` query and
    the routine executor's job once the Rust half exists. It exists so
    reading a fixed policy file needs no live driver process, matching "no
    backend started, zero model responses"; it must never be treated as a
    substitute for engine recruitment legality once a real game runs.
    """
    import tomllib
    from pathlib import Path

    root = Path(units_dir)
    ids: set[str] = set()
    if not root.is_dir():
        return frozenset()
    for toml_path in root.rglob("*.toml"):
        if toml_path.name == "sprite.toml":
            continue
        try:
            with toml_path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        unit_id = data.get("id")
        if isinstance(unit_id, str) and unit_id:
            ids.add(unit_id)
    return frozenset(ids)


def load_checked_in_policy(path: str, context: ValidationContext) -> dict[str, Any]:
    """Read and strictly validate an exact checked-in policy file.

    Pure function: no model backend, request, or usage row is created as a
    side effect of calling this. Raises ``PolicyValidationError`` (or
    ``ValueError``/``OSError`` for file/JSON problems) without partially
    installing anything.
    """
    import json
    from pathlib import Path

    text = Path(path).read_text()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PolicyValidationError(f"--strategy-policy file is not valid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PolicyValidationError("--strategy-policy file must contain a JSON object")
    if set(obj.keys()) == {"kind", "policy"}:
        if obj.get("kind") != "set_policy":
            raise PolicyValidationError(
                "--strategy-policy file 'kind' must be 'set_policy' when present")
        policy_obj = obj["policy"]
    else:
        policy_obj = obj
    return validate_routine_policy(policy_obj, context)


# --------------------------------------------------------------------------
# Response rendering (compact model briefs).
# --------------------------------------------------------------------------

def _strategy_context(state: Optional[dict[str, Any]], *, recruit_options: Any = None,
                      remaining: Any = None, changes: Any = None,
                      policy: Any = None,
                      progress: Any = None,
                      exception: Optional[RoutineException] = None,
                      allowed_kinds: Optional[Iterable[str]] = None) -> str:
    """Render bounded, revision-pinned facts after the stable contract."""
    if not isinstance(state, dict):
        return ""
    terrain = state.get("terrain")
    villages = [
        {key: tile.get(key, "unknown") for key in ("col", "row", "owner")}
        for tile in terrain
        if isinstance(tile, dict) and tile.get("terrain_id") == "village"
    ] if isinstance(terrain, list) else "unknown"
    units = state.get("units")
    # A missing roster is unknown; an empty list is an authoritative empty
    # roster.  Keep that distinction in both the JSON facts and the readable
    # index below.
    compact_units: list[dict[str, Any]] | str = "unknown"
    if isinstance(units, list):
        compact_units = []
        for unit in units:
            if not isinstance(unit, dict):
                continue
            compact_units.append({key: unit.get(key, "unknown") for key in
                             ("id", "faction", "def_id", "col", "row", "hp", "max_hp",
                              "moved", "attacked", "movement", "can_recruit")})
    facts: dict[str, Any] = {
        "revision": state.get("state_revision", "unknown"),
        "turn": state.get("turn", "unknown"),
        "active_faction": state.get("active_faction", "unknown"),
        "phase": state.get("time_of_day", "unknown"),
        "map": {key: state.get(key, "unknown") for key in ("cols", "rows")},
        "gold": state.get("gold", "unknown"),
        "terrain": ([{key: tile.get(key, "unknown") for key in ("col", "row", "terrain_id", "owner")}
                     for tile in terrain] if isinstance(terrain, list) else "unknown"),
        "units": compact_units,
    }
    if recruit_options is not None:
        facts["recruit_options"] = recruit_options
    if remaining is not None:
        facts["remaining"] = remaining
    if policy is not None:
        # The exception request is stateless: repeat the installed objectives
        # and assignments instead of relying on the initial policy response.
        facts["installed_policy"] = policy
        live_scouts = effective_scout_ids(policy, progress, state)
        facts["effective_scout_ids"] = live_scouts if live_scouts is not None else "unknown"
    elif progress is not None:
        live_scouts = effective_scout_ids(policy, progress, state)
        facts["effective_scout_ids"] = live_scouts if live_scouts is not None else "unknown"
    if changes is not None:
        facts["changes"] = changes
    if exception is not None:
        facts["exception"] = {"reason": exception.reason, "evidence": exception.evidence}
        surface = state.get("tactical_surface")
        if isinstance(surface, dict):
            facts["threats"] = surface.get("threats", "unknown")
            facts["exposure"] = surface.get("exposure", "unknown")
            facts["local_options"] = surface.get("turn_options", "unknown")
    body = json.dumps(facts, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    village_text = ",".join(
        f"{item.get('col', 'unknown')},{item.get('row', 'unknown')}"
        for item in villages if isinstance(item, dict)) or "unknown"
    unit_text = " ".join(
        f"id={item.get('id', 'unknown')} faction={item.get('faction', 'unknown')} "
        f"pos={item.get('col', 'unknown')},{item.get('row', 'unknown')} def={item.get('def_id', 'unknown')} "
        f"moved={item.get('moved', 'unknown')} attacked={item.get('attacked', 'unknown')} "
        f"movement={item.get('movement', 'unknown')}"
        for item in compact_units if isinstance(compact_units, list)) or "unknown"
    allowed_str = (", ".join(allowed_kinds) if allowed_kinds is not None
                   else "set_policy, act, finish_turn, or resign")
    return ("\nSTRATEGY_CONTEXT_UNTRUSTED_DATA_BEGIN\nstate_revision=" +
            str(state.get("state_revision", "unknown")) + "\nMAP_VILLAGES=" +
            village_text + "\nMAP_UNITS=" + unit_text + "\n" + body +
            "\nSTRATEGY_CONTEXT_UNTRUSTED_DATA_END\n"
            f"Respond with exactly one of {allowed_str}. Output one complete JSON "
            "object only: no prose, markdown fences, or text before or after the JSON.")


strategy_context = _strategy_context


def _strategy_contract(recruitable_defs: Iterable[str] = ()) -> str:
    """Stable prefix shared by initial and exception requests."""
    defs = ", ".join(sorted(recruitable_defs)) or "see current recruit_options"
    return (
        "Strategy objective: defeat the enemy recruiter while keeping your recruiter alive; "
        "at your own finish, village ownership and income are engine facts. "
        "Routine code executes validated recruitment, scout, village, rally and no-sweep finish steps; "
        "it pauses on typed exceptions such as contact, promotion, blocked recruitment, or unavailable facts.\n"
        "In LIVE_STATE and the current facts, moved and attacked are authoritative engine flags. "
        "movement is the unit's engine movement allowance, not remaining points and not a count of legal moves; "
        "a missing field stays unknown and must not be treated as false or zero. A routine result of finish is a "
        "finishing boundary and does not imply additional legal movement actions.\n"
        "Return exactly one complete JSON object with kind set_policy, act, choose, finish_turn, or resign; "
        "output no prose, markdown fences, or text before or after the JSON. "
        "A set_policy replaces the prior installation. Its policy has reserve_gold (integer), "
        "recruits (0-8 ordered entries, each exact def_id/count/role with count 1-32 and role scout or army), "
        "scouts (0-8 existing friendly integer IDs; existing plus new scout recruits <=8), "
        "villages (0-4 exact integer {col,row} objects), rally (one in-bounds integer {col,row} object or null), and "
        "holds (existing friendly integer IDs, with no scout overlap). Recruitable definitions: " + defs + ".\n"
        "col and row are zero-based integer offsets. Syntax examples, not recommended objectives: "
        '"villages":[' + CANONICAL_COORD_JSON + '] and "rally":' + CANONICAL_RALLY_JSON + ". "
        "A two-element array is not a coordinate. "
        'Shape-only set_policy example (choose live definitions/IDs and nonempty objectives when needed): '
        '{"kind":"set_policy","policy":{"reserve_gold":0,"recruits":[],"scouts":[],"villages":[],"rally":null,"holds":[]}}\n'
        "An act has ordinary engine actions and finish_turn true or false on an ordinary state; "
        "final_only requires true. The finish_turn boolean belongs to act and choose only. "
        "A choose selects 1 to 3 distinct issued option_ids (at most one per actor; array order is execution order): "
        '{"kind":"choose","decision_id":"dec-issued","option_ids":["u6-relocate-2","u7-relocate-1"],"finish_turn":false}. '
        "A standalone finish is exactly " + CANONICAL_FINISH_TURN_JSON +
        "; do not add finish_turn or other keys. "
        "Actions cannot contain a boundary or origin. Supported shapes include "
        '{"action":"Move","unit_id":1,"col":2,"row":3}, '
        '{"action":"Attack","attacker_id":1,"defender_id":2}, '
        '{"action":"Recruit","def_id":"Skeleton","col":2,"row":3}, '
        '{"action":"Advance","unit_id":1,"target_index":0}, and '
        '{"action":"Engage","target_id":2,"steps":[{"attacker_id":1,"col":2,"row":3}]}; '
        "replace example IDs/definition with values in LIVE_STATE and current options.\n"
        "When enabled, optional read-only inspections use one of these complete objects: "
        '{"tool":"inspect_target","unit_id":1,"purpose":"check target"}, '
        '{"tool":"inspect_targets","unit_ids":[1],"purpose":"check targets"}, '
        '{"tool":"inspect_units","unit_ids":[1],"purpose":"check unit"}, or '
        '{"tool":"inspect_hex","col":2,"row":3,"phase":"current"}. '
        "Use inspections only for a current revision fact; return a strategy response after the result.\n"
    )


def render_policy_brief(reserve_gold_default: int, recruitable_defs: Iterable[str], *,
                        state: Optional[dict[str, Any]] = None,
                        recruit_options: Any = None,
                        remaining: Any = None,
                        changes: Any = None,
                        policy: Any = None,
                        progress: Any = None) -> str:
    """Render the stable strategy contract and compact current facts."""
    return (
        _strategy_contract(recruitable_defs) +
        "Select the initial policy with {\"kind\":\"set_policy\",\"policy\":{...}}; "
        "each recruit count is a finite total for this installation, and scouts/villages/holds "
        "must satisfy the current engine limits."
        + _strategy_context(state, recruit_options=recruit_options,
                            remaining=remaining, changes=changes,
                            policy=policy, progress=progress)
    )


def _capacity_relief_line(evidence: Any) -> str:
    """One short castle-capacity explanation. Unknown is not unsafe or unreachable."""
    if not isinstance(evidence, dict) or evidence.get("cause") != "no_placement_hex":
        return ""
    relief = evidence.get("capacity_relief")
    if not isinstance(relief, dict):
        return ""
    status = relief.get("status", "unknown")
    if status not in ("no_rally", "no_eligible_unit", "no_route_endpoint",
                      "no_safe_endpoint", "mixed_blockers", "unknown"):
        status = "unknown"
    rally = relief.get("rally", "unknown") if "rally" in relief else "unknown"
    if rally is None:
        rally_text = "none"
    elif isinstance(rally, dict):
        rally_text = f"{rally.get('col', 'unknown')},{rally.get('row', 'unknown')}"
    else:
        rally_text = "unknown"
    ids = relief.get("eligible_unit_ids")
    if not isinstance(ids, list):
        ids = relief.get("checked_unit_ids")
    id_text = ",".join(str(item) for item in ids) if isinstance(ids, list) and ids else "none"
    if status == "no_rally":
        return (
            f"Castle recruitment has no placement hex. No rally is installed, so ordinary army "
            f"travel cannot free a tile. Eligible castle units: {id_text}."
        )
    if status == "no_eligible_unit":
        return (
            f"Castle recruitment has no placement hex. Rally {rally_text} has no eligible unmoved "
            "army unit on a recruiting castle tile (scouts, holds, and recruiters stay put)."
        )
    if status == "no_route_endpoint":
        return (
            f"Castle recruitment has no placement hex. Ordinary army travel toward rally "
            f"{rally_text} found no usable route endpoint for units {id_text}. Changing the rally "
            "is an available set_policy response."
        )
    if status == "no_safe_endpoint":
        return (
            f"Castle recruitment has no placement hex. Travel toward rally {rally_text} found "
            f"endpoints for units {id_text} that were not safe."
        )
    if status == "mixed_blockers":
        return (
            f"Castle recruitment has no placement hex. Ordinary army travel toward rally "
            f"{rally_text} was blocked by mixed per-unit causes for units {id_text}."
        )
    return (
        f"Castle recruitment has no placement hex. Capacity relief is unknown. Rally {rally_text}; "
        f"units {id_text}."
    )


def render_exception_brief(exception: RoutineException, remaining: list[dict[str, Any]], *,
                           state: Optional[dict[str, Any]] = None,
                           recruit_options: Any = None,
                           changes: Any = None,
                           policy: Any = None,
                           progress: Any = None) -> str:
    """Render a typed exception with current revision-pinned facts."""
    relief = ""
    if exception.reason == "recruitment_blocked":
        line = _capacity_relief_line(exception.evidence)
        if line:
            relief = line + " "
    return (
        _strategy_contract() +
        relief +
        "Routine execution paused on a typed engine exception. The exception facts and current state "
        "below are authoritative; missing values remain unknown. set_policy replaces the installation "
        "and cancels its old remaining work."
        + _strategy_context(state, recruit_options=recruit_options,
                            remaining=remaining, changes=changes,
                            policy=policy, progress=progress,
                            exception=exception)
    )


# --------------------------------------------------------------------------
# Turn orchestration, driven against a scripted/fake exchange and backend.
#
# This loop is deliberately small and is the piece both Stack 1's tests and
# (once the Rust `routine_next` query exists) the real client can drive: it
# only depends on three caller-supplied callables, never on a live process.
# --------------------------------------------------------------------------

class TurnBudgetExhausted(RuntimeError):
    """The configured per-turn query or model-response budget was hit."""


@dataclass
class StrategyTurnOutcome:
    status: str  # "finished", "acted", "resigned", "budget_exhausted"
    reason: Optional[str] = None
    evidence: dict[str, Any] = field(default_factory=dict)
    model_responses: int = 0
    committed_actions: int = 0


def run_scripted_strategy_turn(
    *,
    exchange,
    request_model,
    context: ValidationContext,
    installation: PolicyInstallation,
    progress: RoutineProgress,
    state_revision: int,
    max_queries: int = 256,
    max_model_responses: int = 8,
) -> StrategyTurnOutcome:
    """Drive one controlled turn of routine execution to a boundary.

    ``exchange(query_dict) -> response_dict`` sends a ``{"action":"Query",...}``
    request and returns the raw ``{"ok":..., "body":...}`` reply, matching the
    existing driver protocol used throughout ``tools/llm_client.py``.

    ``request_model(brief_text) -> raw_dict`` calls the model backend and
    returns its parsed JSON object (already decoded from text) for
    ``parse_model_response``. Typed exceptions, including contact, reach the
    model; this helper does not invent tactical actions.

    A ``progress_update`` proposed by ``routine_next`` is only adopted into
    ``progress`` via ``progress.commit_action`` after ``exchange`` reports
    the submission as committed (i.e. after the same call that submits the
    orders envelope succeeds) -- never merely because the query proposed it.
    """
    model_responses = 0
    committed_actions = 0
    revision = state_revision
    policy = installation.policy
    progress.policy = copy.deepcopy(policy)
    queries = 0
    while True:
        if queries >= max_queries:
            return StrategyTurnOutcome("budget_exhausted", reason="max_queries_per_turn",
                                        model_responses=model_responses,
                                        committed_actions=committed_actions)
        queries += 1
        query = build_routine_query(revision, policy, progress)
        raw = exchange(query)
        if not isinstance(raw, dict) or not raw.get("ok") or "body" not in raw:
            message = raw.get("message", "query failed") if isinstance(raw, dict) else "invalid query response"
            raise RuntimeError(f"query_error: routine_next: {message}")
        result = parse_routine_result(raw["body"])

        if isinstance(result, RoutineFinishResult):
            # Finish through the routine envelope with no model call between the
            # last routine step and the boundary. FinishWithGreedy with empty
            # groups and holds is the verified no-sweep boundary; plain EndTurn
            # performs an automatic Greedy sweep and must not be used here.
            finish_envelope = build_orders_envelope([NO_SWEEP_FINISH], revision)
            finish_reply = exchange(finish_envelope)
            if not isinstance(finish_reply, dict) or not finish_reply.get("ok"):
                message = (finish_reply.get("message", "finish failed")
                           if isinstance(finish_reply, dict) else "invalid finish response")
                raise RuntimeError(f"submit_error: routine finish rejected: {message}")
            batch_id = (finish_reply.get("body", {}).get("batch_id")
                        if isinstance(finish_reply.get("body"), dict) else None)
            progress.commit_action(result.progress_update, installation_id=installation.installation_id,
                                   batch_id=batch_id or f"scripted-finish-{committed_actions}",
                                   state_revision=(finish_reply.get("body", {}).get("state_revision", revision)
                                                   if isinstance(finish_reply.get("body"), dict) else revision))
            return StrategyTurnOutcome("finished", reason="no_remaining_routine_steps",
                                        model_responses=model_responses,
                                        committed_actions=committed_actions)

        if isinstance(result, RoutineActionResult):
            orders = [result.action]
            envelope = build_orders_envelope(orders, revision)
            # The envelope is submitted as-is. It must carry no "action" key:
            # the driver detects it by the presence of "orders" and the absence
            # of "action", and would otherwise fall through to its single-order
            # path and reject it.
            submit_reply = exchange(envelope)
            if not isinstance(submit_reply, dict) or not submit_reply.get("ok"):
                message = submit_reply.get("message", "submit failed") if isinstance(submit_reply, dict) else "invalid submit response"
                raise RuntimeError(f"submit_error: routine action rejected: {message}")
            # Only now, proven committed, adopt the proposed progress update.
            body = submit_reply.get("body", {})
            new_revision = body["state_revision"] if isinstance(body, dict) and "state_revision" in body else revision
            batch_id = body.get("batch_id") if isinstance(body, dict) else None
            progress.commit_action(result.progress_update, installation_id=installation.installation_id,
                                   batch_id=batch_id or f"scripted-batch-{committed_actions + 1}",
                                   state_revision=new_revision)
            committed_actions += 1
            if new_revision is not None:
                revision = new_revision
            continue

        # RoutineException
        assert isinstance(result, RoutineException)
        if model_responses >= max_model_responses:
            return StrategyTurnOutcome("budget_exhausted", reason="max_model_responses_per_turn",
                                        model_responses=model_responses,
                                        committed_actions=committed_actions)
        brief = render_exception_brief(result, progress.remaining(policy))
        raw_reply = request_model(brief)
        model_responses += 1
        parsed = parse_model_response(raw_reply)
        if isinstance(parsed, ResignResponse):
            return StrategyTurnOutcome("resigned", model_responses=model_responses,
                                        committed_actions=committed_actions)
        if isinstance(parsed, FinishTurnResponse):
            return StrategyTurnOutcome("finished", reason="model_finish_turn",
                                        model_responses=model_responses,
                                        committed_actions=committed_actions)
        if isinstance(parsed, SetPolicyResponse):
            normalized = validate_routine_policy(parsed.policy, context)
            installation = install_policy(normalized, source_request_id=installation.source_request_id,
                                          source_kind="model")
            policy = installation.policy
            progress = RoutineProgress.fresh(installation.installation_id, installation.policy)
            continue
        if isinstance(parsed, ActResponse):
            orders = list(parsed.actions)
            if parsed.finish_turn:
                orders.append(copy.deepcopy(NO_SWEEP_FINISH))
            # This helper has no driver process, so model-owned actions use the
            # raw ordinary action list. The live client performs the same
            # submission with source=llm and request/side-turn provenance.
            submit_reply = exchange(orders)
            if not isinstance(submit_reply, dict) or not submit_reply.get("ok"):
                message = submit_reply.get("message", "act submit failed") if isinstance(submit_reply, dict) else "invalid act response"
                raise RuntimeError(f"submit_error: tactical act rejected: {message}")
            return StrategyTurnOutcome("finished" if parsed.finish_turn else "acted",
                                        reason=("model_act_finish" if parsed.finish_turn else "model_act"),
                                        model_responses=model_responses,
                                        committed_actions=committed_actions)
        raise ModelResponseError("unrecognized strategy response")
