---
phase: 123-ffi-visibility-filtering
plan: 01
subsystem: engine
tags: [fog-of-war, ffi, visibility, snapshot-filtering]

requires:
  - phase: 122-core-visibility
    provides: compute_visibility(state, faction) → HashSet<Hex>
provides:
  - StateSnapshot::from_game_state_fow(state, faction) — filtered snapshot
  - norrust_get_state_json_fow FFI function
  - M.get_state_fow() Lua wrapper
  - visible_hexes field on StateSnapshot
affects: [124-draw-layer-fog, 125-ai-fog-integration]

tech-stack:
  added: []
  patterns: [fow-filtered snapshot with visible_hexes array]

key-files:
  modified: [norrust_core/src/snapshot.rs, norrust_core/src/ffi.rs, norrust_love/norrust.lua]

key-decisions:
  - "visible_hexes as Option<Vec<VisibleHex>> — None on unfiltered, Some on fow"
  - "Terrain always fully visible — fog only hides enemy units"
  - "No caching for fow queries (per-faction, simpler)"

patterns-established:
  - "Dual snapshot API: get_state (full, cached) vs get_state_fow (filtered, uncached)"

duration: ~5min
completed: 2026-03-13
---

# Phase 123 Plan 01: FFI Visibility Filtering Summary

**Fog-of-war filtered state query added — enemy units on non-visible hexes hidden from snapshot, visible_hexes array included.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Filtered snapshot hides invisible enemies | Pass | test_fow_snapshot_hides_invisible_enemies |
| AC-2: visible_hexes included in snapshot | Pass | Option<Vec<VisibleHex>> with skip_serializing_if |
| AC-3: FFI function returns filtered JSON | Pass | norrust_get_state_json_fow in ffi.rs |
| AC-4: Unfiltered get_state_json unchanged | Pass | Returns all units, visible_hexes=None (not serialized) |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/snapshot.rs` | Modified | VisibleHex struct, visible_hexes field, from_game_state_fow(), 2 tests |
| `norrust_core/src/ffi.rs` | Modified | norrust_get_state_json_fow(engine, faction) |
| `norrust_love/norrust.lua` | Modified | C declaration + M.get_state_fow(engine, faction) wrapper |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Deviations | 0 | None |

## Deferred Items

None.

## Next Phase Readiness

**Ready:**
- Lua can call `norrust.get_state_fow(engine, faction)` to get filtered state
- `visible_hexes` array available for fog/shroud rendering in Phase 124

**Concerns:** None

**Blockers:** None

---
*Phase: 123-ffi-visibility-filtering, Plan: 01*
*Completed: 2026-03-13*
