# Recruitment-efficiency evaluation fixtures

Synthetic boundary positions for Stack 4 of
`docs/plans/strategy-recruitment-efficiency.md`. They are not Trial 7 archives.
Usage produced through fake transport is synthetic. Stack 3 model-owned
displacement was skipped; there is no capacity-choice menu to compare.

Board: `scenarios/big_battle_6/board.toml`
(`26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`).

Treatments: candidate-only at the Stack 2 commit. Do not claim a causal
improvement versus an older driver without a paired cell.

## scout_opening

Opening recruiters only: `tools/fixtures/strategy_routine/stack3/blocked_objective.json`.
Policy recruits one Ghost as scout to village `(2,4)`, then a replacement must
list the returned live scout ID.

Predicates after one controlled turn:

- requested controlled turn completes
- recruiter 1 survives
- a scout-role recruit occurs and the later replacement names that live ID
- missing-scout repairs are zero when the replacement retains the ID

## safe_travel.json

Eight unmoved Skeletons occupy keep-adjacent castle tiles. Policy: two army
Skeletons, rally `(12,7)`, no holds.

Predicates:

- requested controlled turn completes
- recruiter 1 survives
- ordinary `castle_capacity` travel creates a usable vacancy
- the finite requested recruit occurs after that vacancy
- no additional model call is required to free the first vacancy

## no_relief

Same board as `safe_travel.json`. Policy holds every castle army ID, rally
`(12,7)`, one Skeleton recruit. No legal safe automatic relief.

Predicates:

- requested controlled turn completes
- recruiter 1 survives
- `capacity_relief.status` is `no_eligible_unit`
- do not score an impossible recruitment target as task success
- an explicit finish is valid execution, not successful capacity relief
