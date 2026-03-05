---
phase: 45-pipeline-refinement
plan: 01
subsystem: tooling
tags: [gemini, imagemagick, sprites, python, toml]

requires:
  - phase: 44-mage-pipeline
    provides: Proof-of-concept sprite generation via Gemini API + ImageMagick
provides:
  - Production Python pipeline for batch sprite generation
  - Prompt definitions for all 16 units
  - Re-generated Mage sprites via refined pipeline
affects: [46-full-unit-generation]

tech-stack:
  added: [generate_sprites.py]
  patterns: [unit_prompts.toml external prompt definitions, generic animation suffixes]

key-files:
  created:
    - norrust_love/tools/generate_sprites.py
    - norrust_love/tools/unit_prompts.toml
  modified:
    - norrust_love/assets/units/mage/*.png

key-decisions:
  - "All character specifics in unit_prompts.toml, animation suffixes generic in script"
  - "Portrait fuzz configurable per-unit via portrait_fuzz field in TOML"
  - "Love2D save directory stale assets cause viewer duplicates — cleared"

patterns-established:
  - "Unit prompt format: base_desc + faction + weapon + optional portrait_fuzz"
  - "Pipeline CLI: --unit NAME, --all, --dry-run, --portrait-fuzz N"

duration: ~45min
started: 2026-03-05
completed: 2026-03-05
---

# Phase 45 Plan 01: Pipeline Refinement Summary

**Production Python pipeline for all 16 units with TOML-driven prompts, verified via Mage re-generation.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45 min |
| Started | 2026-03-05 |
| Completed | 2026-03-05 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 8 (2 created + 6 re-generated) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Python Pipeline Executable | Pass | `--unit mage --dry-run` prints all prompts without API calls |
| AC-2: Unit Prompts Defined | Pass | 16 units in unit_prompts.toml with base_desc, faction, weapon |
| AC-3: Mage Re-generation Quality | Pass | All 6 spritesheets correct dimensions, human approved in-game |

## Accomplishments

- Created `generate_sprites.py` — self-contained Python 3 pipeline (stdlib only + ImageMagick)
- Defined character descriptions for all 16 units across 3 factions in `unit_prompts.toml`
- Re-generated Mage with pipeline: all 6 spritesheets verified, transparent backgrounds, correct dimensions
- Discovered and fixed Love2D save directory ghost data causing viewer duplicates

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/tools/generate_sprites.py` | Created | Production pipeline: Gemini API → ImageMagick → spritesheets |
| `norrust_love/tools/unit_prompts.toml` | Created | Character descriptions for all 16 units |
| `norrust_love/assets/units/mage/idle.png` | Re-generated | 1024×256 (4 frames) |
| `norrust_love/assets/units/mage/attack-melee.png` | Re-generated | 1536×256 (6 frames) |
| `norrust_love/assets/units/mage/attack-ranged.png` | Re-generated | 1024×256 (4 frames) |
| `norrust_love/assets/units/mage/defend.png` | Re-generated | 768×256 (3 frames) |
| `norrust_love/assets/units/mage/death.png` | Re-generated | 1024×256 (4 frames) |
| `norrust_love/assets/units/mage/portrait.png` | Re-generated | 256×256 |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Generic animation suffixes in script, character specifics in TOML | Decouples character art from animation logic; adding units = adding TOML entry | All 16 units use same prompt templates |
| Per-unit portrait_fuzz in TOML | Mage needs 8% (white beard), shaman 10%; most units use default 20% | Fine-grained control without CLI override |
| Love2D save dir cleared (stale programmatic sprites) | `generate_sprites.lua` wrote to `~/.local/share/love/norrust_love/assets/units/` with capitalized names; merged by Love2D filesystem | Viewer now shows only real filesystem units |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Viewer duplicate fix (Love2D save dir) |
| Deferred | 2 | Logged for future resolution |

**Total impact:** Essential fix discovered during verification, no scope creep.

### Auto-fixed Issues

**1. Love2D save directory ghost assets**
- **Found during:** Task 3 (human-verify checkpoint)
- **Issue:** `generate_sprites.lua` wrote sprites to Love2D save dir (`~/.local/share/love/norrust_love/assets/units/`) with capitalized names (e.g. "Mage", "Elvish Archer"). `love.filesystem.getDirectoryItems()` merges save + game dirs, creating duplicate entries in viewer.
- **Fix:** Removed `~/.local/share/love/norrust_love/` contents entirely.
- **Verification:** User confirmed viewer shows 16 lowercase units only.

### Deferred Items

- `generate_sprites.lua` should be removed or disabled — writes stale assets to Love2D save directory, conflicts with Python pipeline
- Love2D save dir can accumulate stale dev data — consider dev cleanup mechanism

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Gemini 429 rate limit on 1 frame | Retry logic in pipeline handled it automatically |
| Viewer showed duplicate units (Mage vs mage) | Stale Love2D save dir; cleared |

## Next Phase Readiness

**Ready:**
- Pipeline tested end-to-end for Mage
- All 16 unit prompts defined and ready
- `python3 generate_sprites.py --all` will batch-generate all units

**Concerns:**
- Rate limiting may slow batch generation (~336 API calls for all 16 units)
- AI consistency across units not yet validated

**Blockers:**
- None

---
*Phase: 45-pipeline-refinement, Plan: 01*
*Completed: 2026-03-05*
