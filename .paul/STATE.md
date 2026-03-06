# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.9 UI Polish — zoom, viewport clipping (fullscreen + faction order done)

## Current Position

Milestone: v1.9 UI Polish
Phase: 52 of 53 (Board Zoom)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 51 complete, transitioned to Phase 52

Progress:
- v1.9 UI Polish: [███░░░░░░░] 33% (1/3 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for Phase 52 PLAN]
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
Last commit: b266c7d (chore: update STATE.md with commit hash)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 51 complete, ready to plan Phase 52
Next action: /paul:plan for Phase 52
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
