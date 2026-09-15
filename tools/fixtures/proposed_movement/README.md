# Proposed-movement fixtures

Synthetic `boundary=model` positions for strategy proposed-destination
decisions. They are not Trial 8 archives. The revision-125 evidence file is
real engine output from a read-only replay; the original archive stays
untracked.

Board: `scenarios/big_battle_6/board.toml`
(`26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`).

Policy used by the Stack 3 tests: `holds: [1]`, `rally: {col:12,row:7}`,
empty scouts/villages/recruits.

## proposed_move_mover_exposed.json

Friendly Skeleton 5 at (8,7); enemy Skeleton Archer 20 at (14,7). Rally
travel toward (12,7) is rejected as `contact/proposed_destination` exposing
the mover. A bounded menu offers the rejected stop plus two proven-safe
local hexes. Keep (2,7) is not in current contact.

## proposed_move_other_friendly_exposed.json

Same as mover_exposed plus friendly Skeleton 6 at (6,7). Current-board
contact still does not fire. The rejected step's projected threats name
the mover, not unit 6: open-view current-contact already covers a unit
that would be exposable without this move, so a proposed-destination
packet cannot be the first report of that exposure.

## rev125_proposed_destination_evidence.json

Committed real `routine_next` output from trial 8 revision 125. Mid-turn
`boundary=partial` archives are not task-run checkpoints.
