---
phase: 21-factions-recruitment
plan: 01
subsystem: economy
tags: [rust, factions, gold, schema, bridge, gdscript]

requires:
  - phase: 20-gold-economy
    provides: state.gold [u32; 2] initialized at GameState::new()

provides:
  - FactionDef.starting_gold: u32 (default 100, loaded from TOML)
  - apply_starting_gold(f0_id, f1_id) bridge — sets state.gold from faction definitions
  - game.gd calls apply_starting_gold when entering PLAYING mode

affects: [21-02-recruit]

tech-stack:
  added: []
  patterns: [#[serde(default = "default_starting_gold")] — same as existing UnitDef defaults]

key-files:
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/gdext_node.rs
    - norrust_client/scripts/game.gd
    - norrust_core/tests/simulation.rs
  data:
    - data/factions/loyalists.toml
    - data/factions/elves.toml
    - data/factions/orcs.toml

key-decisions:
  - "starting_gold = 100 — Wesnoth standard starting gold"
  - "apply_starting_gold() bridge pattern — GDScript knows both IDs at transition, pushes into state.gold"
  - "No change to GameState::new() — [10,10] remains bare-board default; apply_starting_gold overwrites"

patterns-established:
  - "Bridge method sets state field from faction registry — same push-from-bridge pattern as set_terrain_at()"

duration: ~10min
started: 2026-03-02T00:00:00Z
completed: 2026-03-02T00:00:00Z
---

# Phase 21 Plan 01: FactionDef.starting_gold + Wiring Summary

**FactionDef now carries starting_gold; bridge wires it into state.gold when the game begins.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Tasks | 4 completed |
| Files modified | 7 (3 Rust, 1 GDScript, 3 data) |
| Tests before | 65 |
| Tests after | 66 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: FactionDef.starting_gold deserializes from TOML | Pass | `test_faction_def_starting_gold_loads` passes; default 100 if field absent |
| AC-2: apply_starting_gold sets both state.gold entries | Pass | Bridge implemented and verified via game flow |
| AC-3: game.gd calls apply_starting_gold entering PLAYING | Pass | Wired at SETUP_RED → PLAYING Enter key transition |
| AC-4: All existing tests still pass | Pass | 66 tests (55 lib + 11 integration) |

## Accomplishments

- `FactionDef.starting_gold: u32` — `#[serde(default = "default_starting_gold")]` = 100
- `data/factions/*.toml` — `starting_gold = 100` added to loyalists, elves, orcs
- `apply_starting_gold(f0_id, f1_id)` bridge — looks up both faction defs, sets `state.gold = [g0, g1]`
- `game.gd` — calls bridge when entering PLAYING mode; gold is now faction-driven, not hardcoded
- `test_faction_def_starting_gold_loads` integration test — verifies registry + field value

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/schema.rs` | Added `default_starting_gold()` fn + `starting_gold` field | Schema definition |
| `norrust_core/src/gdext_node.rs` | Added `apply_starting_gold()` bridge | Push starting gold into state |
| `norrust_client/scripts/game.gd` | Added `apply_starting_gold` call at PLAYING transition | Wire at game start |
| `data/factions/loyalists.toml` | Added `starting_gold = 100` | Data |
| `data/factions/elves.toml` | Added `starting_gold = 100` | Data |
| `data/factions/orcs.toml` | Added `starting_gold = 100` | Data |
| `norrust_core/tests/simulation.rs` | Added `test_faction_def_starting_gold_loads` | Verification |

## Discovery: Most of Phase 21 Already Existed

Code review during PLAN revealed that nearly all faction infrastructure was pre-built:
`FactionDef`, `RecruitGroup`, `load_factions()`, `get_faction_ids_json()`, `get_faction_leader()`,
`get_faction_recruits_json()`, faction/recruit-group TOMLs, and the full GDScript setup flow
(faction picker → setup → PLAYING) were all present. Plan 21-01 only needed the `starting_gold` link.

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `starting_gold = 100` | Wesnoth standard; meaningful enough to recruit several units | Plan 21-02 recruitment spending works with real values |
| `apply_starting_gold` as separate bridge call | GDScript knows both IDs only at PLAYING transition; cleaner than auto-wiring in load_factions() | Explicit call = predictable timing |
| `GameState::new()` unchanged | [10,10] is a valid bare-board default for tests | No test breakage |

## Deviations from Plan

None — executed exactly as specified.

## Next Phase Readiness

**Ready for 21-02:**
- `state.gold` is now faction-driven (100 per faction at game start)
- `FactionDef.recruits` (expanded unit def IDs) already available via bridge
- Castle terrain TOML (`data/terrain/castle.toml`) exists with correct properties
- Ready to add castle hexes to `contested.toml` and implement `Action::Recruit`

**Concerns:** None

**Blockers:** None

---
*Phase: 21-factions-recruitment, Plan: 01*
*Completed: 2026-03-02*
