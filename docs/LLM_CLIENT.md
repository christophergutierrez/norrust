# Norrust LLM client

`tools/llm_client.py` is a provider-neutral client for the headless
`greedy_driver` JSON-lines protocol. It asks the engine for authoritative options,
gives those options to a continuing model, validates one action batch, and forwards
the batch. The model controls only the configured `--llm-side`; after its final
`DoneWithImportantMoves`, `EndTurn`, or `FinishWithGreedy`, the driver completes the model boundary and automatically runs the opponent's transactional greedy turn
(including driver-supplied recruitment) and returns a new model-side boundary.

For a hybrid finish, the model may send `FinishWithGreedy` with explicit unit IDs,
optional `greedy` or `toward_hex` groups, and deliberate holds. The driver validates
the allowlist, performs only those delegated actions, records `delegated_greedy`
provenance, and then ends the turn. Recruitment remains model-owned. If the model
command times out, `--timeout-finish` applies the same bounded fallback to eligible
units and records `timeout_fallback`; it never invents recruitment.

The compact board briefing includes `MAP_TERRAIN` and `MAP_UNITS` layers. Terrain
uses two-character cells (`F.` forest, `H.` hills, `C.` castle, `K.` keep, `..`
flat, and `V0`/`V1`/`V-` villages); unit cells use `faction:id`, and `....` is
empty. Odd rows are indented to preserve the engine's odd-r hex geometry. The
unit roster remains authoritative for exact type, HP, and status.

For an opt-in incremental turn, add `--incremental-turns`. The driver permits
up to three accepted partial action arrays without `EndTurn`, returns a fresh
state after each one, and then requires a final array ending in `EndTurn`.
The state includes `turn_boundary`, `accepted_partial_batches`,
`remaining_partial_batches`, and `final_only`. A partial observation does not
run the opponent or reset the model turn; a failed partial batch is rolled back
without discarding earlier accepted batches. Checkpoints are published before
an accepted partial is acknowledged when `--log` is supplied.

The canonical per-turn instructions are the
[MEMORYLESS TACTICAL PLAYBOOK](LLM_TACTICAL_PLAYBOOK.md). The client reads that
file and includes its complete text inline near the beginning of every model
prompt. The model therefore does not need filesystem access. The client also
carries a bounded transcript for generic backends. The Luna adapter additionally
stores a native Codex thread ID in the match-owned `NORRUST_LUNA_SESSION_FILE`
sidecar and resumes that exact thread; it never uses `--last` or ephemeral
sessions. Engine state, revision, and fresh options remain authoritative after
every accepted batch.

Checkpoint branches may choose a new `--max-turns` cap for a controlled probe as
long as the cap is not below the checkpoint's completed side-turn count.

Responses may include an optional full `agenda` replacement with up to eight
tasks (`id`, `goal`, `units`, `status`) and deliberate `holds`. Agenda data is
bookkeeping and never creates engine actions. Malformed agenda data is logged and
ignored while valid actions continue, and a proposed agenda is published only
after its action batch is accepted. Each observation includes a compact
whole-army sweep unless `--disable-agenda-sweep` is passed; this adds no review
call and never prevents `EndTurn`.

## Build and run

Build the driver from the repository root:

```bash
cargo build --bin greedy_driver --manifest-path norrust_core/Cargo.toml
```

An executable deterministic run uses the committed orders fixture:

```bash
python -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --orders-file tools/orders_fixture.jsonl \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 42 --llm-side 0 --max-turns 4 \
  --log /tmp/norrust-llm-match.ndjson
```

That fixture run is a **protocol smoke test**. It proves the client, driver, and
log path work. It does not play a real match — see the cap guidance below.

### Running a real match against a live model

Replace `--orders-file` with exactly one of `--interactive-model` or
`--model-command 'COMMAND'`.

**`--model-command`** runs an automated backend. The command receives the full
prompt on **stdin** and must write **one JSON object** to **stdout**:

```json
{"text": "[{\"action\":\"EndTurn\"}]"}
```

`text` is the model's raw reply. On the first call for a turn, it may contain
either the final bare JSON action array or one `preview_batch` request as described
below. After preview results are returned, it must contain the final bare JSON
action array. The command-backend envelope remains unchanged for both calls:
`{"text":"..."}`. Optionally include `usage`
(`{"input_tokens":N,"output_tokens":N}`); when absent, token budgets are recorded
as estimated rather than measured. A minimal backend:

```python
#!/usr/bin/env python3
import json, sys
prompt = sys.stdin.read()
reply = call_your_provider(prompt)        # returns a string
reply = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
sys.stdout.write(json.dumps({"text": reply}))
```

Strip markdown fences before emitting: models frequently wrap their JSON reply,
and a fenced reply is a validation failure that costs a repair round.

**`--interactive-model`** prints the prompt to the terminal and reads the reply
from stdin, so a human or an agent driving the terminal *is* the model. No
backend process is involved.

A complete evaluation run:

```bash
python -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --model-command 'python3 /path/to/your_backend.py' \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 2001 --llm-side 0 \
  --max-turns 30 \
  --turn-timeout 930 --query-budget-seconds 900 \
  --log /path/to/match.ndjson
```

An incremental evaluation uses the same command with `--incremental-turns`:

```bash
python -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --model-command 'python3 /path/to/your_backend.py' \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 2001 --llm-side 0 --max-turns 25 \
  --incremental-turns --log /path/to/isolated/match.ndjson
```

Use a distinct log and checkpoint directory for every concurrent run. The
client does not force a partial batch; the model may still finish a turn in one
batch. `turn_format` in metadata records the requested mode.

For Luna, use `tools/luna_backend.py` as the model command and provide a unique
session sidecar for every match:

```bash
NORRUST_LUNA_SESSION_FILE=/path/to/match/luna-session.json \
python -m tools.llm_client ... --reasoning-effort high \
  --model-command 'python3 tools/luna_backend.py'
```

The adapter fixes the runtime model to `gpt-5.6-luna` and reasoning to `high`,
uses read-only sandboxing when creating the thread, and records the native
thread, runtime settings, and transport in client metadata. The prompt rejects
unrelated shell, web, file, skill, and connector use; the adapter fails if a
native response reports one of those tool classes.

When an engine rejects a submitted batch, the client allows bounded action
repairs. Inspection results requested during pre-submit repair remain in every
subsequent repair prompt, including across multiple inspections and malformed
responses. Tool requests have their own four-request cap; physical model calls
remain separately recorded. Repeated illegal proposals remain a model-invalid
result and are recorded separately from infrastructure failures.

The default `--turn-timeout` is 930 seconds. The client keeps the model command
timeout and driver query budget independently. It warns when the turn timeout
is below `query_budget_seconds + 2 * model_timeout`, since an action repair can
require two model calls. Driver EOF and broken-pipe failures are written as
durable typed terminal records with the last event count and a bounded stderr
diagnostic tail.

Budget wall-clock accordingly. `--max-turns 30` is ~15 model side-turns; at 2-4
minutes each that is 30-60 minutes, longer with repairs. If you wrap the run in
an external `timeout`, size it above that or you trade a driver timeout for a
wall-clock one and still get no result.

Always pass `--log`. The NDJSON log is the only durable record; without it a
completed match leaves nothing to analyse.

### When a run produces no result

| Symptom | Cause | Fix |
| --- | --- | --- |
| `driver_broken_pipe` terminal | driver exited while the client was writing | inspect the recorded stderr tail and timeout budgets |
| Terminal `max_turns`, no winner | cap too low to reach a decision | raise `--max-turns` to 24+ |
| `model_error` after one repair | backend emitted prose, fences, or a non-array | strip fences in the backend |
| Log stops growing for minutes | normal during a slow model call | check log mtime over minutes, not seconds |

Judge liveness from the log's size and mtime over a multi-minute window. A model
call in flight writes nothing while it runs, so a briefly static log is expected,
not a hang.

## Model response and action batch

On its first response for a turn, the model returns either its final action array
or one read-only preview request containing one or two complete candidate arrays:

```json
{"tool":"preview_batch","candidates":[[{"action":"EndTurn"}],[{"action":"Move","unit_id":12,"col":4,"row":7},{"action":"EndTurn"}]]}
```

Each candidate follows the same action-batch rules as a final response. The
preview does not submit actions or sample combat. The model may also inspect one
friendly unit at a time:

```json
{"tool":"inspect_unit","unit_id":12}
```

That result contains the unit's legal destinations and legal targets from each
origin with exact exchange forecasts. It also includes `destination_threats`,
the next-turn threat summary for each legal position; these are facts, not
ranked move recommendations. Two other factual inspections are
available:

```json
{"tool":"inspect_target","unit_id":19}
{"tool":"inspect_hex","col":4,"row":7,"phase":"next_opponent_turn"}
```

`inspect_target` lists friendly attackers and origins for one enemy.

`inspect_targets` accepts `unit_ids` with one to eight unique visible enemy IDs
and returns the same inspections in one read-only query. It is a batching
optimization only; singular inspection remains supported.
`inspect_hex` lists attack coverage for one hex either now or after the
deterministic next `EndTurn`; empty hexes have no invented combat forecast.
Tool calls are read-only and revision pinned. `--max-tool-calls-per-turn` bounds
them (default 4), while `--max-model-calls-per-turn` remains the overall
model-call bound. Every tool follow-up reports the remaining budget. When no
tool call remains, the follow-up requires final actions only. If the model requests
another tool anyway, the client does not execute it; its correction prompt
retains all prior tool results and requires final actions. A second
`preview_batch` request is still not accepted.

The normal card summarizes each unit with its current hex, legal move count,
attackable target IDs, and attacks available from its current hex. Inspect a unit when a
specific decision needs detailed origins; do not inspect every mover by
default. Movable origins and their target combinations are returned by
`inspect_unit`; `--diagnostic` retains the complete JSON surface.
The default `EVENTS` block is an `EVENT_DIGEST`: compact grouped movement,
recruitment, attack, gold, village, and turn-boundary facts. Diagnostic mode
retains the raw event objects.
`--decision-metrics` adds one read-only preview of the final model-authored
batch to the log so evaluations can compare recruiter danger and remaining
recruitment before and after the decision.
The tactical card also includes exact direct focus vectors: `focus_p` contains
kill probabilities in basis points for the best compatible one-, two-, and
three-attacker volleys, while `focus_e` contains expected cumulative damage in
tenths. These are bounds, not recommendations. Automatic draft review compares
the draft with an unchanged `EndTurn` baseline and labels reply exposure with
the assumption that forecast combatants survive in place. Whole-force `FORCE`
and mechanical `RECRUIT` lines are observations; they do not force recruitment
and saving gold remains legal.

A final action array is a non-empty JSON array of at most 256 objects. Every
object has exactly the fields shown below. There is exactly one final
`DoneWithImportantMoves`, `EndTurn`, or `FinishWithGreedy` boundary; no action follows it.
On turns where a submitted draft leaves the recruiter in projected lethal
danger, the client sends one read-only draft result back to the model. The
model may repeat the draft to confirm it or return a revised final array; the
client never refuses a confirmed dangerous batch.
Before ending a turn, the model is strongly encouraged to exhaust legal
recruitment: move non-recruiters off castle hexes when needed, recruit into the
resulting legal placements, and repeat until gold, definitions, or castle
capacity prevents another recruit. It may deliberately save gold for a better
recruit next turn when that is strategically justified.

```json
{"action":"Move","unit_id":12,"col":4,"row":7}
{"action":"Attack","attacker_id":12,"defender_id":19}
{"action":"Recruit","def_id":"Skeleton","col":3,"row":6}
{"action":"RecruitBatch","def_id":"Skeleton","count":2}
{"action":"Advance","unit_id":12,"target_index":0}
{"action":"Advance","unit_id":12,"def_id":"Veteran Skeleton"}
{"action":"DoneWithImportantMoves"}
```

`Move` has integer `unit_id`, `col`, and `row`. `Attack` has integer
`attacker_id` and `defender_id`. `Recruit` has string `def_id` and integer
`col` and `row`. `RecruitBatch` is optional driver assistance: it has string
`def_id` and positive integer `count`; the driver attempts up to that many legal
placements and reports the actual `recruited` count and `partial` flag.
It is rejected when the driver is started with `--disable-recruit-batch`.
`Advance` has integer `unit_id` and exactly one selector: integer `target_index`
or string `def_id`; `target_index` indexes that unit's `advances_to` list in the
order shown in the board data. `DoneWithImportantMoves` and `EndTurn` have only
`action`. `FinishWithGreedy` accepts explicit groups and holds; its groups may
be empty when every remaining unit is protected.

The client rejects malformed JSON, unknown fields, missing fields, non-integer
numeric fields, non-positive batch counts, and invalid batch structure before
forwarding it. A validation failure may receive one repair call from the model;
if the driver rejects a submitted batch, the entire batch was rolled back. The
repair prompt reports that no prefix action committed and requires replanning
from the unchanged observation using authoritative options.
provider/model/query failures are infrastructure-invalid results with a nonzero
client exit, not gameplay losses or draws. A driver status rejection after
forwarding an action is also recorded as infrastructure-invalid so the client
cannot wait indefinitely for a new boundary.

## Singleton engine queries

The client—not the model—sends queries as singleton JSON lines before each model
call. A model action batch must never contain `Query`:

```json
{"action":"Query","what":"turn_options"}
{"action":"Query","what":"recruit_options"}
```

`turn_options` returns `body.units`. Each unit entry contains `unit_id` and
`positions`; each position contains integer `col`, integer `row`, and `target_ids`.
The current position and reachable positions therefore map directly to `Move` and
`Attack` choices. `recruit_options` returns the active faction's `faction_id`,
`side_can_place`, `placement_hexes`, each legal definition's `def_id`, `cost`, and
`affordable`, plus `batch_macro_enabled`. These engine responses are authoritative:
the client does not reconstruct movement, combat, recruitment, or placement
legality. Additional engine query failures are typed status failures.

## Turn ownership, outcomes, and failures

Every submitted action, including each turn boundary, is accepted only when the configured
model side equals the active faction and every referenced unit belongs to that
faction. An unauthorized action is rejected without state, event, or side-turn
mutation. The model never submits the opponent's turn.

After a successful model turn boundary, the driver automatically performs one greedy
opponent side-turn: recruitment, greedy movement/combat, and its successful turn
boundary. The opponent transaction runs on private state. A preparation, planner,
action, or boundary error produces a typed terminal `game_end` with an additive
`reason` of `infrastructure_failure`, stable `code`, and `message`; it does not
commit state, events, allocated IDs, or counters, print a normal boundary, or become
empty events, a draw, a win, or continuation. Logs identify this with
`infrastructure_invalid: true` and exits nonzero.

The headless driver explicitly disables `objective_hex` and scenario turn-limit
win conditions. Its gameplay win evaluation is recruiter loss, then elimination.
Recruiter loss applies when exactly one side that previously had recruiting
capability has no living recruiter; that side loses. If both sides or neither side
meet that predicate, evaluation falls through to elimination. This is the
headless-client rule; broader GUI/campaign rules may also include scenario
objectives and scenario turn limits.

`--max-turns` is an external completed-side-turn safety cap, not the engine's
displayed round counter or a scenario turn limit. One completed model side-turn
and one completed greedy side-turn each increment it once. A failed greedy turn
adds no opponent side-turn and is terminal; the preceding completed model
side-turn remains counted.

**Use at least 24 for any evaluation run.** The median game runs longer than 12
side-turns, so a cap of 12 or below reliably ends in `max_turns` before the
match is decided — a valid terminal, but one that measures nothing about play.
On `big_battle_6` the armies start at opposite keeps, (2,7) and (21,6), and
spend the opening turns recruiting and closing distance; first contact is
typically around side-turn 10-14, so a low cap cuts the match off before any
combat happens. Short caps are for protocol smoke tests, like the `--max-turns 4`
fixture example above, not for measuring whether a model can win.

Terminal reasons `winner` and `max_turns` are gameplay-valid. A rejected batch
after its repair is `model_invalid` (exit 2), a completed evaluation that is
neither gameplay nor harness failure. Its counters are `rejected_batches` (one
per rolled-back batch) and `rejected_action_items` (failed result items).
Terminal reasons `setup_error`,
`timeout`, `eof`, `infrastructure_failure`, and unknown or malformed terminal
reasons are infrastructure-invalid; the client records
`infrastructure_invalid: true` and exits nonzero. An LLM win is neither guaranteed
nor required for a valid run. The terminal metadata records the configured cap and
match conditions.

The 2026-09-05 controlled checkpoint probes ran six fresh native conversations,
two side turns per arm, with identical checkpoint/RNG/model settings. All six
were gameplay-valid `max_turns` probes. The agenda-enabled arms emitted no
agenda updates, so the comparison measured sweep and prompt changes rather than
objective execution: A-on had 22 unique movers and 1 Luna attack versus A-off's
17 and 4; B-on had 23 and 8 versus B-off's 19 and 10; C-on had 15 and 2 versus
C-off's 14 and 9. This is diagnostic evidence of changed behavior, not evidence
of improved play or a win-rate effect.

The three final 50-side-turn attempts were preserved under
`tmp/luna_agenda_eval/`. Seed 2031 completed 9 model side turns before a native
timeout retry encountered an active thread writer (`infrastructure`); seed 2032
completed 6 before a partial-limit repair exhausted (`model_invalid`); seed 2033
completed 6 before the same active-writer timeout conflict (`infrastructure`).
None produced a gameplay-valid terminal result or winner. The timeout retry was
then removed and committed separately; these attempts are an earlier-build
cohort and must not be resumed as a clean comparison.

Balance tests are explicitly excluded from this client milestone and must not be
run.
