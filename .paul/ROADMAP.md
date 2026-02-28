# Roadmap: The Clash for Norrust

## Overview

Five phases take the project from data schema definitions through a fully playable hex-based strategy game with external AI hooks. The Rust simulation core is built and tested headlessly before any visual work begins; Redot rendering is layered on top once the core is proven.

## Current Milestone

**v0.1 Initial Release** (v0.1.0)
Status: In progress
Phases: 1 of 5 complete

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & Data Schema | 3 | ✅ Complete | 2026-02-27 |
| 2 | The Headless Core | TBD | Not started | - |
| 3 | The Presentation Layer | TBD | Not started | - |
| 4 | The Game Loop & Polish | TBD | Not started | - |
| 5 | AI Hooks & External APIs | TBD | Not started | - |

## Phase Details

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

### Phase 2: The Headless Core

**Goal:** Play the game in the terminal/tests — full simulation logic with no graphics.
**Depends on:** Phase 1 (Rust project and data schemas)
**Research:** Likely (hex coordinate systems, A* with ZOC, Wesnoth combat math)
**Research topics:** Axial vs cube hex coords, ZOC skirmisher rules, time-of-day damage tables

**Scope:**
- Hex grid coordinate system (axial or cube)
- `GameState` struct (board, units, HP, current turn)
- A* pathfinding respecting terrain costs and ZOC
- Combat resolution (RNG, terrain defense, time-of-day)
- Exhaustive Rust unit tests for pathfinding and combat

**Plans:**
- Plans to be defined during `/paul:plan`

### Phase 3: The Presentation Layer

**Goal:** See the game and click things — visual rendering connected to Rust core.
**Depends on:** Phase 2 (working headless core)
**Research:** Likely (Redot TileMap hex configuration, GDExtension data bridge)

**Scope:**
- Redot TileMap configured for hexagons
- Map loading: GDScript/Rust bridge to draw from config
- Unit spawning from Rust `GameState`
- Mouse → hex coordinate input handling
- Valid move range highlighting (queried from Rust)
- Action dispatch: Redot → Rust → visual update

**Plans:**
- Plans to be defined during `/paul:plan`

### Phase 4: The Game Loop & Polish

**Goal:** A complete, playable match from start to win/loss.
**Depends on:** Phase 3 (visual layer working)
**Research:** Unlikely (internal patterns)

**Scope:**
- End Turn logic, Time of Day progression, healing
- Recruitment UI (select and place units on Castle hexes)
- Movement interpolation and basic attack animations
- Win/loss condition detection (leader death or turn limits)

**Plans:**
- Plans to be defined during `/paul:plan`

### Phase 5: AI Hooks & External APIs

**Goal:** Open the doors for the machines — clean external interfaces for AI agents.
**Depends on:** Phase 4 (complete game loop)
**Research:** Unlikely (internal serialization patterns)

**Scope:**
- JSON export of `GameState` in Rust
- Accept JSON action string → convert to `Action`
- (Optional) Lightweight local socket server for external Python agents

**Plans:**
- Plans to be defined during `/paul:plan`

---
*Roadmap created: 2026-02-27*
