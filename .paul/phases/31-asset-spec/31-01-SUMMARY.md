---
phase: 31-asset-spec
plan: 01
subsystem: ui
tags: [love2d, assets, sprites, terrain, lua]

requires:
  - phase: 30-campaign-chain
    provides: Stable Love2D client with hex rendering and unit circles

provides:
  - Asset format specification document (docs/ASSET-SPEC.md)
  - Asset loader module (norrust_love/assets.lua)
  - Fallback-aware rendering in main.lua

affects: [32-terrain-art, 33-unit-sprite-pipeline, 34-asset-viewer, 35-unit-art-expansion]

tech-stack:
  added: []
  patterns: [asset loader with fallback, terrain_id map alongside tile_colors]

key-files:
  created: [docs/ASSET-SPEC.md, norrust_love/assets.lua]
  modified: [norrust_love/main.lua]

key-decisions:
  - "hex_polygon function passed to assets.draw_terrain_hex as callback (avoids circular dependency)"
  - "FACTION_COLORS lookup table keyed by faction integer for sprite underlay"
  - "HP/XP/advancement ring always drawn on top regardless of sprite vs fallback"

patterns-established:
  - "Asset fallback pattern: try sprite, return false, caller draws legacy rendering"
  - "Terrain tile rendering: assets.draw_terrain_hex() with polygon callback fallback"
  - "tile_ids map built alongside tile_colors in love.draw() for terrain_id lookup"

duration: ~15min
completed: 2026-03-03
---

# Phase 31 Plan 01: Asset Specification & Infrastructure Summary

**Asset format specification (7 sections, 301 lines) + Love2D asset loader with terrain/unit sprite loading and full fallback to existing colored polygon/circle rendering.**

## Performance

| Metric | Value |
|--------|-------|
| Tasks | 4 completed (3 auto + 1 checkpoint) |
| Files created | 2 (docs/ASSET-SPEC.md, norrust_love/assets.lua) |
| Files modified | 1 (norrust_love/main.lua) |
| Lines added | ~424 (301 spec + 123 loader) |
| Rust tests | 94 passing (unchanged) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Asset Specification Document | Pass | 7 sections covering directory layout, terrain format, sprite.toml schema, team coloring, animation states, naming conventions, pipeline workflow |
| AC-2: Terrain Tile Loading with Fallback | Pass | assets.draw_terrain_hex() renders PNG when present, colored polygon when absent |
| AC-3: Unit Sprite Loading with Fallback | Pass | assets.draw_unit_sprite() renders sprite+underlay when present, returns false for circle fallback |
| AC-4: Game Runs Identically Without Assets | Pass | Human-verified — all scenarios and campaign playable, no errors, identical rendering |

## Accomplishments

- Comprehensive asset specification covering all conventions needed for Phase 32-35 art production
- Asset loader module with graceful fallback at every level (terrain, unit, portrait)
- Zero visual regression — game renders identically without any asset files
- Clean integration into main.lua with minimal changes to existing rendering code

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `docs/ASSET-SPEC.md` | Created | 7-section asset format specification (301 lines) |
| `norrust_love/assets.lua` | Created | Asset loader module: load_terrain_tiles, load_unit_sprites, draw_terrain_hex, draw_unit_sprite (123 lines) |
| `norrust_love/main.lua` | Modified | Added require("assets"), asset loading in love.load(), terrain/unit rendering wired through assets module |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Pass hex_polygon as callback to draw_terrain_hex | assets.lua shouldn't duplicate hex geometry; main.lua owns hex_polygon() | Clean separation; assets.lua has no hex math dependency |
| FACTION_COLORS table keyed by integer | Matches faction numbering (0=blue, 1=red); reusable for sprite underlay | Consistent with existing BLUE/RED constants |
| HP/XP always drawn on top of sprites | Players need to see stats regardless of art quality | HUD elements remain visible even with sprites |
| Terrain images scaled to hex diameter (not clipped) | Simpler implementation; hex clipping deferred to Phase 32 | Rectangular images may show outside hex edges; acceptable for now |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Asset loader infrastructure in place — Phase 32 can drop terrain PNGs into assets/terrain/ and they render immediately
- sprite.toml schema defined — Phase 33 has clear metadata format for unit sprites
- Fallback rendering ensures game stays playable throughout art production

**Concerns:**
- Terrain images are currently drawn as rectangles (not hex-clipped) — Phase 32 should add hex masking via stencil or pre-masked PNGs

**Blockers:**
None.

---
*Phase: 31-asset-spec, Plan: 01*
*Completed: 2026-03-03*
