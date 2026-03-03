---
phase: 22-selection-panel
plan: 01
subsystem: ui
tags: [gdscript, snapshot, unit-panel, inspection]

# Dependency graph
requires:
  - phase: 21-factions-recruitment
    provides: stable GameState + JSON snapshot with all unit fields; recruit mode infrastructure
provides:
  - UnitSnapshot JSON with movement, attacks[], abilities[]
  - _inspect_unit_id inspection state in game.gd
  - _draw_unit_panel() rendering all unit stats in right sidebar
  - Click-any-unit → stat panel behaviour (friendly + enemy)
affects: [23-in-hex-readability]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_inspect_unit_id separate from _selected_unit_id — inspection orthogonal to selection"
    - "Recruit mode takes draw priority over unit panel via elif in _draw()"
    - "Dead unit after attack: panel gracefully draws nothing (unit not found in state)"

key-files:
  created: []
  modified:
    - norrust_core/src/snapshot.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "_inspect_unit_id is separate state from _selected_unit_id to allow enemy inspection without breaking move/attack flow"
  - "Panel hidden during recruit mode via elif (recruit panel takes priority)"
  - "AttackSnapshot is a flat struct (not reusing AttackDef) to keep snapshot layer independent of schema layer"

patterns-established:
  - "Inspection state (_inspect_unit_id) survives selection/deselection unless cleared by empty-hex click"
  - "All unit display data comes from existing StateSnapshot JSON — no new bridges required"

# Metrics
duration: ~30min
started: 2026-03-02T00:00:00Z
completed: 2026-03-02T00:00:00Z
---

# Phase 22 Plan 01: Selection Panel Summary

**UnitSnapshot JSON extended with attacks/movement/abilities; clicking any unit opens a right-sidebar stat panel showing type, faction, HP, XP, movement status, attacks, and abilities.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Started | 2026-03-02 |
| Completed | 2026-03-02 |
| Tasks | 2 completed |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: UnitSnapshot JSON fields | Pass | movement, attacks[], abilities[] all present in JSON; test_unit_snapshot_includes_movement_attacks_abilities verifies |
| AC-2: Friendly unit click shows panel | Pass | _inspect_unit_id set alongside _selected_unit_id; panel appears with reachable highlights |
| AC-3: Enemy unit click shows panel without attacking | Pass | elif branch in click handler sets _inspect_unit_id without setting _selected_unit_id |
| AC-4: Empty hex click clears panel | Pass | _clear_selection() clears both _selected_unit_id and _inspect_unit_id |
| AC-5: Panel content | Pass | Human-verified: def_id, faction label, HP, XP (when xp_needed>0), move budget, each attack, abilities |
| AC-6: Recruit mode hides panel | Pass | elif _recruit_mode in _draw() — recruit panel takes priority; unit panel not drawn |
| AC-7: All tests pass | Pass | 72 tests passing (was 71 before task 1) |

## Accomplishments

- Extended `UnitSnapshot` with `AttackSnapshot` struct plus `movement`, `attacks`, `abilities` fields — StateSnapshot JSON now exposes full unit loadout to GDScript and AI clients
- Added `_inspect_unit_id` inspection state independent from selection state — enemy inspection works without interfering with move/attack flow
- `_draw_unit_panel()` renders faction-colored header, HP, XP (conditional), movement status with exhaustion note, per-attack breakdown, and abilities list in right sidebar
- Human verification passed: Spearman panel shows correct stats, enemy click shows panel without triggering attack, empty hex clears panel, recruit mode takes draw priority

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/snapshot.rs` | Modified | Added AttackSnapshot struct; extended UnitSnapshot with movement/attacks/abilities; new test |
| `norrust_client/scripts/game.gd` | Modified | Added _inspect_unit_id var, updated _clear_selection(), added _draw_unit_panel(), wired _draw(), updated click handler |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `_inspect_unit_id` separate from `_selected_unit_id` | Selection is about movement intent; inspection is about information — mixing them would clear the panel on every move | Enemy units inspectable without selection; panel persists across moves |
| Recruit mode via `elif` (not separate guard) | Recruit panel and unit panel occupy same right-sidebar strip — they cannot overlap | Clean priority: recruit mode wins; unit stat panel does not draw |
| AttackSnapshot is a flat struct (not reusing schema types) | Snapshot layer should not import schema layer types; flat structs are simpler to serialize | Clean separation between runtime schema and serialization DTO |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | — |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** None — plan executed exactly as written.

Note: MILESTONE-CONTEXT.md stated "No new Rust bridges required — all data already in StateSnapshot JSON." This was technically correct (no new bridges were needed) but UnitSnapshot was missing attacks/movement/abilities. Task 1 fixed the snapshot itself, which was captured in the plan.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- StateSnapshot JSON exposes complete unit loadout (movement, attacks, abilities) — Phase 23 can rely on this for any in-hex label data
- `_inspect_unit_id` inspection pattern established — Phase 23 hex labels are pure display, no new state needed
- Right sidebar panel rendering pattern established in `_draw_unit_panel()`

**Concerns:**
- Phase 23 may need to increase HEX_SIZE to fit unit type name alongside existing HP/XP text — coordinate math in _draw() will need updating accordingly

**Blockers:**
- None

---
*Phase: 22-selection-panel, Plan: 01*
*Completed: 2026-03-02*
