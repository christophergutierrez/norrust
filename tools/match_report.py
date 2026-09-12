"""Small truthful report helper for model-game NDJSON attempts."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


_TYPED_TERMINAL_TYPES = {"model_error", "budget_interrupted", "query_error",
                         "checkpoint_error", "preflight_error", "action_failure",
                         "observer_interrupted"}
_BUDGET_CODES = {"max_game_total_tokens_exhausted", "model_calls_budget_exhausted"}


def terminal_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    for item in reversed(records):
        if item.get("type") == "terminal":
            return item
        if item.get("type") in _TYPED_TERMINAL_TYPES and (
                item.get("type") == "budget_interrupted"
                or isinstance(item.get("terminal_class"), str)
                or item.get("type") == "model_error"):
            return item
    return {}


def terminal_class(record: dict[str, Any]) -> str | None:
    if record.get("type") == "budget_interrupted":
        return "budget_interrupted"
    reason = record.get("reason") or record.get("termination_reason")
    code = record.get("code") or record.get("failure_code") or record.get("error_code")
    # Older clients wrote budget stops as model_invalid.  This is a derived
    # report correction from explicit budget evidence; raw records stay intact.
    if reason == "budget_interrupted" or code in _BUDGET_CODES:
        return "budget_interrupted"
    value = record.get("terminal_class")
    return value if isinstance(value, str) else None


def load_records(path: str | Path) -> list[dict[str, Any]]:
    records = []
    for raw in Path(path).read_text().splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


def aggregate_publication(records: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Summarize `tools.publish_reply` validation-log attempts, or ``None``.

    A missing local validation record (no log supplied or found) is unknown
    evidence, not a perfect first-attempt score, so the caller must pass
    ``None`` rather than an empty list to mean "no record available". Each
    request's attempts are ordered by timestamp; a request whose first
    attempt already published is first-attempt-valid, one whose later
    attempt published after an earlier invalid one is repaired, and one all
    of whose recorded attempts stayed invalid is unresolved (still visible
    here even if the match ended with no later prompt).
    """
    if records is None:
        return None
    by_request: dict[str, list[dict[str, Any]]] = {}
    for item in records:
        request_id = item.get("request_id")
        if isinstance(request_id, str) and request_id:
            by_request.setdefault(request_id, []).append(item)
    first_attempt_valid = 0
    repaired = 0
    unresolved = 0
    total_attempts = 0
    for attempts in by_request.values():
        attempts = sorted(attempts, key=lambda item: item.get("timestamp", 0))
        total_attempts += len(attempts)
        published_index = next((index for index, item in enumerate(attempts)
                                if item.get("status") != "invalid"), None)
        if published_index is None:
            unresolved += 1
        elif published_index == 0:
            first_attempt_valid += 1
        else:
            repaired += 1
    return {
        "requests": len(by_request),
        "first_attempt_valid": first_attempt_valid,
        "repaired": repaired,
        "unresolved": unresolved,
        "total_attempts": total_attempts,
    }


def _forced_partial_limit_boundaries(records: list[dict[str, Any]], boundaries: list[dict[str, Any]]) -> set[int]:
    """Find safety finishes by stable identity, or immediate legacy chronology."""
    forced = [item for item in records if item.get("type") == "partial_limit_finish"]
    positions = {id(item): index for index, item in enumerate(records)}
    boundary_positions = [positions[id(item)] for item in boundaries]
    result: set[int] = {index for index, boundary in enumerate(boundaries)
                        if boundary.get("forced_finish") is True}
    for item in forced:
        explicit = [index for index, boundary in enumerate(boundaries)
                    if (item.get("side_turn_id") is not None
                        and item.get("side_turn_id") == boundary.get("side_turn_id"))
                    or (item.get("state_revision") is not None
                        and item.get("state_revision") == boundary.get("state_revision"))]
        if len(explicit) == 1:
            result.add(explicit[0])
            continue
        position = positions[id(item)]
        next_forced = min((positions[id(other)] for other in forced
                           if positions[id(other)] > position), default=len(records))
        following = [index for index, boundary_position in enumerate(boundary_positions)
                     if position < boundary_position < next_forced]
        if len(following) == 1:
            result.add(following[0])
    return result


def classify(records: list[dict[str, Any]],
             publication_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    terminal = terminal_record(records)
    metadata = next((item for item in records if item.get("type") == "metadata"), {})
    events = [item.get("line", {}) for item in records if item.get("type") == "driver"]
    accepted = [item for item in events if item.get("type") == "events"]
    boundaries = [item for item in records
                  if item.get("type") == "turn_boundary" and item.get("accepted") is True]
    forced_boundary_indexes = _forced_partial_limit_boundaries(records, boundaries)
    handoff_reviews = [item for item in records if item.get("type") == "handoff_review"]
    # Only forwarded batches are eligible. Tool requests and generated fallback
    # orders have no submitted model response and therefore do not enter the
    # denominator. A batch's annotation is authoritative on that exact record.
    annotation_counts = Counter()
    rule_counts = Counter()
    for batch in records:
        if (batch.get("type") != "forwarded_orders"
                or not isinstance(batch.get("orders"), list)
                or not isinstance(batch.get("request_id"), str)
                or not batch["request_id"]):
            continue
        annotation = batch.get("decision_annotation")
        status = annotation.get("status") if isinstance(annotation, dict) else None
        if status == "not_applicable":
            continue
        if status not in {"valid", "missing", "invalid", "not_applicable"}:
            status = "missing"
        annotation_counts[status] += 1
        if status == "valid" and isinstance(annotation, dict):
            decisions = annotation.get("decisions")
            if isinstance(decisions, list):
                for decision in decisions:
                    if isinstance(decision, dict) and isinstance(decision.get("rules"), list):
                        for rule in decision["rules"]:
                            if isinstance(rule, str):
                                rule_counts[rule] += 1
    applicable_submissions = sum(annotation_counts[name] for name in ("valid", "missing", "invalid"))
    telemetry_declared = metadata.get("finish_telemetry_available") is True
    telemetry_available = telemetry_declared or any(
        isinstance(item.get("authored_finish_kind"), str)
        and isinstance(item.get("executed_finish_kind"), str)
        for item in boundaries
    )
    finish_counts = Counter()
    forced_finish_count = len(forced_boundary_indexes)
    delegated_units = set()
    protected_units = set()
    protected_recruiters = set()
    protected_critical = set()
    no_op_finishes = 0
    for boundary in boundaries:
        kind = boundary.get("authored_finish_kind")
        if isinstance(kind, str):
            finish_counts[kind] += 1
        if not boundary.get("delegated_unit_ids"):
            no_op_finishes += 1
        delegated_units.update(unit for unit in boundary.get("delegated_unit_ids", [])
                               if isinstance(unit, int))
        protected_units.update(unit for unit in boundary.get("protected_unit_ids", [])
                               if isinstance(unit, int))
        # The current client records one combined protected list. Do not guess
        # whether an ID was protected as a recruiter or for critical health.
        protected_recruiters.update(unit for unit in boundary.get("protected_recruiter_unit_ids", [])
                                    if isinstance(unit, int))
        protected_critical.update(unit for unit in boundary.get("protected_critical_unit_ids", [])
                                  if isinstance(unit, int))

    # New logs carry the authoritative side-turn total on game_end when the
    # driver reaches a side-turn limit. For older logs retain the state
    # observation fallback used by this report before finish telemetry existed.
    side_turns = set()
    driver_side_turns = [item.get("side_turns") for item in events
                         if item.get("type") == "game_end" and isinstance(item.get("side_turns"), int)]
    for item in events:
        if item.get("type") == "state":
            if isinstance(item.get("side_turns"), int):
                side_turns.add(item["side_turns"])
            elif isinstance(item.get("turn"), int):
                side_turns.add(item["turn"])

    attacks = Counter()
    deaths = Counter()
    factions: dict[int, Any] = {}
    moved = set()
    delegated_event_counts = Counter()
    delegated_kills = 0
    delegated_villages = 0
    generated_end_turns = 0
    generated_model_end_turns = 0
    generated_opponent_end_turns = 0
    for item in events:
        if item.get("type") == "state":
            for unit in item.get("units", []):
                if isinstance(unit, dict) and isinstance(unit.get("id"), int):
                    factions[unit["id"]] = unit.get("faction")
    for batch in accepted:
        for event in batch.get("events", []):
            if not isinstance(event, dict):
                continue
            kind = event.get("kind")
            source = event.get("source", "unknown")
            if kind == "end_turn":
                generated_end_turns += 1
                if source == "delegated_greedy":
                    generated_model_end_turns += 1
                elif source == "greedy":
                    generated_opponent_end_turns += 1
            if source == "delegated_greedy":
                delegated_event_counts[kind] += 1
                if kind in {"village", "capture_village", "village_capture"}:
                    delegated_villages += 1
                for participant_key in ("attacker", "defender"):
                    participant = event.get(participant_key)
                    if isinstance(participant, dict) and participant.get("killed"):
                        delegated_kills += 1
                unit_id = event.get("unit")
                if isinstance(unit_id, int):
                    delegated_units.add(unit_id)
                attacker = event.get("attacker")
                if isinstance(attacker, dict) and isinstance(attacker.get("unit"), int):
                    delegated_units.add(attacker["unit"])
            if kind == "attack":
                attacks[source] += 1
                for role in ("attacker", "defender"):
                    participant = event.get(role)
                    if isinstance(participant, dict) and participant.get("killed"):
                        unit_id = participant.get("unit")
                        deaths[str(factions.get(unit_id, "unknown"))] += 1
            if kind == "move":
                unit = event.get("unit")
                if isinstance(unit, int):
                    moved.add(unit)
            if kind in {"death", "unit_death"}:
                unit = event.get("unit") or event.get("dead") or {}
                faction = unit.get("faction") if isinstance(unit, dict) else event.get("faction", "unknown")
                deaths[str(faction)] += 1
    resolved_side_turns = None
    terminal_reason = terminal.get("reason") or terminal.get("termination_reason")
    if driver_side_turns:
        resolved_side_turns = driver_side_turns[-1]
    elif generated_end_turns:
        # A winner can terminate during an action before emitting EndTurn.
        resolved_side_turns = generated_end_turns + (1 if terminal_reason == "winner" else 0)
    if resolved_side_turns is not None:
        completed_side_turns = resolved_side_turns
    else:
        completed_side_turns = len(side_turns)
    model_turns = len(boundaries)
    engine_rounds = next((item.get("turns") for item in reversed(events)
                          if item.get("type") == "game_end"
                          and isinstance(item.get("turns"), int)), None)

    mismatch_reasons = []
    if driver_side_turns and generated_end_turns and driver_side_turns[-1] != generated_end_turns:
        mismatch_reasons.append("terminal_side_turns_vs_generated_end_turns")
    if (telemetry_available and boundaries
            and generated_model_end_turns < len(boundaries)
            and terminal_reason != "winner"):
        mismatch_reasons.append("accepted_boundaries_vs_generated_end_turns")
    failure = next((item for item in reversed(records) if item.get("type") == "model_error"), {})
    classified_class = terminal_class(terminal) or terminal_class(failure)
    if not classified_class and failure:
        classified_class = "model_invalid"
    if not classified_class:
        reason = terminal.get("reason")
        classified_class = "gameplay" if reason in {"winner", "loss", "max_turns", "turn_limit", "resignation"} else "unfinished_recoverable"
    report = {
        "terminal_class": classified_class,
        "winner": terminal.get("winner") if classified_class == "gameplay" else None,
        "reason": terminal.get("reason"),
        "stop_request_id": terminal.get("stop_request_id"),
        "stop_reason_code": terminal.get("stop_reason_code"),
        "stop_evidence_ids": terminal.get("evidence_ids"),
        "stop_observed_sequence": terminal.get("observed_sequence"),
        "final_proven_checkpoint": terminal.get("final_proven_checkpoint"),
        "action_boundary_status": terminal.get("action_boundary_status"),
        "cancellation_status": terminal.get("cancellation_status"),
        "remote_cancellation": terminal.get("remote_cancellation", "unknown")
        if classified_class == "observer_interrupted" else None,
        "resigned_side": terminal.get("resigned_side"),
        "completed_side_turns": completed_side_turns,
        "resolved_side_turns": resolved_side_turns,
        "model_turns": model_turns,
        "engine_rounds": engine_rounds,
        "accepted_event_batches": len(accepted),
        "attacks_by_source": dict(attacks),
        "deaths_by_faction": dict(deaths),
        "unique_movers": len(moved),
        "model_calls": terminal.get("model_calls", failure.get("model_calls")),
        "tool_calls": terminal.get("queries"),
        "handoff_reviews": len(handoff_reviews),
        "handoff_outcomes": dict(Counter(item.get("outcome", "unknown") for item in handoff_reviews)),
        "decision_annotations": {
            "submitted_batches": applicable_submissions,
            "valid_batches": annotation_counts["valid"],
            "missing_batches": annotation_counts["missing"],
            "invalid_batches": annotation_counts["invalid"],
            "coverage": (annotation_counts["valid"] / applicable_submissions
                         if applicable_submissions else None),
            "rule_counts": dict(rule_counts),
        },
        # A separate breakdown of local pre-publication validation attempts
        # (tools.publish_reply), alongside the final-annotation coverage
        # above. It does not redefine or replace decision_annotations
        # coverage, and repair effort is not folded into it as if free.
        "publication_attempts": aggregate_publication(publication_records),
    }
    if not telemetry_available:
        report.update({
            "finish_telemetry_available": False,
            "awareness_rate": None,
            "awareness_numerator": None,
            "awareness_denominator": None,
            "finish_counts": None,
        })
        return report

    explicit = finish_counts["explicit_done"] + finish_counts["selective"]
    implicit = finish_counts["implicit_end_turn"]
    # A partial-limit safety finish preserves a playable game, but it is not
    # evidence that the model recognized it had completed its important work.
    forced_explicit = sum(1 for index, boundary in enumerate(boundaries)
                          if index in forced_boundary_indexes
                          and boundary.get("authored_finish_kind") in {"explicit_done", "selective"})
    explicit -= forced_explicit
    # Keep raw implicit counts in the finish breakdown. Every resolved ending
    # remains in the awareness denominator; forced endings simply contribute no
    # numerator because they were injected by the safety path.
    denominator = len(boundaries)
    report.update({
        "finish_telemetry_available": True,
        "finish_counts": {
            "explicit_done": finish_counts["explicit_done"],
            "implicit_end_turn": implicit,
            "selective": finish_counts["selective"],
            "timeout": finish_counts["timeout"],
            "forced_partial_limit": forced_finish_count,
        },
        "explicit_done_turns": finish_counts["explicit_done"],
        "implicit_end_turn_turns": implicit,
        "selective_finish_turns": finish_counts["selective"],
        "timeout_finish_turns": finish_counts["timeout"],
        "forced_partial_limit_finishes": forced_finish_count,
        "awareness_numerator": explicit,
        "awareness_denominator": denominator,
        "awareness_rate": explicit / denominator if denominator else None,
        "delegated": {
            "units": len(delegated_units),
            "moves": delegated_event_counts["move"],
            "attacks": delegated_event_counts["attack"],
            "kills": delegated_kills,
            "villages": delegated_villages,
            "end_turns": delegated_event_counts["end_turn"],
        },
        "model_end_turns": generated_model_end_turns,
        "opponent_end_turns": generated_opponent_end_turns,
        "protected_units": len(protected_units),
        "protected_recruiters": len(protected_recruiters) if protected_recruiters else None,
        "protected_critical_units": len(protected_critical) if protected_critical else None,
        "no_op_finishes": no_op_finishes,
        "material_implicit_finishes": sum(
            1 for boundary in boundaries
            if boundary.get("authored_finish_kind") == "implicit_end_turn"
            and boundary.get("delegated_unit_ids")
        ),
        "accounting_mismatch": bool(mismatch_reasons),
        "accounting_mismatch_reasons": mismatch_reasons,
        "accepted_partial_batches": sum(
            1 for item in records
            if item.get("type") == "checkpoint_ref" and item.get("boundary") == "partial"
        ),
    })
    completed_model_turns = len(boundaries)
    report["model_calls_per_completed_model_turn"] = (
        terminal.get("model_calls") / completed_model_turns
        if completed_model_turns and isinstance(terminal.get("model_calls"), (int, float))
        else None
    )
    return report


def main(argv: list[str]) -> int:
    args = list(argv)
    publication_log = None
    if "--publication-log" in args:
        index = args.index("--publication-log")
        try:
            publication_log = args[index + 1]
        except IndexError:
            print("--publication-log requires a path", file=sys.stderr)
            return 2
        del args[index:index + 2]
    if not args:
        print("usage: match_report.py [--publication-log PATH] LOG [LOG ...]", file=sys.stderr)
        return 2
    publication_records = load_records(publication_log) if publication_log else None
    for name in args:
        print(json.dumps({"log": name, **classify(load_records(name), publication_records)},
                         sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
