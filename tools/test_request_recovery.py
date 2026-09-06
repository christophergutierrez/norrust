import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from .luna_reconcile import (
    COMMITTED, COMPLETED_UNCONSUMED, CONSUMED_UNCOMMITTED, INTERRUPTED, UNKNOWN,
    reconcile_request, restart_decision,
)
from .llm_supervisor import run as supervisor_run


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.request = self.root / "request"
        self.request.mkdir()
        (self.request / "answer.json").write_text("{}\n")

    def tearDown(self):
        self.temp.cleanup()

    def state(self, status="completed", **extra):
        return {"request_id": "r1", "state": status, "answer_path": "answer.json",
                "metadata": {}, **extra}

    def test_completed_answer_is_reusable_until_consumed(self):
        result = reconcile_request(self.state(), [], request_dir=self.request)
        self.assertEqual(result.state, COMPLETED_UNCONSUMED)
        self.assertTrue(result.safe_to_restart)
        self.assertEqual(restart_decision(result)[0], True)

    def test_consumed_without_acceptance_stops(self):
        result = reconcile_request(self.state(), [{"type": "reply_consumed", "request_id": "r1"}],
                                   request_dir=self.request)
        self.assertEqual(result.state, CONSUMED_UNCOMMITTED)
        self.assertFalse(result.safe_to_restart)

    def test_commit_requires_matching_checkpoint(self):
        checkpoint_dir = self.root / "checkpoints"
        checkpoint_dir.mkdir()
        payload = b'{"state_revision": 4}\n'
        path = checkpoint_dir / "r1.json"
        path.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        state = self.state(metadata={"checkpoint_path": "r1.json", "checkpoint_digest": digest})
        records = [{"type": "accepted_batch", "request_id": "r1"},
                   {"type": "checkpoint_ref", "request_id": "r1",
                    "path": "r1.json", "digest": digest}]
        result = reconcile_request(state, records, checkpoint_dir, request_dir=self.request)
        self.assertEqual(result.state, COMMITTED)
        self.assertFalse(result.safe_to_restart)

    def test_checkpoint_mismatch_stops_even_after_acceptance(self):
        checkpoint_dir = self.root / "checkpoints"
        checkpoint_dir.mkdir()
        path = checkpoint_dir / "r1.json"
        path.write_text("actual\n")
        state = self.state(metadata={"checkpoint_path": "r1.json", "checkpoint_digest": "0" * 64})
        records = [{"type": "accepted_batch", "request_id": "r1"},
                   {"type": "checkpoint_ref", "request_id": "r1",
                    "path": "r1.json", "digest": "0" * 64}]
        result = reconcile_request(state, records, checkpoint_dir, request_dir=self.request)
        self.assertEqual(result.state, UNKNOWN)
        self.assertIn("mismatch", result.reason)

    def test_interrupted_requires_verified_cleanup(self):
        result = reconcile_request(self.state("interrupted", answer_path=None,
                                             cleanup_verified=True), request_dir=self.request)
        self.assertEqual(result.state, INTERRUPTED)
        self.assertTrue(result.safe_to_restart)
        self.assertEqual(reconcile_request(self.state("interrupted", answer_path=None),
                                           request_dir=self.request).state, UNKNOWN)

    def test_active_failed_and_unknown_stop(self):
        for status in ("prepared", "dispatched", "failed", "unknown"):
            result = reconcile_request(self.state(status), request_dir=self.request)
            self.assertEqual(result.state, UNKNOWN)
            self.assertFalse(result.safe_to_restart)

    def test_missing_answer_is_unknown(self):
        (self.request / "answer.json").unlink()
        self.assertEqual(reconcile_request(self.state(), request_dir=self.request).state, UNKNOWN)

    def test_completed_with_unlinked_checkpoint_does_not_replay(self):
        state = self.state(metadata={"checkpoint_digest": "a" * 64})
        result = reconcile_request(state, [], self.root / "checkpoints", request_dir=self.request)
        self.assertEqual(result.state, UNKNOWN)
        self.assertFalse(result.safe_to_restart)

    def test_supervisor_restarts_only_for_safe_reconciliation(self):
        log = self.root / "match.ndjson"
        log.write_text(json.dumps({"type": "terminal", "terminal_class": "infrastructure"}) + "\n")
        checkpoint_dir = log.with_suffix(".ckpt")
        checkpoint_dir.mkdir()
        (checkpoint_dir / "checkpoint.json").write_text("{}\n")
        state_path = self.request / "state.json"
        state_path.write_text(json.dumps({"request_id": "r1", "state": "completed",
                                           "answer_path": "answer.json"}), encoding="utf-8")
        with mock.patch("subprocess.run", side_effect=[mock.Mock(returncode=2), mock.Mock(returncode=0)]) as process:
            self.assertEqual(0, supervisor_run(["client", "--log", str(log)], log, 1, state_path))
        self.assertEqual(2, process.call_count)

    def test_supervisor_stops_when_reconciliation_is_ambiguous(self):
        log = self.root / "match.ndjson"
        log.write_text(json.dumps({"type": "terminal", "terminal_class": "infrastructure"}) + "\n")
        checkpoint_dir = log.with_suffix(".ckpt")
        checkpoint_dir.mkdir()
        (checkpoint_dir / "checkpoint.json").write_text("{}\n")
        state_path = self.request / "state.json"
        state_path.write_text(json.dumps({"request_id": "r1", "state": "completed",
                                           "answer_path": "answer.json"}), encoding="utf-8")
        log.write_text(log.read_text() + json.dumps({"type": "reply_consumed", "request_id": "r1"}) + "\n")
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=2)) as process:
            self.assertEqual(2, supervisor_run(["client", "--log", str(log)], log, 1, state_path))
        self.assertEqual(1, process.call_count)


if __name__ == "__main__":
    unittest.main()
