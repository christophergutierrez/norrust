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
