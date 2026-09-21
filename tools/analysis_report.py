"""Evidence-linked improvement findings for recorded Norrust decisions.

This module only assembles facts already present in an archive report and an
optional bounded-evaluation artifact.  It never runs a model or simulation.
Findings deliberately keep candidate omission, selection, execution, and
missing evidence separate; a sampled short-horizon result is not a claim of
an optimal move.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence


def _finding(code: str, category: str, severity: str, title: str,
             evidence: Sequence[Any], action: str, *, status: str = "observed",
             limitations: Sequence[str] = ()) -> dict[str, Any]:
    return {
        "code": code, "category": category, "severity": severity,
        "status": status, "title": title, "evidence": list(evidence),
        "recommended_action": action, "limitations": list(limitations),
    }


def classify_findings(archive_report: Mapping[str, Any],
                      evaluation: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Classify only conclusions supported by the supplied evidence."""
    findings: list[dict[str, Any]] = []
    coverage = archive_report.get("coverage_status")
    if coverage != "complete":
        findings.append(_finding(
            "evidence.incomplete", "evidence", "high",
            "Strategic conclusions are limited by incomplete capture",
            [coverage, archive_report.get("coverage_detail")],
            "Repair capture/import coverage before treating this game as a strategy example.",
            status="unknown",
            limitations=["Operational evidence is incomplete; this is not evidence that strategy caused the outcome."],
        ))

    for conflict in archive_report.get("reference_conflicts") or []:
        findings.append(_finding(
            "evidence.reference_conflict", "evidence", "high",
            "Referenced evidence has a hash or path conflict", [conflict],
            "Resolve the archive conflict before using the affected metric.",
            status="conflicting"))

    turns = archive_report.get("turns") or {}
    if turns.get("terminal_partial_turns") or turns.get("open_turns_at_end"):
        findings.append(_finding(
            "execution.open_turn", "execution", "medium",
            "The game ended with an open or terminal-partial turn",
            [turns.get("terminal_partial_turns"), turns.get("open_turns_at_end")],
            "Inspect the final request, validation, repair, and terminal events before judging the move.",
            limitations=["A partial turn is not a completed decision cycle."],
        ))

    decisions = (archive_report.get("decisions") or {}).get("items") or []
    for decision in decisions:
        decision_id = decision.get("decision_id")
        if decision.get("candidate_omission") == "unknown_without_offline_enumeration":
            # This is a known analysis gap, not a claim that a candidate was
            # omitted. It remains useful because it tells the next operator
            # which capsule needs offline enumeration.
            findings.append(_finding(
                "candidate.coverage_unknown", "candidate_generation", "low",
                "Candidate coverage cannot be established from live capture alone",
                [decision_id],
                "Run offline legal-opportunity enumeration for this decision capsule.",
                status="unknown",
                limitations=["The shown menu is not evidence of the complete legal set."],
            ))
        if decision.get("candidates_truncated"):
            findings.append(_finding(
                "candidate.display_truncated", "observation", "medium",
                "The displayed candidate menu was truncated",
                [decision_id, decision.get("candidates_offered")],
                "Measure the omitted menu against the restored legal opportunity set.",
                limitations=["Truncation alone does not prove the omitted action was useful."],
            ))
        if decision.get("validations_rejected", 0):
            findings.append(_finding(
                "execution.validation_rejection", "execution", "high",
                "A proposed action failed validation",
                [decision_id, decision.get("validations_rejected")],
                "Inspect the rejected order and repair path; fix the contract if the intent was legal.",
                limitations=["A rejected order is not a committed action."],
            ))
        if decision.get("repairs", 0):
            findings.append(_finding(
                "execution.repair_loop", "execution", "medium",
                "The decision required response repair",
                [decision_id, decision.get("repairs")],
                "Measure repair frequency and preserve the original response when improving prompts or parsers.",
            ))
        if decision.get("candidates_offered") is not None and decision.get("selection") is None:
            findings.append(_finding(
                "selection.unresolved", "selection", "medium",
                "Candidates were captured but no selection was linked",
                [decision_id],
                "Repair request/action linkage before evaluating selection quality.",
                status="unknown"))

    usage = archive_report.get("usage") or {}
    if usage.get("unknown_total_calls"):
        findings.append(_finding(
            "resource.usage_unknown", "evidence", "medium",
            "Some physical call totals are unavailable",
            [usage.get("unknown_total_calls")],
            "Reconcile provider receipts before comparing cost or token efficiency.",
            status="unknown"))

    if evaluation is not None:
        candidates = evaluation.get("candidates") or []
        by_id = {c.get("candidate_id"): c for c in candidates if isinstance(c, Mapping)}
        best = evaluation.get("best_candidate") or {}
        best_id = best.get("candidate_id")
        if best_id and best_id in by_id:
            best_item = by_id[best_id]
            seen = bool(best_item.get("seen_by_player"))
            if not seen:
                findings.append(_finding(
                    "candidate.omitted_tested_alternative", "candidate_generation", "high",
                    "A tested alternative was absent from the shown candidate set",
                    [best_id, best.get("verdict")],
                    "Improve candidate generation or actor coverage, then retest on held-out positions.",
                    limitations=["This ranks only candidates tested under the declared short-horizon evaluator."],
                ))
            else:
                findings.append(_finding(
                    "selection.shown_alternative", "selection", "medium",
                    "A shown candidate ranked best under the bounded evaluator",
                    [best_id, best.get("verdict")],
                    "Investigate representation and ranking information before changing candidate generation.",
                    limitations=["This is not proof that the action is globally optimal or that the full game would be won."],
                ))
        if evaluation.get("matched_seed_comparison_note"):
            findings.append(_finding(
                "evaluation.matched_seed_limit", "evidence", "low",
                "Candidate samples had unequal completion coverage",
                [evaluation.get("matched_seed_comparison_note")],
                "Investigate censored samples and compare only on the declared matched-seed subset.",
                status="unknown"))
        if not candidates and evaluation.get("best_candidate") is None:
            findings.append(_finding(
                "evaluation.no_verdict", "evidence", "medium",
                "The bounded evaluator produced no comparable candidate verdict",
                [evaluation.get("notes")],
                "Fix capsule, legality, or evaluation coverage before making a selection claim.",
                status="unknown"))

    return findings


def build_improvement_report(archive_report: Mapping[str, Any],
                             evaluation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    findings = classify_findings(archive_report, evaluation)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (severity_order.get(f["severity"], 9), f["code"]))
    return {
        "schema_version": 1,
        "report_kind": "norrust_improvement_analysis",
        "archive": archive_report.get("archive"),
        "coverage_status": archive_report.get("coverage_status"),
        "evidence": {
            "record_count": archive_report.get("record_count", 0),
            "reference_conflicts": len(archive_report.get("reference_conflicts") or []),
            "evaluation_present": evaluation is not None,
        },
        "findings": findings,
        "interpretation": {
            "rule": "Findings identify supported investigation targets; they do not assign a single cause of loss.",
            "sampled_results": "A bounded evaluator ranks only tested candidates under its declared horizon and seed schedule.",
            "unknown": "Unknown or conflicting evidence is never treated as zero, legal, safe, or a strategic verdict.",
        },
    }


def format_improvement_report(report: Mapping[str, Any]) -> str:
    lines = [
        f"improvement report: {report.get('archive')}",
        f"coverage:           {report.get('coverage_status')}",
        f"findings:            {len(report.get('findings') or [])}",
    ]
    for finding in report.get("findings") or []:
        lines.append(f"[{finding['severity']}/{finding['status']}] {finding['code']}: {finding['title']}")
        lines.append(f"  evidence:          {jsonish(finding.get('evidence'))}")
        lines.append(f"  next action:       {finding['recommended_action']}")
        for limitation in finding.get("limitations") or []:
            lines.append(f"  limitation:        {limitation}")
    return "\n".join(lines)


def jsonish(value: Any) -> str:
    import json
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
