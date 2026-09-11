# GLM diagnostic corrections and observed retest

Status: stacks1–4 implemented and cumulatively tested; authorized stack5 live
retest is next. Execution record: `docs/experiments/glm-followup-corrections.md`.
Baseline: `85373d4e0e12e742977967f2284e2ec5a234309c`.
Evidence: `tmp/quick-play-glm-efficiency-xbsjhb82/REPORT.md`,
`OBSERVATIONS.md`, `engage-error-reproduction.json`, and
`turn-attribution-evidence.json`. Historical artifacts are immutable.

## Result and limits

Fix every confirmed defect found in the diagnostic, address the observed
decision overhead using the smallest existing controls, then run ONE fresh
Fireworks GLM 5.3 Flash game and inspect what improves or still fails.
Plumbing tests prove correctness, not playing strength or token savings.

Keep the game rules, unit balance, sampling/reasoning defaults, output escalation,
and existing choice/coordinate and batch/focused modes. No second LLM, planner
service, new strategy language, automatic tactical rankings, unlimited transcript,
automatic retry of an uncertain paid request, or unrelated UI redesign.
Use existing target inspection, partial batches, agenda, and bounded intent.
Native provider conversation continuation is unproven for this model; address
decision continuity through existing committed intent first and report the
remaining hypothesis rather than claim it solved.

## Ownership and execution

Write this plan before starting Luna workers. Parent integrates in the order
below; each completed stack gets focused tests, `python3 -m tools.fast_check`,
an execution-record entry, and its own commit. Do not commit an untested mixture.
The common gate covers Rust, Python, Lua and diff whitespace; no broad unfiltered
`cargo test` tournaments. Save logs in `tmp/glm-followup-exec/` and summaries in
`docs/experiments/glm-followup-corrections.md`.

Workers use isolated worktrees from the plan commit, so shared files cannot be
overwritten by another agent. They may implement in parallel, but must not merge,
launch paid calls, or edit another worker's branch. Commit coherent reviewed
patches locally after focused checks; the parent performs the cumulative full
gate before committing each integrated stack. Parent resolves shared-file
integration explicitly and preserves new behavior from earlier stacks.

- Luna A: stack 1, `llm_client.py` contract/repair/decision context, playbook,
  contract tests and relevant client docs.
- Luna B: stack 2, driver error/profile code, progress helpers in `llm_client.py`,
  engine/progress tests and related docs. Coordinate touched Python functions.
- Luna C: stack 3, history import, request identity/terminal emission in
  `llm_client.py`, accounting/coverage/review tests and history docs.
- First free Luna worker: stack 4, Fireworks transport/evidence/tests/docs;
  start after its existing work is handed off. Parent owns shared integration,
  baseline evidence reproduction, full gates, execution report and live retest.

Every worker reads AGENTS.md, docs/DEVELOPMENT.md and docs/LLM_CLIENT.md.
History work also reads docs/AGENT_GUIDE.md and docs/GAME_HISTORY.md, inspecting
the existing SQLite catalog before raw logs. Missing evidence stays unknown.
Small tracked synthetic fixtures must reproduce real shapes; tests must not
depend on ignored historical files or paid network access. Use the historical
archive as an additional manual acceptance gate.

## Stack 1 — Usable action/tool contracts and bounded decisions

Outcome: a model can request information, repair that SAME request, execute one
engagement and continue the current turn without writing an unnecessary essay.

Implementation:

1. Generate separate action-envelope and bare-tool rules. Bare tools carry only
   their documented keys; no decisions, intent or agenda. Focused mode requests
   annotations only for consequential decisions, matching its validator; batch
   mode retains full authored-order coverage. Missing optional annotations never
   block legal execution. Keep stable rule IDs and annotation evidence semantics.
2. Preview and inspection validation identifies missing/extra keys and bad values.
   Tool-shape repair preserves tool type and candidates/IDs rather than asking
   for an action envelope. Use the same bounded budgets and parser on normal,
   repair and final-only paths. Final-only still means no query or partial reply.
3. Clarify stationary Engage steps; a target's death skips remaining steps.
   Completing one engagement is not ending the turn. After results, consider
   useful remaining attackers before the existing T7 finishing decision.
4. Make the existing active objective and committed intent prominent in focused
   dynamic context, without hiding global recruiter danger, economy or live board.
   Intent stores the reason/constraint behind settled choices, not a duplicate
   roster. Preserve it across successful partials, inspections and resume; rejected
   proposals/simulations cannot overwrite it. No extra planning-only model call.
5. Tighten existing tactics: target inspection for uncertain attack origins; unit
   inspection for a specific unit's retreat/deployment; compare movement-inclusive
   danger with the SAME measure; forecast hits and kills are probabilistic.
   Village ownership persists, so healthy holders may redeploy. Keep wording
   concise; do not append a second universal checklist.
6. Clarify completion-audit readiness: an unused attack flag alone does not prove
   a legal target exists. Separate remaining movement/attack flags from actual
   attack coverage using existing facts; update maintained consumers if renamed.

Acceptance:

- Scripted real-driver run: malformed preview containing action metadata ->
  precise repair -> bare corrected preview -> result -> legal partial combat ->
  fresh observation -> explicit finish. No premature opponent turn or free budget.
- Both encodings/modes agree with their annotation validators. A bare inspection
  needs zero action metadata; consequential annotations remain reviewable.
- Intent/active task survive inspection and partial/resume; rejected actions or
  draft reviews cannot publish speculative state as committed memory.
- EndTurn is not required after one target, and focused task context adds no model
  calls/engine queries. Static-prefix/cache tests pass; one live-state footer last.
- Guide growth stays bounded: at most 15% over baseline byte count; every added
  sentence addresses a listed failure. Small helper text replaces duplication.

Commit: `fix(harness): align tool contracts and focus incremental decisions`.

## Stack 2 — Trustworthy macro errors, progress and mechanical facts

Outcome: the same corrected prompt can act on accurate engine facts and recover
from an illegal combat origin without being told a living unit disappeared.

Implementation:

1. Engage forwards the actual failed nested move/attack code and message, plus
   step index, subaction and IDs. Preserve transactional rollback and successful
   target-death skipping. Do not alter combat, RNG or attack legality.
2. Count committed controlled-side macro movement in TURN_PROGRESS and resume
   reconstruction. Preserve delegated_greedy event attribution. Prefer live flags
   or a shared committed-progress helper; never count opponent or simulated moves.
3. Retain faction names and known recruit pools. Profiles include all living types
   on both sides plus both known recruit pools, deterministically ordered; exclude
   unrelated unit definitions. Render abilities and concise authoritative meanings
   (including regenerates_8 and leadership), preserving unknown versus known empty.
   Keep attack specials/resistance/promotion facts already present.
4. Show authoritative phase modifiers: Dawn/Dusk neutral, Day lawful+25/chaotic-25,
   Night reversed; neutral unaffected. Respect current/opponent/next-round phases.
   Avoid an independent Python rules engine: verify wording against engine tests.

Acceptance:

- Real-driver illegal-origin fixture reproduces the old UnitNotFound laundering;
  corrected Engage and equivalent primitive actions identify NotAdjacent.
  Distinguish unreachable destination, spent action, real missing unit and error
  in a later step. Current batch rolls back; earlier partials remain committed.
- Stationary Engage succeeds; target death skips later steps without moving them.
- Recruit -> MoveGroupToward -> next prompt -> resume has matching live flags and
  progress summary, with original provenance in imported events.
- Opening prompt includes own recruiter, enemy faction/recruit profiles, troll
  regeneration and exact phase modifiers. Promotion introduces a friendly type
  correctly. Unknown abilities remain unknown; profile order/hash deterministic.

Commit: `fix(harness): preserve engine errors and complete tactical facts`.

## Stack 3 — Complete outcome and usage attribution through SQLite

Outcome: new and recoverable old incremental games have honest outcomes and full
request/turn attribution, including paid work in an interrupted open turn.

Implementation:

1. Put canonical side_turn_id on successful and failed model_request records,
   taken from the identity allocated before dispatch. Retain revision and request
   ID on every path, including output exhaustion, repair and provider exceptions.
2. Emit consistent terminal metadata on maintained failure exits (preserve typed
   diagnostic records where useful). Import historical terminal-bearing model_error
   and other actually observed maintained failure records. Store end time, elapsed
   time, terminal reason, failure code, final proven state; never call failure a loss.
   Reimport updates these fields without duplicate snapshots, requests or calls.
3. Import explicit request/turn identity after validating game/turn membership.
   Recover historical identity from matching archived request contexts/journals or
   proven committed boundary chains. Reject conflicts; no nearest-revision or
   arbitrary range inference. Open-turn start revisions and intermediate partials
   must not lose their requests. Use normal import/backfill paths, no SQL patches.
4. Fix coverage to distinguish complete call records from measured token fields.
   One failed call without usage yields partial/unknown measured coverage, never
   a misleading complete usage badge. Keep cache-write unknown if unreported.
5. Investigate the historical unattached handoff review and repair any supported
   identity/provenance mismatch. If it genuinely lacks proof, retain a precise gap;
   do not invent a link. Verify which reasoning blobs are annotations versus raw
   provider reasoning; preserve that distinction in docs and reports.

Acceptance:

- Scripted incremental game with at least two partials, a completed turn, and an
  open turn ending in provider failure: 100% physical-call/request/turn linkage,
  known usage sums unchanged, failed-call fields unknown, outcome infrastructure.
- Reimport twice: same IDs/counts/usage; no foreign-key or dangling links. Explicit
  conflicting/foreign identity cannot attach a request or silently overwrite truth.
- Historical acceptance uses a scratch COPY of the prior archive/catalog: 25 calls,
  24 measured, total993914, reasoning660682; all25 turn links recovered from its
  proven contexts; failed call remains unknown; 22 snapshots/307events preserved.
  Original archives/catalogs remain byte-identical. Document review-link outcome.

Commit: `fix(history): retain failure outcomes and incremental usage identity`.

## Stack 4 — Stream and preserve provider evidence

Outcome: the maintained Fireworks adapter can expose long-response progress and
retain received evidence if transport fails; a partial response never executes.

Use documented SSE streaming behind an explicit `--stream` option and use it in
the authorized retest. Keep non-streaming as a legitimate transport option for
comparison. This addresses long silent requests and lost partial evidence; do not
promise it eliminates all upstream504s. API reference checked during planning:
https://docs.fireworks.ai/api-reference/post-chatcompletions
https://docs.fireworks.ai/guides/reasoning

Implementation:

- Parse data-only SSE frames with the standard library, assemble content and
  reasoning_content separately, retain model/response IDs and final usage. Request
  stream usage using the documented mechanism, including final empty-choice chunks.
- Optional match-owned evidence directory records exact payload/prompt hash,
  incremental received chunks, completed response or partial/error receipt, and
  request context. No authorization headers/secrets. Use this maintained recorder
  for the retest rather than another temporary transport implementation.
- Require a complete stream and valid finish before returning actionable content.
  Handle timeout/EOF/malformed/error frames as uncertain failures with durable
  partial evidence. Preserve usage if supplied; otherwise unknown, never estimated.
  One physical call means one dispatch/final sidecar identity, not one per chunk.
- Preserve existing output-limit escalation and error types in streaming mode.
  No automatic retry of HTTP504 or incomplete responses. No sampling/effort change.
  Import/report raw provider reasoning distinctly from decision annotations if
  adding evidence import; otherwise document exact available evidence locations.

Acceptance:

- Fake/local SSE tests cover fragmented frames/UTF8, reasoning/content deltas,
  empty choices with usage, DONE, length finish, malformed frame, missing DONE,
  interrupted stream with/without usage, HTTP504, IDs and missing credentials.
- Driver+scripted/local transport test proves no partial JSON actions are submitted
  and all charged/unknown calls are recorded once. Complete stream and equivalent
  non-stream fixture give identical content, normalized usage and canonical prompt.
- Passive recorder has25/25-equivalent prompt/hash checks; logs contain no API key.
  CLI docs show streaming launch and interrupted-run accounting clearly.

Commit: `feat(fireworks): stream responses with durable diagnostic evidence`.

## Stack 5 — Combined acceptance, one paid retest, and fresh diagnosis

Parent runs the combined gate after integration; fixes regressions using Luna
workers and commits the tested fix. Save source/driver hashes and clean status.
Publish the implementation handoff before launching the game.

The user explicitly authorized this retest: no additional permission or48-cell
pilot. One fresh isolated GLM5.3Flash game, same seed771125826, map/factions/gold,
focused/choices/incremental,50side-turn cap,1M measured-token game budget,
128k->512k existing exhaustion policy, provider-default sampling/reasoning.
Use `--stream` and the new evidence recorder; document that transport change.
Never change the canonical prompt or checkout during play. Budget is checked
between responses and can overshoot; an uncertain failed request has unknown
usage and must not be blindly retried. Stop at game end, cap or terminal failure.

Observe first three responses, first combat, every repair/review, and ending.
Classify useful deliberation, unsupported/wasteful reasoning, understandable weak
decisions, and missing facts/control. Check all prior bug signatures explicitly.
Compare requests/tokens to first capture, first kill and completed own turns;
distinguish open-turn cost, randomness, engine-query latency, provider latency and
cached input. This single combined retest is descriptive, not causal proof.

Import and verify one replay/catalog with complete event/request provenance.
Final report includes winner or stopping cause, source commit, input/output/
reasoning/cache totals and coverage, known cost and unknown failed-call charge,
aggregate_only_request_ids and unassigned_calls at game AND turn levels. Reverify
current official pricing. Preserve raw reasoning/partial evidence and distinguish
it from annotations. No source changes midgame; newly discovered issues go in the
report with reproducible evidence and next steps. An infrastructure failure or
no strategic improvement is a valid diagnostic outcome, not a reason to hide it.

Commit final tracked execution report and plan status; ignored paid evidence stays
in its isolated archive with a linked `tmp/glm-followup-exec/HANDOFF.md`.
