---
phase: 104-campaign-state-rust
plan: 01
subsystem: engine
tags: [campaign, roster, uuid, ffi, serde]

requires:
  - phase: none
    provides: n/a
provides:
  - CampaignState struct with full campaign progression ownership
  - RosterEntry with UUID-based unit identity tracking
  - 7 new FFI functions for campaign state management
  - Campaign lifecycle proven headlessly
affects: [105-json-save-format, 106-save-ux-cleanup]

tech-stack:
  added: []
  patterns: [campaign-state-ownership-in-rust, uuid-via-xorshift64, id-map-per-scenario]

key-files:
  created: []
  modified: [norrust_core/src/campaign.rs, norrust_core/src/ffi.rs]

key-decisions:
  - "UUID generation uses existing combat::Rng (xorshift64) instead of SmallRng — consistent with codebase"
  - "uuid_counter field uses serde(skip) — regenerated on load, not serialized"
  - "CampaignState lives on NorRustEngine (not GameState) since it persists across scenarios"

patterns-established:
  - "Campaign state owned by Rust, Lua queries via FFI — foundation for Phase 105/106"
  - "id_map (engine_id → uuid) cleared between scenarios, roster persists across"

duration: ~45min
started: 2026-03-10
completed: 2026-03-10
---

# Phase 104 Plan 01: Campaign State in Rust Summary

**CampaignState and RosterEntry structs in Rust with 7 FFI functions, owning all campaign progression previously scattered across Lua tables.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45 min |
| Started | 2026-03-10 |
| Completed | 2026-03-10 |
| Tasks | 3 completed |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: CampaignState holds all progression | Pass | All fields: scenario_index, carry_gold, veterans, roster, id_map |
| AC-2: Roster tracks unit identity across scenarios | Pass | UUID-based roster with id_map, dead tracking via sync_from_state |
| AC-3: Campaign lifecycle works headlessly | Pass | test_campaign_lifecycle proves start → play → victory → carry-over |

## Accomplishments

- CampaignState struct owns all campaign progression (scenario index, gold, veterans, roster)
- RosterEntry with UUID identity tracking and RosterStatus (Alive/Dead) enum
- 7 new FFI functions: start_campaign, add_unit, map_id, sync_roster, record_victory, get_campaign_state_json, get_living_json
- 5 new unit tests + 1 integration test (test_campaign_lifecycle), 113 total passing
- Existing FFI functions preserved for backward compatibility

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/campaign.rs` | Modified (+375 lines) | CampaignState, RosterEntry, RosterStatus types + methods + tests |
| `norrust_core/src/ffi.rs` | Modified (+179 lines) | campaign field on NorRustEngine + 7 new FFI functions |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Use combat::Rng for UUID | Project already uses xorshift64 RNG — no new dependencies | Consistent pattern across codebase |
| serde(skip) on uuid_counter | Counter is transient state, not meaningful to persist | Phase 105 serialization simpler |
| CampaignState on NorRustEngine | GameState resets per scenario; campaign persists | Clean ownership boundary |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minimal — different RNG source |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Trivial deviation, no scope change.

### Auto-fixed Issues

**1. RNG source: SmallRng → combat::Rng**
- **Found during:** Task 1 (CampaignState types)
- **Issue:** Plan specified SmallRng but project uses custom xorshift64 combat::Rng
- **Fix:** Used combat::Rng::new(seed) for UUID generation instead
- **Verification:** test_generate_uuid confirms 8-char hex format

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Borrow checker in test_campaign_lifecycle | Collected UUIDs into Vec<String> before mutable map_id calls |
| Clippy: add_unit too many args (9/7) | Pre-existing pattern (simulate_combat has same warning) — not addressed |

## Next Phase Readiness

**Ready:**
- CampaignState fully serializable via serde (Serialize + Deserialize on all types)
- `norrust_get_campaign_state_json` FFI already returns full state as JSON
- Foundation for Phase 105 (JSON Save Format) is complete

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 104-campaign-state-rust, Plan: 01*
*Completed: 2026-03-10*
