"""Deterministic budget reservation and receipt reconciliation for norrust experiments.

Reuses `tools.model_usage`'s `(game_id, call_id)` physical-call identity and
lifecycle merge helpers (`merge_lifecycle`) to fold repeated dispatch/final
usage-sidecar rows into one accounted call per identity -- never by prompt
hash. Reservation sizing reuses the real output-escalation ceiling from
`tools.output_limits` instead of a guessed fixed number.

Ledger schema notes:
  - `remaining_authorization_usd` is always `standing_cap_usd - prior_spend_usd
    - actual_total_spend_usd`: a pure spend-basis figure, recomputed fresh on
    every reconcile. It is never reduced by an outstanding reservation.
  - `spendable_authorization_usd` is the actually-available figure for
    launching new work: `remaining_authorization_usd - active_reservation_usd`.
    Consult this before starting a new cell.
  - `actual_total_spend_usd` sums only calls with *complete* measured coverage
    (all of input/cached-input/output tokens known from a matched final
    record). It is a measured lower bound, never a fabricated total that
    covers unknown calls with zero.
  - `cells[cell_id]` is fully replaced (upserted) on every reconcile of that
    cell; other cells are preserved untouched. There is no flat top-level
    `calls` list to accumulate duplicates on repeated reconciliation.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

from .model_usage import ModelCall, merge_lifecycle
from .output_limits import DEFAULT_MAX_PROMPT_BYTES, MAX_OUTPUT_LIMIT

def resolved_max_prompt_bytes(cell: dict[str, Any]) -> int:
  """The RESOLVED per-request prompt-byte limit this cell will actually run
  under: the cell's own `--max-prompt-bytes` in `extra_client_args` if it
  passes one, else the client's own default, `DEFAULT_MAX_PROMPT_BYTES`, which
  the client's `--max-prompt-bytes` option also reads, so the two cannot drift.
  `--max-in-flight-context-tokens`-style
  pricing labels are not a source of truth for this -- only what the client
  will actually enforce is.
  """
  args = cell.get("extra_client_args") or []
  for index, token in enumerate(args):
    if token == "--max-prompt-bytes":
      if index + 1 >= len(args):
        raise ValueError("cell extra_client_args has --max-prompt-bytes with no value")
      try:
        value = int(args[index + 1])
      except (TypeError, ValueError):
        raise ValueError(f"cell extra_client_args --max-prompt-bytes value is not an int: {args[index + 1]!r}")
      if value <= 0:
        raise ValueError("cell extra_client_args --max-prompt-bytes must be a positive finite limit")
      return value
    if isinstance(token, str) and token.startswith("--max-prompt-bytes="):
      raw = token.split("=", 1)[1]
      try:
        value = int(raw)
      except ValueError:
        raise ValueError(f"cell extra_client_args --max-prompt-bytes value is not an int: {raw!r}")
      if value <= 0:
        raise ValueError("cell extra_client_args --max-prompt-bytes must be a positive finite limit")
      return value
  return DEFAULT_MAX_PROMPT_BYTES

# tools/model_bakeoff.py:227-234 documents CellRunResult.status as one of
# "ok" | "failed" | "error" | "not_run"; tools/model_bakeoff.py:482-486
# (`_write_run_status`) writes exactly that status into `run_status.json`
# once the supervised client process has actually exited (or failed to
# launch). "ok"/"failed"/"error" all mean the physical process has
# terminated -- "not_run" (never written by `_write_run_status`; only used
# to report a cell that was never attempted) is NOT proof of termination.
# File *existence* alone is not proof: a `run_status.json` is only ever
# written after the process is known to have stopped, so its mere presence
# already implies one of these three statuses -- but we still check the
# value explicitly rather than trusting the bare file existence check the
# previous implementation used.
TERMINAL_RUN_STATUSES = frozenset({"ok", "failed", "error"})

_MODEL_CALL_FIELDS = {f.name for f in dataclasses.fields(ModelCall)}
_COST_RELEVANT_TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "output_tokens")


def load_ledger(path: Path) -> dict[str, Any]:
  return json.loads(path.read_text(encoding="utf-8"))


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
  """Write the ledger atomically: temp file + os.replace.

  An interrupted write leaves either the old complete file or the new
  complete file in place -- never truncated JSON.
  """
  tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
  tmp_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
  os.replace(tmp_path, path)


def compute_reservation_usd(cell: dict[str, Any]) -> float:
  """Derive a conservative reservation from resolved limits and the real
  output-escalation ceiling, including the last in-flight request.

  Retry/cap-check finding (see tools/llm_client.py):
    - `check_game_budget()` (defined around tools/llm_client.py's client loop)
      is called immediately before every physical dispatch: once before the
      first attempt of a logical request (tools/llm_client.py:6189, guarding
      `backend.complete(...)` at :6199) and again before every retry inside
      the output-limit recovery loop (tools/llm_client.py:6233, right before
      the retried dispatch). It raises `max_game_total_tokens_exhausted`
      BEFORE dispatch once `metadata["cumulative_game_total_tokens"] >=` the
      cell's soft cap (`budgets.max_game_total_tokens`).
    - The output-limit ceiling is checked the same way: `output_policy.exhausted`
      is tested before the first attempt (tools/llm_client.py:6171) and again
      before every retry (tools/llm_client.py:6231), raising
      `model_output_limit_exhausted` before another dispatch is made.
    Because BOTH caps are checked before every physical dispatch (not merely
    before every logical request), at most one additional request can still
    be in flight once either cap is reached -- the request that pushed
    measured usage to or past the cap. The conservative bound is therefore:
    the soft token cap charged at the highest applicable token rate, PLUS one
    maximum final request. That final request must be bounded by the real
    output *escalation ceiling* (`tools.output_limits.MAX_OUTPUT_LIMIT`,
    currently 524288 tokens) -- not the cell's initial per-request output
    limit -- because `OutputLimitPolicy.record_failure`
    (tools/output_limits.py:45-52) escalates a call's requested output limit
    from the initial value up to MAX_OUTPUT_LIMIT on its first failure, and
    the client will dispatch again at that escalated limit before either cap
    stops it. The final request's input side is bounded by the RESOLVED
    per-request prompt-byte limit the cell will actually run under
    (`resolved_max_prompt_bytes`: the cell's own `--max-prompt-bytes` in
    `extra_client_args`, else the client's real enforced default read from
    tools/llm_client.py:9646 -- never an independent pricing label). Bytes
    are treated as an upper bound on input tokens (each token is at least one
    byte), so that many tokens are charged at the input rate.

  Missing finite limits raise ValueError rather than guessing a number.
  """
  pricing = cell.get("pricing")
  if not isinstance(pricing, dict) or not isinstance(pricing.get("rates"), dict):
    raise ValueError("cell is missing a configured pricing snapshot with rates; "
                      "refusing to guess a reservation")
  rates = pricing["rates"]
  for key in ("input_per_million", "cached_input_per_million", "output_per_million"):
    value = rates.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
      raise ValueError(f"pricing.rates.{key} must be a resolved finite nonnegative rate")

  budgets = cell.get("budgets")
  if not isinstance(budgets, dict):
    raise ValueError("cell is missing budgets; refusing to guess a reservation")
  soft_cap = budgets.get("max_game_total_tokens")
  if isinstance(soft_cap, bool) or not isinstance(soft_cap, int) or soft_cap <= 0:
    raise ValueError("budgets.max_game_total_tokens must be a resolved positive finite limit")

  max_prompt_bytes = resolved_max_prompt_bytes(cell)

  highest_rate = max(rates["input_per_million"], rates["cached_input_per_million"],
                      rates["output_per_million"])
  soft_cost_usd = soft_cap / 1_000_000.0 * highest_rate
  final_request_cost_usd = (MAX_OUTPUT_LIMIT / 1_000_000.0 * rates["output_per_million"]
                             + max_prompt_bytes / 1_000_000.0 * rates["input_per_million"])
  return soft_cost_usd + final_request_cost_usd


def _row_to_call(row: dict[str, Any]) -> ModelCall | None:
  filtered = {k: v for k, v in row.items() if k in _MODEL_CALL_FIELDS}
  try:
    return ModelCall(**filtered)
  except TypeError:
    return None


def terminal_status(cell_dir: Path) -> str | None:
  """Return the cell's proven-terminal `run_status.json` status, or None.

  None means "not proven stopped" -- either no run_status.json exists yet
  (the process may still be running) or its status is not one of the
  terminal values. File existence alone is never treated as proof.
  """
  path = cell_dir / "run_status.json"
  if not path.is_file():
    return None
  try:
    payload = json.loads(path.read_text(encoding="utf-8"))
  except ValueError:
    return None
  status = payload.get("status") if isinstance(payload, dict) else None
  return status if status in TERMINAL_RUN_STATUSES else None


def reconcile_cell(cell_dir: Path, pricing: dict[str, Any]) -> dict[str, Any]:
  """Reconcile one cell's usage sidecar into accounted calls and cost.

  Returns a dict with `call_count`, `calls` (per-call detail), `cost_usd`
  (measured lower bound; sum of only fully-covered calls' cost),
  `coverage` ("complete" only if every call is dispatched, has a matched
  final with all three cost-relevant token fields measured, and no
  conflicts/malformed records were seen), and `reasons` (file-level gaps).
  """
  usage_file = cell_dir / "usage.ndjson"
  reasons: list[str] = []
  if not usage_file.is_file():
    return {"call_count": 0, "calls": [], "cost_usd": 0.0,
            "coverage": "incomplete", "reasons": ["missing_usage_file"]}

  rates = pricing["rates"]
  by_id: dict[tuple[str, str], ModelCall] = {}
  order: list[tuple[str, str]] = []
  saw_dispatch: set[tuple[str, str]] = set()
  saw_final: set[tuple[str, str]] = set()

  for lineno, line in enumerate(usage_file.read_text(encoding="utf-8").splitlines(), start=1):
    if not line.strip():
      continue
    try:
      rec = json.loads(line)
    except ValueError:
      reasons.append(f"malformed_record:line_{lineno}")
      continue
    if not isinstance(rec, dict) or not rec.get("game_id") or not rec.get("call_id"):
      reasons.append(f"malformed_record:line_{lineno}")
      continue
    kind = rec.get("record_kind")
    if kind not in ("dispatch", "final"):
      reasons.append(f"unknown_record_kind:line_{lineno}:{kind!r}")
      continue
    call = _row_to_call(rec)
    if call is None:
      reasons.append(f"malformed_record:line_{lineno}")
      continue
    key = call.identity()
    if kind == "dispatch":
      saw_dispatch.add(key)
    else:
      saw_final.add(key)
    if key not in by_id:
      by_id[key] = call
      order.append(key)
    else:
      merged, conflicts = merge_lifecycle(by_id[key], call)
      by_id[key] = merged
      if conflicts:
        reasons.append(f"conflicting_final:{key[1]}:{conflicts}")

  calls_out: list[dict[str, Any]] = []
  file_level_complete = not reasons
  total_cost_usd = 0.0
  for key in order:
    call = by_id[key]
    dispatched = key in saw_dispatch
    finaled = key in saw_final
    call_reasons: list[str] = []
    if not dispatched:
      call_reasons.append("final_without_dispatch")
    if not finaled:
      call_reasons.append("dispatch_without_final")
    cost_usd = None
    if finaled:
      tin, cin, out = call.input_tokens, call.cached_input_tokens, call.output_tokens
      if tin is None or cin is None or out is None:
        call_reasons.append("missing_measured_tokens")
      else:
        uncached = max(0, tin - cin)
        cost_usd = (uncached * rates["input_per_million"]
                    + cin * rates["cached_input_per_million"]
                    + out * rates["output_per_million"]) / 1_000_000.0
    relevant_gaps = [g for g in call.normalization_gaps
                     if g.split(":", 1)[0] in _COST_RELEVANT_TOKEN_FIELDS]
    if relevant_gaps:
      call_reasons.append(f"normalization_gaps:{relevant_gaps}")
      cost_usd = None
    call_complete = not call_reasons
    calls_out.append({
      "call_id": call.call_id,
      "status": call.status,
      "dispatched": dispatched,
      "final": finaled,
      "input_tokens": call.input_tokens,
      "cached_input_tokens": call.cached_input_tokens,
      "output_tokens": call.output_tokens,
      "cost_usd": cost_usd,
      "coverage": "complete" if call_complete else "incomplete",
      "reasons": call_reasons,
    })
    if not call_complete:
      file_level_complete = False
    if cost_usd is not None:
      total_cost_usd += cost_usd

  return {
    "call_count": len(order),
    "calls": calls_out,
    "cost_usd": total_cost_usd,
    "coverage": "complete" if file_level_complete else "incomplete",
    "reasons": reasons,
  }


def reserve(ledger_path: Path, cell_id: str, minimum_usd: float,
            amount_usd: float | None = None) -> dict[str, Any]:
  """Reserve funds for `cell_id`. `amount_usd` defaults to `minimum_usd`.

  Refuses (without modifying the ledger) to: under-reserve below
  `minimum_usd`, overwrite another cell's active reservation, or reserve
  more than `remaining_authorization_usd`.
  """
  if isinstance(minimum_usd, bool) or not isinstance(minimum_usd, (int, float)) or minimum_usd < 0:
    raise ValueError("minimum_usd must be a nonnegative computed amount")
  amount = minimum_usd if amount_usd is None else amount_usd
  if isinstance(amount, bool) or not isinstance(amount, (int, float)):
    raise ValueError("amount must be numeric")
  if amount < minimum_usd:
    raise ValueError(
        f"--amount ${amount:.6f} is below the computed minimum reservation "
        f"${minimum_usd:.6f}; a bare --amount may not bypass the computed minimum")

  ledger = load_ledger(ledger_path)
  existing_amount = float(ledger.get("active_reservation_usd", 0.0) or 0.0)
  existing_cell = ledger.get("reserved_for_cell")
  if existing_amount > 0 and existing_cell not in (None, cell_id):
    raise ValueError(
        f"cannot reserve for {cell_id!r}: cell {existing_cell!r} already holds an "
        f"active reservation of ${existing_amount:.6f}")

  remaining = ledger.get("remaining_authorization_usd")
  if not isinstance(remaining, (int, float)) or isinstance(remaining, bool):
    raise ValueError("ledger missing remaining_authorization_usd")
  if amount > remaining:
    raise ValueError(f"insufficient authorization: needed ${amount:.6f}, remaining ${remaining:.6f}")

  ledger["active_reservation_usd"] = amount
  ledger["reserved_for_cell"] = cell_id
  ledger["spendable_authorization_usd"] = remaining - amount
  save_ledger(ledger_path, ledger)
  return ledger


def reconcile(ledger_path: Path, cell_dir: Path, cell_id: str) -> dict[str, Any]:
  ledger = load_ledger(ledger_path)
  pricing = ledger.get("pricing")
  if not isinstance(pricing, dict) or not isinstance(pricing.get("rates"), dict):
    raise ValueError("ledger missing a configured pricing snapshot with rates")

  result = reconcile_cell(cell_dir, pricing)
  status = terminal_status(cell_dir)

  cells = ledger.setdefault("cells", {})
  cells[cell_id] = {
    "call_count": result["call_count"],
    "calls": result["calls"],
    "cost_usd": result["cost_usd"],
    "coverage": result["coverage"],
    "reasons": result["reasons"],
    "run_status": status,
  }
  # Remove the legacy flat call ledger: per-cell `calls` above is the single
  # source of truth and is fully replaced (never appended) on each reconcile.
  ledger.pop("calls", None)

  total_measured_spend = sum(c.get("cost_usd") or 0.0 for c in cells.values())
  ledger["actual_total_spend_usd"] = total_measured_spend
  standing_cap = ledger.get("standing_cap_usd")
  prior_spend = ledger.get("prior_spend_usd")
  if not isinstance(standing_cap, (int, float)) or not isinstance(prior_spend, (int, float)):
    raise ValueError("ledger missing standing_cap_usd/prior_spend_usd")
  ledger["remaining_authorization_usd"] = standing_cap - prior_spend - total_measured_spend

  reserved_for = ledger.get("reserved_for_cell")
  if reserved_for == cell_id:
    stopped = status in TERMINAL_RUN_STATUSES
    if stopped and result["coverage"] == "complete":
      ledger["active_reservation_usd"] = 0.0
      ledger["reserved_for_cell"] = None
    # Otherwise: incomplete evidence -> keep the full reservation (the
    # simple conservative rule), rather than releasing early.

  ledger["spendable_authorization_usd"] = (
      ledger["remaining_authorization_usd"] - ledger.get("active_reservation_usd", 0.0))

  save_ledger(ledger_path, ledger)
  return ledger


def _load_cell_from_manifest(manifest_path: Path, cell_id: str) -> dict[str, Any]:
  manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
  cells = manifest.get("cells")
  if not isinstance(cells, list):
    raise ValueError(f"manifest {manifest_path} has no 'cells' list")
  for cell in cells:
    if cell.get("id") == cell_id:
      return cell
  raise ValueError(f"cell {cell_id!r} not found in manifest {manifest_path}")


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(description="Budget reservation and reconciliation")
  sub = parser.add_subparsers(dest="action", required=True)

  res_p = sub.add_parser("reserve")
  res_p.add_argument("--ledger", type=Path, required=True)
  res_p.add_argument("--manifest", type=Path, required=True,
                      help="Resolved manifest.json used to compute the minimum reservation")
  res_p.add_argument("--cell-id", type=str, required=True)
  res_p.add_argument("--amount", type=float, default=None,
                      help="Optional override; must be >= the computed minimum")

  rec_p = sub.add_parser("reconcile")
  rec_p.add_argument("--ledger", type=Path, required=True)
  rec_p.add_argument("--cell-dir", type=Path, required=True)
  rec_p.add_argument("--cell-id", type=str, required=True)

  args = parser.parse_args(argv)
  if args.action == "reserve":
    cell = _load_cell_from_manifest(args.manifest, args.cell_id)
    minimum_usd = compute_reservation_usd(cell)
    ledger = reserve(args.ledger, args.cell_id, minimum_usd, args.amount)
    print(f"Reserved ${ledger['active_reservation_usd']:.6f} for {args.cell_id} "
          f"(computed minimum ${minimum_usd:.6f}). "
          f"Spendable: ${ledger['spendable_authorization_usd']:.6f}")
  elif args.action == "reconcile":
    ledger = reconcile(args.ledger, args.cell_dir, args.cell_id)
    cell_info = ledger["cells"][args.cell_id]
    print(f"Reconciled {args.cell_id}: calls={cell_info['call_count']}, "
          f"cost=${cell_info['cost_usd']:.6f}, coverage={cell_info['coverage']}. "
          f"Remaining: ${ledger['remaining_authorization_usd']:.6f}, "
          f"reserved_for_cell={ledger.get('reserved_for_cell')!r}")
  return 0


if __name__ == "__main__":
  import sys
  sys.exit(main())
