---
phase: 20-gold-economy
plan: 01
subsystem: economy
tags: [rust, gold, economy, village, income, snapshot, hud, gdscript]

requires:
  - phase: 14-tile-runtime
    provides: village_owners HashMap already tracked in GameState at EndTurn

provides:
  - GameState.gold [u32; 2] per-faction gold counter with starting value 10
  - EndTurn village income: 2 gold per owned village to newly-active faction
  - StateSnapshot.gold field in JSON for AI clients and GDScript
  - HUD displays active faction's gold as "Xg"

affects: [21-factions-recruitment]

tech-stack:
  added: []
  patterns: [gold indexed by faction 0/1 as array; income applied to newly-active faction on EndTurn]

key-files:
  modified:
    - norrust_core/src/game_state.rs
    - norrust_core/src/snapshot.rs
    - norrust_client/scripts/game.gd

key-decisions:
  - "gold: [u32; 2] array (not HashMap) — exactly 2 factions, array simpler than map"
  - "Income paid to newly-active faction on EndTurn — 'gold at start of turn' semantics"
  - "Starting gold hardcoded [10, 10] — Phase 21 replaces with FactionDef.starting_gold"

patterns-established:
  - "state.gold[faction as usize] for gold access; consistent with faction as u8/i8 pattern"

duration: ~5min
started: 2026-03-02T00:00:00Z
completed: 2026-03-02T00:00:00Z
---

# Phase 20 Plan 01: Gold Economy Summary

**Per-faction gold tracking wired: villages pay 2g/turn to their owner; gold in StateSnapshot JSON and HUD.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5 min |
| Tasks | 2 completed |
| Files modified | 3 |
| Tests before | 64 |
| Tests after | 65 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Starting gold 10 per faction | Pass | `GameState::new()` initializes `gold: [10, 10]` |
| AC-2: Village pays 2g per turn to owner | Pass | `test_village_income_adds_gold` verifies 10→12 after one income cycle |
| AC-3: Gold in StateSnapshot JSON | Pass | `pub gold: [u32; 2]` added to StateSnapshot; serializes via derive(Serialize) |
| AC-4: HUD shows active faction's gold | Pass | `state.get("gold")[faction]` appended to HUD string as "Xg" |

## Accomplishments

- `GameState.gold: [u32; 2]` — per-faction gold, starting at [10, 10]
- EndTurn income: after faction flip, newly-active faction earns 2g × owned village count
- `StateSnapshot.gold` — AI clients and GDScript see gold via existing JSON pipe
- HUD: "Turn 1 · Day · Blue's Turn · 10g" — gold visible without any new bridge methods

## Files Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/game_state.rs` | Modified + test added | gold field, EndTurn income, test_village_income_adds_gold |
| `norrust_core/src/snapshot.rs` | Modified | gold field in StateSnapshot |
| `norrust_client/scripts/game.gd` | Modified | HUD gold display |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `[u32; 2]` array not `HashMap<u8, u32>` | Exactly 2 factions always; array cheaper and cleaner | Phase 21 reads `state.gold[faction]` directly |
| Income on newly-active faction's turn start | "You earn gold when your turn begins" semantics; consistent with Wesnoth | Village captured this turn pays income next time you're active |
| Starting gold hardcoded 10 | Phase 21 replaces with FactionDef.starting_gold; avoids over-engineering now | Phase 21 will call `state.gold = [faction0.starting_gold, faction1.starting_gold]` at load time |

## Deviations from Plan

None — executed exactly as specified.

## Next Phase Readiness

**Ready:**
- `state.gold[faction]` available for Phase 21's recruitment deduction
- StateSnapshot gold gives AI clients full economic visibility
- No new bridge methods needed for Phase 21 gold reads (all via JSON)

**Concerns:** None

**Blockers:** None

---
*Phase: 20-gold-economy, Plan: 01*
*Completed: 2026-03-02*
