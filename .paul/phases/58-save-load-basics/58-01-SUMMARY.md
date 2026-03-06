---
phase: 58-save-load-basics
plan: 01
subsystem: save-system
tags: [toml, ffi, save, load, love2d]

requires:
  - phase: 57
    provides: complete v2.0 game with FFI bridge
provides:
  - TOML save/load for scenarios with full combat state
  - F5/F9 quick save/load from any game mode
  - norrust_set_turn, norrust_set_active_faction, norrust_set_unit_combat_state FFI
affects: [60-campaign-save-load, 61-uuid-roster]

tech-stack:
  added: []
  patterns: [custom TOML serializer/parser in save.lua, status flash message overlay]

key-files:
  created: [norrust_love/save.lua]
  modified: [norrust_core/src/ffi.rs, norrust_love/norrust.lua, norrust_love/main.lua, norrust_love/conf.lua]

key-decisions:
  - "Custom parse_save_toml instead of extending toml_parser.lua — save format uses [[arrays-of-tables]] which toml_parser doesn't support"
  - "F9 works from any mode (including PICK_SCENARIO) so saves load after restart"
  - "Phase 59 combat state folded into this plan — minimal extra effort"

patterns-established:
  - "Save/load via save.lua module with serialize_toml/parse_save_toml"
  - "Status flash messages: status_message + status_timer in main.lua, rendered as overlay in love.draw"

duration: ~45min
completed: 2026-03-06
---

# Phase 58 Plan 01: Save/Load Basics + Combat State Summary

**TOML save/load system with F5/F9 hotkeys — saves unit positions, HP, XP, gold, turn, and active faction to ~/.local/share/love/norrust/saves/**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-06 |
| Tasks | 4 completed (+ Phase 59 scope) |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Save Writes TOML File | Pass | F5 writes to saves/ directory |
| AC-2: Load Restores Board State | Pass | F9 restores terrain, units, gold, turn, faction |
| AC-3: Save File Format | Pass | Human-readable TOML with [game] and [[units]] |
| AC-4: Round-Trip Integrity | Pass | User verified: units in correct positions after restart + F9 |
| (Phase 59) Combat state preserved | Pass | HP, XP, moved, attacked saved and restored |

## Accomplishments

- Created save.lua with TOML serializer, custom parser for [[arrays-of-tables]], save writer, and load function
- Added 3 Rust FFI functions: set_turn, set_active_faction, set_unit_combat_state
- Wired F5 (save in PLAYING mode) and F9 (load from any mode) with status flash overlay
- Save files include full combat state: hp, max_hp, xp, xp_needed, moved, attacked per unit

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| norrust_love/save.lua | Created | TOML serializer, save/load functions |
| norrust_core/src/ffi.rs | Modified | Added set_turn, set_active_faction, set_unit_combat_state |
| norrust_love/norrust.lua | Modified | FFI declarations + wrappers for 3 new functions |
| norrust_love/main.lua | Modified | require("save"), F5/F9 handlers, status flash message |
| norrust_love/conf.lua | Modified | Added t.identity = "norrust" for save directory |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Custom save TOML parser vs extending toml_parser.lua | toml_parser doesn't support [[arrays-of-tables]], simpler to keep separate | save.lua is self-contained |
| F9 from any mode, not just PLAYING | Must work after restart when in PICK_SCENARIO | Early return guard moved above mode checks |
| Update BOARD_COLS/ROWS on load | Renderer uses these locals, not engine state | Fixed black-half-screen bug on load |
| Phase 59 folded in | Minimal extra effort (1 FFI + field additions) | Phases 58+59 both done |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential fixes for load functionality |
| Scope additions | 1 | Phase 59 combat state included |

**Total impact:** Scope expansion was positive — combat state preservation required minimal extra work.

### Auto-fixed Issues

**1. F9 unreachable from PICK_SCENARIO mode**
- Found during: Task 4 (human verification)
- Issue: F9 handler was inside PLAYING mode block; after restart, game_mode=PICK_SCENARIO
- Fix: Moved F5/F9 handlers before mode-specific blocks
- Verification: User confirmed F9 works from scenario picker

**2. BOARD_COLS/BOARD_ROWS not updated on load**
- Found during: Task 4 (human verification)
- Issue: Load restored units but terrain only rendered for default 8x5 area
- Fix: Read state.cols/state.rows after load, call center_camera()
- Verification: User confirmed full board renders after load

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| .so not reloaded by running game | User quit and restarted Love2D — shared library loaded at startup |

## Next Phase Readiness

**Ready:**
- Save/load foundation complete with full combat state
- Phase 60 (Campaign Save/Load) can build on save.lua pattern
- Phase 61 (UUID + Roster) can extend save format

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 58-save-load-basics, Plan: 01*
*Completed: 2026-03-06*
