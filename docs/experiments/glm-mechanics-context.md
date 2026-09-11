# Mechanics and focused-context corrections: execution record

Implementation in progress. The user authorized the
[plan](../plans/glm-mechanics-context.md), Luna High implementation, and one
fresh observed GLM 5.3 Flash game after completion. No new paid game has launched.

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

Stack 4 is pending integration. Gate logs and worker handoffs live under
`tmp/glm-mechanics-exec/`.

## Paid retest

Pending all code stacks and their commits. Preserve the previous scenario, seed,
factions, gold, model defaults and caps, using the maintained streaming adapter.
Corrected terrain data changes the game mechanics, so pre-fix runs will be
descriptive context, not a controlled prompt-only comparison.
