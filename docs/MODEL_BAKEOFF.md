# Matched harness comparison

`tools.model_bakeoff` runs isolated cells, imports their evidence into the existing
SQLite catalog, and reports every scheduled trial. The supported task experiment
uses arm A (batch/coordinates, three partial batches), B (focused/coordinates),
and C (focused/choices). Batch remains the default. Offline tests verify execution
and accounting; they do not establish a model's playing strength.

The provider-free fixture matrix is `tools/fixtures/task_harness/matrix.json`:

```bash
python3 -m tools.model_bakeoff run tools/fixtures/task_harness/matrix.json \
  --run-dir /absolute/new/task-harness-run --cohort task-harness-offline
python3 -m tools.model_bakeoff report --run-dir /absolute/new/task-harness-run
```

This invokes a scripted fixture, not a paid model. Its usage counts are explicitly
synthetic test evidence. The fixture README describes the positions and actions.
For a live comparison, copy the manifest, replace `model` and `backend` with the
selected maintained backend, and choose the total time/token ceilings before
launch. Keep provider settings, opponent, faction, initial checkpoint/RNG,
macros, and tactics identical across a matched position's arms. Read the usage
accounting procedure in `LLM_CLIENT.md` for every player shape. A file/native
player still requires an explicitly bound host thread and usage collection;
the Python runner cannot create an LLM subagent itself.

Each cell owns its log, checkpoint directory, request context/journal, usage
sidecar, and optional host session. Existing game logs cannot be overwritten:
use a new run directory for another attempt. `--only-cell ID` supports independent
cell execution; reports retain unrun cells in their denominators. Checkpoint
branches require a model side-turn boundary and become new games with fresh
budgets. The original checkpoint is copied byte-for-byte, its digest is checked,
and only a prepared copy gets local board paths. Current source, driver, guide,
transport, checkpoint hashes, and resolved settings are recorded. Mismatched
comparisons are rejected before execution.

Use manifest `budgets` for limits, including `max_game_total_tokens` and
`max_partial_batches_per_turn`. The cumulative token ceiling reads physical call
lifecycle records in the existing usage sidecar before/after dispatch. It includes
failed and exhausted calls, survives an in-place restart, and permits at most one
in-flight direct API call to cross the ceiling. It does not promise a currency
ceiling or online enforcement for hosts whose usage arrives only after collection.
Unknown usage and unmatched requests leave enforcement explicitly unverified.
The existing per-reply limits and output-exhaustion escalation retain their scope.

The report separates first committed action, first useful action, and final task
success. A forwarded proposal is not proof of execution; a corresponding engine
event with the model source must exist. A Greedy sweep alone cannot satisfy a
model-authored useful-action predicate. Success predicates are conjunctions of
factual final-state requirements: named units alive/absent/at coordinates,
`units_within` (alive unit on any of several listed hexes), named
village ownership, recruiter survival, and completed side-turn count. Missing
facts remain unknown. An OR-of-outcomes movement task (safe stop or policy
change) is not a bakeoff conjunction: keep those facts in screening targets
and evaluate them from the catalog after import. Budget interruptions (`terminal_class: budget_interrupted`,
client exit 3), invalid model responses, infrastructure failures, caps, and
gameplay results are separate outcomes. Budget stops preserve no winner and are
never automatically resumed.

Token totals and their per-field coverage come from SQLite `model_calls`, never
from summing request aggregates with retry attempts. First-useful token metrics
also require physical call evidence. Input includes cached input where reported;
output can include reasoning. These overlapping categories are never added again.
Reports include aggregate-only requests and unassigned physical calls.

## Stack 4 strategy comparison

The prepared strategy pilot has exactly three cells: `strategy_fixed`,
`strategy_glm`, and `focused_glm`. The fixed cell runs the checked-in routine
policy without a model backend. The two GLM cells use the same scenario, seed,
factions, gold, side, engine-turn limit, backend/model, dated pricing, and
explicit budgets; only the named decision treatment differs. The maintained
field is `strategy_treatment`.

The checked-in pilot template remains `prepared_not_run`; this describes the
template, not whether any particular experiment ran. Store actual manifests,
results and findings under ignored `tmp/` and inspect their catalog records
when evaluating a run. The template permits at
most two paid cells, 200,000 player tokens per paid cell, six completed engine
side turns, three controlled player turns for the GLM treatments, a 900-second model-call
timeout, a 2,100-second controlled-turn timeout, a 2,700-second cell wall
deadline, and a $1 aggregate estimate. The recorded public rate evidence is
2026-09-13 Fireworks GLM-5.3 Flash: $0.15/M uncached input, $0.03/M cached
input, and $0.50/M output. Its conservative two-cell estimate is $0.8815744,
including one in-flight context bounded at 1,048,576 tokens. Rates must be
rechecked read-only before any launch; no paid call or observer is part of the
offline checks.

All three cells explicitly use matched client limits of 8 model responses, 64
tool calls, 256 queries, and 64 partial batches per side turn; mode defaults do
not silently widen a comparison arm.

The runner starts each cell through the existing recording-only
`tools.llm_supervisor` with zero restarts. It keeps a compact, durable
`supervisor_heartbeat.json` every five minutes and requests the existing owned
process-tree cleanup at the cell wall deadline. A stopped or incomplete cell
remains in the report with unknown coverage.

The executable provider-free matrix uses the real `greedy_driver` and fixed
routine policies:

```bash
python3 -m tools.strategy_comparison offline-run \
  --run-dir /absolute/new/strategy-matrix \
  --driver /absolute/path/to/norrust_core/target/debug/greedy_driver \
  --out /absolute/new/strategy-matrix-report.json
```

It covers quiet opening, multi-turn travel, blocked recruitment, and contact.
Quiet policies demonstrate different recruited deployments and gold spend;
travel repeats the same policy and seed and compares the canonical executed
event digest. Every source is imported twice into the existing SQLite catalog,
and the report records whether the second import was idempotent. Fixed-policy
rows have zero model calls and no fabricated token usage. A terminal marker by
itself does not make evidence complete: missing usage, boundary, replay, or
partial-failure coverage remains explicit as `unknown_*`.

### Strategy decision boundaries acceptance matrix

The 8-position decision acceptance matrix verifies tactical boundaries, custom action escapes, loop bounds, and resume idempotence through the real driver and fake transport:

```bash
python3 -m tools.strategy_comparison decision-matrix-run \
  --run-dir /absolute/new/strategy-decision-matrix \
  --driver /absolute/path/to/norrust_core/target/debug/greedy_driver \
  --out /absolute/new/strategy-decision-report.json
```

Or re-evaluate recorded decision archives without rerunning:

```bash
python3 -m tools.strategy_comparison decision-matrix-report \
  --run-dir /absolute/existing/strategy-decision-matrix \
  --out /absolute/existing/strategy-decision-matrix/report.json
```

A 16-cell bounded Fireworks screening schedule is prepared at `tools/fixtures/strategy_decisions/fireworks_screening_manifest.json` and can be inspected or dumped via:

```bash
python3 -m tools.strategy_comparison screening-manifest --out /tmp/screening.json
```

The architectural screening compares baseline `cb9a85b` with the accepted current
candidate, both built in release mode. The manifest is a schedule: freeze exact
source/driver hashes and prepare each cell through its source's maintained runner.
Use `tools.strategy_screening.score_cell` and `summarize` for treatment-neutral
board-effect scoring; custom actions and engine-option selections receive the
same credit. Pin withdrawal destinations with the engine's projected threat
query before launch. Selection alone does not prove reduced exposure. Keep failed
cells in token medians, reject duplicate/missing pairs, and never interpret a
prepared packet or fake transport as evidence of model quality.

After a recorded pilot, regenerate the strategy report from saved cell status
and the run-local catalog:

```bash
python3 -m tools.strategy_comparison pilot-report \
  --run-dir /absolute/existing/strategy-pilot \
  --out /absolute/existing/strategy-pilot/strategy-report.json
```

Without `--run-dir`, this command only prepares an unrun report. Missing cells
stay unrun in either report. Raw-archive usage coverage remains unknown for
model players; the report's catalog accounting provides measured physical-call
usage and per-field coverage. A proven fixed-policy run with no model requests
has no accountable inference. The offline-run command exits nonzero when its
acceptance predicates fail or lack evidence.

Cost needs explicit dated rates in each cell, for example:

```json
{"pricing":{"date":"YYYY-MM-DD","rates":{
  "input_per_million":2,"cached_input_per_million":1,
  "output_per_million":10,"reasoning_included_in_output":true
}}}
```

These numbers are illustrative, not a model's prices. There is no default price.
Missing rates or a missing discounted-cache split produce unknown cost. If
reasoning is billed separately, supply `reasoning_per_million` and set
`reasoning_included_in_output` false; missing reasoning then makes cost unknown.
Only fully covered task costs qualify for the pilot promotion gate. Price inputs
and the report are reproducible offline; no pricing lookup occurs during tests.

The three-arm report applies screening thresholds described in the implementation
plan. A passing pilot is a reason to conduct matched full games, not a general
model ranking or an automatic change to the default mode. All failed, unmeasured,
and censored trials remain visible alongside medians.
