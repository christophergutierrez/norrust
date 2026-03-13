---
phase: 124-draw-layer-fog
plan: 01
subsystem: presentation
tags: [fog-of-war, lua, rendering, shroud, fog]

requires:
  - phase: 123-ffi-visibility-filtering
    provides: get_state_fow FFI, visible_hexes array
provides:
  - Fog/shroud rendering on game board
  - Client-side seen_hexes persistence across turns
  - Human player uses fog-filtered state
affects: [125-ai-fog-integration]

tech-stack:
  added: []
  patterns: [fog.seen/fog.visible client-side tracking]

key-files:
  modified: [norrust_love/main.lua, norrust_love/draw_board.lua, norrust_love/state.lua]

key-decisions:
  - "fog.seen persists across turns, fog.visible rebuilt each frame"
  - "Shroud (never seen) = 80% black, fog (previously seen) = 50% black"
  - "FOW only for single-player vs AI — faction 0 hardcoded as viewer"
  - "fog.enabled flag for future toggle"

patterns-established:
  - "Dual state path: PLAYING+fog → get_state_fow, else → get_state"

duration: ~10min
completed: 2026-03-13
---

# Phase 124 Plan 01: Draw Layer Fog Rendering Summary

**Fog of war rendering complete — shroud/fog overlays on board, enemy units hidden beyond vision, seen hexes persist across turns.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Human uses fow state | Pass | get_state_fow(engine, 0) in PLAYING mode |
| AC-2: Shrouded hexes dark | Pass | 80% black overlay on never-seen hexes |
| AC-3: Fogged hexes dimmed | Pass | 50% black overlay on previously-seen hexes |
| AC-4: Visible hexes normal | Pass | No overlay on currently visible hexes |
| AC-5: Seen hexes persist | Pass | fog.seen accumulates, cleared on scenario load |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/state.lua` | Modified | Added fog = {seen, visible, enabled} |
| `norrust_love/main.lua` | Modified | Switched to get_state_fow, fog tracking, reset on scenario load |
| `norrust_love/draw_board.lua` | Modified | Fog/shroud overlay pass after terrain rendering |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Deviations | 0 | None |

## Next Phase Readiness

**Ready:** FOW visual complete for human player
**Concerns:** AI still sees all (uses unfiltered state) — acceptable for now
**Blockers:** None

---
*Phase: 124-draw-layer-fog, Plan: 01*
*Completed: 2026-03-13*
