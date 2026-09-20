# Stack 3 opening fixtures

These fixtures describe the two ordinary opening policies offered by the
initial strategy prompt for `big_battle_6`, undead side 0, seed 2038, and 300
gold.  They contain only relocatable policy and expected fact data; the live
driver remains authoritative for placement, ownership, and committed unit
IDs.

The costs are calculated from the seed-2038 `recruit_options` query:

* Expansion: 2 Vampire Bats, 8 Skeletons, 2 Ghosts, and 7 Dark Adepts cost
  296 gold and leave 0 gold in reserve (spending >= 95% of initial 300 gold).
* Concentration: 1 Vampire Bat, 9 Skeletons, 2 Ghosts, and 7 Dark Adepts cost
  298 gold and leave 0 gold in reserve (spending >= 95% of initial 300 gold).

Both examples set `reserve_gold: 0` to deploy an affordable combined-arms force
immediately. In general, `reserve_gold` is for explicit saving objectives;
custom nonzero reserves remain fully valid.

Both policies use ordinary `set_policy` responses.  Their `scouts` arrays are
empty because recruit IDs do not exist until the engine commits recruitment.
The real-driver tests verify the resulting IDs and objective progress.

Both examples pair a frontline with ranged support, following the shared
combat doctrine in `docs/LLM_TACTICAL_PLAYBOOK.md`. The recipes are legal,
affordable examples, not experimentally established winning compositions.
