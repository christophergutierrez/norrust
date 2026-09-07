# Repair probe boundary

- Source archive: `tmp/luna-cohort-20260906/seed-2002/`
- Source game: `713b828db880e405b2ce40ad26a08fc8`
- Source commit: `a6c368f58890bf2e2de2b2edf66046e192f7e31b`
- Seed: 2002; scenario: `big_battle_6`; factions: Undead versus Undead
- Boundary: model; side turns 14; engine revision 338; turn 8
- Gold: F0=6, F1=2; next unit ID: 47
- Board SHA-256: `26366c43a231ef9f7244b24fb74fe5343792c2c26bc0366941a097ce3c7c4207`
- Source checkpoint SHA-256: `1a7ec942060954c86ae66a9b8ccf64a35d4c9761e317a1fc5ba5e74b19783f7e`
- Relocatable fixture SHA-256: `4b1b629eaced5d47e27a4382a54fcc3758d833182f3677fe08c5d09b5d62380a`

The archived source file was
`match.ckpt/14-338-model-1a7ec942060954c86ae66a9b8ccf64a35d4c9761e317a1fc5ba5e74b19783f7e.json`.

The frozen invalid draft is recorded in the revision-338 request artifacts in
the ignored source archive (`artifacts/00029-result.json` and its matching
request/prompt records); the subsequent recorded repair is `00030-result.json`.
It delegates U13 while holding U45 and contains the 121-character U45 hold
reason. The native repair probe must inject that exact recorded draft through
the real repair entry point, then count the native Luna repair response
separately from the injected fixture data.
