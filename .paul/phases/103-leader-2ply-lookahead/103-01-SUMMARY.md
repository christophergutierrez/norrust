---
phase: 103-leader-2ply-lookahead
plan: 01
subsystem: ai
tags: [2-ply, lookahead, opponent-response, oscillation-fix]

requires:
  - phase: 99-1ply-lookahead
    provides: plan_unit_action, clone-simulate-evaluate pattern
  - phase: 102-recruit-first
    provides: simulate_recruitment, recruit_defs threading
provides:
  - evaluate_with_opponent_response() — 2-ply scoring
  - depth parameter on plan_unit_action for configurable lookahead
  - All units use 2-ply lookahead (~20ms total)
affects: []

tech-stack:
  added: []
  patterns: [2-ply-greedy-response, depth-parameter-on-planner]

key-files:
  created: []
  modified: [norrust_core/src/ai.rs]

key-decisions:
  - "All units get 2-ply, not just leader — performance allowed it (~20ms)"
  - "Opponent response is greedy 1-ply (no recursive depth) to avoid exponential blowup"
  - "2-ply march: evaluate each move candidate with opponent response, not just nearest-enemy heuristic"

patterns-established:
  - "evaluate_with_opponent_response: clone state, run all enemy plan_unit_action(depth=1), evaluate result"
  - "depth parameter gates 1-ply vs 2-ply in plan_unit_action; internal callers always use depth=1 for opponent sim"

duration: ~15min
started: 2026-03-10
completed: 2026-03-10
---

# Phase 103 Plan 01: Leader 2-Ply Lookahead Summary

**All AI units now use 2-ply lookahead — each candidate action is scored after simulating the opponent's best greedy response, catching oscillation and improving tactical decisions across the board.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Tasks | 3 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: 2-ply evaluates opponent response | Pass | evaluate_with_opponent_response runs all enemy 1-ply actions before scoring |
| AC-2: Leader uses 2-ply | Pass | All units use 2-ply (exceeded plan — leader-only not needed) |
| AC-3: Performance within bounds | Pass | ~20ms all-unit 2-ply, far under 30s debug bound |
| AC-4: Existing behavior preserved | Pass | 107 unit tests pass, AI vs AI terminates in 0.44s |

## Accomplishments

- `evaluate_with_opponent_response()` simulates opponent's greedy best response before scoring
- `depth` parameter on `plan_unit_action` gates 1-ply vs 2-ply cleanly
- All units upgraded to 2-ply (not just leader) — ~20ms total planning time made this viable
- 2-ply march evaluation: each move candidate scored with opponent response instead of naive nearest-enemy heuristic

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added evaluate_with_opponent_response, depth param, 3 tests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| All units 2-ply (not leader-only) | 20ms total ≪ 30s bound; all units benefit | Better tactical play across the board |
| Greedy opponent response (not minimax) | Simple, fast, realistic; no exponential depth | Catches oscillation without complexity |
| 2-ply for march moves too | Marching toward enemy is strategic; opponent response matters | Units choose better positions |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope expansion | 1 | Positive — all units 2-ply instead of leader-only |
| Deferred | 0 | - |

**Total impact:** Performance allowed exceeding plan scope (all-unit 2-ply). Strictly positive.

### Scope Expansion

**1. All units upgraded to 2-ply**
- **Plan said:** Leader gets 2-ply, others 1-ply; extend if performance allows
- **Actual:** 20ms total made all-unit 2-ply trivial; enabled immediately
- **Impact:** Better tactical decisions for all units, not just leader

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- v3.6 AI Leader Intelligence milestone complete (both phases done)
- 107 unit tests provide safety net
- AI vs AI terminates quickly (0.44s)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 103-leader-2ply-lookahead, Plan: 01*
*Completed: 2026-03-10*
