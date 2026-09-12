# Complete watchdog reporting and Fireworks integration

Status: planned; implementation authorized by the user.
Baseline: `556866c` plus the existing uncommitted reporting patch in
`docs/LLM_CLIENT.md`, `tools/watchdog_replay.py`, and
`tools/test_watchdog_replay.py`. Preserve that work; its original diff is saved
under `tmp/watchdog-fireworks-exec/incoming-reporting.patch`.

## Outcome and scope

Produce honest evaluation/review reports, replace the unwanted OpenAI observer
with Fireworks, and verify one real judgment before any 12-case evaluation.
The user has Fireworks only. Use `FIREWORKS_API_KEY`; never request, inspect or
reuse an OpenAI credential. Preserve gameplay prompts, hard game limits,
recorder/evidence contracts, validated stops, historical archives and native
client usage collection. No live player game, extra provider, new framework,
continuous coding observer, or tactics changes.

One Luna High worker implements the three ordered end-to-end stacks in the
main checkout. Astra researches provider details, reviews integration and runs
bounded live acceptance after the implementation gates. Only one writer edits
tracked files. The worker does not spawn additional agents or make inference
calls. It can use local fixtures and verified provider documentation.

Read `AGENTS.md`, `docs/DEVELOPMENT.md`, this plan, and relevant source. For
usage conventions read `docs/LLM_CLIENT.md`. Do not reread unrelated gameplay
history. Existing historical reports are evidence, not current launch authority.

For each stack: implement the usable path and its tests/docs, run focused tests,
freeze tracked files, run `python3 -m tools.fast_check`, then commit only after
passing. Do not edit tracked files during the cumulative gate: source-fingerprint
tests detect that. Record actual results in `tmp/watchdog-fireworks-exec/HANDOFF.md`.
A failed paid request is not a model judgment, and unknown usage is never zero.

## Stack 1 — Consistent judgment and failure reporting

Finish the existing patch through replay case reports, aggregate reports, and
`tools/watchdog_review.py` / the supervisor's automatic `review.json` output.

- Use one small shared outcome reader/classifier where practical. Read existing
  controller journals and normalized receipts; do not create a second ledger.
- Distinguish dispatch, usable decisions, failed requests, incomplete/missing
  evidence, and completed observations. `inspect` starts an investigation; it
  does not establish a finished judgment if the required follow-up fails.
- A case with zero judgments is unscored with null false-stop/missed-loop values.
  An observation sequence interrupted by a transport/schema failure cannot be
  scored as a model refusing to stop. Earlier successful windows may still prove
  a false stop, but must not make a later unjudged loop a scored miss.
- Preserve actual verdict/failure counts and denominators. Aggregate status is
  failed when no case has usable judgments, partial for incomplete coverage,
  completed only for fully covered evaluation, and explicitly offline for fake
  transports. Completion is not a quality pass. Missing journals remain unknown.
- Per-case persisted `report.json`, aggregate output and final review must agree;
  remove the stale per-case `requested` success-like summary.
- Tolerate torn/non-object journal entries as coverage gaps, not exceptions or
  successful judgments. Keep reads/output bounded and existing role accounting.

Acceptance:

1. All 12 calls/cases fail: zero judged/scored cases, failures counted, null
   accuracy values, and matching per-case/aggregate/review failure status.
2. A real-provider-labelled failed receipt alone cannot report a model evaluation
   as successfully recorded; an absent receipt/journal remains unknown.
3. Cover mixed healthy decisions and failures, inspect then failed follow-up,
   pending calls, malformed journal records and a successful investigation.
4. The existing fake replay still reports its real fixture outcomes and zero
   network calls; do not change labels to force a pass.
5. Focused and cumulative gates pass. Commit the reporting stack.

## Stack 2 — Fireworks observer from launch through accounting/review

Replace `OpenAIObserverBackend` with a Fireworks chat-completions observer.
Update all maintained callers, fake transports, tests, default settings, CLI
examples, plan/handoff status and evaluation manifest in the same stack.

- Reuse the existing Fireworks endpoint/auth convention and `FIREWORKS_USAGE_MAP`.
  Keep observer responses outside game-action parsing. Preserve bounded packets,
  stable instructions first, new evidence last, strict locally validated decision
  schema, no growing history, and no automatic output escalation.
- Remove OpenAI observer-only classes/settings, nano defaults and credential
  references. Do not remove legitimate historical OpenAI/native usage support.
- Preserve input cap 4096, output cap 512 including reasoning, 30-second deadline,
  20 physical calls per supervised game, two bounded evidence reads and one
  follow-up. Any transport-specific limitation must be reported explicitly.
- Verify model-specific structured output and reasoning controls against official
  Fireworks/model documentation. Do not mechanically translate Responses fields
  or assume `reasoning_effort=none` is supported.
- Retain bounded HTTP error evidence: provider, status, structured code, sanitized
  message and receipt/request identity where available. Confirmed exhausted
  credit/account-quota errors differ from transient 429 rate limiting. A generic
  429 alone does not prove exhausted balance. Never record authorization headers.
- Default candidate: `accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b`,
  returned by this account's read-only model catalog. API availability is still
  unproven until Stack 3. If supported settings cannot be verified, report the
  concrete block before making inference calls; no silent model substitution.
- Pin candidate settings, dated rates/source, per-call caps, maximum calls and
  no-cache ceiling in the manifest. The prior OpenAI authorization flag and price
  are obsolete; no serialized flag may override the user's current run instruction.

Acceptance:

1. Mock HTTP tests assert the Fireworks URL, existing credential convention,
   chat messages, supported schema/settings and output cap without network calls.
2. Valid/malformed/truncated responses and HTTP errors preserve dispatch/final
   identity, normalized usage, requested/reported settings and error evidence.
3. Actual `llm_client` + driver + fake streaming player + fake observer reaches a
   validated stop, imports twice without duplicate roles, and produces an honest
   automatic final review. Preserve canonical prompt hashes and stop fences.
4. CLI/default/manifest references consistently use Fireworks. Fake replay and
   existing player budgets/accounting remain correct. Focused/full gates pass;
   commit the provider stack.

## Stack 3 — One-call check, fail-fast evaluation, and bounded live acceptance

Implement the smallest maintained evaluation entry path for one preflight
judgment followed, only on success, by the existing 12 labelled cases.

- One preflight physical request, no retry/follow-up: exercise the actual observer
  payload, transport, response validation, usage and retained evidence. A completed
  validated decision is required; receiving HTTP 200 or consuming tokens is not
  sufficient. Do not consume the 12 cases before preflight succeeds.
- On a confirmed insufficient-credit/account-quota failure, stop the entire
  evaluation immediately. Retain the failed call; mark later cases not attempted
  and metrics unknown. Do not dispatch two failures for each remaining case.
  Auth/config failures also stop launch. Generic transport failures are not
  secretly relabelled credit failures; bounded failure/partial reporting remains.
- Cap the whole experiment at 37 physical calls: one preflight plus at most three
  calls for each of 12 cases, including investigations and failures. Preserve
  call caps across any resume or refuse output-directory reuse; no budget reset.
- Fake execution never makes a paid preflight call. Preserve chronology, fixed
  labels, held-out/tuning membership and retained artifacts.
- Report preflight outcome, attempted/unattempted cases, valid judgments, failures,
  false stops/misses with coverage, normalized input/output/reasoning/cache usage,
  per-model dated cost and unknowns. Never promote enforce mode based on fixtures.

Offline acceptance:

1. Preflight failure means exactly one dispatch and zero case dispatches.
2. Successful preflight followed by a confirmed quota failure in the first case
   makes no subsequent case calls; remaining cases are explicitly unattempted.
3. Generic 429 and confirmed exhausted-credit responses classify differently.
4. Success path remains within 37 physical calls including investigations; fake
   path has zero network calls; no output-directory reuse can reset the budget.
5. Reports and automatic review agree. Focused and cumulative gates pass; commit
   before any live acceptance so the source is frozen.

Live acceptance authorized by this request to execute steps 1–3:

- Astra may run the implemented single-call check using the existing Fireworks
  account, then the 12-case evaluation only if that succeeds. No player game.
- Maximum 37 calls total, each capped at 4096 input / 512 output; no retries,
  additional experiments, model escalation, top-ups, subscriptions or deposits.
- Operational spend ceiling $0.10. The candidate's currently documented rates
  ($0.05/M input, $0.01/M cached input, $0.20/M output) imply a tighter no-cache
  token ceiling of $0.0113664 for all 37 calls. Verify/pin before launch. Do not
  use the old nano quote. Unknown final billing stays unknown.
- Stop immediately on the first preflight failure or confirmed exhausted credits.
  Finish all offline work regardless. If external access fails, record the exact
  provider evidence and leave real judgment/quality explicitly unproven; do not
  claim the code's offline success establishes model quality.

## Sources and final handoff

Read-only account catalog saved at
`tmp/watchdog-fireworks-exec/model-catalog.json` (26 entries; no inference call).
Official references checked during planning:

- https://docs.fireworks.ai/api-reference/post-chatcompletions
- https://docs.fireworks.ai/structured-responses/structured-response-formatting
- https://docs.fireworks.ai/serverless/pricing

Final handoff must list stack commits, actual gate results, preserved incoming
patch, model/settings/rates, source commit, preflight/evaluation artifacts,
measured versus unknown usage/cost, any provider block and remaining quality
failures. Update the old active handoff so Claude sees the corrected current
state; preserve historical run evidence and avoid further implementation/game
cycles beyond these three steps.
