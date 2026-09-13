"""Bounded classification of observer journal coverage."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

VERDICT_EVENTS = ("verdict", "investigation_verdict")
FAILURE_EVENTS = ("verdict_error", "investigation_error", "preflight_error",
                  "preparation_failed", "investigation_failure")
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
    legacy_stop_requests = 0
    rejected_stops = 0
    stop_rejection_reasons: dict[str, int] = {}
    physical_dispatches = 0
    receipt_completions = 0
    receipt_failures = 0
    preflight_failures = 0
    deterministic_skips = 0
    inspection_attempts = 0
    evidence_reads = 0
    usable_evidence_reads = 0
    failed_evidence_reads = 0
    pending_inspections = 0
    pending_investigations = 0
    cap_exhausted = 0
    disabled_reason: str | None = None
    termination_reason: str | None = None
    dispatched_ids: set[str] = set()
    terminal_ids: set[str] = set()
    journal_available = True
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
        journal_available = False
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
            physical_dispatches += 1
            if isinstance(event.get("call_id"), str):
                dispatched_ids.add(event["call_id"])
            last_outcome = "pending"
            continue
        if kind == "preparation":
            if event.get("status") == "pending":
                last_outcome = "pending"
            continue
        if kind == "deterministic_skip":
            deterministic_skips += 1
            continue
        if kind == "call_cap_exhausted":
            cap_exhausted += 1
            disabled_reason = "observer_call_cap_exhausted"
            termination_reason = "observer_call_cap_exhausted"
            continue
        if kind == "monitoring_terminated":
            termination_reason = str(event.get("reason") or "operator_close")
            continue
        if kind == "inspection_started":
            inspection_attempts += 1
            pending_inspections += 1
            last_outcome = "pending"
            continue
        if kind in {"inspection_completed", "inspection_cancelled"}:
            pending_inspections = max(0, pending_inspections - 1)
            if kind == "inspection_cancelled":
                evidence_gaps["inspection_cancelled"] = evidence_gaps.get("inspection_cancelled", 0) + 1
                last_outcome = "failure"
            continue
        if kind == "evidence_read":
            evidence_reads += 1
            if event.get("status") == "complete":
                usable_evidence_reads += 1
            else:
                failed_evidence_reads += 1
            continue
        if kind == "investigation_cancelled":
            pending_investigations += 1
            evidence_gaps["investigation_cancelled"] = evidence_gaps.get("investigation_cancelled", 0) + 1
            last_outcome = "failure"
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
        if kind == "stop_recommendation":
            # Older journals predate stop_evaluation but the recommendation
            # itself proves that the controller submitted a stop request.
            legacy_stop_requests += 1
            continue
        if kind in VERDICT_EVENTS:
            verdicts += 1
            if isinstance(event.get("call_id"), str):
                terminal_ids.add(event["call_id"])
            receipt_completions += 1
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
            if isinstance(event.get("call_id"), str) and event.get("paid_call") is True:
                terminal_ids.add(event["call_id"])
            if kind in ("preflight_error", "preparation_failed", "investigation_failure"):
                preflight_failures += 1
            else:
                receipt_failures += 1
            reason = event.get("error") or kind
            reasons[str(reason)] = reasons.get(str(reason), 0) + 1
            last_outcome = "failure"
    if truncated:
        # A valid prefix cannot establish coverage for a torn/omitted tail.
        last_outcome = "failure"
    if last_outcome == "pending":
        evidence_gaps["pending_observation"] = evidence_gaps.get("pending_observation", 0) + 1
    unresolved_receipts = len(dispatched_ids - terminal_ids)
    if unresolved_receipts:
        pending_investigations += unresolved_receipts
        evidence_gaps["unresolved_receipt"] = unresolved_receipts
    if pending_inspections:
        evidence_gaps["pending_inspection"] = pending_inspections
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
        "journal_available": journal_available,
        "stop_evaluations": stop_evaluations if journal_available else None,
        "eligible_stops": eligible_stops if journal_available else None,
        "rejected_stops": rejected_stops if journal_available else None,
        "stop_requests": ((stop_requests if stop_evaluations else legacy_stop_requests)
                          if journal_available else None),
        "stop_rejection_reasons": stop_rejection_reasons if journal_available else None,
        # Lifecycle and coverage are deliberately separate dimensions. A
        # dispatch proves a physical provider call; a verdict proves a
        # receipt; evidence reads prove usable investigation material.
        "physical_dispatches": physical_dispatches,
        "receipt_completions": receipt_completions,
        "receipt_failures": receipt_failures,
        "unresolved_receipts": unresolved_receipts,
        "preflight_failures": preflight_failures,
        "deterministic_skips": deterministic_skips,
        "inspection_attempts": inspection_attempts,
        "evidence_reads": evidence_reads,
        "usable_evidence_reads": usable_evidence_reads,
        "failed_evidence_reads": failed_evidence_reads,
        "pending_inspections": pending_inspections,
        "pending_investigations": pending_investigations,
        "call_cap_exhausted": cap_exhausted > 0,
        "disabled_reason": disabled_reason,
        "termination_reason": termination_reason,
    }
