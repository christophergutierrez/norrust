import json
import tempfile
import unittest
from pathlib import Path

from .model_usage import ModelCall
from .usage_cost import role_cost_report


class UsageCostTests(unittest.TestCase):
    def test_rates_are_selected_per_model_and_effective_date_by_role(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rates.json"
            path.write_text(json.dumps({"rates": [
                {"model": "player-model", "effective_date": "2025-01-01",
                 "input_per_million": 1, "cached_input_per_million": .5,
                 "output_per_million": 2, "reasoning_included_in_output": True},
                {"model": "observer-model", "effective_date": "2025-01-01",
                 "input_per_million": 3, "cached_input_per_million": 1,
                 "output_per_million": 4, "reasoning_included_in_output": True},
                {"model": "observer-model", "effective_date": "2026-01-01",
                 "input_per_million": 6, "cached_input_per_million": 2,
                 "output_per_million": 8, "reasoning_included_in_output": True},
            ]}))
            calls = [
                ModelCall(game_id="g", call_id="p", call_role="player",
                          requested_model="player-model", started_at="2025-05-01",
                          input_tokens=100, cached_input_tokens=20, output_tokens=10),
                ModelCall(game_id="g", call_id="o", call_role="observer",
                          requested_model="observer-model", started_at="2025-05-01",
                          input_tokens=100, cached_input_tokens=20, output_tokens=10),
                ModelCall(game_id="g", call_id="o2", call_role="observer",
                          requested_model="observer-model", started_at="2026-05-01",
                          input_tokens=100, cached_input_tokens=20, output_tokens=10),
                ModelCall(game_id="g", call_id="legacy", requested_model="missing",
                          input_tokens=100, output_tokens=10),
            ]
            report = role_cost_report(calls, path)
            self.assertEqual(report["player"]["cost_usd"], .00011)
            self.assertEqual(report["observer"]["cost_usd"], .0009)
            self.assertIsNone(report["unknown"]["cost_usd"])
            self.assertAlmostEqual(report["combined"]["cost_usd"], .00101)
            self.assertEqual(len(report["rates_used"]), 3)

    def test_separately_priced_reasoning_requires_measured_reasoning_tokens(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rates.json"
            path.write_text(json.dumps({"rates": [{
                "model": "m", "effective_date": "2025-01-01",
                "input_per_million": 1, "cached_input_per_million": 1,
                "output_per_million": 2, "reasoning_included_in_output": False,
                "reasoning_per_million": 3,
            }]}))
            missing = ModelCall(game_id="g", call_id="a", requested_model="m",
                                input_tokens=1, output_tokens=1)
            measured = ModelCall(game_id="g", call_id="b", requested_model="m",
                                 started_at="2025-01-01", input_tokens=1,
                                 output_tokens=1, reasoning_tokens=1)
            report = role_cost_report([missing, measured], path)
            self.assertEqual(report["combined"]["known_calls"], 1)
            self.assertEqual(report["combined"]["unknown_calls"], 1)

    def test_unparseable_date_does_not_use_latest_rate(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rates.json"
            path.write_text(json.dumps({"rates": [{
                "model": "m", "effective_date": "2025-01-01",
                "input_per_million": 1, "cached_input_per_million": 1,
                "output_per_million": 2, "reasoning_included_in_output": True,
            }]}))
            call = ModelCall(game_id="g", call_id="a", requested_model="m",
                             started_at="unknown", input_tokens=1, output_tokens=1)
            self.assertIsNone(role_cost_report([call], path)["combined"]["cost_usd"])


if __name__ == "__main__":
    unittest.main()
