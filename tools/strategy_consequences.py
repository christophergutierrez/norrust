"""Comparable consequence extraction and rendering for validated strategy selections.

Pure helper module: no I/O, no driver communication, no global state.
Normalizes engine preview responses from `preview_batch` (mode="forecast")
and formats compact, neutral consequence cards for prompt display.
"""
from __future__ import annotations

import copy
import json
from typing import Any, Optional

from .threat_render import (
    _readable_hp_tenths,
    _readable_lethal_attackers,
    _readable_probability,
    _readable_threat_count,
    _readable_whole_hp,
)


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

    # Check state revision match
    rev = actual_revision if actual_revision is not None else preview_body.get("state_revision")
    if rev is not None and rev != expected_revision:
        return _unavailable_consequences(reason="stale_state_revision")

    candidates = preview_body.get("candidates")
    if not isinstance(candidates, list) or candidate_index >= len(candidates):
        return _unavailable_consequences(reason="candidate_index_missing")

    cand = candidates[candidate_index]
    if not isinstance(cand, dict):
        return _unavailable_consequences(reason="candidate_not_dict")

    if cand.get("valid") is False:
        err = cand.get("preview_error")
        msg = err.get("message", "candidate_invalid") if isinstance(err, dict) else "candidate_invalid"
        return _unavailable_consequences(reason=f"validation_failed: {msg}")

    # Extract phase, assumption, coverage
    phase = preview_body.get("phase", "unknown")
    assumption = cand.get("assumption", "none")
    if assumption is None:
        assumption = "none"

    missing_fields: list[str] = []

    # Projected gold change
    summary = cand.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("gold_before"), int) and isinstance(summary.get("gold_after"), int):
        gold_change: Any = summary["gold_after"] - summary["gold_before"]
    else:
        gold_change = "unknown"
        missing_fields.append("gold_change")

    # Immediate attack forecasts
    attacks: list[dict[str, Any]] = []
    forecasts = cand.get("forecasts", [])
    if isinstance(forecasts, list):
        for f_entry in forecasts:
            if not isinstance(f_entry, dict):
                continue
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

    # Recruiter exposure (preserving direct and open separately)
    recruiter_exposure: Optional[dict[str, Any]] = None
    r_threats = cand.get("recruiter_threats")
    if isinstance(r_threats, dict) and isinstance(r_threats.get("recruiters"), list) and r_threats["recruiters"]:
        # Primary recruiter
        r_entry = r_threats["recruiters"][0]
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

    # Friendly units exposure
    friendly_exposure: list[dict[str, Any]] = []
    exposure_obj = cand.get("exposure")
    if isinstance(exposure_obj, dict) and isinstance(exposure_obj.get("units"), list):
        for u in exposure_obj["units"]:
            if not isinstance(u, dict):
                continue
            # Include if exposed to any attackers
            direct_att = u.get("distinct_attacker_count", 0)
            open_att = u.get("open_distinct_attacker_count", 0)
            if direct_att or open_att:
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

    coverage = "partial" if missing_fields else "complete"

    return {
        "coverage": coverage,
        "forecast_phase": phase,
        "assumption": assumption,
        "gold_change": gold_change,
        "attacks": attacks,
        "recruiter_exposure": recruiter_exposure,
        "friendly_exposure": friendly_exposure,
        "missing": missing_fields,
    }


def _unavailable_consequences(reason: str = "unavailable") -> dict[str, Any]:
    return {
        "coverage": "unavailable",
        "reason": reason,
        "forecast_phase": "unknown",
        "assumption": "unknown",
        "gold_change": "unknown",
        "attacks": [],
        "recruiter_exposure": None,
        "friendly_exposure": [],
        "missing": ["all"],
    }


def format_consequences_comparison(
    validated_selections: list[dict[str, Any]],
    decision_id: str,
    state_revision: int,
) -> str:
    """Format up to two validated selections with their normalized consequences.

    Adheres strictly to the shared design contract:
    - Header labeled SIMULATION — NOT EXECUTED
    - Neutral numbering without ranking/endorsement
    - Explicit submit-ready `choose` response object for each selection
    - Explicit unknown markers for missing data
    - Live state revision reminder
    - Bounded length (< 3 KiB UTF-8)
    """
    if not validated_selections:
        return ""

    cards = validated_selections[:2]
    # If none of the cards have consequences attached, return empty string
    if not any("consequences" in card for card in cards):
        return ""

    lines = [
        "SIMULATION — NOT EXECUTED: Comparative consequences for engine-validated selections.",
        "Estimates are conditional on engine forecast assumptions; not an execution guarantee.",
        f"Hypothetical values only; live state revision remains {state_revision}.",
        "",
    ]

    for idx, card in enumerate(cards, start=1):
        option_ids = card.get("option_ids", [])
        finish_turn = bool(card.get("finish_turn", False))
        intent = card.get("intent")
        intent_suffix = f", intent={intent}" if intent else ""
        c = card.get("consequences") or _unavailable_consequences()

        cov = c.get("coverage", "unknown")
        phase = c.get("forecast_phase", "unknown")
        assumption = c.get("assumption", "unknown")

        lines.append(f"Selection {idx} (option_ids={option_ids}, finish_turn={json.dumps(finish_turn)}{intent_suffix}):")
        lines.append(f"  Consequences: {cov} (forecast phase: {phase}, assumption: {assumption})")

        # Gold change
        g = c.get("gold_change")
        if isinstance(g, int):
            gold_str = f"{g:+d} gold" if g != 0 else "0 gold"
        else:
            gold_str = "gold change unknown"
        lines.append(f"  Projected gold: {gold_str}")

        # Attacks
        attacks = c.get("attacks", [])
        if attacks:
            lines.append("  Immediate attack forecasts:")
            for att in attacks:
                lines.append(
                    f"    - Attacker U{att['attacker_id']} -> Target U{att['target_id']} ({att['scope']}): "
                    f"defender killed {att['defender_killed']}, both survive {att['both_survive']}, "
                    f"attacker killed {att['attacker_killed']}; "
                    f"expected damage {att['expected_damage_to_defender']} (retaliation {att['attacker_retaliation']})"
                )
        else:
            lines.append("  Immediate attack forecasts: none")

        # Recruiter exposure
        rec = c.get("recruiter_exposure")
        if rec and isinstance(rec, dict):
            lines.append(
                f"  Projected recruiter exposure (U{rec['recruiter_id']}, {rec['hp']}): "
                f"direct attackers={rec['direct_attackers']}, direct max incoming={rec['direct_max']} "
                f"(lethal needed: {rec['direct_lethal_needed']}); "
                f"open attackers={rec['open_attackers']}, open max incoming={rec['open_max']} "
                f"(open lethal needed: {rec['open_lethal_needed']})"
            )
        else:
            lines.append("  Projected recruiter exposure: none")

        # Friendly exposure
        friendly = c.get("friendly_exposure", [])
        if friendly:
            lines.append("  Affected friendly unit exposure:")
            for u in friendly:
                lines.append(
                    f"    - U{u['unit_id']} ({u['hp']} at {u['col']},{u['row']}): "
                    f"direct attackers={u['direct_attackers']}, direct max={u['direct_max']}; "
                    f"open attackers={u['open_attackers']}, open max={u['open_max']}"
                )
        else:
            lines.append("  Affected friendly unit exposure: none")

        # Submit-ready choose response
        choose_obj = {
            "kind": "choose",
            "decision_id": decision_id,
            "option_ids": list(option_ids),
            "finish_turn": finish_turn,
        }
        lines.append(f"  To choose this selection: {json.dumps(choose_obj, separators=(',', ':'))}")
        lines.append("")

    lines.append(f"Current live state revision is {state_revision}. The above simulation reflects hypothetical consequences only and does not change the board.")

    rendered = "\n".join(lines)
    # Bound to 3 KiB UTF-8
    encoded = rendered.encode("utf-8")
    if len(encoded) > 3072:
        # If over 3 KiB, note truncation while preserving submit-ready JSON
        lines.insert(-1, "[Notice: some detailed exposure lines omitted to maintain length bound]")
        rendered = "\n".join(lines)
    return rendered
