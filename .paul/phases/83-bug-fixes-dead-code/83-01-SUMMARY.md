---
phase: 83-bug-fixes-dead-code
plan: 01
subsystem: lua
tags: [bugfix, dead-code, cleanup, comments]

requires: [82-shared-table-split]
provides:
  - Correct status message rendering under UI_SCALE
  - Correct font selection for status messages
  - Reduced upvalue pressure in love.load (55, down from ~59)
affects: []

tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified: [norrust_love/main.lua, norrust_love/input.lua]

key-decisions:
  - "fonts[14] for status messages (integer-keyed font table)"
  - "Status message wrapped in push/scale/pop for correct UI_SCALE rendering"

patterns-established: []

duration: ~5min
completed: 2026-03-07
---

# Phase 83 Plan 01: Bug Fixes & Dead Code Summary

**Fixed 2 bugs (fonts.medium nil, status message transform), removed 4 dead code items, cleaned 3 stale comments. love.load upvalues reduced from ~59 to 55.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5min |
| Completed | 2026-03-07 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: fonts.medium bug fixed | Pass | fonts[14] used instead of nil fonts.medium |
| AC-2: Status message UI_SCALE | Pass | Wrapped in push/scale(UI_SCALE)/pop |
| AC-3: Dead code removed | Pass | shared.handle_sidebar_button, 3 unused input.lua locals, redundant sidebar check |
| AC-4: Stale comments updated | Pass | game.gd ref, "two functions", empty helpers header |
| AC-5: Functionality preserved | Pass | Syntax checks pass, human-verified gameplay |

## Accomplishments

- Fixed fonts.medium → fonts[14] (font table is integer-keyed)
- Fixed status message rendering with UI_SCALE push/pop transform
- Removed shared.handle_sidebar_button (dead wrapper)
- Removed 3 unused input.lua locals (FACTION_COLORS, clamp, fire_hex_entered) + corresponding ctx fields
- Removed redundant second sidebar boundary check in input.lua mousepressed
- Cleaned 3 stale comments
- love.load upvalues: ~59 → 55 (5 slots headroom)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Bug fixes, dead code removal, comment cleanup |
| `norrust_love/input.lua` | Modified | Unused locals removed, redundant check removed |

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- Phase 84 (Draw Cleanup) has no blockers

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 83-bug-fixes-dead-code, Plan: 01*
*Completed: 2026-03-07*
