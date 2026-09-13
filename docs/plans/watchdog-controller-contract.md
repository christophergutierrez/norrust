# Align observer decisions with the controller, then test GLM Flash

Baseline: `97914ae`. Requested by the user: plan, Luna implementation, then a
Luna-operated GLM Flash game and an evidence-based report. Fireworks only.

## Problem and scope

The last real observer evaluation returned valid JSON for every request, but
validated none of its four expected loop stops. Three cases proposed stop
without completing the controller's inspection contract and/or without the
required `repeated_no_progress` reason. The reasoning-loop case continued
because a memoryless packet did not explain repeated confirmation. The
semantic-drift fixture has no deterministic repetition alert; missing evidence
must not be turned into proof just to make that case pass.

Keep the working Fireworks DeepSeek Flash observer profile (`reasoning_effort`
`none`), 512 output-token cap, 30-second deadline, existing cooldowns, 20-call
game cap and complete usage accounting. Preserve historical evidence, fixture
labels, player tactics, model response escalation and supervisor stop fences.
No new model registry, agent framework, unlimited observer history, or broad
semantic-loop detector. Do not claim a long request or losing material is a loop.

## Stack 1 — Complete decision contract through live stop validation

One Luna High implementation worker owns this stack in the main checkout.
Read AGENTS.md, docs/DEVELOPMENT.md, docs/LLM_CLIENT.md and the relevant observer,
replay, outcome, integration and stop modules. Read the prior report at
`tmp/watchdog-live-fixes-exec/observer/observer-report.md`.

1. Build a small controller-owned request context from the existing persisted
   state after recording the current observation: initial vs investigation
   phase, current incident identity, distinct-observation count, progress
   identity, available evidence references, and prerequisites still missing.
   Include only bounded summaries; never send fixture expectations or infer
   confirmation from repeated polls of the same observation sequence. Reset
   confirmation on progress/recovery and keep late-response/current-request
   fences intact. Protect this context against similarly named source fields.
2. Give the observer the complete concise procedure: continue when evidence is
   insufficient; on confirmed suspicious non-progress request `inspect` with
   at most two available evidence IDs; the single investigation follow-up
   chooses continue or stop, cannot recursively inspect, and must use exact
   reason `repeated_no_progress` for a stop. Explain the difference between
   an alert's passage count and fresh unchanged observations. First-alert
   inspection must not spend the three-call case budget before confirmation
   can exist. Do not add retries or raise case limits to hide the problem.
3. Validate inspection references and actual read coverage. Empty, unavailable,
   foreign, clipped critical evidence and stale investigations cannot establish
   stop eligibility. No model-supplied flag may bypass a deterministic guard.
4. Journal a bounded explicit result for every stop proposal: eligible vs
   rejected, with the actual failed prerequisite (reason, inspection, freshness,
   recovery, evidence or identity). Distinguish observe-mode non-enforcement
   from an invalid recommendation. Reuse one eligibility path so diagnostics
   agree with enforcement. Expose results through the existing final review;
   preserve distinct physical requests, verdicts, failures and coverage gaps.
5. Add regressions through request payload, controller, journal/review and the
   real-client/fake-transport supervisor path. Prove a contract-following
   observer can inspect and stop a confirmed loop within existing call bounds;
   unknown/stale/recovered evidence and progressing games still cannot stop.
   Repeated identical polls are not independent observations. Confirm prompts
   contain phase, required reason, confirmation and usable references without
   changing player prompt bytes or inventing a second state ledger.
6. Update maintained observer instructions/docs and any affected test fixtures
   together. Preserve original labelled cases and their evidence. Record any
   unsupported semantic-drift stop explicitly rather than weakening safeguards.

Acceptance: focused tests pass, then freeze tracked files and run
`python3 -m tools.fast_check`. Commit the complete code/tests/docs stack after
the gate passes. Parent reviews completed diff before live dispatch. Save
implementation report and commands in `tmp/watchdog-contract-exec/IMPLEMENTATION.md`.

## Stack 2 — Bounded real observer evaluation

After the implementation commit, the same Luna worker runs the maintained
`tools.watchdog_evaluation` once in a new directory against the unchanged
12-case manifest: one preflight, at most 37 physical calls, no retries, existing
input/output/deadline caps, maximum estimated spend $0.05. Confirm current dated
Fireworks rates before dispatch. Stop on credit/auth/config failures. Preserve
payloads, receipts, normalized usage, model settings and source commit.

Measure all denominators, false stops, missed loops, stop rejection reasons,
time to detection, failed calls and cost. Target: all 12 cases judged, zero
false stops, and all three deterministic repetition cases reaching validated
stops. Semantic drift with insufficient confirmation remains a disclosed miss,
not a relabelled success. A failed target is a concrete finding to diagnose;
do not repeat paid evaluations or tune on labels silently. Fix demonstrated
code bugs with focused tests and a committed correction if necessary, retaining
the failed evaluation as evidence. Keep observe mode for the requested game
unless the unchanged full quality gate is demonstrably met; no automatic
promotion based merely on valid JSON or these few fixtures.

Record acceptance results in the handoff. Code changes require their relevant
tests; do not rerun the whole gate for ignored evidence-only report updates.

## Stack 3 — One Luna-operated GLM Flash game, sparse monitoring

Use a fresh Luna High subagent after the code is tested/committed. Read
docs/LLM_CLIENT.md first, including authoritative usage accounting. This agent
operates the harness; Fireworks GLM is the player. No file-backend player or
invented host-usage binding is needed. Preserve the canonical generated prompt.

Launch the maintained supervisor/client/backend in a unique run directory with:

- Player `accounts/fireworks/models/glm-5p3-flash`, explicitly in backend
  `--model` and client `--player-model`, streaming enabled.
- `big_battle_6`, undead mirror, 300 gold, seed 2038, player side 0,
  focused mode and incremental turns, cap 50 completed side-turns.
- Total player budget 1,000,000 tokens (previous run was 500,000); retain
  initial 128k output and 512k escalation/three-exhaustion policy. Model timeout
  900 seconds, turn timeout 2100 seconds, query budget 300 seconds, no automatic
  supervisor restarts. Overall run wall deadline two hours. One in-flight call
  may overshoot the cumulative threshold; report it, do not hide it.
- Working Fireworks observer in observe mode, with existing 20-call limit.
  Preserve run-owned log, request journal/context, checkpoint, evidence, usage
  and observer state. Verify exact selected model from the first real receipt.

The game is authorized, including Fireworks usage. Confirm current rates; the
nominal worst-case GLM output cost at the last checked $0.50/M is about $0.763
including one 512k overshoot, plus less than $0.03 for bounded observation.
Use a $1.00 operational ceiling for this game, allowing for estimation limits.
No top-ups, second game, extra candidates or unbounded retries.

Keep coding-model involvement sparse. Run the supervisor as a direct durable
exec session, not a child orphaned by a short-lived launch script. Persist all
raw evidence automatically. At most every five minutes inspect a small status
summary: elapsed time, stage, revision/turn, last committed action, pending-call
age, player usage, observer health and newly raised alerts. Do not tail full
reasoning or reread accumulated logs. An unchanged revision during a legitimate
open model request is not enough to abort. On a new serious alert, investigate
at most two indexed bounded excerpts and summarize the finding. Use existing
graceful stop/termination facilities if a confirmed futile loop, exhausted
budget, unrecoverable failure or wall deadline requires ending the run; record
the reason, preserve receipts/checkpoint, and distinguish interruption from loss.
Do not let routine parent status updates trigger extra Fireworks calls or full
agent rereads. Send parent only launch, first useful progress, serious incident,
and completion milestones.

At completion/interruption, import into the default Recorded Games SQLite
catalog and a run-local catalog using the maintained path, idempotently.
Read docs/AGENT_GUIDE.md and docs/GAME_HISTORY.md, query the catalog first, then
review the completed archive once with targeted excerpts. Produce a report:

1. Catalog game ID/replay location, source commit, exact settings, terminal
   reason/winner, completed side-turns, rounds, wall time and stop initiator.
2. Per-role physical calls, measured input/output/reasoning/cache/total tokens,
   unknown fields, dated costs, aggregate-only request IDs and unassigned calls.
   Luna/Astra orchestration usage remains separately unknown unless measured.
3. Observer decisions, investigations, eligible/rejected stops and reasons,
   failures/disablement/cap exhaustion, alerts, gaps and raw-record validity.
4. GLM play: recruiting, village control/income, movement toward objectives,
   combat/kills/losses, recruiter safety, useful actions vs rejected or repeated
   work, delegation/fallback attribution. Give concrete turn/request evidence.
   Inspect a few representative recorded reasoning excerpts after completion;
   classify useful/expected, pointless, understandable but poor, or missing
   harness information. Do not invent hidden reasoning or infer a win from a
   budget interruption. Compare with the prior run only over comparable turns;
   changed total budget prevents treating whole-run cost as a matched metric.

## Completion

Parent reviews the final diff, gate logs, evaluation and catalog evidence.
Write `tmp/watchdog-contract-exec/HANDOFF.md`, link the game report, update the
previous active handoff pointer without rewriting historical reports, and
report what was fixed, how GLM actually played, total cost and remaining failures.
No guaranteed win or perfect semantic stopper is implied by passing tests.
