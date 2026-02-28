---
phase: 03-presentation-layer
plan: 02
subsystem: presentation
tags: [redot, tilemap, hex, gdscript, mouse-input]

# Dependency graph
requires:
  - phase: 03-presentation-layer
    provides: GDExtension bridge with GameState API (03-01)
provides:
  - game_scene.tscn: main Redot scene (Node2D + game.gd)
  - game.gd: TileMap hex grid drawn from Rust state, mouse → hex logging
  - project.godot: main scene updated to game_scene.tscn

affects: [03-03-unit-display-action-dispatch]

# Tech stack
tech-stack:
  added: []
  patterns:
    - TileMap created entirely in GDScript (_ready) — no editor TileSet serialisation
    - Image.create() + fill() + ImageTexture.create_from_image() for solid-colour tiles
    - TILE_SHAPE_HEXAGON + TILE_OFFSET_AXIS_VERTICAL + TILE_LAYOUT_STACKED = pointy-top odd-r
    - map_to_local() for screen positioning; local_to_map() for click → hex conversion
    - TileMap.position offset (not Camera2D) to centre the board

key-files:
  created:
    - norrust_client/scenes/game_scene.tscn
    - norrust_client/scripts/game.gd
  modified:
    - norrust_client/project.godot

key-decisions:
  - "TileMap fully in code: avoids manual .tscn TileSet serialisation, stays editor-agnostic"
  - "Solid-colour ImageTexture tiles: no art assets needed for Phase 3"
  - "TileMap.position offset instead of Camera2D: simplest centering for a fixed-size board"
  - "(col+row)%2 terrain pattern: readable checkerboard that exercises both terrain colours"

# Metrics
duration: ~10min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 3 Plan 02: Hex TileMap + Map Rendering Summary

**5×5 hex TileMap rendered in Redot from Rust state — pointy-top hexes with two terrain
colours, centred on screen. Mouse click → "Clicked hex: (col, row)" confirmed by human
verification.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Completed | 2026-02-27 |
| Tasks | 2 auto + 1 checkpoint |
| Files created | 2 (game_scene.tscn, game.gd) |
| Files modified | 1 (project.godot) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Hex Grid Visible | Pass | 5×5 grid, two terrain colours, pointy-top layout, human-verified |
| AC-2: Mouse Click Logs Hex Offset | Pass | "Clicked hex: (col, row)" prints correctly |
| AC-3: Coordinate System Matches Rust | Pass | (0,0) = top-left, (1,0) = one right on row 0, human-verified |

## Accomplishments

- `game_scene.tscn`: minimal Node2D scene, wires `game.gd`
- `game.gd`:
  - `_setup_rust_core()`: loads data, calls `create_game()`, sets 25 hex terrains
  - `_setup_tilemap()`: creates TileSet + two atlas sources (grassland, forest) in code
  - `_draw_map()`: renders 5×5 board via `set_cell()`
  - `_center_camera()`: offsets TileMap.position using `map_to_local()` bounding box
  - `_input()`: left click → `local_to_map()` → prints hex offset
- `project.godot`: main scene switched to `game_scene.tscn`

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| TileMap in GDScript code | Avoids writing TileSet resource in .tscn manually | Clean, editor-agnostic |
| Solid-colour ImageTexture | No art assets needed; Redot clips square to hex shape | Fast, placeholder-ready |
| `TileMap.position` offset for centering | Simpler than Camera2D for a fixed board | Fine for Phase 3; Camera2D in Phase 4 if needed |
| `(col+row)%2` terrain pattern | Visually distinct without needing real map data | Temporary; Plan 03-03 queries Rust board directly |

## Deviations from Plan

None. Implemented exactly as specified. Human checkpoint approved first attempt.

## Next Phase Readiness

**Ready for Plan 03-03:** Unit display + action dispatch.

The hex grid coordinate bridge is proven:
- Redot TileMap `Vector2i(col, row)` ↔ Rust `Hex::from_offset(col, row)` confirmed working
- GDScript can call all 10 bridge methods (verified via create_game + set_terrain_at)
- Mouse → hex coordinate conversion works correctly

Plan 03-03 will add:
- Unit labels/nodes placed at hex positions from `get_unit_positions()`
- Click-to-select a unit, highlight reachable hexes from `get_reachable_hexes()`
- Click-to-move, click-to-attack, End Turn button → action dispatch round-trip

---
*Phase: 03-presentation-layer, Plan: 02*
*Completed: 2026-02-27*
