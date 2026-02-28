# Roadmap: The Clash for Norrust

## Overview

Five phases take the project from data schema definitions through a fully playable hex-based strategy game with external AI hooks. The Rust simulation core is built and tested headlessly before any visual work begins; Redot rendering is layered on top once the core is proven.

## Current Milestone

**v0.1 Initial Release** (v0.1.0)
Status: ✅ Complete
Phases: 5 of 5 complete
Released: 2026-02-28

## Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & Data Schema | 3 | ✅ Complete | 2026-02-27 |
| 2 | The Headless Core | 5 | ✅ Complete | 2026-02-27 |
| 3 | The Presentation Layer | 3 | ✅ Complete | 2026-02-28 |
| 4 | The Game Loop & Polish | 4 | ✅ Complete | 2026-02-28 |
| 5 | AI Hooks & External APIs | 1 | ✅ Complete | 2026-02-28 |

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

### Phase 4: The Game Loop & Polish ✅

**Goal:** A complete, playable match from start to win/loss.
**Depends on:** Phase 3 (visual layer working)
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

**Deferred (scope trimmed):**
- Recruitment UI + castle hexes — future milestone
- Movement/attack animations — future milestone
- Village capture/ownership — future milestone

### Phase 5: AI Hooks & External APIs ✅

**Goal:** Open the doors for the machines — clean external interfaces for AI agents.
**Depends on:** Phase 4 (complete game loop)
**Completed:** 2026-02-28

**Plans:**
- [x] 05-01: JSON state serialization (StateSnapshot) + action submission (ActionRequest) + GDExtension bridge

**Delivered:**
- `snapshot.rs`: `StateSnapshot`, `UnitSnapshot`, `TileSnapshot`, `ActionRequest`
- `get_state_json()` bridge: full game state as JSON string
- `apply_action_json(json)` bridge: action submission from external clients (-99 on parse error)
- 6 new unit tests; serde_json dependency added

**Deferred:**
- Socket/TCP server — JSON layer is ready; transport layer is future work

---
*Roadmap created: 2026-02-27*
