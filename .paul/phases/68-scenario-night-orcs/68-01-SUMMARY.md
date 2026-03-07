---
phase: 68-scenario-night-orcs
plan: 01
type: summary
---

## What Was Built

"Night Orcs" scenario — 3rd campaign scenario featuring a large night-themed board against an orc faction:

- **night_orcs.toml** — 20x12 board with swamp_water/forest/hills terrain, villages, two keeps
- **night_orcs_units.toml** — Blue (Loyalists): Lieutenant + Spearman + Bowman; Red (Orcs): Orcish Warrior leader + Grunt + Archer + Assassin; 3 trigger zones spawning 5 orc reinforcements
- **night_orcs_dialogue.toml** — 6 dialogue entries: intro warning about night danger, nightfall/dawn ToD alerts, midpoint marker, leader attack prompt, late-game urgency
- **Campaign extended** — tutorial.toml now has 3 scenarios (crossing → ambush → night orcs)
- **Scenario list updated** — "Night Orcs (20x12)" selectable from main menu

## Acceptance Criteria Results

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | Board loads and is playable (20x12, both keeps) | PASS |
| AC-2 | Orc chaotic alignment + night ToD bonus + dialogue | PASS |
| AC-3 | Scenario features poison and leadership mechanics | PASS |
| AC-4 | Tutorial campaign extended to 3 scenarios | PASS |
| AC-5 | Trigger zones spawn orc reinforcements | PASS |

## Files Modified

- `scenarios/night_orcs.toml` — NEW: 20x12 board
- `scenarios/night_orcs_units.toml` — NEW: units + 3 trigger zones
- `scenarios/night_orcs_dialogue.toml` — NEW: 6 dialogue entries
- `campaigns/tutorial.toml` — added 3rd scenario entry
- `norrust_love/main.lua` — added Night Orcs to SCENARIOS list
- `norrust_core/src/campaign.rs` — updated test assertion (2 → 3 scenarios)
- `norrust_core/tests/campaign.rs` — updated integration test assertion (2 → 3 scenarios)

## Tests

- 83 Rust lib + 8 campaign + 3 scenario validation + all integration tests passing (121 total)
- luajit syntax check: clean

## Decisions

- Blue keep at (2,6), Red keep at (17,6) — wide east-west march through swamp terrain
- Orc army uses existing data/units: Orcish Warrior (leader), Grunt, Archer, Assassin
- 3 trigger zones at mid-map positions (8,4), (10,8), (13,5) for progressive reinforcements
- 30-turn limit matches crossing scenario difficulty

## Deferred Issues

None.
