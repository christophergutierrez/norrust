---
phase: 118-campaign-orchestration
plan: 01
subsystem: engine
tags: [campaign, ffi, orchestration, rust]

requires:
  - phase: 117-integration-validation
    provides: complete unit tree with verified stats
provides:
  - Rust-side campaign scenario loading (find_keep_and_castles, place_veterans, roster init)
  - Single FFI call for campaign scenario transitions
  - Thin Lua wrapper replacing 120+ lines of orchestration logic
affects: [119-roster-uuid-tracking, 120-game-over-campaign-logic, 121-veteran-deployment]

tech-stack:
  added: []
  patterns: [engine-owned orchestration via single FFI call returning JSON status]

key-files:
  modified: [norrust_core/src/campaign.rs, norrust_core/src/ffi.rs, norrust_love/campaign_client.lua, norrust_love/norrust.lua]

key-decisions:
  - "Keep find_keep_and_castles as local in Lua for commit_deployment (Phase 121 will remove)"
  - "Orchestration logic stays in ffi.rs (not campaign.rs) since it needs NorRustEngine access"

patterns-established:
  - "Single FFI call pattern: complex multi-step operations return JSON status enum"

duration: ~20min
completed: 2026-03-12
---

# Phase 118 Plan 01: Campaign Orchestration Summary

**Rust engine now owns campaign scenario loading — board, units, veterans, gold carried over in a single FFI call.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Keep and Castle Discovery in Rust | Pass | `find_keep_and_castles()` tested for faction 0 (leftmost) and faction 1 (rightmost) |
| AC-2: Veteran Placement in Rust | Pass | Veterans placed on keep+castles, healed to max HP, roster id_map updated |
| AC-3: Single FFI Call Loads Next Scenario | Pass | `norrust_campaign_load_next_scenario` returns JSON status |
| AC-4: Lua Becomes Thin Wrapper | Pass | `load_campaign_scenario` delegates to FFI, only reads back UI state |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/campaign.rs` | Modified | Added `find_keep_and_castles`, `count_available_slots`, `build_veteran_info`, `populate_initial_roster` + 4 new tests |
| `norrust_core/src/ffi.rs` | Modified | Added `norrust_campaign_load_next_scenario` FFI function (~150 lines) |
| `norrust_love/campaign_client.lua` | Modified | Replaced orchestration with thin FFI wrapper (246→120 lines) |
| `norrust_love/norrust.lua` | Modified | Added FFI declaration + Lua wrapper for new function |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minimal — missing `use crate::hex::Hex` import |
| Scope additions | 1 | Kept `find_keep_and_castles` as local in Lua for `commit_deployment` |

**`commit_deployment` deviation:** The plan said to keep `commit_deployment` unchanged, but removing the module-level `find_keep_and_castles` and `place_veterans` broke it. Solution: kept a local `find_keep_and_castles` function inside campaign_client.lua specifically for `commit_deployment`. Phase 121 will remove this when deployment moves to Rust.

## Next Phase Readiness

**Ready:**
- Campaign orchestration is engine-owned — Phase 119 (Roster/UUID tracking) can build on this
- `CampaignState` already has roster methods that Phase 119 will expose more fully

**Concerns:**
- `commit_deployment` still uses old FFI path with Lua-side hex finding (Phase 121)
- Pre-existing `test_unit_registry_loads` test failure (unrelated, expects old "archer" unit name)

**Blockers:** None

---
*Phase: 118-campaign-orchestration, Plan: 01*
*Completed: 2026-03-12*
