# Roadmap: The Clash for Norrust

## Overview

Five phases take the project from data schema definitions through a fully playable hex-based strategy game with external AI hooks. The Rust simulation core is built and tested headlessly before any visual work begins; Redot rendering is layered on top once the core is proven.

## Current Milestone

**v0.3 Unit Advancement** (v0.3.0)
Status: 🚧 In progress
Phases: 0 of 3 complete

## v0.3 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 7 | Advancement Schema | TBD | Not started | - |
| 8 | XP & Advancement Logic | TBD | Not started | - |
| 9 | Advancement Presentation | TBD | Not started | - |

## v0.3 Phase Details

### Phase 7: Advancement Schema

**Goal:** Extend data definitions and runtime structs to carry advancement information — TOML files
gain `experience`, `advances_to`, `level`; `Unit` gains `xp` and `advancement_pending`;
`UnitSnapshot` JSON exposes both for GDScript.
**Depends on:** Phase 6 (StateSnapshot JSON as sole unit data source)
**Plans:** TBD (defined during `/paul:plan`)

### Phase 8: XP & Advancement Logic

**Goal:** Implement XP gain in combat, the `Action::Advance` action, and headless balance
simulation tests that verify advancement thresholds and damage-type interactions are well-tuned.
**Depends on:** Phase 7 (advancement fields on Unit and UnitDef)
**Plans:** TBD (defined during `/paul:plan`)

### Phase 9: Advancement Presentation

**Goal:** Surface XP and advancement state in the Redot layer — XP progress in the HUD,
visual indicator when a unit is ready to advance, and click-to-advance interaction.
**Depends on:** Phase 8 (Advance action implemented and tested)
**Plans:** TBD (defined during `/paul:plan`)

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
*Roadmap updated: 2026-02-28 — v0.2 milestone created*
