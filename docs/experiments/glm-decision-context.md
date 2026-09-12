# GLM decision-context implementation and retest

Completed 2026-09-11 local time (run ended 2026-09-12 UTC).
[Implementation plan](../plans/glm-decision-context.md).
[Previous diagnostic](glm-local-execution.md).

The three implementation stacks passed their cumulative gates and were committed.
The fresh GLM game then stopped on its token budget, with no winner. It reached
a better final board than the previous diagnostic at slightly higher estimated
cost, but still spent most output on reasoning. This is one game per version
with different actions and trajectories, not a controlled estimate of improvement.
The retest also exposed concrete remaining context gaps, described below.

## Implementation and gates

The plan was committed first at `a64c9a4`. Three Luna High workers built isolated
stacks; the parent reviewed and integrated A, B, then C. Each integration passed
`python3 -m tools.fast_check` before its stack commit.

| Stack | Main commit | Python tests | Result |
|---|---|---:|---|
| A | `b778f7e153d34be701a9b5e4d29b10aa59a05a0e` | 714 | Draft intent/annotations through review and repair; sampled candidate and casualty labels; tactical contract corrections |
| B | `a63ee0b6f50b1018234f692d90c4a16fcb389b23` | 720 | Current referenced local facts, matching assigned task, shared inspection facts without dropping options |
| C | `0bc1a8e229e126d1d3cd11ae2187824fe91364b5` | 729 | Budget interruption exit 3 and consumers; zero-call turns; complete normalized review identity coverage |

Rust and Lua checks also passed in each gate. One stale sampled-label expectation
failed the first A gate, was corrected, and passed the complete rerun. No
interactive GUI acceptance is claimed. Gate logs and worker handoffs are under
`tmp/glm-decision-exec/`.

A representative enriched four-unit inspection fell from 120,274 to 28,657 bytes
(76.17%), retaining all 19 attack-option rows. These measurements exclude choice
handles. This proves a serialization reduction, not a reasoning-token saving.
The new game's two three-unit inspections were 25,323 and 32,513 rendered bytes;
the first complete local follow-up was 60,936 bytes. Existing caps were retained.

A separate reimport of the prior game normalized all five reviews, including two
identity-only reviews, and exposed its ninth open zero-call turn with unknown
usage. The original archives were not changed.

## Run identity and outcome

A Luna High operator launched and observed one direct-API GLM game; another Luna
observer audited later calls, and the parent independently checked selected raw
prompts, receipts, outcomes, and copied-checkpoint reproductions. GLM alone
received the unchanged client-generated prompts and authored actions. No coaching,
extra paid game, manual resume, or tracked source change occurred during the run.

- Game: `e27040476dcb31dd0c5c9a88d9230c74`, cohort `glm-decision`.
- Archive: `tmp/quick-play-glm-decision-k41byol0`.
- Conversation: `8c0be63621cd4e43888a2a76d74e8dbd`.
- Frozen source: `0bc1a8e229e126d1d3cd11ae2187824fe91364b5`, clean.
- Driver SHA256: `089226cce2d5601463bbfe5767713a107ca9f5d14c2f8a59f913a7edb8082153`, unchanged after the run.
- Backend: maintained streaming Fireworks, `accounts/fireworks/models/glm-5p3-flash`.
- Scenario: big_battle_6, seed 771125826, Northerners/Loyalists, 300 gold, side 0.
- Mode: focused/choices/incremental; max 50 engine side-turns; 1,000,000 game-token threshold; 131072 output cap with maintained 524288 escalation; default reasoning/sampling.
- Timeouts: model 7200 seconds, turn 14400 seconds; other query/call/partial limits stayed at defaults.
- Recorded duration: 100.05 minutes; provider request elapsed time summed to 97.50 minutes.

Exit **3**, `budget_interrupted`, code `max_game_total_tokens_exhausted`, winner
**unknown/not decided**. Eight model turns ended. Turn 9 remained open at revision
345 with two paid calls and no committed actions. R24 proposed an action envelope;
its preview ran, but R25's review was blocked locally before provider dispatch.
The final call overshot the threshold because the budget is checked between calls.
No output-limit exhaustion or provider retry occurred.

| Final live state | GLM side | Greedy side |
|---|---:|---:|
| Units | 17 | 17 |
| HP / maximum HP | 533 / 642 | 526 / 568 |
| Surviving material cost | 239 | 255 |
| Gold | 12 | 4 |
| Villages | 3 | 2 |

One village remained neutral. GLM's side killed seven Bowmen: four through its
delegated sweep and three through explicit model attacks. It lost ten units,
all during opponent responses. R24's proposed attacks and simulated losses are
excluded from these totals.

## Usage and comparison

| Measured provider usage | Tokens |
|---|---:|
| Input | 404,158 |
| Cached input, included in input | 206,848 |
| Output | 649,120 |
| Reasoning, included in output | 635,491 |
| Total input + output | 1,053,278 |
| Cache-write input | Unknown for every call |

All 24 paid calls returned usage and final receipts. Output was 97.90% reasoning;
51.18% of input was reported cached. Median response time was 210.828 seconds;
the longest was R21 at 506.965 seconds. Do not add reasoning to output again.

Estimated provider cost: **$0.360362**, using $0.15/M uncached input, $0.03/M
cached input, and $0.50/M output, checked 2026-09-11 against the
[Fireworks model page](https://fireworks.ai/models/fireworks/glm-5p3-flash).
The arithmetic is `(404158-206848)*0.15/M + 206848*0.03/M + 649120*0.50/M`.
This is a rate-based estimate, not an invoice, and excludes coding/operator host
usage, which was not reconciled into this game's provider cost.

| Model turn | Paid calls | Input | Output | Reasoning | Total |
|---|---:|---:|---:|---:|---:|
| 1 | 4 | 45,052 | 96,952 | 94,299 | 142,004 |
| 2 | 3 | 45,243 | 83,665 | 81,637 | 128,908 |
| 3 | 2 | 31,072 | 35,755 | 34,539 | 66,827 |
| 4 | 2 | 33,470 | 31,745 | 30,819 | 65,215 |
| 5 | 3 | 52,640 | 79,474 | 78,280 | 132,114 |
| 6 | 3 | 66,648 | 84,107 | 83,277 | 150,755 |
| 7 | 3 | 55,330 | 68,112 | 66,012 | 123,442 |
| 8 | 2 | 35,881 | 93,950 | 91,798 | 129,831 |
| 9, open | 2 | 38,822 | 75,360 | 74,830 | 114,182 |

The per-call ledger also contains cache, prompt/inspection sizes, output limits,
latency, and provider/request identities. The blocked logical R25 is not a paid
call or a fabricated zero-token receipt.

| Comparison | Previous diagnostic | This diagnostic |
|---|---:|---:|
| Paid calls | 24 | 24 |
| Total tokens | 1,035,873 | 1,053,278 |
| Estimated cost | $0.352473 | $0.360362 |
| Completed model turns | 8 | 8 |
| First move, cumulative tokens | 51,837 | 54,218, R2 |
| First attack, cumulative tokens | 549,329, turn 5 | 685,823, turn 6/R17 |
| First enemy kill, cumulative tokens | 731,025 | 685,823, delegated R17 |
| Final units, GLM / opponent | 16 / 21 | 17 / 17 |
| Enemy kills / friendly losses | 3 / 10 | 7 / 10 |

First village ownership changed at R4's end-turn boundary, after 142,004 tokens;
R2 moved onto the village. Do not label recruitment in R1 as movement or capture.
The newer opening used four calls versus six and fewer total tokens, but more
reasoning/output tokens. Smaller prompts alone did not solve excessive reasoning.

## What the model did with the harness

**Useful and expected:** multi-wave recruitment respected occupied castle hexes
and accepted-batch observation. R12 compared two complete attack candidates with
an explicit preview, then R13/R14 chose a defensive alternative. R17 correctly
recognized its full Greedy sweep and evaluated the sampled exchange. R18 made
an accepted partial attack batch, then R19/R20 finished a wounded target using
stationary Engage. R22 eventually corrected its mistaken belief about retaliation.

**Unsupported mistakes despite available facts:** R5/R6 ignored a supplied legal
castle-exit list. R8 recognized that a 13-gold Whelp was affordable with 13 gold,
then saved until the next turn to buy that same unit; R9 retained that choice.
R21 called melee attacks riskless despite the explicit Bowman short-sword profile
and nonzero retaliation forecasts. It also declared the wounded Grunt unable to
escape while leaving a relevant inspection unused. Its rejected proposal did not
execute; R22's repair left the Grunt as bait, and it died in the opponent response.

**Understandable friction:** packed formations, unequal movement costs, zones of
control, retreat risk, and enemy responses require care. However, GLM repeatedly
reopened settled decisions and reverse-engineered facts instead of querying them.
R15 spent 396.605 seconds and 58,409 tokens to output only
`inspect_units [4,5,9]`; R23 spent another 51,560 tokens to request three units.
These observations are not precise token attribution to individual thoughts.

**Missing harness context or behavior:** the following reproductions explain
part of that friction and suggest focused follow-ups. They do not excuse errors
where the correct facts were supplied.

## Remaining fixes and experiments

### 1. Complete effective per-terrain type profiles

R5/R6 at revision 85 proposed Naga U22 moves to `(7,5)` and `(5,5)`. Exact engine
pathfinding on a copied checkpoint gives costs 10 and 8, exceeding its 7 movement
points. R7 selected `(5,4)`, cost 6, and succeeded. The engine was correct.
The delivered prompts contained the legal exit list but no numeric terrain
movement costs; generic terrain costs existed only in raw driver state. Expose
effective per-type costs, including engine fallbacks, in the canonical profile.

Include effective defense in that same profile. R21 repeatedly tried to infer
Naga defense from forecasts, oscillating between 80% and 60%. The definition gives
swamp 60%, hills 40%, forest 40%, flat 30%; these values were absent from TYPE.
This requires no new planner, action, or engine rule.

A second copied-checkpoint probe at revision 314 found 14 legal destinations for
2-HP Grunt U11. `(6,11)` and `(3,9)` were not among them; R21's `(6,11)` failed
at authored index 2 before submission. Four legal destinations had zero direct
attackers on that board: `(4,4)`, `(3,5)`, `(4,5)`, `(3,6)`. These are not safety
guarantees: `(3,6)` still had a conservative open bound of four attackers/84 HP,
and subsequent actions can change blockers. They nevertheless contradict the
model's claim that every retreat was hopeless. Foreground the failed unit's
actual legal options in repair instead of forcing another geometry reconstruction.

Reproductions: `movement-cost-audit.md/json` and `retreat-destination-audit.md/json`
under `tmp/glm-decision-exec/`.

### 2. Preserve purpose and next-phase facts across inspection

R15 developed an attack/retreat purpose, then could send only bare unit IDs.
Adding `intent` to that inspection is rejected by the validator. Focused follow-up
receives older durable intent/agenda and suppresses the raw tool exchange. Thus
R16 receives R14's stale revision-167 intent and a wolves task, not R15's fresh
purpose. R15 also chose not to inspect U7/U8 despite considering their attacks;
that is a separate model-side scope choice. R16 still authored a Naga attack,
so the evidence does not prove the missing purpose caused a no-attacks outcome.

Add one bounded, validated provisional operation-purpose field to inspections,
carry it through local follow-up, and keep it distinct from committed memory.
Do not copy raw reasoning or add another planner. Check the local-to-whole-turn
boundary as well: R16 expanded a three-unit inspection into army-wide planning.
A whole-turn review should have the facts needed for that scope.

R23 explicitly supplied next opponent Day and next round Dusk. R24's local
projection retained only current Day and reused old intent calling turn 10 Night;
its reasoning guessed the future modifier. Retain those already-known next-phase
fields in local guardrails, with no new query.

Reproduction: `inspection-handoff-audit.md`; exact R23/R24 prompt comparison and
parent notes are retained in `tmp/glm-decision-exec/parent-observations.ndjson`.

### 3. Allow a bounded inspection path from review

R20 explicitly identified `inspect_target` as a way to resolve an alternative
attack, then noted that the final instruction forbids inspections. The client
deliberately calls `complete_model(review_prompt, allow_tools=False)` and accepts
only actions there. It retained a draft with predicted casualties. This is a
bounded-review design limitation, not an engine error; an inspection is not proven
to have prevented the actual losses.

Route an information-seeking review back through the existing inspection/correction
flow, retaining draft purpose and consuming existing call/query limits. Do not
allow a new recursive review cycle or silently raise budgets.

### 4. Carry the known revision into nested preview labels

R12's query envelope knew revision 167, but `query_bounded_comparison` discarded
that envelope field from its body. The preview header received 167 separately;
nested sampled-transition rows read the body and said `unknown`. Candidate
identity/results remained intact. Carry the known revision consistently and add
coverage for the real envelope-to-renderer path. This small presentation defect
escaped the implementation fixtures; it is not a reachability or simulation bug.

R14's review draft is candidate 1 (`901 -> 853 HP`, gold `0 -> 6`); baseline is
candidate 0 (`826 -> 736 HP`, gold `12 -> 18`). Explicit-preview C0/C1 are instead
user-proposed candidates. Reproduction: `preview-revision-audit.md`.

### 5. Test an explicit reasoning-effort setting before more tactics prose

The [official GLM model card](https://huggingface.co/zai-org/GLM-5.3-Flash) documents
low/high/max effort and a native default of max when omitted. The
[vLLM recipe](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash) describes the same modes.
Our Fireworks adapter sent no effort field; its actual runtime effort was not
reported. Therefore this is a hypothesis about excessive reasoning, not proof
that Fireworks ran at max. [Fireworks reasoning documentation](https://docs.fireworks.ai/guides/reasoning)
provides the provider control surface.

Add explicit supported effort pass-through and payload/runtime provenance, then
compare low/high on fixed positions with the current budgets. Do not credit prompt
changes for provider-default behavior or claim a model-wide result from this run.

These are targeted contract and context changes. The evidence does not call for
another planner or an engine rewrite.

## Evidence coverage and replay

The game is imported into the normal `.norrust_history/history.sqlite` catalog,
with a 21-frame replay at `tmp/quick-play-glm-decision-k41byol0/replay.json`.
The archive's separate `history.sqlite` has 393 events, 25 logical requests,
24 physical calls, 12 batches, 77 actions, and nine model side-turn rows.

Integrity, foreign keys, request/action/batch/turn links, and idempotent reimport
passed, including identical logical SQL dumps. All five raw reviews normalized:
three with handoff records and two explicitly marked identity-only/no-handoff-record.
No supported review is missing. `aggregate_only_request_ids=[]`, `unassigned_calls=0`.

All 24 dispatch/final sidecars, provider receipts, contexts, and exact canonical
prompt/payload hashes reconcile. Generic request coverage flags R25's absent
sidecar/evidence; its explicit local budget block explains that absence. It is not
a missing paid receipt. Cache-write tokens and runtime reasoning effort remain
unknown. The source and driver stayed unchanged through final import, and all
883 protected historical files remained byte-identical.

Raw SSE, completed responses/reasoning, request journals, checkpoints, usage
exports, per-call ledger, observations, and handoffs are in the archive. Parent
notes and offline reproductions are under `tmp/glm-decision-exec/`. Observer
misattributions were corrected against request IDs and candidate labels before
this report; the report's milestones come from the actual event/request evidence.

The live run exercised two local inspections, one explicit preview with selective
finishers, five automatic reviews, and three pre-submit rejections repaired across
R6/R7/R22. Other finisher forms, engine-repair edge cases, and several context
lifecycle branches are covered by tests rather than demonstrated by this game.
No claim is made that all new paths were exercised by the paid run.
