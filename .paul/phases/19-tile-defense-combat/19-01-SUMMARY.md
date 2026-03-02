---
phase: 19-tile-defense-combat
plan: 01
subsystem: combat
tags: [rust, combat, terrain, defense, fallback]

requires:
  - phase: 14-tile-runtime
    provides: Tile struct with defense field populated from TerrainDef at set_terrain_at()

provides:
  - Tile.defense wired into combat resolution fallback chain (attack + retaliation)
  - test_tile_defense_used_in_combat verifying both scenarios

affects: [ai-combat-scoring, future-combat-phases]

tech-stack:
  added: []
  patterns: [unit.defense[id] → tile.defense → unit.default_defense fallback chain]

key-files:
  modified: [norrust_core/src/game_state.rs]

key-decisions:
  - "Tile.defense is middle tier, not replacement — unit.default_defense remains last resort for bare-board tests"
  - "Both attack and retaliation paths updated symmetrically"

patterns-established:
  - "Terrain defense fallback: unit-specific → tile → unit-default (last resort)"

duration: ~10min
started: 2026-03-02T00:00:00Z
completed: 2026-03-02T00:00:00Z
---

# Phase 19 Plan 01: Tile Defense Combat Wiring Summary

**Tile.defense wired as fallback in combat resolution — both attack and retaliation paths now consult tile before unit.default_defense.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10 min |
| Tasks | 2 completed |
| Files modified | 1 |
| Tests before | 63 |
| Tests after | 64 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Tile defense used as fallback | Pass | tile.defense=100 → 0 damage in test |
| AC-2: Unit-specific entry beats Tile | Pass | unit.defense["hills"]=0 overrides tile.defense=100 |
| AC-3: Fallback to unit.default_defense when no tile | Pass | All 53 prior tests rely on this; all pass unchanged |
| AC-4: Retaliation uses same chain | Pass | Symmetrical change applied to retaliation block |
| AC-5: All existing tests pass | Pass | 64 total passing (54 lib + 10 integration) |

## Accomplishments

- Fallback chain `unit.defense[terrain_id] → tile.defense → unit.default_defense` now active in both combat paths
- `test_tile_defense_used_in_combat`: two scenarios cover AC-1 (tile blocks all hits at 100%) and AC-2 (unit entry wins at 0%)
- Zero regressions — all 53 prior lib tests unchanged

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/game_state.rs` | Modified (2 lookups + 1 test) | Wire Tile.defense into attack + retaliation fallback |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Keep `unit.default_defense` as last resort | Tests with no tile set still work; bare-board test pattern preserved | No existing test changes required |
| No change to `ai.rs` | AI scorer doesn't use combat fallback directly; terrain scoring is separate future scope | Deferred correctly per plan boundaries |

## Deviations from Plan

### Auto-fixed Issues

**1. Duplicate `#[test]` attribute**
- **Found during:** Task 2 (test insertion)
- **Issue:** Replacement string included `#[test]` before `fn test_attack_not_adjacent_returns_error`, but the original line was preceded by a separate `#[test]` not captured in the match — resulted in duplicate attribute
- **Fix:** Removed the duplicate with a second Edit call
- **Verification:** Compiler warning gone; test suite passes

**2. Scenario B assertion panic on killed defender**
- **Found during:** Task 2 first run
- **Issue:** `state.units[&2].hp` panics if the defender was killed (10 strikes × 10 dmg = 100 potential; 50 HP unit); with 0% defense the defender can die
- **Fix:** Changed to `state.units.get(&2).map(|u| u.hp).unwrap_or(0) < 50` — handles partial damage or death
- **Verification:** Test passes; both death and partial-damage cases satisfy "damage was dealt"

**Total impact:** Two auto-fixed issues; no scope creep; plan delivered exactly as specified.

## Next Phase Readiness

**Ready:**
- Combat mechanics are now fully data-driven from TOML terrain definitions
- Tile.defense, Tile.movement_cost, and Tile.healing all wired — terrain system complete
- Battle mechanics contract is stable — safe to build game systems on top

**Concerns:**
- AI scorer in `ai.rs` uses `unit.defense` map directly (not the new fallback chain) — consistent for now, but if terrain-aware AI scoring is ever needed, the same pattern should apply there

**Blockers:** None

---
*Phase: 19-tile-defense-combat, Plan: 01*
*Completed: 2026-03-02*
