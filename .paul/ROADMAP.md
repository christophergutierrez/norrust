# Roadmap: The Clash for Norrust

## Overview

Five phases take the project from data schema definitions through a fully playable hex-based strategy game with external AI hooks. The Rust simulation core is built and tested headlessly before any visual work begins; Redot rendering is layered on top once the core is proven.

## Current Milestone

**v0.5 Unit Content** (v0.5.0)
Status: 🚧 In progress
Phases: 1 of 2 complete

## v0.5 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 12 | UnitDef Schema Expansion | 1 | ✅ Complete | 2026-03-01 |
| 13 | Wesnoth Data Import | TBD | Not started | - |

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

### Phase 13: Wesnoth Data Import

**Goal:** Python scraper reads Wesnoth WML from `/home/chris/git_home/wesnoth/data/core/units/`,
expands movement type macros, and outputs 218 unit TOMLs + terrain TOMLs. All units load via
`Registry::<UnitDef>::load_from_dir()` verified by integration test.
**Depends on:** Phase 12 (expanded UnitDef schema must exist before TOMLs are generated)
**Plans:** TBD (defined during /paul:plan)

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
*Roadmap updated: 2026-03-01 — Phase 12 complete, Phase 13 (Wesnoth Data Import) next*
