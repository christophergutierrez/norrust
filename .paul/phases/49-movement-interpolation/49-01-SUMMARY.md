---
phase: 49-movement-interpolation
plan: 01
subsystem: ui
tags: [love2d, animation, movement, interpolation]

requires:
  - phase: 48-ghost-path-visualization
    provides: Ghost path waypoints via find_path FFI
provides:
  - Smooth sliding movement animation along A* path
  - Input blocking during movement
  - Callback-based follow-up actions (move+attack)
affects: [50-combat-movement]

tech-stack:
  added: []
  patterns: [pending_anims.move for movement animation state]

key-files:
  modified:
    - norrust_love/main.lua
    - norrust_love/draw.lua

key-decisions:
  - "Store move_anim as pending_anims.move to avoid LuaJIT 60-upvalue limit"
  - "Split love.draw ctx building into build_draw_ctx_state() + love.draw() for same reason"
  - "Apply engine move immediately, animate rendering only — keeps engine in sync"
  - "Speed 10 segments/sec (~0.1s per hex) for responsive feel"
  - "Callback-based on_complete for move+attack sequencing"

patterns-established:
  - "pending_anims.move = {uid, path, seg, t, speed, on_complete} for movement animation"
  - "build_draw_ctx_state() splits upvalue budget across two functions"

duration: ~30min
completed: 2026-03-05T23:30:00Z
---

# Phase 49 Plan 01: Movement Interpolation Summary

**Added smooth sliding animation when moves are committed, replacing instant teleport with visible hex-by-hex traversal. Also fixed pre-existing bug where combat animations never played due to sprite key mismatch.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-05 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Smooth Movement Animation | Pass | Units slide along A* path at 10 segs/sec |
| AC-2: Input Blocked During Movement | Pass | keypressed and mousepressed return early during animation |
| AC-3: Follow-up Actions After Animation | Pass | Move+attack callbacks fire after slide completes, combat anims play |

## Accomplishments

- Added `pending_anims.move` movement animation state with segment-based linear interpolation
- Created `start_move_anim()` and modified `commit_ghost_move()` to accept `on_complete` callback
- Updated all 4 commit sites: 2 move+attack (pass attack as callback), 2 move-only (no callback)
- Added movement tick in `love.update(dt)` advancing segments and firing completion callback
- Added position override in `draw.lua` — interpolates between path waypoints during animation
- Blocked input during movement in both `love.keypressed` and `love.mousepressed`
- Split `love.draw` into `build_draw_ctx_state()` + `love.draw()` to stay under LuaJIT 60-upvalue limit
- **Bugfix:** Fixed `play_combat_anim` sprite lookup — was using raw `def_id` instead of normalized key, causing all combat animations to silently fail since Phase 47

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Movement animation state, commit callbacks, input blocking, upvalue split, combat anim bugfix |
| `norrust_love/draw.lua` | Modified | Interpolated position override during movement animation |

## Deviations from Plan

- **LuaJIT 60-upvalue limit:** Adding `move_anim` as a new local exceeded the limit in `love.draw`. Resolved by storing as `pending_anims.move` field and splitting ctx building into a separate function.
- **Combat animation bugfix (unplanned):** Discovered `play_combat_anim` was looking up `unit_sprites[anim_state.def_id]` with raw def_id (e.g. "Spearman") but sprites are keyed by normalized name ("spearman"). This pre-existing Phase 47 bug meant combat animations never actually played. Fixed by normalizing the key.

## Next Phase Readiness

**Ready:**
- Movement interpolation system available for Phase 50 combat movement
- `start_move_anim` pattern reusable for combat approach animations
- Callback-based sequencing proven for chaining animations

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 49-movement-interpolation, Plan: 01*
*Completed: 2026-03-05*
