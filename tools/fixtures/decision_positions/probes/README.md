# Frozen decision probe fixtures

These four checkpoints are relocatable copies of the recorded model boundaries
used by the action-repair and comparison evaluation. They are committed test
inputs, not native probe output. Each `checkpoint.json` retains the complete
driver checkpoint and replaces the archive's machine-specific board path with
`__SCENARIO_BOARD__`. Probe tests must resolve that placeholder against the
checked-out repository, verify `board_sha256`, and refuse a revision-0 or other
opening substitution.

All four fixtures use `big_battle_6`, Undead versus Undead, 300 starting gold,
seed-specific RNG state, model side 0, and a model boundary with no pending
opponent turn. The archived source commit is
`a6c368f58890bf2e2de2b2edf66046e192f7e31b` and the board SHA-256 is
`26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`.

Each case README records its source game, revision, side-turn boundary, and
checkpoint digest. The repair case's frozen invalid response is recorded in the
ignored source archive; the committed repair fixture reuses that boundary and
does not copy native prompt/response artifacts into the repository.
