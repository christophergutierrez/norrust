# Strategy trial follow-up

Status: execution complete with Luna High workers. Stack 1 passed all gates;
Stack 2 completed all 16 cells and missed the efficiency target. The conditional
opening pair was therefore not launched. See the [acceptance record](../experiments/strategy-trial-followup-2026-09-14.md).
Implementation starting point: `ed6b765e24fb9e519751c8c8f723b59c1896cdd3`.

## Objective and scope

Fix action availability omitted from strategy briefs, misleading boundary
accounting, and live-launch documentation. Verify the expensive independent
movement path with actual archived progress, then execute the bounded paired
screening in `strategy-decision-boundaries.md`. Keep transactional rejection,
one player model, existing budgets, and source/usage provenance. No new battle
planner, partial-batch salvage, or paid observer.

## Stack 1: trustworthy brief, reporting and release launch

Three workers may run in isolated worktrees from the baseline:

1. Brief worker owns `routine_policy.py`, `llm_client.py`, relevant unit/real
   driver tests, and the strategy subsection of `docs/LLM_CLIENT.md`. Include
   authoritative `moved`, `attacked`, and `movement` in compact unit facts;
   preserve unknown values and explain that movement is the engine allowance,
   not a remaining-points counter. Keep current revision facts after routine
   moves. Make rejected action feedback identify action index, involved unit
   IDs/destination, and engine error while retaining original validation data.
   Do not infer five legal moves from a result that includes a finish.
2. Reporting worker owns `match_report.py`, reporting tests and relevant
   `docs/GAME_HISTORY.md` notes. Count actual controlled finish boundaries from
   their ownership and recorded provenance, including routine and ordinary
   model paths. Preserve detection of genuinely missing boundaries; unknown
   ownership stays unknown. Do not simply disable the mismatch check or change
   token accounting. Verify the existing trial-4 archive reports three controlled
   and three opponent end turns without this false alarm. Preserve archive bytes.
3. Release/benchmark worker owns `docs/FIREWORKS_RUNBOOK.md`, relevant development
   build notes, and a task-local read-only benchmark artifact. Use a fresh release
   driver explicitly in launch examples. Include dated existing pricing with
   honest estimate semantics, without printing credentials. Reconstruct trial 3's
   installed policy and committed progress at its turn-3 checkpoint using all
   installation/batch/revision proof fields. Measure exact-state routine queries
   with debug and release binaries and report state/progress/source hashes, query
   result, timings and no-mutation proof. No approximate empty-progress replay.

The integration owner controls shared-file resolution, evaluation tooling,
full gates, commits and final handoff. Do not edit another worker's files.

Offline audit additions to Stack 1 (before paid outcomes): the paired scorer
must accept useful custom actions equally with engine options. The original
withdrawal fixture had no lower-exposure destination; move its enemy farther
away while retaining a proved starting threat and update fixture hashes/tests.
Also correct tactical-option expected incoming damage: fixed focus-fire slots
for one/two/three attackers contain zero padding, so reading only the last slot
can falsely report zero for a real one-attacker threat. Use the greatest
supported expected focus damage with explicit semantics and regression coverage.

Acceptance:

- A real-driver mid-turn fixture has routine-moved and unmoved units. The next
  model brief identifies both correctly; attack availability is present too.
- Illegal batch feedback identifies the actual offending IDs and preserves
  atomic rejection; a corrected response executes once. Unknown facts are not
  converted to false/zero. Existing response recovery and choose tests pass.
- Routine/model/delegated/opponent finish fixtures report correct ownership.
  A deliberately missing controlled finish still raises a mismatch; interrupted
  and winner paths retain their documented semantics.
- Read-only trial-4 reanalysis agrees with the catalog's three completed player
  turns. No game archive is modified.
- Runbook manifest parses with the real resolver, uses the release binary,
  contains dated prices, and shell examples pass `bash -n` without paid calls.
- Exact trial-3 benchmark records release performance. If it exceeds the prior
  ten-second query target, report the failure and diagnose before paid launch;
  do not hide it with larger budgets or an approximate replay.
- Run `python3 -m tools.fast_check` with built real driver tests, update docs,
  and commit this complete stack before evaluation.

## Stack 2: validated paired screening, then honest findings

Audit the prepared screening packet before dispatch. Before this follow-up the
packet named `c80f408` as baseline, which would mostly compare implementation
against a later test/report commit. For the previously planned architectural
comparison use `cb9a85b` versus the accepted Stack-1 candidate, both built release.
Record this correction. Freeze exact source hashes, model, prompts, driver hashes,
four starting positions, two repetitions and predicates before paid calls.

Use the maintained runner, checkpoint preparation and catalog importer. Prove
each checkpoint starts the intended position and allows exactly one controlled
turn with fake transports. Check that baseline can consume the same starting
board and applicable policy. Missing APIs/fixtures or false predicates are setup
failures to fix offline, not reasons to spend on invalid comparisons. Add only
the small preparation/report integration needed; do not create a second runner.

Retain the previous plan's 16 cells, 75,000 soft tokens/cell, eight logical
calls/turn, 15-minute wall deadline/cell and 1.2-million aggregate soft-token
launch stop. Keep provider output/retry rules unchanged. Compute the actual
overshoot exposure from resolved limits and dated pricing before launching;
do not describe the soft sum as a hard spending cap. Launch serially and stop
new cells on aggregate budget exhaustion. Inspect compact completion/accounting
only between cells; review full logs once afterward. Only Fireworks credentials
are needed. Follow `docs/LLM_CLIENT.md` usage accounting for every run.

Acceptance uses the prior plan's fixed targets: no illegal/stale/duplicate
commits, bounded repeated incidents, at least six of eight candidate useful-action
successes and no fewer than baseline, candidate median total tokens <=75% of
baseline including failures, and no fixture-defined recruiter death/unsafe
automatic movement. Report incomplete or unavailable cells explicitly. A failed
screen stops the experiment; no rescue games or retuning. Only a passed complete
screen permits the already-planned pair of capped opening runs within scope.

Import all attempts into local and default catalogs, report cost with coverage,
preserve original evidence, and commit the experiment record including failures.
If external availability prevents dispatch, complete all offline work and leave
a concrete ready-to-run packet with the actual blocker; do not claim live success.

## Handoff and completion

Keep `tmp/strategy-trial-followup/HANDOFF.md` current with source/worker commits,
tests, benchmark and trial paths, budget totals, completion state, and next step.
Rebuild main's driver/library/dumper after integration. Final report names fixes,
test result, exact benchmark result, screening outcome, usage/cost, and remaining
limitations. The 50,000-reasoning opening heuristic is not the new paired screen.
