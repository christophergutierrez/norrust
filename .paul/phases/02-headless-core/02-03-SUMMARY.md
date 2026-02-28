---
phase: 02-headless-core
plan: 03
subsystem: core
tags: [pathfinding, astar, zoc, terrain, movement]

# Dependency graph
requires:
  - phase: 02-headless-core
    provides: Hex + Board (02-01), GameState (02-02)
provides:
  - Board.terrain: per-hex terrain id storage
  - find_path(): A* with terrain costs + ZOC stop rule + Skirmisher bypass
  - get_zoc_hexes(): ZOC set from GameState

affects: [02-04-combat, 02-05-simulation]

# Tech stack
tech-stack:
  added: [std::collections::BinaryHeap, std::cmp::Reverse, Hex derives PartialOrd+Ord]
  patterns:
    - A* min-heap via BinaryHeap<Reverse<(u32, u32, Hex)>> — no external crate needed
    - ZOC passed as pre-computed HashSet<Hex>, decoupled from GameState
    - 1-row board in ZOC tests to guarantee linear path (no bypass routes)
    - "#[allow(clippy::too_many_arguments)] on find_path — 8 params genuinely required"

key-files:
  created:
    - norrust_core/src/pathfinding.rs
  modified:
    - norrust_core/src/board.rs
    - norrust_core/src/hex.rs
    - norrust_core/src/lib.rs

key-decisions:
  - "Board stores terrain IDs (String), not TerrainDef objects — decoupled from registry"
  - "find_path takes pre-computed zoc_hexes parameter — caller computes via get_zoc_hexes()"
  - "99 = impassable convention — matches UnitDef.movement_costs schema"
  - "1-row Board for ZOC tests — forces linear path, eliminates bypass routes"

patterns-established:
  - "ZOC stop rule: expand from ZOC hex only if is_skirmisher=true OR current==start"
  - "find_path returns Option<(Vec<Hex>, u32)> — path inclusive of start+end, plus cost"

# Metrics
duration: ~25min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 2 Plan 03: A* Pathfinding + Terrain Costs + ZOC Summary

**A* pathfinding with terrain movement costs, ZOC stop rule, and Skirmisher bypass — Board extended with per-hex terrain map, Hex gains Ord, 23 tests passing, clippy clean.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~25 min |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files modified | 4 (board, hex, lib, pathfinding new) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Terrain Cost Accumulation | Pass | 3 forest hexes × cost 1 = total cost 3 |
| AC-2: ZOC Blocks Path Beyond | Pass | None for destination past ZOC; Some for destination = ZOC hex |
| AC-3: Skirmisher Bypasses ZOC | Pass | Some((path, cost)) returned when is_skirmisher=true |

## Accomplishments

- `Board` extended with `terrain: HashMap<Hex, String>`, `set_terrain()`, `terrain_at()` — backward compatible, no signature changes
- `Hex` gains `PartialOrd + Ord` derives (required for BinaryHeap tuple ordering)
- `find_path()`: A* using stdlib `BinaryHeap<Reverse<(u32, u32, Hex)>>`, terrain cost lookup, movement budget cap, ZOC stop rule, Skirmisher bypass, path reconstruction
- `get_zoc_hexes()`: derives ZOC HashSet from GameState without coupling pathfinding to state mutation
- 23/23 tests pass; `cargo clippy -- -D warnings` clean

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/board.rs` | Modified | Added terrain HashMap, set_terrain(), terrain_at() |
| `norrust_core/src/hex.rs` | Modified | Added PartialOrd + Ord derives |
| `norrust_core/src/pathfinding.rs` | Created | find_path() A* + get_zoc_hexes() + 3 tests |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod pathfinding;` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `Board.terrain: HashMap<Hex, String>` (private field) | Hexes without terrain return None — no default forced on Board | Caller controls fallback via `default_movement_cost` param |
| `find_path` takes `zoc_hexes: &HashSet<Hex>` not `&GameState` | Decouples pathfinding from state; caller decides which faction's ZOC matters | `get_zoc_hexes(state, faction)` is the bridge |
| `#[allow(clippy::too_many_arguments)]` on `find_path` | 8 parameters genuinely required; a struct would be artificial indirection | No wrapper struct added |
| 1-row board (`Board::new(10, 1)`) in ZOC tests | On a 2D board, A* found a bypass route around single ZOC hex — test was wrong, not the algorithm | Reliably tests ZOC stop rule without multi-hex ZOC barriers |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential correctness fix + clippy compliance |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Two essential fixes, no scope creep.

### Auto-fixed Issues

**1. ZOC test scenario allowed bypass route**
- **Found during:** Task 2 verification (`cargo test` — test_zoc_blocks_path_beyond FAILED)
- **Issue:** `Board::new(10, 10)` has enough space for A* to route around a single ZOC hex; test expected `None` but got `Some` (correct algorithm, wrong test setup)
- **Fix:** Changed to `Board::new(10, 1)` — forces strictly linear path, no bypass possible
- **Verification:** `test_zoc_blocks_path_beyond` passes with corrected board

**2. Clippy: too_many_arguments on find_path**
- **Found during:** Task 2 verification (`cargo clippy -- -D warnings`)
- **Issue:** 8-parameter function triggers `clippy::too_many_arguments`
- **Fix:** Added `#[allow(clippy::too_many_arguments)]` — all 8 params are genuinely distinct and required; a grouping struct would be premature abstraction
- **Verification:** clippy exits 0

## Next Phase Readiness

**Ready:**
- `find_path` + `get_zoc_hexes` are the complete movement validation primitives
- `Board.terrain_at()` feeds terrain cost lookups in pathfinding
- All pathfinding logic exercised by 3 focused tests

**Concerns:**
- `find_path` not yet wired into `apply_action(Move)` — that integration is Plan 02-05
- Movement validation in `apply_action` still only checks bounds/occupancy, not terrain budget or ZOC

**Blockers:**
- None

---
*Phase: 02-headless-core, Plan: 03*
*Completed: 2026-02-27*
