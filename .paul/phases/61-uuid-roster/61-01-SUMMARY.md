---
phase: 61-uuid-roster
plan: 01
subsystem: save-system
tags: [uuid, roster, campaign, lua, identity]

requires:
  - phase: 60-campaign-save-load
    provides: Campaign save/load with veterans, trigger/dialogue state
provides:
  - Persistent unit identity via Lua-generated UUIDs
  - Campaign roster tracking all units (alive and dead) across scenarios
  - Roster serialization in save files ([[roster]] TOML section)
affects: []

tech-stack:
  added: []
  patterns: [UUID identity, roster CRUD module, engine_id-to-UUID mapping]

key-files:
  created: [norrust_love/roster.lua, norrust_love/test_roster.lua]
  modified: [norrust_love/main.lua, norrust_love/campaign_client.lua, norrust_love/save.lua]

key-decisions:
  - "UUID is 8-char hex string, Lua-generated (no Rust changes)"
  - "Roster is campaign-only; nil for standalone scenarios"
  - "engine_id-to-UUID mapping rebuilt each scenario"
  - "Standalone Lua test file for roster logic (test_roster.lua)"

patterns-established:
  - "roster_mod as separate Lua module with CRUD + serialization"
  - "uid tracked locally in placement loop (engine doesn't auto-increment)"

duration: ~60min
started: 2026-03-06
completed: 2026-03-06
---

# Phase 61 Plan 01: UUID + Roster Summary

**Persistent unit identity via Lua UUIDs and campaign roster tracking alive/dead units across scenarios, with TOML serialization.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~60min |
| Started | 2026-03-06 |
| Completed | 2026-03-06 |
| Tasks | 4 completed |
| Files modified | 5 (3 modified, 2 created) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Units have persistent UUIDs | Pass | 8-char hex UUID assigned on add |
| AC-2: Roster tracks all units | Pass | Alive and dead tracked; sync_from_engine marks dead |
| AC-3: Roster survives save/load | Pass | [[roster]] section in TOML, from_save_array restores |
| AC-4: Recruited units join roster | Pass | Recruit handler adds to roster with fresh UUID |
| AC-5: Veterans placed from roster | Pass | Living roster entries placed as veterans with UUID mapping |

## Accomplishments

- roster.lua module: UUID generation, roster CRUD, engine_id mapping, save/load serialization
- Campaign flow wired through roster: preset units, recruits, victory sync, veteran placement
- [[roster]] TOML section in save files with uuid, def_id, stats, status per entry
- Standalone test_roster.lua with 6 passing tests exercising full roster lifecycle
- Fixed pre-existing veteran placement uid collision bug

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/roster.lua` | Created | UUID generation, roster CRUD, engine_id mapping |
| `norrust_love/test_roster.lua` | Created | Standalone Lua tests for roster logic |
| `norrust_love/main.lua` | Modified | Roster integration: create/clear/sync/save/load |
| `norrust_love/campaign_client.lua` | Modified | Roster population from presets, UUID mapping on veteran placement, uid fix |
| `norrust_love/save.lua` | Modified | [[roster]] TOML serialization |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 8-char hex UUID (not RFC 4122) | Sufficient for campaign scope; simple | No external deps |
| Roster is campaign-only (nil for standalone) | Standalone scenarios don't need identity tracking | Clean separation |
| Standalone Lua test file | User requested faster feedback loop than full gameplay | test_roster.lua runs in <1s |
| Local uid tracking in placement loop | Engine's place_unit doesn't increment next_unit_id | Fixes pre-existing collision bug |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential bug fix (pre-existing) |
| Scope additions | 1 | test_roster.lua (user requested) |
| Deferred | 2 | Logged for future |

**Total impact:** One essential bug fix, one test file added by user request.

### Auto-fixed Issues

**1. Veteran placement uid collision (pre-existing bug)**
- **Found during:** Task 4 (human verification)
- **Issue:** `get_next_unit_id` called inside placement loop returned same ID each iteration because `place_unit` doesn't increment engine counter. All veterans got same ID, HashMap overwrote all but last.
- **Fix:** Get uid once before loop, increment locally per placement
- **Files:** norrust_love/campaign_client.lua
- **Verification:** Terminal debug showed unique uids (12, 13, 14...), multiple veterans placed

### Deferred Items

- Enemy faction picker always selects Loyalists regardless of user choice (pre-existing, not Phase 61)
- Veteran placement limited by keep/castle hex slots; needs bench/deploy mechanic for excess units

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| User tested standalone scenario (not campaign) — no roster | Clarified roster is campaign-only ('c' key) |
| Slow feedback loop (play full scenario to test) | Added test_roster.lua for fast iteration |
| Veterans all got same uid=12 | Fixed uid tracking in placement loop |

## Next Phase Readiness

**Ready:**
- v2.1 Save System milestone complete (all 4 phases done)
- Full save/load pipeline: positions, combat state, campaign context, trigger/dialogue state, roster

**Concerns:**
- Excess veterans lost when more survivors than keep/castle slots

**Blockers:**
- None

---
*Phase: 61-uuid-roster, Plan: 01*
*Completed: 2026-03-06*
