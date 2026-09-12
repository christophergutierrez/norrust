#!/usr/bin/env python3
"""Produce one bounded offline watchdog review packet.

This command consumes already recorded evidence and never dispatches an
observer or player request.  It is suitable for Stack 4 fixture review and for
an indexed run after the catalog importer has completed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .game_history import _read_usage_sidecar
from .llm_client import TERMINAL_GAMEPLAY, classify_terminal
from .model_usage import aggregate_calls, dedupe_calls
from .watchdog_outcomes import read_observer_outcomes

MAX_REVIEW_EVIDENCE = 2
MAX_EVIDENCE_BYTES = 2048


def _identity_and_terminal(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Stream identity and terminal evidence with a natural-winner fence.

    A driver ``game_end`` is authoritative even if client cleanup appends a
    later infrastructure or observer-interrupted record.  This mirrors the
    supervisor's race resolution and prevents the report from rewriting a
    proven gameplay result as a cancellation.
    """
    metadata: dict[str, Any] = {}
    terminal: dict[str, Any] | None = None
    natural: dict[str, Any] | None = None
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if len(line) > 1024 * 1024:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                if not metadata and value.get("type") == "metadata":
                    metadata = value
                line_value = value.get("line") if value.get("type") == "driver" else value
                if isinstance(line_value, dict) and line_value.get("type") == "game_end":
                    reason = line_value.get("reason")
                    terminal_class = classify_terminal(reason)
                    natural = {"type": "game_end", "terminal_class": terminal_class,
                               "winner": (line_value.get("winner")
                                          if terminal_class == TERMINAL_GAMEPLAY else None),
                               "reason": reason,
                               "code": (line_value.get("code") or line_value.get("failure_code")
                                        or line_value.get("error_code"))}
                if value.get("type") in {"terminal", "observer_interrupted", "game_end",
                                          "budget_interrupted", "model_error"}:
                    terminal = natural if value.get("type") == "game_end" else value
    except OSError:
        pass
    # Only a classified gameplay ``game_end`` wins a terminal race.  A driver
    # failure envelope remains infrastructure evidence and must not mask a
    # later authoritative terminal record.
    if natural is not None and natural.get("terminal_class") == TERMINAL_GAMEPLAY:
        return metadata, natural
    return metadata, terminal if terminal is not None else natural


def _json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _persisted_status(log: Path) -> dict[str, Any]:
    """Read the last recorder packet without polling or mutating the run."""
    state_path = log.parent / f"{log.stem}.watchdog" / "state.json"
    state = _json_file(state_path)
    latest = state.get("latest")
    if isinstance(latest, dict):
        packet = latest.get("packet")
        if isinstance(packet, dict):
            return packet
    packet = state.get("status")
    if isinstance(packet, dict):
        return packet
    return {
        "run_id": state.get("run_id"), "stage": "unknown",
        "revision": None, "freshness": {"state": "unknown"},
        "alerts": [], "evidence_ids": [], "degraded": True,
        "coverage_events": ["recorder_status_unavailable"],
        "usage_coverage": {"status": "unknown"},
    }


def _recorded_watchdog_mode(path: Path) -> str | None:
    """Return the latest supervisor-declared monitoring mode, if recorded."""
    mode: str | None = None
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if len(line) > 1024 * 1024:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict) and value.get("type") == "supervisor_attempt_start":
                    candidate = value.get("watchdog_mode")
                    mode = candidate if candidate in {"off", "observe", "enforce"} else "unknown"
    except OSError:
        return None
    return mode


def _usage_summary(path: Path, *, identities: set[str] | None = None,
                   rate_file: str | Path | None = None) -> dict[str, Any]:
    """Summarize bounded, lifecycle-deduplicated calls from one run.

    ``identities`` contains proven catalog conversation IDs.  When supplied,
    calls from other games are retained only as a filtered-record count and
    never enter totals.  An empty set intentionally means identity is unknown,
    so callers cannot guess from a run UUID or filename.
    """
    calls, malformed = _read_usage_sidecar(path)
    foreign = 0
    if identities is not None:
        accepted = []
        for call in calls:
            if call.game_id in identities:
                accepted.append(call)
            else:
                foreign += 1
        calls = accepted
        if foreign:
            malformed.append(f"foreign_records_filtered:{foreign}")
    calls, conflicts = dedupe_calls(calls)
    buckets = {
        "player": [call for call in calls if call.call_role == "player"],
        "observer": [call for call in calls if call.call_role == "observer"],
        "unknown": [call for call in calls if call.call_role is None],
        "combined": calls,
    }
    summary: dict[str, Any] = {}
    for role, members in buckets.items():
        aggregate = aggregate_calls(members)
        total = aggregate["total_tokens"]
        summary[role] = {
            "status": ("unknown" if not members else
                       "measured" if total["fully_measured"] else "partial_unknown"),
            "calls": len(members),
            "known_tokens": total["sum"],
            "known_calls": total["known_calls"],
            "unknown_calls": total["unknown_calls"],
            "providers": sorted({call.provider for call in members if call.provider}),
            "provider_counts": {provider: sum(1 for call in members if call.provider == provider)
                               for provider in sorted({call.provider for call in members if call.provider})},
        }
    if identities is not None and not identities:
        malformed.append("usage_identity_unknown")
    if identities is not None:
        summary["identity_filter"] = sorted(identities)
    if rate_file is not None:
        from .usage_cost import role_cost_report
        summary["costs"] = role_cost_report(calls, rate_file)
    summary["malformed_records"] = malformed
    summary["lifecycle_conflicts"] = {
        f"{game}:{call}": values for (game, call), values in conflicts.items()}
    return summary


def _observer_calls(path: Path, identities: set[str]) -> list[Any]:
    """Return identity-filtered observer lifecycle calls for outcome review."""
    calls, _malformed = _read_usage_sidecar(path)
    calls = [call for call in calls
             if call.call_role == "observer" and call.game_id in identities]
    calls, _conflicts = dedupe_calls(calls)
    return calls


def _observer_state_path(log: Path, explicit: str | Path | None) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    return log.parent / f"{log.stem}.watchdog" / "observer-state.json"


def _bounded_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)][:MAX_REVIEW_EVIDENCE]


def review(log_path: str | Path, *, run_id: str | None = None,
           observer_state: str | Path | None = None,
           rate_file: str | Path | None = None) -> dict[str, Any]:
    log = Path(log_path).resolve()
    status = _persisted_status(log)
    persisted_run_id = status.get("run_id") if isinstance(status.get("run_id"), str) else None
    resolved_run_id = run_id if isinstance(run_id, str) and run_id else persisted_run_id
    metadata, terminal = _identity_and_terminal(log)
    watchdog_mode = _recorded_watchdog_mode(log)
    conversation_id = metadata.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        conversation_id = status.get("conversation_id") if isinstance(status.get("conversation_id"), str) else None
    usage = _usage_summary(log.with_name("usage.ndjson"),
                           identities={conversation_id} if conversation_id else set(),
                           rate_file=rate_file)
    coverage_events = list(status.get("coverage_events", [])) if isinstance(status.get("coverage_events"), list) else []
    if not conversation_id:
        coverage_events.append("conversation_identity_unknown")
    observer_path = _observer_state_path(log, observer_state)
    observer_state_exists = observer_path is not None and observer_path.is_file()
    observer = _json_file(observer_path) if observer_path is not None else {}
    observer_state_invalid = False
    if resolved_run_id is None or observer.get("run_id") != resolved_run_id:
        if observer:
            coverage_events.append("observer_state_identity_mismatch")
            observer_state_invalid = True
        elif observer_state_exists:
            coverage_events.append("observer_state_unavailable")
            observer_state_invalid = True
        observer = {}
    verdict = observer.get("last_verdict") if isinstance(observer.get("last_verdict"), dict) else None
    observer_calls = observer.get("dispatched_calls")
    observer_calls = observer_calls if isinstance(observer_calls, int) and observer_calls >= 0 else None
    observed_calls = usage["observer"]["calls"]
    providers = set(usage["observer"].get("providers", []))
    journal_outcomes = read_observer_outcomes(
        observer_path.with_suffix(".journal.ndjson")) if observer_path is not None else {
            "judgment_observed": False, "observer_failures": 0,
            "observer_verdicts": 0, "observer_failure_reasons": {},
            "last_outcome": None}
    observer_calls_detail = _observer_calls(log.with_name("usage.ndjson"),
                                            {conversation_id} if conversation_id else set())
    completed_calls = sum(call.status == "completed" for call in observer_calls_detail)
    failed_calls = sum(call.status == "failed" for call in observer_calls_detail)
    journal_available = (observer_path is not None and
                         observer_path.with_suffix(".journal.ndjson").is_file() and
                         journal_outcomes.get("journal_intact", False))
    # An intact observer journal owns lifecycle failure counts. A missing
    # journal falls back to failed receipts, avoiding double-counting the same
    # physical failure from both sources.
    failure_count = (journal_outcomes.get("observer_failures", 0)
                     if journal_available else failed_calls)
    valid_observer_mode = (observer_state_exists and not observer_state_invalid and
                           observer.get("mode") in {"off", "observe", "enforce"}
                           and observer_calls == 0)
    if observer_state_invalid:
        evaluation = {"status": "unknown", "network_calls": None,
                      "observed_calls": observed_calls or observer_calls}
    elif not observer_state_exists and observed_calls:
        evaluation = {"status": "unknown", "network_calls": None,
                      "observed_calls": observed_calls}
    elif observed_calls == 0 and not observer_calls and (watchdog_mode == "off" or valid_observer_mode):
        evaluation = {"status": "not_run", "network_calls": 0}
    elif observed_calls == 0 and not observer_calls:
        evaluation = {"status": "unknown", "network_calls": None}
    elif observed_calls and providers and providers <= {"fake"}:
        evaluation = {"status": "offline_fake", "network_calls": None,
                      "observed_calls": observed_calls}
    elif observed_calls and any(provider != "fake" for provider in providers):
        provider_counts = usage["observer"].get("provider_counts", {})
        network_calls = sum(count for provider, count in provider_counts.items()
                            if provider != "fake")
        # A receipt proves dispatch and perhaps transport delivery. It is a
        # successful evaluation only when a usable decision is also present.
        if not journal_outcomes.get("judgment_observed"):
            evaluation_status = "failed" if failed_calls == observed_calls or completed_calls == 0 else "partial"
        elif (journal_outcomes.get("last_outcome") in {"pending", "failure"}
              or not journal_outcomes.get("journal_intact", False)
              or journal_outcomes.get("evidence_gaps")):
            evaluation_status = "partial"
        elif journal_outcomes.get("observer_failures") or failed_calls:
            evaluation_status = "partial"
        else:
            evaluation_status = "completed"
        evaluation = {"status": evaluation_status, "network_calls": network_calls,
                      "observed_calls": observed_calls,
                      "verdicts": journal_outcomes.get("observer_verdicts", 0),
                      "failures": failure_count,
                      "failure_reasons": journal_outcomes.get("observer_failure_reasons", {}),
                      "evidence_gaps": journal_outcomes.get("evidence_gaps", {}),
                      "coverage_complete": journal_outcomes.get("coverage_complete", False),
                      "journal_truncated": journal_outcomes.get("journal_truncated", False)}
    else:
        evaluation = {"status": "unknown", "network_calls": None,
                      "observed_calls": observer_calls}
    if not isinstance(status, dict):
        coverage_events.append("recorder_status_invalid")
        status = {}
    evidence_ids = _bounded_ids(status.get("evidence_ids"))
    alerts = status.get("alerts") if isinstance(status.get("alerts"), list) else []
    incidents = [{"kind": alert.get("kind"), "identity": alert.get("identity"),
                  "evidence_ids": evidence_ids} for alert in alerts if isinstance(alert, dict)]
    terminal_present = terminal is not None
    return {
        "schema_version": 1,
        "run_id": resolved_run_id,
        "source": {"commit": metadata.get("source_commit") or metadata.get("source_revision"),
                   "conversation_id": conversation_id, "log": log.name},
        "proven_terminal": terminal_present,
        "game_result": ({"winner": terminal.get("winner"), "reason": terminal.get("reason"),
                         "terminal_class": terminal.get("terminal_class"),
                         "code": terminal.get("code")} if terminal else None),
        "stage_progress": {"stage": status.get("stage"), "revision": status.get("revision"),
                           "last_completed_turn": status.get("last_completed_turn"),
                           "freshness": status.get("freshness")},
        "incidents": incidents,
        "stop_effect": {"requested": verdict.get("decision") == "stop" if verdict else False,
                        "effective": bool(terminal and terminal.get("terminal_class") == "observer_interrupted"),
                        "reason": verdict.get("reason_code") if verdict else None},
        "usage": usage,
        "model_evaluation": evaluation,
        "coverage": {"degraded": status.get("degraded"), "events": coverage_events,
                     "evidence_ids": evidence_ids,
                     "evidence_index": [{"evidence_id": item, "max_bytes": MAX_EVIDENCE_BYTES}
                                         for item in evidence_ids]},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--observer-state", type=Path,
                        help="persisted observer controller state (read-only)")
    parser.add_argument("--rate-file", type=Path,
                        help="dated per-model rate file for role costs")
    args = parser.parse_args(argv)
    packet = review(args.log, observer_state=args.observer_state, rate_file=args.rate_file)
    print(json.dumps(packet, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
