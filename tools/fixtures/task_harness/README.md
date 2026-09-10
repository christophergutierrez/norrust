# Stack 4 offline task harness

`matrix.json` is a 24 cell, four family by two variant by three arm acceptance
matrix. Every cell runs the real `llm_client` and `greedy_driver` with the
checked in `scripted_responder.py`; no paid model is contacted.

The responder performs these factual operations from the live board card:

- `opening_deployment`: recruit a Skeleton Archer and move engine assigned unit
  U3 from `(2,6)` to `(2,5)`.
- `competing_villages`: recruit a Vampire Bat and move U3 directly onto the
  initially neutral named village `(2,4)`. Seeds 44 and 45 are the two distinct
  fresh opening variants.
- `recruiter_defense`: attack the named one HP recruiter threat U38 or U40 and
  finish with recruiter U1 alive. `defense_variant1.json` derives from
  `tools/fixtures/decision_positions/promotion.json`; `defense_variant2.json`
  derives from `tools/fixtures/decision_positions/probes/resignation/checkpoint.json`.
  Each task fixture relocates its named threat to `(3,6)` beside U1 and its
  defender to `(3,7)`, preserving the source RNG lineage while making the
  defense predicate factual and executable.
- `coordinated_combat`: kill named target U24 or U58. Variant 1 then attacks
  reserve target U39 after U24 is gone. `combat_variant1.json` derives from
  `tools/fixtures/decision_positions/revision-338/checkpoint.json` with U24
  set to one HP. `combat_variant2.json` derives from
  `tools/fixtures/decision_positions/probes/guards/checkpoint.json`, placing
  U58 by U6 and U59 by reserve U49, both at one HP.

Arms A and B submit coordinate envelopes. Arm C selects opaque choices handles,
including a tool inspection when a newly recruited unit's move choices are not
in the initial card. Each cell has its own log, checkpoint directory, request
context, and usage sidecar. The offline sidecar records fixed measured usage of
100 input, 20 output, and 120 total tokens per physical call with transport
`offline_fixture`.

Run the acceptance test after building the driver:

```bash
python3 -m unittest tools.test_task_harness_matrix
```

The fresh opening and village cells use seeds 42/43 and 44/45 respectively;
their source is the scenario's `big_battle_6` board, with no checkpoint. The
defense variants are derived from `decision_positions/promotion.json` and
`decision_positions/probes/resignation/checkpoint.json`; each relocates its
one HP named threat and defender to `(3,6)` and `(3,7)` beside recruiter U1 and
uses a bounded cap of 18 side turns. Combat variant 1 derives from
`decision_positions/revision-338/checkpoint.json` and changes U24 to one HP
with a 16 turn cap. Combat variant 2 derives from
`decision_positions/probes/guards/checkpoint.json`, places U58 beside U6 and
U59 beside reserve U49 at one HP, and retains the source's 50 turn cap.
