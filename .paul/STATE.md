# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v2.0 Dialogue System

## Current Position

Milestone: v2.0 Dialogue System
Phase: 57 of 57 (Gameplay Triggers)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 56 complete, transitioned to Phase 57

Progress:
- v2.0 Dialogue System: [#######░░░] 75% (3/4 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for next PLAN]
```

## What Happened This Session

1. v1.9 UI Polish milestone completed (prior session)
2. Analyzed Wesnoth "Battle Training" campaign for reference
3. Discussed dialogue system: narrator-only, scenario-scoped, non-blocking
4. v2.0 Dialogue System milestone created (4 phases)
5. Phase 54 Dialogue Data & Engine — complete
   - dialogue.rs: TOML schema, loader, one-shot runtime
   - FFI: norrust_load_dialogue + norrust_get_dialogue
   - 7 new tests, 104 total passing
6. Phase 55 Dialogue Display — complete
   - Lua FFI wrappers in norrust.lua
   - Narrator panel in draw.lua with word wrapping
   - Triggers at scenario_start, turn_start, turn_end
7. Phase 56 Dialogue History — complete
   - H key toggles scrollable history panel
   - Accumulates all triggered dialogue per scenario
   - Newest-first with turn labels

## Next Action

Run `/paul:plan` for Phase 57 (Gameplay Triggers)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Dialogue tied to scenario (not units) | Discussion | Clean separation; dialogue files per scenario |
| Narrator voice only (no named characters) | Discussion | Scalable; no per-character assets needed |
| Auto-clear on turn change | Discussion | Reduces clutter; history log preserves access |
| DialogueState per-scenario (not Registry) | Phase 54 | Loaded/reset per scenario; simpler than global registry |
| One-shot via HashSet fired IDs | Phase 54 | Simple tracking; reset clears for restart |
| FFI returns JSON array of {id, text} | Phase 54 | Minimal payload; client decides rendering |
| Dialogue path derived from board filename | Phase 55 | board.toml → board_dialogue.toml; no config needed |
| Narrator panel lowest priority in chain | Phase 55 | Hidden by combat/recruit/unit/terrain panels |
| turn_end fires before engine end_turn | Phase 55 | Captures ending turn/faction before state advances |
| History newest-first rendering | Phase 56 | Quick access to recent dialogue |
| History panel highest priority overlay | Phase 56 | Shows above all other panels when toggled |

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
Last commit: 32b2b88 feat(55-dialogue-display): narrator panel with turn-boundary triggers
Branch: master
Tests: 104 passing (66 unit + 8 campaign + 3 dialogue + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 56 complete, ready to plan Phase 57
Next action: /paul:plan for Phase 57
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
