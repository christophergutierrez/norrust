# GLM diagnostic corrections: execution and retest

Implementation and the one authorized paid diagnostic are complete. Luna High
workers implemented the [phased plan](../plans/glm-followup-corrections.md) in
isolated worktrees; the parent reviewed, integrated, tested and committed each
stack, then watched the fresh GLM Flash game. The game stopped on its token
budget with no winner. The retest found further correctness and decision-context
issues described below; those findings are not silently counted as fixed.

## Baseline and evidence

Baseline source: `85373d4e0e12e742977967f2284e2ec5a234309c`;
plan-only commit: `14265b3`. The full headless gate passed on that checkout:
609 Python tests, Rust library/binary/named integration suites, and Lua bridge,
replay and recorded-game tests. Interactive GUI acceptance is separate.

Prior game: `d03b99d74969fd764077ae4823c9ea5a`, archive
`tmp/quick-play-glm-efficiency-xbsjhb82/`. Its read-only catalog inspection and
hashes of all 220 original files are saved under `tmp/glm-followup-exec/`.
Historical acceptance operates on a copy and must leave those originals intact.

The previous game stopped on request 25 with HTTP504 after 600.52 seconds;
neither side won. Five controlled-side turns completed, with a partial sixth.
Known 24-call usage: input 317522, cached input 135168 (input subset), output 676392,
reasoning 660682 (output subset), total 993914. Failed-call usage and cost unknown.
The old catalog leaves17 calls without a turn, despite preserved request contexts.
It also misses the failure outcome and reports misleading complete usage coverage.

## Integrated stacks

Stack 1 integrates Luna contract/repair and rejected-intent corrections:
separate bare-tool/action contracts, a shared bounded repair path, explicit
model-call accounting, committed task context, and readiness flags distinguished
from actual attack coverage. Promotion missing/empty semantics are retained.
The guide grew248bytes (+4.94%). Focused checks and the cumulative gate passed: 622 Python tests plus Rust
and Lua suites (`tmp/glm-followup-exec/stack1-fast-check-pass.log`).

The initial integration checks caught prompt size regressions and stale maintained
cache/promotion fixtures. Luna shortened duplicate protocol text and refreshed
those fixtures without raising size limits or weakening the historical cache
prefix ratchet. Additional review caught unbounded tool-followup model calls and
rejected intents leaking into committed memory; regression tests cover both.

Stack2 passed its cumulative gate: 625 Python tests plus Rust and Lua
(`tmp/glm-followup-exec/stack2-fast-check-pass.log`). It preserves nested
Engage errors and rollback, counts committed macro progress, supplies both faction
recruit pools and living type abilities, and derives phase modifiers from engine
combat functions. T2 now directs uncertain attack origins to target inspection
and retreat/deployment to unit inspection. The exact old checkpoint reproduces
NotAdjacent through both macro and primitive actions.

The first cumulative stack 2 gate found a 155-byte prompt overrun. The stack 3/4
gates additionally found a failed logical retry aggregate omitting the final
unknown attempt, a percentile fixture whose request IDs were not catalogued, and
isolated-worktree driver-path setup failures. Luna corrections preserve unknown
usage while retaining all-measured ceiling-exhaustion totals. Parent supplied the
built driver at the maintained default path for the isolated checks. Review also
requires partial-action instructions to be conditional on incremental mode.

Stack3 passed its corrected cumulative gate: 631 Python tests plus Rust and
Lua (`stack3-fast-check-pass.log`). The main tree matches the tested cumulative
checkout `b76abdf` byte for byte, excluding this execution report.

Stack4 passed its cumulative gate: 643 Python tests plus Rust and Lua
(`stack4-fast-check-pass.log`), with no skips. The main source matches tested
checkout `943159a` byte for byte, excluding this execution report. Streaming
retains exact payload/prompt hashes, incremental SSE chunks, reasoning/content,
and complete or partial receipts. Incomplete responses cannot execute actions.
Tests include local HTTP transport through the real driver, unknown usage, and
exactly-once physical-call records. No paid calls occurred in implementation.
Worker handoffs and focused results are in `tmp/glm-followup-exec/stack2-handoff.md`, `stack3-handoff.md`,
`stack3-review-handoff.md`, and `stack4-handoff.md`.

Historical scratch acceptance already reproduces 25 requests/25 calls,24 measured,
all 25 turn links,22renderable snapshots,307 events, and zero unattached reviews.
Totals remain input 317522/output 676392/reasoning 660682/total 993914. Failure code
is `model_backend_failure`, elapsed7569799ms, final proven revision277, measured
usage partial. Reimporting twice preserves counts/links/totals with clean database
integrity. The original archive and catalog hashes are unchanged.

## Paid diagnostic: completed

Game `ee269ac3ee0a761f8dcd433feb9476e6`, source
`bdb5dcf9eb793429c5ef09d9b70af0c444e8612d`, archive
`tmp/quick-play-glm-followup-dekusife/`. Same scenario `big_battle_6`, seed
771125826, Northerners versus Loyalists, gold 300, side 0, focused/choices/
incremental, 50-side-turn cap and 1,000,000 measured-token budget. The maintained
Fireworks adapter used streaming, a 131072 starting output limit, and provider
sampling/reasoning defaults. No output escalation or transport retry occurred.
Actual default sampling/effort values are not reported by the provider and remain
unknown. No second paid run or 48-cell experiment was launched.

**Result: budget_interrupted, no winner.** Seven controlled-side turns completed;
turn 8 opened at revision315. Final actual losses were five units on each side;
GLM retained 22 units/669HP/290 material cost versus 19/634/283, and 3 villages
versus 2 (one neutral). It neither won nor completed the game.
R27 returned an all-hold proposal, but its required
review R28 was blocked locally before dispatch. Thus that proposal did not commit.
The limit is checked between responses: 998810 spent before R27 became 1036415
afterward. Exit2 is the harness budget outcome, not a defeat or a provider failure.
The run ended 2026-09-11T07:54:35Z after about two hours.

| Provider-measured field | Tokens | Coverage |
|---|---:|---|
| Input | 374141 | 27/27 calls |
| Cached input, subset of input | 163840 | 27/27 |
| Output, including reasoning | 662274 | 27/27 |
| Reasoning, subset of output | 647757 | 27/27 |
| Total input + output | 1036415 | 27/27 |
| Cache-write input | UNKNOWN | 0/27 |

There are 28 logical request records and 27 physical paid calls. All paid calls
returned `stop`; R28 is proven locally blocked, not an unmeasured paid attempt.
Known estimated API cost is **$0.367597**, not an invoice. Official rates were
reverified after completion: $0.15/M input, $0.03/M cached input and $0.50/M output
([Fireworks model page](https://fireworks.ai/models/fireworks/glm-5p3-flash)).
Computation: `(374141-163840)*0.15/M + 163840*0.03/M + 662274*0.50/M`;
reasoning is not charged again. Provider elapsed times sum to 7227176ms; this is
provider-call wall time, not measured CPU reasoning time or engine-query time.

Catalog import, repeat import, replay export, foreign keys and integrity passed:
27 snapshots/frames,360 events,8 side-turn records,28 requests,27 calls,
19 accepted batches and 68 authored actions. Game usage has
`aggregate_only_request_ids=[]`, `unassigned_calls=0`; every one of the eight
turn groups reports that same empty/zero pair. Details are in `usage-turn.json`
and `tmp/glm-followup-exec/final-game-audit.md`. Raw reasoning is retained in
`provider/*/completed.json`, separately from model-authored decision annotations.
Every physical call has prompt/context/payload/received chunks/completed receipt;
27/27 canonical prompt hashes and payloads match the client request byte for byte.
The frozen source and all 220 protected old evidence files verified unchanged
before any post-run edits. The replay is also imported in the normal menu catalog.

Replay from the repository root:

```sh
python3 -m tools.replay_game --db .norrust_history/history.sqlite ee269ac3ee0a761f8dcd433feb9476e6
```

The export is `tmp/quick-play-glm-followup-dekusife/replay.json`. The automated
headless replay checks passed; a new interactive GUI review was not performed.

## What improved and what did not

| Milestone | Previous measured tokens | Fresh measured tokens |
|---|---:|---:|
| Opening / first village captures | 195860 | 205511 |
| Completed own turn 3 | 367180 | 314331 |
| Completed own turn 5 | 893899 | 570030 |
| First enemy kill | 798710 | 570030 |

The opening cost 4.93% more, while its reasoning dropped11.40%. The first kill
cost 28.63% fewer tokens. These are descriptive milestones from one combined
retest, not causal estimates or proof of stronger play. The old run stopped on
an unmeasured HTTP504; its $0.369604 is only the known 24-call cost. The fresh run
has complete paid-call usage. Neither run establishes a winner.

Useful behavior included the R8 hypothetical review correcting underspending,
R18 repairing the second-Move error, R19 stopping an Engage when its first
attacker killed the target, and R24 legally finishing two wounded enemies while
retreating damaged units. Macro progress and committed intent reached later
prompts; rejected drafts did not replace committed memory. R21/R22 exposed the
exact nested Move failure and rollback instead of the old misleading unit error.
Both failed route drafts were repaired, though expensively.

Waste remained substantial. R17 used60106 reasoning tokens on an invalid batch,
and its R18 repair used76944. R21/R22 repeatedly replaced a guessed unreachable
origin with another guessed origin. GLM considered inspections but did not send
one; automatic handoff reviews are distinct from model-initiated inspections.
R24 used47374 reasoning tokens for nine legal actions. R25 then used13156 merely
to propose the already planned finish; R26 review added12371. Long responses all
ended normally, so this was not output-token exhaustion.

## Newly diagnosed issues and bounded next work

1. **Terrain data has inverted defense semantics.** Shipped Orcish Archer values
   flat 60/forest 50/castle 40/swamp 70 match Wesnoth chance-to-be-hit, but runtime
   calculates `100-defense`. Actual hit chances are40%/50%/60%/30%: swamp protects
   better than castle. The same contract mismatch affects other imported unit
   and default terrain tables. `tools/scrape_wesnoth.py:50-57,330-355,391-446`
   copies these values; `norrust_core/src/combat.rs:426-440` and `ai.rs:78-93`
   consistently subtract them. Forecasts and combat agree; the import meaning
   is wrong. Official [Wesnoth UnitsWML](https://wiki.wesnoth.org/UnitsWML)
   confirms the source meaning. In the live game U19's flat-to-forest move
   increased the three-volley kill probability 26.66%→50%, even as available
   attackers fell 11→5. Later friendly movement opened more paths, raising
   attackers to 16. GLM repeatedly assumed forest protects and swamp hurts.

   Retain the existing runtime avoidance contract, explicitly convert imported
   hit chances, correct fresh generated tables and conflicting maintained docs,
   and add importer→loader→forecast/combat fixtures. Raw flat 60/castle 40 must
   become stored avoidance 40/60 and runtime hit chance60%/40%. Negative WML
   entries also encode mixed-terrain caps: preserve that meaning if supported,
   or explicitly bound the importer to existing indivisible terrain IDs. Avoid
   an unrelated schema migration and preserve historical game evidence.

2. **Missing action mechanics and ambiguous compact fields cause concrete errors.**
   R17 submitted two Moves for one unit and Move→Attack→Move for another; the
   engine allows one independent Move and one Attack per side turn. Movement
   points validate the single route, not several movement actions. Attack→Move
   advice already exists, so adding it again would miss the actual gap.
   Supply that exact rule, odd-r `(col,row)` semantics, adjacent-castle recruitment,
   and the six-slot phase cycle Dawn/Day/Day/Dusk/Night/Night. State explicitly
   that `inspect_units` returns legal destinations, their attacks and danger.

   Replace ambiguous presentation instead of growing another tactics checklist:
   `E` is own economy, `move_n` counts origins, current attacks absent may mean
   spent or no legal target. Both direct/open danger include enemy movement;
   OPEN removes other-unit blockers/ZOC, not terrain, and is not a joint enemy
   plan. Use named probabilities/units: R25's final risk text read144 whole-HP
   maximum damage as14.4 because other fields use tenths. GLM also confused
   kill-by-1/2/3-attacker probabilities with combat exchange outcome probabilities,
   and zero within that limited forecast with safety against more attackers.
   Keep exact values and scope together in a small selected-unit/target card.

3. **Saved plans become unjustified constraints.** The active `mass` task still
   covers most of the army. Every partial request reopens formation and manual
   geometry. Conversely, R27 noticed potentially useful regenerating-troll
   attacks, then rejected them because its own saved plan said “no duels.” It
   also proposed holding6 HP U3 as bait. The model quotes the stopping rule and
   can explain tools, but does not consistently use them. This is not solved
   by appending “pick quickly” again. Mark retained intent as provisional model
   reasoning, tied to turn/conditions and overridden by changed live facts.
   Show the measured remaining game budget, currently invisible to the model.
   After correctness fixes, test a bounded two-tier variant using existing
   tools: select one target/objective and a small unit set, then execute against
   exact local options. Compare useful actions, failures, tokens and outcomes;
   do not build a second agent service or assume smaller text guarantees savings.

4. **Small provenance and multi-recruiter defects remain.** Automatic reviews lose
   a known origin revision because `query_preview_batch` drops the status
   envelope while the formatter reads the body. Propagate the known revision;
   do not invent `danger_after` when the executor supplies no pre-finish threat
   facts. Separately, advertised recruit placements union all `can_recruit`
   keeps, but manual Recruit chooses the first eligible keep, including a
   leader-only unit. Share eligibility/placement selection and test two keeps
   plus leader-only recruiting. This latent case was source-audited, not exercised
   by the normal single-recruiter game.

5. **Catalog provenance still has narrowly scoped gaps.** All 68 action rows and
   12/19 batch rows have null direct side-turn IDs, although their explicit
   request IDs join to validated request/turn identities. Populate those links
   only from that existing proof and test normal import plus idempotent reimport;
   never infer the nearest revision. Usage attribution itself is complete.
   The game-level driver hash is null although launch.json retains
   `b06788c7672a4237597a996e862c9d8d5c96b667cd778183054b24030d79db9f`;
   per-request prompt hashes are present, while a single game prompt hash is
   naturally not a description of all changing prompts. Four raw draft reviews
   are preserved, but the catalog's two linked reviews count only emitted
   handoff-review records. Scope that coverage clearly rather than equating it
   with every automatic review being normalized. Five completed requests have
   invalid annotations: R5/R10/R12/R16/R25; the post-run correction below addresses
   the omitted field contract.

Several suspected defects were ruled out: empty selective groups do not perform
an automatic full sweep (that was the review's separate baseline candidate);
turn 8 readiness flags were reset correctly (GLM confused coverage with readiness);
and projected casualties did not become live casualties. R26 predicted two
losses, but the live opponent killed only U7. Available evidence must distinguish
an intermediate thought, a final claim, a proposed action and a committed event.

## Post-run regression correction

The retest exposed a regression introduced in stack 1: focused mode omitted the
shared annotation schema/240-byte limits. Legal actions still ran, but several
explanations were rejected. Luna corrected this in an isolated worktree while
the game ran. Shared field rules now match both modes; only coverage differs.
Review/repair wording uses that same optional contract. Action-only paths no
longer end with a contradictory inspection invitation, and final-call tool
repairs reserve the necessary action follow-up. Existing cache size limits and
historical prefix checks remain intact; concrete examples were shortened.

The isolated source at 8e00311 passed 649 Python tests and the full Rust/Lua gate.
The parent integrated byte-identical source only after the paid evidence/source
checks. The final main gate passed 649 Python tests (no skips),176 Rust library
tests,11 driver tests, the named integration suites and all Lua checks. Log:
`tmp/glm-followup-exec/final-fast-check.log`; correction commit: `574f6c8`. This final
correction has offline end-to-end coverage, not a second paid retest. The other
new findings above remain documented next work.

## Evidence and handoff

`tmp/glm-followup-exec/HANDOFF.md` records the completed work and commits.
The fresh archive contains catalog/usage JSON, cost metrics, request evidence
checks, source verification, replay, observations and final audit. Additional
source audits are `terrain-defense-audit.md`, `new-engine-findings.md` and
`new-game-review-method.md` under `tmp/glm-followup-exec/`. These ignored artifacts
preserve exact local evidence; this tracked document preserves the findings and
source identities without committing paid prompt/reasoning archives.
