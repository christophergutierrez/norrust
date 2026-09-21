#!/usr/bin/env python3
"""Factual play diagnostics computed from restored-state engine queries.

Stack 3 (`tmp/analysis-exec/CAPSULE-CONTRACT.md`) restores an archived
decision in isolation and reports what actually happened and what was
actually still legal at that point. This module holds the diagnostic
computations only. It does not restore checkpoints, materialize capsules, or
own a driver subprocess -- that belongs to `tools/decision_capsule.py`
(owned by another worker) and to the caller that wires this module to a live
driver process.

Every function here is pure: it consumes already-fetched query responses,
state snapshots, and event lists, and returns a diagnostic report. Nothing
in this module launches a model, launches a driver, or invents a value.  A
fact that cannot be determined from the inputs given is reported as the
string ``"unknown"``, never a zero and never silently omitted, per
`tmp/analysis-exec/CONTRACT.md`'s evidence-status rules.

## Restored-state query interface

Several diagnostics need enumeration queries (`turn_options`,
`recruit_options`, `tactical_surface`, `inspect_unit`) that already exist in
`norrust_core/src/bin/greedy_driver.rs`. Offline queries against a restored,
isolated state are explicitly legitimate for Stack 3 (unlike stacks 1-2,
which ran during live play).  This module never imports a driver-process
wrapper. Instead it takes a narrow callable:

    QueryFn = Callable[[dict[str, Any]], dict[str, Any]]

The contract for that callable, matching the existing pattern in
`tools/tactical_comparison.py:_query`: given a query payload such as
``{"what": "turn_options", "state_revision": 42}`` (the caller is
responsible for adding whatever transport envelope its driver process
expects, e.g. ``{"action": "Query", ...}``), it returns the driver's final
``status`` response record, i.e. a dict with at least ``ok`` (bool) and,
when ``ok`` is true, ``body`` (dict). This module never touches process
stdin/stdout itself, so its tests can pass a plain mock and stay fast.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Sequence

UNKNOWN = "unknown"

# Evidence-status enum, frozen by tmp/analysis-exec/CONTRACT.md across all
# stacks. Reused verbatim rather than redefined.
EVIDENCE_OBSERVED = "observed"
EVIDENCE_DERIVED = "derived"
EVIDENCE_SAMPLED = "sampled"
EVIDENCE_MISSING = "missing"
EVIDENCE_CONFLICTING = "conflicting"
EVIDENCE_NOT_APPLICABLE = "not_applicable"

QueryFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _query_body(query_fn: QueryFn, payload: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Run one query and return ``(body, evidence_status)``.

    ``evidence_status`` is ``EVIDENCE_OBSERVED`` when the driver answered
    with ``ok: true`` and a dict body, and ``EVIDENCE_MISSING`` otherwise
    (query failed, raised, or returned a malformed body). Callers must not
    treat a missing body as an empty result -- they must propagate the
    ``unknown`` coverage it implies.
    """
    try:
        response = query_fn(payload)
    except Exception:
        return None, EVIDENCE_MISSING
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        return None, EVIDENCE_MISSING
    body = response.get("body")
    if not isinstance(body, Mapping):
        return None, EVIDENCE_MISSING
    return dict(body), EVIDENCE_OBSERVED


# ---------------------------------------------------------------------------
# 1. Legal meaningful opportunities remaining at finish
# ---------------------------------------------------------------------------

def legal_remaining_opportunities(
    turn_options_body: Mapping[str, Any] | None,
    recruit_options_body: Mapping[str, Any] | None,
    *,
    active_faction: int | None,
    villages: Sequence[Mapping[str, Any]] | None = None,
    unit_enumeration_cap: int | None = None,
) -> dict[str, Any]:
    """Classify each eligible unit as having a useful action, or not.

    ``turn_options_body`` is the ``turn_options`` query body: a list of
    ``{"unit_id", "positions": [{"col","row","current","movable",
    "target_ids"}]}`` entries, one per unit that still has an unused move or
    attack flag (`!moved || !attacked` in the driver). That raw eligibility
    is exactly the "unused flag" the plan warns is NOT the same thing as a
    useful legal action. A position counts as useful here only if it has a
    non-empty ``target_ids`` (an attack is legally available from it) or, for
    a ``movable`` position, if it lands on a village hex not already owned by
    ``active_faction`` (a legal capture). Plain repositioning with no attack
    and no capture is not reported as an opportunity.

    ``villages`` is the caller-supplied village terrain list (from the
    restored state's ``terrain``, each with ``col``, ``row``, and ``owner``,
    matching `tools/tactical_comparison.py:_ownership`); pass ``None`` if
    village terrain was not fetched, and village-capture opportunities are
    then reported as unknown rather than assumed absent.

    ``unit_enumeration_cap`` records a cap the CALLER applied above this
    function (e.g. it only queried the first N units for cost reasons). This
    function itself never truncates; it only records the cap it was told
    about so coverage is honest.
    """
    if turn_options_body is None:
        return {
            "evidence_status": EVIDENCE_MISSING,
            "units_with_opportunity": [],
            "units_without_useful_action": [],
            "recruitment_opportunity": UNKNOWN,
            "coverage": {"enumeration_cap": unit_enumeration_cap, "complete": False},
        }

    village_owner: dict[tuple[int, int], Any] | None
    if villages is None:
        village_owner = None
    else:
        village_owner = {}
        for tile in villages:
            col, row = tile.get("col"), tile.get("row")
            if isinstance(col, int) and isinstance(row, int) and "owner" in tile:
                village_owner[(col, row)] = tile.get("owner")

    units = turn_options_body.get("units")
    if not isinstance(units, list):
        units = []

    with_opportunity: list[dict[str, Any]] = []
    without_useful_action: list[dict[str, Any]] = []

    for entry in units:
        if not isinstance(entry, Mapping):
            continue
        unit_id = entry.get("unit_id")
        positions = entry.get("positions")
        if not isinstance(positions, list):
            positions = []

        attack_positions = []
        capture_positions = []
        capture_unknown = False
        for position in positions:
            if not isinstance(position, Mapping):
                continue
            target_ids = position.get("target_ids") or []
            if target_ids:
                attack_positions.append({
                    "col": position.get("col"), "row": position.get("row"),
                    "current": position.get("current"), "target_ids": list(target_ids),
                })
            if position.get("movable"):
                col, row = position.get("col"), position.get("row")
                if village_owner is None:
                    capture_unknown = True
                elif (col, row) in village_owner and village_owner[(col, row)] != active_faction:
                    capture_positions.append({"col": col, "row": row,
                                               "before_owner": village_owner[(col, row)]})

        has_opportunity = bool(attack_positions) or bool(capture_positions)
        record = {
            "unit_id": unit_id,
            "attack_positions": attack_positions,
            "capture_positions": capture_positions,
            "village_capture_coverage": UNKNOWN if capture_unknown else EVIDENCE_OBSERVED,
        }
        if has_opportunity:
            with_opportunity.append(record)
        else:
            record["reason"] = "no_attack_or_capture_reachable"
            without_useful_action.append(record)

    if recruit_options_body is None:
        recruitment_opportunity: Any = UNKNOWN
    else:
        placement_hexes = recruit_options_body.get("placement_hexes") or []
        options = recruit_options_body.get("options") or []
        affordable = [o for o in options if isinstance(o, Mapping) and o.get("affordable")]
        recruitment_opportunity = {
            "side_can_place": bool(recruit_options_body.get("side_can_place")),
            "placement_hex_count": len(placement_hexes),
            "affordable_options": [o.get("def_id") for o in affordable],
            "is_opportunity": bool(recruit_options_body.get("side_can_place")) and bool(affordable),
        }

    capped = unit_enumeration_cap is not None and len(units) >= unit_enumeration_cap
    return {
        "evidence_status": EVIDENCE_OBSERVED,
        "units_with_opportunity": with_opportunity,
        "units_without_useful_action": without_useful_action,
        "recruitment_opportunity": recruitment_opportunity,
        "coverage": {
            "enumeration_cap": unit_enumeration_cap,
            "complete": not capped,
            "note": "unit list truncated by caller-applied cap; coverage beyond it is unknown" if capped else None,
        },
    }


# ---------------------------------------------------------------------------
# 2. Candidate actor/role coverage
# ---------------------------------------------------------------------------

def candidate_actor_coverage(
    shown_candidate_unit_ids: Iterable[Any],
    turn_options_body: Mapping[str, Any] | None,
    *,
    opportunities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Report which live units with a useful legal action were never shown.

    ``shown_candidate_unit_ids`` is whatever set of unit ids the candidate
    generator/renderer actually offered the model across the decision (the
    caller collects this from its own candidate packets; this function does
    not know how candidates are built).

    This NEVER calls its own coverage exhaustive: ``turn_options_body`` is
    itself a finite enumeration (it excludes units already fully spent, and
    is honest about whatever cap the caller applied upstream in
    ``opportunities``). The report says so explicitly in
    ``coverage_status``.
    """
    shown = {u for u in shown_candidate_unit_ids}
    if opportunities is None:
        opportunities = legal_remaining_opportunities(
            turn_options_body, None, active_faction=None, villages=None)

    if opportunities.get("evidence_status") != EVIDENCE_OBSERVED:
        return {
            "omitted_live_units_with_opportunity": UNKNOWN,
            "coverage_status": "unsupported_analysis",
            "reason": "turn_options query unavailable",
        }

    omitted = [
        record for record in opportunities.get("units_with_opportunity", [])
        if record.get("unit_id") not in shown
    ]
    return {
        "omitted_live_units_with_opportunity": omitted,
        "shown_candidate_count": len(shown),
        # Explicitly not "exhaustive_legal_coverage": this is candidate
        # coverage against one finite enumeration (turn_options), which is
        # itself capped per `opportunities["coverage"]`.
        "coverage_status": "finite_candidate_coverage_only",
        "enumeration_coverage": opportunities.get("coverage"),
    }


# ---------------------------------------------------------------------------
# 3. Recruitment queue
# ---------------------------------------------------------------------------

def recruitment_queue_status(
    tactical_recruitment_body: Mapping[str, Any] | None,
    *,
    committed_spending: int | None = None,
    reserve_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Report recruitment progress without conflating saving with stalling.

    ``tactical_recruitment_body`` is the ``recruitment`` sub-object of a
    `tactical_surface` query body: ``{"gold", "placement_hexes", "options",
    "legal_now", "reason", "recruiter_on_keep", ...}``. ``reason`` is the
    driver's own blocker classification
    (``"none"``/``"recruiter_off_keep"``/``"insufficient_gold"``/
    ``"no_capacity"``), reused verbatim rather than re-derived.

    ``committed_spending`` is gold actually spent on recruits this decision
    (caller sums Recruit events), when known.

    ``reserve_policy`` is an explicit, caller-supplied statement of intent
    (e.g. a routine's saving target), when one exists. Without it, this
    function NEVER claims a legal-but-unused recruit opportunity was
    "stalled" -- a blocked queue (``reason != "none"``) is the only thing
    reported as stalled/blocked; an unblocked queue with no recruit
    committed is reported as ``"unblocked_no_recruit_committed"`` with
    intent explicitly unknown, exactly to avoid inventing a stalled-queue
    finding where the evidence only shows unspent gold.
    """
    if tactical_recruitment_body is None:
        return {
            "evidence_status": EVIDENCE_MISSING,
            "blocker_reason": UNKNOWN,
            "gold_available": UNKNOWN,
            "committed_spending": committed_spending if committed_spending is not None else UNKNOWN,
            "queue_status": UNKNOWN,
        }

    reason = tactical_recruitment_body.get("reason")
    legal_now = bool(tactical_recruitment_body.get("legal_now"))
    gold = tactical_recruitment_body.get("gold")
    options = tactical_recruitment_body.get("options") or []

    if reason not in ("none", "recruiter_off_keep", "insufficient_gold", "no_capacity"):
        reason_out: Any = UNKNOWN
    else:
        reason_out = reason

    if not legal_now and reason_out not in (UNKNOWN, "none"):
        queue_status = "blocked"
    elif legal_now and (committed_spending is None or committed_spending == 0):
        if reserve_policy is not None:
            queue_status = "unblocked_reserved_by_policy"
        else:
            # Evidence supports only "not currently recruiting"; whether
            # that is intentional saving or an unreported stall is not
            # determinable from gold/legality alone, so it is left unknown
            # rather than guessed either way.
            queue_status = "unblocked_no_recruit_committed"
    elif legal_now:
        queue_status = "unblocked_recruit_committed"
    else:
        queue_status = UNKNOWN

    return {
        "evidence_status": EVIDENCE_OBSERVED,
        "blocker_reason": reason_out,
        "legal_now": legal_now,
        "gold_available": gold if isinstance(gold, int) else UNKNOWN,
        "committed_spending": committed_spending if committed_spending is not None else UNKNOWN,
        "composition_options": [
            {"def_id": o.get("def_id"), "cost": o.get("cost"), "affordable": o.get("affordable")}
            for o in options if isinstance(o, Mapping)
        ],
        "reserve_policy": dict(reserve_policy) if reserve_policy is not None else None,
        "queue_status": queue_status,
        "intent_known": reserve_policy is not None,
    }


# ---------------------------------------------------------------------------
# 4. Villages and material
# ---------------------------------------------------------------------------

def _village_owner_map(terrain: Sequence[Mapping[str, Any]] | None) -> dict[tuple[int, int], Any] | None:
    if terrain is None:
        return None
    owners: dict[tuple[int, int], Any] = {}
    for tile in terrain:
        if not isinstance(tile, Mapping) or tile.get("terrain_id") != "village":
            continue
        col, row = tile.get("col"), tile.get("row")
        if not isinstance(col, int) or not isinstance(row, int) or "owner" not in tile:
            return None
        owners[(col, row)] = tile.get("owner")
    return owners


def villages_and_material(
    initial_state: Mapping[str, Any] | None,
    final_state: Mapping[str, Any] | None,
    events: Sequence[Mapping[str, Any]] | None,
    *,
    controlled_faction: int | None = None,
) -> dict[str, Any]:
    """Village transitions, income, material changes, deaths -- event-linked.

    ``events`` is the ordered event list collected across the replayed
    horizon (each a `GameEvent` dict tagged by ``kind``, per
    `norrust_core/src/events.rs`). Every reported transition/death links to
    the exact event by its index in this list (``event_index``) plus its
    ``kind``, so a report can be traced back to the record it came from
    rather than merely asserted.
    """
    events = list(events) if events is not None else []

    village_deltas = "unknown"
    initial_villages = _village_owner_map(initial_state.get("terrain")) if isinstance(initial_state, Mapping) else None
    final_villages = _village_owner_map(final_state.get("terrain")) if isinstance(final_state, Mapping) else None
    if initial_villages is not None and final_villages is not None:
        village_deltas = []
        for coord in sorted(initial_villages):
            before = initial_villages[coord]
            after = final_villages.get(coord, before)
            if after != before:
                # Find the Village event that reports this exact hex/owner,
                # so the transition is linked to its source record, not
                # merely inferred from a before/after diff.
                linked = [
                    {"event_index": i, "kind": e.get("kind")}
                    for i, e in enumerate(events)
                    if e.get("kind") == "village" and e.get("col") == coord[0]
                    and e.get("row") == coord[1] and e.get("owner") == after
                ]
                village_deltas.append({
                    "col": coord[0], "row": coord[1], "before": before, "after": after,
                    "linked_events": linked,
                    "evidence_status": EVIDENCE_OBSERVED if linked else EVIDENCE_CONFLICTING,
                })

    gold_events = [
        {"event_index": i, "faction": e.get("faction"), "delta": e.get("delta"),
         "balance": e.get("balance"), "reason": e.get("reason")}
        for i, e in enumerate(events) if e.get("kind") == "gold"
    ]
    income_events = [e for e in gold_events if e.get("reason") not in (None,) and "recruit" not in str(e.get("reason"))]

    deaths = []
    for i, e in enumerate(events):
        if e.get("kind") == "attack":
            for role in ("attacker", "defender"):
                unit_event = e.get(role)
                if isinstance(unit_event, Mapping) and unit_event.get("killed"):
                    deaths.append({
                        "unit_id": unit_event.get("unit"),
                        "role": role,
                        "event_index": i,
                        "kind": "attack",
                    })

    recruiter_ids = "unknown"
    recruiter_exposure = "unknown"
    if isinstance(initial_state, Mapping) and isinstance(initial_state.get("units"), list):
        recruiter_ids = sorted(
            u.get("id") for u in initial_state["units"]
            if isinstance(u, Mapping) and u.get("can_recruit") and u.get("faction") == controlled_faction
        )
        recruiter_exposure = [d for d in deaths if d.get("unit_id") in recruiter_ids]

    initial_units = {u.get("id"): u for u in (initial_state.get("units") or []) if isinstance(u, Mapping)} if isinstance(initial_state, Mapping) else {}
    final_units = {u.get("id"): u for u in (final_state.get("units") or []) if isinstance(u, Mapping)} if isinstance(final_state, Mapping) else {}
    material_unknown = not initial_units or not final_units
    if material_unknown:
        material_changes: Any = UNKNOWN
    else:
        material_changes = {
            "units_lost": sorted(set(initial_units) - set(final_units)),
            "units_gained": sorted(set(final_units) - set(initial_units)),
        }

    return {
        "village_transitions": village_deltas,
        "gold_events": gold_events,
        "income_events_observed": income_events,
        "deaths": deaths,
        "recruiter_ids": recruiter_ids,
        "recruiter_exposure": recruiter_exposure,
        "material_changes": material_changes,
    }


# ---------------------------------------------------------------------------
# 5. Support geometry
# ---------------------------------------------------------------------------

def support_geometry(
    destination_threats: Sequence[Mapping[str, Any]] | None,
    *,
    friendly_positions: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Enemy reach to a unit's legal destinations, from ``inspect_unit``.

    ``destination_threats`` is the ``inspect_unit`` query body's
    ``destination_threats`` list, each entry already carrying engine-computed
    ``cost`` (legal movement cost, ``None`` if unreachable) rather than
    straight-line distance. That IS the "distance through legal paths" the
    plan requires; this function reports it as observed fact, not a
    heuristic.

    Friendly interception/protection is a SEPARATE, much weaker claim: this
    function never asserts "protected" from geometry alone. If
    ``friendly_positions`` is supplied it returns a clearly labelled
    heuristic (straight-line hex distance) and nothing stronger, because
    "legally reachable in time to intercept" is not something this function
    computes (it would require its own engine query this stack does not
    add). A nearby friendly unit is reported, not interpreted as protection.
    """
    if destination_threats is None:
        return {"evidence_status": EVIDENCE_MISSING, "destinations": [], "friendly_proximity": UNKNOWN}

    destinations = []
    for entry in destination_threats:
        if not isinstance(entry, Mapping):
            continue
        destinations.append({
            "col": entry.get("col"), "row": entry.get("row"),
            "current": entry.get("current"),
            "cost": entry.get("cost"),  # legal-path movement cost; None = unreachable
            "distance": entry.get("distance"),  # only present if caller requested a reference hex
            "threats": entry.get("threats", entry.get("threat_ids", UNKNOWN)),
            "evidence_status": EVIDENCE_OBSERVED,
        })

    friendly_proximity: Any
    if friendly_positions is None:
        friendly_proximity = UNKNOWN
    else:
        def hex_distance(a: Mapping[str, Any], b: Mapping[str, Any]) -> int | None:
            # Straight-line offset approximation only -- explicitly NOT a
            # legal-path distance. Labelled heuristic in the returned record
            # so a consumer cannot mistake it for `cost` above.
            ac, ar, bc, br = a.get("col"), a.get("row"), b.get("col"), b.get("row")
            if not all(isinstance(v, int) for v in (ac, ar, bc, br)):
                return None
            return abs(ac - bc) + abs(ar - br)

        friendly_proximity = []
        for dest in destinations:
            nearest = None
            for friendly in friendly_positions:
                d = hex_distance(dest, friendly)
                if d is not None and (nearest is None or d < nearest["straight_line_distance"]):
                    nearest = {"unit_id": friendly.get("unit_id"), "straight_line_distance": d}
            friendly_proximity.append({
                "col": dest.get("col"), "row": dest.get("row"),
                "nearest_friendly": nearest,
                "heuristic": True,
                "method": "straight_line_hex_distance",
                "note": "proximity only; does not establish legal-path interception or protection",
            })

    return {"evidence_status": EVIDENCE_OBSERVED, "destinations": destinations, "friendly_proximity": friendly_proximity}


# ---------------------------------------------------------------------------
# 6. Behavioral patterns
# ---------------------------------------------------------------------------

def behavioral_patterns(
    decision_records: Sequence[Mapping[str, Any]],
    *,
    inactivity_threshold: int = 3,
    invalid_action_threshold: int = 2,
) -> dict[str, Any]:
    """Detect repeated inactivity, invalid actions, and near-exhausted budgets.

    ``decision_records`` is a caller-supplied, already-ordered sequence of
    per-decision summaries (one dict per side-turn decision), each with
    whatever subset of these keys it has evidence for:
    ``unit_id``, ``acted`` (bool), ``invalid_action`` (bool),
    ``stale_actor_reference`` (bool), ``repair_attempted`` (bool),
    ``repair_succeeded`` (bool), ``exception`` (str or None),
    ``budget_remaining`` (int or None), ``budget_total`` (int or None).
    A missing key on a record is treated as unknown for that record, not as
    a negative signal, and does not itself count toward a pattern.
    """
    records = list(decision_records)

    per_unit_inactive: dict[Any, int] = {}
    for r in records:
        if r.get("acted") is False and "unit_id" in r:
            per_unit_inactive[r["unit_id"]] = per_unit_inactive.get(r["unit_id"], 0) + 1
        elif r.get("acted") is True and "unit_id" in r:
            per_unit_inactive[r["unit_id"]] = 0
    repeatedly_inactive = sorted(
        uid for uid, streak in per_unit_inactive.items() if streak >= inactivity_threshold)

    invalid_streak = 0
    max_invalid_streak = 0
    for r in records:
        if r.get("invalid_action") is True:
            invalid_streak += 1
            max_invalid_streak = max(max_invalid_streak, invalid_streak)
        elif r.get("invalid_action") is False:
            invalid_streak = 0
    repeated_invalid_actions = max_invalid_streak >= invalid_action_threshold

    stale_actor_refs = [r for r in records if r.get("stale_actor_reference") is True]
    repair_loops = [r for r in records if r.get("repair_attempted") is True and r.get("repair_succeeded") is False]
    exceptions = [{"index": i, "exception": r.get("exception")}
                  for i, r in enumerate(records) if r.get("exception")]

    near_exhausted_budget = []
    for i, r in enumerate(records):
        remaining, total = r.get("budget_remaining"), r.get("budget_total")
        if isinstance(remaining, int) and isinstance(total, int) and total > 0:
            if remaining / total <= 0.1:
                near_exhausted_budget.append({"index": i, "remaining": remaining, "total": total})

    any_evidence = bool(records)
    return {
        "evidence_status": EVIDENCE_OBSERVED if any_evidence else EVIDENCE_MISSING,
        "repeatedly_inactive_units": repeatedly_inactive,
        "repeated_invalid_actions": repeated_invalid_actions,
        "max_invalid_action_streak": max_invalid_streak,
        "stale_actor_references": stale_actor_refs,
        "repair_loops": repair_loops,
        "routine_exceptions": exceptions,
        "near_exhausted_decision_budgets": near_exhausted_budget,
        "decisions_evaluated": len(records),
    }


# ---------------------------------------------------------------------------
# 7. Cost and prompt metrics
# ---------------------------------------------------------------------------

def cost_and_prompt_metrics(
    model_request_records: Sequence[Mapping[str, Any]],
    *,
    completed_side_turns: int | None = None,
    committed_useful_actions: int | None = None,
) -> dict[str, Any]:
    """Prompt size, cache, latency, and cost metrics, each with its own gaps.

    ``model_request_records`` is a sequence of the analysis capture's
    ``model_request`` record bodies (see `tmp/analysis-exec/CONTRACT.md`),
    consumed by field name only -- this module never imports
    `tools/analysis_capture.py`, so it stays decoupled from that module's
    implementation. Expected (but not required) body fields:
    ``prompt_bytes``, ``prompt_section_bytes`` (dict of section name ->
    bytes), ``usage`` (dict possibly containing ``cache_read_tokens``,
    ``cache_write_tokens``, ``input_tokens``, ``output_tokens``), ``cost``
    (numeric, provider-reported or derived), ``provider_latency_ms``,
    ``total_latency_ms``. Every missing field is reported as ``"unknown"``
    per-record and does not silently become 0 in an aggregate.
    """
    records = list(model_request_records)

    def _sum_known(values: Sequence[Any]) -> Any:
        known = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not known:
            return UNKNOWN
        if len(known) != len(values):
            return {"sum_of_known": sum(known), "known_count": len(known), "total_count": len(values)}
        return sum(known)

    prompt_bytes = [r.get("prompt_bytes") for r in records]
    section_totals: dict[str, list[Any]] = {}
    for r in records:
        sections = r.get("prompt_section_bytes")
        if isinstance(sections, Mapping):
            for name, size in sections.items():
                section_totals.setdefault(name, []).append(size)

    cache_read = [(r.get("usage") or {}).get("cache_read_tokens") if isinstance(r.get("usage"), Mapping) else None for r in records]
    cache_write = [(r.get("usage") or {}).get("cache_write_tokens") if isinstance(r.get("usage"), Mapping) else None for r in records]
    provider_latency = [r.get("provider_latency_ms") for r in records]
    total_latency = [r.get("total_latency_ms") for r in records]
    other_latency = []
    for pl, tl in zip(provider_latency, total_latency):
        if isinstance(pl, (int, float)) and isinstance(tl, (int, float)):
            other_latency.append(tl - pl)
        else:
            other_latency.append(None)

    costs = [r.get("cost") for r in records]
    total_cost = _sum_known(costs)

    def _rate(total: Any, denominator: int | None) -> Any:
        if total is UNKNOWN or not isinstance(total, (int, float)) or not denominator:
            return UNKNOWN
        return total / denominator

    return {
        "evidence_status": EVIDENCE_OBSERVED if records else EVIDENCE_MISSING,
        "requests_evaluated": len(records),
        "prompt_bytes": {
            "definition": "raw prompt size in bytes as recorded at model_request time",
            "per_request": prompt_bytes,
            "total": _sum_known(prompt_bytes),
        },
        "prompt_section_bytes": {
            "definition": "prompt_section_bytes as recorded per model_request, summed per section name",
            "per_section_total": {name: _sum_known(sizes) for name, sizes in section_totals.items()},
        } if section_totals else {"definition": "no per-section prompt sizes recorded", "per_section_total": UNKNOWN},
        "cache_accounting": {
            "definition": "usage.cache_read_tokens / usage.cache_write_tokens as reported by the provider",
            "cache_read_tokens_total": _sum_known(cache_read),
            "cache_write_tokens_total": _sum_known(cache_write),
        },
        "latency": {
            "definition": "provider_latency_ms is provider-reported call time; "
                           "other_latency_ms = total_latency_ms - provider_latency_ms is everything "
                           "else measured around the call (queuing, local repair, transport)",
            "provider_latency_ms_total": _sum_known(provider_latency),
            "other_latency_ms_total": _sum_known([v for v in other_latency if v is not None]) if any(v is not None for v in other_latency) else UNKNOWN,
        },
        "cost": {
            "definition": "sum of per-request cost field as recorded (provider-reported or upstream-derived; "
                           "this module does not price tokens itself)",
            "total": total_cost,
            "per_completed_side_turn": _rate(total_cost, completed_side_turns),
            "per_committed_useful_action": _rate(total_cost, committed_useful_actions),
            "completed_side_turns": completed_side_turns if completed_side_turns is not None else UNKNOWN,
            "committed_useful_actions": committed_useful_actions if committed_useful_actions is not None else UNKNOWN,
        },
    }
