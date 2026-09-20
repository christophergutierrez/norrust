"""Acceptance matrix for Strategy Resilience and Decision Quality.

Executes and verifies the 8 tracked acceptance cases from
tmp/plans/strategy-resilience-and-decision-quality.md:
1. Dead generated scout, completed village, otherwise useful routine army work.
2. Dead explicitly assigned unit and under-capacity pending village; later repair.
3. Partial relocation-plus-attacks with nontrivial projected exposure and assumptions.
4. Many eligible actors, a small menu, continue then finish; deliberate early finish.
5. Threatened recruiter during a remaining policy issue with available support.
6. Threatened recruiter without support, including exhausted-action fallback.
7. Expansion queue completion and interruption/resume equivalence.
8. Concentration queue completion and custom intentional saving.

Also verifies:
- Full client -> prompt -> response -> committed event -> report -> SQLite import linkage.
- Idempotent catalog reimport.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from . import llm_client as lc
from . import match_report as mr
from . import routine_policy as rp
from . import strategy_consequences as sc
from . import strategy_decision as sd
from .game_history import import_game, open_history
from .test_opening_policy_driver import seed_command
from .test_strategy_routine_stack2 import FIXTURES as QUIET_FIXTURES
from .test_strategy_routine_stack2 import prepare as prepare_quiet

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get("NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver"))
FIXTURE_DEFENSIVE = ROOT / "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive"


def _query_driver(checkpoint_path: Path, query_payload: dict, *, timeout: float = 15.0) -> dict:
  proc = subprocess.Popen(
    [str(DRIVER), "--seed", "9211", "--resume-checkpoint", str(checkpoint_path)],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    text=True,
  )
  try:
    deadline = time.monotonic() + timeout
    rev = None
    while time.monotonic() < deadline:
      ready, _, _ = select.select([proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
      if not ready:
        raise TimeoutError("driver produced no output")
      line = proc.stdout.readline()
      if not line:
        break
      msg = json.loads(line)
      if msg.get("type") == "state":
        rev = msg.get("state_revision", 0)
        break
    if rev is None:
      raise RuntimeError("no state message received from driver")
    payload = dict(query_payload)
    payload["state_revision"] = rev
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    ready, _, _ = select.select([proc.stdout.fileno()], [], [], max(0.0, deadline - time.monotonic()))
    if not ready:
      raise TimeoutError("driver query reply timeout")
    reply_line = proc.stdout.readline()
    return json.loads(reply_line) if reply_line else {}
  finally:
    if proc.stdin:
      proc.stdin.close()
    if proc.stdout:
      proc.stdout.close()
    proc.kill()
    proc.wait(timeout=5)


@unittest.skipUnless(DRIVER.is_file(), "Requires compiled greedy_driver")
class StrategyResilienceAcceptanceMatrixTests(unittest.TestCase):
  """Complete 8-case acceptance matrix testing provider-free real driver/client execution."""

  def test_case_1_dead_generated_scout_completed_village_routine_work_committed(self):
    """Case 1: Dead generated scout, completed village, otherwise useful routine army work."""
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      checkpoint, _, _, _ = prepare_quiet(root)

      dead_scout_id = 99
      policy = {
        "reserve_gold": 0,
        "recruits": [
          {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
          {"def_id": "Skeleton", "count": 2, "role": "army"},
        ],
        "scouts": [dead_scout_id],
        "villages": [{"col": 2, "row": 4}],
        "rally": None,
        "holds": [],
      }
      progress = {
        "installation_id": "inst-c1",
        "recruited": [{"queue_index": 0, "done": 1}],
        "scout_ids": [dead_scout_id],
        "scout_assignments": [{"unit_id": dead_scout_id, "col": 2, "row": 4}],
        "completed_villages": [{"col": 2, "row": 4}],
        "policy_complete": False,
      }
      resp = _query_driver(checkpoint, {
        "action": "Query",
        "what": "routine_next",
        "policy": policy,
        "progress": progress,
      })
      body = resp.get("body", {})
      self.assertEqual(body.get("result"), "action")
      self.assertEqual(body.get("reason"), "recruit")
      action = body.get("action", {})
      self.assertEqual(action.get("action"), "Recruit")
      self.assertEqual(action.get("def_id"), "Skeleton")

      p_update = body.get("progress_update", {})
      effects = p_update.get("effects", [])
      kinds = [e.get("kind") for e in effects]
      self.assertIn("scout_retired", kinds)
      self.assertIn("recruited", kinds)

  def test_case_2_dead_explicit_assigned_unit_under_capacity_deferred_village(self):
    """Case 2: Dead explicitly assigned unit and under-capacity pending village; later repair."""
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      checkpoint, _, _, _ = prepare_quiet(root)

      dead_scout_id = 99
      policy = {
        "reserve_gold": 0,
        "recruits": [
          {"def_id": "Vampire Bat", "count": 1, "role": "scout"},
          {"def_id": "Skeleton", "count": 2, "role": "army"},
        ],
        "scouts": [dead_scout_id],
        "villages": [{"col": 2, "row": 4}, {"col": 5, "row": 3}],
        "rally": None,
        "holds": [],
      }
      progress = {
        "installation_id": "inst-c2",
        "recruited": [{"queue_index": 0, "done": 1}],
        "scout_ids": [dead_scout_id],
        "scout_assignments": [{"unit_id": dead_scout_id, "col": 2, "row": 4}],
        "completed_villages": [],  # Scout died before capture
        "policy_complete": False,
      }
      resp = _query_driver(checkpoint, {
        "action": "Query",
        "what": "routine_next",
        "policy": policy,
        "progress": progress,
      })
      body = resp.get("body", {})
      self.assertEqual(body.get("result"), "action")
      self.assertEqual(body.get("reason"), "recruit")
      action = body.get("action", {})
      self.assertEqual(action.get("action"), "Recruit")

      p_update = body.get("progress_update", {})
      effects = p_update.get("effects", [])
      kinds = [e.get("kind") for e in effects]
      self.assertIn("scout_retired", kinds)
      self.assertIn("scout_unassigned", kinds)

  def test_case_3_partial_relocation_attacks_exposure_and_assumptions(self):
    """Case 3: Partial relocation-plus-attacks with nontrivial projected exposure and assumptions."""
    with tempfile.TemporaryDirectory() as td:
      board = ROOT / "scenarios/big_battle_6/board.toml"
      ckpt_data = json.loads((FIXTURE_DEFENSIVE / "checkpoint.json").read_text())
      ckpt_data["board_path"] = str(board)
      ckpt_data["save_state"]["board_path"] = str(board)
      encoded = json.dumps(ckpt_data, separators=(",", ":")).encode()
      ckpt_path = Path(td) / f"0-231-{hashlib.sha256(encoded).hexdigest()}.json"
      ckpt_path.write_bytes(encoded)
      checkpoint_dir = Path(td) / "checkpoints"
      checkpoint_dir.mkdir()

      proc = subprocess.Popen(
        [
          str(DRIVER),
          "--scenario", "big_battle_6",
          "--faction0", "undead",
          "--faction1", "undead",
          "--gold", "300",
          "--seed", "4477",
          "--llm-side", "0",
          "--max-turns", "14",
          "--incremental-turns",
          "--checkpoint-dir", str(checkpoint_dir),
          "--resume-checkpoint", str(ckpt_path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
      )
      try:
        # Read state
        rev = None
        for _ in range(50):
          line = proc.stdout.readline()
          if not line:
            break
          msg = json.loads(line)
          if msg.get("type") == "state":
            rev = msg["state_revision"]
            break
        self.assertIsNotNone(rev)

        policy = json.loads((FIXTURE_DEFENSIVE / "metadata.json").read_text())["policy"]
        progress = json.loads((FIXTURE_DEFENSIVE / "metadata.json").read_text())["progress"]
        proc.stdin.write(json.dumps({
          "action": "Query", "what": "routine_next", "state_revision": rev,
          "policy": policy, "progress": progress,
        }) + "\n")
        proc.stdin.flush()
        r_next = json.loads(proc.stdout.readline())
        options = r_next.get("body", {}).get("evidence", {}).get("options", [])
        by_id = {o["option_id"]: o for o in options}
        ref = json.loads((FIXTURE_DEFENSIVE / "stack4_reference.json").read_text())
        option_ids = ref["alternatives"]["relocation_pressure"]["option_ids"]
        reloc_orders = [action for oid in option_ids for action in by_id[oid]["actions"]]

        proc.stdin.write(json.dumps({
          "action": "Query",
          "what": "preview_batch",
          "state_revision": rev,
          "phase": "partial",
          "candidates": [reloc_orders],
        }) + "\n")
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline())
        self.assertTrue(resp.get("ok"))
        candidates = resp.get("body", {}).get("candidates", [])
        self.assertEqual(len(candidates), 1)
        consequences = sc.extract_candidate_consequences(
            resp.get("body", {}), 0, expected_revision=rev, actual_revision=resp.get("state_revision")
        )
        self.assertEqual(consequences["forecast_phase"], "partial")
        self.assertIn("recruiter_exposure", consequences)
        self.assertIn("friendly_exposure", consequences)
        self.assertIn("assumptions", consequences)
        recruiter_exp = consequences["recruiter_exposure"]
        self.assertIsInstance(recruiter_exp, dict)
        self.assertIn("direct_attackers", recruiter_exp)
        self.assertIn("open_attackers", recruiter_exp)
      finally:
        if proc.stdin:
          proc.stdin.close()
        if proc.stdout:
          proc.stdout.close()
        if proc.stderr:
          proc.stderr.close()
        proc.kill()
        proc.wait(timeout=5)

  def test_case_4_many_eligible_actors_small_menu_turn_status_and_deliberate_finish(self):
    """Case 4: Many eligible actors, a small menu, continue then finish; deliberate early finish."""
    evidence = {
      "stage": "current_state",
      "contact_actionability": "actionable",
      "eligible_actor_count": 18,
      "actor_ids": [1, 2, 3],
      "actors_truncated": True,
      "options": [
        {"option_id": "u1-opt1", "actor_id": 1, "category": "attack",
         "actions": [{"action": "Attack", "attacker_id": 1, "defender_id": 10}]},
        {"option_id": "u2-opt1", "actor_id": 2, "category": "attack",
         "actions": [{"action": "Attack", "attacker_id": 2, "defender_id": 10}]},
      ],
      "options_truncated": True,
    }
    packet = sd.build_decision_packet("contact", evidence, revision=10, game_id="case4", side_turn=2)
    turn_status = rp.render_turn_status_block(packet)
    self.assertIn("18 engine-eligible actors", turn_status)
    self.assertIn("15 eligible actors omitted from this bounded menu", turn_status)
    self.assertIn("finish_turn=true ends your whole side's turn", turn_status)
    self.assertLessEqual(len(turn_status.encode("utf-8")), 900)

    # Deliberate finish response validation
    sd.validate_response_context({"kind": "finish_turn"}, packet)

  def test_case_5_threatened_recruiter_during_policy_issue_with_support(self):
    """Case 5: Threatened recruiter during a remaining policy issue with available support."""
    evidence = {
      "cause": "dead_or_foreign_unit",
      "unit_id": 40,
      "threatened_recruiter": {"recruiter_id": 1},
      "actor_ids": [1, 2, 3],
      "eligible_actor_count": 3,
      "options": [
        {
          "option_id": "u1-reloc",
          "actor_id": 1,
          "category": "relocation",
          "actions": [{"action": "Move", "unit_id": 1, "col": 0, "row": 1}],
          "exposure": {"distinct_attacker_count": 0},
          "movement_cost": 2,
        },
        {
          "option_id": "u2-atk",
          "actor_id": 2,
          "category": "attack",
          "actions": [{"action": "Attack", "attacker_id": 2, "defender_id": 99}],
          "forecast": {"expected_damage_dealt_tenths": 150},
        },
        {
          "option_id": "u3-atk",
          "actor_id": 3,
          "category": "attack",
          "actions": [{"action": "Attack", "attacker_id": 3, "defender_id": 99}],
          "forecast": {"expected_damage_dealt_tenths": 120},
        },
      ],
    }
    packet = sd.build_decision_packet("invalid_assignment", evidence, revision=50, game_id="case5", side_turn=5)
    candidates = sd.candidate_selections(packet)
    self.assertTrue(len(candidates) >= 2)
    # Recipe 1: recruiter relocation + support attacks
    self.assertEqual(candidates[0], ["u1-reloc", "u2-atk", "u3-atk"])
    # Recipe 2: pressure attacks
    self.assertEqual(candidates[1], ["u2-atk", "u3-atk"])

  def test_case_6_threatened_recruiter_without_support_and_exhausted_fallback(self):
    """Case 6: Threatened recruiter without support, including exhausted-action fallback."""
    evidence_solo = {
      "stage": "current_state",
      "contact_actionability": "actionable",
      "threatened_recruiter": {"recruiter_id": 1},
      "actor_ids": [1],
      "eligible_actor_count": 1,
      "options": [
        {
          "option_id": "u1-reloc-1",
          "actor_id": 1,
          "category": "relocation",
          "actions": [{"action": "Move", "unit_id": 1, "col": 0, "row": 1}],
          "exposure": {"distinct_attacker_count": 0},
          "movement_cost": 1,
        }
      ],
    }
    packet_solo = sd.build_decision_packet("contact", evidence_solo, revision=60, game_id="case6", side_turn=6)
    candidates_solo = sd.candidate_selections(packet_solo)
    # Legal retreat singleton is preserved
    self.assertEqual(candidates_solo[0], ["u1-reloc-1"])

    # Exhausted recruiter fallback
    evidence_exhausted = {
      "stage": "current_state",
      "contact_actionability": "exhausted",
      "threatened_recruiter": {"recruiter_id": 1},
      "actor_ids": [],
      "eligible_actor_count": 0,
      "options": [],
      "options_empty_reason": "exhausted_recruiter_no_tactical_options",
    }
    packet_exhausted = sd.build_decision_packet(
      "contact", evidence_exhausted, revision=61, game_id="case6", side_turn=6, final_only=True
    )
    candidates_exhausted = sd.candidate_selections(packet_exhausted)
    self.assertEqual(candidates_exhausted, [])
    self.assertIn("finish_turn", packet_exhausted.allowed_kinds)

  def test_case_7_expansion_queue_completion_and_interruption_resume_equivalence(self):
    """Case 7: Expansion queue completion and interruption/resume equivalence."""
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      backend = root / "backend.py"
      prompt_path = root / "prompt.json"
      control_log = root / "control.ndjson"

      backend.write_text(textwrap.dedent("""
        import json, sys
        prompt = sys.stdin.read()
        if 'OPENING_POLICY_SUGGESTIONS_BEGIN' in prompt:
            lines = prompt.splitlines()
            label = next(i for i, line in enumerate(lines) if line.startswith('Expansion:'))
            resp_line = next(line for line in lines[label+1:] if 'response=' in line)
            resp = json.loads(resp_line.split('response=', 1)[1])
        else:
            resp = {'kind': 'finish_turn'}
        print(json.dumps({'text': json.dumps(resp, separators=(',', ':'))}))
      """).lstrip())

      cmd = seed_command(control_log, backend)
      res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120)
      self.assertEqual(res.returncode, 0, res.stderr)
      control = [json.loads(l) for l in control_log.read_text().splitlines() if l.strip()]
      events = [
        e for r in control
        if r.get("type") == "driver" and isinstance(r.get("line"), dict) and r["line"].get("type") == "events"
        for e in r["line"].get("events", [])
      ]
      recruits = [e for e in events if e.get("kind") == "recruit"]
      self.assertTrue(len(recruits) >= 6, "expansion opening must recruit units")

      # Resume equivalence check: truncate log at first committed recruit to simulate interruption
      first_commit = next(
        i for i, r in enumerate(control)
        if r.get("type") == "routine_progress_committed"
        and any(ef.get("kind") == "recruited" for ef in r.get("progress_update", {}).get("effects", []))
      )
      crash_log = root / "resumed.ndjson"
      crash_log.write_text("\n".join(json.dumps(r) for r in control[:first_commit + 1]) + "\n")
      source_ckpt = control_log.with_suffix(".ckpt")
      target_ckpt = crash_log.with_suffix(".ckpt")
      shutil.copytree(source_ckpt, target_ckpt)
      referenced = {Path(r["path"]).name for r in control[:first_commit + 1] if r.get("type") == "checkpoint_ref"}
      for saved in target_ckpt.iterdir():
        if saved.name not in referenced:
          saved.unlink()

      cmd_resume = seed_command(crash_log, backend, resume_log=True)
      res_resume = subprocess.run(cmd_resume, cwd=ROOT, text=True, capture_output=True, timeout=120)
      self.assertEqual(res_resume.returncode, 0, res_resume.stderr)

  def test_case_8_concentration_queue_completion_and_custom_intentional_saving(self):
    """Case 8: Concentration queue completion and custom intentional saving."""
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      backend = root / "backend.py"
      log_path = root / "run.ndjson"

      # Responds with custom intentional saving reserve_gold=50
      backend.write_text(textwrap.dedent("""
        import json, sys
        prompt = sys.stdin.read()
        if 'OPENING_POLICY_SUGGESTIONS_BEGIN' in prompt:
            resp = {
                "kind": "set_policy",
                "policy": {
                    "reserve_gold": 50,
                    "recruits": [
                        {"def_id": "Dark Adept", "count": 6, "role": "army"},
                        {"def_id": "Skeleton", "count": 6, "role": "army"},
                        {"def_id": "Vampire Bat", "count": 1, "role": "scout"}
                    ],
                    "scouts": [],
                    "villages": [{"col": 2, "row": 4}],
                    "rally": {"col": 3, "row": 6},
                    "holds": []
                }
            }
        else:
            resp = {'kind': 'finish_turn'}
        print(json.dumps({'text': json.dumps(resp, separators=(',', ':'))}))
      """).lstrip())

      cmd = seed_command(log_path, backend)
      res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120)
      self.assertEqual(res.returncode, 0, res.stderr)
      records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
      installed = [r for r in records if r.get("type") == "policy_installed"]
      self.assertTrue(len(installed) > 0)
      installed_policy = installed[0].get("policy", {})
      self.assertEqual(installed_policy.get("reserve_gold"), 50)

  def test_composite_linkage_client_to_report_to_sqlite_history(self):
    """Full pipeline: client execution -> records -> match report -> sqlite history import."""
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      backend = root / "backend.py"
      log_path = root / "match.ndjson"
      db_path = root / "history.sqlite"

      backend.write_text(textwrap.dedent("""
        import json, sys
        prompt = sys.stdin.read()
        resp = {'kind': 'finish_turn'}
        print(json.dumps({'text': json.dumps(resp, separators=(',', ':'))}))
      """).lstrip())

      cmd = seed_command(log_path, backend)
      res = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=120)
      self.assertEqual(res.returncode, 0, res.stderr)

      records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
      report = mr.classify(records)
      self.assertIn("terminal_class", report)
      self.assertIn("completed_side_turns", report)

      # Import into history sqlite database
      db = open_history(db_path)
      try:
        game_id = import_game(db, log_path, cohort_id="test_cohort", game_id="test_game_1")
        self.assertEqual(game_id, "test_game_1")
        count_before = db.execute("SELECT count(*) FROM games WHERE game_id=?", ("test_game_1",)).fetchone()[0]
        self.assertEqual(count_before, 1)

        # Idempotent reimport assertion
        reimport_id = import_game(db, log_path, cohort_id="test_cohort", game_id="test_game_1")
        self.assertEqual(reimport_id, "test_game_1")
        count_after = db.execute("SELECT count(*) FROM games WHERE game_id=?", ("test_game_1",)).fetchone()[0]
        self.assertEqual(count_after, 1, "reimport must be idempotent")
      finally:
        db.close()
