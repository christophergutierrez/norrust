# Effective profiles, carried purpose, bounded review inspection, and effort control

Status: in progress, started 2026-09-11. Implementation complete 2026-09-12;
Stack D (the observed retest) has NOT run and no paid game has been launched.
Baseline: `b46dced`; prior tested gameplay source `0bc1a8e`.

| Stack | Integration commit | Python tests | Result |
|---|---|---:|---|
| A | `2d88e5b` | 732 | Effective terrain profiles, rejected-unit repair facts, movement-fallback correction |
| B | `bafd14d` (merged) | 739 | Bounded inspection purpose, next-phase local facts |
| C | `7087076` (merged) | 752 | Bounded review inspection, preview revision provenance, effort pass-through |
| Integration | `a70fea7` | 754 | `inspect_units` purpose via one shared validator |

Each cumulative gate ran `python3 -m tools.fast_check` (Rust, Python, LuaJIT)
and passed with exit 0 before its commit. Gate logs are under
`tmp/glm-inspection-exec/`. No interactive GUI acceptance is claimed, and no
balance or unfiltered Cargo suite was run.

During integration the parent found that Stack A's first profile stated the
wrong movement fallback: `norrust_get_unit_terrain_info` fell back to the
tile's `movement_cost`, but every real `find_path`/`reachable_hexes` caller
passes `default_movement_cost = 1`, so the engine charges 1. This was
reachable on the retest board -- `mountains` has tile cost 3 and 15 types in
the Northerners/Loyalists roster closure list no `mountains` entry -- so the
new fact would have been confidently wrong for those units. The reported
cost now matches what pathfinding charges, with a regression test pinning
the two together. Defense was already correct and is unchanged.
Evidence: [GLM decision-context retest](../experiments/glm-decision-context.md),
game `e27040476dcb31dd0c5c9a88d9230c74`, archive `tmp/quick-play-glm-decision-k41byol0`.
Read that catalog before raw archives.
Report: [`../experiments/glm-inspection-handoff.md`](../experiments/glm-inspection-handoff.md).

## Outcome and limits

Fix the five remaining harness findings in that report, then have a Sonnet
subagent launch and observe ONE fresh GLM 5.3 Flash game. The parent reviews the
recorded evidence independently and reports remaining bugs and improvements.
Neither a win nor lower token use is an implementation acceptance gate.

Keep this small. Do not add another planner, generic workflow framework,
speculative refactor, new model, mandatory tool call, or large tactics
expansion. Preserve engine mechanics, action schemas, atomic rollback,
query/review/repair budgets, strict parsing, untrusted-data framing, live versus
simulation separation, cache layout, prompt byte caps, and output-limit
escalation (131072 -> 524288; three exhaustions at 524288 stop). Preserve the
improvements already delivered by `b778f7e`, `a63ee0b`, and `0bc1a8e`: draft
rationale continuity, compact local inspection facts, budget classification,
zero-call turns, and normalized review coverage. Raw historical evidence is
immutable.

These are model mistakes, not harness defects, and get no new rule or engine
change: ignoring supplied legal destinations, delaying an already-affordable
Whelp, and claiming Bowmen cannot retaliate in melee against their explicit
short-sword profile and nonzero forecasts. Improve misleading wording only where
justified, and replace conflicting lines rather than accumulating guides.
Supplying better facts is not a promise that the model will use them.

## Work split and integration

Commit this plan before delegation. Three Sonnet workers build isolated stacks in
separate worktrees created from the plan commit. Each reads `AGENTS.md`,
`docs/DEVELOPMENT.md`, and the relevant sections of `docs/LLM_CLIENT.md`; none
performs repeated full-repository reconnaissance or reads `.paul`.

Stacks A, B, and C may be built in parallel. Integrate **A, then B, then C**.
Shared-file ownership is by function, not permission to overwrite another
worker:

- **A** owns `unit_type_profile` in `norrust_core/src/bin/greedy_driver.rs`,
  `compact_unit_type_profiles`, and `candidate_repair_prompt` in
  `tools/llm_client.py`.
- **B** owns `validate_inspect_target_request`, `validate_inspect_targets_request`,
  `validate_inspect_hex_request`, `build_local_execution_context`,
  `local_execution_projection`, `_local_guardrail_data`, and the focused
  local-context lifecycle inside `run()`.
- **C** owns `query_bounded_comparison`, the draft-review block in `run()`
  (the `complete_model(review_prompt, ...)` path and its repair), and
  `tools/fireworks_backend.py`.

The parent resolves overlaps, owns cross-file integration, runs
`python3 -m tools.fast_check` after each integrated stack, and commits that
stack only after its cumulative gate passes. Never run unfiltered cargo tests or
balance tournaments. Workers commit their own work, run focused meaningful
tests, and write ignored handoffs under `tmp/glm-inspection-exec/`. No
interactive GUI acceptance is claimed.

Every stack must connect delivered provider prompt -> response/tool parsing ->
driver behavior -> logging/accounting where affected. An isolated helper with no
proven path through a real client envelope does not satisfy its acceptance gate.
Tests use real client paths and real driver envelopes, never invented payload
schemas, and never depend on ignored archives under `tmp/`. Extract minimal
reusable fixtures instead. Update maintained callers, tests, docs, tool schemas,
canonical prompts, examples, and accounting instructions inside the same stack;
add no compatibility wrapper for a superseded development interface.

## Stack A — Effective terrain profiles and usable repair facts

Owner Sonnet A. Finding 1 in the report.

1. Add effective per-terrain movement cost and defense to the canonical unit
   type profile. `unit_type_profile` currently emits `def_id`, `cost`, `max_hp`,
   `movement`, `alignment`, abilities, attacks, and resistances only; the
   numbers live in `UnitDef.movement_costs` and `UnitDef.defense` and never
   reach the prompt. Emit both maps with the engine's real fallback semantics,
   which `norrust_get_unit_terrain_info` documents and implements as
   `unit.movement_costs[terrain_id] -> tile.movement_cost` and
   `unit.defense[terrain_id] -> tile.defense`. Name the fallback explicitly in
   the payload rather than silently materializing per-tile values; the tile term
   is board data, not unit data. State that 99 is impassable.
2. Render those values compactly in `compact_unit_type_profiles`, extending the
   existing `TYPE` line rather than adding a second card. Reuse the stable
   shared profile so repeated unit types stay factored, preserve the existing
   cache layout and byte caps, and keep the readable resistance descriptions
   unchanged. Missing values stay `unknown`. Retain the profile reference in the
   local inspection views that already cite it so a focused follow-up can read
   a destination's cost without another query.
3. Make a rejected unit's authoritative legal options available during repair.
   `candidate_repair_prompt` currently returns the validation error without the
   failed unit's own reachable set. When a pre-submit rejection names a unit,
   include that unit's revision-pinned legal destinations from the existing
   inspection/tactical result already in scope, within current query budgets and
   byte caps, and add no extra engine query when the facts are already present.
   Say explicitly when they are not available rather than omitting the block.
4. Label those destinations honestly. Zero *direct* attackers is not a safety
   guarantee: the open bound removes blockers and zones of control, and later
   actions in the same batch mutate both. Reuse the existing direct/open
   threat-scope wording; do not invent a new safety score, ranking, or
   truncation, and do not hide destinations.

Fixtures and acceptance:

- A recorded-position fixture reproducing the Naga U22 case at revision 85: 7
  movement points, destinations costing 10, 8, and 6. The rendered `TYPE` line
  must let a reader derive those three costs, and the engine's own
  `norrust_get_unit_terrain_info` must agree with the rendered profile plus
  fallback for each of the three hexes.
- A fixture where a unit type omits a terrain entry, proving the tile fallback
  is applied and labelled, and one where the tile value is also absent, proving
  `unknown` rather than a fabricated number.
- A real-driver fixture reproducing the revision-314 Grunt U11 rejection: the
  repair prompt contains that unit's legal destinations pinned to the live
  revision, marks direct versus open threat scope, and does not assert safety.
  A rejection naming no unit, and one where no inspection result is in scope,
  both render the explicit unavailable marker.
- Rust unit tests for the new profile fields; existing prompt byte caps and the
  byte-identical fixed prefix for an unchanged state and config still pass.
- Full `python3 -m tools.fast_check` gate, then the stack commit.

## Stack B — Carried operation purpose and retained next-phase facts

Owner Sonnet B. Finding 2 in the report.

1. Add ONE bounded, validated, optional provisional `purpose` field to the
   inspection requests. `validate_inspect_target_request` and
   `validate_inspect_targets_request` currently reject every key outside
   `{tool, unit_id}` / `{tool, unit_ids}` with "bare tool requests carry no
   action metadata", which is exactly why R15 could send only
   `inspect_units [4,5,9]`. Accept a single short string, enforce an explicit
   character maximum consistent with the existing hold-reason convention, and
   reject any other added key with the same strictness as today. Apply the same
   treatment to `validate_inspect_hex_request`. Update the canonical prompt,
   tool schema, and examples in the same stack.
2. Carry that purpose through the actual client lifecycle as provisional
   operation state, separate from committed `intent` and from the agenda.
   `build_local_execution_context` already distinguishes `objective` from
   `operation`; put the purpose in `operation`, render it through
   `local_execution_projection` with untrusted-data framing, and label it as the
   requester's provisional purpose rather than an authoritative instruction. Do
   not retain raw reasoning, and never infer an action, hold, or garrison from
   it.
3. Define and test its lifecycle explicitly. The purpose is replaced by a fresh
   reinspection, retained across an engine repair of the same operation, cleared
   by an accepted partial revision that already invalidates the local context,
   cleared when the inspection result is unavailable, and never promoted into
   committed memory when the draft it justified is rejected. It never survives
   into the next side turn.
4. Retain the already-known next-phase facts in `_local_guardrail_data`, which
   today keeps only `"phase": state.get("time_of_day")`. `compact_observation`
   already reads `next_opponent_time_of_day` and `next_round_time_of_day` from
   the tactical surface; carry both into the local guardrails with the same
   two-phase distinction and the same `?`/unknown handling. This needs no extra
   query. R24 guessed the future modifier from a stale "Night turn 10" intent
   while R23 had been given opponent Day and next round Dusk.
5. Address the local-to-whole-turn boundary. R16 expanded a three-unit view into
   army-wide planning. When the model's operation demonstrably exceeds the
   inspected scope, the whole-turn review must have facts matching its scope;
   state the scope of the local view plainly in the projection so a wider plan
   is recognizably unsupported by it. Do not restore the entire global prompt
   into every local operation.

Fixtures and acceptance:

- Real-client mocked response sequences prove a purpose survives
  inspection -> local follow-up, is visible in the delivered prompt with
  untrusted framing, and is absent with an explicit marker when not supplied.
- Each lifecycle branch above has its own test: reinspection replacement,
  repair retention, accepted-partial invalidation, unavailable result, rejected
  draft, and side-turn boundary.
- Over-length, non-string, and duplicate-key purposes are rejected; every other
  unknown key is still rejected with today's message.
- A local guardrail fixture shows current phase, next opponent phase, and next
  round phase together, and shows the distinct unknown forms when the surface
  omits them.
- Matched local prompts remain smaller than the equivalent full follow-up with
  the same result; existing caps and the byte-identical fixed prefix still pass.
- Full gate, then the stack commit.

## Stack C — Bounded review inspection, preview provenance, and effort control

Owner Sonnet C. Findings 3, 4, and 5 in the report.

1. Carry the known revision into nested preview labels. `query_preview_batch`
   already copies the envelope's `state_revision` into its returned body;
   `query_bounded_comparison` returns the raw body and drops it, so R12's
   nested sampled rows read `unknown` while the preview header separately
   received 167. Apply the same envelope-to-body carry, and add coverage on the
   real envelope-to-renderer path rather than on a hand-built body. Do not
   confuse the roles: an automatic review's baseline is candidate index 0 and
   its draft index 1, while explicit-preview C0/C1 are user-proposed candidates.
   Candidate identities and results were already correct; this is presentation
   provenance only.
2. Add a bounded inspection path out of the review. The client deliberately
   calls `complete_model(review_prompt, allow_tools=False)` and accepts only
   actions, so R20 identified `inspect_target` as the way to resolve an
   alternative attack and was then forbidden from asking. Route an
   information-seeking review response back through the existing
   inspection/correction flow: at most one inspection per review, consuming the
   existing tool and per-turn model-call budgets, carrying the draft identity
   and its purpose, appending the compact inspection result to the same review
   prompt, and then completing with tools disallowed. Exhausted budgets fall
   back to today's behavior with an explicit recorded reason.
3. Preserve atomicity and termination. No recursive review cycle, no second
   review slot, no duplicate commit, no silently raised budget, no stale facts
   surviving a revision change, and no speculative memory becoming committed
   when the draft is not accepted. Record the inspection with its review ID,
   request ID, side-turn ID, and prompt hash the way the existing
   `draft_review` and `draft_review_repair` records do, so normalized review
   coverage stays complete. An inspection is not proven to have prevented the
   historical losses; this removes a contract limitation, it does not promise a
   better outcome.
4. Implement explicit provider reasoning-effort pass-through.
   `_stream_payload` in `tools/fireworks_backend.py` sends no effort field, and
   `_reply_from_final` hardcodes `requested_reasoning_effort` and
   `runtime_reasoning_effort` to `None`. Verify the current Fireworks and model
   documentation before choosing supported values; the report's starting points
   are the Z.ai GLM-5.3-Flash Hugging Face card, the vLLM recipe, and the
   Fireworks reasoning guide. Add an explicit option that sends only documented
   supported settings, record the requested value and any provider-reported
   runtime value as separate provenance fields, and keep both `unknown` when the
   provider reports nothing. Reject an unsupported setting honestly with a clear
   error; never silently map it to a nearby value, and never claim a runtime
   effort the provider did not report.
5. Omitting the option must produce a payload byte-identical to today's, so the
   authorized retest keeps the prior provider-default effort and sampling
   settings. Do not run a paid low/high bakeoff. Record that comparison in the
   report as a subsequent experiment requiring separate authorization.

Fixtures and acceptance:

- A real envelope-to-renderer test where the bounded-comparison envelope knows a
  revision the body omits: nested sampled-transition rows render that revision,
  not `unknown`. A genuinely unknown revision still renders `unknown`. Review
  baseline/draft indices and explicit-preview candidate roles stay distinct.
- Real-client mocked sequences for the review inspection: one inspection
  granted and its facts present in the final review prompt; a second inspection
  request in the same review refused; exhausted tool budget and exhausted
  per-turn call budget each falling back with a recorded reason; a revision
  change invalidating stale facts; a rejected draft not committed; no recursive
  review; exactly one commit.
- Offline payload tests: default payload unchanged byte-for-byte; each supported
  effort value present exactly once in the request body; an unsupported value
  rejected before any network call; requested-versus-reported provenance
  surfaced in the reply cache and carried into the usage sidecar and import.
- Full gate, then the stack commit.

## Stack D — One Sonnet-observed GLM retest and parent evidence review

After all implementation gates and commits, the parent freezes a clean source
commit and a fresh driver hash, then gives ONE Sonnet subagent a self-contained
launch and logging assignment. Sonnet is the operator and observer; **GLM alone
plays**. Sonnet must not coach, insert moves, or edit the canonical prompt. No
tracked edits during the run or before final frozen-source reconciliation.
Old `tmp/glm-decision-exec/OBSERVER.md` and its helper scripts are examples, not
ready-to-run launchers: they embed prior run paths, readiness, and source
checks. Adapt only necessary ignored helpers into `tmp/glm-inspection-exec/`,
never rerun old launch or finish scripts against old evidence, and prefer
maintained commands.

Retained baseline settings, unchanged from the prior run: maintained streaming
Fireworks backend, `accounts/fireworks/models/glm-5p3-flash`, big_battle_6, seed
771125826, Northerners/Loyalists, 300 gold, side 0, focused/choices/incremental,
`--max-turns 50`, `--max-game-total-tokens 1000000`, `--max-output-tokens 131072`,
`--model-timeout 7200`, `--turn-timeout 14400`, other call/query/partial limits at
maintained defaults, 524288 escalation preserved with a stop after three
exhaustions at that ceiling, and provider-default reasoning and sampling. The
budget is checked between calls and may overshoot on the final one. Do not raise
limits, start another paid game, or resume after stopping. Verify current pricing
before launch and record the rates and date; the prior ~$0.36 is an estimate, not
a quote or guarantee.

Isolate a NEW archive, checkpoint directory, request journal and context, usage
sidecar, provider SSE and receipts, stdout and stderr, launch metadata, and
process exit. Never reuse the old run's IDs or filenames. Follow the
authoritative Usage accounting procedure in `docs/LLM_CLIENT.md`, including
explicitly UNKNOWN host usage where collection is unavailable, and keep
coding and operator usage separate from GLM API usage.

The observer logs:

- Full raw provider streams, final reasoning and content, exact canonical
  prompts and payload hashes, dispatch and final sidecars, and receipts. Never
  log credentials.
- An append-only observation log keyed by request ID and sequence, live
  revision, model side turn, and stage: objective, inspection, local action,
  preview, review, or repair. Intended actions are recorded separately from
  accepted engine results and explicit error indices.
- Four categories with exact evidence paths and concise excerpts or offsets:
  useful and expected reasoning; unsupported mistakes despite supplied facts;
  understandable friction; missing harness information or behavior. Read what
  was actually delivered to the model, not merely raw driver fields that may
  have been projected out.
- Whether purpose and next-phase facts survive, effective profiles are usable,
  inspections are requested promptly, local operations stay focused, whole-turn
  reviews have appropriate scope, review inspections stay bounded, and corrected
  preview provenance reaches the player. Each changed path is explicitly marked
  exercised or unexercised.
- Per physical call: input, output, reasoning, cached, cache-write, and total
  usage with explicit unknowns; requested and reported effort; output cap and
  retries; latency; prompt, fixed-prefix, local, and tool bytes; and request and
  turn attribution. Reasoning is included in output and cached input is included
  in input; do not add them again. Streamed characters are not token counts.
- First actual move, capture, attack, and kill with cumulative tokens;
  completed and open turns; accepted and rejected batches; casualties by source;
  final HP, material, gold, and villages; terminal class, code, exit, and
  winner. A pre-submit validation failure is not a live rollback, and a sampled
  result is not live state.

The observer notifies the parent after completed turns, material findings or
failures, and termination, and persists through slow calls and compaction. The
game can take roughly two hours; poll at intervals no longer than 45 seconds.
The parent performs read-only audits on copied checkpoints while it runs and
never intervenes live.

After termination and BEFORE any tracked edit, reconcile SQLite, receipts,
prompts, usage, request/action/review/turn links, integrity and foreign keys,
and idempotent reimport. Export the replay and import it into the normal
catalog so it appears in the menu. Hash-check protected historical evidence and
verify the frozen source and driver hash. A locally blocked logical request has
no paid receipt and is not missing provider usage. Deliver the per-call ledger,
metrics, coverage, replay, and a `HANDOFF.md` stating every limitation.

The parent then independently inspects the final catalog and selected raw calls,
cross-checks observer milestones and candidate roles — earlier observers made
exactly these attribution mistakes — probes suspected defects only on copied
checkpoints, and compares with the baseline under single-run and
unequal-trajectory caveats. The parent writes and commits the durable report at
`docs/experiments/glm-inspection-handoff.md`, marks this plan complete only
after the required work is done, and leaves a clean tree. New findings are
documented with reproduction and the smallest plausible follow-up, not silently
fixed, and no further implementation or game cycle begins without authorization.
