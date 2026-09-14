"""Unit and integration tests for strategy decision acceptance matrix and evaluation packet."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from . import match_report, model_bakeoff
from . import strategy_comparison as strategy

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get(
  "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"
))


class TestScreeningManifest(unittest.TestCase):
  """Verify the 16-cell Fireworks screening packet schema and frozen bounds."""

  def test_screening_manifest_structure_and_limits(self):
    manifest = strategy.load_prepared_screening()
    self.assertEqual(manifest.get("schema_version"), 1)
    self.assertEqual(manifest.get("experiment_kind"), "strategy_decision_screening")
    self.assertEqual(manifest.get("status"), "prepared_not_run")
    self.assertEqual(manifest.get("model_evaluation_status"), "pending_authorization")

    # Pricing and spend bounds
    pricing = manifest.get("pricing", {})
    self.assertEqual(pricing.get("provider"), "Fireworks")
    self.assertEqual(pricing.get("model"), "accounts/fireworks/models/glm-5p3-flash")
    self.assertEqual(pricing.get("date"), "2026-09-14")
    rates = pricing.get("rates", {})
    self.assertEqual(rates.get("input_per_million"), 0.15)
    self.assertEqual(rates.get("cached_input_per_million"), 0.03)
    self.assertEqual(rates.get("output_per_million"), 0.5)
    self.assertTrue(rates.get("reasoning_included_in_output"))
    self.assertLessEqual(pricing.get("conservative_estimated_ceiling_usd", 0), 1.20)
    self.assertEqual(pricing.get("soft_sum_cell_tokens"), 1_200_000)

    # Exactly 16 cells: 4 positions x 2 treatments x 2 repetitions
    cells = manifest.get("cells", [])
    self.assertEqual(len(cells), 16)

    positions = {
      "favorable-tactical-attack",
      "withdrawal",
      "independent-scout-movement",
      "repeated-current-contact",
    }
    cell_positions = {c.get("position_id") for c in cells}
    self.assertEqual(cell_positions, positions)

    # Alternating baseline/candidate order
    for idx, cell in enumerate(cells):
      expected_treatment = "baseline" if (idx % 2 == 0) else "candidate"
      self.assertEqual(cell.get("treatment"), expected_treatment)
      budgets = cell.get("budgets", {})
      self.assertEqual(budgets.get("max_game_total_tokens"), 75_000)
      self.assertEqual(budgets.get("max_model_calls_per_turn"), 8)
      self.assertEqual(budgets.get("wall_deadline_seconds"), 900)

  def test_screening_manifest_cli(self):
    with tempfile.TemporaryDirectory() as td:
      out_path = Path(td) / "screening.json"
      code = strategy.main(["screening-manifest", "--out", str(out_path)])
      self.assertEqual(code, 0)
      self.assertTrue(out_path.is_file())
      data = json.loads(out_path.read_text())
      self.assertEqual(len(data.get("cells", [])), 16)
      self.assertEqual(data.get("model_evaluation_status"), "pending_authorization")


class TestFixturePreconditions(unittest.TestCase):
  """Verify fixture preconditions through engine queries and checkpoint hashes."""

  def setUp(self):
    self.manifest = json.loads(strategy.DECISION_MATRIX_PATH.read_text())
    self.cases_by_id = {c["id"]: c for c in self.manifest["cases"]}

  def test_checkpoint_digests_match_manifest(self):
    for case in self.manifest["cases"]:
      fixture_path = ROOT / case["checkpoint_fixture"]
      self.assertTrue(fixture_path.is_file(), f"missing fixture: {fixture_path}")
      digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
      self.assertEqual(digest, case["checkpoint_sha256"], f"digest mismatch in {case['id']}")

  def test_favorable_attack_fixture_preconditions(self):
    case = self.cases_by_id["favorable-tactical-attack"]
    data = json.loads((ROOT / case["checkpoint_fixture"]).read_text())
    units = data["save_state"]["units"]
    attacker = next((u for u in units if u["id"] == case["actor_id"]), None)
    defender = next((u for u in units if u["id"] == case["target_id"]), None)
    self.assertIsNotNone(attacker)
    self.assertIsNotNone(defender)
    self.assertEqual(defender["hp"], 8)
    self.assertEqual(attacker["hp"], 34)
    self.assertEqual(attacker["faction"], 0)
    self.assertEqual(defender["faction"], 1)

  def test_withdrawal_fixture_preconditions(self):
    case = self.cases_by_id["withdrawal"]
    data = json.loads((ROOT / case["checkpoint_fixture"]).read_text())
    units = data["save_state"]["units"]
    recruiter = next((u for u in units if u["id"] == case["actor_id"]), None)
    enemy = next((u for u in units if u["id"] == case["target_id"]), None)
    self.assertIsNotNone(recruiter)
    self.assertIsNotNone(enemy)
    self.assertEqual(recruiter["faction"], 0)
    self.assertEqual(recruiter["col"], 2)
    self.assertEqual(recruiter["row"], 7)
    self.assertEqual(enemy["faction"], 1)
    self.assertEqual(enemy["col"], 3)
    self.assertEqual(enemy["row"], 7)

  def test_independent_scout_fixture_preconditions(self):
    case = self.cases_by_id["independent-scout-movement"]
    data = json.loads((ROOT / case["checkpoint_fixture"]).read_text())
    units = data["save_state"]["units"]
    contact_actor = next((u for u in units if u["id"] == case["actor_id"]), None)
    scout = next((u for u in units if u["id"] == case["scout_id"]), None)
    self.assertIsNotNone(contact_actor)
    self.assertIsNotNone(scout)
    self.assertEqual(contact_actor["col"], 10)
    self.assertEqual(contact_actor["row"], 7)
    self.assertEqual(scout["col"], 2)
    self.assertEqual(scout["row"], 5)

  def test_blocking_unit_fixture_preconditions(self):
    case = self.cases_by_id["blocking-unit"]
    data = json.loads((ROOT / case["checkpoint_fixture"]).read_text())
    units = data["save_state"]["units"]
    scout = next((u for u in units if u["id"] == case["actor_id"]), None)
    blocker = next((u for u in units if u["col"] == 2 and u["row"] == 4), None)
    self.assertIsNotNone(scout)
    self.assertIsNotNone(blocker)
    self.assertEqual(blocker["faction"], 0)
    self.assertEqual(scout["faction"], 0)

  def test_scouts_absent_fixture_preconditions(self):
    case = self.cases_by_id["scouts-absent"]
    data = json.loads((ROOT / case["checkpoint_fixture"]).read_text())
    units = data["save_state"]["units"]
    friendly_units = [u for u in units if u["faction"] == 0]
    scouts = [u for u in friendly_units if u.get("unit_type") in ("Scout", "Vampire Bat")]
    self.assertEqual(len(scouts), 0)
    self.assertEqual(data.get("starting_gold"), 0)

  def test_resume_decision_fixture_preconditions(self):
    case = self.cases_by_id["resume-at-decision-boundary"]
    data = json.loads((ROOT / case["checkpoint_fixture"]).read_text())
    self.assertEqual(data.get("accepted_partial_batches"), 1)
    self.assertEqual(data.get("boundary"), "model")


class TestDecisionAttributionDimensions(unittest.TestCase):
  """Verify the 16 required attribution dimensions."""

  def test_attribution_distinguishes_all_dimensions(self):
    records = [
      {"type": "side_turn_started", "turn": 1},
      {"type": "decision_packet", "packet": {"decision_kind": "tactical", "incident_key": "inc_1"}},
      {"type": "model_request", "request_id": "req_1"},
      {"type": "model", "request_id": "req_1", "usage": {"input_tokens": 100, "output_tokens": 20, "reasoning_tokens": 0, "cached_input_tokens": 0}},
      {"type": "forwarded_orders", "proposal_source": "engine_option", "option_id": "attack_1",
       "orders": [{"action": "Attack", "target_id": 4}]},
      {"type": "driver", "line": {"type": "events", "source": "llm",
       "events": [{"kind": "attack", "damage_to_defender": 8, "defender": {"killed": True}}]}},
      {"type": "driver", "line": {"type": "events", "source": "routine",
       "events": [{"kind": "move", "unit": 5}]}},
      {"type": "terminal", "reason": "max_turns"},
    ]
    attribution = strategy.decision_archive_attribution(records, synthetic=False, pricing=strategy.PILOT_PRICING)

    self.assertEqual(attribution["provider_calls"], 1)
    self.assertEqual(attribution["logical_requests"], 1)
    self.assertEqual(attribution["repairs"], 0)
    self.assertEqual(attribution["option_selections"], 1)
    self.assertEqual(attribution["custom_acts"], 0)
    self.assertEqual(attribution["context_invalid_replies"], 0)
    self.assertEqual(attribution["identical_incident_recurrences"], 0)
    self.assertEqual(attribution["routine_actions"], 1)
    self.assertEqual(attribution["model_actions"], 1)

    effects = attribution["actual_board_effects"]
    self.assertEqual(effects["attacks"], 1)
    self.assertEqual(effects["moves"], 1)
    self.assertEqual(effects["damage_dealt"], 8)
    self.assertEqual(effects["units_killed"], 1)

    self.assertTrue(attribution["incident_resolution"])
    self.assertTrue(attribution["tactical_progress"])
    self.assertFalse(attribution["budget_stop"])
    self.assertTrue(attribution["terminal_present"])

    # Usage and cost
    usage = attribution["usage"]
    self.assertEqual(usage["input_tokens"], 100)
    self.assertEqual(usage["output_tokens"], 20)
    self.assertEqual(usage["usage_coverage"], "complete")

    cost = attribution["cost"]
    self.assertIsNotNone(cost["cost_usd"])
    self.assertEqual(cost["cost_coverage"], "complete")


@unittest.skipUnless(DRIVER.is_file(), "Greedy driver must be built for integration tests")
class TestDecisionMatrixIntegration(unittest.TestCase):
  """End-to-end integration test of all 8 matrix cases through real driver and catalog."""

  def test_run_decision_matrix_all_cases_pass_with_idempotent_catalog(self):
    with tempfile.TemporaryDirectory() as td:
      run_dir = Path(td)
      report_path = run_dir / "report.json"
      code = strategy.main([
        "decision-matrix-run",
        "--run-dir", str(run_dir),
        "--driver", str(DRIVER),
        "--timeout", "60",
        "--out", str(report_path),
      ])
      self.assertEqual(code, 0, f"decision-matrix-run failed; see {report_path}")
      self.assertTrue(report_path.is_file())

      report = json.loads(report_path.read_text())
      self.assertEqual(report.get("acceptance_status"), "passed")
      self.assertEqual(report.get("matrix_status"), "observed")
      self.assertEqual(report.get("denominator", {}).get("observed"), 8)
      self.assertEqual(report.get("denominator", {}).get("scheduled"), 8)

      for case_row in report.get("cases", []):
        case_id = case_row["case_id"]
        status = case_row.get("acceptance_status")
        self.assertEqual(status, "passed", f"case {case_id} failed: {case_row.get('predicate_verdicts')}")
        cat_import = case_row.get("catalog_import", {})
        self.assertTrue(cat_import.get("idempotent"), f"catalog import not idempotent for {case_id}")

      # Now test decision-matrix-report subcommand on the recorded run directory
      report2_path = run_dir / "report_reloaded.json"
      code2 = strategy.main([
        "decision-matrix-report",
        "--run-dir", str(run_dir),
        "--out", str(report2_path),
      ])
      self.assertEqual(code2, 0)
      report2 = json.loads(report2_path.read_text())
      self.assertEqual(report2.get("acceptance_status"), "passed")
      self.assertEqual(report2.get("matrix_status"), "observed")
