# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.8 Movement & Animation Polish

## Current Position

Milestone: v1.8 Movement & Animation Polish
Phase: 49 of 50 (Movement Interpolation)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 48 complete, transitioned to Phase 49

Progress:
- v1.8 Movement & Animation Polish: [███░░░░░░░] 33% (1/3 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — ready for next PLAN]
```

## What Happened This Session

1. v1.7 Enhanced Unit Sprites milestone completed (Phases 44-47)
2. v1.8 Movement & Animation Polish milestone created
3. Phase 48 Ghost Path Visualization — complete
   - Added norrust_find_path FFI wrapping Rust A*
   - Ghost path computed and drawn during ghost movement
   - Human verified

## Next Action

Run `/paul:plan` for Phase 49 (Movement Interpolation)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Faction-based facing (faction 0→right, 1→left) | Phase 47 | Chess-style consistent direction |
| pending_anims timer for combat animation return | Phase 47 | Non-blocking, auto-return to idle |
| hex.distance() for ranged attack range | Phase 47 | Enables melee+ranged ghost targeting |
| Reuse existing Rust find_path A* for ghost path | Phase 48 | No new pathfinding logic |
| White semi-transparent hex fills + line for path | Phase 48 | Visually distinct from reachable/attackable |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| Village capture/ownership mechanic | Phase 4 | M | future |
| Socket/TCP server for external Python agents | Phase 5 | M | future |
| 'A' key advancement requires unit selected — no UI hint | Phase 9 | S | future |
| Some advances_to chains reference units not in registry | Phase 13 | S | future |
| AI scorer uses unit.defense map only — no tile fallback | Phase 19 | S | future |
| AGENT_GUIDE.md placeholder needs content | Phase 31 | M | future |
| Spearman sprite faces backward (art issue) | Phase 47 | S | future |

### Blockers/Concerns
None.

### Git State
Last commit: ad210e9 (Phase 47 — v1.7 complete)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 48 complete, ready to plan Phase 49
Next action: /paul:plan for Phase 49
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
