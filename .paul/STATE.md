# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v0.2 — Bridge Unification (COMPLETE)

## Current Position

Milestone: v0.2 Bridge Unification — ✅ COMPLETE
Phase: 6 of 6 (Bridge Unification) — Complete
Plan: 06-01 complete
Status: v0.2 milestone complete — ready for v0.3 planning
Last activity: 2026-02-28 — Phase 6 complete; v0.2 milestone closed

Progress:
- Milestone v0.2: [██████████] 100%
- Phase 6:        [██████████] 100%

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — v0.2 milestone done]
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
| apply_action mutates &mut GameState in place | Phase 2 | Zero-copy, simpler API; returns Result<(), ActionError> |
| Unit carries combat data (attacks, defense map) | Phase 2 | Avoids registry coupling in apply_action(Attack) |
| Board.healing_map cached at set_terrain_at() | Phase 4 | EndTurn healing needs no registry access |
| get_terrain_at() bridge: Rust is terrain source of truth | Phase 4 | _draw() queries Rust per hex |
| StateSnapshot DTO (not Serialize on GameState) | Phase 5 | Clean JSON; avoids HashMap<Hex,_> + SmallRng issues |
| #[serde(tag="action")] internally-tagged ActionRequest | Phase 5 | Idiomatic JSON for AI clients |
| -99 JSON parse error sentinel | Phase 5 | Distinct from ActionError codes -1..-7 |
| StateSnapshot JSON as sole GDScript unit data source | Phase 6 | get_unit_data/get_unit_positions removed; unit["hp"] etc. |
| get_reachable_hexes() stays PackedInt32Array + RH_* constants | Phase 6 | Coordinate pairs are minimal; JSON overhead unjustified |
| Single _parse_state() per draw/input cycle | Phase 6 | JSON parsed once; Dictionary passed to all helpers |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1 | S | v0.3+ |
| No recruitment / gold / castle system | Phase 3 | L | v0.3+ |
| Movement/attack animations | Phase 4 | M | v0.3+ |
| Village capture/ownership mechanic | Phase 4 | M | v0.3+ |
| Socket/TCP server for external Python agents | Phase 5 | M | v0.3+ |

### Blockers/Concerns
None.

### Git State
Last commit: (pending — phase commit below)
Branch: master

## Session Continuity

Last session: 2026-02-28
Stopped at: v0.2 milestone complete — all phases unified
Next action: /paul:discuss-milestone or /paul:milestone for v0.3
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
