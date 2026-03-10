---
phase: 99-lookahead
plan: 01
subsystem: ai
tags: [lookahead, evaluate_state, clone-simulate, plan_unit_action]

requires:
  - phase: 98-state-evaluation
    provides: evaluate_state(state, faction) -> f32
provides:
  - plan_unit_action() 1-ply lookahead helper
  - Shared decision logic for ai_take_turn and ai_plan_turn
affects: [100-turn-planning, 101-ranged-tactical]

tech-stack:
  added: []
  patterns: [clone-simulate-evaluate per unit action]

key-files:
  modified: [norrust_core/src/ai.rs]

key-decisions:
  - "No baseline comparison for attacks: always pick best attack when attacks available"
  - "March heuristic for move-only: avoids expensive cloning when no attacks possible"
  - "score_attack and expected_outgoing_damage kept but marked #[allow(dead_code)]"

patterns-established:
  - "Clone-simulate-evaluate: clone state, apply action, evaluate result, pick best"

duration: ~30min
completed: 2026-03-10
---

# Phase 99 Plan 01: 1-Ply Unit Lookahead Summary

**Replaced greedy score_attack with clone-simulate-evaluate lookahead: each AI unit tries all reachable (move, attack) combinations on cloned state, picks action producing best evaluate_state score.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-10 |
| Tasks | 2 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: AI uses evaluate_state for move+attack decisions | Pass | plan_unit_action clones, applies, evaluates |
| AC-2: AI considers move-only actions | Pass | March heuristic moves toward nearest enemy |
| AC-3: Existing behavior preserved | Pass | 137 tests pass, AI vs AI terminates |
| AC-4: Both ai_take_turn and ai_plan_turn use lookahead | Pass | Both call plan_unit_action |

## Accomplishments

- Created `plan_unit_action()` shared helper replacing duplicated inline scoring in both AI functions
- AI now evaluates board state after simulated actions instead of scoring attacks in isolation
- 3 new lookahead behavior tests validating kill preference, attack positioning, and march behavior

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added plan_unit_action, rewrote ai_take_turn/ai_plan_turn, added 3 tests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| No baseline comparison for attacks | Using evaluate_state baseline made AI too conservative (refused to attack when retaliation damage worsened score) — caused stalemate | AI always attacks when possible, picks best target |
| March heuristic for move-only | Cloning state for every reachable hex is expensive in debug builds (~60s per balance test) | Move-only uses distance-to-enemy heuristic, fast |
| Keep score_attack as dead code | Plan specified keeping it for future use | Marked #[allow(dead_code)] to suppress warnings |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential — fixed AI stalemate |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** One critical fix to prevent AI stalemate.

### Auto-fixed Issues

**1. AI stalemate with baseline comparison**
- **Found during:** Task 1 (plan_unit_action implementation)
- **Issue:** Plan specified "only pick a move/attack if it improves over staying" (baseline = current evaluate_state). This made AI refuse all attacks when retaliation damage lowered the score, causing infinite stalemate in ai_vs_ai test.
- **Fix:** Changed attack scoring to use f32::NEG_INFINITY as baseline — always pick the best attack when any attack is available. Baseline comparison only applies to "act vs don't act" for positioning.
- **Files:** norrust_core/src/ai.rs
- **Verification:** test_ai_vs_ai_terminates passes

**2. Move-only evaluation too slow**
- **Found during:** Task 1
- **Issue:** Cloning state for every reachable hex (move-only evaluation) caused balance tests to take >60s each in debug builds.
- **Fix:** Move-only candidates use march heuristic (closest to nearest enemy) instead of clone-evaluate.
- **Files:** norrust_core/src/ai.rs
- **Verification:** Balance tests complete in ~110s total

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| test_ai_vs_ai_terminates failed (10 units survived 100 turns) | Removed baseline comparison for attacks |
| Balance tests too slow with full move-only evaluation | Switched to march heuristic for move-only |

## Next Phase Readiness

**Ready:**
- plan_unit_action provides clean per-unit decision interface
- evaluate_state proven to produce good decisions when used for attack selection
- Clone-simulate pattern works within performance budget

**Concerns:**
- Move-only decisions still use heuristic (not evaluation) — Phase 100 turn planning could improve this
- Per-unit lookahead doesn't consider unit ordering — Phase 100 addresses coordination

**Blockers:**
- None

---
*Phase: 99-lookahead, Plan: 01*
*Completed: 2026-03-10*
