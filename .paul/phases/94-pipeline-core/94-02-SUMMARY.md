---
phase: 94-pipeline-core
plan: 02
subsystem: tools
tags: [gemini, PIL, portrait, pipeline]

requires:
  - phase: 94-01
    provides: validation + retry loop infrastructure
provides:
  - portrait generation pipeline (painterly, black bg, 128x128)
  - CLI --portrait flag for standalone portrait generation
affects: [96-batch-generation]

tech-stack:
  added: []
  patterns: [separate-prompt-per-asset-type]

key-files:
  created: []
  modified: [norrust_love/tools/generate_sprites_v2.py]

key-decisions:
  - "Portraits use LANCZOS resampling (not NEAREST) for painterly quality"
  - "Portrait bg cleanup threshold=60 (lower than sprite threshold=100) for dark backgrounds"
  - "Portraits are RGB not RGBA (black bg, no transparency needed)"

patterns-established:
  - "build_portrait_prompt separate from build_prompt — different style per asset type"
  - "Portrait included automatically in generate_unit flow after all poses"

duration: ~15min
completed: 2026-03-09
---

# Phase 94 Plan 02: Portrait Pipeline Summary

**Portrait generation with painterly prompt, 128x128 black background, 100KB size limit, and --portrait CLI flag.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-09 |
| Tasks | 2 completed (1 auto + 1 checkpoint) |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Portrait Prompt | Pass | Painterly style, black bg, no STYLE_PROMPT reuse |
| AC-2: Portrait Processing | Pass | 128x128 LANCZOS, black bg cleanup |
| AC-3: Portrait Size Validation | Pass | 100KB limit with retry loop |
| AC-4: CLI Integration | Pass | --portrait flag, auto-included in full generation |

## Accomplishments

- Added build_portrait_prompt, process_portrait, generate_portrait functions
- Portrait auto-generated as part of generate_unit flow
- CLI --portrait flag for standalone portrait generation
- Human-verified portrait quality

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/tools/generate_sprites_v2.py` | Modified | Added portrait pipeline + CLI flag |

## Decisions Made

None — followed plan as specified.

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- Phase 94 complete: sprite validation + portrait pipeline
- Full generate_sprites_v2.py pipeline ready for batch use

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 94-pipeline-core, Plan: 02*
*Completed: 2026-03-09*
