---
phase: 115-missing-units-cleanup
plan: 01
subsystem: data
tags: [toml, units, advancement-chains]

requires:
  - phase: 107-unit-tree-audit
    provides: unit tree structure and registry loader
provides:
  - General unit definition (completes Lieutenant advancement chain)
  - Verified all 132 units' advancement chains resolve
affects: [116-stat-verification, 117-integration-validation]

tech-stack:
  added: []
  patterns: []

key-files:
  created: [data/units/lieutenant/general/general.toml]
  modified: []

key-decisions:
  - "General is terminal (advances_to = []) — Grand Marshal not in our 4-faction tree"

patterns-established: []

duration: 15min
completed: 2026-03-11T00:00:00Z
---

# Phase 115 Plan 01: Missing Units + Cleanup Summary

**Created General unit TOML from Wesnoth WML; verified all 132 units' advancement chains resolve with zero dangling references.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-11 |
| Tasks | 2 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: General Unit Exists | Pass | Created with Wesnoth-sourced stats from Loyalist_General.cfg |
| AC-2: All Advancement Chains Resolve | Pass | 132 units, 84 advancement targets, zero dangling references |
| AC-3: Registry Loads Successfully | Pass | `cargo test --lib -- test_unit_registry_loads` passes |

## Accomplishments

- Created `data/units/lieutenant/general/general.toml` — Level 3 Loyalist leader with longsword + crossbow attacks
- Verified all 132 unit definitions across 4 factions have fully resolved advancement chains
- The only missing unit in the entire tree (General) is now present

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `data/units/lieutenant/general/general.toml` | Created | General unit definition (Lieutenant → General chain) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| General advances_to = [] (terminal) | Grand Marshal doesn't exist in our 4-faction tree | No impact — consistent with other terminal level 3 units |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- All 132 units have valid advancement chains
- Registry loads all units without errors
- Ready for Phase 116 stat verification against Wesnoth WML

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 115-missing-units-cleanup, Plan: 01*
*Completed: 2026-03-11*
