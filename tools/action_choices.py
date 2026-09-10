"""Deterministic encoding and resolution of legal game operations for choices mode."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

HANDLE_PATTERN = re.compile(r"^c_(\d+)_([0-9a-f]{8})$")


@dataclass(frozen=True)
class Choice:
    handle: str
    description: str
    actions: list[dict[str, Any]]
    category: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_display_dict(self) -> dict[str, Any]:
        return {
            "handle": self.handle,
            "description": self.description,
            "category": self.category,
            **self.metadata,
        }


def make_handle(game_id: str | None, revision: int, canonical_key: str) -> str:
    gid = game_id or "norrust"
    payload = f"{gid}:{revision}:{canonical_key}"
    token = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"c_{revision}_{token}"


def parse_handle(handle: str) -> tuple[int, str] | None:
    if not isinstance(handle, str):
        return None
    m = HANDLE_PATTERN.match(handle)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


def extract_recruitment_choices(
    recruit_options: dict[str, Any],
    game_id: str | None,
    revision: int,
) -> list[Choice]:
    choices: list[Choice] = []
    if not isinstance(recruit_options, dict):
        return choices
    hexes = recruit_options.get("placement_hexes", [])
    if not isinstance(hexes, list):
        hexes = []
    options = sorted(
        [opt for opt in recruit_options.get("options", []) if isinstance(opt, dict)],
        key=lambda o: (o.get("cost", 0), str(o.get("def_id", ""))),
    )
    sorted_hexes = sorted(
        [h for h in hexes if isinstance(h, dict) and "col" in h and "row" in h],
        key=lambda h: (h["col"], h["row"]),
    )
    for opt in options:
        if not opt.get("affordable", False):
            continue
        def_id = opt.get("def_id")
        cost = opt.get("cost", 0)
        if not def_id:
            continue
        for h in sorted_hexes:
            col, row = h["col"], h["row"]
            canonical_key = f"Recruit:{def_id}:{col}:{row}"
            handle = make_handle(game_id, revision, canonical_key)
            desc = f"Recruit {def_id} at ({col},{row}) (cost {cost})"
            choices.append(
                Choice(
                    handle=handle,
                    description=desc,
                    actions=[{"action": "Recruit", "def_id": def_id, "col": col, "row": row}],
                    category="recruit",
                    metadata={"def_id": def_id, "col": col, "row": row, "cost": cost},
                )
            )
    return choices


def extract_turn_options_choices(
    turn_options: dict[str, Any],
    game_id: str | None,
    revision: int,
) -> list[Choice]:
    choices: list[Choice] = []
    if not isinstance(turn_options, dict):
        return choices
    unit_list = sorted(
        [u for u in turn_options.get("units", []) if isinstance(u, dict)],
        key=lambda u: u.get("unit_id", 0),
    )
    for u in unit_list:
        uid = u.get("unit_id")
        if uid is None:
            continue
        positions = sorted(
            [p for p in u.get("positions", []) if isinstance(p, dict)],
            key=lambda p: (p.get("col", 0), p.get("row", 0), p.get("current", False)),
        )
        for pos in positions:
            col = pos.get("col")
            row = pos.get("row")
            if col is None or row is None:
                continue
            current = bool(pos.get("current", False))
            movable = bool(pos.get("movable", True))
            raw_targets = pos.get("target_ids", [])
            target_ids = sorted(raw_targets) if isinstance(raw_targets, list) else []

            if movable and not current:
                canonical_key = f"Move:{uid}:{col}:{row}"
                handle = make_handle(game_id, revision, canonical_key)
                desc = f"Move U{uid} to ({col},{row})"
                choices.append(
                    Choice(
                        handle=handle,
                        description=desc,
                        actions=[{"action": "Move", "unit_id": uid, "col": col, "row": row}],
                        category="move",
                        metadata={"unit_id": uid, "col": col, "row": row},
                    )
                )

            if current:
                for tid in target_ids:
                    canonical_key = f"Attack:{uid}:{col}:{row}:{tid}"
                    handle = make_handle(game_id, revision, canonical_key)
                    desc = f"Attack U{tid} with U{uid} from ({col},{row})"
                    choices.append(
                        Choice(
                            handle=handle,
                            description=desc,
                            actions=[{"action": "Attack", "attacker_id": uid, "defender_id": tid}],
                            category="attack",
                            metadata={"unit_id": uid, "target_id": tid, "col": col, "row": row},
                        )
                    )

            if not current and movable:
                for tid in target_ids:
                    canonical_key = f"MoveAttack:{uid}:{col}:{row}:{tid}"
                    handle = make_handle(game_id, revision, canonical_key)
                    desc = f"Move U{uid} to ({col},{row}) and attack U{tid}"
                    choices.append(
                        Choice(
                            handle=handle,
                            description=desc,
                            actions=[
                                {"action": "Move", "unit_id": uid, "col": col, "row": row},
                                {"action": "Attack", "attacker_id": uid, "defender_id": tid},
                            ],
                            category="move_attack",
                            metadata={"unit_id": uid, "target_id": tid, "col": col, "row": row},
                        )
                    )
    return choices


def extract_advancement_choices(
    units: list[dict[str, Any]],
    game_id: str | None,
    revision: int,
    selector_style: str = "both",
) -> list[Choice]:
    choices: list[Choice] = []
    if not isinstance(units, list):
        return choices
    sorted_units = sorted(
        [u for u in units if isinstance(u, dict)],
        key=lambda u: u.get("id", 0),
    )
    for u in sorted_units:
        if not u.get("advancement_pending"):
            continue
        uid = u.get("id")
        advances = u.get("advances_to", [])
        if not isinstance(advances, list):
            continue
        for idx, def_id in enumerate(advances):
            if selector_style in ("both", "target_index"):
                canonical_key = f"AdvanceIndex:{uid}:{idx}"
                handle = make_handle(game_id, revision, canonical_key)
                desc = f"Advance U{uid} to {def_id} (target_index {idx})"
                choices.append(
                    Choice(
                        handle=handle,
                        description=desc,
                        actions=[{"action": "Advance", "unit_id": uid, "target_index": idx}],
                        category="advance",
                        metadata={"unit_id": uid, "target_index": idx, "def_id": def_id, "selector": "target_index"},
                    )
                )
            if selector_style in ("both", "def_id"):
                canonical_key = f"AdvanceDef:{uid}:{def_id}"
                handle = make_handle(game_id, revision, canonical_key)
                desc = f"Advance U{uid} to {def_id} (def_id {def_id})"
                choices.append(
                    Choice(
                        handle=handle,
                        description=desc,
                        actions=[{"action": "Advance", "unit_id": uid, "def_id": def_id}],
                        category="advance",
                        metadata={"unit_id": uid, "def_id": def_id, "target_index": idx, "selector": "def_id"},
                    )
                )
    return choices


def extract_inspection_choices(
    inspection: dict[str, Any],
    game_id: str | None,
    revision: int,
) -> list[Choice]:
    choices: list[Choice] = []
    if not isinstance(inspection, dict) or inspection.get("available") is False:
        return choices
    uid = inspection.get("unit_id")
    if uid is None:
        return choices
    origins = sorted(
        [o for o in inspection.get("origins", []) if isinstance(o, dict)],
        key=lambda o: (o.get("col", 0), o.get("row", 0), o.get("current", False)),
    )
    for orig in origins:
        col = orig.get("col")
        row = orig.get("row")
        if col is None or row is None:
            continue
        current = bool(orig.get("current", False))
        movable = bool(orig.get("movable", True))
        if movable and not current:
            canonical_key = f"Move:{uid}:{col}:{row}"
            handle = make_handle(game_id, revision, canonical_key)
            desc = f"Move U{uid} to ({col},{row})"
            choices.append(
                Choice(
                    handle=handle,
                    description=desc,
                    actions=[{"action": "Move", "unit_id": uid, "col": col, "row": row}],
                    category="move",
                    metadata={"unit_id": uid, "col": col, "row": row},
                )
            )
        engagements = orig.get("engagements", [])
        if isinstance(engagements, list):
            for eng in engagements:
                if not isinstance(eng, dict):
                    continue
                tid = eng.get("defender_id") if eng.get("defender_id") is not None else eng.get("target_id")
                if tid is None:
                    continue
                if current:
                    canonical_key = f"Attack:{uid}:{col}:{row}:{tid}"
                    handle = make_handle(game_id, revision, canonical_key)
                    desc = f"Attack U{tid} with U{uid} from ({col},{row})"
                    choices.append(
                        Choice(
                            handle=handle,
                            description=desc,
                            actions=[{"action": "Attack", "attacker_id": uid, "defender_id": tid}],
                            category="attack",
                            metadata={"unit_id": uid, "target_id": tid, "col": col, "row": row},
                        )
                    )
                elif movable:
                    canonical_key = f"MoveAttack:{uid}:{col}:{row}:{tid}"
                    handle = make_handle(game_id, revision, canonical_key)
                    desc = f"Move U{uid} to ({col},{row}) and attack U{tid}"
                    choices.append(
                        Choice(
                            handle=handle,
                            description=desc,
                            actions=[
                                {"action": "Move", "unit_id": uid, "col": col, "row": row},
                                {"action": "Attack", "attacker_id": uid, "defender_id": tid},
                            ],
                            category="move_attack",
                            metadata={"unit_id": uid, "target_id": tid, "col": col, "row": row},
                        )
                    )
    return choices


def extract_tactical_surface_choices(
    surface: dict[str, Any],
    game_id: str | None,
    revision: int,
) -> list[Choice]:
    choices: list[Choice] = []
    if not isinstance(surface, dict):
        return choices
    recruitment = surface.get("recruitment")
    if isinstance(recruitment, dict):
        choices.extend(extract_recruitment_choices(recruitment, game_id, revision))

    for unit in surface.get("units", []):
        if not isinstance(unit, dict):
            continue
        uid = unit.get("unit_id")
        if uid is None:
            continue
        for orig in unit.get("origins", []):
            if not isinstance(orig, dict) or not orig.get("current"):
                continue
            col = orig.get("col")
            row = orig.get("row")
            if col is None or row is None:
                continue
            for eng in orig.get("engagements", []):
                if not isinstance(eng, dict):
                    continue
                tid = eng.get("defender_id") if eng.get("defender_id") is not None else eng.get("target_id")
                if tid is None:
                    continue
                canonical_key = f"Attack:{uid}:{col}:{row}:{tid}"
                handle = make_handle(game_id, revision, canonical_key)
                desc = f"Attack U{tid} with U{uid} from ({col},{row})"
                choices.append(
                    Choice(
                        handle=handle,
                        description=desc,
                        actions=[{"action": "Attack", "attacker_id": uid, "defender_id": tid}],
                        category="attack",
                        metadata={"unit_id": uid, "target_id": tid, "col": col, "row": row},
                    )
                )
    return choices


def extract_available_choices(
    state: dict[str, Any],
    game_id: str | None,
    revision: int,
) -> list[Choice]:
    """Extract all choices immediately available in the given state without extra tool queries."""
    seen_handles: set[str] = set()
    result: list[Choice] = []

    def add_all(items: list[Choice]) -> None:
        for c in items:
            if c.handle not in seen_handles:
                seen_handles.add(c.handle)
                result.append(c)

    if isinstance(state.get("turn_options"), dict):
        add_all(extract_turn_options_choices(state["turn_options"], game_id, revision))

    if isinstance(state.get("recruit_options"), dict):
        add_all(extract_recruitment_choices(state["recruit_options"], game_id, revision))

    if isinstance(state.get("tactical_surface"), dict):
        add_all(extract_tactical_surface_choices(state["tactical_surface"], game_id, revision))

    if isinstance(state.get("units"), list):
        add_all(extract_advancement_choices(state["units"], game_id, revision))

    return result


class ChoiceRegistry:
    """Manages currently exposed choices for a game and state revision."""

    def __init__(self, game_id: str | None = None) -> None:
        self.game_id = game_id
        self.current_revision: int = -1
        self.exposed: dict[str, Choice] = {}

    def sync_revision(self, revision: int) -> None:
        if revision != self.current_revision:
            self.current_revision = revision
            self.exposed.clear()

    def register(self, choice: Choice) -> None:
        self.exposed[choice.handle] = choice

    def register_all(self, choices: list[Choice]) -> None:
        for c in choices:
            self.register(c)

    def get_exposed_list(self) -> list[dict[str, Any]]:
        return [c.to_display_dict() for c in self.exposed.values()]

    def resolve(
        self,
        handles: list[str],
        current_revision: int,
    ) -> tuple[list[dict[str, Any]], list[int], list[Choice]]:
        """Resolve a list of handles into primitive actions and expansion indices.

        Raises ValueError on stale, unknown, or malformed handles.
        """
        if not isinstance(handles, list) or not handles:
            raise ValueError("choices must be a non-empty array of handles")
        if len(handles) > 256:
            raise ValueError("choices array exceeds 256 handles")

        resolved_actions: list[dict[str, Any]] = []
        expansion_mapping: list[int] = []
        resolved_choices: list[Choice] = []

        for choice_idx, h in enumerate(handles):
            parsed = parse_handle(h)
            if parsed is None:
                raise ValueError(f"malformed_choice_handle: {h}")
            handle_rev, _ = parsed
            if handle_rev != current_revision:
                raise ValueError(
                    f"stale_choice_handle: {h} was observed at revision {handle_rev}, current is {current_revision}"
                )
            choice = self.exposed.get(h)
            if choice is None:
                raise ValueError(
                    f"unknown_choice_handle: {h} not in exposed choices for revision {current_revision}"
                )
            resolved_choices.append(choice)
            for act in choice.actions:
                resolved_actions.append(dict(act))
                expansion_mapping.append(choice_idx)

        return resolved_actions, expansion_mapping, resolved_choices
