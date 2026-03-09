---
phase: 95-death-viewer
plan: 01
subsystem: presentation
tags: [love2d, animation, death, viewer]

requires:
  - phase: 94
    provides: sprite pipeline without death pose
provides:
  - derived death animation (tilt + fade from idle at render time)
  - viewer without death in pose list
affects: [96-batch-generation]

tech-stack:
  added: []
  patterns: [derived-animation-at-render-time]

key-files:
  created: []
  modified: [norrust_love/draw_board.lua, norrust_love/combat_mod.lua, norrust_love/viewer.lua]

key-decisions:
  - "Death derived from idle sprite with rotation + alpha fade, not a separate sprite"
  - "animation.lua still loads death.png if present (backward compat), just unused"

patterns-established:
  - "Derived animations: compute visual effects at render time from existing sprites"

duration: ~15min
completed: 2026-03-09
---

# Phase 95 Plan 01: Death Removal + Viewer Summary

**Death animation derived at render time — idle sprite tilts 0°→90° and fades 1.0→0.0 over 1s timer. Death removed from viewer and pipeline.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-09 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Derived Death Animation | Pass | Tilt + fade from idle in draw_board.lua |
| AC-2: Pipeline Death Removal | Pass | Already absent from v2 POSE_NAMES |
| AC-3: Viewer Death Removal | Pass | Death block removed from viewer select_asset |

## Accomplishments

- Dying units render with idle sprite + rotation (0°→90°) + fade (1.0→0.0)
- Faction underlay circle also fades with dying unit
- combat_mod.lua trigger_death_anim now sets idle instead of death
- Viewer no longer lists death in pose view

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/draw_board.lua` | Modified | Derived death: tilt + fade from idle sprite |
| `norrust_love/combat_mod.lua` | Modified | trigger_death_anim plays idle, not death |
| `norrust_love/viewer.lua` | Modified | Death removed from anim_names list |

## Decisions Made

None — followed plan as specified.

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- Phase 95 complete: death derived, viewer cleaned up
- Pipeline ready for batch generation (Phase 96)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 95-death-viewer, Plan: 01*
*Completed: 2026-03-09*
