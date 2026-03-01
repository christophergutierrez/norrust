# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-01)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v0.5 Unit Content — COMPLETE

## Current Position

Milestone: v0.5 Unit Content — Complete ✅
Phase: 13 of 13 (Wesnoth Data Import) — Complete
Plan: 13-01 complete
Status: Milestone v0.5 complete — ready for next milestone
Last activity: 2026-03-01 — Phase 13 complete, v0.5 Unit Content milestone delivered

Progress:
- Milestone v0.5: [██████████] 100% ✅

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone v0.5 closed]
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
| Greedy AI (N=0): expected-damage scorer + kill bonus ×3 | Phase 10 | Analytic, deterministic, no RNG rollouts; same apply_action API |
| ai_take_turn() pure Rust in ai.rs; bridge in Phase 11 | Phase 10 | AI is a caller of apply_action — registry-free, testable headlessly |
| Uniform grassland in AI-vs-AI test (not checkerboard) | Phase 10 | Checkerboard (forest=2) with movement=5 prevents first-turn engagement |
| March via min_by_key(distance to nearest enemy) over candidates | Phase 11 | Reuses ZOC-filtered reachable hexes; no extra pathfinding; march respects ZOC |
| GDScript AI trigger checks active_faction after end_turn() | Phase 11 | ai_take_turn() includes EndTurn; checking faction after player's EndTurn is cleanest trigger |
| #[derive(Default)] on AttackDef and UnitDef | Phase 12 | ..Default::default() in test constructions; future fields need 1 line per test file |
| "neutral" alignment maps to Liminal (same ToD modifier) | Phase 12 | Neutral variant deferred; parse_alignment() is the single string→Alignment boundary |
| parse_alignment() as pub fn in unit.rs | Phase 12 | Single conversion point used by place_unit_at() and advance_unit() |
| parse_value() uses [^"]* (first-quote match) in WML scraper | Phase 13 | Avoids capturing WML inline comments after closing "; greedy .* caused 7 malformed TOMLs |
| Denormalized unit TOMLs from scraper (no MovetypeDef registry) | Phase 13 | Keeps loader simple; movement_costs/defense/resistances inlined per unit |
| Registry tests use >= N count assertions | Phase 13 | Hardcoded == 4/== 3 broke with 322-file data dir; >= N survives data growth |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1 | S | v0.6+ |
| No recruitment / gold / castle system | Phase 3 | L | v0.6+ |
| Movement/attack animations | Phase 4 | M | v0.6+ |
| Village capture/ownership mechanic | Phase 4 | M | v0.6+ |
| Socket/TCP server for external Python agents | Phase 5 | M | v0.6+ |
| 'A' key advancement requires unit selected — no UI hint | Phase 9 | S | v0.6+ |
| Scraped terrain IDs (flat/hills/etc.) don't match board terrain IDs (grassland/forest/village) | Phase 13 | M | v0.6+ |
| Some advances_to chains reference units not in registry (skipped for no-attacks/template) | Phase 13 | S | v0.6+ |

### Blockers/Concerns
None.

### Git State
Last commit: bc70f14 — feat(13-wesnoth-data-import): Python WML scraper, 318 unit TOMLs, 11 terrain TOMLs
Branch: master
Feature branches merged: none

## Session Continuity

Last session: 2026-03-01
Stopped at: v0.5 Unit Content milestone complete — Phase 13 UNIFY done
Next action: /paul:discuss-milestone or /paul:milestone for v0.6
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
