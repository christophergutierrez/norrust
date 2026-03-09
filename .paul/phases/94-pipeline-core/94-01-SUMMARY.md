---
phase: 94-pipeline-core
plan: 01
subsystem: tools
tags: [gemini, PIL, sprite-pipeline, validation]

requires:
  - phase: none
    provides: existing generate_sprites_v2.py prototype
provides:
  - sprite validation pipeline (multi-blob, size, edge checks)
  - retry loop with max 3 attempts per pose
affects: [94-02-portrait-pipeline, 96-batch-generation]

tech-stack:
  added: []
  patterns: [validate-after-process, retry-with-backoff]

key-files:
  created: []
  modified: [norrust_love/tools/generate_sprites_v2.py]

key-decisions:
  - "Direction auto-flip removed: COM heuristic unreliable, manual flip via magick -flop"
  - "Processed sprites preferred as --base reference over raw sprites"

patterns-established:
  - "Validation runs automatically after process, before retry decision"
  - "Manual direction fix: magick <file>.png -flop <file>.png"

duration: ~45min
completed: 2026-03-09
---

# Phase 94 Plan 01: Sprite Validation + Retry Loop Summary

**Validation pipeline (multi-blob, size, edge checks) with retry loop integrated into generate_pose — direction auto-flip removed after testing proved COM heuristic unreliable.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-09 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Direction Validation with Auto-Flip | Removed | COM heuristic flipped correct sprites; removed entirely |
| AC-2: Multi-Blob Detection | Pass | BFS flood-fill, 5% threshold, tested on real sprites |
| AC-3: Size Enforcement | Pass | 30KB hard / 20KB warn limits |
| AC-4: Edge Quality | Pass | 2px border check for opaque pixels |
| AC-5: Retry Loop | Pass | max_attempts=3, 10s backoff, NEEDS REVIEW flag |

## Accomplishments

- Added check_multi_blob, check_size, check_edges, validate_sprite functions (PIL-only, no external deps)
- Integrated retry loop into generate_pose with validation gate
- Updated generate_unit to report pass/fail summary per pose
- Tested end-to-end on mage and elvish_archer units

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/tools/generate_sprites_v2.py` | Modified | Added validation functions + retry loop |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Remove direction auto-flip | COM heuristic unreliable — flipped correct sprites on mage and elvish_archer | Manual fix via `magick img.png -flop img.png` when needed |
| Use processed idle as --base | Processed sprites are cleaned up and user-approved; better reference than raw | Users should pass `data/units/<name>/idle.png` as --base |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Direction flip logic inverted, then removed entirely |
| Scope additions | 0 | None |
| Deferred | 0 | None |

**Total impact:** AC-1 dropped — direction is a manual concern, not automatable with pixel analysis.

### Auto-fixed Issues

**1. Direction auto-flip heuristic inverted**
- **Found during:** Human verification checkpoint
- **Issue:** COM-based direction detection flipped correctly-facing sprites
- **Fix:** First inverted the threshold, then removed entirely after continued failures
- **Files:** norrust_love/tools/generate_sprites_v2.py

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| COM heuristic unreliable for direction | Removed; manual `magick -flop` instead |

## Next Phase Readiness

**Ready:**
- Validation pipeline working for multi-blob, size, edges
- Retry loop integrated
- Pipeline tested on multiple units

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 94-pipeline-core, Plan: 01*
*Completed: 2026-03-09*
