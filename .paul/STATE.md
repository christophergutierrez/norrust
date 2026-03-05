# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.7 Enhanced Unit Sprites

## Current Position

Milestone: v1.7 Enhanced Unit Sprites
Phase: 46 of 47 (Full Unit Generation)
Plan: Not started
Status: Ready to plan
Last activity: 2026-03-05 — Phase 45 complete, transitioned to Phase 46

Progress:
- v1.7 Enhanced Unit Sprites: [█████░░░░░] 50% (2/4 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — ready for next PLAN]
```

## What Happened This Session

1. Phase 45 Pipeline Refinement — complete
   - Created `generate_sprites.py` production pipeline (Python 3, stdlib only)
   - Defined prompts for all 16 units in `unit_prompts.toml`
   - Re-generated Mage sprites via pipeline, all 6 files verified
   - Fixed viewer duplicate issue: stale Love2D save directory cleared
2. Key finding: Love2D save dir (`~/.local/share/love/norrust_love/`) merges with game dir via `getDirectoryItems`, causing ghost assets from `generate_sprites.lua`

## Next Action

Run `/paul:plan` for Phase 46 (Full Unit Generation)

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Gemini 2.0 Flash (not MCP nana-banana) for generation | Phase 44 | Direct API calls; MCP tool doesn't generate actual images |
| Flood-fill background removal (not global color replace) | Phase 44 | Corner flood-fill preserves interior detail; fuzz 20% general, 8% portraits |
| White background prompts (not green screen) | Phase 44 | AI generates inconsistent green; white more reliable for flood-fill |
| 256×256 frame format preserved | v1.7 scope | Drop-in replacement, no code changes |
| Generic animation suffixes + TOML character specifics | Phase 45 | Decouples character art from animation logic |
| Per-unit portrait_fuzz in unit_prompts.toml | Phase 45 | Fine-grained control for units with white features |

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
Last commit: 448fb6a (Phase 44 Mage Pipeline — AI-generated sprites)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: Phase 45 complete, ready to plan Phase 46
Next action: /paul:plan for Phase 46 (Full Unit Generation)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
