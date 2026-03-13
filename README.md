# The Clash for Norrust

> A hex-based strategy game with a headless Rust simulation core and a clean JSON interface
> designed from the start for both human players and AI agents.

---

## Why This Repository

Most game engines tangle rules, rendering, and state together. NorRust does not.

The entire game — movement, combat, ZOC, time-of-day, advancement, terrain effects — lives in a
pure-Rust library that has no dependency on Love2D, OpenGL, or any display system. You can
simulate a 5v5 battle, run it 1000 times, and verify the outcome in milliseconds with
`cargo test`. The Love2D frontend is a thin client that renders state it receives as JSON
through a C ABI bridge.

This matters if you want to:
- **Build an AI agent** — write it in Python, speak JSON over a socket, never touch Lua
- **Run headless simulations** — tournament brackets, balance testing, Monte Carlo rollouts
- **Extend the engine** — add a rule, write a test, verify it works before opening Love2D once
- **Learn from the architecture** — a worked example of strict separation between game logic
  and presentation

The game itself is a turn-based hex strategy inspired by Battle for Wesnoth — four factions,
seven scenarios, fog of war, save/load, and campaign progression.

---

## What Works Now

- **Playable game:** four-faction match (Loyalists, Rebels, Northerners, Undead), full
  move/attack/recruit/end-turn loop, human vs. built-in AI
- **168 passing tests:** 130 unit tests + 38 integration tests — all headless, no Love2D required
- **112 data-driven units:** stats, attacks, resistances, alignment, and advancement chains
  loaded from TOML at startup across 4 factions
- **14 terrain types:** each with movement cost, defense bonus, healing — all data-driven
- **7 scenarios:** from tutorial ambushes to full campaign battles, with dialogue triggers
- **Fog of war:** vision-range based, with shroud (unseen) and fog (previously seen) overlays
- **Save/load system:** full game state serialization with roster tracking across campaigns
- **Campaign mode:** multi-scenario progression with veteran carry-over and gold inheritance
- **Procedural map generation:** seeded noise-based terrain placement with guaranteed spawn zones
- **Built-in greedy AI:** expected-damage scoring, kill bonus, plays via the same JSON interface
  available to external agents
- **XP and advancement:** units gain XP on hits and kills, promote when thresholds are met
- **HD-2D sprite rendering:** animated unit sprites and terrain tiles with portrait system
- **Debug sandbox:** config-driven test scenarios with cheat keys for rapid iteration

> Full diagram with sequence flows: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Architecture in 30 Seconds

```
┌─────────────────────────────────────┐
│   Presentation Layer (Love2D/Lua)   │  Renders. Forwards input. Knows no rules.
│   norrust_love/ (29 Lua modules)    │
└────────────────┬────────────────────┘
                 │  LuaJIT FFI → C ABI
                 │  StateSnapshot (JSON) ← norrust_get_state_json()
                 │  Actions             → norrust_apply_move() etc.
┌────────────────▼────────────────────┐
│   C ABI Bridge (Rust)               │  78 extern "C" functions.
│   norrust_core/src/ffi.rs           │  Converts offset ↔ cubic hex coordinates.
└────────────────┬────────────────────┘
                 │  pure function calls
┌────────────────▼────────────────────┐
│   Simulation Core (Rust, headless)  │  All rules. No I/O. cargo test runs this alone.
│   game_state.rs · combat.rs         │
│   pathfinding.rs · ai.rs · mapgen.rs│
│   visibility.rs · campaign.rs       │
└─────────────────────────────────────┘
```

Every player action and every AI action takes the same path:
`apply_action()` validates, mutates state, returns `Ok(())` or an `ActionError`. No exceptions.

---

## Quick Start

**Requirements:** Rust stable toolchain, Love2D 11.5

```bash
# Clone and build
git clone <repo-url>
cd norrust
cargo build --manifest-path norrust_core/Cargo.toml

# Run the unit test suite (no Love2D needed)
cargo test --lib --manifest-path norrust_core/Cargo.toml
# Expected: 130 tests pass

# Run the game
love norrust_love
```

> Full build and workflow guide: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

---

## For AI Developers

The simulation core exposes a JSON interface designed to be consumed by external agents.
Read the game state with `norrust_get_state_json()`. Submit actions with `norrust_apply_move()`,
`norrust_apply_attack()`, or `norrust_apply_action_json()`.

```json
// Read state — units, board, turn, active faction
{ "turn": 4, "active_faction": "red", "units": [ ... ], "terrain": [ ... ] }

// Submit an action via JSON
{ "action": "Move", "unit_id": 1, "col": 3, "row": 2 }
{ "action": "Attack", "attacker_id": 1, "defender_id": 5 }
{ "action": "EndTurn" }
```

Actions return integer codes: `0` = success, negative = typed error (unit not found,
destination unreachable, etc.).

The built-in greedy AI (`ai_take_turn`) plays using this same interface — no special access.
Its weaknesses (no positional awareness, ignores terrain defense, doesn't block) are documented
so you know exactly what a better agent should exploit.

> C ABI function reference: [docs/BRIDGE_API.md](docs/BRIDGE_API.md)
> Agent strategy guide: [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md)

---

## Repository Layout

```
norrust/
├── norrust_core/       # Rust library — simulation engine + C ABI bridge
│   ├── src/            # 18 modules: game_state, combat, pathfinding, ai, ffi, visibility, ...
│   └── tests/          # 6 test suites (simulation, FFI, campaign, dialogue, scenario, balance)
├── norrust_love/       # Love2D project — presentation layer only
│   ├── main.lua        # Entry point and game loop
│   ├── norrust.lua     # LuaJIT FFI bindings wrapping all 78 C ABI functions
│   └── (27 more)       # Modular Lua files: draw, input, camera, combat, save, roster, ...
├── data/
│   ├── units/          # 112 unit TOML definitions across 31 advancement trees
│   ├── terrain/        # 14 terrain TOML + PNG definitions
│   ├── factions/       # 4 faction definitions (Loyalists, Rebels, Northerners, Undead)
│   └── recruit_groups/ # Recruitable unit lists per faction
├── scenarios/          # 7 scenarios (board + units + optional dialogue)
├── campaigns/          # Campaign definitions (multi-scenario progression)
├── debug/              # Debug sandbox config
├── docs/               # Architecture, development, API, agent, asset, and contributor guides
└── tools/              # Utility scripts (Wesnoth scraper, sprite generator, stat verifier, ...)
```

---

## Documentation

| Document | What it covers |
|----------|---------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, component diagram, sequence diagrams |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Build commands, test workflow, key file map |
| [docs/BRIDGE_API.md](docs/BRIDGE_API.md) | C ABI function signatures, error codes, JSON schemas |
| [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) | Turn lifecycle, state semantics, legal moves, combat math |
| [docs/ASSET-SPEC.md](docs/ASSET-SPEC.md) | Sprite format, terrain tiles, animation pipeline |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Adding units, scenarios, factions, and terrain — no code required |

---

## License

TBD.
