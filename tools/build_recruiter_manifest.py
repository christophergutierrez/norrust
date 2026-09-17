"""Generate the 8-cell recruiter survival screening manifest and budget ledger.

8 frozen positions x explicit low / high effort:
- Alternating arm order:
  1. Position 1 (Fixture 1, Rev 231, Seed 4477): low
  2. Position 1 (Fixture 1, Rev 231, Seed 4477): high
  3. Position 2 (Fixture 2, Rev 456, Seed 7731): high
  4. Position 2 (Fixture 2, Rev 456, Seed 7731): low
  5. Position 3 (Fixture 3, Rev 479, Seed 4477): low
  6. Position 3 (Fixture 3, Rev 479, Seed 4477): high
  7. Position 4 (Fixture 4, Rev 86,  Seed 4477): high
  8. Position 4 (Fixture 4, Rev 86,  Seed 4477): low
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

CELL_DEFINITIONS = [
  {
    "id": "screen-01-f1-seed-4477-low",
    "position_id": "fixture_1_seed_4477_defensive",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
    "seed": 4477,
    "max_turns": 14,
    "reasoning_effort": "low",
  },
  {
    "id": "screen-02-f1-seed-4477-high",
    "position_id": "fixture_1_seed_4477_defensive",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive/checkpoint.json",
    "seed": 4477,
    "max_turns": 14,
    "reasoning_effort": "high",
  },
  {
    "id": "screen-03-f2-seed-7731-high",
    "position_id": "fixture_2_seed_7731_defensive",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_2_seed_7731_defensive/checkpoint.json",
    "seed": 7731,
    "max_turns": 24,
    "reasoning_effort": "high",
  },
  {
    "id": "screen-04-f2-seed-7731-low",
    "position_id": "fixture_2_seed_7731_defensive",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_2_seed_7731_defensive/checkpoint.json",
    "seed": 7731,
    "max_turns": 24,
    "reasoning_effort": "low",
  },
  {
    "id": "screen-05-f3-late-emergency-low",
    "position_id": "fixture_3_late_emergency",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_3_late_emergency/checkpoint.json",
    "seed": 4477,
    "max_turns": 30,
    "reasoning_effort": "low",
  },
  {
    "id": "screen-06-f3-late-emergency-high",
    "position_id": "fixture_3_late_emergency",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_3_late_emergency/checkpoint.json",
    "seed": 4477,
    "max_turns": 30,
    "reasoning_effort": "high",
  },
  {
    "id": "screen-07-f4-quiet-control-high",
    "position_id": "fixture_4_quiet_control",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_4_quiet_control/checkpoint.json",
    "seed": 4477,
    "max_turns": 6,
    "reasoning_effort": "high",
    "allow_partial_turn_checkpoint": True,
  },
  {
    "id": "screen-08-f4-quiet-control-low",
    "position_id": "fixture_4_quiet_control",
    "checkpoint_fixture": "tools/fixtures/recruiter_survival/fixture_4_quiet_control/checkpoint.json",
    "seed": 4477,
    "max_turns": 6,
    "reasoning_effort": "low",
    "allow_partial_turn_checkpoint": True,
  },
]


def build_manifest(*, backend_command: str = BACKEND_CMD, driver: str = DRIVER_PATH) -> dict[str, Any]:
  """Construct the raw recruiter survival screening manifest."""
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
    "soft_sum_cell_tokens": 150_000,
    "max_in_flight_context_tokens": 131_072,
    "conservative_estimated_ceiling_usd": 0.145,
  }

  cells = []
  for defn in CELL_DEFINITIONS:
    cell = {
      "id": defn["id"],
      "position_id": defn["position_id"],
      "checkpoint_fixture": defn["checkpoint_fixture"],
      "scenario": "big_battle_6",
      "seed": defn["seed"],
      "faction0": "undead",
      "faction1": "undead",
      "gold": 300,
      "llm_side": 0,
      "max_turns": defn["max_turns"],
      "model": MODEL_ID,
      "driver": driver,
      "reasoning_effort": defn["reasoning_effort"],
      "decision_mode": "strategy",
      "action_encoding": "coordinates",
      "incremental_turns": True,
      "pricing": pricing,
      "budgets": {
        "max_game_total_tokens": 150_000,
        "max_model_calls_per_turn": 3,
        "max_partial_batches_per_turn": 64,
        "max_queries_per_turn": 256,
        "model_timeout": 900,
        "turn_timeout": 2100,
        "wall_deadline_seconds": 2700,
        "token_output_limit": 131072,
      },
      "backend": {
        "kind": "command",
        "command": backend_command,
      },
    }
    if defn.get("allow_partial_turn_checkpoint"):
      cell["allow_partial_turn_checkpoint"] = True
    cells.append(cell)

  return {
    "schema_version": 1,
    "experiment_kind": "recruiter_survival",
    "objective": "8-cell fixed-position low vs high reasoning effort screen under Fireworks GLM-5.3-flash",
    "cells": cells,
  }


def build_initial_budget_ledger(out_dir: Path) -> dict[str, Any]:
  return {
    "schema_version": 1,
    "standing_cap_usd": 2.000000,
    "prior_spend_usd": 0.171026,
    "remaining_authorization_usd": 1.828974,
    "pricing": {
      "date": "2026-09-17",
      "provider": "Fireworks",
      "model": MODEL_ID,
      "rates": {
        "input_per_million": 0.15,
        "cached_input_per_million": 0.03,
        "output_per_million": 0.5,
        "reasoning_included_in_output": True,
      },
    },
    "reservation_per_cell_usd": 0.145,
    "active_reservation_usd": 0.0,
    "actual_screen_spend_usd": 0.0,
    "calls": [],
    "cells": {},
  }


def build_operator_guide(run_dir: Path) -> str:
  lines = [
    "# Recruiter Survival Screening - Operator Runbook",
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
  for idx, c in enumerate(CELL_DEFINITIONS, 1):
    cid = c["id"]
    lines.append(f"### Step {idx}: Run cell `{cid}` ({c['position_id']}, effort `{c['reasoning_effort']}`)")
    lines.append("```bash")
    lines.append(f"python3 -m tools.model_bakeoff run {run_dir}/manifest.json --run-dir {run_dir} --only-cell {cid} --cohort recruiter-survival-screen")
    lines.append("```")
    lines.append("")

  lines.extend([
    "## Post-Run Aggregation & Evidence Generation",
    "Generate full evidence packet (decisions.jsonl, scores.json, evidence-index.json, review-packet.json):",
    "```bash",
    f"python3 -m tools.build_survival_packet --run-dir {run_dir} --catalog {run_dir}/catalog.sqlite",
    "```",
    "",
  ])
  return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Prepare recruiter survival screening manifest and operator files")
  parser.add_argument("--out-dir", type=Path, default=REPO_ROOT / "tmp" / "recruiter-survival")
  args = parser.parse_args(argv)

  args.out_dir.mkdir(parents=True, exist_ok=True)
  raw = build_manifest()
  resolved = model_bakeoff.resolve_manifest(raw)
  validity = model_bakeoff.check_comparison_validity(resolved)
  if not validity["valid"]:
    raise ValueError(f"Manifest validity failed: {validity.get('mismatches')}")

  (args.out_dir / "manifest.json").write_text(json.dumps(resolved, indent=2, sort_keys=True) + "\n")
  (args.out_dir / "budget-ledger.json").write_text(json.dumps(build_initial_budget_ledger(args.out_dir), indent=2, sort_keys=True) + "\n")
  (args.out_dir / "OPERATOR.md").write_text(build_operator_guide(args.out_dir))

  print(f"Successfully generated manifest, budget-ledger, and OPERATOR.md in {args.out_dir}")
  return 0


if __name__ == "__main__":
  import sys
  sys.exit(main())
