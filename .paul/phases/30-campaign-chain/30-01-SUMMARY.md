---
phase: 30-campaign-chain
plan: 01
subsystem: campaign
tags: [toml, serde, ffi, love2d, carry-over, veteran-units]

requires:
  - phase: 28-map-crossing
    provides: LoadedBoard, objective hex + turn limit win conditions, crossing scenario
  - phase: 29-second-scenario
    provides: Ambush scenario, TriggerZone, get_next_unit_id, scenario validation

provides:
  - Campaign TOML schema + loader (CampaignDef, CampaignScenarioDef)
  - VeteranUnit carry-over serialization (hp, xp, xp_needed, advancement_pending, abilities)
  - Gold carry-over calculation (percentage penalty + early finish bonus)
  - FFI functions for campaign management (load, survivors, carry gold, veteran placement, set gold)
  - Love2D campaign flow (selection, progression, victory/defeat overlays)

affects: []

tech-stack:
  added: []
  patterns: [client-side campaign progression, engine reuse across scenarios]

key-files:
  created:
    - campaigns/tutorial.toml
    - norrust_core/src/campaign.rs
    - norrust_core/tests/campaign.rs
  modified:
    - norrust_core/src/lib.rs
    - norrust_core/src/ffi.rs
    - norrust_love/norrust.lua
    - norrust_love/main.lua

key-decisions:
  - "Campaign progression is client-side (Love2D), not engine-side"
  - "Engine reuse: load_board() replaces GameState but keeps registries"
  - "norrust_set_faction_gold FFI added for carry-over gold injection"
  - "Veterans placed on leftmost keep + adjacent castles, skipping occupied hexes"

patterns-established:
  - "Client-side progression: engine provides data extraction (survivors, gold), client manages flow"
  - "unit_from_registry() + field override pattern for veteran placement"

duration: ~45min
completed: 2026-03-03
---

# Phase 30 Plan 01: Campaign Chain Summary

**Campaign system linking crossing + ambush scenarios with unit carry-over (hp/xp/advancement) and gold carry-over (80% penalty + early finish bonus) via client-side Love2D progression.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-03 |
| Tasks | 4 completed |
| Files created | 3 |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Campaign TOML loads and parses | Pass | tutorial.toml with 2 scenarios, gold_carry_percent=80, early_finish_bonus=5 |
| AC-2: Surviving units serialize for carry-over | Pass | get_survivors() returns VeteranUnit with all fields preserved |
| AC-3: Veteran units place with preserved stats | Pass | place_veteran_unit FFI overrides hp/xp/xp_needed/advancement_pending on registry unit |
| AC-4: Gold carries with percentage penalty | Pass | 150 * 80% = 120 verified in test |
| AC-5: Early finish bonus awards extra gold | Pass | 150 * 80% + 10 * 5 = 170 verified in test |
| AC-6: Love2D campaign progresses through scenarios | Pass | C key selects campaign, Enter on victory loads next scenario with veterans + gold |
| AC-7: Individual scenario mode still works | Pass | Number keys still select individual scenarios with campaign_active=false |

## Accomplishments

- Campaign TOML schema and Rust campaign module with load/survivors/gold carry-over logic
- 5 new FFI functions (load_campaign, get_survivors_json, get_carry_gold, place_veteran_unit, set_faction_gold) with Lua wrappers
- Full Love2D campaign flow: selection screen, auto-progression on victory, campaign-specific overlays, defeat handling
- 8 integration tests covering all carry-over scenarios including FFI round-trips

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `campaigns/tutorial.toml` | Created | Campaign definition: 2 scenarios, 80% gold carry, 5 bonus/turn |
| `norrust_core/src/campaign.rs` | Created | CampaignDef, VeteranUnit, load_campaign(), get_survivors(), calculate_carry_gold() |
| `norrust_core/tests/campaign.rs` | Created | 8 integration tests (3 pure Rust + 5 FFI) |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod campaign;` |
| `norrust_core/src/ffi.rs` | Modified | 5 new extern "C" functions for campaign management |
| `norrust_love/norrust.lua` | Modified | 5 cdef declarations + 6 Lua wrappers (load_campaign, get_survivors, get_carry_gold, place_veteran_unit, set_faction_gold, free) |
| `norrust_love/main.lua` | Modified | CAMPAIGNS table, campaign state vars, helper functions (find_keep_and_castles, place_veterans, load_campaign_scenario), C key handler, victory/defeat campaign flow, campaign-aware overlays |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Campaign progression is client-side | Engine is per-scenario; load_board() replaces GameState. Client manages campaign_index, veterans, gold | Clean separation; no campaign state on GameState |
| Added norrust_set_faction_gold FFI | No existing way to set faction gold directly; needed for carry-over gold injection into next scenario | Minimal addition (3 lines); enables gold carry-over |
| Veterans placed on leftmost keep + castles | Player's keep is leftmost; placement skips occupied hexes from preset units | Works with both crossing and ambush board layouts |
| Engine reuse (not recreate) for scenario transitions | load_board() creates fresh GameState while keeping registries; avoids re-loading data/factions | Faster transitions; simpler code |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Scope additions | 1 | Essential for gold carry-over |
| Auto-fixed | 0 | — |
| Deferred | 0 | — |

**Total impact:** One essential addition (norrust_set_faction_gold), no scope creep.

### Scope Addition

**1. norrust_set_faction_gold FFI function**
- **Found during:** Task 2 (FFI functions)
- **Issue:** No existing FFI function to set faction gold; carry-over gold needs to override starting gold in next scenario
- **Fix:** Added minimal norrust_set_faction_gold(engine, faction, gold) setter + Lua wrapper
- **Files:** ffi.rs, norrust.lua
- **Verification:** Used successfully in load_campaign_scenario() in main.lua

## Issues Encountered

None — all tasks completed without errors. All 94 tests pass (59 unit + 8 campaign + 3 scenario_validation + 23 simulation + 1 FFI).

## Verification Results

```
cargo test — 94 tests pass
cargo test --test campaign — 8/8 pass
cargo test --test scenario_validation — 3/3 pass (existing validation unchanged)
```

## Next Phase Readiness

**Ready:**
- Phase 30 is the final phase of v1.3 Campaign Mode
- All 3 phases (28, 29, 30) complete — milestone ready to close

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 30-campaign-chain, Plan: 01*
*Completed: 2026-03-03*
