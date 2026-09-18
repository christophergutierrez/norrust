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

## Budget reservation and reconciliation

Screening and baseline cells spend against one standing budget ledger. Never
recreate, reset or reseed it from a remembered figure: read it, and let the tools
below update it. Operate one cell at a time; the ledger holds a single active
reservation and is not built for concurrent writers.

1. Reserve before launching a cell. `tools.budget_reconciler reserve --ledger
   <standing ledger> --manifest <resolved manifest> --cell-id <cell>` computes the
   minimum from that cell's resolved limits, not from a fixed label: its soft
   game-token cap charged at the highest configured token rate, plus one maximum
   final request of `tools.output_limits.MAX_OUTPUT_LIMIT` output tokens and the
   cell's resolved `--max-prompt-bytes` as input. The client checks both the soft
   cap and the output ceiling before every physical dispatch, retries included, so
   there is no unchecked retry tail to add. Prompt bytes bound input tokens from
   above, and the client refuses an oversized prompt before dispatching it, so the
   manifests pass an explicit finite `--max-prompt-bytes`. A missing finite limit
   is an error, never a guessed reservation. `--amount` may raise the reservation
   above that minimum but cannot lower it. Reservation is refused, leaving the
   ledger untouched, when another cell holds the active reservation or when the
   amount exceeds `remaining_authorization_usd`.
2. Run the cell with `tools.model_bakeoff run ... --only-cell <cell>`.
3. Reconcile after the cell's process has exited, however it ended:
   `tools.budget_reconciler reconcile --ledger <standing ledger> --cell-dir
   <cell dir> --cell-id <cell>`. Physical calls are identified by `(game_id,
   call_id)`, never by prompt hash, so repeated lifecycle rows count once.
   Reconciling is idempotent: the same receipts give the same ledger, and only
   that cell's entry is replaced. A call without measured usage stays unknown
   rather than becoming zero spend.

The reservation is released only when `run_status.json` proves the cell stopped
(`status` `ok`, `failed` or `error`; the file merely existing is not proof) AND
every dispatched call has a matched, fully measured final receipt. Otherwise the
full reservation stays, which is the deliberate conservative default; reconcile
again when late evidence arrives. Before the next cell, judge available funds by
`spendable_authorization_usd`, which already subtracts any reservation still held.

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

### Reasoning effort selection

Fireworks GLM-5.3-Flash supports explicit `reasoning_effort` settings: `"low"`,
`"high"`, or `"max"`. When `reasoning_effort` is omitted or `null`, the model
documents an effective default of `max`. Configure explicit effort at the manifest
cell level (`"reasoning_effort": "low"`) or via `llm_client`'s `--reasoning-effort`
flag. Do not pass `--reasoning-effort` inside `--model-command`; `fireworks_backend`
enforces this precedence and rejects conflicting arguments before network dispatch.
Unsupported values (such as `"medium"`) fail preflight before making calls.

The requested effort flows through client request context, match logs, and SQLite
catalog fields (`game_players.reasoning_requested` and
`model_calls.requested_reasoning_effort`). The provider's actual reported effort
is tracked separately in `reasoning_reported`; unless the provider explicitly
returns the effective setting in usage or headers, reported effort remains
unknown (`null`), not assumed equal to requested.

An experimental low-effort configuration example:

```json
    "reasoning_effort": "low",
```

This experimental setting screens for reduced reasoning token expenditure and
latency during tactical contact decisions. Do not label it proven until paired
screening or full-game evaluation confirms tactical quality and token efficiency.

## Strategy decision quality screening

Before committing to a full game with an experimental effort setting, screen
decision quality across three frozen acceptance positions using paired cells
(explicit `low` vs explicit `high` effort):

1. **Initial 300-gold allocation** (`tools/fixtures/acceptance_scenarios/initial_allocation`):
   Authorizes at least 200 gold of affordable recruitment in the 300-gold opening
   with `reserve_gold <= 100`, feasible scout coverage, and adequate army size.
2. **Completed small queue with idle gold** (`tools/fixtures/acceptance_scenarios/completed_queue`):
   Valid replenishment reaches actual routine recruit commits during remote contact
   (`replenished`), or explicit saving is reported as a behavioral choice (`saved`).
3. **Pre-charge recruiter decision** (`tools/fixtures/acceptance_scenarios/precharge_recruiter`):
   Chosen action retains recruiter survival through the frozen opponent continuation;
   a legal but losing advance (e.g. charging into fatal hexes) fails.

Offline verification runs via `python3 -m unittest tools.test_strategy_quality`.
Evaluation predicates and cell scoring are defined in `tools.strategy_quality`.
Selection rule: select `low` only if all three acceptance gates pass; otherwise
prefer `high` if it passes. If neither passes, stop after findings rather than
adding effort levels or seeds.

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
necessary archive evidence once. Final reports must cover:
- Requested versus reported reasoning effort (`low`, `high`, `max`, or unknown).
- Prompt layout version (`strategy_layout_v1`, `prompt_layout_v2`, or legacy/unknown) and fixed-prefix UTF-8 bytes and SHA-256 hash.
- Completed controlled player turns versus resolved side-turns: report `completed_side_turns` (completed `EndTurn` boundaries) and `resolved_side_turns`, noting any `terminal_partial_side_turn`, terminal reason, and winner only if proven.
- Villages, income, recruiter survival and terminal outcome via `match_report.recruiter_outcome` (last proven live HP and coordinate, last committed model action, and verified death location derived by replaying archive movement events through lethal combat; never a stale pre-move snapshot).
- Strategy choices and recommendation adoption via `match_report.strategy_choices` (response kinds, submitted selections, committed option batches, option-ID matches, exact ID-plus-finish matches, and custom combinations).
- Decisive decisions via `match_report.decisive_decisions` (`first_rejected_choice` and `last_recruiter_action`, referencing exact request, decision, revision, options, error, and checkpoint).
- Delegated tactical actions via `match_report.delegated_tactical_actions` and `tactical_delegation_occurred`: distinguish a no-sweep finish (`FinishWithGreedy(groups=[], holds=[])`) from actual delegated Greedy moves or attacks.
- Recoveries, repairs (distinguishing schema errors, engine rejections, and context rejections), and exceptions.
- Bounded strategy recoveries, counted separately from ordinary repairs:
  dispatched backend attempts, committed batches, rejected responses, and
  unavailable recoveries (`match_report.strategy_recovery`). At most one extra logical response
  per controlled side turn, reserved before dispatch and never refilled by a
  later incident or a resume. A run whose log lacks these counters predates the
  feature: report them as unknown, not zero. A recovery that commits a legal
  move is not evidence of good play, and an unavailable recovery is not a
  failure of the model.
  Reservation is not dispatch, and an accepted response is not yet a committed
  action. Check the usage sidecar for actual provider calls and billing coverage.
- Physical calls versus logical requests, and measured input, cached input, output, and reasoning tokens (included in output).
- Input/output cost separation: compute uncached input, cached input, and output independently at dated rates; count cached input once and do not double-count reasoning. Preserve unknown cache-write usage.
- Measured model elapsed time versus engine execution time.
A fake cache test or layout alignment does not establish live provider support or savings; only provider-reported cached tokens establish a hit. A cap is not a win. A counterfactual saved repair is not a measured rerun. Do not add a rescue/control game outside scope.

Current strategy response and route semantics are in
[Strategy mode](LLM_CLIENT.md#strategy-mode). Historical runs retain their old
labels and parsing behavior; evaluate the source commit that actually ran.

During contact decisions, the strategy model may either pick an offered tactical
choice (`choose`) or author custom coordinates orders (`act`). Routine execution
continues independent movement for units uninvolved in contact. The issued
`DecisionPacket` is authoritative for permitted response kinds and final-only
requirements in the delivered prompt footer; `choose` is advertised only when the
packet allows it. For exhausted contact where involved units cannot act, automatic
outside-unit helper menus are not generated (`options_empty_reason:
exhausted_contact_no_automatic_rescue_menu`, coverage `not_generated`). Custom
actions (`act`), finish, or resign remain permitted; an empty menu is not proof
that every rescue is impossible. If an invalid policy attempt or identical contact
incident is repeated at the same revision, the player is halted after one
corrective follow-up with `budget_interrupted` and stop code `strategy_no_progress`.

During `invalid_assignment` policy maintenance exceptions, if a live friendly
recruiter has next-turn exposure and executable actions, the packet attaches up to
four tactical options (at most two attacks, at most two relocations) and permits
`choose` alongside `set_policy`, `act`, `finish_turn`, and `resign`. Choosing a
tactical action executes that move/attack atomically but does not repair the
installed policy, which remains outstanding. If the threatened recruiter is
exhausted, explicit no-options coverage is reported without generating unrelated
helper menus.

When screening or testing from synthetic strategy fixtures, bootstrap with
`--strategy-policy` (zero paid calls, zero board actions) to produce an authentic
model-boundary checkpoint and companion parent audit log. Resuming that checkpoint
with its parent log restores installed policy and ensures the target decision
(e.g., proposed destination or exhausted contact) is presented at the first model
call, rather than falling back to an initial policy request. Run a fake-transport
preflight to verify the exact packet stage, permissions, and menu expectations
before paid dispatch.

The reusable 16-cell screening template is
`tools/fixtures/strategy_decisions/fireworks_screening_manifest.json`. Its
prepared status describes the template; existing user authorization carries
forward. Freeze the actual source and driver hashes for each execution. The
1.2-million-token aggregate launch stop is soft: one in-flight call can cross
the threshold. Estimate cost from the run's dated rates; the token stop is not
a hard dollar cap.

Store experiment-specific manifests, results and handoffs under ignored `tmp/`.
Use committed fixtures to reproduce the intended situation, then record actual
source and driver hashes for the run. A screening result or turn-cap completion
does not establish a full-game win or a demonstrated efficiency improvement.
