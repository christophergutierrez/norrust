---
phase: 66-unit-abilities
plan: 01
type: summary
---

## What Was Built

3 unit abilities implemented in Rust engine + UI indicators in Love2D:

- **Leadership** — +25% damage per level difference to adjacent lower-level allies (both attack and retaliation)
- **Regenerates** — self-heal N HP per turn from "regenerates_N" ability string, also cures poison
- **Steadfast** — doubles negative resistance values (the protective ones) when defending; weaknesses unaffected

Infrastructure:
- `level: u8` field on Unit (copied from UnitDef at spawn/advance) and UnitSnapshot
- `specials: Vec<String>` on AttackSnapshot (skip_serializing_if empty)
- `leadership_bonus()` helper function computing best adjacent leadership bonus
- Fixed misleading resistance comment (negative = resistance, positive = weakness)

UI (Love2D draw.lua):
- Green dot on unit circle when poisoned, blue dot when slowed
- Level display in unit panel
- Poisoned/Slowed status text in unit panel
- Attack specials shown in parentheses in unit panel

## Acceptance Criteria Results

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | Leadership grants +25% damage to adjacent lower-level allies | PASS |
| AC-2 | Regenerates heals per turn and cures poison | PASS |
| AC-3 | Steadfast doubles negative resistances when defending | PASS |
| AC-4 | Level field on Unit and UnitSnapshot | PASS |
| AC-5 | Status effect indicators on unit circles | PASS |

## Files Modified

- `norrust_core/src/unit.rs` — level field, fixed resistance comment
- `norrust_core/src/snapshot.rs` — level + specials on AttackSnapshot/UnitSnapshot
- `norrust_core/src/game_state.rs` — leadership_bonus(), steadfast in resistance, regenerates in EndTurn, 6 tests
- `norrust_core/src/combat.rs` — leadership/steadfast modifiers in simulate_combat
- `norrust_core/src/ffi.rs` — level from registry, leadership bonus in combat preview
- `norrust_love/draw.lua` — status dots, level/status/specials in panel

## Tests Added (6)

1. test_leadership_boosts_adjacent_lower_level
2. test_regenerates_heals_per_turn
3. test_regenerates_cures_poison
4. test_steadfast_doubles_resistance
5. test_steadfast_no_effect_on_weakness
6. test_level_on_snapshot

## Test Results

- 83 Rust tests passing (77 existing + 6 new)
- cargo build --release: 0 warnings
- luajit syntax check: clean

## Decisions

- Resistance convention: negative = resistance (less damage), positive = weakness (more damage). Fixed misleading comment.
- Steadfast doubles negative resistance values only (protective). Weaknesses (positive) unaffected.
- Regenerates stacks with village healing and cures poison unconditionally.
- Leadership bonus is pre-computed via `leadership_bonus()` helper and passed to simulate_combat for preview accuracy.

## Deferred Issues

None.
