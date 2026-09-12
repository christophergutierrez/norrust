"""Bounded classification of observer journal coverage."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERDICT_EVENTS = ("verdict", "investigation_verdict")
FAILURE_EVENTS = ("verdict_error", "investigation_error", "preflight_error")
MAX_JOURNAL_BYTES = 2 * 1024 * 1024


def read_observer_outcomes(journal_path: Path) -> dict[str, Any]:
    """Classify bounded observer journal evidence without scoring gaps.

    ``inspect`` is an intermediate request. Only a direct non-inspect verdict
    or an investigation verdict is usable; an investigation failure leaves
    that observation window unjudged. Earlier usable windows remain evidence
    for false stops, while a later failed window cannot become a scored miss.
    """
    verdicts = 0
    judgments = 0
    failures = 0
    reasons: dict[str, int] = {}
    last_outcome: str | None = None
    try:
        with journal_path.open("rb") as stream:
            raw = stream.read(MAX_JOURNAL_BYTES + 1)
        truncated = len(raw) > MAX_JOURNAL_BYTES
        all_lines = raw[:MAX_JOURNAL_BYTES].decode("utf-8", errors="replace").splitlines()
        lines = all_lines[:4096]
        if len(all_lines) > 4096:
            truncated = True
    except OSError:
        truncated = False
        lines = []
        failures += 1
        reasons["journal_unavailable"] = 1
    if truncated:
        failures += 1
        reasons["journal_truncated"] = 1
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            failures += 1
            reasons["unreadable_journal_entry"] = reasons.get("unreadable_journal_entry", 0) + 1
            last_outcome = "failure"
            continue
        if not isinstance(event, dict):
            failures += 1
            reasons["journal_record_not_object"] = reasons.get("journal_record_not_object", 0) + 1
            last_outcome = "failure"
            continue
        kind = event.get("type")
        decision = event.get("decision")
        if kind == "dispatch":
            last_outcome = "pending"
            continue
        if kind in VERDICT_EVENTS:
            verdicts += 1
            if decision == "inspect":
                last_outcome = "pending"
            elif decision in {"continue", "stop"}:
                judgments += 1
                last_outcome = "judgment"
            else:
                failures += 1
                reasons["invalid_verdict_decision"] = reasons.get("invalid_verdict_decision", 0) + 1
                last_outcome = "failure"
        elif kind in FAILURE_EVENTS:
            failures += 1
            reason = event.get("error") or kind
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            last_outcome = "failure"
    if truncated:
        # A valid prefix cannot establish coverage for a torn/omitted tail.
        last_outcome = "failure"
    return {
        "observer_verdicts": verdicts,
        "usable_judgments": judgments,
        "observer_failures": failures,
        "observer_failure_reasons": reasons,
        "judgment_observed": judgments > 0,
        "last_outcome": last_outcome,
        "journal_truncated": truncated,
        "coverage_complete": not truncated and failures == 0,
    }
