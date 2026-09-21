"""Tests for tools.bounded_evaluation.

Uses a small in-process mock driver (`MockDriver`) that answers the exact
query shapes `bounded_evaluation` sends -- `preview_batch` in
`mode="bounded_rollout"`, `turn_options`, `recruit_options` -- so these tests
never launch the real driver and run fast. See the module docstring in
`tools/bounded_evaluation.py` for the QueryFn contract this mock implements.
"""
from __future__ import annotations

import json
import unittest
from typing import Any, Callable, Mapping

from tools import bounded_evaluation as be


def _key(orders):
  return tuple(json.dumps(o, sort_keys=True, separators=(",", ":")) for o in orders)


def _make_rollout(*, seed: int, friendly_hp: int, enemy_hp: int, winner=None,
                   friendly_material: int = 10, enemy_material: int = 10,
                   friendly_villages: int = 0, enemy_villages: int = 0,
                   friendly_gold: int = 0, own_event_count: int = 1,
                   opponent_responded: bool = True,
                   opponent_responses: int | None = None) -> dict[str, Any]:
  friendly_side = {
    "side": 0, "units": 1, "hp": friendly_hp, "max_hp": 20,
    "material_cost": friendly_material, "recruiters": 1,
    "villages": friendly_villages, "gold": friendly_gold,
  }
  enemy_side = {
    "side": 1, "units": 1, "hp": enemy_hp, "max_hp": 20,
    "material_cost": enemy_material, "recruiters": 0,
    "villages": enemy_villages, "gold": 0,
  }
  units_detail = [{
    "unit_id": 1, "side": 0, "def_id": "recruiter", "hp": friendly_hp, "max_hp": 20,
    "cost": 10, "position": {"col": 0, "row": 0}, "recruiter": True,
    "advancement_pending": False,
  }]
  stage = {
    "active_faction": 1, "turn": 1, "state_revision": 42,
    "sides": [friendly_side, enemy_side], "units_detail": units_detail,
    "villages": [], "winner": winner,
  }
  stages = {"post_finish": stage}
  if opponent_responses and opponent_responses > 1:
    stages.update({f"post_opponent_{i}": stage for i in range(1, opponent_responses + 1)})
  else:
    stages["post_opponent"] = stage if opponent_responded else None
  result = {
    "evaluation_seed": seed, "policy": "driver_greedy_one_response_v2", "sample_count": 1,
    "stages": stages,
    "own_event_count": own_event_count, "opponent_event_count": 1 if opponent_responded else 0,
    "opponent_error": None,
    "coverage": {"own_finish": True, "opponent_response": opponent_responded},
  }
  if opponent_responses is not None:
    result["opponent_responses"] = opponent_responses
  return result


class MockDriver:
  """A minimal stand-in for a restored driver process. Legality and
  per-seed outcomes are declared explicitly per test, never inferred."""

  def __init__(self) -> None:
    self.calls: list[Mapping[str, Any]] = []
    self._legal: dict[tuple, Callable[[int], dict[str, Any]]] = {}
    self._illegal: dict[tuple, str] = {}
    self._per_seed: dict[tuple, dict[int, str]] = {}
    self.turn_options_body: dict[str, Any] = {"units": []}
    self.recruit_options_body: dict[str, Any] = {"placement_hexes": [], "options": []}

  def add_legal(self, orders, outcome_fn: Callable[[int], dict[str, Any]]) -> None:
    self._legal[_key(orders)] = outcome_fn

  def add_illegal(self, orders, message: str = "not a legal action") -> None:
    self._illegal[_key(orders)] = message

  def censor_seed(self, orders, seed: int, reason: str = "query_timeout") -> None:
    self._per_seed.setdefault(_key(orders), {})[seed] = reason

  def __call__(self, query: Mapping[str, Any]) -> Mapping[str, Any]:
    self.calls.append(query)
    what = query.get("what")
    if what == "turn_options":
      return {"ok": True, "body": self.turn_options_body}
    if what == "recruit_options":
      return {"ok": True, "body": self.recruit_options_body}
    if what != "preview_batch":
      return {"ok": False, "code": "unknown_query"}

    orders = query["candidates"][0]
    key = _key(orders)
    seed = query["evaluation_seed"]

    per_seed_reason = self._per_seed.get(key, {}).get(seed)
    if per_seed_reason == "query_timeout":
      return {"ok": False, "code": "query_timeout", "message": "query budget exceeded"}
    if per_seed_reason == "transport_exception":
      raise TimeoutError("simulated transport timeout")
    if per_seed_reason == "rollout_unavailable":
      return {"ok": True, "body": {"candidates": [{"valid": True, "post_sweep": None}]}}

    if key in self._illegal:
      return {
        "ok": False, "code": "parse", "candidate_index": 0,
        "message": self._illegal[key],
      }
    if key not in self._legal:
      return {"ok": False, "code": "parse", "candidate_index": 0, "message": "undeclared candidate"}

    rollout = self._legal[key](seed)
    return {"ok": True, "body": {"candidates": [{"valid": True, "post_sweep": rollout}]}}


class FakeClock:
  """A deterministic, injectable stand-in for time.monotonic."""

  def __init__(self, start: float = 0.0, step: float = 0.001) -> None:
    self._t = start
    self._step = step

  def __call__(self) -> float:
    self._t += self._step
    return self._t


ACTUAL_CHOICE_ORDERS = [{"action": "Move", "unit_id": 1, "col": 2, "row": 2}]
LEGAL_FINISH = list(be.LEGAL_FINISH_ORDERS)


def _default_config(**overrides) -> be.EvaluationConfig:
  base = dict(seed_schedule=be.default_seed_schedule(4))
  base.update(overrides)
  return be.EvaluationConfig(**base)


class AssembleCandidatesTests(unittest.TestCase):
  def test_four_sources_labelled(self):
    candidates = be.assemble_candidates(
      actual_choice={"orders": ACTUAL_CHOICE_ORDERS},
      shown_alternatives=[{"orders": [{"action": "EndTurn"}], "label": "shown:end_turn"}],
      legal_finish=None,
      reference_candidates=[{"orders": [{"action": "Recruit", "def_id": "x", "col": 1, "row": 1}]}],
    )
    labels = [c.labels for c in candidates]
    self.assertIn((be.LABEL_ACTUAL_CHOICE,), labels)
    self.assertIn((be.LABEL_LEGAL_FINISH,), labels)
    self.assertTrue(any("shown:end_turn" in l for l in labels))
    self.assertTrue(any(be.LABEL_REFERENCE in l for l in labels))


class DedupCandidatesTests(unittest.TestCase):
  def test_merged_candidate_keeps_all_labels(self):
    candidates = be.assemble_candidates(
      actual_choice={"orders": ACTUAL_CHOICE_ORDERS},
      shown_alternatives=[{"orders": ACTUAL_CHOICE_ORDERS, "label": "shown:same_as_actual"}],
    )
    deduped = be.dedup_candidates(candidates)
    matches = [c for c in deduped if c.orders == tuple(ACTUAL_CHOICE_ORDERS)]
    self.assertEqual(len(matches), 1)
    self.assertIn(be.LABEL_ACTUAL_CHOICE, matches[0].labels)
    self.assertIn("shown:same_as_actual", matches[0].labels)

  def test_same_orders_different_phase_not_merged(self):
    candidates = [
      be.Candidate("a", tuple(ACTUAL_CHOICE_ORDERS), "final", (be.LABEL_ACTUAL_CHOICE,), True),
      be.Candidate("b", tuple(ACTUAL_CHOICE_ORDERS), "partial", (be.LABEL_REFERENCE,), False),
    ]
    deduped = be.dedup_candidates(candidates)
    self.assertEqual(len(deduped), 2)


class PruneCandidatesTests(unittest.TestCase):
  def test_reserved_candidates_survive_pruning(self):
    candidates = be.assemble_candidates(
      actual_choice={"orders": ACTUAL_CHOICE_ORDERS},
      shown_alternatives=[
        {"orders": [{"action": "EndTurn"}], "label": f"shown:{i}"} for i in range(10)
      ],
    )
    pruned = be.prune_candidates(candidates, max_candidates=2)
    self.assertEqual(len(pruned), 2)
    all_labels = {label for c in pruned for label in c.labels}
    self.assertIn(be.LABEL_ACTUAL_CHOICE, all_labels)
    self.assertIn(be.LABEL_LEGAL_FINISH, all_labels)


class ReferenceGeneratorTests(unittest.TestCase):
  def test_only_offers_what_driver_enumerates(self):
    driver = MockDriver()
    driver.turn_options_body = {
      "units": [{"unit_id": 5, "positions": [
        {"col": 0, "row": 0, "current": True, "movable": False, "target_ids": [9, 3]},
      ]}],
    }
    driver.recruit_options_body = {
      "placement_hexes": [{"col": 4, "row": 4}],
      "options": [
        {"def_id": "cheap", "cost": 10, "affordable": True},
        {"def_id": "pricey", "cost": 50, "affordable": False},
      ],
    }
    refs = be.generate_reference_candidates(driver, state_revision=42)
    self.assertEqual(len(refs), 2)
    attack = next(r for r in refs if "attack" in r["label"])
    self.assertEqual(attack["orders"], [{"action": "Attack", "attacker_id": 5, "defender_id": 3}])
    recruit = next(r for r in refs if "recruit" in r["label"])
    self.assertEqual(
      recruit["orders"], [{"action": "Recruit", "def_id": "cheap", "col": 4, "row": 4}])

  def test_empty_when_nothing_offered(self):
    driver = MockDriver()
    refs = be.generate_reference_candidates(driver, state_revision=42)
    self.assertEqual(refs, [])


class EvaluateTests(unittest.TestCase):
  def _run(self, driver: MockDriver, **kwargs):
    config = kwargs.pop("config", _default_config())
    clock = FakeClock()
    return be.evaluate(
      driver, state_revision=42, model_side=0, opponent_side=1,
      actual_choice=kwargs.pop("actual_choice", {"orders": ACTUAL_CHOICE_ORDERS}),
      shown_alternatives=kwargs.pop("shown_alternatives", ()),
      legal_finish=kwargs.pop("legal_finish", None),
      reference_candidates=kwargs.pop("reference_candidates", ()),
      config=config, now=clock, **kwargs,
    )

  def test_reproducibility_exact_match(self):
    def make_driver():
      driver = MockDriver()
      driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=5))
      driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
      return driver

    result_a = self._run(make_driver())
    result_b = self._run(make_driver())
    result_a["log"].pop("elapsed_seconds")
    result_b["log"].pop("elapsed_seconds")
    self.assertEqual(result_a, result_b)

  def test_stochastic_fixture_gives_multiple_outcomes(self):
    driver = MockDriver()
    driver.add_legal(
      ACTUAL_CHOICE_ORDERS,
      lambda seed: _make_rollout(seed=seed, friendly_hp=20 if seed % 2 == 0 else 5, enemy_hp=10),
    )
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    result = self._run(driver)
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    hp_values = {s["outcome"]["recruiter_survival"]["hp"][0] for s in actual["samples"]}
    self.assertGreater(len(hp_values), 1)

  def test_deterministic_fixture_stays_deterministic(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=10))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    result = self._run(driver)
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    hp_values = {s["outcome"]["recruiter_survival"]["hp"][0] for s in actual["samples"]}
    self.assertEqual(hp_values, {20})

  def test_illegal_candidate_never_gets_a_rollout(self):
    driver = MockDriver()
    driver.add_illegal(ACTUAL_CHOICE_ORDERS, "unit_id 1 cannot move there")
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    result = self._run(driver)
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    self.assertFalse(actual["legal"])
    self.assertIsNotNone(actual["validation_failure"])
    self.assertEqual(actual["samples"], [])
    self.assertEqual(actual["completed_seeds"], [])

  def test_censored_sample_is_visible_not_zero_not_win(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=10))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    seeds = be.default_seed_schedule(4)
    driver.censor_seed(ACTUAL_CHOICE_ORDERS, seeds[1], reason="query_timeout")
    result = self._run(driver, config=_default_config(seed_schedule=seeds))
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    censored = [s for s in actual["samples"] if s["seed"] == seeds[1]]
    self.assertEqual(len(censored), 1)
    self.assertEqual(censored[0]["status"], "censored")
    self.assertEqual(censored[0]["censor_reason"], "query_timeout")
    self.assertIsNone(censored[0]["outcome"])
    self.assertNotIn(seeds[1], actual["completed_seeds"])
    self.assertIn(seeds[1], actual["censored_seeds"])

  def test_transport_exception_is_censored_not_raised(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=10))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    seeds = be.default_seed_schedule(2)
    driver.censor_seed(ACTUAL_CHOICE_ORDERS, seeds[0], reason="transport_exception")
    result = self._run(driver, config=_default_config(seed_schedule=seeds))
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    first = next(s for s in actual["samples"] if s["seed"] == seeds[0])
    self.assertEqual(first["status"], "censored")
    self.assertEqual(first["censor_reason"], "query_exception")

  def test_matched_seed_subset_used_when_completion_differs(self):
    driver = MockDriver()
    seeds = be.default_seed_schedule(3)
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=5))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=10, enemy_hp=10))
    driver.censor_seed(LEGAL_FINISH, seeds[2], reason="query_timeout")

    def score(outcome):
      return outcome["recruiter_survival"]["hp"][0] - outcome["enemy_material_change"] if outcome else 0

    config = _default_config(seed_schedule=seeds, score_fn=score, score_name="test_score")
    result = self._run(driver, config=config)
    self.assertEqual(sorted(result["matched_seed_subset"]), sorted(seeds[:2]))
    self.assertIsNotNone(result["matched_seed_comparison_note"])
    for candidate in result["scores"].values():
      self.assertEqual(candidate["n"], 2)

  def test_selected_action_and_legal_finish_survive_candidate_pruning(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=5))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    alternatives = [
      {"orders": [{"action": "EndTurn"}, {"action": "Resign"}][:1], "label": f"shown:{i}"}
      for i in range(20)
    ]
    # give each shown alternative distinct-but-irrelevant orders so dedup
    # does not collapse them before pruning is exercised
    alternatives = [
      {"orders": [{"action": "Move", "unit_id": 1, "col": i, "row": 0}], "label": f"shown:{i}"}
      for i in range(20)
    ]
    for alternative in alternatives:
      driver.add_legal(alternative["orders"], lambda seed: _make_rollout(seed=seed, friendly_hp=1, enemy_hp=1))

    config = _default_config(max_candidates=2)
    result = self._run(driver, shown_alternatives=alternatives, config=config)
    self.assertEqual(len(result["candidates"]), 2)
    all_labels = {label for c in result["candidates"] for label in c["labels"]}
    self.assertIn(be.LABEL_ACTUAL_CHOICE, all_labels)
    self.assertIn(be.LABEL_LEGAL_FINISH, all_labels)
    self.assertIn("candidate_budget_pruned", result["log"]["termination_reasons"])

  def test_partial_and_final_compared_at_equal_horizon_with_separate_reporting(self):
    driver = MockDriver()
    partial_orders = [{"action": "Attack", "attacker_id": 1, "defender_id": 2}]
    driver.add_legal(partial_orders, lambda seed: _make_rollout(seed=seed, friendly_hp=15, enemy_hp=5))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    result = self._run(
      driver,
      actual_choice={"orders": partial_orders, "phase": "partial"},
    )
    partial_report = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    final_report = next(c for c in result["candidates"] if be.LABEL_LEGAL_FINISH in c["labels"])
    self.assertEqual(partial_report["phase"], "partial")
    self.assertEqual(partial_report["prefix_orders"], partial_orders)
    self.assertEqual(partial_report["continuation_policy"], be.CONTINUATION_POLICY_NAME)
    self.assertEqual(final_report["phase"], "final")
    self.assertIsNone(final_report["continuation_policy"])
    # both were queried with mode=bounded_rollout so they are on equal
    # (post-finish, post-opponent) footing despite differing phase
    preview_calls = [c for c in driver.calls if c.get("what") == "preview_batch"]
    self.assertTrue(all(c["mode"] == "bounded_rollout" for c in preview_calls))

  def test_output_never_uses_forbidden_language(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=5))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=5, enemy_hp=5))

    def score(outcome):
      return outcome["recruiter_survival"]["hp"][0] if outcome else 0

    config = _default_config(score_fn=score, score_name="friendly_hp")
    result = self._run(driver, config=config)
    dumped = json.dumps(result)
    self.assertNotIn("optimal move", dumped)
    self.assertNotIn("regret", dumped)

  def test_best_candidate_uses_sampled_value_gap_language(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=5))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=5, enemy_hp=5))

    def score(outcome):
      return outcome["recruiter_survival"]["hp"][0] if outcome else 0

    config = _default_config(score_fn=score, score_name="friendly_hp")
    result = self._run(driver, config=config)
    self.assertIsNotNone(result["best_candidate"])
    self.assertEqual(result["best_candidate"]["candidate_id"], "candidate-0")  # actual choice, hp 20 > 5
    self.assertIn("best among tested candidates under this evaluator", result["best_candidate"]["verdict"])
    self.assertIn("candidate-1", result["sampled_value_gaps"])
    self.assertGreater(result["sampled_value_gaps"]["candidate-1"], 0)
    self.assertEqual(result["sampled_value_gaps"]["candidate-0"], 0)

  def test_two_response_horizon_is_declared_and_uses_terminal_stage(self):
    driver = MockDriver()
    driver.add_legal(
      ACTUAL_CHOICE_ORDERS,
      lambda seed: _make_rollout(seed=seed, friendly_hp=11, enemy_hp=4,
                                  opponent_responses=2),
    )
    driver.add_legal(
      LEGAL_FINISH,
      lambda seed: _make_rollout(seed=seed, friendly_hp=9, enemy_hp=7,
                                  opponent_responses=2),
    )
    result = self._run(driver, config=_default_config(opponent_responses=2))
    preview_calls = [c for c in driver.calls if c.get("what") == "preview_batch"]
    self.assertTrue(preview_calls)
    self.assertTrue(all(c["opponent_responses"] == 2 for c in preview_calls))
    self.assertEqual(result["config"]["horizon_rounds"], 2)
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    self.assertEqual(actual["completed_seeds"], list(be.default_seed_schedule(4)))
    self.assertEqual(actual["samples"][0]["outcome"]["recruiter_survival"]["hp"], [11])

  def test_multi_round_response_without_declared_horizon_is_censored(self):
    driver = MockDriver()
    driver.add_legal(ACTUAL_CHOICE_ORDERS, lambda seed: _make_rollout(seed=seed, friendly_hp=20, enemy_hp=10))
    driver.add_legal(LEGAL_FINISH, lambda seed: _make_rollout(seed=seed, friendly_hp=18, enemy_hp=10))
    seeds = be.default_seed_schedule(2)
    result = self._run(driver, config=_default_config(seed_schedule=seeds, opponent_responses=2))
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    self.assertEqual(actual["completed_seeds"], [])
    self.assertEqual({s["censor_reason"] for s in actual["samples"]}, {"unsupported_horizon"})

  def test_early_terminal_state_completes_short_horizon(self):
    driver = MockDriver()
    def terminal(seed):
      value = _make_rollout(seed=seed, friendly_hp=20, enemy_hp=0, winner=0,
                            opponent_responses=3)
      value["terminal_state"] = value["stages"]["post_opponent_1"]
      value["stages"]["post_opponent_2"] = None
      value["stages"]["post_opponent_3"] = None
      value["opponent_responses_completed"] = 1
      value["terminated_early"] = True
      return value
    driver.add_legal(ACTUAL_CHOICE_ORDERS, terminal)
    driver.add_legal(LEGAL_FINISH, terminal)
    result = self._run(driver, config=_default_config(seed_schedule=(7,), opponent_responses=3))
    actual = next(c for c in result["candidates"] if be.LABEL_ACTUAL_CHOICE in c["labels"])
    self.assertEqual(actual["completed_seeds"], [7])
    self.assertEqual(actual["samples"][0]["outcome"]["terminal_result"], 0)


class EvaluationConfigTests(unittest.TestCase):
  def test_score_fn_and_name_must_be_declared_together(self):
    with self.assertRaises(ValueError):
      be.EvaluationConfig(score_fn=lambda outcome: 0.0)
    with self.assertRaises(ValueError):
      be.EvaluationConfig(score_name="only_name")

  def test_max_candidates_floor(self):
    with self.assertRaises(ValueError):
      be.EvaluationConfig(max_candidates=1)

  def test_opponent_responses_are_bounded(self):
    self.assertEqual(be.EvaluationConfig(opponent_responses=2).opponent_responses, 2)
    self.assertEqual(be.EvaluationConfig(opponent_responses=3).opponent_responses, 3)
    with self.assertRaises(ValueError):
      be.EvaluationConfig(opponent_responses=0)
    with self.assertRaises(ValueError):
      be.EvaluationConfig(opponent_responses=4)


if __name__ == "__main__":
  unittest.main()
