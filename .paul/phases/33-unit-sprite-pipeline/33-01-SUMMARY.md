---
phase: 33-unit-sprite-pipeline
plan: 01
subsystem: ui
tags: [love2d, sprites, animation, toml-parser, spearman, programmatic-art]

requires:
  - phase: 32-terrain-art
    provides: Asset loader pipeline (assets.lua), stencil masking pattern, programmatic generation pattern

provides:
  - Programmatic Spearman spritesheets (idle, attack-melee, attack-ranged, defend, death, portrait)
  - Minimal TOML parser for sprite.toml metadata
  - Animation state machine module (frame cycling, facing, per-unit tracking)
  - Animation-aware asset loading and rendering in assets.lua
  - Portrait rendering in unit panel sidebar

affects: [34-asset-viewer, 35-unit-art-expansion]

tech-stack:
  added: []
  patterns: [Love2D Quad-based spritesheet animation, minimal TOML parser, per-unit animation state tracking]

key-files:
  created: [norrust_love/generate_sprites.lua, norrust_love/toml_parser.lua, norrust_love/animation.lua, norrust_love/assets/units/Spearman/sprite.toml, norrust_love/assets/units/Spearman/*.png]
  modified: [norrust_love/assets.lua, norrust_love/main.lua]

key-decisions:
  - "Programmatic sprites via Love2D canvas (same pattern as terrain tiles)"
  - "Minimal TOML parser (~70 lines) for sprite.toml subset — no external deps"
  - "Love2D Quads for spritesheet frames — no anim8 or external animation library"
  - "Animation state stored per unit_id with def_id reference for love.update() lookups"
  - "Facing determined by board column position (right half → face left)"

patterns-established:
  - "Quad-based spritesheet animation: load Image → create Quads per frame → cycle via timer"
  - "Per-unit animation state: unit_anims[uid] = {current, frame, timer, facing, def_id}"
  - "TOML parser: section headers create nested tables, key=value pairs fill current section"
  - "Portrait in sidebar: assets.draw_portrait() returns height used for layout stacking"

completed: 2026-03-04
---

# Phase 33 Plan 01: Unit Sprite Pipeline Summary

**Complete Spearman sprite pipeline — programmatic spritesheets, TOML metadata parser, animation state machine, in-game rendering with facing/flip and portrait sidebar.**

## Performance

| Metric | Value |
|--------|-------|
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files created | 10 (4 Lua modules + sprite.toml + 5 PNGs + portrait) |
| Files modified | 2 (assets.lua, main.lua) |
| Sprite files | 6 (idle, attack-melee, attack-ranged, defend, death, portrait) |
| Rust tests | 94 passing (unchanged) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Spearman Sprites Exist | Pass | 6 PNGs + sprite.toml in assets/units/Spearman/ via --generate-sprites |
| AC-2: Idle Animation Plays In-Game | Pass | Animated idle sprite with faction underlay replaces colored circle |
| AC-3: Unit Facing | Pass | Units on right half face left (negative scale_x flip) |
| AC-4: Portrait in Unit Panel | Pass | Portrait renders above stats in sidebar when Spearman selected |
| AC-5: Fallback Still Works | Pass | Non-Spearman units render as colored circles with abbreviation |

## Accomplishments

- Full sprite pipeline validated end-to-end: generate → metadata → load → animate → render
- Minimal TOML parser handles sprite.toml format (sections, dotted sections, string/number values)
- Animation module with frame cycling, state machine, facing logic — no external dependencies
- Portrait rendering in sidebar with automatic layout adjustment
- Clean fallback: units without sprites still render as colored circles

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/generate_sprites.lua` | Created | Programmatic sprite generator (spearman figure with pose parameters) |
| `norrust_love/toml_parser.lua` | Created | Minimal TOML parser for sprite.toml subset (~70 lines) |
| `norrust_love/animation.lua` | Created | Animation state machine (load_unit_anims, new_state, update, play, get_quad) |
| `norrust_love/assets/units/Spearman/sprite.toml` | Created | Animation metadata (idle/attack/defend/death/portrait definitions) |
| `norrust_love/assets/units/Spearman/idle.png` | Created | 4-frame idle spritesheet (1024x256) |
| `norrust_love/assets/units/Spearman/attack-melee.png` | Created | 6-frame melee attack spritesheet (1536x256) |
| `norrust_love/assets/units/Spearman/attack-ranged.png` | Created | 4-frame ranged attack spritesheet (1024x256) |
| `norrust_love/assets/units/Spearman/defend.png` | Created | 3-frame defend spritesheet (768x256) |
| `norrust_love/assets/units/Spearman/death.png` | Created | 4-frame death spritesheet (1024x256) |
| `norrust_love/assets/units/Spearman/portrait.png` | Created | 256x256 portrait bust |
| `norrust_love/assets.lua` | Modified | Animation-aware loading (sprite.toml → anims), draw_portrait(), updated draw_unit_sprite() |
| `norrust_love/main.lua` | Modified | Animation state tracking, love.update() anim ticks, facing logic, portrait in sidebar |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Programmatic sprites via Love2D canvas | Same pattern as terrain tiles; Nano Banana can't output binary images | Functional sprites; replaceable with AI art later |
| Minimal TOML parser in Lua | No external deps allowed; sprite.toml uses simple subset only | ~70 lines covers sections + key=value; extensible if needed |
| Love2D Quads for frame selection | Built-in API, no external anim8 library needed | Clean integration with love.graphics.draw(img, quad, ...) |
| Per-unit animation state with def_id | love.update() needs to look up anim_data without re-reading game state | O(1) lookup; cleaned up when units die |
| Facing by board column position | Simple heuristic; units face toward center/opponent | Works for all board sizes; can be refined later |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | None |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Plan executed as written. No deviations.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Animation module proven — Phase 34 (Asset Viewer) can reuse animation.lua for preview
- TOML parser ready for any additional sprite.toml files
- Pipeline validated: generate → metadata → load → animate → render
- generate_sprites.lua extensible — add more units to UNITS table for Phase 35

**Concerns:**
- Programmatic sprites are functional but not artistically rich; AI art replacement desirable
- Combat animation triggers (attack/defend/death during gameplay) not yet wired — only idle plays
- Movement/attack animations deferred from Phase 4 still pending

**Blockers:**
None.

---
*Phase: 33-unit-sprite-pipeline, Plan: 01*
*Completed: 2026-03-04*
