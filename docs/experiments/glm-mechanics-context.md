# Mechanics and focused-context corrections: execution record

Implementation and the single authorized paid diagnostic are complete. The user authorized the
[plan](../plans/glm-mechanics-context.md), Luna High implementation, and one
fresh observed GLM 5.3 Flash game after completion. All four cumulative code stacks
were committed before launch; the game source stayed frozen throughout play.

## Baseline and preserved evidence

Baseline code: `90fb2a8`; plan committed before workers: `15fe57f`.
The preceding code gate passed 649 Python tests plus the full supported Rust/Lua
gate; the plan commit changes documentation only. Three Luna High workers use
isolated worktrees for mechanics, context, and provenance. The parent reviews,
integrates and gates each cumulative stack before committing it.

Previous game `ee269ac3ee0a761f8dcd433feb9476e6` stopped at revision 315 with
seven controlled turns completed, no winner, and 1,036,415 measured tokens.
All 27 paid calls returned normally. Input 374,141, cached input 163,840,
output 662,274, reasoning 647,757; cache-write unknown. Known estimated cost was
$0.367597. A 28th logical request was blocked locally before dispatch.

The prior catalog was inspected before raw evidence. Baseline hashes of 465 files
across that archive and `tmp/quick-play-glm-efficiency-xbsjhb82/` are recorded in
`tmp/glm-mechanics-exec/historical-hashes.json`. Historical recovery uses a new
scratch catalog referencing the original canonical paths; original records and
catalogs must not change. The earlier game's confirmed direct action/batch turn
gaps and raw-versus-normalized review gaps are acceptance cases, not speculative
new database rows.

## Stack results

Stack 1 passed the full cumulative gate: 653 Python tests, 179 Rust library
tests, driver and supported integration suites, and all Lua headless checks.
Defense conversion includes unit overrides; shared recruiting uses the same
selected keep. The independent data audit found no non-defense stat changes.
The maintained recruiter-defense fixture needed a deterministic RNG adjustment:
its old rolls 66/44 both miss against corrected 60% castle avoidance. State 2
restores the intended hit without changing the objective predicates; all 24
matrix cells pass. Historical evidence remains byte-identical.

Stack 2 passed the full cumulative gate (657 Python tests plus the supported
Rust/Lua suites). Prompts now show explicit percentages and HP, live move/attack
readiness, exact phase/routing/recruitment rules, and movement-inclusive threat
scope. The presentation ceiling is 18,500 bytes, below the allowed 18,975-byte
maximum; the final largest measured small fixture is 18,176 bytes. Historical
cache-prefix comparisons and runtime prompt-byte limits remain intact.

Stack 3 passed the full cumulative gate (671 Python tests plus supported
Rust/Lua suites). Existing inspections now produce revision-pinned local
contexts with live weapon facts; global state stays available. Provisional
memory carries its origin and resumes only with acceptance evidence, including
a checkpoint saved before acknowledgment. Rejected and open proposals cannot
become committed context.

The game-budget suffix reports measured spend and uncertainty. Real-driver
tests prove that physical usage changes between output-limit attempts while
the retry prompt remains byte-identical, and the next logical request refreshes
its budget. The final byte cap and telemetry include all appended context on
main, tool, and repair dispatches; exact-cap and one-byte-under tests pass.
An independent review found and corrected both the suffix-cap bypass and an
unproven-continuity bug before this gate.

Stack 4 passed the full cumulative gate (682 Python tests plus supported
Rust/Lua suites). Fresh records retain driver hashes and request/turn identity;
preview origin revisions survive rendering. A separate scratch catalog recovered
all 68 historical action links, 19 batch links, and four actual reviews while
retaining the two legacy handoffs as a distinct count. All 27 paid calls remain
linked, with 1,036,415 tokens, no aggregate-only requests, and zero unassigned
calls. Reimport produces an identical logical SQLite dump; integrity checks
pass and all 465 historical files remain byte-identical.

Gate logs and worker handoffs live under
`tmp/glm-mechanics-exec/`.

## Paid retest: stopped at the token cap, no winner

Game `acf48862062d7233448b750b762b6216`, cohort `glm-mechanics`, is available in
`.norrust_history/history.sqlite` for the normal replay menu. Archive:
`tmp/quick-play-glm-mechanics-6gjp83e_/`; standalone bundle: `replay.json`.
Source: `f817fbabbdbbf79a5c372ad445220e61c88f236e`, clean throughout play.
Driver SHA256: `089226cce2d5601463bbfe5767713a107ca9f5d14c2f8a59f913a7edb8082153`.

The maintained streaming Fireworks backend ran `accounts/fireworks/models/glm-5p3-flash`
on big_battle_6, seed 771125826, Northerners/Loyalists, 300 gold, side 0,
focused/choices/incremental, 50-side-turn cap, 1M measured tokens. Provider-default
sampling/reasoning and the 128k→512k output policy were unchanged. No output-limit
retry or paid transport failure occurred. All 28 physical responses returned
`stop`; request 29 was blocked locally before dispatch. The last paid response's
Engage committed, then the next call hit `max_game_total_tokens_exhausted`.
This ceiling is enforced between calls; the 26,917-token overshoot is the final
in-flight response, not an extra retry or an unlogged game.

Started 2026-09-11 12:51:15 UTC, ended 14:39:41 UTC: 108.42 minutes. Four model
turns completed; turn 5 remains open at revision 243. Neither recruiter died and
there is no winner. Catalog status `complete` means the terminated archive is
complete, not that a player won. The final enemy response was not played.

| Final live measure | GLM side 0 | Greedy side 1 |
| --- | ---: | ---: |
| Units |24|21|
| HP / maximum |861/918|644/700|
| Material cost |324|311|
| Gold |6|2|
| Villages |3|2|

One village remains neutral. GLM killed Bowmen U32 and U28, lost Wolf Rider U22.
Its last attack left U27 at 7 HP. The apparent material/HP lead is provisional:
several attackers were exposed and the opponent had not answered turn 5.

### Tokens, cost, and evidence

| Usage | Tokens |
| --- | ---: |
| Input |436,488|
| Cached input, included above |229,376|
| Output |590,429|
| Reasoning, included in output |580,798|
| Input + output |1,026,917|
| Cache-write input |unknown for all 28 calls|

Estimated cost **$0.333163**, about 33¢, not an invoice. The official
[Fireworks GLM 5.3 Flash model page](https://fireworks.ai/models/fireworks/glm-5p3-flash),
reverified 2026-09-11, lists per-million rates of $0.15 input, $0.03 cached input,
and $0.50 output. Calculation:
`(436488-229376)*0.15/1e6 +229376*0.03/1e6 +590429*0.50/1e6`.
Reasoning is already included in output and is not charged twice. Cache hits
cover 52.55% of input; 98.37% of output is reasoning. Median physical response
latency was 181.82 seconds, maximum 632.29 seconds. All 28 paid calls have measured
input/output/reasoning/cache-hit fields; cache-write remains unknown.

| Model turn | Physical calls | Tokens this turn | Cumulative |
| --- | ---: | ---: | ---: |
|1 ended|4|106,630|106,630|
|2 ended|2|52,850|159,480|
|3 ended|5|206,606|366,086|
|4 ended|6|226,686|592,772|
|5 open|11|434,145|1,026,917|

First movement: R2 at 48,757 tokens. Three villages captured at the end of turn 1,
106,630 tokens. First attack: R18; first enemy kill: R19 at 679,448 tokens.
There were four successful model inspections: R16 inspect_units for two Nagas,
and R22/R25/R27 inspect_targets for two targets each. R14's malformed inspection
never executed. Four pre-submission batch validations rejected moves
(R7/R12/R15/R20); none of those batches mutated live state. The terminal's
`rejected_batches=0` counts driver submission rejection, not these validation
failures; do not use it alone to claim error-free action generation.

Catalog-first final import and reimport passed SQLite integrity/foreign keys.
A further import produced an identical full SQL dump.
All 75 authored action rows and 18 batch rows directly link to requests and turns;
all 29 logical requests link to turns; all 28 physical calls link to their requests
and turns. The one actual draft review and its confirmation are retained and
linked. `aggregate_only_request_ids=[]` for the game and every model turn;
`unassigned_calls=0` globally and all 28 calls partition into the five turns.
Request 29 has no physical call because it was locally blocked, not missing spend.
The replay has 23 frames and 256 events; no action/review/event gaps or conflicts.
Catalog action/batch statuses remain `accepted_unknown`: their attribution is
proven, but the catalog does not independently establish per-row acceptance.
Four snapshots retain an `unknown` boundary classification.

Every provider payload contains the exact canonical prompt bytes; all 28 prompt
hash/context/archive comparisons pass. Raw SSE reasoning, final response, receipts,
request journal, usage sidecar, checkpoints, and launch identity are retained.
Source stayed clean/frozen and all 465 historical files match baseline hashes.
The game-level `games.prompt_hash` is NULL; prompt integrity is established by
the per-request hashes and the 28 canonical comparisons above. This is direct
API accounting; it contains no inferred host-subagent usage. The independent
Luna audit is `tmp/glm-mechanics-exec/final-history-audit.md`.
Audit artifacts: `verification.json`, `evidence-audit.json`, `source-verification.json`,
`cost-metrics.json`, `usage-{game,turn,call,request}.json`, `milestones.json`,
`final-analysis.json`, and `process-exit.json` in the new archive.

### What the observed struggle means

The opening was shorter than the previous run: 4 responses/106,630 tokens versus
10 responses/205,511. Later progress did not improve: the previous run reached seven ended
turns and five kills; this one reached four ended turns and two kills. These are
single-run descriptions, not a strength estimate or a controlled prompt comparison:
stack 1 corrected terrain mechanics, so the games use different rules/data.

| Classification | Concrete observation | Implication |
| --- | --- | --- |
|Useful/expected|Recruitment and three opening villages; Dusk-versus-Night tradeoffs; rescue of U5; focus kills U32/U28; checking distinct attack origins.|Do not eliminate all reasoning or force attacks merely to reduce tokens.|
|Unsupported/unproductive|R7 spent 60,794 reasoning tokens hand-routing 17 moves; R7/R12/R15/R20 repeatedly failed Naga movement. R19 invented damage dice; R21 said Bowmen had no melee; several responses gave neutral Nagas a Night bonus.|These are not legal engine quirks. Facts/options exist, but GLM often reconstructs them incorrectly instead of inspecting.|
|Understandable friction|Empty-group finishing legality, an ambiguous exposure omission, current readiness labeled as a historical sweep, and repeated global reassessment after partials.|Make control effects and local scope explicit. More prose alone is unlikely to resolve this.|
|Missing harness behavior|A malformed inspection lost tool access in its repair; an internal preview showing a death did not trigger review; village trends were false zeros.|These are concrete harness defects/gaps, independent of model quality.|

The local context works when reached. R16's inspection immediately ruled out the
bad Naga routes; R17 used inspected destinations and the repair succeeded, at
8,652 reasoning tokens. R23/R26/R28 used inspected Engage origins without another
legality failure. But GLM reached its first successful inspection only at request 16,
and still reopened global strategy inside local execution requests. Current two-tier
behavior is advisory prose plus full global context, not a constrained phase change.

### Remaining findings and bounded next steps

These were discovered during the frozen retest and are **not implemented** by
this iteration. No second paid run or source changes were made during play.

1. **Syntax repair must preserve legitimately available tools.** R14 emitted valid
   inspect_units JSON plus unfenced rationale, producing `Extra data`. Parsing
   failed before tool recognition, so generic repair set `allow_tools=False`.
   R15 explicitly received “Do not request a read-only inspection” despite
   final_only=False and ample tool budget; it guessed both already-failed Naga
   retreats again. R16's engine-error repair allowed inspection and succeeded.
   Keep strict execution parsing, but route syntax repair through the appropriate
   live capabilities; never execute a guessed JSON prefix. Test malformed inspection
   prose→bare corrected inspection→local result→legal action, with final-only/tool
   exhaustion still enforced. Existing fenced JSON can be parsed with surrounding
   prose, explaining why R16 succeeded while R14 did not.
2. **Review the consequence already visible in a bounded preview.** R6 chose
   EndTurn expecting no Day contact. Its sweep moved U22 from (8,7) to (15,6); four
   enemy attacks killed it. The internal sampled preview already showed that
   death, but the current escalation predicates ignore post-sweep casualties when
   exposure is unavailable. The later safe empty-group finish triggered review.
   Surface a concise sampled casualty/position-change delta and test whether it
   triggers review; retain simulation labels and model choice, not an automatic veto.
3. **Make hold-only finishing obvious.** Both EndTurn and DoneWithImportantMoves
   run the automatic own sweep. `FinishWithGreedy` with `groups:[],holds:[]`
   already expresses no own sweep, then the opponent acts. GLM repeatedly doubted
   empty groups were legal, split off an unnecessary Goblin move, and speculated
   holds persist into later turns. Add the minimal explicit example and lifetime
   statement; test it through the real driver. Prefer that over another action alias.
4. **Correct the remaining numeric semantics and coverage display.**
   `summarize_threats` returns null `lethal_attackers_needed` when supplied maxima
   cannot total the target's HP; `_readable_optional_count` calls that unknown.
   Distinguish known nonlethal-within-scope from missing data. Label the integer
   as minimum attackers under maximum hits; maximum, expected damage, and kill
   probability are different measures. The compact renderer omits zero-threat
   units: expose evaluated/threatened/zero coverage without dumping every row.
   Put movement-inclusive/current-position scope beside EXPOSURE itself. R8
   explicitly questioned whether omitted units had been evaluated; R19 repeatedly
   misread direct as no enemy movement; R26 treated expected damage as a hard cap.
5. **Fix false village trends and misleading readiness provenance.**
   `compact_trend()` reads nonexistent `state["village_owners"]` rather than
   `terrain[*].owner`, rendering both sides' villages as 0. Actual revisions 84,
   136, 176 have 3/1, 3/2, 3/2. Test trend versus the strategic/live rendering from the
   same StateSnapshot. Rename `whole_army_sweep` to current-turn readiness and
   label moved/attacked/agenda-unassigned/agenda-holds explicitly; it is built
   after the fresh query, not evidence of the previous automatic finish.
   R12 initially misread it as historical movement. Update maintained callers,
   tests and docs together without a development compatibility alias.
6. **Test an actual local execution boundary before expanding the playbook.**
   Keep global recruiter/economy warnings visible, but make the selected task,
   revision, legal options and immediate response central. Compare a small
   matched set of positions for time to first useful action, reasoning tokens,
   inspection uptake, route failures, operation completion and unwanted replanning.
   Inspect once when a route/target is uncertain; carry the result into execution.
   Avoid mandatory inspections for already supplied legal actions, extra planning
   services, or an unrequested paid matrix. Lower reasoning effort or native tool
   transport would be separate controlled treatments, not proven fixes from this run.

Source-confirming read-only Luna audits are retained at
`tmp/glm-mechanics-exec/{engine,context}-live-audit.md`; streaming observations and
complete derived reasoning are in the game archive. One annotation also referenced
an invalid order index at R19 after the authored list changed; legal actions still
executed. Keep annotation validity separate from action legality and raw reasoning.

### Old-signature acceptance in the live run

| Signature | Live evidence / limit |
| --- | --- |
|Terrain meaning|Corrected data/driver frozen; combat occurred. Cross-terrain conversion matrix remains the deterministic fixture proof; GLM still guessed hit chances.|
|Multiple recruiters|Fixture-only: this game has one recruiter per side.|
|One Move plus independent Attack|No duplicate-Move rejection. Movement/attack spent flags respected in submitted actions; alternate sequences covered offline.|
|Readable numeric units|HP/percent formatting exercised, no raw scale confusion observed; maximum/expected/probability interpretation still poor.|
|Forecast scope|Direct/open movement and current-position interpretation remains unresolved; zero-row legend missing.|
|Local inspection|Four successful requests; R17/R23/R26/R28 consumed local exact options. Uptake slow; R14 syntax recovery lost capability.|
|Weapons|Local target contexts contain Bowman shortsword; GLM sometimes remembered it and sometimes falsely omitted melee, notably R21.|
|Provisional memory|Fresh damage/phase did override earlier plans; rejected batches did not commit their memory. Resume/checkpoint paths fixture-only; model still sometimes treats intent rigidly.|
|Game budget|Known spend/remaining supplied; cap blocked request 29 with fully measured spend. No output-limit retry exercised live.|
|Repair|Four validation failures preserved live revision and were repaired; generic JSON syntax repair tool loss is newly confirmed.|
|Review origin|R11 simulation explicitly originating_revision=153; unavailable danger remained unknown; no preview-death resignation.|
|Actions/reviews/hash|75/75 actions,18/18 batches,29/29 requests,28/28 calls,1/1 reviews linked; fresh hash verified.|
|Prior invariants|Canonical prompt transport, streamed usage, final-only fixtures, atomic rollback and historical hashes preserved.|

All four code stacks remain complete and tested. The observed retest is complete
at its authorized stop rule, with follow-up defects documented rather than silently
folded into a different game. Execution handoff: `tmp/glm-mechanics-exec/HANDOFF.md`.
