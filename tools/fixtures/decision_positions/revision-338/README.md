# Revision 338 repair fixture

This relocatable fixture records the seed 2002 `big_battle_6` boundary at 14
completed side turns and engine revision 338. The source archive is
`tmp/luna-cohort-20260906/seed-2002/match.ckpt/14-338-model-1a7ec942060954c86ae66a9b8ccf64a35d4c9761e317a1fc5ba5e74b19783f7e.json`.
It was recorded from source commit
`2f71e761fd0aa78745a5e41079e679ed52739006`, conversation/game identity
`f2eb07ab10204ce1966bcf6e6597a0c7`, and the source checkpoint SHA-256 is
`1a7ec942060954c86ae66a9b8ccf64a35d4c9761e317a1fc5ba5e74b19783f7e`.

`checkpoint.json` replaces the archived absolute board path with
`__SCENARIO_BOARD__`; tests resolve that placeholder to the checked-out
`scenarios/big_battle_6/board.toml`, verify its digest, and write a temporary
digest-named checkpoint for the driver. `failed-response.json` is copied from
the original archived response and is retained as recorded fixture data.

To relocate it, copy the fixture into a temporary checkpoint directory,
replace `__SCENARIO_BOARD__` with the repository's board path, and invoke the
existing driver with the fixture's manifest settings (seed 2002, revision 338,
side turns 14, side 0). Never substitute an opening or revision-0 checkpoint.
