# Project: The Clash for Norrust

## Description

A clean-room rewrite of The Battle for Wesnoth — a modern, data-driven hex-based strategy game. The Rust simulation core handles all game logic headlessly; Love2D handles presentation and input via LuaJIT FFI. Game rules and stats are defined in TOML config files, not hardcoded.

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
- [x] BoardDef TOML schema (width, height, flat row-major tiles array) — Phase 17 (17-01)
- [x] scenario::load_board(path) pure Rust function: reads board TOML, validates tile count, populates Board — Phase 17 (17-01)
- [x] scenarios/contested.toml: first hand-authored 8×5 scenario board with flat spawn zones, contested interior, 2 villages — Phase 17 (17-01)
- [x] load_board(path, seed) GDExtension bridge: creates GameState, upgrades tiles from TerrainDef registry — Phase 17 (17-01)
- [x] UnitPlacement/UnitsDef TOML schema (id, unit_type, faction, col, row per [[units]] entry) — Phase 18 (18-01)
- [x] scenario::load_units(path) pure Rust function: reads placement file, returns Vec<UnitPlacement> — Phase 18 (18-01)
- [x] scenarios/contested_units.toml: 10 fighters in starting positions (5 per faction, left/right spawn zones) — Phase 18 (18-01)
- [x] load_units() GDExtension bridge: places all units from file via place_unit_at() — Phase 18 (18-01)
- [x] game.gd: _setup_rust_core() wired to load_board() + load_units(); all hardcoded spawns removed — Phase 18 (18-01)
- [x] Tile.defense wired into combat fallback chain (attack + retaliation): unit.defense[id] → tile.defense → unit.default_defense — Phase 19 (19-01)
- [x] GameState.gold [u32; 2] per-faction gold tracking, starting at [10, 10] — Phase 20 (20-01)
- [x] EndTurn village income: 2 gold per owned village to newly-active faction — Phase 20 (20-01)
- [x] StateSnapshot.gold exposed in JSON for AI clients and GDScript — Phase 20 (20-01)
- [x] HUD displays active faction's gold ("Xg" appended to existing HUD string) — Phase 20 (20-01)
- [x] FactionDef TOML schema (id, name, leader_def, recruits, starting_gold); Registry<FactionDef> + RecruitGroup expansion — Phase 21 (21-01)
- [x] Starting gold wired from FactionDef at game start via apply_starting_gold() bridge — Phase 21 (21-01)
- [x] apply_recruit() pure Rust function: castle hex validation, gold check (can't go negative), deduction, placement — Phase 21 (21-02)
- [x] ActionRequest::Recruit in JSON API — AI agents can recruit via external JSON interface — Phase 21 (21-02)
- [x] Castle terrain hexes in contested.toml (col 0 + col 7); GDScript 'R' key recruit panel with teal highlights and unit cost display — Phase 21 (21-02)
- [x] Unit abilities field: `Vec<String>` on Unit, copied from UnitDef at spawn/advance; lieutenant/elvish_captain/orcish_warrior TOMLs carry "leader"/"leadership" abilities — Phase 22 (22-01)
- [x] Recruitment gated on "leader" ability: apply_recruit() + ai_recruit() check abilities before finding keep — Phase 22 (22-01)
- [x] AttackSnapshot struct + UnitSnapshot.movement/attacks/abilities — full unit loadout in StateSnapshot JSON — Phase 22 (22-01)
- [x] _inspect_unit_id inspection state in game.gd (independent from _selected_unit_id): click any unit to open stat panel — Phase 22 (22-01)
- [x] _draw_unit_panel(): faction-colored header, HP, XP (conditional), movement+exhaustion status, per-attack breakdown, abilities list in right sidebar — Phase 22 (22-01)
- [x] Unit type name abbreviation (first-word of def_id, capitalized, max 7 chars) rendered centered inside each hex circle — Phase 23 (23-01)
- [x] C ABI bridge: 36 extern "C" functions (NorRustEngine opaque pointer + caller-frees memory) exposing all game engine methods for LuaJIT FFI — Phase 25 (25-01)
- [x] Love2D game client (1202 lines Lua) with full feature parity to game.gd — hex rendering, input, HUD, sidebar panel, recruitment, camera, AI opponent — Phase 26 (26-01)
- [x] LuaJIT FFI bindings module (norrust.lua) wrapping all 36 C ABI functions with Lua-native types + inline JSON decoder — Phase 26 (26-01)
- [x] Pure hex math (hex_to_pixel, pixel_to_hex) replacing Godot TileMap dependency — no engine dependency for coordinate conversion — Phase 26 (26-01)
- [x] Objective hex win condition: any unit reaching target hex wins for that faction — Phase 28 (28-01)
- [x] Turn limit loss condition: defender (faction 1) wins if turn exceeds max_turns — Phase 28 (28-01)
- [x] check_winner() method on GameState: 3-tier priority (objective hex → turn limit → elimination) — Phase 28 (28-01)
- [x] LoadedBoard struct: load_board() returns board + objective_hex + max_turns from TOML — Phase 28 (28-01)
- [x] Scenario selection screen in Love2D with dynamic board dimensions from state JSON — Phase 28 (28-01)
- [x] Crossing scenario: 16x10 board with preset units, 30-turn limit, reach-enemy-keep objective — Phase 28 (28-01)
- [x] TriggerZone system: schema (TriggerDef/TriggerSpawnDef), runtime (PendingSpawn/TriggerZone), fire-on-Move with two-phase drain, load_triggers() — Phase 29 (29-01)
- [x] Ambush scenario: 12x8 forest board with 3 trigger zones spawning 5 hidden enemies, 25-turn limit, preset units — Phase 29 (29-01)
- [x] norrust_get_next_unit_id() FFI function: avoids ID conflicts after trigger-spawned units — Phase 29 (29-01)
- [x] Headless scenario validation: auto-discovery of TOML pairs, 10 structural invariants, false-winner detection, FFI symbol completeness — Phase 29 (29-01)
- [x] Campaign TOML schema: CampaignDef with scenario sequence, gold_carry_percent, early_finish_bonus — Phase 30 (30-01)
- [x] VeteranUnit carry-over: surviving units serialize with hp/xp/xp_needed/advancement_pending/abilities for next scenario — Phase 30 (30-01)
- [x] place_veteran_unit FFI: unit_from_registry() for combat stats + override progression fields with carried values — Phase 30 (30-01)
- [x] Gold carry-over calculation: percentage penalty + early finish bonus per remaining turn — Phase 30 (30-01)
- [x] Love2D campaign flow: campaign selection (C key), scenario auto-progression on victory, veteran placement on keep+castles, carry-over gold injection — Phase 30 (30-01)
- [x] Tutorial campaign: crossing → ambush with 80% gold carry and 5g/turn early bonus — Phase 30 (30-01)
- [x] Asset format specification: directory layout, sprite.toml schema, terrain/unit naming conventions, animation states, team coloring approach, pipeline workflow — Phase 31 (31-01)
- [x] Asset loader module (assets.lua): terrain tile + unit sprite loading with graceful fallback to colored polygon/circle rendering — Phase 31 (31-01)
- [x] Fallback-aware rendering: main.lua wired through assets.lua; game renders identically when no assets present — Phase 31 (31-01)
- [x] Hex stencil masking: terrain images clipped to hex boundary via Love2D stencil API — Phase 32 (32-01)
- [x] 15 terrain tile PNGs: programmatic textures (grass, trees, peaks, waves, bricks, etc.) replacing colored polygons — Phase 32 (32-01)
- [x] Terrain tile generator tool: generate_tiles.lua with --generate-tiles CLI flag for on-demand regeneration — Phase 32 (32-01)
- [x] Unit sprite pipeline: programmatic Spearman spritesheets (idle, attack, defend, death, portrait) with animation state machine — Phase 33 (33-01)
- [x] Minimal TOML parser for sprite.toml metadata (sections, dotted sections, string/number values) — Phase 33 (33-01)
- [x] Animation module: Quad-based spritesheet frame cycling, per-unit state tracking, facing/flip logic — Phase 33 (33-01)
- [x] Portrait rendering in unit panel sidebar with automatic layout adjustment — Phase 33 (33-01)
- [x] Standalone asset viewer: browse terrain/unit assets, cycle animations, zoom/flip, metadata display — Phase 34 (34-01)
- [x] Programmatic sprites for all 16 priority units (3 faction leaders + 13 recruits) with unique weapons, colors, and body scales — Phase 35 (35-01)
- [x] Generic humanoid drawing system with 8 weapon types and configurable per-unit appearance — Phase 35 (35-01)
- [x] TileSnapshot includes defense, movement_cost, healing fields in state JSON — Phase 36 (36-01)
- [x] norrust_get_unit_terrain_info() FFI: unit-specific effective defense/movement cost with fallback chain — Phase 36 (36-01)
- [x] Right-click terrain inspection panel: terrain type, defense %, movement cost, healing, unit-specific stats — Phase 36 (36-01)
- [x] Ghost movement: two-step click-to-ghost-to-commit replacing immediate move, with translucent preview and adjacent enemy highlighting — Phase 37 (37-01)
- [x] Monte Carlo combat simulation: simulate_combat() runs 100 trials without mutating state, returns damage distributions and kill probabilities — Phase 38 (38-01)
- [x] norrust_simulate_combat() FFI: range-aware (melee/ranged) combat preview with terrain defense and ToD modifiers — Phase 38 (38-01)
- [x] Combat preview panel: click enemy shows damage×strikes, hit %, damage range (min-mean-max), kill % for both sides before committing — Phase 38 (38-01)
- [x] Terrain defense visibility in combat preview: attacker and defender terrain defense % shown in panel — Phase 39 (39-01)
- [x] Auto-preview on re-ghost: moving to different hex adjacent to same enemy auto-updates combat preview for "attack from" comparison — Phase 39 (39-01)
- [x] AI-generated unit sprites for all 16 priority units via Gemini 2.0 Flash pipeline (92 PNG files) — Phase 44-46 (v1.7)
- [x] Python sprite generation pipeline (generate_sprites.py + unit_prompts.toml) replacing obsolete Lua generator — Phase 45 (45-01)
- [x] Combat animations: attack-melee, attack-ranged, defend, death triggered during gameplay with timer-based return to idle — Phase 47 (47-01)
- [x] Sprite pipeline v2: single-pose Gemini generation with PIL validation, retry loop, portrait pipeline — Phase 94 (94-01, 94-02)
- [x] Derived death animation (tilt + fade from idle at render time, no death.png needed) — Phase 95 (95-01)
- [x] Project-level tools/ directory for utilities (generate_sprites.py relocated from norrust_love/tools/) — Phase 96 (96-01)
- [x] Faction-based unit facing (chess-style: faction 0→right, faction 1→left) — Phase 47 (47-01)
- [x] Ranged attack support in ghost movement: hex.distance() + get_attackable_enemies() with max_range — Phase 47 (47-01)
- [x] Ghost path visualization: A* path from unit to ghost position displayed as hex highlights + connecting line — Phase 48 (48-01)
- [x] norrust_find_path FFI exposing Rust A* pathfinder for Lua path queries — Phase 48 (48-01)
- [x] Movement interpolation: smooth sliding along A* path when moves committed, replacing teleport — Phase 49 (49-01)
- [x] Combat movement: melee attackers lunge toward defenders before attack, ranged stay in place — Phase 50 (50-01)
- [x] Distance-based ranged attack detection using hex.distance() — Phase 50 (50-01)
- [x] Maximized window on launch via love.window.maximize() — Phase 51 (51-01)
- [x] Alphabetical faction ordering (Elves, Loyalists, Orcs) in selection screen — Phase 51 (51-01)
- [x] Scroll wheel board zoom (0.5x to 3.0x) with zoom-aware click, pan, and camera lerp — Phase 52 (52-01)
- [x] Combat preview damage_per_hit includes ToD modifier for consistent display — Phase 52 (52-01)
- [x] Board rendering scissor-clipped at right panel edge — no units hidden under sidebar — Phase 53 (53-01)
- [x] Click input guarded against panel region — clicks in sidebar don't hit board hexes — Phase 53 (53-01)
- [x] Dialogue TOML schema (DialogueEntry: id, trigger, turn, faction, text) with per-scenario dialogue files — Phase 54 (54-01)
- [x] DialogueState runtime with one-shot query semantics and fired-tracking via HashSet — Phase 54 (54-01)
- [x] norrust_load_dialogue + norrust_get_dialogue FFI functions returning JSON dialogue arrays — Phase 54 (54-01)
- [x] Lua FFI wrappers for dialogue loading and querying in norrust.lua — Phase 55 (55-01)
- [x] Narrator panel rendering in right sidebar with word-wrapped text and panel priority integration — Phase 55 (55-01)
- [x] Dialogue triggering at scenario_start, turn_start, turn_end with auto-clear on turn change — Phase 55 (55-01)
- [x] Scrollable dialogue history panel accessible via H key, accumulating all triggered dialogue per scenario — Phase 56 (56-01)
- [x] leader_attacked dialogue trigger firing on first attack against a unit with "leader" ability — Phase 57 (57-01)
- [x] hex_entered dialogue trigger firing when a unit moves to a specific hex (col/row match) — Phase 57 (57-01)
- [x] DialogueEntry col/row optional fields for location-based trigger filtering — Phase 57 (57-01)
- [x] TOML save/load system: save.lua with serializer, custom [[units]] parser, F5/F9 hotkeys — Phase 58 (58-01)
- [x] norrust_set_turn + norrust_set_active_faction + norrust_set_unit_combat_state FFI functions — Phase 58 (58-01)
- [x] Save files in Love2D save directory (~/.local/share/love/norrust/saves/) with date-first naming — Phase 58 (58-01)
- [x] Combat state preservation in saves: HP, XP, moved, attacked per unit — Phase 59 (58-01)
- [x] Campaign save/load: [campaign], [[veterans]], [state] sections in save TOML — Phase 60 (60-01)
- [x] Trigger zone and dialogue fired state preservation across save/load — Phase 60 (60-01)
- [x] Auto-save on end turn (before AI takes turn) — Phase 60 (60-01)
- [x] 4 new FFI functions: get/set trigger_zones_fired, get/set dialogue_fired — Phase 60 (60-01)
- [x] Persistent unit identity via Lua-generated 8-char hex UUIDs — Phase 61 (61-01)
- [x] Campaign roster tracking all units (alive/dead) across scenarios with TOML serialization — Phase 61 (61-01)
- [x] Fixed veteran placement uid collision (pre-existing: engine doesn't auto-increment on place_unit) — Phase 61 (61-01)
- [x] Veteran recruitment in recruit panel (roster entries as free options with [V] prefix) — Phase 62 (62-01)
- [x] Preset/campaign scenarios skip faction picker (auto-assign factions) — Phase 62 (62-01)

- [x] TCP agent server on localhost:9876 with line-based protocol (LuaSocket in Love2D) — Phase 63 (63-01)
- [x] Python agent client library (tools/agent_client.py, stdlib only) — Phase 63 (63-01)
- [x] AI vs AI mode: Python script + Love2D --ai-vs-ai for automated testing — Phase 64 (64-01)
- [x] Unit content directories: data/units/<name>/ with TOML + sprites together — Phase 70 (70-01)
- [x] Registry loader subdirectory scanning: <dirname>/<dirname>.toml convention — Phase 70 (70-01)
- [x] Scenario directories: scenarios/<name>/ with board.toml, units.toml, dialogue.toml — Phase 71 (71-01)
- [x] Symlink pattern for Love2D VFS: norrust_love/<dir> -> ../<dir> + setSymlinksEnabled — Phase 71 (71-01)
- [x] File-first sound loading from data/sounds/ with procedural SoundData fallback — Phase 72 (72-01)
- [x] Per-scenario music support via optional music.ogg in scenario directories — Phase 72 (72-01)
- [x] CONTRIBUTING.md with content authoring guides for non-programmer contributors — Phase 73 (73-01)
- [x] Idle animation frame cycling (sprite key normalization fix) — Phase 74 (74-01)
- [x] Death animation visibility with timed cleanup — Phase 74 (74-01)
- [x] Menu music looping on scenario select with transitions to/from gameplay — Phase 75 (75-01)
- [x] Global sound controls (mute/volume) accessible from all game screens — Phase 75 (75-01)
- [x] Help overlay showing all keybindings, toggled with ? key — Phase 76 (76-01)
- [x] Clickable sidebar buttons (End Turn, Recruit, Help) for mouse-only play — Phase 77 (77-01)

- [x] Save management UI: list/load/delete saves from main menu with metadata display — Phase 90 (90-01)
- [x] Save display_name field with UI prompt for editing labels — Phase 91 (91-01)
- [x] Veteran deploy/bench selection screen for campaign overflow — Phase 92 (92-01)
- [x] Castle hex validation for veteran placement (FFI matches apply_recruit rules) — Phase 92 (92-01)
- [x] Campaign faction assignment from TOML config (faction_0/faction_1) — Phase 92 (92-01)
- [x] Veterans healed to full HP on scenario carry-over — Phase 92 (92-01)

- [x] Exit button with inline save confirmation (Y save+exit, N exit, Esc cancel) on game board — Phase 93 (93-01)
- [x] Q/Escape quit from main menu (PICK_SCENARIO) — Phase 93 (93-01)
- [x] Escape from setup/faction-pick modes returns to menu — Phase 93 (93-01)
- [x] Mode-dispatch table for input handling (keypressed refactor from 530→30 lines) — Phase 93 (93-01)
- [x] json_escape() helper for all FFI JSON serialization (3 critical null/escape fixes) — Phase 93 (93-01)
- [x] Reverse hex→unit index (HashMap<Hex, u32>) for O(1) position lookups — Phase 93 (93-01)
- [x] State cache with dirty-flag invalidation on NorRustEngine — Phase 93 (93-01)
- [x] Rust sole authority for next_unit_id (removed Lua dual-tracking) — Phase 93 (93-01)

- [x] AI leader discipline: stays on keep until castle slots filled, returns to keep when off-keep with gold — Phase 97 (97-01)
- [x] Mixed unit type recruitment: round-robin selection instead of always most expensive — Phase 97 (97-01)
- [x] cheapest_recruit_cost parameter for AI planning functions — Phase 97 (97-01)
- [x] evaluate_state(state, faction) holistic board evaluation function — Phase 98 (98-01)
- [x] 1-ply lookahead AI: plan_unit_action() clone-simulate-evaluate for per-unit action selection — Phase 99 (99-01)
- [x] Shared AI decision logic: ai_take_turn and ai_plan_turn both use plan_unit_action — Phase 99 (99-01)
- [x] Multi-ordering turn planner: plan_full_turn() tries 5 unit orderings, picks best final state — Phase 100 (100-01)
- [x] ActionRecord replay: ai_take_turn replays best plan from plan_full_turn — Phase 100 (100-01)
- [x] Ranged distance bonus: +2.0 for distance-2 ranged attacks (avoids melee retaliation) — Phase 101 (101-01)
- [x] Focus fire bonus: up to +5.0 for attacking wounded enemies to secure kills — Phase 101 (101-01)
- [x] Wounded unit retreat: units below 30% HP retreat toward healing terrain when no kill available — Phase 101 (101-01)
- [x] retreat_toward_healing() helper: finds nearest healing hex on board for wounded unit routing — Phase 101 (101-01)
- [x] simulate_recruitment() in planning clone: placeholder units for turn planner to evaluate recruit-first strategy — Phase 102 (102-01)
- [x] recruit_defs (cost, movement) tuples threaded through plan_full_turn/run_turn_ordering — Phase 102 (102-01)
- [x] build_recruit_defs() FFI helper: extracts real unit data from faction registry for planner consumption — Phase 102 (102-01)
- [x] ai_take_turn_with_recruits/ai_plan_turn_with_recruits: recruit-aware AI entry points — Phase 102 (102-01)
- [x] 2-ply lookahead for all units: evaluate_with_opponent_response simulates enemy greedy response before scoring — Phase 103 (103-01)
- [x] depth parameter on plan_unit_action: configurable 1-ply vs 2-ply lookahead — Phase 103 (103-01)
- [x] CampaignState owned by Rust engine (veterans, gold, roster, scenario index) — Phase 104 (104-01)
- [x] UUID generation via xorshift64 in Rust campaign module — Phase 104 (104-01)
- [x] SaveState DTO with serde Serialize/Deserialize for full engine serialization — Phase 105 (105-01)
- [x] norrust_save_json/norrust_load_json FFI functions for single-call save/load — Phase 105 (105-01)
- [x] Registry-based unit restore: saves only runtime state, attacks/defense from registry — Phase 105 (105-01)
- [x] Lua save/load wired to single FFI calls, replacing ~14 manual restore calls — Phase 106 (106-01)
- [x] TOML serialization dead code removed from save.lua — Phase 106 (106-01)
- [x] Legacy TOML/old-JSON save backward compatibility preserved — Phase 106 (106-01)
- [x] Recursive registry loader: load_from_dir scans arbitrarily deep subdirectories — Phase 108 (108-01)
- [x] Tree-structured unit directories mirroring advancement paths (base/evolution1/evolution2/) — Phase 108 (108-01)
- [x] 95-unit registry across 4 factions (Loyalists, Rebels, Northerners, Undead) audited and documented — Phase 107 (107-01)
- [x] All 95 unit TOMLs complete: Walking Corpse (L0→Soulless) and Soulless (L1 terminal) created from Wesnoth WML — Phase 109 (109-01)
- [x] 4 factions fully defined: loyalists, rebels, northerners, undead with correct leaders and recruit groups — Phase 109 (109-01)
- [x] 4 recruit groups complete: human_base (8), rebel_base (7), northerner_base (7), undead_base (7) — all members resolve to real units — Phase 109 (109-01)
- [x] Faction naming aligned to Wesnoth vocabulary: elves→rebels, orcs→northerners — Phase 109 (109-01)
- [x] Sprite generation tool with all 114 unit definitions and tree-path support — Phase 110 (110-01)
- [x] 4 factions (loyalists, rebels, northerners, undead) fully operational with correct campaign references — Phase 111 (111-01)
- [x] Config-driven debug data generator (tools/generate_debug.py) with per-unit override support — Phase 112 (112-01)
- [x] --debug launch flag switching Love2D to debug/data/ with X/G/T cheat keys — Phase 113 (113-01)
- [x] 3 cheat FFI functions (cheat_set_xp, cheat_add_gold, cheat_set_turn) as pure additions — Phase 113 (113-01)

### Active (In Progress / Deferred)

- [ ] Sprite generation for all 114 units (deferred — circles serve as placeholders)
- [ ] Missing advancement target unit definitions (General, many level 3+ units) — advancement silently fails when target def doesn't exist

### Out of Scope

- TOML editor UI for modding — post-MVP
- Multiplayer — post-MVP (architecture supports it via Action queue)

## Constraints

### Technical
- Clean-room rewrite — no code copied from `/home/chris/git_home/wesnoth` (reference only)
- Simulation core must be pure Rust (no graphics/UI dependencies)
- Presentation layer: Love2D 11.5 (norrust_love/)
- Integration via C ABI (extern "C" + LuaJIT FFI)

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
| Tile.defense as middle tier in combat fallback | unit.defense[id] → tile.defense → unit.default_defense; preserves test pattern of bare-board with default_defense=0 | 2026-03-02 | Active |
| gold: [u32; 2] array (not HashMap) | Exactly 2 factions; array simpler; indexed by faction as usize | 2026-03-02 | Active |
| Village income on newly-active faction's turn start | "Gold at start of turn" semantics; village captured this turn pays next time you're active | 2026-03-02 | Active |
| apply_recruit() free function (not Action enum variant) | Advance pattern: registry-free, headlessly testable; bridge handles cost lookup + Unit construction | 2026-03-02 | Active |
| Castle validity = terrain_id == "castle" only | No leader adjacency requirement — keeps recruitment simple; factional restriction via scenario design | 2026-03-02 | Active |
| apply_starting_gold() as separate bridge call (not auto in load_factions) | GDScript knows both faction IDs only at PLAYING transition; explicit timing beats implicit side-effects | 2026-03-02 | Active |
| abilities: Vec<String> on Unit copied from UnitDef at spawn/advance | Same pattern as attacks/resistances; apply_action() stays registry-free; "leader" gates recruitment | 2026-03-02 | Active |
| _inspect_unit_id separate from _selected_unit_id | Selection is movement intent; inspection is information — mixing would break enemy stat viewing | 2026-03-02 | Active |
| AttackSnapshot flat struct (not reusing AttackDef) | Snapshot layer independent of schema layer; clean serialization DTO | 2026-03-02 | Active |
| Opaque NorRustEngine pointer for C ABI | Mirrors NorRustCore without Godot deps; all functions take *mut NorRustEngine as first param | 2026-03-03 | Active |
| Caller-frees string/array memory management | CString::into_raw for returns, norrust_free_string/norrust_free_int_array for cleanup | 2026-03-03 | Active |
| Both bridges coexist (GDExtension + C ABI) | No conditional compilation; GDExtension preserved until Love2D client verified (Phase 27) | 2026-03-03 | Active |
| hex_to_pixel/pixel_to_hex pure math in Love2D | Godot TileMap unavailable; pointy-top odd-r offset formulas are well-defined | 2026-03-03 | Active |
| Inline JSON decoder in norrust.lua (~90 lines) | Love2D/LuaJIT has no JSON parser; external deps prohibited | 2026-03-03 | Active |
| push/pop camera transform in Love2D | Separates board-space hex drawing from screen-space UI cleanly | 2026-03-03 | Active |
| ffi.gc destructor on engine pointer | Automatic cleanup on GC; no explicit free required; memory-safe even if love.quit not called | 2026-03-03 | Active |
| reachable_set as string-keyed lookup ("col,row" → true) | O(1) hex containment checks for click handler; array iteration O(n) insufficient | 2026-03-03 | Active |
| TriggerZone with PendingSpawn: pre-built Units at load time | Avoids registry access at trigger-fire time; IDs assigned sequentially from next_unit_id | 2026-03-03 | Active |
| Two-phase drain pattern for spawn placement | Collect spawns into local Vec then place; avoids mutable borrow conflict on state | 2026-03-03 | Active |
| trigger_faction defaults to 0 via serde default | Most triggers are player-activated; AI-triggered zones opt-in | 2026-03-03 | Active |
| 3-tier check_winner() priority: objective hex → turn limit → elimination | Most specific condition first; universal fallback last; future scenarios mix and match | 2026-03-03 | Active |
| check_winner() as GameState method | Headless-testable without FFI; direct access to state fields | 2026-03-03 | Active |
| LoadedBoard struct from load_board() | Board + scenario metadata returned together; scenarios self-describe win conditions | 2026-03-03 | Active |
| preset_units flag on SCENARIOS table | Crossing uses TOML units; contested uses manual placement; both paths coexist | 2026-03-03 | Active |
| Campaign progression is client-side (Love2D) | Engine is per-scenario; load_board() replaces GameState; client manages campaign_index, veterans, gold | 2026-03-03 | Active |
| Engine reuse across campaign scenarios | load_board() creates fresh GameState but keeps registries; avoids re-loading data/factions | 2026-03-03 | Active |
| unit_from_registry() + field override for veterans | Full combat stats from registry, then override hp/xp/xp_needed/advancement_pending with carried values | 2026-03-03 | Active |
| Veterans placed on leftmost keep + adjacent castles | Player's keep is leftmost; placement skips occupied hexes from preset units | 2026-03-03 | Active |
| Right-click for terrain inspection (not left-click) | Left-click on empty reachable hex triggers movement; right-click avoids conflict | 2026-03-04 | Active |
| Dedicated FFI for unit-terrain queries (not UnitSnapshot expansion) | Avoids per-frame bloat; reusable for combat preview | 2026-03-04 | Active |
| Ghost movement purely client-side (no engine state until commit) | Clean cancel, no rollback needed | 2026-03-04 | Active |
| Lua-side hex neighbor table (not FFI) for adjacency | Simple odd-r offset lookup, no cross-boundary overhead | 2026-03-04 | Active |
| Monte Carlo with independent RNG seeds (i+1) per trial | Reproducible but varied results; no game state mutation | 2026-03-04 | Active |
| Range-aware combat simulation (melee/ranged from distance) | FFI calculates hex distance to pick correct attack type; melee-only defenders don't retaliate against ranged | 2026-03-04 | Active |
| Double-click to confirm attack from preview | First click = preview, second click = execute; natural interaction pattern | 2026-03-04 | Active |
| Terrain defense on CombatPreview struct (not separate query) | Values already computed in FFI; avoids extra round-trip | 2026-03-04 | Active |
| Auto-preview preserves target across re-ghost | Capture prev_target before cancel, re-check in new adjacency list | 2026-03-04 | Active |
| ctx table pattern for Lua module extraction | Build mutable context table per-frame/per-call; modules access state via ctx.field | 2026-03-04 | Active |
| Campaign ctx writeback pattern | build_campaign_ctx() → call → apply_campaign_ctx() bridges state mutations across module boundary | 2026-03-04 | Active |
| Gemini 2.0 Flash for sprite generation (not MCP) | nana-banana MCP returns text, not images; direct API via curl/python | 2026-03-05 | Active |
| Single-pose-per-call sprite generation | Grid sheets unreliable; individual poses with reference image feedback more consistent | 2026-03-09 | Active |
| Direction auto-flip removed | COM heuristic unreliable; manual fix via magick -flop | 2026-03-09 | Active |
| Death derived at render time | AI-generated death sprites low quality; idle tilt+fade is better | 2026-03-09 | Active |
| tools/ as project utility home | Not part of Love2D client; project-level utilities live at root | 2026-03-09 | Active |
| Flood-fill bg removal from corners | Preserves interior detail unlike global color replace; fuzz 20% general, 8% portraits | 2026-03-05 | Active |
| White background prompts for AI sprites | Green screen unreliable from AI; white background + flood-fill more consistent | 2026-03-05 | Active |
| Generic animation suffixes + TOML character specifics | Decouples character art from animation logic; adding units = adding TOML entry | 2026-03-05 | Active |
| Per-unit portrait_fuzz in unit_prompts.toml | White-haired units need lower fuzz; configurable without CLI override | 2026-03-05 | Active |
| love.window.maximize() instead of desktop fullscreen | Desktop fullscreen removes title bar close button; maximize preserves it | 2026-03-05 | Active |
| table.sort factions by name after engine load | Consistent alphabetical order; Rust returns arbitrary order from Vec | 2026-03-05 | Active |
| translate→scale→translate for zoom transform | Clean separation: origin centers, zoom scales, offset pans in board-space | 2026-03-05 | Active |
| Effective viewport = vp/zoom for pan bounds | Zooming in needs more pan range; automatic adjustment | 2026-03-05 | Active |
| setScissor in pixel coords for board clipping | UI_SCALE-divided coords don't work with Love2D scissor API | 2026-03-05 | Active |
| Single click guard at top of mousepressed | Covers all click paths (right-click, setup, playing) with one check | 2026-03-05 | Active |
| DialogueState per-scenario (not Registry) | Dialogue loaded/reset per scenario; simpler than global registry | 2026-03-05 | Active |
| One-shot via HashSet fired IDs | Simple fired tracking; reset clears for scenario restart | 2026-03-05 | Active |
| FFI returns JSON array of {id, text} | Minimal payload; client decides rendering | 2026-03-05 | Active |
| Dialogue path derived from board filename | board.toml → board_dialogue.toml; no separate config needed | 2026-03-05 | Active |
| Narrator panel lowest priority in panel chain | Hidden by combat/recruit/unit/terrain panels; dialogue is ambient | 2026-03-05 | Active |
| turn_end fires before engine end_turn | Captures ending turn/faction before state advances | 2026-03-05 | Active |
| Custom parse_save_toml in save.lua | toml_parser.lua doesn't support [[arrays-of-tables]]; kept for legacy load only | 2026-03-06 | Active |
| Save files in Love2D save directory | t.identity="norrust" → ~/.local/share/love/norrust/saves/; game data stays read-only | 2026-03-06 | Active |
| Date-first flat save naming | YYYY-MM-DD_HHMMSS_scenario.toml; chronological sort without subdirectories | 2026-03-06 | Active |
| F9 works from any game mode | Must load after restart when in PICK_SCENARIO; handler before mode-specific blocks | 2026-03-06 | Active |
| FFI state query returns JSON, restore takes individual calls or JSON | Consistent pattern for serializable engine state | 2026-03-06 | Active |
| Auto-save before AI turn (on 'e' key) | Captures player intent before AI moves; player can undo AI by loading | 2026-03-06 | Active |
| campaign_ctx parameter for optional campaign context in save | nil for standalone, table for campaign; single save function | 2026-03-06 | Superseded (v3.7 — engine owns campaign) |
| 8-char hex UUID for unit identity (not RFC 4122) | Sufficient for campaign scope; no external deps | 2026-03-06 | Active |
| Roster is campaign-only (nil for standalone) | Standalone scenarios don't need identity tracking | 2026-03-06 | Active |
| Local uid tracking in veteran placement loop | Engine's place_unit doesn't increment next_unit_id | 2026-03-06 | Active |
| Global sound controls before mode-specific blocks | M/-/= must work from any screen including menu where music plays | 2026-03-07 | Active |
| Explicit stop_music() on scenario/campaign selection | Belt-and-suspenders: don't rely solely on scenario_loaded event timing | 2026-03-07 | Active |
| Sidebar buttons via shared.buttons coordinate table | Draw sets coordinates, mousepressed reads them; avoids upvalue overflow | 2026-03-07 | Active |
| Auto-save on player win only (not every end turn) | Less aggressive; F5 manual save available anytime | 2026-03-07 | Active |
| Context tables for LuaJIT upvalue management | Group related locals into tables (scn, sel, ghost, campaign, dlg, camera); structural fix for 60-upvalue limit | 2026-03-07 | Active |
| vars table for mutable scalar sharing | Wraps game_mode, game_over, etc. in table so mutations propagate between modules | 2026-03-07 | Active |
| Module context passing via ctx table | Build ctx in love.load with all state/helpers, pass to module.init(); clean module boundary | 2026-03-07 | Active |
| MODES/game_data/mods tables for upvalue reduction | Constants, game data, and pass-through modules grouped into tables; 55→46 upvalues | 2026-03-07 | Active |
| Named draw constants for sidebar geometry | SIDEBAR_W/PAD/X_OFF + color constants replace 100+ magic number sites in draw.lua | 2026-03-07 | Active |
| Tile color cache at scenario load | build_tile_color_cache() avoids per-frame parse_html_color; rebuilt on scenario load | 2026-03-07 | Active |
| let-else error returns in FFI | All Option<GameState> access uses let-else with negative error codes; zero unwrap() | 2026-03-07 | Active |
| CampaignState on NorRustEngine (not GameState) | GameState resets per scenario; campaign persists across scenarios; clean ownership | 2026-03-10 | Active |
| UUID via xorshift64 (combat::Rng) | Consistent with existing RNG pattern; no external deps | 2026-03-10 | Active |
| id_map cleared between scenarios | engine_id → uuid mapping is per-scenario; roster persists | 2026-03-10 | Active |
| SaveState DTO for serialization (not Serialize on GameState) | GameState has HashMap<Hex,_> keys + RNG; SaveState is clean boundary | 2026-03-10 | Active |
| Registry-based unit restore from saves | Saves only runtime state; attacks/defense from registry on load | 2026-03-10 | Active |
| Board reload from path on save restore | Terrain + trigger zones come from TOML; not duplicated in save | 2026-03-10 | Active |
| Single FFI call save/load from Lua | norrust.save_json()/load_json() replace ~14 manual calls; engine owns all state | 2026-03-10 | Active |
| Format detection via top-level field presence | data.board_path = new format, data.game = old format; no version flags | 2026-03-10 | Active |
| Legacy _legacy_restore() for old saves | Shared by both old JSON and TOML; avoids code duplication | 2026-03-10 | Active |
| Recursive scan_dir with load_flat flag | Flat TOMLs only at root; subdirs use dirname.toml convention at any depth | 2026-03-11 | Active |
| Tree-structured unit directories | data/units/base/evolution/name.toml mirrors advancement paths; max depth 4 | 2026-03-11 | Active |
| Non-faction scraped TOMLs deleted | 210 drakes/dwarves/dunes/ships removed; only 4-faction units + legacy test units kept | 2026-03-11 | Active |

## Tech Stack

| Layer | Technology | Notes |
|-------|------------|-------|
| Simulation Core | Rust (norrust_core) | Headless, pure logic; cdylib + rlib |
| Presentation | Love2D 11.5 + LuaJIT | 2D hex rendering via FFI (norrust_love/) |
| Integration | C ABI + LuaJIT FFI | extern "C" functions in ffi.rs → norrust.lua |
| Data Format | TOML / JSON | Config files, state export |
| Reference | Wesnoth source | Read-only at `/home/chris/git_home/wesnoth` |

## Success Criteria

- A complete, playable 2-player match runs from start to win/loss
- External Python script can query game state and submit actions via socket
- All game rules defined in data files, not hardcoded

---
*Created: 2026-02-27*
*Last updated: 2026-03-11 after Phase 111*
| AI leader discipline + mixed recruitment | Smarter AI spending; leader stays on keep, round-robin unit selection | 2026-03-10 | Active |

| evaluate_state centered HP ratio | Raw ratio breaks zero-sum symmetry; (own/total-0.5)*2 centers at 0 | 2026-03-10 | Active |

| No baseline comparison for AI attacks | Baseline made AI too conservative (refused attacks when retaliation worsened score); always pick best attack | 2026-03-10 | Active |

| March heuristic for move-only AI | Clone-evaluate per hex too slow in debug; distance-to-enemy heuristic sufficient | 2026-03-10 | Active |

| Rotation-based unit ordering | Deterministic, no RNG; K=5 rotations covers diverse orderings for implicit coordination | 2026-03-10 | Active |

| ActionRecord replay for ai_take_turn | Both ai_take_turn and ai_plan_turn share identical planning via plan_full_turn | 2026-03-10 | Active |

| Tactical bonuses as tie-breakers | evaluate_state is primary driver; +2.0/+5.0 bonuses steer among similar-score options | 2026-03-10 | Active |

| Enemy HP captured before simulation | Enemy may die during simulated combat; pre-sim ratio needed for focus fire scoring | 2026-03-10 | Active |

| Wounded retreat overrides attack only when no kill possible | Securing kills always worth the risk; retreat is fallback when no kill achievable | 2026-03-10 | Active |

| Placeholder units for recruit simulation | ai.rs has no registry; hp=20/dmg=5/str=2 placeholders sufficient for planning | 2026-03-10 | Active |

| All units 2-ply (not leader-only) | 20ms total ≪ 30s bound; all units benefit from opponent response | 2026-03-10 | Active |

| Greedy opponent response in 2-ply | No recursive depth; catches oscillation without exponential blowup | 2026-03-10 | Active |

*Last updated: 2026-03-11 after Phase 110 Sprite Generation.*
