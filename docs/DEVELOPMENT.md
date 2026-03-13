# Development Guide

## Prerequisites

- Rust toolchain (stable) — [rustup.rs](https://rustup.rs)
- Love2D 11.5 — for running the game client (`sudo pacman -S love` on Arch)

## Repository Layout

```
norrust/
├── norrust_core/    # Rust library — simulation core + C ABI bridge
├── norrust_love/    # Love2D project — presentation layer (29 Lua modules)
├── data/            # TOML data files loaded at runtime
│   ├── units/       # 112 unit definitions across 31 advancement trees
│   ├── terrain/     # 14 terrain definitions + PNG tiles
│   ├── factions/    # 4 faction definitions (Loyalists, Rebels, Northerners, Undead)
│   └── recruit_groups/  # Recruitable unit lists per faction
├── scenarios/       # 7 scenario directories (board + units + dialogue)
├── campaigns/       # Campaign definitions (multi-scenario progression)
├── debug/           # Debug sandbox configuration
├── docs/            # Documentation
└── tools/           # Utility scripts (scraper, sprite generator, stat verifier, etc.)
```

## Building

```bash
cargo build --manifest-path norrust_core/Cargo.toml
```

This produces two artifacts from the same source:
- `target/debug/libnorrust_core.so` — the `cdylib` loaded by Love2D via LuaJIT FFI
- `target/debug/libnorrust_core.rlib` — the `rlib` used by `cargo test`

For a release build:

```bash
cargo build --release --manifest-path norrust_core/Cargo.toml
```

## Running Tests

```bash
# Unit tests only (fast, recommended for development)
cargo test --lib --manifest-path norrust_core/Cargo.toml

# Integration tests (without balance tests)
cargo test --test test_ffi --test scenario_validation --test simulation --test campaign --test dialogue --manifest-path norrust_core/Cargo.toml
```

The test suite runs entirely headlessly — no Love2D required. It covers:
- Unit tests across 18 source modules (130 tests)
- Integration tests: campaign (8), scenario validation (23), simulation (3), dialogue (3), FFI (1)

Expected output: 130 lib tests pass, 38 integration tests pass (168 total).

**Warning:** Do not run `cargo test` without filters — the balance test suite runs thousands of
simulated games and takes a very long time. Always use `--lib` or name specific test files.

## Running the Game

```bash
# Build the .so first
cargo build --manifest-path norrust_core/Cargo.toml

# Launch Love2D
love norrust_love
```

Love2D automatically finds the `.so` relative to its source directory
(`norrust_love/../norrust_core/target/debug/libnorrust_core.so`).

To override the library path:

```bash
NORRUST_LIB=/path/to/libnorrust_core.so love norrust_love
```

The game loads unit and terrain data from `data/` relative to the project root on startup.

### Debug Mode

```bash
love norrust_love -- --debug
```

Switches data path to `debug/data/`, shows "DEBUG MODE" status, and enables cheat keys:
- **X** — max XP on selected unit
- **G** — +1000 gold
- **T** — advance turn

Debug data is generated with `python tools/generate_debug.py` from `debug/debug_config.toml`.

## Typical Workflow

```bash
# Edit Rust code, then:
cargo build --manifest-path norrust_core/Cargo.toml
love norrust_love
```

For logic-only changes (no bridge or presentation work):

```bash
cargo test --lib --manifest-path norrust_core/Cargo.toml
# No rebuild needed for Love2D — tests run against the rlib directly
```

## Project Structure: Key Files

| File | Role |
|------|------|
| `norrust_core/src/ffi.rs` | C ABI bridge — 78 `extern "C"` functions for LuaJIT FFI |
| `norrust_core/src/game_state.rs` | `apply_action()`, `Action`, `ActionError` |
| `norrust_core/src/board.rs` | `Board`, `Tile` structs |
| `norrust_core/src/combat.rs` | Combat resolution, time of day, specials |
| `norrust_core/src/pathfinding.rs` | A* pathfinding, reachable hex flood-fill, ZOC |
| `norrust_core/src/ai.rs` | Built-in greedy AI planner |
| `norrust_core/src/mapgen.rs` | Procedural map generator |
| `norrust_core/src/visibility.rs` | Fog-of-war computation (vision range, faction visibility) |
| `norrust_core/src/campaign.rs` | Campaign state, scenario progression, veteran carry-over |
| `norrust_core/src/dialogue.rs` | Dialogue trigger system |
| `norrust_core/src/save.rs` | Game state serialization/deserialization |
| `norrust_core/src/snapshot.rs` | `StateSnapshot` JSON serialization |
| `norrust_core/src/scenario.rs` | Board/unit file loading |
| `norrust_love/main.lua` | Entry point and game loop |
| `norrust_love/norrust.lua` | LuaJIT FFI bindings + inline JSON decoder |
| `norrust_love/draw.lua` | Main draw dispatcher |
| `norrust_love/input.lua` | Input state machine dispatcher |
| `norrust_love/save.lua` | Save/load system (custom TOML serializer) |
| `norrust_love/roster.lua` | UUID generation + roster CRUD for campaign tracking |
| `norrust_love/campaign_client.lua` | Campaign progression UI |
| `norrust_love/events.lua` | Event bus (decouples gameplay from UI) |

## Tools

| Script | Purpose |
|--------|---------|
| `tools/scrape_wesnoth.py` | WML → TOML unit data importer |
| `tools/generate_sprites.py` | AI-generated unit sprite pipeline (Gemini API) |
| `tools/generate_terrain.py` | AI-generated terrain tile pipeline (Gemini API) |
| `tools/generate_debug.py` | Debug sandbox data generator |
| `tools/verify_stats.py` | Audit unit stats against Wesnoth WML source |
| `tools/review_sprites.py` | Sprite validation and review |
| `tools/agent_client.py` | Python client library for the agent TCP server |
| `tools/ai_vs_ai.py` | Headless AI-vs-AI match runner |
