---
phase: 76-help-overlay
plan: 01
subsystem: ui
tags: [love2d, help, keybindings, overlay]

requires: []
provides:
  - Help overlay toggled with ? key showing all keybindings
affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  modified:
    - norrust_love/main.lua
    - norrust_love/draw.lua

key-decisions:
  - "show_help stored in shared table (not local) to avoid LuaJIT 60-upvalue limit"
  - "? key mapped to '/' in Love2D keypressed handler"

duration: 10min
completed: 2026-03-07
---

# Phase 76 Plan 01: Help Overlay Summary

**Toggleable help overlay (? key) showing all keybindings in three columns: Global, Gameplay, Menu.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-03-07 |
| Tasks | 1 auto + 1 checkpoint |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Help overlay toggles with ? key | Pass | ? toggles overlay from any mode |
| AC-2: Shows correct keybindings | Pass | Three columns with accurate descriptions |
| AC-3: Doesn't block input | Pass | Any other key closes overlay and functions normally |

## Accomplishments

- Help overlay with semi-transparent background over board area
- Three-column layout: Global (?, M, -/=, F5, F9, scroll, drag), Gameplay (click, enter, escape, E, R, A, H, P), Menu (1-9, C)
- Dismisses on any key press (key still functions)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | show_help state in shared table, ? key handler, ctx passthrough |
| `norrust_love/draw.lua` | Modified | draw_help_overlay() function with 3-column keybinding display |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| shared.show_help (not local) | LuaJIT 60-upvalue limit in love.keypressed | Consistent with existing pattern |
| Key "/" for ? | Love2D reports "/" for the ? key | Works correctly |

## Deviations from Plan

### Auto-fixed Issues

**1. LuaJIT 60-upvalue limit**
- **Found during:** Task 1 syntax check
- **Issue:** Adding `show_help` as local exceeded upvalue limit in love.keypressed
- **Fix:** Moved to `shared.show_help` table (existing pattern)

**2. Help text accuracy**
- **Found during:** Checkpoint verification (user feedback)
- **Issue:** A described as generic "Advance unit", P described as "Toggle path display" (incorrect)
- **Fix:** A = "Advance unit (when ready)", P = "Toggle agent server"

## Issues Encountered

None beyond auto-fixed items.

## Next Phase Readiness

**Ready:**
- Help overlay complete, Phase 77 (Mouse Actions) can proceed

**Concerns:**
- None

**Blockers:**
- None

### New Deferred Issue

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| Recruit highlights all castle hexes but only adjacent ones accept placement | Phase 76 (user report) | S | future |

---
*Phase: 76-help-overlay, Plan: 01*
*Completed: 2026-03-07*
