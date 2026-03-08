---
phase: 82-shared-table-split
plan: 01
subsystem: lua
tags: [refactor, shared-table, module-ownership, cleanup]

requires: [78-upvalue-contexts, 79-input-handlers]
provides:
  - Minimal shared table (cross-module bridge only)
  - AI state in focused local table
  - recruit_palette in sel table
  - Sound module passed directly via ctx
affects: []

tech-stack:
  added: []
  patterns: [focused-table-ownership, direct-ctx-passing]

key-files:
  created: []
  modified: [norrust_love/main.lua, norrust_love/input.lua]

key-decisions:
  - "Sound promoted to top-level local in main.lua (not in shared at all)"
  - "AI table uses short field names: vs_ai, delay, timer"
  - "recruit_palette placed in sel table (selection-related state)"

patterns-established:
  - "shared table reserved for cross-module bridge items only (agent, show_help, buttons)"
  - "Module-specific state in focused local tables (ai, sel, sound)"

duration: ~5min
completed: 2026-03-07
---

# Phase 82 Plan 01: Shared Table Split Summary

**Split shared catch-all table (8 fields) into focused groupings: local ai table, sel.recruit_palette, direct sound module. Shared reduced to 5 cross-module bridge items.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5min |
| Completed | 2026-03-07 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: AI state moved out of shared | Pass | local ai = {vs_ai, delay, timer} |
| AC-2: Recruit palette moved to sel | Pass | sel.recruit_palette in both main.lua and input.lua |
| AC-3: Sound passed directly in ctx | Pass | local sound in main.lua, ctx.sound to input.lua |
| AC-4: shared reduced to cross-module bridge | Pass | 5 fields: agent, agent_mod, show_help, buttons, handle_sidebar_button |
| AC-5: All functionality preserved | Pass | Syntax checks pass, human-verified gameplay |

## Accomplishments

- AI fields (ai_vs_ai, ai_delay, ai_timer) → local `ai` table in main.lua
- recruit_palette → sel table (accessible in input.lua via ctx.sel)
- sound module → top-level local in main.lua, passed directly to input.lua via ctx.sound
- shared table reduced from 8+ fields to 5 cross-module bridge items
- No draw.lua changes needed (ctx field names preserved)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | Split shared into ai, sel.recruit_palette, local sound |
| `norrust_love/input.lua` | Modified | Updated refs: sound direct, sel.recruit_palette |

## Deviations from Plan

| Deviation | Rationale |
|-----------|-----------|
| Sound promoted to top-level local instead of staying in shared | main.lua already had all sound refs — no need for shared indirection at all |

## Next Phase Readiness

**Ready:**
- v2.8 milestone complete (5/5 phases)
- All code cleanup and architecture goals achieved

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 82-shared-table-split, Plan: 01*
*Completed: 2026-03-07*
