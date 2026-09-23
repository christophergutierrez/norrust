"""Matched local evaluation for Coordinated Planner selector treatments.

This Stack 5 runner uses only the self-play binary's deterministic fake
selector. Each scheduled matchup is run once with the selector disabled and
once with it enabled, with every gameplay setting held fixed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

from . import algorithm_strength as strength

TREATMENTS = ("coordinated-baseline", "coordinated-llm")
SCHEMA_VERSION = 1


def build_schedule(*, base_seed: int = 38101, gold: int = 300,
                   max_side_turns: int = 200) -> list[dict[str, Any]]:
    """Return 32 matchup cells: 16 paired seeds against each fixed opponent."""
    cells = []
    index = 0
    for opponent in strength.DEFAULT_OPPONENTS:
        for faction in strength.DEFAULT_FACTIONS:
            for side in (0, 1):
                for first in ("team1", "team2"):
                    base = strength._cell(
                        f"{opponent}-{faction}-side{side}-{first}", faction,
                        opponent, side, first, gold, base_seed + index,
                        max_side_turns)
                    base["pair_id"] = base["cell_id"]
                    cells.append(base)
                    index += 1
    return cells


def command_for(cell: Mapping[str, Any], treatment: str, binary: Path,
                record_dir: Path) -> list[str]:
    if treatment not in TREATMENTS:
        raise ValueError(f"unknown treatment: {treatment}")
    command = strength.command_for(cell, binary, record_dir)
    if treatment == "coordinated-llm":
        command += ["--selector-candidate", "objective"]
    return command


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"missing game trace: {path}")
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed game trace: {path}: {exc}") from exc


def validate_trace(cell: Mapping[str, Any], treatment: str, result: Mapping[str, Any],
                   trace: list[Mapping[str, Any]]) -> dict[str, Any]:
    outcome = strength.validate_engine_result(cell, result)
    if len(trace) < 2 or trace[0].get("type") != "metadata" or trace[-1].get("type") != "terminal":
        raise ValueError("trace lacks opening metadata or terminal boundary")
    if trace[0].get("input_seed") != cell["seed"]:
        raise ValueError("trace seed mismatch")
    terminal = trace[-1]
    if terminal.get("side_turns_executed") != result.get("completed_side_turns"):
        raise ValueError("trace terminal turn count mismatch")

    decisions = []
    selected_side = int(cell["controlled_side"])
    for row in trace:
        if row.get("type") != "coordinated_decision" or row.get("side") != selected_side:
            continue
        telemetry = row.get("telemetry")
        if not isinstance(telemetry, dict):
            raise ValueError("malformed coordinated decision telemetry")
        if treatment == "coordinated-baseline" and telemetry.get("selector_invoked"):
            raise ValueError("baseline treatment invoked selector")
        if treatment == "coordinated-llm" and telemetry.get("selector_invoked"):
            ids = {c.get("candidate_id") for c in telemetry.get("candidates", [])}
            if telemetry.get("selected_candidate_id") not in ids:
                raise ValueError("selector chose a candidate absent from telemetry")
            if telemetry.get("fallback_reason") is None and telemetry.get("response_status") not in ("selected", "success"):
                raise ValueError("selector response has unexplained status")
        decisions.append(telemetry)

    return {"outcome": outcome, "decisions": decisions,
            "decision_count": len(decisions), "termination_reason": result.get("termination_reason"),
            "winner_side": result.get("winner_side"),
            "effective_seed": result.get("effective_seed")}


def _treatment_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    outcome_counts = Counter(row.get("outcome", "invalid") for row in rows)
    statuses = Counter(row.get("status", "unrun") for row in rows)
    telemetry = [d for row in rows if row.get("status") == "completed"
                 for d in row.get("decisions", [])]
    invoked = [d for d in telemetry if d.get("selector_invoked")]
    fallback = [d for d in invoked if d.get("fallback_reason") is not None]
    agreed = [d for d in invoked if d.get("selected_candidate_id") == d.get("baseline_candidate_id")]
    margins = [float(d["score_margin"]) for d in telemetry if isinstance(d.get("score_margin"), (int, float))]
    latencies = [int(d["latency_ms"]) for d in invoked if isinstance(d.get("latency_ms"), int)]
    costs = [int(d["cost_microusd"]) for d in invoked if isinstance(d.get("cost_microusd"), int)]
    return {
        "scheduled": len(rows), "completed": statuses["completed"],
        "wins": outcome_counts["win"], "losses": outcome_counts["loss"],
        "draws": outcome_counts["draw"], "caps": outcome_counts["cap"],
        "timeouts": statuses["timeout"], "invalid": statuses["invalid"],
        "unrun": statuses["unrun"], "failed": statuses["failed"],
        "win_rate_all_scheduled": outcome_counts["win"] / len(rows) if rows else None,
        "decisions": len(telemetry), "selector_invocations": len(invoked),
        "invocation_rate": len(invoked) / len(telemetry) if telemetry else 0.0,
        "agreement_count": len(agreed), "disagreement_count": len(invoked) - len(agreed),
        "agreement_rate": len(agreed) / len(invoked) if invoked else None,
        "fallback_count": len(fallback),
        "fallback_rate": len(fallback) / len(invoked) if invoked else None,
        "malformed_count": sum(d.get("response_status") == "malformed" for d in invoked),
        "unknown_id_count": sum(d.get("response_status") in ("unknown_id", "invalid_id") for d in invoked),
        "score_margin_mean": sum(margins) / len(margins) if margins else None,
        "latency_ms_observed": len(latencies),
        "latency_ms_mean": sum(latencies) / len(latencies) if latencies else None,
        "cost_microusd_observed": len(costs),
        "cost_microusd_total": sum(costs) if costs else (0 if invoked else None),
        "cost_basis": "local_fake_selector_zero_provider_cost" if invoked else "not_applicable",
        "status_counts": dict(statuses),
    }


def build_report(schedule: list[Mapping[str, Any]], results: list[Mapping[str, Any]],
                 *, manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    expected = {(str(cell["pair_id"]), treatment) for cell in schedule for treatment in TREATMENTS}
    indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
    invalid_rows = []
    for row in results:
        key = (str(row.get("pair_id")), str(row.get("treatment")))
        if key not in expected:
            invalid_rows.append({"key": list(key), "error": "foreign result"})
        elif key in indexed:
            invalid_rows.append({"key": list(key), "error": "duplicate result"})
        else:
            indexed[key] = row

    rows = []
    paired = []
    for cell in schedule:
        pair = {treatment: dict(indexed.get((str(cell["pair_id"]), treatment), {
            "pair_id": cell["pair_id"], "treatment": treatment, "status": "unrun",
            "outcome": None, "opponent": cell["opponent"], "faction": cell["faction"],
            "controlled_side": cell["controlled_side"], "seed": cell["seed"],
            "decisions": [],
        })) for treatment in TREATMENTS}
        for treatment, row in pair.items():
            row.update({"opponent": cell["opponent"], "faction": cell["faction"],
                        "controlled_side": cell["controlled_side"], "seed": cell["seed"]})
            rows.append(row)
        b, l = pair[TREATMENTS[0]], pair[TREATMENTS[1]]
        paired.append({"pair_id": cell["pair_id"], "opponent": cell["opponent"],
                       "faction": cell["faction"], "seed": cell["seed"],
                       "baseline_outcome": b.get("outcome"), "selector_outcome": l.get("outcome"),
                       "outcome_delta": (1 if l.get("outcome") == "win" else 0) - (1 if b.get("outcome") == "win" else 0),
                       "baseline_decisions": b.get("decision_count", 0),
                       "selector_decisions": l.get("decision_count", 0)})
    summaries = {treatment: _treatment_summary([r for r in rows if r["treatment"] == treatment])
                 for treatment in TREATMENTS}
    by_opponent = {}
    for opponent in strength.DEFAULT_OPPONENTS:
        by_opponent[opponent] = {
            treatment: _treatment_summary([r for r in rows if r["treatment"] == treatment and r["opponent"] == opponent])
            for treatment in TREATMENTS
        }
    complete = not invalid_rows and all(
        summaries[treatment][key] == 0
        for treatment in TREATMENTS for key in ("timeouts", "invalid", "unrun", "failed"))
    return {"schema_version": SCHEMA_VERSION, "status": "complete" if complete else "incomplete",
            "treatment_names": list(TREATMENTS), "manifest": dict(manifest or {}),
            "scheduled_matchup_cells": len(schedule), "scheduled_paired_games": len(schedule) * len(TREATMENTS),
            "paired_seed_cells": paired, "summary": summaries, "by_opponent": by_opponent,
            "invalid_records": invalid_rows,
            "matched_win_delta": {opponent: {
                "selector_minus_baseline_win_rate": by_opponent[opponent][TREATMENTS[1]]["win_rate_all_scheduled"] - by_opponent[opponent][TREATMENTS[0]]["win_rate_all_scheduled"]
            } for opponent in strength.DEFAULT_OPPONENTS},
            "note": "Fake selector is local and unbilled. Latency remains unknown when telemetry omits it; all scheduled cells remain in denominators."}


def _run_one(cell: Mapping[str, Any], treatment: str, binary: Path, out_dir: Path,
             timeout: float) -> dict[str, Any]:
    cell_id = str(cell["pair_id"])
    cell_dir = out_dir / "cells" / cell_id / treatment
    trace_dir = cell_dir / "trace"
    cell_dir.mkdir(parents=True, exist_ok=False)
    command = command_for(cell, treatment, binary, trace_dir)
    (cell_dir / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return {"pair_id": cell_id, "treatment": treatment, "status": "timeout",
                "outcome": None, "elapsed_seconds": time.monotonic() - started,
                "error": str(exc), "opponent": cell["opponent"], "faction": cell["faction"],
                "controlled_side": cell["controlled_side"], "seed": cell["seed"]}
    (cell_dir / "stdout.log").write_text(proc.stdout)
    (cell_dir / "stderr.log").write_text(proc.stderr)
    base = {"pair_id": cell_id, "treatment": treatment, "opponent": cell["opponent"],
            "faction": cell["faction"], "controlled_side": cell["controlled_side"],
            "seed": cell["seed"], "exit_code": proc.returncode,
            "elapsed_seconds": time.monotonic() - started,
            "stdout": str((cell_dir / "stdout.log").relative_to(out_dir)),
            "stderr": str((cell_dir / "stderr.log").relative_to(out_dir))}
    if proc.returncode != 0:
        return {**base, "status": "failed", "outcome": None, "error": f"exit {proc.returncode}"}
    engine_rows = strength._result_lines(proc.stdout)
    try:
        if len(engine_rows) != 1:
            raise ValueError(f"expected one engine result, got {len(engine_rows)}")
        trace = _read_trace(trace_dir / "game-00001.ndjson")
        decoded = validate_trace(cell, treatment, engine_rows[0], trace)
        return {**base, "status": "completed", **decoded,
                "trace": str((trace_dir / "game-00001.ndjson").relative_to(out_dir))}
    except (ValueError, OSError) as exc:
        return {**base, "status": "invalid", "outcome": None, "error": str(exc)}


def run_screen(out_dir: Path, binary: Path, *, base_seed: int = 38101,
               gold: int = 300, max_side_turns: int = 200,
               timeout_seconds: float = 180.0) -> dict[str, Any]:
    schedule = build_schedule(base_seed=base_seed, gold=gold, max_side_turns=max_side_turns)
    out_dir.mkdir(parents=True, exist_ok=False)
    if not binary.is_file():
        raise ValueError(f"self-play binary does not exist: {binary}")
    manifest = {"schema_version": SCHEMA_VERSION, "status": "frozen",
                "source_commit": strength._git(strength.ROOT, "rev-parse", "HEAD"),
                "source_tree": strength._git(strength.ROOT, "rev-parse", "HEAD^{tree}"),
                "binary": str(binary.resolve()), "binary_sha256": strength.sha256_file(binary),
                "data_sha256": strength.data_sha256(), "treatments": list(TREATMENTS),
                "selector": {"kind": "built_in_deterministic_fake", "configured_candidate": "objective",
                             "timeout": "not_applicable", "provider_cost_microusd": 0},
                "settings": {"base_seed": base_seed, "gold": gold, "max_side_turns": max_side_turns,
                             "scenario": "big_battle_6", "recruitment_policy": "first-affordable",
                             "second_gold": 0, "threads": 1, "timeout_seconds": timeout_seconds},
                "schedule": schedule}
    manifest["schedule_sha256"] = hashlib.sha256(strength._canonical_bytes(schedule)).hexdigest()
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    results = []
    for cell in schedule:
        for treatment in TREATMENTS:
            results.append(_run_one(cell, treatment, binary.resolve(), out_dir, timeout_seconds))
            (out_dir / "results.json").write_text(json.dumps({"results": results}, indent=2) + "\n")
    report = build_report(schedule, results, manifest=manifest)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--binary", type=Path, default=strength.ROOT / "norrust_core/target/release/self-play")
    parser.add_argument("--base-seed", type=int, default=38101)
    parser.add_argument("--gold", type=int, default=300)
    parser.add_argument("--max-side-turns", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)
    if args.gold < 1 or args.max_side_turns < 1 or args.timeout_seconds <= 0:
        parser.error("gold, cap, and timeout must be positive")
    report = run_screen(args.out_dir, args.binary, base_seed=args.base_seed,
                        gold=args.gold, max_side_turns=args.max_side_turns,
                        timeout_seconds=args.timeout_seconds)
    print(json.dumps({"status": report["status"], "summary": report["summary"]}, sort_keys=True))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
