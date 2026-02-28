---
phase: 04-game-loop-polish
plan: 03
subsystem: game-logic
tags: [rust, gdextension, combat, resistance, hud, time-of-day]

requires:
  - phase: 04-game-loop-polish/04-02
    provides: 7-tuple unit data, exhaustion indicators, healing

provides:
  - Unit.resistances field (copied from UnitDef at spawn)
  - Resistance modifier applied in forward and retaliation combat
  - get_time_of_day_name() bridge method ("Day"/"Night"/"Neutral")
  - HUD: "Turn N · Day/Night/Neutral · Blue's/Red's Turn" (colored text)

affects: [future combat refinements, AI agent state export]

tech-stack:
  added: []
  patterns:
    - effective_damage = base × (100 + resistance) / 100 computed before resolve_attack()
    - HUD text color matches unit circle color — single source of truth for faction colors

key-files:
  modified:
    - norrust_core/src/unit.rs
    - norrust_core/src/game_state.rs
    - norrust_core/src/gdext_node.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "Resistance applied before resolve_attack() — combat.rs signature unchanged"
  - "HUD text color = faction circle color — Blue text for faction 0, Red for faction 1"

patterns-established:
  - "Faction color constants: faction 0 = Color(0.25, 0.42, 0.88), faction 1 = Color(0.80, 0.12, 0.12)"
  - "All stat data (attacks, defense, resistances) copied from UnitDef into Unit at spawn"

duration: ~1 session
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 4 Plan 03: Resistance Modifiers + HUD Summary

**Resistance modifiers complete the Wesnoth combat formula; a colored HUD shows turn, time of day, and active faction.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~1 session |
| Tasks | 2 completed + 1 checkpoint + 1 UAT fix |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Resistance Modifiers Applied | Pass | effective_damage = base × (100 + resistance) / 100; both forward and retaliation |
| AC-2: HUD Shows Turn/ToD/Faction | Pass | Visible at top-left; colored text matches unit circles |
| AC-3: HUD Updates Across Turns | Pass | Faction name and ToD update immediately on end turn |

## Accomplishments

- `Unit.resistances: HashMap<String, i32>` added; copied from UnitDef at spawn in `place_unit_at()`
- Resistance applied in `apply_action(Attack)` before `resolve_attack()` — formula is now
  `effective_damage = base × (100 + resistance) / 100` for both forward and retaliation
- `get_time_of_day_name()` bridge method uses existing `time_of_day()` and `TimeOfDay` from combat.rs
- HUD draws "Turn N · Day/Night/Neutral · Blue's/Red's Turn" in faction color (blue or red)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/unit.rs` | Modified | Added `resistances: HashMap<String, i32>` field |
| `norrust_core/src/game_state.rs` | Modified | Resistance modifier in forward + retaliation attack |
| `norrust_core/src/gdext_node.rs` | Modified | Copy resistances at spawn; `get_time_of_day_name()` bridge |
| `norrust_client/scripts/game.gd` | Modified | HUD with colored faction text |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Compute effective_damage before resolve_attack() | Keeps combat.rs signature stable | No chain of changes to existing combat tests |
| HUD text in faction color | User feedback: white text made Blue/Red ambiguous | Faction color is now self-documenting |

## Deviations from Plan

**UAT fix:** After checkpoint approval, user noted HUD text was white regardless of faction,
making it ambiguous which colored circle corresponded to which faction name. Fixed by
drawing HUD text in the faction's circle color (blue for faction 0, red for faction 1).

## Deferred Items

| Issue | Origin | Revisit |
|-------|--------|---------|
| Village/castle hexes | Phase 4 scope | 04-04 |
| Recruitment UI + gold | Phase 4 scope | 04-04 |
| Movement animations | Phase 4 scope | 04-04+ |
| Multi-strike retaliation cap | 04-01 | Later |
| Per-unit resistance tooltip on hover | 04-03 | Later |

## Next Phase Readiness

**Ready:**
- Full Wesnoth combat formula implemented: terrain defense × resistance × ToD modifier
- HUD provides clear game state at a glance
- 30 Rust tests passing

**Concerns:**
- Only 2 hardcoded units; game needs recruitment to feel like a strategy game
- No map-level terrain variety (all grassland/forest checkerboard)

**Blockers:** None

---
*Phase: 04-game-loop-polish, Plan: 03*
*Completed: 2026-02-28*
