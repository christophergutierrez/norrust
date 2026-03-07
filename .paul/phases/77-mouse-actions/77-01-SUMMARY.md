---
phase: 77-mouse-actions
plan: 01
subsystem: ui
tags: [love2d, mouse, buttons, sidebar]

requires:
  - phase: 76-help-overlay
    provides: show_help toggle pattern
provides:
  - Clickable sidebar buttons (End Turn, Recruit, Help)
affects: []

tech-stack:
  added: []
  patterns: [sidebar button click detection via shared.buttons coordinate table]

key-files:
  modified:
    - norrust_love/main.lua
    - norrust_love/draw.lua

key-decisions:
  - "recruit_palette moved to shared table to free upvalue slot for love.mousepressed"
  - "Button click handler as shared.handle_sidebar_button to avoid upvalue overflow"
  - "Auto-save reduced: only on player win, not every end turn"

duration: 15min
completed: 2026-03-07
---

# Phase 77 Plan 01: Mouse Actions Summary

**Clickable sidebar buttons (End Turn, Recruit, Help) + auto-save reduced to win-only.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-07 |
| Tasks | 1 auto + 1 checkpoint |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: End Turn button works | Pass | Clicks sidebar button, triggers same as E key |
| AC-2: Recruit button works | Pass | Clicks sidebar button, triggers same as R key |
| AC-3: Help button works | Pass | Clicks sidebar button, toggles help overlay |

## Accomplishments

- Three sidebar buttons at bottom: End Turn (faction-colored), Recruit (green), Help (gray)
- Buttons only show when appropriate (End Turn/Recruit only during gameplay)
- Click detection via coordinate table passed from draw to main via shared.buttons
- Auto-save changed from every end turn to player-win only (user request)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Button click handler, shared.buttons, recruit_palette to shared, auto-save reduction |
| `norrust_love/draw.lua` | Modified | draw_sidebar_buttons() with 3 buttons at bottom of sidebar |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| recruit_palette moved to shared | LuaJIT 60-upvalue limit in love.mousepressed | Frees slot for button handler |
| shared.handle_sidebar_button | Separate closure avoids adding upvalues to mousepressed | Clean separation |
| love.keypressed("e"/"r") for button actions | Reuses existing key handler logic without duplication | DRY |
| Auto-save on win only | User requested less aggressive saves; F5 manual save still available | Better UX |

## Deviations from Plan

### Auto-fixed Issues

**1. LuaJIT 60-upvalue limit (twice)**
- **Found during:** Task 1 syntax check
- **Issue:** love.mousepressed already at 60 upvalues; adding button handler overflowed
- **Fix:** Moved recruit_palette to shared table, button handler as shared method
- **Files:** norrust_love/main.lua

### Scope Addition

**1. Auto-save reduction (user request during checkpoint)**
- Removed auto-save on every end turn
- Added auto-save on player win only
- F5 manual save unchanged

## Issues Encountered

None beyond upvalue limit (resolved).

## Next Phase Readiness

**Ready:**
- v2.7 Controls & Help milestone complete

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 77-mouse-actions, Plan: 01*
*Completed: 2026-03-07*
