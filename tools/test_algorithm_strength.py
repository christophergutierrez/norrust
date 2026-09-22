"""Protocol and accounting tests for frozen gameplay evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import algorithm_strength as strength


class AlgorithmStrengthTests(unittest.TestCase):
    def test_suites_have_declared_sizes_and_correct_controlled_player(self):
        self.assertEqual(len(strength.build_schedule(suite="smoke")), 4)
        self.assertEqual(len(strength.build_schedule(suite="screen")), 32)
        self.assertEqual(len(strength.build_schedule(suite="development")), 256)
        self.assertEqual(len(strength.build_schedule(suite="heldout")), 512)
        for suite in ("smoke", "screen", "development", "heldout"):
            for cell in strength.build_schedule(suite=suite):
                self.assertEqual(cell["controlled_algorithm"], "coordinated")
                command = strength.command_for(cell, Path("self-play"))
                self.assertIn("coordinated", command)
        smoke = strength.build_schedule(suite="smoke")
        self.assertEqual([(c["opponent"], c["controlled_side"], c["first"]) for c in smoke], [
            ("greedy", 0, "team1"), ("greedy", 1, "team1"),
            ("greedy-look-ahead", 0, "team2"), ("greedy-look-ahead", 1, "team2")])

    def test_command_pins_all_treatment_settings(self):
        cell = strength.build_schedule(suite="smoke")[0]
        command = strength.command_for(cell, Path("self-play"), Path("out/trace"))
        self.assertEqual(command[command.index("--ai1") + 1], "coordinated")
        self.assertEqual(command[command.index("--ai2") + 1], "greedy")
        self.assertEqual(command[command.index("--second-gold") + 1], "0")
        self.assertEqual(command[command.index("--threads") + 1], "1")
        self.assertEqual(command[command.index("--recruit1-policy") + 1], "first-affordable")
        self.assertEqual(command[command.index("--recruit2-policy") + 1], "first-affordable")
        self.assertIn("--record-dir", command)

    def test_caps_are_not_draws_and_all_scheduled_cells_are_denominator(self):
        schedule = [{"cell_id": f"c{i}", "opponent": "greedy", "controlled_side": 0,
                     "faction": "undead"} for i in range(10)]
        results = ([{"cell_id": f"c{i}", "status": "completed", "outcome": "win",
                     "engine_result": {"termination_reason": "winner"}} for i in range(8)] +
                   [{"cell_id": "c8", "status": "completed", "outcome": "loss",
                     "engine_result": {"termination_reason": "winner"}},
                    {"cell_id": "c9", "status": "completed", "outcome": "cap",
                     "engine_result": {"termination_reason": "side_turn_cap"}}])
        report = strength.aggregate_results(schedule, results, suite="smoke")
        overall = report["overall"]
        self.assertEqual(overall["wins"], 8)
        self.assertEqual(overall["losses"], 1)
        self.assertEqual(overall["caps"], 1)
        self.assertEqual(overall["genuine_draws"], 0)
        self.assertEqual(overall["win_rate_all_scheduled"], 0.8)
        self.assertEqual(report["verdicts"]["strength"], "not_measured")

    def test_incomplete_rows_do_not_look_strong(self):
        schedule = strength.build_schedule(suite="smoke")
        report = strength.aggregate_results(schedule, [
            {"cell_id": schedule[0]["cell_id"], "status": "completed", "outcome": "win"}])
        self.assertEqual(report["overall"]["unrun"], 3)
        self.assertEqual(report["overall"]["win_rate_all_scheduled"], 0.25)
        self.assertEqual(report["status"], "incomplete")

    def test_complete_losses_are_operationally_complete_but_fail_strength(self):
        schedule = strength.build_schedule(suite="development")
        results = [{"cell_id": cell["cell_id"], "status": "completed", "outcome": "loss",
                    "engine_result": {"termination_reason": "winner"}} for cell in schedule]
        report = strength.aggregate_results(schedule, results, suite="development")
        self.assertEqual(report["status"], "complete")
        self.assertEqual(report["overall"]["operational_failures"], 0)
        self.assertEqual(report["verdicts"]["strength"], "failed")

    def _write_complete_screen(self, out_dir: Path, binary: Path):
        schedule = strength.build_schedule(suite="screen", base_seed=7123)
        manifest = {"schema_version": strength.SCHEMA_VERSION, "suite": "screen", "status": "frozen",
                    "source": {"commit": "commit", "tree": "tree"}, "binary": str(binary),
                    "binary_sha256": strength.sha256_file(binary), "data_sha256": "data",
                    "timeout_seconds": 180.0, "workers": 1,
                    "schedule": schedule,
                    "schedule_sha256": hashlib.sha256(strength._canonical_bytes(schedule)).hexdigest(),
                    "settings": {"base_seed": 7123, "gold": 300, "max_side_turns": 200,
                                 "second_gold": 0, "threads": 1, "controlled_algorithm": "coordinated"}}
        (out_dir / "manifest.json").write_text(json.dumps(manifest))
        results = []
        events = []
        for index, cell in enumerate(schedule):
            algorithms = strength._expected_algorithms(cell)
            winner = cell["controlled_side"]
            engine = {"type": "self_play_result", "raw_seed": cell["seed"],
                      "effective_seed": strength._mix_seed(cell["seed"]), "winner_side": winner,
                      "termination_reason": "winner", "completed_side_turns": 17,
                      "side_turn_cap": 200, "scenario": "big_battle_6",
                      "factions": [cell["faction"], cell["faction"]], "algorithms": algorithms,
                      "recruitment_policies": ["first-affordable", "first-affordable"],
                      "first_side": 0 if cell["first"] == "team1" else 1, "second_gold": 0,
                      "starting_gold": [cell["gold"], cell["gold"]]}
            trace_dir = out_dir / "evidence" / cell["cell_id"] / "attempt-001"
            trace_dir.mkdir(parents=True)
            trace = [{"type": "metadata", "algorithms": algorithms,
                      "input_seed": cell["seed"], "effective_seed": strength._mix_seed(cell["seed"]),
                      "scenario": "big_battle_6", "factions": [cell["faction"], cell["faction"]],
                      "first": 0 if cell["first"] == "team1" else 1,
                      "starting_gold": [cell["gold"], cell["gold"]], "side_turn_cap": 200,
                      "recruitment_policies": ["first-affordable", "first-affordable"]},
                     {"type": "terminal", "reason": "winner", "winner": winner,
                      "side_turns_executed": 17}]
            (trace_dir / "game-00001.ndjson").write_text("\n".join(map(json.dumps, trace)) + "\n")
            logdir = out_dir / "logs" / cell["cell_id"]
            logdir.mkdir(parents=True)
            (logdir / "out").write_text(json.dumps(engine) + "\n")
            (logdir / "err").write_text("")
            results.append({**cell, "status": "completed", "outcome": "win", "engine_result": engine,
                            "attempt": 1,
                            "command": strength.command_for(cell, binary,
                                out_dir / "evidence" / cell["cell_id"] / "attempt-001"),
                            "stdout": str((logdir / "out").relative_to(out_dir)),
                            "stderr": str((logdir / "err").relative_to(out_dir)),
                            "trace": str((trace_dir / "game-00001.ndjson").relative_to(out_dir))})
            events.extend([{"event": "start", "cell_id": cell["cell_id"], "attempt": 1},
                           {"event": "exit", "cell_id": cell["cell_id"], "attempt": 1}])
        (out_dir / "results.json").write_text(json.dumps({"results": results}))
        (out_dir / "attempts.jsonl").write_text("\n".join(map(json.dumps, events)) + "\n")
        return manifest, results

    def test_check_validates_evidence_and_screen_cannot_certify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out_dir = root / "run"; out_dir.mkdir()
            binary = root / "self-play"; binary.write_bytes(b"binary")
            self._write_complete_screen(out_dir, binary)
            with patch.object(strength, "source_identity", return_value={"commit": "commit", "tree": "tree"}), \
                    patch.object(strength, "data_sha256", return_value="data"):
                code, report = strength.check_evidence(out_dir)
            self.assertEqual(code, 0)
            self.assertEqual(report["verdicts"]["strength"], "measured_not_certifying")
            self.assertFalse(report["strength_gate"]["promotion_allowed"])

    def test_check_rejects_tampered_treatment_and_duplicate_cell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out_dir = root / "run"; out_dir.mkdir()
            binary = root / "self-play"; binary.write_bytes(b"binary")
            _, results = self._write_complete_screen(out_dir, binary)
            with patch.object(strength, "source_identity", return_value={"commit": "commit", "tree": "tree"}), \
                    patch.object(strength, "data_sha256", return_value="data"):
                results[0]["engine_result"]["algorithms"][0] = "greedy-look-ahead"
                (out_dir / "results.json").write_text(json.dumps({"results": results}))
                code, report = strength.check_evidence(out_dir)
            self.assertEqual(code, 2)
            self.assertTrue(any("algorithms mismatch" in error for error in report["invalid_records"]))
            results[0]["engine_result"]["algorithms"][0] = "coordinated"
            results.append(results[0])
            (out_dir / "results.json").write_text(json.dumps({"results": results}))
            with patch.object(strength, "source_identity", return_value={"commit": "commit", "tree": "tree"}), \
                    patch.object(strength, "data_sha256", return_value="data"):
                code, report = strength.check_evidence(out_dir)
            self.assertEqual(code, 2)
            self.assertTrue(any("duplicate cell" in error for error in report["invalid_records"]))

    def test_check_rejects_wrong_faction_gold_seed_and_missing_reason(self):
        for key, value in (("factions", ["undead", "undead"]),
                           ("starting_gold", [999, 999]), ("raw_seed", 999),
                           ("termination_reason", None)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); out_dir = root / "run"; out_dir.mkdir()
                binary = root / "self-play"; binary.write_bytes(b"binary")
                _, results = self._write_complete_screen(out_dir, binary)
                results[0]["engine_result"][key] = value
                (out_dir / "results.json").write_text(json.dumps({"results": results}))
                with patch.object(strength, "source_identity", return_value={"commit": "commit", "tree": "tree"}), \
                        patch.object(strength, "data_sha256", return_value="data"):
                    code, report = strength.check_evidence(out_dir)
                self.assertEqual(code, 2)
                self.assertTrue(report["invalid_records"])


if __name__ == "__main__":
    unittest.main()
