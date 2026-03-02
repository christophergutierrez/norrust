# Project: The Clash for Norrust

## Description

A clean-room rewrite of The Battle for Wesnoth — a modern, data-driven hex-based strategy game. The Rust simulation core handles all game logic headlessly; Redot handles presentation and input via GDExtension. Game rules and stats are defined in TOML config files, not hardcoded.

## Core Value

A playable hex-based strategy game where the simulation logic is strictly separated from the presentation, enabling both human players and external AI agents to interact with the same clean game engine.

## Requirements

### Validated (Shipped)

- [x] TOML data schemas for units and terrain — Phase 1 (fighter, archer, grassland, forest)
- [x] Redot presentation layer connected via GDExtension — Phase 1 (NorRustCore class, hello world + data query proven)
- [x] Generic data Registry loadable from disk and queryable from GDScript — Phase 1
- [x] Rust headless simulation core (hex grid, GameState, unit positions) — Phase 2
- [x] Hex grid math (axial/cube coordinates, odd-r offset) with A* pathfinding — Phase 2
- [x] Combat resolution with terrain defense and time-of-day modifiers — Phase 2
- [x] Zone of Control (ZOC) enforcement — Phase 2
- [x] Redot TileMap hex grid + mouse → hex coordinate input — Phase 3
- [x] Unit spawning from Rust GameState, rendered with faction colour and HP — Phase 3
- [x] Valid move range highlighting queried from Rust (reachable_hexes flood-fill) — Phase 3
- [x] Action dispatch: Redot → Rust → visual update (move, attack, end turn) — Phase 3
- [x] End Turn logic, Time of Day progression, per-terrain healing — Phase 4 (04-01, 04-02)
- [x] Adjacency enforcement and defender retaliation (Wesnoth-style bidirectional combat) — Phase 4 (04-01)
- [x] Win/loss condition detection (faction elimination) — Phase 4 (04-01)
- [x] Unit exhaustion visual indicators (dimmed circle on moved/attacked units) — Phase 4 (04-02)
- [x] Resistance modifiers in combat resolution — Phase 4 (04-03)
- [x] Colored HUD (Turn · TimeOfDay · Faction) with faction-colored text — Phase 4 (04-03)
- [x] Village terrain type (healing=8) with contested hexes on 8×5 board — Phase 4 (04-04)
- [x] Terrain-driven rendering via get_terrain_at() bridge (Rust as source of truth) — Phase 4 (04-04)
- [x] JSON state serialization (StateSnapshot) + action deserialization (ActionRequest) — Phase 5 (05-01)
- [x] get_state_json() + apply_action_json() GDExtension bridge for external AI clients — Phase 5 (05-01)
- [x] StateSnapshot JSON as sole unit data source: flat array bridge methods removed, GDScript uses named dict keys — Phase 6 (06-01)
- [x] Named stride constants (RH_STRIDE/RH_COL/RH_ROW) for get_reachable_hexes() boundary — Phase 6 (06-01)
- [x] UnitDef advancement schema: level, experience, advances_to in TOML (serde default) — Phase 7 (07-01)
- [x] Unit runtime XP fields: xp, xp_needed, advancement_pending; xp_needed set at spawn — Phase 7 (07-01)
- [x] UnitSnapshot JSON exposes xp/xp_needed/advancement_pending for GDScript and AI clients — Phase 7 (07-01)
- [x] Level-2 unit definitions: hero.toml (fighter→hero) and ranger.toml (archer→ranger) — Phase 7 (07-01)
- [x] XP gain in combat: 1 XP per hit + 8 kill bonus for both attacker and defender — Phase 8 (08-01)
- [x] advancement_pending auto-set when xp >= xp_needed (guarded by xp_needed > 0) — Phase 8 (08-01)
- [x] advance_unit() pure Rust function: stat mutation, full heal, xp reset — Phase 8 (08-02)
- [x] apply_advance() GDExtension bridge method for GDScript — Phase 8 (08-02)
- [x] ActionRequest::Advance JSON API variant for external AI clients — Phase 8 (08-02)
- [x] Headless advancement simulation: 5-kill XP accumulation → hero promotion verified — Phase 8 (08-02)
- [x] XP progress text ("xp/xp_needed") drawn below HP on each unit circle — Phase 9 (09-01)
- [x] Gold arc ring indicator on units with advancement_pending = true — Phase 9 (09-01)
- [x] 'A' key handler: advances selected unit via apply_advance() with faction + pending guards — Phase 9 (09-01)
- [x] Integration test with real fighter.toml stats: 7×3 sword, 5 kills → hero (45 HP, 9×4 sword) — Phase 9 (09-01)
- [x] Analytic greedy AI: expected_outgoing_damage() scorer, kill bonus ×3, no RNG rollouts — Phase 10 (10-01)
- [x] ai_take_turn(state, faction): greedy move+attack planner for all faction units; EndTurn; pure Rust — Phase 10 (10-01)
- [x] Headless AI-vs-AI integration test: 5v5 fighters terminate with winner in ≤100 turns — Phase 10 (10-01)
- [x] March fallback in ai_take_turn(): advance toward nearest enemy when no attack reachable — Phase 11 (11-01)
- [x] fn ai_take_turn(faction: i32) GDExtension bridge: callable from GDScript — Phase 11 (11-01)
- [x] Human vs AI opponent fully playable: 'E' auto-triggers faction 1 AI, win detection works — Phase 11 (11-01)
- [x] UnitDef schema expanded: race, cost, usage, abilities, alignment (all serde default) — Phase 12 (12-01)
- [x] AttackDef schema expanded: specials field (serde default) — Phase 12 (12-01)
- [x] parse_alignment() pub helper: "lawful"→Lawful, "chaotic"→Chaotic, else→Liminal — Phase 12 (12-01)
- [x] alignment wired from TOML registry to Unit at spawn (place_unit_at) and advance (advance_unit) — Phase 12 (12-01)
- [x] fighter/hero alignment="lawful"; archer/ranger alignment="neutral" in unit TOMLs — Phase 12 (12-01)
- [x] tools/scrape_wesnoth.py: stdlib-only Python WML → TOML scraper for Wesnoth unit data — Phase 13 (13-01)
- [x] 318 Wesnoth unit TOMLs generated from WML source; all 322 units load via Registry<UnitDef> — Phase 13 (13-01)
- [x] 11 terrain type TOMLs (flat, hills, mountains, cave, frozen, fungus, sand, shallow_water, reef, swamp_water, castle) — Phase 13 (13-01)
- [x] Integration test verifying all 322 unit TOMLs load; Spearman spot-check (max_hp=36, movement=5, alignment="lawful") passes — Phase 13 (13-01)
- [x] Tile runtime struct: terrain_id, movement_cost, defense, healing — instantiated from TerrainDef at set-time, autonomous per-hex — Phase 14 (14-01)
- [x] Board stores HashMap<Hex, Tile>; tile_at() query; terrain_at() preserved for compatibility — Phase 14 (14-01)
- [x] healing_map cache removed; EndTurn healing reads tile.healing directly — Phase 14 (14-01)
- [x] set_terrain_at() bridge: Tile::from_def() when TerrainDef in registry, Tile::new() fallback — Phase 14 (14-01)
- [x] Terrain IDs reconciled to Wesnoth vocabulary: "grassland"→"flat", "mountain"→"mountains", "water"→"shallow_water" in all 4 custom unit TOMLs, game.gd, and all test files — Phase 14 (14-01)
- [x] test_terrain_wiring: hills cost 2 MP, flat costs 1 MP — movement costs wire correctly — Phase 14 (14-01)
- [x] mapgen.rs: generate_map(board, seed) — deterministic XOR noise; spawn zones flat; structural villages; contested zone varied — Phase 15 (15-01)
- [x] generate_map(seed: i64) GDExtension bridge: calls generator, upgrades tiles from TerrainDef registry — Phase 15 (15-01)
- [x] game.gd: single _core.generate_map(42) replaces 7-line manual terrain setup loop — Phase 15 (15-01)
- [x] TerrainDef.color, Tile.color, TileSnapshot.color — full color data chain from TOML to JSON — Phase 16 (16-01)
- [x] All 14 terrain TOMLs have distinct hex color values; hills (#8b7355) and mountains (#6b6b6b) visually distinct — Phase 16 (16-01)
- [x] game.gd: data-driven tile_colors map from state["terrain"]; COLOR_FOREST/COLOR_VILLAGE constants removed — Phase 16 (16-01)

### Active (In Progress / Deferred)

- [ ] Factions TOML schema — deferred from Phase 1
- [ ] Recruitment UI (select and place units on Castle hexes) — deferred from Phase 4
- [ ] Movement interpolation and basic attack animations — deferred from Phase 4
- [ ] Socket/TCP server for external Python agents — deferred from Phase 5 (JSON layer complete; transport layer future)

### Out of Scope

- TOML editor UI for modding — post-MVP
- Campaign persistence (veteran units) — post-MVP
- Multiplayer — post-MVP (architecture supports it via Action queue)

## Constraints

### Technical
- Clean-room rewrite — no code copied from `/home/chris/git_home/wesnoth` (reference only)
- Simulation core must be pure Rust (no graphics/UI dependencies)
- Presentation layer must be Redot (not Godot)
- Integration via GDExtension (gdext 0.2.4, Redot 26.1)

### Architecture
- Strict separation: Rust core knows nothing about graphics or UI
- All state mutations via an `Action` queue
- AI hooks must not require ML dependencies in core

## Key Decisions

| Decision | Rationale | Date | Status |
|----------|-----------|------|--------|
| Per-file TOML layout (one entity per file) | Cleaner than arrays-of-tables; adding content = adding one file | 2026-02-27 | Active |
| Generic `Registry<T>` with `IdField` trait | Reusable for all data types; zero new loader code per type | 2026-02-27 | Active |
| `crate-type = ["cdylib", "rlib"]` | cdylib for Redot loading, rlib for `cargo test` — both needed | 2026-02-27 | Active |
| `bin/` copy workflow for .so | Godot `res://` cannot traverse `..`; copy .so to `norrust_client/bin/` after build | 2026-02-27 | Active |
| Return -1 (not panic) for not-found queries | GDScript has no Option type; -1 is clear sentinel for missing data | 2026-02-27 | Active |
| Cubic hex coordinates + odd-r offset at I/O | All internal hex math in cube coords; convert to/from offset only at board/bridge boundaries | 2026-02-27 | Active |
| apply_action() mutates GameState in place | Zero-copy, simple API; returns Result<(), ActionError> | 2026-02-27 | Active |
| movement=0 sentinel → skip pathfinding check | Backward-compat for Unit::new() callers; movement>0 requires valid path | 2026-02-27 | Active |
| PackedInt32Array 7-tuple for get_unit_data() | id/col/row/faction/hp/moved/attacked per unit; exhaustion state queryable from GDScript | 2026-02-28 | Superseded (v0.2) |
| Attack branch before reachable-move in _input() | Enemy click = attack intent; reachable click = move — prevents silent move-to-occupied | 2026-02-28 | Active |
| Copy UnitDef stats into Unit at spawn time | Keeps apply_action() registry-free; phase 3 bridge calls place_unit_at() once per unit | 2026-02-28 | Active |
| Board.healing_map cached at set_terrain_at() | EndTurn healing needs no registry access; healing values stored on board at terrain-set time | 2026-02-28 | Active |
| Unit carries resistances map | Copied from UnitDef at spawn; combat resistance lookup registry-free | 2026-02-28 | Active |
| get_terrain_at() bridge: Rust is terrain source of truth | _draw() queries Rust per hex; adding terrain types requires zero GDScript changes | 2026-02-28 | Active |
| Village always heals (no ownership/capture) | Simpler; capture mechanic deferred to future milestone | 2026-02-28 | Active |
| StateSnapshot DTO (not Serialize on GameState) | GameState has HashMap<Hex,_> keys + SmallRng — neither serializes cleanly via derive | 2026-02-28 | Active |
| #[serde(tag="action")] internally-tagged ActionRequest | Idiomatic JSON discriminated union; human-readable for AI clients | 2026-02-28 | Active |
| -99 JSON parse error sentinel | Distinct from ActionError codes -1..-7; AI clients can distinguish bad JSON from rejected actions | 2026-02-28 | Active |
| StateSnapshot JSON as sole GDScript unit data source | Eliminates dual extraction + magic integer indices; GDScript uses unit["hp"] etc. | 2026-02-28 | Active |
| get_reachable_hexes() stays as PackedInt32Array | Coordinate pairs are minimal; JSON overhead not justified — RH_* constants guard the boundary instead | 2026-02-28 | Active |
| Single _parse_state() call per frame/input | JSON parsed once; Dictionary passed to all helpers — avoids double-parse within a draw/input cycle | 2026-02-28 | Active |
| #[serde(default)] on UnitDef advancement fields | level/experience/advances_to optional in TOML; existing files load without changes | 2026-02-28 | Active |
| xp_needed copied at place_unit_at() from registry | Runtime Unit is registry-free; same pattern as attacks/resistances/defense | 2026-02-28 | Active |
| advancement_pending is data-only in Phase 7 | Field set/cleared in Phase 8 (combat XP gain + Action::Advance); no premature logic | 2026-02-28 | Active |
| 1 XP per hit + 8 kill bonus formula | Simple, testable, Wesnoth-compatible; both attacker and defender earn XP | 2026-02-28 | Active |
| advance_unit() as free function in unit.rs | Directly usable in tests and bridge without registry coupling | 2026-02-28 | Active |
| Advance intercepted in apply_action_json before into() | Preserves registry-free apply_action(); Action enum unchanged | 2026-02-28 | Active |
| advances_to index 0 only for bridge | Multi-target choice deferred to Phase 9+; single path sufficient now | 2026-02-28 | Active |
| int() cast on all JSON numeric fields in GDScript | Redot JSON.parse_string() returns all numbers as float; int() required for display and comparison | 2026-02-28 | Active |
| draw_arc() for advancement ring; draw_polyline() for hex outlines | Visually distinct ring layers — unit-level gold arc vs hex-boundary white polyline | 2026-02-28 | Active |
| 5 fighters per side as starting spawn | With 2 units, advancement (40 XP) is unreachable before one dies; 5 enemies guarantees a full advancement cycle | 2026-02-28 | Active |
| N=0 greedy AI (no simulation) | Analytic expected-value only; deterministic, fast, testable; difficulty adjustment deferred | 2026-02-28 | Active |
| ai_take_turn() in pure Rust ai.rs | AI is a caller of apply_action — same API as GDScript and tests; bridge added in Phase 11 | 2026-02-28 | Active |
| kill_bonus ×3 for expected kills | Prioritizes securing kills over trading blows; simple multiplier without MC rollouts | 2026-02-28 | Active |
| March via min_by_key(distance to nearest enemy) | Reuses ZOC-filtered candidates already computed for scoring; no extra pathfinding call | 2026-02-28 | Active |
| GDScript AI trigger checks active_faction after end_turn() | ai_take_turn() calls EndTurn internally; checking faction after player's EndTurn is the cleanest trigger point | 2026-02-28 | Active |
| #[derive(Default)] on AttackDef and UnitDef | Enables ..Default::default() in ~16 test constructions; future schema additions need only 1 line per test file | 2026-03-01 | Active |
| "neutral" alignment maps to Liminal | Same ToD modifier (no bonus/penalty); Neutral variant deferred until dusk/dawn time periods added | 2026-03-01 | Active |
| parse_alignment() as single string→Alignment conversion point | Clean boundary; all callers (spawn, advance, future) go through one function | 2026-03-01 | Active |
| parse_value() uses [^"]* (non-greedy first-quote) in WML scraper | WML inline comments (# wmllint: no spellcheck) after closing " caused 7 malformed TOMLs with greedy .* — first-quote match avoids capturing them | 2026-03-01 | Active |
| Denormalized unit TOMLs from WML scraper (no MovetypeDef registry) | Keeps loader path simple; movement_costs/defense/resistances inlined per unit as already expected by UnitDef schema | 2026-03-01 | Active |
| Registry tests use >= N count assertions | Hardcoded == 4/== 3 broke when data directory grew; >= N survives future data additions | 2026-03-01 | Active |
| Tile/TileDef mirrors Unit/UnitDef pattern | Each hex is autonomous with its own terrain properties; per-hex customisation without new TOML types; same uniform API | 2026-03-01 | Active |
| Tile::new() defaults: movement_cost=1, defense=40, healing=0 | Sensible open-ground fallback; tests and bridge work without registry | 2026-03-01 | Active |
| set_terrain_at() bridge: Tile::from_def() or Tile::new() fallback | Graceful degradation when terrain ID not in registry; no crash path | 2026-03-01 | Active |
| Board.healing_map replaced by tile.healing | Eliminates stale cache; EndTurn healing reads authoritative per-hex value directly | 2026-03-01 | Active |

## Tech Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| Simulation Core | Rust (norrust_core) | Headless, pure logic; cdylib + rlib |
| Presentation | Redot 26.1 + GDScript | 2D hex rendering |
| Integration | GDExtension (godot crate 0.2.4) | Rust ↔ Redot bridge |
| Data Format | TOML / JSON | Config files, state export |
| Reference | Wesnoth source | Read-only at `/home/chris/git_home/wesnoth` |

## Success Criteria

- A complete, playable 2-player match runs from start to win/loss
- External Python script can query game state and submit actions via socket
- All game rules defined in data files, not hardcoded

---
*Created: 2026-02-27*
*Last updated: 2026-03-01 after Phase 16 (Terrain Presentation — v0.6 Terrain System complete, 53 tests pass)*
