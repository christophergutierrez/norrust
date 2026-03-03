---
phase: 28-map-crossing
plan: 01
subsystem: game-logic
tags: [win-conditions, scenario, objective-hex, turn-limit, love2d]

requires:
  - phase: 27-redot-cleanup
    provides: Stable Love2D client with C ABI bridge
provides:
  - Objective hex win condition (reach target hex to win)
  - Turn limit loss condition (defender wins on timeout)
  - LoadedBoard struct returning board + scenario metadata from TOML
  - Scenario selection screen in Love2D client
  - Dynamic board dimensions from state JSON
  - Crossing scenario (16x10 board with preset units)
affects: [29-second-scenario, 30-campaign-chain]

tech-stack:
  added: []
  patterns:
    - "check_winner() method on GameState for headless-testable win conditions"
    - "LoadedBoard return type for scenario metadata propagation"
    - "preset_units flag for scenarios with TOML-defined unit placements"

key-files:
  created:
    - scenarios/crossing.toml
    - scenarios/crossing_units.toml
  modified:
    - norrust_core/src/game_state.rs
    - norrust_core/src/snapshot.rs
    - norrust_core/src/ffi.rs
    - norrust_core/src/scenario.rs
    - norrust_core/src/schema.rs
    - norrust_core/tests/simulation.rs
    - norrust_love/main.lua
    - norrust_love/norrust.lua

key-decisions:
  - "3-tier win check priority: objective hex > turn limit > elimination"
  - "check_winner() as method on GameState (not free function)"
  - "preset_units flag distinguishes scenarios with TOML units from manual setup"

patterns-established:
  - "LoadedBoard struct wraps Board + scenario metadata from TOML parsing"
  - "Scenario metadata (objective, max_turns) in BoardDef with #[serde(default)]"

duration: ~90min
started: 2026-03-03
completed: 2026-03-03
---

# Phase 28 Plan 01: Map Crossing Summary

**Objective hex + turn limit win conditions, 16x10 crossing scenario with preset units, scenario selection screen in Love2D**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90min |
| Started | 2026-03-03 |
| Completed | 2026-03-03 |
| Tasks | 3 completed |
| Files modified | 10 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Objective hex win condition | Pass | test_objective_hex_win passes; unit on objective → faction wins |
| AC-2: Turn limit loss condition | Pass | test_turn_limit_loss passes; turn > max_turns → faction 1 wins |
| AC-3: Elimination preserved | Pass | test_elimination_still_works passes; no objective/limit → elimination logic unchanged |
| AC-4: Large board loads and plays | Pass | 16x10 crossing.toml loads, AI recruits and defends, player can reach keep |
| AC-5: Dynamic board dimensions | Pass | BOARD_COLS/BOARD_ROWS set from state JSON after scenario load |
| AC-6: HUD turn progress + objective | Pass | "Turn X / 30" displayed; objective hex highlighted with gold border |

## Accomplishments

- Extended GameState with `objective_hex` and `max_turns` fields plus `check_winner()` method implementing 3-tier priority: objective hex → turn limit → elimination
- Created `LoadedBoard` struct so `load_board()` propagates scenario metadata (objective, max_turns) from TOML through to GameState
- Built 16x10 crossing scenario with preset units (blue leader vs red leader + 3 defenders) and 30-turn limit
- Added scenario selection screen, dynamic board dimensions, and preset_units flow to Love2D client

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/game_state.rs` | Modified | objective_hex, max_turns fields + check_winner() method |
| `norrust_core/src/snapshot.rs` | Modified | max_turns, objective_col, objective_row in StateSnapshot |
| `norrust_core/src/ffi.rs` | Modified | norrust_set_objective_hex(), norrust_set_max_turns(), updated norrust_get_winner() + norrust_load_board() |
| `norrust_core/src/scenario.rs` | Modified | LoadedBoard return type from load_board() |
| `norrust_core/src/schema.rs` | Modified | objective_col, objective_row, max_turns on BoardDef |
| `norrust_core/tests/simulation.rs` | Modified | 3 new tests (objective_hex_win, turn_limit_loss, elimination_still_works) |
| `norrust_love/main.lua` | Modified | Scenario selection, dynamic board, preset_units flow, objective highlight, HUD |
| `norrust_love/norrust.lua` | Modified | FFI declarations + wrappers for set_objective_hex, set_max_turns |
| `scenarios/crossing.toml` | Created | 16x10 board with keeps, castles, mixed terrain corridor |
| `scenarios/crossing_units.toml` | Created | Blue leader + red leader + 3 red defenders |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 3-tier check_winner() priority order | Objective hex is most specific condition; turn limit is scenario-level; elimination is universal fallback | Future scenarios can mix and match win conditions |
| check_winner() as GameState method | Headless-testable without FFI; direct access to state fields | Integration tests don't need engine setup |
| LoadedBoard struct | Clean return of board + metadata; avoids side-channel state setting | Scenarios self-describe their win conditions |
| preset_units flag on SCENARIOS table | Crossing has TOML-defined units; contested uses manual placement; both paths must work | Future scenarios choose their setup flow |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essential fixes, no scope creep |
| Scope additions | 0 | - |
| Deferred | 0 | - |

**Total impact:** Three bugs found during execution and testing, all fixed inline.

### Auto-fixed Issues

**1. Missing Debug derive on LoadedBoard**
- **Found during:** Task 1 (Rust core)
- **Issue:** `LoadedBoard` needed `#[derive(Debug)]` for test unwrap_err()
- **Fix:** Added derive attribute
- **Files:** `norrust_core/src/scenario.rs`
- **Verification:** `cargo test` passes

**2. SCENARIOS table nil at runtime**
- **Found during:** Task 2 (Love2D client) — user reported main.lua:256 ipairs error
- **Issue:** SCENARIOS local was defined after draw_setup_hud() which referenced it; Lua locals must be defined before use
- **Fix:** Moved SCENARIOS definition to constants section at top of file
- **Files:** `norrust_love/main.lua`
- **Verification:** Game launches without error

**3. Preset scenario required manual leader placement**
- **Found during:** Task 3 (human-verify) — user reported placing leaders manually in crossing
- **Issue:** Crossing scenario has all units in TOML but game forced SETUP_BLUE/SETUP_RED modes; load_units then clobbered manual placements
- **Fix:** Added `preset_units` flag to SCENARIOS table; when true, faction picker skips setup modes and goes directly to PLAYING with TOML units loaded
- **Files:** `norrust_love/main.lua`
- **Verification:** User confirmed crossing plays correctly with preset units

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| LoadedBoard missing Debug | Added #[derive(Debug)] |
| SCENARIOS nil at runtime | Moved definition before first reference |
| Manual setup for preset scenario | Added preset_units flag to skip setup modes |

## Next Phase Readiness

**Ready:**
- Objective hex and turn limit win conditions working — Phase 29 can add new scenarios using same system
- Scenario selection screen supports arbitrary scenario list — adding scenarios requires only a table entry
- preset_units pattern established for scenarios with TOML-defined units
- Dynamic board dimensions work for any size

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 28-map-crossing, Plan: 01*
*Completed: 2026-03-03*
