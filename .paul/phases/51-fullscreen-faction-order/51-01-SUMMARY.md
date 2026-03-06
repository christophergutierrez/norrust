---
phase: 51-fullscreen-faction-order
plan: 01
subsystem: ui
tags: [love2d, window, factions]

provides:
  - Maximized window on launch
  - Alphabetically sorted faction list
affects: []

key-files:
  modified: [norrust_love/conf.lua, norrust_love/main.lua]

key-decisions:
  - "love.window.maximize() instead of desktop fullscreen — preserves title bar close button"

duration: 5min
completed: 2026-03-05
---

# Phase 51 Plan 01: Fullscreen & Faction Order Summary

**Maximized window on launch + alphabetical faction sorting (Elves, Loyalists, Orcs)**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Fullscreen on Launch | Pass | Window maximized via love.window.maximize() |
| AC-2: Alphabetical Faction Order | Pass | table.sort by name after engine load |

## Accomplishments

- Window opens maximized on launch (fills screen, title bar preserved)
- Faction list sorted alphabetically: Elves, Loyalists, Orcs — consistent every launch

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/conf.lua` | No net change | Fullscreen added then reverted in favor of maximize |
| `norrust_love/main.lua` | Modified | Added table.sort for factions + love.window.maximize() in love.load |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| love.window.maximize() instead of fullscreen | Desktop fullscreen removes title bar, losing the X close button | Window fills screen but remains a decorated window |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential fix — desktop fullscreen removed close button |

**1. Fullscreen approach changed to maximize**
- **Found during:** Human verification checkpoint
- **Issue:** Desktop fullscreen removes window decorations including close button
- **Fix:** Removed conf.lua fullscreen flags, added love.window.maximize() in love.load()
- **Verification:** Human confirmed maximized window with close button works

## Next Phase Readiness

**Ready:**
- Window is maximized, providing large viewport for Phase 52 zoom work

**Blockers:** None

---
*Phase: 51-fullscreen-faction-order, Plan: 01*
*Completed: 2026-03-05*
