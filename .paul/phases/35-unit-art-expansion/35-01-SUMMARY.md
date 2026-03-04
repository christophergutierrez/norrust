---
phase: 35-unit-art-expansion
plan: 01
type: summary
---

## What Was Built

Programmatic sprites for all 16 priority units (Spearman + 15 new) across 3 factions:

- **Loyalists** (7): Spearman, Lieutenant, Bowman, Cavalryman, Mage, Heavy Infantryman, Sergeant
- **Elves** (5): Elvish Captain, Elvish Fighter, Elvish Archer, Elvish Scout, Elvish Shaman
- **Orcs** (4): Orcish Warrior, Orcish Grunt, Orcish Archer, Orcish Assassin

Generic humanoid drawing system with:
- 7 weapon drawing functions (spear, sword, greatsword, bow, staff, mace, dagger, crossbow)
- Configurable body scale, colors, weapon per unit
- Per-animation weapon override (melee_config/ranged_config) for dual-weapon units
- Shared animation frame factories (idle, defend, death) + weapon-specific factories (swing, thrust, draw, throw, cast, crossbow)

## Files Modified

| File | Change |
|------|--------|
| `norrust_love/generate_sprites.lua` | REWRITTEN — generic humanoid system + 16 unit definitions (~530 lines) |
| `norrust_love/assets/units/*/sprite.toml` | 15 NEW sprite.toml files (Spearman unchanged) |
| `norrust_love/assets/units/*/*.png` | 92 PNGs total (86 new + 6 existing Spearman) |

## Acceptance Criteria Results

| AC | Result | Notes |
|----|--------|-------|
| AC-1: All Priority Units Have Sprites | Pass | 16 directories, 92 PNGs, 16 sprite.toml files |
| AC-2: Visual Distinction | Pass | Unique colors/weapons/scale per unit; faction cohesion |
| AC-3: Animations Play Correctly | Pass | All states cycle in viewer with correct frames/FPS |
| AC-4: In-Game Rendering | Pass | Units render with sprites in all scenarios |
| AC-5: Spearman Unchanged | Pass | Same config produces identical output |

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Generic draw_humanoid() with config table | Eliminates per-unit draw functions; config-driven |
| melee_config/ranged_config overrides | Units like Bowman use sword for melee, bow for ranged |
| 8 weapon draw functions + 8 portrait variants | Covers all Wesnoth weapon types in priority units |
| Shared idle/defend/death frames, weapon-specific attack frames | Reduces duplication while keeping distinct combat feel |
| 16 units (not 15) — included Elvish Captain | Leader for elves faction; needed for complete coverage |

## Verification

- [x] `love . --generate-sprites` generates 92 files for 16 units
- [x] 16 directories under assets/units/ with sprite.toml + PNGs
- [x] `love . --viewer` shows all 16 units with correct animations
- [x] `love .` runs the game with sprite art for all spawnable units
- [x] `cargo test` — 94 tests passing
- [x] `luajit -bl generate_sprites.lua /dev/null` — no syntax errors
- [x] Human verification: approved

## Deferred Issues

None.
