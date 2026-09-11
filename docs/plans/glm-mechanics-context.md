# Correct mechanics, readable decisions, and an observed GLM retest

Status: planned, before implementation. Baseline: `90fb2a8`.
Evidence: [previous diagnostic](../experiments/glm-followup-corrections.md),
game `ee269ac3ee0a761f8dcd433feb9476e6`, and the source audits in
`tmp/glm-followup-exec/`. This is the next iteration, not a rerun of completed work.

## Outcome and scope

Fix every confirmed issue from that diagnostic; make the existing focused flow
useful at two levels (choose a small objective, inspect/execute its exact local
options); run one fresh Fireworks GLM 5.3 Flash game and observe it to termination.
Do not promise that mechanical correctness or shorter prompts improve strength.

Keep the runtime avoidance convention, existing engine actions/inspection tools,
agenda shape, model/provider defaults, streaming and output-limit policy. No
second LLM, planner service, new strategy DSL, automatic tactical ranking,
unlimited history, speculative engine action, or paid experiment matrix. Preserve
historical raw logs, checkpoints and catalogs. Unknown evidence stays unknown.
Update maintained callers/tests/docs together; no compatibility aliases for
superseded development-only prompt labels. Raw numeric engine/archive fields
remain unchanged when only their readable presentation changes.

## Execution and ownership

Commit this plan before starting Luna High workers. Use three isolated worktrees
from the plan commit, so parallel edits cannot overwrite each other. Each worker
reads AGENTS.md, DEVELOPMENT.md and LLM_CLIENT.md. History work also reads
AGENT_GUIDE.md and GAME_HISTORY.md, catalog first. Workers do focused tests,
commit coherent local stacks and hand off exact commands/results; no paid calls,
main merges or changes in another worker's tree. Parent integrates in stack order,
reviews shared-file conflicts, runs `python3 -m tools.fast_check` cumulatively,
fixes failures with workers and commits each passing stack separately.

- Luna A owns stack 1: importer/data/engine recruitment and their tests/docs.
- Luna B owns stacks 2 and 3: readable prompt/tool output, local focus/memory and
  budget context. Deliver separate commits so each cumulative milestone is testable.
- Luna C owns stack 4: history/request provenance, review origin, source hash and
  coverage. Coordinate edits to llm_client.py with B; parent handles integration.
- Parent owns source/evidence preservation, cumulative gates and stack 5.

The full gate is Python, Rust library/binaries/named integration suites and Lua.
Never run unfiltered cargo test tournaments. Paid calls are not implementation
tests. Keep logs/handoffs under `tmp/glm-mechanics-exec/`; maintain a tracked
execution report at `docs/experiments/glm-mechanics-context.md`. Do not weaken
assertions to make changed behavior pass; explain and verify changed expectations.

## Stack 1 — Imported defense and executable recruitment agree with the engine

End-to-end result: correct source stats flow through data loading into actual
combat, forecasts and legal recruiting on one or several keeps.

1. Define stored unit `defense` and terrain `default_defense` consistently as
   avoidance percentages. Convert Wesnoth hit chance to avoidance at import,
   including unit overrides and default terrain tables. Align verify_stats and
   maintained schema/developer/player docs. Correct affected generated data only;
   do not accidentally rescrape unrelated attacks, IDs, assets or advancement trees.
2. Audit negative WML defense values (mixed-terrain cap metadata). For Norrust's
   indivisible terrain IDs, explicitly document/test the supported magnitude
   conversion. Do not claim mixed-terrain cap support or silently introduce it.
   Reject unsupported shapes rather than invent stats. No migration framework.
3. Cross-layer fixture uses known orcishfoot raw flat60/forest50/castle40/swamp70:
   stored avoidance40/50/60/30, runtime hit chance60/50/40/70 percent. Verify
   immediate combat parameters, tactical forecast and AI share the meaning;
   use deterministic fixtures rather than a noisy statistical tournament.
4. Share eligible recruiter selection and adjacent free-castle placement between
   manual Recruit and the advertised tactical surface. Retain deterministic
   first-eligible-keep selection (no new recruiter action field), including both
   `can_recruit` and the existing leader ability. A macro may repeat recruiting
   after vacancies change, but must not advertise another keep's illegal slots.

Acceptance: importer fixture plus real-driver forecast/combat checks distinguish
flat from castle/swamp; all affected positive data values audit against the new
contract; two keeps, leader-only recruiting, no eligible keep, occupied castles,
vacate/recruit-again and single-recruiter cases have matching advertised/executed
results. Full cumulative gate passes. Existing historical evidence hashes remain
unchanged. Commit: `fix(engine): align imported defense and recruit placement`.

## Stack 2 — Readable exact rules and consistently scaled tactical facts

End-to-end result: canonical prompts and every inspection/preview/review surface
describe the same real-driver mechanics, without mental unit conversion.

1. State one independent Move and one Attack per unit per side turn. A Move uses
   one complete terrain-cost route; unused points do not permit a second Move.
   Move→Attack and Attack→Move may be legal; Move→Attack→Move is not. Document
   odd-r `(col,row)`, authoritative legal origins, adjacent-castle recruitment,
   no six-recruit cap, and the six-slot phase cycle from engine facts.
2. Render probabilities as exact readable percentages and expected/max damage
   as HP, with distinct names for exchange outcomes and kill-by-1/2/3 attackers.
   Preserve the raw integer engine/SQLite fields and unknown values. Use one
   small formatter across cards, inspection, preview, rescue and draft review;
   do not leave an old tenths/basis-points legend on a new display or duplicate
   both display formats. Distinguish attacker retaliation from defender damage.
3. Replace ambiguous own-economy `E`, move-origin counts and attack `-` with
   descriptive labels/reasons. Keep readiness separate from actual attack
   coverage, using live flags rather than deriving spent status from no targets.
4. Label direct and open as movement-inclusive, at the imminent opponent phase
   and current revision. Open removes other-unit blockers/ZOC, retains terrain,
   and is a bound, not a joint plan. Explicit zero scope must not imply safety
   after other moves or against more attackers than the forecast covers. Keep
   missing projected units distinct from explicit zeros.
5. Describe inspect_units as exact legal destinations, attacks from each and
   destination danger; inspect_target supplies origins against that target.
   MoveGroupToward performs one ordinary move per ID, can target an occupied
   rally point and land there if legal/free, and does not certify safety or end
   the turn. Target death skips later steps inside the same Engage; a separate
   Engage requires its initial target to exist. Use precise type/weapon facts
   near selected combat options so Bowman melee is not lost in a global list.

Acceptance: synthetic and real-driver fixtures render 144HP as144HP, 705bps as
7.05%, expected24 tenths as2.4HP, and distinguish exchange/volley meanings;
unknown stays unknown. Both encodings/modes, tools, review and repairs use the
same units. Fixtures prove one-Move legality, moved/attacked versus no-target
reasons, phase/scope, target-death semantics, and known enemy melee profiles.
Update maintained docs and prompt-cache fixtures without weakening the historical
prefix ratchet. If descriptive labels exceed a presentation-only old size ceiling,
first remove duplicated profiles/rosters; document any unavoidable measured
increase, with a cap no more than 15% above the prior largest fixture. The runtime
prompt-byte safety limit stays unchanged. Full gate and separate commit:
`fix(harness): present exact rules and readable tactical quantities`.

## Stack 3 — Bounded local execution, provisional memory and visible budget

End-to-end result: the same focused client distinguishes objective selection from
execution using existing tools, and never promotes old model prose into authority.

1. Treat intent/agenda goals as provisional model-authored rationale, not rules,
   promised outcomes or permanent garrisons. Preserve accepted memory but label
   its proven origin turn/revision and current/stale/unknown context. Changed
   HP, enemies, phase, vacancies or feasible trades can justify immediate change.
   Old `no duels`/`hold` text must not forbid a useful current action. Add origin
   metadata internally on commit and preserve/recover it through resume; do not
   add required model-written fields or infer old origins without proof.
2. Improve existing focused mode, without another command/mode: upper-level
   context retains global board/economy/recruiter dangers and asks for one small
   next objective. For uncertain execution, existing inspection of one target
   or preferably at most four relevant units selects a local task. Existing
   tool maxima remain valid; the four-unit preference is not a new rejection rule.
   At the follow-up, prominently label the inspected selection/revision and its
   exact local facts, then ask for that useful operation or one necessary lookup.
   Reuse received engine results; no automatic extra query/model planning call,
   arbitrary first-N tactical selection, hidden targets or action restriction.
3. Keep a local selection valid only for its live revision. After an accepted
   partial, observe actual results before another operation. Rejected batches
   retain the same live revision and committed memory. Repair the reported
   failure; do not require a fresh whole-army plan. Final-only/budget exhaustion
   still forbids tools and partial-only output. Show relevant weapon/type/HP and
   available/spent facts beside the inspected options, not speculative safety.
4. Append measured game budget context in the volatile suffix on every actual
   dispatch: configured ceiling or unbounded, known measured spend, remaining
   allowance and coverage. Unknown usage makes the remaining allowance a bound,
   not a precise claim. Use the existing sidecar measurement/accounting helper;
   no invented per-call token predictor, automatic limit reduction or new cost
   budget. Keep identical-prompt output-exhaustion retries byte-identical.

Acceptance: a scripted real-driver sequence selects a target/unit inspection,
gets a revision-pinned local execution context with weapons/legal choices, acts,
and returns to the next live revision without stale local facts. No extra calls
or queries beyond the script. Both failed and successful partials preserve correct
memory origin, resume reconstructs it, and a new turn labels prior memory as
prior rather than an active-turn order. Test known, partially unknown, unbounded
and exhausted budgets plus identical retry prompts. One final live-state/footer
contract remains last. KISS/cache/size gates from stack2 hold. Full gate and commit:
`feat(harness): focus local execution with provisional memory and token budgets`.

## Stack 4 — Proven action/turn links and complete review provenance

End-to-end result: recorded requests, authored actions and all actual automatic
reviews remain attributable in SQLite and exported coverage.

1. Populate batch/action side_turn_id from an existing validated request link
   when direct identity is absent. Reject foreign/conflicting explicit identity;
   no nearest-revision fallback. Apply to normal imports and idempotent backfill.
   Update maintained emission if needed so new records carry proven identity.
2. Preserve the exact query envelope revision in preview results and draft-review
   rendering; never label the known origin unknown. Retain missing danger_after
   when the executor genuinely does not supply it. No simulation-to-live leakage.
3. Retain all four draft reviews and decisions by stable review/request identity,
   including revised drafts and open-turn reviews. Reuse existing metrics/JSON
   columns if sufficient; do not add a duplicate review framework. Export explicit
   raw/imported/linked/missing coverage instead of treating the two old handoff
   shapes as all reviews. Do not fabricate a review for a locally blocked call.
4. Record the resolved driver's hash for fresh launches and import it as game
   provenance. For historical launch sidecars, only recover after matching source/
   archive identity; conflicts remain explicit. Keep changing prompt hashes at
   request granularity, not a fictitious single game prompt hash.

Acceptance: offline two-turn incremental run with partials, revised review,
unchanged review, open-turn stop and a locally blocked call imports with all
provable direct action/batch/request/turn links and distinct review identities.
Conflict/missing-evidence fixtures remain unlinked. Reimport twice is identical;
foreign keys, event provenance and usage totals unchanged. Scratch historical
import of the last game's original canonical path recovers68 action and19 batch
turn links, four archived reviews and27 measured calls/1036415 total tokens,
without modifying original catalogs/logs. Preserve all originals' hashes.
Full cumulative gate and commit: `fix(history): retain action and review provenance`.

## Stack 5 — Combined acceptance and one observed paid game

After all code stacks are reviewed, fully tested and committed, write the actual
implementation handoff before launch. Freeze the clean source/driver/data for
the entire game. User authorization covers this one retest; no additional launch
permission or unrequested matrix. Use LLM_CLIENT.md direct API accounting and
the maintained Fireworks streaming adapter, unchanged canonical prompt transport.

Match the previous configuration: GLM5.3Flash, big_battle_6, seed771125826,
Northerners/Loyalists,300 gold, side0, focused/choices/incremental,50-side-turn
cap,1M measured tokens,128k→512k existing output policy, provider-default sampling
and reasoning. Preserve model/driver/source identity, exact prompts/chunks/receipts,
checkpoint, usage sidecar, request journal and session context in a fresh isolated
archive. Terrain corrections change gameplay: mark pre-fix comparisons as
different rules/data, never a controlled estimate of prompt-only improvement.

Watch openings, first combat, every repair/review and termination. Separate useful
reasoning, unsupported claims, understandable ambiguity and missing controls.
Check each old signature explicitly (exercised, fixture-only or unresolved),
including terrain assumptions, one-Move errors, scaling, inspection use, broad
replanning, rigid intent, review origin and turn attribution. Track tokens to first
capture/kill and completed turns, actual moves/kills/losses, decision latency,
cache coverage and any paid failure. Stop at game end, cap or terminal failure;
never blindly retry an uncertain request. New findings go in the report, with
reproductions and next steps; do not alter live source or launch a second game.

Import/reimport and validate catalog before archive analysis, normal replay menu,
event/action/request/review links, per-game AND per-turn aggregate_only_request_ids
and unassigned_calls, all known usage and unknown fields. Reconcile physical
receipts, reverify official rates, report estimated cost (not invoice), final
winner or stopping cause, source/driver hashes and evidence coverage. Distinguish
raw provider reasoning from annotations. Verify historical hashes unchanged.
Commit final execution report/plan status; link the completed handoff and replay.
