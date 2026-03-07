---
phase: 65-weapon-specials
plan: 01
type: summary
---

## What Was Built

6 weapon specials and 2 status effects implemented in the Rust combat engine:

- **Drain** — attacker heals for damage dealt (capped at max_hp)
- **Poison** — defender becomes poisoned on hit; takes 8 damage/turn on EndTurn; cured at villages
- **Charge** — doubles melee damage for both attacker and defender retaliation
- **Backstab** — doubles damage when an ally occupies the opposite hex (flanking)
- **Slow** — defender becomes slowed on hit; halves movement and damage; cleared at start of faction turn
- **First strike** — no-op (engine already resolves attacker strikes before retaliation)

Status effects (poisoned, slowed) tracked on Unit struct, exposed via UnitSnapshot, and applied in EndTurn resolution.

## Acceptance Criteria Results

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | Drain heals attacker for damage dealt | PASS |
| AC-2 | Poison applies DoT and is cured at villages | PASS |
| AC-3 | Charge doubles damage both ways | PASS |
| AC-4 | Backstab doubles damage when flanked | PASS |
| AC-5 | Slow halves movement and damage next turn | PASS |
| AC-6 | First strike — no-op marker | PASS |
| AC-7 | Status effects in snapshot and cleared properly | PASS |

## Files Modified

- `norrust_core/src/unit.rs` — added poisoned/slowed fields to Unit, has_special() helper, clear on advance
- `norrust_core/src/schema.rs` — updated AttackDef.specials comment
- `norrust_core/src/snapshot.rs` — added poisoned/slowed to UnitSnapshot
- `norrust_core/src/game_state.rs` — specials in Attack handler (drain/poison/charge/backstab/slow), EndTurn poison tick + slow clear, slowed movement halving in Move
- `norrust_core/src/combat.rs` — charge/backstab/slow modifiers in simulate_combat, flanked parameter
- `norrust_core/src/ffi.rs` — slowed movement in reachable_hexes, backstab flanking in combat preview
- `norrust_core/src/ai.rs` — slowed movement halving in AI pathfinding

## Tests Added (9)

1. test_drain_heals_attacker
2. test_poison_applies_on_hit
3. test_poison_damage_on_endturn
4. test_poison_cured_at_village
5. test_charge_doubles_damage
6. test_backstab_doubles_when_flanked
7. test_slow_halves_movement
8. test_slow_halves_damage
9. test_slow_cleared_on_turn_start

## Test Results

- 77 Rust tests passing (68 existing + 9 new)
- cargo build --release: 0 warnings

## Decisions

- Poison ticks for the ending faction (before faction flip), slow clears for the newly active faction (after flip)
- Charge doubles retaliation damage using the attacker's charge special (not the defender's weapon)
- Backstab flanking checks for any ally (same faction as attacker, not the attacker itself) on the opposite hex

## Deferred Issues

None.
