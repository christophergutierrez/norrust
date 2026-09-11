# Reliable inspection and local execution: execution record

Status: complete, 2026-09-11. All three implementation stacks committed and tested; one observed retest reconciled and imported.
Plan: [glm-local-execution](../plans/glm-local-execution.md), committed as
`21c30a0` before three Luna High workers began in isolated worktrees.
Baseline source: `90e35f7`; prior game `acf48862062d7233448b750b762b6216`.

## Implementation and validation

Stack 1 (`7ea0967`) corrects terrain-owner village trends, current-turn readiness,
nullable threat semantics, direct/open exposure scope and coverage, and explicit
selective finishing. The cumulative gate passed 687 Python tests plus the
supported Rust library/binary/integration and Lua checks. A stale test assertion
was corrected to distinguish a supplied nonlethal bound from missing data.
Real-driver tests cover village totals at two boundaries and a held unit moving
on the next turn. Maintained schemas and engine mechanics are unchanged.

Stack 2 (`a598c83`) preserves recognized inspection requests through bounded
syntax repair without executing a JSON prefix, and surfaces a sampled friendly
casualty through the existing review. Its cumulative gate passed 699 Python
tests plus the supported Rust/Lua checks. The real revision-338 fixture has
`exposure=None`, sampled casualty U19, no other audit trigger, and exactly one
review. Confirmation and replacement both commit once from the original live
revision; catalog review links and idempotent import are checked. Repeated
malformed tool output stops without dispatch, and existing final-only and
budget restrictions remain authoritative.

Stack 3 replaces the focused post-inspection dynamic context with selected exact
options, task provenance, current readiness, and compact global guardrails.
Fresh inspection replaces local context; unavailable results clear it; rollback
retains live revision; accepted progress restores objective selection. Preview
and repair results remain visible, and local data retains untrusted framing.
The stable prefix, final live reminder, token accounting, byte cap, and output
retry behavior remain intact. Omitting agenda retains unshown tasks; supplying
it still replaces the full object. The initial cumulative gate exposed an outdated scripted test player: after
inspection it relied on removed global briefing rows and either re-recruited or
re-inspected indefinitely. Its maintained caller now consumes local options, with the existing matrix
objectives and budgets preserved. A stale canonical wording assertion was also
corrected. The final cumulative gate passed 708 Python tests, the supported
Rust library/binary/integration suites, Lua bridge/replay/catalog tests, and
`git diff --check`. All 24 offline matrix cells completed/imported/reported.
No interactive GUI acceptance is claimed.

Independent Luna audits and parent integration caught and corrected fenced-tool
repair regression, stale unavailable-inspection context, discarded preview
results, duplicate or incorrectly scaled guardrails, and dropped readiness.
Audit files and worker handoffs are under `tmp/glm-local-exec/`.

The real-driver byte comparison measures 44,038 bytes for local execution versus
48,424 for the full-context followup with the same inspection byte length and one
budget/live footer: 4,386 fewer bytes (9.06%). This is a structural comparison,
not measured token savings or model reasoning improvement. The largest maintained
small fixture is 18,493 bytes, below the unchanged 18,500-byte ceiling; the playbook
ceiling is unchanged. Evidence: `local-prompt-size-comparison.json` and
`final-prompt-sizes.json` in the execution directory.

## Retest protocol

One fresh maintained streaming Fireworks run, model
`accounts/fireworks/models/glm-5p3-flash`, scenario big_battle_6, seed 771125826,
Northerners/Loyalists, 300 gold, side 0, focused/choices/incremental, 50 side-turn
cap, and 1,000,000 measured total tokens. Provider-default sampling/reasoning and
128k-to-512k output exhaustion policy are unchanged. The between-call game
ceiling may overshoot by the last in-flight response. No automatic extra run.

Freeze source after all code gates and commits. Preserve isolated logs,
checkpoints, journal, sidecar, canonical prompts/payloads and raw SSE receipts.
Baseline hashes cover 710 historical files. Observe reasoning and actions, then
reconcile the terminal archive with SQLite, export replay, and import the normal
replay catalog. Missing evidence remains unknown. The terminal usage, outcome, coverage, and request-specific findings are recorded below.

## Retest result

The single authorized run ended at the measured-token ceiling on 2026-09-11,
not at a gameplay victory or defeat. Eight model turns completed; turn 9 opened
at revision 360 but its request was blocked before provider dispatch. There was
no winner. GLM was substantially behind: 16 units / 438 of 615 HP / 223 material
versus Greedy's 21 units / 668 of 700 HP / 311 material. Villages were 2–3, gold
9–8, with one neutral village. GLM killed three Bowmen and lost ten units.

The code fixes made it through the live run, but this is not evidence of good
play. There was one unreachable retreat, successfully repaired, and no malformed
response, failed provider call, or output-limit retry. Most delay was within
successful calls: repeated geometry, whole-army planning, and re-deriving choices
between preview, review, and execution. Useful casualty review and combat checks
were mixed with unsupported assumptions and excessive holding.

| Evidence | Value |
|---|---|
| Game ID | `6979fd492a285b394e9c0c052c39f1b9` |
| Source commit | `dea48d44cfab60b9cf0ed55f9616003f8ae9c619` |
| Driver SHA-256 | `089226cce2d5601463bbfe5767713a107ca9f5d14c2f8a59f913a7edb8082153` |
| Archive | `tmp/quick-play-glm-local-d_lz1jof/` |
| Replay | `tmp/quick-play-glm-local-d_lz1jof/replay.json` (25 saved frames) |
| Catalogs | Archive `history.sqlite` and normal `.norrust_history/history.sqlite` |
| Time | 19:10:41–21:09:24 UTC, approximately 118.71 minutes |
| Stop | `budget_interrupted / max_game_total_tokens_exhausted`, process exit 2 |
| Paid calls / logical requests | 24 / 25 |

The normal catalog import makes the game available to the maintained replay
flow; no interactive menu/GUI acceptance was performed. Exact settings are in
`launch.json`. Source and driver were frozen for the entire paid run. All 710
previously hashed historical files remained byte-identical.

## Usage and cost

| Provider-reported field | Tokens |
|---|---:|
| Input, including cached input | 420,090 |
| Cached input, subset of input | 153,600 |
| Cache-write input | Unknown on all 24 calls |
| Output, including reasoning | 615,783 |
| Reasoning, subset of output | 601,836 |
| Total input + output | 1,035,873 |

`aggregate_only_request_ids=[]`; `unassigned_calls=0`. Input, cached input,
output, reasoning, and total are measured for every paid call. Reasoning accounts
for 97.74% of output; it is not added again to the total or cost. Reported cached
input is 36.56% of input. Median response time was 209.93 seconds, maximum 950.31
seconds (R20). The final in-flight R24 was allowed at 996,387 tokens; its 39,486
tokens caused the documented between-call overshoot. R25 was blocked locally.

Estimated API cost is **$0.352473**, not an invoice. At the official rates checked
on 2026-09-11, uncached input is $0.15/M, cached input $0.03/M, and output $0.50/M:
`266490 * .15/M + 153600 * .03/M + 615783 * .50/M`.
[Fireworks GLM 5.3 Flash model pricing](https://fireworks.ai/models/fireworks/glm-5p3-flash).
The dated rate evidence is `tmp/glm-local-exec/pricing.json`.

| Completed model turn | Calls | Input | Output | Reasoning subset | Cached input subset | Total |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 6 | 68,873 | 92,085 | 88,742 | 20,480 | 160,958 |
| 2 | 2 | 27,240 | 27,771 | 26,936 | 10,240 | 55,011 |
| 3 | 2 | 32,167 | 9,219 | 8,284 | 18,432 | 41,386 |
| 4 | 4 | 96,909 | 63,069 | 61,805 | 26,624 | 159,978 |
| 5 | 2 | 38,413 | 93,583 | 92,267 | 20,480 | 131,996 |
| 6 | 3 | 54,602 | 127,094 | 124,784 | 14,336 | 181,696 |
| 7 | 3 | 63,545 | 134,353 | 132,214 | 38,912 | 197,898 |
| 8 | 2 | 38,341 | 68,609 | 66,804 | 4,096 | 106,950 |

Turn 9 is open in the catalog with zero physical calls. The usage-by-turn query
omits that empty turn; the side-turn table retains it. This is not missing spend.
Game/turn/call/request usage exports are in the archive. SQLite integrity and
foreign keys passed; reimport produced an identical logical SQL dump. All 91
actions and 16 accepted action batches link to requests and side turns. There
are 413 stored events, 25 snapshots, and no dangling event/call links.

All 24 dispatch/final sidecar pairs match catalog calls and provider evidence;
canonical prompt bytes match archived request, payload, context hash, and prompt
hash file. The generic coverage audit flags R25's missing provider/sidecar
records: its explicit local budget error explains both, so this is not an
unobserved paid call. Cache-write usage remains unknown. Raw provider streams,
reasoning, prompts, and receipts are retained; reasoning is diagnostic evidence,
not a guaranteed faithful explanation of decisions. Temporary live catalogs were
stale during observation; final analysis uses the reconciled terminal catalog.

## Comparison with the previous diagnostic

Both runs used the same model, scenario, seed, factions, gold, mode, and nominal
one-million-token ceiling. Their trajectories differ, so this is a one-run
comparison, not a causal strength or efficiency benchmark.

| Measure | Previous mechanics-context run | This local-execution run |
|---|---:|---:|
| Completed model turns | 4; fifth partly played | 8; ninth unplayed |
| Physical calls | 28 | 24 |
| Total tokens | 1,026,917 | 1,035,873 |
| Reasoning tokens | 580,798 | 601,836 |
| Estimated cost | $0.333163 | $0.352473 |
| First-turn calls / tokens | 4 / 106,630 | 6 / 160,958 |
| First authored movement, cumulative tokens | R2 / 48,757 | R2 / 51,837 |
| First enemy kill, cumulative tokens | R19 / 679,448 | R19 / 731,025 |
| Enemy units killed / friendly units lost | 2 / 1 | 3 / 10 |
| Unreachable-route rejections | 4 | 1 |

The first actual attack in this run occurred in the accepted R16 turn-5 batch,
at 549,329 cumulative tokens. Three villages were captured at the end of turn 1.
Village capture is an end-turn event even when the earlier movement was authored
by the model. The prior run stopped before the opponent answered its fifth turn;
final losses and board totals are therefore not matched-position comparisons.
The observed opening got more expensive; the larger completed-turn count partly
reflects passive turns, not faster accomplishment of the same tactical objectives.

## Request-specific findings and follow-up acceptance

Request IDs below have prefix `2f569102a343488aa01b220993a513dc:request:`.
`provider/*/request_context.json` maps each R-number to its exact prompt, receipt,
and stream. Detailed audits are under `tmp/glm-local-exec/`.

### 1. Local execution omits facts about referenced targets

**Confirmed harness projection defect.** R11 inspected four friendly units at
revision 135. R12's local prompt kept exact origins and exchanges, but enemy
`defender_facts` held type/weapons without current position, HP, side, or status.
GLM guessed U28's position, then recovered it from old event memory. Supporting
friendly positions and named village ownership were also absent from the local
view. Army totals and IDs cannot substitute for those relevant current rows.

The local prompt was 161,112 bytes / 51,236 input tokens; 131,633 bytes were the
inspection rendering itself. The previous objective prompt was 48,031 bytes.
This does not contradict the matched offline byte reduction: the live four-unit
inspection added a large result. R12 made a useful legal retreat, but one local
call cannot establish reasoning savings. Only one `inspect_units` request (four
units) was used during the game; later route uncertainty usually led to guessing.

Minimal follow-up: retain compact current rows for entities referenced by the
selected operation and its support, including position/HP/status and relevant
village facts. Keep unknowns explicit and avoid restoring unrelated option rows.
Test wounded/poisoned targets and supporting units at the exact inspection
revision; assert selected choices are unchanged. Measure fixed-prefix, inspection,
local-view, and final bytes separately. Test task-scoped target/retreat inspection
against broad unit inspection before introducing another planner or control tier.

### 2. Review and repair lose the draft's explanation

**Confirmed context defect.** R13 supplied a rationale for replacing an exposed
Grunt with a regenerating Troll. R14 received draft actions but not that intent
or decision metadata, then re-derived the rationale. R21→R22 repeats the omission.
R24 likewise spends effort interpreting the preceding draft while repairing one
move. Provisional rationale should not be mistaken for accepted memory, but
removing it from review loses useful context.

Minimal follow-up: put bounded draft intent/decisions beside the actions in an
explicitly untrusted candidate block. Test exact distinctive rationale survives
review construction, missing rationale is explicit, and a replacement response
controls committed memory rather than silently publishing the rejected draft.

### 3. Preview instructions specify the wrong ending

**Confirmed prompt/validator mismatch.** The canonical instruction says preview
candidates end with `EndTurn`; validation accepts `EndTurn`,
`DoneWithImportantMoves`, and `FinishWithGreedy`. R15 spends substantial reasoning
on this discrepancy. R20 finally previews two `EndTurn` candidates despite its
selective-finish intention; R21 submits one, and R22 changes it back to a selective
`FinishWithGreedy` with empty groups and 15 explicit holds after seeing the
sweep casualties.

Minimal follow-up: document all supported finishers and their sweep semantics,
including validation errors and maintained examples. Test all three valid
endings and rejection of a candidate without a required finisher. Preserve the
existing action schemas and do not add an automatic sweep.

### 4. Sampled labels and casualty memory obscure which side acted

**Confirmed rendering/provenance defects.** `SAMPLED_OPPONENT_MOVEMENT` actually
reports friendly-unit movement during the opponent interval; an enemy-only move
can therefore produce `moved=-`. `SAMPLED_OPPONENT_CASUALTIES` similarly lists
friendly casualties. R19 initially has to untangle the label. The side filter
is correct; the labels are misleading. Separately, committed batch continuity
can include subsequent opponent-inflicted casualties without an event-source or
phase label. Authored movement progress correctly excludes enemy moves.

Minimal follow-up: explicitly label friendly side and opponent-response interval;
separate controlled-action and opponent-response casualties while preserving all
real events. Test enemy-only movement, mixed-side casualties, both player sides,
and `llm` / `delegated_greedy` / `greedy` event sources. Do not drop opponent
history or relabel a sampled death as live.

### 5. Task, batch, and stopping guidance need sharper boundaries

**Prompt ambiguity plus observed model behavior.** R3/R7 debate whether a legal
multi-action batch violates “one useful operation” or “observe after each step.”
Actual observations follow accepted batches, with no observation between actions
inside one batch. R6 notices that deploying reserves is better, yet cites the
stopping rule to retain a prior hold plan. R7's movement macro reduces distance
to its goal but leaves some units in castle hexes; the model had assumed it meant
“clear the castle.” R23 treats advice about healing destinations as a requirement
even while handling immediate survival.

Minimal follow-up: distinguish primitive action, macro, accepted batch, and turn;
state the macro's actual goal; permit correcting a detected mistake or stale
assumption. Tactical advice should not read like a schema requirement. Tests
should preserve legal multi-action batches and exact post-batch observations,
with separate behavioral cases for corrected plans and justified holds. Avoid
forcing every action through inspection or locking the model to one action.

### 6. Preview and review expose different useful facts

**Workflow opportunity; no candidate-identity bug established.** R20's explicit
preview and R21 follow-up show side totals but not casualty IDs. R22 adds full
sampled rosters, friendly movement/casualties, and a baseline comparison; GLM then
reconsiders the sweep. R20→R21→R22 costs 197,898 total tokens for turn 7.

The selected explicit C0 correctly becomes candidate 1 in the automatic review,
where candidate 0 is the baseline. Candidate action digest, sampled result, and
seed match. There is no evidence of wrong-candidate attachment or a different
sample for that draft. An additional query alone does not prove duplicate engine
work. Test whether a bounded casualty/transition summary in the explicit preview
follow-up removes re-derivation while retaining the existing review's information
and safety properties. Preserve exact revision/candidate identity in those tests.

### 7. Useful reasoning and unsupported reconstruction coexist

**Model behavior, not all missing harness data.** GLM correctly catches
attack-after-target-death hazards and uses `Engage`; it recognizes sampled versus
live boards, retreats wounded units, revises a sweep after casualty warnings,
and repairs the final rejected batch without applying its hypothetical actions.
The new casualty trigger has isolated offline coverage; this live run's warnings
also had other review triggers, so it cannot prove the new predicate alone fired.
No malformed inspection appeared, so repair preservation remains an offline gate.

It also repeatedly recomputes odd-r geometry, guesses terrain costs, confuses
friendly/enemy control zones, and treats maximum-hit bounds as typical damage or
reuses them after changing HP. R20 invents a Bowman sword of 9×2 despite the
same prompt's explicit 5×2 profile; R21 recovers the correct value. R23 guesses
U48's retreat, receives `DestinationUnreachable`, and R24 removes that move. That
is the run's sole rejected batch; all prior hypothetical actions rolled back.
A copied-checkpoint probe confirms `failed_index=4` indexes the authored U48
move; `Engage` expansion does not shift it. The destination is genuinely
unreachable under enemy control, so this is not an error-index or engine bug.

Two suspicions were ruled out by copied-checkpoint engine probes. At rev218 U5
really can move from (2,4) to (5,8) and shoot U32 at (6,9); GLM's disputed coverage
was correct. At rev265 stationary `Engage` emits only an attack and preserves
movement for a later retreat. Add one sentence about that stationary case and a
move-after-Engage regression if clarifying the contract; do not change mechanics.

### 8. Stable prefix does not guarantee provider cache hits

R16–R19 share an identical 19,650-byte fixed prefix and identical non-message
payload settings. R16 reports 14,336 cached tokens; R17/R18 report zero; R19
reports 14,336. Byte evidence does not establish provider TTL, eviction, routing,
or cache eligibility as the cause. Retain measured per-call cache usage and
avoid claiming this proves a new prompt-prefix defect.

### 9. Catalog summaries have reporting gaps despite complete paid usage

The terminal archive preserves `termination_reason=budget_interrupted` and
`failure_code=max_game_total_tokens_exhausted`, but its derived coverage reports
`terminal_class=model_invalid`. Usage-by-turn omits the ninth open turn because
it has no calls. All five raw reviews and their decisions are linked, but the
normalized review view contains only three; R14 and R19 are listed as
`not_normalized`. These are confirmed output differences. Their underlying
normalization policy needs inspection before claiming lost review data.

Minimal follow-up: classify budget interruption distinctly from invalid model
output; make zero-call open turns visible or explicitly document that usage
queries enumerate only turns with usage; expose why linked reviews are not
normalized. Tests should import one budget-blocked request with no dispatch and
assert the correct stop, retained open turn, and zero physical calls. Reproduce
R14/R19 review shapes to either normalize them or report an explicit unsupported
reason, preserving raw identities and idempotence. None of these gaps changes
the measured 24-call usage or creates an unassigned paid call. Evidence:
`tmp/glm-local-exec/final-evidence-audit.md` and archive `catalog-game.json`.

## Recommended next scope

First fix the concrete context omissions and contract wording above, with small
regressions and no engine/schema redesign. Then test a narrower selected-task
handoff: objective plus exact local options and referenced live facts, with a
short stated rationale preserved across review. Compare task completion, invalid
moves, reasoning tokens, and casualties against the present flow. This run does
not justify merely adding more tactical prose, making another broad hierarchy,
or asserting that lowering reasoning alone will solve the problem.

The implementation iteration and its one observed retest are complete. Newly
found defects are recorded here for follow-up; no source was changed during the
paid game and no additional paid game was launched.
