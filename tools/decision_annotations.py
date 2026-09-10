"""Validation and bookkeeping for model supplied decision annotations."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .response_parsing import parse_action_response

GUIDE_VERSION = "tactics-v1"
RULE_IDS = frozenset({"S1", "S2", "T0", "T1", "T2", "T3", "T3.1", "T3.2", "T3.3", "T4", "T5", "T6", "T7", "T8"})
MAX_GROUPS = 16
MAX_REFERENCES = 256
MAX_TEXT_BYTES = 240


def guide_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def inapplicable_annotation(guide_text: str) -> dict[str, Any]:
    return {"status": "not_applicable", "guide_version": GUIDE_VERSION,
            "guide_hash": guide_hash(guide_text), "decisions": [], "error": None}


def _bounded_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"{name} must be a nonempty string of at most 240 UTF-8 bytes")
    return value


def validate_decisions(decisions: Any, action_count: int) -> list[dict[str, Any]]:
    if not isinstance(decisions, list) or len(decisions) > MAX_GROUPS:
        raise ValueError("decisions must contain at most 16 groups")
    covered: set[int] = set()
    total = 0
    result: list[dict[str, Any]] = []
    for group_index, group in enumerate(decisions):
        if not isinstance(group, dict) or set(group) != {"orders", "rules", "expected", "risk"}:
            raise ValueError(f"decision group {group_index} has unknown or missing keys")
        orders = group["orders"]
        if not isinstance(orders, list):
            raise ValueError(f"decision group {group_index} orders must be an array")
        if any(not isinstance(index, int) or isinstance(index, bool) for index in orders):
            raise ValueError(f"decision group {group_index} orders must be integer indices")
        if any(index < 0 or index >= action_count for index in orders):
            raise ValueError(f"decision group {group_index} contains an invalid order index")
        if len(set(orders)) != len(orders):
            raise ValueError("decision order coverage contains duplicates")
        if covered.intersection(orders):
            raise ValueError("decision order coverage contains duplicates")
        rules = group["rules"]
        if (not isinstance(rules, list) or any(not isinstance(rule, str) for rule in rules)
                or not 1 <= len(rules) <= 4 or len(set(rules)) != len(rules)):
            raise ValueError(f"decision group {group_index} rules must contain 1-4 unique IDs")
        if any(not isinstance(rule, str) or rule not in RULE_IDS for rule in rules):
            raise ValueError(f"decision group {group_index} contains an unknown rule ID")
        expected = _bounded_text(group["expected"], f"decision group {group_index} expected")
        risk = _bounded_text(group["risk"], f"decision group {group_index} risk")
        covered.update(orders)
        total += len(orders)
        if total > MAX_REFERENCES:
            raise ValueError("decision order references exceed 256")
        result.append({"orders": list(orders), "rules": list(rules), "expected": expected, "risk": risk})
    if covered != set(range(action_count)):
        raise ValueError("decision groups must cover every authored action exactly once")
    return result


def annotation_for_response(text: str, *, action_count: int | None = None,
                            guide_text: str = "") -> dict[str, Any]:
    """Return the fixed annotation object for any model response.

    Tool requests are deliberately inapplicable. Action responses with no
    decisions are missing evidence; malformed decisions are invalid evidence.
    """
    base = {"status": "missing", "guide_version": GUIDE_VERSION,
            "guide_hash": guide_hash(guide_text), "decisions": [], "error": None}
    try:
        decoded = parse_action_response(text)
    except (TypeError, ValueError) as exc:
        base["status"] = "invalid"
        base["error"] = str(exc)
        return base
    if isinstance(decoded, dict) and "tool" in decoded and "actions" not in decoded:
        base["status"] = "not_applicable"
        return base
    if isinstance(decoded, list):
        return base
    if not isinstance(decoded, dict) or "actions" not in decoded:
        base["status"] = "invalid"
        base["error"] = "response must contain actions"
        return base
    if "decisions" not in decoded:
        return base
    if action_count is None:
        actions = decoded.get("actions")
        if not isinstance(actions, list):
            base.update(status="invalid", error="actions must be an array")
            return base
        action_count = len(actions)
    try:
        base["decisions"] = validate_decisions(decoded["decisions"], action_count)
    except ValueError as exc:
        base["status"] = "invalid"
        base["error"] = str(exc)[:240]
        return base
    base["status"] = "valid"
    return base
