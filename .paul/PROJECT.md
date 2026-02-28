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

### Active (In Progress)

- [ ] Rust headless simulation core (hex grid, GameState, unit positions)
- [ ] Hex grid math (axial/cube coordinates) with A* pathfinding
- [ ] Combat resolution with terrain defense and time-of-day modifiers
- [ ] Zone of Control (ZOC) enforcement
- [ ] Factions TOML schema — deferred from Phase 1

### Planned (Next)

- [ ] Complete game loop: turns, recruitment, win/loss conditions
- [ ] JSON state serialization for external AI agents
- [ ] Socket API for external scripts to query state and send actions
- [ ] Unit and terrain animations in Redot

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
*Last updated: 2026-02-27 after Phase 1*
