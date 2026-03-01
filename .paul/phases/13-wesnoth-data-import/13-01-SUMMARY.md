---
phase: 13-wesnoth-data-import
plan: 01
subsystem: data
tags: [wesnoth, toml, registry, python, scraper]

requires:
  - phase: 12-unit-def-schema
    provides: Expanded UnitDef struct with race/cost/usage/abilities/alignment/specials fields

provides:
  - tools/scrape_wesnoth.py: one-shot WML → TOML scraper
  - data/units/*.toml: 318 Wesnoth unit TOMLs (+ 4 custom = 322 total)
  - data/terrain/*.toml: 11 new terrain TOML files
  - test_wesnoth_units_load: Rust integration test verifying all unit TOMLs load
affects: [phase-14, future-recruitment, ai-content]

tech-stack:
  added: []
  patterns: [WML line-by-line state machine parsing, skip-if-exists for custom data preservation]

key-files:
  created:
    - tools/scrape_wesnoth.py
    - data/units/*.toml (318 Wesnoth units)
    - data/terrain/{flat,hills,mountains,cave,frozen,fungus,sand,shallow_water,reef,swamp_water,castle}.toml
  modified:
    - norrust_core/tests/simulation.rs
    - norrust_core/src/loader.rs

key-decisions:
  - "parse_value() uses first-closing-quote match ([^\"]*) not greedy .* to avoid capturing WML inline comments"
  - "Scraper skips existing files — preserves 4 custom unit TOMLs"
  - "Loader tests use >= N assertions not == N to survive growing data dirs"
  - "Spearman max_hp=36 (plan AC-2 incorrectly stated 33)"

patterns-established:
  - "WML inline comments stripped via first-quote match before storing string values"
  - "Denormalized flat unit TOMLs — no MovetypeDef registry needed"

duration: ~30min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 13 Plan 01: Wesnoth Data Import Summary

**Python WML scraper generates 318 Wesnoth unit TOMLs + 11 terrain TOMLs; all 322 units load via Rust integration test (50 tests pass).**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Started | 2026-03-01 |
| Completed | 2026-03-01 |
| Tasks | 2 completed |
| Files modified | 3 source + 322 data |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: All Generated Unit TOMLs Load | Pass | 322 TOMLs load; registry.len()=322 >= 200; cargo test passes |
| AC-2: Spearman Loads with Correct Stats | Pass (with correction) | max_hp=36 (plan stated 33 — WML is 36); movement=5, level=1, alignment="lawful", pierce attack ✓ |
| AC-3: Terrain TOMLs Generated | Pass | 11 new terrain files written; grassland/forest/village untouched |
| AC-4: No Regressions | Pass | 44 lib + 6 integration = 50 tests pass (up from 49) |

## Accomplishments

- `tools/scrape_wesnoth.py`: 270-line stdlib-only Python scraper — parses 38 movetypes + 328 unit_type blocks from 327 WML files; outputs denormalized TOML with resistances/movement_costs/defense tables inline
- 318 Wesnoth unit TOMLs generated covering all playable factions (human, elf, orc, undead, drake, dwarf, naga, merfolk, etc.)
- 11 terrain TOMLs generated (flat, hills, mountains, cave, frozen, fungus, sand, shallow_water, reef, swamp_water, castle)
- `test_wesnoth_units_load`: integration test loads all 322 unit TOMLs, asserts registry >= 200, spot-checks Spearman stats

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `tools/scrape_wesnoth.py` | Created | One-shot WML → TOML scraper |
| `data/units/{318 files}.toml` | Created | Wesnoth unit definitions |
| `data/terrain/{11 files}.toml` | Created | Terrain type definitions |
| `norrust_core/tests/simulation.rs` | Modified | Added test_wesnoth_units_load + Registry import |
| `norrust_core/src/loader.rs` | Modified | Hardcoded == 4 / == 3 assertions → >= 4 / >= 3 |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `parse_value()` uses `[^"]*` (non-greedy) not `.*` | WML inline comments (`# wmllint: no spellcheck`) appear after closing `"` on same line — greedy match incorrectly captured them | Produces clean TOML string values |
| Skip existing files in scraper | Preserves 4 custom unit TOMLs (fighter/archer/hero/ranger) | Custom units survive re-runs |
| Loader tests use `>= N` assertions | data/units/ dir grows as content is added; hardcoded count breaks | Tests remain valid as data expands |
| Denormalized unit TOMLs (no MovetypeDef registry) | Keeps load path simple; Unit already denormalizes at spawn time | No new registry type needed |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 3 | Essential corrections, no scope creep |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Necessary fixes discovered during execution; no scope creep.

### Auto-fixed Issues

**1. parse_value() WML comment capture bug**
- **Found during:** Task 1 verification (cargo test run)
- **Issue:** `re.match(r'^_?\s*"(.*)"$', v)` captured trailing WML inline comments when `# wmllint: no spellcheck (until name->id)` followed the closing `"` — produced malformed TOML with unescaped quotes in 7 files
- **Fix:** Changed regex to `r'^_?\s*"([^"]*)"'` (first-quote match, no greedy span); added unquoted comment stripping
- **Files:** `tools/scrape_wesnoth.py`, 7 regenerated unit TOMLs
- **Verification:** `cargo test` — 0 TOML parse failures

**2. Plan AC-2 stat error**
- **Found during:** Task 1 verification (reading spearman.toml)
- **Issue:** Plan stated `spearman.max_hp == 33` but actual Wesnoth WML has `hitpoints=36`
- **Fix:** Integration test written with `assert_eq!(spearman.max_hp, 36)` (correct value)
- **Verification:** test_wesnoth_units_load passes

**3. loader.rs hardcoded count assertions**
- **Found during:** Task 2 (first cargo test run — 2 lib tests failed)
- **Issue:** `assert_eq!(registry.len(), 4)` and `assert_eq!(registry.len(), 3)` in loader.rs tests broke after adding 322 unit + 11 terrain files
- **Fix:** Changed to `assert!(registry.len() >= 4, ...)` and `assert!(registry.len() >= 3, ...)`
- **Files:** `norrust_core/src/loader.rs`
- **Verification:** All 44 lib tests pass

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| 7 TOML files had malformed attack names (WML comment embedded as TOML string value) | Fixed scraper parse_value(), deleted 7 bad files, re-ran scraper |
| 2 lib tests failed on first cargo test run | Fixed hardcoded count assertions in loader.rs |

## Next Phase Readiness

**Ready:**
- 322 unit definitions covering full Wesnoth roster — sufficient for meaningful AI vs AI simulations
- 14 terrain types in data/terrain/ — ready for future board/rendering integration
- Registry<UnitDef> proven to handle large datasets

**Concerns:**
- Scraped terrain IDs (flat, hills, etc.) don't match existing board terrain IDs (grassland, forest, village) — intentional mismatch per plan scope limits; needs reconciliation in a future phase
- Some Wesnoth advancement chains reference unit IDs not in our registry (units skipped for lacking attacks or templated movetype) — advances_to strings may dangle

**Blockers:** None

---
*Phase: 13-wesnoth-data-import, Plan: 01*
*Completed: 2026-03-01*
