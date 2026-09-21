"""Small protocol-boundary regressions for the offline tactical comparator."""
from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from . import tactical_comparison as comparison


class TacticalComparisonDefaultsCharacterizationTests(unittest.TestCase):
  """Locks in the pre-generalization behavior of ``_materialize``/``_start``.

  Stack 3 (decision_capsule.py) parameterizes the scenario, factions, gold,
  seed, launch turns and repo root that used to be hardcoded here. These
  tests pin the exact defaults so that generalizing the machinery cannot
  silently change what the Stack 4 recruiter comparison (``run_comparison``/
  ``main`` called with no arguments) does.
  """

  def test_materialize_defaults_to_the_recruiter_fixture_scenario_board(self):
    with tempfile.TemporaryDirectory() as td:
      directory = Path(td)
      source = directory / "checkpoint.json"
      source.write_text(json.dumps({
        "board_path": "/somewhere/else/board.toml",
        "save_state": {"board_path": "/somewhere/else/board.toml", "state_revision": 231},
        "side_turns": 12, "boundary": "model", "pending_opponent_turn": False,
      }), encoding="utf-8")
      result_path = comparison._materialize(source, directory / "out.json")
      data = json.loads(result_path.read_text(encoding="utf-8"))
      expected_board = str(comparison.ROOT / "scenarios/big_battle_6/board.toml")
      self.assertEqual(data["board_path"], expected_board)
      self.assertEqual(data["save_state"]["board_path"], expected_board)

  def test_materialize_honors_a_different_scenario_and_root(self):
    with tempfile.TemporaryDirectory() as td:
      directory = Path(td)
      repo_root = directory / "repo"
      board_dir = repo_root / "scenarios" / "other_scenario"
      board_dir.mkdir(parents=True)
      (board_dir / "board.toml").write_text("# board\n", encoding="utf-8")
      source = directory / "checkpoint.json"
      source.write_text(json.dumps({
        "board_path": "/irrelevant/board.toml",
        "save_state": {"board_path": "/irrelevant/board.toml", "state_revision": 5},
        "side_turns": 1, "boundary": "model", "pending_opponent_turn": False,
      }), encoding="utf-8")
      result_path = comparison._materialize(
        source, directory / "out.json", scenario="other_scenario", repo_root=repo_root)
      data = json.loads(result_path.read_text(encoding="utf-8"))
      expected_board = str(board_dir / "board.toml")
      self.assertEqual(data["board_path"], expected_board)
      self.assertEqual(data["save_state"]["board_path"], expected_board)

  def test_start_builds_the_recruiter_fixture_argv_by_default(self):
    with tempfile.TemporaryDirectory() as td:
      driver = Path(td) / "driver"
      driver.write_bytes(b"")
      captured = {}

      def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return Mock()

      with patch.object(comparison.subprocess, "Popen", side_effect=fake_popen):
        comparison._start(Path("checkpoint.json"), Path("checkpoints"), driver=driver)
      self.assertEqual(captured["argv"], [
        str(driver), "--scenario", "big_battle_6", "--faction0", "undead",
        "--faction1", "undead", "--gold", "300", "--seed", "4477",
        "--llm-side", "0", "--max-turns", "16", "--incremental-turns",
        "--checkpoint-dir", "checkpoints", "--resume-checkpoint", "checkpoint.json",
      ])
      self.assertEqual(captured["kwargs"]["cwd"], comparison.ROOT)

  def test_start_honors_overridden_launch_parameters(self):
    with tempfile.TemporaryDirectory() as td:
      driver = Path(td) / "driver"
      driver.write_bytes(b"")
      captured = {}

      def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        return Mock()

      with patch.object(comparison.subprocess, "Popen", side_effect=fake_popen):
        comparison._start(
          Path("checkpoint.json"), Path("checkpoints"), driver=driver,
          scenario="other_scenario", faction0="loyalists", faction1="rebels",
          gold=150, seed=99, llm_side=1, max_turns=8, incremental_turns=False)
      self.assertEqual(captured["argv"], [
        str(driver), "--scenario", "other_scenario", "--faction0", "loyalists",
        "--faction1", "rebels", "--gold", "150", "--seed", "99",
        "--llm-side", "1", "--max-turns", "8",
        "--checkpoint-dir", "checkpoints", "--resume-checkpoint", "checkpoint.json",
      ])


class TacticalComparisonBoundaryTests(unittest.TestCase):
  def test_checkpoint_requires_matching_digest_revision_and_model_boundary(self):
    with tempfile.TemporaryDirectory() as td:
      directory = Path(td)
      payload = {
        "save_state": {"state_revision": 231},
        "side_turns": 12,
        "boundary": "model",
        "pending_opponent_turn": False,
      }
      encoded = json.dumps(payload, separators=(",", ":")).encode()
      path = directory / "12-231-model.json"
      path.write_bytes(encoded)
      digest = hashlib.sha256(encoded).hexdigest()
      record = {
        "type": "checkpoint", "path": path.name, "digest": digest,
        "state_revision": 231, "side_turns": 12,
        "boundary": "model", "pending_opponent_turn": False,
      }
      accepted = comparison._latest_checkpoint(directory, [record])
      self.assertEqual(accepted["state_revision"], 231)
      self.assertEqual(accepted["side_turns"], 12)

      for field, value in (("digest", "wrong"), ("state_revision", 230),
                           ("boundary", "postbatch"),
                           ("pending_opponent_turn", True)):
        damaged = dict(record, **{field: value})
        self.assertIsNone(comparison._latest_checkpoint(directory, [damaged]))

  def test_invalid_or_incomplete_state_is_unknown_shape(self):
    valid = {"units": [{"id": 1, "faction": 0}],
             "terrain": [{"col": 0, "row": 0, "terrain_id": "village", "owner": -1}]}
    self.assertTrue(comparison._valid_state(valid))
    self.assertFalse(comparison._valid_state({"units": valid["units"]}))
    self.assertFalse(comparison._valid_state({
      "units": [{"id": True, "faction": 0}], "terrain": []}))
    self.assertFalse(comparison._valid_state({
      "units": valid["units"],
      "terrain": [{"col": 0, "row": 0, "terrain_id": "village"}],
    }))

  def test_postsubmit_state_without_opponent_horizon_stays_unknown(self):
    initial = {
      "type": "state", "active_faction": 0, "state_revision": 231,
      "units": [{"id": 1, "faction": 0, "def_id": "Ghoul", "hp": 30}],
      "terrain": [{"col": 0, "row": 0, "terrain_id": "village", "owner": -1}],
    }
    postsubmit = dict(initial, state_revision=239)
    process = Mock()
    process.stdin = io.BytesIO()
    process.stdout = io.BytesIO()  # EOF models the driver stopping before Greedy.
    process.stderr = io.BytesIO()
    process.poll.return_value = None
    routine = {
      "ok": True,
      "body": {"evidence": {
        "stage": "current_state",
        "options": [{"option_id": "u1-relocate-1", "actions": []}],
      }},
    }
    validation = {"ok": True, "body": {"valid": True}}
    reference = {"side_turns": 12, "threatened_recruiter_id": 1}
    checkpoint = {
      "path": "12-231-model.json", "side_turns": 12, "state_revision": 231,
      "save_state": {"state_revision": 231},
    }
    with patch.object(comparison, "_materialize", return_value=Path("checkpoint.json")), \
        patch.object(comparison, "_start", return_value=process), \
        patch.object(comparison, "_read_until", side_effect=([
          initial], [
          {"type": "status", "ok": True, "committed": True}, postsubmit])), \
        patch.object(comparison, "_query", side_effect=[
          (routine, [routine]), (validation, [validation])]), \
        patch.object(comparison, "_latest_checkpoint", return_value=checkpoint), \
        patch.object(comparison.select, "select", return_value=([process.stdout], [], [])):
      result = comparison._case_result("no_sweep", [], reference)

    self.assertTrue(result["committed"])
    self.assertFalse(result["evidence_coverage"]["final_state_after_opponent"])
    self.assertEqual(result["known_material_losses"], "unknown")
    self.assertEqual(result["ownership_changes"], "unknown")
    self.assertEqual(result["recruiter"], {"survived": "unknown", "hp": "unknown"})


if __name__ == "__main__":
  unittest.main()
