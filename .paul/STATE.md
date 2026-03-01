# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-28)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v0.4 — AI Opponent

## Current Position

Milestone: v0.4 AI Opponent
Phase: Not started
Plan: Not started
Status: Ready to plan
Last activity: 2026-02-28 — v0.3 complete, milestone transition to v0.4

Progress:
- Milestone v0.3: [██████████] 100% ✅
- Milestone v0.4: [░░░░░░░░░░] 0%

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [v0.3 complete — ready for v0.4 Phase 1 PLAN]
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
| int() cast on all JSON numeric fields in GDScript | Phase 9 | Redot JSON returns floats; int() required for display + comparison |
| draw_arc() for advancement ring; draw_polyline() for hex outlines | Phase 9 | Visually distinct unit-level vs hex-level ring layers |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1 | S | v0.4+ |
| No recruitment / gold / castle system | Phase 3 | L | v0.4+ |
| Movement/attack animations | Phase 4 | M | v0.4+ |
| Village capture/ownership mechanic | Phase 4 | M | v0.4+ |
| Socket/TCP server for external Python agents | Phase 5 | M | v0.4+ |
| 'A' key advancement requires unit selected — no UI hint | Phase 9 | S | v0.4+ |

### Blockers/Concerns
None.

### Git State
Last commit: 985f2b9 — feat(08-xp-advancement-logic): XP gain, advance_unit(), apply_advance() bridge
Branch: master
Pending: feat(09-advancement-presentation) commit

## Session Continuity

Last session: 2026-02-28
Stopped at: v0.3 complete — v0.4 AI Opponent milestone transition done
Next action: /paul:plan for v0.4 Phase 1 (Greedy AI Opponent)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
