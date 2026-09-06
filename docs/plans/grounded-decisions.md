# Grounded decisions and selective intervention

## Goal and limits

Make the player distinguish the current board from simulated outcomes, interpret
resistances correctly, and avoid holding healthy units without a concrete purpose.
Evaluate behavior before running three full games. Evidence motivating this plan:
[player-contract-recovery-evaluation.md](../experiments/player-contract-recovery-evaluation.md).
Baseline at planning time: `c57441018aaaec37863448eedeb6dec25c3e23d5`.

This document is a plan only. Its commit does not start implementation or games.

Use two complete, separately tested implementation stacks, followed by bounded
behavioral probes and a final three-game cohort. Each stack includes its prompt,
execution/evidence tests, and maintained documentation; do not commit unfinished
renderer, storage, or test layers separately.

KISS/YAGNI constraints:

- Keep engine rules, action JSON, decision annotations, agenda schema, stable
  tactic IDs, and SQLite schema. No new rationale fields or private-reasoning capture.
- Reuse the current client, canonical prompt generation, supported native backend,
  checkpoints, logs, catalog, and tests. No general evaluation framework, dashboard,
  production A/B switch, compatibility aliases, or new persistent telemetry system.
- No additional production model calls or engine queries just to explain or
  validate prose. Do not rewrite model orders, force attacks, prohibit justified
  holds, force recruitment, or make resignation conditional on another model call.
- Replace ambiguous wording instead of accumulating another long tactical essay.
  Do not remove useful preview facts merely to make a model mistake impossible.
- Preserve historical archives. Keep experimental artifacts under an ignored
  directory, with concise committed manifests/results sufficient to reproduce them.

## Phase 0 — Reviewable plan

- [x] Commit this plan before changing implementation files.
- Acceptance: every implementation stack below has a user-visible behavior,
  an execution/evidence test, a full verification gate, and its own commit.

## Stack 1 — Authoritative facts through every model request

**End-to-end behavior:** engine observation and read-only forecasts → unmistakably
scoped canonical prompt → ordinary model response → validated engine actions →
exact request/response/revision evidence in the existing log and SQLite catalog.

### Changes

Primary files: `tools/llm_client.py`, `tools/test_llm_client.py`,
`tools/test_player_contract_integration.py`, `docs/LLM_CLIENT.md`,
`docs/LLM_TACTICAL_PLAYBOOK.md`, and `docs/DEVELOPMENT.md`.

1. Give each candidate's hypothetical results a clear simulation block labeled
   `SIMULATION — NOT EXECUTED`, with its candidate index, originating revision,
   forecast/sampling mode, coverage, and existing assumptions. Label hypothetical
   rosters, gold, casualties, and villages within that scope. A forecast without
   a sampled rollout must retain that distinction; unknown coverage stays unknown.
   Current unit inspections/legal origins and simulated consequences must not be
   presented as one undifferentiated state.
2. After all appended tool, draft-review, and repair context, place one compact
   authoritative live-state reminder immediately before the response instruction.
   Derive it from the latest engine observation, never from a preview or model
   text. Include revision, controlled side, current gold for both sides, unit/HP
   totals for both sides, friendly unit IDs, and recruiter IDs/HP/positions.
   Refer to the existing BOARD block for the full roster; do not duplicate it.
3. State that queries have executed no actions; a revised complete batch replaces
   the draft and starts from the live revision. Preview-created units and preview
   casualties are hypothetical. A resignation explanation must distinguish live
   facts from projected threats; a bad sampled continuation is not proof that all
   alternatives fail. Preserve the existing immediate Resign action.
4. Replace the compact TYPE line's ambiguous signed `resist=` values with readable
   incoming-damage descriptions: `arcane: takes 40% more damage`,
   `cold: takes 60% less damage`, and `0: unchanged damage`. These describe the
   supplied base modifier before other combat effects; engine forecasts remain
   authoritative. Preserve raw engine fields in diagnostic output and archives.
   Label missing data unknown rather than inventing a neutral resistance.
5. Centralize the final live reminder at the model-request boundary so initial,
   inspection follow-up, review, and repair paths cannot silently omit it. Use
   the same final prompt bytes for delivery, hashing, and logging. After an
   accepted partial batch, refresh from the new observed revision. A rolled-back
   batch must keep the original revision and facts.

### Measurable acceptance

- [x] Parse the generated live reminder and compare every field with a fixture
      observation containing deliberately conflicting simulated totals and IDs.
      Check initial, inspection, draft review, malformed-review repair, pre-submit
      action repair, post-submit action repair, and accepted-partial paths.
- [x] Each request contains exactly one final live reminder after its appended
      context; no stale revision, preview-only ID, simulated HP, or simulated gold
      enters that reminder. Retained tool results and budgets are still present.
- [x] Positive, negative, zero, and missing resistance cases render correctly;
      generated canonical prompts include the actual rendered descriptions.
      Damage tenths and basis-point regressions continue to pass.
- [x] A deterministic real-driver fixture requests a preview that recruits units,
      then returns a replacement batch with a different recruitment count.
      Assert actual gold, roster, and recruit events reflect only the submitted
      replacement. Repeated read-only previews leave the live revision unchanged.
- [x] A second fixture presents a sampled losing continuation, then submits a
      legal alternative or resignation. Assert simulation casualties never mutate
      the board; standalone resignation executes without another review or turn.
      Check observed/event state, not a preview's hypothetical output.
- [x] Import the fixture logs into temporary SQLite. Decompress and compare the
      exact delivered prompt, response, final annotations, submitted orders, request
      identity, and revision. Reimport twice with identical rows/payloads; verify
      integrity and foreign keys. Missing/invalid explanations still cannot cause
      metadata-only retries or invent rationale.
- [x] Run `python3 -m tools.fast_check` and `git diff --check`; all checks pass,
      with real-driver tests executed rather than skipped. Review the full diff,
      fix defects, and commit this complete stack. Record the commit as variant A.

## Stack 2 — Concrete interventions, purposeful holds, routine delegation

**End-to-end behavior:** concise guide → existing expected/risk and hold reasons →
authored interventions and selective finish → actual movement/combat events →
auditable claims linked to the final response.

### Changes

Build on stack 1. Primarily edit `docs/LLM_TACTICAL_PLAYBOOK.md` and the matching
client instructions/documentation; extend the existing integration tests where
needed. Preserve all factual grounding and evidence behavior from variant A.

- In S1/T4/T7, state a coherent order of work: choose recruitment or justified
  savings, protect the recruiter, make important attacks/retreats/advances, assign
  specific guards, and delegate remaining routine eligible units when appropriate.
- A held group must have a concrete current job (for example, block a named
  attack origin, retain a healing village, or protect a wounded unit). Use the
  existing `reason`, `expected`, and `risk` fields to name that job and the attack,
  movement, or pressure forgone. “Keep formation” alone does not explain the job.
- Use current danger and legal options to decide exceptions; do not prescribe
  an attack quota, a fixed recruit composition, or mandatory full-army sweeping.
  An attack's value includes retaliation, exposure, coordinated kills, and the
  enemy's response. Attack count alone is not a quality score.
- Keep FinishWithGreedy semantics explicit: group IDs are delegated, held IDs
  and omitted IDs are unswept; earlier authored moves and recruitment vacates
  still occur. DoneWithImportantMoves delegates eligible routine units and
  excludes the recruiter/critical units, without guaranteeing their safety.
- Keep a single concise handoff instruction. Remove contradictory blanket
  “hold everything” or unconditional “always sweep” guidance if encountered.
  Do not add a parser that judges tactical prose or automatically releases holds.

### Measurable acceptance

- [x] Extract the maintained example envelope from the generated prompt and
      validate its actions, annotations, and agenda through the actual parsers.
      Existing final-response linkage and no-extra-call tests still pass.
- [x] Real-driver execution proves a concrete authored retreat, a distinct held
      eligible unit, and a distinct delegated healthy unit behave as ordered.
      Establish units through accepted setup/partial actions; obtain real IDs
      from the resulting state instead of predicting recruitment IDs.
- [x] Include a justified-hold counterexample: holding an eligible guard does not
      become automatic delegation merely because routine units can act. Assert
      positions at the model finish using state or correctly decoded event
      coordinates; distinguish the opponent's subsequent effects.
- [x] Persist the fixture's concrete job and opportunity-cost explanation through
      the final response, NDJSON, and SQLite unchanged. Confirm that descriptions
      themselves do not create actions or holds.
- [x] Production model/query budgets and response schemas remain unchanged.
      Canonical guide text stays no longer in UTF-8 bytes than variant A's guide.
- [x] Parent review, `python3 -m tools.fast_check`, and `git diff --check` all pass.
      Commit the complete stack and record it as variant B. Both A and B are
      reproducible clean revisions, not runtime feature flags.

## Phase 3 — Fixed recorded-position probes before full games

Read `docs/AGENT_GUIDE.md` and `docs/GAME_HISTORY.md`, inspect the recorded SQLite
catalog first, then select six cases from the last cohort. Read `docs/LLM_CLIENT.md`
before invoking native players. Store the case definitions and exact launch
commands in `docs/experiments/grounded-decisions-probes.md` before running them.

| Case | Starting evidence | Question to measure |
|---|---|---|
| Opening replacement | Seed 2003, revision 0, opening review | Does the player distinguish hypothetical recruits, enemy roster, and remaining gold from the current board? |
| Resignation review | Seed 2002, final observed turn/review | Does it distinguish live army totals from sampled future casualties, whether it resigns or continues? |
| Resistance interpretation | A recorded Skeleton/Adept engagement | Are resistance and vulnerability claims consistent with the supplied incoming-damage descriptions? |
| Broad defensive hold | Seed 2002's earlier material advantage | Does the player give held groups concrete jobs and consider useful attacks or delegation? |
| Justified protection | A recorded critical retreat or recruiter threat | Does the policy retain a necessary guard/retreat instead of delegating indiscriminately? |
| Recruitment capacity | A recorded keep with gold and six open spaces | Does it understand auto-vacating capacity, or provide a concrete reason for saving gold? |

For each case record source game/request/revision, checkpoint hash or reproducible
initial-game command, actual expected facts, and a short manual scoring rubric.
Verify the restored live board matches those facts before treating a branch as
that case. If the exact archived boundary is unavailable, document the mismatch
and choose a verifiable nearby case before freezing the manifest. Preserve the
original conflicting draft as a deterministic regression fixture in stack 1;
do not silently force it into a live player response.

Run each case twice for A and twice for B: **24 one-model-turn attempts total**.
Use existing checkpoint resume/fresh-start commands and client-generated prompts.
For a checkpoint, account for any pending opponent turn when selecting the cap:
permit exactly one new model decision turn and at most its opponent response.
Keep case state, seed, mode, checkpoint-provided continuity, and budgets matched
between variants. Give every attempt a fresh native session and unique artifacts;
never reuse a session containing another variant's instructions. Request Luna/high,
with at most four model calls and two model-requested inspections per case. Keep
native/client timeout settings consistent with the supported backend example.

Use isolated worktrees for A/B execution. Prefer an experiment-local launcher and
small manifest over a new maintained CLI. No arbitrary prompt editing through a
file backend, hidden model coaching, or retries until a preferred move appears.

Acceptance and selection:

- [x] All 24 attempts are accounted for, including infrastructure failures,
      missing explanations, budget exhaustion, and unexercised decisions. Archive
      canonical prompt bytes/hashes, requests, responses, revisions, and events.
- [x] Score actual claims about live facts separately from explicitly hypothetical
      claims. Target zero preview-as-live claims and zero resistance-sign errors;
      silence is unassessed, not proof of understanding. Record both error counts
      and the number of assessable decisions.
- [x] Measure legal batches, statement/command agreement, jobs and opportunity
      costs supplied for held groups, actual attacks and retreats, damage/losses,
      recruiter survival, calls, and wall time. Label subjective tactical judgments
      and sampled outcomes; do not turn more attacks into an automatic pass.
- [x] Prefer B for the final cohort only if it introduces no observed increase in
      grounding errors, no loss of the justified-protection behavior, and at least
      one concrete improvement in the broad-hold case's job/alternative reasoning
      or useful execution. Otherwise retain A and record the policy hypothesis as
      unsupported. An unassessable comparison does not establish improvement.
- [x] Review and commit the probe report with the selected revision and reasons.
      Do not alter thresholds or cases after seeing results. These small probes
      diagnose behavior, not statistical significance. Behavioral misses are
      recorded results; they do not authorize open-ended tuning or replacement runs.

Deterministic correctness failures block progression until fixed, tested, and
committed. Model behavioral misses remain explicit limitations in the report;
complete the bounded comparison and select A or B as above. If B is rejected,
revert only its policy changes on the working branch, run the full gate, and
commit the selected A behavior before the final cohort. Preserve B's commit and
all probe evidence. Never discard unrelated work to select a variant.

## Final phase — Three games via parallel Luna subagents

This phase starts only after both stack gates and the committed probe review.
No full games are run before it.

- [x] Freeze the selected clean revision. Build the release greedy_driver and
      record the source commit, driver hash, guide hash, and requested settings.
- [x] Start exactly three parallel Luna subagents, each supervising one native
      Luna/high player using `tools.codex_backend`. Seeds 2001, 2002, and 2003;
      `big_battle_6`; Undead versus Undead; 300 gold; model side 0; single-batch;
      resignation enabled; **max 50 completed side-turns** (at most 25 per side).
- [x] Isolate every game's NDJSON, checkpoints, native session sidecar, request
      journal, prompt/result artifacts, stdout/stderr, and launch/exit records.
      Preserve each complete canonical prompt. Do not change code or policy
      during the cohort or silently replace an unsuccessful attempt.
- [x] Supervise all three attempts to terminal completion or a documented concrete
      failure. Distinguish wins, losses, resignations, caps, model-invalid results,
      and infrastructure failures. Winning is not a completion requirement.
- [x] After completion, import a fresh final SQLite catalog and inspect it before
      raw archives. Check exact prompt/response/annotation/request/revision links,
      full guide delivery, integrity/foreign keys, and two idempotent reimports.
      Keep requested model/effort separate from runtime evidence. Missing usage,
      private reasoning, and endpoint state data remain unknown.
- [x] Review live-versus-simulation claims, resistance interpretation, recruitment,
      held jobs, actual authored/delegated activity, recruiter survival, and
      resignation evidence. Compare with the previous same-seed cohort without
      claiming causal proof from three stochastic games.
- [x] Commit `docs/experiments/grounded-decisions-final-evaluation.md` and update this
      plan. Include a table of outcome, model turns, calls, wall time, annotation
      coverage, authored/delegated/opponent attacks, and a specific finding per
      game; report evidence coverage and source/artifact paths.

The plan is complete when the tested implementation stacks, bounded probe report,
and final three-game evaluation are committed, all attempts are accounted for,
and the performance table has been reported to the user.
