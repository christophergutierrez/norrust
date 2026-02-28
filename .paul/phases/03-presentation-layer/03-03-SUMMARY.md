---
phase: 03-presentation-layer
plan: 03
subsystem: presentation
tags: [gdscript, gdextension, unit-rendering, selection, action-dispatch, combat]

# Dependency graph
requires:
  - phase: 03-presentation-layer
    provides: hex TileMap + mouse input (03-02)
  - phase: 03-presentation-layer
    provides: GameState bridge API — place_unit_at, apply_move, apply_attack (03-01)
provides:
  - place_unit_at() copies full stats (movement, costs, attacks, defense) from UnitDef at spawn
  - get_unit_data() 5-tuple bridge method [id, col, row, faction, hp]
  - game.gd: unit circles with HP, selection ring, reachable hex overlay, move/attack/end-turn

affects: [04-game-loop-polish]

# Tech stack
tech-stack:
  added: []
  patterns:
    - "PackedInt32Array 5-tuples: unit data transported as [id,col,row,faction,hp,...] flat array"
    - "Attack-before-move input priority: enemy check precedes reachable_cells check"
    - "draw_circle() + draw_string(ThemeDB.fallback_font) for unit glyphs in _draw()"
    - "draw_polygon() semi-transparent overlay for reachable hex highlights"
    - "draw_polyline() closed loop for selection ring"

key-files:
  modified:
    - norrust_core/src/gdext_node.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "Copy UnitDef stats at spawn time: place_unit_at() enriches Unit with movement/costs/attacks/defense before GameState insertion"
  - "get_unit_data() 5-tuple format: single bridge call gives GDScript everything needed to render units (no follow-up queries)"
  - "Enemy check before reachable check in _input(): prevents accidental move when enemy hex is within movement range"

# Metrics
duration: ~20min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 3 Plan 03: Unit Display + Action Dispatch Summary

**Two fighter units render as faction-coloured circles with live HP; click-to-select shows reachable hexes in yellow; click-to-move, click-to-attack, and 'E' end-turn are wired to Rust `apply_action` dispatch — human-verified.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min (including 2 UAT fix rounds) |
| Completed | 2026-02-28 |
| Tasks | 2 auto + 1 checkpoint |
| Files modified | 2 (gdext_node.rs, game.gd) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Units Render with Faction Colour and HP | Pass | Blue circle at (0,2), red at (4,2), HP "30" visible — human-verified |
| AC-2: Click-to-Select Shows Reachable Hexes | Pass | White ring on selected unit, yellow overlay on reachable hexes — human-verified |
| AC-3: Click Reachable Hex Moves Unit | Pass | "Moved unit 1 to (3, 2): code 0" confirmed |
| AC-4: Click Enemy Unit Dispatches Attack | Pass | "Attack result: 0" with HP update confirmed after priority fix |
| AC-5: 'E' Key Ends Turn | Pass | "End turn: code 0, faction 1, turn 1" confirmed |

## Accomplishments

- `gdext_node.rs`: `place_unit_at()` now clones UnitDef stats (max_hp, movement, movement_costs, attacks, defense) into the runtime `Unit` before insertion — reachable hexes work correctly on first click
- `gdext_node.rs`: `get_unit_data()` added — single call returns flat `[id, col, row, faction, hp, ...]` 5-tuples, eliminating need for separate faction/HP queries
- `game.gd`: full interactive loop — terrain hexes → reachable overlay → selection ring → unit circles with HP, all drawn in `_draw()` order; `_input()` routes left-click and 'E' key to correct Rust actions

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Copy UnitDef stats at spawn, not at query time | Keeps apply_action() decoupled from registry; consistent with Phase 2 arch decision | fighters get correct movement=5 and terrain costs without extra bridge calls |
| 5-tuple format for get_unit_data() | Single round-trip for all render data; GDScript unpacks in a `while i+5 <= size` loop | Phase 4 can extend to 7-tuples (add moved/attacked flags) without changing callers |
| Attack branch before reachable-move in _input() | Enemy hex can be in movement range; checking enemy first prevents silent move-to-occupied | Clean UX: clicking enemy always = attack intent |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential — correct attack/move intent |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Single essential priority fix; no scope creep.

### Auto-fixed Issues

**1. Input Logic — Attack/move priority order**
- **Found during:** Human checkpoint UAT (first test session)
- **Issue:** Plan specified checking `_reachable_cells` before enemy presence; clicking an enemy hex within movement range triggered `apply_move()` (returned -4 Occupied) instead of `apply_attack()`
- **Fix:** Swapped branch order in `_input()` — enemy check (`pos_map[cell][1] != active`) now precedes `clicked_cell in _reachable_cells`
- **Files:** `norrust_client/scripts/game.gd`
- **Verification:** Second UAT session: "Attack result: 0" printed correctly

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| HP appeared not to change after attack | Added temporary HP debug print; confirmed combat is working — 0-damage is valid when all 3 strikes miss 40% hit rate (forest defense 60%). Not a bug. Debug print removed after confirmation. |

## Next Phase Readiness

**Ready for Phase 4:**
- Complete interactive game loop proven: select → move → attack → end turn
- Rust `apply_action()` dispatch round-trip verified from GDScript
- Unit state (position, HP, faction) correctly reflected on screen after every action
- `get_unit_data()` 5-tuple design can be extended with `moved`/`attacked` flags (add 2 more ints per unit) for Phase 4 greyed-out UI

**Concerns:**
- Combat variance (RNG) can produce 0-damage attacks; acceptable gameplay but may confuse testers unfamiliar with Wesnoth hit-rate system
- No attack adjacency enforcement yet — any unit can attack any enemy — deferred to Phase 4
- No death/victory condition — defender just disappears silently

**Blockers:** None.

---
*Phase: 03-presentation-layer, Plan: 03*
*Completed: 2026-02-28*
