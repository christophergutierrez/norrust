"""Unit tests for tools.bakeoff_metrics (Stack 4)."""
from __future__ import annotations

import unittest
from . import bakeoff_metrics as bm


class BakeoffMetricsPricingTests(unittest.TestCase):

    def test_compute_call_cost_known_rates(self):
        usage = {
            "input_tokens": 1000,
            "cached_input_tokens": 400,
            "output_tokens": 200,
            "reasoning_tokens": 50,
        }
        # custom spec: input $2/M, cached $1/M, output $10/M, reasoning included in output
        custom = {
            "input_per_million": 2.0,
            "cached_input_per_million": 1.0,
            "output_per_million": 10.0,
            "reasoning_included_in_output": True,
        }
        cost = bm.compute_call_cost(usage, custom_prices=custom)
        # 600 uncached * 2 = 1200
        # 400 cached * 1 = 400
        # 200 output * 10 = 2000
        # total = (1200 + 400 + 2000) / 1,000,000 = 0.0036
        self.assertAlmostEqual(cost, 0.0036, places=6)

    def test_compute_call_cost_reasoning_separate(self):
        usage = {
            "input_tokens": 1000,
            "cached_input_tokens": 0,
            "output_tokens": 200,
            "reasoning_tokens": 100,
        }
        custom = {
            "input_per_million": 1.0,
            "cached_input_per_million": 0.5,
            "output_per_million": 10.0,
            "reasoning_included_in_output": False,
            "reasoning_per_million": 5.0,
        }
        cost = bm.compute_call_cost(usage, custom_prices=custom)
        # 1000 * 1 = 1000
        # 200 * 10 = 2000
        # 100 * 5 = 500
        # total = 3500 / 1,000,000 = 0.0035
        self.assertAlmostEqual(cost, 0.0035, places=6)

    def test_compute_call_cost_missing_or_invalid_returns_none(self):
        self.assertIsNone(bm.compute_call_cost(None))
        self.assertIsNone(bm.compute_call_cost({}))
        self.assertIsNone(bm.compute_call_cost({"input_tokens": -5, "output_tokens": 10}))
        self.assertIsNone(bm.compute_call_cost({"input_tokens": "abc", "output_tokens": 10}))

    def test_unknown_model_has_unknown_cost(self):
        usage = {"input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20}
        self.assertIsNone(bm.compute_call_cost(usage, model="fixture-model"))

    def test_missing_reasoning_is_unknown_in_aggregate(self):
        calls = [{"call_id": "c1", "input_tokens": 100,
                  "cached_input_tokens": 0, "output_tokens": 20,
                  "total_tokens": 120},
                 {"call_id": "c2", "input_tokens": 100,
                  "cached_input_tokens": 0, "output_tokens": 20,
                  "total_tokens": 120, "reasoning_tokens": 4}]
        result = bm.aggregate_usage(calls, model="gpt-4o")
        self.assertIsNone(result["reasoning_tokens"])
        self.assertEqual(result["field_coverage"]["reasoning_tokens"]["unknown_calls"], 1)

    def test_repeated_lifecycle_row_is_one_physical_call(self):
        calls = [{"game_id": "g", "call_id": "provider-1", "status": "dispatched",
                  "input_tokens": 100, "cached_input_tokens": 0, "output_tokens": None,
                  "total_tokens": None},
                 {"game_id": "g", "call_id": "provider-1", "status": "completed",
                  "input_tokens": 100, "cached_input_tokens": 0, "output_tokens": 20,
                  "total_tokens": 120}]
        result = bm.aggregate_usage(calls, model="gpt-4o")
        self.assertEqual(result["physical_calls"], 1)
        self.assertEqual(result["total_tokens"], 120)

    def test_aggregate_usage_synthetic_calls(self):
        calls = [
            {"call_id": "c1", "status": "completed", "elapsed_ms": 500,
             "usage": {"input_tokens": 1000, "cached_input_tokens": 200, "output_tokens": 100, "total_tokens": 1100}},
            {"call_id": "c2", "status": "completed", "elapsed_ms": 300,
             "usage": {"input_tokens": 500, "cached_input_tokens": 100, "output_tokens": 50, "total_tokens": 550}},
            {"call_id": "c3", "status": "failed", "elapsed_ms": 100, "error": "rate_limit", "usage": None},
        ]
        agg = bm.aggregate_usage(calls, custom_prices={"input_per_million":2,"cached_input_per_million":1,"output_per_million":10,"reasoning_included_in_output":True})
        self.assertEqual(agg["physical_calls"], 3)
        self.assertEqual(agg["failed_calls"], 1)
        self.assertEqual(agg["measured_calls"], 2)
        self.assertEqual(agg["input_tokens"], 1500)
        self.assertEqual(agg["cached_input_tokens"], 300)
        self.assertEqual(agg["output_tokens"], 150)
        self.assertEqual(agg["total_tokens"], 1650)
        self.assertEqual(agg["elapsed_ms"], 900)
        self.assertIsNotNone(agg["known_cost"])
        self.assertEqual(agg["cost_coverage"], "partial")


class UsefulActionEvaluationTests(unittest.TestCase):

    def test_named_deployment_requires_the_committed_destination(self):
        records = [
            {'type': 'forwarded_orders', 'request_id': 'r1', 'orders': [
                {'action': 'Move', 'unit_id': 3, 'col': 2, 'row': 5}]},
            {'type': 'driver', 'line': {'type': 'events', 'source': 'llm', 'events': [
                {'kind': 'move', 'unit': 3, 'to': {'col': 2, 'row': 5}}]}}]
        self.assertTrue(bm.evaluate_trial_actions(records, useful_spec={
            'kind': 'move', 'unit_id': 3, 'col': 2, 'row': 5})['useful_action_achieved'])
        self.assertFalse(bm.evaluate_trial_actions(records, useful_spec={
            'kind': 'move', 'unit_id': 3, 'col': 3, 'row': 5})['useful_action_achieved'])

    def test_forwarded_proposal_without_engine_event_is_not_committed(self):
        records = [{"type": "model_request", "request_id": "r1",
                    "usage": {"total_tokens": 10}},
                   {"type": "forwarded_orders", "request_id": "r1",
                    "batch_id": "b1", "orders": [{"action": "Move", "unit_id": 4}]}]
        result = bm.evaluate_trial_actions(records, useful_spec={"kind": "move"})
        self.assertIsNone(result["first_legal_action"])
        self.assertIsNone(result["first_useful_action"])
        self.assertFalse(result["useful_action_achieved"])

    def test_first_useful_tokens_use_physical_calls_and_unknowns(self):
        records = [
            {"type": "model_request", "request_id": "r0", "sequence": 1},
            {"type": "model_request", "request_id": "r1", "sequence": 2},
            {"type": "forwarded_orders", "request_id": "r1", "batch_id": "b1",
             "orders": [{"action": "Move", "unit_id": 4}]},
            {"type": "driver", "line": {"type": "events", "source": "llm",
             "events": [{"kind": "move", "unit": 4}]}},
        ]
        physical = [{"call_id": "retry", "request_id": "r0", "total_tokens": 40,
                     "elapsed_ms": 5},
                    {"call_id": "final", "request_id": "r1", "total_tokens": 60,
                     "elapsed_ms": 7}]
        result = bm.evaluate_trial_actions(records, useful_spec={"kind": "move"},
                                           physical_calls=physical)
        self.assertEqual(result["tokens_to_first_useful"], 100)
        self.assertIsNone(result["ms_to_first_useful"])  # No observed commit timestamp.
        with_unassigned = bm.evaluate_trial_actions(
            records, useful_spec={"kind": "move"}, physical_calls=physical + [
                {"call_id": "host-unassigned", "total_tokens": 50}])
        self.assertIsNone(with_unassigned["tokens_to_first_useful"])
        physical[0].pop("total_tokens")
        result = bm.evaluate_trial_actions(records, useful_spec={"kind": "move"},
                                           physical_calls=physical)
        self.assertIsNone(result["tokens_to_first_useful"])

    def test_first_legal_and_useful_action_detection(self):
        records = [
            {"type": "model_request", "request_id": "req-1", "elapsed_ms": 400,
             "usage": {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}},
            {"type": "forwarded_orders", "request_id": "req-1",
             "batch_id": "b1", "orders": [{"action": "Recruit", "def_id": "Skeleton Archer", "col": 2, "row": 6}]},
            {"type": "driver", "line": {"type": "events", "source": "llm",
             "events": [{"kind": "recruit", "unit": 51, "source": "llm", "def_id":"Skeleton Archer", "col":2, "row":6}]}},
            {"type": "model_request", "request_id": "req-2", "elapsed_ms": 300,
             "usage": {"input_tokens": 150, "output_tokens": 25, "total_tokens": 175}},
            {"type": "forwarded_orders", "request_id": "req-2",
             "batch_id": "b2", "orders": [{"action": "Move", "unit_id": 47, "col": 3, "row": 5}, {"action": "EndTurn"}]},
            {"type": "driver", "line": {"type": "events", "source": "llm",
             "events": [{"kind": "move", "unit": 47, "source": "llm", "to":{"col":3,"row":5}}]}},
        ]
        # Predicate: Moving unit 47
        pred = lambda order: order.get("action") == "Move" and order.get("unit_id") == 47
        result = bm.evaluate_trial_actions(records, useful_predicate=pred, physical_calls=[
            {"call_id":"c1","request_id":"req-1","total_tokens":120,"elapsed_ms":400},
            {"call_id":"c2","request_id":"req-2","total_tokens":175,"elapsed_ms":300}])

        # First legal action was Recruit in req-1
        self.assertEqual(result["first_legal_action"]["action"], "Recruit")
        self.assertEqual(result["tokens_to_first_legal"], 120)
        self.assertIsNone(result["ms_to_first_legal"])

        # First useful action was Move U47 in req-2
        self.assertEqual(result["first_useful_action"]["action"], "Move")
        self.assertEqual(result["tokens_to_first_useful"], 295)  # 120 + 175
        self.assertIsNone(result["ms_to_first_useful"])     # 400 + 300
        self.assertTrue(result["useful_action_achieved"])

    def test_end_turn_sweep_alone_never_useful(self):
        records = [
            {"type": "model_request", "request_id": "req-1", "elapsed_ms": 200,
             "usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}},
            {"type": "forwarded_orders", "request_id": "req-1",
             "batch_id": "b1", "orders": [{"action": "EndTurn"}]},
        ]
        pred = lambda order: order.get("action") == "Attack"
        result = bm.evaluate_trial_actions(records, useful_predicate=pred)
        self.assertIsNone(result["first_legal_action"])
        self.assertIsNone(result["first_useful_action"])
        self.assertFalse(result["useful_action_achieved"])


class ArmComparisonTests(unittest.TestCase):

    def test_compare_arms_pilot_thresholds(self):
        cells = []
        # Arm A: 8 trials, 4 successes, median tokens 400, median cost 0.01
        for i in range(8):
            cells.append({
                "arm": "A",
                "status": "ok",
                "terminal_class": "gameplay",
                "task_success": i < 4,
                "tokens_to_first_useful": 400,
                "known_cost": 0.01, "cost_coverage": "complete",
            })
        # Arm B: 8 trials, 6 successes (>= 6 and >= A + 2), median tokens 300, median cost 0.012
        for i in range(8):
            cells.append({
                "arm": "B",
                "status": "ok",
                "terminal_class": "gameplay",
                "task_success": i < 6,
                "tokens_to_first_useful": 300,
                "known_cost": 0.012, "cost_coverage": "complete",
            })
        # Arm C: 8 trials, 7 successes (>= B), median tokens 200 (<= 0.75 * B), median cost 0.012 (<= 1.10 * B)
        for i in range(8):
            cells.append({
                "arm": "C",
                "status": "ok",
                "terminal_class": "gameplay",
                "task_success": i < 7,
                "tokens_to_first_useful": 200,
                "known_cost": 0.012, "cost_coverage": "complete",
            })

        comparison = bm.compare_arms(cells)
        self.assertTrue(comparison["b_promising_over_a"])
        self.assertTrue(comparison["c_promotes_over_b"])


class EvidenceBoundaryTests(unittest.TestCase):
    def test_submissions_and_infrastructure_failures_are_not_committed_actions(self):
        records = [
            {'type': 'forwarded_orders', 'orders': [{'action': 'Move'}, {'action': 'EndTurn'}]},
            {'type': 'driver', 'line': {'type': 'events', 'source': 'greedy',
                                      'events': [{'kind': 'move'}]}},
            {'type': 'model_error', 'terminal_class': 'infrastructure'},
            {'type': 'batch_validation', 'valid': False},
        ]
        telemetry = bm.extract_telemetry(records)
        self.assertEqual(telemetry['submitted_orders_count'], 2)
        self.assertEqual(telemetry['model_actions_count'], 0)
        self.assertEqual(telemetry['driver_actions_count'], 1)
        self.assertEqual(telemetry['selection_validation_failures'], 1)

    def test_infrastructure_failures_cannot_qualify_action_encoding_promotion(self):
        cells = [{'arm': arm, 'status': 'failed' if arm == 'B' and i > 5 else 'ok',
                  'terminal_class': 'infrastructure' if arm == 'B' and i > 5 else 'gameplay',
                  'task_success': i < 6, 'tokens_to_first_useful': 200,
                  'known_cost': .01, 'cost_coverage': 'complete',
                  'telemetry': {'selection_validation_failures': 0}}
                 for arm in 'ABC' for i in range(8)]
        self.assertFalse(bm.compare_arms(cells)['c_promotes_over_b'])

    def test_request_aggregates_are_not_physical_token_evidence(self):
        records = [
            {'type':'model_request','request_id':'r','usage':{'total_tokens':900}},
            {'type':'model_output_limit','request_id':'r','usage':{'total_tokens':300}},
            {'type':'forwarded_orders','request_id':'r','orders':[{'action':'Move','unit_id':4}]},
            {'type':'driver','line':{'type':'events','source':'llm','events':[{'kind':'move','unit':4}]}},
        ]
        result=bm.evaluate_trial_actions(records,useful_spec={'kind':'move'})
        self.assertTrue(result['useful_action_achieved'])
        self.assertIsNone(result['tokens_to_first_useful'])

    def test_missing_earlier_request_makes_first_action_tokens_unknown(self):
        records = [
            {'type': 'model_request', 'request_id': 'r0', 'sequence': 1},
            {'type': 'model_request', 'request_id': 'r1', 'sequence': 2},
            {'type': 'forwarded_orders', 'request_id': 'r1', 'orders': [
                {'action': 'Move', 'unit_id': 4}]},
            {'type': 'driver', 'line': {'type': 'events', 'source': 'llm',
                                        'events': [{'kind': 'move', 'unit': 4}]}}]
        result = bm.evaluate_trial_actions(
            records, useful_spec={'kind': 'move'},
            physical_calls=[{'call_id': 'c1', 'request_id': 'r1', 'total_tokens': 60}])
        self.assertTrue(result['useful_action_achieved'])
        self.assertIsNone(result['tokens_to_first_useful'])

    def test_physical_rows_are_ordered_by_audit_requests_and_retries_sum(self):
        records = [
            {'type': 'model_request', 'request_id': 'r1', 'sequence': 1},
            {'type': 'forwarded_orders', 'request_id': 'r1', 'orders': [
                {'action': 'Move', 'unit_id': 4}]},
            {'type': 'driver', 'line': {'type': 'events', 'source': 'llm',
                                        'events': [{'kind': 'move', 'unit': 4}]}},
            {'type': 'model_request', 'request_id': 'r2', 'sequence': 2}]
        # The later request was inserted first in the catalog, while r1 had
        # two physical attempts. Chronology comes from the audit request order.
        result = bm.evaluate_trial_actions(
            records, useful_spec={'kind': 'move'},
            physical_calls=[
                {'call_id': 'r2-call', 'request_id': 'r2', 'total_tokens': 500},
                {'call_id': 'r1-retry', 'request_id': 'r1', 'total_tokens': 20},
                {'call_id': 'r1-first', 'request_id': 'r1', 'total_tokens': None,
                 'status': 'dispatched'},
                {'call_id': 'r1-first', 'request_id': 'r1', 'total_tokens': 10},
            ])
        self.assertEqual(result['tokens_to_first_useful'], 30)

    def test_canonical_call_with_conflicting_request_links_is_unknown(self):
        records = [
            {'type': 'model_request', 'request_id': 'r1', 'sequence': 1},
            {'type': 'forwarded_orders', 'request_id': 'r1', 'orders': [
                {'action': 'Move', 'unit_id': 4}]},
            {'type': 'driver', 'line': {'type': 'events', 'source': 'llm',
                                        'events': [{'kind': 'move', 'unit': 4}]}},
            {'type': 'model_request', 'request_id': 'r2', 'sequence': 2}]
        result = bm.evaluate_trial_actions(
            records, useful_spec={'kind': 'move'},
            physical_calls=[
                {'game_id': 'g', 'call_id': 'same-call', 'request_id': 'r1',
                 'total_tokens': 10},
                {'game_id': 'g', 'call_id': 'same-call', 'request_id': 'r2',
                 'total_tokens': 10},
            ])
        self.assertTrue(result['useful_action_achieved'])
        self.assertIsNone(result['tokens_to_first_useful'])

    def test_other_attacker_event_cannot_prove_authored_attack(self):
        records=[{'type':'forwarded_orders','request_id':'r','orders':[
            {'action':'Attack','attacker_id':1,'defender_id':2}]},
            {'type':'driver','line':{'type':'events','source':'llm','events':[
                {'kind':'attack','attacker':{'unit':3},'defender':{'unit':2}}]}}]
        self.assertIsNone(bm.evaluate_trial_actions(records,useful_spec={'kind':'attack'})['first_useful_action'])

    def test_missing_discount_split_or_reasoning_cost_is_unknown(self):
        rates={'input_per_million':2,'cached_input_per_million':1,'output_per_million':10,
               'reasoning_included_in_output':True}
        self.assertIsNone(bm.compute_call_cost({'input_tokens':100,'output_tokens':20},custom_prices=rates))
        rates['reasoning_included_in_output']=False
        rates['reasoning_per_million']=10
        self.assertIsNone(bm.compute_call_cost({'input_tokens':100,'cached_input_tokens':0,'output_tokens':20},custom_prices=rates))

    def test_partial_cost_cannot_pass_promotion_gate(self):
        cells=[{'arm':arm,'status':'ok','terminal_class':'gameplay','task_success':True,
                'tokens_to_first_useful':100 if arm=='C' else 200,
                'known_cost':0.01,'cost_coverage':'partial'} for arm in 'ABC' for _ in range(8)]
        self.assertFalse(bm.compare_arms(cells)['c_promotes_over_b'])


if __name__ == "__main__":
    unittest.main()
