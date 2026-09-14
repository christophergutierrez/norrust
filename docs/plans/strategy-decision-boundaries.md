# Strategy decisions with executable choices

Status: planned; no implementation or paid evaluation performed by writing this document.

Baseline: `cb9a85bb932b57964c123ccbf9d3728ddbdbc492`. Check current HEAD and
unrelated changes before starting. This plan supersedes neither historical game
evidence nor the completed strategy/routine implementation. Build on that work.

## 1. Problem and intended result

The strategy player currently receives one broad response union at every
exception. It can answer current-board contact with `set_policy`, even though
the engine checks that contact before executing policy work. The replacement
changes no board state and the same exception returns. Separately, contact
anywhere stops all routine execution, including potentially independent work.

The recorded failure is:

- Game `glm-strategy-20260914T141221Z:glm-strategy`, source baseline above.
- Six `contact` exceptions, `stage: current_state`, at revision 64.
- Five completed calls in each of two player turns; the second turn did not
  finish. The eleventh logical request was blocked by the token ceiling.
- 224,384 measured tokens, ten policy installations, one completed player turn.
- This demonstrates an existing controller weakness, not a proven regression
  from the preceding parser and route-label changes.

After this work, code chooses the kind of decision needed. The LLM receives
relevant facts, applicable responses, and a small set of executable tactical
choices. The engine still owns legality and calculations. The model chooses
tradeoffs. Routine execution may continue a narrowly defined class of movement
while contact exists, but cannot spend gold or conduct combat automatically.

Success means useful execution with fewer wasted calls. A cheap automatic turn
finish, surviving until a cap, or a scripted model passing tests does not prove
better playing strength.

## 2. Scope and non-goals

Keep the driver protocol, transactional executor, checkpoint/commit proof,
request journal, usage accounting, SQLite catalog, and bounded watchdog.
Keep strategy opt-in; do not change focused mode or the default player mode.

Use one player model. Add no planner/critic LLM, autonomous coordinator, vector
store, framework, or new service. The controller described below is Python
code. Tactical facts and candidate generation are Rust code.

Do not build a general battle planner, multi-unit search, new combat simulator,
or a second pathfinder. Reuse `tactics.rs`, existing legal-move functions,
transactional batch validation, and existing action execution. Candidate
generation in this plan stops at a single unit's move or move-and-attack.

Do not auto-recruit, attack, move recruiters, vacate castles for recruitment,
or automatically accept combat risk while contact is unresolved. Expanding
these capabilities requires later evidence. Do not add risk-slider settings.

Keep the parser recovery already implemented. Do not grow the tactical guide
to explain around invalid interfaces. Replace the generic exception prompt
with the appropriate decision brief and update maintained callers together.
No compatibility aliases for superseded development interfaces. Preserve all
historical archives and make new reporting tolerate absent fields as unknown.

## 3. Read these files, then stop exploring unless needed

1. `AGENTS.md`, `docs/LLM_CLIENT.md` strategy and usage-accounting sections,
   `docs/FIREWORKS_RUNBOOK.md`, and `docs/DEVELOPMENT.md`.
2. `tools/llm_client.py`: `strategy_call_model`, `strategy_step`,
   `strategy_install`, strategy submission/commit adoption, and resume handling.
3. `tools/routine_policy.py`: validation, response/result types, prompt
   rendering, progress, and `run_scripted_strategy_turn`.
4. `norrust_core/src/routine.rs`, `norrust_core/src/tactics.rs`, and the
   `routine_next`/validation dispatch in `norrust_core/src/bin/greedy_driver.rs`.
5. `tools/test_strategy_routine_stack3.py`, existing strategy integration tests,
   `tools/test_strategy_response_recovery.py`, `tools/strategy_comparison.py`,
   and `tools/model_bakeoff.py`.

For historical analysis, read `docs/AGENT_GUIDE.md` and `docs/GAME_HISTORY.md`,
then query SQLite before opening individual request archives. The failure
archive is under `tmp/glm-strategy-20260914T141221Z/recording/glm-strategy`.
If ignored evidence is absent, use a checked-in deterministic fixture; do not
fabricate the historical state or claim to reproduce its exact position.

## 4. Ownership and execution order

There are four sequential stacks. Each must work through the real client and
driver, pass its focused acceptance and the full gate, and be committed before
the next stack is integrated. Never call a stack complete from worker tests.

Within a stack, up to three workers can run in parallel in isolated worktrees:

| Owner | Files and responsibility |
| --- | --- |
| Rust worker | `routine.rs`, new `routine_decision.rs` if needed, `tactics.rs` only for reusable fact helpers, module registration, driver dispatch, Rust tests |
| Python worker | New `tools/strategy_decision.py`, `routine_policy.py`, focused Python unit tests |
| Integration owner | `llm_client.py`, real-driver tests, docs, fixtures/report integration, full gate and commits |

Freeze the small JSON contract for each stack before workers start. The
integration owner writes a sample packet in the handoff and resolves contract
questions. Workers must not invent alternate field names or edit another
owner's files. A worker may prepare fixtures/tests against the agreed contract
while the other layer is unfinished, but a fake interface is not acceptance.

Keep one production decision implementation. The scripted helper must call its
shared validation/controller functions; do not add a parallel test-only state
machine. If the helper cannot share the behavior cleanly, migrate its affected
tests to the real client and remove the unused orchestration instead of
maintaining two implementations.

Record in `tmp/strategy-decision-exec/HANDOFF.md`: active stack, baseline and
worker commits/worktrees, contract choices, completed checks, remaining work,
and exact next command. Update it after each integration. It must distinguish
implemented, offline-accepted, and model-evaluated status.

## 5. Contract shared by the stacks

### Decision packet

The Python controller builds one packet per model decision from revision-proven
engine evidence. Keep raw engine results in the existing log. The packet has:

```json
{
  "decision_id": "controller-issued-id",
  "state_revision": 64,
  "decision_kind": "tactical",
  "incident_key": "canonical-content-hash",
  "reason": "contact",
  "evidence": {"stage": "current_state"},
  "allowed_kinds": ["act", "finish_turn", "resign"],
  "options": [],
  "coverage": {"facts": "complete", "options": "not_generated"}
}
```

This example is Stack 1. Stack 2 adds `choose` when options exist. Initial
selection uses `decision_kind: policy`; exceptions use `tactical`, `promotion`,
`policy`, or `facts_unavailable`. Do not create a configurable routing system.

`decision_id` identifies an issued packet and changes when it is reissued.
Log the issued packet before dispatch. A selected option must resolve from that
exact durable packet, including after resume; never resolve an old option ID
against a newly generated menu. Reissued menus invalidate outstanding old IDs.
`incident_key` excludes policy/install IDs, request IDs, remaining budgets,
prose, and option ordering. Canonicalize reason, stage/cause, and the affected
unit/target/destination IDs or coordinates. Current-state contact identifies
the sorted involved units/targets, not a rally point. Include the game and
controlled side-turn identity when tracking a repeated incident.

Decision identity, incident identity, and board revision have different jobs.
Do not use one as a substitute for another. A new decision ID is not progress.

### Responses and legality

For Stack 1, retain the existing strict response shapes and add contextual
validation before installation/submission:

| Request | Applicable responses |
| --- | --- |
| Initial policy or completed objectives | `set_policy`, `act`, `finish_turn`, `resign` |
| `contact/current_state` | `act`, `finish_turn`, `resign` |
| Contact caused by a proposed destination/placement | `set_policy`, `act`, `finish_turn`, `resign` |
| Blocked recruitment, unavailable route, invalid assignment, missing scout | `set_policy`, `act`, `finish_turn`, `resign` |
| Promotion pending | `act` containing the required legal advancement before dependent work, or `resign`; do not offer a finish the engine rejects |
| Required facts unavailable | Existing bounded inspections/re-query or explicit interruption; do not invent safe options or retry indefinitely |

Intersect this table with existing `final_only` and engine legality rules.
Do not remove `resign` accidentally, recommend resignation from simulated
death, or auto-resign. Prompt and validator use the same allowed-kinds value.
Keep the board overview and installed objectives available for global judgment;
do not hide the rest of the battle when presenting a local incident.

All chosen/custom actions still pass schema, current-revision and transactional
engine validation. Inspection cannot reset call limits or an incident loop.

## Stack 1 — Decision-specific handoff and bounded ineffective responses

### Build

1. Introduce the packet/routing/contextual validation functions in
   `tools/strategy_decision.py`. Keep this module independent of transports.
   `llm_client.py` owns dispatch, durable logging and execution.
2. Replace `current_contact`'s boolean-only result with deterministic contact
   facts: involved friendly IDs, enemy IDs when known, and whether the trigger
   is an available attack or projected exposure. Preserve the existing contact
   trigger behavior in this stack. Reuse existing engine fact calculations.
   Full coverage and unknown facts must be distinguishable.
3. Render one specific question and its applicable responses. For current
   contact, say explicitly that changing policy moves no unit and cannot clear
   the current-board pause. For a proposed unsafe move, explain that replacing
   the objective can prevent that proposed step.
4. Reject a village policy with zero existing scouts AND zero scout-role
   requested recruits before installation. Enforce the same rule in Python and
   Rust policy validation, including fixed-policy input. Do not reject a valid
   future scout queue merely because no scout exists yet. Existing death/loss
   handling for scouts remains a runtime concern.
5. Add a deterministic ineffective-response allowance. At a fixed side-turn,
   revision and incident, permit at most one corrective follow-up after an
   invalid contextual response OR an installed replacement that reproduces
   the same incident. The next ineffective response ends as
   `budget_interrupted / strategy_no_progress`. Share the existing one-repair
   allowance; do not accidentally allow one syntax repair plus one contextual
   repair plus another incident repair. A successful read-only inspection is
   not an ineffective response, but remains charged to existing call limits.
6. A policy edit may legitimately change the incident at the same revision.
   Track the set of encountered incidents at that revision so A→B→A cannot
   acquire a fresh allowance. The existing per-turn/global caps remain active.
   A committed board action can invalidate this exact-revision guard; do not
   claim it detects all move-back-and-forth loops across revisions.
7. Log packet issuance, contextual rejection, recurrence and terminal stop
   using the existing journal. Reconstruct consumed allowance from durable
   records on in-place resume. A checkpoint branch inherits the relevant
   parent evidence when available; never silently reset an unresolved incident
   because its policy ID changed. Missing proof follows existing unknown-resume
   handling. No new SQLite table is needed for this stack.

### End-to-end acceptance

- Real driver at a contact checkpoint: policy replacement, then another policy
  replacement produces at most two decision responses at that incident, no
  installation/action from the rejected policies, and a typed interruption.
- The same first invalid response followed by a legal tactical action commits
  exactly once. Confirm prompt and validator both exclude `set_policy` there.
- Proposed-move contact: a changed objective that avoids the incident remains
  accepted. This guards against a blanket `contact` prohibition.
- A→B→A at unchanged revision does not renew the original incident allowance.
- Crash/resume after consuming the allowance cannot buy another attempt;
  replayed journal rows do not consume it twice.
- Empty scout roster plus army-only recruits and villages rejects before any
  recruitment. Existing scouts or a scout-role recruit permits the policy.
- Two player turns can each make five calls with an eight-call cap; nine calls
  in one turn cannot dispatch. Token exhaustion remains a separate stop.
- Keep malformed JSON, recovered-but-illegal action, stale revision, committed
  recruitment deduplication, promotion, final-only and no-sweep tests passing.

Run the full gate, update client docs, commit this executable stack as
`Route strategy decisions and bound ineffective replies`.

## Stack 2 — Small executable tactical choices

### Build

1. Extend the existing revision-pinned `routine_next` exception evidence with
   bounded tactical options for current-state contact. Use an internal Rust
   module if this keeps `routine.rs` readable. Do not introduce a second query
   round trip merely to retrieve the same facts. The entire computation remains
   under the driver's query/time accounting.
2. Choose one primary friendly actor deterministically: threatened recruiter
   first, then lowest-ID threatened friendly unit, then lowest-ID unit with an
   attack opportunity. Report other involved IDs and counts in the packet.
   This orders the menu; it does not hide other units from custom actions.
3. Offer at most four unique action options for that actor:
   - Up to two legal attack alternatives, including a legal move first when
     needed. Rank existing engine forecasts by target kill probability, then
     expected damage, then stable target/coordinate tie-breaks. Name all
     forecast fields and units; do not present expected results as guarantees.
   - Up to two legal relocation alternatives ranked by lower projected
     incoming damage, then movement cost, then coordinates. They need not be
     risk-free; show measured exposure. Exclude the current hex and no-op moves.
   - If a category has fewer options, leave the menu smaller. Do not pad it or
     silently turn the whole army over to Greedy.
4. Use existing legal origins/targets and forecasts. Cap relocation candidate
   evaluation at 16 legal endpoints, selected by movement cost then coordinates
   before expensive forecast work. Return `options_truncated` when candidates
   were omitted. Query exhaustion/unsupported forecasts are unknown, not zero.
   Omit an unavailable category and retain custom actions/inspection; a query
   timeout must use the existing typed budget/error path.
5. An option contains its ID, exact executable action array, actor/target,
   relevant cost and combat/threat facts, and coverage. Options are proposals.
   Clone-based evaluation must not mutate live state or its random-number state.
   Validate each proposed array through the same engine legality path used for
   custom actions. Do not simulate speculative combat to manufacture a certain
   outcome or write a hypothetical result as an executed event.
6. Add the strict response:
   `{"kind":"choose","decision_id":"...","option_id":"...","finish_turn":false}`.
   Require all four fields, no extras; apply existing final-only rules. Python
   expands only an option from the issued packet, verifies revision, and uses
   ordinary tactical submission. Option IDs alone never authorize execution.
7. Keep `act`, bounded inspections, explicit finish and resign as applicable
   escape paths. The brief leads with the specific question and options; it
   need not repeat every custom action example. Do not add another paid call
   that asks the model to explain its choice.
8. Record decision ID, option ID and expanded actions next to the request/batch
   linkage. A selected option is an engine-generated proposal selected by the
   model, not an automatically executed routine action. Preserve existing model
   action attribution and add descriptive proposal-source evidence. Keep raw
   prompts/replies and request-token accounting intact. Historical rows lacking
   option evidence remain unknown, not custom actions by inference.

### End-to-end acceptance

- Repeating the same query at the same state returns the same ordered actions,
  facts and option IDs; state hash/revision/RNG state do not change.
- Every offered option independently executes from the originating checkpoint
  using real transactional validation. An option invalidated by a later
  revision rejects before execution. Unknown option/decision IDs reject.
- Attack fixtures include attack-in-place and move-then-attack, with real event
  attribution and no duplicate action after crash-before-ack/resume.
- A withdrawal fixture offers a lower-exposure legal relocation. A fixture
  with no such move does not fabricate one or describe unknown exposure as safe.
- A custom legal action unavailable in the four-option menu still executes.
- In fixed acceptance fixtures the option-specific JSON is <=8 KiB, has <=4
  actions bundles, and examines <=16 relocation endpoints. Run 20 repeated
  queries per fixture; every query must finish under a 10-second query deadline
  on the development machine. Log elapsed times; reduce work if it fails rather
  than raising the gate. This is a resource bound, not a network-latency claim.
- Import an option-driven game into both test catalogs; request/action linkage,
  usage totals, role attribution and reimport idempotence remain correct.

Update the shared response contract, docs and any maintained response-kind
enumerations. Run the full gate and commit as
`Offer bounded engine-generated choices for tactical decisions`.

## Stack 3 — Continue conservative independent movement during contact

This stack deliberately does less than a general task scheduler. It changes
only routine movement under current-state contact. Stack 2 remains useful if
this optimization proves too restrictive or expensive.

### Build

1. Factor existing village/rally movement proposal generation so the executor
   can examine pending movement without executing it and without stopping at
   the first blocked objective. Reuse the existing routes, holds, scout
   assignments and progress effects. Do not copy the routing algorithm.
2. With current-state contact, scan at most eight candidate policy-directed
   moves, in existing task priority and stable unit-ID order. No automatic
   attack, recruitment, promotion, recruiter move, hold change, or finish.
   Recruiter danger or pending promotion takes priority: do not defer it to
   perform distant movement. All candidates may be rejected.
3. Accept a move only when all these conservative checks pass on a clone:
   - Its unit has no current attack opportunity and zero fully covered current
     and open projected attackers, both before and after the move.
   - All other friendly units' canonical attack-origin/target/forecast surfaces
     and incoming threat summaries are unchanged, including recruiter facts.
     Normalize ordering, not substantive fields. This rejects changes to
     blockers, target access and forecasted exposure even if aggregate damage
     happens to stay equal. If available summaries omit attacker identity,
     include that identity using existing detailed threat functions.
   - No new current-state contact participant is created; HP, gold, recruit
     progress, village ownership and holds are unchanged by the move itself.
   - The move advances an existing policy objective under existing progress
     rules. Do not add a new objective or count a mere policy rewrite.
4. These checks establish independence only under the engine's existing
   tactical forecast horizon. They are not a proof of optimal strategy. Unknown
   coverage, an exhausted query budget, or an unsupported effect prevents
   automatic continuation; never downgrade uncertainty to a pass.
5. Commit at most one accepted move per `routine_next` result through the
   existing routine envelope/progress proof. Recompute on the new revision.
   If no candidate passes, issue the tactical decision packet immediately.
   Do not retry the same scan on unchanged state. Per-turn partial/query budgets
   remain charged and cannot reset because another task was considered.
6. Log the move's policy objective, checks' coverage and before/after tactical
   signature hashes, not another complete copy of the board. Keep the deferred
   incident identifiable across revisions. Do not automatically finish while
   current-state contact still requires model judgment.

### End-to-end acceptance

- A threatened non-recruiter plus a distant eligible scout: at least one
  objective-advancing scout move commits without a model call, then a tactical
  packet is issued for the unresolved contact.
- A blocker move that changes another unit's attack access is refused even if
  no additional expected damage appears. A move that exposes a recruiter is
  refused. Unknown threat coverage is refused.
- Recruiter danger and pending promotion issue their decision before distant
  movement; no auto-recruit or auto-attack occurs during unresolved contact.
- At most eight candidates are examined. Fixed fixtures pass the same repeated
  10-second per-query deadline as Stack 2; failures require less work or a
  narrower eligible class, not larger query budgets.
- After an accepted independent move, resume adopts its progress once and
  regenerates the tactical packet at the new revision. Old option IDs reject.
- A quiet-position fixture retains prior recruitment, village capture and
  no-sweep completion behavior. An unrelated blocked objective cannot cause
  an unbounded scan or erase the pending tactical decision.

Update the documented contact/automation boundary, run the full gate and commit
as `Continue verified independent policy movement during contact`.

## Stack 4 — Acceptance matrix, model screening and operator handoff

### Offline deliverables first

Add fixtures under `tools/fixtures/strategy_decisions/` and a small report
extension in `tools/strategy_comparison.py`. Use `model_bakeoff` for real-client
launching and existing SQLite import. Do not create another runner or replace
the watchdog. Register any new command in maintained docs/tests; do not invent
an unsupported invocation in the handoff.

The matrix must cover these positions through the real driver:

| Position | Required machine-checkable result |
| --- | --- |
| Repeated current contact | Context-invalid policy loop stops within the shared correction allowance; no policy/action mutation |
| Proposed dangerous route | A valid replacement objective can remove the proposed incident |
| Favorable tactical attack | Selected legal attack commits; fixture-defined enemy HP reduction/kill is observed |
| Withdrawal | Selected legal move lowers the fixture's fully covered exposure measure without killing the recruiter |
| Independent scout movement | Scout advances its assigned objective before a model call; tactical incident remains visible |
| Blocking unit | Automatic move is refused; no hidden Greedy sweep |
| Scouts absent | Structurally impossible village policy rejects before installation |
| Resume at decision/commit boundary | No renewed allowance, stale option execution or duplicate action/recruitment |

Pin exact checkpoint hashes, actor/target IDs, initial facts and expected
predicates in the fixture manifest. Assert fixture preconditions through engine
queries so a test cannot silently stop testing its intended situation. Use the
historical revision-64 position as an additional fixture if available; convert
through maintained checkpoint tooling and retain derivation/source identity.

Reports must distinguish:

- Provider calls, logical requests, repairs, option selections and custom acts.
- Context-invalid replies and identical-incident recurrences.
- Engine/routine actions and model-selected actions; actual board effects.
- Incident resolution, tactical progress, explicit finish, and budget stop.
- Input/output/reasoning/cache fields with coverage; observer/operator usage
  remains separate. Cost needs dated rates with reasoning/output semantics.

Incident disappearance caused by changing policy is not automatically tactical
progress. Completing a turn is not sufficient for attack/withdrawal predicates.
Missing a judgment or final state is unknown/failed evaluation, never a pass.

Run fake transports over the complete matrix, verify catalog linkage and
idempotence, run the full gate, and commit
`Add strategy decision acceptance matrix and evaluation packet`.

### Bounded Fireworks screening

Writing this plan does not launch a paid trial. The future implementation
orchestrator checks the user's then-current authorization; authorization for
an already specified trial persists. Prepare the exact reviewable manifest,
dated pricing and limits before resolving any missing launch authorization.
No OpenAI/Anthropic observer credential is required; use Fireworks only.

Use GLM Flash's requested exact available Fireworks ID. Do not change reasoning
effort, temperature, model, or output-exhaustion behavior between treatments.
Baseline is the commit above; candidate is the accepted Stack 4 commit. Isolate
worktrees/binaries and every game's logs, checkpoint, journal and usage sidecar.
Provenance must match its source. Do not disable fingerprint checks to compare
the intentionally different decision contracts.

First screen four contact positions: favorable attack, withdrawal, independent
movement, and the historical loop position (use a documented deterministic
replacement if unavailable). Two repetitions per position per treatment gives
16 cells. Limit each to one controlled turn, eight logical calls, and 75,000
measured total tokens; retain the supported query/turn/output limits and set a
15-minute cell wall deadline. Alternate baseline/candidate order. Do not add
rescue attempts or retune fixtures after seeing outcomes.

The sum of soft cell token ceilings is 1.2 million. This is NOT a hard spend
bound: an in-flight physical request can overshoot its token ceiling. Before
launch, calculate the actual worst-case dollar exposure from prompt caps,
effective provider output/retry limits, dated rates and serialized launches.
Stop launching new cells when cumulative measured usage reaches 1.2 million
tokens or a user dollar budget is reached. Report incomplete cells explicitly;
do not claim a full matrix when this stop rule prevents completion. Unknown
cost cannot be reported as zero. Do not raise caps to obtain a passing result.

Record without a paid semantic observer by default. Use the maintained bounded
runner and final review once; no LLM polling every move. The controller, not the
watchdog, must catch the deterministic policy loop. Follow the authoritative
usage-accounting and import procedure in `docs/LLM_CLIENT.md`.

Screening targets, fixed before running:

1. Zero stale/duplicate/illegal committed choices and zero current-contact
   policy installations in candidate cells.
2. No candidate cell consumes more than the one corrective follow-up on the
   same unresolved incident at the same revision.
3. At least six of eight candidate cells satisfy their predeclared useful
   action predicate, and candidate success count is at least baseline's.
4. Candidate median total tokens across the same eight cells is at most 75%
   of baseline's. Include failed cells and their actual spend; never compare
   only successful candidate runs against all baseline runs.
5. No fixture-defined recruiter death or unsafe automatic move in candidate.

Treat these as a screening decision, not a statistical claim of playing
strength. A failure is a finding: stop, report it, and do not expand the paid
experiment or silently change thresholds.

For this screening, the operator launches the prepared cells serially using
one-cell manifests with the existing runner, checking compact final usage
between cells. This is sufficient to enforce the cross-cell launch stop; do
not build another campaign scheduler. Shared experiment identity and the
predeclared position/treatment/repetition key must survive the separate
launches so the report can join them. A cell's turn limit must be resolved
against its checkpoint's starting turn; do not assume `--max-turns 1` means
one additional player turn after resume. Prove the resulting boundary with a
fake-backend launch before any paid screening.

Only after passing, and within the authorized paid scope, run one matched
six-side-turn opening per treatment at seed 2038, undead mirror, gold 300,
side 0, with the runbook's 200,000-token/45-minute bounds. Compare village
ownership, army material, recruiter survival, completed turns, useful actions
and tokens. These two openings still do not establish win rate. Do not promote
strategy to default from this experiment.

Commit the honest experiment record and updated handoff after authorized runs,
including misses, stopped cells and source/coverage limitations. If paid work
is unavailable, commit the prepared packet and mark model evaluation pending;
implementation acceptance is not evidence that GLM improved.

## 6. Gate required for every stack

Run focused tests first with a freshly built real driver. Then run:

```bash
python3 -m tools.fast_check
```

This is the repository's Rust/Python/Lua headless gate and provides the actual
driver/library/dumper paths to Python tests. Do not run unfiltered tournament
suites or accept skipped driver integration tests. Report test counts, exit
status, candidate SHA and log path. Validate shell examples with `bash -n` and
resolve example manifests through the real parser without paid dispatch.

If changing protocol/response shapes, update maintained callers, fixtures,
docs and tests in that stack. Keep historical archives unchanged. Write the
stack acceptance result into the handoff, commit, then start the next stack.
After final integration, rebuild the main checkout's driver/library/dumper so
the next operator does not use a stale binary.

Required documentation updates: `docs/LLM_CLIENT.md`,
`docs/FIREWORKS_RUNBOOK.md`, relevant `docs/MODEL_BAKEOFF.md` evaluation examples,
and the fixture README. Update `AGENTS.md` only if routing changes. The runbook
must explain choices/custom actions, no-progress stops, contact continuation
limits, current source, Fireworks credentials, catalog import, and final review.

## 7. Completion checklist

- [ ] Stack 1: applicable responses, validated dependencies and durable loop bound.
- [ ] Stack 2: executable options and custom-action escape, with honest attribution.
- [ ] Stack 3: conservative independent movement, with unchanged tactical surfaces.
- [ ] Stack 4: real-driver matrix, reports and bounded evaluation packet.
- [ ] Each stack integrated, fully gated, documented and committed separately.
- [ ] Authorized model screening recorded, or explicitly pending without a quality claim.
- [ ] Main binaries current; clean task tree; Claude/other operator handoff usable.

Do not replace these deliverables with a longer tactics document, larger token
limits, an additional monitoring LLM, or a successful run that hides failures.
