import json
import tempfile
import unittest
from pathlib import Path

from tools.analysis_capture import AnalysisWriter, build_manifest
from tools.controlled_experiment import aggregate_results, build_manifest as build_experiment_manifest
from tools.game_analysis import build_report, run_validate


class AnalysisEndToEndTests(unittest.TestCase):
    def test_capture_to_improvement_report_and_experiment_denominators(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / "match.ndjson"
            log.write_text(json.dumps({"type": "metadata", "conversation_id": "e2e",
                                       "scenario": "s", "seed": 1}) + "\n")
            manifest = build_manifest(conversation_id="e2e", game_log="../match.ndjson",
                                      source_commit="test", driver_hash="d",
                                      data_hash="data", scenario_hash="scenario",
                                      canonical_prompt_hash="prompt",
                                      fixed_prefix_sha256="prefix", game_seed=1,
                                      controlled_side=0,
                                      opponent_identity={"kind": "greedy", "version": "test"},
                                      launch={"driver": "test", "seed": 1})
            writer = AnalysisWriter.create(str(log), manifest)
            decision = writer.next_decision_id()
            writer.record("decision_start", decision_id=decision,
                          side_turn_id="e2e:side_turn:1", state_revision=1)
            writer.record("candidate_packet", decision_id=decision,
                          side_turn_id="e2e:side_turn:1", state_revision=1,
                          body={"packet": {"options": [{"id": "a"}],
                                            "coverage": {"options_truncated": False}}})
            writer.record("turn_boundary", decision_id=decision,
                          side_turn_id="e2e:side_turn:1", state_revision=1,
                          body={"phase": "started"})
            writer.record("game_terminal", decision_id=decision,
                          side_turn_id="e2e:side_turn:1", state_revision=1,
                          body={"reason": "test"})
            writer.close()

            code, _ = run_validate(log)
            self.assertEqual(code, 0)
            report = build_report(log)
            self.assertEqual(report["coverage_status"], "complete")
            self.assertEqual(report["decisions"]["items"][0]["decision_id"],
                             "e2e:decision:1")
            self.assertEqual(report["turns"]["terminal_partial_turns"], ["e2e:side_turn:1"])

            experiment = build_experiment_manifest(scenarios=("s",), seeds=(1,), sides=(0,))
            aggregate = aggregate_results(experiment, [])
            self.assertEqual(aggregate["denominator"]["scheduled"], 3)
            self.assertTrue(all(summary["unrun"] == 1
                                for summary in aggregate["summary"].values()))


if __name__ == "__main__":
    unittest.main()
