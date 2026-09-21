"""Provider-free plumbing for the three-way strategy experiment.

This module prepares and audits the experiment; it does not contact a model.
The treatments are deliberately explicit because equal candidate/search
budgets are required for a useful comparison.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

TREATMENTS = ("current_player", "search_only", "llm_search")
SCHEMA_VERSION = 1


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_manifest(*, scenarios: Iterable[str] = ("big_battle_6",),
                   seeds: Iterable[int] = (1,), sides: Iterable[int] = (0, 1),
                   max_turns: int = 6, driver: str | None = None) -> dict[str, Any]:
    """Build a fully scheduled, provider-free-capable experiment manifest."""
    candidate_config = {
        "generator": "bounded_candidates_v1",
        "max_candidates": 16,
        "seed_count": 16,
        "opponent_responses": 1,
        "continuation_policy": "driver_delegated_greedy_sweep_v1",
    }
    cells: list[dict[str, Any]] = []
    for scenario in scenarios:
        for seed in seeds:
            for side in sides:
                for treatment in TREATMENTS:
                    cell = {
                        "id": f"{treatment}-{scenario}-seed{seed}-side{side}",
                        "treatment": treatment, "scenario": scenario,
                        "seed": int(seed), "controlled_side": int(side),
                        "max_turns": max_turns,
                        "status": "scheduled",
                        "backend": ("existing_current_player" if treatment == "current_player"
                                     else "deterministic_search" if treatment == "search_only"
                                     else "llm_candidate_selector"),
                        "candidate_config": candidate_config,
                        "provider_allowed": False,
                        "driver": driver,
                        "limits": {
                            "max_candidates": 16, "evaluation_seeds": 16,
                            "opponent_responses": 1, "wall_seconds_per_decision": 120,
                        },
                    }
                    cell["treatment_fingerprint"] = _fingerprint({
                        "treatment": treatment, "candidate_config": candidate_config,
                        "limits": cell["limits"], "backend": cell["backend"],
                    })
                    cells.append(cell)
    return {
        "schema_version": SCHEMA_VERSION,
        "experiment_kind": "three_way_strategy_comparison",
        "status": "prepared_not_run",
        "treatments": list(TREATMENTS),
        "candidate_config": candidate_config,
        "cells": cells,
        "provenance": {"source_commit": None, "driver_hash": None, "opponent": "greedy"},
        "notes": [
            "Search-only and LLM-plus-search must receive the identical candidate IDs, order, outcomes, and limits.",
            "This manifest does not authorize provider contact or paid games.",
            "A scheduled, failed, or unrun cell remains in the denominator and is not an in-game loss.",
        ],
    }


def validate_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported schema_version")
    if tuple(manifest.get("treatments") or ()) != TREATMENTS:
        errors.append("treatments must be current_player, search_only, llm_search")
    cells = manifest.get("cells")
    if not isinstance(cells, list) or not cells:
        errors.append("cells must be non-empty")
        cells = []
    ids: set[str] = set()
    for cell in cells:
        if not isinstance(cell, Mapping):
            errors.append("cell is not an object")
            continue
        cell_id = cell.get("id")
        if not isinstance(cell_id, str) or not cell_id:
            errors.append("cell has no id")
        elif cell_id in ids:
            errors.append(f"duplicate cell id: {cell_id}")
        ids.add(cell_id)
        if cell.get("treatment") not in TREATMENTS:
            errors.append(f"invalid treatment in {cell_id}")
        if cell.get("provider_allowed") is not False:
            errors.append(f"provider contact is not disabled in {cell_id}")
        limits = cell.get("limits") or {}
        if limits.get("max_candidates") != 16 or limits.get("evaluation_seeds") != 16:
            errors.append(f"unmatched bounded-evaluation limits in {cell_id}")
        if not isinstance(cell.get("treatment_fingerprint"), str):
            errors.append(f"missing treatment fingerprint in {cell_id}")
    return {"valid": not errors, "errors": errors,
            "scheduled": len(cells), "treatment_counts": {
                treatment: sum(c.get("treatment") == treatment for c in cells if isinstance(c, Mapping))
                for treatment in TREATMENTS}}


def select_search_candidate(candidates: list[Mapping[str, Any]]) -> str | None:
    """Deterministic search-only selector using precomputed mean scores."""
    eligible = [c for c in candidates if c.get("legal") is True and isinstance(c.get("mean_score"), (int, float))]
    if not eligible:
        return None
    return max(eligible, key=lambda c: (float(c["mean_score"]), -int(c.get("index", 0)))).get("candidate_id")


def select_llm_candidate(candidate_ids: Iterable[str], selected_id: str | None,
                         *, fallback_id: str | None = None) -> dict[str, Any]:
    """Validate a model-selected ID without giving it unrestricted orders."""
    allowed = list(candidate_ids)
    if selected_id in allowed:
        return {"selected_id": selected_id, "valid": True, "fallback_used": False}
    return {"selected_id": fallback_id if fallback_id in allowed else (allowed[0] if allowed else None),
            "valid": False, "fallback_used": True, "invalid_selection": selected_id}


def aggregate_results(manifest: Mapping[str, Any], results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate cell outcomes without converting failures into losses."""
    scheduled = list(manifest.get("cells") or [])
    by_id = {r.get("cell_id"): r for r in results if isinstance(r, Mapping)}
    rows: list[dict[str, Any]] = []
    for cell in scheduled:
        result = by_id.get(cell.get("id"))
        if result is None:
            rows.append({"cell_id": cell.get("id"), "treatment": cell.get("treatment"),
                         "status": "unrun", "outcome": None})
        else:
            row = dict(result)
            row.setdefault("treatment", cell.get("treatment"))
            rows.append(row)
    summary: dict[str, Any] = {}
    for treatment in TREATMENTS:
        subset = [r for r in rows if r.get("treatment") == treatment]
        wins = sum(r.get("outcome") == "win" and r.get("status") == "completed" for r in subset)
        completed = sum(r.get("status") == "completed" for r in subset)
        summary[treatment] = {
            "scheduled": len(subset), "completed": completed,
            "wins_completed": wins, "wins_scheduled": wins,
            "completion_rate": completed / len(subset) if subset else None,
            "conditional_win_rate": wins / completed if completed else None,
            "operational_failures": sum(r.get("status") in {"failed", "timeout", "budget_stopped"} for r in subset),
            "unrun": sum(r.get("status") == "unrun" for r in subset),
        }
    return {"schema_version": SCHEMA_VERSION, "rows": rows, "summary": summary,
            "denominator": {"scheduled": len(rows), "recorded": sum(r.get("status") != "unrun" for r in rows)},
            "note": "wins_scheduled excludes operational failures; conditional_win_rate is only among completed games."}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="controlled_experiment")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest_parser = sub.add_parser("manifest")
    manifest_parser.add_argument("--out", required=True)
    report_parser = sub.add_parser("report")
    report_parser.add_argument("--manifest", required=True)
    report_parser.add_argument("--results")
    args = parser.parse_args(argv)
    if args.command == "manifest":
        value = build_manifest()
        Path(args.out).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        return 0
    manifest = json.loads(Path(args.manifest).read_text())
    results = json.loads(Path(args.results).read_text()).get("results", []) if args.results else []
    value = aggregate_results(manifest, results)
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0 if validate_manifest(manifest)["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
