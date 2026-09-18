"""Acceptance tests for tools.budget_reconciler.

Every assertion below computes its expected value by independent arithmetic
in this file -- never by calling the reservation/reconciliation code under
test to produce its own expectation. All ledgers are temporary; the real
tmp/recruiter-survival/budget-ledger.json is never read or written here.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from . import budget_reconciler as br
from .output_limits import MAX_OUTPUT_LIMIT


def _pricing(soft_cap: int = 150_000) -> dict:
  return {
    "date": "2026-09-17",
    "provider": "Fireworks",
    "rates": {
      "input_per_million": 0.15,
      "cached_input_per_million": 0.03,
      "output_per_million": 0.5,
    },
    "soft_sum_cell_tokens": soft_cap,
  }


def _cell(cell_id: str = "cell-1", soft_cap: int = 150_000, max_prompt_bytes: int = 262_144) -> dict:
  return {
    "id": cell_id,
    "pricing": _pricing(soft_cap),
    "budgets": {"max_game_total_tokens": soft_cap, "token_output_limit": 131_072},
    "extra_client_args": ["--max-prompt-bytes", str(max_prompt_bytes)],
  }


def _write_ledger(path: Path, *, standing_cap=2.0, prior_spend=0.171026, remaining=None,
                   pricing=None, active_reservation=0.0, reserved_for_cell=None,
                   cells=None) -> None:
  if remaining is None:
    remaining = standing_cap - prior_spend
  ledger = {
    "schema_version": 1,
    "standing_cap_usd": standing_cap,
    "prior_spend_usd": prior_spend,
    "remaining_authorization_usd": remaining,
    "spendable_authorization_usd": remaining - active_reservation,
    "pricing": pricing or _pricing(),
    "active_reservation_usd": active_reservation,
    "reserved_for_cell": reserved_for_cell,
    "actual_total_spend_usd": 0.0,
    "cells": cells or {},
  }
  path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dispatch(game_id, call_id, **extra) -> dict:
  row = {"game_id": game_id, "call_id": call_id, "record_kind": "dispatch", "status": "dispatched"}
  row.update(extra)
  return row


def _final(game_id, call_id, *, status="completed", input_tokens=None, cached_input_tokens=None,
           output_tokens=None, **extra) -> dict:
  row = {"game_id": game_id, "call_id": call_id, "record_kind": "final", "status": status,
         "input_tokens": input_tokens, "cached_input_tokens": cached_input_tokens,
         "output_tokens": output_tokens}
  row.update(extra)
  return row


def _write_usage(cell_dir: Path, rows: list[dict]) -> None:
  lines = [json.dumps(row) for row in rows]
  (cell_dir / "usage.ndjson").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_run_status(cell_dir: Path, status: str) -> None:
  (cell_dir / "run_status.json").write_text(
      json.dumps({"cell_id": "cell-1", "status": status, "exit_code": 0}), encoding="utf-8")


RATES = _pricing()["rates"]


def _expected_cost(input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
  uncached = max(0, input_tokens - cached_input_tokens)
  return (uncached * RATES["input_per_million"] + cached_input_tokens * RATES["cached_input_per_million"]
          + output_tokens * RATES["output_per_million"]) / 1_000_000.0


class ResolvedMaxPromptBytesTest(unittest.TestCase):
  def test_reads_explicit_extra_client_args_value(self):
    cell = _cell(max_prompt_bytes=262_144)
    self.assertEqual(br.resolved_max_prompt_bytes(cell), 262_144)

  def test_falls_back_to_client_default_when_unset(self):
    cell = _cell()
    del cell["extra_client_args"]
    from tools.output_limits import DEFAULT_MAX_PROMPT_BYTES
    self.assertEqual(br.resolved_max_prompt_bytes(cell), DEFAULT_MAX_PROMPT_BYTES)
    self.assertEqual(DEFAULT_MAX_PROMPT_BYTES, 16 * 1024 * 1024)

  def test_client_option_default_is_the_shared_constant(self):
    """Guard against drift: the client's --max-prompt-bytes default must BE the shared
    constant, not a separately typed literal that could diverge from the reservation."""
    import ast as _ast
    tree = _ast.parse(Path("tools/llm_client.py").read_text(encoding="utf-8"))
    defaults = []
    for node in _ast.walk(tree):
      if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
              and node.func.attr == "add_argument"
              and any(isinstance(a, _ast.Constant) and a.value == "--max-prompt-bytes"
                      for a in node.args)):
        defaults.extend(kw.value for kw in node.keywords if kw.arg == "default")
    self.assertEqual(len(defaults), 1, "exactly one --max-prompt-bytes option must exist")
    self.assertIsInstance(defaults[0], _ast.Name)
    self.assertEqual(defaults[0].id, "DEFAULT_MAX_PROMPT_BYTES")

  def test_missing_value_after_flag_raises(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes"]
    with self.assertRaises(ValueError):
      br.resolved_max_prompt_bytes(cell)

  def test_equals_form_is_accepted(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes=99999"]
    self.assertEqual(br.resolved_max_prompt_bytes(cell), 99999)

  def test_repeated_split_flags_use_argparse_last_value(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes", "100", "--max-prompt-bytes", "200"]
    self.assertEqual(br.resolved_max_prompt_bytes(cell), 200)

  def test_repeated_equals_flags_use_argparse_last_value(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes=100", "--max-prompt-bytes=200"]
    self.assertEqual(br.resolved_max_prompt_bytes(cell), 200)

  def test_repeated_split_and_equals_flags_use_argparse_last_value(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes", "100", "--max-prompt-bytes=200"]
    self.assertEqual(br.resolved_max_prompt_bytes(cell), 200)

  def test_actual_client_parser_uses_last_duplicate_value(self):
    # Patch only the post-parse runner so the real llm_client argparse parser
    # handles both spellings and duplicate store semantics.
    from . import llm_client
    captured = {}

    def capture(args):
      captured["max_prompt_bytes"] = args.max_prompt_bytes
      return 0

    argv = ["llm_client", "--orders-file", "unused-orders.json",
            "--max-prompt-bytes", "100", "--max-prompt-bytes=200"]
    with mock.patch.object(llm_client, "run", side_effect=capture), \
         mock.patch.object(sys, "argv", argv):
      self.assertEqual(llm_client.main(), 0)
    self.assertEqual(captured["max_prompt_bytes"], 200)

  def test_actual_parser_accepts_overridden_nonpositive_duplicate(self):
    from . import llm_client
    captured = {}

    def capture(args):
      captured["max_prompt_bytes"] = args.max_prompt_bytes
      return 0

    argv = ["llm_client", "--orders-file", "unused-orders.json",
            "--max-prompt-bytes", "0", "--max-prompt-bytes", "200"]
    with mock.patch.object(llm_client, "run", side_effect=capture), \
         mock.patch.object(sys, "argv", argv):
      self.assertEqual(llm_client.main(), 0)
    self.assertEqual(captured["max_prompt_bytes"], 200)

  def test_final_nonpositive_prompt_limit_is_rejected(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes", "100", "--max-prompt-bytes", "0"]
    with self.assertRaises(ValueError):
      br.resolved_max_prompt_bytes(cell)


class ComputeReservationTest(unittest.TestCase):
  def test_covers_escalation_from_initial_to_ceiling(self):
    # Worked example: soft cap 2,000,000 tokens, output escalating (per
    # tools/output_limits.py MAX_OUTPUT_LIMIT) to 524,288, resolved
    # prompt-byte limit 262,144 (the cell's explicit --max-prompt-bytes),
    # rates 0.15/0.03/0.5 per million.
    cell = _cell(soft_cap=2_000_000, max_prompt_bytes=262_144)
    self.assertEqual(MAX_OUTPUT_LIMIT, 524_288)
    highest_rate = max(0.15, 0.03, 0.5)
    expected = (2_000_000 / 1_000_000.0 * highest_rate
                + 524_288 / 1_000_000.0 * 0.5
                + 262_144 / 1_000_000.0 * 0.15)
    self.assertAlmostEqual(expected, 1.3014656, places=6)
    got = br.compute_reservation_usd(cell)
    self.assertAlmostEqual(got, expected, places=9)
    # It must exceed a bound computed only from the initial (unescalated)
    # output limit -- that was the original defect.
    under_escalated = (2_000_000 / 1_000_000.0 * highest_rate
                        + 131_072 / 1_000_000.0 * 0.5
                        + 262_144 / 1_000_000.0 * 0.15)
    self.assertGreater(got, under_escalated)

  def test_recruiter_scale_worked_example(self):
    cell = _cell(soft_cap=150_000, max_prompt_bytes=262_144)
    expected = (150_000 / 1_000_000.0 * 0.5
                + 524_288 / 1_000_000.0 * 0.5
                + 262_144 / 1_000_000.0 * 0.15)
    got = br.compute_reservation_usd(cell)
    self.assertAlmostEqual(got, expected, places=9)

  def test_unbounded_prompt_bytes_default_makes_reservation_much_larger(self):
    # Without an explicit --max-prompt-bytes, the resolved limit is the
    # client's real 16 MiB default, not a small pricing label -- proving the
    # reservation is now driven by what the client actually enforces.
    bounded = _cell(soft_cap=150_000, max_prompt_bytes=262_144)
    unbounded = _cell(soft_cap=150_000)
    del unbounded["extra_client_args"]
    self.assertGreater(br.compute_reservation_usd(unbounded), br.compute_reservation_usd(bounded))

  def test_missing_soft_cap_raises_explicit_error(self):
    cell = _cell()
    del cell["budgets"]["max_game_total_tokens"]
    with self.assertRaises(ValueError):
      br.compute_reservation_usd(cell)

  def test_missing_rates_raises_explicit_error(self):
    cell = _cell()
    del cell["pricing"]["rates"]["output_per_million"]
    with self.assertRaises(ValueError):
      br.compute_reservation_usd(cell)

  def test_malformed_prompt_bytes_value_raises_explicit_error(self):
    cell = _cell()
    cell["extra_client_args"] = ["--max-prompt-bytes", "not-a-number"]
    with self.assertRaises(ValueError):
      br.compute_reservation_usd(cell)

  def test_nonfinite_rates_are_rejected(self):
    for bad in (math.nan, math.inf, -math.inf):
      cell = _cell()
      cell["pricing"]["rates"]["input_per_million"] = bad
      with self.subTest(rate=bad), self.assertRaises(ValueError):
        br.compute_reservation_usd(cell)

  def test_nonfinite_computed_reservation_is_rejected(self):
    cell = _cell(soft_cap=10_000_000)
    cell["pricing"]["rates"]["output_per_million"] = 1e308
    with self.assertRaises(ValueError):
      br.compute_reservation_usd(cell)


class ReconcileCellTest(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self._tmp.cleanup)
    self.cell_dir = Path(self._tmp.name) / "cell-1"
    self.cell_dir.mkdir()
    self.pricing = _pricing()

  def test_two_unique_calls_with_duplicated_lifecycle_rows(self):
    rows = [
      _dispatch("g1", "c1"),
      _dispatch("g1", "c1"),  # duplicated dispatch line
      _final("g1", "c1", input_tokens=1000, cached_input_tokens=200, output_tokens=300),
      _final("g1", "c1", input_tokens=1000, cached_input_tokens=200, output_tokens=300),  # duplicate final
      _dispatch("g1", "c2"),
      _final("g1", "c2", input_tokens=500, cached_input_tokens=0, output_tokens=100),
    ]
    _write_usage(self.cell_dir, rows)
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["call_count"], 2)
    expected_cost = _expected_cost(1000, 200, 300) + _expected_cost(500, 0, 100)
    self.assertAlmostEqual(result["cost_usd"], expected_cost, places=12)
    self.assertEqual(result["coverage"], "complete")

  def test_missing_usage_file_is_incomplete_not_zero(self):
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "incomplete")
    self.assertIn("missing_usage_file", result["reasons"])
    self.assertEqual(result["cost_usd"], 0.0)
    self.assertEqual(result["call_count"], 0)

  def test_dispatch_only_call_is_incomplete_no_invented_zero(self):
    _write_usage(self.cell_dir, [_dispatch("g1", "c1")])
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "incomplete")
    self.assertEqual(result["call_count"], 1)
    call = result["calls"][0]
    self.assertIn("dispatch_without_final", call["reasons"])
    self.assertIsNone(call["cost_usd"])
    self.assertEqual(result["cost_usd"], 0.0)  # no fabricated zero cost credited

  def test_orphan_final_without_dispatch_is_incomplete(self):
    _write_usage(self.cell_dir, [_final("g1", "c1", input_tokens=10, cached_input_tokens=0, output_tokens=10)])
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "incomplete")
    self.assertIn("final_without_dispatch", result["calls"][0]["reasons"])

  def test_missing_usage_field_stays_unknown_not_zero(self):
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", input_tokens=1000, cached_input_tokens=None, output_tokens=300),
    ])
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "incomplete")
    call = result["calls"][0]
    self.assertIsNone(call["cached_input_tokens"])
    self.assertIsNone(call["cost_usd"])
    self.assertIn("missing_measured_tokens", call["reasons"])

  def test_conflicting_final_reports_gap_not_last_writer_wins(self):
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", input_tokens=1000, cached_input_tokens=200, output_tokens=300),
      _final("g1", "c1", input_tokens=1000, cached_input_tokens=200, output_tokens=999),
    ])
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "incomplete")
    self.assertTrue(any("conflicting_final" in r for r in result["reasons"]))

  def test_malformed_record_line_is_incomplete(self):
    (self.cell_dir / "usage.ndjson").write_text("not json\n", encoding="utf-8")
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "incomplete")
    self.assertTrue(any("malformed_record" in r for r in result["reasons"]))

  def test_terminal_failure_with_measured_usage_is_charged(self):
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", status="failed", input_tokens=800, cached_input_tokens=0, output_tokens=524_288),
    ])
    result = br.reconcile_cell(self.cell_dir, self.pricing)
    self.assertEqual(result["coverage"], "complete")
    expected_cost = _expected_cost(800, 0, 524_288)
    self.assertAlmostEqual(result["cost_usd"], expected_cost, places=9)
    self.assertEqual(result["calls"][0]["status"], "failed")


class TerminalStatusTest(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self._tmp.cleanup)
    self.cell_dir = Path(self._tmp.name)

  def test_no_file_is_not_proven_stopped(self):
    self.assertIsNone(br.terminal_status(self.cell_dir))

  def test_not_run_is_not_proven_stopped(self):
    (self.cell_dir / "run_status.json").write_text(json.dumps({"status": "not_run"}))
    self.assertIsNone(br.terminal_status(self.cell_dir))

  def test_ok_failed_error_are_proven_stopped(self):
    for status in ("ok", "failed", "error"):
      (self.cell_dir / "run_status.json").write_text(json.dumps({"status": status}))
      self.assertEqual(br.terminal_status(self.cell_dir), status)


class ReserveTest(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self._tmp.cleanup)
    self.ledger_path = Path(self._tmp.name) / "ledger.json"

  def test_reserve_defaults_to_minimum(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
    ledger = br.reserve(self.ledger_path, "cell-1", 0.5)
    self.assertEqual(ledger["active_reservation_usd"], 0.5)
    self.assertEqual(ledger["reserved_for_cell"], "cell-1")
    self.assertAlmostEqual(ledger["spendable_authorization_usd"], 1.5, places=9)

  def test_bare_amount_below_minimum_is_refused_without_modifying_ledger(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
    before = self.ledger_path.read_text()
    with self.assertRaises(ValueError):
      br.reserve(self.ledger_path, "cell-1", 0.5, amount_usd=0.1)
    self.assertEqual(self.ledger_path.read_text(), before)

  def test_amount_exceeding_remaining_is_refused_without_modifying_ledger(self):
    _write_ledger(self.ledger_path, standing_cap=1.0, prior_spend=0.9)  # remaining = 0.1
    before = self.ledger_path.read_text()
    with self.assertRaises(ValueError):
      br.reserve(self.ledger_path, "cell-1", 0.5)
    self.assertEqual(self.ledger_path.read_text(), before)

  def test_second_reservation_for_different_cell_is_refused(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.4, reserved_for_cell="cell-A")
    before = self.ledger_path.read_text()
    with self.assertRaises(ValueError):
      br.reserve(self.ledger_path, "cell-B", 0.3)
    self.assertEqual(self.ledger_path.read_text(), before)

  def test_re_reserving_same_cell_is_allowed(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.4, reserved_for_cell="cell-A")
    ledger = br.reserve(self.ledger_path, "cell-A", 0.6)
    self.assertEqual(ledger["active_reservation_usd"], 0.6)
    self.assertEqual(ledger["reserved_for_cell"], "cell-A")

  def test_nonfinite_amounts_are_refused_without_modifying_ledger(self):
    for amount in (math.nan, math.inf, -math.inf):
      with self.subTest(amount=amount):
        _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
        before = self.ledger_path.read_bytes()
        with self.assertRaises(ValueError):
          br.reserve(self.ledger_path, "cell-1", 0.5, amount_usd=amount)
        self.assertEqual(self.ledger_path.read_bytes(), before)

  def test_nonfinite_minimums_are_refused_without_modifying_ledger(self):
    for minimum in (math.nan, math.inf, -math.inf):
      with self.subTest(minimum=minimum):
        _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
        before = self.ledger_path.read_bytes()
        with self.assertRaises(ValueError):
          br.reserve(self.ledger_path, "cell-1", minimum)
        self.assertEqual(self.ledger_path.read_bytes(), before)

  def test_public_cli_nonfinite_amounts_are_refused_without_modifying_ledger(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      cell = _cell("cli-cell")
      manifest = root / "manifest.json"
      manifest.write_text(json.dumps({"cells": [cell]}), encoding="utf-8")
      _write_ledger(root / "ledger.json", standing_cap=2.0, prior_spend=0.0,
                    pricing=cell["pricing"])
      ledger = root / "ledger.json"
      for amount in ("nan", "inf", "-inf"):
        before = ledger.read_bytes()
        result = subprocess.run(
            [sys.executable, "-m", "tools.budget_reconciler", "reserve",
             "--ledger", str(ledger), "--manifest", str(manifest),
             "--cell-id", "cli-cell", "--amount=" + amount],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("finite numeric value", result.stderr)
        self.assertEqual(ledger.read_bytes(), before)

  def test_nonfinite_ledger_balances_are_refused_without_modifying_ledger(self):
    for field, bad in (("remaining_authorization_usd", math.nan),
                       ("active_reservation_usd", math.inf),
                       ("spendable_authorization_usd", -math.inf)):
      with self.subTest(field=field):
        _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
        ledger = json.loads(self.ledger_path.read_text())
        ledger[field] = bad
        self.ledger_path.write_text(json.dumps(ledger, allow_nan=True, indent=2, sort_keys=True) + "\n")
        before = self.ledger_path.read_bytes()
        with self.assertRaises(ValueError):
          br.reserve(self.ledger_path, "cell-1", 0.5)
        self.assertEqual(self.ledger_path.read_bytes(), before)


class ReconcileLedgerTest(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self._tmp.cleanup)
    self.root = Path(self._tmp.name)
    self.ledger_path = self.root / "ledger.json"
    self.cell_dir = self.root / "cell-1"
    self.cell_dir.mkdir()

  def _complete_receipts(self):
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", input_tokens=1000, cached_input_tokens=200, output_tokens=300),
    ])

  def test_ledger_missing_prior_spend_usd_raises_not_a_remembered_default(self):
    # A ledger lacking prior_spend_usd is malformed; the fix removed a silent
    # `ledger.get("prior_spend_usd", 0.171026)` default that would otherwise
    # fill in a stale historical spend figure here.
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
    ledger = json.loads(self.ledger_path.read_text())
    del ledger["prior_spend_usd"]
    self.ledger_path.write_text(json.dumps(ledger))
    self._complete_receipts()
    with self.assertRaises(ValueError):
      br.reconcile(self.ledger_path, self.cell_dir, "cell-1")

  def test_ledger_missing_standing_cap_usd_raises(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
    ledger = json.loads(self.ledger_path.read_text())
    del ledger["standing_cap_usd"]
    self.ledger_path.write_text(json.dumps(ledger))
    self._complete_receipts()
    with self.assertRaises(ValueError):
      br.reconcile(self.ledger_path, self.cell_dir, "cell-1")

  def test_reconcile_idempotent_on_identical_receipts(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.5, reserved_for_cell="cell-1")
    self._complete_receipts()
    _write_run_status(self.cell_dir, "ok")
    first = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    second = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(first, second)
    self.assertEqual(first["cells"]["cell-1"]["call_count"], 1)
    expected_cost = _expected_cost(1000, 200, 300)
    self.assertAlmostEqual(first["cells"]["cell-1"]["cost_usd"], expected_cost, places=12)

  def test_late_final_after_unmatched_dispatch_completes_exactly_once(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.5, reserved_for_cell="cell-1")
    _write_usage(self.cell_dir, [_dispatch("g1", "c1")])
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["cells"]["cell-1"]["coverage"], "incomplete")
    self.assertEqual(ledger["active_reservation_usd"], 0.5)  # retained: incomplete evidence

    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", input_tokens=10, cached_input_tokens=0, output_tokens=5),
    ])
    _write_run_status(self.cell_dir, "ok")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["cells"]["cell-1"]["coverage"], "complete")
    self.assertEqual(ledger["active_reservation_usd"], 0.0)
    self.assertIsNone(ledger["reserved_for_cell"])

  def test_reservation_retained_without_terminal_status(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.5, reserved_for_cell="cell-1")
    self._complete_receipts()
    # No run_status.json written: coverage is complete but termination is unproven.
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["cells"]["cell-1"]["coverage"], "complete")
    self.assertEqual(ledger["active_reservation_usd"], 0.5)
    self.assertEqual(ledger["reserved_for_cell"], "cell-1")

  def test_file_existence_alone_is_not_proof_of_termination(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.5, reserved_for_cell="cell-1")
    self._complete_receipts()
    _write_run_status(self.cell_dir, "not_run")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["active_reservation_usd"], 0.5)
    self.assertEqual(ledger["reserved_for_cell"], "cell-1")

  def test_incomplete_coverage_keeps_full_reservation(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.5, reserved_for_cell="cell-1")
    _write_usage(self.cell_dir, [_dispatch("g1", "c1")])  # dispatch-only: incomplete
    _write_run_status(self.cell_dir, "failed")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["cells"]["cell-1"]["coverage"], "incomplete")
    self.assertEqual(ledger["active_reservation_usd"], 0.5)
    self.assertEqual(ledger["reserved_for_cell"], "cell-1")

  def test_reconcile_cell_a_while_b_reserved_leaves_b_untouched(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  active_reservation=0.5, reserved_for_cell="cell-B")
    self._complete_receipts()
    _write_run_status(self.cell_dir, "ok")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["active_reservation_usd"], 0.5)
    self.assertEqual(ledger["reserved_for_cell"], "cell-B")
    self.assertEqual(ledger["cells"]["cell-1"]["coverage"], "complete")

  def test_reconcile_preserves_other_cells(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0,
                  cells={"cell-0": {"call_count": 3, "cost_usd": 0.01, "coverage": "complete",
                                    "reasons": [], "calls": [], "run_status": "ok"}})
    self._complete_receipts()
    _write_run_status(self.cell_dir, "ok")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertIn("cell-0", ledger["cells"])
    self.assertEqual(ledger["cells"]["cell-0"]["call_count"], 3)

  def test_reconcile_updates_remaining_and_spendable_authorization(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.171026,
                  active_reservation=0.5, reserved_for_cell="cell-1")
    self._complete_receipts()
    _write_run_status(self.cell_dir, "ok")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    expected_cost = _expected_cost(1000, 200, 300)
    expected_remaining = 2.0 - 0.171026 - expected_cost
    self.assertAlmostEqual(ledger["remaining_authorization_usd"], expected_remaining, places=12)
    # Reservation released (complete coverage + proven stopped), so spendable == remaining.
    self.assertAlmostEqual(ledger["spendable_authorization_usd"], expected_remaining, places=12)

  def test_no_prompt_hash_deduplication(self):
    # Two distinct call_ids sharing the same (irrelevant) prompt_hash field
    # must both be counted -- dedup is by (game_id, call_id) only.
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1", prompt_hash="deadbeef"),
      _final("g1", "c1", input_tokens=10, cached_input_tokens=0, output_tokens=5, prompt_hash="deadbeef"),
      _dispatch("g1", "c2", prompt_hash="deadbeef"),
      _final("g1", "c2", input_tokens=10, cached_input_tokens=0, output_tokens=5, prompt_hash="deadbeef"),
    ])
    _write_run_status(self.cell_dir, "ok")
    ledger = br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(ledger["cells"]["cell-1"]["call_count"], 2)

  def test_nonfinite_ledger_balance_is_refused_without_modifying_ledger(self):
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0)
    ledger = json.loads(self.ledger_path.read_text())
    ledger["actual_total_spend_usd"] = math.nan
    self.ledger_path.write_text(json.dumps(ledger, allow_nan=True, indent=2, sort_keys=True) + "\n")
    self._complete_receipts()
    before = self.ledger_path.read_bytes()
    with self.assertRaises(ValueError):
      br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(self.ledger_path.read_bytes(), before)

  def test_nonfinite_rate_is_refused_without_modifying_ledger(self):
    pricing = _pricing()
    pricing["rates"]["cached_input_per_million"] = math.inf
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0, pricing=pricing)
    self._complete_receipts()
    before = self.ledger_path.read_bytes()
    with self.assertRaises(ValueError):
      br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(self.ledger_path.read_bytes(), before)

  def test_nonfinite_computed_call_cost_is_refused_without_modifying_ledger(self):
    pricing = _pricing()
    pricing["rates"]["output_per_million"] = 1e308
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0, pricing=pricing)
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", input_tokens=1, cached_input_tokens=0, output_tokens=10_000_000),
    ])
    before = self.ledger_path.read_bytes()
    with self.assertRaises(ValueError):
      br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(self.ledger_path.read_bytes(), before)

  def test_finite_call_costs_cannot_overflow_the_cell_total(self):
    pricing = _pricing()
    pricing["rates"]["output_per_million"] = 1e308
    _write_ledger(self.ledger_path, standing_cap=2.0, prior_spend=0.0, pricing=pricing)
    _write_usage(self.cell_dir, [
      _dispatch("g1", "c1"),
      _final("g1", "c1", input_tokens=0, cached_input_tokens=0, output_tokens=1_000_000),
      _dispatch("g1", "c2"),
      _final("g1", "c2", input_tokens=0, cached_input_tokens=0, output_tokens=1_000_000),
    ])
    with self.assertRaisesRegex(ValueError, "computed cell cost"):
      br.reconcile_cell(self.cell_dir, pricing)
    before = self.ledger_path.read_bytes()
    with self.assertRaises(ValueError):
      br.reconcile(self.ledger_path, self.cell_dir, "cell-1")
    self.assertEqual(self.ledger_path.read_bytes(), before)


class AtomicWriteTest(unittest.TestCase):
  def test_save_ledger_leaves_no_temp_file_and_is_readable(self):
    with tempfile.TemporaryDirectory() as tmp:
      path = Path(tmp) / "ledger.json"
      br.save_ledger(path, {"a": 1})
      self.assertEqual(json.loads(path.read_text()), {"a": 1})
      leftovers = [p for p in Path(tmp).iterdir() if p.name != "ledger.json"]
      self.assertEqual(leftovers, [])


class OfflineLifecycleTest(unittest.TestCase):
  """Manifest -> reserve CLI -> synthetic receipts -> reconcile CLI twice."""

  def test_full_offline_lifecycle_is_idempotent(self):
    with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      cell = _cell("lifecycle-cell", soft_cap=150_000, max_prompt_bytes=262_144)
      manifest_path = root / "manifest.json"
      manifest_path.write_text(json.dumps({"cells": [cell]}), encoding="utf-8")

      ledger_path = root / "ledger.json"
      _write_ledger(ledger_path, standing_cap=2.0, prior_spend=0.0, pricing=cell["pricing"])

      rc = br.main(["reserve", "--ledger", str(ledger_path), "--manifest", str(manifest_path),
                    "--cell-id", "lifecycle-cell"])
      self.assertEqual(rc, 0)
      ledger = json.loads(ledger_path.read_text())
      expected_min = br.compute_reservation_usd(cell)
      self.assertAlmostEqual(ledger["active_reservation_usd"], expected_min, places=9)
      self.assertEqual(ledger["reserved_for_cell"], "lifecycle-cell")

      # A bare --amount below the computed minimum must be refused.
      rc = None
      with self.assertRaises(ValueError):
        br.main(["reserve", "--ledger", str(ledger_path), "--manifest", str(manifest_path),
                 "--cell-id", "lifecycle-cell", "--amount", "0.0001"])

      cell_dir = root / "lifecycle-cell"
      cell_dir.mkdir()
      _write_usage(cell_dir, [
        _dispatch("g1", "c1"),
        _final("g1", "c1", input_tokens=2000, cached_input_tokens=500, output_tokens=400),
      ])
      _write_run_status(cell_dir, "ok")

      rc = br.main(["reconcile", "--ledger", str(ledger_path), "--cell-dir", str(cell_dir),
                    "--cell-id", "lifecycle-cell"])
      self.assertEqual(rc, 0)
      first = json.loads(ledger_path.read_text())
      self.assertEqual(first["cells"]["lifecycle-cell"]["coverage"], "complete")
      self.assertEqual(first["active_reservation_usd"], 0.0)
      expected_cost = _expected_cost(2000, 500, 400)
      self.assertAlmostEqual(first["cells"]["lifecycle-cell"]["cost_usd"], expected_cost, places=12)

      rc = br.main(["reconcile", "--ledger", str(ledger_path), "--cell-dir", str(cell_dir),
                    "--cell-id", "lifecycle-cell"])
      self.assertEqual(rc, 0)
      second = json.loads(ledger_path.read_text())
      self.assertEqual(first, second)


if __name__ == "__main__":
  unittest.main()
