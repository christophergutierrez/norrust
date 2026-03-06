# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.9 UI Polish — Complete!

## Current Position

Milestone: v1.9 UI Polish
Phase: 53 of 53 (Viewport Clipping)
Plan: 53-01 complete
Status: Milestone complete
Last activity: 2026-03-05 — Phase 53 complete, v1.9 milestone done

Progress:
- v1.9 UI Polish: [██████████] 100% (3/3 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone done]
```

## What Happened This Session

1. v1.8 Movement & Animation Polish milestone completed (prior session)
2. v1.9 UI Polish milestone created (3 phases)
3. Phase 51 Fullscreen & Faction Order — complete
   - love.window.maximize() on launch
   - Alphabetical faction sorting (Elves, Loyalists, Orcs)
4. Phase 52 Board Zoom — complete
   - Scroll wheel zoom 0.5x-3.0x
   - Zoom-aware click, pan, camera lerp
   - Combat preview ToD damage fix
5. Phase 53 Viewport Clipping — complete
   - Scissor clip at right panel edge
   - Click guard for panel region

## Next Action

Run `/paul:discuss-milestone` for next milestone

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| love.window.maximize() instead of desktop fullscreen | Phase 51 | Keeps title bar X close button |
| table.sort factions by name after engine load | Phase 51 | Consistent alphabetical order |
| translate→scale→translate zoom transform | Phase 52 | Clean board-space zoom composing with pan |
| damage_per_hit includes ToD modifier | Phase 52 | Fixes display inconsistency in combat preview |
| setScissor in pixel coords for board clipping | Phase 53 | Correct clipping regardless of UI_SCALE |
| Single click guard at top of mousepressed | Phase 53 | Covers all click paths with one check |

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
| Combat preview should label ToD modifier on damage display | Phase 52 | S | future |

### Blockers/Concerns
None.

### Git State
Last commit: a0a15b2 (Phase 52 — Board Zoom + combat preview fix)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: v1.9 milestone complete
Next action: /paul:discuss-milestone for next milestone
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
