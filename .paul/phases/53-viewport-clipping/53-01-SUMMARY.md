---
phase: 53-viewport-clipping
plan: 01
subsystem: ui
tags: [love2d, scissor, clipping, panel]

provides:
  - Board rendering clipped at panel boundary
  - Click input respects panel boundary
affects: []

key-files:
  modified: [norrust_love/draw.lua, norrust_love/main.lua]

key-decisions:
  - "love.graphics.setScissor in pixel coords (not UI_SCALE-divided) for correct clipping"
  - "Single click guard at top of love.mousepressed covers all click paths"

duration: 5min
completed: 2026-03-05
---

# Phase 53 Plan 01: Viewport Clipping Summary

**Board rendering scissor-clipped at right panel edge + click guard for panel region**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Board Clipped at Panel Edge | Pass | setScissor(0, 0, sw - 200*UI_SCALE, sh) before board draw |
| AC-2: Clicks in Panel Area Don't Hit Board | Pass | Early return when x >= vp_w - 200 |
| AC-3: All Scenarios Work | Pass | Tested at multiple zoom levels |

## Accomplishments

- Board hexes and units clip at the right panel boundary — no content hidden under sidebar
- Clicks in the panel region (rightmost 200px) don't select or target board hexes
- Scissor works correctly at all zoom levels and scenarios

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/draw.lua` | Modified | setScissor before board-space draw, clear after pop |
| `norrust_love/main.lua` | Modified | Click guard at top of love.mousepressed |

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:** v1.9 milestone complete — all 3 phases done.

**Blockers:** None

---
*Phase: 53-viewport-clipping, Plan: 01*
*Completed: 2026-03-05*
