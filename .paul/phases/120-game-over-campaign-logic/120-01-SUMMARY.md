---
phase: 120-game-over-campaign-logic
plan: 01
subsystem: engine
tags: [ffi, campaign, game-over, lua-cleanup]

requires:
  - phase: 119-roster-uuid-tracking
    provides: campaign_record_victory FFI, CampaignState owns roster/veterans/gold
provides:
  - campaign_record_victory returns status ("next_scenario" or "campaign_complete")
  - campaign_load_next_scenario returns board filename in result
  - Game-over handler fully engine-driven — no redundant Lua state
affects: [121-veteran-deployment]

tech-stack:
  added: []
  patterns: [engine-driven status fields replace Lua-side completion checks]

key-files:
  modified: [norrust_core/src/ffi.rs, norrust_love/input_play.lua, norrust_love/campaign_client.lua, norrust_love/main.lua]

key-decisions:
  - "Added status field to existing VictoryResult rather than creating new FFI function"
  - "Board filename returned in load_next result so campaign_client drops campaign_index dependency"

patterns-established:
  - "FFI results include status fields for Lua to branch on — Lua never checks engine-internal state"

duration: ~10min
completed: 2026-03-13
---

# Phase 120 Plan 01: Game-Over Campaign Logic Summary

**Game-over flow fully engine-driven — Lua reads status from FFI, no shadow copies of veterans/gold/index.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Victory Result Includes Status | Pass | `status: "next_scenario"` or `"campaign_complete"` added to VictoryResult |
| AC-2: Load Next Scenario Returns Board Name | Pass | `board` field added to both "playing" and "deploy_needed" results |
| AC-3: Game-Over Handler Uses Engine Status | Pass | Handler reduced from ~30 lines to ~10 lines, reads result.status directly |
| AC-4: No Fallback Path | Pass | get_survivors/get_carry_gold fallback removed entirely |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ffi.rs` | Modified | Added `status` to VictoryResult, `board` to load_next playing/deploy results |
| `norrust_love/input_play.lua` | Modified | Game-over: removed veterans/gold/index copying, removed fallback, uses result.status |
| `norrust_love/campaign_client.lua` | Modified | load_campaign_scenario reads board from FFI result instead of campaign_index |
| `norrust_love/main.lua` | Modified | Removed campaign_index, campaign_veterans, campaign_gold from build_campaign_ctx |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Deviations | 0 | None |

**Total impact:** Plan executed exactly as written.

## Deferred Items

- `input.lua` save/load still uses `campaign.veterans`, `campaign.gold`, `campaign.index` (save system boundary)
- `input_deploy.lua` still passes `campaign_veterans` in commit_deployment ctx (Phase 121 scope, value is unused)
- `campaign.veterans`/`.gold`/`.index` still set in `input_setup.lua` on campaign start and `input.lua` on load — needed by save system

## Next Phase Readiness

**Ready:**
- Phase 121 (Veteran Deployment) can proceed — deploy screen already uses engine FFI results
- `commit_deployment` in campaign_client.lua is the last major Lua-side gameplay logic to migrate

**Concerns:** None

**Blockers:** None

---
*Phase: 120-game-over-campaign-logic, Plan: 01*
*Completed: 2026-03-13*
