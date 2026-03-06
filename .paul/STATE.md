# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v2.0 Dialogue System — COMPLETE

## Current Position

Milestone: v2.0 Dialogue System — COMPLETE
Phase: 57 of 57 (Gameplay Triggers) — Complete
Plan: 57-01 complete
Status: Milestone complete
Last activity: 2026-03-05 — Phase 57 complete, v2.0 milestone finished

Progress:
- v2.0 Dialogue System: [##########] 100% (4/4 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Milestone complete]
```

## What Happened This Session

1. v1.9 UI Polish milestone completed (prior session)
2. Analyzed Wesnoth "Battle Training" campaign for reference
3. Discussed dialogue system: narrator-only, scenario-scoped, non-blocking
4. v2.0 Dialogue System milestone created (4 phases)
5. Phase 54 Dialogue Data & Engine — complete
   - dialogue.rs: TOML schema, loader, one-shot runtime
   - FFI: norrust_load_dialogue + norrust_get_dialogue
6. Phase 55 Dialogue Display — complete
   - Lua FFI wrappers, narrator panel, turn-boundary triggers
7. Phase 56 Dialogue History — complete
   - H key toggles scrollable history panel
8. Phase 57 Gameplay Triggers — complete
   - leader_attacked + hex_entered triggers
   - DialogueEntry col/row fields for location filtering
   - 106 tests passing

## Next Action

Run `/paul:complete-milestone` or `/paul:discuss-milestone` for next milestone

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Dialogue tied to scenario (not units) | Discussion | Clean separation; dialogue files per scenario |
| Narrator voice only (no named characters) | Discussion | Scalable; no per-character assets needed |
| DialogueState per-scenario (not Registry) | Phase 54 | Loaded/reset per scenario; simpler than global registry |
| One-shot via HashSet fired IDs | Phase 54 | Simple tracking; reset clears for restart |
| FFI returns JSON array of {id, text} | Phase 54 | Minimal payload; client decides rendering |
| Dialogue path derived from board filename | Phase 55 | board.toml → board_dialogue.toml |
| Narrator panel lowest priority in chain | Phase 55 | Hidden by interactive panels |
| History panel highest priority overlay | Phase 56 | Shows above all panels when toggled |
| col/row optional i32 on DialogueEntry | Phase 57 | None = any hex; -1 FFI sentinel |
| leader_attacked checks abilities array | Phase 57 | No engine change needed; client-side |

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
Last commit: 4bd8fe8 feat(56-dialogue-history): scrollable history panel with H key toggle
Branch: master
Tests: 106 passing (68 unit + 8 campaign + 3 dialogue-ffi + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: v2.0 Dialogue System milestone complete
Next action: /paul:complete-milestone or /paul:discuss-milestone
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
