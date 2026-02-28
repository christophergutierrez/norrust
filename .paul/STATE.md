# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v0.3 — Unit Advancement

## Current Position

Milestone: v0.3 Unit Advancement
Phase: 9 of 9 (Advancement Presentation) — Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-28 — Phase 8 complete, transitioned to Phase 9

Progress:
- Milestone v0.3: [██████░░░░] ~67%
- Phase 8:        [██████████] 100% ✅

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — ready for Phase 9 PLAN]
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
| #[serde(default)] on UnitDef advancement fields | Phase 7 | Existing TOML files load without modification |
| xp_needed copied at place_unit_at() from registry | Phase 7 | Runtime Unit stays registry-free; same pattern as attacks/resistances |
| advancement_pending data-only in Phase 7 | Phase 7 | Logic (set/clear) is Phase 8 work; no premature coupling |
| 1 XP/hit + 8 kill bonus; both sides earn | Phase 8 | Symmetric XP; headless sim verified 5-kill chain |
| advance_unit() free function; bridge-side registry | Phase 8 | apply_action stays registry-free; advance intercepted before into() |

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
Last commit: TBD — feat(08-xp-advancement-logic): pending phase commit
Branch: master

## Session Continuity

Last session: 2026-02-28
Stopped at: Phase 8 complete — ready to plan Phase 9
Next action: /paul:plan for Phase 9 (Advancement Presentation)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
