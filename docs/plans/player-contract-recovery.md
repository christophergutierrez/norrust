# Player contract recovery: implementation and three-game evaluation

## Scope

Repair four observed interface failures before changing tactical policy: malformed
agenda envelopes, recruiting only six units despite available macro capacity,
misreading damage tenths as HP, and describing holds without encoding them.
Keep the existing actions, annotation format, engine rules, and stable tactic IDs.
No compatibility aliases, natural-language hold parser, new review calls, tactical
scoring framework, or automatic changes to model orders. Explanations remain
self-reports. A hold check means comparing stated intent with actual finish orders
and observed movement; it does not infer intent from arbitrary prose in production.

## Phase 0: plan

- [x] Record scope, ownership, measurable gates, and evaluation conditions here.
- [x] Commit the plan before coding starts.

## Phase 1: one complete implementation stack

Use three Luna agents at medium effort with disjoint ownership. Parent reviews,
fixes integration defects, runs the complete gate, and commits the whole stack.

1. Prompt agent owns `tools/llm_client.py` and `tools/test_llm_client.py`.
   Restore an exact valid actions/decisions/agenda example, including agenda's
   `tasks` and integer `holds`, task fields and allowed statuses. Explicitly state
   that agenda/annotation prose creates no normal engine holds. Explain selective
   `FinishWithGreedy` allowlists/holds and the automatic sweep of other finishes.
   Explain that RecruitBatch can recruit beyond initially empty castle hexes by
   driver-assisted vacating, subject to affordability and actual capacity, with
   no invented IDs or fixed roster recommendation. Label every compact forecast
   `e` and focus damage in tenths of HP and every probability in basis points;
   include 24 = 2.4 HP and 6400 = 64%. Preserve numeric payloads and canonical
   prompt delivery. Add regressions for generated prompts and all relevant cards.
2. Contract/integration agent owns `tools/turn_agenda.py`, its tests, and a new
   `tools/test_player_contract_integration.py`. Ensure malformed metadata remains
   nonfatal even for invalid field types/UTF-8; preserve strict object-shaped agenda.
   Use real-driver tests to prove RecruitBatch count 12 exceeds six initial castle
   spaces, spends gold, creates units and vacate events; query validation must not
   mutate live state. Prove selective finish keeps a named eligible unit fixed
   through the model finish while a delegated unit can move; distinguish later
   opponent effects. Exercise canonical prompt -> valid annotated response with
   agenda -> accepted orders -> agenda memory on the next prompt -> log/SQLite.
   Also exercise a malformed agenda with legal actions and no extra metadata-only
   repair call. Do not change the engine just to make tests pass.
3. Documentation agent owns `docs/LLM_CLIENT.md`,
   `docs/LLM_TACTICAL_PLAYBOOK.md`, and `docs/DEVELOPMENT.md`. Concisely document
   exact agenda shape, macro capacity/auto-vacate tradeoff, numerical units, and
   executable holds. Keep tactic IDs and avoid speculative strategy rewrites.

Acceptance milestones:

- [x] Exact prompt agenda example parses successfully through the real parser;
      malformed values are logged/ignored without preventing legal play.
- [x] Prompt/card regression demonstrates unambiguous 2.4 HP and 64% scales.
- [x] Real driver recruits at least 12 from six starting castle spaces, with
      matching gold/unit/vacate effects; read-only validation preserves revision.
- [x] Real-driver hold/delegation test proves the model-finish positions, and
      agenda persists only after the accepted response, through the next prompt.
- [x] Deterministic integration log imports into SQLite with intact prompt,
      response, annotation, request and revision links; repeated import is stable.
- [x] Parent reviews all diffs and fixes issues. `python3 -m tools.fast_check`
      and `git diff --check` pass; record results and commit the complete stack.

Validation: `python3 -m tools.fast_check` passed 234 Rust tests, 182 Python
tests, LuaJIT bridge smoke, and `git diff --check`. Log:
`tmp/player-contract-fast-check.log`. Parent review fixed incorrect selective
finish wording, restored forecast vector meanings, staged agendas only from
final submissions, and replaced weak tests with live-state and exact-payload
assertions. No engine rules changed.

## Phase 2: frozen implementation, three parallel Luna games

- [x] Read client and analysis routing docs; build release greedy_driver from the
      reviewed clean commit, recording source and driver/guide hashes.
- [x] Launch exactly three Luna subagents supervising native Luna/high players,
      seeds 2001/2002/2003, big_battle_6, Undead vs Undead, 300 gold, side 0,
      single-batch, resignation enabled, max 50 completed side-turns (25 per side).
      Isolate NDJSON, checkpoints, native session, request journal, artifacts,
      stdout/stderr and launch/exit records. Preserve canonical prompts unchanged.
- [x] Account for all attempts to terminal completion or documented failure.
      No silent replacement games or policy/code changes during the cohort.
- [x] Inspect imported SQLite before individual archives. Verify integrity,
      idempotence, payload/annotation linkage and evidence coverage. Treat absent
      runtime settings, usage, reasoning and endpoint states as unknown.
- [x] Review agenda acceptance, first-turn recruitment/gold, damage interpretations,
      stated versus encoded holds, actual movements/attacks, and review revisions.
      Compare these with the prior same-seed cohort without claiming causality.
- [x] Commit `docs/experiments/player-contract-recovery-evaluation.md` and mark
      this plan complete. Report a table of result, completed turns, model calls,
      wall time, annotations, and specific behavior per game. Winning is an
      observed result, not a condition for finishing this plan.

## Completion record

- Plan commit: `d4ddfee`; reviewed implementation/game source: `c6486e8`.
- Post-game test-only coordinate replay correction: `24d4c11`; all three
  player-contract integration tests and `git diff --check` pass.
- Cohort: `tmp/player-contract-recovery-20260906T195814Z/`. All three native
  Luna/high attempts completed normally: one recruiter-kill win, two resignations.
- Final catalog: 93 exact native prompt/response pairs, 33/33 valid submitted
  annotations, zero failed requests or rejected batches, passing integrity and
  repeated-import checks. Missing endpoint states/runtime settings remain unknown.
- Results: [player-contract-recovery-evaluation.md](../experiments/player-contract-recovery-evaluation.md).
  No policy or gameplay code changed during the cohort.
