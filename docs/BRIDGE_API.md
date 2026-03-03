# Bridge API Reference

## Purpose

Reference for the C ABI bridge (`ffi.rs`) exposed by `norrust_core`. These 36 `extern "C"`
functions are called via LuaJIT FFI from Love2D, but any language with C FFI support can use them.

## Memory Management

All functions take an opaque `NorRustEngine*` pointer as their first argument (except
`norrust_new()`, `norrust_get_core_version()`, and the free functions).

**Caller-frees pattern:**
- Strings returned as `char*` must be freed with `norrust_free_string()`
- Integer arrays returned as `int32_t*` must be freed with `norrust_free_int_array()`
- The engine itself must be freed with `norrust_free()`

## Lifecycle Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `norrust_new` | `() -> *NorRustEngine` | Create a new engine instance |
| `norrust_free` | `(*NorRustEngine)` | Destroy an engine instance |
| `norrust_free_string` | `(*char)` | Free a string returned by the engine |
| `norrust_free_int_array` | `(*int32_t, int32_t len)` | Free an integer array returned by the engine |

## Data Loading

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_get_core_version` | `() -> *char` | Version string | Returns engine version (currently "0.1.0") |
| `norrust_load_data` | `(*engine, *data_path) -> i32` | 1=ok | Load unit + terrain registries from data/ directory |
| `norrust_get_unit_max_hp` | `(*engine, *unit_id) -> i32` | HP value | Query max HP from unit registry |

## Game Initialization

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_create_game` | `(*engine, cols, rows, seed) -> i32` | 1=ok | Create empty board with dimensions |
| `norrust_set_terrain_at` | `(*engine, col, row, *terrain_id)` | void | Place terrain at hex |
| `norrust_generate_map` | `(*engine, seed) -> i32` | 1=ok | Procedural map generation |
| `norrust_load_board` | `(*engine, *board_path, seed) -> i32` | 1=ok | Load board from TOML scenario file |
| `norrust_load_units` | `(*engine, *units_path) -> i32` | 1=ok | Load unit placements from TOML file |
| `norrust_get_terrain_at` | `(*engine, col, row) -> *char` | Terrain ID | Query terrain at hex (free with norrust_free_string) |

## Unit Management

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_place_unit_at` | `(*engine, unit_id, *def_id, hp, faction, col, row)` | void | Place a unit on the board |
| `norrust_remove_unit_at` | `(*engine, col, row) -> i32` | 1=ok | Remove unit at hex |
| `norrust_get_unit_cost` | `(*engine, *def_id) -> i32` | Gold cost | Query recruitment cost from registry |
| `norrust_get_unit_level` | `(*engine, *def_id) -> i32` | Level | Query unit level from registry |

## Recruitment

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_recruit_unit_at` | `(*engine, unit_id, *def_id, col, row) -> i32` | 0=ok, negative=error | Recruit a unit at a castle hex |
| `norrust_ai_recruit` | `(*engine, *faction_id, start_unit_id) -> i32` | Next available unit ID | AI auto-recruitment for a faction |
| `norrust_apply_starting_gold` | `(*engine, *f0_id, *f1_id) -> i32` | 1=ok | Set starting gold from faction definitions |

## Faction Queries

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_load_factions` | `(*engine, *data_path) -> i32` | 1=ok | Load faction definitions |
| `norrust_get_faction_ids_json` | `(*engine) -> *char` | JSON array | Get all faction IDs as JSON |
| `norrust_get_faction_leader` | `(*engine, *faction_id) -> *char` | Leader def ID | Get faction's leader unit type |
| `norrust_get_faction_recruits_json` | `(*engine, *faction_id, max_level) -> *char` | JSON array | Get recruitable unit types |

## Game State Queries

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_get_active_faction` | `(*engine) -> i32` | Faction index | 0 or 1 |
| `norrust_get_turn` | `(*engine) -> i32` | Turn number | Starting from 1 |
| `norrust_get_time_of_day_name` | `(*engine) -> *char` | ToD name | "Day", "Dusk", "Night", "Dawn" |
| `norrust_get_winner` | `(*engine) -> i32` | -1=none, 0/1=faction | Check for game end |
| `norrust_get_state_json` | `(*engine) -> *char` | Full JSON snapshot | Complete game state as JSON |

## Actions

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_apply_move` | `(*engine, unit_id, col, row) -> i32` | 0=ok | Move unit to hex |
| `norrust_apply_attack` | `(*engine, attacker_id, defender_id) -> i32` | 0=ok | Attack adjacent enemy |
| `norrust_apply_advance` | `(*engine, unit_id) -> i32` | 0=ok | Advance (promote) a unit |
| `norrust_end_turn` | `(*engine) -> i32` | 0=ok | End current faction's turn |
| `norrust_apply_action_json` | `(*engine, *json) -> i32` | 0=ok | Submit action as JSON string |

## Pathfinding

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_get_reachable_hexes` | `(*engine, unit_id, *out_len) -> *i32` | Col/row pairs | Flat array of reachable hex coordinates |

## AI

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_ai_take_turn` | `(*engine, faction)` | void | AI plays full turn for faction |

---

## Error Code Table

| Code | Meaning |
|------|---------|
| 0 | Success |
| -1 | Unit not found |
| -2 | Not your turn |
| -3 | Destination out of bounds |
| -4 | Destination occupied |
| -5 | Unit already moved |
| -6 | Destination unreachable |
| -7 | Not adjacent (attack) |
| -8 | Not enough gold (recruit) |
| -9 | Destination not castle (recruit) |
| -10 | Leader not on keep (recruit) |
| -99 | JSON parse error (apply_action_json only) |

## JSON Schemas

### StateSnapshot (from `norrust_get_state_json`)

```json
{
  "turn": 1,
  "active_faction": 0,
  "gold": [100, 100],
  "terrain": [
    {"col": 0, "row": 0, "terrain_id": "castle", "color": "#808080"}
  ],
  "units": [
    {
      "id": 1,
      "def_id": "Spearman",
      "col": 0, "row": 0,
      "faction": 0,
      "hp": 36, "max_hp": 36,
      "xp": 0, "xp_needed": 40,
      "moved": false, "attacked": false,
      "advancement_pending": false,
      "level": 1,
      "movement": 5,
      "attacks": [
        {"name": "spear", "damage": 7, "strikes": 3, "range": "melee", "damage_type": "pierce"}
      ],
      "abilities": ["leader"]
    }
  ]
}
```

### ActionRequest (for `norrust_apply_action_json`)

```json
{"action": "Move", "unit_id": 1, "col": 3, "row": 2}
{"action": "Attack", "attacker_id": 1, "defender_id": 5}
{"action": "Advance", "unit_id": 1}
{"action": "EndTurn"}
{"action": "Recruit", "unit_id": 99, "def_id": "Spearman", "col": 0, "row": 1}
```

## Startup Sequence

```
norrust_new()
  → norrust_load_data(engine, "data/")
  → norrust_load_factions(engine, "data/")
  → norrust_load_board(engine, "scenarios/contested.toml", seed)
  → norrust_load_units(engine, "scenarios/contested_units.toml")
  → norrust_apply_starting_gold(engine, "loyalists", "orcs")
  → Game loop: get_state_json, apply_move, apply_attack, end_turn, ...
  → norrust_free(engine)
```

## Coordinate Conventions

The board uses **offset coordinates** (col, row) at the FFI boundary — 0-indexed, col increases
left-to-right, row increases top-to-bottom. Internally, the Rust core converts to cubic hex
coordinates via `Hex::from_offset()` at every entry point and converts back with `hex.to_offset()`
for outgoing data. Hex geometry is pointy-top with odd-row offset (odd rows shift right by half
a hex width).
