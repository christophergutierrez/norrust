# Matched model comparisons

`tools/model_bakeoff.py` runs a small, explicit experiment manifest as isolated
`tools.llm_client` matches, imports every completed match into one shared
`tools.game_history` catalog, and produces one reproducible comparison report.
It reuses `tools.llm_client`, `tools.match_report`, and `tools.game_history`;
it does not add a parallel database, a provider abstraction, or a second
report format.

## Manifest

A manifest is a JSON object with an `objective` string and an explicit `cells`
list. Each cell is a full match configuration:

```json
{
  "objective": "Compare configuration A and B on big_battle_6, both sides",
  "cells": [
    {
      "id": "config-a-side0",
      "configuration": "config-a",
      "scenario": "big_battle_6",
      "seed": 2001,
      "faction0": "undead", "faction1": "undead",
      "llm_side": 0, "gold": 300, "max_turns": 30,
      "model": "MODEL_ID", "reasoning_effort": "high",
      "backend": {"kind": "codex"},
      "budgets": {"turn_timeout": 930, "query_budget_seconds": 900}
    }
  ]
}
```

`seed` may be a concrete int or the literal string `"random"`. Random settings
are resolved exactly once, before any cell runs, by `resolve_manifest`; the
resolved value is written into `<run-dir>/manifest.json` and every later step
(including a `report`-only re-run) reads that frozen copy rather than
re-rolling anything.

`resolve_manifest` also stamps each cell's `provenance`: `source_commit`,
`dirty_patch_hash` (from `tools.llm_client.source_metadata`), `driver_hash`
(sha256 of the resolved `driver` executable), `guide_hash` (sha256 of the
exact `docs/LLM_TACTICAL_PLAYBOOK.md` text every prompt currently ships,
reusing `tools.decision_annotations.guide_hash`), and the requested model/
effort. After a real run, `aggregate_cell` additionally compares that
requested identity against whatever the backend actually reported
(`backend_requested_model`/`runtime_model` in match metadata), the same
requested-versus-reported distinction `tools.llm_client` already records.

### Backend kinds

- `"orders_file"` — a deterministic scripted responder (`{"path": "..."}"`).
  Used for the offline test suite; not a live model.
- `"command"` — an arbitrary `--model-command` (`{"command": "...", "env": {...}}`).
- `"codex"` — wires `tools.codex_backend` with a per-cell session sidecar,
  artifact directory, and match ID (`NORRUST_CODEX_*` env vars), matching the
  setup in [LLM_CLIENT.md](LLM_CLIENT.md).
- `"file"` — wires `tools.file_backend` against a per-cell `requests/`
  directory. **This only sets up the file transport.** Python cannot select a
  host subagent model by passing its name to the file backend, so for this
  backend kind the coordinator must separately start one persistent player
  per cell, using the host's own subagent API, pointed at that cell's exact
  `requests/` directory, before the run will proceed past its first
  `waiting_*` marker. There is no nested model CLI or unsupported SDK here —
  this handoff is a manual, documented step.

## Running

```bash
python3 -m tools.model_bakeoff run manifest.json --run-dir /path/to/run --cohort my-experiment
```

This resolves the manifest once (or reuses `<run-dir>/manifest.json` if
already resolved), then runs cells **sequentially by default**. Pass
`--only-cell ID` to run exactly one cell — that is how a coordinator runs
independent cells in parallel: one `model_bakeoff run --only-cell` invocation
per cell, all pointed at the same `--run-dir`.

Every cell gets its own subdirectory under `--run-dir` (`cell_dir_for`) with
its own `match.ndjson` log, `.ckpt` checkpoint directory (derived by
`tools.llm_client` from the log path), `identity.json` sidecar (the same
shape `tools.recorded_games` already reads to fill in a requested model
identity), `client_stderr.log`, and `run_status.json` (exit status). A cell
that already has a `run_status.json` is reported from that record rather than
silently re-run as an unrecorded fresh game — pass `--force` to deliberately
re-run it.

After running, `run` imports every cell that produced a log into
`<run-dir>/catalog.sqlite` under the given `--cohort`, using
`tools.game_history.import_game` with an explicit, reproducible
`game_id = "<cohort>:<cell id>"` (reimport is idempotent, same as the rest of
the catalog).

Re-aggregate without rerunning anything:

```bash
python3 -m tools.model_bakeoff report --run-dir /path/to/run
```

## Report

`report.json` lists **every scheduled cell**, whatever happened to it —
completed, failed, not run, or model-invalid — never only the ones that
finished cleanly. Each cell entry carries:

- `terminal_class`, `winner`, `reason` (from `tools.match_report.classify`);
  a draw (`winner: null` on a `gameplay` terminal class) is tallied
  separately from wins and is never counted as one.
- `match`: the full `tools.match_report.classify` object, including
  `decision_annotations` coverage and `publication_attempts` (S3's
  first-attempt/repaired/unresolved counts) when a `requests/validation_log.ndjson`
  is present next to the cell.
- `compute`: `model_calls`, `wall_ms`, `usage_measured` — reported separately
  from outcome, never folded into a win rate.
- `display_turns` (engine rounds) reported separately from
  `completed_side_turns`.
- `cap_remaining`: `max_turns` minus the engine round count, or `null` when
  that count is unknown.
- `villages_round5_side0`: village ownership at the state where the engine's
  `turn` field equals 5 and it is side 0's turn, before side 0 has acted —
  the one non-partial boundary that means "start of round 5". When no such
  boundary was logged (the game ended sooner, or only a partial/checkpoint
  snapshot exists at that point), this reports `unknown: true` rather than
  interpolating from a nearby state.
- `recruiter_status`: each side's live recruiter unit(s) — HP, position, and
  `alive` — from the terminal's embedded state or the last logged state.
- `resignation`: the recorded T8 rationale (rules/expected/risk) when the
  match ended in a resignation, or `null` otherwise.

`totals` and each `configurations[*]` bucket give explicit numerator/
denominator pairs: `win_rate` is wins over *gameplay* cells only (draws and
losses share that denominator; model-invalid and infrastructure-failed cells
do not shrink it), while `completion_rate` is completed cells over *every*
scheduled cell in that configuration, including ones that never ran. This is
deliberate: excluding a configuration's failures from its win-rate
denominator would make it look silently stronger than it played.

`comparison` states whether this manifest may be read as a matched model
test:

- `experiment_kind: "matched"` (the default) requires every cell's fixed
  settings (`scenario`, `gold`, `max_turns`) and provenance fingerprint
  (`guide_hash`, `driver_hash`, `source_commit`, `dirty_patch_hash`) to be
  identical. Any mismatch sets `valid: false` and lists the exact field and
  cells involved — the report never silently calls a mismatched setup
  "matched".
- `experiment_kind: "baseline_candidate"` with a `declared_change_field` (for
  example `"guide_hash"` for a prompt-wording experiment) permits exactly
  that one field to differ from the baseline cell; every other field must
  still match, or the comparison is refused the same way.

## Locking a baseline

```bash
python3 -m tools.model_bakeoff run manifest.json --run-dir /path/to/run --lock-baseline
```

writes `<run-dir>/baseline.json` (the resolved manifest's report, timestamped).
A locked baseline is never silently overwritten: a second `--lock-baseline`
against the same `--run-dir` raises unless the caller explicitly passes
`force=True` (there is no CLI flag for that — a deliberate re-lock is a
one-off script call, not a routine option). Earlier comparisons stay
historical observations; nothing here retroactively relabels them as "the"
baseline.

## Tests

```bash
python3 -m unittest tools.test_model_bakeoff
```

Every test is offline: manifest/aggregation fixtures use synthetic NDJSON
records, and the one real-driver integration test (skipped unless
`greedy_driver` is built, matching every other real-driver test in this
repository) runs four tiny cells through a deterministic `--orders-file`
responder, not a live model.

Running an actual paid-model pilot is a separate, explicitly cost-bearing
decision, never triggered by this module or its tests. A reasonable pilot is
four explicit seed/faction cases paired across both sides (eight cells per
configuration); record the selected models, total games, concurrency, and
resource caps before running it, and report per-cell results with the
denominators above rather than treating eight cells as proof of superiority.
