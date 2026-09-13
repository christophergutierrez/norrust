"""Prepared Stack 4 strategy comparisons and the provider-free matrix.

This is an experiment/report layer over :mod:`tools.model_bakeoff`.  It does
not run a game, contact a provider, or invent a second history or cost store.
The three named strategy treatments are kept separate from bakeoff arms A/B/C:
``strategy_fixed`` (checked-in policy and no backend), ``strategy_glm`` (the
same routine executor with GLM decisions), and ``focused_glm`` (existing
focused mode with no routine).
"""
from __future__ import annotations

import copy
import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from . import bakeoff_metrics, match_report, model_bakeoff

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tools" / "fixtures" / "strategy_comparison"
PILOT_MANIFEST_PATH = FIXTURE_DIR / "pilot_manifest.json"
OFFLINE_MATRIX_PATH = FIXTURE_DIR / "offline_matrix.json"
FIXED_POLICY_PATH = FIXTURE_DIR / "strategy_fixed_policy.json"

STRATEGY_TREATMENTS = model_bakeoff.STRATEGY_TREATMENTS
PILOT_MODEL = "accounts/fireworks/models/glm-5p3-flash"
PILOT_SCENARIO = "big_battle_6"
PILOT_SEED = 2038
PILOT_MAX_TURNS = 6
PILOT_GOLD = 300
PILOT_PLAYER_SIDE = 0
PILOT_MAX_PLAYER_TOKENS = 200_000
PILOT_AGGREGATE_CEILING_USD = 1.0


class StrategyComparisonError(ValueError):
    """A strategy manifest or evidence row is malformed."""


def _backend_for(treatment: str) -> dict[str, Any]:
    if treatment == "strategy_fixed":
        return {"kind": "fixed_policy", "path": str(FIXED_POLICY_PATH.relative_to(REPO_ROOT))}
    return {
        "kind": "command",
        "command": f"python3 -m tools.fireworks_backend --stream --model {PILOT_MODEL}",
    }


def build_pilot_manifest(*, driver: str | None = None,
                         source_commit: str | None = None) -> dict[str, Any]:
    """Return the exact, prepared three-cell pilot schedule.

    The result intentionally has no resolved provenance or pricing: those are
    stamped immediately before an authorized launch after a read-only model
    availability and dated-rate check.  Keeping this function provider-free
    makes accidentally launching from a test impossible.
    """
    cells: list[dict[str, Any]] = []
    for treatment in STRATEGY_TREATMENTS:
        strategy = treatment.startswith("strategy_")
        cell: dict[str, Any] = {
            "id": f"strategy-opening-{treatment}",
            "strategy_treatment": treatment,
            "configuration": treatment,
            "scenario": PILOT_SCENARIO,
            "seed": PILOT_SEED,
            "faction0": "undead",
            "faction1": "undead",
            "llm_side": PILOT_PLAYER_SIDE,
            "gold": PILOT_GOLD,
            "max_turns": PILOT_MAX_TURNS,
            "model": PILOT_MODEL if treatment != "strategy_fixed" else "fixed-policy-code",
            "reasoning_effort": None,
            "decision_mode": "strategy" if strategy else "focused",
            "action_encoding": "coordinates",
            "incremental_turns": True,
            "strategy_policy": (str(FIXED_POLICY_PATH.relative_to(REPO_ROOT))
                                 if treatment == "strategy_fixed" else None),
            "backend": _backend_for(treatment),
            "budgets": {
                "max_game_total_tokens": PILOT_MAX_PLAYER_TOKENS,
                "model_timeout": 900,
                "turn_timeout": 2100,
                "query_budget_seconds": 300,
                "max_partial_batches_per_turn": 64,
            },
            "pilot_status": "prepared_not_run",
        }
        if driver is not None:
            cell["driver"] = driver
        if source_commit is not None:
            cell["prepared_source_commit"] = source_commit
        cells.append(cell)
    return {
        "schema_version": 1,
        "experiment_kind": "strategy_comparison",
        "status": "prepared_not_run",
        "objective": "Matched Stack 4 strategy opening treatments",
        "pilot_limits": {
            "scenario": PILOT_SCENARIO,
            "faction0": "undead", "faction1": "undead",
            "gold": PILOT_GOLD, "seed": PILOT_SEED,
            "llm_side": PILOT_PLAYER_SIDE, "opponent": "Greedy",
            "completed_engine_side_turns": PILOT_MAX_TURNS,
            "player_turns_for_glm_treatments": 3,
            "paid_cells_max": 2,
            "player_token_cap_per_paid_cell": PILOT_MAX_PLAYER_TOKENS,
            "model_call_timeout_seconds": 900,
            "controlled_turn_timeout_seconds": 2100,
            "query_budget_seconds": 300,
            "wall_deadline_seconds": 2700,
            "aggregate_estimated_ceiling_usd": PILOT_AGGREGATE_CEILING_USD,
            "in_flight_overshoot_allowed": True,
            "provider": "Fireworks",
            "model": PILOT_MODEL,
            "reasoning_effort": None,
            "temperature": "provider_default",
            "initial_output_tokens": 131072,
            "output_exhaustion_escalation": "existing_client_policy",
            "retries_or_rescue_games": False,
        },
        "pricing": {"status": "unknown_until_dated_read_only_check"},
        "cells": cells,
    }


def load_prepared_pilot(path: Path = PILOT_MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyComparisonError(f"cannot read pilot manifest {path}: {exc}") from exc
    if manifest.get("status") != "prepared_not_run":
        raise StrategyComparisonError("pilot manifest must remain prepared_not_run until launch authorization")
    return manifest


def validate_pilot_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate exact pilot identity and the maintained runner contract."""
    mismatches: list[dict[str, Any]] = []
    expected = build_pilot_manifest()
    cells = manifest.get("cells")
    if not isinstance(cells, list):
        return {"valid": False, "mismatches": [{"error": "cells must be a list"}]}
    if len(cells) != len(expected["cells"]):
        mismatches.append({"error": "pilot must contain exactly three treatment cells"})
    for actual, wanted in zip(cells, expected["cells"]):
        for key in ("id", "strategy_treatment", "scenario", "seed", "faction0", "faction1",
                    "llm_side", "gold", "max_turns", "model", "decision_mode",
                    "action_encoding", "incremental_turns", "budgets"):
            if actual.get(key) != wanted.get(key):
                mismatches.append({"cell": actual.get("id"), "field": key,
                                   "expected": wanted.get(key), "actual": actual.get(key)})
        if actual.get("backend") != wanted.get("backend"):
            mismatches.append({"cell": actual.get("id"), "field": "backend"})
    try:
        resolved = model_bakeoff.resolve_manifest(copy.deepcopy(manifest))
        comparison = model_bakeoff.check_comparison_validity(resolved)
    except (model_bakeoff.ManifestError, OSError, ValueError, TypeError) as exc:
        comparison = {"valid": False, "mismatches": [{"error": str(exc)}]}
    if not comparison.get("valid"):
        mismatches.extend(comparison.get("mismatches", []))
    return {"valid": not mismatches, "mismatches": mismatches,
            "comparison": comparison}


def event_source_counts(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Count actual executed events by their recorded source and kind.

    Proposals, forwarded orders, and snapshots are excluded.  A missing event
    source is retained under ``unknown`` instead of being attributed to the
    model or routine by position.
    """
    by_source: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_source_kind: dict[str, dict[str, int]] = {}
    total = 0
    for record in records:
        if record.get("type") != "driver" or not isinstance(record.get("line"), dict):
            continue
        line = record["line"]
        if line.get("type") != "events" or not isinstance(line.get("events"), list):
            continue
        for event in line["events"]:
            if not isinstance(event, dict):
                continue
            source = event.get("source") or line.get("source") or "unknown"
            kind = event.get("kind") or "unknown"
            by_source[source] = by_source.get(source, 0) + 1
            by_kind[kind] = by_kind.get(kind, 0) + 1
            by_source_kind.setdefault(source, {})[kind] = by_source_kind.setdefault(source, {}).get(kind, 0) + 1
            total += 1
    return {"actual_event_count": total, "events_by_source": by_source,
            "events_by_kind": by_kind, "events_by_source_and_kind": by_source_kind}


def archive_attribution(records: list[dict[str, Any]], *, synthetic: bool = False) -> dict[str, Any]:
    """Summarize source/count evidence from one archive without inference."""
    counts = event_source_counts(records)
    terminal = match_report.terminal_record(records)
    model_requests = sum(1 for item in records if item.get("type") in {"model", "model_request"})
    counts.update({
        "source_label": "synthetic_fixture" if synthetic else "recorded_archive",
        "synthetic": synthetic,
        "model_request_count": model_requests if terminal else None,
        "routine_event_count": counts["events_by_source"].get("routine", 0),
        "model_event_count": counts["events_by_source"].get("llm", 0),
        "delegated_event_count": counts["events_by_source"].get("delegated_greedy", 0),
        "evidence_status": "complete" if terminal else "unknown_truncated",
    })
    return counts


def build_offline_matrix_report(matrix: dict[str, Any] | None = None,
                                *, archives: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Report the four network-free cases, retaining Rust-dependent unknowns."""
    if matrix is None:
        try:
            matrix = json.loads(OFFLINE_MATRIX_PATH.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise StrategyComparisonError(f"cannot read offline matrix: {exc}") from exc
    cases = matrix.get("cases") if isinstance(matrix, dict) else None
    if not isinstance(cases, list) or not cases:
        raise StrategyComparisonError("offline matrix must contain cases")
    rows: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise StrategyComparisonError("offline matrix case needs a string id")
        records = (archives or {}).get(case["id"])
        row = {"case_id": case["id"], "description": case.get("description"),
               "required_engine": case.get("required_engine", True),
               "expected": copy.deepcopy(case.get("expected", {})),
               "status": "unknown_unrun", "attribution": None}
        if records is not None:
            row["status"] = "observed"
            row["attribution"] = archive_attribution(records, synthetic=True)
        else:
            row["blocked_reason"] = case.get("blocked_reason", "Rust Stack 3/4 driver fixture pending")
        rows.append(row)
    return {"schema_version": 1, "matrix_status": "partial_pending_rust" if any(
        row["status"] != "observed" for row in rows) else "observed",
        "cases": rows,
        "denominator": {"scheduled": len(rows),
                        "observed": sum(row["status"] == "observed" for row in rows),
                        "unknown_unrun": sum(row["status"] != "observed" for row in rows)},
        "note": "Unknown/unrun cases remain explicit; synthetic attribution is labelled and does not establish gameplay quality."}


def build_strategy_report(manifest: dict[str, Any] | None = None,
                          results: list[model_bakeoff.CellRunResult] | None = None,
                          *, catalog_path: Path | None = None,
                          cohort_id: str | None = None) -> dict[str, Any]:
    """Build a strategy report through the maintained bakeoff aggregator."""
    manifest = copy.deepcopy(manifest or load_prepared_pilot())
    if not all(isinstance((cell.get("provenance") if isinstance(cell, dict) else None), dict)
               for cell in manifest.get("cells", [])):
        manifest = model_bakeoff.resolve_manifest(manifest)
    check = validate_pilot_manifest(manifest)
    if not check["valid"]:
        raise StrategyComparisonError(f"invalid strategy manifest: {check['mismatches']}")
    report = model_bakeoff.build_report(manifest, results or [], catalog_path=catalog_path,
                                        cohort_id=cohort_id)
    result_by_id = {result.cell_id: result for result in (results or [])}
    for entry, cell in zip(report["cells"], manifest["cells"]):
        treatment = cell.get("strategy_treatment") or cell.get("treatment")
        entry["strategy_treatment"] = treatment
        entry["controller"] = ("fixed_policy_code" if treatment == "strategy_fixed" else
                                "model" if treatment in ("strategy_glm", "focused_glm") else "unknown")
        if entry.get("status") == "not_run":
            entry["evidence_status"] = "unknown_unrun"
            entry["source_attribution"] = None
        else:
            result = result_by_id.get(entry["cell_id"])
            if result is None or not result.log_path.is_file():
                entry["evidence_status"] = "unknown_unimported"
                entry["source_attribution"] = None
            else:
                records = match_report.load_records(result.log_path)
                entry["evidence_status"] = "recorded_archive"
                entry["source_attribution"] = archive_attribution(records)
                if catalog_path is not None:
                    game_id = f"{cohort_id}:{entry['cell_id']}" if cohort_id else entry["cell_id"]
                    try:
                        import sqlite3
                        conn = sqlite3.connect(f"file:{catalog_path}?mode=ro", uri=True)
                        try:
                            counts = {}
                            for table in ("events", "actions", "model_calls"):
                                counts[table] = conn.execute(
                                    f"SELECT count(*) FROM {table} WHERE game_id=?", (game_id,)
                                ).fetchone()[0]
                        finally:
                            conn.close()
                        entry["source_attribution"]["catalog_counts"] = counts
                    except (OSError, ValueError, sqlite3.Error):
                        entry["source_attribution"]["catalog_counts"] = "unknown_catalog_error"
    report["strategy_treatments"] = list(STRATEGY_TREATMENTS)
    report["pilot_status"] = manifest.get("status", "prepared_not_run")
    report["pilot_limits"] = copy.deepcopy(manifest.get("pilot_limits", {}))
    report["bakeoff"] = None  # A/B/C comparison never includes named strategy cells.
    report["note"] += " Named strategy treatments are separate from A/B/C; missing logs, calls, costs and predicates remain unknown."
    return report


def main(argv: list[str] | None = None) -> int:
    """Prepare or print reports; this CLI has no run/launch operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pilot = sub.add_parser("pilot-manifest", help="write the prepared pilot manifest")
    pilot.add_argument("--out", required=True)
    report = sub.add_parser("pilot-report", help="write an unrun/unknown pilot report")
    report.add_argument("--manifest", default=str(PILOT_MANIFEST_PATH))
    report.add_argument("--out", required=True)
    matrix = sub.add_parser("offline-report", help="write the provider-free matrix report")
    matrix.add_argument("--matrix", default=str(OFFLINE_MATRIX_PATH))
    matrix.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "pilot-manifest":
        payload = load_prepared_pilot() if Path(args.out).resolve() == PILOT_MANIFEST_PATH.resolve() else build_pilot_manifest()
    elif args.command == "pilot-report":
        payload = build_strategy_report(json.loads(Path(args.manifest).read_text()))
    else:
        payload = build_offline_matrix_report(json.loads(Path(args.matrix).read_text()))
    Path(args.out).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
