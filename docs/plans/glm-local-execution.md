# Reliable facts, inspection recovery, and local execution

Status: code stacks complete and cumulatively tested, 2026-09-11; observed retest pending.
Baseline: `90e35f7`.
Evidence: [last diagnostic](../experiments/glm-mechanics-context.md), game
`acf48862062d7233448b750b762b6216`. Inspect its catalog before original archives.

## Outcome and constraints

Fix the six remaining findings, including maintained documentation and callers.
Then observe one fresh GLM 5.3 Flash game through its terminal stop and report
reasoning, actions, spend, coverage, bugs, and further opportunities. Better
strength or fewer reasoning tokens is an experimental question, not a release gate.

Keep existing engine rules, action/tool schemas, parser execution strictness,
atomic rollback, annotations, agenda validation, automatic sweep policy,
simulation/live separation, query budgets, and 128k-to-512k output retry policy.
No extra model, planner service, action alias, hidden automatic action, new
database schema, compatibility wrapper, or paid experiment matrix. Rule IDs stay
stable. Historical evidence is immutable. Missing observations remain unknown.

## Execution and integration

Commit this plan before assigning implementation. Three Luna High workers work
in separate worktrees from that commit. They may read everything relevant, but
must only edit their owned areas and must not launch paid calls. Read AGENTS.md,
docs/DEVELOPMENT.md, and docs/LLM_CLIENT.md first. Workers own focused tests and
their documentation. Each produces a commit and an ignored handoff listing
changes, exact tests/results, risks, and touched shared functions.

Workers can implement stacks 1, 2, and 3 concurrently against the baseline.
The parent integrates in that order, resolves shared-file overlap explicitly,
runs `python3 -m tools.fast_check` after each complete stack, and commits that
stack only when its cumulative gate passes. This includes the supported Rust
library/binary/integration tests, Python suite, and Lua headless checks. Never run
unfiltered Cargo tournaments. Reuse passing checks unless changes justify a
repeat. No interactive GUI acceptance is claimed by the headless gate.

The parent owns final integration, source freeze, evidence preservation, the
single live run, and the report. A free worker may independently audit evidence
or integration while the parent does useful work. Logs and handoffs belong in
`tmp/glm-local-exec/`; durable plan/results belong in docs.

## Stack 1 — Accurate decision facts and explicit finishing (Luna A)

Own compact threat renderers, compact_trend, readiness construction/prompt field,
finishing examples and their tests/docs. Do not edit dispatch/repair/review logic
or the local-execution orchestration owned by the other workers.

1. Count villages from live StateSnapshot terrain village tiles and their owner,
   not the nonexistent village_owners field. Preserve bounded completed-turn
   history. Unknown/missing terrain is unknown, not fabricated zero.
2. Replace whole_army_sweep with current_turn_readiness everywhere maintained.
   Label moved_this_turn, attacked_this_turn, agenda_unassigned, and agenda_holds
   explicitly, with live revision/turn. Prior finish provenance stays separate.
3. Render lethal_attackers_needed consistently: a present null in an evaluated
   threat summary means supplied maximum volleys cannot reach HP; an absent or
   unavailable summary is unknown. Do not turn a scoped statement into safety.
   Label counts as minimum attackers under maximum hits. Expected HP, maximum HP,
   and kill probability remain distinct. Keep raw archive/engine fields intact.
4. Beside compact EXPOSURE, identify current-position and movement-inclusive
   scope for direct/open views; report evaluated/threatened/zero counts and
   missing coverage honestly. Do not dump omitted zero-threat rows or imply all
   friendly units were evaluated when the surface is partial.
5. Add one complete valid no-own-sweep example using FinishWithGreedy with empty
   groups and holds. State that it still ends the turn and permits the opponent
   response; executable holds apply to this finish only. Clarify existing facts:
   damage per successful strike is fixed after modifiers, not random damage dice;
   unit alignment/profile and inspected retaliation are authoritative. Reuse
   existing rule fixtures, and add engine fixtures only for any newly stated fact.

Acceptance: real-driver state/briefing/trend village counts agree at two boundaries
including neutral ownership; a new-turn readiness reset does not rewrite prior
finish history; renderer fixtures distinguish scoped nonlethal/null, missing,
positive lethal count, zero threat, and partial coverage. Real-driver empty-group
finish proves no own sweep and subsequent opponent action, with holds absent next
turn. Existing tactical values, raw payloads, schemas, and rule IDs are unchanged.
Update maintained tests and docs together. Full cumulative gate and commit.

## Stack 2 — Preserve inspection and surface sampled consequences (Luna B)

Own response parsing/repair classification, draft review predicates/rendering,
and related loop call sites/tests/docs. Coordinate helper call signatures with A;
do not modify A's numeric renderer implementation or C's prompt projection.

1. Reproduce R14's valid inspection JSON followed by unfenced rationale. Strict
   execution parsing must still reject it. For repair classification only, a
   narrowly decoded first complete recognized bare-tool object may identify the
   pending lookup. Never execute extracted prefixes or arbitrary brace snippets.
   Preserve the existing single bounded shape-repair path when live capabilities
   allow it; require a fully parsed corrected response before any tool dispatch.
   Keep final-only, exhausted budgets, and once-per-turn preview limits authoritative.
2. Derive a compact sampled transition from the existing valid draft preview:
   friendly movement during own finish and casualties during the sampled opponent
   response. Use the actual draft candidate and originating revision, not the
   baseline candidate or assumed array position. Missing stages remain unknown.
3. A valid sampled friendly casualty in the proposed finish triggers the existing
   bounded review even when exposure is unavailable. Show casualty IDs and relevant
   position changes as SIMULATION — NOT EXECUTED; do not silently veto a legal
   draft or make the simulated board live. Reuse the existing preview and review
   budget; no extra driver query solely to create this warning.

Acceptance: an offline real-client sequence malformed inspection -> corrected bare
inspection -> local facts -> legal action succeeds and records every request;
malformed actions, truncated JSON, unrecognized tools, final-only and exhausted
budgets retain their restrictions, with no prefix execution. A deterministic
real-driver sweep-casualty case with null exposure produces exactly one review;
confirmation commits once, replacement starts from original live state, missing
post-opponent data does not invent a death, and a casualty-free control does not
trigger this new predicate. Import review/request/turn links and reimport
idempotently. Full cumulative gate and commit.

## Stack 3 — A concrete local execution phase (Luna C)

Own focused prompt assembly and tool-followup/engine-repair context routing,
focused-flow tests and docs. Do not change tool/action schemas, numeric renderers,
generic syntax classification, or review predicates. Coordinate shared call sites.

1. After a successful inspection in focused mode, build the next request as a
   local execution view from structured current state and that inspection. This
   must change the volatile context selection, not merely append another slogan
   to the full global prompt. Keep the stable rules, geometry and type-profile
   prefix byte-identical for the same live revision and configuration.
2. Make the selected target/units/hex, revision, settled task/intent with provenance,
   exact inspected legal options, and one useful next operation central. Replace
   unrelated full tactical option rows and broad replanning history with compact
   guardrails: live side/phase, recruiter facts and danger, economy/villages,
   live army totals/IDs, and required pending promotion information. All globally
   available warnings must remain truthful; missing information is unknown.
3. Scope the execution context to the current revision. Carry it through format
   repair and engine-validation repair after rollback, including another allowed
   inspection. An accepted partial invalidates it and rebuilds objective selection
   from fresh state. A fresh inspection replaces the selected local task view;
   retain raw tool history in the archive without endlessly accumulating prompt
   copies. Reviews retain their dedicated authoritative simulation/live contract.
4. Do not enforce a new action subset or force an inspection when legal actions
   were supplied already. Existing action validation is authoritative. The model
   can request another permitted inspection or reconsider when facts invalidate
   the objective. Non-focused modes retain their existing flow.
5. Keep the final live reminder last, the final byte cap/telemetry inclusive of
   all context, game usage visible, and retries byte-identical. Use small explicit
   helpers/parameters; no generic workflow framework or marker-based arbitrary
   text extraction. Update instructions to explain the actual phase transition.

Acceptance: use small deterministic matched fixtures for a retreat with unequal
terrain costs, an Engage with retaliation, and hold-only finishing. Exercise
objective -> inspection -> execution -> accepted partial -> fresh objective plus
validation rollback and reinspection. Assert exact options, same revision,
guardrails, correct phase invalidation, stable prefix, prompt cap, and request/
usage linkage. On a fixture with unrelated army options, local dynamic bytes must
be fewer than the previous full-followup bytes while retaining all selected legal
options and mandatory guardrails. Track bytes and scripted operation completion;
offline fixtures cannot establish real model reasoning savings. Avoid brittle
exact whole-prompt snapshots and increasing existing caps just to pass tests.
Full cumulative gate and commit.

## Stack 4 — One observed GLM retest and evidence report (parent)

After all code stacks pass and commit, freeze source and build a fresh driver.
Hash the previous archive before/after; use a new isolated log, checkpoint folder,
request journal/context, provider evidence directory, usage sidecar, and launch
manifest. Use the maintained streaming Fireworks adapter, canonical prompts
unchanged, accounts/fireworks/models/glm-5p3-flash; same scenario big_battle_6,
seed 771125826, Northerners/Loyalists, 300 gold, side 0, focused/choices/incremental,
50 side-turn cap, 1,000,000 measured total-token ceiling. Keep provider-default
sampling/reasoning and existing 131072 -> 524288 output policy. No silent resume,
extra run, or live source mutation. The between-call cap may overshoot by the
final response. A setup-only local failure may be corrected before paid dispatch.

Observe streamed provider reasoning and completed actions. Record concrete request
IDs/revisions for: first movement/villages/attack/kill; inspection uptake and cost;
local execution versus repeated global planning; guessed routes and retaliation;
repair capabilities; sampled warning/review behavior; trend/readiness/threat
interpretation; game-budget adherence. Classify useful reasoning, unsupported
mistakes, understandable friction, and missing harness behavior separately.

After gameplay terminal, budget stop, or failure: reconcile direct-API receipts,
import the new game into its own SQLite and the normal replay catalog, export
replay, verify integrity/foreign keys/idempotent reimport and action/request/turn/
review links, and run the authoritative game/turn/call usage queries. Report
input, output, reasoning, cached/cache-write breakdown and unknowns;
aggregate_only_request_ids and unassigned_calls; source commit/driver hash;
termination/winner/open-turn status and replay location. Verify current official
pricing and distinguish estimated cost from invoice. Review raw reasoning as
provider evidence, not guaranteed faithful explanations.

Acceptance: one terminal archive, complete or explicitly unknown evidence for
every paid call, measured per-turn totals, request-specific findings, preserved
historical hashes, and a durable report in docs/experiments/glm-local-execution.md.
Newly discovered defects are documented with minimal follow-up tests, not silently
fixed during this frozen game. Mark plan complete and commit the report/handoff.

## Evidence limits that are not new feature requests

The prior game's game-level prompt hash and per-action accepted_unknown statuses
are evidence limitations, not permission to invent acceptance or migrate historical
data. Per-request canonical hashes and event links remain the proof. Invalid
decision order indices remain annotation validation failures separate from legal
actions; preserve raw annotations and existing diagnostics. Do not add schema
work to this iteration without a reproduced defect in maintained logging.
