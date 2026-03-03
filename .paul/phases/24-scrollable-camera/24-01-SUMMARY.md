---
phase: 24-scrollable-camera
plan: 01
subsystem: ui
tags: [gdscript, camera, viewport, hex-rendering]

requires:
  - phase: 23-in-hex-readability
    provides: unit labels in hex circles, stable _draw_units() rendering
provides:
  - Scrollable camera with drag-to-pan and arrow key panning
  - Larger hexes (96px radius) with proportionally scaled labels
  - Camera-follow on unit selection with smooth lerp
  - Board-edge clamping
affects: [campaign-scenario, larger-boards]

tech-stack:
  added: []
  patterns: [manual tilemap position offset for camera, _select_unit() helper with camera-follow]

key-files:
  modified: [norrust_client/scripts/game.gd]

key-decisions:
  - "Arrow keys only for pan — WASD conflicts with A (advance) and R (recruit)"
  - "Manual _tile_map.position offset instead of Camera2D node — no node hierarchy changes"
  - "_select_unit() helper centralizes selection + camera-follow logic"

patterns-established:
  - "_apply_camera_offset() as single point for clamp + position update"
  - "Drag state (_drag_active, _drag_start, _drag_camera_start) pattern for click-drag interactions"

duration: ~15min
completed: 2026-03-03
---

# Phase 24 Plan 01: Scrollable Camera Summary

**Larger hexes (96px) with scrollable camera — drag-to-pan, arrow key panning, board clamping, and smooth camera-follow on unit selection.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-03 |
| Tasks | 4 completed (3 auto + 1 checkpoint) |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Larger Hex Size | Pass | HEX_RADIUS=96, HEX_CELL_W=166, HEX_CELL_H=192; labels scaled 1.5× |
| AC-2: Camera Drag-to-Pan | Pass | Drag on empty board space or off-board area pans; HUD/sidebar fixed |
| AC-3: Arrow Key Camera Panning | Pass | Arrow keys pan at 500px/sec; WASD dropped due to key conflicts |
| AC-4: Camera Clamped to Board Bounds | Pass | Pan range computed from board extent; half-viewport + HEX_RADIUS margin |
| AC-5: Camera Follows Selection | Pass | Smooth lerp (factor 8.0) to center selected unit; keyboard pan cancels lerp |

## Accomplishments

- HEX_RADIUS increased 64→96px with proportional scaling: name label 9→14pt, HP 13→18pt, XP 10→14pt, advancement arc 2.5→3.5px
- Camera panning via drag-to-pan (empty hexes + off-board clicks) and arrow keys with board-edge clamping
- `_select_unit()` helper extracted from inline selection code — centralizes reachable hex lookup + camera-follow lerp
- `_center_camera()` now computes `_board_origin` and `_camera_min`/`_camera_max` clamp bounds
- `_process(delta)` added for continuous keyboard pan and smooth camera lerp

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_client/scripts/game.gd` | Modified | Hex size increase, camera panning system, selection-follow |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Arrow keys only (no WASD) | KEY_A = advance, KEY_R = recruit — WASD would fire both pan and game actions | Future: could add WASD in non-PLAYING modes if needed |
| Manual _tile_map.position offset (no Camera2D) | Existing draw code already uses _tile_map.position; no Node hierarchy changes | Simpler; Camera2D can be added later if zoom needed |
| _select_unit() helper | Selection logic was duplicated; camera-follow needs unit position lookup | Cleaner code; single place to modify selection behavior |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope reduction | 1 | WASD dropped — arrow keys sufficient |

**Total impact:** Minor — WASD was a nice-to-have; arrow keys cover the need.

### Deferred Items

None.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Camera system supports any board size — unlocks v1.2 campaign scenario (16×6 board)
- 72 tests passing (56 lib + 16 integration) — zero Rust changes

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 24-scrollable-camera, Plan: 01*
*Completed: 2026-03-03*
