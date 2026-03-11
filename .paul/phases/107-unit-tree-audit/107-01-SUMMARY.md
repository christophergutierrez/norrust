---
phase: 107-unit-tree-audit
plan: 01
subsystem: data
tags: [wesnoth, units, toml, advancement-trees, factions]

requires:
  - phase: none
    provides: n/a
provides:
  - UNIT-REGISTRY.md — definitive list of 95 units across 4 factions
  - TOML status audit (17 dir+sprites, 76 toml, 2 missing)
  - Proposed tree directory structure for all units
affects: [108-directory-reorg, 109-toml-completion, 110-sprite-generation, 111-faction-integration]

tech-stack:
  added: []
  patterns: [tree-structured unit directories mirroring advancement chains]

key-files:
  created: [".paul/phases/107-unit-tree-audit/UNIT-REGISTRY.md"]
  modified: []

key-decisions:
  - "4 factions chosen: Loyalists, Rebels, Northerners, Undead (2 lawful, 2 chaotic)"
  - "Wose Sapling (L0) excluded — Rebels recruit Wose (L1)"
  - "Mage tree shared between Loyalists and Rebels, single directory"
  - "Tree directory convention: base/evolution1/evolution2/"

patterns-established:
  - "Tree directories: data/units/<base>/<evolution>/<evolution>/<name>.toml"
  - "Shared units: single canonical directory, referenced by multiple factions"

duration: ~45min
started: 2026-03-10
completed: 2026-03-10
---

# Phase 107 Plan 01: Unit Tree Audit Summary

**Definitive registry of 95 units across 4 factions with advancement trees, TOML status audit, and proposed tree directory structure.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Started | 2026-03-10 |
| Completed | 2026-03-10 |
| Tasks | 3 completed |
| Files modified | 1 created |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Complete Unit Enumeration | Pass | 95 unique units across 4 factions, all advancement chains traced |
| AC-2: TOML Status Audit | Pass | 17 dir+sprites, 76 toml, 2 MISSING — totals verified |
| AC-3: Advancement Tree Verification | Pass | All 16 branching units verified, no dangling references |
| AC-4: Proposed Directory Tree | Pass | Every unit has proposed path, max depth 4, shared units noted |

## Accomplishments

- Enumerated all 95 unique units from Wesnoth WML source across Loyalists (34), Rebels (28), Northerners (22), Undead (21), with 10 shared units identified
- Audited every unit against `data/units/` — only 2 truly missing TOMLs (walking_corpse, soulless), 76 scraped TOMLs ready for use
- Proposed tree directory layout with max nesting depth of 4 levels (Mage red path, Elvish Shaman sorceress path)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `.paul/phases/107-unit-tree-audit/UNIT-REGISTRY.md` | Created | Definitive unit registry with status and proposed paths |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 4 factions: Loyalists, Rebels, Northerners, Undead | 2 lawful/day + 2 chaotic/night for balanced gameplay | Scopes all subsequent phases |
| Exclude Wose Sapling (L0) | Rebels recruit Wose (L1); Sapling is campaign-only | 95 units instead of 96 |
| Mage tree shared, single directory | Avoid duplication; both factions reference same path | Phase 111 must wire both factions to shared unit |
| Tree directory structure | Mirrors advancement chains, intuitive navigation | Loader must recurse (Phase 108) |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential corrections |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Minor corrections, no scope creep

### Auto-fixed Issues

**1. Missing merfolk units**
- **Found during:** Task 1 (unit enumeration)
- **Issue:** Initial enumeration missed Merman Fighter (Loyalists) and Merman Hunter (Rebels) from recruit lists
- **Fix:** Added both units with full advancement trees after user flagged the omission
- **Verification:** Cross-checked against Wesnoth WML faction recruit lists

**2. Unit count correction (87 → 95)**
- **Found during:** Task 1 (unit enumeration)
- **Issue:** Initial estimate of ~87 units was low; thorough WML verification found additional units
- **Fix:** Complete re-enumeration yielded 95 unique units
- **Verification:** Sort -u on all unit IDs confirmed 95 unique entries

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Roc/flying units questioned | Confirmed campaign-only, not in multiplayer faction recruit lists |
| grep overcounting table rows | Used sort -u filtering for accurate unique counts |

## Next Phase Readiness

**Ready:**
- UNIT-REGISTRY.md provides exact unit list, proposed paths, and current status for Phase 108
- 76 scraped TOMLs already have correct advances_to wiring from WML scraper
- Only 2 TOMLs need creation (walking_corpse, soulless)

**Concerns:**
- Registry loader (`load_from_dir`) only scans 1 level deep — Phase 108 must make it recursive before directory moves
- Max nesting depth of 4 may need testing with the loader

**Blockers:**
- None

---
*Phase: 107-unit-tree-audit, Plan: 01*
*Completed: 2026-03-10*
