"""Deterministic budget reservation and receipt reconciliation for norrust experiments."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_ledger(path: Path) -> dict[str, Any]:
  return json.loads(path.read_text(encoding="utf-8"))


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
  path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def reserve(ledger_path: Path, cell_id: str, amount_usd: float) -> dict[str, Any]:
  ledger = load_ledger(ledger_path)
  rem = ledger.get("remaining_authorization_usd", 0.0)
  if amount_usd > rem:
    raise ValueError(f"Insufficient authorization: needed ${amount_usd:.6f}, remaining ${rem:.6f}")
  ledger["active_reservation_usd"] = amount_usd
  ledger["reserved_for_cell"] = cell_id
  save_ledger(ledger_path, ledger)
  return ledger


def reconcile(ledger_path: Path, cell_dir: Path, cell_id: str) -> dict[str, Any]:
  ledger = load_ledger(ledger_path)
  rates = ledger.get("pricing", {}).get("rates", {
    "input_per_million": 0.15,
    "cached_input_per_million": 0.03,
    "output_per_million": 0.5,
  })

  usage_file = cell_dir / "usage.ndjson"
  final_calls = []
  if usage_file.is_file():
    for line in usage_file.read_text(encoding="utf-8").splitlines():
      if not line.strip():
        continue
      rec = json.loads(line)
      if rec.get("record_kind") == "final":
        final_calls.append(rec)

  cell_input = 0
  cell_cached = 0
  cell_output = 0
  cell_cost = 0.0

  for call in final_calls:
    cin = call.get("cached_input_tokens") or 0
    tin = call.get("input_tokens") or 0
    out = call.get("output_tokens") or 0
    uncached = max(0, tin - cin)
    cost = (uncached * rates.get("input_per_million", 0.15) +
            cin * rates.get("cached_input_per_million", 0.03) +
            out * rates.get("output_per_million", 0.50)) / 1_000_000.0
    cell_input += tin
    cell_cached += cin
    cell_output += out
    cell_cost += cost
    ledger.setdefault("calls", []).append(call)

  ledger.setdefault("cells", {})[cell_id] = {
    "calls": len(final_calls),
    "input_tokens": cell_input,
    "cached_tokens": cell_cached,
    "output_tokens": cell_output,
    "cost_usd": cell_cost,
    "status": "completed" if (cell_dir / "run_status.json").is_file() else "unknown",
  }

  total_experiment_spend = sum(c.get("cost_usd", 0.0) for c in ledger["cells"].values())
  ledger["actual_total_spend_usd"] = total_experiment_spend
  standing_cap = ledger.get("standing_cap_usd", 2.0)
  prior_spend = ledger.get("prior_spend_usd", 0.171026)
  ledger["remaining_authorization_usd"] = standing_cap - prior_spend - total_experiment_spend
  ledger["active_reservation_usd"] = 0.0
  ledger["reserved_for_cell"] = None

  save_ledger(ledger_path, ledger)
  return ledger


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Budget reservation and reconciliation")
  sub = parser.add_subparsers(dest="action", required=True)

  res_p = sub.add_parser("reserve")
  res_p.add_argument("--ledger", type=Path, required=True)
  res_p.add_argument("--cell-id", type=str, required=True)
  res_p.add_argument("--amount", type=float, required=True)

  rec_p = sub.add_parser("reconcile")
  rec_p.add_argument("--ledger", type=Path, required=True)
  rec_p.add_argument("--cell-dir", type=Path, required=True)
  rec_p.add_argument("--cell-id", type=str, required=True)

  args = parser.parse_args(argv)
  if args.action == "reserve":
    ledger = reserve(args.ledger, args.cell_id, args.amount)
    print(f"Reserved ${args.amount:.6f} for {args.cell_id}. Remaining: ${ledger['remaining_authorization_usd']:.6f}")
  elif args.action == "reconcile":
    ledger = reconcile(args.ledger, args.cell_dir, args.cell_id)
    cell_info = ledger["cells"][args.cell_id]
    print(f"Reconciled {args.cell_id}: calls={cell_info['calls']}, cost=${cell_info['cost_usd']:.6f}. Remaining: ${ledger['remaining_authorization_usd']:.6f}")
  return 0


if __name__ == "__main__":
  import sys
  sys.exit(main())
