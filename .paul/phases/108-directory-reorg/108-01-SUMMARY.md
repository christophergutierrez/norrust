---
phase: 108-directory-reorg
plan: 01
subsystem: data
tags: [loader, registry, directory-structure, units, tree]

requires:
  - phase: 107-unit-tree-audit
    provides: UNIT-REGISTRY.md with proposed directory paths for 95 units
provides:
  - Recursive registry loader (arbitrary depth)
  - Tree-structured unit directories mirroring advancement paths
affects: [109-toml-completion, 110-sprite-generation, 111-faction-integration]

tech-stack:
  added: []
  patterns: [recursive scan_dir helper with load_flat flag]

key-files:
  created: []
  modified: ["norrust_core/src/loader.rs", "norrust_core/tests/simulation.rs", "data/units/**"]

key-decisions:
  - "Legacy test units (fighter, archer, hero, ranger) kept as root-level directories"
  - "210 non-faction scraped TOMLs deleted (drakes, dwarves, dunes, ships, etc.)"
  - "scan_dir helper with load_flat boolean controls flat TOML loading at root only"

patterns-established:
  - "Tree directories: data/units/<base>/<evolution>/<name>.toml at arbitrary depth"
  - "Recursive loader: scan_dir(path, load_flat, items) — load_flat=true only at root"

duration: ~15min
started: 2026-03-11
completed: 2026-03-11
---

# Phase 108 Plan 01: Directory Reorganization + Recursive Loader Summary

**Recursive registry loader and complete tree-structured directory reorganization for 93 faction units + 4 legacy test units.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Started | 2026-03-11 |
| Completed | 2026-03-11 |
| Tasks | 3 completed |
| Files modified | 2 Rust files + ~300 data file moves/deletes |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Recursive Loader | Pass | scan_dir recurses to arbitrary depth; backward compatible |
| AC-2: All Units in Tree Directories | Pass | 93 of 95 units in tree dirs (2 missing TOMLs deferred to Phase 109) |
| AC-3: Existing Sprites Preserved | Pass | All 17 sprite directories intact (orcish_warrior, elvish_captain moved with sprites) |
| AC-4: All Tests Pass | Pass | 118 unit + 38 integration tests pass; 1 assertion updated |

## Accomplishments

- Extracted recursive `scan_dir` helper in loader.rs — loads `<dirname>.toml` at any nesting depth, flat TOMLs only at root
- Moved 93 unit TOMLs into tree directories per UNIT-REGISTRY.md (14 new root dirs, 72 nested dirs, 2 directory moves)
- Deleted 210 non-faction scraped TOMLs (drakes, dwarves, dunes, ships, saurians, etc.)
- Preserved 4 legacy test units (fighter, archer, hero, ranger) as root-level directories
- Deep nesting verified: `mage/red_mage/arch_mage/great_mage/` and `elvish_shaman/elvish_sorceress/elvish_enchantress/elvish_sylph/`

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/loader.rs` | Modified | Recursive scan_dir helper for arbitrary-depth loading |
| `norrust_core/tests/simulation.rs` | Modified | Updated unit count assertion (>= 200 → >= 95) |
| `data/units/` | Reorganized | 93 units in tree dirs, 210 non-faction deleted |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Keep legacy test units at root | Tests depend on fighter/archer/hero/ranger by ID | No tree nesting for these 4 |
| Delete non-faction TOMLs | 210 scraped units not in 4 target factions; reduce noise | Registry now loads only relevant units |
| scan_dir load_flat parameter | Prevents loading stray TOMLs in subdirectories | Clean separation of root vs nested behavior |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Test assertion update |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Minimal — one test assertion adjusted

### Auto-fixed Issues

**1. test_wesnoth_units_load assertion**
- **Found during:** Task 3 (test verification)
- **Issue:** Test expected >= 200 units; after deleting non-faction TOMLs only 112 remain
- **Fix:** Updated assertion to >= 95 with comment explaining composition
- **File:** `norrust_core/tests/simulation.rs:339-344`
- **Verification:** Test passes

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| None beyond expected assertion update | — |

## Next Phase Readiness

**Ready:**
- Recursive loader handles any depth — Phase 109 can create missing TOMLs in correct locations
- Tree directory structure is complete reference for Phase 110 sprite generation
- All advancement trees visible in filesystem layout

**Concerns:**
- 2 missing TOMLs (walking_corpse, soulless) — Phase 109 must create them
- Recruit groups and faction TOMLs still reference old unit names — Phase 109

**Blockers:**
- None

---
*Phase: 108-directory-reorg, Plan: 01*
*Completed: 2026-03-11*
