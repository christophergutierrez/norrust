# Bridge API Reference

## Purpose

Reference for the C ABI bridge (`ffi.rs`) exposed by `norrust_core`. These 78 `extern "C"`
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
| `norrust_get_core_version` | `() -> *char` | Version string | Returns engine version |
| `norrust_load_data` | `(*engine, *data_path) -> i32` | 1=ok | Load unit + terrain registries from data/ directory |
| `norrust_get_unit_max_hp` | `(*engine, *unit_id) -> i32` | HP value | Query max HP from unit registry |
| `norrust_get_unit_cost` | `(*engine, *def_id) -> i32` | Gold cost | Query recruitment cost from registry |
| `norrust_get_unit_level` | `(*engine, *def_id) -> i32` | Level | Query unit level from registry |

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
| `norrust_place_unit_at` | `(*engine, *def_id, faction, col, row) -> i32` | Unit ID | Place a unit on the board |
| `norrust_restore_unit_at` | `(*engine, *def_id, faction, col, row, hp, xp, xp_needed) -> i32` | Unit ID | Restore a unit with specific stats (save/load) |
| `norrust_remove_unit_at` | `(*engine, col, row) -> i32` | 1=ok | Remove unit at hex |
| `norrust_get_next_unit_id` | `(*engine) -> i32` | Next ID | Get the next available unit ID |
| `norrust_get_unit_at` | `(*engine, col, row) -> i32` | Unit ID or -1 | Query unit at hex position |
| `norrust_get_unit_terrain_info` | `(*engine, unit_id) -> *char` | JSON | Get unit's terrain defense/movement info |
| `norrust_set_display_name` | `(*engine, unit_id, *name)` | void | Override a unit's display name |
| `norrust_set_unit_combat_state` | `(*engine, unit_id, moved, attacked)` | void | Set unit's moved/attacked flags |

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
| `norrust_get_state_json` | `(*engine) -> *char` | Full JSON snapshot | Complete game state as JSON (cached) |
| `norrust_get_state_json_fow` | `(*engine, faction) -> *char` | Filtered JSON | Game state filtered by fog of war (uncached) |
| `norrust_get_gold` | `(*engine, faction) -> i32` | Gold amount | Query faction's current gold |
| `norrust_get_board_size` | `(*engine, *out_w, *out_h)` | void | Write board dimensions to output pointers |

## Win Conditions

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_set_objective_hex` | `(*engine, col, row)` | void | Set the objective hex for victory |
| `norrust_set_max_turns` | `(*engine, max_turns)` | void | Set turn limit (defender wins if exceeded) |

## Actions

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_apply_move` | `(*engine, unit_id, col, row) -> i32` | 0=ok | Move unit to hex |
| `norrust_apply_attack` | `(*engine, attacker_id, defender_id) -> i32` | 0=ok | Attack adjacent enemy |
| `norrust_get_advance_options` | `(*engine, unit_id) -> *char` | JSON array | Get available advancement choices |
| `norrust_apply_advance` | `(*engine, unit_id) -> i32` | 0=ok | Advance (promote) a unit |
| `norrust_end_turn` | `(*engine) -> i32` | 0=ok | End current faction's turn |
| `norrust_apply_action_json` | `(*engine, *json) -> i32` | 0=ok | Submit action as JSON string |

## Pathfinding

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_get_reachable_hexes` | `(*engine, unit_id, *out_len) -> *i32` | Col/row pairs | Flat array of reachable hex coordinates |
| `norrust_find_path` | `(*engine, unit_id, col, row, *out_len) -> *i32` | Col/row pairs | A* shortest path to destination |

## Combat Preview

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_simulate_combat` | `(*engine, attacker_id, defender_id) -> *char` | JSON | Simulate combat outcome (no state mutation) |

## AI

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_ai_take_turn` | `(*engine, faction)` | void | AI plays full turn for faction |
| `norrust_ai_plan_turn` | `(*engine, faction) -> *char` | JSON | AI plans turn and returns planned actions |
| `norrust_ai_deploy_recruits` | `(*engine, faction, start_uid) -> i32` | Next UID | AI recruits units for deployment phase |

## State Manipulation (Save/Load)

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_save_json` | `(*engine) -> *char` | JSON | Serialize full game state to JSON |
| `norrust_load_json` | `(*engine, *json) -> i32` | 1=ok | Restore game state from JSON |
| `norrust_set_faction_gold` | `(*engine, faction, gold)` | void | Set faction's gold directly |
| `norrust_set_turn` | `(*engine, turn)` | void | Set current turn number |
| `norrust_set_active_faction` | `(*engine, faction)` | void | Set the active faction |

## Campaign

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_load_campaign` | `(*engine, *campaign_path) -> i32` | 1=ok | Load campaign definition from TOML |
| `norrust_start_campaign` | `(*engine, *campaign_id) -> i32` | 1=ok | Start a loaded campaign |
| `norrust_get_campaign_state_json` | `(*engine) -> *char` | JSON | Get current campaign progress |
| `norrust_get_survivors_json` | `(*engine) -> *char` | JSON array | Get surviving units after scenario |
| `norrust_get_carry_gold` | `(*engine, faction) -> i32` | Gold amount | Get gold carried to next scenario |
| `norrust_place_veteran_unit` | `(*engine, *def_id, faction, col, row, hp, xp, xp_needed, adv_pending) -> i32` | Unit ID | Place a veteran unit with carried stats (heals to full) |
| `norrust_campaign_commit_deployment` | `(*engine, *json) -> i32` | 1=ok | Finalize deployment phase unit placements |
| `norrust_campaign_add_unit` | `(*engine, *uuid, *def_id, faction) -> i32` | 1=ok | Add unit to campaign roster |
| `norrust_campaign_map_id` | `(*engine, *uuid, unit_id) -> i32` | 1=ok | Map a roster UUID to an in-game unit ID |
| `norrust_campaign_sync_roster` | `(*engine) -> *char` | JSON | Sync roster state with current game state |
| `norrust_campaign_record_victory` | `(*engine, faction) -> i32` | 1=ok | Record scenario victory for faction |
| `norrust_campaign_get_living_json` | `(*engine) -> *char` | JSON array | Get UUIDs of living roster units |
| `norrust_campaign_get_mapped_uuids_json` | `(*engine) -> *char` | JSON array | Get UUID-to-unit-ID mappings |
| `norrust_campaign_load_next_scenario` | `(*engine) -> i32` | 1=ok, 0=no more | Load the next scenario in the campaign |

## Dialogue

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_load_dialogue` | `(*engine, *path) -> i32` | 1=ok | Load dialogue triggers from TOML file |
| `norrust_get_dialogue` | `(*engine, *trigger, turn, faction, col, row) -> *char` | JSON array | Query and fire pending dialogue (one-shot) |
| `norrust_get_dialogue_fired` | `(*engine) -> *char` | JSON array | Get IDs of all fired dialogue entries |
| `norrust_set_dialogue_fired` | `(*engine, *ids_json)` | void | Mark dialogue entries as fired (for save/load) |
| `norrust_get_trigger_zones_fired` | `(*engine) -> *char` | JSON array | Get fired trigger zone IDs |
| `norrust_set_trigger_zone_fired` | `(*engine, *ids_json)` | void | Mark trigger zones as fired (for save/load) |

## Debug / Cheat Functions

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `norrust_cheat_set_xp` | `(*engine, unit_id, xp) -> i32` | 0=ok | Set unit XP (debug mode only) |
| `norrust_cheat_add_gold` | `(*engine, faction, amount) -> i32` | 0=ok | Add gold to faction (debug mode only) |
| `norrust_cheat_set_turn` | `(*engine, turn) -> i32` | 0=ok | Set current turn (debug mode only) |

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
      "xp": 0, "xp_needed": 42,
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
  → norrust_load_board(engine, "scenarios/contested/board.toml", seed)
  → norrust_load_units(engine, "scenarios/contested/units.toml")
  → norrust_apply_starting_gold(engine, "loyalists", "rebels")
  → Game loop: get_state_json, apply_move, apply_attack, end_turn, ...
  → norrust_free(engine)
```

## Coordinate Conventions

The board uses **offset coordinates** (col, row) at the FFI boundary — 0-indexed, col increases
left-to-right, row increases top-to-bottom. Internally, the Rust core converts to cubic hex
coordinates via `Hex::from_offset()` at every entry point and converts back with `hex.to_offset()`
for outgoing data. Hex geometry is pointy-top with odd-row offset (odd rows shift right by half
a hex width).
