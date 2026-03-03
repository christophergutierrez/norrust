---
phase: 23-in-hex-readability
plan: 01
subsystem: ui
tags: [gdscript, rendering, hex, readability]

requires:
  - phase: 22-selection-panel
    provides: UnitSnapshot with def_id already in JSON snapshot

provides:
  - Unit type name abbreviation rendered inside every hex circle at all times

affects: []

tech-stack:
  added: []
  patterns:
    - "First-word abbreviation: def_id.split('_')[0].capitalize().left(7) for in-hex labels"

key-files:
  modified:
    - norrust_client/scripts/game.gd

key-decisions:
  - "First-word abbreviation of def_id: fighter→Fighter, elvish_captain→Elvish, orcish_warrior→Orcish"
  - "Name centered at 9px font, baseline center.y-6; no HEX_RADIUS change needed"

patterns-established: []

duration: <5min
started: 2026-03-02T00:00:00Z
completed: 2026-03-02T00:00:00Z
---

# Phase 23 Plan 01: In-Hex Readability Summary

**Unit type abbreviation rendered centered inside each hex circle — units identifiable at a glance without clicking.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | <5 min |
| Started | 2026-03-02 |
| Completed | 2026-03-02 |
| Tasks | 1 completed |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Type Name Visible In-Hex | Pass | Name drawn centered above HP in every unit circle |
| AC-2: Abbreviation Correct | Pass | split("_")[0].capitalize().left(7) — "elvish_captain"→"Elvish", "fighter"→"Fighter" |
| AC-3: Layout Not Broken | Pass | HP shifted to y+7, XP to y+20; no overlap |
| AC-4: All Tests Pass | Pass | 72 tests (56 lib + 16 integration) — all pass |

## Accomplishments

- `_draw_units()` now renders `def_id.split("_")[0].capitalize().left(7)` centered at 9px font inside each unit circle
- HP/XP text positions shifted 2px down to maintain clean separation
- No Rust changes, no HEX_RADIUS changes, no new bridges — pure GDScript, 7 lines

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_client/scripts/game.gd` | Modified | Added abbrev computation + name draw_string in `_draw_units()` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| First-word abbreviation via split("_")[0] | Semantic > truncation — "Elvish" beats "elvish_" | All unit types get meaningful 1-word label |
| 9px font, 56px centering width | Fits inside existing 58px circle diameter; no HEX_RADIUS change needed | Zero coordinate math changes |
| HP baseline +2px, XP baseline +2px | Minimal shift to give name room above | Existing layout preserved |

## Deviations from Plan

None — plan executed exactly as specified.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- v1.0 milestone complete: both phases done
- Units now readable at a glance; stat panel for detail; in-hex label for identity

**Concerns:** None.

**Blockers:** None.

---
*Phase: 23-in-hex-readability, Plan: 01*
*Completed: 2026-03-02*
