"""Prepared Stack 4 strategy comparisons and the provider-free matrix.

This is an experiment/report layer over :mod:`tools.model_bakeoff`.  Its
offline-run command executes fixed policies through the real driver without a
provider; it does not invent a second history or cost store.
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
import sys
from typing import Any, Iterable

from . import bakeoff_metrics, game_history, match_report, model_bakeoff

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tools" / "fixtures" / "strategy_comparison"
PILOT_MANIFEST_PATH = FIXTURE_DIR / "pilot_manifest.json"
OFFLINE_MATRIX_PATH = FIXTURE_DIR / "offline_matrix.json"
FIXED_POLICY_PATH = FIXTURE_DIR / "strategy_fixed_policy.json"
DECISION_FIXTURE_DIR = REPO_ROOT / "tools" / "fixtures" / "strategy_decisions"
DECISION_MATRIX_PATH = DECISION_FIXTURE_DIR / "matrix_manifest.json"
SCREENING_MANIFEST_PATH = DECISION_FIXTURE_DIR / "fireworks_screening_manifest.json"
FAKE_TRANSPORT_PATH = DECISION_FIXTURE_DIR / "fake_transport.py"

STRATEGY_TREATMENTS = model_bakeoff.STRATEGY_TREATMENTS
PILOT_MODEL = "accounts/fireworks/models/glm-5p3-flash"
PILOT_SCENARIO = "big_battle_6"
PILOT_SEED = 2038
PILOT_MAX_TURNS = 6
PILOT_GOLD = 300
PILOT_PLAYER_SIDE = 0
PILOT_MAX_PLAYER_TOKENS = 200_000
PILOT_AGGREGATE_CEILING_USD = 1.0
PILOT_MAX_MODEL_CALLS_PER_TURN = 8
PILOT_MAX_TOOL_CALLS_PER_TURN = 64
PILOT_MAX_QUERIES_PER_TURN = 256
OFFLINE_DRIVER = model_bakeoff.DEFAULT_DRIVER
PILOT_PRICING = {
    "date": "2026-09-13",
    "rates": {"input_per_million": 0.15, "cached_input_per_million": 0.03,
               "output_per_million": 0.5,
               "reasoning_included_in_output": True},
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
                "max_model_calls_per_turn": PILOT_MAX_MODEL_CALLS_PER_TURN,
                "max_tool_calls_per_turn": PILOT_MAX_TOOL_CALLS_PER_TURN,
                "max_queries_per_turn": PILOT_MAX_QUERIES_PER_TURN,
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
            "matched_client_limits": {
                "max_model_calls_per_turn": PILOT_MAX_MODEL_CALLS_PER_TURN,
                "max_tool_calls_per_turn": PILOT_MAX_TOOL_CALLS_PER_TURN,
                "max_queries_per_turn": PILOT_MAX_QUERIES_PER_TURN,
                "max_partial_batches_per_turn": 64,
            },
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
    if (manifest.get("pilot_limits", {}).get("matched_client_limits") !=
            expected["pilot_limits"].get("matched_client_limits")):
        mismatches.append({"field": "pilot_limits.matched_client_limits",
                           "expected": expected["pilot_limits"].get("matched_client_limits"),
                           "actual": manifest.get("pilot_limits", {}).get("matched_client_limits")})
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
    metadata_rows = [item for item in records if item.get("type") == "metadata"]
    metadata = metadata_rows[-1] if metadata_rows else {}
    # The initial metadata row is written before dispatch and commonly says
    # true. Only final metadata plus every logical request's measured usage
    # can establish known accounting coverage.
    fixed_without_calls = (model_requests == 0
                           and metadata.get("model_backend") == "fixed_policy_code")
    # Raw archives do not contain the authoritative physical-call/catalog
    # coverage. Even a non-null aggregate (including {}) is insufficient.
    usage_coverage = "not_applicable" if fixed_without_calls else "unknown"
    side_turn_started = sum(item.get("type") == "side_turn_started" for item in records)
    turn_boundaries = sum(item.get("type") == "turn_boundary" for item in records)
    checkpoint_refs = sum(item.get("type") == "checkpoint_ref" for item in records)
    batch_commits = sum(item.get("type") == "batch_committed" for item in records)
    submitted = sum(item.get("type") == "request_submitted" for item in records)
    boundary_complete = (bool(terminal) and side_turn_started > 0
                         and turn_boundaries == side_turn_started
                         and batch_commits == submitted
                         and checkpoint_refs >= batch_commits)
    boundary_coverage = "known" if boundary_complete else "unknown"
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
        "boundary_evidence": {"side_turn_started": side_turn_started,
                               "turn_boundary": turn_boundaries,
                               "checkpoint_ref": checkpoint_refs,
                               "request_submitted": submitted,
                               "batch_committed": batch_commits},
        "partial_failure": partial_failure,
        "routine_event_count": counts["events_by_source"].get("routine", 0),
        "model_event_count": counts["events_by_source"].get("llm", 0),
        "delegated_event_count": counts["events_by_source"].get("delegated_greedy", 0),
        "evidence_status": evidence_status,
    })
    return counts


def _verdict(actual: Any, expected: Any) -> bool | None:
    """Compare a factual value while preserving unavailable evidence."""
    return None if actual is None else actual == expected


def _acceptance_status(verdicts: dict[str, Any]) -> str:
    values = [value for value in verdicts.values() if isinstance(value, bool)]
    if any(value is False for value in values):
        return "failed"
    if any(value is None for value in verdicts.values()) or not values:
        return "unknown"
    return "passed"


def _matrix_run_predicates(case: dict[str, Any], records: list[dict[str, Any]],
                           attribution: dict[str, Any] | None,
                           exception: str | None) -> dict[str, Any]:
    expected = case.get("expected", {}) if isinstance(case.get("expected"), dict) else {}
    if not records or attribution is None:
        return {key: None for key in ("expected_exception", "model_calls",
                                      "contact", "actual_events", "fallback",
                                      "usage_coverage", "boundary_coverage")}
    predicates: dict[str, Any] = {}
    predicates["usage_coverage"] = attribution.get("usage_coverage") not in (None, "unknown")
    predicates["boundary_coverage"] = _verdict(attribution.get("boundary_coverage"), "known")
    if "exception" in expected:
        terminal_present = attribution.get("terminal_present") is True
        predicates["expected_exception"] = _verdict(
            exception if exception is not None else ("none" if terminal_present else None),
            expected["exception"])
    if "model_calls" in expected:
        predicates["model_calls"] = _verdict(attribution.get("model_request_count"), expected["model_calls"])
    if "completed_side_turns_at_least" in expected:
        terminal = match_report.terminal_record(records)
        terminal_line = terminal.get("line", {}) if isinstance(terminal, dict) else {}
        completed = terminal.get("side_turns") if isinstance(terminal, dict) else None
        if not isinstance(completed, int):
            completed = terminal_line.get("side_turns") if isinstance(terminal_line, dict) else None
        predicates["completed_turns"] = (
            None if not isinstance(completed, int)
            else completed >= expected["completed_side_turns_at_least"])
    if "routine_move_events_at_least" in expected:
        moves = sum(
            1 for record in records
            if record.get("type") == "driver"
            and isinstance(record.get("line"), dict)
            and record["line"].get("type") == "events"
            for event in record["line"].get("events", [])
            if isinstance(event, dict)
            and event.get("kind") == "move"
            and event.get("source") == "routine")
        predicates["routine_moves"] = moves >= expected["routine_move_events_at_least"]
    if "objectives_complete" in expected:
        complete = any(
            isinstance(record, dict)
            and record.get("type") == "routine_progress_committed"
            and any(isinstance(effect, dict) and effect.get("kind") == "policy_completed"
                    for effect in (record.get("progress_update", {}).get("effects", [])
                                   if isinstance(record.get("progress_update"), dict) else []))
            for record in records)
        predicates["objectives"] = complete == expected["objectives_complete"]
    if "owned_villages" in expected:
        predicates["village_objective"] = model_bakeoff.evaluate_objective(
            records, {"owned_villages": expected["owned_villages"]}, 0)
    if "contact" in expected:
        terminal_present = attribution.get("terminal_present") is True
        predicates["contact"] = _verdict(
            (exception == "contact") if exception is not None
            else (False if terminal_present else None), expected["contact"])
    if expected.get("actual_events_required"):
        count = attribution.get("actual_event_count")
        predicates["actual_events"] = None if not isinstance(count, int) else count > 0
    if "model_tactical_fallback" in expected:
        model_events = attribution.get("model_event_count")
        predicates["fallback"] = (
            None if not isinstance(model_events, int) else
            (model_events > 0) == expected["model_tactical_fallback"])
    if "fallback_to_greedy" in expected:
        delegated = attribution.get("delegated_event_count")
        predicates["fallback"] = (
            None if not isinstance(delegated, int) else
            (delegated > 0) == expected["fallback_to_greedy"])
    if expected.get("boundary_coverage_required"):
        predicates["boundary_coverage"] = _verdict(attribution.get("boundary_coverage"), "known")
    else:
        # Typed exception cases intentionally stop before an own-turn boundary;
        # archive attribution still reports that coverage separately.
        predicates.pop("boundary_coverage", None)
    return predicates


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
            exception = next((r.get("reason") for r in records
                              if r.get("type") == "routine_exception"), None)
            row["predicate_verdicts"] = _matrix_run_predicates(
                case, records, row["attribution"], exception)
            row["acceptance_status"] = _acceptance_status(row["predicate_verdicts"])
        else:
            row["blocked_reason"] = case.get(
                "blocked_reason", "not executed; run the offline-run command with the real driver")
        rows.append(row)
    observed = sum(row["status"] == "observed" for row in rows)
    acceptance = [row.get("acceptance_status") for row in rows
                  if row["status"] == "observed"]
    acceptance_status = ("failed" if "failed" in acceptance else
                         "unknown" if len(acceptance) != len(rows) or "unknown" in acceptance
                         else "passed")
    return {"schema_version": 1, "matrix_status": "unknown_unrun" if any(
        row["status"] != "observed" for row in rows) else "observed",
        "cases": rows,
        "denominator": {"scheduled": len(rows),
                        "observed": observed,
                        "unknown_unrun": sum(row["status"] != "observed" for row in rows)},
        "acceptance_status": acceptance_status,
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


def _catalog_snapshot(catalog: Path, game_ids: list[str]) -> dict[str, Any]:
    """Hash all imported per-game rows so re-import checks content, not IDs."""
    if not game_ids:
        return {}
    import sqlite3
    conn = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    try:
        snapshot: dict[str, Any] = {}
        placeholders = ",".join("?" for _ in game_ids)
        for table in game_history.TABLES:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            if "game_id" not in columns:
                continue
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE game_id IN ({placeholders}) ORDER BY rowid",
                game_ids).fetchall()
            normalized = [
                [value.hex() if isinstance(value, bytes) else value for value in row]
                for row in rows
            ]
            encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                                 default=str).encode()
            snapshot[table] = {"count": len(rows),
                               "sha256": hashlib.sha256(encoded).hexdigest()}
        return snapshot
    finally:
        conn.close()


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
            import_snapshot = _catalog_snapshot(catalog, imported)
            imported_again = model_bakeoff.import_cells(catalog, results, "strategy-offline")
            import_snapshot_again = _catalog_snapshot(catalog, imported_again)
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
            run_predicates = _matrix_run_predicates(case, records, attribution, exception)
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
                             "import_idempotent": import_snapshot == import_snapshot_again,
                             "import_snapshot": {"before": import_snapshot,
                                                 "after": import_snapshot_again},
                             "predicate_verdicts": run_predicates,
                             "acceptance_status": _acceptance_status(run_predicates)})
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
        case_predicates: dict[str, Any] = {
            "runs": (None if not run_rows else
                     (False if any(item.get("acceptance_status") == "failed" for item in run_rows)
                      else None if any(item.get("acceptance_status") != "passed" for item in run_rows)
                      else True)),
        }
        if case.get("expected", {}).get("deployment_diff_required"):
            case_predicates["policy_difference"] = (
                None if policy_difference is None else policy_difference.get("satisfied"))
        if case.get("identical_policy_seed_replays"):
            case_predicates["deterministic_replay"] = (
                None if replay is None else replay.get("same_event_digest"))
        case_predicates["import_idempotence"] = (
            None if not run_rows else
            (False if any(item.get("import_idempotent") is False for item in run_rows)
             else None if any(item.get("import_idempotent") is None for item in run_rows)
             else True))
        rows.append({"case_id": case["id"], "description": case.get("description"),
                     "expected": copy.deepcopy(case.get("expected", {})), "status":
                     "observed" if all(item["status"] == "observed" for item in run_rows) else "unknown_unrun",
                     "runs": run_rows, "policy_difference": policy_difference,
                     "deterministic_replay": replay,
                     "predicate_verdicts": case_predicates,
                     "acceptance_status": _acceptance_status(case_predicates)})
    observed = sum(row["status"] == "observed" for row in rows)
    acceptance = [row.get("acceptance_status") for row in rows]
    acceptance_status = ("failed" if "failed" in acceptance else
                         "unknown" if observed != len(rows) or "unknown" in acceptance
                         else "passed")
    return {"schema_version": 1, "matrix_status": "observed" if observed == len(rows) else "partial_unknown",
            "cases": rows,
            "denominator": {"scheduled": len(rows), "observed": observed,
                            "unknown_unrun": len(rows) - observed},
            "acceptance_status": acceptance_status,
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


def _pilot_results_from_run_dir(run_dir: Path,
                                resolved_manifest: dict[str, Any]) -> list[model_bakeoff.CellRunResult]:
    """Load every scheduled pilot cell, preserving cells that never ran."""
    results: list[model_bakeoff.CellRunResult] = []
    for cell in resolved_manifest.get("cells", []):
        cell_id = cell["id"]
        cell_dir = model_bakeoff.cell_dir_for(run_dir, cell_id)
        result = model_bakeoff._load_run_status(cell_dir, cell_id)
        if result is None:
            result = model_bakeoff.CellRunResult(
                cell_id, cell_dir, cell_dir / "match.ndjson", None, "", None, "not_run")
        results.append(result)
    return results


def decision_archive_attribution(records: list[dict[str, Any]], *,
                                 synthetic: bool = False,
                                 pricing: dict[str, Any] | None = None) -> dict[str, Any]:
  """Summarize the 16 required strategy decision dimensions from match records."""
  counts = event_source_counts(records)
  terminal = match_report.terminal_record(records)
  classification = match_report.classify(records) if records else {"terminal_class": "unknown"}
  terminal_class = classification.get("terminal_class", "unknown")
  terminal_code = terminal.get("code") if isinstance(terminal, dict) else None
  terminal_present = bool(terminal)

  # 1 & 2: Provider calls and logical requests
  request_rows = [item for item in records if item.get("type") == "model_request"]
  response_rows = [item for item in records if item.get("type") == "model"]
  request_ids = {
    item.get("request_id") for item in request_rows
    if isinstance(item.get("request_id"), str) and item.get("request_id")
  }
  logical_requests = len(request_ids) + sum(
    1 for item in request_rows
    if not (isinstance(item.get("request_id"), str) and item.get("request_id"))
  )
  if not request_rows:
    response_ids = {
      item.get("request_id") for item in response_rows
      if isinstance(item.get("request_id"), str) and item.get("request_id")
    }
    logical_requests = len(response_ids) + sum(
      1 for item in response_rows
      if not (isinstance(item.get("request_id"), str) and item.get("request_id"))
    )
  provider_calls = len(response_rows)

  # 3: Repairs
  repairs = sum(
    1 for item in records
    if item.get("type") in ("strategy_response_repair", "action_repair", "model_response_repair")
    or item.get("purpose") == "repair"
  )

  # 4 & 5: Option selections and custom acts
  forwarded_rows = [item for item in records if item.get("type") == "forwarded_orders"]
  option_selections = sum(
    1 for item in forwarded_rows
    if item.get("proposal_source") == "engine_option" or item.get("option_id") is not None
  )
  custom_acts = sum(
    1 for item in forwarded_rows
    if item.get("proposal_source") != "engine_option"
    and item.get("option_id") is None
    and bool(item.get("orders"))
  )

  # 6 & 7: Context-invalid replies and identical incident recurrences
  context_invalid_replies = sum(
    1 for item in records if item.get("type") == "contextual_rejection"
  )
  incident_keys: list[str] = []
  for item in records:
    if item.get("type") == "decision_packet" and isinstance(item.get("packet"), dict):
      key = item["packet"].get("incident_key")
      if key:
        incident_keys.append(str(key))
    elif item.get("type") == "contextual_rejection" and item.get("incident_key"):
      incident_keys.append(str(item["incident_key"]))
  identical_incident_recurrences = sum(
    1 for idx in range(1, len(incident_keys))
    if incident_keys[idx] == incident_keys[idx - 1]
  )

  # 8, 9 & 10: Routine vs model actions and actual board effects
  routine_actions = counts["events_by_source"].get("routine", 0)
  model_actions = counts["events_by_source"].get("llm", 0)
  damage_dealt = 0
  units_killed = 0
  moves = 0
  attacks = 0
  recruits = 0
  captures = 0
  for item in records:
    if item.get("type") != "driver" or not isinstance(item.get("line"), dict):
      continue
    line = item["line"]
    if line.get("type") != "events" or not isinstance(line.get("events"), list):
      continue
    for ev in line["events"]:
      if not isinstance(ev, dict):
        continue
      k = ev.get("kind")
      if k == "move":
        moves += 1
      elif k == "attack":
        attacks += 1
        dmg = ev.get("damage_to_defender", ev.get("damage_dealt", ev.get("damage", 0)))
        if isinstance(dmg, (int, float)):
          damage_dealt += int(dmg)
        defender = ev.get("defender")
        attacker = ev.get("attacker")
        if ((isinstance(defender, dict) and defender.get("killed"))
            or (isinstance(attacker, dict) and attacker.get("killed"))
            or ev.get("killed")):
          units_killed += 1
      elif k == "recruit":
        recruits += 1
      elif k == "village":
        captures += 1
      elif k == "kill":
        units_killed += 1

  board_effects = {
    "total_events": counts["actual_event_count"],
    "moves": moves,
    "attacks": attacks,
    "recruits": recruits,
    "captures": captures,
    "damage_dealt": damage_dealt,
    "units_killed": units_killed,
    "events_by_source": counts["events_by_source"],
    "events_by_kind": counts["events_by_kind"],
  }

  # 11, 12, 13 & 14: Incident resolution, tactical progress, explicit finish, budget stop
  tactical_incidents = [
    item for item in records
    if item.get("type") == "decision_packet"
    and isinstance(item.get("packet"), dict)
    and item["packet"].get("decision_kind") == "tactical"
  ]
  incident_raised = len(tactical_incidents) > 0
  replacement_policy_installed = any(
    item.get("type") == "policy_installed" and item.get("source_kind") == "model"
    for item in records
  )
  incident_resolution = None
  if incident_raised:
    incident_resolution = (
      option_selections > 0
      or custom_acts > 0
      or replacement_policy_installed
      or (terminal_class == "gameplay" and not context_invalid_replies)
    )

  relocation_selected = any(
    item.get("type") == "forwarded_orders" and str(item.get("option_id", "")).startswith("relocate")
    for item in records
  )
  tactical_progress = (attacks > 0 and damage_dealt > 0) or (moves > 0 and relocation_selected)

  explicit_finish = (
    any(
      item.get("type") == "forwarded_orders"
      and (not item.get("orders") or item.get("authored_finish_kind") is not None)
      for item in records
    )
    or (terminal.get("reason") in ("max_turns", "winner", "resignation") if isinstance(terminal, dict) else False)
  )

  budget_stop = (
    terminal_class == "budget_interrupted"
    or terminal_code in ("strategy_no_progress", "model_calls_exhausted", "tool_calls_exhausted", "operator_wall_deadline")
  )

  # 15 & 16: Usage and cost accounting
  pricing_dict = copy.deepcopy(pricing) if pricing else copy.deepcopy(PILOT_PRICING)
  usage_summary = bakeoff_metrics.aggregate_usage(
    response_rows,
    model=pricing_dict.get("model"),
    price_date=pricing_dict.get("date"),
    custom_prices=pricing_dict.get("rates"),
  )
  cost_val = usage_summary.get("known_cost")
  cost_cov = usage_summary.get("cost_coverage", "unknown")
  usage_cov = usage_summary.get("usage_coverage", "unknown")

  if not terminal_present:
    evidence_status = "unknown_truncated"
  elif usage_cov == "unknown":
    evidence_status = "unknown_coverage"
  elif budget_stop:
    evidence_status = "budget_stopped"
  else:
    evidence_status = "complete"

  return {
    "source_label": "synthetic_fixture" if synthetic else "recorded_archive",
    "synthetic": synthetic,
    "provider_calls": provider_calls if terminal_present else None,
    "logical_requests": logical_requests if terminal_present else None,
    "repairs": repairs,
    "option_selections": option_selections,
    "custom_acts": custom_acts,
    "context_invalid_replies": context_invalid_replies,
    "identical_incident_recurrences": identical_incident_recurrences,
    "routine_actions": routine_actions,
    "model_actions": model_actions,
    "actual_board_effects": board_effects,
    "incident_resolution": incident_resolution,
    "tactical_progress": tactical_progress,
    "explicit_finish": explicit_finish,
    "budget_stop": budget_stop,
    "terminal_present": terminal_present,
    "terminal_class": terminal_class,
    "terminal_code": terminal_code,
    "usage": {
      "input_tokens": usage_summary.get("input_tokens"),
      "output_tokens": usage_summary.get("output_tokens"),
      "reasoning_tokens": usage_summary.get("reasoning_tokens"),
      "cached_input_tokens": usage_summary.get("cached_input_tokens"),
      "total_tokens": (
        (usage_summary.get("input_tokens") or 0) + (usage_summary.get("output_tokens") or 0)
        if usage_summary.get("input_tokens") is not None and usage_summary.get("output_tokens") is not None
        else None
      ),
      "usage_coverage": usage_cov,
    },
    "cost": {
      "cost_usd": cost_val,
      "cost_coverage": cost_cov,
      "pricing": pricing_dict,
    },
    "evidence_status": evidence_status,
  }


def _decision_matrix_predicates(case: dict[str, Any],
                                records: list[dict[str, Any]],
                                attribution: dict[str, Any] | None) -> dict[str, Any]:
  """Evaluate the acceptance predicates for one matrix position."""
  expected = case.get("expected", {}) if isinstance(case.get("expected"), dict) else {}
  if not records or attribution is None:
    return {
      "terminal_class": None,
      "terminal_outcome": None,
      "predicate_pass": None,
    }

  predicates: dict[str, Any] = {}
  pos = case.get("position")

  if pos == "repeated_current_contact":
    predicates["budget_stopped"] = (attribution["budget_stop"] is True)
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "budget_interrupted"))
    predicates["terminal_code"] = (attribution["terminal_code"] == expected.get("terminal_code", "strategy_no_progress"))
    predicates["bounded_requests"] = (
      attribution["logical_requests"] is not None
      and attribution["logical_requests"] <= expected.get("max_model_calls", 3)
    )
    predicates["context_invalid_observed"] = (
      attribution["context_invalid_replies"] >= expected.get("context_invalid_count", 1)
    )
    predicates["no_board_mutation"] = (attribution["actual_board_effects"]["total_events"] == expected.get("board_actions_count", 0))
    rejection_seen = False
    policy_after_rejection = False
    for r in records:
      if r.get("type") == "contextual_rejection":
        rejection_seen = True
      elif rejection_seen and r.get("type") == "policy_installed":
        policy_after_rejection = True
    predicates["policy_not_mutated"] = not policy_after_rejection

  elif pos == "proposed_dangerous_route":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "gameplay"))
    predicates["replacement_objective_accepted"] = any(
      r.get("type") == "policy_installed" and r.get("source_kind") == "model" for r in records
    )
    predicates["incident_removed"] = (attribution["actual_board_effects"]["attacks"] == 0)
    predicates["no_budget_stop"] = (attribution["budget_stop"] is False)

  elif pos == "favorable_tactical_attack":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "gameplay"))
    predicates["attack_committed"] = (
      attribution["option_selections"] >= 1
      and attribution["actual_board_effects"]["attacks"] >= 1
    )
    predicates["enemy_hp_reduced"] = (attribution["actual_board_effects"]["damage_dealt"] > 0)
    predicates["defender_killed"] = (attribution["actual_board_effects"]["units_killed"] >= 1)
    predicates["tactical_progress"] = (attribution["tactical_progress"] is True)

  elif pos == "withdrawal":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "gameplay"))
    predicates["relocation_committed"] = (
      attribution["option_selections"] >= 1
      and attribution["actual_board_effects"]["moves"] >= 1
      and any(r.get("type") == "forwarded_orders" and str(r.get("option_id", "")).startswith("relocate") for r in records)
    )
    predicates["recruiter_survived"] = (
      attribution["actual_board_effects"]["units_killed"] == 0
      and attribution["terminal_class"] == "gameplay"
    )
    predicates["exposure_lowered"] = (attribution["tactical_progress"] is True)

  elif pos == "independent_scout_movement":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "gameplay"))
    predicates["independent_routine_move"] = (
      any(r.get("type") == "independent_routine_move" for r in records)
      and attribution["routine_actions"] >= 1
    )
    predicates["tactical_incident_visible"] = any(
      r.get("type") == "decision_packet"
      and r.get("packet", {}).get("decision_kind") == "tactical"
      for r in records
    )
    predicates["tactical_option_executed"] = (attribution["actual_board_effects"]["attacks"] >= 1)

  elif pos == "blocking_unit":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "gameplay"))
    predicates["automatic_move_refused"] = (attribution["actual_board_effects"]["moves"] == 0)
    no_greedy_sweep_actions = not any(
      r.get("type") == "driver"
      and isinstance(r.get("line"), dict)
      and any(
        e.get("source") == "delegated_greedy" and e.get("kind") in ("move", "attack")
        for e in r["line"].get("events", [])
      )
      for r in records
    )
    predicates["no_greedy_sweep"] = (
      attribution["actual_board_effects"]["attacks"] == 0
      and no_greedy_sweep_actions
    )

  elif pos == "scouts_absent":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "model_invalid"))
    predicates["policy_rejected_before_installation"] = not any(
      r.get("type") == "policy_installed" for r in records
    )
    predicates["zero_board_actions"] = (attribution["actual_board_effects"]["total_events"] == expected.get("board_actions_count", 0))

  elif pos == "resume_at_decision_boundary":
    predicates["terminal_class"] = (attribution["terminal_class"] == expected.get("terminal_class", "gameplay"))
    predicates["no_renewed_allowance"] = (attribution["budget_stop"] is False)
    predicates["attack_executed"] = (attribution["actual_board_effects"]["attacks"] == 1)
    predicates["no_duplicate_actions"] = (
      attribution["actual_board_effects"]["recruits"] == 0
      and attribution["option_selections"] == 1
    )

  else:
    for k, v in expected.items():
      predicates[k] = _verdict(attribution.get(k), v)

  return predicates


def build_decision_matrix_report(manifest: dict[str, Any] | None = None, *,
                                 archives: dict[str, list[dict[str, Any]]] | None = None,
                                 pricing: dict[str, Any] | None = None) -> dict[str, Any]:
  """Generate the acceptance matrix report across all 8 positions."""
  if manifest is None:
    manifest = json.loads(DECISION_MATRIX_PATH.read_text())
  cases = manifest.get("cases", [])
  if not cases:
    raise StrategyComparisonError("decision matrix manifest has no cases")

  rows: list[dict[str, Any]] = []
  for case in cases:
    records = (archives or {}).get(case["id"])
    row: dict[str, Any] = {
      "case_id": case["id"],
      "position": case.get("position"),
      "description": case.get("description"),
      "checkpoint_fixture": case.get("checkpoint_fixture"),
      "checkpoint_sha256": case.get("checkpoint_sha256"),
      "actor_id": case.get("actor_id"),
      "target_id": case.get("target_id"),
      "expected": copy.deepcopy(case.get("expected", {})),
      "status": "observed" if records is not None else "unknown_unrun",
      "attribution": None,
    }
    if records is not None:
      attribution = decision_archive_attribution(records, synthetic=False, pricing=pricing)
      verdicts = _decision_matrix_predicates(case, records, attribution)
      row["attribution"] = attribution
      row["predicate_verdicts"] = verdicts
      row["acceptance_status"] = _acceptance_status(verdicts)
    else:
      row["blocked_reason"] = "not executed; run the decision-matrix-run command with real driver"
    rows.append(row)

  observed_count = sum(1 for r in rows if r["status"] == "observed")
  statuses = [r.get("acceptance_status") for r in rows if r["status"] == "observed"]
  overall_status = (
    "failed" if "failed" in statuses
    else "unknown" if len(statuses) != len(rows) or "unknown" in statuses
    else "passed"
  )

  return {
    "schema_version": 1,
    "matrix_status": "observed" if observed_count == len(rows) else "unknown_unrun",
    "cases": rows,
    "denominator": {
      "scheduled": len(rows),
      "observed": observed_count,
      "unknown_unrun": len(rows) - observed_count,
    },
    "acceptance_status": overall_status,
    "pricing": copy.deepcopy(pricing) if pricing else copy.deepcopy(PILOT_PRICING),
    "note": "Strategy decision boundaries acceptance matrix covering all 8 specified positions.",
  }


def run_decision_matrix(manifest: dict[str, Any] | None = None, *,
                        run_dir: Path, driver: str | None = None,
                        timeout: float = 90.0,
                        pricing: dict[str, Any] | None = None) -> dict[str, Any]:
  """Execute the 8 matrix cases with real driver, verify 2x catalog import idempotence."""
  if manifest is None:
    manifest = json.loads(DECISION_MATRIX_PATH.read_text())
  cases = manifest.get("cases", [])
  if not cases:
    raise StrategyComparisonError("decision matrix manifest has no cases")

  driver = driver or OFFLINE_DRIVER
  driver_path = Path(driver)
  if not driver_path.is_absolute():
    driver_path = REPO_ROOT / driver_path
  if not driver_path.is_file():
    raise StrategyComparisonError(f"driver is unavailable: {driver}")

  run_dir.mkdir(parents=True, exist_ok=True)
  catalog = run_dir / "catalog.sqlite"
  archives: dict[str, list[dict[str, Any]]] = {}
  catalog_audits: dict[str, Any] = {}

  for case in cases:
    cell_dir = model_bakeoff.cell_dir_for(run_dir, case["id"])
    cell_dir.mkdir(parents=True, exist_ok=True)

    resp_file = cell_dir / "responses.json"
    resp_file.write_text(json.dumps(case["fake_responses"], indent=2))
    log_reqs = cell_dir / "prompt_requests.ndjson"

    ckpt_path = REPO_ROOT / case["checkpoint_fixture"]
    ckpt_data = json.loads(ckpt_path.read_text())

    cmd = f"{sys.executable} {FAKE_TRANSPORT_PATH} --responses {resp_file} --request-log {log_reqs}"
    cell = {
      "id": case["id"],
      "scenario": str(ckpt_data["scenario"]),
      "seed": int(ckpt_data["seed"]),
      "faction0": str(ckpt_data["faction0"]),
      "faction1": str(ckpt_data["faction1"]),
      "llm_side": int(ckpt_data["llm_side"]),
      "gold": int(ckpt_data.get("starting_gold", 300)),
      "max_turns": 1,
      "model": "fake-glm-decision",
      "decision_mode": "strategy",
      "action_encoding": "coordinates",
      "checkpoint_fixture": case["checkpoint_fixture"],
      "allow_partial_turn_checkpoint": bool(case.get("allow_partial_turn_checkpoint", case.get("position") == "resume_at_decision_boundary")),
      "backend": {
        "kind": "command",
        "command": cmd,
      },
      "driver": str(driver_path),
      "budgets": {
        "max_model_calls_per_turn": 8,
        "max_partial_batches_per_turn": 64,
        "query_budget_seconds": 20,
        "turn_timeout": 45,
        "model_timeout": 10,
      },
      "pricing": copy.deepcopy(pricing or PILOT_PRICING),
    }

    resolved = model_bakeoff.resolve_manifest({
      "experiment_kind": "matched",
      "cells": [cell],
    })
    results = model_bakeoff.run_manifest(resolved, run_dir, timeout=timeout)
    res = results[0]
    records = match_report.load_records(res.log_path) if res.log_path.is_file() else []
    archives[case["id"]] = records

    # Import into SQLite catalog twice to verify idempotence
    imported1 = model_bakeoff.import_cells(catalog, results, "strategy-matrix")
    snap1 = _catalog_snapshot(catalog, imported1)
    imported2 = model_bakeoff.import_cells(catalog, results, "strategy-matrix")
    snap2 = _catalog_snapshot(catalog, imported2)
    catalog_audits[case["id"]] = {
      "imported_game_ids": imported1,
      "idempotent": (snap1 == snap2),
      "snapshot": snap1,
    }

  report = build_decision_matrix_report(manifest, archives=archives, pricing=pricing)
  for case_row in report.get("cases", []):
    audit = catalog_audits.get(case_row["case_id"])
    if audit:
      case_row["catalog_import"] = audit
      if not audit["idempotent"]:
        case_row["acceptance_status"] = "failed"
        case_row["predicate_verdicts"]["catalog_import_idempotent"] = False

  statuses = [r.get("acceptance_status") for r in report["cases"]]
  report["acceptance_status"] = (
    "failed" if "failed" in statuses
    else "unknown" if "unknown" in statuses or not statuses
    else "passed"
  )
  return report


def load_prepared_screening(path: Path = SCREENING_MANIFEST_PATH) -> dict[str, Any]:
  try:
    manifest = json.loads(path.read_text())
  except (OSError, json.JSONDecodeError) as exc:
    raise StrategyComparisonError(f"cannot read screening manifest {path}: {exc}") from exc
  if manifest.get("status") != "prepared_not_run":
    raise StrategyComparisonError("screening manifest must remain prepared_not_run until launch authorization")
  return manifest


def main(argv: list[str] | None = None) -> int:
    """Prepare manifests, print reports, or run the provider-free matrix."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pilot = sub.add_parser("pilot-manifest", help="write the prepared pilot manifest")
    pilot.add_argument("--out", required=True)
    report = sub.add_parser("pilot-report", help="write a pilot report from a prepared or recorded run")
    report.add_argument("--manifest", default=str(PILOT_MANIFEST_PATH))
    report.add_argument("--run-dir", help="re-aggregate recorded cells from this run directory")
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
    dm_run = sub.add_parser("decision-matrix-run", help="execute the strategy decision acceptance matrix")
    dm_run.add_argument("--manifest", default=str(DECISION_MATRIX_PATH))
    dm_run.add_argument("--run-dir", required=True)
    dm_run.add_argument("--driver", default=OFFLINE_DRIVER)
    dm_run.add_argument("--timeout", type=float, default=90)
    dm_run.add_argument("--out", required=True)
    dm_report = sub.add_parser("decision-matrix-report", help="report from strategy decision matrix run")
    dm_report.add_argument("--manifest", default=str(DECISION_MATRIX_PATH))
    dm_report.add_argument("--run-dir", help="run directory containing recorded match.ndjson files")
    dm_report.add_argument("--out", required=True)
    screening = sub.add_parser("screening-manifest", help="write the prepared 16-cell screening manifest")
    screening.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if args.command == "pilot-manifest":
        payload = load_prepared_pilot() if Path(args.out).resolve() == PILOT_MANIFEST_PATH.resolve() else build_pilot_manifest()
    elif args.command == "pilot-report":
        if args.run_dir:
            run_dir = Path(args.run_dir)
            saved_manifest = run_dir / "manifest.json"
            if not saved_manifest.is_file():
                raise StrategyComparisonError(f"no resolved manifest at {saved_manifest}")
            resolved = json.loads(saved_manifest.read_text())
            cohort_path = run_dir / "cohort.json"
            cohort_id = (json.loads(cohort_path.read_text()).get("cohort_id")
                         if cohort_path.is_file() else run_dir.name)
            catalog = run_dir / "catalog.sqlite"
            payload = build_strategy_report(
                resolved, _pilot_results_from_run_dir(run_dir, resolved),
                catalog_path=catalog if catalog.is_file() else None,
                cohort_id=cohort_id)
        else:
            payload = build_strategy_report(json.loads(Path(args.manifest).read_text()))
    elif args.command == "offline-report":
        payload = build_offline_matrix_report(json.loads(Path(args.matrix).read_text()))
    elif args.command == "offline-run":
        payload = run_offline_matrix(json.loads(Path(args.matrix).read_text()),
                                     run_dir=Path(args.run_dir), driver=args.driver,
                                     timeout=args.timeout)
    elif args.command == "decision-matrix-run":
        payload = run_decision_matrix(
            json.loads(Path(args.manifest).read_text()),
            run_dir=Path(args.run_dir),
            driver=args.driver,
            timeout=args.timeout,
        )
    elif args.command == "decision-matrix-report":
        archives = None
        if args.run_dir:
            run_dir = Path(args.run_dir)
            manifest = json.loads(Path(args.manifest).read_text())
            archives = {}
            for c in manifest.get("cases", []):
                cid = c["id"]
                match_path = run_dir / cid / "match.ndjson"
                if match_path.is_file():
                    archives[cid] = match_report.load_records(match_path)
        payload = build_decision_matrix_report(
            json.loads(Path(args.manifest).read_text()),
            archives=archives,
        )
    elif args.command == "screening-manifest":
        payload = load_prepared_screening()
    Path(args.out).write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
    if args.command in ("offline-run", "decision-matrix-run") and payload.get("acceptance_status") != "passed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
