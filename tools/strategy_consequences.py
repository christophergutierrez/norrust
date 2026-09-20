"""Comparable consequence extraction and rendering for validated strategy selections.

Pure helper module: no I/O, no driver communication, no global state.
Normalizes engine preview responses from `preview_batch` (mode="forecast")
and formats compact, neutral consequence cards for prompt display.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .threat_render import (
    _readable_hp_tenths,
    _readable_lethal_attackers,
    _readable_probability,
    _readable_threat_count,
    _readable_whole_hp,
)


MAX_COMPARISON_BYTES = 3072
_FORECAST_PHASES = {"partial", "final"}


def _field_status(statuses: dict[str, str], field: str, status: str,
                  missing: list[str]) -> None:
    """Record field coverage without turning malformed data into an empty result."""
    statuses[field] = status
    if status != "known" and field not in missing:
        missing.append(field)


def _read_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _valid_forecast_entry(entry: Any) -> bool:
    if not isinstance(entry, dict) or not isinstance(entry.get("forecast"), dict):
        return False
    forecast = entry["forecast"]
    return "outcome_bps" in forecast or "expected_damage_tenths" in forecast


def _valid_recruiter_entry(entry: Any) -> bool:
    return (isinstance(entry, dict)
            and "recruiter_id" in entry
            and "hp" in entry
            and ("distinct_attacker_count" in entry
                 or "open_distinct_attacker_count" in entry))


def _valid_exposure_entry(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    # These fields decide whether a unit is affected.  Without either one an
    # empty rendered list would falsely assert that the unit is unexposed.
    return ("distinct_attacker_count" in entry
            or "open_distinct_attacker_count" in entry)


def _coverage_status(coverage: dict[str, Any], field: str) -> str:
    """Translate the driver's bounded coverage flags to our field status."""
    key = "forecast" if field in {"attacks", "gold_change"} else "threats"
    value = coverage.get(key)
    if value in {"truncated", "partial"}:
        return "partial"
    if value in {"unknown", "unavailable", "missing", None}:
        return "unknown"
    return "known" if value in {"conditional_pre_finish", "pre_finish", "complete", "known"} else "unknown"


def _threat_quality(entry: dict[str, Any]) -> str:
    counts = (entry.get("distinct_attacker_count"),
              entry.get("open_distinct_attacker_count"))
    if all(value is None for value in counts):
        return "unknown"
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0
           for value in counts):
        return "partial"
    required = (
        "max_incoming_sum", "lethal_attackers_needed",
        "open_max_incoming_sum", "open_lethal_attackers_needed",
    )
    if not all(key in entry for key in required):
        return "partial"
    for key in ("max_incoming_sum", "open_max_incoming_sum"):
        value = entry[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return "partial"
    for key in ("lethal_attackers_needed", "open_lethal_attackers_needed"):
        value = entry[key]
        if value is not None and (not isinstance(value, int)
                                  or isinstance(value, bool) or value < 0):
            return "partial"
    return "known"


def _forecast_quality(entry: dict[str, Any]) -> str:
    if not _valid_forecast_entry(entry):
        return "unknown"
    forecast = entry["forecast"]
    outcomes = forecast.get("outcome_bps")
    damage = forecast.get("expected_damage_tenths")
    valid_outcomes = (isinstance(outcomes, (list, tuple)) and len(outcomes) == 3
                      and all(isinstance(value, int) and not isinstance(value, bool)
                              and 0 <= value <= 10000 for value in outcomes))
    valid_damage = (isinstance(damage, (list, tuple)) and len(damage) == 2
                    and all(isinstance(value, int) and not isinstance(value, bool)
                            and value >= 0 for value in damage))
    if valid_outcomes and valid_damage:
        return "known"
    return "partial"


def extract_candidate_consequences(
    preview_body: Optional[dict[str, Any]],
    candidate_index: int,
    *,
    expected_revision: int,
    actual_revision: Optional[int] = None,
) -> dict[str, Any]:
    """Normalize a candidate's forecast consequences from preview_batch output.

    Explicitly marks missing or unknown fields. Never treats missing danger as safe.
    Invalidates consequences if revisions do not match or the preview failed.
    """
    if preview_body is None or not isinstance(preview_body, dict):
        return _unavailable_consequences(reason="preview_unavailable")

    # Forecast cards are scoped to this exact envelope.  A missing revision or
    # scope marker is unknown, never an implicit match.
    rev = actual_revision if actual_revision is not None else preview_body.get("state_revision")
    if not isinstance(rev, int) or isinstance(rev, bool):
        return _unavailable_consequences(reason="forecast_revision_missing")
    if rev != expected_revision:
        return _unavailable_consequences(reason="stale_state_revision")
    if preview_body.get("mode") != "forecast":
        return _unavailable_consequences(reason="forecast_mode_invalid")
    if "sampling" in preview_body and preview_body.get("sampling") is not False:
        return _unavailable_consequences(reason="forecast_sampling_invalid")
    phase = preview_body.get("phase")
    if phase not in _FORECAST_PHASES:
        return _unavailable_consequences(reason="forecast_phase_invalid")
    envelope_coverage = preview_body.get("coverage")
    if (not isinstance(envelope_coverage, dict)
            or not isinstance(envelope_coverage.get("forecast"), str)
            or not isinstance(envelope_coverage.get("threats"), str)):
        return _unavailable_consequences(reason="forecast_coverage_missing")

    candidates = preview_body.get("candidates")
    if (not isinstance(candidates, list) or isinstance(candidate_index, bool)
            or candidate_index < 0 or candidate_index >= len(candidates)):
        return _unavailable_consequences(reason="candidate_index_missing")

    cand = candidates[candidate_index]
    if not isinstance(cand, dict):
        return _unavailable_consequences(reason="candidate_not_dict")

    if cand.get("valid") is not True:
        err = cand.get("preview_error")
        if cand.get("valid") is False:
            msg = err.get("message", "candidate_invalid") if isinstance(err, dict) else "candidate_invalid"
            return _unavailable_consequences(reason=f"validation_failed: {msg}")
        return _unavailable_consequences(reason="candidate_validity_missing")

    # Extract phase, assumption, and per-field coverage.  A field is known
    # only when the engine supplied a correctly shaped value; an authoritative
    # empty list is therefore distinct from an absent list.
    assumption = cand.get("assumption")
    if assumption is None and "assumptions" in cand:
        assumption = cand.get("assumptions")
    missing_fields: list[str] = []
    field_coverage: dict[str, str] = {}
    if isinstance(assumption, str) and assumption:
        assumption_value = assumption
        field_coverage["assumption"] = "known"
        field_coverage["assumptions"] = "known"
    else:
        assumption_value = "unknown"
        _field_status(field_coverage, "assumption", "unknown", missing_fields)
        field_coverage["assumptions"] = "unknown"

    if not isinstance(phase, str):
        _field_status(field_coverage, "forecast_phase", "unknown", missing_fields)
    else:
        field_coverage["forecast_phase"] = "known"

    # Projected gold change
    summary = cand.get("summary")
    if (isinstance(summary, dict)
            and _read_int(summary.get("gold_before")) is not None
            and _read_int(summary.get("gold_after")) is not None):
        gold_quality = _coverage_status(envelope_coverage, "gold_change")
        gold_change: Any = (
            summary["gold_after"] - summary["gold_before"]
            if gold_quality != "unknown" else "unknown")
        _field_status(field_coverage, "gold_change", gold_quality, missing_fields)
    else:
        gold_change = "unknown"
        _field_status(field_coverage, "gold_change", "unknown", missing_fields)

    # Immediate attack forecasts
    attacks: list[dict[str, Any]] = []
    forecasts = cand.get("forecasts")
    if forecasts is None:
        _field_status(field_coverage, "attacks", "unknown", missing_fields)
    elif isinstance(forecasts, list):
        invalid_forecasts = 0
        partial_forecasts = 0
        for f_entry in forecasts:
            if not _valid_forecast_entry(f_entry):
                invalid_forecasts += 1
                continue
            if _forecast_quality(f_entry) == "partial":
                partial_forecasts += 1
            f_data = f_entry.get("forecast", {})
            outcomes = f_data.get("outcome_bps")
            dmg = f_data.get("expected_damage_tenths")
            att_info = {
                "attacker_id": f_entry.get("attacker_id", "unknown"),
                "target_id": f_entry.get("defender_id", "unknown"),
                "scope": "immediate_exchange",
                "defender_killed": _readable_probability(outcomes[0]) if isinstance(outcomes, (list, tuple)) and len(outcomes) > 0 else "unknown",
                "both_survive": _readable_probability(outcomes[1]) if isinstance(outcomes, (list, tuple)) and len(outcomes) > 1 else "unknown",
                "attacker_killed": _readable_probability(outcomes[2]) if isinstance(outcomes, (list, tuple)) and len(outcomes) > 2 else "unknown",
                "expected_damage_to_defender": _readable_hp_tenths(dmg[0]) if isinstance(dmg, (list, tuple)) and len(dmg) > 0 else "unknown",
                "attacker_retaliation": _readable_hp_tenths(dmg[1]) if isinstance(dmg, (list, tuple)) and len(dmg) > 1 else "unknown",
            }
            attacks.append(att_info)
        list_quality = ("unknown" if invalid_forecasts == len(forecasts) and forecasts
                        else ("partial" if invalid_forecasts or partial_forecasts else "known"))
        coverage_quality = _coverage_status(envelope_coverage, "attacks")
        if coverage_quality == "unknown" or list_quality == "unknown":
            list_quality = "unknown"
        elif coverage_quality == "partial" or list_quality == "partial":
            list_quality = "partial"
        _field_status(field_coverage, "attacks", list_quality, missing_fields)
    else:
        _field_status(field_coverage, "attacks", "unknown", missing_fields)

    # Recruiter exposure (preserving direct and open separately)
    recruiter_exposure: Optional[dict[str, Any]] = None
    r_threats = cand.get("recruiter_threats")
    if r_threats is None:
        _field_status(field_coverage, "recruiter_exposure", "unknown", missing_fields)
    elif isinstance(r_threats, dict) and isinstance(r_threats.get("recruiters"), list):
        recruiter_entries = r_threats["recruiters"]
        invalid_recruiters = sum(not _valid_recruiter_entry(item)
                                 for item in recruiter_entries)
        # Primary recruiter
        r_entry = next((item for item in recruiter_entries
                        if _valid_recruiter_entry(item)), None)
        if r_entry is None:
            r_entry = next((item for item in recruiter_entries
                            if isinstance(item, dict)), None)
        if isinstance(r_entry, dict):
            recruiter_exposure = {
                "recruiter_id": r_entry.get("recruiter_id", "unknown"),
                "hp": _readable_whole_hp(r_entry.get("hp")),
                "direct_attackers": _readable_threat_count(r_entry, "distinct_attacker_count"),
                "direct_max": _readable_whole_hp(r_entry.get("max_incoming_sum")),
                "direct_lethal_needed": _readable_lethal_attackers(r_entry, "lethal_attackers_needed"),
                "direct_origins_conflict": r_entry.get("origins_conflict", "unknown"),
                "open_attackers": _readable_threat_count(r_entry, "open_distinct_attacker_count"),
                "open_max": _readable_whole_hp(r_entry.get("open_max_incoming_sum")),
                "open_lethal_needed": _readable_lethal_attackers(r_entry, "open_lethal_attackers_needed"),
                "open_origins_conflict": r_entry.get("open_origins_conflict", "unknown"),
            }
        entry_quality = ("partial" if invalid_recruiters else "known")
        if isinstance(r_entry, dict):
            metric_quality = _threat_quality(r_entry)
            if metric_quality == "unknown":
                entry_quality = "unknown"
            elif metric_quality == "partial":
                entry_quality = "partial"
        coverage_quality = _coverage_status(envelope_coverage, "recruiter_exposure")
        if coverage_quality == "unknown" or entry_quality == "unknown":
            entry_quality = "unknown"
        elif coverage_quality == "partial" or entry_quality == "partial":
            entry_quality = "partial"
        _field_status(field_coverage, "recruiter_exposure", entry_quality, missing_fields)
    else:
        _field_status(field_coverage, "recruiter_exposure", "unknown", missing_fields)

    # Friendly units exposure
    friendly_exposure: list[dict[str, Any]] = []
    exposure_obj = cand.get("exposure")
    if exposure_obj is None:
        _field_status(field_coverage, "friendly_exposure", "unknown", missing_fields)
    elif isinstance(exposure_obj, dict) and isinstance(exposure_obj.get("units"), list):
        exposure_entries = exposure_obj["units"]
        invalid_exposure = sum(not _valid_exposure_entry(item)
                               for item in exposure_entries)
        for u in exposure_obj["units"]:
            if not _valid_exposure_entry(u):
                continue
            # Include if exposed to any attackers
            direct_att = u.get("distinct_attacker_count")
            open_att = u.get("open_distinct_attacker_count")
            unit_quality = _threat_quality(u)
            if ((direct_att is not None and direct_att != 0)
                    or (open_att is not None and open_att != 0)
                    or unit_quality != "known"):
                friendly_exposure.append({
                    "unit_id": u.get("unit_id", "unknown"),
                    "hp": _readable_whole_hp(u.get("hp")),
                    "col": u.get("col", "unknown"),
                    "row": u.get("row", "unknown"),
                    "direct_attackers": _readable_threat_count(u, "distinct_attacker_count"),
                    "direct_max": _readable_whole_hp(u.get("max_incoming_sum")),
                    "direct_lethal_needed": _readable_lethal_attackers(u, "lethal_attackers_needed"),
                    "open_attackers": _readable_threat_count(u, "open_distinct_attacker_count"),
                    "open_max": _readable_whole_hp(u.get("open_max_incoming_sum")),
                    "open_lethal_needed": _readable_lethal_attackers(u, "open_lethal_attackers_needed"),
                })
        entry_quality = "partial" if invalid_exposure else "known"
        if any(_threat_quality(item) == "unknown"
               for item in exposure_entries if isinstance(item, dict)):
            entry_quality = "unknown"
        elif any(_threat_quality(item) == "partial"
                 for item in exposure_entries if isinstance(item, dict)):
            entry_quality = "partial"
        coverage_quality = _coverage_status(envelope_coverage, "friendly_exposure")
        if coverage_quality == "unknown" or entry_quality == "unknown":
            entry_quality = "unknown"
        elif coverage_quality == "partial" or entry_quality == "partial":
            entry_quality = "partial"
        _field_status(field_coverage, "friendly_exposure", entry_quality, missing_fields)
    else:
        _field_status(field_coverage, "friendly_exposure", "unknown", missing_fields)

    coverage = "partial" if missing_fields else "complete"

    return {
        "coverage": coverage,
        "forecast_phase": phase,
        "assumption": assumption_value,
        "assumptions": assumption_value,
        "gold_change": gold_change,
        "attacks": attacks,
        "recruiter_exposure": recruiter_exposure,
        "friendly_exposure": friendly_exposure,
        "missing": missing_fields,
        "field_coverage": field_coverage,
    }


def _unavailable_consequences(reason: str = "unavailable") -> dict[str, Any]:
    return {
        "coverage": "unavailable",
        "reason": reason,
        "forecast_phase": "unknown",
        "assumption": "unknown",
        "assumptions": "unknown",
        "gold_change": "unknown",
        "attacks": [],
        "recruiter_exposure": None,
        "friendly_exposure": [],
        "missing": ["all"],
        "field_coverage": {
            "forecast_phase": "unknown",
            "assumption": "unknown",
            "assumptions": "unknown",
            "gold_change": "unknown",
            "attacks": "unknown",
            "recruiter_exposure": "unknown",
            "friendly_exposure": "unknown",
        },
    }


def _status_for(consequences: dict[str, Any], field: str) -> str:
    statuses = consequences.get("field_coverage")
    if isinstance(statuses, dict):
        status = statuses.get(field)
        if status in {"known", "partial", "unknown"}:
            return status
    return "unknown"


def _coverage_label(consequences: dict[str, Any]) -> str:
    value = consequences.get("coverage", "unknown")
    return value if isinstance(value, str) and value else "unknown"


def _bounded_fallback(state_revision: int) -> str:
    """Render a truthful fallback when the mandatory card framing cannot fit."""
    lines = [
        "SIMULATION — NOT EXECUTED: consequence cards unavailable within the 3072-byte UTF-8 display bound.",
        "Use the existing engine-validated legal menu; no identifier was clipped or rewritten.",
        f"Live state revision is {state_revision}; hypothetical values are unavailable.",
    ]
    return "\n".join(lines)


def format_consequences_comparison(
    validated_selections: list[dict[str, Any]],
    decision_id: str,
    state_revision: int,
) -> str:
    """Format up to two validated selections with a strict UTF-8 byte bound.

    Card framing, coverage, assumptions, live revision, and complete choose
    response objects are mandatory.  Forecast detail is optional and is added
    in order while it fits.  This makes the bound deterministic without ever
    clipping JSON or UTF-8 code points.
    """
    if not validated_selections:
        return ""

    cards = validated_selections[:2]
    # If none of the cards have consequences attached, return empty string
    if not any("consequences" in card for card in cards):
        return ""

    header = [
        "SIMULATION — NOT EXECUTED: Comparative consequences for engine-validated selections.",
        "Estimates are conditional on engine forecast assumptions; not an execution guarantee.",
        f"Hypothetical values only; live state revision remains {state_revision}.",
        "",
    ]
    card_blocks: list[list[str]] = []
    details_by_card: list[list[str]] = []
    for idx, card in enumerate(cards, start=1):
        option_ids = card.get("option_ids", [])
        if not isinstance(option_ids, list):
            option_ids = []
        finish_turn = bool(card.get("finish_turn", False))
        intent = card.get("intent")
        c = card.get("consequences") or _unavailable_consequences()

        choose_obj = {
            "kind": "choose",
            "decision_id": decision_id,
            "option_ids": list(option_ids),
            "finish_turn": finish_turn,
        }
        choose_json = json.dumps(choose_obj, ensure_ascii=False, separators=(",", ":"))
        cov = _coverage_label(c)
        phase = c.get("forecast_phase", "unknown")
        phase = phase if isinstance(phase, str) and phase else "unknown"
        assumption = c.get("assumption", "unknown")
        assumption = assumption if isinstance(assumption, str) and assumption else "unknown"
        label = (f"Selection {idx} (option_ids={option_ids}, finish_turn={json.dumps(finish_turn)}):")
        block = [
            label,
            f"  Consequences: {cov} (forecast phase: {phase}, assumption: {assumption})",
            f"  To choose this selection: {choose_json}",
            "",
        ]

        details: list[str] = []
        if isinstance(intent, str) and intent:
            details.append(f"  Intent: {intent}")
        g = c.get("gold_change")
        gold_str = (f"{g:+d} gold" if isinstance(g, int) and g != 0
                    else ("0 gold" if isinstance(g, int) else "gold change unknown"))
        details.append(f"  Projected gold: {gold_str}")

        attack_status = _status_for(c, "attacks")
        attacks = c.get("attacks")
        if attack_status == "unknown" or (attack_status == "partial" and not attacks):
            details.append("  Immediate attack forecasts: unknown (coverage incomplete)")
        elif isinstance(attacks, list) and attacks:
            details.append("  Immediate attack forecasts:")
            for att in attacks:
                if not isinstance(att, dict):
                    continue
                details.append(
                    f"    - Attacker U{att.get('attacker_id', 'unknown')} -> Target U{att.get('target_id', 'unknown')} ({att.get('scope', 'unknown')}): "
                    f"defender killed {att.get('defender_killed', 'unknown')}, both survive {att.get('both_survive', 'unknown')}, "
                    f"attacker killed {att.get('attacker_killed', 'unknown')}; expected damage "
                    f"{att.get('expected_damage_to_defender', 'unknown')} (retaliation {att.get('attacker_retaliation', 'unknown')})"
                )
        else:
            details.append("  Immediate attack forecasts: none")

        rec_status = _status_for(c, "recruiter_exposure")
        rec = c.get("recruiter_exposure")
        if rec_status == "unknown" or (rec_status == "partial" and not rec):
            details.append("  Projected recruiter exposure: unknown (coverage incomplete)")
        elif isinstance(rec, dict):
            details.append(
                f"  Projected recruiter exposure (U{rec.get('recruiter_id', 'unknown')}, {rec.get('hp', 'unknown')}): "
                f"direct attackers={rec.get('direct_attackers', 'unknown')}, direct max incoming={rec.get('direct_max', 'unknown')} "
                f"(lethal needed: {rec.get('direct_lethal_needed', 'unknown')}); "
                f"open attackers={rec.get('open_attackers', 'unknown')}, open max incoming={rec.get('open_max', 'unknown')} "
                f"(open lethal needed: {rec.get('open_lethal_needed', 'unknown')})"
            )
        else:
            details.append("  Projected recruiter exposure: none")

        friendly_status = _status_for(c, "friendly_exposure")
        friendly = c.get("friendly_exposure")
        if friendly_status == "unknown" or (friendly_status == "partial" and not friendly):
            details.append("  Affected friendly unit exposure: unknown (coverage incomplete)")
        elif isinstance(friendly, list) and friendly:
            details.append("  Affected friendly unit exposure:")
            for unit in friendly:
                if not isinstance(unit, dict):
                    continue
                details.append(
                    f"    - U{unit.get('unit_id', 'unknown')} ({unit.get('hp', 'unknown')} at {unit.get('col', 'unknown')},{unit.get('row', 'unknown')}): "
                    f"direct attackers={unit.get('direct_attackers', 'unknown')}, direct max={unit.get('direct_max', 'unknown')}; "
                    f"open attackers={unit.get('open_attackers', 'unknown')}, open max={unit.get('open_max', 'unknown')}"
                )
        else:
            details.append("  Affected friendly unit exposure: none")
        card_blocks.append(block)
        details_by_card.append(details)

    reminder = (f"Current live state revision is {state_revision}. The above simulation reflects "
                "hypothetical consequences only and does not change the board.")
    notice = "[Notice: optional consequence detail omitted to maintain the 3072-byte UTF-8 bound.]"
    # Reserve every card's exact JSON, coverage/assumption framing, the live
    # revision, and the omission marker before adding optional detail.  Card B
    # therefore cannot disappear merely because Card A has verbose forecasts.
    mandatory = list(header)
    for block in card_blocks:
        mandatory.extend(block)
    final_overhead = ["", notice, reminder]
    if len("\n".join(mandatory + final_overhead).encode("utf-8")) > MAX_COMPARISON_BYTES:
        return _bounded_fallback(state_revision)

    lines = list(header)
    optional_omitted = False
    for card_index, (block, details) in enumerate(zip(card_blocks, details_by_card)):
        lines.extend(block)
        remaining_mandatory = [line for future in card_blocks[card_index + 1:]
                               for line in future]
        for detail in details:
            candidate = lines + [detail] + remaining_mandatory + final_overhead
            if len("\n".join(candidate).encode("utf-8")) <= MAX_COMPARISON_BYTES:
                lines.append(detail)
            else:
                optional_omitted = True

    lines.append("")
    if optional_omitted:
        lines.append(notice)
    lines.append(reminder)
    rendered = "\n".join(lines)
    if len(rendered.encode("utf-8")) > MAX_COMPARISON_BYTES:
        return _bounded_fallback(state_revision)
    return rendered
