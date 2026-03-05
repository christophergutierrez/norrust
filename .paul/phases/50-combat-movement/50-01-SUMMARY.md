---
phase: 50-combat-movement
plan: 01
subsystem: ui
tags: [love2d, animation, combat, melee]

requires:
  - phase: 49-movement-interpolation
    provides: Movement interpolation system (pending_anims.move)
provides:
  - Melee combat lunge animation (approach + attack + return)
  - Ranged attacks stay in place
  - Distance-based ranged detection replacing broken name-based check
affects: []

tech-stack:
  added: []
  patterns: [pending_anims.combat_slide for combat approach animation]

key-files:
  modified:
    - norrust_love/main.lua
    - norrust_love/draw.lua

key-decisions:
  - "pending_anims.combat_slide with pixel coordinates (not hex path) for fractional positioning"
  - "40% approach distance — close enough to feel like contact without overlapping defender"
  - "3-phase slide: approach → pause (0.3s for attack anims) → return"
  - "Distance-based is_ranged_attack() using hex.distance instead of attack name matching"

patterns-established:
  - "pending_anims.combat_slide = {uid, start_x/y, target_x/y, t, speed, phase, ...} for combat movement"
  - "execute_attack takes on_done callback for async melee completion"

duration: ~20min
completed: 2026-03-05T23:50:00Z
---

# Phase 50 Plan 01: Combat Movement Summary

**Added melee lunge animation — attackers slide toward defenders before combat, then return. Fixed pre-existing ranged detection bug (attack name vs hex distance).**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Completed | 2026-03-05 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Melee Approach Animation | Pass | Attacker slides 40% toward defender, attacks, slides back |
| AC-2: Ranged Stays In Place | Pass | Fixed is_ranged_attack() to use hex distance instead of name matching |
| AC-3: All Attack Paths Work | Pass | All 4 call sites (Enter ghost+attack, Enter direct, mouse ghost+attack, mouse direct) tested |

## Accomplishments

- Added `pending_anims.combat_slide` state for melee approach/return animation
- 3-phase combat slide: approach (speed 6) → pause 0.3s → return (speed 6)
- Added `apply_attack_with_anims()` extracted from `execute_attack()` for reuse in slide callback
- `execute_attack()` now takes `on_done` callback — all 4 call sites updated
- Added combat_slide interpolation in draw.lua (same pattern as move_anim)
- Input blocked during combat slide (keypressed + mousepressed guards)
- **Bugfix:** `is_ranged_attack()` now uses `hex.distance()` instead of checking if attack name contains "ranged" — attack names are weapon names like "bow", not range descriptors

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Combat slide state, execute_attack callback, is_ranged_attack fix, input blocking |
| `norrust_love/draw.lua` | Modified | Combat slide position interpolation in draw_units |

## Deviations from Plan

- **Ranged detection fix (unplanned):** `is_ranged_attack()` checked `combat_preview.attacker_attack_name` for the string "ranged", but attack names are weapon names (e.g. "bow", "sword"). Replaced with `hex.distance()` check — distance > 1 means ranged. This was a pre-existing Phase 47 bug.

## Next Phase Readiness

**v1.8 milestone complete!**
- All 3 phases (48-50) delivered
- Ghost path visualization, movement interpolation, combat movement all working

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 50-combat-movement, Plan: 01*
*Completed: 2026-03-05*
