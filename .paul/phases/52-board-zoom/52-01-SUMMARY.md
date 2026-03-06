---
phase: 52-board-zoom
plan: 01
subsystem: ui
tags: [love2d, camera, zoom]

provides:
  - Scroll wheel board zoom (0.5x to 3.0x)
  - Zoom-aware input transforms
affects: [53-viewport-clipping]

key-files:
  modified: [norrust_love/main.lua, norrust_love/draw.lua, norrust_core/src/combat.rs]

key-decisions:
  - "translate(origin) → scale(zoom) → translate(offset) for board-space transform"
  - "Divide effective viewport by zoom for pan range calculation"

duration: 10min
completed: 2026-03-05
---

# Phase 52 Plan 01: Board Zoom Summary

**Scroll wheel zoom (0.5x–3.0x) with zoom-aware click, pan, and camera lerp + combat preview ToD fix**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Scroll Wheel Zoom | Pass | wheelmoved scales camera_zoom by 0.1 per tick |
| AC-2: Zoom Limits | Pass | Clamped to 0.5x min, 3.0x max |
| AC-3: Click Accuracy at Zoom | Pass | All 3 click-to-hex sites use (x - origin) / zoom - offset |
| AC-4: Pan Composability | Pass | Drag delta divided by zoom; pan bounds use effective viewport |

## Accomplishments

- Scroll wheel zoom in/out on hex board (0.5x to 3.0x, step 0.1)
- All input transforms zoom-aware: click-to-hex, drag pan, arrow key pan, camera lerp
- Board-space draw transform: translate(origin) → scale(zoom) → translate(offset)
- Combat preview damage_per_hit now includes ToD modifier (pre-existing bug fix)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | camera_zoom state, ZOOM constants, love.wheelmoved, zoom-aware center_camera/click/drag/lerp |
| `norrust_love/draw.lua` | Modified | Board-space transform uses origin+scale+offset instead of single translate |
| `norrust_core/src/combat.rs` | Modified | damage_per_hit includes ToD modifier for consistent display |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| translate→scale→translate transform | Clean separation: origin centers board, zoom scales, offset pans in board-space | Matches inverse for input: (screen - origin) / zoom - offset |
| Effective viewport = vp / zoom for pan bounds | Zooming in means less board visible, so more pan range needed | Pan clamp adjusts automatically |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential bug fix — combat preview damage display |

**1. Combat preview damage_per_hit ToD mismatch**
- **Found during:** Human verification (user reported)
- **Issue:** `damage_per_hit` showed base+resistance only; min/mean/max included ToD modifier — numbers didn't add up (showed 11x2 max 26 instead of max 22)
- **Fix:** Apply ToD modifier to `attacker_damage_per_hit` and `defender_damage_per_hit` in CombatPreview construction
- **Files:** `norrust_core/src/combat.rs`
- **Verification:** 97 tests pass

## Next Phase Readiness

**Ready:**
- camera_zoom available via ctx for Phase 53 viewport clipping
- Board-space transform clean and composable

**Blockers:** None

---
*Phase: 52-board-zoom, Plan: 01*
*Completed: 2026-03-05*
