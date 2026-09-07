# Bounded match recovery

## Outcome and scope

An invalid model candidate should receive a bounded repair, and an unexpected
process exit should be logged and resumed when durable evidence proves it is
safe. One logical match keeps its history and budgets across attempts. A win,
resignation, cap, user cancellation, exhausted budget, or ambiguous commit
state stops the match with an explicit reason.

Use two complete code stacks, each reviewed, fully tested, and committed before
the next starts. The last phase plays three games through the supervisor using
parallel Luna subagents. This document plans the work; writing it does not start
implementation or games.

Reuse `tools/llm_client.py`, `tools/llm_supervisor.py`,
`tools/request_recovery.py`, `tools/request_journal.py`, `tools/codex_backend.py`,
and the driver's atomic checkpoints. Keep the existing game actions and tactical
guide. No new recovery service, generic workflow framework, automatic tactical
substitutions, or restart that silently falls back to Greedy.

Known gaps that must be addressed, not assumed solved:

- Final seed 2001 stopped at revision 286 after ten completed side turns. U21
  died in the prior opponent turn; the next draft still delegated it. The
  preview returned `unauthorized_unit`, which became fatal `draft_review_error`.
  The exact source is `tmp/luna-final-20260907/seed-2001/match.ndjson`, with the
  model checkpoint `10-286-model-85e1e79beca194a4db8c663604536ea34d1c128fe7f549990acabda084ec83fe.json`.
- The supervisor recognizes signals and infrastructure records but misses some
  unexpected exits without a terminal record. Its request reconciliation is
  optional, checkpoint detection only checks for a JSON file, and attempt
  selection can consult stale terminal records in a resumed log.
- Request reconciliation expects explicit consumed/committed evidence; verify
  and implement the actual client/driver linkage. Existing mock tests alone do
  not prove that real restart avoids duplicate execution.

## Execution rules

- [x] Write and commit this plan before implementation.
- [ ] When execution is authorized, use Luna/medium for bounded coding tasks;
  the parent reviews and fixes the results. Assign one owner per shared file.
- [ ] Complete Stack 1 and commit it before changing Stack 2 behavior. Do not
  merge stacks merely because agents produced their changes concurrently.

Every code stack must pass `python3 -m tools.fast_check` and `git diff --check`.
The gate must build the current driver and run new integration tests without
skips. Record exact commits, commands, counts, and limitations. Checkboxes need
observed evidence: do not substitute mocked processes, opening positions, or
phrase checks for the execution milestone they claim to satisfy.

## Stack 1 — Invalid candidates repair within the live turn

Files: client query/repair handling, focused and real-driver tests, a small
relocatable seed-2001 fixture, and relevant client/development documentation.

1. Classify driver responses using their structured error codes. Candidate
   illegality, such as an unauthorized/dead unit, is a model error; transport,
   protocol, or checkpoint failures remain infrastructure errors. Enumerate
   the engine codes supported by this path in one small mapping. Unknown codes
   stay visible and do not default to success or an invented safe preview.
2. Apply that classification consistently to player-requested comparisons and
   automatic draft review. Reuse the existing bounded repair machinery. Include
   candidate/action identity when supplied, the rejected draft, error code and
   message, original inspection context, and the final authoritative reminder.
   Do not silently delete U21 or alter the model's action batch.
3. Give the model one repair opportunity for an invalid candidate, within the
   remaining model/tool/repair budgets. Repairing an automatic review does not
   create another unlimited review cycle. A repeated invalid response ends as
   `model_invalid`; it does not qualify for supervisor restart.
4. Preserve valid workflows: a confirmed risky but legal candidate can execute;
   ordinary legal comparisons retain their results; standalone resignation is
   immediate and never previewed or retried.
5. Freeze revision 286 and the exact failing draft as committed, relocatable
   fixtures. Record source log/request identity, source commit from the log,
   checkpoint/board hashes, and the path relocation procedure. Verify U21 is
   absent and the position is ten completed side turns, not revision zero.

Acceptance:

- [ ] Both query entry paths return the real `unauthorized_unit` error to the
  player within the same live revision. Genuine backend/query failures retain
  a typed infrastructure error. Unit tests cover unknown/malformed responses.
- [ ] A deterministic backend replays the archived draft, receives repair
  facts, and submits a legal correction through the real client and driver.
  Verify no invalid prefix executes, no opponent turn runs during repair,
  and the correction changes actual state as its authored actions specify.
- [ ] A second invalid response produces a single terminal model-invalid
  outcome; the supervisor does not restart it. Tests at exhausted budgets
  prove repair does not exceed the existing call limits.
- [ ] Exact prompts, responses, final annotations, request IDs, and revisions
  remain linked in NDJSON and a fresh SQLite import. Inspect the final engine
  checkpoint and events, not just submitted JSON.
- [ ] Parent review, focused regressions, full gate, and diff check pass.
  Commit the code, fixture, tests, and docs together; record the hash.

## Stack 2 — Unexpected exits resume one logical match safely

Files: existing supervisor, client, journal/reconciliation and backend modules;
minimal driver checkpoint metadata where needed; integration tests; client,
development, and history documentation. Change the catalog importer only as
needed to represent attempts and the final outcome correctly, preferably using
existing metadata fields instead of introducing tables.

### Durable identity and commit boundary

1. Use one stable match ID, explicit attempt IDs, unique logical request/batch
   IDs, originating revision, and prompt/response hashes. Keep client/backend
   ID mapping explicit. Emit durable consumed/submitted/committed evidence
   recognized by the existing reconciler; a `forwarded_orders` record alone
   is not proof of a committed batch.
2. Define commitment as a verified atomically published driver checkpoint
   carrying sufficient batch identity. Record its digest, resulting revision,
   completed side turns, partial-batch state, and pending-opponent state. If
   needed, add narrowly scoped execution metadata to link the batch to its
   checkpoint; do not change the gameplay action schema. Publish the link
   before acknowledging commit to close the lost-acknowledgment gap.
3. Select a checkpoint by verified match identity, content hash, and commit
   evidence, never by modification time or the existence of a JSON file alone.
   Account for a published checkpoint whose notification never reached the
   client. Resume a pending opponent boundary exactly once.
4. Reuse a completed unconsumed response only when its request, prompt hash,
   revision, and workflow phase match. Restore that phase's inspection/repair
   context. If the batch is committed, advance from its checkpoint without
   replaying it. If no new commit exists and cleanup proves the request was
   interrupted safely, restore the last committed state and retry the pending
   work. If evidence is contradictory or insufficient, stop explicitly.
   Do not regenerate a response or reroll combat to seek a better result.

### One bounded recovery owner

5. Make the existing supervisor the documented normal automated-game entry
   point. Validate that it and the client use the same match/log/settings.
   Automatically locate the match-owned journal; recovery must not bypass
   reconciliation because a caller omitted `--request-state`.
6. Log an attempt outcome for every client exit, including nonzero exit without
   a terminal, signal termination, and exit zero without a completed gameplay
   record. Add top-level client exception logging where possible. The
   supervisor covers exits the child cannot log, such as SIGKILL. Do not catch
   an exception and continue with partially initialized or uncertain state.
7. Retry transient backend failures within their existing local allowance.
   The supervisor handles process recovery after that allowance; count both
   levels so nesting cannot multiply retries silently. Confirm old processes
   are gone and no request/session lock is still owned before starting another
   attempt. Never dispatch a second active model request for the same session.
8. Use at most three process restarts per logical match and at most two for the
   same `(error code or exit category, revision, pending phase)` without durable
   progress. Persist these counters across supervisor restarts. Use short
   bounded backoff. A repeated deterministic failure stops with its actual
   error and checkpoint, not an endless resumption loop.
9. Preserve total match cap, model/tool counts for an unfinished turn, configured
   token limits, cumulative measured usage, and remaining turn deadline across
   attempts. Crash/retry does not reset them. Unknown usage stays unknown;
   replaying an archived answer is not billed as a new native call. Respect
   an explicit user cancellation and never resume gameplay-terminal or
   model-invalid outcomes, even if the process later exits nonzero.

### Evidence and failure-injection gate

10. Retain append-only attempt records within the logical match, with explicit
    boundaries so old terminal records cannot decide a new attempt's status.
    Record cause, exit code, phase, request/batch IDs, checkpoint hash, recovery
    decision, and response reuse/regeneration. Report one logical match and
    all its attempts. Preserve unexpected errors and measured costs even if
    play eventually succeeds. Missing logs/checkpoints or write failures must
    produce an actionable stop, not pretend that evidence was saved.

Use a real supervisor/client/driver and deterministic backend. Synchronize
interruptions on observed protocol events or test-only barriers, not timing
sleeps. Add the smallest test seam needed; no public production fault-injection
CLI. Run each recoverable case twice independently to catch accidental timing
dependence, and compare it with uninterrupted execution of the same responses.

| Injected interruption or error | Required observable result |
|---|---|
| Completed answer saved, before client consumption | Original matching answer is reused; no extra native request or duplicate action. |
| Batch sent, before durable commit publication | Prior committed state and saved request are reconciled; uncommitted effects do not survive. |
| Checkpoint published, before acknowledgment is read | Published batch is recognized as committed and is never submitted again. |
| Model finish committed, before opponent completion | Resume pending opponent processing once; preserve RNG and side-turn accounting. |
| Accepted incremental partial batch, before next request | Retain that partial's effects and remaining partial/call budgets. |
| Unexpected code-1 exit, SIGKILL, or code-0 exit without terminal | Supervisor logs the missing outcome and resumes only with verified safe evidence. |
| Corrupt/missing checkpoint, mismatched identity, active/unknown request | Explicit unrecoverable result; no automatic action or second active request. |
| Same failure repeated at the same revision | Persistent per-error and match restart limits stop the loop. |
| Win, resignation, turn cap, model-invalid, or user cancellation | No restart; retain the final outcome even if cleanup fails. |

Acceptance:

- [ ] Real interruption tests reach the intended boundaries, resume to a
  gameplay result, and match the uninterrupted canonical engine state,
  including roster/HP/XP, positions, gold, villages, RNG, and side turns.
  Assert each committed recruitment, movement, attack, and opponent boundary
  occurs once. Distinguish provisional pre-commit events from committed ones.
- [ ] Tests prove no restart refreshes model/tool/turn/token allowances or
  reuses an answer from a different prompt/revision/phase. Unknown remote
  completion stops safely rather than being treated as a fresh request.
- [ ] Recovery counters survive restarting the supervisor itself; two
  simultaneous supervisors cannot control the same match. Cancellation and
  terminal recognition tests include stale prior-attempt records.
- [ ] A fresh catalog import preserves one logical match, its final outcome,
  total request/usage counts, and attempt evidence without double-counting
  replayed responses or batches. Reimport is idempotent; integrity and foreign
  keys pass. Label any unavailable boundary/event details as unknown.
- [ ] The documented supervisor command runs a deterministic smoke game from
  a clean checkout with a verified interrupted-and-recovered attempt.
- [ ] Parent reviews implementation and fault-test evidence, fixes defects,
  and runs the full gate and diff check. Commit this complete stack with docs
  and record the hash before native evaluation. No incomplete milestone is
  waived merely because ordinary tests pass.

## Final phase — Three supervised games via parallel Luna subagents

After both stacks pass and are committed, read `docs/LLM_CLIENT.md`. Start
exactly three Luna subagents in parallel, one match supervisor per game.
Use fresh matches, seeds 2001/2002/2003, `big_battle_6`, Undead versus Undead,
300 gold, model side 0, single-batch turns, and Greedy with normal driver
recruitment. Set `--max-turns 50`: fifty completed side turns, approximately
twenty-five model turns. Do not restart the match from the opening to replace
a failure; automatic verified recovery remains part of its original match.

Freeze identical explicit settings: native `gpt-5.6-luna` at high effort,
eight model calls and four tool calls per model turn, query budget 300 seconds,
model timeout 900 seconds, native timeout 840 seconds, turn timeout 2,100
seconds, and supervisor limits above. Retain the canonical client prompt
unchanged. Give each match its own log, checkpoints, request journal, sidecar,
stdout/stderr, and recovery records. Record source, driver, guide, and settings
hashes before launch. Do not inject faults or tune prompts during these games.

- [ ] All three logical matches reach gameplay completion or a bounded,
  explicitly unrecoverable failure. Preserve every attempt; do not manually
  reset limits, replace failed games, or count failures as draws.
- [ ] Import the original logs into a fresh catalog and inspect it before
  individual archives. Cross-check all outcomes against raw attempt/terminal
  records, exact prompt/result hashes, request/batch links, and checkpoints.
  Catalog integrity and foreign-key checks pass.
- [ ] Review each recovery or error: identify what caused it, whether state
  was preserved, which work was reused, and whether the next decision made
  progress. Zero live recovery events is a valid result, but is not evidence
  that fault recovery was exercised outside the deterministic tests.
- [ ] Commit `docs/experiments/bounded-match-recovery-evaluation.md` and update
  this plan with actual evidence. Include a three-game table of outcome,
  completed side/model turns, process restarts, local retries, invalid-candidate
  repairs, native calls versus answer reuses, measured tokens, wall time, and
  valid submitted annotations. Distinguish resumed matches from uninterrupted
  ones and requested model settings from unreported runtime settings.
- [ ] Report both implementation commits, test/fault coverage, all three game
  results, and remaining limitations. Three games measure the observed cohort;
  they do not establish a reliable win rate or prove universal recovery.

Completion requires both tested stacks and the three-game evidence report.
Do not mark recovery complete merely because processes exited or SQLite opened.
