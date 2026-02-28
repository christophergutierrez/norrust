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
| PackedInt32Array 7-tuple for get_unit_data() | id/col/row/faction/hp/moved/attacked per unit; exhaustion state queryable from GDScript | 2026-02-28 | Active |
| Attack branch before reachable-move in _input() | Enemy click = attack intent; reachable click = move — prevents silent move-to-occupied | 2026-02-28 | Active |
| Copy UnitDef stats into Unit at spawn time | Keeps apply_action() registry-free; phase 3 bridge calls place_unit_at() once per unit | 2026-02-28 | Active |
| Board.healing_map cached at set_terrain_at() | EndTurn healing needs no registry access; healing values stored on board at terrain-set time | 2026-02-28 | Active |
| Unit carries resistances map | Copied from UnitDef at spawn; combat resistance lookup registry-free | 2026-02-28 | Active |
| get_terrain_at() bridge: Rust is terrain source of truth | _draw() queries Rust per hex; adding terrain types requires zero GDScript changes | 2026-02-28 | Active |
| Village always heals (no ownership/capture) | Simpler; capture mechanic deferred to future milestone | 2026-02-28 | Active |
| StateSnapshot DTO (not Serialize on GameState) | GameState has HashMap<Hex,_> keys + SmallRng — neither serializes cleanly via derive | 2026-02-28 | Active |
| #[serde(tag="action")] internally-tagged ActionRequest | Idiomatic JSON discriminated union; human-readable for AI clients | 2026-02-28 | Active |
| -99 JSON parse error sentinel | Distinct from ActionError codes -1..-7; AI clients can distinguish bad JSON from rejected actions | 2026-02-28 | Active |

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
*Last updated: 2026-02-28 after Phase 5 (v0.1 milestone complete)*
