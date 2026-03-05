---
phase: 40-asset-directory-naming
plan: 01
subsystem: assets
tags: [lua, naming, snake_case, love2d]

requires:
  - phase: 39-commit-cancel-flow
    provides: stable codebase with 16 unit sprite directories
provides:
  - snake_case asset directories (no spaces in any path)
  - normalize_unit_dir() function for def_id → directory mapping
affects: [41-split-main-lua, 43-lua-documentation]

tech-stack:
  added: []
  patterns: [normalize_unit_dir def_id-to-path mapping]

key-files:
  modified:
    - norrust_love/assets.lua
    - norrust_love/generate_sprites.lua

key-decisions:
  - "Game data IDs unchanged — only filesystem paths normalized"
  - "normalize via def_id:lower():gsub(' ', '_') — no lookup table needed"

patterns-established:
  - "Asset directories use snake_case matching data/units/*.toml convention"
  - "Lua code normalizes game data IDs to filesystem paths at lookup time"

duration: ~15min
completed: 2026-03-04
---

# Phase 40 Plan 01: Asset Directory Naming Summary

**Renamed 16 unit asset directories from PascalCase (with spaces) to snake_case, added normalize function for def_id → path mapping**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Completed | 2026-03-04 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 22 (16 sprite.toml + 3 Lua + 16 dir renames + 1 doc rename) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: No spaces in directory/file names | Pass | `find . -name "* *"` returns empty |
| AC-2: Asset directories use snake_case | Pass | All 16 dirs confirmed snake_case |
| AC-3: Love2D loads all sprites correctly | Pass | Human verified — all sprites render |
| AC-4: Rust tests still pass | Pass | 97/97 tests pass (no Rust changes) |
| AC-5: MISSSION_CONTROL.md typo fixed | Pass | Renamed to MISSION_CONTROL.md |

## Accomplishments

- 16 unit asset directories renamed to snake_case via `git mv` (preserving history)
- `normalize_unit_dir()` function added to assets.lua — converts "Elvish Archer" → "elvish_archer" at lookup time
- `normalize_dir()` added to generate_sprites.lua for output path construction
- sprite.toml `id` fields updated to match new directory names
- MISSSION_CONTROL.md typo fixed

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| norrust_love/assets/units/* | 16 renames | PascalCase → snake_case directories |
| norrust_love/assets/units/*/sprite.toml | Modified (16) | Updated `id` field to snake_case |
| norrust_love/assets.lua | Modified | Added `normalize_unit_dir()`, updated lookups |
| norrust_love/generate_sprites.lua | Modified | Added `normalize_dir()`, updated output paths |
| norrust_love/animation.lua | Modified | Comment update (Spearman → spearman) |
| MISSION_CONTROL.md | Renamed | Fixed triple-'s' typo |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Game data IDs stay unchanged | Changing "Elvish Archer" everywhere would touch 322+ TOML files, Rust tests, scenarios | Only Lua path code and filesystem changed |
| normalize via lower()+gsub | Simple string transform covers all cases; no lookup table needed | Works for any future unit names too |
| git mv for renames | Preserves git history for sprite files | Clean git log |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minor |

**Total impact:** Minimal — one command variant

### Auto-fixed Issues

**1. MISSSION_CONTROL.md not git-tracked**
- **Found during:** Task 1
- **Issue:** `git mv` failed because the file was untracked
- **Fix:** Used plain `mv` instead
- **Verification:** File exists at correct name

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- All asset directories use consistent snake_case
- No spaces in any file/directory names
- normalize function pattern established for future asset work

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 40-asset-directory-naming, Plan: 01*
*Completed: 2026-03-04*
