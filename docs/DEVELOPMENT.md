# Development Guide

## Prerequisites

- Rust toolchain (stable) — [rustup.rs](https://rustup.rs)
- Redot 26.1 — for running the game client
- Godot extension headers are provided by the `godot` crate (no separate install needed)

## Repository Layout

```
norrust/
├── norrust_core/    # Rust library — simulation core + GDExtension bridge
├── norrust_client/  # Redot project — presentation layer
├── data/            # TOML data files loaded at runtime
│   ├── units/       # 322 unit definitions
│   └── terrain/     # 14 terrain definitions
├── docs/            # Documentation
└── tools/           # Utility scripts (scraper etc.)
```

## Building

```bash
cargo build --manifest-path norrust_core/Cargo.toml
```

This produces two artifacts from the same source:
- `target/debug/libnorrust_core.so` — the `cdylib` loaded by Redot at runtime
- `target/debug/libnorrust_core.rlib` — the `rlib` used by `cargo test`

For a release build:

```bash
cargo build --release --manifest-path norrust_core/Cargo.toml
```

## Copying the Library

Redot loads the `.so` from `norrust_client/bin/`. After each build, copy it manually:

```bash
# Debug build
cp norrust_core/target/debug/libnorrust_core.so norrust_client/bin/

# Release build
cp norrust_core/target/release/libnorrust_core.so norrust_client/bin/
```

The `bin/` directory is checked in to the repository so Redot can find the library on first clone.

## Running Tests

```bash
cargo test --manifest-path norrust_core/Cargo.toml
```

The test suite runs entirely headlessly — no Redot required. It covers:
- Unit tests in each source file (44 tests)
- Integration tests in `norrust_core/tests/simulation.rs` (8 tests)

Expected output: `53 tests pass` (45 lib + 8 integration).

## Running the Game

1. Build and copy the `.so` (see above)
2. Open Redot 26.1
3. Import the project at `norrust_client/project.godot`
4. Press Play (F5)

The game loads unit and terrain data from `data/` relative to the project root on startup.
If the data path isn't found, units will spawn with default stats (no TOML values).

## Typical Workflow

```bash
# Edit Rust code, then:
cargo build --manifest-path norrust_core/Cargo.toml
cp norrust_core/target/debug/libnorrust_core.so norrust_client/bin/
# Switch to Redot and press Play
```

For logic-only changes (no bridge or presentation work):

```bash
cargo test --manifest-path norrust_core/Cargo.toml
# No copy needed — tests run against the rlib directly
```

## Project Structure: Key Files

| File | Role |
|------|------|
| `norrust_core/src/gdext_node.rs` | GDExtension bridge — all `#[func]` methods |
| `norrust_core/src/game_state.rs` | `apply_action()`, `Action`, `ActionError` |
| `norrust_core/src/board.rs` | `Board`, `Tile` structs |
| `norrust_core/src/combat.rs` | Combat resolution, time of day |
| `norrust_core/src/mapgen.rs` | Procedural map generator |
| `norrust_core/src/snapshot.rs` | `StateSnapshot` JSON serialization |
| `norrust_core/tests/simulation.rs` | Integration tests |
| `norrust_client/scripts/game.gd` | Main scene — all GDScript logic |
| `data/units/fighter.toml` | Example unit definition |
| `data/terrain/flat.toml` | Example terrain definition |
