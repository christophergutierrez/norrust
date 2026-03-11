---
phase: 105-json-save-format
plan: 01
subsystem: engine
tags: [save, load, json, serde, ffi]

requires:
  - phase: 104-campaign-state-rust
    provides: CampaignState with Serialize/Deserialize
provides:
  - SaveState struct for full engine state serialization
  - norrust_save_json() FFI for single-call save
  - norrust_load_json() FFI for single-call restore
affects: [106-save-ux-cleanup]

tech-stack:
  added: []
  patterns: [save-state-dto, registry-based-unit-restore, board-path-reload]

key-files:
  created: [norrust_core/src/save.rs]
  modified: [norrust_core/src/ffi.rs, norrust_core/src/lib.rs, norrust_core/src/combat.rs, norrust_core/src/campaign.rs]

key-decisions:
  - "SaveState is the serialization DTO — GameState/Unit stay non-serializable"
  - "Units restored via registry lookup (compact saves, forward-compatible)"
  - "Board terrain reloaded from board.toml path, not stored in save"
  - "Engine tracks board_path/dialogue_path/display_name for save context"

patterns-established:
  - "Save boundary: SaveState captures runtime state, registry provides static data on restore"
  - "Engine metadata fields (board_path, dialogue_path, display_name) set during load, read during save"

duration: ~30min
started: 2026-03-10
completed: 2026-03-10
---

# Phase 105 Plan 01: JSON Save Format Summary

**SaveState/SaveUnit structs with norrust_save_json() and norrust_load_json() FFI enabling single-call JSON save/restore of full engine state.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Started | 2026-03-10 |
| Completed | 2026-03-10 |
| Tasks | 3 completed |
| Files modified | 5 (1 created, 4 modified) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: SaveState captures all restorable engine state | Pass | Units, gold, turn, triggers, villages, dialogue, campaign, RNG |
| AC-2: JSON round-trip preserves game state | Pass | test_save_state_serde_round_trip + test_save_load_round_trip |
| AC-3: norrust_load_json restores full engine state | Pass | FFI function rebuilds board, units, metadata, dialogue, campaign |
| AC-4: Existing FFI functions unaffected | Pass | All 118 unit tests pass, no signature changes |

## Accomplishments

- SaveState struct captures all engine state in a single serializable DTO
- norrust_save_json() / norrust_load_json() replace ~14 separate FFI calls with 1 each
- Engine tracks board_path, dialogue_path, display_name metadata for save context
- Rng::state() accessor added for RNG state serialization
- PartialEq added to campaign types for test assertions

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/save.rs` | Created (~300 lines) | SaveState, SaveUnit structs + build() + 5 tests |
| `norrust_core/src/ffi.rs` | Modified (+130 lines) | 3 metadata fields + norrust_set_display_name/save_json/load_json |
| `norrust_core/src/lib.rs` | Modified (+1 line) | pub mod save |
| `norrust_core/src/combat.rs` | Modified (+4 lines) | Rng::state() accessor |
| `norrust_core/src/campaign.rs` | Modified (5 derives) | Added PartialEq to campaign types |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| SaveState as DTO, not Serialize on GameState | GameState has HashMap<Hex,_> keys + RNG — not cleanly serializable | Clean separation; internal types stay simple |
| Registry-based unit restore | Saves only runtime state; attacks/defense from registry | Compact saves, forward-compatible with stat changes |
| Board reload from path | Terrain + trigger zone geometry from TOML file | No terrain duplication in save file |
| Engine metadata fields | board_path/dialogue_path/display_name tracked on NorRustEngine | Save can access paths without Lua passing them again |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minimal — PartialEq on campaign types |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Trivial addition, no scope change.

### Auto-fixed Issues

**1. PartialEq needed on campaign types**
- **Found during:** Task 1 (SaveState types)
- **Issue:** SaveState derives PartialEq but contains Option<CampaignState> which lacked PartialEq
- **Fix:** Added PartialEq to CampaignScenarioDef, CampaignDef, VeteranUnit, RosterEntry, CampaignState
- **Verification:** All tests pass

## Issues Encountered

None

## Next Phase Readiness

**Ready:**
- norrust_save_json() returns complete JSON that Lua can write to disk
- norrust_load_json() restores full state from that JSON
- Phase 106 only needs to wire these two FFI calls into Lua save.lua

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 105-json-save-format, Plan: 01*
*Completed: 2026-03-10*
