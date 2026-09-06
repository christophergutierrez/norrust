# Player contract recovery: three Luna games

The cohort produced **one recruiter-kill win and two resignation losses**.
All three attempts completed normally; none was restarted or substituted.

| Seed | Result | Model turns | Calls | Client wall time | Valid submitted annotations | Attacks: authored / delegated / opponent |
|---|---|---:|---:|---:|---:|---:|
| 2001 | Loss — resigned | 11 | 32 | 23m 39s | 12/12 | 10 / 17 / 131 |
| 2002 | Loss — resigned | 10 | 38 | 22m 37s | 11/11 | 12 / 0 / 101 |
| 2003 | Win — enemy recruiter killed | 10 | 23 | 14m 37s | 10/10 | 8 / 69 / 49 |

Model turns exclude resignation requests; the winning attack can finish a game
before an EndTurn event. Completed side-turn counts were 22, 20, and 19.
Calls include inspection responses, drafts, reviews, and repairs. Wall time is
from each client's terminal record. Annotation coverage measures recorded
explanations, not tactical quality or access to private reasoning.

## Implementation and validation

Plan: [player-contract-recovery.md](../plans/player-contract-recovery.md),
committed as `d4ddfee`. Three Luna/medium coding agents worked on the prompt,
agenda/integration checks, and documentation. Parent review corrected selective
finish semantics, maximum versus expected damage units, a missing forecast-vector
legend, and tests that checked proposed actions instead of actual execution.

Reviewed implementation and game source:
`c6486e86d4c66c714f947c04757d2f866a6de41b`. Changes:

- An exact, parseable actions/decisions/agenda example and strict agenda object
  shape; malformed optional metadata remains nonfatal.
- Only the response actually submitted can stage an agenda. An omitted or
  invalid replacement preserves committed tasks; discarded drafts and generated
  fallback orders cannot publish new tasks. Holds remain scoped to a turn.
- Explicit RecruitBatch auto-vacating beyond initial castle spaces, including
  its movement and positional cost.
- Compact forecast labels and legends distinguish tenths of HP, basis points,
  and whole-HP maximum damage. Numeric engine payloads are unchanged.
- Executable selective holds and delegation are distinguished from bookkeeping
  and ordinary automatic finishes. The guide includes a final hold self-check.

`python3 -m tools.fast_check` passed **234 Rust tests, 182 Python tests, LuaJIT
bridge smoke, and git diff --check**. Log: `tmp/player-contract-fast-check.log`.
Real-driver regressions verify twelve recruits from six initial spaces, six
vacates, the exact gold deduction and resulting unit roster, unchanged live
queries after repeated validation, and held/omitted positions versus delegated
movement. Client integration checks parse the next turn's actual BOARD block,
verify exact SQLite payloads and links, and compare malformed-metadata call
counts with valid runs.

After all games finished, parent review corrected the test's replay of move
coordinates to read the event's `col`/`row` fields. Commit `24d4c11` changes only
that test assertion path; all three player-contract integration tests and
`git diff --check` passed again. Gameplay code and prompts were unchanged during
the cohort. Focused log: `tmp/player-contract-final-test-review.log`.

## Conditions and evidence

All games used `big_battle_6`, Undead versus Undead, 300 gold, model side 0,
single-batch turns, resignation enabled, and a 50-completed-side-turn cap.
Three parallel Luna supervisors ran native `tools.codex_backend` players,
requesting `gpt-5.6-luna` at high effort. Native runtime model/effort are not
confirmed by the available events; requested configuration is archived separately.
The release driver was built from the clean reviewed commit before launch.

Archive: `tmp/player-contract-recovery-20260906T195814Z/`. Each `seed-N/`
contains its own launch/exit records, NDJSON log, checkpoint directory, native
session sidecar, request journal, prompt/result artifacts, and stdout/stderr.
`cohort.json` records source, driver and guide hashes. Raw evidence remains ignored
by Git and must be preserved separately from this report.

The final `history.sqlite` was imported after completion and inspected before
individual archives. It contains 3 games, 31 model turns, 93 requests, 33 authored
batches, and 113 authored actions. `evidence-audit.json` records the cross-checks:

- All 93 exact prompt/response pairs match the native artifacts, and every prompt
  includes the complete committed guide. Input/output usage fields are present
  for all requests; they are not evidence of confirmed runtime settings.
- All 33 submitted annotations are valid and match their exact response,
  revision, and action indices. There are 67 valid annotated responses including
  discarded drafts, plus 26 tool responses marked not applicable.
- No failed model requests, rejected submitted batches, timeout finishes, or
  accounting mismatches. Model response repairs did occur and are included in calls.
- Two repeated imports preserved request, batch, action, and turn records.
  SQLite integrity is `ok`, with zero foreign-key errors.
- All 31 model-turn start state blobs are present; exact post-model endpoint
  blobs remain absent. Event evidence and subsequent boards support the analysis;
  missing boundaries and private reasoning are not invented.

`live-history.sqlite` was used for progress inspection only. Its incremental
import leaves terminal wall time NULL when a game was first imported unfinished;
use the final `history.sqlite` and terminal records for these results.

## What changed in play

### Agenda shape and numerical units improved

Seed 2003 supplied 20 object-shaped agendas across drafts and final responses;
all ten submitted agendas were accepted. It maintained tasks from building the
army through attacking the enemy recruiter. Seeds 2001 and 2002 supplied no
agendas, using intent text instead. Thus the contract worked when exercised,
but these games do not demonstrate universal agenda adoption.

Exact numerical examples now agree with the supplied card:

- Seed 2001, batch 5 / request 14: U14 versus U27 displayed
  `p[5000,5000,0] e[120,0]`. The explanation said **50% kill, 12 expected damage**.
- Seed 2002, batch 7 / request 24: U5/U34 attacks displayed `e[105,0]`, and U35
  displayed `e[84,0]`. The explanations correctly used **10.5 and 8.4 HP**.

This is direct evidence of correct interpretation on these decisions. It does
not establish that all numerical reasoning was correct.

### Recruitment capacity was used, but the six-unit stopping rule persisted

Seed 2001 recruited 21 units in its opening, spending all 300 gold. At the next
board it had 22 total units versus 20, with 2 gold after income. Seed 2002 still
opened with six recruits and retained 210 gold, then recruited thirteen on turn
two. Seed 2003 proposed eleven opening recruits but revised to six; it also
retained 210 gold. The macro explanation enabled larger batches in two games,
without consistently changing the opening completion decision.

### Holds executed correctly; widespread holding still lost the fights

Seed 2001 issued 74 explicit held-unit references across ten selective finishes;
seed 2002 issued 109 across nine. The raw event audit found **zero delegated
moves of explicitly held units**. Authored retreat moves before a hold are
consistent with that hold taking effect at the finish.

The defensive choices still surrendered too much activity. Seed 2001 made only
27 authored/delegated attacks against 131 opponent attacks, losing 21 units
versus six. At resignation (request 32), its recruiter had 4 HP and its remaining
four units totaled 51 HP against twenty enemy units / 392 HP.

Seed 2002 made twelve attacks against 101 and lost fourteen units versus one.
At turn five it had 21 units / 639 HP against 21 / 588 HP; by the final observed
board it had nine / 172 HP against 23 / 569 HP. Holding, retreating, and village
work did not convert that earlier advantage into effective attacks.

### The win came from sustained attacking activity and delegation

Seed 2003 recruited fourteen Skeletons and six Skeleton Archers over four turns.
It combined eight authored attacks with 69 delegated attacks, losing four units
while eliminating 25 enemies. All ten turns finished with DoneWithImportantMoves.
Its recruiter remained at full health on the home keep throughout the battle,
while the main army closed on the opposing keep.

At batch 10 / request 23, the model ordered U38 to attack the last enemy corpse
and delegated the remaining force. Delegated units U31 and U33 damaged recruiter
U2; U35 delivered the kill. Of 25 enemy kills, four were authored attacks and
21 were delegated. This is a successful composition-and-handoff run, not evidence
that Luna selected every winning combat move itself. It won without capturing
villages, so village control was not required for this particular conversion.

## Remaining explanation failures

The most consequential new finding is confusion between hypothetical review
results and current state:

- Seed 2003's opening request 3 / batch 1 refers to bats U12/U13 and an enemy
  adept mass from the discarded eleven-recruit preview. The actual revision-0
  board still contained only the two recruiters. Its six-Skeleton replacement
  created U3–U8 and no bats. Calling the remaining gold a limited reserve was
  also inconsistent with the 210 gold left by that replacement.
- Seed 2002's resignation at request 38 cites an enemy force of 536 HP and a
  remaining three-unit force. The live board had nine friendly units / 172 HP
  against 23 / 569 HP. The sampled POST_OPPONENT result had four friendly units
  including the recruiter and 23 enemies / **536 HP**. The explanation appears
  to use that sampled future as present evidence. The live position was badly
  behind, but one candidate's sampled continuation does not prove no recovery
  route exists.

Seed 2003 also called Skeletons arcane-resistant. The engine's resistance values
are signed incoming-damage modifiers: `arcane:+40` means vulnerability and
`cold:-60` means resistance. The compact TYPE line omits the source field's
explicit sign convention. This is another concrete interface ambiguity to address
before interpreting every wrong tactical statement as an independent reasoning
failure. Overbroad tactic citations persisted too, such as T3.2 (save the
recruiter) on ordinary-unit retreats.

## Comparison limits

The prior annotated cohort at `7eb6c4e` lost all three games by resignation.
The same-seed results here are better, but three stochastic games and several
simultaneous contract clarifications cannot establish causality or reliable
playing strength. Calls rose from 84 to 93 overall; the experiment does not
establish a cycle-saving improvement.

The strongest conclusions are narrower: agendas can now survive the full
contract, sampled explanations show correct damage scales, explicit holds are
executed, and excessive holding can still lose badly. The next investigation
should make live state versus sampled futures unmistakable and spell out
resistance signs, while preserving these regression and evidence checks.
