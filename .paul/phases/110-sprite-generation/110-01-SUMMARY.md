---
phase: 110-sprite-generation
plan: 01
subsystem: tools
tags: [sprites, generate-sprites, gemini, unit-art, tree-paths]

requires:
  - phase: 109-toml-completion
    provides: All 95 unit TOMLs complete, 4 factions defined
provides:
  - Sprite generation tool with all 114 unit definitions
  - Tree-path support for nested unit directories
affects: [111-faction-integration]

tech-stack:
  added: []
  patterns: [tree-path unit names with "/" separators in UNITS dict]

key-files:
  created: []
  modified: ["tools/generate_sprites.py"]

key-decisions:
  - "Sprite generation deferred — circles serve as placeholders until user runs tool with API key"
  - "Raw file paths use '__' separator for tree units (e.g., spearman__swordsman_v2_idle.png)"
  - "sprite.toml uses leaf name as ID (e.g., 'swordsman' not 'spearman/swordsman')"

patterns-established:
  - "Tree-path unit keys: 'spearman/swordsman' in UNITS dict maps to data/units/spearman/swordsman/"
  - "Raw sprite filenames use '__' to avoid filesystem issues with slashes"

duration: ~20min
started: 2026-03-11
completed: 2026-03-11
---

# Phase 110 Plan 01: Sprite Generation Summary

**Sprite generation tool updated with all 114 unit definitions and tree-path support. Actual image generation deferred — tool ready for user to run on demand.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Started | 2026-03-11 |
| Completed | 2026-03-11 |
| Tasks | 1 completed, 2 deferred |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: All Units Have Sprite Definitions | Pass | 114 units in UNITS dict, cross-checked against all TOML directories |
| AC-2: Tree-Path Unit Support | Pass | "/" keys work correctly, raw files use "__", sprite IDs use leaf name |
| AC-3: Batch Generation Completes | Deferred | Tool ready; user will run generation with API key when needed |
| AC-4: Visual Quality Verification | Deferred | Circles serve as placeholders; sprites generated incrementally |

## Accomplishments

- Added 97 new unit descriptions to UNITS dict in generate_sprites.py (4 legacy + 20 loyalist evolutions + 17 rebel evolutions + 20 northerner evolutions + 20 undead + 16 misc evolutions)
- Fixed tree-path support: raw filenames use "__" separator, sprite.toml uses leaf name as ID
- Cross-verified all 114 TOML unit directories have matching UNITS entries
- Each description includes accurate race, equipment, weapons, and defend behavior based on actual TOML attack data

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `tools/generate_sprites.py` | Modified | Added 97 unit defs, tree-path fixes for raw paths and sprite IDs |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Defer sprite generation | User wants to generate incrementally; circles work as placeholders | Phase 111 can proceed without sprites |
| "__" separator for raw filenames | "/" in filenames would create subdirectories in sprites_raw/ | Clean flat raw file storage |
| Leaf name for sprite.toml ID | "swordsman" is the correct ID, not "spearman/swordsman" | Matches unit TOML IDs |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Deferred | 2 | Sprite generation and visual verification deferred to user's schedule |
| Auto-fixed | 1 | Tree-path raw filename and sprite ID handling |

**Total impact:** Minimal — tool is fully ready, generation is a user-driven step.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| None | — |

## Next Phase Readiness

**Ready:**
- All 114 unit sprite definitions in place
- Tool handles tree-structured paths correctly
- User can generate sprites at any time with GEMINI_API_KEY

**Concerns:**
- 97 units still need sprite generation (~2 hours of API calls)
- Some generated sprites may need manual review/redo

**Blockers:**
- None — Phase 111 can proceed with circle placeholders

---
*Phase: 110-sprite-generation, Plan: 01*
*Completed: 2026-03-11*
