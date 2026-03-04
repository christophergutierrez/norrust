---
phase: 36-terrain-info-panel
plan: 01
subsystem: ui
tags: [terrain, ffi, sidebar-panel, love2d, luajit]

requires:
  - phase: 35-terrain-tile-art
    provides: terrain tile rendering with color data
provides:
  - TileSnapshot with defense/movement_cost/healing fields
  - norrust_get_unit_terrain_info() FFI function
  - draw_terrain_panel() sidebar in Love2D
  - Right-click terrain inspection interaction
affects: [37-ghost-movement, 38-combat-preview]

tech-stack:
  added: []
  patterns: [right-click for terrain inspection, unit-specific FFI queries]

key-files:
  created: []
  modified:
    - norrust_core/src/snapshot.rs
    - norrust_core/src/ffi.rs
    - norrust_love/norrust.lua
    - norrust_love/main.lua

key-decisions:
  - "Right-click for terrain inspection instead of left-click, to avoid conflicting with move/select"
  - "Dedicated FFI function for unit-terrain queries instead of bloating UnitSnapshot"

patterns-established:
  - "Right-click for non-gameplay inspection panels"
  - "Unit-specific terrain queries via separate FFI call rather than per-frame snapshot expansion"

duration: ~30min
completed: 2026-03-04
---

# Phase 36 Plan 01: Terrain Info Panel Summary

**Right-click terrain inspection panel with base stats and unit-specific defense/movement via new FFI function.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-04 |
| Tasks | 3 completed |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: TileSnapshot includes terrain stats | Pass | defense, movement_cost, healing fields added and populated |
| AC-2: Unit-terrain info FFI | Pass | norrust_get_unit_terrain_info() returns effective defense/move cost with fallback chain |
| AC-3: Terrain panel on hex click | Pass | Right-click shows terrain type, defense %, move cost, healing |
| AC-4: Unit-specific terrain info | Pass | With unit selected, right-click shows effective defense/move cost |
| AC-5: Panel priority | Pass | Unit panel (left-click) takes priority; terrain panel (right-click) independent |

## Accomplishments

- Extended TileSnapshot with defense, movement_cost, healing fields — all terrain stats now available in state JSON
- Added norrust_get_unit_terrain_info() FFI function with unit.defense[terrain] → tile.defense fallback chain
- Built draw_terrain_panel() sidebar matching existing unit panel style
- Added 2 new Rust unit tests (96 total, all passing)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/snapshot.rs` | Modified | Added defense/movement_cost/healing to TileSnapshot + 2 new tests |
| `norrust_core/src/ffi.rs` | Modified | Added norrust_get_unit_terrain_info() FFI function |
| `norrust_love/norrust.lua` | Modified | Added FFI declaration + Lua wrapper for unit terrain info |
| `norrust_love/main.lua` | Modified | Added draw_terrain_panel(), right-click handler, inspect_terrain state |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Right-click for terrain inspection | Left-click empty hex triggers movement when unit selected — can't overload | Clean separation: left=gameplay, right=inspection |
| Dedicated FFI function vs UnitSnapshot expansion | Avoids sending per-unit terrain maps every frame | Future phases can reuse get_unit_terrain_info() for combat preview |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential UX fix |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Essential interaction fix, no scope creep.

### Auto-fixed Issues

**1. Click conflict: terrain inspection vs unit movement**
- **Found during:** Task 2 (Lua wiring) + human-verify
- **Issue:** Left-click on empty reachable hex moves the selected unit, preventing terrain inspection
- **Fix:** Changed terrain inspection to right-click, keeping left-click for all gameplay actions
- **Files:** norrust_love/main.lua
- **Verification:** User confirmed right-click terrain panel works correctly

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Left-click terrain inspection conflicted with unit movement | Switched to right-click for terrain inspection |

## Next Phase Readiness

**Ready:**
- Terrain stats visible to players — foundation for tactical decisions
- Unit-specific terrain FFI available for ghost movement and combat preview
- Right-click inspection pattern established for future panels

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 36-terrain-info-panel, Plan: 01*
*Completed: 2026-03-04*
