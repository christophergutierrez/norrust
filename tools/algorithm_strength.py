"""Bounded, provider-free strength screening for the built-in algorithms.

The runner schedules matched self-play cells and preserves operational failures
as failures. It never infers a winner from a process exit code, a timeout, or a
missing JSON result. Use it for development screens; held-out acceptance belongs
to the Stack 7 procedure.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FACTIONS = ("loyalists", "rebels", "northerners", "undead")
DEFAULT_OPPONENTS = ("greedy", "coordinated")
SCHEMA_VERSION = 1


def binary_sha256(binary: Path) -> str:
    return hashlib.sha256(binary.read_bytes()).hexdigest()


def source_commit(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def build_schedule(
    *,
    factions: Iterable[str] = DEFAULT_FACTIONS,
    opponents: Iterable[str] = DEFAULT_OPPONENTS,
    controlled_algorithm: str = "greedy-look-ahead",
    gold: int = 300,
    base_seed: int = 26001,
    max_side_turns: int = 200,
) -> list[dict[str, Any]]:
    """Return the fixed 32-cell screening schedule in stable order."""
    cells: list[dict[str, Any]] = []
    index = 0
    for opponent in opponents:
        for faction in factions:
            for controlled_side in (0, 1):
                for first in ("team1", "team2"):
                    cells.append(
                        {
                            "cell_id": f"{faction}-{opponent}-side{controlled_side}-{first}",
                            "faction": faction,
                            "opponent": opponent,
                            "controlled_algorithm": controlled_algorithm,
                            "controlled_side": controlled_side,
                            "first": first,
                            "gold": gold,
                            "second_gold": 0,
                            "seed": base_seed + index,
                            "max_side_turns": max_side_turns,
                        }
                    )
                    index += 1
    return cells


def command_for(cell: Mapping[str, Any], binary: Path) -> list[str]:
    controlled = str(cell["controlled_algorithm"])
    opponent = str(cell["opponent"])
    if int(cell["controlled_side"]) == 0:
        ai1, ai2 = controlled, opponent
    else:
        ai1, ai2 = opponent, controlled
    return [
        str(binary),
        "--scenario",
        "big_battle_6",
        "--team1",
        str(cell["faction"]),
        "--team2",
        str(cell["faction"]),
        "--ai1",
        ai1,
        "--ai2",
        ai2,
        "--games",
        "1",
        "--seed",
        str(cell["seed"]),
        "--threads",
        "1",
        "--gold",
        str(cell["gold"]),
        "--second-gold",
        str(cell["second_gold"]),
        "--first",
        str(cell["first"]),
        "--max-side-turns",
        str(cell["max_side_turns"]),
        "--recruit1-policy",
        "first-affordable",
        "--recruit2-policy",
        "first-affordable",
        "--json",
    ]


def _result_line(stdout: str) -> dict[str, Any] | None:
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("type") == "self_play_result":
            rows.append(value)
    return rows[0] if len(rows) == 1 else None


def run_cell(cell: Mapping[str, Any], *, binary: Path, timeout_seconds: float) -> dict[str, Any]:
    started = time.monotonic()
    command = command_for(cell, binary)
    base = dict(cell)
    base.update({"command": command, "binary": str(binary)})
    try:
        process = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        base.update(
            {
                "status": "timeout",
                "outcome": None,
                "exit_code": None,
                "stdout": error.stdout or "",
                "stderr": error.stderr or "",
            }
        )
    else:
        result = _result_line(process.stdout) if process.returncode == 0 else None
        if process.returncode != 0:
            status = "failed"
            outcome = None
        elif result is None:
            status = "failed"
            outcome = None
        else:
            status = "completed"
            outcome = (
                "win"
                if result.get("winner_side") == int(cell["controlled_side"])
                else "loss"
                if result.get("winner_side") in (0, 1)
                else "draw"
            )
        base.update(
            {
                "status": status,
                "outcome": outcome,
                "exit_code": process.returncode,
                "stdout": process.stdout,
                "stderr": process.stderr,
                "engine_result": result,
            }
        )
    base["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return base


def aggregate_results(
    schedule: Iterable[Mapping[str, Any]], results: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Aggregate completed outcomes while retaining the scheduled denominator."""
    scheduled = list(schedule)
    by_id = {str(row.get("cell_id")): row for row in results}
    rows: list[dict[str, Any]] = []
    for cell in scheduled:
        row = dict(by_id.get(str(cell["cell_id"]), {"status": "unrun", "outcome": None}))
        row.setdefault("cell_id", cell["cell_id"])
        row.setdefault("faction", cell["faction"])
        row.setdefault("opponent", cell["opponent"])
        row.setdefault("controlled_side", cell["controlled_side"])
        row.setdefault("first", cell["first"])
        rows.append(row)

    def summarize_subset(subset: list[Mapping[str, Any]]) -> dict[str, Any]:
        status_counts = Counter(str(row.get("status")) for row in subset)
        outcome_counts = Counter(
            str(row.get("outcome"))
            for row in subset
            if row.get("status") == "completed"
        )
        completed = status_counts["completed"]
        wins = outcome_counts["win"]
        cap_count = sum(
            row.get("engine_result", {}).get("termination_reason") == "side_turn_cap"
            for row in subset
            if row.get("status") == "completed"
        )
        return {
            "scheduled": len(subset),
            "completed": completed,
            "operational_failures": len(subset) - completed,
            "wins": wins,
            "losses": outcome_counts["loss"],
            "draws": outcome_counts["draw"],
            "conditional_win_rate": wins / completed if completed else None,
            "cap_count": cap_count,
            "cap_rate": cap_count / completed if completed else None,
            "status_counts": dict(status_counts),
            "outcome_counts": dict(outcome_counts),
        }

    groups: dict[str, list[Mapping[str, Any]]] = {}
    strata_groups: dict[tuple[str, str, int, str], list[Mapping[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row["opponent"]), []).append(row)
        strata_groups.setdefault(
            (
                str(row["opponent"]),
                str(row["faction"]),
                int(row["controlled_side"]),
                str(row["first"]),
            ),
            [],
        ).append(row)
    summaries = {
        opponent: summarize_subset(subset) for opponent, subset in sorted(groups.items())
    }
    strata = []
    for (opponent, faction, controlled_side, first), subset in sorted(strata_groups.items()):
        strata.append(
            {
                "opponent": opponent,
                "faction": faction,
                "controlled_side": controlled_side,
                "first": first,
                **summarize_subset(subset),
            }
        )
    operational_failures = sum(row.get("status") != "completed" for row in rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "rows": rows,
        "summary": summaries,
        "strata": strata,
        "status": "complete" if operational_failures == 0 else "incomplete",
        "strength_claim_allowed": operational_failures == 0,
        "denominator": {
            "scheduled": len(rows),
            "completed": sum(row.get("status") == "completed" for row in rows),
            "operational_failures": operational_failures,
        },
        "note": "Operational failures and unrun cells are excluded from conditional win rates.",
    }


def run_schedule(
    schedule: list[dict[str, Any]],
    *,
    binary: Path,
    timeout_seconds: float,
    workers: int,
) -> list[dict[str, Any]]:
    if workers < 1:
        raise ValueError("workers must be positive")
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(run_cell, cell, binary=binary, timeout_seconds=timeout_seconds)
            for cell in schedule
        ]
        return [future.result() for future in futures]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="algorithm_strength")
    parser.add_argument("--binary", type=Path, default=ROOT / "norrust_core/target/release/self-play")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--base-seed", type=int, default=26001)
    parser.add_argument("--gold", type=int, default=300)
    parser.add_argument("--max-side-turns", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--controlled-algorithm", default="greedy-look-ahead")
    parser.add_argument("--opponents", nargs="+", default=list(DEFAULT_OPPONENTS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.max_side_turns < 1 or args.timeout_seconds <= 0:
        parser.error("caps must be positive")
    if not args.binary.is_file() and not args.dry_run:
        parser.error(f"self-play binary does not exist: {args.binary}")
    schedule = build_schedule(
        opponents=args.opponents,
        controlled_algorithm=args.controlled_algorithm,
        gold=args.gold,
        base_seed=args.base_seed,
        max_side_turns=args.max_side_turns,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_kind": "algorithm_strength_screening",
        "status": "prepared_not_run" if args.dry_run else "running",
        "source_commit": source_commit(ROOT),
        "binary": str(args.binary),
        "binary_sha256": binary_sha256(args.binary) if args.binary.is_file() else None,
        "timeout_seconds": args.timeout_seconds,
        "workers": args.workers,
        "schedule": schedule,
        "limits": {"max_side_turns": args.max_side_turns, "gold": args.gold},
    }
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    results = [] if args.dry_run else run_schedule(
        schedule,
        binary=args.binary,
        timeout_seconds=args.timeout_seconds,
        workers=args.workers,
    )
    (args.out_dir / "results.json").write_text(json.dumps({"results": results}, indent=2) + "\n")
    report = aggregate_results(schedule, results)
    manifest["status"] = "prepared_not_run" if args.dry_run else "completed"
    (args.out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"scheduled": len(schedule), "completed": report["denominator"]["completed"], "out_dir": str(args.out_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
