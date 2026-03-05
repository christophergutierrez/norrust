# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-03-05)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** v1.7 Enhanced Unit Sprites — COMPLETE

## Current Position

Milestone: v1.7 Enhanced Unit Sprites — COMPLETE
Phase: 47 of 47 (Polish & Verification) — Complete
Plan: 47-01 complete
Status: Milestone complete, ready for next milestone
Last activity: 2026-03-05 — Phase 47 complete, v1.7 milestone done

Progress:
- v1.7 Enhanced Unit Sprites: [██████████] 100% (4/4 phases)

## Loop Position

```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Loop complete — milestone done]
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
3. Phase 47 Polish & Verification — complete
   - Removed obsolete generate_sprites.lua (862 lines)
   - Fixed call_call_load_campaign_scenario bug
   - Added faction-based unit facing
   - Added combat animations (attack-melee, attack-ranged, defend, death)
   - Added ranged attack support in ghost movement
   - Human verified in-game and viewer

## Next Action

v1.7 milestone complete. Run `/paul:discuss-milestone` or `/paul:milestone` for v1.8.

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
| Faction-based facing (faction 0→right, 1→left) | Phase 47 | Chess-style consistent direction |
| pending_anims timer for combat animation return | Phase 47 | Non-blocking, auto-return to idle |
| hex.distance() for ranged attack range | Phase 47 | Enables melee+ranged ghost targeting |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| Village capture/ownership mechanic | Phase 4 | M | future |
| Socket/TCP server for external Python agents | Phase 5 | M | future |
| 'A' key advancement requires unit selected — no UI hint | Phase 9 | S | future |
| Some advances_to chains reference units not in registry | Phase 13 | S | future |
| AI scorer uses unit.defense map only — no tile fallback | Phase 19 | S | v1.8+ |
| AGENT_GUIDE.md placeholder needs content | Phase 31 | M | future |
| Spearman sprite faces backward (art issue) | Phase 47 | S | v1.8+ |
| Movement interpolation (smooth unit movement) | Phase 4 | M | v1.8+ |

### Blockers/Concerns
None.

### Git State
Last commit: 3baec6d (Phase 47 Polish & Verification — v1.7 complete)
Branch: master
Tests: 97 passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

## Session Continuity

Last session: 2026-03-05
Stopped at: v1.7 milestone complete
Next action: /paul:discuss-milestone or /paul:milestone for v1.8
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
