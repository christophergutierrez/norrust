# Promotion boundary fixture

This fixture is a relocatable copy of the seed 2003 model checkpoint at engine
revision 383. The source archive is `grounded-decisions-final-20260906`, game
`e5894441fc744105623143e8c26bac0a`, recorded from commit
`a6c368f58890bf2e2de2b2edf66046e192f7e31b`. The source checkpoint body hash is
`1d9d34a3ebcd38076751350b6ad43255e40828619651e2f76582cc37c67f4b2b`.

`promotion.json` keeps the complete driver checkpoint and replaces the
machine-specific scenario board path with `__SCENARIO_BOARD__`. The integration
test resolves that placeholder against the checked-out repository, verifies the
board digest, then writes a digest-named temporary checkpoint for the real
`greedy_driver`. This makes the test independent of ignored archives and
absolute paths while retaining the archived engine state. At the boundary,
U13 is a pending level 1 Skeleton Archer whose ordered promotion choice is
`Bone Shooter`.

## Handoff boundary

`handoff.json` is seed 2001, game `698d935e4b61288644a5599ca6f94c68`, at
revision 270 (side turn 14), from the same source commit above. Its archived
checkpoint body hash is `37985edd919915b7acc6390f723e464ecd0e602f8faa687e2d9c0a9fd855b814`.
It uses the same relocatable board placeholder and is restored independently
for each handoff branch in the integration test.
