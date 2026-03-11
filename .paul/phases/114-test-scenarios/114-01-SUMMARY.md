---
phase: 114-test-scenarios
plan: 01
subsystem: debug, scenarios
tags: [love2d, debug-mode, test-scenarios, toml]

requires:
  - phase: 113-debug-launch
    provides: --debug flag, debug data loading, cheat keys
provides:
  - Debug advance test scenario (8x5 board with keeps)
  - Debug recruit test scenario (8x5 board with keeps)
  - Debug scenarios wired into --debug scenario list
  - Attack damage patching in generate_debug.py
affects: []

tech-stack:
  added: []
  patterns: [debug scenario layout mirrors contested scenario for proven hex adjacency]

key-files:
  created: [scenarios/debug_advance/board.toml, scenarios/debug_advance/units.toml, scenarios/debug_recruit/board.toml, scenarios/debug_recruit/units.toml]
  modified: [norrust_love/main.lua, tools/generate_debug.py, debug/debug_config.toml, data/units/dark_adept/dark_sorcerer/dark_sorcerer.toml]

key-decisions:
  - "Used 8x5 board layout matching contested scenario for proven hex adjacency"
  - "preset_units = false — standalone scenarios don't support load_units(), use faction picker flow"
  - "Attack damage patching added to generate_debug.py for 1-damage debug combat"

patterns-established:
  - "Debug scenarios use proven board layouts (8x5 with keeps at (1,2) and (6,2)) to avoid odd-r hex adjacency bugs"

duration: ~90min
started: 2026-03-11
completed: 2026-03-11
---

# Phase 114 Plan 01: Test Scenarios + Polish Summary

**Two debug test scenarios (advance + recruit) with 8x5 boards, wired into --debug mode; fixed Dark Sorcerer missing leader ability and added attack damage patching to debug generator.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~90min |
| Started | 2026-03-11 |
| Completed | 2026-03-11 |
| Tasks | 3 completed |
| Files modified | 8 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Debug Advance Scenario Exists | Pass | 8x5 board with keeps for both factions (revised from original 4x3 plan) |
| AC-2: Debug Recruit Scenario Exists | Pass | 8x5 board with keeps and leaders, both factions can recruit |
| AC-3: Debug Mode Shows Debug Scenarios | Pass | [DBG] prefixed scenarios appear first in --debug mode |
| AC-4: Normal Mode Unchanged | Pass | Only original 3 scenarios shown without --debug |

## Accomplishments

- Created two debug test scenarios with proven 8x5 board layouts matching contested scenario hex geometry
- Extended generate_debug.py to patch attack damage fields inside `[[attacks]]` TOML sections
- Fixed Dark Sorcerer missing "leader" ability — was preventing all non-Loyalist factions from recruiting

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `scenarios/debug_advance/board.toml` | Created | 8x5 board with keeps for advance testing |
| `scenarios/debug_advance/units.toml` | Created | Unit definitions (not loaded — preset_units=false) |
| `scenarios/debug_recruit/board.toml` | Created | 8x5 board with keeps for recruit testing |
| `scenarios/debug_recruit/units.toml` | Created | Leaders at keeps for both factions |
| `norrust_love/main.lua` | Modified | Prepend [DBG] scenarios when --debug flag set (2 lines) |
| `tools/generate_debug.py` | Modified | Attack field patching inside [[attacks]] sections |
| `debug/debug_config.toml` | Modified | Added [defaults.attacks] section with damage = 1 |
| `data/units/dark_adept/dark_sorcerer/dark_sorcerer.toml` | Modified | Added "leader" to abilities |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 8x5 board instead of 4x3/6x3 | Odd-r hex offset makes small boards prone to adjacency bugs; contested layout proven | Reliable keep+castle adjacency |
| preset_units = false | load_units() only called in campaign flow, not standalone scenarios | Users pick factions and place leaders manually |
| Attack damage = 1 in debug | Units gain XP without killing each other quickly | Enables advancement testing with multiple combats |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essential — scenarios wouldn't work without fixes |
| Scope additions | 1 | Attack damage patching (small, needed for advance testing) |
| Deferred | 0 | None |

**Total impact:** All deviations were essential fixes discovered during testing.

### Auto-fixed Issues

**1. Board layout: 4x3 → 8x5**
- **Found during:** Task 1 (checkpoint:human-verify)
- **Issue:** Original 4x3 board had no keeps; 6x5 board had odd-r hex adjacency bugs
- **Fix:** Used proven 8x5 layout from contested scenario
- **Verification:** User confirmed working keeps and castles

**2. preset_units = true → false**
- **Found during:** Task 1 (checkpoint:human-verify)
- **Issue:** Standalone scenarios never call load_units() — only campaign flow does
- **Fix:** Changed to preset_units = false, users go through faction picker
- **Verification:** Both factions can pick and place leaders

**3. Dark Sorcerer missing "leader" ability**
- **Found during:** Task 3 (checkpoint:human-verify)
- **Issue:** Undead faction leader (Dark Sorcerer) had abilities = [] — apply_recruit requires "leader" ability
- **Fix:** Added "leader" to abilities in dark_sorcerer.toml
- **Verification:** Debug output confirmed faction 1 leader detected, recruitment working

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Odd-r hex adjacency on small boards | Adopted proven 8x5 contested layout as template |
| Faction 1 (non-Loyalist) can't recruit | Dark Sorcerer was missing "leader" ability — data bug |
| Debug prints crashed on u.col access | Removed debug prints after fixing root cause |

## Next Phase Readiness

**Ready:**
- Complete debug sandbox workflow: config → generate → launch --debug → test scenarios → cheat keys
- All 4 factions can recruit (leader ability bug fixed)

**Concerns:**
- Missing advancement targets (e.g., General for Lieutenant) — units with no advances_to target silently fail to advance

**Blockers:**
- None

---
*Phase: 114-test-scenarios, Plan: 01*
*Completed: 2026-03-11*
