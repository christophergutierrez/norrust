---
phase: 121-veteran-deployment
plan: 01
subsystem: engine
tags: [ffi, campaign, deployment, veteran, lua-cleanup]

requires:
  - phase: 120-game-over-campaign-logic
    provides: Engine-driven game-over flow, campaign_record_victory with status
provides:
  - norrust_campaign_commit_deployment FFI (single-call veteran placement)
  - All gameplay logic owned by Rust engine — Lua is purely presentation/input
  - campaign_client.lua has zero hex-scanning or unit-placement logic
affects: []

tech-stack:
  added: []
  patterns: [deployed-indices-as-JSON for user selection → engine placement]

key-files:
  modified: [norrust_core/src/ffi.rs, norrust_love/norrust.lua, norrust_love/campaign_client.lua, norrust_love/input_deploy.lua]

key-decisions:
  - "Deployed veterans sent as index array JSON rather than per-unit FFI calls"
  - "Reused same placement logic as auto-placement path in load_next_scenario"

patterns-established:
  - "User selections sent as JSON indices; engine owns all validation and placement"

duration: ~10min
completed: 2026-03-13
---

# Phase 121 Plan 01: Veteran Deployment Summary

**Veteran deployment migrated to single FFI call — Rust engine now owns ALL gameplay logic, completing v5.0.**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Single FFI Call for Deployment | Pass | `norrust_campaign_commit_deployment` takes JSON indices, places veterans |
| AC-2: find_keep_and_castles Removed from Lua | Pass | No hex-scanning functions remain in campaign_client.lua |
| AC-3: Dead Context Fields Removed | Pass | campaign_veterans, campaign_roster, roster_mod removed from input_deploy.lua ctx |

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ffi.rs` | Modified | Added `norrust_campaign_commit_deployment` (~100 lines) |
| `norrust_love/norrust.lua` | Modified | Added C declaration + Lua wrapper for commit_deployment |
| `norrust_love/campaign_client.lua` | Modified | Replaced commit_deployment (90 lines → 15 lines), removed find_keep_and_castles |
| `norrust_love/input_deploy.lua` | Modified | Removed 5 dead ctx fields from both commit blocks |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Deviations | 0 | None |

## Deferred Items

- `roster.lua` still exists for save system serialization (out of v5.0 scope)
- `campaign.veterans`/`.gold`/`.index` still set in `input_setup.lua` and `input.lua` (save system boundary)
- `place_veteran_unit` FFI still exists (used by nothing in active gameplay, but harmless)

## Next Phase Readiness

**Ready:**
- v5.0 milestone complete — all 4 phases finished
- Rust engine owns: campaign orchestration, roster tracking, game-over logic, veteran deployment
- Lua is purely presentation/input — any alternative frontend works without reimplementing game logic

**Concerns:** None

**Blockers:** None

---
*Phase: 121-veteran-deployment, Plan: 01*
*Completed: 2026-03-13*
