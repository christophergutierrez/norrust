# Unit Registry — v3.8 Unit Expansion

**Generated:** 2026-03-10
**Factions:** 4 (Loyalists, Rebels, Northerners, Undead)
**Total unique units:** 95 (Mage tree counted once, shared by Loyalists+Rebels; Wose Sapling excluded — see notes)

## Status Legend

- **dir+sprites** — has `data/units/<name>/` directory with TOML + sprite PNGs
- **toml** — has flat `data/units/<name>.toml` only (from WML scraper)
- **MISSING** — no TOML exists

## Summary Counts

| Status | Count |
|--------|-------|
| dir+sprites | 17 |
| toml | 76 |
| MISSING | 2 (walking_corpse, soulless) |
| **Total** | **95** |

---

## 1. LOYALISTS (34 units)

### Cavalryman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Cavalryman | 1 | Dragoon | dir+sprites | `cavalryman/` |
| Dragoon | 2 | Cavalier | toml | `cavalryman/dragoon/` |
| Cavalier | 3 | (terminal) | toml | `cavalryman/dragoon/cavalier/` |

### Horseman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Horseman | 1 | Knight, Lancer | toml | `horseman/` |
| Knight | 2 | Paladin, Grand Knight | toml | `horseman/knight/` |
| Paladin | 3 | (terminal) | toml | `horseman/knight/paladin/` |
| Grand Knight | 3 | (terminal) | toml | `horseman/knight/grand_knight/` |
| Lancer | 2 | (terminal) | toml | `horseman/lancer/` |

### Spearman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Spearman | 1 | Swordsman, Pikeman, Javelineer | dir+sprites | `spearman/` |
| Swordsman | 2 | Royal Guard | toml | `spearman/swordsman/` |
| Royal Guard | 3 | (terminal) | toml | `spearman/swordsman/royal_guard/` |
| Pikeman | 2 | Halberdier | toml | `spearman/pikeman/` |
| Halberdier | 3 | (terminal) | toml | `spearman/pikeman/halberdier/` |
| Javelineer | 2 | (terminal) | toml | `spearman/javelineer/` |

### Fencer Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Fencer | 1 | Duelist | toml | `fencer/` |
| Duelist | 2 | Master at Arms | toml | `fencer/duelist/` |
| Master at Arms | 3 | (terminal) | toml | `fencer/duelist/master_at_arms/` |

### Heavy Infantryman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Heavy Infantryman | 1 | Shock Trooper | dir+sprites | `heavy_infantryman/` |
| Shock Trooper | 2 | Iron Mauler | toml | `heavy_infantryman/shock_trooper/` |
| Iron Mauler | 3 | (terminal) | toml | `heavy_infantryman/shock_trooper/iron_mauler/` |

### Bowman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Bowman | 1 | Longbowman | dir+sprites | `bowman/` |
| Longbowman | 2 | Master Bowman | toml | `bowman/longbowman/` |
| Master Bowman | 3 | (terminal) | toml | `bowman/longbowman/master_bowman/` |

### Mage Line (SHARED with Rebels)
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Mage | 1 | White Mage, Red Mage | dir+sprites | `mage/` |
| White Mage | 2 | Mage of Light | toml | `mage/white_mage/` |
| Mage of Light | 3 | (terminal) | toml | `mage/white_mage/mage_of_light/` |
| Red Mage | 2 | Arch Mage, Silver Mage | toml | `mage/red_mage/` |
| Arch Mage | 3 | Great Mage | toml | `mage/red_mage/arch_mage/` |
| Great Mage | 4 | (terminal) | toml | `mage/red_mage/arch_mage/great_mage/` |
| Silver Mage | 3 | (terminal) | toml | `mage/red_mage/silver_mage/` |

### Merman Fighter Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Merman Fighter | 1 | Merman Warrior | toml | `merman_fighter/` |
| Merman Warrior | 2 | Merman Triton, Merman Hoplite | toml | `merman_fighter/merman_warrior/` |
| Merman Triton | 3 | (terminal) | toml | `merman_fighter/merman_warrior/merman_triton/` |
| Merman Hoplite | 3 | (terminal) | toml | `merman_fighter/merman_warrior/merman_hoplite/` |

---

## 2. REBELS (22 units, excluding shared Mage tree)

### Elvish Fighter Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Elvish Fighter | 1 | Elvish Captain, Elvish Hero | dir+sprites | `elvish_fighter/` |
| Elvish Captain | 2 | Elvish Marshal | dir+sprites | `elvish_fighter/elvish_captain/` |
| Elvish Marshal | 3 | (terminal) | toml | `elvish_fighter/elvish_captain/elvish_marshal/` |
| Elvish Hero | 2 | Elvish Champion | toml | `elvish_fighter/elvish_hero/` |
| Elvish Champion | 3 | (terminal) | toml | `elvish_fighter/elvish_hero/elvish_champion/` |

### Elvish Archer Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Elvish Archer | 1 | Elvish Ranger, Elvish Marksman | dir+sprites | `elvish_archer/` |
| Elvish Ranger | 2 | Elvish Avenger | toml | `elvish_archer/elvish_ranger/` |
| Elvish Avenger | 3 | (terminal) | toml | `elvish_archer/elvish_ranger/elvish_avenger/` |
| Elvish Marksman | 2 | Elvish Sharpshooter | toml | `elvish_archer/elvish_marksman/` |
| Elvish Sharpshooter | 3 | (terminal) | toml | `elvish_archer/elvish_marksman/elvish_sharpshooter/` |

### Elvish Shaman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Elvish Shaman | 1 | Elvish Druid, Elvish Sorceress | dir+sprites | `elvish_shaman/` |
| Elvish Druid | 2 | Elvish Shyde | toml | `elvish_shaman/elvish_druid/` |
| Elvish Shyde | 3 | (terminal) | toml | `elvish_shaman/elvish_druid/elvish_shyde/` |
| Elvish Sorceress | 2 | Elvish Enchantress | toml | `elvish_shaman/elvish_sorceress/` |
| Elvish Enchantress | 3 | Elvish Sylph | toml | `elvish_shaman/elvish_sorceress/elvish_enchantress/` |
| Elvish Sylph | 4 | (terminal) | toml | `elvish_shaman/elvish_sorceress/elvish_enchantress/elvish_sylph/` |

### Elvish Scout Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Elvish Scout | 1 | Elvish Rider | dir+sprites | `elvish_scout/` |
| Elvish Rider | 2 | Elvish Outrider | toml | `elvish_scout/elvish_rider/` |
| Elvish Outrider | 3 | (terminal) | toml | `elvish_scout/elvish_rider/elvish_outrider/` |

### Wose Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Wose | 1 | Elder Wose | toml | `wose/` |
| Elder Wose | 2 | Ancient Wose | toml | `wose/elder_wose/` |
| Ancient Wose | 3 | (terminal) | toml | `wose/elder_wose/ancient_wose/` |

### Merman Hunter Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Merman Hunter | 1 | Merman Spearman, Merman Netcaster | toml | `merman_hunter/` |
| Merman Spearman | 2 | Merman Javelineer | toml | `merman_hunter/merman_spearman/` |
| Merman Javelineer | 3 | (terminal) | toml | `merman_hunter/merman_spearman/merman_javelineer/` |
| Merman Netcaster | 2 | Merman Entangler | toml | `merman_hunter/merman_netcaster/` |
| Merman Entangler | 3 | (terminal) | toml | `merman_hunter/merman_netcaster/merman_entangler/` |

### Mage Line
*Shared with Loyalists — see Loyalists section. Single directory tree at `mage/`, referenced by both factions' recruit groups.*

---

## 3. NORTHERNERS (23 units)

### Orcish Grunt Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Orcish Grunt | 1 | Orcish Warrior | dir+sprites | `orcish_grunt/` |
| Orcish Warrior | 2 | Orcish Warlord | dir+sprites | `orcish_grunt/orcish_warrior/` |
| Orcish Warlord | 3 | (terminal) | toml | `orcish_grunt/orcish_warrior/orcish_warlord/` |

### Troll Whelp Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Troll Whelp | 1 | Troll, Troll Rocklobber | toml | `troll_whelp/` |
| Troll | 2 | Troll Warrior | toml | `troll_whelp/troll/` |
| Troll Warrior | 3 | (terminal) | toml | `troll_whelp/troll/troll_warrior/` |
| Troll Rocklobber | 2 | (terminal) | toml | `troll_whelp/troll_rocklobber/` |

### Wolf Rider Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Wolf Rider | 1 | Goblin Knight, Goblin Pillager | toml | `wolf_rider/` |
| Goblin Knight | 2 | Direwolf Rider | toml | `wolf_rider/goblin_knight/` |
| Direwolf Rider | 3 | (terminal) | toml | `wolf_rider/goblin_knight/direwolf_rider/` |
| Goblin Pillager | 2 | (terminal) | toml | `wolf_rider/goblin_pillager/` |

### Orcish Archer Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Orcish Archer | 1 | Orcish Crossbowman | dir+sprites | `orcish_archer/` |
| Orcish Crossbowman | 2 | Orcish Slurbow | toml | `orcish_archer/orcish_crossbowman/` |
| Orcish Slurbow | 3 | (terminal) | toml | `orcish_archer/orcish_crossbowman/orcish_slurbow/` |

### Orcish Assassin Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Orcish Assassin | 1 | Orcish Slayer | dir+sprites | `orcish_assassin/` |
| Orcish Slayer | 2 | Orcish Nightblade | toml | `orcish_assassin/orcish_slayer/` |
| Orcish Nightblade | 3 | (terminal) | toml | `orcish_assassin/orcish_slayer/orcish_nightblade/` |

### Naga Fighter Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Naga Fighter | 1 | Naga Warrior | toml | `naga_fighter/` |
| Naga Warrior | 2 | Naga Myrmidon | toml | `naga_fighter/naga_warrior/` |
| Naga Myrmidon | 3 | (terminal) | toml | `naga_fighter/naga_warrior/naga_myrmidon/` |

### Goblin Spearman Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Goblin Spearman | 0 | Goblin Impaler, Goblin Rouser | toml | `goblin_spearman/` |
| Goblin Impaler | 1 | (terminal) | toml | `goblin_spearman/goblin_impaler/` |
| Goblin Rouser | 1 | (terminal) | toml | `goblin_spearman/goblin_rouser/` |

---

## 4. UNDEAD (22 units)

### Skeleton Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Skeleton | 1 | Revenant, Deathblade | toml | `skeleton/` |
| Revenant | 2 | Draug | toml | `skeleton/revenant/` |
| Draug | 3 | (terminal) | toml | `skeleton/revenant/draug/` |
| Deathblade | 2 | (terminal) | toml | `skeleton/deathblade/` |

### Skeleton Archer Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Skeleton Archer | 1 | Bone Shooter | toml | `skeleton_archer/` |
| Bone Shooter | 2 | Banebow | toml | `skeleton_archer/bone_shooter/` |
| Banebow | 3 | (terminal) | toml | `skeleton_archer/bone_shooter/banebow/` |

### Walking Corpse Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Walking Corpse | 0 | Soulless | MISSING | `walking_corpse/` |
| Soulless | 1 | (terminal) | MISSING | `walking_corpse/soulless/` |

### Ghost Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Ghost | 1 | Wraith, Shadow | toml | `ghost/` |
| Wraith | 2 | Spectre | toml | `ghost/wraith/` |
| Spectre | 3 | (terminal) | toml | `ghost/wraith/spectre/` |
| Shadow | 2 | Nightgaunt | toml | `ghost/shadow/` |
| Nightgaunt | 3 | (terminal) | toml | `ghost/shadow/nightgaunt/` |

### Dark Adept Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Dark Adept | 1 | Dark Sorcerer | dir+sprites | `dark_adept/` |
| Dark Sorcerer | 2 | Lich, Necromancer | toml | `dark_adept/dark_sorcerer/` |
| Lich | 3 | (terminal) | toml | `dark_adept/dark_sorcerer/lich/` |
| Necromancer | 3 | (terminal) | toml | `dark_adept/dark_sorcerer/necromancer/` |

### Vampire Bat Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Vampire Bat | 0 | Blood Bat | toml | `vampire_bat/` |
| Blood Bat | 1 | Dread Bat | toml | `vampire_bat/blood_bat/` |
| Dread Bat | 2 | (terminal) | toml | `vampire_bat/blood_bat/dread_bat/` |

### Ghoul Line
| Unit ID | Level | advances_to | Status | Proposed Path |
|---------|-------|-------------|--------|---------------|
| Ghoul | 1 | Necrophage | toml | `ghoul/` |
| Necrophage | 2 | Ghast | toml | `ghoul/necrophage/` |
| Ghast | 3 | (terminal) | toml | `ghoul/necrophage/ghast/` |

---

## Cross-Faction Shared Units

| Unit | Factions | Note |
|------|----------|------|
| Mage (+ full tree) | Loyalists, Rebels | Single directory at `mage/`; both factions reference in recruit groups |

## Existing Units NOT in These 4 Factions

These units currently exist in `data/units/` with sprites but are NOT part of any of the 4 target factions:

| Unit | Status | Note |
|------|--------|------|
| lieutenant | dir+sprites | Loyalist leader (not a recruit) |
| sergeant | dir+sprites | Loyalist leader variant (not a recruit) |

**Decision:** Lieutenant and Sergeant are leader units, not recruits. They stay in `data/units/` at the top level (not in advancement trees). Faction TOMLs reference them as `leader_def`.

## Excluded Units

| Unit | Reason |
|------|--------|
| Wose Sapling (Level 0) | Rebels recruit Wose (Level 1), not Sapling. Sapling excluded from tree — it's a campaign-only precursor. |

## Advancement Wiring Verification

All branching units checked — `advances_to` fields in existing TOMLs match Wesnoth WML:
- Spearman → [Swordsman, Pikeman, Javelineer] ✓
- Horseman → [Knight, Lancer] ✓
- Mage → [White Mage, Red Mage] ✓
- Elvish Fighter → [Elvish Captain, Elvish Hero] ✓
- Elvish Archer → [Elvish Ranger, Elvish Marksman] ✓
- Elvish Shaman → [Elvish Druid, Elvish Sorceress] ✓
- Ghost → [Wraith, Shadow] ✓
- Skeleton → [Revenant, Deathblade] ✓
- Dark Sorcerer → [Lich, Necromancer] ✓
- Troll Whelp → [Troll, Troll Rocklobber] ✓
- Wolf Rider → [Goblin Knight, Goblin Pillager] ✓
- Goblin Spearman → [Goblin Impaler, Goblin Rouser] ✓
- Merman Hunter → [Merman Spearman, Merman Netcaster] ✓
- Merman Warrior → [Merman Triton, Merman Hoplite] ✓
- Red Mage → [Arch Mage, Silver Mage] ✓
- Knight → [Paladin, Grand Knight] ✓

No dangling references found — every `advances_to` target exists as a unit in this registry.

## Max Directory Depth

Deepest trees (5 levels):
- `mage/red_mage/arch_mage/great_mage/` (4 nesting levels)
- `elvish_shaman/elvish_sorceress/elvish_enchantress/elvish_sylph/` (4 nesting levels)

All other trees are 3 nesting levels or fewer.

---

*This registry is the authoritative reference for Phases 108-111.*
