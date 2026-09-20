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
    from .game_history import import_game, open_history
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
    from game_history import import_game, open_history  # type: ignore


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
    first.
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
    report["record_count"] = len(records)
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
