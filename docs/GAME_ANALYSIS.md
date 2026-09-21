# Optional game analysis

Analysis capture is opt-in. Ordinary games do not create an analysis sidecar,
make extra driver queries, or make extra provider calls.

## Capture one game

Add `--analysis-capture` to the normal `tools.llm_client` invocation:

```bash
python3 -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --seed 42 --max-turns 6 --orders-file ORDERS.jsonl \
  --log /absolute/run/match.ndjson --analysis-capture
```

This writes `/absolute/run/match.analysis/manifest.json` and
`analysis.ndjson`. The sidecar records durable decisions, candidate packets,
requests, repairs, validation, committed actions, turn boundaries, and
terminal status. It references existing artifacts by hash; it does not copy
credentials or the process environment.

Capture has a bounded byte budget. A full disk, serialization error, or byte
cap stops optional capture and lets the game continue. The final status makes
that gap visible. A missing final status means the process ended before the
sidecar closed.

## Validate and report

```bash
python3 -m tools.game_analysis validate --archive /absolute/run/match.ndjson
python3 -m tools.game_analysis report --archive /absolute/run/match.ndjson
python3 -m tools.game_analysis report --archive /absolute/run/match.ndjson \
  --improvement --json > /absolute/run/improvement.json
```

`report` is read-only. The improvement report classifies evidence gaps,
candidate coverage, selection, and execution separately. Unknown or
conflicting evidence is never treated as zero, legal, safe, or a strategic
failure.

If a bounded evaluation artifact has already been produced from a validated
capsule, attach it without running anything:

```bash
python3 -m tools.game_analysis report --archive /absolute/run/match.ndjson \
  --improvement --evaluation /absolute/run/evaluation.json
```

The resulting phrase “best among tested candidates under this evaluator” is a
short-horizon sampled comparison. It is not an optimal-move or full-game win
claim.

## Provider-free three-way experiment preparation

Prepare and validate a schedule without contacting a provider:

```bash
python3 -m tools.controlled_experiment manifest --out tmp/analysis-manifest.json
python3 -m tools.controlled_experiment report \
  --manifest tmp/analysis-manifest.json
```

The schedule contains `current_player`, `search_only`, and `llm_search` cells.
The latter two share candidate generation, bounded evaluation, continuation,
and fallback settings. Search-only has no model request. The model-assisted arm
may select only a candidate ID from the evaluated set; invalid IDs are
recorded and use the declared fallback. The prepared manifest explicitly
disables provider contact. A later paid run requires a separate manifest with
explicit model, dollar, token, call, and wall-time limits and the normal
usage-accounting procedure.

## Evidence and interpretation

The archive and capsule contracts distinguish `observed`, `derived`,
`sampled`, `missing`, `conflicting`, and `not_applicable`. A started turn is
not a completed turn. A terminal event while a turn is open is a terminal
partial turn. Manual continuations retain their parent/checkpoint lineage and
are not silently counted as uninterrupted benchmark games.

Keep whole trajectories and their counterfactual branches in one evaluation
split. A sampled alternative is useful for prioritizing investigation, but
short horizons, one-opponent-response rollouts, censored samples, and finite
candidate sets limit what it can establish.

For recorded-game analysis, inspect the SQLite catalog and coverage before
opening individual archives. Missing usage, prompt, reasoning, boundary, and
lineage evidence remains unknown.
