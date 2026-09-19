"""Bounded, engine-fact-backed opening policy suggestions.

The opening menu is deliberately small.  It is offered only when the live
state has the supported big_battle_6 undead opening shape and every fact needed
to validate both recipes is present.  The returned responses are ordinary
``set_policy`` objects; no menu selector or future unit ID is introduced.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from .routine_policy import ValidationContext, PolicyValidationError, validate_routine_policy


SUPPORTED_VILLAGES = ((2, 4), (5, 3), (6, 11), (17, 2), (18, 10), (21, 9))
EXPANSION_VILLAGES = ((2, 4), (5, 3))
CONCENTRATION_VILLAGES = ((5, 3),)


def _supported_opening_state(state: Any) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("active_faction") != 0 or state.get("cols") != 24 or state.get("rows") != 14:
        return False
    # The menu belongs to the first ordinary policy boundary only.  A later
    # state can retain 300 gold and the same map while its opening facts and
    # available castle space have already changed.
    if state.get("turn") != 1 or state.get("state_revision") != 0:
        return False
    gold = state.get("gold")
    if not isinstance(gold, list) or len(gold) <= 0 or gold[0] != 300:
        return False
    factions = state.get("factions")
    if not isinstance(factions, list) or len(factions) < 2:
        return False
    ids = {item.get("side"): item.get("id") for item in factions if isinstance(item, dict)}
    if ids.get(0) != "undead" or ids.get(1) != "undead":
        return False
    units = state.get("units")
    if not isinstance(units, list) or len(units) != 2:
        return False
    leaders = [u for u in units if isinstance(u, dict) and u.get("faction") == 0
               and u.get("can_recruit") is True]
    if len(leaders) != 1 or leaders[0].get("col") != 2 or leaders[0].get("row") != 7:
        return False
    enemy_leaders = [u for u in units if isinstance(u, dict) and u.get("faction") == 1
                     and u.get("can_recruit") is True]
    if len(enemy_leaders) != 1:
        return False
    terrain = state.get("terrain")
    if not isinstance(terrain, list):
        return False
    villages = {
        (tile.get("col"), tile.get("row")): tile
        for tile in terrain
        if isinstance(tile, dict) and tile.get("terrain_id") == "village"
    }
    return all(pair in villages and villages[pair].get("owner") == -1
               for pair in SUPPORTED_VILLAGES)


def _option_costs(recruit_options: Any) -> dict[str, int] | None:
    if not isinstance(recruit_options, dict):
        return None
    if recruit_options.get("side_can_place") is not True:
        return None
    placements = recruit_options.get("placement_hexes")
    if not isinstance(placements, list) or not placements:
        return None
    options = recruit_options.get("options")
    if not isinstance(options, list):
        return None
    costs: dict[str, int] = {}
    for option in options:
        if not isinstance(option, dict):
            continue
        def_id, cost = option.get("def_id"), option.get("cost")
        if isinstance(def_id, str) and isinstance(cost, int) and not isinstance(cost, bool) and cost >= 0:
            if def_id in {"Vampire Bat", "Ghost", "Skeleton", "Dark Adept"} and option.get("affordable") is not True:
                return None
            costs[def_id] = cost
    needed = {"Vampire Bat", "Ghost", "Skeleton", "Dark Adept"}
    return costs if needed <= costs.keys() else None


def _policy(label: str, intent: str, policy: dict[str, Any], costs: dict[str, int],
            validation_context: ValidationContext) -> dict[str, Any] | None:
    try:
        normalized = validate_routine_policy(policy, validation_context)
    except PolicyValidationError:
        return None
    cost = sum(costs[item["def_id"]] * item["count"] for item in normalized["recruits"])
    gold = 300
    if cost + normalized["reserve_gold"] > gold or cost < (gold * 80 // 100):
        return None
    return {
        "label": label,
        "intent": intent,
        "response": {"kind": "set_policy", "policy": copy.deepcopy(normalized)},
        "recruit_cost": cost,
        "reserve_gold": normalized["reserve_gold"],
    }


def build_opening_policies(
    state: dict[str, Any] | None,
    validation_context: ValidationContext | None,
    recruit_options: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Return up to two validated opening ``set_policy`` responses.

    An empty list means the live state is unsupported or a required engine fact
    is unknown.  Existing scout IDs are intentionally empty: IDs for recruits
    do not exist until the driver commits those recruits.
    """
    if not _supported_opening_state(state) or not isinstance(validation_context, ValidationContext):
        return []
    costs = _option_costs(recruit_options)
    if costs is None:
        return []

    expansion = _policy(
        "Expansion",
        "Use two scouts for nearby villages, Skeletons and Ghosts as a frontline, and Dark Adepts as ranged support; advance them together toward the rally.",
        {
            "reserve_gold": 50,
            "recruits": [
                {"def_id": "Vampire Bat", "count": 2, "role": "scout"},
                {"def_id": "Skeleton", "count": 6, "role": "army"},
                {"def_id": "Ghost", "count": 2, "role": "army"},
                {"def_id": "Dark Adept", "count": 6, "role": "army"},
            ],
            "scouts": [],
            "villages": [{"col": col, "row": row} for col, row in EXPANSION_VILLAGES],
            "rally": {"col": 6, "row": 6},
            "holds": [],
        }, costs, validation_context)
    concentration = _policy(
        "Concentration",
        "Use one scout for a central village and a larger Skeleton frontline with Ghosts and Dark Adept ranged support; keep the army together toward the rally.",
        {
            "reserve_gold": 48,
            "recruits": [
                {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
                {"def_id": "Skeleton", "count": 7, "role": "army"},
                {"def_id": "Ghost", "count": 2, "role": "army"},
                {"def_id": "Dark Adept", "count": 6, "role": "army"},
            ],
            "scouts": [],
            "villages": [{"col": col, "row": row} for col, row in CONCENTRATION_VILLAGES],
            "rally": {"col": 6, "row": 6},
            "holds": [],
        }, costs, validation_context)
    return [item for item in (expansion, concentration) if item is not None]


def render_opening_policy_menu(policies: list[dict[str, Any]]) -> str:
    """Render the volatile, copy-ready opening menu under a 4 KiB bound."""
    if not policies:
        return (
            "OPENING_POLICY_SUGGESTIONS: unavailable for this state or because required live "
            "engine facts are unknown; use the ordinary custom set_policy response."
        )
    lines = [
        "OPENING_POLICY_SUGGESTIONS_BEGIN",
        "Supported scope: big_battle_6, undead side 0, ordinary 300-gold opening.",
        "These are complete ordinary set_policy responses; copy one or edit it. "
        "Scout IDs stay empty until the driver commits actual recruits. These compositions are examples, not proven counters; adapt them to enemy weapons and live threats.",
    ]
    for item in policies[:2]:
        response = json.dumps(item["response"], sort_keys=True, separators=(",", ":"))
        lines.append(f"{item['label']}: {item['intent']}")
        lines.append(f"  recruit_cost={item['recruit_cost']}, reserve_gold={item['reserve_gold']}")
        lines.append(f"  response={response}")
    lines.append("OPENING_POLICY_SUGGESTIONS_END")
    rendered = "\n".join(lines)
    if len(rendered.encode("utf-8")) > 4096:
        return (
            "OPENING_POLICY_SUGGESTIONS: unavailable because the validated menu exceeded its "
            "volatile prompt bound; use the ordinary custom set_policy response."
        )
    return rendered
