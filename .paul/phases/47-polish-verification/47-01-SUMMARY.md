---
phase: 47-polish-verification
plan: 01
subsystem: ui
tags: [love2d, sprites, animation, combat]

requires:
  - phase: 46-full-unit-generation
    provides: 92 AI-generated sprite PNGs for all 16 units
provides:
  - Obsolete generate_sprites.lua removed
  - Combat animation system (attack-melee, attack-ranged, defend, death)
  - Faction-based unit facing
  - Ranged attack support in ghost movement
affects: [v1.8 combat polish]

tech-stack:
  added: []
  patterns: [pending_anims timer-based animation return, hex.distance for range queries]

key-files:
  modified:
    - norrust_love/main.lua
    - norrust_love/draw.lua
    - norrust_love/hex.lua
  deleted:
    - norrust_love/generate_sprites.lua

key-decisions:
  - "Faction-based facing (faction 0→right, faction 1→left) replacing position-based flip"
  - "Combat animations via pending_anims timer table with auto-return to idle"
  - "hex.distance() for ranged attack range checks (odd-r → cube conversion)"

patterns-established:
  - "execute_attack() wrapper: animate → apply → check death"
  - "is_ranged_attack() queries combat_preview before cancel"
  - "get_attackable_enemies() with max_range parameter for melee+ranged"

duration: ~30min
completed: 2026-03-05T22:00:00Z
---

# Phase 47 Plan 01: Polish & Verification Summary

**Removed obsolete Lua sprite generator, added combat animations and faction-based facing, fixed ranged ghost attacks.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-05 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 3 (+1 deleted) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Obsolete Generator Removed | Pass | generate_sprites.lua deleted, --generate-sprites flag removed, no stale refs |
| AC-2: All Units Render In-Game | Pass | Human verified — all units display correctly with combat animations |
| AC-3: Viewer Shows All Units Correctly | Pass | Human verified — 16 units, no duplicates |

## Accomplishments

- Deleted 862-line obsolete `generate_sprites.lua` and `--generate-sprites` CLI flag
- Added combat animation system: attack-melee, attack-ranged, defend, death triggered during gameplay
- Fixed unit facing to be faction-based (chess-style) instead of position-based
- Added ranged attack support in ghost movement via `hex.distance()` and `get_attackable_enemies()`
- Fixed pre-existing bug: `call_call_load_campaign_scenario` double-prefix typo

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/generate_sprites.lua` | Deleted | 862-line obsolete Lua sprite generator removed |
| `norrust_love/main.lua` | Modified | Removed CLI flag, added combat animations, ranged ghost attacks |
| `norrust_love/draw.lua` | Modified | Faction-based facing for units and ghosts |
| `norrust_love/hex.lua` | Modified | Added hex.distance() for range calculations |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Faction-based facing (not position-based) | Chess-style: your units always face opponent | Consistent visual direction |
| pending_anims timer table for animation return | Simple, non-blocking; auto-returns to idle | No coroutines needed |
| is_ranged_attack() called before cancel_combat_preview() | Preview data needed for ranged detection | All 4 call sites use same pattern |
| hex.distance() via cube conversion | Standard hex math; needed for range > 1 | Enables future range mechanics |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Pre-existing bug fix |
| Scope additions | 3 | User-requested features during verify |
| Deferred | 1 | Spearman sprite art |

**Total impact:** Essential polish — user requested combat animations and facing fix during human verify checkpoint.

### Auto-fixed Issues

**1. Function naming bug**
- **Found during:** Task 1 (generator removal)
- **Issue:** `call_call_load_campaign_scenario` had double `call_` prefix — game crashed on start
- **Fix:** Renamed to `call_load_campaign_scenario`
- **Files:** norrust_love/main.lua
- **Verification:** Game launches correctly

### Scope Additions (User-Requested)

**1. Faction-based unit facing** — draw.lua lines 43, 587
**2. Combat animation system** — main.lua: play_combat_anim, trigger_attack_anims, trigger_death_anim, execute_attack, pending_anims cleanup
**3. Ranged ghost attack support** — hex.lua: hex.distance(); main.lua: get_attackable_enemies(), unit_max_range()

### Deferred Items

- Spearman sprite faces backward (art issue, not code — needs sprite regeneration)

## Next Phase Readiness

**Ready:**
- v1.7 Enhanced Unit Sprites milestone complete
- All 16 units with AI sprites, combat animations, and correct facing
- 97 tests passing

**Concerns:**
- Spearman sprite art faces wrong direction (cosmetic only)

**Blockers:**
- None

---
*Phase: 47-polish-verification, Plan: 01*
*Completed: 2026-03-05*
