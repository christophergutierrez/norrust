---
phase: 97-recruit-discipline
plan: 01
subsystem: ai
tags: [ai, recruitment, leader-discipline, game-ai]

requires: []
provides:
  - Leader discipline (stay on keep, return to keep)
  - Mixed unit type recruitment (round-robin)
  - cheapest_recruit_cost parameter for AI planning
affects: [98-state-evaluation, 99-lookahead, 100-turn-planning]

tech-stack:
  added: []
  patterns: [leader-aware AI planning, round-robin recruitment]

key-files:
  created: []
  modified: [norrust_core/src/ai.rs, norrust_core/src/ffi.rs, norrust_core/tests/simulation.rs, norrust_core/tests/balance.rs]

key-decisions:
  - "Used faction index into e.factions Vec for cheapest cost lookup (not string-based)"
  - "Round-robin recruitment by least-recruited count with rotation index for tie-breaking"
  - "cheapest_recruit_cost computed in FFI layer, passed as u32 to pure Rust AI functions"

patterns-established:
  - "Leader identification: unit.abilities.contains('leader')"
  - "Keep/castle topology helpers reusable for future AI phases"

duration: ~30min
completed: 2026-03-10
---

# Phase 97 Plan 01: Recruit Discipline Summary

**AI leader stays on keep to finish recruiting, returns when off-keep with gold, and recruits a mix of unit types via round-robin selection.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-10 |
| Tasks | 3 completed |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Leader stays on keep until castle slots full | Pass | `should_leader_stay` skips leader in unit loop; verified by `test_leader_stays_on_keep_when_can_recruit` |
| AC-2: Leader returns to keep when off-keep with gold | Pass | `leader_should_return_to_keep` redirects leader toward keep; verified by `test_leader_moves_to_keep_when_off_keep` |
| AC-3: Mixed unit type recruitment | Pass | Round-robin by recruited_counts in `norrust_ai_recruit`; deterministic tie-breaking via rotation_idx |

## Accomplishments

- Added 6 leader discipline helpers to ai.rs: `find_leader`, `find_keep_hexes`, `find_faction_keep`, `has_empty_castle_slots`, `should_leader_stay`, `leader_should_return_to_keep`
- Modified `ai_take_turn` and `ai_plan_turn` to accept `cheapest_recruit_cost: u32` parameter for leader decision-making
- Replaced most-expensive recruitment with round-robin selection that prefers least-recruited unit types
- Added `cheapest_recruit_cost_ref` FFI helper to compute cheapest cost from faction's recruit list and unit registry
- 3 new tests: leader stays, leader returns, leader fights when broke
- All 128 tests pass, no new clippy warnings

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Leader discipline helpers, modified signatures for `ai_take_turn`/`ai_plan_turn` |
| `norrust_core/src/ffi.rs` | Modified | `cheapest_recruit_cost_ref` helper, updated FFI wrappers, round-robin recruitment |
| `norrust_core/tests/simulation.rs` | Modified | Updated `ai_take_turn` calls with new signature |
| `norrust_core/tests/balance.rs` | Modified | Updated `ai_take_turn` call with new signature |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Compute cheapest cost in FFI layer | AI functions stay pure (no registry access), FFI has access to engine with factions and unit defs | Clean separation maintained |
| Use `e.factions[faction_idx]` for lookup | Factions loaded in order; simpler than string-based lookup from GameState | Works for 2-faction games |
| Round-robin not RNG | Plan specified deterministic behavior; round-robin with rotation index achieves variety without randomness | Reproducible AI behavior |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential — test callers needed signature update |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Minimal — one expected cascading change from signature modification.

### Auto-fixed Issues

**1. Integration test callers needed update**
- **Found during:** Task 2 (FFI updates)
- **Issue:** `tests/simulation.rs` and `tests/balance.rs` called `ai_take_turn` with old 2-arg signature
- **Fix:** Added `u32::MAX` as third argument (no recruitment info needed in these tests)
- **Files:** `tests/simulation.rs`, `tests/balance.rs`
- **Verification:** All 128 tests pass

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- Leader discipline foundation in place for state evaluation to build on
- Keep/castle topology helpers reusable in Phase 98
- `cheapest_recruit_cost` parameter pattern established for AI function signatures

**Concerns:**
- Faction lookup by Vec index assumes factions loaded in consistent order (fine for 2-faction games)

**Blockers:**
- None

---
*Phase: 97-recruit-discipline, Plan: 01*
*Completed: 2026-03-10*
