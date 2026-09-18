"""Tests for tools.build_recruiter_manifest's reservation and ledger wiring.

Independently recomputes the expected conservative reservation rather than
calling tools.budget_reconciler.compute_reservation_usd to produce its own
expectation.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from . import build_recruiter_manifest as brm
from . import model_bakeoff
from .output_limits import MAX_OUTPUT_LIMIT


def _resolved_max_prompt_bytes(cell: dict) -> int:
  args = cell.get("extra_client_args") or []
  for index, token in enumerate(args):
    if token == "--max-prompt-bytes":
      return int(args[index + 1])
  raise AssertionError("cell does not pass an explicit --max-prompt-bytes")


class RecruiterManifestReservationTest(unittest.TestCase):
  def test_conservative_ceiling_covers_output_escalation_and_resolved_prompt_bytes(self):
    raw = brm.build_manifest()
    cell = raw["cells"][0]
    rates = cell["pricing"]["rates"]
    soft_cap = cell["budgets"]["max_game_total_tokens"]
    max_prompt_bytes = _resolved_max_prompt_bytes(cell)
    self.assertEqual(max_prompt_bytes, 262_144)  # what the recorded full game used
    highest_rate = max(rates["input_per_million"], rates["cached_input_per_million"],
                        rates["output_per_million"])
    expected = (soft_cap / 1_000_000.0 * highest_rate
                + MAX_OUTPUT_LIMIT / 1_000_000.0 * rates["output_per_million"]
                + max_prompt_bytes / 1_000_000.0 * rates["input_per_million"])
    self.assertAlmostEqual(cell["pricing"]["conservative_estimated_ceiling_usd"], expected, places=9)
    self.assertAlmostEqual(expected, 0.3764656, places=9)
    # Must exceed the old fixed guessed label ($0.145) that predated the fix,
    # since a single escalated request alone can already approach the soft cap.
    self.assertGreater(cell["pricing"]["conservative_estimated_ceiling_usd"], 0.145)

  def test_pricing_no_longer_carries_an_independent_context_label(self):
    raw = brm.build_manifest()
    cell = raw["cells"][0]
    self.assertNotIn("max_in_flight_context_tokens", cell["pricing"])

  def test_manifest_resolves_and_passes_comparison_validity(self):
    raw = brm.build_manifest()
    resolved = model_bakeoff.resolve_manifest(raw)
    validity = model_bakeoff.check_comparison_validity(resolved)
    self.assertTrue(validity["valid"], validity.get("mismatches"))


class RecruiterManifestLedgerTest(unittest.TestCase):
  def test_initial_ledger_has_no_fixed_reservation_label(self):
    with tempfile.TemporaryDirectory() as tmp:
      ledger = brm.build_initial_budget_ledger(Path(tmp))
      self.assertNotIn("reservation_per_cell_usd", ledger)
      self.assertNotIn("calls", ledger)  # no flat top-level call list to double-append into
      self.assertIn("spendable_authorization_usd", ledger)
      self.assertEqual(ledger["reserved_for_cell"], None)

  def test_main_writes_operator_guide_with_reserve_and_reconcile_steps(self):
    with tempfile.TemporaryDirectory() as tmp:
      out_dir = Path(tmp) / "recruiter"
      rc = brm.main(["--out-dir", str(out_dir)])
      self.assertEqual(rc, 0)
      operator_guide = (out_dir / "OPERATOR.md").read_text()
      self.assertIn("tools.budget_reconciler reserve", operator_guide)
      self.assertIn("tools.budget_reconciler reconcile", operator_guide)
      ledger = json.loads((out_dir / "budget-ledger.json").read_text())
      self.assertNotIn("reservation_per_cell_usd", ledger)

  def test_refuses_to_overwrite_an_existing_ledger(self):
    """Never recreate or reset a standing ledger that already exists at the
    target path (tmp/recruiter-survival/budget-ledger.json is exactly this
    builder's default --out-dir, so this is not a hypothetical path)."""
    with tempfile.TemporaryDirectory() as tmp:
      out_dir = Path(tmp) / "recruiter"
      out_dir.mkdir(parents=True)
      sentinel = {"schema_version": 1, "standing_cap_usd": 2.0, "prior_spend_usd": 0.5,
                  "remaining_authorization_usd": 1.234567, "spendable_authorization_usd": 1.234567,
                  "active_reservation_usd": 0.0, "reserved_for_cell": None,
                  "actual_total_spend_usd": 0.0, "cells": {}}
      ledger_path = out_dir / "budget-ledger.json"
      ledger_path.write_text(json.dumps(sentinel, indent=2, sort_keys=True) + "\n")

      with self.assertRaises(FileExistsError):
        brm.main(["--out-dir", str(out_dir)])

      # The pre-existing ledger, with its real remaining_authorization_usd,
      # must be completely untouched.
      self.assertEqual(json.loads(ledger_path.read_text()), sentinel)


if __name__ == "__main__":
  unittest.main()
