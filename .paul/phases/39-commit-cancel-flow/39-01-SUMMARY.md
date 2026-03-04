---
phase: 39-commit-cancel-flow
plan: 01
subsystem: combat
tags: [combat-preview, terrain-defense, ghost-movement, auto-preview, love2d]

requires:
  - phase: 38-combat-preview
    provides: simulate_combat(), combat_preview state, CombatPreview struct
provides:
  - Terrain defense visibility in combat preview panel
  - Auto-preview on re-ghost for "attack from" comparison
affects: []

tech-stack:
  added: []
  patterns: [auto-preview on re-ghost preserving target across position change]

key-files:
  created: []
  modified:
    - norrust_core/src/combat.rs
    - norrust_core/src/ffi.rs
    - norrust_love/main.lua

key-decisions:
  - "Terrain defense fields added to CombatPreview struct (not separate query)"
  - "Auto-preview preserves target ID across re-ghost, re-queries from new position"

patterns-established:
  - "prev_target capture before cancel, re-check against new ghost_attackable"

duration: ~10min
completed: 2026-03-04
---

# Phase 39 Plan 01: Commit/Cancel Flow Summary

**Terrain defense in combat preview + auto-preview on re-ghost for "attack from" position comparison.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~10min |
| Completed | 2026-03-04 |
| Tasks | 3 completed (2 auto + 1 checkpoint) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Terrain defense in combat preview | Pass | Both attacker and defender terrain defense % shown in panel |
| AC-2: Auto-preview on re-ghost | Pass | Re-ghost to hex adjacent to same enemy auto-updates preview |
| AC-3: Auto-preview clears when target not adjacent | Pass | cancel_combat_preview() clears when target not in new ghost_attackable |
| AC-4: Full state machine edge cases | Pass | All flows verified: ghost+commit, ghost+preview+commit, ghost+cancel, direct adjacent |

## Accomplishments

- Added attacker_terrain_defense and defender_terrain_defense to CombatPreview struct and FFI JSON
- Combat preview panel shows terrain defense % for both sides (muted green color)
- Re-ghosting preserves combat_preview_target: if same enemy adjacent at new position, auto-shows updated preview
- 97 tests passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/combat.rs` | Modified | Added attacker_terrain_defense/defender_terrain_defense fields to CombatPreview |
| `norrust_core/src/ffi.rs` | Modified | Added terrain defense fields to JSON output |
| `norrust_love/main.lua` | Modified | Auto-preview on re-ghost + terrain defense display in draw_combat_preview() |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Store terrain defense on CombatPreview (not separate query) | Values already computed in FFI; avoids extra round-trip | Simple, no new FFI functions needed |
| Capture prev_target before cancel, re-check in new adjacency | Clean lifecycle: cancel clears state, then optionally re-establish | No stale preview possible |

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**Ready:**
- v1.5 Tactical Planning milestone complete (all 4 phases)
- Full tactical loop: Select → Ghost → Preview → Compare → Commit/Cancel

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 39-commit-cancel-flow, Plan: 01*
*Completed: 2026-03-04*
