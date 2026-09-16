"""Unit and fake preflight tests for Stack 6 acceptance scenarios and quality predicates."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from . import strategy_quality as sq

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
BOARD = ROOT / "scenarios/big_battle_6/board.toml"
FIXTURES = ROOT / "tools/fixtures/acceptance_scenarios"


class StrategyQualityUnitTests(unittest.TestCase):
  def test_initial_allocation_predicate_checks_200g_threshold(self):
    """Authorizes >= 200 gold in opening, checking reserve, army adequacy and scout coverage."""
    # 1. Low opening: 7 units costing 93 gold (historical failure)
    bad_policy = {
      "reserve_gold": 0,
      "recruits": [
        {"def_id": "Ghost", "count": 1, "role": "scout"},
        {"def_id": "Skeleton Archer", "count": 2, "role": "army"},
        {"def_id": "Skeleton", "count": 2, "role": "army"},
        {"def_id": "Walking Corpse", "count": 2, "role": "army"},
      ],
      "scouts": [],
      "villages": [{"col": 2, "row": 4}],
      "rally": {"col": 8, "row": 6},
      "holds": [],
    }
    records = [{"type": "policy_installed", "policy": bad_policy}]
    score = sq.score_initial_allocation(records)
    self.assertFalse(score["passed"])
    self.assertEqual(score["gold_allocated"], 93)
    self.assertFalse(score["authorizes_sufficient_recruitment"])
    self.assertFalse(score["army_adequacy"]) # only 6 army units

    # 2. Adequate opening: 14 units costing 208 gold
    good_policy = {
      "reserve_gold": 0,
      "recruits": [
        {"def_id": "Ghost", "count": 1, "role": "scout"},
        {"def_id": "Skeleton Archer", "count": 6, "role": "army"},
        {"def_id": "Skeleton", "count": 7, "role": "army"},
      ],
      "scouts": [],
      "villages": [{"col": 2, "row": 4}],
      "rally": {"col": 8, "row": 6},
      "holds": [],
    }
    score2 = sq.score_initial_allocation([{"type": "policy_installed", "policy": good_policy}])
    self.assertTrue(score2["passed"])
    self.assertEqual(score2["gold_allocated"], 208)
    self.assertTrue(score2["authorizes_sufficient_recruitment"])
    self.assertTrue(score2["feasible_scout_coverage"])
    self.assertTrue(score2["army_adequacy"])

    # 3. Deliberate reserve > 100 gold
    reserve_policy = copy_policy = dict(good_policy)
    reserve_policy["reserve_gold"] = 150
    score3 = sq.score_initial_allocation([{"type": "policy_installed", "policy": reserve_policy}])
    self.assertFalse(score3["passed"])

  def test_replenishment_predicate_distinguishes_routine_commits_from_saving(self):
    """Valid replenishment requires routine recruit commits; saving is reported as a choice."""
    # 1. Replenished via routine
    records_replenished = [
      {
        "type": "decision_packet",
        "packet": {"reason": "recruitment_review", "allowed_kinds": ["set_policy", "act"]},
      },
      {
        "type": "policy_installed",
        "policy": {
          "reserve_gold": 0,
          "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
        },
      },
      {
        "type": "routine_progress_committed",
        "progress_update": {"effects": [{"kind": "recruited", "unit_id": 10}]},
      },
    ]
    score = sq.score_replenishment(records_replenished)
    self.assertTrue(score["passed"])
    self.assertEqual(score["behavior"], "replenished")
    self.assertEqual(score["recruits_committed"], 1)

    # 2. Saved deliberately
    records_saved = [
      {
        "type": "decision_packet",
        "packet": {"reason": "recruitment_review", "allowed_kinds": ["set_policy", "act"]},
      },
      {
        "type": "policy_installed",
        "policy": {
          "reserve_gold": 200,
          "recruits": [],
        },
      },
    ]
    score_saved = sq.score_replenishment(records_saved)
    self.assertFalse(score_saved["passed"])
    self.assertEqual(score_saved["behavior"], "saved")

    # 3. Idle unreplenished
    records_idle = [
      {
        "type": "decision_packet",
        "packet": {"reason": "recruitment_review", "allowed_kinds": ["set_policy", "act"]},
      },
      {
        "type": "policy_installed",
        "policy": {
          "reserve_gold": 0,
          "recruits": [],
        },
      },
    ]
    score_idle = sq.score_replenishment(records_idle)
    self.assertFalse(score_idle["passed"])
    self.assertEqual(score_idle["behavior"], "idle_unreplenished")

  def test_pre_charge_safety_predicate(self):
    """Chosen action retains recruiter survival; losing charge to (6,6) fails."""
    # 1. Surviving recruiter relocated to safe hex
    safe_records = [
      {
        "type": "forwarded_orders",
        "orders": [{"action": "Move", "unit_id": 1, "col": 2, "row": 6}],
      },
      {
        "type": "driver",
        "line": {
          "type": "state",
          "units": [{"id": 1, "hp": 48, "col": 2, "row": 6}],
        },
      },
    ]
    score_safe = sq.score_pre_charge_safety(safe_records)
    self.assertTrue(score_safe["passed"])
    self.assertTrue(score_safe["recruiter_alive"])
    self.assertFalse(score_safe["charged_fatal_hex"])

    # 2. Fatal charge to (6,6) where recruiter died
    fatal_records = [
      {
        "type": "forwarded_orders",
        "orders": [{"action": "Move", "unit_id": 1, "col": 6, "row": 6}],
      },
      {
        "type": "driver",
        "line": {
          "type": "state",
          "units": [{"id": 1, "hp": 0, "col": 6, "row": 6}],
        },
      },
    ]
    score_fatal = sq.score_pre_charge_safety(fatal_records)
    self.assertFalse(score_fatal["passed"])
    self.assertFalse(score_fatal["recruiter_alive"])
    self.assertTrue(score_fatal["charged_fatal_hex"])

  def test_acceptance_summarizer_selection(self):
    """Selects low effort only if all 3 pass; prefers high if low fails; otherwise fails."""
    positions = ["initial_allocation", "completed_queue", "precharge_recruiter"]

    # All pass on both
    cells_all_pass = [
      {"effort": e, "position_id": p, "score": {"passed": True}}
      for e in ("low", "high") for p in positions
    ]
    res1 = sq.summarize_acceptance(cells_all_pass)
    self.assertEqual(res1["status"], "passed")
    self.assertEqual(res1["selected_effort"], "low")

    # Low fails 1, High passes all
    cells_low_fails = [
      {"effort": e, "position_id": p, "score": {"passed": (e == "high" or p != "precharge_recruiter")}}
      for e in ("low", "high") for p in positions
    ]
    res2 = sq.summarize_acceptance(cells_low_fails)
    self.assertEqual(res2["status"], "passed")
    self.assertEqual(res2["selected_effort"], "high")

    # Both fail
    cells_both_fail = [
      {"effort": e, "position_id": p, "score": {"passed": False}}
      for e in ("low", "high") for p in positions
    ]
    res3 = sq.summarize_acceptance(cells_both_fail)
    self.assertEqual(res3["status"], "failed")
    self.assertIsNone(res3["selected_effort"])


@unittest.skipUnless(DRIVER.is_file(), "build greedy_driver before running real-driver tests")
class StrategyQualityFakePreflightTests(unittest.TestCase):
  """Fake preflight proves the intended first packet for each position."""

  def test_preflight_position1_initial_allocation_packet(self):
    """Position 1 delivers initial policy decision packet."""
    with tempfile.TemporaryDirectory() as td:
      tpath = Path(td)
      log_path = tpath / "p1.ndjson"
      backend = tpath / "p1_backend.py"
      policy_resp = {
        "kind": "set_policy",
        "policy": {
          "reserve_gold": 0,
          "recruits": [
            {"def_id": "Ghost", "count": 1, "role": "scout"},
            {"def_id": "Skeleton Archer", "count": 6, "role": "army"},
            {"def_id": "Skeleton", "count": 7, "role": "army"},
          ],
          "scouts": [],
          "villages": [{"col": 2, "row": 4}],
          "rally": {"col": 8, "row": 6},
          "holds": [],
        },
      }
      finish_resp = {"kind": "finish_turn"}
      backend.write_text(f"""
import json, sys
prompt = sys.stdin.read()
if "initial" in prompt:
    print(json.dumps({{"text": json.dumps({policy_resp})}}))
else:
    print(json.dumps({{"text": json.dumps({finish_resp})}}))
""")
      cmd = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--scenario", "big_battle_6",
        "--faction0", "undead",
        "--faction1", "undead",
        "--gold", "300",
        "--seed", "4477",
        "--max-turns", "1",
        "--llm-side", "0",
        "--decision-mode", "strategy",
        "--log", str(log_path),
        "--model-command", f"{sys.executable} {str(backend)}",
      ]
      res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
      self.assertEqual(res.returncode, 0, f"Failed:\n{res.stderr}")
      records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
      packets = [r for r in records if r.get("type") == "decision_packet"]
      self.assertTrue(len(packets) > 0)
      self.assertEqual(packets[0]["packet"]["reason"], "initial")
      self.assertIn("set_policy", packets[0]["packet"]["allowed_kinds"])

      # Test evaluation predicate
      score = sq.score_cell("initial_allocation", records)
      self.assertTrue(score["passed"])
      self.assertEqual(score["gold_allocated"], 208)

  def test_preflight_position2_completed_queue_packet(self):
    """Position 2 delivers recruitment_review packet as intended first packet."""
    with tempfile.TemporaryDirectory() as td:
      tpath = Path(td)
      ckpt_src = FIXTURES / "completed_queue/checkpoint.json"
      journal_src = FIXTURES / "completed_queue/journal.ndjson"

      ckpt_dir = tpath / "match.ckpt"
      ckpt_dir.mkdir()
      ckpt_data = json.loads(ckpt_src.read_text())
      ckpt_data["board_path"] = str(BOARD)
      ckpt_data["save_state"]["board_path"] = str(BOARD)
      encoded = json.dumps(ckpt_data, separators=(",", ":")).encode()
      digest = hashlib.sha256(encoded).hexdigest()
      ckpt_file = ckpt_dir / f"{ckpt_data['side_turns']}-{ckpt_data['save_state']['state_revision']}-{ckpt_data['boundary']}-{digest}.json"
      ckpt_file.write_bytes(encoded)

      (tpath / "match.ndjson").write_text(journal_src.read_text())
      new_log = tpath / "new_match.ndjson"

      backend = tpath / "p2_backend.py"
      replacement_policy = {
        "kind": "set_policy",
        "policy": {
          "reserve_gold": 0,
          "recruits": [{"def_id": "Skeleton", "count": 2, "role": "army"}],
          "scouts": [],
          "villages": [],
          "rally": None,
          "holds": [],
        },
      }
      backend.write_text(f"""
import json, sys
prompt = sys.stdin.read()
if "recruitment_review" in prompt or "policy" in prompt:
    print(json.dumps({{"text": json.dumps({replacement_policy})}}))
else:
    print(json.dumps({{"text": json.dumps({{"kind": "finish_turn"}})}}))
""")
      cmd = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--scenario", "big_battle_6",
        "--faction0", "undead",
        "--faction1", "undead",
        "--gold", "300",
        "--seed", str(ckpt_data.get("seed", 9211)),
        "--llm-side", "0",
        "--decision-mode", "strategy",
        "--resume-checkpoint", str(ckpt_file),
        "--log", str(new_log),
        "--max-turns", "4",
        "--model-command", f"{sys.executable} {str(backend)}",
      ]
      res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
      self.assertIn(res.returncode, (0, 3), f"Failed:\n{res.stderr}")
      records = [json.loads(l) for l in new_log.read_text().splitlines() if l.strip()]
      packets = [r for r in records if r.get("type") == "decision_packet"]
      self.assertTrue(len(packets) > 0)
      # Proves avoiding initial-policy substitution error
      self.assertEqual(packets[0]["packet"]["reason"], "recruitment_review")
      self.assertIn("set_policy", packets[0]["packet"]["allowed_kinds"])

      # Test evaluation predicate
      score = sq.score_cell("completed_queue", records)
      self.assertTrue(score["passed"])
      self.assertEqual(score["behavior"], "replenished")
      self.assertGreaterEqual(score["recruits_committed"], 1)

  def test_preflight_position3_precharge_recruiter_packet(self):
    """Position 3 delivers contact packet with recruiter tactical options."""
    with tempfile.TemporaryDirectory() as td:
      tpath = Path(td)
      ckpt_src = FIXTURES / "precharge_recruiter/checkpoint.json"
      journal_src = FIXTURES / "precharge_recruiter/journal.ndjson"

      ckpt_dir = tpath / "match.ckpt"
      ckpt_dir.mkdir()
      ckpt_data = json.loads(ckpt_src.read_text())
      ckpt_data["board_path"] = str(BOARD)
      ckpt_data["save_state"]["board_path"] = str(BOARD)
      encoded = json.dumps(ckpt_data, separators=(",", ":")).encode()
      digest = hashlib.sha256(encoded).hexdigest()
      ckpt_file = ckpt_dir / f"{ckpt_data['side_turns']}-{ckpt_data['save_state']['state_revision']}-{ckpt_data['boundary']}-{digest}.json"
      ckpt_file.write_bytes(encoded)

      (tpath / "match.ndjson").write_text(journal_src.read_text())
      new_log = tpath / "new_match.ndjson"

      backend = tpath / "p3_backend.py"
      # Model selects safe relocation u1-relocate-1 (holding or retreating safely)
      backend.write_text("""
import json, sys
prompt = sys.stdin.read()
dec_id = "dec-unknown"
if '"decision_id": "' in prompt:
    dec_id = prompt.split('"decision_id": "')[1].split('"')[0]
resp = {
    "kind": "choose",
    "decision_id": dec_id,
    "option_ids": ["u1-relocate-1"],
    "finish_turn": True
}
print(json.dumps({"text": json.dumps(resp)}))
""")
      cmd = [
        sys.executable, "-m", "tools.llm_client",
        "--driver", str(DRIVER),
        "--scenario", "big_battle_6",
        "--faction0", "undead",
        "--faction1", "undead",
        "--gold", "300",
        "--seed", "4477",
        "--llm-side", "0",
        "--decision-mode", "strategy",
        "--resume-checkpoint", str(ckpt_file),
        "--log", str(new_log),
        "--max-turns", "12",
        "--model-command", f"{sys.executable} {str(backend)}",
      ]
      res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
      self.assertIn(res.returncode, (0, 3), f"Failed:\n{res.stderr}")
      records = [json.loads(l) for l in new_log.read_text().splitlines() if l.strip()]
      packets = [r for r in records if r.get("type") == "decision_packet"]
      self.assertTrue(len(packets) > 0)
      # Proves avoiding initial-policy substitution error
      self.assertEqual(packets[0]["packet"]["reason"], "contact")
      actors = {opt["actor_id"] for opt in packets[0]["packet"]["options"]}
      self.assertIn(1, actors) # Unit 1 (recruiter) is an eligible actor

      # Test evaluation predicate
      score = sq.score_cell("precharge_recruiter", records)
      self.assertTrue(score["passed"])
      self.assertTrue(score["recruiter_alive"])
      self.assertFalse(score["charged_fatal_hex"])


if __name__ == "__main__":
  unittest.main()
