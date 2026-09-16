# Contact-efficiency evaluation fixtures

Synthetic boundary positions for multi-actor choices and exhausted-contact
closure in the strategy harness. They are not Trial 6 archives.
Usage produced through fake transport is synthetic.

Board: `scenarios/big_battle_6/board.toml`
(`26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`).

## three_actors.json

Three independently movable threatened friendlies: Skeleton 3 at (10,7) vs
enemy 4 at (11,7); Ghost 5 at (12,6) vs enemy 7 at (13,6); Ghost 6 at (10,5)
vs enemy 8 at (11,5).

Predicates after one controlled turn:

- requested controlled turn completes
- recruiter 1 survives
- units 3, 5, and 6 survive
- all three make legal moves with reduced destination exposure, counting
  custom acts equal with engine options

## exhausted_helper.json

Involved Skeleton 3 has already moved and attacked. Ghost 5 at (2,5) is an
outside unit. Contact is exhausted for involved units. No automatic helper
menu is generated.

Predicates:

- requested controlled turn completes
- recruiter 1 survives
- unit 3 survives
- an explicit finish or a custom legal act occurs; bare recruit without
  finish must not spend gold

Treatments: Stack 1 baseline `b1461d0495c3f4daabc27d2570549b04616b119d` vs
Stack 3 candidate `fe3663d2b6d2abcedfcfbf2a8fee0a26f552887b`.
