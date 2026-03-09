---
phase: 96-batch-cleanup
plan: 01
subsystem: tools
tags: [sprite-pipeline, cleanup, file-organization]

requires:
  - phase: 94
    provides: generate_sprites_v2.py sprite pipeline
  - phase: 95
    provides: death derived at render time (death.png no longer needed)
provides:
  - v1 pipeline files removed
  - death.png artifacts removed
  - tools/generate_sprites.py as canonical sprite tool location
affects: []

tech-stack:
  added: []
  patterns: [project-root-tools-directory]

key-files:
  created: []
  modified: [tools/generate_sprites.py]

key-decisions:
  - "tools/ is canonical home for project-level utilities (not norrust_love/tools/)"
  - "v2 script renamed to generate_sprites.py (v2 is now the only version)"

patterns-established:
  - "Project utilities live in top-level tools/ directory"

duration: ~10min
completed: 2026-03-09
---

# Phase 96 Plan 01: Batch Cleanup Summary

**Deleted 5 obsolete v1 pipeline files, 16 death.png artifacts, and relocated generate_sprites_v2.py to tools/generate_sprites.py as the canonical sprite tool.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-03-09 |
| Tasks | 2 completed (1 auto + 1 checkpoint) |
| Files deleted | 21 (5 v1 tools + 16 death.pngs) |
| Files moved | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Obsolete Files Removed | Pass | 5 v1 pipeline files deleted, norrust_love/tools/ directory removed |
| AC-2: Death PNGs Removed | Pass | 16 death.png files deleted, find returns nothing |
| AC-3: Script Relocated | Pass | tools/generate_sprites.py --list works from project root |

## Accomplishments

- Deleted 5 v1 pipeline files (generate_all_sprites.py, generate_sprites.py, process_spritesheet.py, unit_prompts.toml, generate_ai_sprites.sh)
- Deleted 16 death.png files across all unit directories
- Moved generate_sprites_v2.py to tools/generate_sprites.py with updated PROJECT_ROOT
- Removed [death] sections from ~10 sprite.toml files
- Removed norrust_love/tools/ directory entirely

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `tools/generate_sprites.py` | Moved + modified | Relocated from norrust_love/tools/generate_sprites_v2.py, PROJECT_ROOT updated |
| `norrust_love/tools/*` | Deleted | 5 obsolete v1 pipeline files removed |
| `data/units/*/death.png` | Deleted | 16 death sprites no longer needed (derived at render time) |
| `data/units/*/sprite.toml` | Modified | [death] sections removed from ~10 files |

## Decisions Made

None — followed plan as specified.

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- Phase 96 complete: all cleanup done
- Milestone v3.4 complete: all 3 phases finished

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 96-batch-cleanup, Plan: 01*
*Completed: 2026-03-09*
