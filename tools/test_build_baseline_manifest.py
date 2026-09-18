"""Tests for tools.build_baseline_manifest's reservation wiring.

Independently recomputes the expected conservative reservation rather than
calling tools.budget_reconciler.compute_reservation_usd to produce its own
expectation.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from . import build_baseline_manifest as bbm
from . import model_bakeoff
from .output_limits import MAX_OUTPUT_LIMIT


def _resolved_max_prompt_bytes(cell: dict) -> int:
  args = cell.get("extra_client_args") or []
  for index, token in enumerate(args):
    if token == "--max-prompt-bytes":
      return int(args[index + 1])
  raise AssertionError("cell does not pass an explicit --max-prompt-bytes")


class BaselineManifestReservationTest(unittest.TestCase):
  def test_conservative_ceiling_covers_output_escalation_and_resolved_prompt_bytes(self):
    raw = bbm.build_baseline_manifest()
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
    self.assertAlmostEqual(expected, 1.3014656, places=9)
    # Must exceed the old fixed guessed label ($1.080536) that predated the fix.
    self.assertGreater(cell["pricing"]["conservative_estimated_ceiling_usd"], 1.080536)

  def test_pricing_no_longer_carries_an_independent_context_label(self):
    raw = bbm.build_baseline_manifest()
    cell = raw["cells"][0]
    self.assertNotIn("max_in_flight_context_tokens", cell["pricing"])

  def test_every_cell_carries_its_own_computed_ceiling(self):
    raw = bbm.build_baseline_manifest()
    ceilings = {cell["pricing"]["conservative_estimated_ceiling_usd"] for cell in raw["cells"]}
    self.assertEqual(len(ceilings), 1)  # identical budgets/pricing across cells here
    for cell in raw["cells"]:
      self.assertIn("conservative_estimated_ceiling_usd", cell["pricing"])

  def test_manifest_resolves_and_passes_comparison_validity(self):
    raw = bbm.build_baseline_manifest()
    resolved = model_bakeoff.resolve_manifest(raw)
    validity = model_bakeoff.check_comparison_validity(resolved)
    self.assertTrue(validity["valid"], validity.get("mismatches"))


class BaselineManifestNeverTouchesLedgerTest(unittest.TestCase):
  """This builder must never create, seed, or reset a budget ledger -- the
  standing ledger (tmp/recruiter-survival/budget-ledger.json) already tracks
  real spend, and seeding a fresh one from a hardcoded historical figure
  would overstate available funds. See the plan: "Do not recreate or reset
  the standing ledger."
  """

  def test_main_never_creates_a_ledger_file(self):
    with tempfile.TemporaryDirectory() as tmp:
      out_dir = Path(tmp) / "baseline"
      rc = bbm.main(["--out-dir", str(out_dir)])
      self.assertEqual(rc, 0)
      self.assertFalse((out_dir / "budget-ledger.json").exists())
      # Confirm nothing anywhere under out_dir looks like a ledger either.
      self.assertEqual(list(out_dir.glob("*ledger*")), [])

  def test_module_no_longer_defines_a_ledger_builder(self):
    self.assertFalse(hasattr(bbm, "build_initial_budget_ledger"))

  def test_operator_guide_references_the_standing_ledger_not_a_fresh_one(self):
    with tempfile.TemporaryDirectory() as tmp:
      out_dir = Path(tmp) / "baseline"
      bbm.main(["--out-dir", str(out_dir)])
      operator_guide = (out_dir / "OPERATOR.md").read_text()
      self.assertIn("tools.budget_reconciler reserve", operator_guide)
      self.assertIn("tools.budget_reconciler reconcile", operator_guide)
      self.assertIn("tmp/recruiter-survival/budget-ledger.json", operator_guide)
      self.assertNotIn(f"{out_dir}/budget-ledger.json", operator_guide)


if __name__ == "__main__":
  unittest.main()
