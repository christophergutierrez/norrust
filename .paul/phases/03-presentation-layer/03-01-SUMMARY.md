---
phase: 03-presentation-layer
plan: 01
subsystem: bridge
tags: [gdextension, gamestate, pathfinding, flood-fill, bridge-api]

# Dependency graph
requires:
  - phase: 02-headless-core
    provides: GameState, apply_action, find_path, get_zoc_hexes (02-05)
provides:
  - reachable_hexes(): Dijkstra flood-fill in pathfinding.rs
  - NorRustCore.game: Option<GameState> — bridge owns live game state
  - 10 new #[func] bridge methods callable from GDScript

affects: [03-02-tilemap, 03-03-action-dispatch]

# Tech stack
tech-stack:
  added: []
  patterns:
    - action_err_code() free function maps ActionError → negative i32 sentinel
    - PackedInt32Array for flat position/hex data (GDScript-friendly, no custom types)
    - let Some(x) = ... else { return } pattern for safe early returns in #[func]

key-files:
  modified:
    - norrust_core/src/pathfinding.rs
    - norrust_core/src/gdext_node.rs

key-decisions:
  - "PackedInt32Array for all position data: avoids custom GodotClass types, GDScript unpacks triplets [id, col, row]"
  - "action_err_code as free function: not a method, keeps error mapping testable and isolated"
  - "Board::new takes u32 not usize: compile error caught and fixed (cols as u32)"
  - "get_reachable_hexes hardcodes is_skirmisher=false: skirmisher flag deferred to Phase 4"

# Metrics
duration: ~15min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 3 Plan 01: GDExtension Bridge — GameState API Summary

**`reachable_hexes()` flood-fill added to pathfinding; `NorRustCore` extended with `game: Option<GameState>` and 10 GDScript-callable bridge methods — 28 unit tests + 1 integration test, clippy clean.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files modified | 2 (pathfinding, gdext_node) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: GameState Lifecycle | Pass | create_game() initialises state; get_active_faction()/get_turn() return correct values |
| AC-2: Unit Placement Query | Pass | place_unit_at() + get_unit_positions() return [id, col, row] triplets |
| AC-3: Move Action Error Codes | Pass | 0=Ok, -6=DestinationUnreachable correctly mapped |
| AC-4: Reachable Hexes Flood Fill | Pass | test_reachable_hexes_respects_budget: budget=2 excludes (0,0) from (2,2) |

## New Bridge API

| Method | Returns | Purpose |
|--------|---------|---------|
| `create_game(cols, rows, seed)` | `bool` | Initialise GameState |
| `set_terrain_at(col, row, terrain_id)` | `void` | Set board terrain |
| `place_unit_at(id, def_id, hp, faction, col, row)` | `void` | Spawn unit |
| `apply_move(unit_id, col, row)` | `i32` | Move action (0=ok, neg=error) |
| `apply_attack(attacker_id, defender_id)` | `i32` | Attack action |
| `end_turn()` | `i32` | End turn action |
| `get_unit_positions()` | `PackedInt32Array` | Flat [id,col,row,...] |
| `get_active_faction()` | `i32` | Current faction (0 or 1) |
| `get_turn()` | `i32` | Current turn number |
| `get_reachable_hexes(unit_id)` | `PackedInt32Array` | Flat [col,row,...] |

## Error Code Table (apply_* methods)

| Code | Meaning |
|------|---------|
| 0 | Ok |
| -1 | UnitNotFound (or no game) |
| -2 | NotYourTurn |
| -3 | DestinationOutOfBounds |
| -4 | DestinationOccupied |
| -5 | UnitAlreadyMoved |
| -6 | DestinationUnreachable |

## Deviations from Plan

### Auto-fixed
**`Board::new` takes `u32` not `usize`**: `cols as usize` → `cols as u32`. Caught at compile time, trivial fix.

No other deviations.

## Next Phase Readiness

**Ready for Plan 03-02:** Redot TileMap setup + map rendering.

GDScript can now:
- Call `create_game()` → `set_terrain_at()` × N → `place_unit_at()` × N
- Apply actions via `apply_move()` / `apply_attack()` / `end_turn()`
- Query state via `get_unit_positions()` and `get_reachable_hexes()`

The visual layer can be built entirely on top of this bridge without touching Rust again (until Phase 4).

---
*Phase: 03-presentation-layer, Plan: 01*
*Completed: 2026-02-27*
