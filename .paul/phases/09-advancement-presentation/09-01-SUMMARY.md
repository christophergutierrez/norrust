---
phase: 09-advancement-presentation
plan: 01
subsystem: presentation
tags: [gdscript, redot, advancement, xp, ui, draw-api]

requires:
  - phase: 08-xp-advancement-logic
    plan: 02
    provides: apply_advance() bridge method, unit["advancement_pending"] in JSON snapshot

provides:
  - XP progress text ("xp/xp_needed") drawn per unit via draw_string()
  - Gold arc ring indicator for advancement_pending units via draw_arc()
  - 'A' key handler: advances selected unit via _core.apply_advance()
  - 5 fighters per side spawn — advancement reachable in normal play
  - test_fighter_advancement_with_real_stats — integration test with actual fighter weapon stats

affects: [10-ai-opponent]

tech-stack:
  added: []
  patterns:
    - "int() cast required for all JSON numeric comparisons in GDScript — Redot returns all JSON numbers as float"
    - "draw_arc() for unit-level rings; draw_polyline() for hex-level outlines — visually distinct layers"
    - "All game logic remains in Rust; GDScript only calls bridge and redraws"

key-files:
  created: []
  modified:
    - norrust_client/scripts/game.gd
    - norrust_core/tests/simulation.rs

key-decisions:
  - "draw_arc() over draw_polyline() for advancement ring — simpler, circular, distinct from hex outline"
  - "int() cast on unit[\"xp\"] and unit[\"xp_needed\"] — Redot JSON.parse_string() returns all numbers as float"
  - "5 fighters per side — with 2, advancement (40 XP) was unreachable before one unit died"
  - "test_fighter_advancement_with_real_stats added — proves pipeline with actual 7×3 sword stats"

patterns-established:
  - "Presentation-layer verification: cargo test proves Rust correctness; human-verify confirms visual layer"
  - "JSON float guard: always apply int() when comparing JSON numeric fields to GDScript int variables"

duration: ~30min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 9 Plan 01: Advancement Presentation Summary

**XP text, gold ring, and 'A' key advancement surfaced in Redot — human players can now see XP accumulating, know when a unit is ready to advance, and trigger promotion via keyboard.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: XP Text Visible | Pass | Shows "xp/xp_needed" below HP; int() cast applied for float display |
| AC-2: Gold Ring on Advancement-Ready | Pass | User confirmed "it did turn gold" — draw_arc() renders correctly |
| AC-3: 'A' Key Advances Unit | Pass | Logic correct per code review; int() casts guard JSON float comparisons |
| AC-4: No Regression | Pass | 44 tests pass (41 lib + 3 integration), all prior interactions intact |

## Accomplishments

- Advancement state is now fully visible: XP progress text on every unit circle, gold ring when ready
- 'A' key handler wired to `_core.apply_advance()` with faction + selection + pending guards
- Game spawn updated to 5 fighters per side — advancement reachable in normal play (5 kills × 9 XP = 45 XP)
- New integration test `test_fighter_advancement_with_real_stats` proves the full XP→advance→reset pipeline using actual fighter.toml weapon stats (7×3 sword → hero with 9×4 sword, max_hp 30→45)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_client/scripts/game.gd` | Modified | XP text, gold ring, 'A' key handler, 5-unit spawn, int() casts |
| `norrust_core/tests/simulation.rs` | Modified | `test_fighter_advancement_with_real_stats` integration test |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `int()` cast on all JSON numerics | Redot returns all JSON numbers as `float`; `str(53.0)` shows "53.0" not "53" | Applied in XP text and 'A' key handler |
| 5 fighters per side | With 2 fighters, one dies before accumulating 40 XP; 5 enemies = 5 kills = 45 XP | Advancement actually reachable in normal play |
| `draw_arc()` for advancement ring | Simpler than `draw_polyline()` loop; circular shape distinct from hex boundary outline | Visually clear at a glance |
| Integration test with real stats | Manual testing revealed float display bug late; headless test catches logic regressions earlier | `test_fighter_advancement_with_real_stats` added |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential corrections, no scope creep |
| Scope additions | 2 | Necessary for feature to be testable/usable |
| Deferred | 0 | — |

**Total impact:** Necessary fixes and test coverage; no unplanned feature additions.

### Auto-fixed Issues

**1. Float display — XP showed "53.0/40.0"**
- Found during: Task 3 (human-verify)
- Issue: `str(unit["xp"])` produced "53.0" because Redot JSON parser returns all numbers as float
- Fix: `str(int(unit["xp"])) + "/" + str(int(unit["xp_needed"]))`
- Files: `norrust_client/scripts/game.gd`

**2. Float comparison in 'A' key handler**
- Found during: Investigating AC-3 float behavior
- Issue: `unit["faction"] == active` compares float (from JSON) to int; added int() cast for safety
- Fix: `int(unit["id"]) == _selected_unit_id and int(unit["faction"]) == active`
- Files: `norrust_client/scripts/game.gd`

### Scope Additions

**1. 5 fighters per side (was 2)**
- Reason: With 2 fighters, advancement threshold (40 XP) is unreachable — one unit dies after ~3 combat exchanges (~11 XP max)
- Required for the feature to be demonstrable at all

**2. `test_fighter_advancement_with_real_stats` integration test**
- Reason: Manual testing is too slow for advancement verification; headless test proves pipeline with actual TOML stats
- Verifies: 7×3 sword, xp_needed=40, 5 kills → 45 XP → advance to hero (45 HP, 9×4 sword, xp_needed=80)

## Issues Encountered

| Issue | Resolution |
|-------|-----------|
| "53.0/40.0" float display | int() cast on both xp fields |
| 2-unit game can't reach 40 XP | Spawned 5 fighters per side |
| Manual verification slow | Added headless integration test with real stats |

## Next Phase Readiness

**Ready:**
- Full advancement pipeline visible and interactable in Redot
- `apply_advance()`, `get_state_json()`, `apply_action_json()` all stable
- JSON API unchanged — external agents (AI, LLM) can observe advancement state and trigger advances
- Headless simulation runs clean at 44 tests

**Concerns:**
- 'A' key advancement requires unit to be selected first — not obvious to players; future UX improvement
- No UI prompt/hint when advancement_pending (only visual ring); could add HUD text

**Blockers:**
- None — Phase 10 (AI Opponent) may begin immediately

---
*Phase: 09-advancement-presentation, Plan: 01*
*Completed: 2026-02-28*
