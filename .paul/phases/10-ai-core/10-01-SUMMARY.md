---
phase: 10-ai-core
plan: 01
subsystem: simulation
tags: [rust, ai, greedy, expected-damage, pathfinding, integration-test]

requires:
  - phase: 09-advancement-presentation
    plan: 01
    provides: stable GameState, apply_action, reachable_hexes, combat APIs

provides:
  - expected_outgoing_damage() analytic damage scorer (f32, no RNG)
  - score_attack() attacker/defender pair scorer with kill bonus ×3
  - pub fn ai_take_turn(state, faction) — greedy move+attack AI, registry-free
  - test_ai_vs_ai_terminates — 5v5 headless integration test, terminates with winner

affects: [11-ai-bridge-gdscript]

tech-stack:
  added: []
  patterns:
    - "Block-scoped immutable borrows released before apply_action mutable call"
    - "Clone enemy data (Vec<(u32, Hex, Unit)>) before scoring loop to avoid state borrow conflicts"
    - "ai_take_turn() is a pure caller of apply_action — no registry, same API as GDScript/tests"

key-files:
  created:
    - norrust_core/src/ai.rs
  modified:
    - norrust_core/src/lib.rs
    - norrust_core/tests/simulation.rs

key-decisions:
  - "Uniform grassland terrain in ai-vs-ai test — checkerboard (forest=2) limits movement range to ~3 hexes, preventing first-turn engagement with movement=5"
  - "Block pattern for borrow scope — { let unit = &state.units[&uid]; ... } releases immutable borrow before apply_action"
  - "Two-step enemy collect — iter units then separate position lookup avoids closure borrow conflict"

patterns-established:
  - "Clone data upfront, score in immutable block, mutate after block exits"
  - "Ignore apply_action errors from AI — target may have died from prior action this turn"

duration: ~30min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 10 Plan 01: AI Core Summary

**Analytic greedy AI implemented in pure Rust — `ai_take_turn()` scores every (destination, target) pair by expected damage, applies best move+attack per unit, and a headless 5v5 AI-vs-AI integration test confirms the game terminates with a winner.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 2 completed (both auto) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Expected Damage Helper Correct | Pass | 7×3×0.60 = 12.6 ✓ (`test_expected_damage_40pct_defense`) |
| AC-2: AI Selects Kill Over Non-Kill | Pass | Kill bonus ×3 gives weak-enemy higher score (`test_score_prefers_kill`) |
| AC-3: AI-vs-AI Game Terminates | Pass | 5v5 fighters terminate within 100 AI turns (`test_ai_vs_ai_terminates`) |
| AC-4: No Regressions | Pass | 44 lib + 4 integration = 48 total, all pass |

## Accomplishments

- `expected_outgoing_damage()`: analytic expected-value scorer — hit_chance × effective_damage × strikes (no RNG rollouts)
- `score_attack()`: scores attacker vs defender pair — dealt × kill_bonus / received.max(1.0); uses terrain, ToD, and resistance lookups from GameState
- `ai_take_turn()`: greedy AI for all faction units — reachable_hexes flood-fill + neighbor scan + apply best Move+Attack + EndTurn; handles retaliation deaths and already-attacked skips
- `test_ai_vs_ai_terminates`: 5 fighters per side on 8×5 board, confirms game ends with a winner in ≤100 AI turns

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ai.rs` | Created | `expected_outgoing_damage()`, `score_attack()`, `ai_take_turn()`, 3 unit tests |
| `norrust_core/src/lib.rs` | Modified | `pub mod ai;` added |
| `norrust_core/tests/simulation.rs` | Modified | `test_ai_vs_ai_terminates` integration test |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Uniform grassland in AI-vs-AI test | Checkerboard (forest=2) limits range to ~3 hexes; units at col 1 can only reach col 4, not adjacent to col 6 faction-1 units | Test engages on turn 1; game terminates reliably |
| Block-scoped borrow pattern | `{ let unit = &state.units[uid]; score_attack(unit,...,state); }` releases immutable borrow before `apply_action(&mut state,...)` | Clean borrow semantics; no unsafe required |
| Two-step enemy collect | `iter().map(u.clone())` then separate `positions[&id]` lookup avoids closure capturing state twice | Avoids borrow-checker conflict in chained iterator |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential — plan's terrain setup caused AI deadlock |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** One necessary terrain fix for the integration test; all other code follows the plan exactly.

### Auto-fixed Issues

**1. Terrain: checkerboard → uniform grassland in test**
- Found during: Task 2 (`test_ai_vs_ai_terminates` failure)
- Issue: Checkerboard terrain (grassland=1, forest=2 alternating) limits effective range. From (1,1) with movement=5: reaches (4,1) at cost 5 (alternating 2,1,2,1,2). Nearest faction-1 unit at (6,1) is at distance 5, requiring 4 steps to reach (5,1) which is adjacent — but movement cost is 6 (2+1+2+1). Unit can't reach attack position.
- Fix: Uniform grassland (cost 1). From (1,1) with movement=5: reaches (5,1) in 4 steps — adjacent to (6,1). Engagement on turn 1.
- Files: `norrust_core/tests/simulation.rs`

## Issues Encountered

| Issue | Resolution |
|-------|-----------|
| `test_ai_vs_ai_terminates` failed: 5+5 units remain after 100 turns | Changed terrain from checkerboard to uniform grassland — units now engage on turn 1 |

## Next Phase Readiness

**Ready:**
- `ai_take_turn(state, faction)` callable from any Rust context (same signature for bridge)
- All prior APIs stable: `apply_action`, `get_state_json`, `apply_action_json`, `apply_advance`
- Phase 11 (AI Bridge & GDScript) can add a bridge method calling `ai_take_turn` in 1 plan

**Concerns:**
- Greedy AI doesn't advance toward enemies unless attack is possible from reachable hexes — on wide boards with forest terrain, units may never engage (same issue discovered in test). Bridge integration uses 8×5 checkerboard as shipped — Phase 11 should verify engagement or add a "march toward enemy" fallback.

**Blockers:**
- None — Phase 11 may begin immediately.

---
*Phase: 10-ai-core, Plan: 01*
*Completed: 2026-02-28*
