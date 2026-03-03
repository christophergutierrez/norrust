---
phase: 29-second-scenario
plan: 01
subsystem: game-engine
tags: [trigger-zones, scenario, ffi, toml, hex]

requires:
  - phase: 28-map-crossing
    provides: LoadedBoard, objective hex, max_turns, preset_units pattern, scenario selection
provides:
  - TriggerZone system (schema, runtime, Move integration)
  - Ambush scenario (12x8 board + trigger zones + preset units)
  - norrust_get_next_unit_id FFI function
  - Headless scenario validation test suite
affects: [30-campaign-chain]

tech-stack:
  added: []
  patterns: [trigger-zone spawn-on-entry, two-phase borrow pattern for spawns]

key-files:
  created:
    - scenarios/ambush.toml
    - scenarios/ambush_units.toml
    - norrust_core/tests/scenario_validation.rs
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/game_state.rs
    - norrust_core/src/scenario.rs
    - norrust_core/src/ffi.rs
    - norrust_core/tests/simulation.rs
    - norrust_love/main.lua
    - norrust_love/norrust.lua
    - scenarios/crossing.toml
    - scenarios/crossing_units.toml

key-decisions:
  - "TriggerZone with PendingSpawn: pre-built Units with assigned IDs at load time"
  - "Two-phase drain pattern: collect spawns into local Vec, then place — avoids borrow conflict"
  - "trigger_faction defaults to 0 (player) via serde default"
  - "Headless scenario validation: auto-discover + 10 structural invariants + false-winner check"

patterns-established:
  - "Trigger zones: schema (TriggerDef/TriggerSpawnDef) → load_triggers() → PendingSpawn/TriggerZone runtime → fire in apply_action::Move"
  - "Scenario validation: discover_scenarios() auto-finds all TOML pairs; new scenarios validated automatically"

duration: ~2 sessions
completed: 2026-03-03
---

# Phase 29 Plan 01: Trigger Zones + Ambush Scenario Summary

**Trigger zone system with enemy spawn-on-entry, 12x8 ambush scenario with 3 hidden reinforcement zones, and headless scenario validation test suite**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~2 sessions |
| Completed | 2026-03-03 |
| Tasks | 2 completed (Rust core + Love2D client) |
| Files created | 3 |
| Files modified | 9 |
| Tests | 83 total (56 lib + 23 integration + 3 scenario_validation + 1 FFI) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Trigger zone spawns enemies on player move | Pass | test_trigger_zone_spawns_units |
| AC-2: Trigger fires only once | Pass | test_trigger_fires_only_once |
| AC-3: Trigger skips occupied spawn hexes | Pass | test_trigger_skips_occupied_hex |
| AC-4: Trigger only fires for designated faction | Pass | test_trigger_faction_filter |
| AC-5: Ambush scenario loads and plays | Pass | FFI smoke test + manual verification |
| AC-6: Love2D uses get_next_unit_id for recruitment | Pass | norrust.lua wrapper + main.lua wired |

## Accomplishments

- **TriggerZone system** — `TriggerDef`/`TriggerSpawnDef` schema, `PendingSpawn`/`TriggerZone` runtime structs, fire-on-Move integration with two-phase drain pattern, `load_triggers()` loader, `norrust_get_next_unit_id()` FFI
- **Ambush scenario** — 12x8 forest-heavy board with Blue keep (1,4), Red keep (10,4), 25-turn limit, 3 trigger zones spawning 5 hidden enemies (Spearman, Bowman, Heavy Infantryman)
- **Headless scenario validation** — `scenario_validation.rs` with auto-discovery, 10 structural invariants, false-winner detection, FFI symbol completeness test, and per-scenario FFI smoke test
- **Crossing scenario fixes** — Blue castle ring at (2,4)/(2,6) fixed from forest→castle; Red keep position aligned (objective→col 13)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `scenarios/ambush.toml` | Created | 12x8 forest-heavy board with keeps, castles, objective, 25-turn limit |
| `scenarios/ambush_units.toml` | Created | 6 units + 3 trigger zones with 5 hidden spawns |
| `norrust_core/tests/scenario_validation.rs` | Created | Auto-discovery validation: 10 invariants + false winner + FFI tests |
| `norrust_core/src/schema.rs` | Modified | TriggerSpawnDef, TriggerDef structs; UnitsDef.triggers field |
| `norrust_core/src/game_state.rs` | Modified | PendingSpawn, TriggerZone, trigger_zones/next_unit_id on GameState, fire in Move |
| `norrust_core/src/scenario.rs` | Modified | load_triggers() function |
| `norrust_core/src/ffi.rs` | Modified | norrust_get_next_unit_id(), trigger loading in norrust_load_units() |
| `norrust_core/tests/simulation.rs` | Modified | 4 new trigger zone integration tests |
| `norrust_love/norrust.lua` | Modified | FFI cdef + Lua wrapper for get_next_unit_id |
| `norrust_love/main.lua` | Modified | Ambush in SCENARIOS table, get_next_unit_id wiring |
| `scenarios/crossing.toml` | Modified | Fixed Blue castle ring + Red keep objective position |
| `scenarios/crossing_units.toml` | Modified | Swapped Red leader/spearman positions to match keep |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Pre-built Units in PendingSpawn at load time | Avoids registry access at trigger-fire time; IDs assigned sequentially | next_unit_id tracks highest assigned ID |
| Two-phase drain for spawn placement | Mutable borrow conflict: can't iterate trigger_zones and mutate state simultaneously | Clean pattern, no unsafe |
| trigger_faction defaults to 0 via serde | Most triggers are player-activated; AI triggers opt-in | Backward compatible |
| Relaxed invariant 6 for leader-less scenarios | contested.toml has no leaders (pure combat scenario) | Check only when faction has leader units |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential fixes, no scope creep |
| Scope additions | 1 | Headless validation test suite (separate milestone) |

**Total impact:** Fixes caught real bugs; validation suite prevents future regressions

### Auto-fixed Issues

**1. Crossing scenario: Blue castle ring incomplete**
- **Found during:** Scenario validation testing
- **Issue:** Hexes (2,4) and (2,6) were "forest" instead of "castle" — Blue keep had 4/6 castles
- **Fix:** Changed both tiles to "castle" in crossing.toml
- **Verification:** test_all_scenarios_valid passes invariant 7

**2. Crossing scenario: Red keep position mismatch**
- **Found during:** Scenario validation testing
- **Issue:** Keep tile at (13,5) but objective_col=14 and leader at (14,5)
- **Fix:** Changed objective_col to 13; swapped leader/spearman positions in crossing_units.toml
- **Verification:** test_all_scenarios_valid + test_all_scenarios_ffi_smoke pass

### Scope Addition

**Headless scenario validation test suite** — implemented as a separate "Headless Scenario Validation" milestone before the PAUL unify. Added `scenario_validation.rs` (538 lines) with:
- Auto-discovery of all scenario TOML pairs
- 10 structural invariants (terrain, registry, bounds, duplicates, keep/castle rings, objectives, triggers)
- False-winner detection via real GameState
- FFI symbol completeness test (all 39 functions)
- Per-scenario FFI smoke test (load, no winner, 2 AI turns, queryable)

## Issues Encountered

None — plan executed cleanly.

## Next Phase Readiness

**Ready:**
- Both scenarios (crossing + ambush) validated and playable
- Trigger zone system extensible for future scenarios
- All 83 tests passing — strong regression safety net
- Scenario validation catches structural bugs automatically

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 29-second-scenario, Plan: 01*
*Completed: 2026-03-03*
