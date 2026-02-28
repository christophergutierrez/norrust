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

### Active (In Progress)

- [ ] Factions TOML schema — deferred from Phase 1
- [ ] End Turn logic, Time of Day progression, healing — Phase 4
- [ ] Recruitment UI (select and place units on Castle hexes) — Phase 4
- [ ] Win/loss condition detection (leader death or turn limits) — Phase 4
- [ ] Movement interpolation and basic attack animations — Phase 4

### Planned (Next)

- [ ] JSON state serialization for external AI agents
- [ ] Socket API for external scripts to query state and send actions

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
| PackedInt32Array 5-tuple for get_unit_data() | Single bridge call: id/col/row/faction/hp per unit; GDScript loops in steps of 5 | 2026-02-28 | Active |
| Attack branch before reachable-move in _input() | Enemy click = attack intent; reachable click = move — prevents silent move-to-occupied | 2026-02-28 | Active |
| Copy UnitDef stats into Unit at spawn time | Keeps apply_action() registry-free; phase 3 bridge calls place_unit_at() once per unit | 2026-02-28 | Active |

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
*Last updated: 2026-02-28 after Phase 3*
