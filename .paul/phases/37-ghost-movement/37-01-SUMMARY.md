---
phase: 37-ghost-movement
plan: 01
subsystem: ui
tags: [ghost-movement, tactical-planning, love2d, state-machine]

requires:
  - phase: 36-terrain-info-panel
    provides: right-click terrain inspection, TileSnapshot terrain stats
provides:
  - Ghost movement state machine (Select → Ghost → Commit/Cancel/Attack)
  - Translucent unit rendering at ghost position
  - Adjacent enemy highlighting from ghost position
  - Escape/Enter keyboard controls for cancel/commit
affects: [38-combat-preview, 39-commit-cancel-flow]

tech-stack:
  added: []
  patterns: [ghost state machine, odd-r hex neighbor table in Lua, goto continue for loop skip]

key-files:
  created: []
  modified:
    - norrust_love/main.lua

key-decisions:
  - "Ghost is purely client-side — no engine state until commit"
  - "Hex neighbor table in Lua (odd-r offset) rather than new FFI function"
  - "goto continue pattern for skipping ghost unit in draw_units loop"

patterns-established:
  - "Ghost state variables (ghost_col/row/unit_id/attackable) as module-level state"
  - "get_adjacent_enemies() using Lua-side odd-r neighbor table"
  - "commit_ghost_move() keeps unit selected after move for follow-up actions"

duration: ~15min
completed: 2026-03-04
---

# Phase 37 Plan 01: Ghost Movement Summary

**Two-step ghost positioning replaces immediate click-to-move — translucent preview with adjacent enemy highlighting and commit/cancel flow.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-04 |
| Tasks | 3 completed |
| Files modified | 1 (main.lua only) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Ghost positioning | Pass | Click reachable hex → translucent unit appears, not moved in engine |
| AC-2: Adjacent enemy highlighting | Pass | Red/orange borders on enemies adjacent to ghost position |
| AC-3: Re-ghost | Pass | Click different reachable hex → ghost moves, highlights update |
| AC-4: Cancel ghost | Pass | Escape cancels ghost, unit stays selected at original position |
| AC-5: Commit move | Pass | Enter or click ghost hex commits the engine move |
| AC-6: Attack from ghost | Pass | Click highlighted enemy → move + attack executes |

## Accomplishments

- Replaced immediate click-to-move with ghost preview state machine
- Added translucent unit rendering at ghost position with dim outline at original
- Adjacent enemies highlighted with red/orange hex border from ghost position
- Escape cancels, Enter commits, click enemy attacks — full keyboard + mouse flow
- Zero Rust changes — entirely client-side in Love2D

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Ghost state vars, hex_neighbors(), get_adjacent_enemies(), ghost rendering, click handler rewrite |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Lua-side hex neighbors (not FFI) | Simple odd-r offset table, no Rust needed | Fast, no cross-boundary overhead |
| Ghost purely client-side | Engine state unchanged until commit | Clean separation, easy cancel |
| Unit stays selected after commit | Allows follow-up attack or re-inspect | Natural flow for Phase 39 |

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- Ghost position established — combat preview can query "what if unit attacks from here?"
- get_adjacent_enemies() available for combat preview target selection
- State machine ready for Phase 39 commit/cancel extension

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 37-ghost-movement, Plan: 01*
*Completed: 2026-03-04*
