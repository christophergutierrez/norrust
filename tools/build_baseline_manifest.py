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
from .budget_reconciler import compute_reservation_usd

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
      # 262144 is what the recorded full game used; an explicit finite
      # prompt-byte ceiling keeps the reservation's final-request bound
      # meaningful rather than the client's 16 MiB default (see
      # tools/budget_reconciler.py resolved_max_prompt_bytes /
      # tools/llm_client.py:9646).
      "extra_client_args": ["--max-output-tokens", "131072", "--max-prompt-bytes", "262144"],
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
    # `conservative_estimated_ceiling_usd` is derived from the resolved soft
    # cap and the real output-escalation ceiling (tools/budget_reconciler.py
    # compute_reservation_usd), not a fixed guessed label. It is a per-cell
    # figure (pricing is otherwise shared) so it lives on the cell, not on
    # the shared `pricing` dict.
    cell["pricing"] = dict(pricing, conservative_estimated_ceiling_usd=compute_reservation_usd(cell))
    cells.append(cell)

  return {
    "schema_version": 1,
    "experiment_kind": "observation",
    "objective": "3 full-game baseline observations (seeds 4477, 7731, 2038) at explicit low effort under Fireworks GLM-5.3-flash",
    "cells": cells,
  }


def build_operator_guide(run_dir: Path, cells: list[dict[str, Any]],
                          *, ledger_path: str = "tmp/recruiter-survival/budget-ledger.json") -> str:
  """`ledger_path` is the pre-existing STANDING ledger, never one this builder
  creates. This module must never write, seed, or reset a ledger -- doing so
  from a hardcoded historical spend figure would overstate available funds
  and violate "do not recreate or reset the standing ledger" from the plan.
  """
  lines = [
    "# Baseline Observations - Operator Runbook",
    "",
    "## Environment and Prerequisite Checks",
    "Ensure `FIREWORKS_API_KEY` is present in the environment:",
    "```bash",
    "test -n \"$FIREWORKS_API_KEY\" || echo \"ERROR: FIREWORKS_API_KEY is not set\"",
    "```",
    f"Ensure the standing ledger already exists at `{ledger_path}` and read its",
    "current `spendable_authorization_usd` before proceeding -- this runbook",
    "never creates or resets that ledger.",
    "",
    "## Execution Commands",
    "Reserve budget from resolved limits, run, then reconcile receipts for each",
    "cell in turn (one sequential operator; do not overlap cells). The reserve",
    "step computes its minimum from the resolved manifest -- a bare `--amount`",
    "cannot bypass it:",
    "",
  ]
  for idx, c in enumerate(cells, 1):
    cid = c["id"]
    lines.append(f"### Step {idx}: Cell `{cid}` (seed `{c['seed']}`, effort `{c['reasoning_effort']}`)")
    lines.append("```bash")
    lines.append(f"python3 -m tools.budget_reconciler reserve --ledger {ledger_path} "
                 f"--manifest {run_dir}/manifest.json --cell-id {cid}")
    lines.append(f"python3 -m tools.model_bakeoff run {run_dir}/manifest.json --run-dir {run_dir} "
                 f"--only-cell {cid} --cohort baseline-observations --timeout 7200")
    lines.append(f"python3 -m tools.budget_reconciler reconcile --ledger {ledger_path} "
                 f"--cell-dir {run_dir}/{cid} --cell-id {cid}")
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
  # This builder never creates or writes a budget-ledger.json: it must not
  # seed a fresh ledger with a hardcoded historical spend figure, and must
  # not recreate or reset the pre-existing standing ledger. Operators reserve
  # against the existing standing ledger directly (see OPERATOR.md).
  (args.out_dir / "OPERATOR.md").write_text(build_operator_guide(args.out_dir, resolved["cells"]))

  print(f"Successfully generated baseline manifest, launch.json, and OPERATOR.md in {args.out_dir}")
  return 0


if __name__ == "__main__":
  import sys
  sys.exit(main())
