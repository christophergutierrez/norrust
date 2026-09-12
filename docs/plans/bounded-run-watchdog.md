# Bounded run watchdog and one post-run review

Status: planned; implementation and paid runs have not started.
Planning baseline: `d1f6f6c` (recheck the working tree before implementation).

## Outcome

Run the game without an actively watching coding agent. Ordinary code records
the evidence and tracks progress. A cheap API model receives occasional small
progress packets, can read bounded evidence when suspicious, and can request a
durable stop. The orchestrator reviews the indexed results once after the run.
Observer calls, tokens, and cost are separately accountable and strictly bounded.

This replaces the repeated live LLM observation procedure in future launches,
including the observer instructions in `tmp/claude-glm-handoff.md` if that handoff
is still used. Preserve all historical observation files and game evidence.
Do not reopen the unrelated gameplay fixes in `glm-inspection-handoff.md`.

## Read first and preserve

- `AGENTS.md`, `docs/DEVELOPMENT.md`, and the usage-accounting section of
  `docs/LLM_CLIENT.md`.
- `tools/llm_supervisor.py`: currently blocks in `subprocess.run`, then reconciles
  failures and sometimes restarts. It does not monitor a running request.
- `tools/llm_client.py`: request/turn lifecycle, command subprocesses, terminal
  outcomes, existing budgets, checkpoint and resume paths.
- `tools/fireworks_backend.py`: streaming evidence, dispatch/final receipts,
  canonical prompt preservation, and usage sidecar.
- `tools/model_usage.py`, `tools/game_history.py`, and `tools/match_report.py`:
  use existing usage normalization and import/report conventions.
- Before extracting historical fixtures, read `docs/AGENT_GUIDE.md` and
  `docs/GAME_HISTORY.md`, inspect the SQLite catalog, then open selected archives.

Preserve gameplay prompts, action tools, engine behavior, output-limit escalation,
query budgets, and provider settings. A watchdog must never inject tactical advice
or consume the player's model/tool allowances. Missing reasoning, live usage,
boundaries, and provider cancellation confirmation remain unknown.

## Scope and fixed contracts

Use the existing supervisor and plain Python modules. No always-running coding
subagent, generic agent framework, MCP server, dashboard, vector index, second
planner, or multi-model escalation tree. Only one watchdog request may be active
per game. The player continues while the watchdog checks; its latency must not
block stream recording, game execution, or hard timeouts.

Deliver these three internal interfaces, with matching small CLI commands for
testing and operator use. They are functions first; no remote service is needed.

| Interface | Contract |
| --- | --- |
| `run_status(run_id)` | Bounded progress packet derived from recorded evidence; includes its observation sequence and freshness. |
| `read_run_evidence(run_id, evidence_id, offset, limit)` | A bounded excerpt from an indexed artifact belonging to this run. No arbitrary filesystem paths. |
| `stop_run(run_id, reason_code, evidence_ids, observed_sequence)` | Persist an idempotent stop request; supervisor validates freshness and owns cancellation. |

An observation sequence identifies the packet, not an engine revision. Track both
separately. An evidence reference identifies artifact, request/call when known,
byte range, and source hash or immutable-prefix hash for a growing file.
Read only the recorded range, not whatever later appears at that path.

The model response schema is deliberately small:
`decision: continue|inspect|stop`, `reason_code`, bounded `evidence_ids`, and a
short explanation. Only `inspect` can supply a bounded list of evidence reads.
Reject unknown fields, invalid references, excessive output, and arbitrary tool
names. Treat player text as untrusted evidence, never watchdog instructions.

### Initial operating policy

These are explicit starting settings, not experimentally established optima:

- Modes: `off` (default), `observe` (record recommendations), `enforce` (permit
  validated stops). Recording and existing hard limits work in every mode.
- Code polls new evidence every 5 seconds using incremental cursors, not full
  log reads. A regular watchdog check is eligible every 300 seconds while active;
  do not check after every stream chunk or every model response.
- Trigger earlier inspection on three identical rejected actions or identical
  tool requests at the same live revision, sustained repeated stream passages,
  or a request exceeding the 300-second progress interval. Threshold crossings
  create alerts, not automatic semantic stops. Coalesce simultaneous alerts and
  apply a 60-second cooldown; an unchanged alert must not repeatedly wake the model.
- Each packet states the stage, current request age, last completed turn and
  committed action, revision, recent actions/errors, repetition counters,
  objective/resource deltas, received stream bytes, and measured usage coverage.
  Include a small recent excerpt and a reference to the previous verdict.
  Byte growth proves receipt of output, not useful reasoning. A preview revision
  is never live progress. Legitimate inspection/review need not mutate the board.
- At most 20 physical observer calls per game, including investigation, failures,
  and any retry. At most two evidence slices of 2 KiB each per incident and one
  investigation follow-up. All observer input is capped at 4,096 tokens per call;
  all generated tokens, including reasoning, at 512. No automatic output escalation.
  Keep normal responses much shorter than that maximum.
- Each observer request has a 30-second deadline. Disable advisory monitoring
  after two consecutive transport/schema failures or exhausted observer allowance;
  persist the reason and retain the independent hard watchdog. Do not stop a
  healthy player because its observer is unavailable.
- Use fresh bounded requests with stable instructions first and new evidence last.
  Do not accumulate conversation history. Persist counters, alert identity, last
  verdict, and consumed/reserved allowance so restarting cannot reset the budget.

For the first backend, use a direct OpenAI API call with configurable model and
`gpt-5.4-nano`, reasoning `none`, as the candidate default. It is a candidate to
evaluate, not a claim of adequate judgment. Verify supported API fields against
official documentation when implementing. The earlier recommendation used the
[nano model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-nano).
Implement a narrow backend boundary and fake backend for tests. An Anthropic/Haiku
adapter and stronger-model fallback are deferred until there is a demonstrated need.

## Execution and commits

Commit this plan before starting implementation. Each stack must deliver a usable
path through launch, execution, evidence, and reporting, with no disconnected
helpers presented as completion. Integrate in order, run the cumulative gate
`python3 -m tools.fast_check`, and commit each passing stack separately. Do not
run balance tournaments or claim GUI checks. Record actual counts and commands;
do not assume an earlier session's test count is current.

For Opus/Sonnet execution: Opus owns shared-file integration and gates. Assign
Sonnet workers bounded work in separate worktrees. Worker A owns progress and
evidence modules; Worker B owns supervisor/client cancellation; Worker C owns
observer backend and accounting. A leads stack 1, B stack 2, C stack 3. After the
interfaces above are pinned, B and C may prepare isolated implementation and
tests in parallel, but their integrated acceptance depends on preceding stacks.
An available worker may prepare stack 4 fixtures independently. No worker edits
another worker's shared functions or launches a paid game. The orchestrator
integrates changes to `llm_client.py`, `game_history.py`, and shared docs.

Keep short handoffs under `tmp/watchdog-exec/`: files owned, interfaces delivered,
tests run, remaining issues. Do not repeatedly spawn observers or send live
transcripts to the orchestrator. This document is a plan only; delegation starts
when implementation is requested.

## Stack 1 — Automatic recording, bounded status, and evidence reads

Implement `tools/run_watchdog.py` for progress projection/evidence access and a
small command entry point. Wire the existing supervisor to launch and poll its
child without blocking; preserve recovery behavior. Monitoring must work during
a single long provider call, not just between turns.

1. Reuse match logs, checkpoints, request contexts, usage sidecars, and Fireworks
   stream files as authoritative evidence. Require a run-owned evidence directory
   for monitored streaming launches. Add only missing lifecycle/freshness signals;
   do not duplicate full prompts or streams in every status packet.
2. Maintain a compact derived status and append-only watchdog journal. Use bounded
   incremental parsing of NDJSON/SSE, including partial UTF-8 and incomplete final
   records. Bound parser buffers and repetition state; index raw ranges before
   discarding working buffers. Do not accumulate assembled streams in the observer.
3. Implement a deterministic repetition detector with a documented minimum passage
   size and window. Repeated boilerplate/tool syntax alone must not count. Record
   exact matches and counts as evidence; no embeddings or semantic scoring.
4. Generate alerts and regular eligibility using an injectable monotonic clock.
   Keep actual game progression, request/tool activity, and stream activity as
   separate measures. Missing files, truncation, or recorder failure produce an
   explicit coverage/degraded-status event and cannot imply a healthy run.
5. Provide status/evidence commands and recording-only launch documentation.
   Restrict evidence reads to indexed run artifacts, reject traversal and symlink
   escapes, and label truncated data. Never log credentials or authorization headers.

Acceptance and commit:

- A fake streaming provider through the real client/supervisor emits fragments,
  accepted/rejected actions and an inspection/review. Status changes while the
  request is open; canonical player prompt hashes are unchanged; no observer
  network calls occur.
- Positive repetition fixtures alert once per incident; normal repeated JSON
  syntax, successful inspection, and simulation-only changes behave as specified.
- Fake-clock tests prove the 300-second schedule and 60-second cooldown without
  real sleeps. Large-stream tests prove bounded reads/buffers and no repeated full
  scan. Missing usage is NULL/unknown, never a byte-derived measured token count.
- Foreign-run, stale/changed-range, oversized and traversal evidence requests fail.
- Existing supervisor recovery tests and the cumulative gate pass. Commit stack 1.

## Stack 2 — Durable stop through subprocesses, checkpoints, and catalog

Connect `stop_run` to a real, bounded cancellation path before an LLM can use it.

1. Persist the stop request atomically before signaling. Serialize finalization
   with natural game completion: an already established engine result wins, and
   a late observer recommendation is recorded as ignored. Duplicate stops have
   one effect. Revalidate active run, request, relevant progress, and evidence;
   reject stale recommendations if the suspected condition has cleared.
2. Make the supervisor own its child process tree, including the command backend
   shell and provider process. Try graceful shutdown, then bounded forced cleanup
   (initial grace: 5 seconds). Verify nested process/session behavior rather than
   assuming terminating the immediate shell kills its children. Do not signal
   unrelated processes. Cancellation must remain responsive during observer I/O.
3. Fence cancellation before another request dispatch or action-batch commit.
   Preserve already committed actions. At an interrupted mutation boundary use
   existing journal/checkpoint reconciliation and report uncertainty; never assume
   rollback or silently replay a possibly accepted batch.
4. Record `observer_interrupted` as a non-gameplay terminal outcome with reason,
   evidence refs, final proven checkpoint, and cancellation/coverage status. Update
   maintained terminal readers, catalog import, replay metadata and reports together.
   Preserve partial raw stream data and dispatched-call identity. A remote request
   may continue billing after local cancellation; record unknown final usage and
   do not claim confirmed remote cancellation without evidence.
5. Intentional stops must not be classified as recoverable infrastructure errors.
   The stop remains effective across supervisor restart and explicit client resume
   of that run. A separately requested new experiment uses a new run identity.

Acceptance and commit:

- Integration fixtures stop a silent/hung provider, a streaming provider, a nested
  child, and a process ignoring graceful termination. All owned local processes
  exit within grace plus a small declared scheduling margin; no new dispatch occurs.
- Exercise stop before dispatch, during request, around batch commit, after natural
  victory, duplicate stop, stale stop, and supervisor crash/restart after stop intent.
- No automatic or direct resume bypass; partial evidence survives; interrupted
  calls remain accounted or explicitly unknown; no invented winner/loss.
- Import twice into SQLite: one terminal outcome, no duplicate calls/actions,
  integrity/FK checks pass, natural winners remain unchanged. Cumulative gate passes.
  Commit stack 2.

## Stack 3 — Cheap bounded checks, investigation, and separate accounting

Wire a maintained API observer into the completed status/stop path. Start in
`observe` mode. No paid requests are needed for implementation acceptance.

1. Add the narrow observer backend with strict structured response validation,
   model/effort/output-limit configuration and request deadline. Its credential
   source is separate from Fireworks. Use fake transport tests through the real
   scheduling path. No shell or unrestricted tools are exposed to the model.
2. Implement the fixed policy above. Input-size enforcement counts the entire
   request including instructions/schema/evidence. Use the supported tokenizer or
   a documented conservative bound including API framing; do not equate characters
   with tokens. Record clipping and coverage; an incomplete packet cannot support
   a claim about omitted evidence.
3. Reserve a call and its maximum token allowance durably before dispatch. On
   uncertain completion keep that reservation consumed; do not reset on restart.
   The 20-call and per-call limits bound exposure even when receipts are absent.
   Make no automatic retries. Investigation uses the same allowance, no recursion.
4. Reuse the ModelCall lifecycle/normalizers for observer receipts. Add the minimal
   explicit call-role support needed to keep player and observer totals separate
   through sidecars, SQLite, CLI, and reports. Tag new calls at the source. Do not
   create fake player requests/turns to attach observer calls; link an observation
   to the request it examined separately from inference ownership.
5. Define migration semantics before changing queries: historical role evidence
   may be unknown; retain historical player-only report behavior for existing
   archives, expose unknown classification, and never silently classify ambiguous
   imports as observer or alter historical measured counts. Test this explicitly.
6. Report player, observer, and combined known spend with coverage for each. Cache
   and reasoning remain subsets according to provider receipts. Retain raw usage,
   response identity, requested/reported model and effort, dated rate source, and
   failed-call counts. Unknown usage has no fabricated dollar value. Ensure the
   player's game-token limit excludes observer calls; both limits apply independently.
7. For `enforce`, permit a semantic stop only after a bounded investigation cites
   repeated non-progress evidence in at least two observations with no intervening
   recovery. Hard budget/time limits stay deterministic. Poor tactics, a long call,
   or a negative material balance alone cannot authorize a stop. Borderline cases
   continue under the existing game budget. Keep tactical hopelessness judgments
   out of the initial stop policy.

Acceptance and commit:

- Fake model paths: continue, inspect then continue, inspect then stop, malformed
  response, timeout, injected player instructions, evidence-limit violation, stale
  verdict, concurrent alert, call-cap exhaustion, and interrupted observer call.
- A game can finish while its observer is pending; late replies cannot stop a
  subsequent game. An observer timeout cannot delay the player's hard deadline.
- Twenty dispatched calls are the absolute ceiling, including investigations and
  restart. No growing history, no budget reset, and no player-prompt changes.
- An observe-mode stop recommendation never kills; the same validated sequence in
  enforce mode exercises stack 2. Model errors disable observation as specified.
- SQLite import/reimport and reports reconcile player/observer/combined receipts
  exactly; retries/unknowns are not lost; old report fixtures remain correct.
- Cumulative gate passes. Commit stack 3.

## Stack 4 — Replay evaluation, final review packet, and operator handoff

Prove the cost/control architecture offline, then prepare a bounded model-quality
evaluation. Implementation completeness and model stop-quality are separate gates.

1. Check available catalogs first. Extract small committed, sanitized fixtures
   from selected recorded long-but-useful requests and loop/failure cases; retain
   provenance hashes and evidence limits. Synthetic cases cover missing failure
   modes, labelled synthetic. Tests must work without ignored `tmp/` archives.
2. Build an offline replay runner that reveals evidence in chronological windows.
   Do not show a future winner or later recovery to an earlier watchdog decision.
   Label cases manually with expected continue/investigate/stop and supporting
   evidence before evaluating a model. Include long useful reasoning, harmless
   repetition, rejected actions followed by adaptation, persistent invalid retries,
   semantic rambling without exact repetition, missing streams/usage, and a bad
   tactical position that still progresses.
3. Keep at least 12 labelled cases: four healthy, four recoverable/suspicious,
   four persistent failures, with at least one multi-turn and one single-request
   case in each applicable group. Separate tuning and held-out cases by incident,
   not adjacent windows. A small set is a smoke evaluation, not general proof.
4. Report false stops, missed persistent failures, detection delay, investigated
   cases, calls/tokens/cost and coverage. The initial model-quality gate is zero
   false stops on healthy/recoverable cases and detection of every labelled
   persistent failure within two eligible observations plus one investigation.
   If it fails, keep `observe` mode and report failure; do not relax labels or
   secretly switch to a larger model to call the plan complete.
5. Generate one bounded post-run review packet automatically: run/source identity,
   actual terminal outcome, progression, flagged incidents/verdicts, evidence index,
   player/observer cost and coverage, and whether any stop affected the comparison.
   The expensive orchestrator reads this once and only retrieves selected evidence.
   A review packet is not a full log concatenation or another automatic model call.
6. Update `docs/LLM_CLIENT.md` launch/accounting/final-report instructions,
   `docs/GAME_HISTORY.md`, relevant agent guidance, and the active Claude handoff
   if present. Include tested commands for recording only, observe, enforce,
   status, evidence, manual stop, offline replay, and final review. Remove active
   instructions requiring recurring LLM polling; preserve historical reports.

Acceptance and commit:

- A no-network end-to-end test launches the real harness with fake player and
  observer transports, completes or stops it, imports the archive, and generates
  the review packet. A second run proves no cross-run artifact/stop leakage.
- Fake-clock replay is deterministic and respects bounded reads/calls. Report
  generation uses zero LLM calls. Documentation examples pass parser/smoke checks.
- Cumulative gate passes. Commit stack 4 and write `tmp/watchdog-exec/HANDOFF.md`
  with commit IDs, gate results, usage/import evidence, and remaining quality gaps.
- Prepare, but do not execute as part of this planning request, an exact paid
  evaluation manifest with selected model, cases, maximum calls/input/output,
  dated prices, and worst-case cost. A paid model evaluation or fresh GLM game
  requires explicit launch authorization. Offline fake success must never be
  reported as nano having passed the quality gate.

## Completion checklist

- Four integrated stacks independently tested and committed; clean intended tree.
- Recording requires no LLM, and a long live request can trigger a bounded check.
- Investigation and total observer exposure are bounded and survive restart.
- A validated stop preserves evidence, cannot restart itself, and is not a loss.
- Observer spend is visible and cannot pollute player comparisons or allowances.
- One generated review packet replaces continuous orchestrator supervision.
- Handoff distinguishes implementation complete, fake/offline tests passed, actual
  model evaluation pending/passed/failed, and live game not run/run. No hidden paid
  validation, no promise of perfect loop detection, and no unrelated gameplay work.
