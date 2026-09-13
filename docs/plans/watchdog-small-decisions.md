# Reliable bounded observation and smaller GLM decisions

Baseline: `c4f2785`. User authorized this plan, Luna implementation, a bounded
Fireworks observer evaluation, and one GLM Flash game. Fireworks is the only
provider. The user wants sparse supervision and one completed-log review.

## Evidence and scope

Read `AGENTS.md`, `docs/DEVELOPMENT.md`, relevant sections of
`docs/LLM_CLIENT.md`, and `tmp/glm-watchdog-prep-QWYqM2/REVIEW.md`.
Prior game `82a5cad2b7121d07a6d74e08046a8092` timed out after five completed
GLM turns: 489,312 measured player tokens plus one unknown call. It captured
three villages, killed two units and lost five. Nineteen of 20 observer replies
had incomplete evidence; one inspection preparation failure vanished from
reporting. The observer exhausted its cap around minute 30.

Keep this small: existing controller, recorder, inspection tools, legal actions,
SQLite schema, and provider adapters. No new agent framework, model registry,
engine solver, broad tactical rewrite, new provider, or unbounded retries.
Preserve archived games and strict stop identity/freshness/evidence guards.
Unknown provider usage stays unknown. Improving protocol does not prove model
judgment quality, and one game does not establish win rate.

## Ownership and integration

Use Luna High workers. Parent owns plan, integration review, acceptance decisions
and final findings. Worker A owns watchdog/controller/recorder/review/evaluation
files and associated tests/docs. Worker B owns player/backend lifecycle and the
small-decision experiment with their tests/docs. Shared documentation may need
parent conflict resolution. Work in isolated worktrees based on the baseline;
never run Git mutations concurrently in the main checkout. Workers commit only
owned changes, report exact commits and test results, and do not launch paid
calls without the launch task below. Do not nest more agents.

Each stack is an end-to-end slice: implementation, executable regression,
maintained docs and a commit after its gate passes. Full gate is
`python3 -m tools.fast_check`. Freeze tracked files while running it. Integrate
in stack order and run the combined full gate once before live dispatch. Avoid
repeating a passed gate without changes or a concrete unresolved concern.

## Stack 1 — An observer that can obtain evidence and report its limits

Worker A owns this complete slice.

1. Record every inspection attempt through completion or explicit preparation,
   evidence-read, transport, cancellation or budget failure. Release reservations
   safely; never silently abandon a follow-up. Historical absence remains
   unknown. An early pending/failed observation must not disappear when a later
   observation succeeds. Do not count an undispatched preparation failure as a
   paid physical call.
2. Report separate physical-call/receipt coverage, usable-evidence coverage,
   unresolved investigations and monitoring termination (including cap/disabled
   reasons). Maintain review/replay/evaluation callers and tests together. Do
   not retain a misleading duplicate field solely for compatibility; historical
   evidence must still be readable. False-stop/missed-loop denominators must
   contain judged cases of the relevant category only.
3. Replace indiscriminate status dumping with a bounded initial/investigation
   projection. Preserve trusted phase, confirmation, identity, freshness and
   recovery facts. Reserve space for two bounded evidence excerpts under the
   existing input bound; include text once, without redundant raw/base64 forms.
   Model-visible evidence choices should have short descriptions/type and
   allowed IDs. Do not invite selection of references that the reader rejects.
   Keep immutable provenance for offline audit. Detect and report genuinely
   insufficient/clipped critical evidence, without marking harmless deliberate
   summarization as missing critical data. Identify estimated token bounds as
   estimates rather than promising tokenizer-exact counts.
4. Coalesce overlapping repetition passages into a stable request-scoped
   incident for scheduling/confirmation while retaining raw alerts as evidence.
   A new request or real progress resets confirmation; repeated identical
   observation sequences do not count twice. When controller rules permit only
   continue, record a deterministic skip and spend no model call. This is not
   a model judgment or a semantic quality success. Respect cooldowns and keep
   20 total physical calls including follow-ups/failures; no hidden retries.
5. Regress the actual failure shapes offline: crowded live packet + two evidence
   slices; invalid advertised-choice selection; oversized follow-up explicitly
   reported; pending window followed by success; exhausted cap; foreign/stale
   evidence; progress resets; overlapping stream alerts; duplicate sequence.
   Exercise real client/supervisor integration with fake transports and verify
   SQLite usage-role separation and idempotent import. Keep labelled fixture
   expectations unchanged, including semantic drift with insufficient evidence.

Acceptance: focused regressions pass, existing offline replay runs without
network access, every attempt has an honest terminal/pending outcome, valid
confirmed loop can inspect/stop within three calls, progressing/unknown evidence
cannot stop. Full gate passes, then commit this slice. Save report in
`tmp/watchdog-decision-exec/observer/`.

## Stack 2 — Close interrupted player-call lifecycle without inventing usage

Worker B implements this before stack 3.

Reproduce the prior streaming timeout with a fake streaming server/backend and
short test deadlines. Use the existing lifecycle/sidecar primitives to record a
terminal timeout/cancel outcome for the correct physical call, request and role,
even when no provider final usage arrives. Preserve received bytes and partial
reasoning. Use bounded cleanup so children do not outlive the run. Keep remote
cancellation and unreported tokens explicitly unknown. Preserve valid final
provider usage if it won the race; no duplicate physical calls or double-counted
usage. Do not add unsafe automatic resume or provider-error retries.

Acceptance: real subprocess timeout test terminates, final unknown usage links
to the original request in SQLite, reimport is idempotent, successful and
output-exhausted calls retain exact usage/identity. Document independent wall
and output limits. Full gate passes, then commit this slice separately.

## Stack 3 — One bounded player operation, then fresh state

Worker B implements a minimal opt-in experiment using existing focused mode.
Focused mode already describes objective selection and local inspection: reuse
that implementation instead of adding another tier/framework. Add one clearly
named configured limit for a single authored mutating operation per decision;
default behavior remains available for comparison. An existing `Engage` on one
target, `RecruitBatch`, or `MoveGroupToward` is one operation, using engine-owned
expansion. Finishing is a separate decision so a consequential operation returns
fresh state before a turn boundary. Respect the driver's `final_only` case.
Do not silently split/reorder/truncate an oversized model batch or infer tactics.

Explain this small contract prominently in the canonical prompt and local
inspection phase. Offer existing target/unit inspection when legal destinations
or attack origins are uncertain. Avoid requiring an inspection for every obvious
recruit or safe move; do not add annotation verbosity. Enforce the same limit on
initial responses, repaired/reviewed batches and relevant action-encoding paths;
reject before engine submission with a concise corrective response under the
existing bounded call/repair budgets. No alternate path may bypass the limit.
Record the setting and rejection counts in normal run provenance/reporting.

Acceptance: a real-driver fake player can recruit/move, receive a newer revision,
engage, and then finish; oversized batches never mutate state; stale local context
is cleared after progress; repair/review and final-only edge cases work. Existing
mode behavior remains tested. A multi-step same-target engagement that kills its
target stops safely using the existing engine semantics. Full gate passes and
commit separately. Save reports in `tmp/watchdog-decision-exec/player/`.

## Stack 4 — Bounded evaluation, one GLM game, recorded comparison

After integration review and the combined gate, freeze the source. A Luna worker
performs the following sequentially. No concurrent game or additional paid runs.
Read `docs/LLM_CLIENT.md` first, including authoritative usage accounting.

### Observer evaluation

Run the maintained unchanged 12-case labelled fixture evaluation against
`accounts/fireworks/models/deepseek-v4-flash-0731`, reasoning disabled. At most
one preflight plus three physical calls per case (37 total), $0.05 estimated
aggregate ceiling, no paid retries. Verify available models and dated Fireworks
rates without exposing credentials. Preserve requests/receipts/usage/results
and source. Stop evaluation on auth/credit/configuration failures; do not change
fixture labels or relax safety guards to pass.

Targets: all cases have explicit judged/unknown outcomes; all three deterministic
loop cases achieve validated stops, no healthy case is falsely stopped, and
semantic drift remains a disclosed miss/unknown when evidence is insufficient.
Failed semantic targets are findings, not a reason for unlimited tuning/evals.
Use observe mode for the game regardless; do not promote enforce automatically.
A concrete code defect may be fixed and retested before the game, with the
failed evidence retained, but no second paid evaluation is authorized here.

### One live game

Use a unique artifact directory, canonical prompt unchanged through the
maintained Fireworks backend. Player GLM model must be explicit in both backend
and client: `accounts/fireworks/models/glm-5p3-flash`, streaming, reasoning effort
omitted/provider default. Same comparison settings: `big_battle_6`, undead mirror,
300 gold, seed 2038, side 0, focused incremental mode, max 50 engine side-turns,
1,000,000 player total tokens, 900s model timeout, 2100s turn timeout, 300s query
budget, 128k initial output with existing 512k/three-exhaustions policy. Enable
the new single-operation limit. Do not change temperature/model/other game
settings to rescue results. Observer stays DeepSeek Flash none, observe mode,
20 physical calls. Supervisor restarts zero. Two-hour hard wall deadline and
$1 estimated operational ceiling; an in-flight call can overshoot a cumulative
threshold and missing provider usage prevents claiming an exact bill.

Use a direct durable exec session and existing graceful watchdog stop facility.
Install a run-specific automatic wall deadline before leaving the run waiting;
no orphaned processes or background paid retry script. Log a compact operator
heartbeat/status at most every five minutes automatically. Luna reads only new
compact status/serious incidents, at most two indexed excerpts per serious
incident. Parent should not repeatedly open gameplay logs. Do not stop because
one request is long, a historical repetition alert persists, or GLM is losing;
stop on a demonstrated futile loop, unrecoverable failure, or configured limit.
Operator acknowledgments and final status must be durable, so a stalled coding
agent cannot hide run ownership. Send parent launch, serious incident, completion.

At completion OR interruption, import into default Recorded Games and run-local
SQLite, idempotently. Read `docs/AGENT_GUIDE.md` and `docs/GAME_HISTORY.md`, inspect
SQLite before individual archives, review the completed logs once. Write
`FINAL.json` and `REVIEW.md` with game ID/replay, source, outcome, exact completed
side-turn and player-turn counts, per-role physical calls/tokens/cache/known cost
and unknown coverage, observer skips/investigations/failures/cap coverage, actual
moves/recruits/villages/kills/losses, delegation attribution and request examples
of useful reasoning vs thrash. Keep operator/coding-agent usage separate and
unknown unless actually measured. No invented host-player binding for a direct
API game.

Compare matched completed-turn boundaries to prior game
`82a5cad2b7121d07a6d74e08046a8092`: useful engine actions, rejected drafts, player
calls and reasoning per completed turn, villages, casualties, material and cost.
The treatment changes action granularity; observer/lifecycle changes also share
the new source, so describe a one-game observational comparison, not a causal or
statistical performance claim. Timeout/interruption is not a loss or a draw.

## Completion

Parent reviews commit/test evidence and the completed report, writes
`tmp/watchdog-decision-exec/HANDOFF.md`, and adds a current-handoff pointer to the
previous handoff without rewriting historical evidence. Final response states
implemented changes, measured acceptance results, GLM performance/cost and any
remaining failures. Do not claim newly found defects were fixed unless they were.
