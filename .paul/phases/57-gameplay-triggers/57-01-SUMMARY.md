---
phase: 57-gameplay-triggers
plan: 01
subsystem: engine, presentation
tags: [dialogue, triggers, leader, hex-entry, ffi]

requires:
  - phase: 55-dialogue-display
    provides: active_dialogue rendering and append_to_history
provides:
  - leader_attacked dialogue trigger on first attack against a leader unit
  - hex_entered dialogue trigger when moving to a specific hex
  - DialogueEntry col/row optional fields for location-based filtering
affects: []

key-files:
  modified: [norrust_core/src/dialogue.rs, norrust_core/src/ffi.rs, norrust_core/tests/dialogue.rs, norrust_love/norrust.lua, norrust_love/main.lua, scenarios/crossing_dialogue.toml]

key-decisions:
  - "col/row as optional i32 on DialogueEntry — None means any hex"
  - "FFI uses -1 sentinel for 'no hex filter' — converted to None in Rust"
  - "leader_attacked checks defender abilities array for 'leader' string"
  - "hex_entered fires after move completes (post-animation)"

duration: 8min
completed: 2026-03-05
---

# Phase 57 Plan 01: Gameplay Triggers Summary

**leader_attacked and hex_entered dialogue triggers with col/row schema extension and client-side firing**

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: DialogueEntry Supports col/row Fields | Pass | Optional i32 fields with serde default |
| AC-2: get_pending Filters by col/row | Pass | test_hex_entry_filter verifies matching + non-matching |
| AC-3: leader_attacked Fires on First Leader Attack | Pass | Checks abilities array in execute_attack |
| AC-4: hex_entered Fires on Unit Movement | Pass | fire_hex_entered called from both move paths |

## Accomplishments

- DialogueEntry extended with optional col/row fields for location-based triggers
- get_pending filters by col/row when entry specifies them (None = any hex)
- FFI updated: norrust_get_dialogue takes col, row params (-1 = no filter)
- leader_attacked trigger: fires in execute_attack when defender has "leader" ability
- hex_entered trigger: fire_hex_entered helper called after move animation completes
- 2 new unit tests (test_hex_entry_filter, test_leader_attacked_trigger)
- 2 sample dialogue entries in crossing_dialogue.toml

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/dialogue.rs` | Modified | col/row fields, get_pending signature + filtering, 2 new tests |
| `norrust_core/src/ffi.rs` | Modified | col/row params on norrust_get_dialogue |
| `norrust_core/tests/dialogue.rs` | Modified | Updated FFI test calls with col/row params |
| `norrust_love/norrust.lua` | Modified | Updated cdef + wrapper for col/row |
| `norrust_love/main.lua` | Modified | leader_attacked in execute_attack, fire_hex_entered helper |
| `scenarios/crossing_dialogue.toml` | Modified | Added leader_attacked + hex_entered sample entries |

## Deviations from Plan

None — plan executed exactly as written.

## Next Phase Readiness

**Ready:** This is the final phase of v2.0 Dialogue System. All 4 phases complete. Milestone ready for closure.

**Blockers:** None

---
*Phase: 57-gameplay-triggers, Plan: 01*
*Completed: 2026-03-05*
