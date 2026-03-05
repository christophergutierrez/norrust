# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.7 Enhanced Unit Sprites

## Current Position

Milestone: v1.7 Enhanced Unit Sprites
Phase: 45 of 47 (Pipeline Refinement)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 44 complete, transitioned to Phase 45

Progress:
- v1.7 Enhanced Unit Sprites: [██░░░░░░░░] 25% (1/4 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ○        ○        ○     [Ready for next PLAN]
```

## What Happened This Session

1. Planned and executed Phase 44 (Mage Pipeline)
   - Generated 6 Mage sprite files via Gemini 2.0 Flash API
   - Built flood-fill background removal pipeline (ImageMagick)
   - Created reusable generate_ai_sprites.sh script
   - User verified in-game: "looked perfect"
2. Key finding: nana-banana MCP doesn't generate images; direct Gemini API required
3. Key finding: green screen unreliable; white bg + flood-fill works well

## Next Action

Run `/paul:plan` for Phase 45 (Pipeline Refinement)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Gemini 2.0 Flash (not MCP nana-banana) for generation | Phase 44 | Direct API calls; MCP tool doesn't generate actual images |
| Flood-fill background removal (not global color replace) | Phase 44 | Corner flood-fill preserves interior detail; fuzz 20% general, 8% portraits |
| White background prompts (not green screen) | Phase 44 | AI generates inconsistent green; white more reliable for flood-fill |
| 256×256 frame format preserved | v1.7 scope | Drop-in replacement, no code changes |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| Combat animation triggers (attack/defend/death during gameplay) | Phase 33 | M | v1.8+ |
| Village capture/ownership mechanic | Phase 4 | M | future |
| Socket/TCP server for external Python agents | Phase 5 | M | future |
| 'A' key advancement requires unit selected — no UI hint | Phase 9 | S | future |
| Some advances_to chains reference units not in registry | Phase 13 | S | future |
| AI scorer uses unit.defense map only — no tile fallback | Phase 19 | S | v1.8+ |
| AGENT_GUIDE.md placeholder needs content | Phase 31 | M | future |
| Viewer shows old/broken sprites for some units | Phase 44 | S | Phase 47 |
| Board-position flip is correct but may look odd with AI sprites | Phase 44 | S | v1.8+ |

### Blockers/Concerns
None.

### Git State
Last commit: (pending Phase 44 commit)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 44 complete, ready to plan Phase 45
Next action: /paul:plan for Phase 45 (Pipeline Refinement)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
