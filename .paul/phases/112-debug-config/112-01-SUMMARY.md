---
phase: 112-debug-config
plan: 01
subsystem: tools
tags: [debug, generator, testing, toml-patching]

requires:
  - phase: none
    provides: Existing data/ directory with unit/faction/terrain TOMLs
provides:
  - Config-driven debug data generator
  - debug/data/ output directory with patched game data
affects: [113-debug-launch, 114-test-scenarios]

tech-stack:
  added: [tomllib]
  patterns: [line-by-line TOML patching preserving complex sections]

key-files:
  created: ["tools/generate_debug.py", "debug/debug_config.toml"]
  modified: [".gitignore"]

key-decisions:
  - "Line-by-line TOML patching instead of full parser — preserves [[attacks]] and [sections] unchanged"
  - "tomllib for config parsing (Python 3.11+) — simple config, no arrays-of-tables complexity"
  - "Section tracking: only patch top-level fields (before any [section] header)"

patterns-established:
  - "debug/debug_config.toml as declarative test config with defaults + per-unit overrides"
  - "tools/generate_debug.py follows same pattern as generate_sprites.py and generate_terrain.py"

duration: ~10min
started: 2026-03-11
completed: 2026-03-11
---

# Phase 112 Plan 01: Debug Config + Generator Tool Summary

**Config-driven debug data generator producing 131 patched unit TOMLs with per-unit override support.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Started | 2026-03-11 |
| Completed | 2026-03-11 |
| Tasks | 2 completed |
| Files created | 2 |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Config Schema Covers Key Parameters | Pass | experience, max_hp, cost, movement, starting_gold all supported |
| AC-2: Generator Copies and Patches Real Data | Pass | 131 units copied, 114 patched with experience=1, attacks/resistances preserved |
| AC-3: Full Data Directory Structure | Pass | units/, terrain/, factions/, recruit_groups/ all present in debug/data/ |
| AC-4: Per-Unit Overrides Work | Pass | Spearman=50 while others=1 verified |

## Accomplishments

- Created `tools/generate_debug.py` — stdlib + tomllib Python generator
- Created `debug/debug_config.toml` — declarative config with defaults and per-unit overrides
- Line-by-line TOML patching preserves complex structures ([[attacks]], [resistances], etc.)
- Generator produces complete debug/data/ directory (131 units, 4 factions, 15 terrain, 4 recruit groups)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `tools/generate_debug.py` | Created | Config-driven debug data generator |
| `debug/debug_config.toml` | Created | Declarative test configuration |
| `.gitignore` | Modified | Added debug/data/ to ignore generated output |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Line-by-line patching | Full TOML parser would mangle [[attacks]] arrays-of-tables | Safe, predictable patching |
| Section tracking (in_section flag) | Only top-level fields should be patched, not fields inside [resistances] etc. | Correct field targeting |
| tomllib for config | Python 3.14 available; config is simple key-value | Clean config parsing |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| None | — |

## Next Phase Readiness

**Ready:**
- Generator tool complete and tested
- debug/data/ produces loadable game data
- Config schema extensible for future fields

**Concerns:**
- None

**Blockers:**
- None — Phase 113 can proceed

---
*Phase: 112-debug-config, Plan: 01*
*Completed: 2026-03-11*
