# Strategy decisions with automatic routine execution

Status: implementation plan; no implementation or games are requested by the
act of writing this document. When the user asks to execute this plan, complete
the stacks and the bounded pilot below. Do not start a wider model tournament.

Baseline inspected: `956b027` (game implementation source `7754017`). Recheck
HEAD and local changes before implementation; preserve unrelated work. This
plan supersedes the single-operation experiment as the proposed next direction.
It does not change the existing default until evidence supports that decision.

## 1. Objective and boundaries

Let the player model select executable objectives and resolve consequential
tradeoffs. Let deterministic code perform legal recruitment, uncontested village
capture, travel toward a selected rally point, bookkeeping, and turn completion.
An ordinary engine action must not, by itself, require another model call.

Deliver one opt-in client mode, `--decision-mode strategy`. Retain the existing
batch/focused modes for actual comparisons. Reject combining strategy mode with
`--focused-max-operations-per-decision`; do not silently reinterpret that flag.
Strategy mode requires incremental driver turns. Its defaults are 64 partial
batches, 256 queries, and eight logical model responses per controlled turn;
keep existing validated overrides and include resolved values in provenance.
A fixed-policy execution installs no backend and uses zero model responses.
Keep the existing provider,
usage collector, supervisor, recorder, history catalog, and GUI replay.

This is a hybrid player. Attribute automatically selected actions to code, even
when they serve a model-selected objective. Do not call these model-authored
moves, or attribute the fixed-policy baseline's strength to GLM.

First release scope:

- Finite recruitment orders with a gold reserve.
- Explicit village objectives, automatically assigned to designated scouts.
- One rally point for the remaining mobile army.
- Persistent explicit holds and an automatically stationary recruiter.
- Automatic execution while the defined threat checks permit it.
- A small model response contract for policy changes and tactical exceptions.
- Existing model-authored combat actions/inspections when automation pauses.

Excluded: autonomous combat planning, combat candidate search/ranking, automatic
promotion selection, automatic resignation, formations, learned routing,
multiple planner agents, a general workflow/task framework, and a new database
for policies. No tactical-guide expansion or broad engine refactor. Do not hide
an existing whole-army Greedy turn inside the routine executor.

## 2. Why this change

Prior GLM game `bb5784f9b0b2a985768e269f84a31033` used 333,626 player tokens,
including 174,859 reasoning tokens, without finishing its first turn. It did
recruit 15 units and occupy three village hexes. Four drafts needed repair; the
last repair still combined recruitment and finishing. The phrase "separate
decision" was interpreted as a second `decisions[]` annotation group inside one
response. The validator meant a separate response. Annotation bookkeeping and
whole-turn reconsideration consumed visible effort.

The goal is to remove that work, not merely ask GLM to think faster. Success is
measured first by completed objectives and fewer model dispatches. Beating
Greedy remains a separately measured gameplay outcome.

Evidence: `tmp/watchdog-decision-exec/PARENT_FINDINGS.md` and
`tmp/glm-single-operation-live-20260913T154253541846Z/PROMPT_AUDIT.md`.
These ignored archives are context, not dependencies for new regression tests.
Check in minimal self-contained fixtures for every required test.

## 3. Definitions — use these words consistently

- **Model response:** one completed provider reply. Never call this a decision
  group. `decisions[]` is the old annotation array and is absent from this mode.
- **Policy:** a validated structured set of executable orders. Policy prose is
  not parsed or executed. Old `intent` and `agenda` fields remain annotations in
  old modes; they must not become executable by inference.
- **Routine step:** one engine-selected ordinary Move or Recruit, or a finish
  that performs no friendly sweep. It uses no model call.
- **Exception:** a machine-detected condition that routine execution cannot
  resolve under the current policy. A model response can resolve the condition,
  change policy, take tactical actions, or explicitly finish the turn.
- **Committed:** proven by the existing driver/checkpoint acknowledgement
  protocol. A proposed response, query result, or forecast is not committed.
- **Threat-screened:** passes the explicit next-opponent-turn checks below.
  This is not a guarantee against every future enemy strategy.
- **Completed player turn:** an actual controlled-side turn boundary. A partial
  batch, snapshot/frame, model response, or round number is not a completed turn.

## 4. Final player contract

The JSON below specifies the new contract, not an existing supported API.
Use a strict discriminated union with exactly the listed keys. Generate prompt
examples and validation from one definition where practical. Four response forms:

### Replace the policy

```json
{
  "kind": "set_policy",
  "policy": {
    "reserve_gold": 60,
    "recruits": [
      {"def_id": "Ghost", "count": 3, "role": "scout"},
      {"def_id": "Skeleton", "count": 6, "role": "army"}
    ],
    "scouts": [],
    "villages": [{"col": 2, "row": 4}, {"col": 5, "row": 3}],
    "rally": {"col": 8, "row": 7},
    "holds": []
  }
}
```

`reserve_gold`: integer >= 0. Each recruitment count is a finite total for this
policy installation, not a count to buy each turn. `recruits`: ordered list of
at most eight entries; count 1..32; recruitable definition; role scout or army.
`scouts`: distinct existing friendly unit IDs, at most eight, excluding recruiters.
New scout recruits are added using actual returned IDs, never predicted IDs.
Existing scouts plus all requested new scouts must total at most eight; reject
a larger policy before any execution.
`villages`: at most four distinct existing village coordinates. `rally`: one
in-bounds coordinate or null. `holds`: distinct existing friendly IDs; held IDs
cannot be scouts. Never automatically move a recruiter, including a held one.
Bounds constrain this first implementation; do not build a configurable schema
registry. Invalid policy input causes no engine mutation.

A policy replacement replaces all previous orders, assignments and remaining
recruit counts. The model receives the remaining counts in its brief. If it
copies a count into a replacement, it is explicitly requesting that many future
recruits. The client never replays a replacement merely because it resumed.
Persist an internal installation ID linked to the source request; do not ask the
model to invent IDs or revision numbers. A valid installation is durably recorded
before its first routine step. It is an instruction commitment, not evidence
that any engine action already happened.

### Take consequential tactical actions

```json
{"kind":"act","actions":[{"action":"Attack","attacker_id":12,"defender_id":19}],"finish_turn":true}
```

`actions`: 1..16 existing legal nonfinal actions/macros. Reuse ordinary action
validation. Allow relevant existing Move, Attack, Engage, Recruit/RecruitBatch,
and Advance semantics; do not invent attacks. No boundary or Resign inside this
array. `finish_turn`: required Boolean. If true, append exactly one empty
selective finish after the authored actions. If false, return to the routine
loop from fresh state. This explicitly permits one tactical response to act and
finish; it does not impose the failed one-operation restriction.

### Finish without more friendly actions, or resign

```json
{"kind":"finish_turn"}
{"kind":"resign"}
```

These are distinct. Finishing does not resign. Preserve existing rules for a
standalone resignation, including no invented winner before an accepted result.

There are no required `decisions`, rule citations, risk/expected strings, intent,
or agenda in strategy mode. Preserve the raw reply and provider reasoning when
available; do not fabricate model rationale from deterministic execution logs.
A valid action must not need a second model call just to annotate it.

For tactical uncertainty, retain the existing bounded read-only inspection tool
shapes. Advertise only relevant supported tools in an exception brief. Do not
add new planning tools or require an inspection before every response.

## 5. Architecture and execution rules

### Ownership and small interfaces

Keep the outer run/model/usage lifecycle in `tools/llm_client.py`. Put policy
validation, committed progress, exceptions and response rendering in one small
Python module, proposed `tools/routine_policy.py`. Avoid another all-purpose
client. Put engine-dependent step selection in one small Rust module, proposed
`norrust_core/src/routine.rs`, reusing pathfinding/tactics/action execution.

Add one revision-pinned read-only driver query:
`{"action":"Query","what":"routine_next","state_revision":N,...}`.
Its additional fields are the validated policy and committed progress. Its
result is exactly one of: an ordinary action with its proposed progress update;
a finish-ready result; or a typed exception with evidence. It must not change
live state, RNG, unit ID allocation, policy progress, or the checkpoint. Select
one routine step at a time and refresh after commitment; this is cheap code
iteration, not an LLM iteration. Bound and charge its work to existing query
budgets. Do not perform unbounded per-unit inspection fan-out.

Routine submissions need trustworthy batch provenance. Extend the client-driver
boundary with a small internal orders envelope carrying `origin: routine` and
its source revision. Keep existing ordinary arrays for the other modes. Only
client code constructs this envelope; a model response cannot set its origin.
Reject stale revision before mutation. Feed its orders through the same
transactional executor/checkpoint/event path as normal orders. Tag those engine
events `routine`, and update importer, metrics and export consumers together.
Preserve existing `llm`, `delegated_greedy`, and opponent attribution.

Do not teach Python combat math, path legality, ZOC, or hex-coordinate rules.
Do not implement an alternate mutation path for routine actions.

### Required threat screen

Before each step, check current authoritative information. Pause if:

1. Any friendly unit has a legal attack, or an enemy can attack any friendly
   unit on its next activation according to the engine's current/open exposure
   views. This deliberately hands contact to the model early in version one.
2. The proposed destination/recruit placement is attackable in either exposure
   view. Check the post-step clone, including effects on recruiter exposure.
3. Threat information is absent, truncated, timed out, or otherwise unavailable.
4. A friendly promotion is pending, or a named order refers to a dead/foreign
   unit, invalid objective, or unavailable necessary fact.

Zero threats means an explicitly evaluated zero, never missing data. Use the
same observed information available to the model. Do not inspect hidden enemies
if the configured game does not expose them. Label incomplete visibility and
pause for model judgment rather than claiming unknown regions are safe.
No automatic attack, intentional sacrifice, recruiter movement, or relocation
of a held unit is permitted. The model can still choose such legal tactics in
an explicit `act` response. Its next fresh state can raise another exception.

Conservative pauses are acceptable. Excessive pauses must be measured, not
fixed by silently weakening this definition during an experiment.

### Deterministic routine priority and progress

Re-evaluate from the fresh revision after each committed step:

1. Apply the threat/promotion/identity checks above.
2. Assign eligible scouts to selected villages, then move scouts still needing
   movement. Exclude held/recruiter units. Keep assignments until capture,
   invalidation, or policy replacement. Use engine terrain-cost distance; assign
   the cheapest eligible scout/village pair, breaking ties by village row,
   village column, then unit ID. Do not solve a general assignment optimization.
3. Recruit the next unfinished queue entry into a legal empty castle hex while
   preserving the gold reserve. Tie-break by row then column. Use ordinary
   Recruit actions; **do not auto-vacate occupied castle hexes**. Vacating can
   spend a scout's movement or violate a hold. If full, attempt eligible army
   travel below, then re-evaluate capacity. Never skip a queue entry silently.
4. Move eligible non-scout, non-recruiter, non-held army units toward the rally,
   processing unit IDs in ascending order. New army recruits inherit the rally.
   With rally=null they receive no automatic movement order.
5. If all remaining steps require a new turn, finish automatically. If an order
   is blocked rather than merely movement-spent, raise one typed exception.

For multi-turn travel, use engine terrain-cost routes and legal current-turn
endpoints, not geometric distance alone. Reuse existing pathfinding. An endpoint
must be legal/unoccupied; friendly intermediate occupancy must follow the
engine's actual rules. Choose the furthest threat-screened reachable endpoint
on a shortest route, with deterministic coordinate tie-breaks. Rally destinations
are staging areas: allow a distinct free target-adjacent hex at distance <=1;
a unit already there is arrived. A village requires its exact hex. Do not loop
at an occupied rally or move an arrived unit back and forth. If no path/endpoint
is available, record the cause and pause rather than re-ask the same query.

A scout standing on an uncaptured village holds there through the finish. A
village objective completes only when the engine records friendly ownership;
arrival alone does not complete it. Completed village scouts hold until the
next policy replacement in this first version. Do not invent their next target.

Queue counts decrease only for committed successful recruitment events. A
not-yet-affordable next recruit waits if owned/occupied-to-be-captured villages
will provide sufficient positive income; otherwise raise `recruitment_blocked`.
Do not auto-end forever hoping for impossible income. Insufficient legal space
with no eligible vacating-by-travel move is also blocked. At most one attempt
per unchanged revision/plan state; a rejected routine action is an executor
failure to diagnose, not a model-output repair opportunity.

Finishing must use `FinishWithGreedy` with `groups:[]` and `holds:[]`, after
verifying its existing no-sweep behavior. **Plain driver EndTurn can perform an
automatic Greedy sweep. Do not use it as a harmless boundary.** Opponent
activation remains the existing driver-owned behavior. No model call is needed
between the final routine step and an allowed automatic finish.

If `final_only` is true, no further routine partial action is permitted. Finish
without a model call when the screen permits; otherwise ask only for a legal
final response. Explicit tactical `act` must then set finish_turn=true. Never
consume the last legal batch slot and then submit an illegal partial response.

### Model invocation and progress limits

Call the model at initial policy selection and at typed exceptions: contact,
unsafe/unknown route, recruitment blocked, invalidated assignment, promotion,
all objectives completed, or no executable orders. Defer an all-objectives-completed notification until
a no-sweep finish has committed; it must not prevent the current turn from
finishing. At the next controlled turn, request replacement orders if the run
continues. A selected policy persists
across both partial batches and completed turns. Never ask merely because the
revision advanced, a unit moved, a recruit received an ID, or a turn ended.

Brief contents: compact global situation; current executable orders and their
remaining counts; changes since the last model response; the precise exception;
and relevant engine-derived local options/threats. Keep a compact global map or
objective map so local choices have strategic context. Offer existing bounded
inspection for missing detail. Do not dump the full ordinary action schema,
legacy annotation contract, full army options, and unrelated tactical prose into
every brief. Keep stable instructions before volatile state. Preserve the latest
LIVE_STATE guard and label simulations as not executed.

Name the budget in physical model calls, not decision groups. Use at most eight
logical player responses per controlled turn in this mode; tool follow-ups and
repairs count. Existing physical output-exhaustion attempts remain counted and
bounded separately. One malformed response gets one targeted repair. Repeating
an exception without changed state, policy, or an accepted finish does not reset
budgets. On budget exhaustion, record an interrupted game; do not invent a win,
resign, or silently hand the turn to Greedy.

All routine actions/queries count against driver action/query/turn budgets.
Do not treat automatic execution as unlimited. Existing wall deadline, provider
limits and usage unknown handling remain in force.

## 6. Persistence, observability and attribution

Extend existing client checkpoint-ref metadata; do not create a parallel policy
save system. Persist policy installation, remaining recruit counts, actual scout
IDs/assignments, completed objectives, holds, and the last proven revision.
Persist pending progress with the same source/checkpoint evidence as the batch.
Adopt it only when commitment is proven. Lost acknowledgement, cancellation,
resume and rollback must not duplicate recruitment or repeat a completed step.
If the checkpoint has advanced but its matching policy progress cannot be
reconstructed, interrupt with explicit unknown action-boundary status. Do not
reset to the original recruitment list. A branch is a new game with recorded
lineage; never mutate the parent archive.

Record policy install/replace, routine step proposed/committed, exception raised/
resolved, and automatic finish. Link execution to policy installation/source
request without manufacturing a new model request for each routine action.
Routine execution creates zero usage rows. Model calls keep real request IDs,
role, input/cache/output/reasoning coverage and provider receipts as before.

Reuse event/snapshot/action-batch tables and existing metadata/raw records.
Extend source handling to `routine`; make routine batches available in playback
and exclude them from model-authored action/training predicates. Reject forged
origin metadata at the model response boundary. Record model tactical macros'
existing delegated expansion separately. Missing model annotations in this mode
are expected, not a failed rationale-completeness score. Do not migrate or
relabel historical evidence. Reimport must preserve per-game row counts/hashes.

Metrics: player responses and physical calls; tokens/cache/cost and unknown
coverage; completed player turns; routine and model-authored actions separately;
fulfilled objectives; villages owned; recruiter survival; exceptions by reason;
repeated unchanged exceptions; rejected drafts; time to first capture; time and
player tokens through each completed turn. No division by zero when no turn ends.

## 7. Implementation stacks and gates

Implement in order. Every stack includes executable integration, relevant docs,
focused tests, the full headless gate, and its own commit. Do not leave all wiring
or history integration until the last stack. Before each commit freeze tracked
files, run `python3 -m tools.fast_check`, inspect its exit status, and save the
command/output/source in `tmp/strategy-exec/stack-N/`. Do not run unfiltered
`cargo test` (the balance suite is large). Do not edit under a running full gate.
Use default Cargo artifact paths unless the actual tests support an override.

### Stack 1 — Executable recruitment policy, persistence, and automatic finish

Implement strategy mode and the minimal set_policy/finish response paths, ordered
finite recruitment, reserve enforcement, no-sweep finish, routine query/submission
provenance, checkpoint progress, and catalog import. For this stack advertise
only recruitment policies: scouts/villages/holds empty and rally=null. Nonempty
future fields must be rejected explicitly, not accepted and ignored. Before
contact support lands, contact ends the fixture run as an explicit unsupported
exception; no hidden fallback. Use a scripted backend, not a live model.

Gate, real client + built driver + temporary SQLite:

- One scripted policy response recruits an affordable finite queue and finishes
  a player turn. The executor makes zero further backend calls.
- Recruitment can finish over two turns without buying the original queue twice.
- Reserve is maintained, actual recruit IDs are captured, and illegal/nonempty
  unsupported policies mutate nothing.
- Occupied castle spaces cause no auto-vacate. No held/recruiter movement, attack,
  or automatic Greedy sweep occurs during routine completion.
- Crash after a committed recruit/before acknowledgement, then resume: same final
  recruit count/gold as uninterrupted execution. Rejection leaves progress intact.
- One real backend call record, correctly labelled routine events, playable
  snapshots, terminal/budget outcomes and idempotent import. No invented usage.
- Existing batch/focused tests still pass. Full gate, docs, commit.

### Stack 2 — Persistent village and rally execution

Enable the remaining policy fields. Implement assignment, engine-cost routes,
arrival/ownership distinction, deterministic ordering and all routine blocking
rules. Keep model invocation scripted for this stack. Extend the same saved
progress rather than adding separate task and intent stores.

Gate with checked-in positions and exact predicates:

- One policy response drives at least three complete friendly turns with zero
  follow-up responses while selected distant objectives remain valid. Pick a
  quiet fixture without enemy contact and with an incomplete objective through
  the tested window, so all-objectives-complete is not an artificial extra call.
- Three designated scouts occupy three reachable village hexes and ownership
  changes only on the actual first finish. No scout leaves an uncaptured target.
- Distinct assignments, occupied rally, terrain detour, friendly intermediate
  occupancy, movement exhaustion, unreachable target and unit death have fixed
  expected outcomes. Movement exhaustion finishes; genuine blocking pauses.
- A reserve/space blockage cannot create an infinite auto-turn loop.
- State/threat changes between proposal and submission reject stale work. Missing
  threat data pauses. A proposed move exposing the recruiter does not execute.
- Restart/branch preserves valid assignments and remaining queue counts, including
  newly recruited scout IDs. A duplicate pending step is never applied twice.
- End-to-end catalog attribution and replay remain correct. Full gate, docs, commit.

### Stack 3 — Small GLM contract and tactical exceptions

Implement the complete response union, compact strategy/exception prompts,
existing bounded inspection support, and model-owned tactical actions. This
stack removes unsupported-contact termination from stack 1. Old full annotation
prompts must not leak into strategy mode. Fixed rules remain versioned in
provenance, but no model-generated rule citation is required.

Gate using fake transports and real driver; assertions concern actual events:

- Quiet progress makes no extra model call. Enemy contact pauses before the next
  routine action and sends the correct current revision and exception facts.
- Scripted policy -> automatic travel -> contact -> scripted tactical act with
  finish_turn=true produces legal combat and one no-sweep boundary. Ordinary
  multi-action tactical responses do not hit the focused one-operation limit.
- Promotion, recruiter danger, unknown information and a blocked objective each
  produce one bounded useful brief. Missing evidence is not called zero risk.
- A policy replacement changes subsequent execution and cancels old holds/orders;
  it never resurrects completed recruitment through resume.
- Tactical state change invalidates stale local options. Resignation is explicit.
- Exact previous failure shape: actions plus finishing in a single `act` response
  with finish_turn=true works. `decisions[]` is neither required nor mistaken for
  a second response. Illegal embedded boundary receives the precise corrective
  message and at most one repair; malformed repair terminates honestly.
- final_only=true cannot submit a partial response. No hidden extra finish call
  is required for a valid act-and-finish response.
- Repeated unchanged policy/exception loops hit the existing bounded interruption
  path. Timed-out/unknown provider usage and stop fencing continue to work.
- Backend prompt passes byte-for-byte through Fireworks/file transport; prompts,
  receipts, events and counts reproduce from maintained artifacts. Full gate,
  updated LLM_CLIENT/DEVELOPMENT/GAME_HISTORY docs, commit.

### Stack 4 — Fixed-policy control, matched report and bounded live pilot

Reuse `tools.model_bakeoff`, task-harness fixtures, history import and cost
reporting. Do not replace the runner or silently weaken the existing A/B/C
fingerprint/predicate rules. Add named strategy comparison treatments separately
from A/B/C. A routine action can satisfy an objective predicate but cannot
satisfy a model-authored-action predicate.

Treatments:

1. `strategy_fixed`: same routine executor, checked-in policy input, zero model
   calls. Add `--strategy-policy PATH`, valid only with strategy mode, to install
   that exact policy without starting a backend. Record the controller identity
   as fixed-policy code, not a model. At an exception requiring judgment, stop
   with a recorded `fixed_policy_exception` interruption and no winner. No Greedy
   combat fallback is added. This measures the routine executor's contribution
   to the opening, not a standalone full-game competitor. No synthetic request
   or usage row should be created for reading this file.
2. `strategy_glm`: identical routine code, policy selected by GLM, exceptions
   handled by GLM. Model/provider settings fixed before launch.
3. `focused_glm`: existing focused mode with the single-operation flag disabled.
   No routine execution. This is the current-interface comparison, not a claim
   that its amount of deterministic assistance matches the new strategy mode.

First run a small network-free matrix covering quiet opening, multi-turn travel,
blocked objective, and contact. Scripted strategy responses must influence actual
outcomes: two different valid policies on the same position must produce the
specified different deployments/spending. Identical policies/seeds reproduce
identical committed events. All catalog identities and per-game counts are
verified after two imports. Synthetic usage is labelled synthetic.

Create a pilot manifest and report generator, with fixed predicates and explicit
unknown/unrun cells, then pass the full gate and commit before live execution.
No new model call or tool is needed to watch every move.

When this plan is executed, the authorized pilot scope is one matched opening
trial per treatment, three trials total, using `big_battle_6`, undead mirror,
300 gold, seed 2038, side0 versus Greedy, and at most six completed engine
side-turns (three GLM/fixed player turns). No retries/rescue games after failure.
Use Fireworks only and the exact GLM model ID currently used by the maintained
backend, `accounts/fireworks/models/glm-5p3-flash`, after a read-only availability
check. Do not substitute models or change reasoning effort/temperature between
GLM treatments. Keep 131072 initial output and the existing exhaustion escalation;
do not attempt to buy success with larger limits.

Each paid cell: 200,000 cumulative player tokens, 900-second model-call timeout,
2100-second controlled-turn timeout, 300-second query budget, and a 45-minute
automatic wall deadline. Read and follow docs/LLM_CLIENT.md Usage accounting.
A cumulative cap permits one in-flight overshoot; document that in the manifest.
Verify dated Fireworks rates and conservatively cost the possible overshoot
before dispatch. Aggregate pilot estimated ceiling: $1. If current rates/limits
cannot support that bound, leave the pilot prepared and report the exact conflict;
do not change budgets, add providers, or launch an unbounded approximation.

Use recording-only monitoring (no paid observer calls) plus the existing automatic
wall deadline/stop facility and a durable five-minute compact heartbeat. Read
full gameplay logs once after completion. Preserve source/driver/prompt hashes,
independent run directories, partial failures, and all real usage. Import every
finished/interrupted run into default Recorded Games and a run-local catalog.
No fake native host binding for a direct API player; operator tokens are separate
and unknown unless measured. Calculate cached-input cost once, and do not add
reasoning again if already included in output.

Pilot acceptance has two distinct parts:

- **Functional:** all unrun/failed cells explicit; quiet fixed-policy execution
  needs zero model calls; strategy GLM finishes three controlled turns without
  malformed-response/executor failures, meets its selected reachable village
  objectives, and keeps the recruiter alive. Audit every exception that prevented
  routine progress. Replay and usage coverage are complete or specifically unknown.
- **Screening target, not a unit test:** strategy GLM uses fewer calls and measured
  tokens per completed opening than focused GLM, with at most two player responses
  per completed quiet turn on average. Target <=50,000 reasoning tokens through
  three turns. If the comparator fails to complete, report censored results rather
  than dividing its totals by zero or asserting a percentage improvement.

A missed screening target is a finding, not permission to alter fixtures or
rerun until it passes. Record the outcome in a final experiment commit (docs/data
only; no unnecessary full gate rerun without code changes). Leave default mode
unchanged. Three opening trials cannot establish win rate or combat strength.
A broader matched full-game experiment is future work after reviewing this pilot.

## 8. Ownership and handoff for Opus

Opus is the integrator. Parallel work is optional, not a reason to add layers.
If delegating, give workers disjoint files in isolated worktrees:

- Rust worker: routine planner, driver query/submit integration, Rust tests.
- Python worker: strategy loop/contract/persistence, Python integration tests.
- Evaluation/docs worker: fixtures, comparison/report consumers and docs after
  the response/event contract is frozen.

Agree on the small query result and internal submission envelope before coding.
The integrator owns shared-file integration, cross-layer resume/provenance tests,
full gates and final commits. Merge each end-to-end stack before advancing; do
not merge all Rust work first and call an unconnected library a completed stack.
Do not rewrite unrelated llm_client branches while introducing the strategy path.

Keep `tmp/strategy-exec/HANDOFF.md` current with last passed stack/commit, actual
commands/results, source changes, pending failures, and any live process/run ID.
If credits run out, leave an exact resumable handoff. Never write "complete"
because code files exist. Completion means the documented gates ran, changes
were committed, the pilot was completed or explicitly blocked/unrun, and a
report names remaining limitations. Distinguish implementation completion,
functional acceptance, and gameplay improvement in the final answer.
