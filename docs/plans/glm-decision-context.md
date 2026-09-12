# Complete decision context and accurate evaluation reporting

Status: complete, 2026-09-11.
Implementation commits: `b778f7e`, `a63ee0b`, `0bc1a8e`.
Cumulative gates: 714 / 720 / 729 Python tests plus Rust and Lua.
[Retest, accounting, and remaining findings](../experiments/glm-decision-context.md).
The single retest ended on its token budget; newly discovered follow-ups are
recorded in the report and were not silently changed during the frozen run.
Baseline: `c4ba434`.
Evidence: [local-execution diagnostic](../experiments/glm-local-execution.md),
game `6979fd492a285b394e9c0c052c39f1b9`. Read its catalog before raw archives.

## Outcome and limits

Fix every demonstrated harness issue in that report, then have a Luna High
subagent launch and observe one fresh GLM 5.3 Flash game. The parent reviews
its recorded evidence and reports remaining bugs and opportunities. A win or
reduced reasoning spend is an experimental outcome, not an implementation gate.

Keep this small: finish the existing objective/inspection/execution flow, do not
add another planner, model, mandatory tool call, action restriction, or generic
workflow framework. Preserve engine mechanics, action schemas, atomic rollback,
query/review/repair budgets, strict parsing, untrusted-data framing, live versus
simulation separation, and output-limit escalation (131072 -> 524288; three
exhaustions at 524288 stop). Do not lower reasoning or sampling settings in this
comparison. Do not silently raise prompt caps. Raw historical evidence is immutable.

Explicit nonbugs need clarification or regression coverage, not engine changes:
U5's rev218 ranged coverage was legal; stationary Engage preserves movement;
failed_index indexes authored top-level actions; review baseline/draft indices
correctly differ from explicit-preview indices. Provider cache misses despite
an identical prefix do not establish a prefix defect. Do not promise that prompt
changes will eliminate model arithmetic errors or indecision.

## Work split and integration

Commit this plan before delegation. Use three Luna High workers, each in an
isolated worktree created from that plan commit. Read AGENTS.md,
docs/DEVELOPMENT.md, and docs/LLM_CLIENT.md. The following stacks may be built
in parallel; integrate A, then B, then C. Workers run focused meaningful tests,
commit their work, and write ignored handoffs under tmp/glm-decision-exec/.
The parent resolves overlaps, runs `python3 -m tools.fast_check` after each
integrated stack, and commits only after its cumulative gate passes. Never run
unfiltered cargo tests/balance tournaments. No interactive GUI acceptance is claimed.

Shared-file ownership is by function, not permission to overwrite another worker:
A owns contract/preview/review/continuity construction and playbook; B owns
inspection renderers and local-context selection/projection; C owns history and
terminal classification only. Parent integrates shared llm_client.py/docs edits.
Workers may propose a small helper, but avoid extraction/refactoring unrelated
code. Keep maintained callers, tests, and documentation aligned; no wrappers for
superseded development interfaces. Tests must not depend on ignored archives.

## Stack A — One coherent proposal across preview, review, and repair

Owner Luna A. Own compact_batch_preview, sampled-transition rendering,
review/repair prompt construction, committed continuity, canonical contract and
playbook wording. Coordinate helper interfaces with B; do not edit B's local
projection or C's terminal taxonomy.

1. Preserve validated draft intent and decision annotations next to the draft
   action list in a bounded, explicitly untrusted rationale block. Include an
   absent marker when unavailable. Carry the correct draft through automatic
   review and engine repair; never publish a rejected draft as committed memory.
   Reuse current validated response metadata; do not retain raw hidden reasoning.
2. Fix preview instructions/examples/errors to allow the same three finishers
   as validation. Explain full versus selective sweep; candidates still need a
   complete finish. Stationary Engage uses no Move; after an accepted batch is
   the observation boundary, not between its primitive actions. failed_index is
   the authored top-level action index; nested failures retain step information.
3. Label sampled friendly movement/casualties with side, originating revision,
   candidate, and own-finish/opponent-response interval. Replace misleading
   rendered labels everywhere maintained. Preserve unknown coverage and raw data.
4. Show a bounded per-candidate friendly casualty/movement summary in explicit
   preview follow-ups using the existing sampled result (no additional query).
   Use the same semantics as automatic review; retain candidate action identity
   and baseline/draft roles. Do not eliminate the review or claim duplicate
   engine work without proof. Do not dump all hypothetical rosters into previews.
5. Separate controlled-action and opponent-response casualties in continuity.
   Preserve all real history and explicit sources; unknown sources remain unknown.
   Do not attach following enemy-inflicted losses to an authored batch unqualified.
6. Tighten existing tactical prose: a detected mistake/stale assumption permits
   correction; useful holds need a purpose/revisit condition, not permanent
   garrisons; survival can precede healing; arithmetic/profiles and movement costs
   come from facts, not another game's rules. Clarify MoveGroupToward reduces
   distance, not guarantees castle evacuation. Distinguish advice from schema
   requirements. Replace conflicting lines instead of adding another long guide.

Acceptance: real-client mocked response sequences prove rationale survives review
and repair, replacement controls committed memory, and the final live reminder
remains last. Test three preview finishers plus missing-finisher rejection;
two different sampled candidates retain correct IDs/casualties and no extra
query; both sides and missing stages stay correct. Real-driver stationary
Engage->Move and macro-before-failed-action fixtures prove movement and indexing.
Continuity fixtures distinguish llm/delegated_greedy/greedy/unknown sources.
Prompt/repair budgets and byte caps remain enforced. Full gate and stack commit.

## Stack B — Self-contained, bounded local decisions

Owner Luna B. Own inspection enrichment/rendering and local context helpers,
focused prompt projection/lifecycle, related fixtures/callers/docs. No new tools.

1. Derive relevant entity IDs structurally from the selected inspection, its
   referenced attacks/threats, and matching assigned support units. Include
   compact current rows at the same live revision: ID, side, type, position,
   HP/max HP, moved/attacked, poison/slow, promotion state/choices, and weapons
   or an exact shared profile reference. Missing rows/fields stay unknown.
   Include named village coordinates/ownership relevant to selected origins,
   destinations, or assigned objective; use structured IDs/coordinates, not
   arbitrary parsing of free-text intent. A small complete village list is fine.
2. Make the selected inspection operation central and distinguish it from a
   provisional global agenda. Prefer a matching assigned task over an unrelated
   first active task; if none matches, say so. Preserve stated intent/provenance
   without presenting it as authoritative. Keep recruiter safety, economy,
   readiness, and pending promotion guardrails.
3. Reduce repeated inspection facts without dropping legal options or forecasts:
   factor repeated unit/profile/terrain facts into exact referenced rows; render
   numeric exchanges/threats compactly once per distinct item where lossless.
   Do not introduce ranked/truncated top-k recommendations or hide destinations.
   Raw driver results stay unchanged in archives. Preserve choice-handle identity.
4. Give the model a concrete instruction to inspect one target for an attack or
   the specific unit for an uncertain retreat; use the resulting local view for
   the selected operation. Do not make inspection mandatory when facts suffice.
   Keep accepted partial invalidation, rollback, unavailable-result clearing,
   fresh reinspection replacement, previews/repairs, and final-only behavior.
5. Add deterministic recorded-position fixtures for a wounded target with status,
   supported retreat with unequal movement costs, a held unit's reassignment,
   and a multi-attacker kill/retreat. Extract minimal reusable fixture data from
   archive evidence if needed; no tests depend on tmp/ paths.

Acceptance: exact referenced live facts and all legal choices survive objective
-> inspection -> local action -> refreshed objective; stale states never leak
through repair/reinspection. Matched local prompts are smaller than full followups
with the same result. On a representative multi-origin inspection, repeated-fact
factoring demonstrably reduces tool-result bytes while preserving option counts,
forecast values, and legal operation results. Fixed prefix stays byte-identical
for the same state/config; current maintained caps still pass. Report bytes and
scripted task success separately from unmeasured LLM reasoning savings. Full gate
and stack commit. If an existing scripted caller assumed a removed field, update
its maintained behavior without weakening its objective or budget.

## Stack C — Honest terminal, turn, and review summaries

Owner Luna C. Own game_history and its maintained consumers/tests/docs; only the
terminal taxonomy/budget-stop paths in llm_client.py. Coordinate those edits with A.

1. Give budget interruption its own explicit non-gameplay, non-model-fault
   classification, including a distinct documented exit code (3). Update launch,
   resume/supervisor, bakeoff/report/replay consumers that enumerate outcomes.
   Preserve no-winner semantics and existing no-automatic-resume behavior. Interpret
   historical explicit budget reason/code correctly without rewriting archives;
   do not relabel actual invalid actions or unknown infrastructure failures.
2. Usage-by-turn must include known open/completed side-turn rows with zero calls.
   Empty groups have call_count=0 and empty IDs; do not invent measured usage or
   turn attribution. Totals and denominator conventions remain explicit.
3. Reproduce why R14/R19 raw linked reviews are absent from normalized coverage.
   Normalize every supported review by explicit request/review/side-turn identity
   rather than replacing one review with another batch at a similar position.
   Where evidence is genuinely unsupported, expose the reason next to the raw ID.
   Use existing JSON storage unless a demonstrated constraint requires otherwise;
   no speculative database migration. Preserve historical raw review identities.

Acceptance: import an offline game with a repaired rejection then a local budget
block: correct distinct stop, no fabricated paid call/winner, ninth open empty
turn visible. True unrepaired rejection remains model_invalid; infrastructure
and gameplay remain distinct. Reproduce confirmed/revised reviews across partial
and finished batches, prove every supported raw ID appears in normalized coverage
or has an explicit unresolved reason, and reimport idempotently. Integrity/FKs,
request/action/review/turn links and cost/usage reports pass. Full gate and commit.

## Stack D — Luna-observed GLM game and parent evidence review

After all code commits/gates, parent freezes source and writes launch/handoff
instructions; then a Luna High subagent owns ONE direct-API game and observation.
The subagent is an operator/observer, not the game player; GLM alone receives the
unchanged client-generated prompts and produces game actions. Read the authoritative
Usage accounting section of docs/LLM_CLIENT.md. No intervention/coaching injected
into the game and no paid retries outside the maintained policy.

Use the maintained streaming Fireworks backend, model
accounts/fireworks/models/glm-5p3-flash, big_battle_6, seed 771125826,
Northerners/Loyalists, 300 gold, side 0, focused/choices/incremental,
--max-turns 50, --max-game-total-tokens 1000000, --max-output-tokens 131072,
--model-timeout 7200, --turn-timeout 14400. Same provider-default sampling/reasoning
as the prior run. Query/model/partial limits remain defaults. The game ceiling
is checked between calls and can overshoot by its final call. No second game,
silent resume, or source edit during the frozen run. Setup-only correction is
allowed before any paid dispatch. Reverify official model pricing before launch.

Allocate a unique archive, checkpoint directory, request journal/context, usage
sidecar, and provider evidence directory. Record source commit/clean status,
fresh driver build/hash, exact commands/settings, timestamps, PID, and process
exit. Hash the prior game's original evidence before and after. Never print keys.

The observer must deliver these files under tmp/glm-decision-exec/ or the archive:

- An append-only observations log keyed by request ID/sequence, live revision,
  side turn, stage (objective/inspection/local/preview/review/repair), tool or
  authored action, accepted/rejected outcome, and evidence paths. Sample streamed
  reasoning periodically; preserve all raw SSE, final reasoning and content.
- A per-call ledger with provider/model IDs, requested output cap, elapsed time,
  prompt/fixed-prefix/tool/local bytes, input/output/reasoning/cached/cache-write/
  total usage and explicit unknowns. Do not infer tokens from characters or
  trust model-reported usage. Link each physical attempt to its logical request.
- Concrete examples in four categories: useful/expected reasoning; unsupported
  mistakes despite supplied facts; understandable friction; missing harness
  behavior. Record enough request-linked excerpts and action evidence to let
  the parent verify, not just a narrative verdict. Watch task focus, exact target
  facts, rationale continuity, preview finish choice, sampled/live interpretation,
  repeated geometry, inspection uptake, holds, route errors and repair capability.
- Milestones: first authored move, village capture, attack and kill, cumulative
  tokens at each; ended/open turns; kills/losses/HP/material/villages; terminal
  reason/class/code/winner. Distinguish simulation outcomes from real events.
- Reconciled SQLite catalog, game/turn/call/request usage exports, replay bundle,
  integrity/FKs/idempotence and request/action/review/turn linkage results. Import
  into the normal replay catalog too. Reconcile dispatch/final sidecars and exact
  canonical prompts/payload hashes with every paid receipt; locally blocked
  requests are not missing paid calls. Report aggregate_only_request_ids and
  unassigned_calls, all unknown fields, and measured versus estimated cost.
- HANDOFF.md with exact archive/game ID, stop state, final usage/cost, evidence
  coverage, strongest findings, and any incomplete verification. Update parent
  at each completed turn or material failure and immediately when stopped.

Parent independently inspects the final catalog and selected raw calls, probes
suspected engine defects only on copied checkpoints, and compares to the previous
run with single-run/unequal-trajectory caveats. Do useful independent audit while
the observer runs; do not launch another model game. Finish a durable report at
docs/experiments/glm-decision-context.md, mark this plan complete, and commit the
report. New findings are documented with minimal reproduction/tests, not silently
fixed during the game. Final response includes code gates, outcome, replay,
measured usage/coverage, cost estimate, and remaining actionable findings.
