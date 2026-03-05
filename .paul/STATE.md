# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.8 Movement & Animation Polish — Complete!

## Current Position

Milestone: v1.8 Movement & Animation Polish
Phase: 50 of 50 (Combat Movement)
Plan: 50-01 complete
Status: Milestone complete
Last activity: 2026-03-05 — Phase 50 complete, v1.8 milestone done

Progress:
- v1.8 Movement & Animation Polish: [██████████] 100% (3/3 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone done]
```

## What Happened This Session

1. v1.7 Enhanced Unit Sprites milestone completed (Phases 44-47)
2. v1.8 Movement & Animation Polish milestone created
3. Phase 48 Ghost Path Visualization — complete
4. Phase 49 Movement Interpolation — complete
   - Smooth sliding along A* path on commit
   - Fixed combat animation sprite lookup bug
5. Phase 50 Combat Movement — complete
   - Melee lunge animation (approach → attack → return)
   - Fixed ranged detection (hex distance vs name matching)

## Next Action

Run `/paul:discuss-milestone` for next milestone

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
| pending_anims.combat_slide with pixel coords | Phase 50 | Fractional positioning for 40% approach |
| Distance-based ranged detection via hex.distance | Phase 50 | Replaces broken attack-name check |

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
Last commit: (pending — Phase 50 commit)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: v1.8 milestone complete
Next action: /paul:discuss-milestone for next milestone
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
