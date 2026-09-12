import json
import tempfile
import unittest
from pathlib import Path

from .model_usage import ModelCall
from .llm_supervisor import _game_end_terminal
from .watchdog_review import review
from .watchdog_outcomes import read_observer_outcomes

HAS_ROLES = "call_role" in ModelCall.__dataclass_fields__


class WatchdogReviewTests(unittest.TestCase):
    def test_driver_game_end_classification_preserves_non_gameplay_and_unknown(self):
        infrastructure = _game_end_terminal([{
            "type": "driver", "line": {"type": "game_end",
                                          "reason": "infrastructure_failure",
                                          "winner": None, "code": "driver_failed"}}])
        self.assertEqual(infrastructure["terminal_class"], "infrastructure")
        self.assertIsNone(infrastructure["winner"])
        missing = _game_end_terminal([{
            "type": "driver", "line": {"type": "game_end", "winner": 1}}])
        self.assertEqual(missing["terminal_class"], "infrastructure")
        self.assertIsNone(missing["winner"])
        gameplay = _game_end_terminal([{
            "type": "driver", "line": {"type": "game_end", "reason": "winner", "winner": 1}}])
        self.assertEqual(gameplay["terminal_class"], "gameplay")
        self.assertEqual(gameplay["winner"], 1)

    def _run_files(self, root: Path, *, conversation="catalog-game", evidence=None):
        log = root / "match.ndjson"
        metadata = {"type": "metadata", "conversation_id": conversation}
        log.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
        state_root = root / "match.watchdog"
        state_root.mkdir()
        packet = {"run_id": "run-uuid", "stage": "terminal", "revision": 7,
                  "alerts": [{"kind": "repeated_stream_passage", "identity": "incident"}],
                  "evidence_ids": evidence or [], "coverage_events": [], "degraded": False}
        (state_root / "state.json").write_text(json.dumps({"run_id": "run-uuid", "latest": {"packet": packet}}))
        return log, state_root

    def test_owned_observer_state_and_natural_game_end_win_race(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log, state_root = self._run_files(root, evidence=["e1", "e2", "e3"])
            with log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "game_end", "winner": "side-0", "reason": "winner"}) + "\n")
                stream.write(json.dumps({"type": "terminal", "terminal_class": "observer_interrupted",
                                         "reason": "observer_interrupted"}) + "\n")
            observer = {"run_id": "run-uuid", "dispatched_calls": 1,
                        "last_verdict": {"decision": "stop", "reason_code": "repeated_no_progress"}}
            (state_root / "observer-state.json").write_text(json.dumps(observer))
            packet = review(log)
            from .llm_supervisor import _last_terminal
            self.assertEqual(_last_terminal(log)["terminal_class"], "gameplay")
            self.assertEqual(packet["source"]["conversation_id"], "catalog-game")
            self.assertEqual(packet["game_result"]["terminal_class"], "gameplay")
            self.assertEqual(packet["game_result"]["winner"], "side-0")
            self.assertTrue(packet["proven_terminal"])
            self.assertFalse(packet["stop_effect"]["effective"])
            self.assertEqual(packet["coverage"]["evidence_ids"], ["e1", "e2"])
            self.assertEqual(packet["incidents"][0]["evidence_ids"], ["e1", "e2"])

    def test_review_preserves_driver_failure_game_end_without_inventing_winner(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata", "conversation_id": "catalog-game"}) + "\n" +
                           json.dumps({"type": "driver", "line": {"type": "game_end",
                               "reason": "infrastructure_failure", "winner": None,
                               "code": "driver_failed"}}) + "\n", encoding="utf-8")
            packet = review(log)
            self.assertTrue(packet["proven_terminal"])
            self.assertEqual(packet["game_result"]["terminal_class"], "infrastructure")
            self.assertIsNone(packet["game_result"]["winner"])

    @unittest.skipUnless(HAS_ROLES, "role accounting is supplied by the observer stack")
    def test_sidecar_filters_foreign_conversation_and_fake_is_not_network_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log, state_root = self._run_files(root)
            rows = []
            for game_id, call_id in (("catalog-game", "observer-1"), ("other-game", "observer-foreign")):
                rows.append(dict(ModelCall(game_id=game_id, call_id=call_id, call_role="observer",
                                           provider="fake", status="completed", total_tokens=9,
                                           input_tokens=5, output_tokens=4).to_row(), record_kind="final"))
            (root / "usage.ndjson").write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            (state_root / "observer-state.json").write_text(json.dumps(
                {"run_id": "run-uuid", "dispatched_calls": 1,
                 "last_verdict": {"decision": "continue"}}))
            packet = review(log)
            self.assertEqual(packet["usage"]["observer"]["calls"], 1)
            self.assertIn("foreign_records_filtered:1", packet["usage"]["malformed_records"])
            self.assertEqual(packet["model_evaluation"]["status"], "offline_fake")
            self.assertIsNone(packet["model_evaluation"]["network_calls"])

    def test_missing_conversation_does_not_guess_from_run_uuid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata"}) + "\n")
            state_root = root / "match.watchdog"
            state_root.mkdir()
            (state_root / "state.json").write_text(json.dumps({"run_id": "run-uuid"}))
            row = dict(ModelCall(game_id="run-uuid", call_id="observer-1",
                                 provider="real", status="completed", total_tokens=9).to_row(), record_kind="final")
            (root / "usage.ndjson").write_text(json.dumps(row) + "\n")
            packet = review(log)
            self.assertIsNone(packet["source"]["conversation_id"])
            self.assertEqual(packet["usage"]["observer"]["calls"], 0)
            self.assertIn("conversation_identity_unknown", packet["coverage"]["events"])
            self.assertEqual(packet["model_evaluation"]["status"], "unknown")

    def test_recorded_off_mode_proves_no_observer_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "supervisor_attempt_start",
                                       "watchdog_mode": "off"}) + "\n")
            self.assertEqual(review(log)["model_evaluation"]["status"], "not_run")

    def test_valid_observer_state_with_zero_calls_is_known_not_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log, state_root = self._run_files(root)
            (state_root / "observer-state.json").write_text(json.dumps(
                {"run_id": "run-uuid", "mode": "observe", "dispatched_calls": 0}))
            self.assertEqual(review(log)["model_evaluation"]["status"], "not_run")

    def test_failed_real_receipt_is_not_recorded_as_a_successful_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            log, state_root = self._run_files(root)
            failed = ModelCall(game_id="catalog-game", call_id="observer-1",
                               call_role="observer", provider="fireworks",
                               status="failed", error_code="insufficient_credit")
            (root / "usage.ndjson").write_text(
                json.dumps(dict(failed.to_row(), record_kind="final")) + "\n")
            (state_root / "observer-state.json").write_text(json.dumps(
                {"run_id": "run-uuid", "dispatched_calls": 1}))
            packet = review(log)
            self.assertEqual(packet["model_evaluation"]["status"], "failed")
            self.assertEqual(packet["model_evaluation"]["network_calls"], 1)

    def test_pending_inspect_and_malformed_journal_are_coverage_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "observer.journal.ndjson"
            path.write_text('{"type":"dispatch"}\n{"type":"verdict","decision":"inspect"}\n'
                            '42\n{"type":"investigation_error","error":"timeout"}\n')
            outcomes = read_observer_outcomes(path)
            self.assertFalse(outcomes["judgment_observed"])
            self.assertEqual(outcomes["last_outcome"], "failure")
            self.assertGreaterEqual(outcomes["observer_failures"], 2)


if __name__ == "__main__":
    unittest.main()
