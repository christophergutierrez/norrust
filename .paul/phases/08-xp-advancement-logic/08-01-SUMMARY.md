---
phase: 08-xp-advancement-logic
plan: 01
subsystem: game-logic
tags: [rust, combat, xp, advancement, game_state]

requires:
  - phase: 07-advancement-schema
    provides: Unit.xp / .xp_needed / .advancement_pending fields

provides:
  - XP awarded in Action::Attack — attacker and defender both gain XP
  - kill bonus (+8 XP) on the killing blow
  - advancement_pending auto-set when xp >= xp_needed
  - 4 unit tests covering all XP grant scenarios

affects: [08-02-advance-action, 09-advancement-presentation]

tech-stack:
  added: []
  patterns:
    - "XP grant inserted after each strike phase in apply_action(Attack) — no registry access"
    - "attacker_killed local bool avoids double HashMap lookup in retaliation block"

key-files:
  created: []
  modified:
    - norrust_core/src/game_state.rs

key-decisions:
  - "1 XP per hit + 8 XP kill bonus — simple, testable, Wesnoth-compatible formula"
  - "XP block placed after purge so kill bonus logic reads from already-computed defender_hp"
  - "attacker_killed bool introduced to cleanly share kill detection with defender XP block"

patterns-established:
  - "XP grant is registry-free — uses only Unit fields copied at spawn time"
  - "advancement_pending guarded by xp_needed > 0 — units with xp_needed=0 never trigger"

duration: ~15min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 8 Plan 01: XP Gain in Combat Summary

**XP grant inserted into `Action::Attack`: attacker earns 1 XP per hit + 8 for kill; defender earns the same from retaliation; `advancement_pending` auto-sets at threshold.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 2 completed (all auto) |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Attacker Gains XP for Dealing Damage | Pass | `test_attacker_gains_xp_on_hit` — xp >= 1 after hit |
| AC-2: Attacker Gains Kill Bonus XP | Pass | `test_attacker_gains_kill_bonus_xp` — xp == 9 (1 hit + 8 kill) |
| AC-3: advancement_pending Set at Threshold | Pass | `test_advancement_pending_triggers_at_threshold` — xp=39+1→40, flag set |
| AC-4: Defender Gains XP from Retaliation | Pass | `test_defender_gains_xp_from_retaliation` — defender.xp >= 1 |
| AC-5: No XP for Zero Damage | Pass | Guarded by `if damage > 0` condition |

## Accomplishments

- XP system fully functional in headless Rust — no GDScript changes needed
- Both attacker and defender gain XP symmetrically from the same combat exchange
- `advancement_pending` flag sets automatically when threshold crossed; guarded by `xp_needed > 0` so units without advancement chain never trigger
- 41 tests passing (40 lib + 1 integration), 0 regressions

## Task Commits

No atomic task commits (batched into phase commit).

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/game_state.rs` | Modified | XP grant blocks after attacker and defender strike phases; 4 new unit tests |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| 1 XP per hit + 8 kill bonus | Simple, testable formula; matches Wesnoth spirit | Plan 08-02 can assert exact XP values in simulation tests |
| `attacker_killed` local bool | Avoids double HashMap lookup; makes defender XP block readable | Slight refactor of existing kill-detection code; no behaviour change |
| `xp_needed > 0` guard | Units placed without registry (e.g. test fixtures) have xp_needed=0 and must never trigger advancement | Tests using `Unit::new()` directly are safe without setting xp_needed |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minor refactor, no behaviour change |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** None — plan executed as written; local bool refactor is a readability improvement.

### Auto-fixed Issues

**1. Attacker-kill detection refactored into local bool**
- **Found during:** Task 1 (inserting defender XP block)
- **Issue:** Plan suggested `!state.units.contains_key(&attacker_id)` to detect kill, but the existing code structure requires reading `attacker_hp` first and then conditionally removing — the bool is the natural result
- **Fix:** Introduced `let attacker_killed: bool` from the existing HP-check block
- **Verification:** All 4 new tests pass; existing tests unchanged

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- `unit.xp` accumulates correctly after each combat — Plan 08-02 can rely on it for simulation tests
- `advancement_pending` flag triggers reliably — Plan 08-02 can check it to gate `apply_advance()`
- Formula (1+8) is documented and testable — balance simulation in 08-02 can use known thresholds

**Concerns:**
- None

**Blockers:**
- None — Plan 08-02 (Advance action + bridge method + simulation test) may begin immediately

---
*Phase: 08-xp-advancement-logic, Plan: 01*
*Completed: 2026-02-28*
