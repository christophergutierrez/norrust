"""Small, optional bookkeeping for Luna's model-authored turn objectives."""
from __future__ import annotations

import json
from typing import Any

MAX_TASKS = 8
MAX_GOAL_BYTES = 160
MAX_AGENDA_BYTES = 4096
STATUSES = {"pending", "active", "done", "deferred"}


def normalize_agenda(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a full agenda replacement without making it executable."""
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, "agenda must be an object"
    tasks = value.get("tasks", [])
    holds = value.get("holds", [])
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        return None, "agenda.tasks must contain at most eight tasks"
    if not isinstance(holds, list):
        return None, "agenda.holds must be an array"
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    active = 0
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {"id", "goal", "units", "status"}:
            return None, "agenda tasks require exactly id, goal, units, status"
        task_id, goal, units, status = (task["id"], task["goal"], task["units"], task["status"])
        if not isinstance(task_id, str) or not task_id or task_id in ids:
            return None, "agenda task ids must be unique non-empty strings"
        if not isinstance(goal, str) or len(goal.encode()) > MAX_GOAL_BYTES:
            return None, "agenda task goals must be at most 160 UTF-8 bytes"
        if not isinstance(units, list) or any(not isinstance(unit, int) or isinstance(unit, bool) for unit in units):
            return None, "agenda task units must be integer friendly ids"
        if status not in STATUSES:
            return None, "agenda task status is invalid"
        active += status == "active"
        ids.add(task_id)
        normalized.append({"id": task_id, "goal": goal, "units": list(dict.fromkeys(units)), "status": status})
    if active > 1:
        return None, "agenda may have at most one active task"
    if any(not isinstance(unit, int) or isinstance(unit, bool) for unit in holds):
        return None, "agenda holds must contain integer friendly ids"
    result = {"tasks": normalized, "holds": list(dict.fromkeys(holds))}
    if len(json.dumps(result, separators=(",", ":")).encode()) > MAX_AGENDA_BYTES:
        return None, "agenda is too large"
    return result, None


def response_agenda(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(value, dict) or "agenda" not in value:
        return None, None
    return normalize_agenda(value.get("agenda"))


def compact_agenda(agenda: dict[str, Any] | None) -> str:
    if not agenda:
        return "AGENDA none"
    tasks = "; ".join(
        "%s[%s] U%s: %s" % (
            task["id"], task["status"], ",".join("U%s" % unit for unit in task["units"]) or "-", task["goal"])
        for task in agenda.get("tasks", [])
    )
    holds = ",".join("U%s" % unit for unit in agenda.get("holds", [])) or "-"
    return "AGENDA tasks=%s holds=%s" % (tasks or "none", holds)


def agenda_from_response(text: str, current: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None, bool]:
    agenda, error = response_agenda(text)
    if error:
        return current, error, False
    if agenda is None:
        return current, None, False
    return agenda, None, True
