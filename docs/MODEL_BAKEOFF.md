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
factual final-state requirements: named units alive/absent/at coordinates, named
village ownership, recruiter survival, and completed side-turn count. Missing
facts remain unknown. Budget interruptions, invalid model responses,
infrastructure failures, caps, and gameplay results are separate outcomes.

Token totals and their per-field coverage come from SQLite `model_calls`, never
from summing request aggregates with retry attempts. First-useful token metrics
also require physical call evidence. Input includes cached input where reported;
output can include reasoning. These overlapping categories are never added again.
Reports include aggregate-only requests and unassigned physical calls.

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
