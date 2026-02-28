---
phase: 02-headless-core
plan: 04
subsystem: core
tags: [combat, rng, time-of-day, alignment, damage, death]

# Dependency graph
requires:
  - phase: 02-headless-core
    provides: GameState + apply_action stub (02-02), Board terrain (02-03)
provides:
  - Rng (Xorshift64): deterministic seeded RNG, no external crate
  - Alignment enum (in unit.rs): Lawful, Chaotic, Liminal
  - TimeOfDay + time_of_day() + tod_damage_modifier()
  - resolve_attack(): per-strike hit/miss + ToD-scaled damage
  - apply_action(Attack): full implementation with dead-unit removal
  - Unit gains: max_hp, alignment, attacks, defense, default_defense

affects: [02-05-simulation]

# Tech stack
tech-stack:
  added: []
  patterns:
    - Xorshift64 RNG implemented inline — no rand crate dependency
    - Alignment defined in unit.rs to avoid circular import with combat.rs
    - Unit carries combat data (attacks, defense map) — no registry coupling in apply_action
    - Attack handler: validate → gather (immutable borrows) → resolve (mutable rng) → apply

key-files:
  created:
    - norrust_core/src/combat.rs
  modified:
    - norrust_core/src/unit.rs
    - norrust_core/src/game_state.rs
    - norrust_core/src/lib.rs

key-decisions:
  - "Alignment in unit.rs: prevents circular import (combat imports unit, not vice versa)"
  - "Rng derives Debug+Clone: required since GameState derives both"
  - "Unit.default_defense = 40 in Unit::new(): reasonable baseline, zero for test units"
  - "No defender retaliation: deferred to Phase 4 (bidirectional combat)"

patterns-established:
  - "apply_action(Attack) borrow pattern: split into named scopes to satisfy borrow checker"
  - "saturating_sub for HP: prevents underflow, defender.hp == 0 triggers removal"

# Metrics
duration: ~20min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 2 Plan 04: Combat Resolution Summary

**Xorshift64 RNG, ToD alignment modifiers, per-strike hit/miss resolution, and `apply_action(Attack)` with dead-unit removal — 26 tests passing, clippy clean.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files modified | 4 (combat new, unit, game_state, lib) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: ToD Damage Modifier Applied Exactly | Pass | 4 × 125/100 = 5; integer arithmetic confirms +25% |
| AC-2: Hit Rate Matches Terrain Defense | Pass | Seed=1, 10k rolls: hits in [3500,4500] at 40% hit rate |
| AC-3: Defender Death Purges Unit from GameState | Pass | unit 2 absent from state.units and state.positions after lethal attack |

## Accomplishments

- `combat.rs`: `Rng` (Xorshift64), `TimeOfDay`, `time_of_day()`, `tod_damage_modifier()`, `resolve_attack()`
- `unit.rs`: `Alignment` enum, `Unit` gains `max_hp`, `alignment`, `attacks`, `defense`, `default_defense`
- `game_state.rs`: `GameState.rng`, `new_seeded()`, `apply_action(Attack)` fully implemented
- All 26 tests pass; `cargo clippy -- -D warnings` clean

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/combat.rs` | Created | Rng, TimeOfDay, resolve_attack — 2 tests |
| `norrust_core/src/unit.rs` | Modified | Alignment enum + 5 new Unit fields with defaults |
| `norrust_core/src/game_state.rs` | Modified | rng field, new_seeded(), Attack handler, death removal |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod combat;` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `Alignment` in `unit.rs`, not `combat.rs` | `combat.rs` uses `Alignment`; if `unit.rs` also imported `combat.rs`, circular dependency | Clean: `unit → schema`, `combat → unit`, `game_state → combat + unit` |
| `#[derive(Debug, Clone)]` on `Rng` | `GameState` derives both; compiler error without it | Rng state is just a u64 — trivially clonable/debuggable |
| `Unit.default_defense = 40` in `Unit::new()` | Sensible mid-range default; tests that need 0% defense set explicitly | Existing tests unaffected (they don't exercise Attack) |
| No defender retaliation | Out of scope for Phase 2; adds significant complexity | Deferred to Phase 4 |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Compile errors, minimal impact |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Two compile-time fixes, no scope creep.

### Auto-fixed Issues

**1. Operator precedence: `as u32 < hit_pct` parse error**
- **Found during:** Task 1 compilation
- **Issue:** Rust parses `expr as u32 < hit_pct` as `expr as (u32 < hit_pct)` (generic syntax), causing a parse error
- **Fix:** `((self.next_u64() % 100) as u32) < hit_pct` — explicit parentheses

**2. `Rng` missing `Debug` + `Clone` derives**
- **Found during:** Task 2 compilation (GameState derives both)
- **Issue:** `Rng` is a field of `GameState`; without derives, GameState can't derive them
- **Fix:** Added `#[derive(Debug, Clone)]` to `Rng`

## Next Phase Readiness

**Ready:**
- `apply_action(Move)`, `apply_action(Attack)`, `apply_action(EndTurn)` all functional
- Combat math (ToD, hit/miss, damage) fully exercised
- Dead-unit removal tested

**Concerns:**
- `apply_action(Move)` still only checks bounds/occupancy — terrain budget and ZOC not enforced (Plan 02-05 integration)
- No defender retaliation (Phase 4)

**Blockers:**
- None

---
*Phase: 02-headless-core, Plan: 04*
*Completed: 2026-02-27*
