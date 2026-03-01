---
phase: 11-ai-bridge-gdscript
plan: 01
subsystem: simulation
tags: [rust, ai, march, gdextension, gdscript, bridge, integration-test]

requires:
  - phase: 10-ai-core
    plan: 01
    provides: ai_take_turn(state, faction) — greedy move+attack AI, pure Rust

provides:
  - March fallback in ai_take_turn(): units advance toward nearest enemy when no attack is reachable
  - fn ai_take_turn(faction: i32) GDExtension bridge method — callable from GDScript
  - Auto-AI for faction 1 after player presses 'E' (GDScript wiring)
  - test_ai_marches_toward_enemy_when_no_attack integration test

affects: [milestone-v0.4-complete]

tech-stack:
  added: []
  patterns:
    - "March via min_by_key(distance to nearest enemy) over reachable non-start hexes"
    - "AI bridge method is a thin wrapper: validate faction, delegate to crate::ai::ai_take_turn"
    - "GDScript auto-AI: end_turn() → check active_faction == 1 → ai_take_turn(1) → _check_game_over()"

key-files:
  created: []
  modified:
    - norrust_core/src/ai.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/tests/simulation.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "March uses min_by_key over candidates (already filtered to landable hexes) — reuses existing ZOC+reachability data"
  - "Bridge method is a no-op for invalid faction — matches established GDScript sentinel pattern"
  - "EndTurn called inside ai_take_turn() (Phase 10 design) — GDScript checks get_active_faction() after end_turn() to decide if AI runs"

patterns-established:
  - "AI bridge wraps crate::ai::ai_take_turn directly — no intermediate state copy needed"
  - "GDScript AI trigger: check faction after player EndTurn, run AI, check game over, redraw"

duration: ~20min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 11 Plan 01: AI Bridge & GDScript Summary

**March fallback + GDExtension bridge + GDScript wiring complete: human vs AI opponent is fully playable — faction 1 AI marches, attacks, and can win.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 3 auto + 1 human-verify checkpoint |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: March Fallback Advances Units Toward Enemies | Pass | 8×1 grassland board; faction 0 at col 0 marches to col 5 (movement=5, enemy at col 7) ✓ |
| AC-2: Bridge Method Exists and Is Callable | Pass | `fn ai_take_turn(faction: i32)` compiles; cargo build succeeds ✓ |
| AC-3: GDScript Auto-Plays Faction 1 After Player EndTurn | Pass | Human-verified in Redot: 'E' triggers AI turn, board redraws, game-over overlay works ✓ |
| AC-4: No Regressions | Pass | 44 lib + 5 integration = 49 tests, all pass ✓ |

## Accomplishments

- `ai_take_turn()` march branch: `min_by_key(|&&c| enemies.iter().map(|(_, epos, _)| c.distance(*epos)).min())` — picks the reachable non-start hex closest to any enemy; plugs directly into the existing `candidates` + `enemies` data already collected before the scoring block
- `fn ai_take_turn(faction: i32)` GDExtension bridge: validates faction (0–1), delegates to `crate::ai::ai_take_turn`; no-op on invalid faction or missing game
- GDScript KEY_E handler extended: after `_core.end_turn()`, if `get_active_faction() == 1`, calls `_core.ai_take_turn(1)` and `_check_game_over()` before `queue_redraw()`
- 49 tests passing (44 lib + 5 integration) — new `test_ai_marches_toward_enemy_when_no_attack` confirms march to col 5

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Modified | Added march fallback (`else if !enemies.is_empty()`) after the attack branch |
| `norrust_core/src/gdext_node.rs` | Modified | Added `fn ai_take_turn(faction: i32)` bridge method in AI/External API section |
| `norrust_core/tests/simulation.rs` | Modified | Added `test_ai_marches_toward_enemy_when_no_attack` integration test |
| `norrust_client/scripts/game.gd` | Modified | Extended KEY_E handler to auto-play faction 1 AI after player EndTurn |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| March uses `candidates` (already ZOC-filtered) | Avoids re-computing reachability; same data collected for scoring | No extra pathfinding call; march respects ZOC automatically |
| Bridge is a no-op for faction > 1 | Consistent with GDScript sentinel pattern (-1 for missing data); prevents panic | Safe to call from GDScript without precondition checks |
| `_check_game_over()` called after AI turn | AI can eliminate all faction-0 units in one turn — win must be detected immediately | Game-over overlay appears correctly if AI wins on first trigger |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | — |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Zero deviations — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- v0.4 AI Opponent milestone is complete: human (faction 0) vs AI (faction 1) plays end-to-end
- All APIs stable: `apply_action`, `get_state_json`, `ai_take_turn`, bridge methods
- 49 tests provide full regression coverage

**Concerns:**
- None identified.

**Blockers:**
- None — milestone v0.4 complete.

---
*Phase: 11-ai-bridge-gdscript, Plan: 01*
*Completed: 2026-02-28*
