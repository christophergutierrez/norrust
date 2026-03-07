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
| v1.5 Combat UX | 2026-03-04 | ~1 day | 3 phases, 3 plans |
| v1.6 Codebase Cleanup | 2026-03-04 | ~1 day | 4 phases, 4 plans |
| v1.7 Enhanced Unit Sprites | 2026-03-05 | ~1 day | 4 phases, 4 plans |
| v1.8 Movement & Animation Polish | 2026-03-05 | ~1 day | 3 phases, 3 plans |
| v1.9 UI Polish | 2026-03-05 | ~1 day | 3 phases, 3 plans |
| v2.0 Dialogue System | 2026-03-05 | ~1 day | 4 phases, 4 plans |
| v2.1 Save System | 2026-03-06 | ~1 day | 4 phases, 3 plans |
| v2.2 AI & Agents | 2026-03-06 | ~1 day | 3 phases, 3 plans |
| v2.3 Combat Depth & Campaign | 2026-03-07 | ~1 day | 5 phases, 5 plans |
| v2.4 Content Organization | 2026-03-07 | ~1 day | 4 phases, 4 plans |
| v2.5 Animation Fixes | 2026-03-07 | ~10min | 1 phase, 1 plan |
| v2.6 Music | 2026-03-07 | ~15min | 1 phase, 1 plan |
| v2.7 Controls & Help | 2026-03-07 | ~30min | 2 phases, 2 plans |
| v2.8 Code Cleanup & Architecture | In Progress | - | 5 phases |

---

## v2.8 Code Cleanup & Architecture (In Progress)

**Theme:** Refactor main.lua monolith, consolidate draw.lua constants, harden FFI boundary, split shared table.

**Phases:**
| Phase | Name | Status |
|-------|------|--------|
| 78 | Upvalue Contexts | Not started |
| 79 | Input Handlers | Not started |
| 80 | Draw Constants | Not started |
| 81 | FFI Hardening | Not started |
| 82 | Shared Table Split | Not started |

---

## v2.7 Controls & Help

**Completed:** 2026-03-07
**Duration:** ~30min

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 2 |
| Tests | 121 Rust |

### Key Accomplishments

- **Help overlay** — ? key toggles keybinding overlay showing all controls in 3 columns
- **Sidebar buttons** — clickable End Turn, Recruit, Help buttons at bottom of sidebar
- **Auto-save reduction** — saves only on player win instead of every end turn

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| show_help in shared table | LuaJIT 60-upvalue limit avoidance |
| shared.buttons coordinate table | Draw sets positions, mousepressed reads them; no upvalue overflow |
| love.keypressed() delegation for button clicks | Reuses existing key handler logic |
| Auto-save on win only | User preference; F5 manual save still available |

---

## v2.6 Music

**Completed:** 2026-03-07
**Duration:** ~15min

### Stats

| Metric | Value |
|--------|-------|
| Phases | 1 |
| Plans | 1 |
| Tests | 121 Rust |

### Key Accomplishments

- **Menu music** — battle_background.ogg loops on scenario select screen as menu_music.ogg
- **Music transitions** — stops on scenario/campaign start, resumes on return to menu
- **Global sound controls** — M (mute), - (volume down), = (volume up) work from any screen

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Global sound controls before mode-specific blocks | M/-/= must work from menu where music plays |
| Explicit stop_music() on scenario/campaign selection | Belt-and-suspenders; don't rely on event timing |

---

## v2.5 Animation Fixes

**Completed:** 2026-03-07
**Duration:** ~10min

### Stats

| Metric | Value |
|--------|-------|
| Phases | 1 |
| Plans | 1 |
| Tests | 121 Rust |

### Key Accomplishments

- **Idle animation fix** — sprite key normalization in love.update (`:lower():gsub(" ", "_")`)
- **Death animation fix** — dying_units table renders dead units for 1s during death animation before cleanup

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| dying_units table with timed cleanup | Decouples visual rendering from engine state; dead units visible during animation |
| 1.0 second death timer | Matches typical death animation duration |

---

## v2.4 Content Organization

**Completed:** 2026-03-07
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 |
| Plans | 4 |
| Tests | 121 Rust |

### Key Accomplishments

- **Unit content directories** — data/units/<name>/ with TOML + sprites together; Registry loader scans subdirs
- **Scenario directories** — scenarios/<name>/ with board.toml, units.toml, dialogue.toml per scenario
- **Sound asset loading** — file-first (.ogg/.wav) from data/sounds/ with procedural SoundData fallback
- **Per-scenario music** — optional music.ogg in scenario directories, loaded automatically
- **Symlink pattern** — norrust_love/<dir> -> ../<dir> + setSymlinksEnabled for Love2D VFS access
- **CONTRIBUTING.md** — content authoring guides for non-programmer contributors

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Symlink pattern for Love2D VFS | love.filesystem.mount doesn't work for plain dirs (physfs limitation) |
| Registry loader scans subdirs | <dirname>/<dirname>.toml convention for self-contained unit dirs |
| Single CONTRIBUTING.md | Covers all content types in one place vs per-directory READMEs |

---

## ✅ v2.3 Combat Depth & Campaign

**Completed:** 2026-03-07
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 5 |
| Plans | 5 |
| Tests | 121 Rust |

### Key Accomplishments

- **Combat specials** — poison, charge, backstab, slow, drain, magical, marksman, firststrike with full integration
- **Unit abilities** — steadfast, regenerates, skirmisher, leadership with stacking and ToD interaction
- **Procedural sound system** — SoundData-based SFX (hit, miss, death, move, recruit, select, turn_end) + music API
- **Night Orcs scenario** — 20x12 board, orc faction, 3 trigger zones, 30-turn limit
- **Final Battle scenario** — 24x14 board (largest), 4 trigger zones, 35-turn limit, campaign finale with 4 scenarios

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Poison ticks for ending faction | Consistent with Wesnoth; damage before opponent acts |
| Charge doubles retaliation via attacker's special | Attacker chose to charge; both sides pay the price |
| Resistance: negative=resistant, positive=weak | Matches Wesnoth convention; steadfast doubles negative only |
| Sound in shared table (not local) | LuaJIT 60-upvalue limit; shared already captured |
| Odd-r offset hex neighbors | Must match engine's Hex::from_offset() coordinate system |

---

## ✅ v2.2 AI & Agents

**Completed:** 2026-03-06
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 106 Rust + 6 Lua roster tests |

### Key Accomplishments

- **Veteran recruitment** — living roster entries as free recruitable options with [V] prefix in recruit panel
- **Preset scenario faction auto-assignment** — skip misleading faction picker for scenarios with hardcoded units
- **TCP agent server** — non-blocking LuaSocket server on localhost:9876 with line-based JSON protocol
- **Python agent client** — stdlib-only TCP client library for programmatic game control
- **AI vs AI mode** — Python script and Love2D --ai-vs-ai flag for automated testing

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Lua-side TCP server (not Rust) | Keeps simulation core pure; avoids threading |
| Line-based protocol | Simple, debuggable with nc/telnet |
| shared table for upvalue overflow | Reusable pattern for LuaJIT 60-upvalue limit |
| ai_take_turn only (no explicit end_turn) | AI calls EndTurn internally; simpler loop |

---

## ✅ v2.1 Save System

**Completed:** 2026-03-06
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 |
| Plans | 3 |
| Tests | 106 Rust + 6 Lua roster tests |

### Key Accomplishments

- **TOML save/load** — F5/F9 hotkeys, custom [[units]] parser, saves in Love2D save directory
- **Combat state preservation** — HP, XP, moved, attacked per unit in saves
- **Campaign save/load** — campaign context, veterans, trigger zones, dialogue state
- **Auto-save on end turn** — before AI takes turn for undo capability
- **Persistent unit identity** — 8-char hex UUIDs, campaign roster tracking alive/dead

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Custom parse_save_toml | toml_parser.lua doesn't support [[arrays-of-tables]] |
| Date-first flat save naming | Chronological sort without subdirectories |
| 8-char hex UUID | Sufficient for campaign scope; no external deps |

---

## ✅ v2.0 Dialogue System

**Completed:** 2026-03-05
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 |
| Plans | 4 |
| Tests | 97 (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Dialogue TOML schema** — per-scenario dialogue files with trigger types and one-shot semantics
- **Narrator panel** — right sidebar with word-wrapped text and panel priority integration
- **Scrollable dialogue history** — H key toggle, accumulating all triggered dialogue per scenario
- **Gameplay triggers** — leader_attacked and hex_entered dialogue triggers during combat/movement

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| DialogueState per-scenario | Simpler than global registry; reset on scenario change |
| One-shot via HashSet fired IDs | Simple tracking; reset clears for restart |
| Dialogue path derived from board filename | No separate config needed |

---

## ✅ v1.9 UI Polish

**Completed:** 2026-03-05
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 97 (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Maximized window on launch** — love.window.maximize() preserving title bar close button
- **Alphabetical faction order** — Elves, Loyalists, Orcs consistently sorted
- **Scroll wheel board zoom** — 0.5x to 3.0x with zoom-aware click, pan, camera lerp
- **Viewport clipping** — board rendering scissor-clipped at right panel edge; no units hidden under sidebar
- **Combat preview fix** — damage_per_hit now includes ToD modifier for consistent display

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| love.window.maximize() not desktop fullscreen | Preserves title bar with close button |
| translate→scale→translate zoom transform | Clean separation: origin centers, zoom scales, offset pans |
| setScissor in pixel coords for clipping | Love2D scissor API uses window pixels, not UI_SCALE coords |
| Single click guard at top of mousepressed | One check covers all click paths |

---

## ✅ v1.8 Movement & Animation Polish

**Completed:** 2026-03-05
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 97 (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Ghost path visualization** — A* path displayed as hex highlights + connecting line during ghost movement
- **Movement interpolation** — smooth sliding along A* path when moves committed, replacing instant teleport
- **Combat movement** — melee attackers lunge toward defenders before attack, ranged stay in place
- **Combat animation bugfix** — sprite key normalization fix (raw def_id vs lowercase directory name)
- **Ranged detection fix** — hex.distance() replaces broken attack-name matching

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| pending_anims.move for movement state | Avoids LuaJIT 60-upvalue limit in love.draw |
| Apply engine move immediately, animate rendering | Keeps engine in sync; animation is visual only |
| Callback on_complete for sequencing | Clean move→attack chaining |
| 40% approach distance for melee lunge | Contact feel without overlapping defender sprite |
| Distance-based ranged detection | Attack names are weapon names, not range descriptors |

---

## ✅ v1.7 Enhanced Unit Sprites

**Completed:** 2026-03-05
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 |
| Plans | 4 |
| Tests | 97 (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **AI sprite generation pipeline** — Gemini 2.0 Flash + Python pipeline (generate_sprites.py + unit_prompts.toml) producing 92 PNG sprite files
- **All 16 unit sprites** — AI-generated spritesheets replacing programmatic stick figures; idle, attack-melee, attack-ranged, defend, death, portrait
- **Combat animation system** — attack/defend/death animations triggered during gameplay via pending_anims timer
- **Faction-based unit facing** — chess-style: faction 0 faces right, faction 1 faces left
- **Ranged ghost attack support** — hex.distance() + get_attackable_enemies() for distance-2 targeting

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Gemini 2.0 Flash for sprite generation | Direct API; nana-banana MCP returns text not images |
| White background + flood-fill removal | More reliable than green screen from AI |
| Generic animation suffixes + TOML character specifics | Decoupled pipeline; adding units = adding TOML entry |
| pending_anims timer for animation return | Non-blocking; auto-returns to idle after duration |

---

## ✅ v1.6 Codebase Cleanup

**Completed:** 2026-03-04
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 4 |
| Plans | 4 |
| Tests | 97 (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Asset directory normalization** — 16 unit directories renamed to snake_case with normalize_unit_dir()
- **main.lua modularization** — Split into 5 modules (hex.lua, draw.lua, campaign_client.lua); 47% line reduction
- **Full Rust documentation** — //! module docs on all 15 .rs files, /// docs on all ~27 public items
- **Full Lua documentation** — --- doc comments on ~120 functions across 12 .lua files

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| ctx table pattern for module extraction | Explicit dependencies, per-frame ctx build |
| One-line docs for FFI wrappers | Clean balance of thoroughness vs readability |
| Campaign ctx writeback pattern | Bridges state mutations across module boundary |

---

## ✅ v1.5 Combat UX

**Completed:** 2026-03-04
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 97 (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI) |

### Key Accomplishments

- **Terrain inspection panel** — Right-click for terrain type, defense %, movement cost, unit-specific stats via FFI
- **Ghost movement** — Two-step click-to-ghost-to-commit with translucent preview and adjacent enemy highlighting
- **Monte Carlo combat preview** — 100-trial simulation with damage distributions, kill probabilities, terrain defense display
- **Auto-preview on re-ghost** — Moving to different hex adjacent to same enemy auto-updates combat preview

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| Ghost movement purely client-side | Clean cancel, no engine rollback needed |
| Monte Carlo with independent RNG seeds | Reproducible varied results; no game state mutation |
| Double-click to confirm attack from preview | First click = preview, second = execute |

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
*MILESTONES.md — Updated: 2026-03-07 (v2.7 Controls & Help)*
