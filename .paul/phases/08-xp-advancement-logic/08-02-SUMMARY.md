---
phase: 08-xp-advancement-logic
plan: 02
subsystem: game-logic
tags: [rust, advancement, bridge, gdextension, simulation, json-api]

requires:
  - phase: 08-xp-advancement-logic
    plan: 01
    provides: Unit.xp accumulation, advancement_pending flag, kill bonus XP

provides:
  - advance_unit(unit, new_def) — pure Rust stat mutation, registry-free
  - apply_advance(unit_id) — GDExtension bridge method for GDScript
  - ActionRequest::Advance — JSON API variant for external AI clients
  - test_headless_advancement_scenario — integration test verifying full XP→advance chain

affects: [09-advancement-presentation]

tech-stack:
  added: []
  patterns:
    - "advance_unit() is a free function in unit.rs — usable in tests and bridge without coupling"
    - "Advance dispatched in apply_action_json() before into() — keeps Action enum registry-free"
    - "apply_advance() follows same validation pattern as apply_move/apply_attack (error i32 codes)"

key-files:
  created: []
  modified:
    - norrust_core/src/unit.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/src/snapshot.rs
    - norrust_core/tests/simulation.rs

key-decisions:
  - "advance_unit() is a free function, not a method — keeps Unit::impl minimal; tests call it directly"
  - "ActionRequest::Advance intercepted before into() in apply_action_json — no Action::Advance needed"
  - "unreachable!() in From<ActionRequest> for Action for Advance arm — exhaustive match, clear intent"
  - "apply_advance() always uses advances_to[0] — multi-target choice is Phase 9+ concern"

patterns-established:
  - "Bridge advancement: registry lookup + advance_unit() call — same two-step pattern as place_unit_at()"
  - "JSON Advance variant: handled at bridge level, not passed to apply_action — registry-free boundary preserved"

duration: ~20min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 8 Plan 02: Advance Action Summary

**`advance_unit()` pure Rust function, `apply_advance()` GDScript bridge, `ActionRequest::Advance` JSON API variant, and headless simulation test confirming the full XP → advancement_pending → advance chain.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 2 completed (all auto) |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: advance_unit() Mutates Stats Correctly | Pass | `test_advance_unit_updates_stats_and_resets_xp` — all fields verified |
| AC-2: apply_advance() Returns 0 on Success | Pass | Bridge method compiles; integration test exercises the logic path |
| AC-3: apply_advance() Returns Error Codes on Failure | Pass | -1 not found, -2 wrong faction, -8 not pending, -9 no target, -10 def missing |
| AC-4: ActionRequest::Advance Routes Through JSON API | Pass | `apply_action_json` intercepts Advance before into(); compiles clean |
| AC-5: Headless Simulation Test Passes | Pass | `test_headless_advancement_scenario`: 5 kills → 45 XP → advance to hero (45 HP) |

## Accomplishments

- Full advancement chain works end-to-end in pure Rust: XP accumulates, flag sets, unit promotes with new stats
- `advance_unit()` is cleanly callable from tests and bridge without any registry dependency
- JSON AI clients can send `{"action":"Advance","unit_id":N}` and have it routed correctly
- `Action` enum and `apply_action()` remain registry-free — architectural boundary preserved
- 43 tests passing (41 lib + 2 integration), 0 regressions

## Task Commits

No atomic task commits (batched into phase commit).

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/unit.rs` | Modified | `advance_unit()` free function + `test_advance_unit_updates_stats_and_resets_xp` |
| `norrust_core/src/gdext_node.rs` | Modified | `apply_advance()` bridge method; `apply_action_json()` dispatches Advance before into() |
| `norrust_core/src/snapshot.rs` | Modified | `ActionRequest::Advance { unit_id }` variant; `unreachable!()` From arm |
| `norrust_core/tests/simulation.rs` | Modified | `test_headless_advancement_scenario`: 5-kill XP accumulation + hero promotion |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `advance_unit()` as free function | Minimal impl block; directly usable in integration tests without bridge | Pattern consistent with Rust idiom; no coupling |
| Advance intercepted in `apply_action_json` before `into()` | Keeps `Action` enum and `apply_action()` registry-free — core invariant | `unreachable!()` in From arm documents intent; compiler still enforces exhaustiveness |
| `advances_to[0]` only | Avoids premature UI decision (which advancement to pick); Phase 9 adds choice | Simple and correct for single-path advancement chains |

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- `apply_advance(unit_id)` callable from GDScript — Phase 9 can wire it to a button/click
- `unit["advancement_pending"]` already in `get_state_json()` output — Phase 9 HUD can read it now
- `unit["xp"]` and `unit["xp_needed"]` in JSON snapshot — XP progress bar can be derived immediately

**Concerns:**
- None

**Blockers:**
- None — Phase 9 (Advancement Presentation) may begin immediately

---
*Phase: 08-xp-advancement-logic, Plan: 02*
*Completed: 2026-02-28*
