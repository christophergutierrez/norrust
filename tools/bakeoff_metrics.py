"""Bakeoff metrics, pricing, and useful action evaluation helper (Stack 4).

Pure helper module for:
1. Exact non-overlapping token accounting (input, cached input, output, reasoning, total).
2. Dated pricing schedules and known cost calculation with explicit coverage.
3. First legal commit vs first useful action detection and physical-call token timing.
4. Three-arm bakeoff comparison (Arm A: batch, Arm B: focused coords, Arm C: focused choices)
   and pilot threshold screening.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

from . import model_usage

DEFAULT_PRICE_DATE = None


def get_price_spec(model=None, price_date=None, custom_prices=None):
    """Only explicitly supplied rates are evidence; never guess a model price."""
    return custom_prices if isinstance(custom_prices, dict) and custom_prices else None


def compute_call_cost(usage: Optional[dict[str, Any]], model: Optional[str] = None,
                      price_date: str = DEFAULT_PRICE_DATE,
                      custom_prices: Optional[dict[str, Any]] = None) -> Optional[float]:
    """Compute known cost for one usage payload.

    Returns None if usage is missing or incomplete.
    Never double-counts reasoning tokens if they are already included in output.
    """
    if not isinstance(usage, dict):
        return None
    inp, _ = model_usage.normalize_int(usage.get("input_tokens"))
    out, _ = model_usage.normalize_int(usage.get("output_tokens"))
    spec = get_price_spec(model, price_date, custom_prices)
    if inp is None or out is None or spec is None:
        return None
    import math
    rate_names = ("input_per_million", "cached_input_per_million", "output_per_million")
    if any(type(spec.get(k)) not in (int, float) or not math.isfinite(spec[k])
           or spec[k] < 0 for k in rate_names):
        return None
    cached, _ = model_usage.normalize_int(usage.get("cached_input_tokens"))
    if cached is None:
        if spec["input_per_million"] != spec["cached_input_per_million"]:
            return None
        cached = 0  # Same price: missing cache split cannot change the cost.
    if cached > inp or type(spec.get("reasoning_included_in_output")) is not bool:
        return None
    cost = ((inp-cached)*spec["input_per_million"] + cached*spec["cached_input_per_million"]
            + out*spec["output_per_million"])
    if not spec["reasoning_included_in_output"]:
        reasoning, _ = model_usage.normalize_int(usage.get("reasoning_tokens"))
        rate = spec.get("reasoning_per_million")
        if reasoning is None or type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0:
            return None
        cost += reasoning * rate
    return cost / 1_000_000


def aggregate_usage(call_records: list[dict[str, Any]], model: Optional[str] = None,
                    price_date: str = DEFAULT_PRICE_DATE,
                    custom_prices: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Aggregate physical model calls into exact non-overlapping totals and cost."""
    calls: list[model_usage.ModelCall] = []
    for index, raw in enumerate(call_records):
        usage = raw.get("usage") if isinstance(raw.get("usage"), dict) else raw
        usage = usage if isinstance(usage, dict) else {}
        fields = {key: value for key, value in raw.items()
                  if key in model_usage.ModelCall.__dataclass_fields__ and key not in model_usage.TOKEN_FIELDS}
        fields.setdefault("game_id", "fixture")
        fields.setdefault("call_id", f"unidentified:{index}")
        fields.setdefault("status", "failed" if raw.get("error") else "completed")
        call = model_usage.ModelCall(**fields)
        for field in model_usage.TOKEN_FIELDS:
            value, gap = model_usage.normalize_int(usage.get(field))
            setattr(call, field, value)
            if gap:
                call.normalization_gaps.append(gap)
        calls.append(call)
    calls, conflicts = model_usage.dedupe_calls(calls)
    aggregate = model_usage.aggregate_calls(calls)
    total_physical_calls = aggregate["call_count"]
    measured_calls = sum(1 for call in calls if call.input_tokens is not None and call.output_tokens is not None)
    failed_calls = sum(1 for call in calls if call.status in ("failed", "error") or call.error_code)
    total_elapsed_ms = sum(call.elapsed_ms for call in calls if isinstance(call.elapsed_ms, int) and call.elapsed_ms > 0)
    known_cost_calls = 0
    total_cost = 0.0
    for call in calls:
        usage = {field: getattr(call, field) for field in model_usage.TOKEN_FIELDS}
        cost = (compute_call_cost(usage, model, price_date, custom_prices)
                if not call.normalization_gaps else None)
        if cost is not None:
            total_cost += cost
            known_cost_calls += 1

    if total_physical_calls == 0:
        usage_cov = "empty"
        cost_cov = "empty"
    elif measured_calls == total_physical_calls:
        usage_cov = "complete"
        cost_cov = ("complete" if known_cost_calls == total_physical_calls and not conflicts
                    else "partial" if known_cost_calls else "unknown")
    elif measured_calls > 0:
        usage_cov = "partial"
        cost_cov = "partial" if known_cost_calls > 0 else "unknown"
    else:
        usage_cov = "unknown"
        cost_cov = "unknown"

    return {
        "physical_calls": total_physical_calls,
        "failed_calls": failed_calls,
        "measured_calls": measured_calls,
        "input_tokens": aggregate["input_tokens"]["sum"],
        "cached_input_tokens": aggregate["cached_input_tokens"]["sum"],
        "output_tokens": aggregate["output_tokens"]["sum"],
        "reasoning_tokens": (aggregate["reasoning_tokens"]["sum"]
                              if aggregate["reasoning_tokens"]["fully_measured"] else None),
        # The sum is the measured portion; field_coverage says whether every
        # physical call supplied it. A partial sum is useful for reporting but
        # must never be presented as complete coverage.
        "total_tokens": aggregate["total_tokens"]["sum"],
        "elapsed_ms": total_elapsed_ms,
        "known_cost": round(total_cost, 6) if known_cost_calls > 0 else None,
        "usage_coverage": usage_cov,
        "cost_coverage": cost_cov,
        "normalization_conflicts": [str(k) for k in conflicts],
        "field_coverage": {field: aggregate[field] for field in model_usage.TOKEN_FIELDS},
    }


def _event_matches_order(event: dict[str, Any], order: dict[str, Any]) -> bool:
    """Match engine identity and coordinates, not merely an action kind."""
    action, kind = order.get("action"), event.get("kind")
    if action == "Engage":
        for step in order.get("steps", []):
            if kind == "attack" and _event_matches_order(event, {
                    "action":"Attack", "attacker_id":step.get("attacker_id"),
                    "defender_id":order.get("target_id")}):
                return True
            if kind == "move" and _event_matches_order(event, {
                    "action":"Move", "unit_id":step.get("attacker_id"),
                    "col":step.get("col"), "row":step.get("row")}):
                return True
        return False
    expected = {"Move":"move", "Attack":"attack", "Recruit":"recruit",
                "RecruitBatch":"recruit", "Advance":"advance"}.get(action)
    if kind != expected or expected is None:
        return False
    if action == "Attack":
        return (event.get("attacker", {}).get("unit") == order.get("attacker_id")
                and event.get("defender", {}).get("unit") == order.get("defender_id"))
    if action in ("Move", "Advance") and event.get("unit") != order.get("unit_id"):
        return False
    if action in ("Recruit", "RecruitBatch") and event.get("def_id") != order.get("def_id"):
        return False
    if action in ("Recruit", "Move"):
        destination = event.get("to", {}) if action == "Move" else event
        return all(k not in order or destination.get(k) == order[k] for k in ("col", "row"))
    return True


def _physical_request_totals(records: list[dict[str, Any]],
                            physical_calls: list[dict[str, Any]]) -> dict[str, int | None]:
    """Return cumulative physical tokens at each logged model request.

    The catalog's call rows are a set of evidence, not a chronology: SQLite
    row order can change on reimport and a host can finish a later retry before
    an earlier request is written.  Group calls by their harness request, then
    apply those groups in the request order recorded in the audit log.  A
    request with no detailed call, an unlinked call, or an unknown/conflicting
    total makes every subsequent offset unknown.  This is conservative about
    missing attempts while keeping retries for one request in that request's
    group.
    """
    request_ids = []
    seen_requests: set[str] = set()
    for record in records:
        if record.get("type") not in ("model_request", "model"):
            continue
        request_id = record.get("request_id")
        if isinstance(request_id, str) and request_id and request_id not in seen_requests:
            request_ids.append(request_id)
            seen_requests.add(request_id)

    # Physical rows normally come from query_usage(..., "call") and are
    # already lifecycle-deduplicated.  Fold duplicate IDs here as well so the
    # pure helper remains correct for callers supplying raw sidecar fixtures.
    calls_by_id: dict[tuple[str, str], dict[str, Any]] = {}
    conflicts: set[tuple[str, str]] = set()
    unlinked = False
    for index, raw in enumerate(physical_calls):
        if not isinstance(raw, dict):
            unlinked = True
            continue
        request_id = raw.get("request_id")
        call_id = raw.get("call_id")
        if not isinstance(request_id, str) or not request_id or not isinstance(call_id, str) or not call_id:
            unlinked = True
            continue
        # Usage identity is the catalog's canonical (game_id, call_id), not
        # the request link. A retry can update its request linkage while the
        # call itself remains one physical attempt.
        game_id = raw.get("game_id")
        if not isinstance(game_id, str) or not game_id:
            game_id = "fixture"
        key = (game_id, call_id)
        total = raw.get("total_tokens")
        if isinstance(raw.get("usage"), dict):
            total = raw["usage"].get("total_tokens")
        if key in calls_by_id:
            old_request_id = calls_by_id[key].get("request_id")
            if old_request_id != request_id:
                conflicts.add(key)
            old = calls_by_id[key].get("total_tokens")
            if old is None and total is not None:
                # A dispatch lifecycle row may be followed by its terminal
                # row.  The catalog normally merges these before this helper
                # sees them, but retain the same fill-unknown behavior for
                # direct fixtures.
                calls_by_id[key]["total_tokens"] = total
            elif old is not None and total is not None and old != total:
                conflicts.add(key)
            continue
        calls_by_id[key] = {"game_id": game_id, "request_id": request_id, "call_id": call_id,
                            "total_tokens": total,
                            "normalization_gaps": raw.get("normalization_gaps")}

    known_request_ids = set(request_ids)
    if any(call["request_id"] not in known_request_ids for call in calls_by_id.values()):
        unlinked = True
    grouped: dict[str, list[dict[str, Any]]] = {}
    for call in calls_by_id.values():
        grouped.setdefault(call["request_id"], []).append(call)

    offsets: dict[str, int | None] = {}
    cumulative: int | None = None if unlinked else 0
    for request_id in request_ids:
        calls = grouped.get(request_id)
        if not calls:
            cumulative = None
        elif cumulative is not None:
            request_total = 0
            for call in calls:
                total = call.get("total_tokens")
                key = (call["game_id"], call["call_id"])
                if (type(total) is not int or total < 0 or call.get("normalization_gaps")
                        or key in conflicts):
                    cumulative = None
                    break
                request_total += total
            if cumulative is not None:
                cumulative += request_total
        offsets[request_id] = cumulative
    return offsets


def evaluate_trial_actions(records: list[dict[str, Any]],
                            useful_predicate: Optional[Callable[[dict[str, Any]], bool]] = None,
                            useful_spec: Optional[dict[str, Any]] = None,
                            physical_calls: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Find first committed and useful authored action using engine evidence.

    ``forwarded_orders`` is a proposal. A model action becomes committed only
    when a following driver event from ``llm`` proves it executed.
    """
    if physical_calls is not None:
        request_usage_map = _physical_request_totals(records, physical_calls)
    else:
        # Request usage can already include retries. Without physical evidence,
        # these token/timing metrics are unknown, never a sum of request hints.
        request_usage_map = {}

    first_legal_action: Optional[dict[str, Any]] = None
    tokens_to_first_legal: Optional[int] = None
    ms_to_first_legal: Optional[int] = None

    first_useful_action: Optional[dict[str, Any]] = None
    tokens_to_first_useful: Optional[int] = None
    ms_to_first_useful: Optional[int] = None

    started_at = next((r.get("started_at") for r in records if r.get("type") == "metadata"), None)
    active_batch: dict[str, Any] | None = None
    for r in records:
        if r.get("type") == "forwarded_orders":
            if r.get("accepted") is False or r.get("status") in {"rejected", "invalid"}:
                active_batch = None
                continue
            req_id = r.get("request_id")
            tokens_at_forward = request_usage_map.get(req_id)
            orders = r.get("orders") or []
            active_batch = {"orders": orders, "tokens": tokens_at_forward}
            continue
        if r.get("type") != "driver":
            continue
        line = r.get("line")
        if isinstance(line, dict) and line.get("type") == "status" and line.get("ok") is False:
            active_batch = None
        if not isinstance(line, dict) or line.get("type") != "events" or line.get("source") != "llm":
            continue
        try:
            observed_ms = max(0, round((datetime.fromisoformat(r["observed_at"])
                                        - datetime.fromisoformat(started_at)).total_seconds()*1000))
        except (KeyError, TypeError, ValueError):
            observed_ms = None
        for event in line.get("events", []):
            if not isinstance(event, dict) or active_batch is None:
                continue
            for order in active_batch["orders"]:
                if not isinstance(order, dict) or order.get("action") in (
                        "EndTurn", "DoneWithImportantMoves", "FinishWithGreedy", "Resign"):
                    continue
                if not _event_matches_order(event, order):
                    continue
                if first_legal_action is None:
                    first_legal_action = order
                    tokens_to_first_legal, ms_to_first_legal = active_batch["tokens"], observed_ms
                if first_useful_action is None:
                    useful = False
                    if useful_predicate:
                        useful = useful_predicate(event)
                        if not useful:
                            # Callers with an order predicate can still use
                            # the API; the event proof above remains required.
                            useful = useful_predicate(order)
                    else:
                        useful = True
                    if useful_spec:
                        useful = _matches_spec(event, useful_spec)
                    if useful:
                        first_useful_action = order
                        tokens_to_first_useful, ms_to_first_useful = active_batch["tokens"], observed_ms
                break

    return {
        "first_legal_action": first_legal_action,
        "tokens_to_first_legal": tokens_to_first_legal,
        "ms_to_first_legal": ms_to_first_legal,
        "first_useful_action": first_useful_action,
        "tokens_to_first_useful": tokens_to_first_useful,
        "ms_to_first_useful": ms_to_first_useful,
        "useful_action_achieved": (first_useful_action is not None
                                   if useful_predicate or useful_spec else None),
    }


def _matches_spec(event: dict[str, Any], spec: dict[str, Any]) -> bool:
    """Match a small declarative fixture predicate against an executed event."""
    kind = spec.get("kind", spec.get("action"))
    if kind is not None and event.get("kind") != kind:
        return False
    destination = event.get("to", {}) if event.get("kind") == "move" else event
    if any(key in spec and destination.get(key) != spec[key] for key in ("col", "row")):
        return False
    for key in ("unit", "unit_id", "target", "target_id", "faction"):
        if key in spec:
            actual = event.get(key)
            if actual is None and key == "unit_id":
                actual = event.get("unit")
            if actual is None and key in ("target", "target_id"):
                actual = event.get("defender", {}).get("unit")
            if actual is None and key == "unit_id":
                actual = event.get("attacker", {}).get("unit")
            if actual != spec[key]:
                return False
    return True


def extract_telemetry(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract action encoding and execution telemetry from records."""
    handle_choices_used = 0
    coordinate_fallbacks = 0
    choice_actions_expanded = 0
    model_orders_count = 0
    model_actions_count = 0
    driver_orders_count = 0
    selection_validation_failures = 0
    active_task_observations = 0
    total_agenda_observations = 0

    for r in records:
        rtype = r.get("type")
        if rtype == "forwarded_orders":
            orders = r.get("orders") or []
            model_orders_count += len(orders)
            choices = r.get("authored_choices")
            if choices is not None:
                handle_choices_used += len(choices)
                choice_actions_expanded += len(orders)
            elif r.get("coordinate_fallback"):
                coordinate_fallbacks += 1
        elif rtype == "agenda_observation":
            total_agenda_observations += 1
            agenda = r.get("agenda")
            if isinstance(agenda, dict) and any(t.get("status") == "active" for t in agenda.get("tasks", [])):
                active_task_observations += 1
        elif rtype == "repair" and r.get("validation_error"):
            selection_validation_failures += 1
        elif rtype == "batch_validation" and r.get("valid") is False:
            selection_validation_failures += 1
        elif rtype == "driver":
            line = r.get("line") or {}
            events = line.get("events") or []
            for ev in events:
                if ev.get("kind") in ("move", "attack", "recruit", "advance"):
                    if line.get("source") == "llm":
                        model_actions_count += 1
                    elif line.get("source") is not None:
                        driver_orders_count += 1

    terminal = next((r for r in reversed(records) if r.get("type") == "terminal"), {})

    return {
        "handle_choices_used": terminal.get("handle_choices_used", handle_choices_used),
        "coordinate_fallbacks": terminal.get("coordinate_fallbacks", coordinate_fallbacks),
        "choice_actions_expanded": terminal.get("choice_actions_expanded", choice_actions_expanded),
        "submitted_orders_count": model_orders_count,
        "model_actions_count": model_actions_count,
        "driver_actions_count": driver_orders_count,
        "selection_validation_failures": selection_validation_failures,
        "active_task_coverage": (active_task_observations / total_agenda_observations) if total_agenda_observations else None,
    }


def compare_arms(cells_report: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare arms A, B, and C across matched position families.

    Arms:
    A: batch baseline, incremental enabled with cap 3, coordinates
    B: focused, coordinates
    C: focused, choices

    Pilot criteria from plan:
    - B is promising over A if at least 6/8 trials complete the task and has >= 2 more
      successes than A, or if A already has >= 6/8, B matches count with >= 25% lower
      median tokens to first useful action.
    - Promote C over B only if task successes >= B's, median cost per completed task <= 110% of B's,
      and either halves selection/validation failures (when B has >= 2) or reduces median tokens
      to first useful action by >= 25%.
    """
    by_arm: dict[str, list[dict[str, Any]]] = {"A": [], "B": [], "C": []}
    for entry in cells_report:
        arm = entry.get("arm") or entry.get("configuration")
        if arm in by_arm:
            by_arm[arm].append(entry)

    def stats_for(entries: list[dict[str, Any]]) -> dict[str, Any]:
        scheduled = len(entries)
        completed = sum(1 for e in entries if e.get("status") == "ok" and e.get("terminal_class") in ("gameplay", "complete"))
        task_successes = sum(1 for e in entries if e.get("task_success") is True)
        useful_tokens = [e["tokens_to_first_useful"] for e in entries if isinstance(e.get("tokens_to_first_useful"), (int, float))]
        def median(values: list[float | int]) -> float | int | None:
            if not values:
                return None
            ordered = sorted(values)
            middle = len(ordered) // 2
            if len(ordered) % 2:
                return ordered[middle]
            return (ordered[middle - 1] + ordered[middle]) / 2
        median_useful_tokens = median(useful_tokens)
        # The promotion gate is cost per completed task. Unknown cost stays
        # out of the measured median and is visible through the denominator.
        costs = [e["known_cost"] for e in entries
                 if e.get("task_success") is True and e.get("cost_coverage") == "complete"
                 and isinstance(e.get("known_cost"), (int, float))]
        median_cost = median(costs)
        failures = [e.get("telemetry", {}).get("selection_validation_failures") for e in entries]
        return {
            "scheduled": scheduled,
            "completed": completed,
            "task_successes": task_successes,
            "median_tokens_to_first_useful": median_useful_tokens,
            "median_cost": median_cost,
            "cost_complete": len(costs) == task_successes and task_successes > 0,
            "tokens_unmeasured_or_censored": scheduled - len(useful_tokens),
            "selection_validation_failures": (sum(failures) if failures and
                all(isinstance(value, int) and not isinstance(value, bool) for value in failures) else None),
        }

    stats_a = stats_for(by_arm["A"])
    stats_b = stats_for(by_arm["B"])
    stats_c = stats_for(by_arm["C"])

    # B vs A evaluation
    b_promising = False
    b_reason = ""
    if stats_b["scheduled"] >= 8:
        if stats_b["task_successes"] >= 6 and (stats_b["task_successes"] - stats_a["task_successes"]) >= 2:
            b_promising = True
            b_reason = f"B achieved {stats_b['task_successes']}/8 successes vs A's {stats_a['task_successes']}/8 (>=2 gain)"
        elif stats_a["task_successes"] >= 6 and stats_b["task_successes"] >= stats_a["task_successes"]:
            if (stats_a["tokens_unmeasured_or_censored"] == stats_b["tokens_unmeasured_or_censored"] == 0
                    and stats_a["median_tokens_to_first_useful"] and stats_b["median_tokens_to_first_useful"]
                    and stats_b["median_tokens_to_first_useful"] <= 0.75 * stats_a["median_tokens_to_first_useful"]):
                b_promising = True
                b_reason = f"B matched A ({stats_b['task_successes']}/8) with >=25% lower median tokens to useful action"
            else:
                b_reason = "B matched A in successes but did not achieve >=25% token reduction"
        else:
            b_reason = f"B achieved {stats_b['task_successes']}/8 successes (threshold not met)"
    else:
        b_reason = "Insufficient trials to evaluate pilot thresholds"

    # C vs B evaluation
    c_promotes = False
    c_reason = ""
    if stats_c["scheduled"] >= 8 and stats_b["scheduled"] >= 8:
        cost_ok = (stats_c["cost_complete"] and stats_b["cost_complete"]
                   and stats_c["median_cost"] is not None and stats_b["median_cost"] is not None
                   and stats_c["median_cost"] <= 1.10 * stats_b["median_cost"])
        success_ok = stats_c["task_successes"] >= stats_b["task_successes"]
        token_reduction = (stats_b["tokens_unmeasured_or_censored"] == stats_c["tokens_unmeasured_or_censored"] == 0
                           and stats_b["median_tokens_to_first_useful"] and stats_c["median_tokens_to_first_useful"]
                           and stats_c["median_tokens_to_first_useful"] <= 0.75 * stats_b["median_tokens_to_first_useful"])
        b_failures = stats_b["selection_validation_failures"]
        c_failures = stats_c["selection_validation_failures"]
        halved_failures = (b_failures is not None and c_failures is not None
                           and b_failures >= 2 and c_failures <= b_failures // 2)

        if success_ok and cost_ok and (token_reduction or halved_failures):
            c_promotes = True
            c_reason = "C matches/exceeds B successes, cost <= 110% of B, and satisfies token or failure reduction gate"
        else:
            c_reason = "C did not meet all promotion gates over B"
    else:
        c_reason = "Insufficient trials to evaluate promotion thresholds"

    return {
        "arm_a": stats_a,
        "arm_b": stats_b,
        "arm_c": stats_c,
        "b_promising_over_a": b_promising,
        "b_decision_reason": b_reason,
        "c_promotes_over_b": c_promotes,
        "c_decision_reason": c_reason,
    }
