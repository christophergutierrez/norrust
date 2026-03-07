---
phase: 69-scenario-final-battle
plan: 01
type: summary
---

## What Was Built

"Final Battle" scenario — campaign finale and largest board:

- **final_battle.toml** — 24x14 board with diverse terrain (forest, hills, mountains, swamp_water, villages)
- **final_battle_units.toml** — Blue: 4 units (Lieutenant, Spearman, Bowman, Cavalryman); Red: 5 orcs (Orcish Warrior leader, 2 Grunts, Archer, Assassin); 4 trigger zones spawning 8 reinforcements
- **final_battle_dialogue.toml** — 6 dialogue entries: campaign conclusion narrative, nightfall/dawn ToD alerts, midpoint marker, leader attack, urgency warning
- **Campaign complete** — tutorial.toml now has 4 scenarios (crossing -> ambush -> night orcs -> final battle)

## Acceptance Criteria Results

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | 24x14 board loads and is playable | PASS |
| AC-2 | Full mechanic showcase (ToD, specials, abilities, triggers) | PASS |
| AC-3 | Narrative conclusion dialogue | PASS |
| AC-4 | Tutorial campaign has 4 scenarios | PASS |
| AC-5 | All tests pass including scenario validation | PASS |

## Files Modified

- `scenarios/final_battle.toml` — NEW: 24x14 board (336 tiles)
- `scenarios/final_battle_units.toml` — NEW: 9 starting units + 4 trigger zones
- `scenarios/final_battle_dialogue.toml` — NEW: 6 dialogue entries
- `campaigns/tutorial.toml` — added 4th scenario entry
- `norrust_love/main.lua` — added Final Battle to SCENARIOS list
- `norrust_core/src/campaign.rs` — updated test assertion (3 -> 4 scenarios)
- `norrust_core/tests/campaign.rs` — updated integration test assertion (3 -> 4 scenarios)

## Tests

- 121 total Rust tests passing (lib + integration + scenario validation)
- luajit syntax check: clean

## Decisions

- Blue keep at (2,7), Red keep at (21,7) — long east-west march across diverse terrain
- 35-turn limit (longest of all scenarios)
- 4 trigger zones spread across map for progressive difficulty
- Used odd-r offset hex neighbor calculation (matching engine's Hex::from_offset) for castle placement

## Deferred Issues

None.
