# Run and observe a Fireworks game

This is the operator recipe for Claude, Codex, or another coding agent. Read
[LLM_CLIENT.md](LLM_CLIENT.md) first; its usage-accounting procedure is
authoritative. The Fireworks model is the player. The coding agent launches,
collects, and reviews the run; it does not rewrite the player's canonical prompt
or think through every move. Only `FIREWORKS_API_KEY` is needed. Do not print it.

## Before launch

Use the user's requested model, mode, seed and limits. Existing authorization
carries forward; do not ask again merely because an old fixture says
`prepared_not_run`. This document itself does not request a paid trial.
Read current source and docs, not a stale worker checkout or historical handoff.
Record `git rev-parse HEAD` and `git status --short`, and build from that source:

```bash
cargo build --release --lib --bin greedy_driver --bin dump_checkpoint --manifest-path norrust_core/Cargo.toml
```

Keep source and settings fixed during the run. Use a new directory per game.
Check exact model availability read-only when needed; do not substitute a model
or make an extra paid credit probe. Use dated model rates for cost estimates,
with an explicit `reasoning_included_in_output` value. Missing usage remains
unknown. A token ceiling permits one in-flight overshoot and is not a dollar cap.
A strategy finish is `{"kind":"finish_turn"}`; `finish_turn` true or false belongs
to `act`/`choose`. The redundant recorded object
`{"kind":"finish_turn","finish_turn":true}` is accepted and normalized without a
repair call. Do not treat that normalization as extra usage.

## Bounded recording without a paid observer

This example is one strategy opening, not the three-cell pilot or a full game.
Six engine side-turns means at most three controlled player turns. Change these
example settings only to match the requested trial. Run shell commands from the
repository root. The heredoc prepares data; the final command launches the game.

```bash
export NORRUST_TRIAL_ROOT="$PWD/tmp/glm-strategy-$(date -u +%Y%m%dT%H%M%SZ)"
export NORRUST_RELEASE_DRIVER="$PWD/norrust_core/target/release/greedy_driver"
test -x "$NORRUST_RELEASE_DRIVER"
mkdir "$NORRUST_TRIAL_ROOT"
cat > "$NORRUST_TRIAL_ROOT/requested-manifest.json" <<JSON
{
  "experiment_kind": "matched",
  "cells": [{
    "id": "glm-strategy", "scenario": "big_battle_6", "seed": 2038,
    "faction0": "undead", "faction1": "undead", "gold": 300,
    "llm_side": 0, "max_turns": 6,
    "model": "accounts/fireworks/models/glm-5p3-flash",
    "driver": "$NORRUST_RELEASE_DRIVER",
    "decision_mode": "strategy", "action_encoding": "coordinates",
    "incremental_turns": true, "reasoning_effort": null,
    "pricing": {"date": "2026-09-13", "rates": {
      "input_per_million": 0.15, "cached_input_per_million": 0.03,
      "output_per_million": 0.50, "reasoning_included_in_output": true
    }},
    "budgets": {
      "max_game_total_tokens": 200000, "model_timeout": 900,
      "turn_timeout": 2100, "query_budget_seconds": 300,
      "max_model_calls_per_turn": 8, "max_tool_calls_per_turn": 64,
      "max_queries_per_turn": 256, "max_partial_batches_per_turn": 64
    },
    "extra_client_args": ["--max-output-tokens", "131072"],
    "backend": {
      "kind": "command",
      "command": "python3 -m tools.fireworks_backend --stream --model accounts/fireworks/models/glm-5p3-flash"
    }
  }]
}
JSON
python3 -m tools.model_bakeoff run "$NORRUST_TRIAL_ROOT/requested-manifest.json" \
  --run-dir "$NORRUST_TRIAL_ROOT/recording" \
  --cohort "$(basename "$NORRUST_TRIAL_ROOT")" --timeout 2700
```

The maintained runner freezes provenance, starts the recording supervisor with
zero restarts, writes a five-minute `supervisor_heartbeat.json`, and uses the
owned-process stop facility at the 45-minute wall deadline. Existing output
exhaustion rules still apply. It imports every available result into
`recording/catalog.sqlite` and writes `recording/report.json`; inspect per-cell
status because the reporting command can succeed while a game failed. Rates
are recorded in the manifest using the schema described in
[MODEL_BAKEOFF.md](MODEL_BAKEOFF.md); the estimate remains unknown when the
required usage fields are missing.

The dated rates in this example are the existing 2026-09-13 Fireworks GLM-5.3
Flash evidence: $0.15/M uncached input, $0.03/M cached input, and $0.50/M
output, with `reasoning_included_in_output: true`. They produce an estimate
when usage coverage is complete; they are neither an invoice nor a hard dollar
cap. Recheck them read-only before any paid launch and leave cost unknown when
the required usage fields are missing.

Announce and persist the run path, source commit, command and tool session ID
when launching. Wait using the client application's background-process facility;
do not repeatedly read the full archive or stream to fill the wait. The child
game and automatic deadline do not need an LLM to poll each move.

## Occasional inspection and stopping

The cell directory is `$NORRUST_TRIAL_ROOT/recording/glm-strategy`. Read its compact
status only when needed; investigate specific indexed evidence if it shows a
problem:

```bash
python3 -m tools.run_watchdog status "$NORRUST_TRIAL_ROOT/recording/glm-strategy/match.watchdog"
python3 -m tools.run_watchdog read "$NORRUST_TRIAL_ROOT/recording/glm-strategy/match.watchdog" EVIDENCE_ID --limit 2048
python3 -m tools.watchdog_stop request \
  --run-id "$NORRUST_TRIAL_ROOT/recording/glm-strategy/match.ndjson" \
  --reason-code manual_operator_stop --observed-sequence 0
```

The last command is an intentional stop, not a status read; run it only when
stopping is intended. The supervisor cleans up its owned processes and records
the interruption. A proposal, forecast, or simulated recruiter death is not a
live result. Poor tactics or a long request alone do not prove a stuck game.

For a **paid bounded observer**, use the direct `llm_supervisor` recipe in
[Bounded watchdog observer](LLM_CLIENT.md#bounded-watchdog-observer), retaining
the chosen client limits, `--stream` and `--max-restarts 0`. `observe` records
judgments; only `enforce` can request an automatic semantic stop. Both player
and observer use Fireworks. The comparison runner above is recording-only; it
does not expose observer-mode flags. The direct supervisor has no wall-timeout
CLI flag, so do not claim its call/turn limits are a separate 45-minute deadline.
Zero observer dispatches can be normal; they do not validate its judgment.
Use current evaluation evidence, not the old OpenAI-credit failure. Completing
a healthy game does not establish stop-detection quality.

## Collect before reporting

Import failures and interruptions too. Observation runs are not exempt. The
runner already imports its local catalog; copy the same game identity into the
default Recorded Games catalog with the maintained importer:

```bash
python3 - <<'PY'
import os
from pathlib import Path
from tools.game_history import open_history, import_game
trial = Path(os.environ["NORRUST_TRIAL_ROOT"])
cohort = trial.name
db = open_history(Path.cwd() / ".norrust_history/history.sqlite")
try:
    print(import_game(db, trial / "recording/glm-strategy",
                      cohort_id=cohort, game_id=f"{cohort}:glm-strategy"))
finally:
    db.close()
PY
python3 -m tools.game_history usage \
  --db "$NORRUST_TRIAL_ROOT/recording/catalog.sqlite" \
  "$(basename "$NORRUST_TRIAL_ROOT"):glm-strategy" --group-by game --json
```

For a direct-supervisor game, import its run directory into both catalogs using
the same importer-returned game ID. A direct API player already has a durable
usage sidecar; do not invent a native Claude/Codex player binding or ask the
player to estimate tokens. Operator host spending is separate.

Inspect SQLite first, then review the final `match.watchdog/review.json` and
necessary archive evidence once. Report completed controlled turns, terminal
reason, winner only if proven, villages/recruiter survival, model versus routine
actions, recoveries/repairs/exceptions, and measured input/output/reasoning/cache
with coverage, aggregate-only requests and unassigned calls. Cost must count
cached input once and must not add reasoning twice. Preserve unknown cache-write
usage; it does not automatically prevent a cost estimate when those tokens are
not a separate billing dimension. A cap is not a win. A counterfactual saved
repair is not a measured rerun. Do not add a rescue/control game outside scope.

Current strategy response and route semantics are in
[Strategy mode](LLM_CLIENT.md#strategy-mode). Historical runs retain their old
labels and parsing behavior; evaluate the source commit that actually ran.

During contact decisions, the strategy model may either pick an offered tactical
choice (`choose`) or author custom coordinates orders (`act`). Routine execution
continues independent movement for units uninvolved in contact. If an invalid
policy attempt or identical contact incident is repeated at the same revision,
the player is halted after one corrective follow-up with `budget_interrupted`
and stop code `strategy_no_progress`.

The reusable 16-cell screening template is
`tools/fixtures/strategy_decisions/fireworks_screening_manifest.json`. Its
prepared status describes the template; existing user authorization carries
forward. Freeze the actual source and driver hashes for each execution. The
1.2-million-token aggregate launch stop is soft: dated rates plus one possible
in-flight context overshoot estimated $1.124288 exposure for the completed
follow-up, not a hard dollar cap.

The [completed follow-up](experiments/strategy-trial-followup-2026-09-14.md)
compared pre-controller baseline `cb9a85b` with candidate `5d1a7b8`. Both met
6/8 targets; candidate median tokens were about 5% higher, missing the required
25% reduction. All 16 one-turn cells completed, costing an estimated $0.2052.
The conditional opening pair was not launched. Do not describe this result as
a full-game win or a demonstrated efficiency improvement.
