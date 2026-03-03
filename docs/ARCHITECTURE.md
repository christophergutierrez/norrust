# NorRust Architecture

NorRust is built on a strict separation of concerns: the headless simulation core owns all game rules, while the presentation layer handles visuals and input. This means game logic can be tested without Love2D, and external AI agents interact via the same interface as the human player.

## System Overview

```mermaid
graph TD
    subgraph Presentation Layer ["Presentation Layer (Love2D / Lua)"]
        UI[User Interface / HUD]
        Input[Player Input Handling]
        Renderer[Hex Grid & Unit Renderer]
        ClientAI[Lua AI Trigger]
    end

    subgraph Integration Bridge ["C ABI Bridge (LuaJIT FFI)"]
        Bridge[Rust ↔ Lua Bridge]
        JSON_State[StateSnapshot (JSON)]
        JSON_Action[ActionRequest (JSON)]
    end

    subgraph Simulation Core ["Simulation Core (Rust - Headless)"]
        State[GameState & Board]
        Logic[Game Rules & Combat Math]
        Pathfinding[A* & Reachability]
        InternalAI[Analytic AI Planner]
    end

    subgraph Data Layer ["Data Layer (Disk)"]
        TOML_Units[(Unit Definitions .toml)]
        TOML_Terrain[(Terrain Definitions .toml)]
    end

    subgraph External ["External Clients (Future)"]
        Ext_AI[Python / RL Agents]
    end

    %% Flow of control and data
    Input -->|Events| Bridge
    ClientAI -->|Triggers| Bridge
    UI -->|Queries| Bridge
    Renderer -->|Queries| Bridge

    Bridge <-->|Parses / Serializes| JSON_State
    Bridge <-->|Dispatches| JSON_Action

    JSON_Action -->|Mutates| State
    JSON_State <--|Reads| State

    Logic --> State
    Pathfinding --> State
    InternalAI --> State

    TOML_Units -->|Loads on Startup| Bridge
    TOML_Terrain -->|Loads on Startup| Bridge

    Ext_AI -.->|Socket/TCP| JSON_Action
    Ext_AI -.->|Socket/TCP| JSON_State
```

## Key Architectural Patterns

1. **Strictly One-Way Data Flow:**
   `Input -> FFI Bridge -> apply_action() -> Mutate State -> JSON Snapshot -> Render`
2. **"Fail-Fast" Action Validation:**
   Actions submitted to the core are validated before execution. If an action is illegal (e.g., moving too far, attacking out of range), the core returns an `ActionError` and the state remains pristine.
3. **Headless-First Testing:**
   Because the core is independent of Love2D, complex scenarios (like a 5v5 AI battle taking 100 turns) can be simulated and verified in milliseconds via standard `cargo test`.

---

## Directory Structure

```
norrust/
├── norrust_core/           # Rust simulation core (cdylib + rlib)
│   ├── src/
│   │   ├── lib.rs          # Module declarations
│   │   ├── board.rs        # Board, Tile structs
│   │   ├── game_state.rs   # GameState, apply_action(), Action, ActionError
│   │   ├── hex.rs          # Hex coordinate type (cubic + odd-r offset)
│   │   ├── unit.rs         # Unit, advance_unit(), parse_alignment()
│   │   ├── combat.rs       # Combat resolution, time_of_day()
│   │   ├── pathfinding.rs  # reachable_hexes(), A*, ZOC
│   │   ├── ai.rs           # ai_take_turn() greedy planner
│   │   ├── mapgen.rs       # generate_map() procedural terrain generator
│   │   ├── schema.rs       # UnitDef, TerrainDef, AttackDef (serde)
│   │   ├── loader.rs       # Registry<T>, load_from_dir()
│   │   ├── snapshot.rs     # StateSnapshot, TileSnapshot, ActionRequest (JSON)
│   │   ├── scenario.rs     # load_board(), load_units() file I/O
│   │   └── ffi.rs          # C ABI bridge — 36 extern "C" functions
│   └── tests/
│       ├── simulation.rs   # Integration tests (headless)
│       └── test_ffi.rs     # FFI integration test
├── norrust_love/           # Love2D project (Lua frontend)
│   ├── main.lua            # Complete game client (831 lines)
│   ├── norrust.lua         # LuaJIT FFI bindings + JSON decoder (365 lines)
│   └── conf.lua            # Window configuration
├── data/
│   ├── units/              # 322 unit TOML files (4 custom + 318 Wesnoth)
│   ├── terrain/            # 14 terrain TOML files
│   └── factions/           # Faction definitions
├── scenarios/              # Board and unit placement files
└── tools/
    └── scrape_wesnoth.py   # WML → TOML scraper (stdlib only)
```

---

## Component Details

### 1. Presentation Layer (Love2D / Lua)
The frontend (`norrust_love/`) is entirely responsible for visuals and capturing player intent. It knows *nothing* about game rules, unit stats, or hex math beyond coordinate conversion.
- **Responsibilities:** Rendering the hex grid, drawing unit circles with HP/XP/name text, handling mouse clicks, managing the UI HUD, sidebar panels, and recruit interface.
- **State Management:** The client holds no authoritative state. Every frame, it calls `norrust.get_state(engine)` to receive a fresh parsed StateSnapshot and renders from that data alone.
- **Action Dispatch:** When a player clicks to move or attack, the client does not execute the action. It calls a typed FFI wrapper (`norrust.apply_move`, `norrust.apply_attack`, `norrust.end_turn`) and the Rust core decides whether it is legal.
- **Hex Math:** Pure Lua functions (`hex_to_pixel`, `pixel_to_hex`) handle pointy-top odd-r offset coordinate conversion — no engine-specific tile map dependency.

### 2. Integration Bridge (C ABI & LuaJIT FFI)
The boundary between Love2D (Lua) and Rust. This layer translates Lua calls into type-safe Rust execution.
- **C ABI:** `ffi.rs` exposes 36 `extern "C"` functions with an opaque `NorRustEngine` pointer. All functions use C-compatible types (i32, `*const c_char`, `*mut i32`).
- **LuaJIT FFI Bindings:** `norrust.lua` uses `ffi.cdef` to declare all C function signatures and wraps them with Lua-friendly return types. Strings are converted via `ffi.string()` then freed with `norrust_free_string()`. Integer arrays are read into Lua tables then freed with `norrust_free_int_array()`.
- **Memory Management:** Caller-frees pattern. Rust allocates strings/arrays with `CString::into_raw()` / `Box::into_raw()`. Lua is responsible for calling the corresponding free function. `ffi.gc` attaches `norrust_free` as a destructor on the engine pointer for automatic cleanup.
- **JSON State Serialization:** The Rust core exports the full board and unit state as a JSON string (`StateSnapshot`). An inline pure-Lua JSON decoder (~90 lines) in `norrust.lua` parses it into native Lua tables.
- **Coordinate Translation:** Lua works in offset coordinates (col, row). The bridge converts these to cubic hex coordinates via `Hex::from_offset()` at every entry point; `hex.to_offset()` converts back for outgoing data.
- **Registry Ownership:** On startup, `norrust_load_data()` reads the `data/` directory and populates `Registry<UnitDef>` and `Registry<TerrainDef>` on the engine. The simulation core itself has no registry access — unit and terrain stats are copied into runtime structs at spawn/placement time.
- **Future External Access:** The JSON state/action contract is transport-agnostic. A future TCP layer would expose the same interface to external Python or RL agents without touching the simulation core.

### 3. Simulation Core (`norrust_core`)
The authoritative brain of the game, written in pure Rust. It operates entirely headlessly and can be compiled as a standard library (`rlib`) for unit testing or as a dynamic library (`cdylib`) for loading via LuaJIT FFI.
- **GameState & Board:** `Board` stores a `HashMap<Hex, Tile>` where each `Tile` carries terrain properties (movement cost, defense, healing, color). `GameState` owns the unit registry (`HashMap<u32, Unit>`) and position map (`HashMap<u32, Hex>`) separately.
- **Game Rules:** Enforces movement costs, Zone of Control (ZOC), combat resolution (RNG, damage calculation, resistances, Time of Day modifiers), and XP/advancement logic.
- **Pathfinding:** Implements flood-fill reachability and A* shortest-path for movement and ZOC calculations.
- **Analytic AI:** A built-in greedy AI (`ai_take_turn`) scores every possible move+attack pair using expected damage, picks the best, and calls `apply_action()` like any other client. No external scripts or ML dependencies required.

### 4. Data Layer (TOML)
NorRust is heavily data-driven. Hardcoding stats is strictly avoided.
- **Registry Pattern:** On startup, the bridge reads the `data/` directory and loads all `.toml` files into a generic `Registry<T>`, keyed by the item's `id` field.
- **Unit Definitions:** Stats for all 322 units (HP, movement, attacks, resistances, alignment, advancement chains) are defined here. When a unit is spawned via `place_unit_at()`, it copies its properties from the registry into a standalone `Unit` struct.
- **Terrain Definitions:** Each terrain type (defense, movement cost, healing, color) is defined here. When a tile is placed via `set_terrain_at()` or `generate_map()`, a `Tile` struct is initialised from the matching `TerrainDef`.

---

## Sequence Diagrams

### Player Move

```mermaid
sequenceDiagram
    participant P as Player
    participant LUA as Love2D (main.lua)
    participant FFI as norrust.lua (LuaJIT FFI)
    participant CORE as Simulation Core (Rust)

    P->>LUA: left-click on friendly unit
    LUA->>FFI: norrust.get_reachable_hexes(engine, unit_id)
    FFI->>CORE: norrust_get_reachable_hexes(engine, unit_id, &out_len)
    CORE-->>FFI: *int32_t array (col, row pairs)
    FFI-->>LUA: Lua table of {col=N, row=N}
    LUA->>LUA: store reachable_cells + reachable_set

    P->>LUA: left-click on reachable hex
    LUA->>FFI: norrust.apply_move(engine, unit_id, col, row)
    FFI->>CORE: norrust_apply_move(engine, unit_id, col, row)
    CORE->>CORE: validate: unit exists, active faction, not yet moved, in bounds, path reachable
    CORE->>CORE: update positions map, set unit.moved = true
    CORE-->>FFI: 0 (success)
    FFI-->>LUA: 0
    LUA->>LUA: clear selection

    Note over LUA,CORE: Every love.draw() call
    LUA->>FFI: norrust.get_state(engine)
    FFI->>CORE: norrust_get_state_json(engine)
    CORE-->>FFI: JSON string (freed after copy)
    FFI-->>LUA: Parsed Lua table (StateSnapshot)
    LUA->>LUA: render board from state table
```

### Combat Resolution

```mermaid
sequenceDiagram
    participant P as Player
    participant LUA as Love2D (main.lua)
    participant FFI as norrust.lua (LuaJIT FFI)
    participant CORE as Simulation Core (Rust)

    P->>LUA: left-click on enemy unit (friendly unit selected)
    LUA->>FFI: norrust.apply_attack(engine, attacker_id, defender_id)
    FFI->>CORE: norrust_apply_attack(engine, attacker_id, defender_id)

    CORE->>CORE: validate: both exist, attacker is active faction, not yet attacked, units are adjacent

    Note over CORE: Attacker strikes
    CORE->>CORE: hit_chance = 100 - defender.defense_for_terrain
    CORE->>CORE: tod_modifier from time_of_day(turn) × attacker.alignment
    CORE->>CORE: for each strike: roll RNG → apply damage × tod_modifier × resistance
    CORE->>CORE: grant XP: 1 per hit, +8 kill bonus

    alt defender survives
        Note over CORE: Defender retaliates
        CORE->>CORE: hit_chance = 100 - attacker.defense_for_terrain
        CORE->>CORE: for each strike: roll RNG → apply damage × resistance
        CORE->>CORE: grant XP: 1 per hit, +8 kill bonus
    end

    CORE->>CORE: remove dead units, set attacker.attacked = true
    CORE-->>FFI: 0 (success)
    FFI-->>LUA: 0
    LUA->>LUA: clear selection

    Note over LUA,CORE: Every love.draw() call
    LUA->>FFI: norrust.get_state(engine)
    FFI-->>LUA: Parsed state table
    LUA->>LUA: render updated HP, remove dead units
```
