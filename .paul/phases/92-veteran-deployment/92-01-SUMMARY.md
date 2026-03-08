---
phase: 92-veteran-deployment
plan: 01
subsystem: ui
tags: [lua, love2d, campaign, veterans, ffi]

requires:
  - phase: 91-save-naming
    provides: save system foundation
provides:
  - Veteran deploy/bench selection screen for campaign overflow
  - Castle hex validation for veteran placement (FFI)
  - Campaign faction assignment from TOML config
  - Veteran HP healing on carry-over
affects: []

tech-stack:
  added: []
  patterns:
    - DEPLOY_VETERANS game mode with toggle selection UI
    - FFI castle validation matching apply_recruit rules

key-files:
  created: []
  modified:
    - norrust_love/state.lua
    - norrust_love/main.lua
    - norrust_love/campaign_client.lua
    - norrust_love/draw.lua
    - norrust_love/input.lua
    - norrust_core/src/ffi.rs
    - norrust_core/src/campaign.rs
    - campaigns/tutorial.toml
    - norrust_core/tests/campaign.rs

key-decisions:
  - "Deploy screen uses same list UI pattern as LOAD_SAVE screen"
  - "Veterans fully healed (hp = max_hp) on scenario carry-over"
  - "Campaign factions specified via faction_0/faction_1 in TOML"

patterns-established:
  - "Game mode screens: DEPLOY_VETERANS = 6, follows LOAD_SAVE pattern"

duration: ~2 sessions
completed: 2026-03-08
---

# Phase 92 Plan 01: Veteran Deployment Summary

**Deploy/bench selection screen for campaign veteran overflow, plus castle placement validation and campaign bug fixes.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~2 sessions |
| Completed | 2026-03-08 |
| Tasks | 2 auto + 1 checkpoint completed |
| Files modified | 9 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Auto-skip when veterans fit | Pass | Veterans auto-placed, no deploy screen shown |
| AC-2: Deploy screen on overflow | Pass | Screen appears with veteran list, [+]/[-] status, slot counter |
| AC-3: Toggle deploy/bench | Pass | Space/number keys toggle, slot limit enforced |
| AC-4: Confirm and start | Pass | Enter deploys selected, Escape deploys all |

## Accomplishments

- Deploy/bench selection screen (DEPLOY_VETERANS mode) with toggle UI when veterans exceed keep+castle slots
- Castle hex validation added to `norrust_place_veteran_unit` FFI — veterans restricted to castle hexes adjacent to leader's keep (matching `apply_recruit` rules)
- Campaign faction assignment from TOML (`faction_0`/`faction_1` fields) instead of alphabetical auto-pick
- Veterans healed to full HP on scenario carry-over (XP preserved)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/state.lua` | Modified | Added `campaign.deploy` table (active, veterans, slots, selected) |
| `norrust_love/main.lua` | Modified | Added DEPLOY_VETERANS = 6 mode, draw ctx wiring |
| `norrust_love/campaign_client.lua` | Modified | Slot counting, deploy screen trigger, commit_deployment() |
| `norrust_love/draw.lua` | Modified | Deploy screen rendering (veteran list, toggle status, controls) |
| `norrust_love/input.lua` | Modified | Deploy screen input (toggle, confirm, escape), veteran error codes |
| `norrust_core/src/ffi.rs` | Modified | Castle/keep validation in place_veteran_unit, campaign faction fields |
| `norrust_core/src/campaign.rs` | Modified | faction_0/faction_1 fields in CampaignDef |
| `campaigns/tutorial.toml` | Modified | Added faction_0 = "loyalists", faction_1 = "orcs" |
| `norrust_core/tests/campaign.rs` | Modified | Updated veteran placement test for castle validation |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essential bug fixes discovered during testing |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Essential fixes, no scope creep

### Auto-fixed Issues

**1. Campaign faction assignment**
- **Found during:** User testing
- **Issue:** Factions assigned alphabetically (Elves, Loyalists) instead of campaign-specified
- **Fix:** Added faction_0/faction_1 to CampaignDef, FFI JSON, and tutorial.toml
- **Files:** campaign.rs, ffi.rs, tutorial.toml, input.lua

**2. Veteran HP carry-over**
- **Found during:** User testing
- **Issue:** Veterans carried wounded HP into next scenario
- **Fix:** Set hp = max_hp on carry-over (heal between scenarios)
- **Files:** input.lua (victory handler)

**3. Veteran castle placement validation**
- **Found during:** User testing
- **Issue:** Veterans could be placed on any hex via place_veteran_unit FFI (no castle check)
- **Fix:** Added leader-on-keep + castle-adjacent validation matching apply_recruit rules
- **Files:** ffi.rs, input.lua (error map), tests/campaign.rs

## Issues Encountered

None — all bugs found during testing were fixed in-session.

## Next Phase Readiness

**Ready:**
- v3.2 Campaign Management milestone complete (phases 90, 91, 92 all done)
- All campaign features tested end-to-end

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 92-veteran-deployment, Plan: 01*
*Completed: 2026-03-08*
