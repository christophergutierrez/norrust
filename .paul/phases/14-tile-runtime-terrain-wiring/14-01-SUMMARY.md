---
phase: 14-tile-runtime-terrain-wiring
plan: 01
subsystem: data
tags: [tile, terrain, board, pathfinding, movement-costs]

requires:
  - phase: 13-wesnoth-data-import
    provides: TerrainDef TOMLs for all Wesnoth terrain types (flat, hills, mountains, etc.)

provides:
  - norrust_core/src/board.rs: Tile struct + Board refactored to HashMap<Hex, Tile>
  - board.tile_at(): per-hex autonomous Tile query
  - Terrain ID reconciliation: "grassland"→"flat", "mountain"→"mountains", "water"→"shallow_water"
  - EndTurn healing via tile.healing (healing_map removed)
  - test_terrain_wiring: integration test verifying hills cost 2 MP not fallback 1
affects: [phase-15, phase-16, future-ai, future-map-gen]

tech-stack:
  added: []
  patterns: [Tile/TerrainDef mirrors Unit/UnitDef pattern — per-hex autonomous properties]

key-files:
  modified:
    - norrust_core/src/board.rs
    - norrust_core/src/game_state.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/src/pathfinding.rs
    - norrust_core/src/snapshot.rs
    - norrust_core/src/loader.rs
    - norrust_core/tests/simulation.rs
    - data/units/fighter.toml
    - data/units/archer.toml
    - data/units/hero.toml
    - data/units/ranger.toml
    - norrust_client/scripts/game.gd

key-decisions:
  - "Tile::new() uses default movement_cost=1, defense=40, healing=0 — fallback for tests without registry"
  - "set_terrain_at() bridge: TerrainDef found → Tile::from_def(); not found → Tile::new() fallback"
  - "loader.rs test_terrain_registry_loads updated from 'grassland' to 'flat' (flat.toml has defense=60)"
  - "grassland.toml retained; only board runtime uses 'flat' now"

patterns-established:
  - "Board.tile_at(hex) returns Option<&Tile> — single query for all per-hex properties"
  - "Tile struct mirrors Unit pattern: instantiated from def at set-time, then autonomous"

duration: ~20min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 14 Plan 01: Tile Runtime + Terrain Wiring Summary

**`Tile` struct replaces `HashMap<Hex, String>` on Board; terrain IDs reconciled to Wesnoth vocabulary; movement costs and healing wire correctly through tile properties; 51 tests pass.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Started | 2026-03-01 |
| Completed | 2026-03-01 |
| Tasks | 2 completed |
| Files modified | 12 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Tile Runtime Struct on Board | Pass | `Tile` struct added; `board.tile_at()` returns `Option<&Tile>`; `terrain_at()` backward-compat; `healing_map` removed |
| AC-2: Terrain IDs Reconciled | Pass | Zero "grassland" matches in custom unit TOMLs, tests, game.gd; all board setups use "flat" |
| AC-3: Movement Costs Wire Correctly | Pass | `test_terrain_wiring`: Spearman reaches col 3 (5 MP budget), cannot reach col 4 (6 MP) |
| AC-4: EndTurn Healing via tile.healing | Pass | `state.board.tile_at(hex).map(|t| t.healing).unwrap_or(0)` replaces `healing_for()` |
| AC-5: No Regressions | Pass | 51 tests pass (44 lib + 7 integration) |

## Accomplishments

- `Tile` struct in `board.rs` with `terrain_id`, `movement_cost`, `defense`, `healing` — mirrors `Unit`/`UnitDef` pattern
- `Board` now stores `HashMap<Hex, Tile>`; `tile_at()` exposes per-hex properties; `terrain_at()` preserved for compatibility
- `healing_map` cache eliminated; EndTurn healing reads `tile.healing` directly
- `set_terrain_at()` bridge initialises `Tile::from_def()` when TerrainDef in registry, falls back to `Tile::new()` otherwise
- Terrain IDs reconciled: "grassland"→"flat", "mountain"→"mountains", "water"→"shallow_water" in all 4 custom unit TOMLs, game.gd, and all test files
- `test_terrain_wiring`: headless proof that hills (cost=2) block movement where flat (cost=1) would not

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/board.rs` | Modified | `Tile` struct + `Board` refactor; `tile_at()`, `set_tile()`; removed `set_healing()`/`healing_for()` |
| `norrust_core/src/game_state.rs` | Modified | EndTurn healing: `healing_map` → `tile.healing` |
| `norrust_core/src/gdext_node.rs` | Modified | `set_terrain_at()`: `Tile::from_def()` when TerrainDef found in registry |
| `norrust_core/src/pathfinding.rs` | Modified | Test: "grassland" → "flat" |
| `norrust_core/src/snapshot.rs` | Modified | Test: "grassland" → "flat" |
| `norrust_core/src/loader.rs` | Modified | Test: "grassland" → "flat"; `default_defense` assertion 40 → 60 (flat.toml has 60) |
| `norrust_core/tests/simulation.rs` | Modified | All "grassland" → "flat"; added `test_terrain_wiring` |
| `data/units/fighter.toml` | Modified | Terrain keys: flat/mountains/shallow_water |
| `data/units/archer.toml` | Modified | Terrain keys: flat/mountains/shallow_water |
| `data/units/hero.toml` | Modified | Terrain keys: flat/mountains/shallow_water |
| `data/units/ranger.toml` | Modified | Terrain keys: flat/mountains/shallow_water |
| `norrust_client/scripts/game.gd` | Modified | "grassland" → "flat"; `COLOR_GRASSLAND` → `COLOR_FLAT` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `Tile::new()` defaults: movement_cost=1, defense=40, healing=0 | Sensible open-ground fallback; tests work without registry | Tests that use `set_terrain()` without registry still pass |
| `set_terrain_at()` bridge: Tile::from_def() or Tile::new() fallback | Graceful degradation if terrain ID not in registry (e.g. "village" called before registry loads) | All current GDScript terrain calls work correctly |
| loader.rs test updated to "flat" with defense=60 | flat.toml (generated from Wesnoth) has default_defense=60, not 40 like grassland.toml | Test accurately reflects actual Wesnoth flat terrain values |
| grassland.toml retained | May be referenced by old game saves; no cost to keep | No regression; legacy file preserved |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minor value correction |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** One minor correction; no scope creep.

### Auto-fixed Issues

**1. loader.rs defense assertion value**
- **Found during:** Task 2 verification (reviewing flat.toml values)
- **Issue:** Plan assumed `flat.toml` would have `default_defense=40` (matching grassland.toml); actual value is 60 (Wesnoth "flat" terrain has 60% defense)
- **Fix:** Updated `test_terrain_registry_loads` assertion to `assert_eq!(flat.default_defense, 60)`
- **Files:** `norrust_core/src/loader.rs`
- **Verification:** All 44 lib tests pass

## Issues Encountered

None — plan executed cleanly.

## Next Phase Readiness

**Ready:**
- `Board.tile_at()` available for Phase 15 map generator to query per-hex properties
- Tile struct has `terrain_id`, `movement_cost`, `defense`, `healing` — sufficient for all current use cases
- Movement costs now wire correctly through terrain IDs for all 322 unit types
- Phase 16 can add `color` and `highlight_mode` fields to `Tile` without touching pathfinding or combat

**Concerns:**
- `Tile.defense` is not yet used as combat fallback — `Unit.default_defense` still governs when terrain key absent. Phase 16 or later may want to wire this.
- Village terrain in game.gd is still called "village" — this matches the data/terrain/village.toml ID, so village healing (8 HP) works correctly via `Tile::from_def()`.

**Blockers:** None

---
*Phase: 14-tile-runtime-terrain-wiring, Plan: 01*
*Completed: 2026-03-01*
