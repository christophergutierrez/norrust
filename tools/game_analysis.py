#!/usr/bin/env python3
"""CLI for inspecting and importing optional per-decision analysis sidecars.

This module reads the evidence written by `tools/analysis_capture.py` (the
`<logstem>.analysis/` sidecar: `manifest.json` + `analysis.ndjson`) and the
field names, enums, and lifecycle rules come from `tmp/analysis-exec/CONTRACT.md`.
It implements that contract and must not redesign it independently.

Stack 1 (this module, this stage) provides three subcommands:

- `validate` checks a sidecar's internal consistency without touching the
  catalog: manifest readability, record sequencing, reference hashes, and the
  final `capture_status` marker.
- `report` produces the coverage/boundary report -- never launching a model
  or a simulation -- distinguishing the different reasons a report might have
  less than complete evidence (`COVERAGE_STATUSES`).
- `import` imports the underlying match archive into the existing
  `tools.game_history` catalog and cross-checks the analysis sidecar's
  references against it. It does not invent new tables: `game_history` has
  no notion of `decision_id`/`turn_boundary` records, so those stay sidecar
  evidence surfaced by `report`, not new catalog rows.

`evaluate` (a later stack) is stubbed here to fail loudly rather than silently
do nothing.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional

try:
    from .analysis_capture import (
        ANALYSIS_MANIFEST_NAME,
        ANALYSIS_RECORDS_NAME,
        ANALYSIS_SCHEMA_VERSION,
        COVERAGE_STATUSES,
        ReadResult,
        analysis_dir_for_log,
        read_records,
        validate_records,
    )
    from .game_history import _read_usage_sidecar, import_game, open_history
    from .model_usage import dedupe_calls
except ImportError:  # pragma: no cover - direct script compatibility
    from analysis_capture import (  # type: ignore
        ANALYSIS_MANIFEST_NAME,
        ANALYSIS_RECORDS_NAME,
        ANALYSIS_SCHEMA_VERSION,
        COVERAGE_STATUSES,
        ReadResult,
        analysis_dir_for_log,
        read_records,
        validate_records,
    )
    from game_history import _read_usage_sidecar, import_game, open_history  # type: ignore
    from model_usage import dedupe_calls  # type: ignore


def resolve_log_path(archive: str | Path) -> Path:
    """Resolve the main match-log path for an `--archive` argument.

    Mirrors `tools.game_history.import_game`'s own resolution exactly (a
    file is used as-is, a directory is assumed to hold `match.ndjson`) so
    `--archive` means the same thing here as it does to the importer, and
    `analysis_dir_for_log` locates the same sidecar the writer created.
    """
    root = Path(archive).resolve()
    return root if root.is_file() else root / "match.ndjson"


def _load_manifest(analysis_dir: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    manifest_path = analysis_dir / ANALYSIS_MANIFEST_NAME
    if not manifest_path.is_file():
        return None, f"missing {ANALYSIS_MANIFEST_NAME}"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"unreadable {ANALYSIS_MANIFEST_NAME}: {exc}"
    if not isinstance(manifest, dict):
        return None, f"{ANALYSIS_MANIFEST_NAME} is not a JSON object"
    version = manifest.get("analysis_schema_version")
    if version != ANALYSIS_SCHEMA_VERSION:
        return manifest, f"unsupported analysis_schema_version {version!r}"
    return manifest, None


def _resolve_ref_path(analysis_dir: Path, ref: dict[str, Any]) -> tuple[Optional[Path], Optional[str]]:
    """Resolve one `refs` entry's path, honoring the frozen archive-root rule.

    A reference is only trustworthy if it resolves inside the archive root
    (the analysis directory's parent), exactly as `make_reference` enforces
    at write time. This re-checks it at read time too, since a hand-edited
    or corrupted record could name a path anywhere.
    """
    raw_path = ref.get("path")
    if not isinstance(raw_path, str):
        return None, "reference has no path"
    target = (analysis_dir / raw_path).resolve()
    archive_root = analysis_dir.parent
    try:
        target.relative_to(archive_root)
    except ValueError:
        return None, f"reference path {raw_path!r} escapes archive root {archive_root}"
    return target, None


def _hash_check_refs(analysis_dir: Path, records: list[dict[str, Any]]) -> list[str]:
    """Re-hash every `refs` entry across every record; report every mismatch.

    A mismatch is a CONFLICT per the contract -- never silently resolved by
    picking one side -- so every problem found is returned, not just the
    first.  A reference with `byte_offset`/`byte_length` names a byte RANGE
    of its artifact (deviation 002): the hash and size describe exactly those
    bytes, so a reader can verify one game-log line without trusting the
    rest of the file.
    """
    problems: list[str] = []
    for record in records:
        sequence = record.get("sequence")
        for ref in record.get("refs") or []:
            if not isinstance(ref, dict):
                problems.append(f"sequence {sequence}: reference is not an object")
                continue
            target, error = _resolve_ref_path(analysis_dir, ref)
            if error:
                problems.append(f"sequence {sequence}: {error}")
                continue
            try:
                if ref.get("byte_offset") is not None or ref.get("byte_length") is not None:
                    offset = ref.get("byte_offset")
                    length = ref.get("byte_length")
                    if not isinstance(offset, int) or not isinstance(length, int) or offset < 0 or length <= 0:
                        problems.append(f"sequence {sequence}: reference {ref.get('path')!r} "
                                        "has an invalid byte range")
                        continue
                    with target.open("rb") as stream:
                        stream.seek(offset)
                        payload = stream.read(length)
                    if len(payload) != length:
                        problems.append(
                            f"sequence {sequence}: reference {ref.get('path')!r} range "
                            f"[{offset}, {offset + length}) exceeds the file size")
                        continue
                else:
                    payload = target.read_bytes()
            except OSError as exc:
                problems.append(f"sequence {sequence}: reference {ref.get('path')!r} unreadable: {exc}")
                continue
            actual_hash = hashlib.sha256(payload).hexdigest()
            if actual_hash != ref.get("sha256"):
                problems.append(
                    f"sequence {sequence}: reference {ref.get('path')!r} hash mismatch "
                    f"(expected {ref.get('sha256')}, got {actual_hash})")
                continue
            if len(payload) != ref.get("bytes"):
                problems.append(
                    f"sequence {sequence}: reference {ref.get('path')!r} size mismatch "
                    f"(expected {ref.get('bytes')}, got {len(payload)})")
    return problems


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def run_validate(archive: str | Path) -> tuple[int, list[str]]:
    log_path = resolve_log_path(archive)
    analysis_dir = analysis_dir_for_log(log_path)
    lines: list[str] = []
    if not analysis_dir.is_dir():
        return 1, [f"no analysis directory at {analysis_dir}; capture was disabled for this archive"]

    manifest, manifest_error = _load_manifest(analysis_dir)
    if manifest_error:
        lines.append(f"manifest problem: {manifest_error}")

    records_path = analysis_dir / ANALYSIS_RECORDS_NAME
    if not records_path.is_file():
        lines.append(f"missing {ANALYSIS_RECORDS_NAME}")
        return 1, lines

    read_result = read_records(analysis_dir)
    for warning in read_result.warnings:
        if warning.partial:
            lines.append(f"partial (truncated) final record at byte {warning.byte_offset}: {warning.message}")
        else:
            lines.append(f"corrupt interior record at byte {warning.byte_offset}: {warning.message}")

    validation = validate_records(read_result.records)
    lines.extend(f"validation error: {error}" for error in validation.errors)
    for conflict in validation.conflicts:
        lines.append(
            f"request_id {conflict.request_id} conflict across sequences "
            f"{conflict.sequences}: {conflict.reason}")

    ref_problems = _hash_check_refs(analysis_dir, read_result.records)
    lines.extend(ref_problems)

    if not read_result.has_final_marker:
        lines.append("capture incomplete (process did not finish): no final capture_status record")

    ok = (
        manifest_error is None
        and not read_result.warnings
        and validation.ok
        and not validation.conflicts
        and not ref_problems
        and read_result.has_final_marker
    )
    if ok:
        lines.insert(0, f"OK: {len(read_result.records)} records, all references verified, capture complete")
        return 0, lines
    lines.insert(0, f"FAILED: {analysis_dir}")
    return 1, lines


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def determine_coverage(analysis_dir: Path) -> tuple[str, dict[str, Any], Optional[ReadResult], Optional[dict[str, Any]]]:
    """Classify capture coverage into one of `COVERAGE_STATUSES`.

    The five statuses are genuinely different conditions and must not
    collapse into one "no data" message:
    - `capture_disabled`: no `.analysis` directory at all (capture was off).
    - `unsupported_analysis`: a directory exists but the manifest is
      missing/unreadable, or names a schema version this tool doesn't know.
    - `empty_result`: readable records, but nothing beyond the start/stop
      bookends -- capture ran but the game produced no decision evidence.
    - `capture_stopped`: capture began but did not finish cleanly, whether
      because the final marker is altogether missing (crash) or it is
      present with a non-"complete" outcome (byte cap / write error).
    - `complete`: a full, well-formed capture.
    """
    if not analysis_dir.is_dir():
        return "capture_disabled", {"reason": "no analysis directory"}, None, None

    manifest, manifest_error = _load_manifest(analysis_dir)
    if manifest_error:
        return "unsupported_analysis", {"reason": manifest_error}, None, manifest

    records_path = analysis_dir / ANALYSIS_RECORDS_NAME
    if not records_path.is_file():
        return "empty_result", {"reason": f"no {ANALYSIS_RECORDS_NAME}"}, None, manifest

    read_result = read_records(analysis_dir)
    if not read_result.records:
        return "empty_result", {"reason": "no records"}, read_result, manifest

    if not read_result.has_final_marker:
        return "capture_stopped", {"reason": "crashed: no final capture_status marker"}, read_result, manifest

    final = next(r for r in read_result.records if r.get("kind") == "capture_status")
    outcome = (final.get("body") or {}).get("outcome")
    if outcome != "complete":
        return "capture_stopped", {"reason": f"stopped: {outcome}"}, read_result, manifest

    # Only the capture_started/capture_status bookends: capture ran but
    # never observed a single decision, request, batch, or turn boundary.
    if len(read_result.records) <= 2:
        return "empty_result", {"reason": "no decision evidence captured"}, read_result, manifest

    return "complete", {}, read_result, manifest


def summarize_turns(records: list[dict[str, Any]]) -> dict[str, Any]:
    started: dict[Optional[str], dict[str, Any]] = {}
    started_count = 0
    finished_count = 0
    terminal_partial_turns: list[Optional[str]] = []
    for record in records:
        kind = record.get("kind")
        if kind == "turn_boundary":
            side_turn_id = record.get("side_turn_id")
            phase = (record.get("body") or {}).get("phase")
            if phase == "started":
                started_count += 1
                started[side_turn_id] = record
            elif phase == "finished":
                finished_count += 1
                started.pop(side_turn_id, None)
        elif kind == "game_terminal":
            for side_turn_id in started:
                terminal_partial_turns.append(side_turn_id)
    return {
        "turns_started": started_count,
        "turns_finished": finished_count,
        "open_turns_at_end": sorted((t for t in started if t is not None)),
        "terminal_partial_turns": sorted(set(t for t in terminal_partial_turns if t is not None)),
        "note": "a started turn is not a completed turn; a game_terminal while a turn "
                "is still open is reported as a terminal partial turn, not a completed one",
    }


def summarize_identities(records: list[dict[str, Any]]) -> dict[str, Any]:
    decision_ids = {r.get("decision_id") for r in records if r.get("decision_id") is not None}
    side_turn_ids = {r.get("side_turn_id") for r in records if r.get("side_turn_id") is not None}
    request_ids = {r.get("request_id") for r in records if r.get("request_id") is not None}
    batch_ids = {r.get("batch_id") for r in records if r.get("batch_id") is not None}
    validation = validate_records(records)
    return {
        "decision_count": len(decision_ids),
        "side_turn_count": len(side_turn_ids),
        "request_count": len(request_ids),
        "batch_count": len(batch_ids),
        "request_identity_conflicts": [
            {"request_id": c.request_id, "sequences": c.sequences, "reason": c.reason}
            for c in validation.conflicts
        ],
    }


def summarize_evidence(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = collections.Counter(r.get("evidence_status") for r in records)
    return {str(status): count for status, count in sorted(counts.items(), key=lambda kv: str(kv[0]))}


def summarize_decisions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """One line per decision: what was offered, selected, repaired, executed.

    This is the stack-2 deliverable in report form -- a user can see what the
    player was offered, what it selected, what failed, and what actually
    executed, including repair attempts.  Counts stay honest: a rejected
    order contributes no committed-action count, and a routine submission is
    listed as engine-selected rather than misattributed to a model decision.
    """
    decisions: dict[str, dict[str, Any]] = {}
    for record in records:
        decision_id = record.get("decision_id")
        if not isinstance(decision_id, str):
            continue
        entry = decisions.setdefault(decision_id, {
            "decision_id": decision_id,
            "side_turn_id": record.get("side_turn_id"),
            "stage": None,
            "client_decision_id": None,
            "requests": 0,
            "candidates_offered": None,
            "candidates_truncated": None,
            "candidate_filtering": None,
            "candidate_omission": None,
            "selection": None,
            "selection_source": None,
            "custom_orders": False,
            "repairs": 0,
            "validations_rejected": 0,
            "committed_batches": [],
            "finish_kinds": set(),
        })
        kind = record.get("kind")
        body = record.get("body") or {}
        if kind == "decision_start":
            entry["stage"] = body.get("stage")
            entry["client_decision_id"] = body.get("client_decision_id")
        elif kind == "model_request":
            entry["requests"] += 1
        elif kind == "candidate_packet":
            packet = body.get("packet") if isinstance(body.get("packet"), dict) else {}
            options = packet.get("options")
            if isinstance(options, list):
                entry["candidates_offered"] = len(options)
            coverage = packet.get("coverage") if isinstance(packet.get("coverage"), dict) else {}
            entry["candidates_truncated"] = bool(coverage.get("options_truncated"))
            # Omission, filtering and display truncation are three different
            # things and must stay distinguishable.  The generator reports
            # whether the shown list was truncated, but it does not report why
            # a legal action was never generated, nor a per-candidate filter
            # reason.  That absence is recorded as unreported -- never as
            # "nothing was filtered" -- because the shown set is not evidence
            # of the complete legal set.  Establishing what was legally
            # available but absent requires offline enumeration from a
            # restored state, which is stack 3 work, not a guess made here.
            reasons = coverage.get("filter_reasons")
            entry["candidate_filtering"] = (
                "reported" if isinstance(reasons, (list, dict)) and reasons else "unreported")
            entry["candidate_omission"] = "unknown_without_offline_enumeration"
        elif kind == "execution_submit":
            if body.get("option_ids"):
                entry["selection"] = list(body.get("option_ids"))
                entry["selection_source"] = body.get("proposal_source") or "engine_option"
            elif body.get("orders"):
                entry["custom_orders"] = True
                entry["selection_source"] = body.get("source") or "custom"
        elif kind == "response_repair":
            entry["repairs"] += 1
        elif kind == "batch_validation" and body.get("valid") is False:
            entry["validations_rejected"] += 1
        elif kind == "action_commit":
            entry["committed_batches"].append(record.get("batch_id"))
        elif kind == "turn_boundary" and body.get("phase") == "finished":
            for key in ("authored_finish_kind", "executed_finish_kind"):
                if body.get(key):
                    entry["finish_kinds"].add(f"{key}={body.get(key)}")
    for entry in decisions.values():
        entry["committed_batches"] = sorted(b for b in entry["committed_batches"] if b)
        entry["finish_kinds"] = sorted(entry["finish_kinds"])
    return {"count": len(decisions), "items": list(decisions.values())}


def summarize_usage(log_path: Path) -> dict[str, Any]:
    """Summarize the authoritative physical usage receipts beside the log.

    Token accounting definitions are stated explicitly, and absent values
    stay unknown rather than becoming zero: a receipt without reasoning
    tokens says reasoning is unreported, and a missing cache field says
    cached input is unknown.  `total_tokens` is provider-reported and is
    never recomputed from components.
    """
    sidecar = log_path.parent / "usage.ndjson"
    if not sidecar.is_file():
        return {"status": "missing",
                "note": "no physical usage sidecar beside the log; usage is unknown, not zero"}
    try:
        from .game_history import _read_usage_sidecar
        from .model_usage import dedupe_calls
    except ImportError:  # pragma: no cover - direct script compatibility
        from game_history import _read_usage_sidecar  # type: ignore
        from model_usage import dedupe_calls  # type: ignore
    records, malformed = _read_usage_sidecar(sidecar)
    calls, conflicts = dedupe_calls(records)
    known_total = 0
    unknown_calls = 0
    reasoning_reported = 0
    cached_reported = 0
    for call in calls:
        total = call.total_tokens
        if isinstance(total, int) and not call.normalization_gaps:
            known_total += total
        else:
            unknown_calls += 1
        if isinstance(call.reasoning_tokens, int):
            reasoning_reported += 1
        if isinstance(call.cached_input_tokens, int):
            cached_reported += 1
    return {
        "status": "observed",
        "physical_calls": len(calls),
        "malformed_rows": len(malformed),
        "conflicting_identities": len(conflicts),
        "known_total_tokens": known_total,
        "unknown_total_calls": unknown_calls,
        "reasoning_reported_calls": reasoning_reported,
        "cached_input_reported_calls": cached_reported,
        "definitions": {
            "total_tokens": "provider-reported; never recomputed as input+cached+output+reasoning",
            "reasoning": "reasoning_tokens reported by the adapter; absent means unknown, not zero",
            "cached_input": "cached_input_tokens reported by the adapter; absent means unknown, not zero",
            "unknown_total_calls": "calls whose total could not be measured; excluded from known_total_tokens",
        },
    }


def summarize_timings(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize measured stage timings; unmeasured stages stay unknown."""
    spans: dict[str, list[int]] = collections.defaultdict(list)
    unavailable: collections.Counter = collections.Counter()
    requests = 0
    for record in records:
        if record.get("kind") != "stage_timing":
            continue
        requests += 1
        body = record.get("body") or {}
        for name, value in (body.get("spans") or {}).items():
            if isinstance(value, int):
                spans[name].append(value)
        for name in body.get("unavailable") or []:
            unavailable[name] += 1
    def stats(values: list[int]) -> dict[str, int]:
        ordered = sorted(values)
        return {"count": len(ordered), "median_ms": ordered[len(ordered) // 2],
                "max_ms": ordered[-1]}
    return {
        "requests_with_timings": requests,
        "spans": {name: stats(values) for name, values in sorted(spans.items())},
        "unavailable_span_counts": dict(unavailable),
        "clock": "time.monotonic",
        "note": "spans are non-overlapping; an absent span is unknown, never zero",
    }


def build_report(archive: str | Path) -> dict[str, Any]:
    log_path = resolve_log_path(archive)
    analysis_dir = analysis_dir_for_log(log_path)
    status, detail, read_result, manifest = determine_coverage(analysis_dir)

    report: dict[str, Any] = {
        "archive": str(log_path),
        "analysis_dir": str(analysis_dir),
        "coverage_status": status,
        "coverage_detail": detail,
    }
    records = read_result.records if read_result is not None else []
    ref_problems = _hash_check_refs(analysis_dir, records) if analysis_dir.is_dir() else []
    report["reference_conflicts"] = ref_problems
    report["turns"] = summarize_turns(records)
    report["identities"] = summarize_identities(records)
    report["evidence"] = summarize_evidence(records)
    report["decisions"] = summarize_decisions(records)
    report["usage"] = summarize_usage(log_path)
    report["timings"] = summarize_timings(records)
    report["record_count"] = len(records)
    # Manifest fields left null on purpose, each with its reason.  Surfacing
    # these keeps a known limit from reading as missing evidence: a null
    # scenario hash because capture may not query the driver is a different
    # thing from a hash that should have been recorded and was not.
    report["provenance_gaps"] = (manifest or {}).get("provenance_gaps") or {}
    return report


def format_report_text(report: dict[str, Any]) -> str:
    lines = [
        f"archive:          {report['archive']}",
        f"analysis dir:     {report['analysis_dir']}",
        f"coverage status:  {report['coverage_status']}",
    ]
    if report["coverage_detail"]:
        lines.append(f"  detail:         {report['coverage_detail']}")
    lines.append(f"records:          {report['record_count']}")
    turns = report["turns"]
    lines.append(f"turn boundaries:  {turns['turns_started']} started, {turns['turns_finished']} finished")
    if turns["open_turns_at_end"]:
        lines.append(f"  open at end:    {turns['open_turns_at_end']}")
    if turns["terminal_partial_turns"]:
        lines.append(f"  TERMINAL PARTIAL TURNS: {turns['terminal_partial_turns']}")
    identities = report["identities"]
    lines.append(
        f"identities:       {identities['decision_count']} decisions, "
        f"{identities['side_turn_count']} side turns, {identities['request_count']} requests, "
        f"{identities['batch_count']} batches")
    if identities["request_identity_conflicts"]:
        lines.append(f"  CONFLICTS:      {identities['request_identity_conflicts']}")
    lines.append(f"evidence status:  {report['evidence']}")
    gaps = report.get("provenance_gaps") or {}
    if gaps:
        lines.append(f"provenance gaps:  {len(gaps)} manifest field(s) null by design")
        for field_name in sorted(gaps):
            lines.append(f"  {field_name}: {gaps[field_name]}")
    decisions = report.get("decisions") or {}
    if decisions.get("count"):
        lines.append(f"decisions:        {decisions['count']}")
        for item in decisions.get("items") or []:
            offered = (f"{item['candidates_offered']} options"
                       if item["candidates_offered"] is not None else "no packet")
            if item.get("candidates_truncated"):
                offered += " (display truncated)"
            if item.get("candidate_filtering") == "unreported":
                offered += ", filtering unreported"
            selected = (f"selected {item['selection']}"
                        if item["selection"] else
                        ("custom orders" if item["custom_orders"] else "no selection captured"))
            suffix = ""
            if item["repairs"]:
                suffix += f", {item['repairs']} repairs"
            if item["validations_rejected"]:
                suffix += f", {item['validations_rejected']} rejected validations"
            if item["committed_batches"]:
                suffix += f", committed {', '.join(item['committed_batches'])}"
            else:
                suffix += ", nothing committed"
            lines.append(f"  {item['decision_id']}: {item['stage']}, {offered}, "
                         f"{selected}{suffix}")
    usage = report.get("usage") or {}
    if usage.get("status") == "observed":
        lines.append(f"usage:             {usage['physical_calls']} physical calls, "
                     f"{usage['known_total_tokens']} known total tokens "
                     f"({usage['unknown_total_calls']} unknown)")
        lines.append("  definitions:     total is provider-reported and never recomputed; "
                     "absent reasoning/cache values are unknown, not zero")
    else:
        lines.append("usage:             unknown (no physical usage sidecar)")
    timings = report.get("timings") or {}
    if timings.get("requests_with_timings"):
        span_text = ", ".join(f"{name} median {data['median_ms']}ms"
                              for name, data in (timings.get("spans") or {}).items())
        lines.append(f"stage timings:     {timings['requests_with_timings']} requests; {span_text}")
    if report["reference_conflicts"]:
        lines.append(f"REFERENCE CONFLICTS: {report['reference_conflicts']}")
    return "\n".join(lines)


def run_report(archive: str | Path, as_json: bool) -> int:
    report = build_report(archive)
    if as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(format_report_text(report))
    return 0


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

def run_import(db_path: str | Path, archive: str | Path) -> tuple[int, dict[str, Any]]:
    log_path = resolve_log_path(archive)
    analysis_dir = analysis_dir_for_log(log_path)

    warnings: list[str] = []
    ref_conflicts: list[str] = []
    request_conflicts: list[dict[str, Any]] = []
    analysis_present = analysis_dir.is_dir()

    if analysis_present:
        manifest, manifest_error = _load_manifest(analysis_dir)
        if manifest_error:
            warnings.append(f"manifest problem: {manifest_error}")
        records_path = analysis_dir / ANALYSIS_RECORDS_NAME
        if records_path.is_file():
            read_result = read_records(analysis_dir)
            for warning in read_result.warnings:
                if warning.partial:
                    warnings.append(
                        f"partial import: truncated final record at byte {warning.byte_offset} "
                        f"({warning.message}); prior records retained")
                else:
                    warnings.append(
                        f"corrupt interior record at byte {warning.byte_offset}: {warning.message}")
            validation = validate_records(read_result.records)
            for conflict in validation.conflicts:
                request_conflicts.append({
                    "request_id": conflict.request_id,
                    "sequences": conflict.sequences,
                    "reason": conflict.reason,
                })
            ref_conflicts = _hash_check_refs(analysis_dir, read_result.records)
            if not read_result.has_final_marker:
                warnings.append("capture incomplete: no final capture_status record")
            if manifest:
                resume = manifest.get("resume") or {}
                parent_game_id = resume.get("parent_game_id")
                if parent_game_id:
                    conn_check = open_history(db_path, read_only=False)
                    try:
                        row = conn_check.execute(
                            "SELECT 1 FROM games WHERE game_id=?", (parent_game_id,)).fetchone()
                    finally:
                        conn_check.close()
                    if row is None:
                        warnings.append(
                            f"manifest names parent_game_id {parent_game_id!r} which is not in the catalog")
        else:
            warnings.append(f"analysis directory present but missing {ANALYSIS_RECORDS_NAME}")
    else:
        warnings.append(f"no analysis directory at {analysis_dir}; importing game evidence only")

    conn = open_history(db_path)
    try:
        game_id = import_game(conn, archive)
    finally:
        conn.close()

    result = {
        "game_id": game_id,
        "analysis_capture_present": analysis_present,
        "warnings": warnings,
        "reference_conflicts": ref_conflicts,
        "request_identity_conflicts": request_conflicts,
    }
    exit_code = 1 if ref_conflicts else 0
    return exit_code, result


# ---------------------------------------------------------------------------
# evaluate (stub -- a later stack)
# ---------------------------------------------------------------------------

def run_evaluate(_args: argparse.Namespace) -> int:
    print(
        "game_analysis evaluate: not implemented in this stack (stack 1 is "
        "validate/report/import only); see tmp/analysis-exec/CONTRACT.md",
        file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="game_analysis")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="validate an analysis sidecar without touching the catalog")
    validate_parser.add_argument("--archive", required=True)

    report_parser = sub.add_parser("report", help="coverage/boundary report for an analysis sidecar")
    report_parser.add_argument("--archive", required=True)
    report_parser.add_argument("--json", action="store_true")

    import_parser = sub.add_parser("import", help="import the archive into the catalog and cross-check the sidecar")
    import_parser.add_argument("--db", required=True)
    import_parser.add_argument("--archive", required=True)

    evaluate_parser = sub.add_parser("evaluate", help="not implemented in stack 1")
    evaluate_parser.add_argument("--archive", required=False)
    evaluate_parser.add_argument("--db", required=False)

    args = parser.parse_args(argv)

    if args.command == "validate":
        exit_code, lines = run_validate(args.archive)
        print("\n".join(lines))
        return exit_code
    if args.command == "report":
        return run_report(args.archive, args.json)
    if args.command == "import":
        exit_code, result = run_import(args.db, args.archive)
        print(json.dumps(result, sort_keys=True))
        return exit_code
    return run_evaluate(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
