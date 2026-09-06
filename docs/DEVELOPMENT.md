# Development Guide

## Prerequisites

- Rust toolchain (stable) — [rustup.rs](https://rustup.rs)
- Python 3.10 or newer — for the headless model tools and their tests
- LuaJIT — for the headless bridge smoke test in `tools.fast_check`
- Love2D 11.5 — for running the game client (`sudo pacman -S love` on Arch)

## Repository Layout

```
norrust/
├── norrust_core/    # Rust library — simulation core + C ABI bridge
├── norrust_love/    # Love2D project — presentation layer
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

With Cargo's default target directory, the library artifacts are:
- `norrust_core/target/debug/libnorrust_core.so` — the `cdylib` loaded by Love2D via LuaJIT FFI
- `norrust_core/target/debug/libnorrust_core.rlib` — the `rlib` used by `cargo test`

The same build also produces the `greedy_driver` and `self-play` executables.
If you customize Cargo's target directory, use the corresponding paths when
launching a driver or setting `NORRUST_LIB` for Love2D.

For a release build:

```bash
cargo build --release --manifest-path norrust_core/Cargo.toml
```

## Running Tests

From the repository root, run the complete headless verification gate:

```bash
python3 -m tools.fast_check
```

It runs Rust library and both binary unit tests, the six named non-balance
integration suites, Python tool tests, and the LuaJIT bridge smoke test. It builds
the library and drivers explicitly and uses Cargo's reported artifact paths,
including when `CARGO_TARGET_DIR` or Cargo configuration selects another target
directory. The Python driver check uses the same build. LuaJIT is required; no
display is needed. Interactive Love2D/editor acceptance remains a separate check.

For focused Rust checks:

```bash
# Unit tests only (fast, recommended for development)
cargo test --lib --manifest-path norrust_core/Cargo.toml

# Driver protocol integration tests
cargo test --test driver_protocol --manifest-path norrust_core/Cargo.toml
```

The Rust test suite runs entirely headlessly — no Love2D required. Its integration
suites are `campaign`, `dialogue`, `driver_protocol`, `scenario_validation`,
`simulation`, and `test_ffi`; select each with `--test` as needed.

Expected output: the current library tests pass (`cargo test --lib`). Run the
named integration suites separately when changing the bridge or driver.

For focused Python checks:

```bash
python3 -m unittest tools.test_codex_backend tools.test_cli_commands
# All Python tools; build greedy_driver first for the real-driver check.
python3 -m unittest discover -s tools -t .
```

`tools.test_cli_commands` exercises the maintained backend and report commands as
both modules and direct scripts, including native-session start/resume with an
offline Codex substitute. `tools.fast_check` supplies `NORRUST_TEST_DRIVER` when
the driver is built outside the default target directory.

### Self-play simulations

```bash
cargo build --release --manifest-path norrust_core/Cargo.toml --bin self-play
norrust_core/target/release/self-play \
  --scenario big_battle_6 --team1 undead --team2 undead \
  --ai1 greedy --ai2 greedy --games 10 --seed 1 --threads 4 \
  --gold 300 --second-gold 0 --first team1
```

Full protocol, board check, recipes, and current baselines:
[SELF_PLAY.md](SELF_PLAY.md). Algorithms: `greedy`, `greedy-look-ahead`, `random`.

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
# These tests use the rlib. Rebuild before checking the change in Love2D.
```

The product is unreleased. Refactors should update maintained callers, tests,
and documentation together and remove superseded entry points, environment
aliases, and duplicate fields. Keep model choice in configuration; name shared
tools by responsibility and transport adapters by the runtime they invoke.
Historical experiment reports and game archives retain their original identities.

## Project Structure: Key Files

| File | Role |
|------|------|
| `norrust_core/src/ffi.rs` | C ABI bridge for LuaJIT FFI |
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
| `norrust_love/save.lua` | JSON save/load system with legacy TOML reading |
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
| `tools/fast_check.py` | Headless verification gate with freshly built Cargo artifacts |
| `tools/llm_client.py` | Provider-neutral headless model match client |
| `tools/codex_backend.py` | Native Codex session adapter with explicit model configuration |
| `tools/file_backend.py` | File transport preserving the complete client prompt |
| `tools/llm_supervisor.py` | Bounded client restart supervisor |
| `tools/request_journal.py` | Durable model request records and writer locking |
| `tools/request_recovery.py` | Read-only reconciliation of request, log, and checkpoint evidence |
| `tools/turn_agenda.py` | Validation and formatting for model-authored objective bookkeeping |
| `tools/match_report.py` | NDJSON match summaries |
| `tools/game_history.py` | SQLite game catalog import, inspection, evaluation, and maintenance |
| `tools/game_training_export.py` | Exports selected, reviewed training records |

See [LLM_CLIENT.md](LLM_CLIENT.md) for backend setup,
[GAME_HISTORY.md](GAME_HISTORY.md) for catalog commands, and
[GLOSSARY.md](GLOSSARY.md) for shared terminology.
