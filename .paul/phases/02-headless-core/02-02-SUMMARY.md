---
phase: 02-headless-core
plan: 02
subsystem: core
tags: [game-state, unit, action, dispatcher, state-management]

# Dependency graph
requires:
  - phase: 02-headless-core
    provides: Hex cubic coordinates, Board boundary validation (Plan 02-01)
provides:
  - Unit runtime instance struct
  - GameState snapshot (board, units, positions, turn, faction)
  - Action enum (Move, Attack, EndTurn)
  - ActionError enum
  - apply_action() validated state dispatcher

affects: [02-03-pathfinding, 02-04-combat, 02-05-simulation]

# Tech stack
tech-stack:
  added: [std::collections::HashMap]
  patterns:
    - Instance/blueprint separation: Unit (runtime) linked to UnitDef (registry) by def_id string
    - apply_action mutates &mut GameState in place — zero-copy, returns Result<(), ActionError>
    - Attack handler stubbed — deferred to Plan 02-04

key-files:
  created:
    - norrust_core/src/unit.rs
    - norrust_core/src/game_state.rs
  modified:
    - norrust_core/src/lib.rs

key-decisions:
  - "Unit instance vs UnitDef blueprint: GameState owns Unit (runtime HP/flags), def_id links to registry at lookup time"
  - "&mut GameState in place (not clone-and-return) for apply_action"

patterns-established:
  - "State changes flow exclusively through apply_action — no direct field mutation outside this function"
  - "ActionError variants are specific (DestinationOutOfBounds, NotYourTurn, etc.) not generic"

# Metrics
duration: ~15min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 2 Plan 02: GameState + Action Dispatcher Summary

**`Unit` instance struct, `GameState` snapshot, `Action`/`ActionError` enums, and `apply_action` dispatcher — 19 tests passing, clippy clean.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Completed | 2026-02-27 |
| Tasks | 1 completed |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: GameState Construction | Pass | `place_unit` stores unit and position; retrievable by id |
| AC-2: Valid Move Updates Position | Pass | Position updated to destination, `moved = true` |
| AC-3: Invalid Move Returns Error | Pass | `Err(DestinationOutOfBounds)`, position unchanged |

## Accomplishments

- `unit.rs`: `Unit` struct with `new()` constructor — id, def_id, hp, faction, moved, attacked
- `game_state.rs`: `GameState::new()`, `place_unit()`, `apply_action()` with full Move validation + EndTurn logic
- `Action::Attack` stubbed cleanly (returns `Ok(())`) — no panic, awaits Plan 02-04
- 19/19 tests pass; `cargo clippy -- -D warnings` exits 0

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/unit.rs` | Created | Runtime unit instance: id, def_id, hp, faction, flags |
| `norrust_core/src/game_state.rs` | Created | GameState, Action, ActionError, apply_action dispatcher |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod game_state;` and `pub mod unit;` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `Unit` holds runtime data only; `def_id: String` links to `UnitDef` | Avoids cloning registry data into every game state; lookup happens at combat resolution | Plan 02-04 fetches UnitDef by def_id when resolving attacks |
| `apply_action` takes `&mut GameState` (mutate in place) | Zero-copy, simpler Rust API; no need to clone full state on each action | All callers hold a `&mut GameState` reference; matches expected usage in tests and simulation |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- `GameState` + `apply_action` is the stable interface all Phase 2 systems write to
- Move validation (bounds, occupancy, faction, already-moved) fully exercised
- EndTurn resets per-turn flags and advances faction/turn counter

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 02-headless-core, Plan: 02*
*Completed: 2026-02-27*
