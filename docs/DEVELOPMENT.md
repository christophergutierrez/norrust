# Development Guide

## Prerequisites

- Rust toolchain (stable) — [rustup.rs](https://rustup.rs)
- Love2D 11.5 — for running the game client (`sudo pacman -S love` on Arch)

## Repository Layout

```
norrust/
├── norrust_core/    # Rust library — simulation core + C ABI bridge
├── norrust_love/    # Love2D project — presentation layer
├── data/            # TOML data files loaded at runtime
│   ├── units/       # 322 unit definitions
│   ├── terrain/     # 14 terrain definitions
│   └── factions/    # Faction definitions
├── scenarios/       # Board and unit placement TOML files
├── docs/            # Documentation
└── tools/           # Utility scripts (scraper etc.)
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
cargo test --manifest-path norrust_core/Cargo.toml
```

The test suite runs entirely headlessly — no Love2D required. It covers:
- Unit tests in each source file (56 tests)
- Integration tests in `norrust_core/tests/` (16 tests)
- FFI integration test (1 test)

Expected output: `73 tests pass` (56 lib + 16 integration + 1 FFI).

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

## Typical Workflow

```bash
# Edit Rust code, then:
cargo build --manifest-path norrust_core/Cargo.toml
love norrust_love
```

For logic-only changes (no bridge or presentation work):

```bash
cargo test --manifest-path norrust_core/Cargo.toml
# No rebuild needed for Love2D — tests run against the rlib directly
```

## Project Structure: Key Files

| File | Role |
|------|------|
| `norrust_core/src/ffi.rs` | C ABI bridge — 36 `extern "C"` functions for LuaJIT FFI |
| `norrust_core/src/game_state.rs` | `apply_action()`, `Action`, `ActionError` |
| `norrust_core/src/board.rs` | `Board`, `Tile` structs |
| `norrust_core/src/combat.rs` | Combat resolution, time of day |
| `norrust_core/src/pathfinding.rs` | A* pathfinding, reachable hex flood-fill, ZOC |
| `norrust_core/src/ai.rs` | Built-in greedy AI planner |
| `norrust_core/src/mapgen.rs` | Procedural map generator |
| `norrust_core/src/snapshot.rs` | `StateSnapshot` JSON serialization |
| `norrust_core/src/scenario.rs` | Board/unit file loading |
| `norrust_core/tests/test_ffi.rs` | FFI integration test |
| `norrust_love/main.lua` | Complete game client — all rendering, input, HUD, AI trigger |
| `norrust_love/norrust.lua` | LuaJIT FFI bindings + inline JSON decoder |
| `norrust_love/conf.lua` | Love2D window configuration |
| `data/units/fighter.toml` | Example unit definition |
| `data/terrain/flat.toml` | Example terrain definition |
| `scenarios/contested.toml` | Default 8x5 board scenario |
| `scenarios/contested_units.toml` | Default unit placements |
