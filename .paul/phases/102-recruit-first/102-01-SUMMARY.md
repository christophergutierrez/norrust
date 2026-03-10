---
phase: 102-recruit-first
plan: 01
subsystem: ai
tags: [recruitment, turn-planning, leader-discipline, simulate-recruit]

requires:
  - phase: 97-recruit-discipline
    provides: should_leader_stay, leader_should_return_to_keep, ai_recruit round-robin
  - phase: 100-turn-planning
    provides: plan_full_turn, run_turn_ordering, K=5 orderings
provides:
  - simulate_recruitment() for planning clone
  - recruit_defs parameter threading through turn planner
  - build_recruit_defs() FFI helper for real unit data
affects: [103-leader-2ply-lookahead]

tech-stack:
  added: []
  patterns: [simulate-before-plan, placeholder-unit-for-planning]

key-files:
  created: []
  modified: [norrust_core/src/ai.rs, norrust_core/src/ffi.rs]

key-decisions:
  - "Placeholder units use hp=20, damage=5, strikes=2 — just enough for scoring"
  - "Recruited IDs skipped during replay (real recruitment via FFI unchanged)"
  - "recruit_defs as (cost, movement) tuples — avoids registry access in ai.rs"

patterns-established:
  - "simulate_recruitment pattern: clone state, create placeholders, plan with them, discard"
  - "build_recruit_defs extracts real unit data at FFI boundary for planner consumption"

duration: ~25min
started: 2026-03-10
completed: 2026-03-10
---

# Phase 102 Plan 01: Recruit-First Ordering Summary

**AI turn planner now simulates all affordable recruitment before movement planning, so recruited units participate in tactical decisions and the leader naturally stays on keep while gold remains.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~25min |
| Tasks | 3 completed |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Recruited units participate in turn planning | Pass | simulate_recruitment creates placeholders in clone; they're appended to unit ordering |
| AC-2: Leader stays on keep while recruiting | Pass | test_recruit_first_leader_stays verifies no Move action for leader |
| AC-3: All affordable recruitment before movement | Pass | simulate_recruitment loops until gold < cheapest or no castle slots |
| AC-4: Existing behavior preserved | Pass | 104 unit tests pass, AI vs AI terminates, clippy clean |

## Accomplishments

- `simulate_recruitment()` creates placeholder units in the planning clone so the planner evaluates boards with recruits present
- `build_recruit_defs()` in ffi.rs extracts real (cost, movement) from faction registry — clean boundary between engine and AI
- Old `ai_take_turn`/`ai_plan_turn` preserved as wrappers passing `&[]` for backward compatibility

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added simulate_recruitment, recruit_defs threading, _with_recruits variants, 3 tests |
| `norrust_core/src/ffi.rs` | Modified | Added build_recruit_defs, wired FFI functions to _with_recruits |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Placeholder units (not full UnitDef copies) | ai.rs has no registry access; only need cost+movement for planning | Clean module boundary preserved |
| Skip simulated recruit IDs during replay | Real recruitment happens via FFI; planner recruits are planning-only | Avoids double-recruiting |
| Round-robin recruit selection in sim matches FFI | Consistency between simulated and actual recruitment | Planning accuracy |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essential fixes, no scope creep |
| Deferred | 0 | - |

### Auto-fixed Issues

**1. Test setup: Castle hexes not neighbors of keep**
- **Found during:** Task 3 (tests)
- **Issue:** Custom board placed castles at positions not hex-adjacent to keep
- **Fix:** Switched to existing `setup_keep_board` helper which uses `hex.neighbors()`
- **Verification:** All 3 tests pass

**2. Duplicate make_leader helper**
- **Found during:** Task 3 (tests)
- **Issue:** New make_leader(id, faction, hp) conflicted with existing make_leader(id, faction)
- **Fix:** Removed duplicate, used existing helper
- **Verification:** Compilation succeeds

**3. Replay crashes on simulated recruit IDs**
- **Found during:** Task 2 (FFI wiring)
- **Issue:** ai_take_turn_with_recruits replays Move actions for units that don't exist in real state
- **Fix:** Added `if !state.units.contains_key(unit_id) { continue; }` guard
- **Verification:** AI vs AI test passes

## Issues Encountered

None beyond auto-fixed items above.

## Next Phase Readiness

**Ready:**
- simulate_recruitment pattern established — Phase 103 can extend to 2-ply by running it twice
- recruit_defs threading complete — all callers pass real data
- 104 unit tests provide safety net for Phase 103 changes

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 102-recruit-first, Plan: 01*
*Completed: 2026-03-10*
