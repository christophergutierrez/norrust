"""Bounded, reproducible offline evaluation of alternative plans at one
recorded decision.

This is Stack 4 of `tmp/plans/optional-game-analysis-and-controlled-evaluation.md`.
It compares a small, bounded set of legal plans from the SAME restored
position under the SAME declared evaluation-seed schedule, using the
driver's `preview_batch` query in `mode="bounded_rollout"`. That mode seeds
the private evaluation RNG once (`evaluation_seed`) before the candidate's
own orders execute, and lets that single stream continue through candidate
combat, finish/delegated behavior, and one opponent response -- never a
second fixed-seed reset. See `norrust_core/src/bin/greedy_driver.rs`,
`bounded_rollout_summary` and the `preview_batch` handler, for the Rust side
this module drives.

This module never restores a capsule and never talks to the driver process
directly -- it takes a `QueryFn` as a dependency and lets the caller
(the integrator, via `tools/decision_capsule.py`) own restoration. It never
imports `tools.decision_capsule`.

## QueryFn contract

    QueryFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]

Called with a query mapping of the exact shape the driver's stdin protocol
expects, e.g.:

    {"action": "Query", "what": "preview_batch", "mode": "bounded_rollout",
     "phase": "final", "evaluation_seed": 123, "state_revision": 42,
     "candidates": [[{"action": "FinishWithGreedy", "groups": [], "holds": []}]]}

and must return the driver's status response as a mapping -- e.g.
`{"type": "status", "ok": True, "body": {...}}` -- not the
`(response, records)` tuple some internal helpers return. A `QueryFn` may
raise on transport failure (e.g. a subprocess timeout); `evaluate()` treats
any exception the same as a driver-reported error response: as a candidate
signal, never as a Python-level crash of the evaluation run.

## Honesty rules this module enforces (see tmp/analysis-exec/CONTRACT.md,
CAPSULE-CONTRACT.md, and the plan's Stack 4 section)

- Candidates are LABELLED by origin (`actual_choice`, `shown_alternative`,
  `legal_finish`, `reference_generator`) and whether the player actually saw
  them. Merging equivalent candidates preserves every label.
- The actual choice is NEVER dropped for being illegal. It keeps its
  validation failure and never receives a rollout it did not earn.
- A timed-out or otherwise incomplete sample is CENSORED and visible in the
  output -- never recorded as a loss, a win, or silently dropped.
- Bounds here (16 candidates, 16 seeds, 1 opponent response, 120s wall
  ceiling) are EXPLORATION DEFAULTS, not statistically sufficient proof.
- Output language says "best among tested candidates under this evaluator",
  never "optimal move"; "sampled value gap", never unqualified "regret";
  and a safety caveat wherever a safety-shaped claim (e.g. zero deaths)
  would otherwise be read as a guarantee.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

QueryFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# The driver's own "delegate the entire turn to its built-in greedy logic"
# instruction (norrust_core/src/bin/greedy_driver.rs: is_routine_empty_finish).
# Used both as the default "legal finish" candidate and, implicitly, as what
# the driver does to complete a partial candidate's turn under bounded
# rollout (see CONTINUATION_POLICY_NAME below).
LEGAL_FINISH_ORDERS: tuple[Mapping[str, Any], ...] = (
  {"action": "FinishWithGreedy", "groups": [], "holds": []},
)

# The single named continuation policy applied to every partial candidate
# before completed-turn outcomes are compared, per the plan's horizon
# normalization requirement. It is not something this module implements --
# it is the driver's OWN behavior: when `preview_batch` is queried with
# `mode="bounded_rollout"` and `phase="partial"`, the driver completes the
# rest of the turn with its built-in greedy logic, under the same
# evaluation-seeded RNG stream as the candidate's own orders. Every partial
# candidate gets this identical treatment, so partial plans are compared at
# equal horizon. `preview_batch` does not expose the individual actions the
# sweep added, only aggregate event counts and the resulting state -- so the
# continuation is reported as an aggregate delta here, never as a fabricated
# order list.
CONTINUATION_POLICY_NAME = "driver_delegated_greedy_sweep_v1"

LABEL_ACTUAL_CHOICE = "actual_choice"
LABEL_SHOWN_ALTERNATIVE = "shown_alternative"
LABEL_LEGAL_FINISH = "legal_finish"
LABEL_REFERENCE = "reference_generator"

_RESERVED_LABELS = frozenset({LABEL_ACTUAL_CHOICE, LABEL_LEGAL_FINISH})

DEFAULT_MAX_CANDIDATES = 16
DEFAULT_SEED_COUNT = 16
DEFAULT_OPPONENT_RESPONSES = 1
MAX_OPPONENT_RESPONSES = 3
DEFAULT_WALL_CEILING_SECONDS = 120.0

# Response codes that describe an INFRASTRUCTURE failure (stale restored
# state, wrong side to move, a query budget timeout, an oversized reply, a
# transport exception this module wrapped) rather than a verdict on whether
# the candidate's orders are legal. These never mark a candidate illegal;
# they censor the individual sample and evaluation moves on.
_INFRA_ERROR_CODES = frozenset({
  "stale_state", "unauthorized_side", "query_timeout", "reply_too_large",
  "internal_error", "query_exception",
})


def default_seed_schedule(count: int = DEFAULT_SEED_COUNT) -> tuple[int, ...]:
  """A small, fixed, declared evaluation-seed schedule.

  Deterministic and reused verbatim for every candidate so results are
  reproducible and comparable across candidates. This is never drawn from
  live game RNG -- private replay state, including RNG, is a replay input
  only, never seeded from the future (CAPSULE-CONTRACT.md hard rule 2).
  """
  if count < 1:
    raise ValueError("a seed schedule must declare at least one seed")
  base = 0x5EED_5EED_5EED_5EED
  return tuple((base + index) & 0xFFFFFFFFFFFFFFFF for index in range(count))


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class EvaluationConfig:
  """Bounds and predeclared scoring for one evaluation run.

  `score_fn` and `score_name` must be declared TOGETHER, before results are
  seen -- the plan forbids tuning a scalar score on the held-out evaluation
  set. `tie_break` is a human-readable description of the tie-break rule
  actually used (lowest candidate index among ties on the predeclared
  score), logged for auditability; the code's tie-break behavior itself is
  fixed (see `select_best_candidate`), not driven by this string.
  """
  max_candidates: int = DEFAULT_MAX_CANDIDATES
  seed_schedule: tuple[int, ...] = field(default_factory=default_seed_schedule)
  opponent_responses: int = DEFAULT_OPPONENT_RESPONSES
  wall_ceiling_seconds: float = DEFAULT_WALL_CEILING_SECONDS
  continuation_policy: str = CONTINUATION_POLICY_NAME
  score_fn: Callable[[Mapping[str, Any]], float] | None = None
  score_name: str | None = None
  tie_break: str = "lowest candidate index among ties on the predeclared score"

  def __post_init__(self) -> None:
    if self.max_candidates < 2:
      raise ValueError(
        "max_candidates must allow at least the actual choice and the legal finish")
    if not self.seed_schedule:
      raise ValueError("seed_schedule must declare at least one seed")
    if not 1 <= self.opponent_responses <= MAX_OPPONENT_RESPONSES:
      raise ValueError(
        "opponent_responses must be between 1 and "
        f"{MAX_OPPONENT_RESPONSES} complete responses"
      )
    if (self.score_fn is None) != (self.score_name is None):
      raise ValueError(
        "score_fn and score_name must be declared together and in advance")


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
  """One assembled candidate: an order sequence to submit to `preview_batch`,
  labelled with every origin it was reached from."""
  candidate_id: str
  orders: tuple[Mapping[str, Any], ...]
  phase: str                    # "final" | "partial"
  labels: tuple[str, ...]
  seen_by_player: bool


def _normalize_raw_candidate(
  raw: Mapping[str, Any],
  *,
  default_label: str,
  default_seen: bool,
) -> tuple[tuple[Mapping[str, Any], ...], tuple[str, ...], bool, str]:
  orders = tuple(raw["orders"])
  if raw.get("labels"):
    labels = tuple(raw["labels"])
  else:
    labels = (raw.get("label", default_label),)
  seen = bool(raw.get("seen_by_player", default_seen))
  phase = raw.get("phase", "final")
  if phase not in ("final", "partial"):
    raise ValueError(f"candidate phase must be 'final' or 'partial', got {phase!r}")
  return orders, labels, seen, phase


def assemble_candidates(
  *,
  actual_choice: Mapping[str, Any],
  shown_alternatives: Sequence[Mapping[str, Any]] = (),
  legal_finish: Sequence[Mapping[str, Any]] | None = None,
  reference_candidates: Sequence[Mapping[str, Any]] = (),
) -> list[Candidate]:
  """Assemble the bounded candidate set from the plan's four declared
  sources, each explicitly labelled with its origin and whether the player
  actually saw it. `legal_finish=None` uses the driver's own empty-finish
  delegation (`LEGAL_FINISH_ORDERS`).

  Each raw candidate mapping (for `actual_choice`, entries of
  `shown_alternatives`, and entries of `reference_candidates`) has the shape
  `{"orders": [...], "label": str | "labels": [str, ...],
  "seen_by_player": bool, "phase": "final" | "partial"}`; only `orders` is
  required. Does not deduplicate or prune -- see `dedup_candidates` and
  `prune_candidates`.
  """
  raw_items: list[tuple[Mapping[str, Any], str, bool]] = [
    (actual_choice, LABEL_ACTUAL_CHOICE, True),
  ]
  for alternative in shown_alternatives:
    raw_items.append((alternative, LABEL_SHOWN_ALTERNATIVE, True))
  finish_orders = tuple(legal_finish) if legal_finish is not None else LEGAL_FINISH_ORDERS
  raw_items.append(({"orders": finish_orders}, LABEL_LEGAL_FINISH, False))
  for reference in reference_candidates:
    raw_items.append((reference, LABEL_REFERENCE, False))

  candidates: list[Candidate] = []
  for index, (raw, default_label, default_seen) in enumerate(raw_items):
    orders, labels, seen, phase = _normalize_raw_candidate(
      raw, default_label=default_label, default_seen=default_seen)
    candidates.append(Candidate(
      candidate_id=f"candidate-{index}",
      orders=orders, phase=phase, labels=labels, seen_by_player=seen,
    ))
  return candidates


def _canonical_orders_key(orders: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
  return tuple(json.dumps(order, sort_keys=True, separators=(",", ":")) for order in orders)


def dedup_candidates(candidates: Sequence[Candidate]) -> list[Candidate]:
  """Merge candidates that share the same canonical executed order sequence
  AND continuation context (phase -- a partial and a final candidate with
  textually identical orders are NOT the same continuation context, since
  the partial one is completed by the delegated sweep and the final one is
  not).

  Preserves every source label on the merged candidate: a plan reachable
  two ways (e.g. the actual choice was also offered as a shown alternative)
  keeps both labels, and `candidate_id` is kept from the first occurrence so
  downstream ordering stays stable.
  """
  merged: dict[tuple[tuple[str, ...], str], Candidate] = {}
  order: list[tuple[tuple[str, ...], str]] = []
  for candidate in candidates:
    key = (_canonical_orders_key(candidate.orders), candidate.phase)
    if key in merged:
      existing = merged[key]
      combined_labels = tuple(dict.fromkeys((*existing.labels, *candidate.labels)))
      merged[key] = replace(
        existing,
        labels=combined_labels,
        seen_by_player=existing.seen_by_player or candidate.seen_by_player,
      )
    else:
      merged[key] = candidate
      order.append(key)
  return [merged[key] for key in order]


def prune_candidates(candidates: Sequence[Candidate], max_candidates: int) -> list[Candidate]:
  """Reserve the selected action and the legal finish BEFORE pruning the
  rest to fit `max_candidates`. Original relative order is preserved."""
  reserved = [c for c in candidates if _RESERVED_LABELS & set(c.labels)]
  others = [c for c in candidates if not (_RESERVED_LABELS & set(c.labels))]
  remaining_budget = max(max_candidates - len(reserved), 0)
  kept_others = others[:remaining_budget]
  kept_ids = {id(c) for c in (*reserved, *kept_others)}
  return [c for c in candidates if id(c) in kept_ids]


# --------------------------------------------------------------------------
# Reference candidate generation (the plan's "small deterministic reference
# generator"). Only ever offers actions the driver's own enumeration showed
# as reachable; never invents one.
# --------------------------------------------------------------------------

def generate_reference_candidates(query: QueryFn, state_revision: int) -> list[dict[str, Any]]:
  """A small, deterministic reference set built from the driver's own
  `turn_options`/`recruit_options` enumeration at the restored position.

  At most one attack candidate (the lowest `(attacker_id, defender_id)`
  pair the driver's own `turn_options` reports as reachable) and one
  recruitment candidate (the cheapest affordable option at the first listed
  placement hex) -- "only where supported and legal": each is included
  only when the driver's enumeration actually offers it, never guessed.
  Both are `phase="partial"`, since a single action does not finish a turn;
  `evaluate()` applies the same delegated-sweep continuation as any other
  partial candidate.
  """
  candidates: list[dict[str, Any]] = []

  try:
    turn_response = query({
      "action": "Query", "what": "turn_options", "state_revision": state_revision,
    })
  except Exception:
    turn_response = {"ok": False}
  if turn_response.get("ok"):
    best_pair: tuple[int, int] | None = None
    for unit in turn_response.get("body", {}).get("units", []):
      unit_id = unit.get("unit_id")
      if unit_id is None:
        continue
      for position in unit.get("positions", []):
        for target_id in position.get("target_ids") or []:
          pair = (unit_id, target_id)
          if best_pair is None or pair < best_pair:
            best_pair = pair
    if best_pair is not None:
      attacker_id, defender_id = best_pair
      candidates.append({
        "orders": [{"action": "Attack", "attacker_id": attacker_id, "defender_id": defender_id}],
        "label": "reference:lowest_id_reachable_attack",
        "phase": "partial",
      })

  try:
    recruit_response = query({
      "action": "Query", "what": "recruit_options", "state_revision": state_revision,
    })
  except Exception:
    recruit_response = {"ok": False}
  if recruit_response.get("ok"):
    body = recruit_response.get("body", {})
    placements = body.get("placement_hexes") or []
    affordable = [o for o in body.get("options", []) if o.get("affordable")]
    if placements and affordable:
      cheapest = min(affordable, key=lambda option: (option.get("cost", 0), option.get("def_id")))
      hex0 = placements[0]
      candidates.append({
        "orders": [{
          "action": "Recruit", "def_id": cheapest["def_id"],
          "col": hex0["col"], "row": hex0["row"],
        }],
        "label": "reference:cheapest_affordable_recruit",
        "phase": "partial",
      })

  return candidates


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Sample:
  seed: int
  status: str                              # "completed" | "censored"
  censor_reason: str | None
  outcome: Mapping[str, Any] | None        # raw outcome vector; None unless completed


def _side_summary(stage: Mapping[str, Any] | None, side: int) -> Mapping[str, Any] | None:
  if not stage:
    return None
  for entry in stage.get("sides", []):
    if entry.get("side") == side:
      return entry
  return None


def _delta(post: Mapping[str, Any] | None, pre: Mapping[str, Any] | None, key: str) -> int | None:
  if post is None or pre is None:
    return None
  post_value, pre_value = post.get(key), pre.get(key)
  if post_value is None or pre_value is None:
    return None
  return post_value - pre_value


def extract_outcome_vector(
  rollout: Mapping[str, Any], *, model_side: int, opponent_side: int,
) -> dict[str, Any]:
  """The raw outcome vector for one completed sample, straight from the
  driver's `bounded_rollout_summary`/`rollout_state_summary` fields.

  Kept strictly separate from any named heuristic score -- see
  `EvaluationConfig.score_fn` -- per the plan's "record raw outcome vectors
  ... save distributions and named heuristic scores separately."
  """
  stages = rollout.get("stages", {}) or {}
  post_finish = stages.get("post_finish")
  terminal_state = rollout.get("terminal_state")
  # Horizon-1 uses the historical singular key. Multi-round drivers may
  # expose post_opponent_1, post_opponent_2, ...; choose the final present
  # stage so terminal outcomes remain raw driver evidence.
  opponent_stages = [
    stages[name] for name in sorted(
      (name for name in stages if name.startswith("post_opponent_")),
      key=lambda name: int(name.rsplit("_", 1)[1]) if name.rsplit("_", 1)[1].isdigit() else -1,
    )
    if stages[name] is not None
  ]
  if terminal_state is not None:
    terminal_stage = terminal_state
  elif opponent_stages:
    terminal_stage = opponent_stages[-1]
  else:
    post_opponent = stages.get("post_opponent")
    terminal_stage = post_opponent if post_opponent is not None else post_finish

  friendly_pre = _side_summary(post_finish, model_side)
  friendly_post = _side_summary(terminal_stage, model_side)
  enemy_pre = _side_summary(post_finish, opponent_side)
  enemy_post = _side_summary(terminal_stage, opponent_side)

  recruiters = [
    unit for unit in (terminal_stage or {}).get("units_detail", [])
    if unit.get("side") == model_side and unit.get("recruiter")
  ]

  return {
    "terminal_result": (terminal_stage or {}).get("winner"),
    "recruiter_survival": {
      "count_alive": len(recruiters),
      "hp": [unit.get("hp") for unit in recruiters],
    },
    "friendly_material_change": _delta(friendly_post, friendly_pre, "material_cost"),
    "enemy_material_change": _delta(enemy_post, enemy_pre, "material_cost"),
    "friendly_villages": friendly_post.get("villages") if friendly_post else None,
    "enemy_villages": enemy_post.get("villages") if enemy_post else None,
    "friendly_gold": friendly_post.get("gold") if friendly_post else None,
    # "useful committed actions": the driver's own combined event count for
    # the candidate's submitted orders (and, for a partial candidate, the
    # delegated sweep that completed the turn -- preview_batch reports these
    # combined, not separately; see CONTINUATION_POLICY_NAME).
    "committed_events": rollout.get("own_event_count"),
    "opponent_event_count": rollout.get("opponent_event_count"),
    "opponent_error": rollout.get("opponent_error"),
    "opponent_responded": (rollout.get("coverage") or {}).get("opponent_response"),
    "legal": True,
  }


def _build_query(
  candidate: Candidate, seed: int, state_revision: int, opponent_responses: int,
) -> dict[str, Any]:
  return {
    "action": "Query",
    "what": "preview_batch",
    "mode": "bounded_rollout",
    "phase": candidate.phase,
    "evaluation_seed": seed,
    "state_revision": state_revision,
    # Explicitly declare the bounded multi-round horizon. A driver that does
    # not report this horizon is handled as censored by _run_candidate.
    "opponent_responses": opponent_responses,
    # The driver accepts at most two candidate order-arrays per call
    # ("candidates must contain one or two action arrays"). This module
    # always sends exactly one: pairing two candidates in the same call
    # would let one candidate's contract violation fail the WHOLE call,
    # silently withholding a legal partner's result. One-per-call is the
    # "existing small driver request limit in chunks" used safely.
    "candidates": [list(candidate.orders)],
  }


@dataclass(frozen=True)
class CandidateResult:
  candidate: Candidate
  legal: bool | None            # None = never determined (every attempt hit an infra error)
  validation_failure: Mapping[str, Any] | None
  samples: tuple[Sample, ...]

  @property
  def completed_seeds(self) -> tuple[int, ...]:
    return tuple(s.seed for s in self.samples if s.status == "completed")

  @property
  def censored_seeds(self) -> tuple[int, ...]:
    return tuple(s.seed for s in self.samples if s.status == "censored")


def _run_candidate(
  query: QueryFn,
  candidate: Candidate,
  *,
  state_revision: int,
  model_side: int,
  opponent_side: int,
  seed_schedule: Sequence[int],
  opponent_responses: int,
  deadline: float,
  now: Callable[[], float],
  termination_reasons: set[str],
) -> CandidateResult:
  legal: bool | None = None
  validation_failure: Mapping[str, Any] | None = None
  samples: list[Sample] = []

  for seed in seed_schedule:
    if legal is False:
      # The actual choice keeps its validation failure but never gets a
      # rollout it never earned -- stop sampling once a candidate is known
      # illegal, for every candidate, not only the actual choice.
      break
    if now() >= deadline:
      termination_reasons.add("wall_ceiling_exceeded")
      samples.append(Sample(seed, "censored", "wall_ceiling_exceeded", None))
      continue

    try:
      response = query(_build_query(candidate, seed, state_revision, opponent_responses))
    except Exception as exc:  # noqa: BLE001 - a transport failure is evaluation data
      response = {"ok": False, "code": "query_exception", "message": str(exc)}

    ok = response.get("ok") is True
    code = response.get("code")

    if not ok and code in _INFRA_ERROR_CODES:
      samples.append(Sample(seed, "censored", code or "infra_error", None))
      continue

    if not ok:
      legal = False
      validation_failure = dict(response)
      continue

    body = response.get("body") or {}
    candidate_bodies = body.get("candidates") or []
    candidate_body = candidate_bodies[0] if candidate_bodies else None
    if candidate_body is None or candidate_body.get("valid") is not True:
      legal = False
      validation_failure = dict(candidate_body) if candidate_body else {
        "message": "driver rejected the candidate with no candidate body",
      }
      continue

    legal = True
    rollout = candidate_body.get("post_sweep")
    if rollout is None:
      samples.append(Sample(seed, "censored", "rollout_unavailable", None))
      continue

    declared_horizon = rollout.get("opponent_responses")
    # A terminal game is a valid completed sample even when it ends before the
    # requested horizon. The driver must provide the terminal state explicitly;
    # a missing numbered stage alone remains an unsupported horizon.
    terminal_complete = rollout.get("terminal_state") is not None
    if opponent_responses > 1 and declared_horizon != opponent_responses and not terminal_complete:
      samples.append(Sample(seed, "censored", "unsupported_horizon", None))
      continue

    outcome = extract_outcome_vector(rollout, model_side=model_side, opponent_side=opponent_side)
    samples.append(Sample(seed, "completed", None, outcome))

  return CandidateResult(
    candidate=candidate, legal=legal, validation_failure=validation_failure,
    samples=tuple(samples),
  )


def compute_matched_seed_subset(results: Sequence[CandidateResult]) -> tuple[int, ...]:
  """The seed subset every LEGAL candidate with at least one completed
  sample actually completed. Comparisons across candidates with differing
  completion counts use this subset, per the plan's matched-seed rule."""
  completed_sets = [
    set(result.completed_seeds) for result in results
    if result.legal and result.completed_seeds
  ]
  if not completed_sets:
    return ()
  common = completed_sets[0]
  for other in completed_sets[1:]:
    common &= other
  return tuple(sorted(common))


# --------------------------------------------------------------------------
# Scoring (kept strictly separate from raw outcome vectors)
# --------------------------------------------------------------------------

def _mean(values: Sequence[float]) -> float | None:
  values = list(values)
  return sum(values) / len(values) if values else None


def summarize_scores(
  results: Sequence[CandidateResult],
  matched_seeds: Sequence[int],
  score_fn: Callable[[Mapping[str, Any]], float],
) -> dict[str, dict[str, Any]]:
  """Per-candidate score distribution over the matched-seed subset only.
  Distinct from `extract_outcome_vector` -- this is the predeclared
  heuristic, not the raw record."""
  matched = set(matched_seeds)
  summary: dict[str, dict[str, Any]] = {}
  for result in results:
    if not result.legal:
      continue
    scores = [
      score_fn(sample.outcome) for sample in result.samples
      if sample.status == "completed" and sample.seed in matched and sample.outcome is not None
    ]
    summary[result.candidate.candidate_id] = {
      "scores": scores, "mean": _mean(scores), "n": len(scores),
    }
  return summary


def select_best_candidate(
  score_summary: Mapping[str, Mapping[str, Any]],
  order: Sequence[str],
) -> str | None:
  """Best-scoring candidate id among those with at least one matched-seed
  sample, tie-broken by lowest candidate index (`order`'s own sequence --
  `max()` returns the first-encountered item on ties, which is why `order`
  must already be index-ascending). Predeclared, not chosen post hoc."""
  eligible = [cid for cid in order if score_summary.get(cid, {}).get("n", 0) > 0]
  if not eligible:
    return None
  return max(eligible, key=lambda cid: score_summary[cid]["mean"])


# --------------------------------------------------------------------------
# Top-level entry point
# --------------------------------------------------------------------------

def evaluate(
  query: QueryFn,
  *,
  state_revision: int,
  model_side: int,
  opponent_side: int,
  actual_choice: Mapping[str, Any],
  shown_alternatives: Sequence[Mapping[str, Any]] = (),
  legal_finish: Sequence[Mapping[str, Any]] | None = None,
  reference_candidates: Sequence[Mapping[str, Any]] | None = None,
  config: EvaluationConfig | None = None,
  now: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
  """Evaluate a bounded set of alternative plans from one restored decision.

  `reference_candidates=None` (the default) auto-generates the small
  deterministic reference set via `generate_reference_candidates(query,
  state_revision)`; pass `()` to explicitly evaluate without one.

  Repeating a call with the same `query` responses, `config`, and clock
  produces byte-for-byte identical `candidates`/`scores`/`best_candidate`
  content (only `log.elapsed_seconds` and `log.started_at` vary with wall
  time) -- see `tools/test_bounded_evaluation.py`'s reproducibility test.
  """
  cfg = config or EvaluationConfig()
  if reference_candidates is None:
    reference_candidates = generate_reference_candidates(query, state_revision)

  assembled = assemble_candidates(
    actual_choice=actual_choice, shown_alternatives=shown_alternatives,
    legal_finish=legal_finish, reference_candidates=reference_candidates,
  )
  deduped = dedup_candidates(assembled)
  pruned = prune_candidates(deduped, cfg.max_candidates)
  pruning_occurred = len(pruned) < len(deduped)

  termination_reasons: set[str] = set()
  if pruning_occurred:
    termination_reasons.add("candidate_budget_pruned")

  # Reserved candidates (actual choice, legal finish) are sampled first so a
  # wall-ceiling shortfall falls on the rest of the set, never on them.
  reserved = [c for c in pruned if _RESERVED_LABELS & set(c.labels)]
  others = [c for c in pruned if not (_RESERVED_LABELS & set(c.labels))]
  processing_order = [*reserved, *others]

  started_at = now()
  deadline = started_at + cfg.wall_ceiling_seconds

  results_by_id: dict[str, CandidateResult] = {}
  observed_opponent_policy: str | None = None
  for candidate in processing_order:
    result = _run_candidate(
      query, candidate, state_revision=state_revision, model_side=model_side,
      opponent_side=opponent_side, seed_schedule=cfg.seed_schedule, deadline=deadline,
      opponent_responses=cfg.opponent_responses,
      now=now, termination_reasons=termination_reasons,
    )
    results_by_id[candidate.candidate_id] = result

  # Report in the assembled (not processing) order for readability.
  ordered_results = [results_by_id[c.candidate_id] for c in pruned]
  elapsed = now() - started_at

  matched_seeds = compute_matched_seed_subset(ordered_results)
  completion_counts = {r.candidate.candidate_id: len(r.completed_seeds) for r in ordered_results if r.legal}
  matched_seed_comparison_note = None
  if len(set(completion_counts.values())) > 1:
    matched_seed_comparison_note = (
      "candidates completed different numbers of samples; comparison uses "
      "the matched-seed subset shown in matched_seed_subset, not each "
      "candidate's full sample set"
    )

  scores_summary: dict[str, Any] | None = None
  best_candidate: dict[str, Any] | None = None
  sampled_value_gaps: dict[str, float] | None = None
  if cfg.score_fn is not None and matched_seeds:
    scores_summary = summarize_scores(ordered_results, matched_seeds, cfg.score_fn)
    order = [r.candidate.candidate_id for r in ordered_results]
    best_id = select_best_candidate(scores_summary, order)
    if best_id is not None:
      best_mean = scores_summary[best_id]["mean"]
      sampled_value_gaps = {
        cid: (best_mean - summary["mean"])
        for cid, summary in scores_summary.items()
        if summary["mean"] is not None
      }
      best_candidate = {
        "candidate_id": best_id,
        "score_name": cfg.score_name,
        "mean_score": best_mean,
        "matched_seed_count": len(matched_seeds),
        "verdict": (
          f"{best_id} is best among tested candidates under this evaluator "
          f"(mean {cfg.score_name} over {len(matched_seeds)} matched-seed "
          "samples). This ranks only the candidates that were actually "
          "tested here; it is not a claim about the single best action in "
          "the position, and short-horizon sampling can miss effects "
          "further into the game."
        ),
      }

  notes = [
    "max_candidates, the seed schedule, and the wall ceiling are exploration "
    "defaults, not statistically sufficient proof.",
    "equal evaluation seeds do not guarantee identical combat events across "
    "candidates, because different actions consume random numbers "
    "differently; this improves reproducibility without claiming perfect "
    "event pairing.",
    "zero recorded deaths across the sampled seeds is not a guarantee of "
    "safety beyond the tested seed schedule.",
  ]

  candidate_reports = []
  for result in ordered_results:
    candidate = result.candidate
    candidate_reports.append({
      "candidate_id": candidate.candidate_id,
      "labels": list(candidate.labels),
      "seen_by_player": candidate.seen_by_player,
      "phase": candidate.phase,
      "prefix_orders": list(candidate.orders),
      "continuation_policy": cfg.continuation_policy if candidate.phase == "partial" else None,
      "legal": result.legal,
      "validation_failure": result.validation_failure,
      "completed_seeds": list(result.completed_seeds),
      "censored_seeds": list(result.censored_seeds),
      "samples": [
        {
          "seed": sample.seed, "status": sample.status,
          "censor_reason": sample.censor_reason, "outcome": sample.outcome,
        }
        for sample in result.samples
      ],
    })

  # The observed opponent policy identity is provenance, not an outcome
  # field, so extract_outcome_vector deliberately does not carry it. Any
  # completed sample confirms the driver actually ran a bounded rollout, and
  # `bounded_rollout_summary` always stamps the same fixed policy identity
  # ("driver_greedy_one_response_v2") on every rollout it produces.
  for candidate in processing_order:
    result = results_by_id[candidate.candidate_id]
    if any(sample.status == "completed" for sample in result.samples):
      observed_opponent_policy = "driver_greedy_one_response_v2"
      break

  return {
    "generated_by": "tools.bounded_evaluation",
    "state_revision": state_revision,
    "model_side": model_side,
    "opponent_side": opponent_side,
    "config": {
      "max_candidates": cfg.max_candidates,
      "seed_count": len(cfg.seed_schedule),
      "opponent_responses": cfg.opponent_responses,
      "horizon_rounds": cfg.opponent_responses,
      "wall_ceiling_seconds": cfg.wall_ceiling_seconds,
      "continuation_policy": cfg.continuation_policy,
      "score_name": cfg.score_name,
      "tie_break": cfg.tie_break,
    },
    "log": {
      "seed_schedule": list(cfg.seed_schedule),
      "observed_opponent_policy": observed_opponent_policy,
      "continuation_policy": cfg.continuation_policy,
      "depth": {
        "description": "candidate finish (or delegated sweep for a partial "
                        "candidate) then the declared number of opponent responses",
        "opponent_responses": cfg.opponent_responses,
      },
      "candidate_budget": cfg.max_candidates,
      "sample_budget_per_candidate": len(cfg.seed_schedule),
      "elapsed_seconds": elapsed,
      "termination_reasons": sorted(termination_reasons),
    },
    "candidates": candidate_reports,
    "matched_seed_subset": list(matched_seeds),
    "matched_seed_comparison_note": matched_seed_comparison_note,
    "scores": scores_summary,
    "best_candidate": best_candidate,
    "sampled_value_gaps": sampled_value_gaps,
    "notes": notes,
  }
