---
phase: 119-roster-uuid-tracking
plan: 01
subsystem: engine
tags: [roster, uuid, ffi, campaign]

requires:
  - phase: 118-campaign-orchestration
    provides: CampaignState with roster methods, campaign FFI functions
provides:
  - All roster operations routed through Rust engine FFI
  - Lua roster.lua no longer called from active gameplay paths
  - 7 new FFI wrappers in norrust.lua
affects: [120-game-over-campaign-logic, 121-veteran-deployment]

tech-stack:
  added: []
  patterns: [engine-owned roster via FFI, campaign_record_victory replaces multi-step sync]

key-files:
  modified: [norrust_love/norrust.lua, norrust_love/input_play.lua, norrust_love/input_setup.lua, norrust_love/main.lua, norrust_core/src/ffi.rs]

key-decisions:
  - "Added norrust_campaign_get_mapped_uuids_json FFI (small Rust addition needed for veteran filtering)"
  - "Save/load roster code in input.lua left untouched (save system boundary)"

patterns-established:
  - "campaign_record_victory as single-call game-over handler (replaces sync+get_living+carry_gold)"

duration: ~15min
completed: 2026-03-13
---

# Phase 119 Plan 01: Roster & UUID Tracking Summary

**Rust engine is now the sole roster owner — all unit identity tracking goes through FFI, roster.lua no longer called from active gameplay.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: FFI Wrappers Exist | Pass | 7 wrappers: start_campaign, campaign_add_unit, campaign_sync_roster, campaign_record_victory, campaign_get_living, campaign_map_id, campaign_get_mapped_uuids |
| AC-2: Roster Operations Use FFI | Pass | Game-over, recruit, veteran placement all use engine FFI |
| AC-3: roster.lua No Longer Required | Pass | No roster_mod calls in input_play, input_setup, main, campaign_client |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/norrust.lua` | Modified | 7 FFI C declarations + 7 Lua wrapper functions |
| `norrust_love/input_play.lua` | Modified | Game-over uses campaign_record_victory; recruit uses campaign_get_living + campaign_get_mapped_uuids |
| `norrust_love/input_setup.lua` | Modified | start_campaign replaces load_campaign; removed campaign.roster creation |
| `norrust_love/main.lua` | Modified | Removed roster_mod require and all references |
| `norrust_core/src/ffi.rs` | Modified | Added norrust_campaign_get_mapped_uuids_json (deviation) |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 1 | Small — added 1 FFI function to Rust |

**norrust_campaign_get_mapped_uuids_json:** Plan stated no Rust changes needed, but veteran recruit filtering required knowing which roster UUIDs are already mapped to engine IDs. Added a ~10-line FFI function returning the id_map values as JSON. Essential for correctness.

## Deferred Items

- `input.lua` save/load code still uses roster_mod (save system boundary, not this phase)
- `input_deploy.lua` passes roster_mod to campaign_client.commit_deployment (Phase 121 scope)
- `test_roster.lua` still references roster_mod (test file, harmless)

## Next Phase Readiness

**Ready:**
- Phase 120 (Game-Over Campaign Logic) can proceed — game-over flow already uses campaign_record_victory
- Phase 121 (Veteran Deployment) can build on the FFI wrappers added here

**Concerns:** None

**Blockers:** None

---
*Phase: 119-roster-uuid-tracking, Plan: 01*
*Completed: 2026-03-13*
