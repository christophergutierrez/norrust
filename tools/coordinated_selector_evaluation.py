"""Matched evaluation for the Coordinated Planner selector treatments.

Remote treatments are admitted only through a frozen selector profile and
their game decisions must join to physical provider receipts by game/request
identity. The local fake selector is a separate, unbilled treatment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import time
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from . import algorithm_strength as strength

TREATMENTS = (
    "coordinated-baseline",
    "coordinated-fake-selector",
    "coordinated-fireworks-glm",
    "coordinated-fireworks-deepseek",
)
LOCAL_TREATMENTS = TREATMENTS[:2]
REMOTE_TREATMENTS = TREATMENTS[2:]
SCHEMA_VERSION = 2
FAKE_CANDIDATE = "objective"
PROFILE_REQUIRED_FIELDS = ("command", "model", "reasoning_effort", "profile_id",
                           "prompt_profile", "limits", "pricing")
PROFILE_LIMIT_FIELDS = ("max_prompt_bytes", "max_output_tokens", "deadline_seconds",
                        "max_requests")


def build_schedule(*, base_seed: int = 38101, gold: int = 300,
                   max_side_turns: int = 200) -> list[dict[str, Any]]:
    """Return 32 matchup cells: 16 paired seeds against each fixed opponent."""
    cells = []
    index = 0
    for opponent in strength.DEFAULT_OPPONENTS:
        for faction in strength.DEFAULT_FACTIONS:
            for side in (0, 1):
                for first in ("team1", "team2"):
                    base = strength._cell(
                        f"{opponent}-{faction}-side{side}-{first}", faction,
                        opponent, side, first, gold, base_seed + index,
                        max_side_turns)
                    base["pair_id"] = base["cell_id"]
                    cells.append(base)
                    index += 1
    return cells


def build_pilot_schedule(seeds: tuple[int, ...] | list[int], *, gold: int = 300,
                         max_side_turns: int = 200) -> list[dict[str, Any]]:
    """Build an explicit small paired pilot; never expands to the 32-cell suite."""
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("pilot seeds must be a non-empty unique list")
    cells = []
    seats = ((0, "team1"), (1, "team1"), (0, "team2"))
    for index, seed in enumerate(seeds):
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("pilot seeds must be non-negative integers")
        side, first = seats[index % len(seats)]
        cell = strength._cell(f"pilot-greedy-undead-seed{seed}-side{side}-{first}", "undead",
                              "greedy", side, first, gold, seed, max_side_turns)
        cell["pair_id"] = cell["cell_id"]
        cells.append(cell)
    return cells


def _validate_profile(treatment: str, profile: Mapping[str, Any] | None) -> dict[str, Any]:
    if treatment in ("coordinated-baseline", "coordinated-fake-selector"):
        if profile is not None:
            raise ValueError(f"{treatment} does not accept a remote selector profile")
        return {}
    if treatment not in REMOTE_TREATMENTS:
        raise ValueError(f"unknown treatment: {treatment}")
    if not isinstance(profile, Mapping):
        raise ValueError(f"{treatment} requires a frozen selector profile")
    missing = [key for key in PROFILE_REQUIRED_FIELDS if key not in profile]
    if missing:
        raise ValueError(f"{treatment} selector profile missing: {', '.join(missing)}")
    command = profile.get("command")
    if (not isinstance(command, Mapping) or not isinstance(command.get("program"), str)
            or not command["program"].strip()
            or not isinstance(command.get("args"), list)
            or any(not isinstance(arg, str) for arg in command["args"])):
        raise ValueError(f"{treatment} selector profile command must contain program and string args")
    expected_model = {
        "coordinated-fireworks-glm": "accounts/fireworks/models/glm-5p3-flash",
        "coordinated-fireworks-deepseek": "accounts/fireworks/models/deepseek-v4p1-flash",
    }[treatment]
    if profile.get("model") != expected_model:
        raise ValueError(f"{treatment} requires model identity {expected_model}")
    for key in ("reasoning_effort", "profile_id", "prompt_profile"):
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise ValueError(f"{treatment} selector profile requires non-empty {key}")
    allowed_efforts = ({"low"} if treatment == "coordinated-fireworks-glm"
                       else {"low", "provider_default_unknown"})
    if profile["reasoning_effort"] not in allowed_efforts:
        raise ValueError(f"{treatment} reasoning effort is outside the frozen selector profile")
    allowed_efforts = ({"low"} if treatment == "coordinated-fireworks-glm"
                       else {"low", "provider_default_unknown"})
    if profile["reasoning_effort"] not in allowed_efforts:
        raise ValueError(f"{treatment} reasoning effort is outside the frozen selector profile")
    limits = profile.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError(f"{treatment} selector profile requires finite limits")
    for key in PROFILE_LIMIT_FIELDS:
        value = limits.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"{treatment} selector profile requires positive {key}")
        if key != "deadline_seconds" and not isinstance(value, int):
            raise ValueError(f"{treatment} selector profile requires integer {key}")
        if key != "deadline_seconds" and not isinstance(value, int):
            raise ValueError(f"{treatment} selector profile requires integer {key}")
    if (limits["max_prompt_bytes"] > 12288 or limits["max_output_tokens"] != 2048
            or limits["deadline_seconds"] != 60 or limits["max_requests"] > 32):
        raise ValueError(f"{treatment} selector profile exceeds the frozen selector limits")
    if (limits["max_prompt_bytes"] > 12288 or limits["max_output_tokens"] != 2048
            or limits["deadline_seconds"] != 60 or limits["max_requests"] > 32):
        raise ValueError(f"{treatment} selector profile exceeds the frozen selector limits")
    pricing = profile.get("pricing")
    if (not isinstance(pricing, Mapping) or not isinstance(pricing.get("date"), str)
            or not pricing["date"].strip() or pricing.get("reasoning_included_in_output") is not True):
        raise ValueError(f"{treatment} selector profile requires dated pricing and reasoning accounting")
    rates = pricing.get("rates")
    if not isinstance(rates, Mapping):
        raise ValueError(f"{treatment} selector profile requires pricing rates")
    for key in ("input_per_million", "cached_input_per_million", "output_per_million"):
        rate = rates.get(key)
        if (isinstance(rate, bool) or not isinstance(rate, (int, float))
                or not math.isfinite(rate) or rate < 0):
            raise ValueError(f"{treatment} selector profile requires valid pricing rate {key}")
    return dict(profile)


def command_for(cell: Mapping[str, Any], treatment: str, binary: Path,
                record_dir: Path, *, profile: Mapping[str, Any] | None = None) -> list[str]:
    if treatment not in TREATMENTS:
        raise ValueError(f"unknown treatment: {treatment}")
    profile = _validate_profile(treatment, profile)
    command = strength.command_for(cell, binary, record_dir)
    side_flag = f"--ai{int(cell['controlled_side']) + 1}"
    if command[command.index(side_flag) + 1] != "coordinated":
        raise ValueError("Coordinated selector treatment must run the Coordinated Planner")
    if binary.name == "greedy_driver" or any(arg in command for arg in
            ("--llm-side", "--decision-mode", "--player-model", "--model-command")):
        raise ValueError("direct-action player path cannot be used for selector evaluation")
    if treatment == "coordinated-fake-selector":
        command += ["--selector-candidate", FAKE_CANDIDATE,
                    "--selector-side", str(int(cell["controlled_side"]) + 1)]
    elif treatment in REMOTE_TREATMENTS:
        command += ["--selector-command", profile["command"]["program"]]
        for arg in profile["command"]["args"]:
            command += ["--selector-arg", arg]
        command += ["--selector-usage-sidecar", str((record_dir.parent / "selector-usage.ndjson").resolve()),
                    "--selector-evidence-dir", str((record_dir.parent / "selector-evidence").resolve())]
        command += ["--selector-side", str(int(cell["controlled_side"]) + 1)]
    return command


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"missing game trace: {path}")
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed game trace: {path}: {exc}") from exc


def _read_usage(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed selector usage sidecar: {path}: {exc}") from exc


def _linked_receipts(game_id: str, request_id: str,
                     usage_rows: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    rows = [row for row in usage_rows
            if row.get("game_id") == game_id and row.get("request_id") == request_id]
    dispatches = [row for row in rows if row.get("record_kind") == "dispatch"]
    finals = [row for row in rows if row.get("record_kind") == "final"]
    if len(dispatches) != 1 or len(finals) != 1:
        raise ValueError("selector usage join must have exactly one dispatch and one final receipt")
    dispatch, final = dispatches[0], finals[0]
    if not dispatch.get("call_id") or dispatch.get("call_id") != final.get("call_id"):
        raise ValueError("selector dispatch/final receipts have mismatched physical call IDs")
    return [dispatch, final]


def _evidence_call_dir(evidence_dir: Path, call_id: str) -> Path:
    safe_id = "".join(char if char.isalnum() or char in "_.-" else "_" for char in call_id)
    return evidence_dir / safe_id


def _validate_call_evidence(evidence_dir: Path, call_id: str, request_id: str,
                            profile: Mapping[str, Any], final: Mapping[str, Any]) -> dict[str, Any]:
    call_dir = _evidence_call_dir(evidence_dir, call_id)
    required = ("prompt.txt", "prompt.sha256", "request_context.json", "payload.json")
    if any(not (call_dir / name).is_file() for name in required):
        raise ValueError("provider call is missing prompt, request context, or payload evidence")
    prompt_bytes = (call_dir / "prompt.txt").read_bytes()
    digest = hashlib.sha256(prompt_bytes).hexdigest()
    if (call_dir / "prompt.sha256").read_text().strip() != digest:
        raise ValueError("provider prompt evidence hash mismatch")
    if len(prompt_bytes) > profile["limits"]["max_prompt_bytes"]:
        raise ValueError("provider prompt exceeds frozen selector profile")
    try:
        context = json.loads((call_dir / "request_context.json").read_text())
        payload = json.loads((call_dir / "payload.json").read_text())
    except json.JSONDecodeError as exc:
        raise ValueError("provider call identity evidence is malformed") from exc
    if context.get("harness_request_id") != request_id:
        raise ValueError("provider evidence request identity mismatch")
    if final.get("prompt_layout_version") != profile["prompt_profile"]:
        raise ValueError("provider prompt profile differs from frozen selector profile")
    if payload.get("model") != profile["model"]:
        raise ValueError("provider payload model differs from frozen selector profile")
    if payload.get("max_tokens") != profile["limits"]["max_output_tokens"]:
        raise ValueError("provider payload output limit differs from frozen selector profile")
    expected_effort = (None if profile["reasoning_effort"] == "provider_default_unknown"
                       else profile["reasoning_effort"])
    if payload.get("reasoning_effort") != expected_effort:
        raise ValueError("provider payload reasoning effort differs from frozen selector profile")
    return {"prompt_bytes": len(prompt_bytes), "prompt_sha256": digest,
            "evidence_dir": str(call_dir)}


def _usage_snapshot(usage_rows: list[Mapping[str, Any]],
                    profile: Mapping[str, Any] | None) -> dict[str, Any]:
    by_call: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in usage_rows:
        if isinstance(row.get("call_id"), str):
            by_call[row["call_id"]].append(row)
    costs: list[int | None] = []
    incomplete = False
    for records in by_call.values():
        dispatches = [r for r in records if r.get("record_kind") == "dispatch"]
        finals = [r for r in records if r.get("record_kind") == "final"]
        if len(dispatches) != 1 or len(finals) != 1 or profile is None:
            costs.append(None)
            incomplete = True
            continue
        cost = _cost_microusd(finals[0], profile["pricing"])
        costs.append(cost)
        incomplete |= cost is None
    return {"provider_call_count": len(by_call),
            "provider_call_costs_microusd": costs,
            "provider_usage_missing": incomplete}


def _cost_microusd(final: Mapping[str, Any], pricing: Mapping[str, Any]) -> int | None:
    tokens = (final.get("input_tokens"), final.get("cached_input_tokens"),
              final.get("output_tokens"))
    rates = pricing.get("rates") if isinstance(pricing, Mapping) else None
    if any(isinstance(token, bool) or not isinstance(token, int) for token in tokens):
        return None
    if not isinstance(rates, Mapping):
        return None
    input_rate = rates.get("input_per_million")
    cached_rate = rates.get("cached_input_per_million")
    output_rate = rates.get("output_per_million")
    if any(isinstance(rate, bool) or not isinstance(rate, (int, float))
           or rate < 0 for rate in (input_rate, cached_rate, output_rate)):
        return None
    input_tokens, cached_tokens, output_tokens = tokens
    if cached_tokens > input_tokens:
        return None
    usd = ((input_tokens - cached_tokens) * input_rate + cached_tokens * cached_rate
           + output_tokens * output_rate) / 1_000_000
    return int(round(usd * 1_000_000))


def validate_trace(cell: Mapping[str, Any], treatment: str, result: Mapping[str, Any],
                   trace: list[Mapping[str, Any]], *,
                   usage_rows: list[Mapping[str, Any]] | None = None,
                   selector_profile: Mapping[str, Any] | None = None,
                   expected_game_id: str | None = None,
                   evidence_dir: Path | None = None) -> dict[str, Any]:
    if treatment not in TREATMENTS:
        raise ValueError(f"unknown treatment: {treatment}")
    selector_profile = _validate_profile(treatment, selector_profile)
    usage_rows = usage_rows or []
    outcome = strength.validate_engine_result(cell, result)
    if len(trace) < 2 or trace[0].get("type") != "metadata" or trace[-1].get("type") != "terminal":
        raise ValueError("trace lacks opening metadata or terminal boundary")
    if trace[0].get("input_seed") != cell["seed"]:
        raise ValueError("trace seed mismatch")
    terminal = trace[-1]
    if terminal.get("side_turns_executed") != result.get("completed_side_turns"):
        raise ValueError("trace terminal turn count mismatch")

    game_id = expected_game_id or trace[0].get("game_id")
    if treatment in REMOTE_TREATMENTS:
        if not isinstance(game_id, str) or not game_id:
            raise ValueError("real selector trace lacks game_id identity")
        if trace[0].get("game_id") != game_id:
            raise ValueError("trace metadata game_id does not match frozen game identity")

    decisions = []
    selected_side = int(cell["controlled_side"])
    seen_decision_ids: set[str] = set()
    seen_request_ids: set[str] = set()
    linked_call_ids: set[str] = set()
    provider_call_costs: list[int | None] = []
    prompt_evidence: list[dict[str, Any]] = []
    for row in trace:
        if row.get("type") != "coordinated_decision":
            continue
        telemetry = row.get("telemetry")
        if not isinstance(telemetry, dict):
            raise ValueError("malformed coordinated decision telemetry")
        invoked = telemetry.get("selector_invoked") is True
        if int(row.get("side", -1)) != selected_side:
            if invoked:
                raise ValueError("selector invoked on uncontrolled side")
            continue
        if treatment == "coordinated-baseline" and invoked:
            raise ValueError("baseline treatment invoked selector")
        if treatment == "coordinated-baseline":
            decisions.append({**telemetry, "decision_state": "baseline"})
            continue
        if not invoked:
            status = telemetry.get("response_status") or row.get("response_status")
            skip_reason = status if status in ("skipped_clear_lead", "disabled",
                                               "budget_exhausted", "circuit_open") else None
            if treatment != "coordinated-baseline" and skip_reason is None:
                raise ValueError("selector non-invocation lacks explicit skip status")
            decisions.append({**telemetry, "decision_state": "skipped",
                              "skip_reason": skip_reason})
            continue

        expected_backend = "test-fake" if treatment == "coordinated-fake-selector" else "command"
        if row.get("backend") != expected_backend:
            raise ValueError(f"{treatment} trace backend mismatch: expected {expected_backend}")
        if treatment == "coordinated-fake-selector":
            usage = row.get("usage")
            if (not isinstance(usage, Mapping)
                    or any(usage.get(key) is not None for key in
                           ("input_tokens", "cached_input_tokens", "output_tokens",
                            "reasoning_tokens", "cost_microusd"))):
                raise ValueError("fake selector must not claim measured provider usage")
        if treatment in REMOTE_TREATMENTS:
            decision_id = row.get("decision_id")
            request_id = row.get("request_id")
            if not isinstance(decision_id, str) or not decision_id:
                raise ValueError("real selector trace lacks decision_id identity")
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("real selector decision lacks linked provider request_id")
            if decision_id in seen_decision_ids:
                raise ValueError("reused selector decision_id")
            if request_id in seen_request_ids:
                raise ValueError("reused selector request_id")
            seen_decision_ids.add(decision_id)
            seen_request_ids.add(request_id)
            if row.get("game_id") != game_id:
                raise ValueError("real selector decision game_id mismatch")
            linked = _linked_receipts(str(game_id), request_id, usage_rows)
            call_id = str(linked[0]["call_id"])
            if call_id in linked_call_ids:
                raise ValueError("one physical provider call was linked to multiple decisions")
            linked_call_ids.add(call_id)
            final = linked[1]
            if final.get("requested_model") != selector_profile["model"]:
                raise ValueError("provider receipt model differs from frozen selector profile")
            expected_effort = (None if selector_profile["reasoning_effort"] == "provider_default_unknown"
                               else selector_profile["reasoning_effort"])
            if final.get("requested_reasoning_effort") != expected_effort:
                raise ValueError("provider receipt reasoning effort differs from frozen selector profile")
            if final.get("output_limit") != selector_profile["limits"]["max_output_tokens"]:
                raise ValueError("provider receipt output limit differs from frozen selector profile")
            if evidence_dir is None:
                raise ValueError("real selector validation requires isolated provider evidence directory")
            prompt_evidence.append(_validate_call_evidence(evidence_dir, call_id, request_id,
                                                            selector_profile, final))
            provider_call_costs.append(_cost_microusd(final, selector_profile["pricing"]))

        ids = {c.get("candidate_id") for c in telemetry.get("candidates", [])
               if isinstance(c, Mapping)}
        request = row.get("request")
        summaries = request.get("candidates") if isinstance(request, Mapping) else None
        if not isinstance(summaries, list) or not summaries:
            raise ValueError("selector decision lacks full candidate summaries")
        offered_ids = {candidate.get("candidate_id") for candidate in summaries
                       if isinstance(candidate, Mapping)}
        if len(offered_ids) != len(summaries):
            raise ValueError("selector request candidate summaries are malformed or duplicated")
        selected = telemetry.get("selected_candidate_id")
        response = row.get("response")
        response_candidate = response.get("candidate_id") if isinstance(response, Mapping) else None
        if selected is None:
            selected = response_candidate
        if selected not in ids or selected not in offered_ids:
            raise ValueError("selector chose a candidate absent from telemetry")
        baseline = telemetry.get("baseline_candidate_id")
        if baseline not in offered_ids:
            raise ValueError("deterministic baseline is absent from offered candidate summaries")
        fallback_reason = telemetry.get("fallback_reason") or row.get("fallback_reason")
        response_status = telemetry.get("response_status") or row.get("response_status")
        if fallback_reason is None:
            if response_status not in ("accepted", "selected", "success"):
                raise ValueError("selector response has unexplained status")
            if response_candidate != selected:
                raise ValueError("accepted selector response differs from telemetry choice")
            decision_state = "model_accepted" if treatment in REMOTE_TREATMENTS else "fake_accepted"
        else:
            if response_status not in ("rejected", "error", "failed", "timeout", "fallback"):
                raise ValueError("selector fallback has unexplained status")
            if selected != baseline:
                raise ValueError("selector fallback did not use the deterministic baseline")
            decision_state = "fallback"
        cost_microusd = None
        if treatment in REMOTE_TREATMENTS and decision_state == "model_accepted":
            if final.get("record_kind") != "final" or final.get("status") != "completed":
                raise ValueError("accepted model choice lacks a completed provider usage receipt")
            if any(final.get(field) is None for field in
                   ("input_tokens", "cached_input_tokens", "output_tokens")):
                raise ValueError("accepted model choice has incomplete provider token usage")
            if final["output_tokens"] > selector_profile["limits"]["max_output_tokens"]:
                raise ValueError("provider output exceeded frozen selector profile")
            cost_microusd = _cost_microusd(final, selector_profile["pricing"])
            if cost_microusd is None:
                raise ValueError("accepted model choice has unknown provider cost")
        decisions.append({**telemetry, "decision_state": decision_state,
                          "selected_candidate_id": selected,
                          "fallback_reason": fallback_reason,
                          "response_status": response_status,
                          "cost_microusd": cost_microusd})

    if treatment in REMOTE_TREATMENTS:
        linked_requests = {row.get("request_id") for row in usage_rows
                           if row.get("game_id") == game_id}
        if linked_requests - seen_request_ids:
            raise ValueError("orphan provider usage receipt has no selector decision")
    return {"outcome": outcome, "decisions": decisions,
            "decision_count": len(decisions), "termination_reason": result.get("termination_reason"),
            "winner_side": result.get("winner_side"),
            "effective_seed": result.get("effective_seed"),
            "provider_call_count": len(linked_call_ids),
            "provider_call_costs_microusd": provider_call_costs,
            "prompt_evidence": prompt_evidence,
            "usage_rows": list(usage_rows) if treatment in REMOTE_TREATMENTS else []}


def _treatment_summary(rows: list[Mapping[str, Any]], treatment: str) -> dict[str, Any]:
    outcome_counts = Counter(row.get("outcome", "invalid") for row in rows)
    statuses = Counter(row.get("status", "unrun") for row in rows)
    telemetry = [d for row in rows if row.get("status") == "completed"
                 for d in row.get("decisions", [])]
    invoked = [d for d in telemetry if d.get("selector_invoked")]
    fallback = [d for d in telemetry if d.get("decision_state") == "fallback"]
    skipped = [d for d in telemetry if d.get("decision_state") == "skipped"]
    accepted = [d for d in telemetry if d.get("decision_state") == "model_accepted"]
    fake_accepted = [d for d in telemetry if d.get("decision_state") == "fake_accepted"]
    agreed = [d for d in invoked if d.get("selected_candidate_id") == d.get("baseline_candidate_id")]
    margins = [float(d["score_margin"]) for d in telemetry if isinstance(d.get("score_margin"), (int, float))]
    latencies = [int(d["latency_ms"]) for d in invoked if isinstance(d.get("latency_ms"), int)]
    decision_costs = [int(d["cost_microusd"]) for d in accepted
                      if isinstance(d.get("cost_microusd"), int)]
    physical_calls = sum(int(row.get("provider_call_count", 0) or 0)
                         for row in rows)
    costs = [int(cost) for row in rows
             for cost in row.get("provider_call_costs_microusd", []) if isinstance(cost, int)]
    unknown_usage = any(row.get("provider_usage_missing") is True for row in rows)
    if treatment == "coordinated-fake-selector":
        cost_total, cost_basis, usage_coverage = 0, "fake_selector_zero_provider_cost", "not_applicable"
    elif treatment in REMOTE_TREATMENTS:
        if physical_calls == 0 and not unknown_usage:
            usage_coverage = "not_applicable"
            cost_total = None
            cost_basis = "no_provider_calls"
        else:
            usage_coverage = "complete" if len(costs) == physical_calls and not unknown_usage else "incomplete"
            cost_total = sum(costs) if usage_coverage == "complete" else None
            cost_basis = "dated_provider_usage_estimate" if cost_total is not None else "unknown_incomplete_provider_usage"
    else:
        cost_total, cost_basis, usage_coverage = None, "not_applicable", "not_applicable"
    return {
        "scheduled": len(rows), "completed": statuses["completed"],
        "wins": outcome_counts["win"], "losses": outcome_counts["loss"],
        "draws": outcome_counts["draw"], "caps": outcome_counts["cap"],
        "timeouts": statuses["timeout"], "invalid": statuses["invalid"],
        "unrun": statuses["unrun"], "failed": statuses["failed"],
        "win_rate_all_scheduled": outcome_counts["win"] / len(rows) if rows else None,
        "decisions": len(telemetry), "selector_invocations": len(invoked),
        "selector_skips": len(skipped), "model_accepted_choices": len(accepted),
        "fake_accepted_choices": len(fake_accepted), "physical_provider_calls": physical_calls,
        "invocation_rate": len(invoked) / len(telemetry) if telemetry else 0.0,
        "agreement_count": len(agreed), "disagreement_count": len(invoked) - len(agreed),
        "agreement_rate": len(agreed) / len(invoked) if invoked else None,
        "fallback_count": len(fallback),
        "fallback_rate": len(fallback) / len(invoked) if invoked else None,
        "malformed_count": sum(d.get("response_status") == "malformed" for d in invoked),
        "unknown_id_count": sum(d.get("response_status") in ("unknown_id", "invalid_id") for d in invoked),
        "score_margin_mean": sum(margins) / len(margins) if margins else None,
        "latency_ms_observed": len(latencies),
        "latency_ms_mean": sum(latencies) / len(latencies) if latencies else None,
        "cost_microusd_observed": len(costs),
        "accepted_choice_cost_microusd_observed": len(decision_costs),
        "cost_microusd_total": cost_total,
        "cost_basis": cost_basis, "usage_coverage": usage_coverage,
        "status_counts": dict(statuses),
    }


def build_report(schedule: list[Mapping[str, Any]], results: list[Mapping[str, Any]],
                 *, manifest: Mapping[str, Any] | None = None,
                 treatments: tuple[str, ...] = TREATMENTS) -> dict[str, Any]:
    if not treatments or treatments[0] != "coordinated-baseline" or any(t not in TREATMENTS for t in treatments):
        raise ValueError("treatments must start with coordinated-baseline and use known names")
    expected = {(str(cell["pair_id"]), treatment) for cell in schedule for treatment in treatments}
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    invalid_rows = []
    for row in results:
        key = (str(row.get("pair_id")), str(row.get("treatment")))
        if key not in expected:
            invalid_rows.append({"key": list(key), "error": "foreign result"})
        elif key in indexed:
            invalid_rows.append({"key": list(key), "error": "duplicate result"})
        else:
            indexed[key] = row

    rows = []
    paired = []
    for cell in schedule:
        pair = {treatment: dict(indexed.get((str(cell["pair_id"]), treatment), {
            "pair_id": cell["pair_id"], "treatment": treatment, "status": "unrun",
            "outcome": None, "opponent": cell["opponent"], "faction": cell["faction"],
            "controlled_side": cell["controlled_side"], "seed": cell["seed"],
            "decisions": [],
        })) for treatment in treatments}
        for treatment, row in pair.items():
            row.update({"opponent": cell["opponent"], "faction": cell["faction"],
                        "controlled_side": cell["controlled_side"], "seed": cell["seed"]})
            rows.append(row)
        baseline = pair["coordinated-baseline"]
        paired.append({"pair_id": cell["pair_id"], "opponent": cell["opponent"],
                       "faction": cell["faction"], "seed": cell["seed"],
                       "comparisons": {t: {
                           "baseline_outcome": baseline.get("outcome"),
                           "treatment_outcome": pair[t].get("outcome"),
                           "win_delta": (1 if pair[t].get("outcome") == "win" else 0)
                                        - (1 if baseline.get("outcome") == "win" else 0),
                           "baseline_decisions": baseline.get("decision_count", 0),
                           "treatment_decisions": pair[t].get("decision_count", 0),
                       } for t in treatments if t != "coordinated-baseline"}})
    summaries = {treatment: _treatment_summary([r for r in rows if r["treatment"] == treatment], treatment)
                 for treatment in treatments}
    verdicts = {}
    for treatment, summary in summaries.items():
        all_games_observed = summary["completed"] == summary["scheduled"]
        operational = "pass" if all_games_observed else "fail"
        if treatment in REMOTE_TREATMENTS:
            if summary["physical_provider_calls"] and summary["usage_coverage"] != "complete":
                operational = "fail"
            if summary["unrun"] or summary["invalid"] or summary["timeouts"] or summary["failed"]:
                operational = "fail"
            if summary["model_accepted_choices"]:
                implementation = "pass"
            elif summary["selector_invocations"]:
                implementation = "fail"
            else:
                implementation = "inconclusive"
        elif treatment == "coordinated-fake-selector":
            implementation = "pass" if summary["fake_accepted_choices"] else "inconclusive"
        else:
            implementation = "baseline"
        strength_verdict = "measured" if all_games_observed else "inconclusive"
        verdicts[treatment] = {"implementation": implementation,
                               "operations": operational,
                               "strength": strength_verdict}
    by_opponent = {}
    for opponent in strength.DEFAULT_OPPONENTS:
        by_opponent[opponent] = {
            treatment: _treatment_summary([r for r in rows if r["treatment"] == treatment and r["opponent"] == opponent], treatment)
            for treatment in treatments
        }
    complete = not invalid_rows and all(
        summaries[treatment][key] == 0
        for treatment in treatments for key in ("timeouts", "invalid", "unrun", "failed"))
    return {"schema_version": SCHEMA_VERSION, "status": "complete" if complete else "incomplete",
            "treatment_names": list(treatments), "manifest": dict(manifest or {}),
            "scheduled_matchup_cells": len(schedule), "scheduled_paired_games": len(schedule) * len(treatments),
            "paired_seed_cells": paired, "summary": summaries, "verdicts": verdicts,
            "by_opponent": by_opponent,
            "invalid_records": invalid_rows,
            "matched_win_delta": {opponent: {
                treatment: (
                    by_opponent[opponent][treatment]["win_rate_all_scheduled"]
                    - by_opponent[opponent]["coordinated-baseline"]["win_rate_all_scheduled"]
                    if by_opponent[opponent][treatment]["win_rate_all_scheduled"] is not None
                    and by_opponent[opponent]["coordinated-baseline"]["win_rate_all_scheduled"] is not None
                    else None
                )
                for treatment in treatments if treatment != "coordinated-baseline"
            } for opponent in strength.DEFAULT_OPPONENTS},
            "note": "Fake selector is local and unbilled. Remote costs require linked measured receipts and dated pricing. Latency remains unknown when telemetry omits it; all scheduled cells remain in denominators."}


def _run_one(cell: Mapping[str, Any], treatment: str, binary: Path, out_dir: Path,
             timeout: float, *, profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    cell_id = str(cell["pair_id"])
    cell_dir = out_dir / "cells" / cell_id / treatment
    trace_dir = cell_dir / "trace"
    cell_dir.mkdir(parents=True, exist_ok=False)
    command = command_for(cell, treatment, binary, trace_dir, profile=profile)
    (cell_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    game_id = f"{cell_id}:{treatment}"
    env = os.environ.copy()
    evidence_dir = None
    usage_path = cell_dir / "selector-usage.ndjson"
    if treatment in REMOTE_TREATMENTS:
        usage_path = usage_path.resolve()
        evidence_dir = (cell_dir / "selector-evidence").resolve()
        evidence_dir.mkdir(parents=True, exist_ok=False)
        env.update({"NORRUST_GAME_ID": game_id,
                    "NORRUST_USAGE_SIDECAR": str(usage_path),
                    "NORRUST_EVIDENCE_DIR": str(evidence_dir)})
    (cell_dir / "launch.json").write_text(json.dumps({
        "game_id": game_id, "pair_id": cell_id, "treatment": treatment,
        "controlled_side": cell["controlled_side"], "algorithm": cell["controlled_algorithm"],
        "binary": str(binary.resolve()), "selector_profile": dict(profile or {}),
        "command": command,
        "usage_sidecar": str((cell_dir / "selector-usage.ndjson").resolve())
                         if treatment in REMOTE_TREATMENTS else None,
        "evidence_dir": str((cell_dir / "selector-evidence").resolve())
                        if treatment in REMOTE_TREATMENTS else None,
    }, indent=2, sort_keys=True) + "\n")
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        usage_rows = _read_usage(usage_path) if treatment in REMOTE_TREATMENTS else []
        usage_stats = _usage_snapshot(usage_rows, profile) if treatment in REMOTE_TREATMENTS else {}
        if treatment in REMOTE_TREATMENTS and not usage_path.is_file():
            usage_stats["provider_usage_missing"] = True
        return {"pair_id": cell_id, "treatment": treatment, "status": "timeout",
                "outcome": None, "elapsed_seconds": time.monotonic() - started,
                "error": str(exc), "opponent": cell["opponent"], "faction": cell["faction"],
                "controlled_side": cell["controlled_side"], "seed": cell["seed"], **usage_stats}
    (cell_dir / "stdout.log").write_text(proc.stdout)
    (cell_dir / "stderr.log").write_text(proc.stderr)
    base = {"pair_id": cell_id, "treatment": treatment, "opponent": cell["opponent"],
            "faction": cell["faction"], "controlled_side": cell["controlled_side"],
            "seed": cell["seed"], "exit_code": proc.returncode,
            "elapsed_seconds": time.monotonic() - started,
            "stdout": str((cell_dir / "stdout.log").relative_to(out_dir)),
            "stderr": str((cell_dir / "stderr.log").relative_to(out_dir))}
    usage_rows = _read_usage(usage_path) if treatment in REMOTE_TREATMENTS else []
    usage_stats = _usage_snapshot(usage_rows, profile) if treatment in REMOTE_TREATMENTS else {}
    if proc.returncode != 0:
        if treatment in REMOTE_TREATMENTS and not usage_path.is_file():
            usage_stats["provider_usage_missing"] = True
        return {**base, **usage_stats, "status": "failed", "outcome": None,
                "error": f"exit {proc.returncode}"}
    engine_rows = strength._result_lines(proc.stdout)
    try:
        if len(engine_rows) != 1:
            raise ValueError(f"expected one engine result, got {len(engine_rows)}")
        trace = _read_trace(trace_dir / "game-00001.ndjson")
        trace_game_id = trace[0].get("game_id") if trace else None
        if treatment in REMOTE_TREATMENTS and (not isinstance(trace_game_id, str)
                                                or not trace_game_id):
            raise ValueError("real selector trace lacks engine game_id identity")
        decoded = validate_trace(cell, treatment, engine_rows[0], trace,
                                 usage_rows=usage_rows, selector_profile=profile,
                                 expected_game_id=trace_game_id if treatment in REMOTE_TREATMENTS else None,
                                 evidence_dir=evidence_dir)
        if treatment in REMOTE_TREATMENTS and decoded["provider_call_count"] == 0:
            usage_stats["provider_usage_missing"] = False
        return {**base, **usage_stats, "status": "completed", **decoded,
                "trace": str((trace_dir / "game-00001.ndjson").relative_to(out_dir))}
    except (ValueError, OSError) as exc:
        if treatment in REMOTE_TREATMENTS:
            usage_stats["provider_usage_missing"] = True
        return {**base, **usage_stats, "status": "invalid", "outcome": None, "error": str(exc)}


def run_screen(out_dir: Path, binary: Path, *, base_seed: int = 38101,
               gold: int = 300, max_side_turns: int = 200,
               timeout_seconds: float = 180.0,
               treatments: tuple[str, ...] = LOCAL_TREATMENTS,
               selector_profiles: Mapping[str, Mapping[str, Any]] | None = None,
               pilot_seeds: tuple[int, ...] | list[int] | None = None) -> dict[str, Any]:
    if not treatments or treatments[0] != "coordinated-baseline" or any(t not in TREATMENTS for t in treatments):
        raise ValueError("treatments must start with coordinated-baseline and use known names")
    selector_profiles = dict(selector_profiles or {})
    resolved_profiles = {}
    for treatment in treatments:
        if treatment in REMOTE_TREATMENTS:
            resolved_profiles[treatment] = _validate_profile(treatment, selector_profiles.get(treatment))
        elif treatment in selector_profiles:
            raise ValueError(f"unexpected selector profile for {treatment}")
    if set(selector_profiles) - set(treatments):
        raise ValueError("selector profile supplied for a treatment that is not scheduled")
    schedule = (build_pilot_schedule(pilot_seeds, gold=gold, max_side_turns=max_side_turns)
                if pilot_seeds is not None else
                build_schedule(base_seed=base_seed, gold=gold, max_side_turns=max_side_turns))
    out_dir.mkdir(parents=True, exist_ok=False)
    if not binary.is_file():
        raise ValueError(f"self-play binary does not exist: {binary}")
    manifest = {"schema_version": SCHEMA_VERSION, "status": "frozen",
                "source_commit": strength._git(strength.ROOT, "rev-parse", "HEAD"),
                "source_tree": strength._git(strength.ROOT, "rev-parse", "HEAD^{tree}"),
                "binary": str(binary.resolve()), "binary_sha256": strength.sha256_file(binary),
                "data_sha256": strength.data_sha256(), "treatments": list(treatments),
                "selector_profiles": {
                    "coordinated-baseline": {"backend": "none", "profile_id": "planner-baseline-v1"},
                    "coordinated-fake-selector": {"backend": "fake", "profile_id": "fake-objective-v1",
                                                  "candidate_id": FAKE_CANDIDATE,
                                                  "provider_cost_microusd": 0},
                    **{t: {"backend": "fireworks-command", **resolved_profiles[t]}
                       for t in resolved_profiles},
                },
                "settings": {"base_seed": base_seed,
                             "pilot_seeds": list(pilot_seeds) if pilot_seeds is not None else None,
                             "gold": gold, "max_side_turns": max_side_turns,
                             "scenario": "big_battle_6", "recruitment_policy": "first-affordable",
                             "second_gold": 0, "threads": 1, "timeout_seconds": timeout_seconds},
                "schedule": schedule}
    manifest["schedule_sha256"] = hashlib.sha256(strength._canonical_bytes(schedule)).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    results = []
    # Complete deterministic baselines before dispatching any paid model games.
    treatment_order = sorted(treatments, key=lambda t: (t not in LOCAL_TREATMENTS, treatments.index(t)))
    for treatment in treatment_order:
        for cell in schedule:
            results.append(_run_one(cell, treatment, binary.resolve(), out_dir, timeout_seconds,
                                    profile=resolved_profiles.get(treatment)))
            (out_dir / "results.json").write_text(json.dumps({"results": results}, indent=2) + "\n")
    report = build_report(schedule, results, manifest=manifest, treatments=treatments)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=strength.ROOT / "norrust_core/target/release/self-play")
    parser.add_argument("--base-seed", type=int, default=38101)
    parser.add_argument("--gold", type=int, default=300)
    parser.add_argument("--max-side-turns", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--treatment", choices=TREATMENTS, action="append")
    parser.add_argument("--selector-profiles", type=Path,
                        help="JSON mapping remote treatment names to frozen selector profiles")
    parser.add_argument("--pilot-seeds", type=int, nargs="+",
                        help="run only these paired seeds (undead vs Greedy; seats alternate side0/team1, side1/team1, side0/team2)")
    args = parser.parse_args(argv)
    if args.gold < 1 or args.max_side_turns < 1 or args.timeout_seconds <= 0:
        parser.error("gold, cap, and timeout must be positive")
    treatments = tuple(args.treatment or LOCAL_TREATMENTS)
    profiles = {}
    if args.selector_profiles:
        profiles = json.loads(args.selector_profiles.read_text())
        if not isinstance(profiles, dict):
            parser.error("selector profile file must be a JSON object")
    report = run_screen(args.out_dir, args.binary, base_seed=args.base_seed,
                        gold=args.gold, max_side_turns=args.max_side_turns,
                        timeout_seconds=args.timeout_seconds, treatments=treatments,
                        selector_profiles=profiles, pilot_seeds=args.pilot_seeds)
    print(json.dumps({"status": report["status"], "summary": report["summary"]}, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
