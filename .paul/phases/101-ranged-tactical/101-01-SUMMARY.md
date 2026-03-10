---
phase: 101-ranged-tactical
plan: 01
subsystem: ai
tags: [tactical-ai, ranged-preference, focus-fire, wounded-retreat, healing]

requires:
  - phase: 99-lookahead
    provides: plan_unit_action() per-unit 1-ply lookahead
  - phase: 100-turn-planning
    provides: plan_full_turn() multi-ordering turn planner
provides:
  - Ranged distance bonus (+2.0 for distance-2 attacks)
  - Focus fire bonus (up to +5.0 for wounded enemies)
  - Wounded unit retreat toward healing terrain
  - retreat_toward_healing() helper function
affects: []

tech-stack:
  added: []
  patterns: [tactical scoring bonuses as tie-breakers on top of evaluate_state]

key-files:
  modified: [norrust_core/src/ai.rs]

key-decisions:
  - "Tactical bonuses are additive tie-breakers, not dominant factors — keeps evaluate_state as primary driver"
  - "Enemy HP ratio captured before simulation to handle dead-after-combat case"
  - "retreat_toward_healing extracted as standalone helper for reuse in both no-attack and has-attack-but-no-kill paths"
  - "Wounded retreat overrides attack decision only when no kill is possible — securing kills always takes priority"

patterns-established:
  - "Tactical bonuses: small score additions after evaluate_state, before best_score comparison"
  - "Retreat logic: RETREAT_HP_RATIO constant, check for kill possibility before retreating"

duration: ~15min
completed: 2026-03-10
---

# Phase 101 Plan 01: Ranged & Tactical Behavior Summary

**Added three tactical behaviors to AI unit decision-making: ranged distance preference, focus fire on wounded enemies, and wounded unit retreat toward healing terrain.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-10 |
| Tasks | 3 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Ranged units prefer distance over adjacent | Pass | +2.0 bonus for distance-2 ranged attacks; test_ranged_prefers_distance verifies |
| AC-2: Focus fire on wounded enemies | Pass | (1.0 - hp_ratio) * 5.0 bonus; test_focus_fire_wounded verifies |
| AC-3: Wounded units retreat toward healing | Pass | RETREAT_HP_RATIO=0.30, retreat_toward_healing helper; test_wounded_retreats_to_village verifies |
| AC-4: Existing behavior preserved | Pass | 101 unit tests pass, AI vs AI terminates, no new clippy warnings |

## Accomplishments

- Added ranged distance bonus (+2.0) steering ranged units to attack from distance 2 (avoiding melee retaliation)
- Added focus fire bonus (up to +5.0) encouraging AI to finish wounded enemies rather than spreading damage
- Created `retreat_toward_healing()` helper that finds nearest healing hex and routes wounded units there
- Wounded units (< 30% HP) retreat when no kill is available, but still attack for guaranteed kills
- 4 new tests validating all three tactical behaviors

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added tactical scoring bonuses, retreat_toward_healing helper, RETREAT_HP_RATIO constant, 4 new tests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Bonuses are small tie-breakers (+2.0, +5.0 max) | evaluate_state already captures HP/unit advantage; bonuses just steer toward tactically better choices among similar-score options | AI behavior improves without breaking existing balance |
| Capture enemy HP before simulation | Enemy may die during simulated combat, making post-sim HP check impossible | Correct focus fire scoring |
| Retreat overrides attack only when no kill possible | Securing a kill is always worth the risk for a wounded unit | Prevents passive behavior when kills are available |
| Iterate board dimensions for healing hex discovery | Board.tiles is private, no public iterator; from_offset(col, row) covers all hexes | Simple, correct approach |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Tile struct not imported in test module | Added `Tile` to existing `use crate::board::{Board, Tile}` import |

## Next Phase Readiness

**Ready:**
- All 5 phases of v3.5 AI Overhaul milestone complete
- AI now has: recruit discipline, holistic state evaluation, 1-ply lookahead, multi-ordering turn planning, and tactical behaviors
- 101 unit tests + 42 integration tests all passing

**Concerns:**
- Balance tests take ~8 min in debug mode due to 5x orderings (from Phase 100)
- Retreat logic iterates all board hexes for healing — acceptable for current board sizes

**Blockers:**
- None

---
*Phase: 101-ranged-tactical, Plan: 01*
*Completed: 2026-03-10*
