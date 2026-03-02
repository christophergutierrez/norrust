---
phase: 15-map-generator
plan: 01
subsystem: data
tags: [mapgen, terrain, board, procedural, gdextension]

requires:
  - phase: 14-tile-runtime-terrain-wiring
    provides: Tile struct, set_tile(), terrain_at() — Board API stable for mapgen

provides:
  - norrust_core/src/mapgen.rs: generate_map(board, seed) pure-Rust procedural generator
  - gdext_node.rs: generate_map(seed: i64) -> bool GDExtension bridge
  - game.gd: single _core.generate_map(42) call replaces manual terrain loop
  - test_generate_map: integration test verifying coverage, spawn zones, villages, variety
affects: [phase-16, future-ai]

tech-stack:
  added: []
  patterns: [deterministic XOR hash for terrain noise; pure-Rust generator with no registry coupling]

key-files:
  created:
    - norrust_core/src/mapgen.rs
  modified:
    - norrust_core/src/lib.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/tests/simulation.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "generate_map() is registry-free — sets string IDs only; bridge does the Tile::from_def() upgrade pass"
  - "Village positions are structural: (cols/3, rows/2) and (cols*2/3, rows/2) = (2,2) and (5,2) for 8×5"
  - "Mountains confined to dist_center <= 1 (innermost contested cols) — prevents mountain wall at edge"
  - "Collect-then-apply pattern in bridge: avoids immutable/mutable borrow conflict on state.board"

patterns-established:
  - "Two-phase terrain initialisation: generate_map() sets string IDs; bridge upgrades to Tile::from_def()"
  - "terrain_noise() XOR hash: wrapping_mul Knuth constants + seed; fast, deterministic, no std dependency"

duration: ~10min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 15 Plan 01: Map Generator Summary

**Procedural map generator in pure Rust replaces hardcoded GDScript terrain loop; 52 tests pass.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Started | 2026-03-01 |
| Completed | 2026-03-01 |
| Tasks | 2 completed |
| Files modified | 4 (+ 1 created) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Full Board Coverage | Pass | All 40 hexes return Some(terrain_id) after generate_map() |
| AC-2: Spawn Zones Always Flat | Pass | Cols 0-1 and 6-7 always "flat" — verified by test |
| AC-3: Villages at Structural Positions | Pass | (2,2)="village", (5,2)="village" with seed=42 |
| AC-4: Contested Zone Has Terrain Variety | Pass | ≥2 distinct terrain IDs in contested zone; all from valid set |
| AC-5: GDScript Uses Generator, Not Manual Loop | Pass | `_core.generate_map(42)` only; no set_terrain_at() setup calls |
| AC-6: No Regressions | Pass | 52 tests pass (44 lib + 8 integration) |

## Accomplishments

- `mapgen.rs`: `generate_map(board, seed)` with `terrain_noise()` XOR hash and `contested_terrain()` classifier
- Layout algorithm: outer 2 cols = flat (spawn zones), structural villages at 1/3 and 2/3 columns at mid-row, contested zone noise-based (flat ~43%, forest ~21%, hills ~21%, mountains ~15% center-only)
- `generate_map(seed: i64) -> bool` bridge added to `NorRustCore` — calls generator, then upgrades all tiles from TerrainDef registry using collect-then-apply pattern
- `game.gd`: 7 lines of manual terrain setup replaced with 1 line `_core.generate_map(42)`
- `test_generate_map`: integration test verifying all 4 ACs headlessly (no registry)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/mapgen.rs` | Created | `generate_map()`, `terrain_noise()`, `contested_terrain()` |
| `norrust_core/src/lib.rs` | Modified | `pub mod mapgen;` added alphabetically after loader |
| `norrust_core/src/gdext_node.rs` | Modified | `generate_map(seed: i64) -> bool` bridge method |
| `norrust_core/tests/simulation.rs` | Modified | `HashSet` import; `test_generate_map` integration test |
| `norrust_client/scripts/game.gd` | Modified | Manual terrain loop → `_core.generate_map(42)` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `generate_map()` is registry-free | Keeps function purely headlessly testable; same pattern as `apply_action()` | `test_generate_map` needs no TOML loading |
| Bridge does collect-then-apply for tile upgrade | `state.board.terrain_at()` returns `&str` borrow; `set_tile()` needs `&mut` — collect breaks the conflict | Clean compile with no unsafe |
| Village priority before spawn zone check | Villages at (2,2) and (5,2) are in contested zone cols (2-5); placing village check first ensures correct assignment | Predictable structural positions |
| Mountains confined to dist_center ≤ 1 | Avoids mountain clusters at contested-zone edges that would block movement lanes | Tactically balanced center |

## Deviations from Plan

None — plan executed exactly as specified.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Board now has procedurally generated terrain with tactically meaningful layout
- Spawn zones guaranteed flat for movement; villages at structural positions for healing
- Phase 16 can add `color` and `highlight_mode` to TerrainDef/Tile; generator unchanged
- `generate_map(seed)` bridge in place for future variable-seed support

**Concerns:**
- `Tile.defense` still not wired as combat fallback (deferred from Phase 14) — Phase 16+ work
- Terrain color in `_draw()` only handles flat/forest/village — hills/mountains show as flat-colored (Phase 16 fixes this)

**Blockers:** None

---
*Phase: 15-map-generator, Plan: 01*
*Completed: 2026-03-01*
