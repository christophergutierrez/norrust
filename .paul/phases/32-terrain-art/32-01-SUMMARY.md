---
phase: 32-terrain-art
plan: 01
subsystem: ui
tags: [love2d, terrain, art, stencil, procedural]

requires:
  - phase: 31-asset-spec
    provides: Asset loader module (assets.lua) with draw_terrain_hex fallback

provides:
  - 15 terrain tile PNGs (programmatic, 512x512 each)
  - Hex stencil masking for terrain rendering
  - Tile generator tool (generate_tiles.lua)

affects: [33-unit-sprite-pipeline, 34-asset-viewer]

tech-stack:
  added: []
  patterns: [love2d stencil clipping, programmatic tile generation, bit.bxor hash noise]

key-files:
  created: [norrust_love/generate_tiles.lua, norrust_love/assets/terrain/*.png]
  modified: [norrust_love/assets.lua, norrust_love/main.lua]

key-decisions:
  - "Programmatic tiles instead of Nano Banana (MCP tool cannot output binary images)"
  - "Love2D stencil replace/greater for hex clipping (clean approach, no shader needed)"
  - "--generate-tiles CLI flag for regenerating tiles on demand"

patterns-established:
  - "Stencil-based hex clipping: stencil(polygon, replace, 1) → setStencilTest(greater, 0) → draw → clearStencilTest"
  - "Deterministic noise via integer hash (bit.bxor) for reproducible textures"

completed: 2026-03-03
---

# Phase 32 Plan 01: Terrain Art Summary

**15 programmatic terrain tile PNGs with hex stencil masking — colored polygons replaced by textured terrain across all scenarios.**

## Performance

| Metric | Value |
|--------|-------|
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files created | 16 (generate_tiles.lua + 15 PNGs) |
| Files modified | 2 (assets.lua, main.lua) |
| Terrain tiles | 15 (512x512 each, ~6.3 MB total) |
| Rust tests | 94 passing (unchanged) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Hex Stencil Masking | Pass | love.graphics.stencil clips rectangular PNGs to hex boundary |
| AC-2: All 15 Terrain Tiles Generated | Pass | 15 PNGs in assets/terrain/ — one per terrain_id |
| AC-3: Terrain Art Renders In-Game | Pass | Human-verified: textured terrain visible in all scenarios |
| AC-4: Fallback Still Works | Pass | Missing PNGs fall back to colored polygon (Phase 31 behavior) |

## Accomplishments

- Hex stencil masking cleanly clips terrain images to hex boundaries
- 15 distinct terrain textures with pattern variety (grass, trees, peaks, waves, bricks, roofs, etc.)
- Tile generator tool allows re-generation on demand via `love . --generate-tiles`
- Game transformed from solid-color polygons to textured terrain across all scenarios

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/assets.lua` | Modified | Added stencil-based hex clipping to draw_terrain_hex |
| `norrust_love/main.lua` | Modified | Added --generate-tiles CLI flag in love.load() |
| `norrust_love/generate_tiles.lua` | Created | Programmatic terrain tile generator (15 patterns, 512x512) |
| `norrust_love/assets/terrain/*.png` | Created | 15 terrain tile PNGs (~6.3 MB total) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Programmatic tiles instead of AI-generated | Nano Banana MCP tool cannot output binary images; gemini CLI lacks image generation | Tiles are functional but not hand-painted quality; can be replaced with AI art later |
| Love2D stencil for hex clipping | Clean approach using built-in API; no custom shader needed | Works with any rectangular image; no pre-masking required |
| --generate-tiles CLI flag | Allows regenerating all tiles without modifying code | Easy iteration on tile patterns/colors |
| Deterministic integer hash for noise | bit.bxor-based hash produces reproducible textures from seed | Same tiles generated every time; no randomness surprises |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Tool substitution | 1 | Nano Banana → programmatic generation |
| Scope additions | 1 | Added generate_tiles.lua tool + CLI flag |

**Total impact:** Essential adaptation — AI image generation unavailable, programmatic tiles prove the pipeline equally well. Tiles can be replaced with AI art in the future.

### Tool Substitution

**1. Nano Banana unavailable for binary image output**
- **Found during:** Task 2 (terrain tile generation)
- **Issue:** MCP tool `mcp__nana-banana__generate_image` cannot output binary images; gemini CLI lacks image generation commands
- **Fix:** Created `generate_tiles.lua` — programmatic tile generator using Love2D canvas + deterministic noise patterns
- **Files:** norrust_love/generate_tiles.lua, norrust_love/main.lua (CLI flag)
- **Verification:** 15 PNGs generated successfully, render correctly in-game

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Stencil masking pattern proven — unit sprites (Phase 33) can use same approach if needed
- Asset loader pipeline validated end-to-end: PNG → load → render → hex-clip
- Terrain tiles replaceable with higher-quality art at any time (drop-in replacement)

**Concerns:**
- Programmatic tiles are functional but not artistically rich; may want AI-generated replacements eventually
- Tile file sizes are large for programmatic art (~400KB each) — could be optimized

**Blockers:**
None.

---
*Phase: 32-terrain-art, Plan: 01*
*Completed: 2026-03-03*
