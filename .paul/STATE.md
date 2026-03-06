# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.9 UI Polish — viewport clipping (fullscreen, faction order, zoom done)

## Current Position

Milestone: v1.9 UI Polish
Phase: 53 of 53 (Viewport Clipping)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 52 complete, transitioned to Phase 53

Progress:
- v1.9 UI Polish: [██████░░░░] 67% (2/3 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for Phase 53 PLAN]
```

## What Happened This Session

1. v1.8 Movement & Animation Polish milestone completed
2. Discussed v1.9 UI Polish milestone scope
3. v1.9 milestone created with 3 phases

## Next Action

Run `/paul:plan` for Phase 51 (Fullscreen & Faction Order)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| love.window.maximize() instead of desktop fullscreen | Phase 51 | Keeps title bar X close button |
| table.sort factions by name after engine load | Phase 51 | Consistent alphabetical order |
| translate→scale→translate zoom transform | Phase 52 | Clean board-space zoom composing with pan |
| damage_per_hit includes ToD modifier | Phase 52 | Fixes display inconsistency in combat preview |

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
Last commit: 8c7c9db (Phase 51 — Fullscreen & Faction Order)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 52 complete, ready to plan Phase 53
Next action: /paul:plan for Phase 53
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
