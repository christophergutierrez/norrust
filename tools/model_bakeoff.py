"""Reproducible matched model comparison runner and report (S4).

Reuses `tools.llm_client` for isolated client runs, `tools.match_report` for
per-match classification, and `tools.game_history` for catalog import. This
module does not create a parallel database, a provider abstraction, or a
second report format.

A manifest is an explicit list of cells (scenario, seed, factions, LLM side,
gold, cap, budgets, selected model/effort, and backend command configuration).
`resolve_manifest` resolves any random settings exactly once and records
source commit, dirty-patch hash, driver hash, guide hash, and the requested
model identity for every cell before anything runs. `run_manifest` executes
each cell as its own isolated `tools.llm_client` process (own log, checkpoint
directory, request files/journal, session sidecar, identity, and exit
status) and never silently restarts a failed cell as an unrecorded fresh
game. `build_report` aggregates every *scheduled* cell -- including ones that
did not run, produced an invalid model response, or failed for
infrastructure reasons -- with explicit denominators, so a report can never
make a model look silently stronger by excluding its failures.

For the subagent/file transport, this module only wires the plumbing
(`--model-command 'python3 -m tools.file_backend --directory <cell requests
dir>'`); Python cannot itself select a host subagent model, so the
coordinator must start one persistent player per such cell using the host's
own subagent API and point it at that cell's request directory. That handoff
is documented, not invented: there is no nested model CLI or unsupported SDK
here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import game_history
from . import match_report
from .decision_annotations import guide_hash as _annotation_guide_hash
from .llm_client import load_tactical_playbook, source_metadata

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DRIVER = "norrust_core/target/debug/greedy_driver"

REQUIRED_CELL_KEYS = ("id", "scenario", "seed", "faction0", "faction1",
                      "llm_side", "gold", "max_turns", "model", "backend")

# Fields that must match across every cell being compared, unless a
# baseline/candidate experiment explicitly declares exactly one of them as
# its permitted change.
FINGERPRINT_KEYS = ("guide_hash", "driver_hash", "source_commit", "dirty_patch_hash")
FIXED_SETTING_KEYS = ("scenario", "gold", "max_turns")

_BUDGET_FLAGS = {
    "turn_timeout": "--turn-timeout",
    "query_budget_seconds": "--query-budget-seconds",
    "max_queries_per_turn": "--max-queries-per-turn",
    "max_model_calls_per_turn": "--max-model-calls-per-turn",
    "max_tool_calls_per_turn": "--max-tool-calls-per-turn",
    "token_input_limit": "--token-input-limit",
    "token_output_limit": "--token-output-limit",
    "token_total_limit": "--token-total-limit",
}


class ManifestError(ValueError):
    """The manifest is missing, malformed, or ambiguous."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _driver_hash(driver: str) -> str | None:
    path = Path(driver)
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guide_hash() -> str:
    """Hash of the exact tactical-playbook text every prompt currently ships."""
    return _annotation_guide_hash(load_tactical_playbook())


# ---------------------------------------------------------------------------
# Manifest resolution
# ---------------------------------------------------------------------------

def resolve_manifest(manifest: dict[str, Any], *, rng: random.Random | None = None) -> dict[str, Any]:
    """Resolve random settings once and stamp provenance onto every cell.

    Returns a new manifest; the caller's object is never mutated. Re-resolving
    an already-resolved manifest keeps its previously resolved seeds (a
    concrete int is left alone) and simply refreshes provenance, so this is
    safe to call again against the same on-disk manifest file.
    """
    rng = rng or random.Random()
    resolved = json.loads(json.dumps(manifest))
    cells = resolved.get("cells")
    if not isinstance(cells, list) or not cells:
        raise ManifestError("manifest must declare a non-empty 'cells' list")
    guide = guide_hash()
    driver_hashes: dict[str, str | None] = {}
    seen_ids: set[str] = set()
    for cell in cells:
        missing = [key for key in REQUIRED_CELL_KEYS if key not in cell]
        if missing:
            raise ManifestError(f"cell missing required field(s): {missing}")
        cell_id = cell["id"]
        if not isinstance(cell_id, str) or not cell_id:
            raise ManifestError("cell 'id' must be a non-empty string")
        if cell_id in seen_ids:
            raise ManifestError(f"duplicate cell id: {cell_id!r}")
        seen_ids.add(cell_id)
        if cell["seed"] == "random":
            cell["seed"] = rng.randrange(1, 2 ** 31 - 1)
        elif not isinstance(cell["seed"], int) or isinstance(cell["seed"], bool):
            raise ManifestError(f"cell {cell_id!r}: seed must be an int or the literal 'random'")
        driver = cell.get("driver") or resolved.get("driver") or DEFAULT_DRIVER
        cell["driver"] = driver
        if driver not in driver_hashes:
            driver_hashes[driver] = _driver_hash(driver)
        provenance = {
            "guide_hash": guide,
            "driver_hash": driver_hashes[driver],
            "requested_model": cell.get("model"),
            "requested_reasoning_effort": cell.get("reasoning_effort"),
        }
        provenance.update(source_metadata())
        cell["provenance"] = provenance
        cell["budgets"] = dict(cell.get("budgets") or {})
        cell.setdefault("configuration", cell.get("model"))
    resolved["resolved_at"] = _now()
    resolved.setdefault("experiment_kind", "matched")
    return resolved


# ---------------------------------------------------------------------------
# Running cells
# ---------------------------------------------------------------------------

@dataclass
class CellRunResult:
    cell_id: str
    cell_dir: Path
    log_path: Path
    exit_code: int | None
    started_at: str
    ended_at: str | None
    status: str  # "ok" | "failed" | "error" | "not_run"
    error: str | None = None


def _safe_dirname(cell_id: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in cell_id) or "cell"


def cell_dir_for(run_dir: Path, cell_id: str) -> Path:
    return run_dir / _safe_dirname(cell_id)


def write_identity(cell_dir: Path, cell: dict[str, Any]) -> None:
    """Write the identity.json sidecar `tools.recorded_games` already reads."""
    identity = {
        "requested": {
            "llm_player_model": cell.get("model"),
            "llm_side": cell.get("llm_side"),
            "seed": cell.get("seed"),
            "scenario": cell.get("scenario"),
            "gold": cell.get("gold"),
            "max_turns": cell.get("max_turns"),
            "faction0": cell.get("faction0"),
            "faction1": cell.get("faction1"),
            "reasoning_effort": cell.get("reasoning_effort"),
        },
        "backend": {"kind": cell.get("backend", {}).get("kind")},
        "provenance": cell.get("provenance"),
    }
    (cell_dir / "identity.json").write_text(json.dumps(identity, sort_keys=True, indent=2))


def build_llm_client_argv(cell: dict[str, Any], cell_dir: Path) -> tuple[list[str], dict[str, str]]:
    """Build the isolated `python -m tools.llm_client` command for one cell.

    Every cell gets its own `--log` (and therefore its own `.ckpt`
    checkpoint directory, since `tools.llm_client` derives that from the log
    path) under `cell_dir`.
    """
    log_path = cell_dir / "match.ndjson"
    argv = [sys.executable, "-m", "tools.llm_client",
            "--driver", cell["driver"],
            "--scenario", cell["scenario"],
            "--faction0", cell["faction0"], "--faction1", cell["faction1"],
            "--gold", str(cell["gold"]), "--seed", str(cell["seed"]),
            "--llm-side", str(cell["llm_side"]), "--max-turns", str(cell["max_turns"]),
            "--log", str(log_path)]
    for key, flag in _BUDGET_FLAGS.items():
        value = cell.get("budgets", {}).get(key)
        if value is not None:
            argv += [flag, str(value)]
    if cell.get("reasoning_effort"):
        argv += ["--reasoning-effort", cell["reasoning_effort"]]
    if cell.get("incremental_turns"):
        argv.append("--incremental-turns")
    extra_args = cell.get("extra_client_args")
    if isinstance(extra_args, list):
        argv += [str(item) for item in extra_args]

    backend = cell.get("backend") or {}
    kind = backend.get("kind")
    env = dict(os.environ)
    if kind == "orders_file":
        path = backend.get("path")
        if not path:
            raise ManifestError(f"cell {cell['id']!r}: orders_file backend requires 'path'")
        argv += ["--orders-file", str(path)]
    elif kind == "command":
        command = backend.get("command")
        if not command:
            raise ManifestError(f"cell {cell['id']!r}: command backend requires 'command'")
        argv += ["--model-command", command]
        env.update({str(key): str(value) for key, value in (backend.get("env") or {}).items()})
    elif kind == "file":
        # Subagent/file workflow: this only wires the file-transport backend
        # and creates the request directory. Python cannot select a host
        # subagent model itself -- the coordinator must separately start one
        # persistent player per cell (using the host's own subagent API)
        # pointed at this exact directory before the run below will proceed
        # past its first `waiting_*` marker.
        requests_dir = cell_dir / "requests"
        requests_dir.mkdir(parents=True, exist_ok=True)
        argv += ["--model-command",
                 f"{sys.executable} -m tools.file_backend --directory {requests_dir}"]
    elif kind == "codex":
        argv += ["--model-command", f"{sys.executable} -m tools.codex_backend"]
        env["NORRUST_CODEX_MODEL"] = str(cell.get("model"))
        if cell.get("reasoning_effort"):
            env["NORRUST_CODEX_REASONING_EFFORT"] = str(cell["reasoning_effort"])
        env.setdefault("NORRUST_CODEX_SESSION_FILE", str(cell_dir / "session.json"))
        env.setdefault("NORRUST_CODEX_ARTIFACT_DIR", str(cell_dir / "artifacts"))
        env.setdefault("NORRUST_CODEX_MATCH_ID", cell["id"])
    else:
        raise ManifestError(f"cell {cell['id']!r}: unsupported backend kind {kind!r}")
    return argv, env


def run_cell(cell: dict[str, Any], run_dir: Path, *, timeout: float | None = None) -> CellRunResult:
    """Run exactly one cell as its own isolated client process."""
    cell_dir = cell_dir_for(run_dir, cell["id"])
    cell_dir.mkdir(parents=True, exist_ok=True)
    write_identity(cell_dir, cell)
    log_path = cell_dir / "match.ndjson"
    started = _now()
    argv, env = build_llm_client_argv(cell, cell_dir)
    stderr_path = cell_dir / "client_stderr.log"
    exit_code: int | None
    try:
        with open(stderr_path, "w") as stderr_file:
            completed = subprocess.run(argv, cwd=str(REPO_ROOT), env=env,
                                       stdout=subprocess.DEVNULL, stderr=stderr_file,
                                       timeout=timeout)
        exit_code = completed.returncode
        status = "ok" if exit_code == 0 else "failed"
        error = None if exit_code == 0 else f"client exited {exit_code}; see {stderr_path.name}"
    except subprocess.TimeoutExpired:
        exit_code, status, error = None, "failed", "timeout waiting for client process"
    except OSError as exc:
        exit_code, status, error = None, "error", str(exc)
    ended = _now()
    result = CellRunResult(cell["id"], cell_dir, log_path, exit_code, started, ended, status, error)
    _write_run_status(result)
    return result


def _write_run_status(result: CellRunResult) -> None:
    (result.cell_dir / "run_status.json").write_text(json.dumps({
        "cell_id": result.cell_id, "status": result.status, "exit_code": result.exit_code,
        "started_at": result.started_at, "ended_at": result.ended_at, "error": result.error,
    }, sort_keys=True, indent=2))


def _load_run_status(cell_dir: Path, cell_id: str) -> CellRunResult | None:
    path = cell_dir / "run_status.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text())
    return CellRunResult(cell_id, cell_dir, cell_dir / "match.ndjson", payload.get("exit_code"),
                         payload.get("started_at", ""), payload.get("ended_at"),
                         payload.get("status", "error"), payload.get("error"))


def run_manifest(resolved_manifest: dict[str, Any], run_dir: Path, *, only_cell: str | None = None,
                 force: bool = False, timeout: float | None = None) -> list[CellRunResult]:
    """Run scheduled cells sequentially by default.

    Pass `only_cell` to run exactly one manifest cell, which is how a
    coordinator runs independent cells in parallel: one `run_manifest` call
    per cell, all sharing the same `run_dir`. A cell that already recorded a
    `run_status.json` (from an earlier attempt, successful or not) is
    reported from that record rather than silently restarted as an
    unrecorded fresh game, unless `force=True`.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        manifest_path.write_text(json.dumps(resolved_manifest, sort_keys=True, indent=2))
    results = []
    for cell in resolved_manifest["cells"]:
        if only_cell is not None and cell["id"] != only_cell:
            continue
        cell_dir = cell_dir_for(run_dir, cell["id"])
        if not force:
            previous = _load_run_status(cell_dir, cell["id"])
            if previous is not None:
                results.append(previous)
                continue
        results.append(run_cell(cell, run_dir, timeout=timeout))
    return results


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _load_publication_records(cell_dir: Path) -> list[dict[str, Any]] | None:
    path = cell_dir / "requests" / "validation_log.ndjson"
    if not path.is_file():
        return None
    return match_report.load_records(path)


def _driver_state_lines(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = []
    for item in records:
        if item.get("type") != "driver":
            continue
        line = item.get("line")
        if isinstance(line, dict) and line.get("type") == "state":
            lines.append(line)
    return lines


def villages_at_round5_side0(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Village ownership at the start of round 5, before side 0 acts.

    The engine's `turn` field advances only when play returns to side 0, so
    the state where `turn == 5` and `active_faction == 0` is exactly that
    boundary -- provided it is a full boundary, not a mid-turn partial
    observation. If no such state was ever logged (the game ended earlier,
    or the boundary evidence is a partial/checkpoint-only snapshot), this
    reports `unknown` rather than interpolating from whatever is closest.
    """
    for line in _driver_state_lines(records):
        if line.get("turn") != 5 or line.get("active_faction") != 0:
            continue
        if line.get("turn_boundary") == "partial":
            continue
        terrain = line.get("terrain")
        if not isinstance(terrain, list):
            continue
        counts = {"side0": 0, "side1": 0, "neutral": 0}
        for tile in terrain:
            if not isinstance(tile, dict) or tile.get("terrain_id") != "village":
                continue
            owner = tile.get("owner")
            if owner == 0:
                counts["side0"] += 1
            elif owner == 1:
                counts["side1"] += 1
            else:
                counts["neutral"] += 1
        return {"unknown": False, "round": 5, **counts}
    return {"unknown": True, "round": 5, "side0": None, "side1": None, "neutral": None}


def _final_state(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    terminal = next((r for r in reversed(records) if r.get("type") == "terminal"), None)
    if isinstance(terminal, dict) and isinstance(terminal.get("state"), dict):
        return terminal["state"]
    lines = _driver_state_lines(records)
    return lines[-1] if lines else None


def recruiter_status(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Live recruiter presence/HP/position per side from the last known state."""
    state = _final_state(records)
    if not isinstance(state, dict) or not isinstance(state.get("units"), list):
        return {"unknown": True, "side0": [], "side1": []}
    result: dict[str, Any] = {"unknown": False, "side0": [], "side1": []}
    for unit in state["units"]:
        if not isinstance(unit, dict) or not unit.get("can_recruit"):
            continue
        faction = unit.get("faction")
        if faction not in (0, 1):
            continue
        hp = unit.get("hp")
        result[f"side{faction}"].append({
            "unit_id": unit.get("id"), "hp": hp, "max_hp": unit.get("max_hp"),
            "col": unit.get("col"), "row": unit.get("row"),
            "alive": isinstance(hp, int) and hp > 0,
        })
    return result


def resignation_rationale(records: list[dict[str, Any]], terminal: dict[str, Any]) -> dict[str, Any] | None:
    """Recorded resignation rationale, when the match ended that way."""
    if terminal.get("reason") != "resignation":
        return None
    for batch in reversed(records):
        if batch.get("type") != "forwarded_orders":
            continue
        orders = batch.get("orders")
        if not isinstance(orders, list) or not any(
                isinstance(order, dict) and order.get("action") == "Resign" for order in orders):
            continue
        annotation = batch.get("decision_annotation")
        decisions = annotation.get("decisions") if isinstance(annotation, dict) else None
        if isinstance(decisions, list) and decisions and isinstance(decisions[0], dict):
            decision = decisions[0]
            return {"resigned_side": terminal.get("resigned_side"), "rules": decision.get("rules"),
                    "expected": decision.get("expected"), "risk": decision.get("risk")}
        break
    return {"resigned_side": terminal.get("resigned_side"), "rules": None, "expected": None, "risk": None}


def aggregate_cell(result: CellRunResult, cell: dict[str, Any]) -> dict[str, Any]:
    """Build one cell's report entry. Always returns an entry, even for a cell
    that never produced a log -- unknown evidence is reported as unknown, never
    omitted."""
    entry: dict[str, Any] = {
        "cell_id": result.cell_id,
        "status": result.status,
        "exit_code": result.exit_code,
        "error": result.error,
        "model": cell.get("model"),
        "reasoning_effort": cell.get("reasoning_effort"),
        "configuration": cell.get("configuration", cell.get("model")),
        "llm_side": cell.get("llm_side"),
        "scenario": cell.get("scenario"),
        "seed": cell.get("seed"),
        "provenance": cell.get("provenance"),
    }
    if not result.log_path.is_file():
        entry.update(terminal_class="not_run", match=None)
        return entry
    records = match_report.load_records(result.log_path)
    if not records:
        entry.update(terminal_class="not_run", match=None)
        return entry
    publication_records = _load_publication_records(result.cell_dir)
    classified = match_report.classify(records, publication_records)
    metadata = next((r for r in records if r.get("type") == "metadata"), {})
    terminal = next((r for r in reversed(records) if r.get("type") == "terminal"), {})
    entry.update({
        "terminal_class": classified["terminal_class"],
        "winner": classified["winner"],
        "reason": classified["reason"],
        "match": classified,
        "identity": {
            "requested_model": metadata.get("backend_requested_model") or cell.get("model"),
            "reported_model": metadata.get("runtime_model"),
            "requested_reasoning_effort": metadata.get("requested_reasoning_effort"),
            "reported_reasoning_effort": metadata.get("runtime_reasoning_effort"),
        },
        "compute": {
            "model_calls": classified.get("model_calls"),
            "wall_ms": terminal.get("wall_ms"),
            "usage_measured": metadata.get("usage_measured"),
        },
        "display_turns": classified.get("engine_rounds"),
        "completed_side_turns": classified.get("completed_side_turns"),
        "cap_remaining": (cell["max_turns"] - classified["engine_rounds"]
                         if isinstance(classified.get("engine_rounds"), int) else None),
        "villages_round5_side0": villages_at_round5_side0(records),
        "recruiter_status": recruiter_status(records),
        "resignation": resignation_rationale(records, terminal),
    })
    return entry


def _is_infrastructure_failure(entry: dict[str, Any]) -> bool:
    if entry["status"] != "ok":
        return True
    match = entry.get("match")
    if isinstance(match, dict) and match.get("terminal_class") == "unfinished_recoverable":
        return True
    return False


def check_comparison_validity(resolved_manifest: dict[str, Any]) -> dict[str, Any]:
    """Refuse to call a comparison "matched" when settings or the guide differ.

    `experiment_kind` defaults to `"matched"`: every cell's fixed settings and
    provenance fingerprint must be identical. `"baseline_candidate"` permits
    exactly the one field named in `declared_change_field` to differ between
    the group and the baseline; every other field must still match.
    """
    kind = resolved_manifest.get("experiment_kind", "matched")
    declared_field = resolved_manifest.get("declared_change_field")
    cells = resolved_manifest["cells"]
    mismatches: list[dict[str, Any]] = []
    if kind == "baseline_candidate" and not declared_field:
        return {"experiment_kind": kind, "valid": False, "mismatches": [
            {"error": "baseline_candidate experiments must set 'declared_change_field'"}]}
    baseline_fp = None
    baseline_id = None
    for cell in cells:
        provenance = cell.get("provenance") or {}
        fingerprint = {key: provenance.get(key) for key in FINGERPRINT_KEYS}
        fingerprint.update({key: cell.get(key) for key in FIXED_SETTING_KEYS})
        if baseline_fp is None:
            baseline_fp, baseline_id = fingerprint, cell["id"]
            continue
        for key, value in fingerprint.items():
            if value == baseline_fp[key]:
                continue
            if kind == "baseline_candidate" and key == declared_field:
                continue
            mismatches.append({"cell": cell["id"], "baseline_cell": baseline_id, "field": key,
                               "baseline_value": baseline_fp[key], "candidate_value": value})
    return {"experiment_kind": kind, "valid": not mismatches, "mismatches": mismatches}


def build_report(resolved_manifest: dict[str, Any], results: list[CellRunResult]) -> dict[str, Any]:
    """Aggregate every scheduled cell, even ones absent from `results`."""
    by_id = {cell["id"]: cell for cell in resolved_manifest["cells"]}
    scheduled_ids = list(by_id)
    reported_by_id = {result.cell_id: aggregate_cell(result, by_id[result.cell_id])
                      for result in results if result.cell_id in by_id}
    cells_report = []
    for cell_id in scheduled_ids:
        if cell_id in reported_by_id:
            cells_report.append(reported_by_id[cell_id])
        else:
            cell = by_id[cell_id]
            cells_report.append({
                "cell_id": cell_id, "status": "not_run", "exit_code": None, "error": None,
                "terminal_class": "not_run", "match": None, "model": cell.get("model"),
                "reasoning_effort": cell.get("reasoning_effort"),
                "configuration": cell.get("configuration", cell.get("model")),
                "llm_side": cell.get("llm_side"), "scenario": cell.get("scenario"),
                "seed": cell.get("seed"), "provenance": cell.get("provenance"),
            })

    totals = {
        "scheduled": len(scheduled_ids),
        "completed": sum(1 for e in cells_report if e["status"] == "ok"),
        "failed": sum(1 for e in cells_report if e["status"] == "failed"),
        "error": sum(1 for e in cells_report if e["status"] == "error"),
        "not_run": sum(1 for e in cells_report if e["status"] == "not_run"),
        "model_invalid": sum(1 for e in cells_report if e.get("terminal_class") == "model_invalid"),
        "infrastructure_invalid": sum(1 for e in cells_report if _is_infrastructure_failure(e)),
    }

    configurations: dict[str, dict[str, Any]] = {}
    for entry in cells_report:
        config = entry.get("configuration") or "unknown"
        bucket = configurations.setdefault(config, {
            "cells": 0, "completed": 0, "gameplay_cells": 0,
            "wins": 0, "losses": 0, "draws": 0,
            "model_invalid": 0, "infrastructure_invalid": 0, "not_run": 0,
        })
        bucket["cells"] += 1
        if entry["status"] == "ok":
            bucket["completed"] += 1
        terminal_class = entry.get("terminal_class")
        if terminal_class == "not_run":
            bucket["not_run"] += 1
        elif terminal_class == "gameplay":
            bucket["gameplay_cells"] += 1
            winner = entry.get("winner")
            if winner is None:
                bucket["draws"] += 1
            elif winner == entry.get("llm_side"):
                bucket["wins"] += 1
            else:
                bucket["losses"] += 1
        elif terminal_class == "model_invalid":
            bucket["model_invalid"] += 1
        if _is_infrastructure_failure(entry) and terminal_class != "model_invalid":
            bucket["infrastructure_invalid"] += 1
    for bucket in configurations.values():
        gameplay = bucket["gameplay_cells"]
        bucket["win_rate"] = {"numerator": bucket["wins"], "denominator": gameplay,
                              "rate": (bucket["wins"] / gameplay) if gameplay else None}
        bucket["completion_rate"] = {"numerator": bucket["completed"], "denominator": bucket["cells"],
                                     "rate": (bucket["completed"] / bucket["cells"]) if bucket["cells"] else None}

    return {
        "schema_version": SCHEMA_VERSION,
        "objective": resolved_manifest.get("objective"),
        "resolved_at": resolved_manifest.get("resolved_at"),
        "comparison": check_comparison_validity(resolved_manifest),
        "totals": totals,
        "configurations": configurations,
        "cells": cells_report,
        "note": ("Draws are counted separately from wins and are never wins. "
                "Compute cost (model_calls, wall_ms) is reported per cell, "
                "separate from outcome. Every scheduled cell above is listed "
                "regardless of status."),
    }


# ---------------------------------------------------------------------------
# Catalog import
# ---------------------------------------------------------------------------

def import_cells(catalog_path: Path, results: list[CellRunResult], cohort_id: str) -> list[str]:
    """Import every cell that produced a log into one shared catalog."""
    conn = game_history.open_history(catalog_path)
    imported = []
    try:
        for result in results:
            if not result.log_path.is_file():
                continue
            game_id = f"{cohort_id}:{result.cell_id}"
            game_history.import_game(conn, result.cell_dir, cohort_id=cohort_id, game_id=game_id)
            imported.append(game_id)
    finally:
        conn.close()
    return imported


# ---------------------------------------------------------------------------
# Baseline locking
# ---------------------------------------------------------------------------

def lock_baseline(run_dir: Path, report: dict[str, Any], *, force: bool = False) -> Path:
    """Lock this run's report as the baseline for future prompt experiments.

    Old comparisons remain historical observations: a locked baseline is
    never silently overwritten or relabeled by a later run.
    """
    baseline_path = run_dir / "baseline.json"
    if baseline_path.is_file() and not force:
        raise ManifestError(
            f"a baseline is already locked at {baseline_path}; it stays the historical "
            "reference. Pass force=True only for a deliberate, explicit re-lock.")
    baseline_path.write_text(json.dumps({"locked_at": _now(), "report": report},
                                        sort_keys=True, indent=2))
    return baseline_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="resolve (if needed), run, import, and report a manifest")
    run_p.add_argument("manifest", help="path to the experiment manifest JSON")
    run_p.add_argument("--run-dir", required=True)
    run_p.add_argument("--only-cell")
    run_p.add_argument("--force", action="store_true")
    run_p.add_argument("--cohort")
    run_p.add_argument("--lock-baseline", action="store_true")
    run_p.add_argument("--timeout", type=float)

    report_p = sub.add_parser("report", help="re-aggregate an already-run run-dir")
    report_p.add_argument("--run-dir", required=True)
    report_p.add_argument("--lock-baseline", action="store_true")

    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir)

    if args.command == "run":
        manifest = json.loads(Path(args.manifest).read_text())
        manifest_path = run_dir / "manifest.json"
        if manifest_path.is_file():
            resolved = json.loads(manifest_path.read_text())
        else:
            resolved = resolve_manifest(manifest)
        results = run_manifest(resolved, run_dir, only_cell=args.only_cell,
                               force=args.force, timeout=args.timeout)
        cohort_id = args.cohort or run_dir.name
        import_cells(run_dir / "catalog.sqlite", results, cohort_id)
        report = build_report(resolved, results)
    else:
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.is_file():
            print(f"no resolved manifest at {manifest_path}", file=sys.stderr)
            return 2
        resolved = json.loads(manifest_path.read_text())
        results = [_load_run_status(cell_dir_for(run_dir, cell["id"]), cell["id"])
                  or CellRunResult(cell["id"], cell_dir_for(run_dir, cell["id"]),
                                  cell_dir_for(run_dir, cell["id"]) / "match.ndjson",
                                  None, "", None, "not_run")
                  for cell in resolved["cells"]]
        report = build_report(resolved, results)

    (run_dir / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2))
    if args.lock_baseline:
        lock_baseline(run_dir, report)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
