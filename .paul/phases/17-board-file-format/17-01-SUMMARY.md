---
phase: 17-board-file-format
plan: 01
subsystem: scenario
tags: [toml, board, scenario, gdextension, serde]

requires:
  - phase: 16-terrain-presentation
    provides: Tile.color chain stable; TerrainDef registry used to upgrade tiles

provides:
  - BoardDef serde struct for TOML board files
  - scenario::load_board() pure Rust function
  - scenarios/contested.toml — first hand-authored 8×5 scenario
  - load_board(path, seed) GDExtension bridge method
  - 55 passing tests (46 lib + 9 integration)

affects: [18-unit-placement-wiring]

tech-stack:
  added: []
  patterns: [scenario module for file-driven game setup; load_board mirrors generate_map borrow pattern]

key-files:
  created:
    - norrust_core/src/scenario.rs
    - scenarios/contested.toml
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/lib.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/tests/simulation.rs

key-decisions:
  - "scenario.rs is the home for both load_board() and future load_units(); one module for scenario I/O"
  - "load_board(path, seed) replaces create_game() + generate_map() in one call for scenario-based play"
  - "tiles are row-major (left→right, top→bottom) — consistent with natural reading order"
  - "AC-4 unit test lives in scenario.rs (uses temp file); integration test focuses on the real file"

patterns-established:
  - "load_board() pure Rust → bridge method upgrades tiles from registry: same two-layer pattern as mapgen"
  - "collect-then-apply borrow pattern for disjoint field borrowing in GDExtension bridge"

duration: ~15min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 17 Plan 01: Board File Format Summary

**BoardDef TOML schema + scenario::load_board() pure Rust function + scenarios/contested.toml + load_board() GDExtension bridge; 55 tests pass.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Tasks | 2 completed |
| Files modified | 6 |
| Tests before | 53 |
| Tests after | 55 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Board loads with correct dimensions | Pass | width=8, height=5 verified in test_load_board_from_file |
| AC-2: All hexes have terrain | Pass | All 40 hexes verified in integration test |
| AC-3: Spawn zones are flat | Pass | Cols 0,1,6,7 all flat — verified by test |
| AC-4: Invalid tile count returns Err | Pass | Unit test in scenario.rs using temp file; error contains "tiles.len()" |
| AC-5: Bridge creates a playable GameState | Pass | load_board() bridge compiles; tiles upgraded from TerrainDef registry |

## Accomplishments

- `BoardDef` struct added to `schema.rs` — TOML board files with `width`, `height`, `tiles` (flat row-major Vec<String>)
- `scenario::load_board(path) -> Result<Board, String>` — pure Rust, no registry, no bridge; validates tile count, iterates row-major, calls `board.set_terrain()`
- `scenarios/contested.toml` — 8×5 hand-authored map: flat spawn zones, forest edges, contested interior with hills/mountains, two villages
- `load_board(path, seed)` GDExtension bridge — creates `GameState::new_seeded()`, then upgrades all tiles from TerrainDef registry using established collect-then-apply pattern

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/scenario.rs` | Created | load_board() pure function + AC-4 unit test |
| `scenarios/contested.toml` | Created | First hand-authored 8×5 board |
| `norrust_core/src/schema.rs` | Modified | Added BoardDef struct |
| `norrust_core/src/lib.rs` | Modified | Added pub mod scenario |
| `norrust_core/src/gdext_node.rs` | Modified | Added load_board() bridge method |
| `norrust_core/tests/simulation.rs` | Modified | Added test_load_board_from_file integration test |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Tiles are row-major (left→right, top→bottom) | Natural reading order; consistent with how map editors work | Phase 18 load_units() follows same convention |
| `load_board()` creates `GameState` (replaces `create_game()` + `generate_map()`) | Board dimensions come from the file; caller shouldn't need to know them in advance | GDScript startup becomes load_data → load_board → load_units |
| AC-4 unit test in scenario.rs using temp file | Integration test only runs from repo root; unit test is self-contained | Clean separation of test types |
| `scenario.rs` module (not in loader.rs) | Scenario I/O is conceptually distinct from registry loading; will hold load_units() in Phase 18 | Phase 18 adds load_units() to same module |

## Deviations from Plan

None. Plan executed exactly as written. The borrow pattern for the bridge method matched the established `generate_map()` pattern without issues.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- `load_board()` bridge is stable and callable from GDScript
- `scenarios/contested.toml` exists and loads correctly
- `scenario.rs` module is the natural home for Phase 18's `load_units()`

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 17-board-file-format, Plan: 01*
*Completed: 2026-03-01*
