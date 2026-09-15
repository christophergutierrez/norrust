# Proposed-movement fixtures

Synthetic `boundary=model` positions for strategy proposed-destination
decisions. They are not Trial 8 archives. The revision-125 evidence file is
real engine output from a read-only replay; the original archive stays
untracked. Usage produced through fake transport is synthetic and is not
model evaluation.

Board: `scenarios/big_battle_6/board.toml`
(`26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`).

Policy used by the Stack 3/4 tests: `holds: [1]`, `rally: {col:12,row:7}`,
empty scouts/villages/recruits.

Offline proofs (real client, release or debug driver, fake transport):

- scout-capacity rejection then correction, and all-owned zero scouts:
  `tools/test_strategy_scout_capacity_integration.py`
- safe alternative, risky proceed, hold, stale option id:
  `tools/test_strategy_proposed_movement_stack3.py`
- no-op finish is not movement-task success, invalid predicates, catalog
  import, recovery: `tools/test_strategy_proposed_movement_stack4.py`

Do not launch a historical `boundary=partial` mid-turn archive as a task
run. Query Trial 8 checkpoints only as read-only evidence.

The Fireworks template is `fireworks_candidate_manifest.json`. It is
`prepared_not_run`. The four cells use two checkpoints and two source
trees (Stack 2 facts-only at `ffbdaf5`, Stack 3 choices at the commit that
added the menu). Launch each cell as its own one-cell bakeoff run so the
matched-fingerprint check is not asked to compare different checkpoints or
drivers. Store actual run manifests under ignored `tmp/`.

## proposed_move_mover_exposed.json

Friendly Skeleton 5 at (8,7); enemy Skeleton Archer 20 at (14,7). Rally
travel toward (12,7) is rejected as `contact/proposed_destination` exposing
the mover. A bounded menu offers the rejected stop `(9,7)` plus two
proven-safe local hexes `(8,5)` and `(8,6)`, both `advances_objective=false`.
Keep (2,7) is not in current contact.

Cell `success_predicate` for live cells is only `recruiter_alive` and
`completed_side_turns_at_least: 1`. Movement-task success is not that
conjunction: it is a safe stop for unit 5 on `(8,5)` or `(8,6)` (or another
custom safe hex), or a justified `set_policy` that holds unit 5 or changes
the rally. Finish that leaves unit 5 on `(8,7)` is legal and is not
movement-task success. Do not require live proceed-into-damage.

## proposed_move_other_friendly_exposed.json

Same as mover_exposed plus friendly Skeleton 6 at (6,7). Current-board
contact still does not fire. The rejected step's projected threats name
the mover, not unit 6: open-view current-contact already covers a unit
that would be exposable without this move, so a proposed-destination
packet cannot be the first report of that exposure.

## rev125_proposed_destination_evidence.json

Committed real `routine_next` output from trial 8 revision 125. Mid-turn
`boundary=partial` archives are not task-run checkpoints.
