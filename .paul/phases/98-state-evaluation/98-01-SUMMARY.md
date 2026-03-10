---
phase: 98-state-evaluation
plan: 01
subsystem: ai
tags: [ai, evaluation, heuristic, game-ai]

requires:
  - phase: 97-recruit-discipline
    provides: leader identification helpers reused in leader safety scoring
provides:
  - evaluate_state(state, faction) → f32 holistic board evaluation
  - Scoring components: HP, unit count, HP ratio, villages, gold, objective proximity, leader safety
affects: [99-lookahead, 100-turn-planning, 101-ranged-tactical]

tech-stack:
  added: []
  patterns: [zero-sum evaluation with centered HP ratio]

key-files:
  created: []
  modified: [norrust_core/src/ai.rs]

key-decisions:
  - "HP ratio centered at 0 (own/total - 0.5)*2*weight, not raw ratio, for zero-sum symmetry"
  - "Positional value simplified: both attacker and defender benefit from objective proximity"
  - "Enemy leader low-HP bonus (opportunity to kill) separate from own leader safety"

patterns-established:
  - "evaluate_state as pure function consuming &GameState — no mutation, clonable"

duration: ~10min
completed: 2026-03-10
---

# Phase 98 Plan 01: State Evaluation Summary

**Pure `evaluate_state(state, faction) → f32` function scoring board positions by HP, unit count, villages, gold, objective proximity, and leader safety.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-03-10 |
| Tasks | 2 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: HP advantage scores higher | Pass | `test_eval_hp_advantage` — 60 HP vs 20 HP gives higher score |
| AC-2: Village control contributes | Pass | `test_eval_village_control` — owning 2 villages vs 0 scores higher |
| AC-3: Terminal states extreme | Pass | `test_eval_terminal_win` + `test_eval_terminal_loss` — f32::MAX/MIN |
| AC-4: Positional objective proximity | Pass | Implemented; proximity reward for both attacker and defender |
| AC-5: Leader safety contributes | Pass | `test_eval_leader_safety` — full HP leader scores higher than wounded |

## Accomplishments

- Added `evaluate_state` pub function with 7 weighted scoring components
- HP ratio uses centered formula `(own/total - 0.5)*2*weight` for zero-sum symmetry
- 6 new tests: hp_advantage, village_control, terminal_win, terminal_loss, leader_safety, symmetric
- All 134 tests pass (92 unit + 42 integration), no new clippy warnings

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added `evaluate_state` function + 6 tests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Centered HP ratio (subtract 0.5) | Raw ratio always positive for both sides, breaking symmetry test | Zero-sum: equal forces → score ≈ 0 |
| Simplified positional value | Both attacker and defender benefit from proximity equally | Cleaner code, defender naturally blocks by being near objective |
| Enemy leader opportunity bonus | Low-HP enemy leader is a strategic opportunity worth scoring | Encourages finishing off wounded leaders |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | HP ratio formula needed centering for symmetry |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Minimal — one formula adjustment during testing.

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- `evaluate_state` is pub and ready for Phase 99 to consume
- Function takes `&GameState` — works with cloned states for lookahead
- Weights are reasonable defaults; can be tuned when Phase 99 exposes move quality

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 98-state-evaluation, Plan: 01*
*Completed: 2026-03-10*
