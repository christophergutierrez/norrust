"""Generate the Stack 4 baseline observations manifest and operator files.

3 baseline games (seeds 4477, 7731, 2038) at explicit low effort under Fireworks GLM-5.3-flash:
- Maximum 120 engine side-turns (60 player turns)
- 2,000,000 measured tokens per game
- 7,200 seconds wall deadline
- Release driver
- big_battle_6, undead sides, 300 gold, controlled side 0 versus Greedy
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import model_bakeoff

REPO_ROOT = Path(__file__).resolve().parents[1]
DRIVER_PATH = "norrust_core/target/release/greedy_driver"
MODEL_ID = "accounts/fireworks/models/glm-5p3-flash"
BACKEND_CMD = f"python3 -m tools.fireworks_backend --stream --model {MODEL_ID}"

BASELINE_CELLS = [
  {
    "id": "obs-01-seed-4477-low",
    "seed": 4477,
    "reasoning_effort": "low",
  },
  {
    "id": "obs-02-seed-7731-low",
    "seed": 7731,
    "reasoning_effort": "low",
  },
  {
    "id": "obs-03-seed-2038-low",
    "seed": 2038,
    "reasoning_effort": "low",
  },
]


def build_baseline_manifest(*, backend_command: str = BACKEND_CMD, driver: str = DRIVER_PATH) -> dict[str, Any]:
  pricing = {
    "date": "2026-09-17",
    "provider": "Fireworks",
    "model": MODEL_ID,
    "rates": {
      "input_per_million": 0.15,
      "cached_input_per_million": 0.03,
      "output_per_million": 0.5,
      "reasoning_included_in_output": True,
    },
    "soft_sum_cell_tokens": 2_000_000,
    "max_in_flight_context_tokens": 131_072,
    "conservative_estimated_ceiling_usd": 1.080536,
  }

  cells = []
  for defn in BASELINE_CELLS:
    cell = {
      "id": defn["id"],
      "scenario": "big_battle_6",
      "seed": defn["seed"],
      "faction0": "undead",
      "faction1": "undead",
      "gold": 300,
      "llm_side": 0,
      "max_turns": 120,
      "model": MODEL_ID,
      "driver": driver,
      "reasoning_effort": defn["reasoning_effort"],
      "decision_mode": "strategy",
      "action_encoding": "coordinates",
      "incremental_turns": True,
      "extra_client_args": ["--max-output-tokens", "131072"],
      "pricing": pricing,
      "budgets": {
        "max_game_total_tokens": 2_000_000,
        "max_model_calls_per_turn": 8,
        "max_partial_batches_per_turn": 64,
        "max_queries_per_turn": 256,
        "query_budget_seconds": 300,
        "model_timeout": 900,
        "turn_timeout": 2100,
        "wall_deadline_seconds": 7200,
        "token_output_limit": 131072,
      },
      "backend": {
        "kind": "command",
        "command": backend_command,
      },
    }
    cells.append(cell)

  return {
    "schema_version": 1,
    "experiment_kind": "observation",
    "objective": "3 full-game baseline observations (seeds 4477, 7731, 2038) at explicit low effort under Fireworks GLM-5.3-flash",
    "cells": cells,
  }


def build_operator_guide(run_dir: Path) -> str:
  lines = [
    "# Baseline Observations - Operator Runbook",
    "",
    "## Environment and Prerequisite Checks",
    "Ensure `FIREWORKS_API_KEY` is present in the environment:",
    "```bash",
    "test -n \"$FIREWORKS_API_KEY\" || echo \"ERROR: FIREWORKS_API_KEY is not set\"",
    "```",
    "",
    "## Execution Commands",
    "Run each cell sequentially using `tools.model_bakeoff`:",
    "",
  ]
  for idx, c in enumerate(BASELINE_CELLS, 1):
    cid = c["id"]
    lines.append(f"### Step {idx}: Run cell `{cid}` (seed `{c['seed']}`, effort `{c['reasoning_effort']}`)")
    lines.append("```bash")
    lines.append(f"python3 -m tools.model_bakeoff run {run_dir}/manifest.json --run-dir {run_dir} --only-cell {cid} --cohort baseline-observations --timeout 7200")
    lines.append("```")
    lines.append("")

  return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Prepare baseline observations manifest and operator files")
  parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "tmp" / "recruiter-survival" / "baseline-games")
  args = parser.parse_args(argv)

  args.out_dir.mkdir(parents=True, exist_ok=True)
  raw = build_baseline_manifest()
  resolved = model_bakeoff.resolve_manifest(raw)
  validity = model_bakeoff.check_comparison_validity(resolved)
  if not validity["valid"]:
    raise ValueError(f"Manifest validity failed: {validity.get('mismatches')}")

  launch_entries = []
  for cell in resolved["cells"]:
    launch_entries.append({
      "cell_id": cell["id"],
      "command": f"python3 -m tools.model_bakeoff run {args.out_dir}/manifest.json --run-dir {args.out_dir} --only-cell {cell['id']} --cohort baseline-observations --timeout 7200",
      "seed": cell["seed"],
      "scenario": cell["scenario"],
      "reasoning_effort": cell["reasoning_effort"],
      "model": cell["model"],
      "driver_hash": cell["provenance"]["driver_hash"],
      "pricing": cell["pricing"],
      "budgets": cell["budgets"],
      "max_turns": cell["max_turns"],
    })
  (args.out_dir / "launch.json").write_text(json.dumps({"cells": launch_entries}, indent=2, sort_keys=True) + "\n")
  (args.out_dir / "manifest.json").write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n")
  (args.out_dir / "OPERATOR.md").write_text(build_operator_guide(args.out_dir))

  print(f"Successfully generated baseline manifest, launch.json, and OPERATOR.md in {args.out_dir}")
  return 0


if __name__ == "__main__":
  import sys
  sys.exit(main())
