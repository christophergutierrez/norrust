---
phase: 109-toml-completion
plan: 01
subsystem: data
tags: [loader, registry, factions, recruit-groups, units, toml, undead]

requires:
  - phase: 108-directory-reorg
    provides: Tree-structured directories and recursive loader
provides:
  - All 95 unit TOMLs complete (walking_corpse + soulless added)
  - 4 factions with correct leaders and recruit groups
  - All recruit group members resolve to real units
affects: [110-sprite-generation, 111-faction-integration]

tech-stack:
  added: []
  patterns: []

key-files:
  created: ["data/units/walking_corpse/walking_corpse.toml", "data/units/walking_corpse/soulless/soulless.toml", "data/factions/rebels.toml", "data/factions/northerners.toml", "data/factions/undead.toml", "data/recruit_groups/rebel_base.toml", "data/recruit_groups/northerner_base.toml", "data/recruit_groups/undead_base.toml"]
  modified: ["data/factions/loyalists.toml", "data/recruit_groups/human_base.toml", "norrust_core/src/loader.rs", "norrust_core/src/campaign.rs", "norrust_core/tests/balance.rs", "norrust_core/tests/test_ffi.rs", "norrust_core/tests/scenario_validation.rs"]

key-decisions:
  - "Walking Corpse/Soulless stats scraped from Wesnoth WML, resistance formula: toml_value = wml_value - 100"
  - "Smallfoot movetype defaults taken from dark_adept.toml (same movetype in Wesnoth)"
  - "Updated all test files referencing old faction names (orcs→northerners) beyond loader.rs — necessary for AC-4"

patterns-established:
  - "Resistance conversion: Wesnoth WML percentage → TOML value via subtract 100"
  - "Faction naming: loyalists, rebels, northerners, undead (matches Wesnoth vocabulary)"

duration: ~20min
started: 2026-03-11
completed: 2026-03-11
---

# Phase 109 Plan 01: TOML Completion + Advancement Wiring Summary

**All 95 unit TOMLs complete, 4 factions (loyalists/rebels/northerners/undead) with full recruit groups and correct leaders.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Started | 2026-03-11 |
| Completed | 2026-03-11 |
| Tasks | 2 completed |
| Files modified | 15 (8 created, 3 deleted, 4 modified) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Missing Unit TOMLs Created | Pass | walking_corpse (L0, advances_to Soulless) and soulless (L1, terminal) created with scraped WML stats |
| AC-2: All 4 Factions Exist | Pass | loyalists, rebels, northerners, undead — each with valid leader_def |
| AC-3: Recruit Groups Complete | Pass | human_base (8), rebel_base (7), northerner_base (7), undead_base (7) — all members exist in registry |
| AC-4: All Tests Pass | Pass | 118 unit + 27 integration tests pass; balance tests updated and running |

## Accomplishments

- Created Walking Corpse and Soulless TOMLs with stats scraped from Wesnoth WML (smallfoot movetype, arcane vulnerability, plague attack)
- Renamed elves→rebels and orcs→northerners factions to match Wesnoth vocabulary
- Created Undead faction with Dark Sorcerer leader and undead_base recruit group
- Updated human_base recruit group: added Horseman, Fencer, Merman Fighter; removed Sergeant (leader, not recruit)
- All 4 recruit groups resolve every member to a real unit in the registry

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `data/units/walking_corpse/walking_corpse.toml` | Created | Level 0 undead unit, advances to Soulless |
| `data/units/walking_corpse/soulless/soulless.toml` | Created | Level 1 terminal undead unit |
| `data/factions/rebels.toml` | Created | Replaces elves.toml (leader: Elvish Captain) |
| `data/factions/northerners.toml` | Created | Replaces orcs.toml (leader: Orcish Warrior) |
| `data/factions/undead.toml` | Created | New faction (leader: Dark Sorcerer) |
| `data/recruit_groups/rebel_base.toml` | Created | Replaces elf_base.toml (7 members) |
| `data/recruit_groups/northerner_base.toml` | Created | Replaces orc_base.toml (7 members) |
| `data/recruit_groups/undead_base.toml` | Created | New recruit group (7 members) |
| `data/recruit_groups/human_base.toml` | Modified | Updated member list (+3, -1) |
| `data/factions/elves.toml` | Deleted | Replaced by rebels.toml |
| `data/factions/orcs.toml` | Deleted | Replaced by northerners.toml |
| `data/recruit_groups/elf_base.toml` | Deleted | Replaced by rebel_base.toml |
| `data/recruit_groups/orc_base.toml` | Deleted | Replaced by northerner_base.toml |
| `norrust_core/src/loader.rs` | Modified | Test assertions: 3→4 factions/groups, renamed faction/group IDs |
| `norrust_core/src/campaign.rs` | Modified | Test helper: faction_1 "orcs"→"northerners" |
| `norrust_core/tests/balance.rs` | Modified | All "orcs" references→"northerners" |
| `norrust_core/tests/test_ffi.rs` | Modified | FFI test: "orcs"→"northerners" |
| `norrust_core/tests/scenario_validation.rs` | Modified | Scenario test: "orcs"→"northerners" |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Resistance formula: toml = wml - 100 | Verified by cross-referencing Skeleton TOML vs known Wesnoth values | Consistent with all existing undead TOMLs |
| Smallfoot values from dark_adept.toml | Both Dark Adept and Walking Corpse use smallfoot movetype in Wesnoth | Accurate movement/defense without parsing WML macros |
| Updated test files beyond loader.rs | Balance, FFI, campaign, scenario_validation tests all referenced "orcs" which no longer exists | Required for AC-4 (all tests pass) |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential — tests would fail without it |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** Minimal — one necessary extension to update all old faction name references in test code.

### Auto-fixed Issues

**1. Old faction names in test files beyond loader.rs**
- **Found during:** Task 2 (test updates)
- **Issue:** balance.rs, test_ffi.rs, scenario_validation.rs, and campaign.rs test helper all referenced "orcs" faction which was renamed to "northerners"
- **Fix:** Updated all references from "orcs" to "northerners"
- **Files:** balance.rs, test_ffi.rs, scenario_validation.rs, campaign.rs
- **Verification:** All 145 tests pass

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| None beyond the auto-fixed deviation | — |

## Next Phase Readiness

**Ready:**
- All 95 unit TOMLs exist and load correctly
- 4 factions fully defined with complete recruit lists
- All advancement trees wired (Walking Corpse → Soulless)
- Registry loader handles all units at arbitrary depth

**Concerns:**
- Walking Corpse and Soulless have no sprites yet — Phase 110 must generate them
- Scenarios still hardcode faction assignments — Phase 111 must add faction selection

**Blockers:**
- None

---
*Phase: 109-toml-completion, Plan: 01*
*Completed: 2026-03-11*
