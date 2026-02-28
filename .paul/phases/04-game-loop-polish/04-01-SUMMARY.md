---
phase: 04-game-loop-polish
plan: 01
subsystem: game-logic
tags: [rust, gdextension, combat, hex, win-condition]

requires:
  - phase: 03-presentation-layer
    provides: interactive unit display, move/attack/end-turn dispatch

provides:
  - Adjacent-only melee attack enforcement (NotAdjacent error code)
  - Defender retaliation (bidirectional combat)
  - Win/loss detection via get_winner() bridge
  - Game-over overlay and input freeze in GDScript

affects: [04-02-healing-recruitment, future combat phases]

tech-stack:
  added: []
  patterns:
    - NotAdjacent sentinel error code (-7) consistent with existing error code scheme
    - Retaliation resolved within same apply_action() call (atomic combat round)
    - get_winner() stateless query — no extra state field, derives from unit presence

key-files:
  modified:
    - norrust_core/src/game_state.rs
    - norrust_core/src/gdext_node.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "Retaliation is atomic within apply_action(Attack): defender strikes back in same call"
  - "get_winner() derives winner from unit presence — no separate game_over field in Rust"
  - "_game_over flag lives in GDScript only — Rust stays stateless about end condition"

patterns-established:
  - "All ActionError variants map to negative i32 codes; -7 = NotAdjacent"
  - "_check_game_over() called after every attack (only attacks remove units)"

duration: ~1 session
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 4 Plan 01: Combat Completion + Win/Loss Summary

**Adjacency enforcement, bidirectional combat with retaliation, and win screen — a match can now be played to a conclusion.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~1 session |
| Tasks | 2 completed + 1 checkpoint |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Adjacent-Only Attack | Pass | Non-adjacent attack returns -7 (NotAdjacent); 0 HP change confirmed in UAT |
| AC-2: Defender Retaliation | Pass | Both units' HP change after adjacent attack; retaliation block fires when defender survives |
| AC-3: Win/Loss Detection | Pass | "Faction N wins!" rendered in yellow; all input blocked after win |

## Accomplishments

- `ActionError::NotAdjacent` added to Rust enum; adjacency check fires before any damage is computed
- Full retaliation block: defender's first attack resolves against attacker's terrain defense; attacker removed if HP reaches 0; defender's `attacked` flag set
- `get_winner()` GDExtension bridge queries live unit presence — pure, stateless
- GDScript `_check_game_over()` called after every attack; `_game_over` flag freezes all further input

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/game_state.rs` | Modified | NotAdjacent variant, adjacency check, retaliation block, new test |
| `norrust_core/src/gdext_node.rs` | Modified | -7 error code, get_winner() #[func] |
| `norrust_client/scripts/game.gd` | Modified | _game_over flag, _check_game_over(), win overlay in _draw(), input guard |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Retaliation atomic in apply_action() | Single call = single observable state change; no partial states | Combat is deterministic, testable |
| get_winner() stateless | Rust has no game_over bool; derives from unit count per faction | No extra state to keep in sync |
| _game_over flag in GDScript only | Rust engine stays presentation-agnostic | Clean separation; Rust doesn't know about UI flow |

## Deviations from Plan

None — plan executed exactly as written. All task actions matched specification.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| User initially surprised that both units lose HP on attack | Explained: retaliation is AC-2, intended Wesnoth-style bidirectional combat. User accepted. |
| "Attack result: -7" read as damage by user | Clarified: -7 is the NotAdjacent error code, not a damage value |

## Deferred Items

| Issue | Origin | Revisit |
|-------|--------|---------|
| Resistance modifiers not applied in combat | Phase 2, 02-04 | 04-02 |
| Skirmisher flag (ZoC bypass) | Phase 2, 02-05 | 04-02 |
| No healing / village hexes | Phase 3 | 04-02 |
| No recruitment / gold system | Phase 3 | 04-02 |
| Multi-strike retaliation cap (Wesnoth: 1 round) | This plan | 04-02 |
| Ranged attack range check | Deferred | Later |

## Next Phase Readiness

**Ready:**
- Full match loop: spawn → select → move → attack (with retaliation) → end turn → win screen
- Rust engine is clean and presentation-agnostic; GDScript drives all UI
- 30 passing unit tests including NotAdjacent regression

**Concerns:**
- Only 2 units with hardcoded positions; recruitment system needed for real gameplay
- No visual distinction between "moved" and "not yet moved" units

**Blockers:** None

---
*Phase: 04-game-loop-polish, Plan: 01*
*Completed: 2026-02-28*
