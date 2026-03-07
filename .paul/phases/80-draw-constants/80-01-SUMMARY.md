---
phase: 80-draw-constants
plan: 01
subsystem: ui
tags: [lua, love2d, rendering, refactoring, constants]

requires:
  - phase: 79-input-handlers
    provides: ctx table pattern for module communication
provides:
  - Named layout/color constants in draw.lua
  - Helper functions for repeated draw patterns
  - Tile color cache at scenario load
affects: [82-shared-table-split]

tech-stack:
  added: []
  patterns: [named-constants, draw-helpers, tile-color-caching]

key-files:
  created: []
  modified: [norrust_love/draw.lua, norrust_love/main.lua]

key-decisions:
  - "Only extract colors used 3+ times to named constants"
  - "draw_sidebar_bg() takes opacity param to cover all 3 alpha variants"
  - "Tile color cache built at scenario load, not per-frame"

patterns-established:
  - "Layout constants: SIDEBAR_W, SIDEBAR_PAD, SIDEBAR_X_OFF for sidebar geometry"
  - "Color constants: C_GRAY, C_GOLD, C_WARM_TITLE, C_WHITE, C_YELLOW"

duration: ~15min
completed: 2026-03-07
---

# Phase 80 Plan 01: Draw Constants Summary

**Consolidated draw.lua magic numbers into named constants and helpers; cached tile colors at scenario load.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15min |
| Completed | 2026-03-07 |
| Tasks | 2 completed (1 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Named constants replace magic numbers | Pass | SIDEBAR_W/PAD/X_OFF + 5 color constants used 100+ times total |
| AC-2: Repeated patterns extracted to helpers | Pass | draw_sidebar_bg (7 sites), faction_color (3 sites) |
| AC-3: Tile colors cached at load time | Pass | build_tile_color_cache() called from call_load_scenario/call_load_campaign_scenario |
| AC-4: All functionality preserved | Pass | luajit syntax passes, user verified identical visuals |

## Accomplishments

- 3 layout constants replace 71 hardcoded sidebar width references
- 5 color constants replace ~40 hardcoded RGB tuples
- draw_sidebar_bg() consolidates 7 sidebar background draw blocks
- faction_color() consolidates 3 faction color selection patterns
- Tile color map built once at scenario load instead of every frame

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/draw.lua` | Modified | Added constants block, helpers, replaced magic numbers throughout |
| `norrust_love/main.lua` | Modified | Added tile_color_cache, build_tile_color_cache(), passed to draw ctx |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Only extract 3+ use colors | Avoids constant bloat for one-off colors | 5 constants cover ~40 call sites |
| draw_sidebar_bg takes opacity param | All 7 sites differ only in opacity (0.6, 0.75, 0.85) | Single helper, no branching |
| tile_ids still built per-frame | Lightweight string refs, not worth caching; only colors are expensive (parse_html_color) | Minimal per-frame work remains |

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- draw.lua now uses named constants for all repeated values
- Tile color cache established for future optimization
- Phase 81 (FFI Hardening) has no dependency on draw constants

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 80-draw-constants, Plan: 01*
*Completed: 2026-03-07*
