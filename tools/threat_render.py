"""Readable-rendering helpers for engine threat/forecast facts.

These functions turn raw engine numbers (basis points, tenths of HP,
nullable lethal-volley bounds, per-attacker focus forecasts) into short
human-readable text without inventing facts: missing or ``None`` values are
rendered as ``unknown`` rather than silently becoming zero.

Extracted from ``tools/llm_client.py`` (Stack 2 of the proposed-movement
plan) so that ``tools/routine_policy.py`` can reuse them for causal contact
explanations without importing ``tools.llm_client`` (which would create a
circular import: ``llm_client`` imports ``routine_policy``).

Every function here calls only the others in this module and uses no module
globals; they are pure functions of their arguments.
"""
from __future__ import annotations

from typing import Any


def _readable_probability(value: Any) -> str:
    """Render engine basis points as an exact percentage without changing payloads."""
    if not isinstance(value, int) or isinstance(value, bool):
        return "unknown"
    return f"{value / 100:.2f}".rstrip("0").rstrip(".") + "%"


def _readable_hp_tenths(value: Any) -> str:
    """Render engine tenths of HP as HP; absent values remain unknown."""
    if not isinstance(value, int) or isinstance(value, bool):
        return "unknown"
    return f"{value / 10:.1f}".rstrip("0").rstrip(".") + "HP"


def _readable_whole_hp(value: Any) -> str:
    if not isinstance(value, int) or isinstance(value, bool):
        return "unknown"
    return f"{value}HP"


def _readable_probability_list(values: Any, labels: tuple[str, ...]) -> str:
    if not isinstance(values, (list, tuple)):
        return "unknown"
    return ",".join(
        f"{label}={_readable_probability(values[index]) if index < len(values) else 'unknown'}"
        for index, label in enumerate(labels)
    )


def _readable_exchange(forecast: Any) -> str:
    """Render an exchange forecast with damage roles made explicit."""
    if not isinstance(forecast, dict):
        return "exchange=unknown"
    outcomes = _readable_probability_list(
        forecast.get("outcome_bps"),
        ("defender_killed", "both_survive", "attacker_killed"),
    )
    damage = forecast.get("expected_damage_tenths")
    if isinstance(damage, (list, tuple)):
        damage_text = ",".join(
            f"{label}={_readable_hp_tenths(damage[index]) if index < len(damage) else 'unknown'}"
            for index, label in enumerate(("to_defender", "attacker_retaliation"))
        )
    else:
        damage_text = "to_defender=unknown,attacker_retaliation=unknown"
    return f"exchange=({outcomes}; expected_damage=({damage_text}))"


def _readable_focus(values: Any, *, damage: bool = False) -> str:
    """Render one-, two-, and three-attacker focus facts with named outcomes."""
    if not isinstance(values, (list, tuple)):
        return "unknown"
    labels = (("damage_from_1", "damage_from_2", "damage_from_3")
              if damage else ("kill_by_1", "kill_by_2", "kill_by_3"))
    renderer = _readable_hp_tenths if damage else _readable_probability
    return ",".join(
        f"{label}={renderer(values[index]) if index < len(values) else 'unknown'}"
        for index, label in enumerate(labels)
    )


def _readable_kill(value: Any) -> str:
    """Render aggregate kill probability or the three focus probabilities."""
    return (_readable_focus(value) if isinstance(value, (list, tuple))
            else _readable_probability(value))


def _readable_damage(value: Any) -> str:
    """Render aggregate expected damage or the three focus damage values."""
    return (_readable_focus(value, damage=True) if isinstance(value, (list, tuple))
            else _readable_hp_tenths(value))


def _readable_threat_count(item: dict[str, Any], key: str) -> str:
    """Render an evaluated count without turning missing data into zero."""
    value = item.get(key) if key in item else None
    return "unknown" if key not in item or value is None else str(value)


def _readable_lethal_attackers(item: dict[str, Any], key: str = "lethal_attackers_needed") -> str:
    """Explain the nullable lethal-volley bound while preserving its meaning.

    The tactics engine uses ``None`` for an evaluated scope where the supplied
    maximum volleys cannot reach the target HP.  An absent field means that no
    evaluated result was supplied, which is a different fact.
    """
    if key not in item:
        return "unknown"
    value = item[key]
    if value is None:
        return "null (unreachable under supplied maximum volleys)"
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return "unknown"
