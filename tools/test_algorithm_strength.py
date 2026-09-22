"""Tests for the bounded built-in algorithm strength harness."""
from __future__ import annotations

import unittest
from pathlib import Path

from .algorithm_strength import aggregate_results, build_schedule, command_for, _result_line


class AlgorithmStrengthTests(unittest.TestCase):
    def test_screening_schedule_is_four_mirrors_two_opponents(self):
        schedule = build_schedule()
        self.assertEqual(len(schedule), 32)
        self.assertEqual({row["faction"] for row in schedule}, {
            "loyalists", "rebels", "northerners", "undead"
        })
        self.assertEqual({row["opponent"] for row in schedule}, {"greedy", "coordinated"})
        self.assertEqual({row["controlled_side"] for row in schedule}, {0, 1})
        self.assertEqual({row["first"] for row in schedule}, {"team1", "team2"})
        self.assertEqual(len({row["cell_id"] for row in schedule}), 32)

    def test_command_keeps_recruitment_and_clock_fixed(self):
        cell = build_schedule(opponents=("greedy",), factions=("undead",))[0]
        command = command_for(cell, Path("self-play"))
        self.assertIn("--max-side-turns", command)
        self.assertIn("200", command)
        self.assertEqual(command[-1], "--json")
        self.assertEqual(command[command.index("--recruit1-policy") + 1], "first-affordable")
        self.assertEqual(command[command.index("--recruit2-policy") + 1], "first-affordable")
        self.assertEqual(command[command.index("--ai1") + 1], "greedy-look-ahead")
        self.assertEqual(command[command.index("--ai2") + 1], "greedy")

    def test_parser_requires_exactly_one_engine_result(self):
        result = '{"type":"self_play_result","winner_side":0}'
        self.assertEqual(_result_line(result)["winner_side"], 0)
        self.assertIsNone(_result_line(result + "\n" + result))
        self.assertIsNone(_result_line("process failed"))

    def test_failed_and_unrun_cells_are_not_wins(self):
        schedule = build_schedule(opponents=("greedy",), factions=("undead",))
        results = [
            {"cell_id": schedule[0]["cell_id"], "status": "completed", "outcome": "win",
             "engine_result": {"termination_reason": "winner"}},
            {"cell_id": schedule[1]["cell_id"], "status": "failed", "outcome": None},
        ]
        report = aggregate_results(schedule, results)
        summary = report["summary"]["greedy"]
        self.assertEqual(summary["scheduled"], 4)
        self.assertEqual(summary["completed"], 1)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["operational_failures"], 3)
        self.assertEqual(summary["conditional_win_rate"], 1.0)
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["strength_claim_allowed"])
        self.assertEqual(len(report["strata"]), 4)

    def test_cap_is_explicit_metric(self):
        schedule = build_schedule(opponents=("greedy",), factions=("undead",))
        results = [
            {"cell_id": row["cell_id"], "status": "completed", "outcome": "draw",
             "engine_result": {"termination_reason": "side_turn_cap"}}
            for row in schedule
        ]
        report = aggregate_results(schedule, results)
        self.assertEqual(report["summary"]["greedy"]["cap_count"], 4)
        self.assertEqual(report["summary"]["greedy"]["cap_rate"], 1.0)
        self.assertEqual(report["summary"]["greedy"]["draws"], 4)


if __name__ == "__main__":
    unittest.main()
