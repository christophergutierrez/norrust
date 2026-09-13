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
import hashlib
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
OFFLINE_DRIVER = model_bakeoff.DEFAULT_DRIVER
PILOT_PRICING = {
    "date": "2026-09-13",
    "rates": {"input_per_million": 0.15, "cached_input_per_million": 0.03,
               "output_per_million": 0.5},
}


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
        if treatment != "strategy_fixed":
            cell["pricing"] = copy.deepcopy(PILOT_PRICING)
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
            "supervisor_max_restarts": 0,
            "supervisor_mode": "recording_only",
            "heartbeat_seconds": 300,
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
        "pricing": {**copy.deepcopy(PILOT_PRICING),
                    "status": "dated_read_only_public_evidence",
                    "conservative_estimated_ceiling_usd": 0.8815744,
                    "ceiling_basis": "two 200k paid cells plus one in-flight context bounded at 1048576 tokens"},
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
    for key in ("completed_engine_side_turns", "player_turns_for_glm_treatments",
                "paid_cells_max", "player_token_cap_per_paid_cell",
                "model_call_timeout_seconds", "controlled_turn_timeout_seconds",
                "query_budget_seconds", "wall_deadline_seconds",
                "supervisor_max_restarts", "supervisor_mode", "heartbeat_seconds",
                "aggregate_estimated_ceiling_usd"):
        if manifest.get("pilot_limits", {}).get(key) != expected["pilot_limits"].get(key):
            mismatches.append({"field": f"pilot_limits.{key}",
                               "expected": expected["pilot_limits"].get(key),
                               "actual": manifest.get("pilot_limits", {}).get(key)})
    for actual, wanted in zip(cells, expected["cells"]):
        for key in ("id", "strategy_treatment", "scenario", "seed", "faction0", "faction1",
                    "llm_side", "gold", "max_turns", "model", "decision_mode",
                    "action_encoding", "incremental_turns", "budgets", "pricing"):
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
    # A client writes one model_request envelope and one model response row for
    # a logical call.  Count the envelope (deduplicated by request identity),
    # while physical attempts remain the catalog's model_calls metric.
    request_rows = [item for item in records if item.get("type") == "model_request"]
    response_rows = [item for item in records if item.get("type") == "model"]
    request_ids = {item.get("request_id") for item in request_rows
                   if isinstance(item.get("request_id"), str) and item.get("request_id")}
    model_requests = len(request_ids) + sum(
        1 for item in request_rows
        if not (isinstance(item.get("request_id"), str) and item.get("request_id")))
    if not request_rows:
        response_ids = {item.get("request_id") for item in response_rows
                        if isinstance(item.get("request_id"), str) and item.get("request_id")}
        model_requests = len(response_ids) + sum(
            1 for item in response_rows
            if not (isinstance(item.get("request_id"), str) and item.get("request_id")))
    metadata = next((item for item in records if item.get("type") == "metadata"), {})
    usage_measured = metadata.get("usage_measured")
    usage_coverage = ("not_applicable" if model_requests == 0 else
                      "known" if usage_measured is True else
                      "unknown" if model_requests or usage_measured is not False else "not_applicable")
    boundary_types = {"side_turn", "turn_boundary", "checkpoint_ref", "batch_committed"}
    boundary_coverage = ("known" if any(item.get("type") in boundary_types for item in records)
                         else "unknown")
    partial_failure = any(item.get("type") in {"supervisor_error", "infrastructure_error"}
                          for item in records)
    terminal_present = bool(terminal)
    if not terminal_present:
        evidence_status = "unknown_truncated"
    elif partial_failure or usage_coverage == "unknown" or boundary_coverage == "unknown":
        evidence_status = "unknown_coverage"
    else:
        evidence_status = "complete"
    counts.update({
        "source_label": "synthetic_fixture" if synthetic else "recorded_archive",
        "synthetic": synthetic,
        "model_request_count": model_requests if terminal_present else None,
        "terminal_present": terminal_present,
        "usage_coverage": usage_coverage,
        "boundary_coverage": boundary_coverage,
        "partial_failure": partial_failure,
        "routine_event_count": counts["events_by_source"].get("routine", 0),
        "model_event_count": counts["events_by_source"].get("llm", 0),
        "delegated_event_count": counts["events_by_source"].get("delegated_greedy", 0),
        "evidence_status": evidence_status,
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
            row["blocked_reason"] = case.get(
                "blocked_reason", "not executed; run the offline-run command with the real driver")
        rows.append(row)
    return {"schema_version": 1, "matrix_status": "unknown_unrun" if any(
        row["status"] != "observed" for row in rows) else "observed",
        "cases": rows,
        "denominator": {"scheduled": len(rows),
                        "observed": sum(row["status"] == "observed" for row in rows),
                        "unknown_unrun": sum(row["status"] != "observed" for row in rows)},
        "note": "Unknown/unrun cases remain explicit; synthetic attribution is labelled and does not establish gameplay quality."}


def _offline_policy_path(name: str) -> Path:
    path = FIXTURE_DIR / f"{name}.json"
    if not path.is_file():
        raise StrategyComparisonError(f"offline policy fixture is missing: {path}")
    return path


def _offline_checkpoint_path(case: dict[str, Any]) -> Path:
    filename = case.get("checkpoint_fixture", "quiet_checkpoint.json")
    path = FIXTURE_DIR / filename
    if not path.is_file():
        raise StrategyComparisonError(f"offline checkpoint fixture is missing: {path}")
    return path


def _offline_cell(case: dict[str, Any], variant: str, policy: str, *,
                  driver: str) -> dict[str, Any]:
    checkpoint = _offline_checkpoint_path(case)
    policy_path = _offline_policy_path(policy)
    return {
        "id": f"offline-{case['id']}-{variant}",
        "scenario": "big_battle_6", "seed": int(case.get("seed", 9211)),
        "faction0": "undead", "faction1": "undead", "llm_side": 0,
        "gold": 300, "max_turns": int(case.get("max_turns", 2)),
        "model": "fixed-policy-code", "decision_mode": "strategy",
        "action_encoding": "coordinates", "incremental_turns": True,
        "strategy_policy": str(policy_path.relative_to(REPO_ROOT)),
        "checkpoint_fixture": str(checkpoint.relative_to(REPO_ROOT)),
        "backend": {"kind": "fixed_policy",
                     "path": str(policy_path.relative_to(REPO_ROOT))},
        "driver": driver,
        "budgets": {"max_partial_batches_per_turn": 64},
    }


def _event_digest(records: list[dict[str, Any]]) -> str:
    events = []
    for record in records:
        line = record.get("line") if record.get("type") == "driver" else None
        if isinstance(line, dict) and line.get("type") == "events":
            events.extend(event for event in line.get("events", []) if isinstance(event, dict))
    encoded = json.dumps(events, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _event_spend(records: list[dict[str, Any]]) -> int:
    spend = 0
    for record in records:
        line = record.get("line") if record.get("type") == "driver" else None
        if not isinstance(line, dict) or line.get("type") != "events":
            continue
        for event in line.get("events", []):
            if isinstance(event, dict) and event.get("kind") == "recruit":
                value = event.get("cost", event.get("gold_spent", 0))
                if isinstance(value, (int, float)):
                    spend += int(value)
    return spend


def run_offline_matrix(matrix: dict[str, Any] | None = None, *,
                       run_dir: Path, driver: str | None = None,
                       timeout: float | None = 90) -> dict[str, Any]:
    """Execute the provider-free matrix through the real driver.

    Every policy run owns a normal bakeoff cell, log, checkpoint, and catalog
    game id.  Expected typed exceptions are observed evidence, not skipped
    cases.  The same travel policy is run twice with the same seed and its
    executed-event digest is compared.  Each source is imported twice to
    exercise the history importer's idempotence fence.
    """
    if matrix is None:
        matrix = json.loads(OFFLINE_MATRIX_PATH.read_text())
    cases = matrix.get("cases") if isinstance(matrix, dict) else None
    if not isinstance(cases, list) or not cases:
        raise StrategyComparisonError("offline matrix must contain cases")
    driver = driver or OFFLINE_DRIVER
    driver_path = Path(driver)
    if not driver_path.is_absolute():
        driver_path = REPO_ROOT / driver_path
    if not driver_path.is_file():
        raise StrategyComparisonError(f"offline driver is unavailable: {driver}")
    run_dir.mkdir(parents=True, exist_ok=True)
    catalog = run_dir / "catalog.sqlite"
    rows: list[dict[str, Any]] = []
    for case in cases:
        variants = [str(value) for value in case.get("policy_variants", [])]
        if not variants:
            raise StrategyComparisonError(f"case {case.get('id')!r} has no policy_variants")
        expanded: list[tuple[str, str]] = []
        for variant in variants:
            expanded.append((variant, variant))
            if case.get("identical_policy_seed_replays") and variant == variants[0]:
                expanded.append((variant, f"{variant}-replay"))
        run_rows = []
        for policy, variant in expanded:
            cell = _offline_cell(case, variant, policy, driver=str(driver_path))
            resolved = model_bakeoff.resolve_manifest({"experiment_kind": "matched",
                                                        "cells": [cell]})
            results = model_bakeoff.run_manifest(resolved, run_dir, timeout=timeout)
            result = results[0]
            records = match_report.load_records(result.log_path) if result.log_path.is_file() else []
            imported = model_bakeoff.import_cells(catalog, results, "strategy-offline")
            imported_again = model_bakeoff.import_cells(catalog, results, "strategy-offline")
            attribution = archive_attribution(records, synthetic=False) if records else None
            exception = next((r.get("reason") for r in records
                              if r.get("type") == "routine_exception"), None)
            if exception is None:
                terminal = match_report.terminal_record(records)
                message = terminal.get("message") if isinstance(terminal, dict) else None
                if isinstance(message, str) and "unsupported exception:" in message:
                    exception = message.split("unsupported exception:", 1)[1].strip()
                elif isinstance(message, str) and "cannot resolve exception:" in message:
                    exception = message.split("cannot resolve exception:", 1)[1].strip()
            run_rows.append({"variant": variant, "policy": policy,
                             "status": "observed" if records else "unknown_unrun",
                             "exit_status": result.status, "exit_code": result.exit_code,
                             "terminal_class": match_report.classify(records)["terminal_class"] if records else "unknown",
                             "exception": exception,
                             "event_digest": _event_digest(records) if records else None,
                             "deployment_count": sum(1 for r in records
                                                      if r.get("type") == "driver"
                                                      and isinstance(r.get("line"), dict)
                                                      and r["line"].get("type") == "events"
                                                      for e in r["line"].get("events", [])
                                                      if isinstance(e, dict) and e.get("kind") == "recruit"),
                             "spend": _event_spend(records),
                             "attribution": attribution,
                             "imported_game_ids": imported,
                             "import_idempotent": sorted(imported) == sorted(imported_again)})
        policy_difference = None
        distinct_policy_rows = []
        seen_policies = set()
        for item in run_rows:
            if item["policy"] not in seen_policies:
                seen_policies.add(item["policy"])
                distinct_policy_rows.append(item)
        if (len(distinct_policy_rows) >= 2 and
                distinct_policy_rows[0]["status"] == distinct_policy_rows[1]["status"] == "observed"):
            policy_difference = {
                "different_event_digest": distinct_policy_rows[0]["event_digest"] != distinct_policy_rows[1]["event_digest"],
                "different_deployment": distinct_policy_rows[0]["deployment_count"] != distinct_policy_rows[1]["deployment_count"],
                "different_spend": distinct_policy_rows[0]["spend"] != distinct_policy_rows[1]["spend"],
                "required": bool(case.get("expected", {}).get("deployment_diff_required")),
            }
            policy_difference["satisfied"] = (
                not policy_difference["required"] or
                policy_difference["different_deployment"] or policy_difference["different_spend"])
        replay = None
        if case.get("identical_policy_seed_replays") and len(run_rows) >= 2:
            replay = {"same_event_digest": run_rows[0]["event_digest"] == run_rows[1]["event_digest"],
                      "event_digest": run_rows[0]["event_digest"]}
        rows.append({"case_id": case["id"], "description": case.get("description"),
                     "expected": copy.deepcopy(case.get("expected", {})), "status":
                     "observed" if all(item["status"] == "observed" for item in run_rows) else "unknown_unrun",
                     "runs": run_rows, "policy_difference": policy_difference,
                     "deterministic_replay": replay})
    observed = sum(row["status"] == "observed" for row in rows)
    return {"schema_version": 1, "matrix_status": "observed" if observed == len(rows) else "partial_unknown",
            "cases": rows,
            "denominator": {"scheduled": len(rows), "observed": observed,
                            "unknown_unrun": len(rows) - observed},
            "catalog": str(catalog), "network": "disabled", "paid_calls": 0,
            "note": "Fixed policies use real engine transitions; usage is unknown/not applicable and no synthetic model tokens are claimed."}


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
        treatment = cell.get("strategy_treatment")
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
    run_matrix = sub.add_parser("offline-run", help="execute the provider-free matrix through the real driver")
    run_matrix.add_argument("--matrix", default=str(OFFLINE_MATRIX_PATH))
    run_matrix.add_argument("--run-dir", required=True)
    run_matrix.add_argument("--driver", default=OFFLINE_DRIVER)
    run_matrix.add_argument("--timeout", type=float, default=90)
    run_matrix.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "pilot-manifest":
        payload = load_prepared_pilot() if Path(args.out).resolve() == PILOT_MANIFEST_PATH.resolve() else build_pilot_manifest()
    elif args.command == "pilot-report":
        payload = build_strategy_report(json.loads(Path(args.manifest).read_text()))
    elif args.command == "offline-report":
        payload = build_offline_matrix_report(json.loads(Path(args.matrix).read_text()))
    else:
        payload = run_offline_matrix(json.loads(Path(args.matrix).read_text()),
                                     run_dir=Path(args.run_dir), driver=args.driver,
                                     timeout=args.timeout)
    Path(args.out).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
