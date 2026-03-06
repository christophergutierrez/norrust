---
phase: 60-campaign-save-load
plan: 01
subsystem: save-system
tags: [ffi, toml, campaign, save-load, trigger-zones, dialogue]

requires:
  - phase: 58-save-load-basics
    provides: save.lua TOML serializer/parser, F5/F9 handlers, basic save/load flow
provides:
  - Campaign save/load with full context restoration
  - Trigger zone and dialogue fired state preservation
  - Auto-save on end turn
  - 4 new FFI functions for state query/restore
affects: [61-uuid-roster]

tech-stack:
  added: []
  patterns: [campaign context passthrough, inline TOML arrays, state serialization via FFI]

key-files:
  created: []
  modified: [norrust_core/src/ffi.rs, norrust_core/src/dialogue.rs, norrust_love/norrust.lua, norrust_love/save.lua, norrust_love/main.lua]

key-decisions:
  - "dialogue.rs gets fired_ids() and mark_fired() methods for save/load"
  - "Trigger zone state serialized as TOML inline boolean array"
  - "Dialogue fired state serialized as TOML inline string array"
  - "Auto-save fires before AI turn (on 'e' key press)"

patterns-established:
  - "FFI state query returns JSON, restore takes individual calls or JSON"
  - "campaign_ctx parameter pattern for optional campaign context in save"

duration: ~45min
started: 2026-03-06
completed: 2026-03-06
---

# Phase 60 Plan 01: Campaign Save/Load Summary

**Extended save/load with campaign context, trigger zone/dialogue state preservation, and auto-save on end turn via 4 new FFI functions.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Started | 2026-03-06 |
| Completed | 2026-03-06 |
| Tasks | 4 completed |
| Files modified | 5 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Campaign save contains campaign context | Pass | [campaign] section with file, index, gold, faction IDs |
| AC-2: Campaign load restores campaign context | Pass | campaign_data reloaded, progression works after load |
| AC-3: Trigger zone state preserved | Pass | Boolean array in [state], restored via FFI |
| AC-4: Dialogue fired state preserved | Pass | String array in [state], restored via FFI |
| AC-5: Auto-save at turn start | Pass | Fires on 'e' key before AI turn |

## Accomplishments

- 4 new FFI functions: get/set trigger_zones_fired, get/set dialogue_fired
- save.lua extended with [campaign], [[veterans]], [state] sections and inline TOML array support
- Campaign context round-trip: save mid-campaign, load, win scenario, progress to next
- Auto-save on every end-turn with status flash message
- Fixed game_over flag leak (not reset on campaign complete / scenario end)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ffi.rs` | Modified | 4 new FFI functions for trigger/dialogue state |
| `norrust_core/src/dialogue.rs` | Modified | fired_ids() and mark_fired() methods |
| `norrust_love/norrust.lua` | Modified | FFI declarations + Lua wrappers for 4 new functions |
| `norrust_love/save.lua` | Modified | [campaign], [[veterans]], [state] sections; inline array support |
| `norrust_love/main.lua` | Modified | Campaign context in F5/F9, auto-save on 'e', game_over reset fix |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 4 separate FFI functions (not bulk state) | Matches existing FFI pattern, simpler | Consistent API |
| Inline TOML arrays for trigger/dialogue | Compact, readable in save files | Custom parser handles them |
| Auto-save before AI turn (not after) | Captures player's intent before AI moves | Player can undo AI by loading |
| game_over reset in both paths | Bug fix: flag leaked across sessions | Clean campaign restarts |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential bug fix |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** One essential bug fix, no scope creep.

### Auto-fixed Issues

**1. game_over flag leak across sessions**
- **Found during:** Task 4 (human verification)
- **Issue:** game_over and winner_faction not reset when campaign completed or scenario ended; starting new campaign immediately showed victory screen
- **Fix:** Added `game_over = false; winner_faction = -1` in both campaign-complete and scenario-end paths
- **Files:** norrust_love/main.lua
- **Verification:** User confirmed new campaigns start correctly

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Cached .so in Love2D memory | User quit and restarted Love2D to pick up new symbols |

## Next Phase Readiness

**Ready:**
- Full save/load pipeline complete (standalone + campaign)
- All state preserved: positions, combat, campaign context, triggers, dialogue
- Foundation for Phase 61 UUID + Roster

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 60-campaign-save-load, Plan: 01*
*Completed: 2026-03-06*
