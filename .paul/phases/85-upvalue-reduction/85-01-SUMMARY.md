---
phase: 85-upvalue-reduction
plan: 01
subsystem: lua
tags: [refactor, upvalue, luajit, tables, grouping]

requires:
  - phase: 78-upvalue-contexts
    provides: Context table grouping pattern (vars, scn, sel, ghost, campaign, dlg, camera)
provides:
  - MODES table for mode constants
  - game_data table for scenarios/campaigns/faction state
  - mods table for pass-through module references to input.lua
affects: [86-ux-fixes]

tech-stack:
  added: []
  patterns: [constant-table-grouping, module-pass-through-table]

key-files:
  created: []
  modified: [norrust_love/main.lua, norrust_love/input.lua]

key-decisions:
  - "MODES table replaces 6 individual mode constant locals"
  - "game_data table replaces 5 game data locals (factions, faction_id, leader_placed, SCENARIOS, CAMPAIGNS)"
  - "mods table built inline in ctx for pass-through to input.lua (original module locals kept in main.lua)"
  - "draw.lua ctx fields kept as individual assignments from MODES.*/game_data.* (draw.lua not modified)"
  - "campaign_client ctx PLAYING field assigned from MODES.PLAYING"

patterns-established:
  - "Group related constants/data into tables to reduce LuaJIT upvalue pressure"
  - "Pass-through module table: build inline when modules are used locally AND passed to another module"

duration: ~10min
completed: 2026-03-07
---

# Phase 85 Plan 01: Upvalue Reduction Summary

**Reduced love.load upvalues from 55 to 46 by grouping mode constants into MODES table, game data into game_data table, and pass-through modules into mods table.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-03-07 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Mode constants grouped into MODES table | Pass | 6 constants → MODES table, all refs updated |
| AC-2: Module references grouped into mods table | Pass | 5 modules passed via inline mods table in ctx |
| AC-3: Game data grouped into game_data table | Pass | 5 locals → game_data table |
| AC-4: Upvalue count reduced significantly | Pass | 55 → 46 (-9 upvalues, 14 headroom) |
| AC-5: All functionality preserved | Pass | Syntax checks pass, human-verified |

## Accomplishments

- Created MODES table replacing 6 individual mode constant locals (-5 upvalues)
- Created game_data table replacing 5 game data locals (-4 upvalues)
- Created inline mods table for input.lua pass-through (norrust, hex, events, save, roster_mod)
- Updated all references in main.lua, input.lua (draw.lua/campaign_client.lua ctx assignments updated to use MODES.*/game_data.*)
- Fixed table constructor issue where replace_all turned `faction_id = faction_id` into invalid `game_data.faction_id = game_data.faction_id`

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | MODES table, game_data table, inline mods in ctx, updated all references |
| `norrust_love/input.lua` | Modified | Replaced 14 locals with 3 (game_data, mods, MODES), updated all references |

## Deviations from Plan

### Upvalue target
- Plan targeted ≤35 upvalues; actual result is 46
- The 17 helper functions were explicitly excluded from grouping ("too invasive")
- 46 provides 14 upvalues of headroom — sufficient for foreseeable features

### Additional file references
- campaign_client.lua uses `ctx.PLAYING` — updated build_campaign_ctx to use `MODES.PLAYING`
- draw.lua ctx assignments updated to source from `MODES.*` and `game_data.*` (draw.lua itself unchanged)

## Next Phase Readiness

**Ready:**
- input.lua references updated for new table structure
- Phase 86 (UX Fixes) can proceed

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 85-upvalue-reduction, Plan: 01*
*Completed: 2026-03-07*
