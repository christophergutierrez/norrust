---
phase: 04-game-loop-polish
plan: 02
subsystem: game-logic
tags: [rust, gdextension, healing, terrain, exhaustion, visual]

requires:
  - phase: 04-game-loop-polish/04-01
    provides: adjacency enforcement, retaliation, win/loss detection

provides:
  - TerrainDef.healing field (serde default 0) — per-terrain HP recovery rate
  - Board.healing_map — stores healing values at terrain-set time, no runtime registry lookup
  - EndTurn healing — newly-active faction's units recover HP on their turn start
  - get_unit_data() 7-tuple — id/col/row/faction/hp/moved/attacked
  - Exhausted unit visual — dimmed circles (alpha 0.4) for moved/attacked units

affects: [04-03, future terrain-based mechanics]

tech-stack:
  added: []
  patterns:
    - Healing stored on Board at set_terrain_at() time — registry not needed in apply_action()
    - 7-tuple get_unit_data() as the canonical unit data bridge format
    - serde(default) pattern for backward-compatible TerrainDef field additions

key-files:
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/board.rs
    - norrust_core/src/game_state.rs
    - norrust_core/src/gdext_node.rs
    - data/terrain/grassland.toml
    - data/terrain/forest.toml
    - norrust_client/scripts/game.gd

key-decisions:
  - "Healing cached on Board.healing_map at set_terrain_at() time — no registry lookup in apply_action()"
  - "get_unit_data() extended to 7-tuple (not a new method) — single bridge call, consistent stride"
  - "grassland healing = 2, forest healing = 0 — mechanic observable without village hexes"

patterns-established:
  - "All unit data via 7-tuple: [id, col, row, faction, hp, moved, attacked] — stride = 7 everywhere in GDScript"
  - "#[serde(default)] for optional TerrainDef fields — backward-compat TOML extension pattern"

duration: ~1 session
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 4 Plan 02: Exhaustion Indicators + Per-Turn Healing Summary

**Dimmed unit circles for exhausted units and per-turn terrain healing — positional play now has visible feedback and a recovery mechanic.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~1 session |
| Tasks | 2 completed + 1 checkpoint |
| Files modified | 7 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Exhausted Unit Visual | Pass | Moved/attacked units draw at alpha 0.4; full opacity after end turn |
| AC-2: Per-Turn Terrain Healing | Pass | Grassland units gain +2 HP at turn start; visible in HP label |
| AC-3: No Overheal | Pass | HP capped at max_hp via `.min(unit.max_hp)` in EndTurn |

## Accomplishments

- `TerrainDef.healing` added with `#[serde(default)]` — existing TOMLs without the field parse cleanly
- `Board.healing_map` caches terrain healing at `set_terrain_at()` time — `apply_action(EndTurn)` needs no registry reference
- `get_unit_data()` extended from 5-tuple to 7-tuple — `moved` and `attacked` now visible to GDScript
- GDScript `_draw_units()` and `_build_unit_pos_map()` updated to stride 7; exhaustion alpha applied per unit

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/schema.rs` | Modified | Added `#[serde(default)] pub healing: u32` to TerrainDef |
| `norrust_core/src/board.rs` | Modified | Added `healing_map` field, `set_healing()`, `healing_for()` |
| `norrust_core/src/game_state.rs` | Modified | EndTurn healing loop for newly-active faction |
| `norrust_core/src/gdext_node.rs` | Modified | `set_terrain_at()` populates healing map; `get_unit_data()` → 7-tuple |
| `data/terrain/grassland.toml` | Modified | `healing = 2` |
| `data/terrain/forest.toml` | Modified | `healing = 0` |
| `norrust_client/scripts/game.gd` | Modified | Stride 5→7 in both data loops; exhaustion alpha in `_draw_units()` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Cache healing on Board at terrain-set time | apply_action() has no registry access; avoids coupling | EndTurn healing is registry-free, consistent with architecture |
| Extend get_unit_data() (not new method) | Single bridge call, single stride, minimal GDScript change | All callers update stride; no new bridge method to maintain |
| grassland healing = 2 | Observable without village hexes; easy to change later | Mechanic verified without new terrain types |

## Deviations from Plan

None — executed exactly as specified.

## Deferred Items

| Issue | Origin | Revisit |
|-------|--------|---------|
| Village hexes (healing = 8) | Phase 4 scope | 04-03 |
| Castle hexes for recruitment | Phase 4 scope | 04-03 |
| Recruitment UI + gold system | Phase 4 scope | 04-03 |
| Movement interpolation animations | Phase 4 scope | 04-03+ |
| Resistance modifiers in combat | Phase 2, deferred | Later |
| Multi-strike retaliation cap | Phase 4, 04-01 | Later |

## Next Phase Readiness

**Ready:**
- 7-tuple data bridge is the stable format for all future unit display work
- Healing infrastructure supports village/castle terrain when added (just set `healing = 8` in TOML)
- 30 Rust tests passing; all combat, movement, healing logic tested

**Concerns:**
- Only 2 hardcoded units; no recruitment means matches are fixed
- No visual map (terrain type not shown on tiles, just color)

**Blockers:** None

---
*Phase: 04-game-loop-polish, Plan: 02*
*Completed: 2026-02-28*
