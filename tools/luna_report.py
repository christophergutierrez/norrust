"""Small truthful report helper for Luna NDJSON attempts."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


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


def classify(records: list[dict[str, Any]]) -> dict[str, Any]:
    terminal = next((item for item in reversed(records) if item.get("type") == "terminal"), {})
    events = [item.get("line", {}) for item in records if item.get("type") == "driver"]
    accepted = [item for item in events if item.get("type") == "events"]
    side_turns = set()
    attacks = Counter()
    deaths = Counter()
    factions: dict[int, Any] = {}
    moved = set()
    for item in events:
        if item.get("type") == "state":
            for unit in item.get("units", []):
                if isinstance(unit, dict) and isinstance(unit.get("id"), int):
                    factions[unit["id"]] = unit.get("faction")
            if isinstance(item.get("side_turns"), int):
                side_turns.add(item["side_turns"])
            elif isinstance(item.get("turn"), int):
                side_turns.add(item["turn"])
            continue
    for batch in accepted:
        for event in batch.get("events", []):
            if not isinstance(event, dict):
                continue
            kind = event.get("kind")
            source = event.get("source", "unknown")
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
    failure = next((item for item in reversed(records) if item.get("type") == "model_error"), {})
    terminal_class = terminal.get("terminal_class") or failure.get("terminal_class")
    if not terminal_class and failure:
        terminal_class = "model_invalid"
    if not terminal_class:
        reason = terminal.get("reason")
        terminal_class = "gameplay" if reason in {"winner", "loss", "max_turns", "turn_limit"} else "unfinished_recoverable"
    return {
        "terminal_class": terminal_class,
        "winner": terminal.get("winner"),
        "reason": terminal.get("reason"),
        "completed_side_turns": len(side_turns),
        "accepted_event_batches": len(accepted),
        "attacks_by_source": dict(attacks),
        "deaths_by_faction": dict(deaths),
        "unique_movers": len(moved),
        "model_calls": terminal.get("model_calls", failure.get("model_calls")),
        "tool_calls": terminal.get("queries"),
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: luna_report.py LOG [LOG ...]", file=sys.stderr)
        return 2
    for name in argv:
        print(json.dumps({"log": name, **classify(load_records(name))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
