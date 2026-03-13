---
phase: 122-core-visibility
plan: 01
subsystem: engine
tags: [fog-of-war, visibility, vision-range, hex-distance]

requires:
  - phase: none
    provides: N/A — first phase of v6.0
provides:
  - compute_visibility(state, faction) → HashSet<Hex>
  - vision_range field on UnitDef and Unit
  - Board::tile_hexes() public iterator
affects: [123-ffi-visibility-filtering, 124-draw-layer-fog, 125-ai-fog-integration]

tech-stack:
  added: []
  patterns: [range-based visibility with movement fallback]

key-files:
  created: [norrust_core/src/visibility.rs]
  modified: [norrust_core/src/schema.rs, norrust_core/src/unit.rs, norrust_core/src/board.rs, norrust_core/src/combat.rs, norrust_core/src/lib.rs]

key-decisions:
  - "vision_range=0 means use movement as vision (Wesnoth convention)"
  - "Range-based visibility, not line-of-sight"
  - "Computed on demand, not cached on GameState"
  - "Board::tile_hexes() added to iterate hexes without exposing private tiles HashMap"

patterns-established:
  - "Visibility as pure function: compute_visibility(state, faction) → HashSet<Hex>"

duration: ~10min
completed: 2026-03-13
---

# Phase 122 Plan 01: Core Visibility Calculation Summary

**Range-based per-faction visibility calculation added — vision_range on units, compute_visibility returns HashSet<Hex>.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: vision_range on UnitDef | Pass | `#[serde(default)]` — all existing TOMLs load with 0 |
| AC-2: vision_range on Unit | Pass | Copied in `apply_def()`, defaults to 0 in `Unit::new()` |
| AC-3: compute_visibility returns correct hexes | Pass | 4 tests verify basic, union, and boundary cases |
| AC-4: vision_range 0 falls back to movement | Pass | `test_vision_range_fallback_to_movement` confirms |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/visibility.rs` | Created | `compute_visibility()` + 4 unit tests |
| `norrust_core/src/schema.rs` | Modified | Added `vision_range: u32` to UnitDef |
| `norrust_core/src/unit.rs` | Modified | Added `vision_range: u32` to Unit, copied in `apply_def()` |
| `norrust_core/src/board.rs` | Modified | Added `tile_hexes()` public iterator |
| `norrust_core/src/combat.rs` | Modified | Added `vision_range: 0` to 2 test struct literals |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod visibility;` |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minor — Board.tiles is private |

**Board.tiles private field:** Plan specified iterating `board.tiles.keys()` but `tiles` is private. Added `Board::tile_hexes()` public iterator instead. Cleaner API, no encapsulation break.

## Deferred Items

None.

## Next Phase Readiness

**Ready:**
- `compute_visibility()` available for Phase 123 FFI integration
- `vision_range` field on all units (defaults to movement via 0)

**Concerns:** None

**Blockers:** None

---
*Phase: 122-core-visibility, Plan: 01*
*Completed: 2026-03-13*
