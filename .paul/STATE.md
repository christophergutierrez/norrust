# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** Phase 4 — The Game Loop & Polish

## Current Position

Milestone: v0.1 Initial Release
Phase: 4 of 5 (The Game Loop & Polish) — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-28 — Phase 3 complete, transitioned to Phase 4

Progress:
- Milestone: [██████████░░░░░] 60%
- Phase 4:   [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for PLAN — Phase 4 not started]
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
| PackedInt32Array 5-tuple for get_unit_data() | Phase 3, 03-03 | id/col/row/faction/hp per unit; GDScript loops in steps of 5 |
| Copy UnitDef stats into Unit at spawn time | Phase 3, 03-03 | place_unit_at() enriches Unit before insertion; apply_action() stays registry-free |
| Attack branch before reachable-move in _input() | Phase 3, 03-03 | Enemy click = attack; reachable click = move; no silent move-to-occupied hex |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1, 01-01 | S | Before Phase 4 recruitment |
| Defender retaliation not implemented | Phase 2, 02-04 | M | Phase 4 (bidirectional combat) |
| Resistance modifiers not applied | Phase 2, 02-04 | S | Phase 4 |
| Skirmisher flag on Unit | Phase 2, 02-05 | S | Phase 4 |
| Attack adjacency not enforced | Phase 3, 03-03 | S | Phase 4 |
| No win/loss condition detection | Phase 3, 03-03 | M | Phase 4 |

### Blockers/Concerns
None.

### Git State
Last commit: 4f669e6 — feat(01-foundation): data schemas, GDExtension bridge, end-to-end data flow
Branch: master
Note: Phase 2 + Phase 3 work uncommitted — commit before starting Phase 4

## Session Continuity

Last session: 2026-02-28
Stopped at: Phase 3 complete — unit display + action dispatch human-verified
Next action: Commit Phase 2+3 work, then /paul:plan for Phase 4
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
