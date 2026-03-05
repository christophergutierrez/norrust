# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.7 Enhanced Unit Sprites

## Current Position

Milestone: v1.7 Enhanced Unit Sprites
Phase: 47 of 47 (Polish & Verification)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 46 complete, transitioned to Phase 47

Progress:
- v1.7 Enhanced Unit Sprites: [███████░░░] 75% (3/4 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — ready for next PLAN]
```

## What Happened This Session

1. Phase 45 Pipeline Refinement — complete
   - Created generate_sprites.py + unit_prompts.toml (16 units)
   - Re-generated Mage, verified
   - Fixed viewer duplicates (Love2D save dir)
2. Phase 46 Full Unit Generation — complete
   - Batch-generated all 16 units (~336 API calls, ~15 min)
   - 92 PNG files, all dimensions verified
   - Human approved visual quality

## Next Action

Run `/paul:plan` for Phase 47 (Polish & Verification)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Gemini 2.0 Flash (not MCP nana-banana) for generation | Phase 44 | Direct API calls |
| Flood-fill background removal from corners | Phase 44 | Fuzz 20% general, 8% portraits |
| White background prompts for AI sprites | Phase 44 | More reliable than green screen |
| 256×256 frame format preserved | v1.7 scope | Drop-in replacement |
| Generic animation suffixes + TOML character specifics | Phase 45 | Decoupled pipeline |
| Per-unit portrait_fuzz in unit_prompts.toml | Phase 45 | Fine-grained control |
| Batch --all regenerates all units for consistency | Phase 46 | ~336 calls, ~15 min |

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
| Board-position flip is correct but may look odd with AI sprites | Phase 44 | S | v1.8+ |
| generate_sprites.lua writes stale assets to Love2D save dir | Phase 45 | S | Phase 47 |
| Love2D save dir accumulates stale dev data | Phase 45 | S | Phase 47 |

### Blockers/Concerns
None.

### Git State
Last commit: 514e5d9 (Phase 45 Pipeline Refinement)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 46 complete, ready to plan Phase 47
Next action: /paul:plan for Phase 47 (Polish & Verification)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
