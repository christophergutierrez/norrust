# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** Phase 5 — AI Hooks & External APIs

## Current Position

Milestone: v0.1 Initial Release
Phase: 5 of 5 (AI Hooks & External APIs) — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-28 — Phase 4 complete, transitioned to Phase 5

Progress:
- Milestone: [████████████████░] 90%
- Phase 5:   [░░░░░░░░░░] 0%

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Phase 4 complete — ready to plan Phase 5]
```

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Per-file TOML layout (one entity per file) | Phase 1 | All future data follows: `data/{type}/{id}.toml` |
| Generic `Registry<T>` with `IdField` trait | Phase 1 | Reusable for factions/attacks with no new loader code |
| `crate-type = ["cdylib", "rlib"]` | Phase 1 | cdylib for Redot, rlib for cargo test — both needed |
| `bin/` copy workflow for .so | Phase 1 | After `cargo build`: `cp target/debug/libnorrust_core.so ../norrust_client/bin/` |
| Return -1 (not panic) for not-found GDScript queries | Phase 1 | GDScript has no Option; -1 = sentinel for missing data |
| Cubic hex coordinates (x+y+z=0) as canonical type | Phase 2, 02-01 | All hex math internal; offset only at I/O boundaries |
| Odd-r offset (pointy-top) for Board/map | Phase 2, 02-01 | Matches Wesnoth map convention |
| Unit instance (Unit) separate from blueprint (UnitDef) | Phase 2, 02-02 | GameState owns runtime Unit; def_id string links to Registry at lookup time |
| apply_action mutates &mut GameState in place | Phase 2, 02-02 | Zero-copy, simpler API; returns Result<(), ActionError> |
| 99 = impassable movement cost convention | Phase 2, 02-03 | Matches UnitDef.movement_costs schema; skip terrain with cost >= 99 |
| Alignment enum in unit.rs (not combat.rs) | Phase 2, 02-04 | Prevents circular import: combat.rs imports unit.rs, not vice versa |
| Unit carries combat data (attacks, defense map) | Phase 2, 02-04 | Avoids registry coupling in apply_action(Attack); caller copies from UnitDef at spawn |
| movement=0 sentinel on Unit | Phase 2, 02-05 | Skip pathfinding check — backward compat for all existing Unit::new() callers |
| PackedInt32Array 7-tuple for get_unit_data() | Phase 4, 04-02 | id/col/row/faction/hp/moved/attacked; GDScript loops in steps of 7 |
| Copy UnitDef stats into Unit at spawn time | Phase 3, 03-03 | place_unit_at() enriches Unit before insertion; apply_action() stays registry-free |
| Attack branch before reachable-move in _input() | Phase 3, 03-03 | Enemy click = attack; reachable click = move; no silent move-to-occupied hex |
| Board.healing_map cached at set_terrain_at() | Phase 4, 04-02 | EndTurn healing needs no registry access |
| Unit carries resistances map | Phase 4, 04-03 | Copied from UnitDef at spawn; combat resistance lookup registry-free |
| get_terrain_at() bridge: Rust is terrain source of truth | Phase 4, 04-04 | _draw() queries Rust per hex; new terrain types need zero GDScript changes |
| Village always heals (no ownership/capture) | Phase 4, 04-04 | Simpler; capture mechanic deferred to future |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1, 01-01 | S | Future milestone |
| Skirmisher flag on Unit | Phase 2, 02-05 | S | Future |
| Multi-strike retaliation cap (1 round) | Phase 4, 04-01 | S | Future |
| No recruitment / gold / castle system | Phase 3 | L | Future milestone |
| No visual "already moved" indicator | Phase 4, 04-01 | S | Future |
| Ranged attack range check | Deferred | M | Future |
| Movement/attack animations | Phase 4 | M | Future milestone |
| Village capture/ownership mechanic | Phase 4, 04-04 | M | Future |

### Blockers/Concerns
None.

### Git State
Last commit: 6e0f8a8 — feat(04-game-loop-polish): complete game loop with combat, healing, HUD, and villages
Branch: master

## Session Continuity

Last session: 2026-02-28
Stopped at: Phase 4 complete — all 4 plans unified; ready to plan Phase 5
Next action: /paul:plan for Phase 5 (AI Hooks & External APIs)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
