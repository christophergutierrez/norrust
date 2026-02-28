# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v0.1 COMPLETE — all 5 phases shipped

## Current Position

Milestone: v0.1 Initial Release — ✅ COMPLETE
Phase: 5 of 5 (AI Hooks & External APIs) — Complete
Plan: 05-01 unified
Status: Milestone complete — ready for v0.2 planning
Last activity: 2026-02-28 — Phase 5 complete, v0.1 milestone closed

Progress:
- Milestone: [████████████████████] 100%
- Phase 5:   [████████████████████] 100%

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [v0.1 milestone complete]
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
| Cubic hex coordinates (x+y+z=0) as canonical type | Phase 2 | All hex math internal; offset only at I/O boundaries |
| Odd-r offset (pointy-top) for Board/map | Phase 2 | Matches Wesnoth map convention |
| Unit instance (Unit) separate from blueprint (UnitDef) | Phase 2 | GameState owns runtime Unit; def_id string links to Registry at lookup time |
| apply_action mutates &mut GameState in place | Phase 2 | Zero-copy, simpler API; returns Result<(), ActionError> |
| 99 = impassable movement cost convention | Phase 2 | Matches UnitDef.movement_costs schema; skip terrain with cost >= 99 |
| Unit carries combat data (attacks, defense map) | Phase 2 | Avoids registry coupling in apply_action(Attack); caller copies from UnitDef at spawn |
| PackedInt32Array 7-tuple for get_unit_data() | Phase 4 | id/col/row/faction/hp/moved/attacked; GDScript loops in steps of 7 |
| Copy UnitDef stats into Unit at spawn time | Phase 3 | place_unit_at() enriches Unit before insertion; apply_action() stays registry-free |
| Board.healing_map cached at set_terrain_at() | Phase 4 | EndTurn healing needs no registry access |
| Unit carries resistances map | Phase 4 | Copied from UnitDef at spawn; combat resistance lookup registry-free |
| get_terrain_at() bridge: Rust is terrain source of truth | Phase 4 | _draw() queries Rust per hex; new terrain types need zero GDScript changes |
| StateSnapshot DTO (not Serialize on GameState) | Phase 5 | GameState has HashMap<Hex,_> + SmallRng — neither serializes cleanly via derive |
| #[serde(tag="action")] internally-tagged ActionRequest | Phase 5 | Idiomatic JSON for AI clients; human-readable discriminated union |
| -99 JSON parse error sentinel | Phase 5 | Distinct from ActionError codes -1..-7; AI clients can distinguish bad JSON from rejected actions |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1 | S | v0.2 |
| Skirmisher flag on Unit | Phase 2 | S | v0.2 |
| No recruitment / gold / castle system | Phase 3 | L | v0.2 |
| Movement/attack animations | Phase 4 | M | v0.2 |
| Village capture/ownership mechanic | Phase 4 | M | v0.2 |
| Socket/TCP server for external Python agents | Phase 5 | M | v0.2 |

### Blockers/Concerns
None.

### Git State
Last commit: 6962b46 — docs(paul): update STATE.md with phase 4 commit hash
Phase 5 work: uncommitted (snapshot.rs, gdext_node.rs, Cargo.toml changes)
Branch: master

## Session Continuity

Last session: 2026-02-28
Stopped at: v0.1 milestone complete — all 5 phases unified
Next action: /paul:milestone to start v0.2, or /paul:discuss-milestone to explore next goals
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
