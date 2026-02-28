# Project State

## Project Reference

See: .paul/PROJECT.md (updated 2026-02-27)

**Core value:** A playable hex-based strategy game where simulation logic is strictly separated from presentation, enabling human players and AI agents to use the same clean engine.
**Current focus:** Phase 2 — The Headless Core

## Current Position

Milestone: v0.1 Initial Release
Phase: 2 of 5 (The Headless Core) — Ready to plan
Plan: Not started
Status: Ready to plan Phase 2
Last activity: 2026-02-27 — Phase 1 complete, transitioned to Phase 2

Progress:
- Milestone: [███░░░░░░░] 20%
- Phase 2:   [░░░░░░░░░░] 0%

## Loop Position

Current loop state:
```
PLAN ──▶ APPLY ──▶ UNIFY
  ✓        ✓        ✓     [Phase 1 loop closed — ready for Phase 2 PLAN]
```

## Accumulated Context

### Decisions

| Decision | Phase | Impact |
|----------|-------|--------|
| Per-file TOML layout (one entity per file) | Phase 1 | All future data follows: `data/{type}/{id}.toml` |
| Generic `Registry<T>` with `IdField` trait | Phase 1 | Reusable for factions/attacks with no new loader code |
| `crate-type = ["cdylib", "rlib"]` | Phase 1 | cdylib for Redot, rlib for cargo test — both needed |
| `bin/` copy workflow for .so | Phase 1 | After `cargo build`: `cp target/debug/libnorrust_core.so ../norrust_client/bin/` |
| Return -1 (not panic) for not-found GDScript queries | Phase 1 | GDScript has no Option; -1 = sentinel for missing data |

### Deferred Issues

| Issue | Origin | Effort | Revisit |
|-------|--------|--------|---------|
| `factions.toml` schema not designed | Phase 1, 01-01 | S | Before Phase 4 recruitment |
| Only `max_hp` exposed to GDScript | Phase 1, 01-03 | S | Phase 3 (movement_costs, defense, attacks needed) |

### Blockers/Concerns
None.

### Git State
Last commit: (none — Phase 1 commit incoming)
Branch: master

## Session Continuity

Last session: 2026-02-27
Stopped at: Phase 1 complete — all 3 plans unified, phase committed
Next action: /paul:plan for Phase 2 (The Headless Core)
Resume file: .paul/ROADMAP.md

---
*STATE.md — Updated after every significant action*
