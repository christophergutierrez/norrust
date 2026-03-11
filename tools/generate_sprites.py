#!/usr/bin/env python3
"""generate_sprites.py — Generate unit sprites one pose at a time via Gemini.

Generates each pose as a separate API call. The idle pose is generated first,
then fed back as a reference image for subsequent poses to maintain consistency.

Usage:
    # Generate all poses for a unit
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit lieutenant

    # Redo just one pose, using idle as reference
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit bowman --redo defend

    # Redo one pose with a specific reference image
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit bowman --redo defend --base data/units/bowman/idle.png

    # Generate only the portrait
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit lieutenant --portrait

    # List all units
    python3 tools/generate_sprites.py --list
"""

import argparse
import base64
import io
import json
import math
import os
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_UNITS_DIR = os.path.join(PROJECT_ROOT, "data", "units")
SPRITES_RAW_DIR = os.path.join(PROJECT_ROOT, "sprites_raw")

FRAME_SIZE = 256
PORTRAIT_SIZE = 128

POSE_NAMES = ["idle", "attack-melee", "attack-ranged", "defend"]

STYLE_PROMPT = """Style: HD-2D aesthetic. High-fidelity pixel art sprite (32-bit era detail). \
Character has a clean, dark outline. \
Perspective: Slight 3/4 top-down view (isometric-lite). \
Lighting: Even, flat studio lighting with no dramatic shadows or rim-lighting \
(this keeps the color palette clean for masking). \
Background: Solid, uniform #FF00FF (pure magenta) color. \
No floor, no background elements, and no environment lighting effects. \
The sprite is centered on the mask."""

# Unit definitions
# (description, melee_weapon, ranged_weapon_or_None, defend_desc)
# defend_desc describes how the character defends WITHOUT adding equipment they don't have.
# Keys use "/" for tree-structured paths (e.g., "spearman/swordsman").
UNITS = {
    # ── Legacy test units ─────────────────────────────────────────
    "fighter": (
        "human fighter soldier, simple chain mail, iron helmet, longsword, round shield",
        "sword", None,
        "raising round shield to block, crouching behind it with sword ready",
    ),
    "archer": (
        "human archer, leather jerkin, brown hood, simple shortbow, quiver of arrows",
        "short sword", "shortbow",
        "leaping sideways to dodge, bow clutched to chest",
    ),
    "hero": (
        "human hero champion, gleaming plate armor, winged helm, bastard sword, ornate shield, red cape",
        "sword", None,
        "bracing behind ornate shield with sword held high, cape billowing",
    ),
    "ranger": (
        "human ranger woodsman, green cloak, leather armor, longbow, short sword at hip",
        "short sword", "longbow",
        "ducking low with cloak wrapped protectively, bow held aside",
    ),
    # ── Loyalists ─────────────────────────────────────────────────
    "spearman": (
        "human spearman soldier, chain mail armor, iron helmet, long spear, blue tabard",
        "spear", "spear throw",
        "bracing with spear held crosswise, crouching low to absorb impact",
    ),
    "spearman/swordsman": (
        "human swordsman veteran, polished chain mail, steel helmet with visor, longsword, kite shield, blue tabard",
        "sword", None,
        "crouching behind kite shield with sword at the ready",
    ),
    "spearman/swordsman/royal_guard": (
        "human royal guard elite, full plate armor, plumed great helm, ornate longsword, tower shield with royal crest",
        "longsword", None,
        "braced behind tower shield bearing royal crest, longsword raised to counter",
    ),
    "spearman/pikeman": (
        "human pikeman soldier, chain mail and plate pauldrons, open helm, long pike, blue tabard",
        "pike", None,
        "pike planted and angled forward, crouching low behind the shaft",
    ),
    "spearman/pikeman/halberdier": (
        "human halberdier elite, full plate armor, closed helm with visor, ornate halberd with axe blade and spike",
        "halberd", None,
        "halberd held crosswise as a barrier, armored stance braced for impact",
    ),
    "spearman/javelineer": (
        "human javelineer skirmisher, light chain mail, open helm, bundle of javelins, small round shield",
        "spear", "javelin throw",
        "ducking behind small round shield, javelin held back ready to throw",
    ),
    "bowman": (
        "human bowman archer, leather armor, green hood, longbow, quiver of arrows",
        "short sword", "longbow",
        "dodging sideways, leaning away from attack with arm raised to protect face",
    ),
    "bowman/longbowman": (
        "human longbowman veteran, reinforced leather armor, green cloak, tall longbow, sword at hip",
        "sword", "longbow",
        "stepping back evasively with bow raised as a ward",
    ),
    "bowman/longbowman/master_bowman": (
        "human master bowman elite, studded leather armor, feathered cap, masterwork longbow, ornate quiver",
        "sword", "longbow",
        "leaning away gracefully, bow arm raised protectively",
    ),
    "cavalryman": (
        "human cavalryman on horseback, plate armor, lance, mounted knight on brown horse",
        "sword from horseback", None,
        "horse rearing back, rider pulling reins defensively",
    ),
    "cavalryman/dragoon": (
        "human dragoon on armored brown horse, plate armor with blue plume, sword and crossbow, mounted",
        "sword from horseback", "crossbow from horseback",
        "horse turning sideways, rider raising armored forearm to block",
    ),
    "cavalryman/dragoon/cavalier": (
        "human cavalier on barded warhorse, full plate armor, blue and gold plume, longsword, mounted on armored horse",
        "longsword from horseback", "crossbow from horseback",
        "barded horse rearing, cavalier with longsword raised in parrying stance",
    ),
    "heavy_infantryman": (
        "human heavy infantryman, full plate armor, great helm, heavy iron mace, tower shield",
        "mace", None,
        "crouching behind tower shield, braced for impact",
    ),
    "heavy_infantryman/shock_trooper": (
        "human shock trooper, heavy plate armor with spiked pauldrons, full helm, morning star flail",
        "flail", None,
        "hunching behind spiked pauldrons, flail drawn back ready to swing",
    ),
    "heavy_infantryman/shock_trooper/iron_mauler": (
        "human iron mauler elite, massive plate armor with iron rivets, horned great helm, heavy spiked flail",
        "flail", None,
        "crouching in full armor, massive flail held crosswise as a barrier",
    ),
    "horseman": (
        "human horseman cavalry, chain mail and plate, lance, mounted on brown horse, blue pennant",
        "spear from horseback", None,
        "horse rearing back, rider bracing with spear at guard",
    ),
    "horseman/lancer": (
        "human lancer heavy cavalry, plate armor, long lance with pennant, mounted on armored horse",
        "lance from horseback", None,
        "armored horse turning, lancer holding lance defensively across body",
    ),
    "horseman/knight": (
        "human knight in full plate, plumed helm, longsword and lance, mounted on barded warhorse, noble crest",
        "sword from horseback", None,
        "barded warhorse rearing, knight with sword raised in guard position",
    ),
    "horseman/knight/grand_knight": (
        "human grand knight commander, ornate gilded plate armor, great plumed helm, greatsword and lance, mounted on fully barded destrier",
        "longsword from horseback", None,
        "fully barded destrier turning, grand knight with greatsword held high defensively",
    ),
    "horseman/knight/paladin": (
        "human paladin holy knight, gleaming white and gold plate armor, winged helm, glowing blessed sword, mounted on white barded warhorse",
        "glowing holy sword from horseback", None,
        "white warhorse rearing, paladin raising glowing sword creating a divine ward",
    ),
    "fencer": (
        "human fencer duelist, light leather armor, plumed hat, rapier saber, agile stance",
        "saber", None,
        "parrying with saber in en garde stance, body turned sideways",
    ),
    "fencer/duelist": (
        "human duelist master fencer, fine leather armor with silver trim, feathered hat, elegant rapier, hand crossbow at hip",
        "saber", "crossbow",
        "sidestepping with rapier extended in parry, body angled to present smaller target",
    ),
    "fencer/duelist/master_at_arms": (
        "human master at arms weapons expert, reinforced leather and chain, captain's hat with plume, masterwork rapier, ornate crossbow",
        "saber", "crossbow",
        "flowing defensive stance with rapier weaving a pattern, perfectly balanced",
    ),
    "merman_fighter": (
        "merman fighter warrior, aqua-green scales, fish tail, coral-tipped trident, shell armor chest plate",
        "trident", None,
        "raising trident crosswise to block, scales bristling defensively",
    ),
    "merman_fighter/merman_warrior": (
        "merman warrior veteran, deep blue-green scales, muscular, heavy trident, reinforced shell armor",
        "trident", None,
        "crouching with trident braced forward, armored tail coiled",
    ),
    "merman_fighter/merman_warrior/merman_hoplite": (
        "merman hoplite elite, bronze-green scales, coral plate armor, long spear, large round shell shield",
        "spear", None,
        "braced behind round shell shield with spear ready to thrust",
    ),
    "merman_fighter/merman_warrior/merman_triton": (
        "merman triton champion, iridescent blue scales, ornate coral armor, golden trident, crown of shells",
        "trident", None,
        "sweeping golden trident in a defensive arc, scales glowing faintly",
    ),
    "sergeant": (
        "human sergeant officer, chain mail, red cape, sword and shield, commanding officer",
        "sword", "crossbow bolt shot",
        "crouching behind shield, sword held back ready to counter",
    ),
    "lieutenant": (
        "human lieutenant commander, plate armor, white cape, longsword, gold crown, leader",
        "sword", "crossbow bolt shot",
        "parrying with longsword held high, armored shoulder turned forward",
    ),
    # ── Rebels ────────────────────────────────────────────────────
    "elvish_fighter": (
        "elf warrior, green leather armor, long blonde hair, elven sword, leaf-pattern shield",
        "sword", "bow shot",
        "crouching behind leaf-pattern shield, sword ready at side",
    ),
    "elvish_fighter/elvish_hero": (
        "elf hero veteran, burnished green and silver armor, flowing golden hair, ornate elven longsword, leaf-pattern shield",
        "sword", "bow shot",
        "spinning parry with elven longsword, hair flowing behind",
    ),
    "elvish_fighter/elvish_hero/elvish_champion": (
        "elf champion master, gleaming mithril and emerald armor, crown circlet, legendary elven blade, golden shield with tree motif",
        "sword", "bow shot",
        "champion stance with legendary blade raised, golden shield braced forward",
    ),
    "elvish_fighter/elvish_captain": (
        "elf captain leader, ornate green and gold armor, elven longsword, flowing cape, crown circlet",
        "sword", "bow",
        "parrying with elven longsword, cape flowing behind",
    ),
    "elvish_fighter/elvish_captain/elvish_marshal": (
        "elf marshal commander, resplendent gold and green plate, great cape, master-forged elven blade, crown with emerald, leader",
        "sword", "bow shot",
        "commanding stance with blade raised high, cape billowing, crown gleaming",
    ),
    "elvish_archer": (
        "elvish archer, green hooded cloak, brown boots, longbow, quiver",
        "sword", "longbow",
        "leaping back evasively, cloak swirling, bow held to the side",
    ),
    "elvish_archer/elvish_marksman": (
        "elf marksman sharpshooter, dark green hooded cloak, reinforced leather, long-range elven longbow, precision quiver",
        "sword", "longbow",
        "sidestepping with practiced grace, bow lowered defensively",
    ),
    "elvish_archer/elvish_marksman/elvish_sharpshooter": (
        "elf sharpshooter elite, forest camouflage cloak, masterwork leather armor, legendary elven longbow, magical quiver",
        "sword", "longbow",
        "vanishing step backward, cloak blurring, bow ready at hip",
    ),
    "elvish_archer/elvish_ranger": (
        "elf ranger woodsman, brown and green leather, woodland cloak, sturdy bow, short sword at belt",
        "sword", "bow",
        "crouching low in forest stance, sword drawn ready to parry",
    ),
    "elvish_archer/elvish_ranger/elvish_avenger": (
        "elf avenger shadow warrior, dark green and black leather, hooded, twin daggers and composite bow, silent and deadly",
        "sword", "bow",
        "coiled defensive stance, blade drawn and eyes fixed, hood shadowing face",
    ),
    "elvish_scout": (
        "elf scout rider on white horse, light green leather armor, sword, mounted",
        "sword from horseback", "bow shot from horseback",
        "horse turning sideways, rider ducking low against horse's neck",
    ),
    "elvish_scout/elvish_rider": (
        "elf rider mounted on swift white horse, green and silver leather, elven sword, longbow, flowing mane",
        "sword from horseback", "bow from horseback",
        "white horse sidestepping, rider leaning low with sword in guard",
    ),
    "elvish_scout/elvish_rider/elvish_outrider": (
        "elf outrider on majestic white stallion, ornate silver and green armor, master-forged sword, elven war bow, banner",
        "sword from horseback", "bow from horseback",
        "stallion rearing, outrider with sword raised protectively, armor gleaming",
    ),
    "elvish_shaman": (
        "female elf shaman healer, white and green robes, wooden staff with leaves, nature magic",
        "staff", "magic healing energy blast",
        "holding staff forward with a nature magic ward of swirling leaves",
    ),
    "elvish_shaman/elvish_druid": (
        "female elf druid, flowing green and brown robes, gnarled oak staff with glowing leaves, vine crown",
        "staff", "thorny vine magic blast",
        "raising oak staff with roots and vines coiling protectively around",
    ),
    "elvish_shaman/elvish_druid/elvish_shyde": (
        "female elf shyde nature spirit, luminous white and green gown, staff of living wood blooming with flowers, crown of blossoms, ethereal glow",
        "faerie touch", "thorn and vine magic blast",
        "radiant ward of swirling petals and light surrounding body",
    ),
    "elvish_shaman/elvish_sorceress": (
        "female elf sorceress, deep blue and silver robes, silver staff with crystal, arcane runes floating, mystical",
        "staff", "faerie fire arcane magic blast",
        "spinning staff creating a swirl of arcane faerie fire shield",
    ),
    "elvish_shaman/elvish_sorceress/elvish_enchantress": (
        "female elf enchantress, flowing violet and silver robes, ornate crystal staff, glowing ethereal webs of magic",
        "staff", "ethereal web magic blast",
        "weaving shimmering web of protective magic with staff",
    ),
    "elvish_shaman/elvish_sorceress/elvish_enchantress/elvish_sylph": (
        "female elf sylph, translucent gossamer wings, radiant white and gold gown, staff of pure light, fey aura, floating slightly above ground",
        "faerie touch", "ethereal web and faerie fire blast",
        "wings spreading wide creating a shimmering barrier of fey light",
    ),
    "mage": (
        "human mage wizard, blue robes, pointed hat, wooden staff with glowing crystal top",
        "staff", "fireball magic blast from staff",
        "holding staff up defensively with a faint magic barrier shimmering in front",
    ),
    "mage/red_mage": (
        "human red mage, deep red robes with gold trim, red pointed hat, staff with blazing ruby crystal",
        "staff", "fireball blast from staff",
        "staff raised with swirling flame shield in front",
    ),
    "mage/red_mage/arch_mage": (
        "human arch mage, ornate crimson and gold robes, tall pointed hat with runes, master staff with enormous blazing crystal",
        "staff", "massive fireball blast",
        "sweeping staff creating a wall of protective fire",
    ),
    "mage/red_mage/arch_mage/great_mage": (
        "human great mage supreme wizard, resplendent crimson and gold vestments, jeweled crown, legendary staff crackling with pure fire energy",
        "staff", "devastating fire magic blast",
        "standing firm as a dome of pure magical fire swirls protectively",
    ),
    "mage/red_mage/silver_mage": (
        "human silver mage, shimmering silver and white robes, silver circlet, staff with glowing moonstone, arcane and fire dual magic",
        "staff", "silver fire missile blast",
        "staff creating a shimmering silver magic barrier",
    ),
    "mage/white_mage": (
        "human white mage healer, pure white robes with gold trim, white hood, staff with radiant white crystal, holy light",
        "staff", "beam of holy white light from staff",
        "staff raised creating a dome of protective white light",
    ),
    "mage/white_mage/mage_of_light": (
        "human mage of light, radiant white and gold vestments, golden halo, flail and holy staff, beams of divine light",
        "flail", "intense beam of holy light",
        "golden halo blazing, divine light forming a protective shield",
    ),
    "merman_hunter": (
        "merman hunter, blue-green scales, fish tail, trident spear, light shell armor, aquatic",
        "spear", "thrown spear",
        "raising spear crosswise with tail coiled defensively",
    ),
    "merman_hunter/merman_netcaster": (
        "merman netcaster, sea-green scales, weighted throwing net, wooden club, shell pauldrons",
        "club", "weighted net throw",
        "pulling net close protectively, club raised to ward off attacks",
    ),
    "merman_hunter/merman_netcaster/merman_entangler": (
        "merman entangler veteran, dark green scales, reinforced shell armor, heavy club, large enchanted net with barbs",
        "club", "barbed net throw",
        "spinning net in a defensive circle, club held ready",
    ),
    "merman_hunter/merman_spearman": (
        "merman spearman, turquoise scales, long coral-tipped spear, shell chest armor, aquatic warrior",
        "spear", "thrown spear",
        "spear held horizontally to block, tail braced",
    ),
    "merman_hunter/merman_spearman/merman_javelineer": (
        "merman javelineer elite, deep blue scales, bundle of coral javelins, ornate shell armor, powerful tail",
        "spear", "javelin throw",
        "javelin held crosswise defensively, scales bristling",
    ),
    "wose": (
        "wose tree creature, massive living tree humanoid, bark skin, moss-covered, thick branch arms, ancient and slow",
        "crushing branch arms", None,
        "hunching forward with bark-covered arms crossed protectively like a wall",
    ),
    "wose/elder_wose": (
        "elder wose ancient tree being, enormous gnarled bark body, deep moss and lichen, massive crushing limbs, glowing amber sap eyes",
        "crushing branch arms", None,
        "rooting deeply into ground, bark thickening into a defensive wall",
    ),
    "wose/elder_wose/ancient_wose": (
        "ancient wose primeval tree titan, colossal bark body, trailing vines and flowers, thunderous limbs, wise glowing eyes, oldest of the forest",
        "crushing branch arms", None,
        "standing immovable like an ancient oak, bark hardened into impenetrable armor",
    ),
    # ── Northerners ───────────────────────────────────────────────
    "orcish_grunt": (
        "orc grunt warrior, green skin, leather and bone armor, crude iron sword, muscular",
        "sword", None,
        "raising muscular forearm to block, snarling, crude sword held back",
    ),
    "orcish_grunt/orcish_warrior": (
        "orc warrior chieftain, green skin, heavy bone and iron armor, great two-handed sword, leader",
        "greatsword", None,
        "holding greatsword crosswise in front as a barrier, roaring defiantly",
    ),
    "orcish_grunt/orcish_warrior/orcish_warlord": (
        "orc warlord supreme leader, green skin, massive spiked plate and bone armor, enormous greatsword, war banner on back, scarred veteran",
        "greatsword", "crude bow",
        "greatsword planted in ground as a wall, snarling behind it",
    ),
    "orcish_archer": (
        "orc archer, green skin, leather armor, crude shortbow, bone-tipped arrows",
        "dagger", "shortbow",
        "ducking low with bow clutched to chest, turning sideways to present smaller target",
    ),
    "orcish_archer/orcish_crossbowman": (
        "orc crossbowman, green skin, reinforced leather and iron studs, heavy iron crossbow, short sword",
        "short sword", "crossbow",
        "hunching behind crossbow held sideways as a shield, sword ready",
    ),
    "orcish_archer/orcish_crossbowman/orcish_slurbow": (
        "orc slurbow elite, green skin, heavy iron and leather armor, massive repeating crossbow, short sword, fire bolts",
        "short sword", "repeating crossbow",
        "crouching behind massive crossbow, armored and snarling",
    ),
    "orcish_assassin": (
        "orc assassin rogue, green skin, dark leather armor, twin daggers, hooded, stealthy",
        "throwing daggers", "poison darts",
        "crossed daggers in front of face, crouching low in defensive stance",
    ),
    "orcish_assassin/orcish_slayer": (
        "orc slayer veteran assassin, green skin, black leather armor, wicked daggers, hooded, poisoned blades, scarred",
        "dagger", "throwing knives",
        "spinning low with daggers crossed defensively, hood shadowing face",
    ),
    "orcish_assassin/orcish_slayer/orcish_nightblade": (
        "orc nightblade master assassin, green skin, pitch-black leather armor, dual serrated blades, shadowy, glowing red eyes under hood",
        "dual blades", "throwing knives",
        "vanishing into shadow, blades crossed in an X, only red eyes visible",
    ),
    "goblin_spearman": (
        "goblin spearman, small green-skinned goblin, ragged leather armor, crude spear, pointed ears, sneaky",
        "spear", "thrown spear",
        "cowering behind spear held forward, hunched and ready to flee",
    ),
    "goblin_spearman/goblin_impaler": (
        "goblin impaler veteran, small green-skinned, reinforced leather, longer barbed spear, war paint, fierce for a goblin",
        "spear", "thrown spear",
        "spear braced forward in a desperate defensive stance",
    ),
    "goblin_spearman/goblin_rouser": (
        "goblin rouser leader, small green-skinned, crude iron helmet, spear and small shield, war drum on back, rally flag",
        "spear", None,
        "hiding behind small shield with spear pointed outward",
    ),
    "troll_whelp": (
        "troll whelp young troll, gray-green skin, massive fists, loincloth, tusks, hunched, regenerating",
        "fist", None,
        "raising huge fists protectively, hunching shoulders, snarling",
    ),
    "troll_whelp/troll": (
        "troll adult, massive gray-green skin, huge wooden club, loincloth and bone necklace, towering, regenerating",
        "club", None,
        "hunching forward with club held across body, snarling defiantly",
    ),
    "troll_whelp/troll/troll_warrior": (
        "troll warrior veteran, massive gray-green skin, iron-banded war hammer, crude iron armor plates, battle-scarred, regenerating",
        "hammer", None,
        "hammer held crosswise, armored shoulders hunched protectively",
    ),
    "troll_whelp/troll_rocklobber": (
        "troll rocklobber, gray-green skin, huge sling, bag of boulders, loincloth, throwing stance",
        "fist", "sling with boulder",
        "hunching down with arms raised to block, bag of rocks clutched",
    ),
    "wolf_rider": (
        "goblin wolf rider, small goblin mounted on gray wolf, leather armor, wolf has fangs and claws",
        "wolf fangs", None,
        "wolf snarling and bristling, goblin rider ducking low on wolf's back",
    ),
    "wolf_rider/goblin_knight": (
        "goblin knight, small goblin in crude iron armor mounted on large gray wolf, wolf has iron collar",
        "wolf fangs", None,
        "wolf growling and crouching, armored goblin bracing on its back",
    ),
    "wolf_rider/goblin_knight/direwolf_rider": (
        "direwolf rider, small goblin in spiked iron armor mounted on massive dire wolf, dire wolf has iron fangs and spiked collar",
        "dire wolf fangs and claws", None,
        "dire wolf snarling with hackles raised, goblin rider hunching behind wolf's armored head",
    ),
    "wolf_rider/goblin_pillager": (
        "goblin pillager raider, small goblin mounted on wolf, torch in one hand, net in other, leather and stolen armor",
        "wolf fangs and torch", "weighted net throw",
        "wolf turning defensively, goblin raising torch to ward off attackers",
    ),
    "naga_fighter": (
        "naga fighter, serpentine lower body, humanoid torso, green scales, curved sword, no legs, snake tail",
        "sword", None,
        "coiling serpent body defensively, sword held in guard position",
    ),
    "naga_fighter/naga_warrior": (
        "naga warrior veteran, muscular serpentine body, dark green scales, two curved swords, shell armor, war-scarred",
        "dual swords", None,
        "coiled and ready with both swords crossed defensively",
    ),
    "naga_fighter/naga_warrior/naga_myrmidon": (
        "naga myrmidon champion, massive serpentine body, iridescent dark scales, ornate dual blades, golden scale armor, crown of coral",
        "dual swords", None,
        "towering on coiled body with blades weaving a defensive pattern",
    ),
    # ── Undead ────────────────────────────────────────────────────
    "skeleton": (
        "skeleton warrior undead, bare bones, rusty axe, tattered cloth remnants, glowing eye sockets, animated bones",
        "axe", None,
        "raising bony arm with axe held crosswise, hollow eyes glowing",
    ),
    "skeleton/revenant": (
        "revenant undead warrior, armored skeleton, rusted chain mail over bones, heavy axe, glowing green eyes, relentless",
        "axe", None,
        "armored bones bracing with axe held defensively, eyes blazing green",
    ),
    "skeleton/revenant/draug": (
        "draug undead champion, ancient armored skeleton, dark plate armor fused to bones, massive axe, burning blue eyes, death aura",
        "axe", None,
        "standing immovable in fused armor, axe raised in eternal guard, blue fire in eye sockets",
    ),
    "skeleton/deathblade": (
        "deathblade undead warrior, skeleton with dark energy, twin axes crackling with shadow, tattered dark cloak, purple glowing eyes",
        "axe", None,
        "twin axes crossed defensively, shadow energy swirling around bones",
    ),
    "skeleton_archer": (
        "skeleton archer undead, bare bones, crude bow, quiver of bone arrows, tattered hood, glowing eye sockets",
        "bone fist", "bow",
        "hunching with bow clutched to ribcage, eye sockets flickering",
    ),
    "skeleton_archer/bone_shooter": (
        "bone shooter undead archer, reinforced skeleton, iron-bound bow, bone arrows, rusty armor scraps, steady glowing eyes",
        "dagger", "bow",
        "stepping back with bow lowered, bony hand raised to deflect",
    ),
    "skeleton_archer/bone_shooter/banebow": (
        "banebow undead marksman, dark skeleton, enchanted black bow with green glow, poisoned arrows, dark cloak, blazing green eyes",
        "dagger", "enchanted bow",
        "bow raised as a ward, green energy crackling along bones",
    ),
    "ghost": (
        "ghost undead spirit, translucent pale blue spectral figure, floating, tattered ethereal robes, hollow eyes, wailing",
        "spectral touch", "cold wail blast",
        "flickering and phasing partially out of existence",
    ),
    "ghost/shadow": (
        "shadow undead spirit, dark translucent wraith, shadowy claws, wispy dark form, glowing red eyes, menacing",
        "shadow claws", None,
        "dissolving into wisps of darkness, claws drawn inward",
    ),
    "ghost/shadow/nightgaunt": (
        "nightgaunt undead horror, pitch-black spectral form, long shadowy talons, faceless dark void head, trailing darkness",
        "shadow claws", None,
        "melting into a pool of darkness, only talons visible",
    ),
    "ghost/wraith": (
        "wraith undead spirit, dark hooded spectral figure, glowing spectral blade, tattered black robes, piercing blue eyes",
        "baneblade", "cold wail blast",
        "spectral robes billowing, baneblade raised as a ward, fading partially",
    ),
    "ghost/wraith/spectre": (
        "spectre undead horror, towering dark spectral figure, massive glowing baneblade, crown of shadow, blazing blue eyes, death incarnate",
        "baneblade", "devastating cold wail blast",
        "looming with robes swirling, baneblade creating an arc of spectral energy",
    ),
    "ghoul": (
        "ghoul undead, hunched decaying humanoid, pale gray skin, long claws, tattered rags, feral, glowing yellow eyes",
        "claws", None,
        "crouching low with claws raised protectively, snarling",
    ),
    "ghoul/necrophage": (
        "necrophage undead, larger hunched decaying form, bloated gray-green skin, massive claws, plague-ridden, yellow eyes",
        "claws", None,
        "hunching forward with arms crossed, claws spread threateningly",
    ),
    "ghoul/necrophage/ghast": (
        "ghast undead horror, massive bloated decaying form, putrid green-gray skin, enormous fanged maw, huge claws, plague aura",
        "bite", None,
        "rearing back with massive maw open, claws raised in feral defense",
    ),
    "vampire_bat": (
        "vampire bat, large dark bat, red eyes, leathery wings spread, fangs bared, flying",
        "fangs", None,
        "wings folded protectively, body twisted to dodge",
    ),
    "vampire_bat/blood_bat": (
        "blood bat, large crimson-tinged bat, glowing red eyes, sharp fangs dripping, wider wingspan, flying",
        "fangs", None,
        "banking sharply, wings angled to deflect, red eyes blazing",
    ),
    "vampire_bat/blood_bat/dread_bat": (
        "dread bat, massive dark bat, enormous wingspan, burning red eyes, wicked fangs, shadow aura, flying terror",
        "fangs", None,
        "diving and twisting, massive wings creating a shield of darkness",
    ),
    "walking_corpse": (
        "walking corpse zombie undead, shambling decaying humanoid, tattered clothes, gray-green rotting skin, blank eyes, arms outstretched",
        "touch", None,
        "stumbling backward with arms raised, decaying body absorbing blow",
    ),
    "walking_corpse/soulless": (
        "soulless zombie undead, larger shambling corpse, more muscular decay, tattered armor scraps, glowing dead eyes, plague touch",
        "touch", None,
        "lurching forward with arms crossed protectively, dead eyes glowing",
    ),
    "dark_adept": (
        "dark adept necromancer, pale skin, dark purple/black hooded robe, glowing purple eyes, skeletal staff with skull top",
        "staff jab", "purple chill wave magic blast",
        "raising skeletal staff with skull glowing, dark energy shield swirling around",
    ),
    "dark_adept/dark_sorcerer": (
        "dark sorcerer undead master, pale gaunt face, ornate black and purple robes, staff with glowing skull, shadow magic crackling, leader",
        "staff", "chill wave and shadow wave magic",
        "staff raised with swirling dark energy barrier, skull blazing purple",
    ),
    "dark_adept/dark_sorcerer/lich": (
        "lich undead archmage, skeletal body in ancient black robes, crown of bone, staff of pure dark energy, blazing blue fire eyes, supreme undead",
        "arcane touch", "chill tempest and shadow wave",
        "floating with robes billowing, dark energy vortex swirling as a shield",
    ),
    "dark_adept/dark_sorcerer/necromancer": (
        "necromancer dark wizard, pale hooded figure, heavy black robes with skull motifs, plague staff, green necromantic energy, summoner of dead",
        "plague staff", "chill wave and shadow wave magic",
        "plague staff raised creating a barrier of sickly green necromantic energy",
    ),
}


def load_image_base64(path):
    """Load an image file and return base64-encoded data."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def generate_image(api_key, prompt, reference_image_path=None, retries=3):
    """Generate an image via Gemini API, optionally with a reference image."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash-exp-image-generation:generateContent"
    )

    parts = []

    if reference_image_path:
        img_b64 = load_image_base64(reference_image_path)
        parts.append({
            "inlineData": {
                "mimeType": "image/png",
                "data": img_b64,
            }
        })

    parts.append({"text": prompt})

    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }).encode()

    for attempt in range(retries):
        if attempt > 0:
            wait = 30 * attempt
            print(f"    Retry {attempt} (waiting {wait}s)...", flush=True)
            time.sleep(wait)

        try:
            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"    API error: {type(e).__name__}", flush=True)
            continue

        candidates = data.get("candidates", [])
        if not candidates:
            print("    No candidates in response", flush=True)
            continue
        parts_resp = candidates[0].get("content", {}).get("parts", [])
        for p in parts_resp:
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])

        print("    No image in response", flush=True)

    return None


def process_single_image(img_data, out_path, threshold=100):
    """Process a single generated image: resize to single frame, remove bg, center."""
    from PIL import Image

    img = Image.open(io.BytesIO(img_data)).convert("RGBA")

    # Scale to square, fitting into FRAME_SIZE x FRAME_SIZE
    max_dim = max(img.width, img.height)
    scale = FRAME_SIZE / max_dim
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.NEAREST)

    # Sample background color from corners
    corners = [
        (0, 0), (new_w - 1, 0),
        (0, new_h - 1), (new_w - 1, new_h - 1),
    ]
    bg = tuple(
        sum(img.getpixel(c)[i] for c in corners) // 4
        for i in range(3)
    )

    # Find content bounding box
    pixels = img.load()
    left_c, right_c = new_w, 0
    top_c, bot_c = new_h, 0
    for y in range(new_h):
        for x in range(new_w):
            r, g, b, a = pixels[x, y]
            if math.sqrt((r - bg[0])**2 + (g - bg[1])**2 + (b - bg[2])**2) >= threshold:
                left_c = min(left_c, x)
                right_c = max(right_c, x)
                top_c = min(top_c, y)
                bot_c = max(bot_c, y)

    # No content found — save blank frame
    if right_c < left_c:
        frame = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (0, 0, 0, 0))
        frame.save(out_path)
        return False, 0, 0

    content_w = right_c - left_c + 1
    content_h = bot_c - top_c + 1

    # Crop to content
    crop = img.crop((left_c, top_c, right_c + 1, bot_c + 1))

    # Fit into FRAME_SIZE with padding
    fit_scale = min((FRAME_SIZE - 10) / content_w, (FRAME_SIZE - 10) / content_h)
    if fit_scale < 1.0:
        crop = crop.resize((int(content_w * fit_scale), int(content_h * fit_scale)), Image.NEAREST)

    # Center on FRAME_SIZE x FRAME_SIZE canvas
    frame = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (bg[0], bg[1], bg[2], 255))
    x_off = (FRAME_SIZE - crop.width) // 2
    y_off = (FRAME_SIZE - crop.height) // 2
    frame.paste(crop, (x_off, y_off))

    # Remove background + pink artifacts
    pixels = frame.load()
    bg2 = tuple(
        sum(frame.getpixel(c)[i] for c in [
            (0, 0), (FRAME_SIZE - 1, 0),
            (0, FRAME_SIZE - 1), (FRAME_SIZE - 1, FRAME_SIZE - 1),
        ]) // 4
        for i in range(3)
    )
    for y in range(FRAME_SIZE):
        for x in range(FRAME_SIZE):
            r, g, b, a = pixels[x, y]
            if math.sqrt((r - bg2[0])**2 + (g - bg2[1])**2 + (b - bg2[2])**2) < threshold:
                pixels[x, y] = (0, 0, 0, 0)
            elif r > 180 and b > 150 and g < 120:
                pixels[x, y] = (0, 0, 0, 0)

    # Verify padding
    top_p, bot_p = FRAME_SIZE, 0
    for y in range(FRAME_SIZE):
        for x in range(FRAME_SIZE):
            if pixels[x, y][3] > 0:
                top_p = min(top_p, y)
                bot_p = max(bot_p, y)
                break

    pad_top = top_p
    pad_bot = FRAME_SIZE - 1 - bot_p
    ok = pad_bot >= 3 and pad_top >= 3

    frame.save(out_path)
    return ok, pad_top, pad_bot


def check_multi_blob(img_path):
    """Detect multiple disconnected figures via flood-fill connected components."""
    from PIL import Image

    img = Image.open(img_path).convert("RGBA")
    pixels = img.load()
    w, h = img.width, img.height

    # Build binary mask
    visited = [[False] * w for _ in range(h)]
    total_opaque = 0
    for y in range(h):
        for x in range(w):
            if pixels[x, y][3] > 0:
                total_opaque += 1

    if total_opaque == 0:
        return True, 0

    threshold = total_opaque * 0.05
    blob_count = 0

    for sy in range(h):
        for sx in range(w):
            if visited[sy][sx] or pixels[sx, sy][3] == 0:
                continue
            # BFS flood-fill
            queue = [(sx, sy)]
            visited[sy][sx] = True
            size = 0
            while queue:
                cx, cy = queue.pop()
                size += 1
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and pixels[nx, ny][3] > 0:
                        visited[ny][nx] = True
                        queue.append((nx, ny))
            if size >= threshold:
                blob_count += 1

    return blob_count <= 1, blob_count


def check_size(img_path, hard_limit=30720, warn_limit=20480):
    """Check file size against limits. Hard fail >30KB, warn >20KB."""
    file_bytes = os.path.getsize(img_path)
    if file_bytes > hard_limit:
        return False, file_bytes
    if file_bytes > warn_limit:
        print(f"    SIZE WARNING: {file_bytes} bytes (>{warn_limit} target)", flush=True)
    return True, file_bytes


def check_edges(img_path, border=2):
    """Check that no opaque pixels exist in outermost border pixels."""
    from PIL import Image

    img = Image.open(img_path).convert("RGBA")
    pixels = img.load()
    w, h = img.width, img.height
    edge_count = 0

    for y in range(h):
        for x in range(w):
            if x < border or x >= w - border or y < border or y >= h - border:
                if pixels[x, y][3] > 0:
                    edge_count += 1

    return edge_count == 0, edge_count


def validate_sprite(img_path):
    """Run all validation checks on a processed sprite. Returns (ok, issues)."""
    issues = []

    # Multi-blob check
    blob_ok, blob_count = check_multi_blob(img_path)
    if not blob_ok:
        issues.append(f"multi-blob ({blob_count} significant blobs)")
        print(f"    MULTI-BLOB: FAIL ({blob_count} blobs)", flush=True)
    else:
        print(f"    MULTI-BLOB: ok ({blob_count} blob)", flush=True)

    # Size check
    size_ok, file_bytes = check_size(img_path)
    if not size_ok:
        issues.append(f"oversized ({file_bytes} bytes > 30KB)")
        print(f"    SIZE: FAIL ({file_bytes} bytes)", flush=True)
    else:
        print(f"    SIZE: ok ({file_bytes} bytes)", flush=True)

    # Edge check
    edge_ok, edge_count = check_edges(img_path)
    if not edge_ok:
        issues.append(f"edge-clipped ({edge_count} border pixels)")
        print(f"    EDGES: FAIL ({edge_count} border pixels)", flush=True)
    else:
        print(f"    EDGES: ok", flush=True)

    return len(issues) == 0, issues


def write_sprite_toml(unit_dir, unit_name, has_ranged=True):
    """Write sprite.toml for a unit. Single frame per pose (v2 pipeline)."""
    toml_path = os.path.join(unit_dir, "sprite.toml")
    # Use leaf name as sprite ID (e.g., "swordsman" not "spearman/swordsman")
    sprite_id = unit_name.rsplit("/", 1)[-1] if "/" in unit_name else unit_name
    with open(toml_path, "w") as f:
        f.write(f'id = "{sprite_id}"\n')
        for name in POSE_NAMES:
            if name == "attack-ranged" and not has_ranged:
                continue
            # Only write if the png exists
            png_path = os.path.join(unit_dir, f"{name}.png")
            if not os.path.exists(png_path):
                continue
            if name.startswith("attack-"):
                attack_type = name.split("-", 1)[1]
                f.write(f"\n[attacks.{attack_type}]\n")
            else:
                f.write(f"\n[{name}]\n")
            f.write(f'file = "{name}.png"\n')
            f.write(f"frame_width = {FRAME_SIZE}\n")
            f.write(f"frame_height = {FRAME_SIZE}\n")
            f.write(f"frames = 1\n")
            f.write(f"fps = 1\n")
        portrait_path = os.path.join(unit_dir, "portrait.png")
        if os.path.exists(portrait_path):
            f.write("\n[portrait]\n")
            f.write('file = "portrait.png"\n')


def build_prompt(unit_name, pose, ref_path):
    """Build the generation prompt for a unit + pose."""
    desc, melee_weapon, ranged_weapon, defend_desc = UNITS[unit_name]

    pose_descriptions = {
        "idle": "standing idle, weapon at rest, relaxed stance.",
        "attack-melee": f"mid-swing {melee_weapon} melee attack, dynamic action pose.",
        "attack-ranged": f"aiming {ranged_weapon or melee_weapon} ranged attack, ready to fire.",
        "defend": defend_desc,
    }
    pose_desc = pose_descriptions[pose]

    if ref_path is None:
        # First generation — no reference
        return (
            f"{STYLE_PROMPT}\n\n"
            f"Make a {desc}.\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"Just one character, facing right, centered on the magenta background."
        )
    else:
        # With reference image for consistency
        return (
            f"This is a reference image of the character. "
            f"Generate the SAME character in a new pose.\n\n"
            f"{STYLE_PROMPT}\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"SAME character as the reference — same colors, same proportions, "
            f"same outfit, same style. Facing right. "
            f"Do NOT add equipment the character does not have."
        )


def build_portrait_prompt(unit_name):
    """Build prompt for a painterly portrait on black background."""
    desc = UNITS[unit_name][0]
    return (
        f"A painterly close-up portrait of a {desc}. "
        f"Show the face and upper body only, slightly angled, with dramatic lighting. "
        f"Rich detail, oil painting style, fantasy RPG character portrait. "
        f"Background: solid, uniform black (#000000). "
        f"No environment, no props, no text. Just the character portrait on black."
    )


def process_portrait(img_data, out_path, threshold=60):
    """Process a portrait: scale to 128x128, replace background with black."""
    from PIL import Image

    img = Image.open(io.BytesIO(img_data)).convert("RGB")

    # Scale to fit PORTRAIT_SIZE x PORTRAIT_SIZE
    max_dim = max(img.width, img.height)
    scale = PORTRAIT_SIZE / max_dim
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center on black canvas
    frame = Image.new("RGB", (PORTRAIT_SIZE, PORTRAIT_SIZE), (0, 0, 0))
    x_off = (PORTRAIT_SIZE - new_w) // 2
    y_off = (PORTRAIT_SIZE - new_h) // 2
    frame.paste(img, (x_off, y_off))

    # Clean near-black edges to pure black
    pixels = frame.load()
    for y in range(PORTRAIT_SIZE):
        for x in range(PORTRAIT_SIZE):
            r, g, b = pixels[x, y]
            if r < threshold and g < threshold and b < threshold:
                pixels[x, y] = (0, 0, 0)

    frame.save(out_path)
    file_bytes = os.path.getsize(out_path)
    return True, file_bytes


def generate_portrait(api_key, unit_name, max_attempts=3):
    """Generate a portrait for a unit. Returns True on success."""
    if unit_name not in UNITS:
        print(f"Unknown unit: {unit_name}")
        return False

    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    os.makedirs(unit_dir, exist_ok=True)
    os.makedirs(SPRITES_RAW_DIR, exist_ok=True)

    out_path = os.path.join(unit_dir, "portrait.png")
    raw_name = unit_name.replace("/", "__")
    raw_path = os.path.join(SPRITES_RAW_DIR, f"{raw_name}_v2_portrait.png")

    prompt = build_portrait_prompt(unit_name)

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"\n  Retry {attempt}/{max_attempts} for portrait...", flush=True)
            time.sleep(10)
        else:
            print(f"\n  Generating portrait...", end=" ", flush=True)

        img_data = generate_image(api_key, prompt)

        if not img_data:
            print("FAILED (no image)")
            continue

        # Save raw
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"raw saved ({len(img_data)} bytes)", end=" ", flush=True)

        # Process
        _, file_bytes = process_portrait(img_data, out_path)
        print(f"processed ({file_bytes} bytes)", flush=True)

        # Size check (100KB limit)
        if file_bytes > 102400:
            print(f"  portrait: OVERSIZED ({file_bytes} bytes > 100KB)", flush=True)
            continue

        print(f"  portrait: PASSED ({file_bytes} bytes)", flush=True)
        return True

    print(f"  NEEDS REVIEW: portrait failed after {max_attempts} attempts", flush=True)
    return False


def generate_pose(api_key, unit_name, pose, ref_path=None, max_attempts=3):
    """Generate a single pose with validation + retry. Returns (ok, raw_path)."""
    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    os.makedirs(unit_dir, exist_ok=True)
    os.makedirs(SPRITES_RAW_DIR, exist_ok=True)

    out_path = os.path.join(unit_dir, f"{pose}.png")
    raw_name = unit_name.replace("/", "__")
    raw_path = os.path.join(SPRITES_RAW_DIR, f"{raw_name}_v2_{pose}.png")

    prompt = build_prompt(unit_name, pose, ref_path)

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"\n  Retry {attempt}/{max_attempts} for {pose}...", flush=True)
            time.sleep(10)
        else:
            print(f"\n  Generating {pose}...", end=" ", flush=True)

        img_data = generate_image(api_key, prompt, reference_image_path=ref_path)

        if not img_data:
            print("FAILED (no image)")
            continue

        # Save raw
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"raw saved ({len(img_data)} bytes)", end=" ", flush=True)

        # Process
        _, pad_top, pad_bot = process_single_image(img_data, out_path)
        print(f"processed (top={pad_top} bot={pad_bot})")

        # Validate
        print(f"  Validating {pose}:", flush=True)
        valid, issues = validate_sprite(out_path)

        if valid:
            print(f"  {pose}: PASSED", flush=True)
            return True, raw_path
        else:
            print(f"  {pose}: FAILED validation — {', '.join(issues)}", flush=True)

    print(f"  NEEDS REVIEW: {pose} failed after {max_attempts} attempts", flush=True)
    return False, raw_path


def generate_unit(api_key, unit_name, reference_path=None):
    """Generate all poses for one unit."""
    if unit_name not in UNITS:
        print(f"Unknown unit: {unit_name}")
        return False

    _, _, ranged_weapon, _ = UNITS[unit_name]
    has_ranged = ranged_weapon is not None

    poses = POSE_NAMES if has_ranged else [p for p in POSE_NAMES if p != "attack-ranged"]

    ref_path = reference_path
    passed = []
    failed = []

    for pose in poses:
        ok, raw_path = generate_pose(api_key, unit_name, pose, ref_path=ref_path)
        if ok:
            passed.append(pose)
        else:
            failed.append(pose)

        # After idle, use it as reference for remaining poses
        if pose == "idle" and ref_path is None and raw_path:
            ref_path = raw_path
            print(f"  (idle will be used as reference for remaining poses)")

        time.sleep(10)

    # Generate portrait
    time.sleep(10)
    portrait_ok = generate_portrait(api_key, unit_name)
    if not portrait_ok:
        failed.append("portrait")

    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    write_sprite_toml(unit_dir, unit_name, has_ranged)

    total = len(poses) + 1  # poses + portrait
    print(f"\n{'=' * 50}")
    print(f"Summary: {len(passed) + (1 if portrait_ok else 0)}/{total} assets passed validation")
    if failed:
        print(f"NEEDS REVIEW: {', '.join(failed)}")
    print(f"Sprites in {unit_dir}/")
    print(f"{'=' * 50}")
    return len(failed) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate unit sprites one pose at a time with reference feedback"
    )
    parser.add_argument("--unit", help="Unit name (e.g., lieutenant)")
    parser.add_argument("--redo", help="Regenerate only this pose (e.g., defend)")
    parser.add_argument("--base", help="Reference image for --redo (default: idle raw)")
    parser.add_argument("--portrait", action="store_true", help="Generate only the portrait")
    parser.add_argument("--list", action="store_true", help="List available units")
    args = parser.parse_args()

    if args.list:
        for name in sorted(UNITS.keys()):
            desc, melee, ranged, defend = UNITS[name]
            r = f" + {ranged}" if ranged else ""
            print(f"  {name}: {desc}")
            print(f"    weapons: {melee}{r}")
            print(f"    defend: {defend}")
        return 0

    if not args.unit:
        parser.error("--unit is required (use --list to see available units)")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        return 1

    if args.portrait:
        print(f"{'=' * 50}")
        print(f"Portrait: {args.unit}")
        print(f"{'=' * 50}")

        ok = generate_portrait(api_key, args.unit)
        print(f"\nResult: {'OK' if ok else 'NEEDS REVIEW'}")
        return 0 if ok else 1

    if args.redo:
        # Single pose redo
        if args.unit not in UNITS:
            print(f"Unknown unit: {args.unit}")
            return 1

        _, _, ranged_weapon, _ = UNITS[args.unit]
        has_ranged = ranged_weapon is not None
        valid_poses = POSE_NAMES if has_ranged else [p for p in POSE_NAMES if p != "attack-ranged"]

        if args.redo not in valid_poses:
            print(f"Invalid pose '{args.redo}'. Valid: {valid_poses}")
            return 1

        # Determine reference
        if args.base:
            ref_path = os.path.abspath(args.base)
            if not os.path.exists(ref_path):
                print(f"Reference not found: {ref_path}")
                return 1
        else:
            # Default to idle raw
            raw_name = args.unit.replace("/", "__")
            ref_path = os.path.join(SPRITES_RAW_DIR, f"{raw_name}_v2_idle.png")
            if not os.path.exists(ref_path):
                print(f"No idle reference found at {ref_path}")
                print("Use --base to specify a reference image")
                return 1

        print(f"{'=' * 50}")
        print(f"Redo: {args.unit} / {args.redo}")
        print(f"Reference: {ref_path}")
        print(f"{'=' * 50}")

        ok, _ = generate_pose(api_key, args.unit, args.redo, ref_path=ref_path)

        unit_dir = os.path.join(DATA_UNITS_DIR, args.unit)
        write_sprite_toml(unit_dir, args.unit, has_ranged)

        print(f"\nResult: {'OK' if ok else 'NEEDS REVIEW'}")
        return 0 if ok else 1
    else:
        # Full unit generation
        print(f"{'=' * 50}")
        print(f"Generating: {args.unit} (v2 pipeline)")
        print(f"{'=' * 50}")

        ok = generate_unit(api_key, args.unit, reference_path=args.base)

        print(f"\nResult: {'OK' if ok else 'NEEDS REVIEW'}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
