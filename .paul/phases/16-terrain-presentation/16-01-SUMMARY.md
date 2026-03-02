---
phase: 16-terrain-presentation
plan: 01
subsystem: data+presentation
tags: [terrain, color, snapshot, tilemap, rendering]

requires:
  - phase: 15-map-generator
    provides: generate_map() producing hills/mountains/forest/village — all 4 types now need distinct colors

provides:
  - norrust_core/src/schema.rs: TerrainDef.color field
  - norrust_core/src/board.rs: Tile.color field; Tile::from_def() copies color from def
  - norrust_core/src/snapshot.rs: TileSnapshot.color field; from_game_state() uses tile_at()
  - data/terrain/*.toml: color field in all 14 terrain TOMLs
  - norrust_client/scripts/game.gd: data-driven tile_colors map; hardcoded terrain switch removed
affects: [phase-17+, future-ai-clients]

tech-stack:
  added: []
  patterns: [Color data flows TOML → TerrainDef → Tile → TileSnapshot → JSON → GDScript]

key-files:
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/board.rs
    - norrust_core/src/snapshot.rs
    - norrust_core/src/loader.rs
    - data/terrain/flat.toml
    - data/terrain/grassland.toml
    - data/terrain/forest.toml
    - data/terrain/hills.toml
    - data/terrain/mountains.toml
    - data/terrain/village.toml
    - data/terrain/castle.toml
    - data/terrain/cave.toml
    - data/terrain/frozen.toml
    - data/terrain/fungus.toml
    - data/terrain/reef.toml
    - data/terrain/sand.toml
    - data/terrain/shallow_water.toml
    - data/terrain/swamp_water.toml
    - norrust_client/scripts/game.gd

key-decisions:
  - "Tile::new() default color is '#808080' (grey) — visually signals 'no TOML color assigned' vs empty string which fails Color.html()"
  - "from_game_state() switched from terrain_at() to tile_at() — allows color to flow through without a second board lookup"
  - "GDScript builds tile_colors Dictionary once per _draw() from state['terrain'] — O(40) not O(1) per tile"
  - "COLOR_FLAT kept as fallback constant; COLOR_FOREST and COLOR_VILLAGE removed — fallback only needed for hexes with missing color data"

patterns-established:
  - "Color-as-data: all visual properties defined in TOML, not in GDScript constants"
  - "TileSnapshot as complete rendering source: terrain_id + color — GDScript needs no terrain knowledge"

duration: ~10min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 16 Plan 01: Terrain Presentation Summary

**Color data flows from TOML through Tile/TileSnapshot to GDScript; hills and mountains render distinctly; hardcoded terrain-to-color switch eliminated; 53 tests pass.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Started | 2026-03-01 |
| Completed | 2026-03-01 |
| Tasks | 2 completed |
| Files modified | 19 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: TileSnapshot Exposes Color | Pass | `test_tile_snapshot_includes_color`: color "#4a7c4e" appears in JSON output |
| AC-2: All Active Terrain Types Have Distinct Colors | Pass | flat=#4a7c4e, forest=#2d5927, hills=#8b7355, mountains=#6b6b6b, village=#b89a30 — all unique |
| AC-3: GDScript Uses Data-Driven Colors | Pass | No COLOR_FOREST/COLOR_VILLAGE; no get_terrain_at(); no terrain string comparisons for color |
| AC-4: Hills and Mountains Render Distinctly | Pass | hills=#8b7355 (brown-tan), mountains=#6b6b6b (grey) — both differ from flat=#4a7c4e |
| AC-5: No Regressions | Pass | 53 tests pass (45 lib + 8 integration) |

## Accomplishments

- `TerrainDef.color`: `#[serde(default)]` String — all 14 terrain TOMLs updated with hex color values
- `Tile.color`: copied from `TerrainDef.color` at `from_def()` time; `Tile::new()` defaults to `"#808080"`
- `TileSnapshot.color`: `from_game_state()` switched from `terrain_at()` → `tile_at()` to read full Tile including color
- game.gd: `COLOR_FOREST` and `COLOR_VILLAGE` removed; `tile_colors` Dictionary built from `state["terrain"]` per frame; single `Color.html()` call per tile
- `test_tile_snapshot_includes_color`: unit test verifying color flows from Tile → TileSnapshot → JSON
- loader.rs `test_terrain_registry_loads`: `flat.color == "#4a7c4e"` assertion added

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/schema.rs` | Modified | `TerrainDef.color` field added |
| `norrust_core/src/board.rs` | Modified | `Tile.color`; `new()` + `from_def()` updated |
| `norrust_core/src/snapshot.rs` | Modified | `TileSnapshot.color`; `from_game_state()` uses `tile_at()`; new test |
| `norrust_core/src/loader.rs` | Modified | Color assertion in `test_terrain_registry_loads` |
| `data/terrain/*.toml` (14 files) | Modified | `color = "#RRGGBB"` added to each |
| `norrust_client/scripts/game.gd` | Modified | Data-driven `tile_colors` map; removed `COLOR_FOREST`, `COLOR_VILLAGE`, hardcoded color switch |

## Color Palette

| Terrain | Color | Hex |
|---------|-------|-----|
| flat | Medium green | #4a7c4e |
| grassland | Bright green | #5a8c5e |
| forest | Dark green | #2d5927 |
| hills | Brown-tan | #8b7355 |
| mountains | Grey | #6b6b6b |
| village | Gold-tan | #b89a30 |
| castle | Light stone | #c8b47a |
| cave | Dark grey | #4a4a4a |
| frozen | Ice blue | #a8c8d8 |
| fungus | Dark brown | #6b5c2e |
| reef | Teal | #3d7a8a |
| sand | Sandy yellow | #c8a85a |
| shallow_water | Blue | #4a8aaa |
| swamp_water | Murky green | #5a7a4a |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `Tile::new()` color = "#808080" | Empty string fails `Color.html()`; grey clearly signals "fallback, check TOML" | GDScript `c != ""` guard handles both new() tiles and missing color gracefully |
| Switch `from_game_state()` to `tile_at()` | `terrain_at()` only returns `&str` — can't get color without extra lookup | Cleaner: one call gets full tile data |
| Remove COLOR_FOREST/COLOR_VILLAGE entirely | They were only ever used in the now-deleted terrain switch | Reduces constants to only the meaningful fallback |

## Deviations from Plan

None — plan executed exactly as specified.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- All terrain types are visually distinct — the map is now readable
- Color data is in TOML and flows through to AI clients via `get_state_json()` (TileSnapshot includes color)
- Future terrain types only need a `color` field in their TOML — zero GDScript changes required

**Concerns:**
- `Tile.defense` still not wired as combat fallback — `Unit.default_defense` still governs (deferred since Phase 14)
- Highlight mode for reachable hexes is still GDScript-only (`_reachable_cells`) — Rust has no awareness of selection state

**Blockers:** None

---
*Phase: 16-terrain-presentation, Plan: 01*
*Completed: 2026-03-01*
