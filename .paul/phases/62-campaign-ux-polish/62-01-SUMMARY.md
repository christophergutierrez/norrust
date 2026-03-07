---
phase: 62-campaign-ux-polish
plan: 01
subsystem: campaign-ui
tags: [recruit, veteran, faction-picker, lua, love2d]

requires:
  - phase: 61-uuid-roster
    provides: Roster module with UUID tracking and living/dead status
provides:
  - Veteran recruitment from roster in recruit panel
  - Auto-faction assignment for preset/campaign scenarios (no picker)
affects: []

tech-stack:
  added: []
  patterns: [combat_state table consolidation, recruit_state.veterans pattern]

key-files:
  created: []
  modified: [norrust_love/main.lua, norrust_love/draw.lua]

key-decisions:
  - "Skip faction picker for preset/campaign scenarios (auto-assign alphabetically)"
  - "Veterans are free to recruit (no gold cost)"
  - "combat_preview/combat_preview_target consolidated into combat_state table (upvalue fix)"
  - "recruit_veterans stored in recruit_state table (upvalue fix)"

patterns-established:
  - "Table consolidation for LuaJIT 60-upvalue limit: combat_state, recruit_state"

duration: ~30min
started: 2026-03-06
completed: 2026-03-06
---

# Phase 62 Plan 01: Campaign UX Polish Summary

**Veteran recruitment in recruit panel with [V] prefix and free placement; preset/campaign scenarios skip faction picker with auto-assigned factions.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Started | 2026-03-06 |
| Completed | 2026-03-06 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Veterans appear in recruit panel | Pass | [V] prefix, green color, "(free)" label |
| AC-2: Veteran recruitment places unit from roster | Pass | place_veteran_unit FFI, UUID mapped, removed from list |
| AC-3: Preset scenarios skip faction picker | Pass | Auto-assign factions[1] and factions[2], go straight to PLAYING |
| AC-4: Non-preset scenarios keep faction picker | Pass | Contested still shows picker flow |

## Accomplishments

- Veteran recruitment: living roster entries shown in recruit panel as free options above normal recruits
- Faction picker eliminated for preset/campaign scenarios (factions auto-assigned alphabetically)
- LuaJIT 60-upvalue limit managed via combat_state and recruit_state table consolidation

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Faction picker skip, veteran recruit logic, upvalue consolidation |
| `norrust_love/draw.lua` | Modified | Veteran entries in recruit panel with [V] prefix |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Skip faction picker for preset scenarios | Preset units have hardcoded factions; picker was misleading | Cleaner flow |
| Auto-assign factions alphabetically | factions[] already sorted; first=player, second=enemy | Consistent |
| Veterans free to recruit | Veterans are earned; gold cost would double-penalize | Simpler UX |
| place_veteran_unit for veteran recruit | Same FFI as auto-placement; no castle-hex validation | Any empty hex valid |
| combat_state table consolidation | New recruit_state upvalue pushed love.mousepressed over 60 limit | -1 net upvalue |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | LuaJIT upvalue limit (essential) |
| Deferred | 2 | Logged for future |

**Total impact:** One essential fix for LuaJIT constraint, two observations deferred.

### Auto-fixed Issues

**1. LuaJIT 60-upvalue limit in love.mousepressed**
- **Found during:** Task 2 (veteran recruit logic)
- **Issue:** Adding recruit_state.veterans as new local pushed love.mousepressed over 60 upvalues
- **Fix:** Consolidated combat_preview + combat_preview_target into combat_state table, recruit_veterans into recruit_state table
- **Files:** norrust_love/main.lua
- **Verification:** luajit -bl compiles clean

### Deferred Items

- Death animation not playing during combat (user observation, not Phase 62 scope)
- Dead roster entries saved to file unnecessarily (implicit from absence; harmless, low priority)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| combat_preview replace-all broke function name cancel_combat_preview | Fixed: restored function name, used table field for data only |
| Bracket nesting error after recruit handler refactor | Fixed missing end for if/else block |

## Next Phase Readiness

**Ready:**
- Phase 62 complete, campaign UX polished
- Ready for Phase 63: TCP Agent Server

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 62-campaign-ux-polish, Plan: 01*
*Completed: 2026-03-06*
