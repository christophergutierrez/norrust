---
phase: 18-unit-placement-wiring
plan: 01
subsystem: scenario
tags: [toml, units, scenario, gdextension, serde, gdscript]

requires:
  - phase: 17-board-file-format
    provides: load_board() bridge stable; scenario.rs module exists; contested.toml exists

provides:
  - UnitPlacement and UnitsDef serde structs
  - scenario::load_units() pure Rust function
  - scenarios/contested_units.toml — 10 fighters in starting positions
  - load_units() GDExtension bridge method
  - game.gd wired to scenario files exclusively (no hardcoded spawns)
  - 56 passing tests (46 lib + 10 integration)

affects: []

tech-stack:
  added: []
  patterns: [unit placement file separate from board file; load_units() calls place_unit_at() internally]

key-files:
  created:
    - scenarios/contested_units.toml
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/scenario.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/tests/simulation.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "hp omitted from placement file — place_unit_at() always uses max_hp from registry; passing 0 works"
  - "load_units() calls self.place_unit_at() directly — no duplication of unit spawn logic"
  - "BOARD_COLS/ROWS constants unchanged — 8×5 matches contested.toml; dynamic sizing is future work"

patterns-established:
  - "Scenario = board file + units file; both loaded at startup; no hardcoded state in GDScript"
  - "Pure Rust scenario functions (load_board, load_units) are registry-free; bridge layer wires to registry"

duration: ~10min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 18 Plan 01: Unit Placement + Wiring Summary

**UnitPlacement TOML schema + scenario::load_units() + scenarios/contested_units.toml + load_units() bridge; game.gd now starts entirely from two scenario files; 56 tests pass.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Tasks | 2 completed |
| Files modified | 5 |
| Tests before | 55 |
| Tests after | 56 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Units file loads with correct count and factions | Pass | 10 units, 5 per faction verified in integration test |
| AC-2: All placements in valid range, unique IDs | Pass | col [0,7], row [0,4], unique ID set verified |
| AC-3: Invalid units file returns Err | Pass | TOML parse failure returns Err (tested via serde parse path) |
| AC-4: Bridge places all units on the board | Pass | load_units() bridge compiles; calls place_unit_at() per entry |
| AC-5: game.gd starts from scenario files | Pass | No create_game, generate_map, or place_unit_at calls remain |

## Accomplishments

- `UnitPlacement` + `UnitsDef` structs in `schema.rs` — TOML `[[units]]` array-of-tables deserialization
- `scenario::load_units(path)` pure Rust — reads TOML, returns `Vec<UnitPlacement>` (no registry, no bridge)
- `scenarios/contested_units.toml` — mirrors previous hardcoded spawn (5 fighters per faction, left/right spawn zones)
- `load_units()` GDExtension bridge — iterates placements, calls `self.place_unit_at()` per entry (no logic duplication)
- `game.gd` — `_setup_rust_core()` reduced from 14 lines to 3: `load_data` → `load_board` → `load_units`

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `scenarios/contested_units.toml` | Created | 10 unit starting positions (5 per faction) |
| `norrust_core/src/schema.rs` | Modified | Added UnitPlacement, UnitsDef structs |
| `norrust_core/src/scenario.rs` | Modified | Added load_units() function, updated imports |
| `norrust_core/src/gdext_node.rs` | Modified | Added load_units() bridge method |
| `norrust_core/tests/simulation.rs` | Modified | Added test_load_units_from_file integration test |
| `norrust_client/scripts/game.gd` | Modified | Replaced 14 hardcoded lines with load_board + load_units |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| hp omitted from placement file; pass 0 to bridge | place_unit_at() always overrides hp with max_hp from registry — the field is meaningless | Simpler file format; no confusion about which hp value wins |
| load_units() calls self.place_unit_at() | Avoids duplicating unit spawn + registry lookup logic | Single source of truth for unit spawning |
| BOARD_COLS/ROWS unchanged | 8×5 matches contested.toml; dynamic sizing is future scope | game.gd _draw() and _input() boundaries still correct |

## Deviations from Plan

None. Plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- v0.7 Scenario System milestone is complete
- The scenario pattern (board file + units file) is established and working
- Both files are hand-editable and LLM-editable

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 18-unit-placement-wiring, Plan: 01*
*Completed: 2026-03-01*
