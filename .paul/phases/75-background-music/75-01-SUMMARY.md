---
phase: 75-background-music
plan: 01
subsystem: audio
tags: [love2d, music, sound, menu]

requires:
  - phase: 72-sound-assets
    provides: play_music/stop_music infrastructure in sound.lua
provides:
  - Menu music looping on scenario select screen
  - Music transitions (stop on scenario/campaign start, resume on return)
  - Global mute/volume controls (M/-/= work from any screen)
affects: []

tech-stack:
  added: []
  patterns: [global key handlers for sound controls]

key-files:
  created:
    - data/sounds/menu_music.ogg
  modified:
    - norrust_love/main.lua

key-decisions:
  - "Explicit stop_music() on scenario/campaign start rather than relying on scenario_loaded event timing"
  - "Sound controls (M/-/=) moved to global scope in love.keypressed, not mode-specific"

patterns-established:
  - "Global key handlers placed after F5/F9 save/load block, before mode-specific blocks"

duration: 15min
completed: 2026-03-07
---

# Phase 75 Plan 01: Background Music Summary

**Menu music loops on scenario select, stops on gameplay start, resumes on return. Sound controls work globally.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-07 |
| Tasks | 1 auto + 1 checkpoint |
| Files modified | 2 (1 moved, 1 edited) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Menu music plays on scenario select | Pass | play_music() in love.load() after sound.load() |
| AC-2: Menu music stops when scenario starts | Pass | Explicit stop_music() on scenario/campaign selection + scenario_loaded handler |
| AC-3: Menu music resumes on return | Pass | play_music() at both return-to-menu paths (campaign complete, individual scenario end) |

## Accomplishments

- Menu music (battle_background.ogg → data/sounds/menu_music.ogg) loops on scenario select
- Music stops when selecting any scenario or starting a campaign
- Menu music resumes when returning to scenario select after win/loss
- Mute (M) and volume (-/=) controls work from all game screens (moved to global scope)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `data/sounds/menu_music.ogg` | Moved | Renamed from battle_background.ogg in project root |
| `norrust_love/main.lua` | Modified | Menu music playback, stop on start, resume on return, global sound controls |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Explicit stop_music() at scenario/campaign selection | scenario_loaded event fires after load, but music should stop immediately on selection | Belt-and-suspenders reliability |
| Sound controls in global scope | M key was only in PLAYING block; unreachable from menu where music plays | Users can mute/adjust from any screen |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential fixes for usability |

**Total impact:** Essential fixes, no scope creep

### Auto-fixed Issues

**1. Mute unreachable from menu screen**
- **Found during:** Checkpoint verification
- **Issue:** M/-/= key handlers were inside PLAYING mode block, unreachable from PICK_SCENARIO
- **Fix:** Moved sound control handlers to global "available from any mode" section
- **Files:** norrust_love/main.lua
- **Verification:** User confirmed mute works from all screens

**2. Campaign start didn't stop menu music**
- **Found during:** Checkpoint verification
- **Issue:** Campaign start path relied on scenario_loaded event timing; music continued briefly
- **Fix:** Added explicit stop_music() calls when selecting scenarios and starting campaigns
- **Files:** norrust_love/main.lua
- **Verification:** User confirmed music stops on campaign start

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Mute key only in PLAYING block | Moved to global key handler section |
| Campaign music continuation | Added explicit stop_music() on campaign/scenario selection |

## Next Phase Readiness

**Ready:**
- Music system complete — menu + per-scenario + transitions all working
- v2.6 Music milestone fully delivered

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 75-background-music, Plan: 01*
*Completed: 2026-03-07*
