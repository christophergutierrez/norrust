# GLM decision efficiency and harness corrections

Status: stacks 1–5 implemented; offline integration and milestone-6 launch preparation
recorded in [the execution report](../experiments/glm-decision-efficiency.md).
Paid pilot and full-game model validation remain unrun. The requirements below
are retained as the implementation and evaluation acceptance contract.

Source inspected: `342d1b5d824d342a37db563eab5052f93110c596`.

## Outcome and scope

Make routine actions straightforward: the player understands the rules, retains
its objective, obtains authoritative movement options cheaply, and stops
deliberating once it has a useful legal action. Preserve detailed reasoning for
consequential combat and recruiter safety.

Implement five independently usable, cumulative stacks. Every stack includes
its player contract, execution path, evidence, documentation, and tests before
its commit. A sixth milestone evaluates the result. Do not build separate
database, engine, and UI phases that become usable only at the end.

The initial two-tier design uses the existing agenda: select one objective,
then execute small steps toward it. No second LLM, mandatory planning call,
new planning language, hidden automatic strategist, or replacement harness.
Keep batch/coordinate play working. Do not change gameplay balance, default
decision mode, output escalation, or provider sampling/reasoning settings.

## Evidence and issue ledger

Diagnostic evidence is in
`tmp/quick-play-glm-tactics-73w8wceu/ANALYSIS.md`, with request mapping in
`calls.json` and original prompts/provider replies in `requests/`.
This is an opening/round-two diagnosis, not a completed-game strength result.
Preserve these files; do not overwrite their prompts or recompute their facts
using new rules.

| ID | Finding | Classification and destination |
|---|---|---|
| B1 | Choices-mode response instructions omit the explicit partial-step/observe/continue explanation and full agenda schema. | Confirmed contract bug; stack 1. |
| B2 | Four attempted agendas with multiple active tasks were discarded; the next prompt did not explain the error. | Confirmed memory/feedback bug; stack 2. |
| B3 | `recruit_cap` is calculated from open placements OR vacatable occupants. It is not a recruitment-per-turn cap. | Misleading field and lossy summary; stack 1. |
| B4 | Prompt omits fresh-recruit readiness, capture timing, income/upkeep facts, and precise round progression. | Missing contract facts; stack 1, each backed by engine tests. |
| B5 | `next_time_of_day` means next round, although the imminent opponent may act in this round. Threat calculations already project the opponent correctly. | Presentation ambiguity; stack 1. |
| P1 | GLM repeatedly revisits safe placements, JSON shape, speculative mechanics, and already settled choices. | Observed behavior; stopping-rule hypothesis in stack 3. |
| C1 | Friendly inspection takes one model tool response per unit; base choices may offer no movement handles. Request 6 guessed paths for 22 moves and failed preflight. | Control cost/gap; stack 4. |
| C2 | `toward_hex` movement delegation is coupled to `FinishWithGreedy`, which ends the turn. | Missing intermediate control; stack 5. |
| H1 | Generic Fireworks calls rebuild one user message; reasoning-only conclusions are not persistent memory. | Possible amplifier; fix existing agenda first. Native provider history deferred. |
| H2 | GLM's publisher documents default maximum reasoning effort; the adapter omits the setting. | Possible amplifier, effective provider value unknown. Explicit effort experiment deferred. |

Request 4 used 37,178 reasoning tokens while performing legal deployment and
recruitment. Request 6 used 47,968 before an invalid batch. These establish
specific failure cases, not a required improvement percentage or proof of one
root cause. Missing reasoning, usage, or boundary evidence remains unknown.

## Working rules and common completion gate

Read `AGENTS.md`, `docs/LLM_CLIENT.md`, `docs/DEVELOPMENT.md`, and
`docs/MODEL_BAKEOFF.md`. For catalog analysis also read `docs/AGENT_GUIDE.md`
and `docs/GAME_HISTORY.md`, and inspect SQLite before individual archives.

Before implementation, record the current commit and clean/dirty status, and
run `python3 -m tools.fast_check` once to establish the baseline. Do not modify
an active game's checkout or artifacts: use an isolated worktree if a game is
still using this checkout. Build and launch each experiment with explicit paths
to its own checkout and driver.

For **every stack**:

1. Reproduce its behavioral failure with an appropriate fixture. Prefer a real
   driver plus scripted responder for protocol/state regressions. Avoid tests
   that merely repeat implementation strings.
2. Implement the smallest change below, including maintained callers and docs.
3. Run focused tests, then `python3 -m tools.fast_check` on the integrated stack.
   This builds the driver and supplies artifact paths to Python/Lua tests.
   All required tests must pass; skipped real-driver coverage is not acceptance.
4. Check prompt/cache invariants where affected: stable rules before the fixed
   prefix boundary, volatile facts after it, unchanged canonical prompt delivery,
   correct guide/prompt hashes. Do not claim a cache hit from equal hashes.
5. Record commands, results, fixture outcomes, and remaining limitations in
   `docs/experiments/glm-decision-efficiency.md`. Commit only that completed
   stack; name its commit in the handoff. Do not mark paid evaluation complete
   using synthetic usage or scripted play.

Suggested focused suites below supplement the full gate; they are not an
exhaustive substitute. Update maintained names and remove superseded player
interfaces together. Historical archives remain immutable; historical readers
may still need to understand old evidence.

## Stack 1 — Complete and truthful player contract

**Result:** both response encodings describe the same execution semantics, and
the opening no longer requires the player to infer basic rules or field meanings.

Primary files: `tools/llm_client.py`,
`norrust_core/src/bin/greedy_driver.rs`, `norrust_core/src/game_state.rs`,
`docs/LLM_CLIENT.md` and the affected prompt/driver tests.

Implementation:

- Assemble shared response rules once in `prompt_for`: partial continuation,
  final-only behavior, intent, complete agenda schema/limits, and annotation
  requirements. Leave only the encoding-specific envelope/handle instructions
  in the choices/coordinates branches. Match focused-mode annotation behavior
  to its actual validator; do not introduce a second annotation policy.
- Show remaining model/tool/partial budgets in all initial and follow-up
  requests, including repair requests. Distinguish another model call from
  advancing the side turn. Budget exhaustion must not invent a new ending rule.
- Replace live `recruit_capacity`/`recruit_cap` with separate
  `open_recruit_hexes` and `vacatable_castle_units` counts. Neither is a total
  recruitment cap or a guarantee that all vacancies are simultaneously usable.
  Keep affordability and actual recruitment legality authoritative. Missing
  data stays unknown, not zero. Do not add the two counts into a new cap.
- Rename live `next_time_of_day` to `next_round_time_of_day`; expose
  `next_opponent_time_of_day` from the same authoritative phase projection used
  for threats. Do not approximate it in Python. Update compact/full displays,
  maintained consumers, and tests; no duplicate live aliases.
- Add concise `ENGINE_RULES` facts, verified against source and new
  `test_documented_rule_*` fixtures: new recruits can act immediately; villages
  change ownership on the occupying side's EndTurn and remain owned afterward;
  the newly active side receives two gold per owned village; no imagined
  Wesnoth upkeep/base-income rule; rounds advance after both sides act.
  If source contradicts this description, fix the proposed wording, not gameplay.

Measurable acceptance:

- A scripted player recruits, moves a recruit, and recruits again in one side
  turn under both encodings; no opponent action occurs between partial batches.
- More than six recruits can be produced when affordability and legal vacating
  allow it. Full, partly full, and unavailable recruitment states have correct
  independent counts.
- A village remains neutral during partial movement, captures at the correct
  boundary, persists after departure, and pays the correct side at activation.
- Side-0 and side-1 fixtures across a time-of-day transition show the correct
  imminent opponent time and next-round time; threat forecasts agree.
- Valid shared agenda examples and partial replies parse and execute in both
  encodings; final-only requests still reject partial-only submissions.
- Repair and inspection prompts accurately reflect consumed budgets.

Focused suites: `tools.test_player_contract_integration`,
`tools.test_focused_turns`, `tools.test_action_choices_integration`,
`tools.test_prompt_cache_layout`, and Rust documented-rule/driver tests.

Commit: `fix(harness): make player rules and live summaries unambiguous`.

## Stack 2 — Preserve task memory and report rejected metadata

**Result:** an invalid agenda cannot silently erase the player's working
objective or leave it unaware that its proposed memory was not accepted.

Primary files: `tools/llm_client.py`, `tools/turn_agenda.py`, existing checkpoint
and request-journal code, `docs/LLM_CLIENT.md`.

Implementation:

- Keep the existing validator: at most one active task, full replacement,
  bounded sizes. Do not silently pick an active task, merge conflicting plans,
  or turn agenda prose into executable actions.
- On invalid agenda metadata, retain the last committed agenda, execute any
  otherwise-valid actions normally, and include a bounded correction in the
  next model request: which constraint failed and that the prior agenda remains.
  Link the feedback to the originating request/revision; expose it in the log.
- Retain that correction until a valid replacement is committed, or until the
  side turn ends. If the bad agenda occurred in the ending response, deliver it
  once at the next own-side request. Persist pending feedback through existing
  checkpoint/resume state; clear superseded errors. Never accumulate a transcript
  of all past metadata errors.
- Publish a proposed valid agenda only after its associated actions commit.
  Rejected/rolled-back action batches must not update memory. No extra LLM call
  solely to fix optional metadata.
- Use existing `active_task`, intent, and committed action summaries for the
  two-tier loop. Display the objective prominently in volatile context; retain
  global recruiter threats, economy, and whole-army summary. Do not hide the
  board or force a planning-only response when no agenda exists.

Measurable acceptance:

- Real-driver fixture: valid agenda A -> legal action plus invalid two-active
  agenda B -> next prompt retains A and explains B -> accepted valid C replaces
  A and clears the correction.
- The invalid metadata adds zero model calls and does not prevent the legal move.
- Invalid actions plus otherwise-valid C cannot publish C. A discarded draft
  cannot overwrite the finally accepted response's agenda.
- Resume before feedback delivery preserves it; tool follow-ups, partial
  boundaries, and the next-turn case obey the lifetime above.
- Every active-task display derives from committed metadata and live unit facts,
  including dead units, rather than a simulated or rejected candidate state.

Focused suites: `tools.test_turn_agenda`, `tools.test_focused_turns`,
`tools.test_request_recovery`, `tools.test_request_journal`, and relevant
real-driver integration tests.

Commit: `fix(harness): retain agenda state and surface validation feedback`.

## Stack 3 — Give routine decisions an explicit stopping rule

**Result:** a short guide describes when to act, when to inspect, and when deeper
reasoning is worthwhile. This remains a separate commit so its effect can be
compared without changing controls or reasoning effort.

Primary files: `docs/LLM_TACTICAL_PLAYBOOK.md`, `docs/LLM_CLIENT.md`, and existing
guide/annotation/prompt tests. Preserve all existing S/T rule IDs.

Near the top of the guide, use:

> Routine decisions are simple. Use supplied legal options, choose a useful
> action, and execute promptly. Good enough is sufficient for recruitment, safe
> movement, and uncontested village capture. Reserve detailed analysis for
> recruiter safety, contested combat, and irreversible losses.

Near the bottom, use:

> Have a useful action with established legality and acceptable risk? Submit it
> now. Inspect a specific missing fact when necessary. Reconsider only when new
> evidence changes the decision; do not restart the whole plan.

Integrate these additional ideas into existing rules rather than appending a
second checklist:

- Choose one immediate objective; perform its next useful step. Replan when it
  completes, is blocked, or material facts change. Recruiter emergencies interrupt.
- Uncertain legality: inspect. Similar useful legal alternatives: choose one.
- Once a routine option meets the objective with acceptable risk, stop searching.
  Consequential combat still warrants comparing a legal alternative.
- Use documented mechanics and supplied facts; do not import another game's rules
  or repeatedly reconstruct paths already settled by authoritative options.
- Replace T7's universal hold essay with: "Hold for a concrete purpose. Explain
  only consequential idle units or deliberate saving." Align the corresponding
  prose in `LLM_CLIENT.md`; executable hold reasons and schema limits still apply.
- Routine explanations stay brief but satisfy the selected annotation contract.
  Never trade established legality for speed or label all combat "simple."

Measurable acceptance:

- Complete guide UTF-8 size is no more than 110% of the pre-stack guide. Record
  before/after sizes; remove redundant prose if needed. Keep each behavioral
  instruction in one place; the opening principle and closing stopping rule
  are complementary, not verbatim duplicates.
- Rule-ID extraction, annotation validation, and canonical delivery tests pass;
  the archived guide hash changes and matches the delivered bytes.
- Human checklist confirms the decision-speed ideas above and retained recruiter safety,
  simulation/live distinction, and legal-action requirements. Do not write brittle
  tests demanding the exact English sentences.
- Do not claim reduced internal reasoning from shorter final answers. That is
  evaluated with actual reasoning-token evidence in milestone 6.

Commit: `docs(tactics): bound routine deliberation and simplify hold guidance`.

## Stack 4 — Inspect a small friendly group in one response

**Result:** the model can inspect units assigned to its objective without one
model response per unit or manually reconstructing their paths.

Primary files: `tools/llm_client.py`, `tools/action_choices.py`, corresponding
inspection/repair/choice tests, `docs/LLM_CLIENT.md`.

Implementation:

- Use one player-facing friendly inspection contract:
  `{"tool":"inspect_units","unit_ids":[12,13]}`, one to eight unique friendly
  living IDs. One ID is supported by this same interface. Replace the old
  player-facing `inspect_unit` entry point in maintained prompts, responders,
  tests, and docs. Retain the driver's singular query as an internal primitive,
  not a second advertised player interface.
- Implement bounded Python fan-out over the existing authoritative driver query
  at one live revision. No new Rust query framework is necessary. Validate the
  complete request first; errors produce no partial success disguised as a full
  result. Reads mutate neither live state nor RNG.
- Return existing per-unit legal origins and danger information, grouped by unit,
  and union their choice handles using existing revision-bound identity rules.
  Do not invent a second movement representation or tactical ranking algorithm.
- Charge one player tool call and its actual underlying query time; maintain
  existing per-turn limits. Apply the same path to normal and repair responses.
- Explain that active-task units are a useful inspection scope. No automatic
  inspection of the entire army, mandatory agenda, or extra planner call.

Measurable acceptance:

- Inspect eight units with one model tool request, then submit a coherent legal
  partial move batch using returned options. Exactly one tool allowance is spent.
- One ID works; empty, duplicate, nine-ID, enemy, dead, malformed, and stale-revision
  requests fail clearly. No inspection consumes movement, RNG, or a side turn.
- Handles from all inspected units work at the returned revision and fail when
  stale. Sequential destination conflicts still receive ordinary validation.
- An empty base choices list does not force a finish: inspection supplies movement
  choices, accepted moves commit, and the player receives another fresh request.
- Repair can use the same tool without resetting budgets or silently ending play.

Focused suites: `tools.test_action_choices`,
`tools.test_action_choices_integration`, `tools.test_repair_execution`,
`tools.test_focused_turns`, and real-driver inspection tests.

Commit: `feat(harness): batch friendly inspections for focused tasks`.

## Stack 5 — Delegate movement without ending the turn

**Result:** "deploy these recruits toward this objective, return control, recruit
again" is an executable operation. This is the smallest additional group control;
it is not a new strategic AI.

Primary files: `norrust_core/src/bin/greedy_driver.rs`, `norrust_core/src/ai.rs`,
`tools/llm_client.py`, relevant action parsing/annotation/history reporting code,
`docs/LLM_CLIENT.md` and driver/integration tests.

One new action:

```json
{"action":"MoveGroupToward","unit_ids":[12,13],"col":8,"row":6}
```

Implementation contract:

- Accept one to eight unique living friendly IDs and one in-bounds rally hex.
  Process IDs in submitted order. Explicitly listed recruiters are permitted,
  with the same loss-of-keep consequences as manual movement; never include
  unlisted units automatically. The target may be occupied: it is a direction.
- Reuse `choose_toward_hex_destination` from existing `toward_hex` delegation.
  Compute each next unit's move after earlier moves. Choose only legal destinations
  strictly closer to the target, with the existing deterministic tie-break.
  Spent units or units with no improving destination produce an explicit no-move
  result. Report moved and skipped units, not an invented success claim.
- Movement only: no attacks, recruiting, promotions, greedy sweep, EndTurn, or
  opponent activation. Geometric progress is not proof of safety, screen quality,
  or a route around obstacles. Document these limits prominently.
- Validate the whole action shape/ownership before mutation and use the existing
  transactional batch path. Preflight and execution share expansion semantics;
  rollback preserves earlier accepted partial batches.
- Coordinate envelopes can invoke the macro in both encodings; do not add a
  combinatorial menu of group handles. Existing final-only rules still apply.
- Preserve authored macro -> expanded engine moves -> request/revision lineage
  in existing event/history accounting. Generated moves must not be mislabeled
  as individually authored moves or inflate task-success statistics. Reuse the
  established macro provenance convention; extend an enum only if necessary.

Measurable acceptance:

- End-to-end recruit -> group deploy -> recruit again -> explicit finish fixture:
  first three operations remain in one model side turn, return fresh state,
  leave the opponent untouched, and are replayable after SQLite import.
- Tests cover occupied targets, competing destinations, reversed submission
  order, blockers/ZOC, spent units, no-progress units, explicit recruiter,
  invalid/enemy IDs, duplicate IDs, and out-of-bounds targets.
- A failed later action rolls back the current batch only. Successful movement
  never generates attacks or a boundary. Old finishing macros retain their tests.
- Event provenance, request linkage, annotation index before expansion, and
  idempotent history import are verified through the real driver.

Focused suites: Rust AI/driver protocol tests, `tools.test_handoff_execution`,
`tools.test_handoff_prompt`, `tools.test_decision_annotations_integration`,
`tools.test_game_events`, `tools.test_game_history`, and new group-movement cases.

Commit: `feat(harness): allow nonfinal movement toward an objective`.

## Milestone 6 — Controlled evaluation and final handoff

**Result:** reproducible evidence distinguishes working plumbing from improved
model behavior. Deliver a report even if the changes fail to improve GLM.

First extend the existing provider-free task fixtures with the regressions above.
Run the existing 24-cell matrix and the new cases. Do not create a new benchmark
framework or use synthetic token counts as performance measurements.

Prepare three explicitly different treatment revisions:

- A: end of stack 2, with the old guide (contract/memory fixes only).
- B: end of stack 3 (A plus stopping-rule guide).
- C: end of stack 5 (B plus batched inspection and nonfinal group movement).

Compare A/B first, then B/C. Keep the same GLM model, omitted effort/sampling
settings, budgets, opponent, factions, map, seeds/checkpoint bytes, and decision
mode/encoding. Requested default is not measured runtime effort. Do not change
temperature or set effort to low during these comparisons.

The existing bakeoff rejects differing source/guide fingerprints within one
matched cohort. Respect that invariant: use a separate worktree for each
treatment and a separate cohort for each treatment/position pair (repeats share
the same seed and checkpoint), then an explicit cross-revision analysis keyed
by trial IDs.
Record intentional source/guide/tool differences. Do not disable fingerprint
validation, call these identical configurations, or force these treatments into
the runner's existing A/B/C decision-mode comparison labels.

Paid evaluation is a bounded execution task, not part of writing this plan:

1. Use four task families: recruitment/deployment, uncontested village capture,
   threatened recruiter, and coordinated combat; two fixed positions each.
   Reuse existing fixtures where their success predicates fit. Run two trials
   per position/treatment: 16 cells per treatment, 48 total if both comparisons
   proceed. Use predeclared seeds and keep failed cells in the denominator.
2. Set `max_game_total_tokens=250000` per cell and `turn_timeout=1800` seconds
   per side turn, using maintained budget controls. Bound each task's side-turn
   count in its manifest; the turn timeout is not a whole-game timeout. Record
   enforcement limits: a
   physical call can overshoot the cumulative budget. Keep existing output
   escalation unchanged. Stop launching paid cells after 12 million recorded
   tokens across the pilot; report remaining cells as unrun. Price the manifest
   with verified dated rates before launch. Do not auto-retry the whole pilot.
3. Follow `LLM_CLIENT.md` usage accounting for every cell. Store prompt, source,
   driver, guide and requested-settings hashes; physical call IDs; provider usage;
   committed events; repairs; and final/unfinished status. Use the existing
   passive diagnostic recorder
   (`tmp/quick-play-glm-tactics-73w8wceu/recording_backend.py`) for provider
   reasoning, verify canonical prompt delivery, and keep its artifacts per cell.
   Copy/configure it for each checkout without changing the maintained adapter's
   payload or output; verify its import path resolves to that checkout. Retain
   its source/hash with the evaluation artifacts. Never put auth headers in receipts.
   Missing provider reasoning is unknown, not evidence of no deliberation.
4. Report per-cell task success, recruiter survival, premature finish, invalid
   actions, rejected agendas, inspections, calls, time to first useful committed
   action, total/ reasoning tokens, cache coverage, and cost. Report both failed
   and successful task costs. Compute per-action values from committed events,
   distinguish macros/delegated work, and never count rejected proposals as moves.
5. Review the first three completed calls plus every invalid/length-limited call
   in each cell using the user's four categories: useful/expected; unjustified;
   understandable but poor; missing information/control. Record request IDs and
   concise supporting excerpts. If raw reasoning is absent, report that coverage
   gap and assess only visible actions/explanations.

Pilot promotion criteria, specified before seeing results:

- Candidate treatment succeeds in at least as many of the 16 cells as its
  predecessor; it adds no recruiter-loss failure in the defense positions.
- Invalid-batch and premature-finish counts do not increase.
- Median reasoning tokens among paired successful tasks decline by at least
  25%, with at least eight usable pairs and complete reasoning coverage for those
  pairs. Report all-cell tokens/cost and failures alongside this conditional metric.
- Missing evidence or too few successful pairs makes the efficiency result
  inconclusive. A small pilot is a screening result, not statistical proof.
- If the guide fails the gate, retain verified correctness fixes, report the
  result, and revise only the unproven guidance before further paid runs. Do not
  silently tune wording across cells or change effort to obtain a pass.

After a passing pilot, run two full-game seed pairs for the retained predecessor
and candidate (four games), cap 50 completed side turns and 1 million total tokens
per game, with identical other settings. Report winner/cap/failure, cost, and all
coverage gaps; do not claim a strength ranking from four games. If budget or
credentials prevent this, mark model validation incomplete and leave concrete
launch artifacts, not a claim of completion.

Final artifacts: `docs/experiments/glm-decision-efficiency.md` with commits,
test results, treatment manifest locations, SQLite game IDs, metrics and evidence
links; `tmp/glm-efficiency-exec/HANDOFF.md` with completed/pending work and exact
reproduction commands. Keep raw provider archives outside versioned documentation.
Commit the fixtures/report/docs as
`test(harness): evaluate decision efficiency and record evidence` after the
common gate. Clearly separate implementation-complete from model-validated.

## Parallel work instructions

An implementation coordinator owns `tools/llm_client.py`, shared prompt assembly,
integration, final docs, full gates, and commits. Workers use separate worktrees
or submit patches; do not concurrently edit this shared file in one checkout.

| Worker packet | Independent work | Dependency and handoff |
|---|---|---|
| Engine facts | B4 engine fixtures; B5 authoritative phase labels and driver tests. | Start immediately; deliver to stack 1 integrator. |
| Contract/memory | B1/B3 prompt contract and B2 feedback/checkpoint integration. | Coordinator owns shared client; stacks 1 then 2. |
| Guide | Draft stack 3 wording, size comparison, preserved-ID checklist. | Can draft alongside stack 1; merge only after stack 2. |
| Inspection | Stack 4 validator/query helper and focused fixtures; provide a client integration patch. | Branch from stack 2 interface; rebase onto stack 3 before gate. |
| Movement | Stack 5 driver macro, transactional/event tests; provide Python integration requirements. | Can develop after stack 1 driver facts land; integrate after stack 4. |
| Evaluation | Fixture positions, success predicates, isolated manifests and offline evidence analysis. | Prepare in parallel; live cells use frozen passing commits only. |

Do not assume all packets run simultaneously. With three workers, prioritize
engine facts, guide drafting, and fixture preparation while the coordinator fixes
the contract/memory path. After integration, assign inspection and movement work.
Never parallelize edits to the same worktree's driver or client. Never commit an
unfinished stack just because one worker finished its layer.

Each worker returns: owned files, exact test commands/results, behavior implemented,
remaining integration changes, and known limits. The coordinator resolves shared
contracts and runs the full gate after integration, not merely worker test logs.

## Explicitly deferred

- Sending provider-native tools, retaining raw reasoning in subsequent prompts,
  and constructing a persistent Fireworks conversation. These are separate
  transport experiments; full history may preserve mistakes and expand context.
- Model-specific effort/temperature tuning or a general parameter registry.
  Test explicit GLM effort only after the prompt/control comparison, with
  provider support verified and requested versus reported values distinguished.
- Automatic task generation, hard task-based information hiding, extra model
  tiers, new databases, dashboards, or tactical search algorithms.
- Claims that top/bottom placement or shorter prose inherently improves play.
  The placement and stopping rules are hypotheses evaluated by milestone 6.
