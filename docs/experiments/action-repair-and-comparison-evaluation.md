# Action repair and candidate comparison evaluation

This report covers the implementation and probe fixtures in
`3c630e133f3c9ecc49a3579eaa2ef6364c43ea11`.
The two code stacks were reviewed and committed as `0f63382`; the four
relocatable frozen-position fixtures were committed as `3c630e1`.

The full gate passed after implementation: 209 Python tests, all Rust suites,
the LuaJIT bridge smoke test, and `git diff --check`. The revision-338 real
driver test verified that the archived FinishWithGreedy response reports both
the overlapping U13 and 121-character U45 reason defects in one repair prompt,
does not forward the invalid batch, and executes the corrected batch from
revision 338 to 340 with intact NDJSON/SQLite hashes and links.

Eight native Luna probes then ran once on the pre-change client (`271f857`) and
once on the repaired client (`0f63382`), using the same four restored model
boundaries. All reached their bounded terminal boundary with no infrastructure
failure. Repair probes used one injected frozen draft plus native repair calls;
that fixture input is excluded from native call totals.

| Version | Case | Boundary | Native calls | Queries | Result |
|---|---|---:|---:|---:|---|
| baseline | repair | 15 side turns | 2 native + 1 injected | 3 | corrected repair accepted |
| current | repair | 15 side turns | 2 native + 1 injected | 3 | corrected repair accepted |
| baseline | guards | 49 side turns | 3 | 4 | capped after legal boundary |
| current | guards | 49 side turns | 2 | 4 | capped after legal boundary |
| baseline | bat | 3 side turns | 3 | 4 | capped after legal boundary |
| current | bat | 3 side turns | 4 | 5 | capped after legal boundary |
| baseline | resignation | 17 side turns | 3 | 4 | continued and capped |
| current | resignation | 17 side turns | 4 | 4 | continued and capped |

The probe evidence is descriptive. It does not establish that either version
made a better tactical choice. All eight logs were imported into
`tmp/probes-20260907/history.sqlite`; the catalog contains 8 games and 25 model
requests, with `PRAGMA integrity_check=ok` and zero foreign-key errors.
Repair and guard archives are under `tmp/probes-20260907/`; bat and resignation
archives are under `/tmp/probes-20260907/` because their supervisors used an
isolated temporary root. Their original logs, checkpoints, sidecars, and native
artifacts remain intact.

## Final three-game cohort

All games used `big_battle_6`, Undead versus Undead, 300 gold, model side 0,
single-batch turns, requested `gpt-5.6-luna` at high effort, and a 50 completed
side-turn cap. Artifacts are isolated under
`tmp/luna-final-20260907/seed-{2001,2002,2003}/`.

| Seed | Outcome | Completed model turns | Completed side turns | Model calls | Queries | Invalid / repairs | Annotation coverage |
|---:|---|---:|---:|---:|---:|---|---|
| 2001 | Infrastructure failure during draft review; no winner | 5 | 10 | 24 | 30 | 0 rejected / 2 action + 1 review repair | 12 valid action responses |
| 2002 | Luna win; winner side 0 | 11 | 21 | 30 | 44 | 0 rejected / 2 action repairs | 11/11 submitted |
| 2003 | Luna win; winner side 0 | 18 | 36 resolved | 52 | 69 | 0 rejected / 1 repair | 18/18 submitted |

Seed 2001 failed because the model's proposed FinishWithGreedy referenced
dead model-side units during draft review. The client recorded the typed
`draft_review_error`; it did not silently turn this into a draw or rerun it.
The native runtime did not report confirmed model or reasoning settings;
requested values are recorded separately. Transport retries are preserved in
the per-game journals. The final catalog is
`tmp/luna-final-20260907/history.sqlite`, with 3 imported games, 34 side-turns,
106 model requests, 34 action batches, `PRAGMA integrity_check=ok`, and zero
foreign-key errors. Since the failed run has a `model_error` rather than a
terminal record, the importer correctly marks it incomplete; the raw log is
the authority for its failure classification.

These three games are too small and confounded by one infrastructure failure
to support a win-rate or improvement claim. They do show that the corrected
repair path handled the archived error in controlled tests, while native Luna
still produced at least one invalid tactical handoff and one invalid review
candidate in the full cohort.
