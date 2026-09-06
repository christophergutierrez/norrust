# Decision annotation experiment

All three games ended in model resignations. All **26 submitted batches** had
valid annotations, including the three resignations. The experiment produced
usable explanations of failures, but no evidence of improved playing strength.

| Seed | Result | Completed model turns | Model calls | Wall time | Annotation coverage | Main finding |
|---|---|---:|---:|---:|---:|---|
| 2001 | Loss — resigned | 6 | 17 | 7m 11s | 7/7 (100%) | Skipped retreat inspection despite available move counts; four named wounded units died. |
| 2002 | Loss — resigned | 10 | 43 | 21m 24s | 11/11 (100%) | Repeated retreats and holds produced only 6 attacks against Greedy's 102. |
| 2003 | Loss — resigned | 7 | 24 | 9m 54s | 8/8 (100%) | Stated holds were swept forward; an expected-damage claim was ten times the supplied forecast. |

Model calls include inspection responses, drafts, reviews, and resignation.
Resignation does not complete another model turn. These attempts ended at
12, 20, and 14 completed side-turns, well before the 50-side-turn cap. Thus
concession was used early, although these runs cannot measure the counterfactual
number of calls saved. All clients exited 0 with gameplay-valid losses, no failed
model requests, no rejected batches, and no generated timeout finishes.

## Implementation and conditions

The implementation is commit `7eb6c4ef9a83e029866ccc6127e7c6c97903954a`.
Three Luna agents at medium effort implemented the client, persistence/report,
and integration/documentation slices. Parent review corrected response attribution,
fallback handling, conflicting prompt instructions, parser edge cases, and test
gaps before committing the complete stack.

`python3 -m tools.fast_check` passed 234 Rust tests, 174 Python tests, the
LuaJIT bridge smoke, and `git diff --check`. The real-driver integration tests
verify executed movement, exact payloads, request/revision/action linkage,
idempotent import, approved rationale export, and legal play with missing or
invalid annotations. Validation log: `tmp/decision-annotations-fast-check.log`.

The three games use seeds 2001, 2002, and 2003, `big_battle_6`, Undead versus
Undead, 300 starting gold, model side 0, ordinary single-batch turns, and a cap
of 50 completed side-turns (at most 25 model turns). Three parallel Luna
subagents supervise native `tools.codex_backend` players requesting
`gpt-5.6-luna` at high effort. Runtime model/effort remain unconfirmed by the
native events; requested settings are not runtime evidence.

The working tree was clean at launch and the release driver was freshly built.
The cohort archive is `tmp/decision-annotations-20260906T190809Z/`, with a
`cohort.json` recording driver/guide hashes and one isolated `seed-N/` directory
per game. Each game owns its launch manifest, NDJSON log, checkpoints, session,
native request journal and prompt/result artifacts, stdout/stderr, and exit record.
Raw archives are ignored by Git and must be retained separately from this report.

## Interpretation limits

The annotations are short model self-reports: cited rule, expected effect, and
stated risk. A valid citation establishes neither tactical compliance nor the
model's private reasoning. Explanation coverage measures whether submitted
authored action batches have valid annotations. Inspection requests, discarded
drafts, and generated fallback orders do not enter that denominator.

The earlier cohort, `tmp/model-games-20260906T172306Z/`, used the same seeds and
main game settings at commit `1a5eaf08c7ab47f67ac00e07fa58c67df1516679`.
It produced one capped game and two losses. Its catalog has no rationale blobs
or prompt/response blobs, although native prompt/response artifacts exist.
The new cohort also has resignation enabled and changed annotation instructions;
three stochastic games cannot isolate a causal effect on strength or cost.

## Evidence coverage

`tmp/decision-annotations-20260906T190809Z/history.sqlite` contains 3 games,
23 completed model side-turns, 84 requests, 26 submitted batches, and 93 authored
actions. `evidence-audit.json` records the cross-check results.

- All 84 prompts and responses are stored, and match the corresponding native
  request/result archives exactly. Every prompt includes the complete guide.
- There are 49 valid annotated action responses, including discarded drafts,
  and 35 tool responses marked `not_applicable`. Only the 26 submitted responses
  enter the 100% coverage figure. No missing or invalid annotations were observed.
- Every submitted batch links to its exact request, raw actions, annotation,
  prompt hash, and state revision. Non-applicable requests have NULL rationale.
- Two repeated imports preserved counts and payloads. SQLite integrity is `ok`
  with zero foreign-key errors. All launch/exit records and isolated archives are
  present; no substitute runs were used.
- Runtime model/effort remain unknown. The catalog contains 23 model-turn start
  snapshots, but no exact post-model endpoint state blobs. Review therefore uses
  the recorded driver events and subsequent boards, and does not infer missing
  intermediate states or hidden reasoning.

## Decision evidence

Request numbers below are the `model_requests.sequence` values within each game;
batch numbers are `action_batches.sequence`. The catalog links them explicitly.

### Seed 2001: legality caution became a reason to skip inspection

At batch 6 / request 16 / revision 270, Luna cited T2/T6/T7 and declined retreats
for wounded U28, U34, U36, and U37 because “no legal destinations are supplied.”
The compact card supplied positive move counts of 1, 3, 8, and 15 respectively,
and labeled each unit `inspect=inspect_unit`. No inspection request was made that
turn. Detailed retreat coordinates were not in the base card, but there was a
supported way to request them. All four units were killed in the following
opponent turn. This demonstrates a failure to investigate available moves;
it does not establish that a safe retreat existed for every unit.

The same batch attempted U39's attack against U16, whose displayed kill
probability was 6400 basis points (64%). It dealt zero damage and took 24 in
retaliation. That sampled failure alone is not proof that the attack was bad.
The annotation correctly acknowledged the risk of the target surviving.

Luna also repeatedly cited formation rules while leaving much of the formation
to the greedy sweep. The game recorded 71 delegated moves and no village captures
by the delegated units. At resignation (request 17, revision 310), its stated
material facts matched the board: 5 units / 114 HP against 17 / 397 HP, 2 gold,
and no affordable recruit. The recruiter remained at 48 HP. This was a major
material/economic deficit, rather than immediate recruiter death.

### Seed 2002: deliberate defense gave up too much attacking activity

At turn 5 / revision 161, Luna had 21 units and 615 HP against 20 units and
512 HP. Batch 5 / request 20 retreated U28 and then explicitly held the remaining
force, citing T1/T4/T7. Its stated risk was that enemies could continue attacking
exposed units. Later annotations repeatedly declined attacks to avoid exposure,
duplicate targets, or insufficient individual kill probability.

By turn 9 / revision 299, that force had fallen to 13 units / 270 HP against
21 / 476 HP. Across the game Luna executed **6 attacks**, Greedy executed **102**,
and losses were 19 model units versus 2 enemy units. Eight of ten turns ended
with empty delegation groups and deliberate holds. This was explicitly chosen
defensive play, rather than unexplained inactivity. It failed to convert an
earlier material advantage into useful attacking activity; the record does not
prove every declined attack would have been good.

There were useful decisions: U7 captured the village at (6,11), U41 was sent to
(2,4), and the recruiter retreated from (2,7) to (0,10) when its keep was threatened.
At resignation (request 43, revision 381), the board had 5 units / 127 HP against
23 / 476 HP, only 6 gold, and eight direct potential attackers on the recruiter.
The threat summary allowed a lethal two-volley total; it did not guarantee an
actual kill. The stated decision to concede was grounded in that severe deficit.

### Seed 2003: stated holds were not encoded, and damage units were misread

At batch 2 / request 5 / revision 52, Luna said it would hold U1/U3/U4/U5/U6
to preserve a screen, citing T1/T4. Its actions ended with `DoneWithImportantMoves`
and contained no explicit holds. The engine recorded delegated moves for U3,
U4, U5, and U6 to (10,8), (8,7), (8,8), and (7,7). This is a direct mismatch
between the stated intention and the submitted command. An empty annotation
group records an omission; it does not issue a hold action.

That response also expected “about 48 cumulative damage” from two Ghost attacks
whose compact forecasts each showed `e[24, …]`. The source forecast field is
`expected_damage_tenths`, so their displayed expected damage sums to **4.8 HP**.
The compact prompt described `e` as damage without specifying tenths. The
annotation exposes an apparent factor-of-ten interpretation error and an actual
prompt ambiguity; this should not be blamed entirely on tactical reasoning.
The individual forecasts also showed zero kill probability against the 28-HP
target. See `tools/llm_client.py`'s compact inspection renderers and prompt legend.

There was evidence of useful execution too: later batches inspected and retreated
U3, U4, and U39 to named destinations. Their authored move events matched the
annotations. But U3 was swept forward again on the next turn after its retreat,
showing that maintaining a recovery plan across turns remained weak.
Some citations were overbroad: T3.2 concerns saving the recruiter, yet Luna cited
it for ordinary-unit retreats, and cited T3.1 (kill the enemy recruiter) for an
attack on ordinary Dark Adept U18. Valid IDs do not imply correct application.

At resignation (request 24, revision 343), Luna had 4 total units / 93 HP against
11 / 237 HP and 2 gold. Its explanation counted three non-recruiter combat units,
two critically wounded, and the opponent's village advantage.

## What this changes about the next investigation

The first priority is to make compact forecast units explicit: the observed
4.8-versus-48 error identifies a concrete presentation defect. Next, distinguish
written hold intentions from commands that actually hold units, and distinguish
missing detailed coordinates from an inability to inspect legal retreats.
Seed 2002 also provides evidence to investigate excessive individual risk
avoidance and missing coordinated attacks. These findings are stronger than
another speculative rewrite of the tactical guide, but they do not establish
an optimal replacement policy. The three games used the committed experiment
unchanged; no tactical or forecast-format changes were introduced mid-cohort.
