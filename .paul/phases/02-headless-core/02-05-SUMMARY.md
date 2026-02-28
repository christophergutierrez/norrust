---
phase: 02-headless-core
plan: 05
subsystem: core
tags: [pathfinding, movement, integration-test, simulation]

# Dependency graph
requires:
  - phase: 02-headless-core
    provides: A* pathfinding + ZOC (02-03), combat resolution (02-04)
provides:
  - Unit.movement: u32 (0 = unconstrained sentinel)
  - Unit.movement_costs: HashMap<String, u32>
  - ActionError::DestinationUnreachable
  - apply_action(Move) wired to find_path when movement > 0
  - tests/simulation.rs: scripted 5×5 headless match integration test

affects: [Phase 3 — Presentation Layer]

# Tech stack
tech-stack:
  added: []
  patterns:
    - movement=0 sentinel preserves backward compatibility for all existing Move tests
    - Integration test uses rlib public API only (no private items)
    - get_zoc_hexes called inside apply_action(Move) to provide ZOC context to find_path

key-files:
  modified:
    - norrust_core/src/unit.rs
    - norrust_core/src/game_state.rs
  created:
    - norrust_core/tests/simulation.rs

key-decisions:
  - "movement=0 sentinel: skip pathfinding entirely — all existing Unit::new() calls unaffected"
  - "find_path wired with default_movement_cost=1 for uncategorised terrain"
  - "is_skirmisher=false — skirmisher flag deferred to future phase"

# Metrics
duration: ~10min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 2 Plan 05: Headless Match Simulation Summary

**Pathfinding wired into `apply_action(Move)`, `DestinationUnreachable` error added, and scripted 5×5 integration test passing — 27 unit tests + 1 integration test, clippy clean. Phase 2 complete.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files modified | 2 (unit, game_state) |
| Files created | 1 (tests/simulation.rs) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Unreachable Destination Returns Error | Pass | movement=2, dest 4 steps away → `Err(DestinationUnreachable)` |
| AC-2: Scripted Scenario Executes Without Error | Pass | Move → Attack → EndTurn all `Ok(())` |
| AC-3: Winner Determined — One Survivor | Pass | `state.units.len() == 1`; unit 1 survives, unit 2 dead |

## Accomplishments

- `unit.rs`: `Unit` gains `movement: u32` (default=0) and `movement_costs: HashMap<String, u32>` (default=empty)
- `game_state.rs`: `ActionError::DestinationUnreachable` added; `apply_action(Move)` wired to `find_path` when `unit.movement > 0`; `test_move_unreachable_returns_error` added
- `tests/simulation.rs`: full integration test — 5×5 grassland board, unit 1 moves + kills unit 2, EndTurn, state verified
- 27 unit tests + 1 integration test all pass; `cargo clippy -- -D warnings` clean

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/unit.rs` | Modified | Added `movement` and `movement_costs` fields with defaults |
| `norrust_core/src/game_state.rs` | Modified | `DestinationUnreachable` variant, pathfinding wire-in, new test |
| `norrust_core/tests/simulation.rs` | Created | Scripted 5×5 headless match integration test |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `movement=0` sentinel for "unconstrained" | All existing `Unit::new()` callers unaffected — no signature change | Zero breakage; clean upgrade path |
| `find_path` called with `default_movement_cost=1` | Reasonable default for terrain with no explicit cost entry | Grassland (cost=1) works correctly in integration test |
| `is_skirmisher=false` hardcoded | Skirmisher flag out of scope for Phase 2 | Deferred; ZOC stop rule applies to all units |

## Deviations from Plan

None. Implemented exactly as specified.

## Next Phase Readiness

**Phase 2 complete.** All 5 plans delivered:
- 02-01: Hex coordinate system
- 02-02: GameState + Action dispatcher
- 02-03: A* pathfinding + ZOC
- 02-04: Combat resolution (RNG, ToD, damage)
- 02-05: Pathfinding wired into Move + headless match simulation

**Ready for Phase 3:** Presentation Layer (Redot TileMap, GDExtension bridge for hex/board/unit types).

**Deferred issues carried forward:**

| Issue | Effort | Revisit |
|-------|--------|---------|
| Defender retaliation | M | Phase 4 |
| Resistance modifiers | S | Phase 4 |
| Skirmisher flag on Unit | S | Phase 4 |
| GDExtension exposure of new types | M | Phase 3 |

---
*Phase: 02-headless-core, Plan: 05*
*Completed: 2026-02-27*
