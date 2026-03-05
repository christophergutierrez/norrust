# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.8 Movement & Animation Polish

## Current Position

Milestone: v1.8 Movement & Animation Polish
Phase: 49 of 50 (Movement Interpolation)
Plan: 49-01 complete
Status: Phase complete
Last activity: 2026-03-05 — Phase 49 complete

Progress:
- v1.8 Movement & Animation Polish: [██████░░░░] 67% (2/3 phases)

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
4. Phase 49 Movement Interpolation — complete
   - Smooth sliding animation along A* path on commit
   - Callback-based move+attack sequencing
   - Input blocked during movement
   - Fixed pre-existing combat animation sprite lookup bug
   - Human verified

## Next Action

Run `/paul:plan` for Phase 50 (Combat Movement)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Faction-based facing (faction 0→right, 1→left) | Phase 47 | Chess-style consistent direction |
| pending_anims timer for combat animation return | Phase 47 | Non-blocking, auto-return to idle |
| hex.distance() for ranged attack range | Phase 47 | Enables melee+ranged ghost targeting |
| Reuse existing Rust find_path A* for ghost path | Phase 48 | No new pathfinding logic |
| White semi-transparent hex fills + line for path | Phase 48 | Visually distinct from reachable/attackable |
| pending_anims.move for movement anim (upvalue limit) | Phase 49 | Avoids LuaJIT 60-upvalue limit |
| Apply engine move immediately, animate rendering only | Phase 49 | Keeps engine in sync during animation |
| Callback on_complete for move+attack sequencing | Phase 49 | Clean separation of movement and follow-up |

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
Last commit: (pending — Phase 49 commit)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 49 complete, ready to plan Phase 50
Next action: /paul:plan for Phase 50
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
