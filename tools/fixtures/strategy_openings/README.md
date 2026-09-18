# Stack 3 opening fixtures

These fixtures describe the two ordinary opening policies offered by the
initial strategy prompt for `big_battle_6`, undead side 0, seed 2038, and 300
gold.  They contain only relocatable policy and expected fact data; the live
driver remains authoritative for placement, ownership, and committed unit
IDs.

The costs are calculated from the seed-2038 `recruit_options` query:

* Expansion: 2 Vampire Bats, 6 Ghosts, and 8 Skeletons cost 260 gold and
  leave the required 40-gold reserve.
* Concentration: 1 Vampire Bat, 7 Ghosts, and 8 Skeletons cost 266 gold and
  leave 32 gold in reserve.

Both policies use ordinary `set_policy` responses.  Their `scouts` arrays are
empty because recruit IDs do not exist until the engine commits recruitment.
The real-driver tests verify the resulting IDs and objective progress.
