# GLM decision efficiency — implementation and evaluation evidence

Stacks 1–5 are implemented and tested. The evaluation apparatus and concrete
48-cell launch packet are validated offline. **No paid model cell was launched.**
GLM strength, token savings, cost, qualitative reasoning review, and the promotion
criteria remain unmeasured. See the [acceptance plan](../plans/glm-decision-efficiency.md)
and [local handoff](../../tmp/glm-efficiency-exec/HANDOFF.md).

## Integrated stacks

| Stack | Commit | Result and evidence |
| --- | --- | --- |
| 1 | `7a98156` | Shared response contract, parseable examples, accurate economy and imminent-opponent phase facts. |
| 2 | `29c5bb4` | Retain committed agenda and show rejected-metadata feedback. |
| 2 correction | `a77d05b` | Preserve request/revision identity and feedback delivery/expiry across checkpoint resume; real-driver resume tests and full gate (558 Python, Rust and Lua). |
| 3 | `c2e2118` | Routine-action stopping rule and clarified recruiter/hold guidance. Guide is 5,024 bytes against 4,571 original (109.91%, within 110%). |
| 4 | `0842767` | `inspect_units` for 1–8 living friendly units; full gate (580 Python, Rust and Lua). |
| 5 | `30d56d0` | Nonfinal `MoveGroupToward`, rollback and delegated provenance; combined gate (583 Python, Rust and Lua). |

Three Luna High workers used isolated worktrees for inspections, movement, and
evaluation. The parent integrated shared files and corrected agenda resume and
reporting issues found during review. The interrupted tree was preserved under
`tmp/glm-efficiency-exec/resume/` before integration.

Group inspection prevalidates the entire live roster, pins every query and choice
handle to one revision, and works in both normal and repair responses. An invalid
member yields no partial result. Eight units cost one model tool allowance and
eight underlying driver queries; actual query time remains charged. A regression
covers exhaustion during fan-out. The old player-facing singular tool is removed;
the driver's singular query remains an internal implementation primitive.

Group movement processes listed IDs in order, returns moved/skipped facts, and
leaves the turn open. It never recruits, attacks, promotes, sweeps, or runs the
opponent. The real-driver fixture exercises recruit → group move/skip → recruit
→ group move → explicit finish in coordinate and choices-fallback modes. It
verifies rollback, annotations, authored macro indices, delegated engine events,
request linkage, replayable SQLite import, and idempotent reimport. Geometric
progress does not guarantee tactical safety or routing around obstacles.

The combined static prompt was shortened without increasing the 16,500-byte
cap; the largest minimal fixture is 16,485 bytes. The cache fixture retains its
stored cases and historical common-prefix ratchet; expected contract bytes were
regenerated for stacks 1+4+5. Cached input may still be billed.

## Offline checks

`python3 -m tools.fast_check` is the common gate. It includes Rust library,
binary and protocol suites; Python discovery with the real 24-cell scripted
matrix; SQLite import/report tests; and Lua bridge/replay/recorded-game tests.
The final integrated result is 609 Python tests passed, plus all Rust and Lua checks.
Logs: `tmp/glm-efficiency-exec/resume/agenda-full-gate.log`,
`stack4-full-gate.log`, `stack45-full-gate.log`, and `final-full-gate.log`.
Interactive GUI acceptance and long tournaments are outside this headless gate;
these stacks do not change GUI code.

The evaluator's scripted two-trial runner test imports real driver archives into
SQLite and reads physical `model_calls` through the maintained accounting tools.
Its temporary catalog is removed by the test. A separately retained two-cell
scripted run is recorded at
`/mnt/storage/git_home/norrust-glm-evaluation/tmp/glm-eval-offline-e2e/evidence.json`,
with its `runs/catalog.sqlite` and game IDs
`offline-glm-eval-preserved:opening_deployment-p1-t1` and `...-t2`. Scripted usage
is fixture evidence, not a GLM measurement. The packet and recorder payload
checks are retained under the launch directory below.

## Frozen launch packet — unrun

The local packet is `tmp/glm-efficiency-exec/launch/packet.stack5-ready.json`.
It names all 24 position/treatment cohorts and 48 trial cells, with raw manifests,
resolved manifests, exact dry-run commands, worktree paths, and source/driver/
guide/checkpoint/transport fingerprints. Each manifest is resolved by a subprocess
running the intended treatment checkout's own runner.

| Treatment | Frozen source | Checkout |
| --- | --- | --- |
| `stack2_contract_memory` | `2d07fc4ac863fbb086ee7eddc8c4cada54aa8524` | `/mnt/storage/git_home/norrust-glm-eval-stack2` |
| `stack3_stopping_rule` | `a77d05be78c79732fac0c2190e626f23573f7e94` | `/mnt/storage/git_home/norrust-glm-eval-stack3` |
| `stack5_batched_movement` | `30d56d01e0444c8aa86341beeb22f2c5fadd2054` | `/mnt/storage/git_home/norrust-glm-eval-stack5` |

All treatments include the same agenda lifecycle correction. Stack 2 and 3 have
identical engine source and different guides. Separately built debug binaries
have different hashes, which are recorded. Stack 5 intentionally changes engine,
inspection, and prompt contracts. Checkpoints, backend command/environment,
model, omitted effort/sampling settings, and per-position budgets remain matched.
The three treatments are separate cohorts; no runner fingerprint checks are disabled.

Each cell uses focused/choices with incremental turns, the canonical task matrix's
scenario/seed/factions/side-turn limit and predicate, 250,000 cumulative tokens,
1,800 seconds per side turn, and 64 partial batches. The default provider output
escalation remains unchanged. An in-flight call can overshoot cumulative tokens;
12 million is the nominal 48-cell allocation, **not a hard spend ceiling**. The
launcher must stop launching after 12 million recorded tokens across cohorts and
retain remaining cells as unrun. Use the runner's `--only-cell` option to inspect
usage between launches; do not automatically retry the whole pilot.

The passive recorder uses one absolute backend command across treatments and
imports the maintained adapter from the current treatment checkout. Every cell
gets its own raw prompt/request/response/receipt directory. The offline check
verifies unchanged canonical prompt, adapter payload and response, request ID,
and receipt isolation without saving auth headers. The historical dated
`pricing.json` must be reverified before a paid launch; it is not an invoice.

## Evaluation contract and remaining work

`tools/glm_eval_manifest.py` loads the canonical eight positions, predicates and
useful-action specifications from `tools/fixtures/task_harness/matrix.json`.
A useful action requires a committed driver event matching an authored order
and the declared predicate. Proposals and greedy-generated events do not count
as individually authored actions. Physical calls, retries, token fields and cost
come from imported SQLite through `bakeoff_metrics`; missing coverage is unknown.
Model inspection calls and driver inspection queries are separate metrics.

Cross-treatment analysis preserves all 16 scheduled trial keys, including missing
archives, and blocks promotion on missing, duplicate, unexpected or mismatched
records/fingerprints. It checks task success, new recruiter losses in defense,
invalid batches and premature finishes. Efficiency requires at least eight paired
successful trials with complete reasoning coverage and a 25% median reduction.
An incomplete pilot cannot claim improvement.

Remaining paid work is the plan's milestone 6: compare stack 2→3, then stack 3→5;
review the first three completed calls and every invalid/length-limited call using
the user's four categories; report failed and successful task costs and coverage;
and, only after a passing pilot, run the conditional four full games. There are
no paid game IDs, provider usage totals, qualitative findings, or promotion
results for this experiment yet.
