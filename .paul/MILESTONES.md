# Milestones

Completed milestone log for this project.

| Milestone | Completed | Duration | Stats |
|-----------|-----------|----------|-------|
| v0.1 Initial Release | 2026-02-27 | ~1 day | 5 phases, 13 plans |
| v0.2 Bridge Unification | 2026-02-28 | ~1 day | 1 phase, 1 plan |
| v0.3 Unit Advancement | 2026-02-28 | ~1 day | 3 phases, 4 plans |
| v0.4 AI Opponent | 2026-02-28 | ~1 day | 2 phases, 2 plans |
| v0.5 Unit Content | 2026-03-01 | ~1 day | 2 phases, 2 plans |
| v0.6 Terrain System | 2026-03-01 | ~1 day | 3 phases, 3 plans |
| v0.7 Scenario System | 2026-03-01 | ~1 day | 2 phases, 2 plans |
| v0.8 Combat Completeness | 2026-03-02 | ~1 day | 1 phase, 1 plan |
| v0.9 Game Mechanics | 2026-03-02 | ~1 day | 2 phases, 3 plans |
| v1.0 Game Readability | 2026-03-02 | ~1 day | 2 phases, 2 plans |
| v1.1 Camera & Viewport | 2026-03-03 | ~1 day | 1 phase, 1 plan |
| v1.2 Love2D Migration | 2026-03-03 | ~1 day | 3 phases, 3 plans |
| v1.3 Campaign Mode | 2026-03-03 | ~1 day | 3 phases, 3 plans |
| v1.4 Visual Asset System | 2026-03-04 | ~1 day | 5 phases, 5 plans |

---

## ✅ v1.4 Visual Asset System

**Completed:** 2026-03-04
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 5 |
| Plans | 5 |
| Files created | ~100 (sprites, tiles, modules) |
| Tests | 94 (59 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Asset format specification** — directory layout, sprite.toml schema, terrain/unit naming conventions, animation states
- **Asset loader module** (assets.lua) — terrain tile + unit sprite loading with graceful fallback
- **15 hex-clipped terrain tiles** — programmatic textures via stencil masking
- **Unit sprite pipeline** — TOML parser, animation module, portrait rendering, facing/flip logic
- **Standalone asset viewer** — browse terrain/unit assets, cycle animations, zoom/flip, metadata display
- **16 unit sprites** — generic humanoid drawing system with 8 weapon types covering all priority units

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Generic draw_humanoid() with config table | Eliminates per-unit draw functions; config-driven |
| melee_config/ranged_config overrides | Dual-weapon units use different weapons per animation |
| Love callback override for --viewer | Cleaner isolation; viewer replaces all love callbacks |
| Programmatic sprites (not image files) | Generated via Love2D canvas; reproducible, tweakable |

---

## ✅ v1.3 Campaign Mode

**Completed:** 2026-03-03
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 94 (59 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Objective hex + turn limit win conditions** — check_winner() with 3-tier priority
- **TriggerZone system** — enemies spawn when player enters designated areas
- **Campaign TOML schema** — scenario sequence, gold carry-over, early finish bonus
- **Veteran carry-over** — surviving units transfer between scenarios with XP/level/abilities
- **Two scenarios** — Crossing (16x10 reach-the-keep) + Ambush (12x8 trigger zones)
- **Headless scenario validation** — auto-discovery, 10 structural invariants

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| 3-tier check_winner() priority | objective hex → turn limit → elimination; most specific first |
| Campaign progression client-side | Engine is per-scenario; client manages index, veterans, gold |
| Two-phase drain for trigger spawns | Avoids mutable borrow conflict on state |

---

## ✅ v1.2 Love2D Migration

**Completed:** 2026-03-03
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Files created | 3 (norrust_love/) |
| Files deleted | 10 (norrust_client/ + gdext_node.rs) |
| Tests | 73 (56 lib + 16 integration + 1 FFI) |

### Key Accomplishments

- **C ABI bridge** — 36 `extern "C"` functions with opaque `NorRustEngine` pointer and caller-frees memory management
- **Love2D game client** — 1202 lines of Lua (conf.lua + norrust.lua + main.lua) with full game.gd feature parity
- **LuaJIT FFI bindings** — `norrust.lua` wraps all 36 C functions with Lua-native types + inline JSON decoder (~90 lines)
- **Pure hex math** — `hex_to_pixel`/`pixel_to_hex` replacing Godot TileMap dependency
- **Redot cleanup** — `norrust_client/` deleted, `gdext_node.rs` deleted, `godot` crate dependency removed
- **Documentation updated** — README, ARCHITECTURE, BRIDGE_API, DEVELOPMENT all rewritten for Love2D

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Opaque NorRustEngine pointer for C ABI | Mirrors NorRustCore without Godot deps |
| Caller-frees string/array memory | CString::into_raw for returns; LuaJIT caller frees |
| ffi.gc destructor on engine pointer | Automatic cleanup on GC; memory-safe |
| Inline JSON decoder in norrust.lua | No external Lua deps; ~90 lines |
| push/pop camera transform | Clean separation of board-space and screen-space |
| cdylib crate-type retained after cleanup | Still needed for .so loaded by LuaJIT FFI |

---

## ✅ v1.1 Camera & Viewport

**Completed:** 2026-03-03
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 1 |
| Plans | 1 |
| Tests | 72 (56 lib + 16 integration) |

### Key Accomplishments

- **HEX_RADIUS 64→96px** — larger hexes with HEX_CELL_W=166, HEX_CELL_H=192; labels scaled 1.5×
- **Drag-to-pan** on empty board space + **arrow key continuous pan** at 500px/sec
- **Board-edge clamping** with half-viewport + HEX_RADIUS margin
- **Smooth camera lerp** (factor 8.0) to center selected unit; keyboard pan cancels lerp
- **_select_unit() helper** centralizing selection + camera-follow logic

---

## ✅ v1.0 Game Readability

**Completed:** 2026-03-02
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 2 |
| Tests | 72 (56 lib + 16 integration) |

### Key Accomplishments

- **Unit stat panel** — click any unit to see full details: name, level, HP, XP, movement, attacks, abilities
- **AttackSnapshot struct** — full unit loadout in StateSnapshot JSON
- **_inspect_unit_id** — inspection state independent of selection for viewing enemy stats
- **In-hex type name** — `def_id.split("_")[0].capitalize().left(7)` visible in every hex without clicking

---

## ✅ v0.9 Game Mechanics

**Completed:** 2026-03-02
**Duration:** ~1 day (same session as v0.8)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 3 |
| Files changed | ~10 |
| Tests | 69 (55 lib + 14 integration) |

### Key Accomplishments

- **Per-faction gold economy** — `GameState.gold [u32; 2]` starting at [10,10]; villages pay 2g/turn on EndTurn; gold exposed via `StateSnapshot.gold` in JSON
- **FactionDef TOML schema** with `starting_gold` field — applied from faction data at PLAYING transition via `apply_starting_gold()` bridge
- **Full GDScript faction setup flow** — faction picker → leader placement → unit palette placement → PLAYING (all existing; confirmed and extended)
- **`apply_recruit()` pure Rust function** — castle hex validation, gold check (can't go negative), gold deduction, unit placement; fully testable headlessly
- **`ActionError::NotEnoughGold` + `::DestinationNotCastle`** — error codes -8 and -9 extending the existing -1..-7 range
- **`recruit_unit_at()` + `get_unit_cost()` GDExtension bridges** — GDScript recruitment path; same stat-copy pattern as `place_unit_at()`
- **`ActionRequest::Recruit`** in JSON API — AI agents can now recruit units via the external JSON action interface
- **Castle hexes in `scenarios/contested.toml`** — col 0 (faction 0) and col 7 (faction 1) are castle terrain; 5 recruit slots per side
- **GDScript 'R' key recruit panel** — castle hexes highlighted teal, sidebar with unit list + costs, 1-9 key selection, click-to-place, exits mode after placement

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| `gold: [u32; 2]` array (not HashMap) | Exactly 2 factions; array simpler, cheaper than map |
| Village income on newly-active faction's turn | "Gold at start of turn" semantics; consistent with Wesnoth |
| Starting gold 100 per faction (Wesnoth standard) | Enough for several recruits; meaningful economic decisions |
| `apply_starting_gold()` as separate bridge call | GDScript knows both faction IDs only at PLAYING transition |
| `apply_recruit()` free function (not Action variant) | Advance pattern: registry-free, headlessly testable; bridge handles cost lookup |
| Castle validity = terrain_id == "castle" only | No leader adjacency check — minimal and correct |
| Recruit exits mode after one placement | Simpler state; R again to recruit another unit |

---

## ✅ v0.8 Combat Completeness

**Completed:** 2026-03-02
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 1 |
| Plans | 1 |
| Files changed | 1 |
| Tests | 65 (54 lib + 11 integration) → 64+1 |

### Key Accomplishments

- **`Tile.defense` wired into combat resolution** as the authoritative middle tier: `unit.defense[terrain_id]` → `tile.defense` → `unit.default_defense`
- Fallback chain applies to **both attack and retaliation** paths
- `test_tile_defense_used_in_combat` — Scenario A (100% tile defense blocks all hits) + Scenario B (0% unit entry overrides tile) both verified

---

## ✅ v0.7 Scenario System

**Completed:** 2026-03-01

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 2 |
| Tests | 56 (46 lib + 10 integration) |

### Key Accomplishments

- `BoardDef` TOML schema + `scenario::load_board()` pure Rust — board dimensions and terrain from file
- `UnitPlacement`/`UnitsDef` TOML schema + `scenario::load_units()` — unit starting positions from file
- `scenarios/contested.toml` + `scenarios/contested_units.toml` — first hand-authored scenario
- game.gd startup: 14+ lines of hardcoded setup replaced by `load_board()` + `load_units()`

---

## ✅ v0.6 Terrain System

**Completed:** 2026-03-01

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 53 (45 lib + 8 integration) |

### Key Accomplishments

- `Tile` runtime struct — per-hex autonomous properties (terrain_id, movement_cost, defense, healing, color)
- `generate_map()` procedural map generator with deterministic XOR noise seed
- Full color data chain: `TerrainDef.color` → `Tile.color` → `TileSnapshot.color` → GDScript rendering
- 14 terrain TOMLs with distinct hex color values

---

## ✅ v0.5 Unit Content

**Completed:** 2026-03-01

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 2 |
| Tests | 50 (44 lib + 6 integration) |

### Key Accomplishments

- `UnitDef` schema expanded: race, cost, usage, abilities, alignment (all serde default)
- `parse_alignment()` single conversion point; alignment wired from TOML to Unit at spawn and advance
- `tools/scrape_wesnoth.py` — stdlib-only WML → TOML scraper
- 318 Wesnoth unit TOMLs generated; all 322 units load via Registry<UnitDef>

---

## ✅ v0.4 AI Opponent

**Completed:** 2026-02-28

### Key Accomplishments

- `ai_take_turn(state, faction)` — greedy expected-damage scorer with march fallback; pure Rust
- Human vs AI opponent fully playable: 'E' auto-triggers faction 1 AI

---

## ✅ v0.3 Unit Advancement

**Completed:** 2026-02-28

### Key Accomplishments

- XP gain (1/hit + 8 kill bonus, both sides), `advancement_pending` auto-set
- `advance_unit()` free function + `apply_advance()` bridge + `ActionRequest::Advance` JSON API
- Visual: gold arc ring on pending units, XP progress text, 'A' key handler

---

## ✅ v0.2 Bridge Unification

**Completed:** 2026-02-28

### Key Accomplishments

- `StateSnapshot` JSON as sole unit data source — removed all flat array bridge methods
- `_parse_state()` helper parses JSON once per frame/input cycle

---

## ✅ v0.1 Initial Release

**Completed:** 2026-02-27

### Key Accomplishments

- Rust headless simulation core: hex grid (cubic coordinates), GameState, A* pathfinding, ZOC, combat resolution
- GDExtension bridge connecting Rust core to Redot presentation
- TOML data schemas + generic Registry<T> loader
- Full Wesnoth-style combat: adjacency enforcement, bidirectional retaliation, time-of-day modifiers, resistances

---
*MILESTONES.md — Updated: 2026-03-03 (v1.2 Love2D Migration)*
