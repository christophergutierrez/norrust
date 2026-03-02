# The Clash for Norrust

> A hex-based strategy game with a headless Rust simulation core and a clean JSON interface
> designed from the start for both human players and AI agents.

---

## Why This Repository

Most game engines tangle rules, rendering, and state together. NorRust does not.

The entire game — movement, combat, ZOC, time-of-day, advancement, terrain effects — lives in a
pure-Rust library that has no dependency on Redot, OpenGL, or any display system. You can
simulate a 5v5 battle, run it 1000 times, and verify the outcome in milliseconds with
`cargo test`. The Redot frontend is a thin client that renders state it receives as JSON.

This matters if you want to:
- **Build an AI agent** — write it in Python, speak JSON over a socket, never touch GDScript
- **Run headless simulations** — tournament brackets, balance testing, Monte Carlo rollouts
- **Extend the engine** — add a rule, write a test, verify it works before opening Redot once
- **Learn from the architecture** — a worked example of strict separation between game logic
  and presentation

The game itself is a turn-based hex strategy inspired by Battle for Wesnoth — two factions,
one map, last unit standing wins.

---

## What Works Now

- **Playable game:** two-faction match, full move/attack/end-turn loop, human vs. built-in AI
- **53 passing tests:** unit, integration, and headless AI simulations — no Redot required
- **322 data-driven units:** stats, attacks, resistances, alignment, and advancement chains
  loaded from TOML at startup
- **14 terrain types:** each with movement cost, defense bonus, healing, and display color —
  all data-driven, no hardcoded values
- **Procedural map generation:** seeded noise-based terrain placement with guaranteed spawn zones
- **Built-in greedy AI:** expected-damage scoring, kill bonus, plays via the same JSON interface
  available to external agents
- **XP and advancement:** units gain XP on hits and kills, promote when thresholds are met

The visuals are intentionally minimal — colored hex polygons, unit circles with HP text. The
architecture is not.

---

## Architecture in 30 Seconds

```
┌─────────────────────────────────────┐
│   Presentation Layer (GDScript)     │  Renders. Forwards input. Knows no rules.
│   norrust_client/scripts/game.gd    │
└────────────────┬────────────────────┘
                 │  GDExtension (C API)
                 │  StateSnapshot (JSON) ← get_state_json()
                 │  ActionRequest (JSON) → apply_action_json()
┌────────────────▼────────────────────┐
│   Integration Bridge (Rust)         │  Translates types. Owns registries.
│   norrust_core/src/gdext_node.rs    │  Converts offset ↔ cubic hex coordinates.
└────────────────┬────────────────────┘
                 │  pure function calls
┌────────────────▼────────────────────┐
│   Simulation Core (Rust, headless)  │  All rules. No I/O. cargo test runs this alone.
│   game_state.rs · combat.rs         │
│   pathfinding.rs · ai.rs · mapgen.rs│
└─────────────────────────────────────┘
```

Every player action and every AI action takes the same path:
`apply_action()` validates, mutates state, returns `Ok(())` or an `ActionError`. No exceptions.

→ Full diagram with sequence flows: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

---

## Quick Start

**Requirements:** Rust stable toolchain, Redot 26.1

```bash
# Clone and build
git clone <repo-url>
cd norrust
cargo build --manifest-path norrust_core/Cargo.toml

# Run the test suite (no Redot needed)
cargo test --manifest-path norrust_core/Cargo.toml
# Expected: 53 tests pass

# Copy the library for Redot
cp norrust_core/target/debug/libnorrust_core.so norrust_client/bin/

# Open Redot 26.1, import norrust_client/project.godot, press F5
```

→ Full build and workflow guide: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

---

## For AI Developers

The simulation core exposes a JSON interface designed to be consumed by external agents.
Read the game state with `get_state_json()`. Submit actions with `apply_action_json()`.

```json
// Read state — units, board, turn, active faction
{ "turn": 4, "active_faction": "red", "units": [ ... ], "terrain": [ ... ] }

// Submit an action
{ "action": "Move", "unit_id": 1, "col": 3, "row": 2 }
{ "action": "Attack", "attacker_id": 1, "defender_id": 5 }
{ "action": "EndTurn" }
```

Actions return integer codes: `0` = success, negative = typed error (unit not found,
destination unreachable, etc.).

The built-in greedy AI (`ai_take_turn`) plays using this same interface — no special access.
Its weaknesses (no positional awareness, ignores terrain defense, doesn't block) are documented
so you know exactly what a better agent should exploit.

→ GDExtension method reference: [docs/BRIDGE_API.md](docs/BRIDGE_API.md) *(in progress)*
→ Agent strategy guide: [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) *(in progress)*

---

## Repository Layout

```
norrust/
├── norrust_core/       # Rust library — simulation engine + GDExtension bridge
│   ├── src/            # game_state, combat, pathfinding, ai, mapgen, ...
│   └── tests/          # Headless integration tests
├── norrust_client/     # Redot project — presentation layer only
│   └── scripts/game.gd # The entire frontend in one file
├── data/
│   ├── units/          # 322 unit TOML definitions
│   └── terrain/        # 14 terrain TOML definitions
├── docs/               # Architecture, development, API, and agent guides
└── tools/
    └── scrape_wesnoth.py  # WML → TOML scraper used to import Wesnoth unit data
```

---

## Documentation

| Document | What it covers |
|----------|---------------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, component diagram, sequence diagrams |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Build commands, test workflow, key file map |
| [docs/BRIDGE_API.md](docs/BRIDGE_API.md) | GDExtension method signatures, error codes, JSON schemas |
| [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) | Turn lifecycle, state semantics, legal moves, combat math |

---

## License

TBD.
