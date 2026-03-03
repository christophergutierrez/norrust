# Roadmap: The Clash for Norrust

## Overview

Five phases take the project from data schema definitions through a fully playable hex-based strategy game with external AI hooks. The Rust simulation core is built and tested headlessly before any visual work begins; Redot rendering is layered on top once the core is proven.

## Current Milestone

**v1.1 Camera & Viewport**
Status: ✅ Complete
Phases: 1 of 1 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 24 | Scrollable Camera | 1 | ✅ Complete | 2026-03-03 |

## v1.1 Phase Details

### Phase 24: Scrollable Camera ✅

**Goal:** Make the board scrollable and hexes larger so the game is visually comfortable at any board size. Increase HEX_RADIUS from 64 to 96px, add drag-to-pan and arrow key panning, clamp camera to board bounds, and soft-pan camera to follow unit selection. HUD and sidebar panel remain screen-anchored.
**Depends on:** Phase 23 (in-hex readability complete; all rendering uses world coords via _tile_map)
**Constraints:** Pure GDScript/Redot changes — no Rust or bridge changes
**Completed:** 2026-03-03

**Plans:**
- [x] 24-01: HEX_RADIUS 64→96 + drag-to-pan + arrow key pan + board clamp + selection-follow

**Delivered:**
- HEX_RADIUS 96px; HEX_CELL_W=166, HEX_CELL_H=192; labels scaled 1.5× (name 14pt, HP 18pt, XP 14pt)
- Drag-to-pan on empty board space; arrow key continuous pan at 500px/sec
- Board-edge clamping with half-viewport + HEX_RADIUS margin
- Smooth camera lerp (factor 8.0) to center selected unit; keyboard pan cancels lerp
- _select_unit() helper; _apply_camera_offset() clamp helper; _process(delta) for continuous input
- Zero Rust changes; 72 tests passing (56 lib + 16 integration)

---

## Previous Milestone

**v1.0 Game Readability**
Status: ✅ Complete
Phases: 2 of 2 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 22 | Selection Panel | 1 | ✅ Complete | 2026-03-02 |
| 23 | In-Hex Readability | 1 | ✅ Complete | 2026-03-02 |

## v1.0 Phase Details

### Phase 22: Selection Panel ✅

**Goal:** Clicking any unit (friendly or enemy) opens a stat panel showing full details from the existing JSON snapshot: unit name/type, level, HP (current/max), XP progress, movement budget remaining, all attacks (name, damage, strikes, range), terrain defense % at current position, and abilities list. Panel is read-only for enemy units. No new Rust bridges required — all data already in StateSnapshot JSON.
**Depends on:** Phase 21 (stable GameState + JSON snapshot with all unit fields)
**Completed:** 2026-03-02

**Plans:**
- [x] 22-01: UnitSnapshot JSON extension + _inspect_unit_id state + _draw_unit_panel() in game.gd

**Delivered:**
- `AttackSnapshot` struct + `UnitSnapshot.movement`, `.attacks`, `.abilities` — full loadout in StateSnapshot JSON
- `_inspect_unit_id` inspection state in game.gd independent of selection state
- `_draw_unit_panel()`: faction-colored header, HP, XP (conditional), movement+exhaustion, per-attack breakdown, abilities list
- Click-any-unit (friendly or enemy) shows panel; empty hex clears; recruit mode takes priority
- 72 tests passing (1 new: test_unit_snapshot_includes_movement_attacks_abilities)

### Phase 23: In-Hex Readability ✅

**Goal:** Show the unit's type name (or meaningful abbreviation) inside each hex at all times so units are identifiable without clicking.
**Depends on:** Phase 22 (selection panel complete; UnitSnapshot with def_id already in JSON)
**Completed:** 2026-03-02

**Plans:**
- [x] 23-01: In-hex name abbreviation in _draw_units()

**Delivered:**
- `_draw_units()`: `def_id.split("_")[0].capitalize().left(7)` drawn centered at 9px font above HP text
- "Fighter", "Elvish", "Orcish" etc. visible in every hex at all times — no click required
- HP/XP baseline shifted 2px down; HEX_RADIUS unchanged; zero Rust changes
- 72 tests passing (56 lib + 16 integration)

---

## v0.9 Phase Details

### Phase 20: Gold Economy ✅

**Goal:** Add per-faction gold tracking to GameState. On EndTurn, each faction earns 2 gold per village it owns (village_owners already tracked). Starting gold hardcoded at 10 per faction. StateSnapshot JSON exposes gold per faction. HUD displays current gold.
**Depends on:** Phase 19 (Tile system stable; village_owners already in GameState)
**Completed:** 2026-03-02

**Plans:**
- [x] 20-01: GameState.gold, EndTurn income, StateSnapshot + HUD

**Delivered:**
- `GameState.gold: [u32; 2]` — per-faction gold, starting [10, 10]
- EndTurn income: 2g × owned village count to newly-active faction
- `StateSnapshot.gold` in JSON — AI clients and GDScript both see it
- HUD: "Turn 1 · Day · Blue's Turn · 10g"
- 65 tests passing (55 lib + 10 integration)

### Phase 21: Factions + Recruitment

**Goal:** Define FactionDef TOML schema (id, name, starting_gold, recruitable_units[]). Load factions via Registry<FactionDef> + load_factions() bridge, replacing hardcoded starting gold. Add castle hexes to contested.toml. Implement Action::Recruit with can't-go-negative guard. Wire 'R' key in GDScript to recruit first affordable unit from faction list on selected castle hex.
**Depends on:** Phase 20 (gold tracking must exist before recruitment can spend it)

**Plans:**
- [x] 21-01: FactionDef.starting_gold + apply_starting_gold() bridge + game.gd wiring
- [x] 21-02: Action::Recruit + castle scenario + GDScript 'R' key + headless tests

**Delivered:**
- `FactionDef.starting_gold: u32` (default 100) — set into state.gold at game start via bridge
- `apply_recruit(state, unit, destination, cost)` — pure Rust, registry-free, headlessly testable
- `ActionError::NotEnoughGold` + `::DestinationNotCastle` (-8/-9 error codes)
- `recruit_unit_at()` + `get_unit_cost()` GDExtension bridges
- `ActionRequest::Recruit` — JSON API path for AI agent recruitment
- `scenarios/contested.toml` — col 0 + col 7 are castle (recruit zones); col 1 + 6 flat corridors
- GDScript 'R' key: recruit panel with teal castle highlights, unit list with costs, click-to-place
- 69 tests passing (55 lib + 14 integration)

---

## Previous Milestone

**v0.8 Combat Completeness** (v0.8.0)
Status: ✅ Complete
Phases: 1 of 1 complete
Released: 2026-03-02

## v0.8 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 19 | Tile Defense Combat Wiring | 1 | ✅ Complete | 2026-03-02 |

## v0.8 Phase Details

### Phase 19: Tile Defense Combat Wiring

**Goal:** Wire `Tile.defense` into combat resolution as the authoritative terrain defense value, replacing `Unit.default_defense`. The per-hex defense stat is already stored on `Tile` (populated from `TerrainDef` at `set_terrain_at()`) but is not yet consulted during attack calculations. This phase makes combat fully data-driven from TOML terrain definitions.
**Depends on:** Phase 18 (Tile system stable, terrain IDs reconciled)
**Completed:** 2026-03-02

**Plans:**
- [x] 19-01: Wire Tile.defense into combat fallback chain (attack + retaliation), test_tile_defense_used_in_combat

**Delivered:**
- Fallback chain `unit.defense[terrain_id] → tile.defense → unit.default_defense` in both attack and retaliation paths
- `test_tile_defense_used_in_combat`: Scenario A (tile blocks all hits at 100%) and Scenario B (unit entry wins at 0%) both verified
- 64 tests passing (54 lib + 10 integration)

---

## Previous Milestone

**v0.7 Scenario System** (v0.7.0)
Status: ✅ Complete
Phases: 2 of 2 complete
Released: 2026-03-01

## v0.7 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 17 | Board File Format | 1 | ✅ Complete | 2026-03-01 |
| 18 | Unit Placement + Wiring | 1 | ✅ Complete | 2026-03-01 |

## v0.7 Phase Details

### Phase 17: Board File Format

**Goal:** Define a TOML schema for board files (`width`, `height`, flat `tiles` array of terrain IDs). Add `load_board()` GDExtension bridge method that reads the file, looks up each terrain ID in the TerrainDef registry, and populates the board. Headless integration test verifying terrain loads correctly from file.
**Depends on:** Phase 16 (Tile struct and terrain color chain stable)
**Completed:** 2026-03-01

**Plans:**
- [x] 17-01: Board TOML schema, `load_board()` bridge, headless test

**Delivered:**
- `BoardDef` TOML struct: width, height, flat row-major tiles array
- `scenario::load_board(path)` pure Rust: reads TOML, validates tile count, populates Board
- `scenarios/contested.toml`: 8×5 board with flat spawn zones, forest/hills/mountains interior, 2 villages
- `load_board(path, seed)` GDExtension bridge: creates GameState, upgrades tiles from registry
- 55 tests passing (46 lib + 9 integration)

### Phase 18: Unit Placement + Wiring

**Goal:** Define a separate TOML schema for unit placement files (`[[units]]` array with `unit_type`, `faction`, `col`, `row`). Add `load_units()` bridge method. Wire both `load_board()` and `load_units()` into game.gd startup, replacing `generate_map()` and the hardcoded spawn block. Create first hand-authored scenario in `scenarios/`.
**Depends on:** Phase 17 (`load_board()` bridge stable)
**Completed:** -

**Plans:**
- [x] 18-01: Unit placement TOML schema, `load_units()` bridge, game.gd wiring, first scenario

**Delivered:**
- `UnitPlacement` + `UnitsDef` TOML structs: `[[units]]` array-of-tables with id, unit_type, faction, col, row
- `scenario::load_units(path)` pure Rust: reads TOML, returns `Vec<UnitPlacement>` (registry-free)
- `scenarios/contested_units.toml`: 10 fighters, 5 per faction, left/right spawn zones
- `load_units()` GDExtension bridge: iterates placements, calls `place_unit_at()` per entry
- `game.gd` startup: 14 hardcoded lines replaced by `load_board()` + `load_units()` — no hardcoded state
- 56 tests passing (46 lib + 10 integration)

---

## Previous Milestone

**v0.6 Terrain System** (v0.6.0)
Status: ✅ Complete
Phases: 3 of 3 complete
Released: 2026-03-01

## v0.6 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 14 | Tile Runtime + Terrain Wiring | 1 | ✅ Complete | 2026-03-01 |
| 15 | Map Generator | 1 | ✅ Complete | 2026-03-01 |
| 16 | Terrain Presentation | 1 | ✅ Complete | 2026-03-01 |

## v0.6 Phase Details

### Phase 14: Tile Runtime + Terrain Wiring ✅

**Goal:** Replace `HashMap<Hex, String>` with `HashMap<Hex, Tile>` on Board. `Tile` is a runtime struct instantiated from `TerrainDef` at `set_terrain_at()` — same pattern as `Unit`/`UnitDef`. Reconcile terrain IDs to Wesnoth vocabulary. Wire movement costs and defense into pathfinding and combat from `Tile` properties.
**Depends on:** Phase 13 (TerrainDef TOMLs for all Wesnoth terrain types exist)
**Completed:** 2026-03-01

**Plans:**
- [x] 14-01: Tile struct, Board refactor, terrain ID reconciliation, test_terrain_wiring

**Delivered:**
- `Tile` struct: terrain_id, movement_cost, defense, healing — instantiated from TerrainDef at placement
- `Board` stores `HashMap<Hex, Tile>`; `tile_at()` query; `terrain_at()` backward-compatible
- `healing_map` removed; EndTurn healing reads `tile.healing` directly
- `set_terrain_at()` bridge: `Tile::from_def()` when TerrainDef found, `Tile::new()` fallback
- Terrain IDs reconciled: "flat", "mountains", "shallow_water" in all custom unit TOMLs, tests, game.gd
- `test_terrain_wiring`: hills cost 2 MP, flat costs 1 MP — movement costs verified end-to-end
- 51 tests passing (44 lib + 7 integration)

### Phase 15: Map Generator ✅

**Goal:** Procedural map generation with geographically sensible terrain placement. Spawn zones flat, contested zone mixed flat/forest/hills/mountains, villages at structural positions. Board initialized from generator rather than hardcoded GDScript calls.
**Depends on:** Phase 14 (Tile system and terrain IDs in place)
**Completed:** 2026-03-01

**Plans:**
- [x] 15-01: mapgen.rs with generate_map(board, seed), GDExtension bridge, game.gd wiring

**Delivered:**
- `mapgen.rs`: `generate_map(board, seed)` with XOR noise hash; outer 2 cols = flat (spawn zones); villages at (cols/3, rows/2) and (cols*2/3, rows/2); contested zone = flat/forest/hills/mountains
- `generate_map(seed: i64) -> bool` GDExtension bridge — calls generator, upgrades tiles from registry
- `game.gd`: single `_core.generate_map(42)` replaces 7 lines of manual terrain setup
- `test_generate_map`: integration test verifying all ACs headlessly (no registry)
- 52 tests passing (44 lib + 8 integration)

### Phase 16: Terrain Presentation ✅

**Goal:** Per-tile color from TOML data through Tile/TileSnapshot to GDScript rendering. Replace hardcoded terrain-to-color switch with data-driven lookup.
**Depends on:** Phase 15 (map generator produces varied terrain to display)
**Completed:** 2026-03-01

**Plans:**
- [x] 16-01: TerrainDef.color + Tile.color + TileSnapshot.color + 14 terrain TOMLs + game.gd data-driven rendering

**Delivered:**
- `TerrainDef.color`, `Tile.color`, `TileSnapshot.color` — full data chain from TOML to JSON
- All 14 terrain TOMLs updated with distinct hex color values
- game.gd: `tile_colors` map from `state["terrain"]`; `COLOR_FOREST`/`COLOR_VILLAGE` constants removed
- Hills (#8b7355) and mountains (#6b6b6b) now render distinctly from flat (#4a7c4e)
- `test_tile_snapshot_includes_color`: new unit test verifying color in JSON output
- 53 tests passing (45 lib + 8 integration)

---

## Previous Milestone

**v0.5 Unit Content** (v0.5.0)
Status: ✅ Complete
Phases: 2 of 2 complete
Released: 2026-03-01

## v0.5 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 12 | UnitDef Schema Expansion | 1 | ✅ Complete | 2026-03-01 |
| 13 | Wesnoth Data Import | 1 | ✅ Complete | 2026-03-01 |

## v0.5 Phase Details

### Phase 12: UnitDef Schema Expansion ✅

**Goal:** Extend `UnitDef` and `AttackDef` Rust structs with new fields — `alignment`, `race`, `cost`,
`usage`, `abilities`, attack `specials` — all with `#[serde(default)]` so existing TOMLs load unchanged.
Move `alignment` from GDScript spawn-time parameter to registry-sourced data.
**Depends on:** Phase 11 (stable GDExtension bridge, place_unit_at() API)
**Completed:** 2026-03-01

**Plans:**
- [x] 12-01: UnitDef/AttackDef schema expansion + alignment wired from TOML to Unit at spawn/advance

**Delivered:**
- `UnitDef`: race, cost, usage, abilities, alignment — all `#[serde(default)]`
- `AttackDef`: specials — `#[serde(default)]`
- `parse_alignment()`: "lawful"→Lawful, "chaotic"→Chaotic, else→Liminal — pub fn in unit.rs
- alignment wired: place_unit_at() + advance_unit() both call parse_alignment()
- 4 unit TOMLs updated: fighter/hero="lawful", archer/ranger="neutral"
- 49 tests passing (44 lib + 5 integration)

### Phase 13: Wesnoth Data Import ✅

**Goal:** Python scraper reads Wesnoth WML from `/home/chris/git_home/wesnoth/data/core/units/`,
expands movement type macros, and outputs unit TOMLs + terrain TOMLs. All units load via
`Registry::<UnitDef>::load_from_dir()` verified by integration test.
**Depends on:** Phase 12 (expanded UnitDef schema must exist before TOMLs are generated)
**Completed:** 2026-03-01

**Plans:**
- [x] 13-01: Python WML scraper + terrain TOMLs + Rust integration test

**Delivered:**
- `tools/scrape_wesnoth.py`: 270-line stdlib-only WML → TOML scraper; 38 movetypes, 328 unit_type blocks parsed
- 318 Wesnoth unit TOMLs generated (322 total with 4 custom); all load via Registry<UnitDef>
- 11 terrain TOMLs (flat, hills, mountains, cave, frozen, fungus, sand, shallow_water, reef, swamp_water, castle)
- `test_wesnoth_units_load`: asserts registry.len() >= 200; Spearman spot-check (hp=36, mv=5, pierce)
- 50 tests passing (44 lib + 6 integration)

---

## Previous Milestone

**v0.4 AI Opponent** (v0.4.0)
Status: ✅ Complete
Phases: 2 of 2 complete
Released: 2026-02-28

## v0.4 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 10 | AI Core (ai.rs) | 1 | ✅ Complete | 2026-02-28 |
| 11 | AI Bridge & GDScript | 1 | ✅ Complete | 2026-02-28 |

## v0.4 Phase Details

### Phase 10: AI Core (ai.rs) ✅

**Goal:** Implement the analytic greedy AI in a pure-Rust `ai.rs` module — expected-damage
scorer, move+attack planner, and headless AI-vs-AI integration test.
**Depends on:** Phase 9 (stable GameState, apply_action, pathfinding, combat APIs)
**Completed:** 2026-02-28

**Plans:**
- [x] 10-01: expected_outgoing_damage(), score_attack(), ai_take_turn(), test_ai_vs_ai_terminates

**Delivered:**
- `expected_outgoing_damage()`: analytic expected-value scorer (hit_chance × effective_dmg × strikes × tod)
- `score_attack()`: pair scorer using terrain defense, time-of-day, resistances; kill bonus ×3
- `ai_take_turn(state, faction)`: greedy move+attack for all faction units; EndTurn; registry-free
- `test_ai_vs_ai_terminates`: 5v5 headless integration test — game terminates with a winner in ≤100 turns
- 48 tests passing (44 lib + 4 integration)

### Phase 11: AI Bridge & GDScript ✅

**Goal:** Connect the Phase 10 Rust AI to the Redot presentation layer: march fallback, GDExtension bridge method, and GDScript auto-trigger — making human vs AI opponent fully playable.
**Depends on:** Phase 10 (ai_take_turn() pure Rust API)
**Completed:** 2026-02-28

**Plans:**
- [x] 11-01: March fallback, ai_take_turn() bridge, GDScript KEY_E wiring, human-verify

**Delivered:**
- March fallback in `ai_take_turn()`: units advance toward nearest enemy when no attack is reachable
- `fn ai_take_turn(faction: i32)` GDExtension bridge: callable from GDScript with faction validation
- GDScript auto-AI: after player 'E', faction 1 AI plays automatically; win detection follows
- `test_ai_marches_toward_enemy_when_no_attack`: 8×1 board, col 0 → col 5 with movement=5
- 49 tests passing (44 lib + 5 integration)

---

## Previous Milestone

**v0.3 Unit Advancement** (v0.3.0)
Status: ✅ Complete
Phases: 3 of 3 complete
Released: 2026-02-28

## v0.3 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 7 | Advancement Schema | 1 | ✅ Complete | 2026-02-28 |
| 8 | XP & Advancement Logic | 2 | ✅ Complete | 2026-02-28 |
| 9 | Advancement Presentation | 1 | ✅ Complete | 2026-02-28 |

## v0.3 Phase Details

### Phase 7: Advancement Schema ✅

**Goal:** Extend data definitions and runtime structs to carry advancement information — TOML files
gain `experience`, `advances_to`, `level`; `Unit` gains `xp`, `xp_needed`, and `advancement_pending`;
`UnitSnapshot` JSON exposes all three for GDScript and AI clients.
**Depends on:** Phase 6 (StateSnapshot JSON as sole unit data source)
**Completed:** 2026-02-28

**Plans:**
- [x] 07-01: UnitDef schema, TOML data files, Unit runtime struct, UnitSnapshot JSON

**Delivered:**
- `UnitDef`: `level`, `experience`, `advances_to` — all `#[serde(default)]`
- `data/units/fighter.toml` + `archer.toml`: level 1, experience=40, advances_to set
- `data/units/hero.toml` + `ranger.toml`: new level-2 definitions with dual-attack loadouts
- `Unit`: `xp`, `xp_needed`, `advancement_pending` runtime fields; `xp_needed` set at spawn
- `UnitSnapshot` JSON: exposes all XP/advancement fields; 37 tests passing

### Phase 8: XP & Advancement Logic ✅

**Goal:** Implement XP gain in combat, the advancement action, and headless balance simulation tests.
**Depends on:** Phase 7 (advancement fields on Unit and UnitDef)
**Completed:** 2026-02-28

**Plans:**
- [x] 08-01: XP gain in Attack branch (1 XP/hit + 8 kill bonus, both attacker and defender)
- [x] 08-02: advance_unit() + apply_advance() bridge + ActionRequest::Advance JSON API + simulation test

**Delivered:**
- XP grant in `Action::Attack` — attacker and defender earn XP symmetrically; `advancement_pending` auto-sets
- `advance_unit()` pure Rust free function — usable without registry or bridge
- `apply_advance()` GDExtension bridge method — GDScript callable with error codes
- `ActionRequest::Advance` JSON variant — AI clients can advance units via JSON API
- Headless simulation: 5-kill XP accumulation → hero promotion verified end-to-end
- 43 tests passing (41 lib + 2 integration)

### Phase 9: Advancement Presentation ✅

**Goal:** Surface XP and advancement state in the Redot layer — XP progress in the HUD,
visual indicator when a unit is ready to advance, and click-to-advance interaction.
**Depends on:** Phase 8 (Advance action implemented and tested)
**Completed:** 2026-02-28

**Plans:**
- [x] 09-01: XP text, gold arc ring, 'A' key advancement handler, 5-unit spawn, float fix

**Delivered:**
- XP progress text ("xp/xp_needed") drawn per unit; int() cast guards Redot float JSON values
- Gold draw_arc() ring on units with advancement_pending = true (visually distinct from hex outline)
- 'A' key handler: advances selected friendly unit; guards faction + pending + selection
- 5 fighters per side — advancement reachable in normal play (5 kills × 9 XP = 45 XP)
- test_fighter_advancement_with_real_stats: headless proof using actual 7×3 fighter sword stats
- 44 tests passing (41 lib + 3 integration)

---

## Previous Milestone

**v0.2 Bridge Unification** (v0.2.0)
Status: ✅ Complete
Phases: 1 of 1 complete
Released: 2026-02-28

## v0.2 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 6 | Bridge Unification | 1 | ✅ Complete | 2026-02-28 |

## v0.2 Phase Details

### Phase 6: Bridge Unification ✅

**Goal:** Eliminate dual state extraction and magic array indices — `StateSnapshot` JSON becomes
the sole source of truth for unit data in both GDScript and external AI clients.
**Depends on:** Phase 5 (get_state_json() bridge stable)
**Completed:** 2026-02-28

**Plans:**
- [x] 06-01: Remove flat array bridge methods, refactor GDScript to parse JSON snapshot

**Delivered:**
- `get_unit_data()` and `get_unit_positions()` removed from gdext_node.rs
- `_parse_state()` helper: single JSON parse per draw/input cycle
- `_draw_units()` and `_build_unit_pos_map()` use named dictionary keys (`unit["hp"]`, etc.)
- `RH_STRIDE`, `RH_COL`, `RH_ROW` constants guard `get_reachable_hexes()` boundary
- Visual regression: none — game renders identically

---

## Previous Milestone

**v0.1 Initial Release** (v0.1.0)
Status: ✅ Complete
Phases: 5 of 5 complete
Released: 2026-02-28

## v0.1 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & Data Schema | 3 | ✅ Complete | 2026-02-27 |
| 2 | The Headless Core | 5 | ✅ Complete | 2026-02-27 |
| 3 | The Presentation Layer | 3 | ✅ Complete | 2026-02-28 |
| 4 | The Game Loop & Polish | 4 | ✅ Complete | 2026-02-28 |
| 5 | AI Hooks & External APIs | 1 | ✅ Complete | 2026-02-28 |

## v0.1 Phase Details

### Phase 1: Foundation & Data Schema ✅

**Goal:** Define the language of the game — data schemas, project scaffolding, and a working GDExtension hello-world.
**Completed:** 2026-02-27

**Plans:**
- [x] 01-01: Rust core scaffold + TOML data schemas + Registry<T> loader
- [x] 01-02: GDExtension bridge (NorRustCore GodotClass, Redot 26.1 project)
- [x] 01-03: End-to-end data flow (Registry → GDExtension → Redot console)

**Delivered:**
- `norrust_core/` Rust library (cdylib + rlib, serde/toml/gdext)
- `data/units/` and `data/terrain/` TOML files
- Generic `Registry<T>` loader
- `NorRustCore` GodotClass with `load_data()` + `get_unit_max_hp()`
- Round-trip proven: Disk → TOML → Rust → GDScript

### Phase 2: The Headless Core ✅

**Goal:** Play the game in the terminal/tests — full simulation logic with no graphics.
**Completed:** 2026-02-27

**Delivered:**
- Cubic hex coordinate system (odd-r offset at I/O boundaries)
- `GameState` struct with A* pathfinding, ZOC, unit placement
- Combat resolution: RNG, terrain defense, time-of-day modifiers, resistances
- 30+ Rust unit tests

### Phase 3: The Presentation Layer ✅

**Goal:** See the game and click things — visual rendering connected to Rust core.
**Completed:** 2026-02-28

**Delivered:**
- Redot TileMap hex grid, mouse → hex coordinate input
- Unit spawning, faction colours, HP display, move range highlighting
- Action dispatch: Redot → Rust → visual update (move, attack, end turn)

### Phase 4: The Game Loop & Polish ✅

**Goal:** A complete, playable match from start to win/loss.
**Completed:** 2026-02-28

**Plans:**
- [x] 04-01: Adjacency enforcement, defender retaliation, win/loss detection
- [x] 04-02: Unit exhaustion indicators, per-terrain healing on EndTurn
- [x] 04-03: Resistance modifiers in combat, colored HUD (Turn · ToD · Faction)
- [x] 04-04: Village terrain (healing=8), 8×5 board, terrain-driven rendering

**Delivered:**
- Full Wesnoth-style combat: adjacency check, bidirectional retaliation, time-of-day modifiers, resistance types
- Turn structure: EndTurn with faction flip, per-terrain healing, time-of-day cycle
- Visual polish: exhausted unit dimming, colored HUD, village gold-tan hexes
- Rust as terrain source of truth: `get_terrain_at()` bridge drives `_draw()`

### Phase 5: AI Hooks & External APIs ✅

**Goal:** Open the doors for the machines — clean external interfaces for AI agents.
**Completed:** 2026-02-28

**Plans:**
- [x] 05-01: JSON state serialization (StateSnapshot) + action submission (ActionRequest) + GDExtension bridge

**Delivered:**
- `snapshot.rs`: `StateSnapshot`, `UnitSnapshot`, `TileSnapshot`, `ActionRequest`
- `get_state_json()` bridge: full game state as JSON string
- `apply_action_json(json)` bridge: action submission from external clients (-99 on parse error)
- 6 new unit tests; serde_json dependency added

---

## Completed Milestones

<details>
<summary>v0.9 Game Mechanics — 2026-03-02 (2 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 20 | Gold Economy | 1 | 2026-03-02 |
| 21 | Factions + Recruitment | 2 | 2026-03-02 |

Archive: `.paul/milestones/v0.9-ROADMAP.md`
</details>

<details>
<summary>v0.8 Combat Completeness — 2026-03-02 (1 phase)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 19 | Tile Defense Combat Wiring | 1 | 2026-03-02 |

Archive: `.paul/milestones/v0.8-ROADMAP.md`
</details>

<details>
<summary>v0.7 Scenario System — 2026-03-01 (2 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 17 | Board File Format | 1 | 2026-03-01 |
| 18 | Unit Placement + Wiring | 1 | 2026-03-01 |
</details>

<details>
<summary>v0.6 Terrain System — 2026-03-01 (3 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 14 | Tile Runtime + Terrain Wiring | 1 | 2026-03-01 |
| 15 | Map Generator | 1 | 2026-03-01 |
| 16 | Terrain Presentation | 1 | 2026-03-01 |
</details>

<details>
<summary>Earlier milestones (v0.1–v0.5) — 2026-02-27 to 2026-03-01</summary>
See MILESTONES.md for full history.
</details>

---
*Roadmap updated: 2026-03-03 — v1.1 Camera & Viewport milestone complete (Phase 24 Scrollable Camera)*
