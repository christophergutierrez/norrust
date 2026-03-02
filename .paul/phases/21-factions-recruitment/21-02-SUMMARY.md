---
phase: 21-factions-recruitment
plan: 02
subsystem: recruitment
tags: [rust, recruit, gold, castle, gdscript, action]

requires:
  - phase: 21-01
    provides: state.gold set from FactionDef.starting_gold; faction recruits available via bridge

provides:
  - apply_recruit() pure Rust function (testable headlessly)
  - ActionError::NotEnoughGold + ActionError::DestinationNotCastle
  - recruit_unit_at() bridge (GDScript + JSON API)
  - ActionRequest::Recruit for JSON AI clients
  - get_unit_cost() bridge for UI display
  - Castle hexes in contested.toml (col 0 + col 7, 5 each)
  - GDScript 'R' key recruit panel with castle hex highlighting

affects: []

tech-stack:
  added: []
  patterns:
    - apply_recruit() free function — same registry-free testable pattern as advance_unit()
    - ActionRequest::Recruit intercepted in apply_action_json() — same as Advance
    - recruit_unit_at() reuses place_unit_at() stat-copy pattern

key-files:
  modified:
    - norrust_core/src/game_state.rs
    - norrust_core/src/snapshot.rs
    - norrust_core/src/gdext_node.rs
    - norrust_client/scripts/game.gd
    - scenarios/contested.toml
    - norrust_core/tests/simulation.rs

key-decisions:
  - "No Action::Recruit variant — free function + bridge intercept (Advance pattern)"
  - "apply_recruit takes cost as parameter — registry-free, Unit pre-built by bridge"
  - "col 0 + col 7 all rows = castle — 5 hexes per faction, aligns with leader spawn zones"
  - "Error codes -8 (NotEnoughGold), -9 (DestinationNotCastle) extending -1..-7 range"
  - "Recruit exits mode after one placement — R again to recruit another unit"

patterns-established:
  - "action_err_code() is the single dispatch point for all ActionError → i32 mappings"

duration: ~25min
started: 2026-03-02T00:00:00Z
completed: 2026-03-02T00:00:00Z
---

# Phase 21 Plan 02: Action::Recruit + Castle + GDScript 'R' Key Summary

**Recruitment fully wired: pure Rust gold-guarded apply_recruit(), bridge + JSON API, 'R' key UI.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~25 min |
| Tasks | 6 completed |
| Files modified | 6 |
| Tests before | 66 |
| Tests after | 69 |
| Bug fix during apply | 1 (non-exhaustive match in From<ActionRequest>; unreachable! arm added) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: apply_recruit deducts gold and places unit on castle hex | Pass | test_recruit_deducts_gold: 50→36 after cost=14 |
| AC-2: apply_recruit returns NotEnoughGold when broke | Pass | test_recruit_fails_not_enough_gold |
| AC-3: apply_recruit returns DestinationNotCastle for non-castle hex | Pass | test_recruit_fails_not_castle_hex |
| AC-4: contested.toml has castle tiles at col 0 and col 7 | Pass | test_load_board_from_file updated + passes |
| AC-5: 'R' key opens recruit panel; click places unit and deducts gold | Pass | code review |
| AC-6: All existing tests pass | Pass | 69 tests (55 lib + 14 integration) |

## Accomplishments

- `ActionError::NotEnoughGold` + `ActionError::DestinationNotCastle` — extend enum, no breaking change
- `apply_recruit(state, unit, destination, cost)` — pure Rust, registry-free, headlessly testable
- `ActionRequest::Recruit { unit_id, def_id, col, row }` — JSON API path for AI agent recruitment
- `action_err_code()` extended to cover -8 and -9 (exhaustive match)
- `recruit_unit_at(unit_id, def_id, col, row)` bridge — uses active_faction, same stat-copy pattern as place_unit_at()
- `get_unit_cost(def_id)` bridge — GDScript reads cost for UI label display
- `scenarios/contested.toml` — col 0 + col 7 become castle (5 hexes each); col 1 and 6 remain flat corridors
- GDScript: `_recruit_mode` flag, 'R' key toggle, `_draw_recruit_panel()` with castle hex teal overlay + sidebar, 1-9 key palette selection, click-to-recruit handler

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/game_state.rs` | NotEnoughGold + DestinationNotCastle in ActionError; apply_recruit() | Core logic |
| `norrust_core/src/snapshot.rs` | ActionRequest::Recruit variant + unreachable!() arm | JSON API |
| `norrust_core/src/gdext_node.rs` | action_err_code() -8/-9; recruit_unit_at(); get_unit_cost(); Recruit intercept | Bridge |
| `norrust_client/scripts/game.gd` | _recruit_mode vars; _draw_recruit_panel(); 'R' key; click handler | UI |
| `scenarios/contested.toml` | Col 0 + col 7 flat→castle | Scenario data |
| `norrust_core/tests/simulation.rs` | 3 recruit tests + test_load_board_from_file updated for castle | Verification |

## Fix During Apply

**Non-exhaustive match** in `From<ActionRequest> for Action`:
- Added `ActionRequest::Recruit { .. } => unreachable!("...")` arm, same pattern as Advance

**test_load_board_from_file** asserted all of cols 0-1, 6-7 were flat. Updated to:
- cols 0 + 7 → "castle"
- cols 1 + 6 → "flat"

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| No `Action::Recruit` enum variant | Advance pattern: bridge-intercepted, registry access needed | apply_action() stays registry-free |
| Recruit exits mode after one placement | Simpler UX — R again to recruit another | Less state to manage |
| Castle validity = terrain_id == "castle" | No leader adjacency check — keep simple | Any castle hex is valid for any faction |

## Deviations from Plan

None — executed exactly as specified, plus one anticipated fix (exhaustive match).

## Phase 21 Complete

Both plans delivered:
- 21-01: FactionDef.starting_gold wired at game start
- 21-02: Full recruitment loop — validate, spend gold, place unit

**v0.9 Game Mechanics is now complete.**

---
*Phase: 21-factions-recruitment, Plan: 02*
*Completed: 2026-03-02*
