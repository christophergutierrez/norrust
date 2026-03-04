---
phase: 38-combat-preview
plan: 01
subsystem: combat
tags: [monte-carlo, combat-preview, ffi, love2d, simulation]

requires:
  - phase: 37-ghost-movement
    provides: ghost state machine, ghost_attackable enemy list
provides:
  - Monte Carlo combat simulation (simulate_combat in Rust)
  - norrust_simulate_combat() FFI function returning JSON
  - Combat preview panel in Love2D sidebar
  - Preview-before-attack flow for both ghost and direct adjacent attacks
affects: [39-commit-cancel-flow]

tech-stack:
  added: []
  patterns: [Monte Carlo simulation with independent RNG seeds, range-aware combat preview]

key-files:
  created: []
  modified:
    - norrust_core/src/combat.rs
    - norrust_core/src/ffi.rs
    - norrust_love/norrust.lua
    - norrust_love/main.lua

key-decisions:
  - "Range-aware simulation: FFI calculates distance to determine melee vs ranged"
  - "Preview for both ghost and direct adjacent attacks"
  - "Double-click to confirm attack from preview"

patterns-established:
  - "combat_preview/combat_preview_target state variables for preview lifecycle"
  - "cancel_combat_preview() called from cancel_ghost() and clear_selection()"
  - "simulate_combat() takes range_needed parameter for melee/ranged"

duration: ~20min
completed: 2026-03-04
---

# Phase 38 Plan 01: Combat Preview Summary

**Monte Carlo combat simulation with preview panel — click enemy shows damage distributions before committing attack.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Completed | 2026-03-04 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Monte Carlo simulation function | Pass | simulate_combat() runs N simulations with independent RNG seeds, returns CombatPreview struct |
| AC-2: FFI function returns JSON | Pass | norrust_simulate_combat() returns full JSON with damage distributions, kill %, attack names |
| AC-3: Combat preview panel displayed | Pass | Panel shows on clicking enemy from ghost or direct adjacent — no state mutation |
| AC-4: Preview state navigation | Pass | Escape dismisses preview, Enter executes attack, click different enemy updates preview, double-click confirms |

## Accomplishments

- Added CombatPreview struct and simulate_combat() pure Rust function with range-aware attack selection
- FFI function calculates engagement distance and terrain defense from game state
- Combat preview panel renders in sidebar with color-coded kill probabilities
- Preview works for both ghost attacks (move + attack) and direct adjacent attacks
- 97 tests passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/combat.rs` | Modified | CombatPreview struct, simulate_combat() function, test_simulate_combat_distribution |
| `norrust_core/src/ffi.rs` | Modified | norrust_simulate_combat() FFI with distance-based range detection |
| `norrust_love/norrust.lua` | Modified | FFI declaration + simulate_combat() Lua wrapper |
| `norrust_love/main.lua` | Modified | combat_preview state, draw_combat_preview(), click handler + keypressed changes |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Range-aware simulation (melee/ranged) | Direct adjacent attacks can be ranged (distance 2); melee-only defender shouldn't show retaliation against ranged | Correct preview for all attack types |
| Preview for direct adjacent attacks too | User expects preview when clicking adjacent enemy without ghosting first | Consistent UX regardless of whether unit moved |
| Double-click to confirm attack | Natural interaction pattern; first click = preview, second click = execute | Phase 39 can refine this flow |
| Independent RNG seed per trial (i+1) | Reproducible but varied results across simulations | Deterministic preview for same game state |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential fixes for correct behavior |
| Scope additions | 1 | Direct adjacent attack preview |

**Total impact:** Essential fixes, improved UX coverage.

### Auto-fixed Issues

**1. Debug .so not rebuilt**
- **Found during:** Human verification
- **Issue:** norrust.lua loads from target/debug/ by default; `cargo test` doesn't rebuild cdylib
- **Fix:** Explicit `cargo build` after `cargo test` to rebuild debug .so
- **Verification:** Symbol found in .so, game launches

**2. Ranged attacks showed incorrect retaliation**
- **Found during:** Human verification
- **Issue:** simulate_combat() hardcoded "melee" range; ranged attackers incorrectly showed melee retaliation from defenders
- **Fix:** Added range_needed parameter to simulate_combat(); FFI calculates distance from attacker/defender positions
- **Verification:** Ranged attack preview correctly shows "No retaliation" for melee-only defenders

### Scope Addition

**Direct adjacent attack preview** — Plan only specified ghost-state preview. Added preview for direct adjacent attacks (no ghost needed) since the user expected consistent behavior.

## Next Phase Readiness

**Ready:**
- Combat preview panel established — Phase 39 can build "attack from" comparison on top
- simulate_combat() supports both melee and ranged engagements
- Preview state (combat_preview/combat_preview_target) clean lifecycle with cancel helpers

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 38-combat-preview, Plan: 01*
*Completed: 2026-03-04*
