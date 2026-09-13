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
    evidence_gaps: dict[str, int] = {}
    stop_evaluations = 0
    eligible_stops = 0
    stop_requests = 0
    rejected_stops = 0
    stop_rejection_reasons: dict[str, int] = {}
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
        evidence_gaps["journal_unavailable"] = 1
    if truncated:
        evidence_gaps["journal_truncated"] = 1
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            evidence_gaps["unreadable_journal_entry"] = evidence_gaps.get("unreadable_journal_entry", 0) + 1
            last_outcome = "failure"
            continue
        if not isinstance(event, dict):
            evidence_gaps["journal_record_not_object"] = evidence_gaps.get("journal_record_not_object", 0) + 1
            last_outcome = "failure"
            continue
        kind = event.get("type")
        decision = event.get("decision")
        if kind == "dispatch":
            last_outcome = "pending"
            continue
        if kind == "stop_evaluation":
            stop_evaluations += 1
            if event.get("eligible") is True:
                eligible_stops += 1
            else:
                rejected_stops += 1
                reason = event.get("failed_prerequisite") or "unknown"
                stop_rejection_reasons[str(reason)] = stop_rejection_reasons.get(str(reason), 0) + 1
            if event.get("stop_requested") is True:
                stop_requests += 1
            continue
        if kind in VERDICT_EVENTS:
            verdicts += 1
            if decision == "inspect":
                last_outcome = "pending"
            elif decision in {"continue", "stop"}:
                judgments += 1
                last_outcome = "judgment"
            else:
                evidence_gaps["invalid_verdict_decision"] = evidence_gaps.get("invalid_verdict_decision", 0) + 1
                last_outcome = "failure"
        elif kind in FAILURE_EVENTS:
            failures += 1
            reason = event.get("error") or kind
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            last_outcome = "failure"
    if truncated:
        # A valid prefix cannot establish coverage for a torn/omitted tail.
        last_outcome = "failure"
    if last_outcome == "pending":
        evidence_gaps["pending_observation"] = evidence_gaps.get("pending_observation", 0) + 1
    return {
        "observer_verdicts": verdicts,
        "usable_judgments": judgments,
        "observer_failures": failures,
        "observer_failure_reasons": reasons,
        "evidence_gaps": evidence_gaps,
        "judgment_observed": judgments > 0,
        "last_outcome": last_outcome,
        "journal_truncated": truncated,
        "journal_intact": not evidence_gaps,
        "coverage_complete": not evidence_gaps and failures == 0,
        "stop_evaluations": stop_evaluations,
        "eligible_stops": eligible_stops,
        "rejected_stops": rejected_stops,
        "stop_requests": stop_requests,
        "stop_rejection_reasons": stop_rejection_reasons,
    }
