---
phase: 100-turn-planning
plan: 01
subsystem: ai
tags: [turn-planning, multi-ordering, coordination, plan_full_turn]

requires:
  - phase: 99-lookahead
    provides: plan_unit_action() per-unit 1-ply lookahead
provides:
  - plan_full_turn() multi-ordering turn planner
  - run_turn_ordering() single-ordering helper
  - Shared turn planning for ai_take_turn and ai_plan_turn
affects: [101-ranged-tactical]

tech-stack:
  added: []
  patterns: [rotation-based multi-ordering for implicit coordination]

key-files:
  modified: [norrust_core/src/ai.rs]

key-decisions:
  - "Rotation-based ordering instead of random shuffle — deterministic, no RNG needed"
  - "Leader always acts first regardless of ordering — preserves discipline"
  - "ai_take_turn replays best plan on real state via ActionRecord replay"

patterns-established:
  - "Multi-ordering: try K rotations of unit list, pick ordering with best final evaluate_state"

duration: ~15min
completed: 2026-03-10
---

# Phase 100 Plan 01: Turn Planning Summary

**Added multi-ordering turn planner: tries 5 rotations of non-leader unit order per turn, picks the ordering producing the best final board evaluation.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-10 |
| Tasks | 2 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: AI tries multiple unit orderings | Pass | TURN_PLAN_ORDERINGS=5, rotation-based |
| AC-2: Better coordination via ordering | Pass | test_turn_planner_multiple_orderings verifies score >= baseline |
| AC-3: Existing behavior preserved | Pass | 139 tests pass, AI vs AI terminates |
| AC-4: Both functions use turn planner | Pass | Both call plan_full_turn |

## Accomplishments

- Created `plan_full_turn()` that tries K=5 unit orderings and picks the best
- Extracted `run_turn_ordering()` as reusable single-ordering helper
- `ai_take_turn` now replays best plan via ActionRecord replay (cleaner than inline mutation)
- 2 new turn planner tests

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added plan_full_turn, run_turn_ordering, rewrote ai_take_turn/ai_plan_turn, added 2 tests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Rotation-based ordering | Deterministic, no RNG needed, covers diverse orderings | Reproducible results |
| Leader always first | Preserves leader discipline (stay/return logic) | Leader decisions unaffected by ordering |
| ActionRecord replay for ai_take_turn | Cleaner than duplicating mutation logic; same code path as ai_plan_turn | Both functions truly share identical logic |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Balance tests slower (~458s vs ~110s) | Expected with 5x orderings in debug mode; acceptable |

## Next Phase Readiness

**Ready:**
- Turn planner provides coordinated multi-unit planning
- Clean helper functions for future tactical overlays
- ActionRecord replay pattern enables ai_take_turn to share planning logic

**Concerns:**
- Balance tests now take ~8 min in debug mode (5x orderings)

**Blockers:**
- None

---
*Phase: 100-turn-planning, Plan: 01*
*Completed: 2026-03-10*
