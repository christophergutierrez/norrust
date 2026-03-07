---
phase: 79-input-handlers
plan: 01
subsystem: ui
tags: [lua, love2d, input-handling, refactoring]

requires:
  - phase: 78-upvalue-contexts
    provides: context tables (scn, sel, ghost, campaign, dlg, camera)
provides:
  - input.lua module with all input handler logic
  - main.lua reduced to thin dispatcher (~980 lines)
affects: [80-draw-constants, 82-shared-table-split]

tech-stack:
  added: []
  patterns: [module-context-passing, vars-table-for-mutable-scalars]

key-files:
  created: [norrust_love/input.lua]
  modified: [norrust_love/main.lua]

key-decisions:
  - "vars table wraps mutable scalars (game_mode, game_over, etc.) for shared mutation"
  - "input.lua receives full ctx table in M.init() and unpacks to module-level locals"
  - "Sidebar button handler calls M.keypressed() internally instead of love.keypressed()"

patterns-established:
  - "Module context passing: build ctx table in love.load, pass to module.init()"
  - "Mutable scalar sharing: wrap in table so mutations propagate between modules"

duration: ~30min
completed: 2026-03-07
---

# Phase 79 Plan 01: Input Handlers Summary

**Extracted all input handlers (keypressed, mousepressed, mousereleased, mousemoved, wheelmoved) into input.lua module, reducing main.lua from 1667 to 980 lines.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-07 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Input handlers extracted to input.lua | Pass | All 5 handlers + sidebar button handler in input.lua |
| AC-2: All functionality preserved | Pass | luajit syntax check passes, user verified full gameplay |
| AC-3: main.lua line count reduced | Pass | 980 lines (target: ≤1000) |

## Accomplishments

- Created input.lua (804 lines) with all input handler logic
- main.lua reduced from 1667 to 980 lines with thin dispatchers (≤5 lines each)
- Introduced `vars` table pattern for mutable scalar sharing between modules

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/input.lua` | Created | All input handler logic (keypressed, mousepressed, mousereleased, mousemoved, wheelmoved) |
| `norrust_love/main.lua` | Modified | Thin dispatchers, vars table for mutable scalars, ctx table built in love.load |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| vars table for mutable scalars | Lua tables pass by reference; scalars don't. Wrapping game_mode, game_over, etc. in vars table lets input.lua mutate them visibly to main.lua | main.lua reads vars.game_mode etc. everywhere |
| Full ctx table passed to M.init() | Single init call with all references avoids passing 30+ args to each handler | Clean module boundary |
| Sidebar handler calls M.keypressed internally | Avoids circular dependency through love.keypressed | Keeps handler logic within module |

## Deviations from Plan

### Auto-fixed Issues

**1. Table constructor key corruption during bulk rename**
- **Found during:** Task 1 (vars rename)
- **Issue:** Python regex `\b` word-boundary replaced table constructor keys (e.g., `engine = vars.engine` became `vars.engine = vars.engine` as keys)
- **Fix:** Manually restored original key names in build_campaign_ctx and build_draw_ctx_state
- **Files:** norrust_love/main.lua
- **Verification:** luajit -bl syntax check

**Total impact:** Essential fix, no scope creep

## Next Phase Readiness

**Ready:**
- main.lua is now ~980 lines, clean dispatcher pattern
- Context tables and vars table established for future module extraction
- Phase 80 (Draw Constants) has no dependency on input extraction

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 79-input-handlers, Plan: 01*
*Completed: 2026-03-07*
