"""Offline task-harness player with factual, deterministic objectives."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


def _board(prompt: str) -> dict:
    try:
        return json.loads(prompt.split("BOARD_UNTRUSTED_DATA_BEGIN:\n", 1)[1]
                       .split("\nBOARD_UNTRUSTED_DATA_END", 1)[0])
    except (IndexError, json.JSONDecodeError):
        return {}


def _options(prompt: str) -> list[dict]:
    try:
        payload = json.loads(prompt.split("OPTION_PAYLOADS_UNTRUSTED_DATA_BEGIN:\n", 1)[1]
                             .split("\nOPTION_PAYLOADS_UNTRUSTED_DATA_END", 1)[0])
        return [item for item in payload.get("choices", []) if isinstance(item, dict)]
    except (IndexError, json.JSONDecodeError, AttributeError):
        return []


def _partial(briefing: str) -> int:
    match = re.search(r"accepted_partials=(\d+)", briefing)
    return int(match.group(1)) if match else 0


def _units(briefing: str, faction: int = 0) -> list[dict]:
    result = []
    for line in briefing.splitlines():
        match = re.search(r"^id=(\d+) faction=(\d+) def=(\S+) .*?pos=\((-?\d+),(-?\d+)\)", line.strip())
        if match and int(match.group(2)) == faction:
            result.append({"id": int(match.group(1)), "def_id": match.group(3),
                           "col": int(match.group(4)), "row": int(match.group(5))})
    return result


def _choice(options: list[dict], category: str, **wanted: object) -> dict | None:
    for item in options:
        if item.get("category") == category and all(item.get(k) == v for k, v in wanted.items()):
            return item
    return None


def _tool_handle(prompt: str, destination: tuple[int, int] | None = None) -> str | None:
    for line in prompt.splitlines():
        if not line.startswith("CHOICES "):
            continue
        for item in line.removeprefix("CHOICES ").split("; "):
            match = re.match(r"(c_\d+_[0-9a-f]{8}): Move .* to \((-?\d+),(-?\d+)\)", item)
            if match and (destination is None or (int(match.group(2)), int(match.group(3))) == destination):
                return match.group(1)
    return None


def _tool_attack(prompt: str, target: int) -> dict | None:
    for line in prompt.splitlines():
        if not line.startswith("CHOICES "):
            continue
        for item in line.removeprefix("CHOICES ").split("; "):
            match = re.match(r"c_\d+_[0-9a-f]{8}: Attack U(\d+) with U(\d+)", item)
            if match and int(match.group(1)) == target:
                return {"action": "Attack", "attacker_id": int(match.group(2)),
                        "defender_id": target}
    return None


def _reply_for(prompt: str, choices_mode: bool = False) -> dict:
    family = os.environ.get("TASK_HARNESS_FAMILY", "opening_deployment")
    variant = int(os.environ.get("TASK_HARNESS_VARIANT", "1"))
    arm = "C" if choices_mode else os.environ.get("TASK_HARNESS_ARM", "A")
    board = _board(prompt)
    briefing = str(board.get("briefing", ""))
    partial = _partial(briefing)
    options = _options(prompt)
    units = _units(briefing)
    recruited = next((u for u in units if u["def_id"] == "Skeleton" and u["col"] == 2), None)
    if recruited is None:
        recruited = next((u for u in units if u["def_id"] == "Skeleton Archer"), None)

    def emit(action: dict, category: str | None = None, **wanted: object) -> dict:
        if arm == "C" and category:
            selected = _choice(options, category, **wanted)
            if selected is not None:
                return {"choices": [selected["handle"]], "intent": f"{family} {category}",
                        "decisions": [{"orders": [0], "rules": ["T0"],
                                       "expected": category, "risk": "none"}]}
        return {"actions": [action], "intent": f"{family} {action.get('action')}",
                "decisions": [{"orders": [0], "rules": ["T0"],
                               "expected": action.get("action", "operation"), "risk": "none"}]}

    if family == "opening_deployment":
        if partial == 0 and recruited is None:
            return emit({"action": "Recruit", "def_id": "Skeleton Archer", "col": 2, "row": 6},
                        "recruit", def_id="Skeleton Archer", col=2, row=6)
        if recruited and (recruited["col"], recruited["row"]) == (2, 6):
            if arm == "C" and not _choice(options, "move", unit_id=recruited["id"], col=2, row=5):
                handle = _tool_handle(prompt, (2, 5))
                if handle:
                    return {"choices": [handle], "intent": "opening move by handle"}
                return {"tool": "inspect_units", "unit_ids": [recruited["id"]]}
            return emit({"action": "Move", "unit_id": recruited["id"], "col": 2, "row": 5},
                        "move", unit_id=recruited["id"], col=2, row=5)
        return {"actions": [{"action": "EndTurn"}], "intent": "opening complete"}

    if family == "competing_villages":
        scout = next((u for u in units if u["def_id"] == "Vampire" or u["def_id"] == "Vampire Bat"), None)
        if scout is None:
            return emit({"action": "Recruit", "def_id": "Vampire Bat", "col": 2, "row": 6},
                        "recruit", def_id="Vampire Bat", col=2, row=6)
        if (scout["col"], scout["row"]) != (2, 4):
            dest = (2, 4)
            if arm == "C" and not _choice(options, "move", unit_id=scout["id"], col=dest[0], row=dest[1]):
                handle = _tool_handle(prompt, (2, 4))
                if handle:
                    return {"choices": [handle], "intent": "village move by handle"}
                return {"tool": "inspect_units", "unit_ids": [scout["id"]]}
            return emit({"action": "Move", "unit_id": scout["id"], "col": dest[0], "row": dest[1]},
                        "move", unit_id=scout["id"], col=dest[0], row=dest[1])
        return {"actions": [{"action": "EndTurn"}], "intent": "village captured"}

    if family == "recruiter_defense":
        target = 38 if variant == 1 else 40
        attacker = 13 if variant == 1 else 21
        attack = _choice(options, "attack", unit_id=attacker, target_id=target)
        if arm == "C" and attack:
            return {"choices": [attack["handle"]], "intent": "answer recruiter threat",
                    "decisions": [{"orders": [0], "rules": ["T3.3"],
                                   "expected": "attack threat", "risk": "none"}]}
        if partial > 0:
            return {"actions": [{"action": "EndTurn"}], "intent": "threat addressed"}
        if arm != "C":
            inspected = _tool_attack(prompt, target)
            if inspected:
                return {"actions": [inspected], "intent": "answer recruiter threat"}
            if "TOOL_RESULT_UNTRUSTED_DATA_BEGIN" not in prompt and "CHOICES " not in prompt:
                return {"tool": "inspect_units", "unit_ids": [attacker]}
            # The inspection result has already established the live threat;
            # submit the same factual attack once rather than re-inspecting.
        return emit({"action": "Attack", "attacker_id": attacker, "defender_id": target}, "attack",
                    unit_id=attacker, target_id=target)
        return {"actions": [{"action": "EndTurn"}], "intent": "recruiter survived"}

    if family == "coordinated_combat":
        target = 24 if variant == 1 else 58
        if not re.search(rf"\bid={target}\b", briefing):
            if partial == 1:
                reserve_attacker, reserve_target = ((18, 39) if variant == 1 else (49, 59))
                return emit({"action": "Attack", "attacker_id": reserve_attacker,
                             "defender_id": reserve_target}, "attack",
                            unit_id=reserve_attacker, target_id=reserve_target)
            return {"actions": [{"action": "EndTurn"}], "intent": "target resolved; reserve redirected"}
        if arm == "C":
            target = 24 if partial == 0 else 39
            attacker = 7 if partial == 0 else 18
            attack = _choice(options, "attack", unit_id=attacker, target_id=target)
            if attack:
                return {"choices": [attack["handle"]], "intent": "coordinated combat",
                        "decisions": [{"orders": [0], "rules": ["T3.3"],
                                       "expected": "attack then redirect", "risk": "none"}]}
        if variant == 1 and partial == 0:
            return emit({"action": "Attack", "attacker_id": 7, "defender_id": 24}, "attack",
                        unit_id=7, target_id=24)
        if variant == 1 and partial == 1:
            return emit({"action": "Attack", "attacker_id": 18, "defender_id": 39}, "attack",
                            unit_id=18, target_id=39)
        if variant == 2 and partial == 0:
            return emit({"action": "Attack", "attacker_id": 6, "defender_id": 58}, "attack",
                        unit_id=6, target_id=58)
        if variant == 2 and partial == 1:
            return emit({"action": "Attack", "attacker_id": 49, "defender_id": 59}, "attack",
                        unit_id=49, target_id=59)
        attack = next((c for c in options if c.get("category") == "attack"), None)
        if attack:
            return {"actions": [{"action": "Attack", "attacker_id": attack.get("unit_id"),
                                  "defender_id": attack.get("target_id")}], "intent": "coordinated combat"}
        return {"actions": [{"action": "EndTurn"}], "intent": "combat complete"}

    return {"actions": [{"action": "EndTurn"}], "intent": "fixture complete"}


def main() -> None:
    prompt = sys.stdin.read()
    usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
    context_path = Path(os.environ.get("NORRUST_REQUEST_CONTEXT_FILE", ""))
    context = json.loads(context_path.read_text()) if context_path.is_file() else {}
    game_log = context.get("game_log")
    request_id = context.get("harness_request_id")
    if game_log and request_id:
        sidecar = Path(game_log).with_name("usage.ndjson")
        call_id = f"offline:{request_id}"
        identity = {"game_id": context.get("conversation_id") or "offline_fixture",
                    "call_id": call_id, "request_id": request_id, "provider": "offline",
                    "transport": "offline_fixture", "status": "dispatched",
                    "raw_usage_json": {"fixture": True}}
        with sidecar.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(identity, sort_keys=True) + "\n")
            stream.write(json.dumps(dict(identity, status="completed", **usage), sort_keys=True) + "\n")
    print(json.dumps({"text": json.dumps(_reply_for(prompt,
        choices_mode=context.get("action_encoding") == "choices")), "usage": usage}))


if __name__ == "__main__":
    main()
