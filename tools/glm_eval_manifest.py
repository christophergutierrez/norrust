"""Build and inspect bounded GLM milestone-6 evaluation manifests.

This is a thin experiment layer over ``tools.model_bakeoff``.  It never
launches a provider and never creates a second accounting/report framework.
One matched manifest contains one fixed position and two repeat trials.  The
eight position manifests for a treatment are separate cohorts because the
runner requires every fixed setting in a matched cohort to be identical.

Task predicates, useful actions, and checkpoint fixtures are loaded from the
maintained task matrix; they are not duplicated in this module.
"""
from __future__ import annotations

import argparse
import copy
import json
import shlex
import statistics
from pathlib import Path
from typing import Any

from . import bakeoff_metrics, game_history, match_report, model_bakeoff

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO_ROOT / "tools/fixtures/task_harness/matrix.json"
TREATMENTS = ("stack2_contract_memory", "stack3_stopping_rule", "stack5_batched_movement")
REQUIRED_TRIALS_PER_POSITION = 2
DEFAULT_BUDGETS = {"max_game_total_tokens": 250000, "turn_timeout": 1800}
_FROZEN_FIELDS = (
    "scenario", "seed", "faction0", "faction1", "llm_side", "gold", "max_turns",
    "checkpoint_fixture", "success_predicate", "useful_action", "model",
    "reasoning_effort", "decision_mode", "action_encoding", "incremental_turns", "budgets",
)
_FROZEN_FINGERPRINT_FIELDS = frozenset((*_FROZEN_FIELDS, "backend", "checkpoint_sha256",
                                        "transport_fingerprint"))
_INSPECTION_TOOLS = {"inspect_unit", "inspect_units", "inspect_target", "inspect_targets", "inspect_hex"}


class ManifestSpecError(ValueError):
    """The requested treatment manifest cannot be built or is inconsistent."""


def load_positions(matrix_path: Path = MATRIX_PATH) -> list[dict[str, Any]]:
    """Load the eight canonical positions from arm A of the task matrix."""
    try:
        matrix = json.loads(matrix_path.read_text())
        cells = matrix["cells"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ManifestSpecError(f"cannot read task matrix {matrix_path}: {exc}") from exc
    required = ("position_family", "variant", "scenario", "seed", "faction0", "faction1",
                "llm_side", "gold", "max_turns", "success_predicate", "useful_action")
    positions: list[dict[str, Any]] = []
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("arm") != "A":
            continue
        missing = [key for key in required if key not in cell]
        if missing:
            raise ManifestSpecError(f"task matrix arm-A row is missing {missing}")
        position = copy.deepcopy(cell)
        position["position"] = position.pop("variant")
        positions.append(position)
    positions.sort(key=lambda item: (item["position_family"], item["position"]))
    keys = [(item["position_family"], item["position"]) for item in positions]
    if len(positions) != 8 or len(set(keys)) != len(keys):
        raise ManifestSpecError(f"expected eight unique arm-A positions, found {keys}")
    return positions


# The values are loaded from the matrix at import time; facts are not copied.
POSITIONS = load_positions()
EXPECTED_KEYS = [(p["position_family"], p["position"], trial)
                 for p in POSITIONS for trial in range(1, REQUIRED_TRIALS_PER_POSITION + 1)]


def _position(position_family: str, position: int) -> dict[str, Any]:
    for candidate in POSITIONS:
        if candidate["position_family"] == position_family and candidate["position"] == position:
            return candidate
    available = ", ".join(f"{p['position_family']}:p{p['position']}" for p in POSITIONS)
    raise ManifestSpecError(f"unknown position {position_family}:p{position}; available: {available}")


def _position_cell_id(position: dict[str, Any], trial: int) -> str:
    return f"{position['position_family']}-p{position['position']}-t{trial}"


def build_treatment_manifest(*, treatment: str, model: str, backend_command: str,
                             source_commit: str, worktree_path: str,
                             position_family: str | None = None, position: int | None = None,
                             reasoning_effort: str | None = None, decision_mode: str = "focused",
                             action_encoding: str = "choices", pricing: dict[str, Any] | None = None,
                             seeds_note: str | None = None) -> dict[str, Any]:
    """Build one two-trial matched cohort for a canonical position."""
    if treatment not in TREATMENTS:
        raise ManifestSpecError(f"unknown treatment {treatment!r}; expected one of {TREATMENTS}")
    if position_family is None or position is None:
        raise ManifestSpecError("one matched manifest must name --position-family and --position")
    if decision_mode not in ("batch", "focused") or action_encoding not in ("coordinates", "choices"):
        raise ManifestSpecError("invalid decision_mode/action_encoding")
    if action_encoding == "choices" and decision_mode != "focused":
        raise ManifestSpecError("choices encoding requires focused mode")
    canonical = _position(position_family, position)
    # Repeats must have byte-equal backend settings. Trial identity stays in
    # the cell record and is not smuggled into backend env/fingerprint.
    backend = {"kind": "command", "command": backend_command,
               "env": {"GLM_EVAL_POSITION_FAMILY": position_family,
                       "GLM_EVAL_POSITION": str(position)}}
    cells: list[dict[str, Any]] = []
    for trial in range(1, REQUIRED_TRIALS_PER_POSITION + 1):
        budgets = dict(DEFAULT_BUDGETS)
        budgets["max_partial_batches_per_turn"] = 64 if decision_mode == "focused" else 3
        cells.append({
            "id": _position_cell_id(canonical, trial), "position_family": position_family,
            "position": position, "trial": trial, "match_group": f"{position_family}:p{position}",
            "scenario": canonical["scenario"], "seed": canonical["seed"],
            "faction0": canonical["faction0"], "faction1": canonical["faction1"],
            "llm_side": canonical["llm_side"], "gold": canonical["gold"],
            "max_turns": canonical["max_turns"], "checkpoint_fixture": canonical.get("checkpoint_fixture"),
            "success_predicate": copy.deepcopy(canonical["success_predicate"]),
            "useful_action": copy.deepcopy(canonical["useful_action"]), "model": model,
            "reasoning_effort": reasoning_effort, "decision_mode": decision_mode,
            "action_encoding": action_encoding, "incremental_turns": True, "budgets": budgets,
            "backend": copy.deepcopy(backend),
            **({"pricing": copy.deepcopy(pricing)} if pricing is not None else {}),
        })
    return {"schema_version": 1, "experiment_kind": "matched",
            "objective": f"milestone 6 pilot cell: treatment {treatment}, {position_family}:p{position}",
            "treatment": treatment, "source_commit": source_commit, "worktree_path": worktree_path,
            "seeds_note": seeds_note or "both repeats use the canonical position seed and checkpoint bytes",
            "cells": cells}


def build_all_treatment_manifests(**kwargs: Any) -> list[dict[str, Any]]:
    """Build the eight separate position cohorts for one treatment."""
    return [build_treatment_manifest(**kwargs, position_family=p["position_family"], position=p["position"])
            for p in POSITIONS]


def validate_position_pairs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate repeats and reject a cross-position matched cohort."""
    cells = manifest.get("cells")
    if not isinstance(cells, list) or len(cells) != REQUIRED_TRIALS_PER_POSITION:
        return [{"error": "expected_one_position_two_trials",
                 "found": len(cells) if isinstance(cells, list) else None}]
    groups: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        if isinstance(cell, dict):
            groups.setdefault(str(cell.get("match_group")), []).append(cell)
    mismatches: list[dict[str, Any]] = []
    if len(groups) != 1 or len(next(iter(groups.values()), [])) != REQUIRED_TRIALS_PER_POSITION:
        mismatches.append({"error": "expected_one_position_match_group", "groups": sorted(groups)})
    baseline = cells[0] if isinstance(cells[0], dict) else {}
    for other in cells[1:]:
        if not isinstance(other, dict):
            mismatches.append({"error": "cell_not_object"})
            continue
        for key in sorted(set(baseline) | set(other)):
            if key in {"id", "trial"}:
                continue
            if baseline.get(key) != other.get(key):
                mismatches.append({"field": key, "baseline_cell": baseline.get("id"),
                                   "other_cell": other.get("id"),
                                   "baseline_value": baseline.get(key), "other_value": other.get(key)})
    family, pos = baseline.get("position_family"), baseline.get("position")
    if not isinstance(family, str) or not isinstance(pos, int):
        mismatches.append({"error": "position_identity_missing"})
    else:
        try:
            _position(family, pos)
        except ManifestSpecError as exc:
            mismatches.append({"error": "unknown_position", "detail": str(exc)})
    return mismatches


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Run local checks and the actual runner matched comparison invariant."""
    mismatches = validate_position_pairs(manifest)
    comparison = None
    if not mismatches:
        try:
            resolved = model_bakeoff.resolve_manifest(manifest)
            comparison = model_bakeoff.check_comparison_validity(resolved)
            if not comparison["valid"]:
                mismatches.extend(comparison["mismatches"])
        except (model_bakeoff.ManifestError, OSError, KeyError, TypeError, ValueError) as exc:
            mismatches.append({"error": "runner_resolution_failed", "detail": str(exc)})
    return {"valid": not mismatches, "mismatches": mismatches, "comparison": comparison}


# ---------------------------------------------------------------------------
# Archive analysis: existing match report + physical SQLite model_calls.
# ---------------------------------------------------------------------------

def _game_usage(catalog_path: Path, game_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conn = game_history.open_history(catalog_path, read_only=True)
    try:
        calls = game_history.query_usage(conn, game_id, "call").get("calls", [])
        coverage = game_history.query_usage(conn, game_id, "game")
    finally:
        conn.close()
    return coverage, calls


def _count_rejected_agendas(records: list[dict[str, Any]]) -> int:
    return sum(1 for item in records if item.get("type") == "agenda_error")


def _count_invalid_batches(records: list[dict[str, Any]]) -> int:
    return sum(1 for item in records
               if item.get("type") == "batch_validation" and item.get("valid") is not True
               and item.get("reason") != "partial_limit_finish")


def _count_inspections(records: list[dict[str, Any]]) -> int | None:
    """Read model inspection calls from cumulative client metadata.

    A grouped inspection has one model tool call but may contain several
    underlying driver facts, and a failed repair can have a driver query with
    no tool-result record.  Counting those records would measure transport
    shape rather than model behavior.  The terminal/latest metadata counter
    is updated for both successful and repair paths; absent or malformed
    counters remain unknown.
    """
    terminal = match_report.terminal_record(records)
    if terminal is None:
        return None
    counter = terminal.get("tool_calls_by_name")
    if not isinstance(counter, dict):
        return None
    values = [counter.get(tool, 0) for tool in _INSPECTION_TOOLS]
    if not all(type(value) is int and value >= 0 for value in values):
        return None
    return sum(values)


def _count_driver_inspection_queries(records: list[dict[str, Any]]) -> int:
    """Count raw driver inspection replies separately from model tool calls."""
    return sum(1 for item in records
               if item.get("type") == "query"
               and isinstance(item.get("line"), dict)
               and item["line"].get("what") in _INSPECTION_TOOLS)


def _count_repairs(records: list[dict[str, Any]]) -> int:
    """Count recorded model repair attempts, including review repairs."""
    return sum(1 for item in records
               if item.get("type") in {"repair", "action_repair", "draft_review_repair"})


def _frozen_fingerprint(cell: dict[str, Any]) -> dict[str, Any]:
    provenance = cell.get("provenance") if isinstance(cell.get("provenance"), dict) else {}
    frozen = {key: copy.deepcopy(cell.get(key)) for key in _FROZEN_FIELDS}
    # Relative fixture names are useful provenance, but the resolved bytes and
    # transport settings are the comparison facts. Unknown hashes remain None
    # and make the later promotion gate inconclusive.
    frozen.update({"backend": copy.deepcopy(cell.get("backend")),
                   "checkpoint_sha256": provenance.get("checkpoint_sha256"),
                   "transport_fingerprint": provenance.get("transport_fingerprint")})
    return frozen


def _invalid_frozen_fingerprint(fingerprint: Any) -> list[str]:
    """Return missing or unusable frozen evidence fields.

    A report may only compare cells after resolution has supplied every
    projection field.  ``None`` remains valid for a deliberately unset
    setting such as reasoning effort, and for checkpoint SHA when that cell
    has no checkpoint fixture; missing keys are always an evidence gap.
    """
    if not isinstance(fingerprint, dict):
        return ["frozen_fingerprint"]
    missing = sorted(_FROZEN_FINGERPRINT_FIELDS - set(fingerprint))
    if missing:
        return missing
    invalid: list[str] = []
    if not isinstance(fingerprint.get("backend"), dict) or not fingerprint["backend"]:
        invalid.append("backend")
    if not isinstance(fingerprint.get("transport_fingerprint"), str) or not fingerprint["transport_fingerprint"]:
        invalid.append("transport_fingerprint")
    if fingerprint.get("checkpoint_fixture") and (
            not isinstance(fingerprint.get("checkpoint_sha256"), str)
            or not fingerprint["checkpoint_sha256"]):
        invalid.append("checkpoint_sha256")
    return invalid


def analyze_cell_archive(records: list[dict[str, Any]], cell: dict[str, Any], *,
                         catalog_path: Path | None = None, game_id: str | None = None) -> dict[str, Any]:
    """Analyze one archive; measured usage can only come from SQLite calls."""
    classified = match_report.classify(records)
    llm_side = int(cell.get("llm_side", 0))
    success = model_bakeoff.evaluate_objective(records, cell.get("success_predicate"), llm_side)
    recruiter = model_bakeoff.recruiter_status(records)
    recruiter_side = recruiter.get(f"side{llm_side}") if not recruiter.get("unknown") else None
    recruiter_survival = any(entry.get("alive") for entry in recruiter_side) if recruiter_side is not None else None
    physical_calls: list[dict[str, Any]] | None = None
    usage: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    if catalog_path is not None:
        if not game_id:
            raise ManifestSpecError("game_id is required when catalog_path is supplied")
        coverage, physical_calls = _game_usage(catalog_path, game_id)
        usage = bakeoff_metrics.aggregate_usage(
            physical_calls, model=cell.get("model"), price_date=(cell.get("pricing") or {}).get("date"),
            custom_prices=(cell.get("pricing") or {}).get("rates"))
    trial = bakeoff_metrics.evaluate_trial_actions(
        records, useful_spec=cell.get("useful_action") if isinstance(cell.get("useful_action"), dict) else None,
        physical_calls=physical_calls)
    elapsed_seconds = (trial["ms_to_first_useful"] / 1000
                       if isinstance(trial.get("ms_to_first_useful"), (int, float)) else None)
    terminal_reason, completed, expected = classified.get("reason"), classified.get("completed_side_turns"), cell.get("max_turns")
    premature_finish = None
    if isinstance(terminal_reason, str) and isinstance(completed, int) and isinstance(expected, int):
        premature_finish = terminal_reason not in ("max_turns", "turn_limit") and success is not True and completed < expected
    entry: dict[str, Any] = {
        "cell_id": cell.get("id"), "position_family": cell.get("position_family"),
        "position": cell.get("position"), "trial": cell.get("trial"), "task_success": success,
        "recruiter_survival": recruiter_survival, "premature_finish": premature_finish,
        "terminal_class": classified.get("terminal_class"), "terminal_reason": terminal_reason,
        "invalid_actions": _count_invalid_batches(records), "rejected_agendas": _count_rejected_agendas(records),
        "inspections": _count_inspections(records),
        "driver_inspection_queries": _count_driver_inspection_queries(records),
        "repairs": _count_repairs(records),
        "repairs_coverage": ("complete" if any(item.get("type") == "terminal" for item in records)
                              else "observed_truncated"),
        "harness_requests": classified.get("model_calls"),
        "first_legal_action": trial.get("first_legal_action"), "first_useful_action": trial.get("first_useful_action"),
        "useful_action_achieved": trial.get("useful_action_achieved"),
        "time_to_first_useful_committed_action_seconds": elapsed_seconds,
        "tokens_to_first_useful": trial.get("tokens_to_first_useful"),
        "decision_annotations": classified.get("decision_annotations"),
        "frozen_fingerprint": _frozen_fingerprint(cell), "provenance": copy.deepcopy(cell.get("provenance")),
        "treatment_fingerprint": {key: (cell.get("provenance") or {}).get(key)
                                   for key in ("source_commit", "dirty_patch_hash", "guide_hash", "driver_hash")},
    }
    if usage is None:
        for field in ("model_calls", "total_tokens", "reasoning_tokens", "input_tokens", "cached_input_tokens",
                      "output_tokens", "known_cost", "usage_coverage", "cost_coverage", "field_coverage"):
            entry[field] = "unknown_not_imported"
        entry["aggregate_only_request_ids"] = "unknown_not_imported"
        entry["unassigned_calls"] = "unknown_not_imported"
    else:
        entry.update({"model_calls": usage["physical_calls"], "total_tokens": usage["total_tokens"],
                      "reasoning_tokens": usage["reasoning_tokens"], "input_tokens": usage["input_tokens"],
                      "cached_input_tokens": usage["cached_input_tokens"], "output_tokens": usage["output_tokens"],
                      "known_cost": usage["known_cost"], "usage_coverage": usage["usage_coverage"],
                      "cost_coverage": usage["cost_coverage"], "field_coverage": usage["field_coverage"],
                      "physical_usage": usage, "aggregate_only_request_ids": coverage.get("aggregate_only_request_ids"),
                      "unassigned_calls": coverage.get("unassigned_calls")})
    return entry


def _median(values: list[int | float]) -> float | None:
    return statistics.median(values) if values else None


def _paired_comparison(predecessor: str, candidate: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    pred_entries = [row[predecessor] for row in rows if row.get(predecessor) is not None]
    cand_entries = [row[candidate] for row in rows if row.get(candidate) is not None]
    pairs = [row for row in rows if row.get(predecessor) is not None and row.get(candidate) is not None]
    complete_pair_schedule = len(rows) == len(EXPECTED_KEYS) and len(pairs) == len(EXPECTED_KEYS)
    def reasoning_complete(entry: dict[str, Any]) -> bool:
        coverage = entry.get("field_coverage")
        reasoning_cov = coverage.get("reasoning_tokens") if isinstance(coverage, dict) else None
        return (entry.get("task_success") is True and isinstance(entry.get("reasoning_tokens"), int)
                and entry.get("usage_coverage") == "complete"
                and entry.get("unassigned_calls") == 0
                and entry.get("aggregate_only_request_ids") == []
                and isinstance(reasoning_cov, dict) and reasoning_cov.get("fully_measured") is True)

    usable = [row for row in pairs if reasoning_complete(row[predecessor]) and reasoning_complete(row[candidate])]
    before = _median([row[predecessor]["reasoning_tokens"] for row in usable])
    after = _median([row[candidate]["reasoning_tokens"] for row in usable])
    improvement = ((before - after) / before if before and after is not None else None)
    pred_success, cand_success = sum(e.get("task_success") is True for e in pred_entries), sum(e.get("task_success") is True for e in cand_entries)
    def total_count(entries: list[dict[str, Any]], field: str) -> int | None:
        values = [entry.get(field) for entry in entries]
        if len(values) != len(EXPECTED_KEYS) or not all(isinstance(value, int) for value in values):
            return None
        return sum(values)

    pred_invalid, cand_invalid = total_count(pred_entries, "invalid_actions"), total_count(cand_entries, "invalid_actions")
    pred_premature, cand_premature = total_count(pred_entries, "premature_finish"), total_count(cand_entries, "premature_finish")
    # Recruiter safety is a defense-position criterion.  Aggregate losses
    # across unrelated families could hide a new defense failure.
    defense_rows = [row for row in rows if row.get("position_family") == "recruiter_defense"]
    defense_new_loss_free: bool | None = True
    for row in defense_rows:
        old, new = row.get(predecessor), row.get(candidate)
        if old is None or new is None or not isinstance(old.get("recruiter_survival"), bool) or not isinstance(new.get("recruiter_survival"), bool):
            defense_new_loss_free = None
            continue
        if old["recruiter_survival"] and not new["recruiter_survival"]:
            defense_new_loss_free = False
    checks = {
        "candidate_successes_at_least_predecessor": cand_success >= pred_success if complete_pair_schedule and all(e.get("task_success") in (True, False) for e in pred_entries + cand_entries) else None,
        "candidate_recruiter_loss_not_increased_in_defense": defense_new_loss_free if complete_pair_schedule else None,
        "invalid_actions_not_increased": (cand_invalid <= pred_invalid if cand_invalid is not None and pred_invalid is not None else None),
        "premature_finishes_not_increased": (cand_premature <= pred_premature if cand_premature is not None and pred_premature is not None else None),
        "usable_success_pairs_at_least_8": len(usable) >= 8 if complete_pair_schedule else None,
        "reasoning_improvement_at_least_25_percent": (improvement is not None and improvement >= 0.25) if complete_pair_schedule and len(usable) >= 8 else None,
    }
    promotion = None if any(value is None for value in checks.values()) else all(checks.values())
    return {"predecessor": predecessor, "candidate": candidate,
            "denominator": {"scheduled_pairs": len(rows), "paired_cells": len(pairs),
                             "predecessor_cells": len(pred_entries), "candidate_cells": len(cand_entries)},
            "successes": {"predecessor": pred_success, "candidate": cand_success},
            "invalid_actions": {"predecessor": pred_invalid, "candidate": cand_invalid},
            "premature_finishes": {"predecessor": pred_premature, "candidate": cand_premature},
            "usable_success_pairs": len(usable), "median_reasoning_tokens": {"predecessor": before, "candidate": after},
            "reasoning_improvement_fraction": improvement, "checks": checks, "promotion_eligible": promotion}


def cross_treatment_report(reports_by_treatment: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Explicitly pair treatment cells and apply the predeclared screening gates."""
    keyed: dict[str, dict[tuple[Any, Any, Any], dict[str, Any]]] = {}
    duplicate_keys: dict[str, list[tuple[Any, Any, Any]]] = {}
    unexpected_keys: dict[str, list[tuple[Any, Any, Any]]] = {}
    for treatment, entries in reports_by_treatment.items():
        keyed[treatment] = {}
        for entry in entries:
            key = (entry.get("position_family"), entry.get("position"), entry.get("trial"))
            if key in keyed[treatment]:
                duplicate_keys.setdefault(treatment, []).append(key)
            keyed[treatment][key] = entry
            if key not in EXPECTED_KEYS:
                unexpected_keys.setdefault(treatment, []).append(key)
    # The schedule is fixed by the canonical matrix.  Missing entries in every
    # treatment still appear, so absent archives cannot shrink the denominator.
    all_keys = list(EXPECTED_KEYS)
    rows, frozen_mismatches, fingerprint_unknown = [], [], []
    for key in all_keys:
        row: dict[str, Any] = {"position_family": key[0], "position": key[1], "trial": key[2]}
        frozen, owner = None, None
        for treatment in reports_by_treatment:
            entry = keyed[treatment].get(key)
            row[treatment] = entry
            if entry is not None:
                candidate = entry.get("frozen_fingerprint")
                invalid_fields = _invalid_frozen_fingerprint(candidate)
                if invalid_fields:
                    fingerprint_unknown.append({"key": key, "treatment": treatment,
                                                "fields": invalid_fields})
                else:
                    if frozen is None:
                        frozen, owner = candidate, treatment
                    elif candidate != frozen:
                        frozen_mismatches.append({"key": key, "baseline_treatment": owner,
                                                  "treatment": treatment, "baseline": frozen,
                                                  "candidate": candidate})
                treatment_fingerprint = entry.get("treatment_fingerprint")
                if (not isinstance(treatment_fingerprint, dict)
                        or any(treatment_fingerprint.get(field) in (None, "")
                               for field in ("source_commit", "guide_hash", "driver_hash"))):
                    fingerprint_unknown.append({"key": key, "treatment": treatment,
                                                "fields": ["source_commit", "guide_hash", "driver_hash"]})
        rows.append(row)
    treatments = list(reports_by_treatment)
    comparisons = [_paired_comparison(a, b, rows) for a, b in zip(treatments, treatments[1:])]
    missing = {t: sorted(set(all_keys) - set(keyed[t])) for t in treatments}
    treatment_fingerprints = {t: sorted({json.dumps((entry.get("treatment_fingerprint") or {}), sort_keys=True)
                                         for entry in entries})
                              for t, entries in reports_by_treatment.items()}
    treatment_fingerprint_mismatches = {
        treatment: values for treatment, values in treatment_fingerprints.items() if len(values) > 1
    }
    incomplete = bool(duplicate_keys or unexpected_keys or frozen_mismatches or fingerprint_unknown
                      or treatment_fingerprint_mismatches or any(missing.values()))
    # A missing/duplicate/mismatched record is a known apparatus failure. The
    # metric checks themselves remain explicit unknowns; no promotion can pass.
    if incomplete:
        for comparison in comparisons:
            comparison["checks"]["manifest_integrity"] = False
            comparison["promotion_eligible"] = False
    return {"rows": rows, "treatments": treatments, "treatment_fingerprints": treatment_fingerprints,
            "denominator": {"scheduled_cells": len(all_keys), "expected_cells_per_treatment": len(EXPECTED_KEYS),
                             "missing_by_treatment": missing},
            "duplicate_keys": duplicate_keys, "frozen_mismatches": frozen_mismatches,
            "unexpected_keys": unexpected_keys,
            "fingerprint_unknown": fingerprint_unknown,
            "treatment_fingerprint_mismatches": treatment_fingerprint_mismatches,
            "manifest_integrity": not incomplete, "comparisons": comparisons,
            "note": "Missing archives, calls, tokens, and predicates remain unknown and stay in denominators."}


def _read_pricing(path: str | None) -> dict[str, Any] | None:
    return json.loads(Path(path).read_text()) if path else None


def _build_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {"treatment": args.treatment, "model": args.model, "backend_command": args.backend_command,
            "source_commit": args.source_commit, "worktree_path": args.worktree_path,
            "position_family": getattr(args, "position_family", None), "position": getattr(args, "position", None),
            "reasoning_effort": args.reasoning_effort, "decision_mode": args.decision_mode,
            "action_encoding": args.action_encoding, "pricing": _read_pricing(args.pricing)}


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--treatment", required=True, choices=TREATMENTS)
    parser.add_argument("--model", required=True); parser.add_argument("--backend-command", required=True)
    parser.add_argument("--source-commit", required=True); parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--reasoning-effort", default=None); parser.add_argument("--decision-mode", default="focused")
    parser.add_argument("--action-encoding", default="choices"); parser.add_argument("--pricing")


def _cmd_build(args: argparse.Namespace) -> int:
    manifest = build_treatment_manifest(**_build_kwargs(args)); result = validate_manifest(manifest)
    if not result["valid"]:
        print(json.dumps({"error": "manifest_self_check_failed", **result}, indent=2)); return 1
    Path(args.out).write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out} (2 cells; one matched position cohort)"); return 0


def _cmd_build_all(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    kwargs = _build_kwargs(args); kwargs.pop("position_family"); kwargs.pop("position")
    for manifest in build_all_treatment_manifests(**kwargs):
        result = validate_manifest(manifest)
        if not result["valid"]:
            print(json.dumps({"error": "manifest_self_check_failed", **result}, indent=2)); return 1
        cell = manifest["cells"][0]
        path = out_dir / f"{manifest['treatment']}-{cell['position_family']}-p{cell['position']}.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(POSITIONS)} manifests to {out_dir}"); return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    result = validate_manifest(json.loads(Path(args.manifest).read_text()))
    print(json.dumps(result, indent=2)); return 0 if result["valid"] else 1


def _cmd_analyze(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text()); by_id = {c["id"]: c for c in manifest.get("cells", [])}
    if args.cell_id not in by_id:
        raise ManifestSpecError(f"unknown cell {args.cell_id!r}")
    records = match_report.load_records(args.archive)
    result = analyze_cell_archive(records, by_id[args.cell_id], catalog_path=Path(args.catalog) if args.catalog else None,
                                  game_id=args.game_id)
    print(json.dumps(result, indent=2)); return 0


def _cmd_dry_run(args: argparse.Namespace) -> int:
    manifest = json.loads(Path(args.manifest).read_text()); resolved = model_bakeoff.resolve_manifest(manifest)
    comparison = model_bakeoff.check_comparison_validity(resolved)
    if not comparison["valid"]:
        print(json.dumps({"valid": False, "comparison": comparison}, indent=2)); return 1
    commands = []
    for cell in resolved["cells"]:
        argv, env = model_bakeoff.build_llm_client_argv(cell, Path(args.run_dir) / cell["id"])
        commands.append({"cell_id": cell["id"], "argv": shlex.join(argv),
                         "env_overrides": {k: v for k, v in env.items()
                                            if k.startswith("NORRUST_") or k.startswith("GLM_EVAL_")}})
    print(json.dumps({"valid": True, "cohort": args.cohort,
                      "runner_command": f"python3 -m tools.model_bakeoff run {args.manifest} --run-dir {args.run_dir} --cohort {args.cohort}",
                      "cells": commands}, indent=2)); return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-manifest"); _common(build); build.add_argument("--position-family", required=True)
    build.add_argument("--position", required=True, type=int); build.add_argument("--out", required=True); build.set_defaults(func=_cmd_build)
    all_build = sub.add_parser("build-manifests"); _common(all_build); all_build.add_argument("--out-dir", required=True); all_build.set_defaults(func=_cmd_build_all)
    validate = sub.add_parser("validate"); validate.add_argument("--manifest", required=True); validate.set_defaults(func=_cmd_validate)
    analyze = sub.add_parser("analyze"); analyze.add_argument("--manifest", required=True); analyze.add_argument("--cell-id", required=True)
    analyze.add_argument("--archive", required=True); analyze.add_argument("--catalog"); analyze.add_argument("--game-id"); analyze.set_defaults(func=_cmd_analyze)
    dry = sub.add_parser("dry-run"); dry.add_argument("--manifest", required=True); dry.add_argument("--run-dir", required=True)
    dry.add_argument("--cohort", required=True); dry.set_defaults(func=_cmd_dry_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv); return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
