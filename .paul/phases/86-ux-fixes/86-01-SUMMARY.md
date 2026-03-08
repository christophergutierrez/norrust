---
phase: 86-ux-fixes
plan: 01
subsystem: lua
tags: [ux, draw, recruit, combat-preview, advancement, zoom]

requires:
  - phase: 85-upvalue-reduction
    provides: MODES/game_data/mods table structure
provides:
  - Adjacent-only castle highlight in recruit mode
  - ToD label in combat preview panel
  - Advancement hint in unit inspection panel
  - Zoom-corrected setup placement prompt
affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: [norrust_love/draw.lua]

key-decisions:
  - "Castle adjacency uses hex.distance == 1 (not square grid dx/dy check)"
  - "ToD label from get_time_of_day_name placed below combat preview header"
  - "Advancement hint text in gold after XP line in unit panel"
  - "Setup prompt zoom: board_origin + zoom * (hex_pos + camera_offset)"

patterns-established: []

duration: ~10min
completed: 2026-03-07
---

# Phase 86 Plan 01: UX Fixes Summary

**4 UX polish fixes in draw.lua: adjacent-only recruit castle highlight, combat preview ToD label, advancement hint text, zoom-corrected setup prompt.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-03-07 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Recruit castle highlight limited to adjacent | Pass | hex.distance == 1 check |
| AC-2: Combat preview shows ToD label | Pass | "Time: Dawn" etc. below header |
| AC-3: Advancement hint in unit panel | Pass | Gold "Ready to advance! [A]" text |
| AC-4: Setup prompt zoom-corrected | Pass | zoom * (bx + offset) formula |
| AC-5: All functionality preserved | Pass | Syntax check + human-verified |

## Accomplishments

- Recruit highlight now only shows castles adjacent to keeps (hex.distance == 1)
- Combat preview panel displays current Time of Day name
- Unit panel shows gold "Ready to advance! [A]" when advancement_pending
- Setup placement prompt correctly positioned at all zoom levels

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/draw.lua` | Modified | All 4 UX fixes |

## Deviations from Plan

### Castle adjacency fix required iteration
- Initial implementation used square-grid `dx<=1, dy<=1` check
- Human-verify caught this — too many castles highlighted
- Fixed to use `hex.distance(tc, tr, k.col, k.row) == 1` for correct hex adjacency

## Next Phase Readiness

**Ready:**
- v3.0 milestone complete (2/2 phases)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 86-ux-fixes, Plan: 01*
*Completed: 2026-03-07*
