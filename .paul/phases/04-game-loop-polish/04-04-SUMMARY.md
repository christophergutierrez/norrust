---
phase: 04-game-loop-polish
plan: 04
subsystem: ui
tags: [terrain, village, healing, board, gdextension, gdscript]

requires:
  - phase: 04-03
    provides: resistance modifiers, colored HUD, get_time_of_day_name() bridge

provides:
  - Village terrain type (healing=8, defense=40)
  - get_terrain_at(col, row) bridge method
  - 8×5 board with two contested village hexes at (3,1) and (4,3)
  - Terrain-driven rendering via Rust state (not hardcoded GDScript formula)

affects: phase-05-ai-hooks

tech-stack:
  added: []
  patterns:
    - "Rust as rendering source of truth: _draw() queries get_terrain_at() per hex"
    - "Village healing wired automatically via board.healing_map cached at set_terrain_at() time"

key-files:
  created:
    - data/terrain/village.toml
  modified:
    - norrust_core/src/gdext_node.rs
    - norrust_core/src/loader.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "Village always heals all units standing on it (no ownership/capture mechanic)"
  - "Terrain color driven by Rust: get_terrain_at() replaces hardcoded GDScript checkerboard"

patterns-established:
  - "New terrain type = one .toml file; healing wires automatically via healing_map"

duration: ~20min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 4 Plan 04: Village Hexes + 8×5 Board Summary

**Village terrain (healing=8) added, board expanded to 8×5, terrain-driven rendering via `get_terrain_at()` bridge.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Tasks | 2 auto + 1 checkpoint |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Village Heals 8 HP Per Turn | Pass | Wired automatically via board.healing_map set at set_terrain_at() time; no new EndTurn code needed |
| AC-2: Village Rendered in Distinct Colour | Pass | Gold-tan COLOR_VILLAGE = Color(0.72, 0.60, 0.25); visible at (3,1) and (4,3) |
| AC-3: Terrain Color Driven by Rust State | Pass | _draw() calls get_terrain_at(col, row) per hex; checkerboard formula removed |

## Accomplishments

- Added `data/terrain/village.toml` (healing=8, defense=40, movement_cost=1)
- Added `get_terrain_at(col, row)` #[func] bridge — Rust is now authoritative for terrain rendering
- Expanded board from 5×5 to 8×5; units repositioned (blue col=1, red col=6)
- Village healing works without any new EndTurn code (healing_map populated at set_terrain_at time)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `data/terrain/village.toml` | Created | Village terrain def: healing=8, defense=40, movement_cost=1 |
| `norrust_core/src/gdext_node.rs` | Modified | Added `get_terrain_at()` #[func] |
| `norrust_core/src/loader.rs` | Modified | Updated test assertion: 2 → 3 terrain types; added village assertions |
| `norrust_client/scripts/game.gd` | Modified | 8×5 board, COLOR_VILLAGE, village hexes, terrain-driven _draw(), unit positions |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Village always heals all units (no capture) | Simpler; capture mechanic deferred | Villages are neutral healing positions |
| Terrain color driven by get_terrain_at() | Rust is source of truth; GDScript rendering stays in sync automatically | Extending terrain types requires zero GDScript changes |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential test update |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** One required fix; no scope creep.

### Auto-fixed Issues

**1. Test assertion stale after adding village.toml**
- **Found during:** Task 1 verification
- **Issue:** `test_terrain_registry_loads` asserted `len() == 2`; village.toml made it 3
- **Fix:** Updated assertion to `== 3`; added `registry.get("village")` assertions for healing and defense
- **Files:** `norrust_core/src/loader.rs`
- **Verification:** `cargo test` — 30/30 pass

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Complete Phase 4 game loop: EndTurn, healing, combat, win detection, HUD, villages
- All 30 tests pass; build stable
- Phase 5 (AI Hooks) can begin: GameState is pure Rust, JSON serialization is straightforward

**Concerns:**
- Recruitment/gold deferred; Phase 5 AI agents can only observe and move/attack existing units
- No castle hexes yet; recruitment deferred to future milestone

**Blockers:** None.

---
*Phase: 04-game-loop-polish, Plan: 04*
*Completed: 2026-02-28*
