---
phase: 84-draw-cleanup
plan: 01
subsystem: lua
tags: [refactor, draw, dedup, constants, cleanup]

requires: [83-bug-fixes-dead-code]
provides:
  - draw_unit_fallback() shared helper for unit circle rendering
  - Consistent C_GOLD constant usage in draw.lua
  - Direct sound.play in input.lua (no indirection)
affects: []

tech-stack:
  added: []
  patterns: [draw-helper-extraction]

key-files:
  created: []
  modified: [norrust_love/draw.lua, norrust_love/input.lua, norrust_love/main.lua]

key-decisions:
  - "draw_unit_fallback includes HP rendering (both fallback sites fully replaced)"
  - "Sprite path keeps its own HP rendering (sprites don't draw HP internally)"

patterns-established:
  - "Shared draw helpers at top of draw.lua for reusable rendering patterns"

duration: ~5min
completed: 2026-03-07
---

# Phase 84 Plan 01: Draw Cleanup Summary

**Deduplicated ghost unit fallback (~20 lines), replaced 3 inline gold colors with C_GOLD, removed play_sfx indirection.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5min |
| Completed | 2026-03-07 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: C_GOLD constant used | Pass | 3 inline gold tuples replaced |
| AC-2: Ghost fallback deduplicated | Pass | draw_unit_fallback() used by both sites |
| AC-3: play_sfx indirection removed | Pass | 2 call sites + 1 stash removed |
| AC-4: Functionality preserved | Pass | Syntax checks pass, human-verified |

## Accomplishments

- Extracted draw_unit_fallback() helper (circle + abbreviation + HP)
- Replaced draw_units fallback block with helper call
- Replaced ghost fallback block with helper call (~20 lines eliminated)
- 3 inline {1.0, 0.85, 0.0} → C_GOLD constant references
- sel.recruit_state.play_sfx → direct sound.play (2 sites in input.lua)
- Removed play_sfx stash from main.lua

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/draw.lua` | Modified | draw_unit_fallback helper, C_GOLD usage |
| `norrust_love/input.lua` | Modified | Direct sound.play replacing play_sfx |
| `norrust_love/main.lua` | Modified | Removed play_sfx stash |

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- v2.9 milestone complete (2/2 phases)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 84-draw-cleanup, Plan: 01*
*Completed: 2026-03-07*
