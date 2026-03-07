---
phase: 78-upvalue-contexts
plan: 01
subsystem: ui
tags: [lua, luajit, upvalues, refactoring]

requires: []
provides:
  - Context tables (scn, sel, ghost, campaign, dlg, camera) for handler modules
affects: [79-input-handlers, 82-shared-table-split]

tech-stack:
  added: []
  patterns: [context-table grouping for LuaJIT upvalue management]

key-files:
  created: []
  modified: [norrust_love/main.lua]

key-decisions:
  - "Table naming: short names (scn, sel, dlg) over verbose (scenario_ctx, selection_ctx)"
  - "Bulk rename via Python script with word-boundary regex, manual fixup for table constructor keys"

patterns-established:
  - "Context tables group related state: camera.offset_x not camera_offset_x"
  - "ctx builder functions preserve original key names for module interfaces"

duration: ~45min
completed: 2026-03-07
---

# Phase 78 Plan 01: Upvalue Contexts Summary

**Grouped main.lua's 62 file-scope state variables into 6 context tables, reducing upvalue pressure from 62 to 32 state-related locals.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-07 |
| Tasks | 2 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Upvalue count reduced | Pass | 62 state locals → 20 individual + 6 tables = 26 state locals (48 total including requires/constants) |
| AC-2: All functionality preserved | Pass | luajit syntax check passes; user verified gameplay |
| AC-3: Context tables logically grouped | Pass | 6 tables: scn, sel, ghost, campaign, dlg, camera |

## Accomplishments

- Replaced 62 individual state variables with 6 context tables containing 48 fields total
- 383 variable references renamed throughout the 1700-line file
- All module interfaces preserved (draw.lua, campaign_client, save.lua receive same ctx keys)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Grouped state variables into context tables, updated all references |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Short table names (scn, sel, dlg) | Keeps code concise since these appear hundreds of times | Future phases use same names |
| Python script for bulk rename | Too many references for manual editing; regex word boundaries handle most cases | Required manual fixup for table constructor keys |
| Preserve ctx builder key names | draw.lua and campaign_client read these keys by name | No changes needed in other modules |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential fix, no scope change |

**Total impact:** Minor — bulk rename script corrupted table constructor keys, fixed manually.

### Auto-fixed Issues

**1. Table constructor key corruption from bulk rename**
- **Found during:** Task 1
- **Issue:** Python regex replaced table constructor keys (left side of `=`) in addition to values
- **Fix:** Manually restored original key names in `build_draw_ctx_state()`, `build_campaign_ctx()`, `sel` declaration, `camera` declaration
- **Verification:** `luajit -bl` syntax check + user gameplay verification

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Bulk rename corrupted table constructor keys | Manual fixup of 4 table constructors after script run |

## Next Phase Readiness

**Ready:**
- Context tables established — Phase 79 (Input Handlers) can receive these as parameters
- Clean module interfaces preserved for Phase 82 (Shared Table Split)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 78-upvalue-contexts, Plan: 01*
*Completed: 2026-03-07*
