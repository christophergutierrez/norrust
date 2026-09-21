"""Tests for the portable decision capsule (Stack 3).

Coverage matches the plan's portability milestone: a capsule copied to a
different temporary directory must still validate and restore, independent
of the archive it was built from. Real-driver tests are skipped when the
built `greedy_driver` binary is absent, matching the pattern in
`tools/test_analysis_client_capture.py`.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from . import decision_capsule as capsule

ROOT = Path(__file__).resolve().parents[1]
DRIVER = Path(os.environ.get(
  "NORRUST_TEST_DRIVER", ROOT / "norrust_core/target/debug/greedy_driver")).resolve()

PROMOTION_CHECKPOINT = ROOT / "tools/fixtures/decision_positions/promotion.json"
HANDOFF_CHECKPOINT = ROOT / "tools/fixtures/decision_positions/handoff.json"
REVISION_286_CHECKPOINT = ROOT / "tools/fixtures/decision_positions/revision-286/checkpoint.json"
REVISION_338_CHECKPOINT = ROOT / "tools/fixtures/decision_positions/revision-338/checkpoint.json"

FIXTURE_1 = ROOT / "tools/fixtures/recruiter_survival/fixture_1_seed_4477_defensive"
FIXTURE_4_PARTIAL = ROOT / "tools/fixtures/recruiter_survival/fixture_4_quiet_control"


def _fixture_1_policy_progress() -> tuple[dict, dict]:
  metadata = json.loads((FIXTURE_1 / "metadata.json").read_text(encoding="utf-8"))
  return metadata["policy"], metadata["progress"]


class BuildAndValidateRoundTripTests(unittest.TestCase):
  """build_capsule -> validate_capsule for a full_client_replay capsule."""

  def test_full_client_replay_round_trip(self):
    policy, progress = _fixture_1_policy_progress()
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      manifest = capsule.build_capsule(
        FIXTURE_1 / "checkpoint.json", capsule_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_1",
                "source_commit": None, "dirty_patch_hash": None},
        policy=policy, progress=progress, request_context={"harness_request_id": "req-1"},
      )
      self.assertEqual(manifest["capability"], capsule.CAPABILITY_FULL_CLIENT_REPLAY)
      self.assertEqual(manifest["provenance_gaps"], {})
      report = capsule.validate_capsule(capsule_dir)
      self.assertEqual(report["problems"], [])
      self.assertTrue(report["ok"])
      self.assertEqual(report["capability"], capsule.CAPABILITY_FULL_CLIENT_REPLAY)

  def test_board_only_capsule_does_not_claim_replay_equivalence(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      manifest = capsule.build_capsule(
        PROMOTION_CHECKPOINT, capsule_dir,
        source={"archive": "grounded-decisions-final-20260906",
                "game_id": "e5894441fc744105623143e8c26bac0a",
                "source_commit": "a6c368f58890bf2e2de2b2edf66046e192f7e31b",
                "dirty_patch_hash": None},
      )
      self.assertEqual(manifest["capability"], capsule.CAPABILITY_BOARD_ONLY)
      self.assertIn("policy", manifest["provenance_gaps"])
      self.assertIn("progress", manifest["provenance_gaps"])
      self.assertIn("request_context", manifest["provenance_gaps"])
      report = capsule.validate_capsule(capsule_dir)
      self.assertTrue(report["ok"], report["problems"])
      self.assertEqual(report["capability"], capsule.CAPABILITY_BOARD_ONLY)

  def test_claiming_full_client_replay_without_policy_fails_validation(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      manifest = capsule.build_capsule(
        PROMOTION_CHECKPOINT, capsule_dir,
        source={"archive": "x", "game_id": "y", "source_commit": None, "dirty_patch_hash": None},
      )
      self.assertEqual(manifest["capability"], capsule.CAPABILITY_BOARD_ONLY)
      # Tamper with the manifest to falsely claim full replay equivalence.
      manifest_path = capsule_dir / capsule.CAPSULE_MANIFEST_NAME
      tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
      tampered["capability"] = capsule.CAPABILITY_FULL_CLIENT_REPLAY
      manifest_path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")

      report = capsule.validate_capsule(capsule_dir)
      self.assertFalse(report["ok"])
      self.assertTrue(any("policy.json is missing" in p for p in report["problems"]))
      self.assertTrue(any("progress.json is missing" in p for p in report["problems"]))
      self.assertTrue(any("request_context.json is missing" in p for p in report["problems"]))

  def test_copied_capsule_validates_from_a_different_directory(self):
    """Plan's portability milestone: a capsule must not depend on its
    original absolute build path."""
    policy, progress = _fixture_1_policy_progress()
    with tempfile.TemporaryDirectory() as td:
      original_dir = Path(td) / "built_here"
      capsule.build_capsule(
        FIXTURE_1 / "checkpoint.json", original_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_1",
                "source_commit": None, "dirty_patch_hash": None},
        policy=policy, progress=progress, request_context={"harness_request_id": "req-1"},
      )
      with tempfile.TemporaryDirectory() as td2:
        moved_dir = Path(td2) / "somewhere" / "else" / "entirely"
        shutil.copytree(original_dir, moved_dir)
        report = capsule.validate_capsule(moved_dir)
        self.assertTrue(report["ok"], report["problems"])
        self.assertEqual(report["capability"], capsule.CAPABILITY_FULL_CLIENT_REPLAY)

  def test_wrong_checkpoint_body_hash_fails_clearly(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      capsule.build_capsule(
        PROMOTION_CHECKPOINT, capsule_dir,
        source={"archive": "x", "game_id": "y", "source_commit": None, "dirty_patch_hash": None},
      )
      checkpoint_path = capsule_dir / capsule.CAPSULE_CHECKPOINT_NAME
      data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
      data["side_turns"] = data["side_turns"] + 1000  # corrupt without breaking JSON shape
      checkpoint_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

      report = capsule.validate_capsule(capsule_dir)
      self.assertFalse(report["ok"])
      self.assertTrue(any("checkpoint body hash mismatch" in p for p in report["problems"]))
      # Names what mismatched: both the capsule.json-recorded and the actual hash.
      mismatch = next(p for p in report["problems"] if "checkpoint body hash mismatch" in p)
      self.assertIn("capsule.json says", mismatch)
      self.assertIn("checkpoint.json is", mismatch)

  def test_non_model_boundary_yields_unsupported_boundary_not_an_advanced_board(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      manifest = capsule.build_capsule(
        FIXTURE_4_PARTIAL / "checkpoint.json", capsule_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_4",
                "source_commit": None, "dirty_patch_hash": None},
      )
      self.assertEqual(manifest["capability"], capsule.CAPABILITY_UNSUPPORTED_BOUNDARY)
      self.assertIn("boundary", manifest["provenance_gaps"])
      # The checkpoint written into the capsule is the fixture's own
      # boundary, unmodified -- nothing advanced it to "model".
      checkpoint_data = json.loads((capsule_dir / capsule.CAPSULE_CHECKPOINT_NAME).read_text())
      self.assertEqual(checkpoint_data["boundary"], "partial")
      report = capsule.validate_capsule(capsule_dir)
      self.assertTrue(report["ok"], report["problems"])
      self.assertEqual(report["capability"], capsule.CAPABILITY_UNSUPPORTED_BOUNDARY)

  def test_pending_opponent_turn_true_yields_unsupported_boundary(self):
    with tempfile.TemporaryDirectory() as td:
      source_checkpoint = Path(td) / "checkpoint.json"
      data = json.loads(PROMOTION_CHECKPOINT.read_text(encoding="utf-8"))
      data["pending_opponent_turn"] = True
      source_checkpoint.write_text(json.dumps(data), encoding="utf-8")
      capsule_dir = Path(td) / "capsule"
      manifest = capsule.build_capsule(
        source_checkpoint, capsule_dir,
        source={"archive": "x", "game_id": "y", "source_commit": None, "dirty_patch_hash": None},
      )
      self.assertEqual(manifest["capability"], capsule.CAPABILITY_UNSUPPORTED_BOUNDARY)

  def test_original_fixture_files_are_byte_identical_after_building(self):
    before = PROMOTION_CHECKPOINT.read_bytes()
    with tempfile.TemporaryDirectory() as td:
      capsule.build_capsule(
        PROMOTION_CHECKPOINT, Path(td) / "capsule",
        source={"archive": "x", "game_id": "y", "source_commit": None, "dirty_patch_hash": None},
      )
    after = PROMOTION_CHECKPOINT.read_bytes()
    self.assertEqual(before, after)

  def test_all_named_real_checkpoints_build_without_raising(self):
    checkpoints = [
      PROMOTION_CHECKPOINT, HANDOFF_CHECKPOINT,
      REVISION_286_CHECKPOINT, REVISION_338_CHECKPOINT,
    ]
    for name in ("fixture_1_seed_4477_defensive", "fixture_2_seed_7731_defensive",
                 "fixture_3_late_emergency", "fixture_4_quiet_control"):
      checkpoints.append(ROOT / f"tools/fixtures/recruiter_survival/{name}/checkpoint.json")
    with tempfile.TemporaryDirectory() as td:
      for i, checkpoint_path in enumerate(checkpoints):
        before = checkpoint_path.read_bytes()
        manifest = capsule.build_capsule(
          checkpoint_path, Path(td) / f"capsule_{i}",
          source={"archive": "x", "game_id": str(i), "source_commit": None, "dirty_patch_hash": None},
        )
        self.assertIn(manifest["capability"], capsule.CAPABILITIES)
        self.assertEqual(checkpoint_path.read_bytes(), before)


@unittest.skipUnless(DRIVER.is_file(), "built greedy_driver required; run tools.fast_check first")
class RestoreAndReplayTests(unittest.TestCase):
  """Real-driver tests: restore a capsule and query/replay against it."""

  def test_restore_board_only_capsule_and_query_initial_state(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      capsule.build_capsule(
        FIXTURE_1 / "checkpoint.json", capsule_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_1",
                "source_commit": None, "dirty_patch_hash": None},
      )
      workspace = Path(td) / "workspace"
      handle = capsule.restore_capsule(capsule_dir, DRIVER, workspace)
      try:
        self.assertEqual(handle.observation["state_revision"], 231)
        self.assertIsNone(handle.policy)
        self.assertIn("rng_state", handle.replay_state)
        # Private replay state must not appear inside the observation.
        self.assertNotIn("rng_state", handle.observation)
      finally:
        capsule.close_capsule_session(handle)

  def test_restore_refuses_unsupported_boundary(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      capsule.build_capsule(
        FIXTURE_4_PARTIAL / "checkpoint.json", capsule_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_4",
                "source_commit": None, "dirty_patch_hash": None},
      )
      workspace = Path(td) / "workspace"
      with self.assertRaises(capsule.CapsuleUnsupportedBoundaryError):
        capsule.restore_capsule(capsule_dir, DRIVER, workspace)

  def test_restore_works_from_a_copied_capsule_directory(self):
    policy, progress = _fixture_1_policy_progress()
    with tempfile.TemporaryDirectory() as td:
      original_dir = Path(td) / "built_here"
      capsule.build_capsule(
        FIXTURE_1 / "checkpoint.json", original_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_1",
                "source_commit": None, "dirty_patch_hash": None},
        policy=policy, progress=progress, request_context={"harness_request_id": "req-1"},
      )
      with tempfile.TemporaryDirectory() as td2:
        moved_dir = Path(td2) / "moved" / "capsule"
        shutil.copytree(original_dir, moved_dir)
        workspace = Path(td2) / "workspace"
        handle = capsule.restore_capsule(moved_dir, DRIVER, workspace)
        try:
          self.assertEqual(handle.observation["state_revision"], 231)
          self.assertEqual(handle.policy, policy)
          self.assertEqual(handle.progress, progress)
        finally:
          capsule.close_capsule_session(handle)

  def test_replay_recorded_action_reports_integrity_defect_on_mismatch(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      capsule.build_capsule(
        FIXTURE_1 / "checkpoint.json", capsule_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_1",
                "source_commit": None, "dirty_patch_hash": None},
      )
      workspace = Path(td) / "workspace"
      result = capsule.replay_recorded_action(
        capsule_dir, DRIVER, workspace,
        {"actions": [{"action": "FinishWithGreedy", "groups": [], "holds": []}],
         "expected_state_revision": 999999},
      )
      self.assertTrue(result["integrity_defect"])
      self.assertIn("state_revision", result["mismatches"])
      self.assertEqual(result["mismatches"]["state_revision"]["recorded"], 999999)

  def test_replay_recorded_action_matches_when_expectation_is_correct(self):
    with tempfile.TemporaryDirectory() as td:
      capsule_dir = Path(td) / "capsule"
      capsule.build_capsule(
        FIXTURE_1 / "checkpoint.json", capsule_dir,
        source={"archive": "recruiter_survival", "game_id": "fixture_1",
                "source_commit": None, "dirty_patch_hash": None},
      )
      workspace = Path(td) / "workspace"
      result = capsule.replay_recorded_action(
        capsule_dir, DRIVER, workspace,
        {"actions": [{"action": "FinishWithGreedy", "groups": [], "holds": []}]},
      )
      self.assertFalse(result["integrity_defect"])
      self.assertEqual(result["mismatches"], {})
      self.assertIsNotNone(result["replayed_state"])


if __name__ == "__main__":
  unittest.main()


class RevisionConflictTests(unittest.TestCase):
  """A contradicted identity is a conflict, not something to silently fix.

  The checkpoint is ground truth for the revision, so its value must win. But a
  caller that supplied a different one has a bug, and a capsule that quietly
  corrects it conceals that bug. Both facts are kept.
  """

  def _fixture(self):
    return Path(__file__).resolve().parents[1] / "tools/fixtures/decision_positions/promotion.json"

  def test_contradicted_revision_is_recorded_not_silently_corrected(self):
    with tempfile.TemporaryDirectory() as td:
      manifest = capsule.build_capsule(
        self._fixture(), Path(td) / "cap",
        source={"archive": "x", "game_id": "g"},
        decision={"decision_id": "d1", "state_revision": 999999})
      truth = json.loads(self._fixture().read_text())["save_state"]["state_revision"]
      self.assertEqual(truth, manifest["decision"]["state_revision"])
      conflict = manifest["decision"].get("state_revision_conflict")
      self.assertIsNotNone(conflict, "a contradicted revision must be recorded")
      self.assertEqual(999999, conflict["supplied"])
      self.assertEqual(truth, conflict["checkpoint"])

  def test_agreeing_revision_records_no_conflict(self):
    with tempfile.TemporaryDirectory() as td:
      truth = json.loads(self._fixture().read_text())["save_state"]["state_revision"]
      manifest = capsule.build_capsule(
        self._fixture(), Path(td) / "cap",
        source={"archive": "x", "game_id": "g"},
        decision={"decision_id": "d1", "state_revision": truth})
      self.assertNotIn("state_revision_conflict", manifest["decision"])

  def test_absent_revision_records_no_conflict(self):
    with tempfile.TemporaryDirectory() as td:
      manifest = capsule.build_capsule(
        self._fixture(), Path(td) / "cap",
        source={"archive": "x", "game_id": "g"},
        decision={"decision_id": "d1"})
      self.assertNotIn("state_revision_conflict", manifest["decision"])


@unittest.skipUnless(
  (Path(os.environ.get("NORRUST_TEST_DRIVER",
                       ROOT / "norrust_core/target/debug/greedy_driver"))).is_file(),
  "built greedy_driver required; run tools.fast_check first")
class CapsuleQueryAdapterTests(unittest.TestCase):
  """The seam between a restored capsule and the bounded evaluator.

  The evaluator is a pure function of a callable so it can be tested without a
  driver, which leaves exactly one thing unproven: that the adapter really
  speaks the driver's protocol. This test closes that gap against a real
  process rather than a mock.
  """

  def _driver(self):
    return Path(os.environ.get("NORRUST_TEST_DRIVER",
                               ROOT / "norrust_core/target/debug/greedy_driver"))

  def test_adapter_drives_a_real_bounded_evaluation(self):
    from . import bounded_evaluation as be
    fixture = ROOT / "tools/fixtures/decision_positions/promotion.json"
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      capsule.build_capsule(fixture, root / "cap", source={"archive": "x", "game_id": "g"})
      handle = capsule.restore_capsule(root / "cap", self._driver(), root / "ws")
      try:
        query = capsule.capsule_query_fn(handle)
        revision = handle.observation["state_revision"]
        result = be.evaluate(
          query, state_revision=revision, model_side=0, opponent_side=1,
          actual_choice={"orders": [{"action": "EndTurn"}]},
          config=be.EvaluationConfig(seed_schedule=(1, 2, 3)))
      finally:
        capsule.close_capsule_session(handle)
    candidate = result["candidates"][0]
    self.assertEqual([1, 2, 3], list(candidate["completed_seeds"]))
    self.assertEqual([], list(candidate["censored_seeds"]))
    self.assertTrue(candidate["legal"])

  def test_best_candidate_never_claims_an_optimal_move(self):
    """A ranking over tested candidates is not a claim about the position."""
    from . import bounded_evaluation as be
    fixture = ROOT / "tools/fixtures/decision_positions/promotion.json"
    with tempfile.TemporaryDirectory() as td:
      root = Path(td)
      capsule.build_capsule(fixture, root / "cap", source={"archive": "x", "game_id": "g"})
      handle = capsule.restore_capsule(root / "cap", self._driver(), root / "ws")
      try:
        query = capsule.capsule_query_fn(handle)
        result = be.evaluate(
          query, state_revision=handle.observation["state_revision"],
          model_side=0, opponent_side=1,
          actual_choice={"orders": [{"action": "EndTurn"}]},
          config=be.EvaluationConfig(
            seed_schedule=(1, 2),
            score_fn=lambda outcome: (outcome or {}).get("gold_after", 0),
            score_name="gold_after_predeclared"))
      finally:
        capsule.close_capsule_session(handle)
    verdict = result["best_candidate"]["verdict"]
    self.assertIn("best among tested candidates under this evaluator", verdict)
    self.assertNotIn("optimal move", verdict)
