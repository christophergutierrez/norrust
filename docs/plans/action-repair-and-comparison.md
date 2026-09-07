# Action repair and concrete candidate comparison

## Objective and scope

Make the existing repair useful, then test whether comparing concrete alternatives
improves decisions at observed failure positions. Finish with three parallel Luna
games against Greedy. This document is the implementation plan; creating it does
not start coding or paid model runs.

The reference implementation is `2f71e761fd0aa78745a5e41079e679ed52739006`.
Evidence is in `tmp/luna-cohort-20260906/seed-{2001,2002,2003}/`:

- Seed 2002, revision 338: the initial response both delegates and holds U13,
  and gives U45 a 121-character hold reason. The repair removes the overlap but
  fails the undisclosed 120-character reason limit. The reported index 3 is the
  action index, not the position of the bad hold.
- Seed 2001, revision 608: three healthy corpses remain assigned to the keep
  screen, with vague release conditions despite distant enemies.
- Seed 2003, revision 78: Luna describes expected damage as guaranteed and
  exposes its bat for a small attack. The opponent subsequently damages it.
- Seed 2003, revision 386: resignation cites material and income deficits
  without establishing that recovery routes are closed. This is insufficient
  explanation, not proof that continuing would win.

Keep the action/decision/agenda schemas and engine rules. Reuse the existing
checkpoint loader, client, `preview_batch`, `query_bounded_comparison`, request
archives, and SQLite importer. No new planner, generic validation framework,
tactical scoring service, tournament framework, mandatory attack quota, or
automatic editing of player orders. Do not add an explanation-only model call
or increase call budgets. Keep the tactical guide at or below its current
10,908 UTF-8 bytes by replacing wording rather than appending another checklist.

## Execution and commit rule

- [x] Write this plan before implementation.
- [x] Commit the plan before beginning Stack 1 (this document's initial commit).
- [ ] Implement stacks in order. Each stack includes behavior, documentation,
  focused tests, a real client/driver test, and a commit before the next stack.
- [ ] When execution is authorized, use Luna at medium effort for bounded coding
  assignments. The parent owns review and fixes. Parallelize independent tests
  or documentation; give the shared client file one owner at a time.

For each code stack, run `python3 -m tools.fast_check` and `git diff --check`.
The full gate must build the current driver and execute the new integration
tests without skips. Assert state changes and persisted evidence, not only
helper return values or the presence of wording. Record the source commit,
commands, test counts, and actual result here or in the final report. A failed
gate is not completion; fix the failure and rerun the affected checks and gate.

## Stack 1 — One repair exposes the complete handoff problem

Primary files: `tools/llm_client.py`, `docs/LLM_CLIENT.md`,
`docs/DEVELOPMENT.md`, focused action-repair tests, and
`tools/fixtures/decision_positions/` with its provenance README.

Implementation:

1. Collect independently detectable `FinishWithGreedy` validation errors across
   groups and holds before rejecting that action. Report duplicates, overlaps,
   bad shapes/types, and reason lengths with exact zero-based field paths.
   For the archived response, report both the U13 overlap and
   `actions[3].holds[7].reason: 121 characters; maximum 120` in the first repair.
   Include both conflicting paths for an overlapping ID. Handle malformed
   containers without exceptions or cascading invented errors; explain the
   enclosing shape error where child checks cannot be performed safely.
2. Keep the existing validator entry point and `ValueError` repair flow. Scope
   aggregation to the selective-finish structure; do not rewrite every action
   validator. Bound error output, and state explicitly if further errors are
   omitted. Do not silently truncate reasons, drop holds, or change delegation.
3. State selective-finish limits in the canonical action contract, including
   the 120-character reason limit and disjoint held/delegated IDs. Match the
   implementation's character counting; do not describe this as a byte limit.
   Keep the explanation requirement in existing reason/expected/risk fields.
4. Deliver these errors through the existing bounded repair path with its
   original prompt, inspection context, and final live-state reminder intact.
   Keep malformed actions separate from nonfatal annotation problems.
5. Commit the actual failed response and a relocatable revision-338 checkpoint
   with source path, source hash, board hash, game identity, and relocation
   procedure. Preserve the ignored original archive unchanged.

Acceptance:

- [ ] The exact archived initial response reports the U13 overlap and U45
  length violation together. The recorded repaired response reports only its
  remaining length violation. No error confuses action and hold indices.
- [ ] Focused cases cover reason lengths 119/120/121, non-ASCII characters,
  non-string reasons, malformed containers, duplicate IDs, and overlap. The
  valid 120-character boundary remains accepted and actions remain unchanged.
- [ ] A deterministic backend receives both actionable errors in one repair,
  returns a corrected annotated envelope, and the real client/driver accepts
  and executes it from revision 338. Verify the resulting unit positions,
  attack/finish events, and changed revision against the submitted actions.
  The invalid proposal must cause no engine mutation.
- [ ] There is exactly one syntax-repair call; any existing draft-review call
  is counted separately and justified by the actual flow. A second invalid
  response still ends as model-invalid within existing budgets.
- [ ] Exact prompt/response hashes, final annotations, request ID, submitted
  orders, and before/after revisions survive NDJSON and a fresh SQLite import.
  Cross-check terminal failure classification against the raw log: the current
  importer can call a `model_error`-ended run incomplete. Do not turn that into
  an unrequested catalog migration or count it as a gameplay draw.
- [ ] Parent review, full gate, and diff check pass. Commit code, fixture,
  tests, and documentation together. Record this hash as the probe baseline.

## Stack 2 — A concrete alternative reaches execution and recorded evidence

Primary files: existing preview handling and rendering in `tools/llm_client.py`,
`docs/LLM_CLIENT.md`, `docs/LLM_TACTICAL_PLAYBOOK.md`, focused comparison tests,
and small fixtures/tests in `tools/fixtures/decision_positions/`.

Implementation:

1. Route the existing player-requested `preview_batch` through the existing
   bounded comparison helper. Retain its one/two candidate action-array schema;
   do not introduce another tool or mode field. This intentionally changes the
   player tool from exchange-only forecasts to a labeled sampled comparison
   through at most one Greedy opponent response. Update its documentation.
   The engine's ordinary forecast mode remains available to existing internal
   consumers. Reuse existing rollout rendering and policy/seed/coverage labels.
2. Replace the generic recommendation to reconsider with a concise instruction:
   when a consequential choice is uncertain, compare the proposed complete
   action batch with one specific legal alternative. For a hold, consider a
   concrete contribution elsewhere; for an attack, consider retaining or
   repositioning the unit. Explain the important difference using existing
   decision fields. Do not require previews of routine moves or every unit.
3. Keep the existing automatic draft review and its current triggers, call cap,
   and baseline. It already compares against `EndTurn`, which runs an automatic
   sweep and is not a stationary hold. Label that baseline honestly. Make its
   existing final-response instruction ask for the relevant difference between
   the shown branches rather than treating confirmation as evidence of review.
   Do not add another automatic candidate generator or review round.
4. Keep comparison facts explicitly hypothetical and tied to the originating
   revision and candidate index. One sampled reply is not a probability or a
   guarantee. Candidate invalidity or missing coverage must remain visible.
   Revised final orders may be legal without matching either candidate; record
   that accurately rather than attaching another candidate's result to them.
5. Keep immediate standalone resignation legal without an extra call. It is
   not a preview candidate. If unsure, the player may compare legal continuation
   plans; it need not prove hopelessness to the parser. Evaluate its factual
   explanation separately from action legality.

Freeze these four cases after successful driver restoration, before native
probes. Store only needed relocatable checkpoints, responses, and provenance;
reuse Stack 1's fixture rather than copying it:

| Case | Source | Required restored boundary | Question to test |
|---|---|---|---|
| Repair | seed 2002 | 14 completed side turns, revision 338 | Can one repair resolve both known structural errors? |
| Guards | seed 2001 | 48 completed side turns, revision 608 | Do current threats justify the specific guards and release conditions? |
| Bat | seed 2003 | 2 completed side turns, revision 78 | Is the small attack worth its post-move exposure and lost village role? |
| Resignation | seed 2003 | 16 completed side turns, revision 386 | Does the explanation assess a concrete recovery route using live facts? |

Acceptance:

- [ ] Every fixture's initial revision, side-turn count, roster, positions,
  HP, gold, and board hash match its manifest. Refuse an opening/revision-0
  substitution. Tests run without the original ignored archives.
- [ ] A real client/driver test requests two distinct legal candidates from
  a restored guard or bat boundary, receives their sampled opponent responses,
  chooses a final annotated action, and executes it. Verify both preview inputs,
  their observed consequences, unchanged live state/RNG after preview, and
  the final action's actual engine consequences. Do not require live combat
  to equal the preview's separately seeded sample.
- [ ] Checks cover one/two candidates, invalid candidate reporting, rejection
  of three candidates and repeated preview requests, and absent coverage.
  A forced backend failure is a typed error, not fabricated safe results.
- [ ] Instrumented tests prove the comparison is charged to existing tool and
  query budgets, does not add a separate explanation call, and preserves the
  existing model-call ceiling. Resignation still needs just its own response.
- [ ] The exact delivered prompt contains one final live-state reminder after
  tool/review/repair context. Selected and revised final orders keep their own
  annotations and request links through execution and SQLite import. Verify
  candidate/revision association directly in raw records where the catalog
  does not have a structured field.
- [ ] Maintained action/preview examples pass the real parsers, stable tactic
  IDs remain intact, and the guide is at most 10,908 UTF-8 bytes.
- [ ] Parent review, full gate, and diff check pass. Commit the complete stack
  before paid probes. Record its hash as the comparison version.

## Final phase — Frozen-position probes, then three parallel Luna games

This is the last phase. It produces evidence and a committed evaluation report;
it does not silently become another coding or prompt-tuning cycle.

### A. Eight bounded decision probes

Run the four cases once on the Stack 1 baseline and once on Stack 2: eight
native Luna/high probes total. Use separate clean worktrees/drivers and fresh
native sessions for the two committed versions. Restore the same checkpoint
and bounded transcript in each pair, with the explicit budgets and backend
settings listed in part B below.
Preserve each version's client-generated prompt unchanged. For the repair case,
replay the frozen invalid draft through the real repair entry point so both
conditions receive the same failure; the repair response is native Luna output.
Label that injected draft as recorded fixture data and distinguish it from
new native requests in call and usage totals.
For the other cases, allow the player to choose using its canonical prompt; do
not supply the preferred answer or force tool use outside the client contract.

Stop each probe after one accepted model boundary or a typed failure/resignation.
If the existing cap also runs an opponent boundary, record it explicitly and
compare equal observation stages. Do not count transcript history as new calls.
Use the existing fixture pattern or one small cohort-specific launcher; no
general experiment service. Each probe owns its log, checkpoint directory,
session sidecar, request journal, stdout/stderr, and prompt/result artifacts.

Before running, freeze a small rubric: legal execution; both repair issues
resolved; exact expected-damage versus guaranteed-damage distinction; named
current threat supporting a guard; concrete alternative contribution; and a
recovery assessment beyond aggregate disadvantage. Record executable choice,
actual opponent effects where available, calls, measured usage, and elapsed time.
An accurate explanation or revised choice alone is not a tactical success.
Keeping a guard or resigning can be justified; do not require a predetermined
action to pass. Mark unassessable evidence unknown.

- [ ] Eight attempts exist with verified starting boundaries and immutable
  version/settings manifests. No rerolls, case substitutions, or omitted failures.
- [ ] Import their original logs into a fresh SQLite catalog and inspect it
  before archive-level analysis. Cross-check model errors against raw terminal
  evidence, payload hashes, request links, integrity, and foreign keys.
- [ ] Report all eight cases with the frozen rubric. This small experiment is
  descriptive, not a win-rate estimate. Do not tune the guide after seeing it.
  Infrastructure/protocol defects must be resolved before full games; poor
  tactical choices alone do not block the requested final cohort.

### B. Three full games using parallel Luna subagents

Read `docs/LLM_CLIENT.md` and start exactly three Luna subagents in parallel,
one supervisor/player session per game. Use the reviewed Stack 2 source unless
a required fix has been reviewed, fully tested, committed, and clearly recorded
as a different version. Do not introduce an unrequested stronger-model cohort.

Freeze identical settings for all three games:

- Seeds 2001, 2002, and 2003; `big_battle_6`; Undead versus Undead; 300 gold;
  model side 0; Greedy with the normal driver recruitment policy; single-batch.
- Requested native backend `gpt-5.6-luna`, high effort; `--max-turns 50`.
  This means 50 completed side turns, approximately 25 model turns, not 50 rounds.
- Existing limits: eight model calls and four player tool calls per model turn;
  300-second query budget, 900-second model timeout, 840-second native timeout,
  and 2,100-second turn timeout. Pass the same explicit settings for each run.
- Fresh isolated logs, checkpoints, request journals, native session sidecars,
  and stdout/stderr. Preserve exact canonical prompts and requested settings.
  Do not enable timeout-to-Greedy fallback. Do not restart, resume, or replace a
  failed original attempt; preserve and report its failure.

- [ ] All three original processes reach an observed exit and terminal outcome
  or typed failure. A model-invalid run counts as a failed attempt, never a draw.
- [ ] Import completed original logs into a fresh final catalog. Verify request
  and submitted-annotation coverage, prompt/result hashes, source and driver
  hashes, request/revision links, retries, fallbacks, and database integrity.
  Report runtime model/effort as unknown when native evidence does not confirm
  them. Do not infer private reasoning from decision annotations.
- [ ] Review decisions and executed consequences against the same issues as the
  probes. Report whether Luna used comparisons, interpreted replies correctly,
  released justified guards, and explained resignation with current facts.
- [ ] Commit `docs/experiments/action-repair-and-comparison-evaluation.md` and
  complete this plan's checkboxes with actual evidence. Include all eight probe
  results and a three-game table with outcome/failure, completed side turns,
  model turns, calls, measured tokens, wall time, invalid responses/repairs,
  comparison use, and valid submitted annotations. Preserve raw ignored
  artifacts and link their locations; distinguish them from committed fixtures.
  Keep all failures visible and avoid claiming improvement from three games.

Completion means two reviewed and fully tested code stacks committed, eight
bounded probes reported, and three original parallel games reported with an
honest performance table. Wins are an outcome to measure, not a condition for
marking the implementation plan complete.
