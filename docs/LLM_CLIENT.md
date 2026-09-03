# Norrust LLM client

`tools/llm_client.py` is a provider-neutral client for the headless
`greedy_driver` JSON-lines protocol. It asks the engine for authoritative options,
gives those options to a memoryless model, validates one action batch, and forwards
the batch. The model controls only the configured `--llm-side`; after its final
`EndTurn`, the driver automatically runs the opponent's transactional greedy turn
(including driver-supplied recruitment) and returns a new model-side boundary.

The canonical per-turn instructions are the
[MEMORYLESS TACTICAL PLAYBOOK](LLM_TACTICAL_PLAYBOOK.md). The client reads that
file and includes its complete text inline near the beginning of every model
prompt. The model therefore does not need filesystem access.

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
preview does not submit actions or sample combat. After receiving preview results,
the model must return a final action array; a second preview request is not
accepted.

A final action array is a non-empty JSON array of at most 256 objects. Every
object has exactly the fields shown below. There is exactly one final
`{"action":"EndTurn"}`; `EndTurn` is not optional and no action follows it.
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
{"action":"EndTurn"}
```

`Move` has integer `unit_id`, `col`, and `row`. `Attack` has integer
`attacker_id` and `defender_id`. `Recruit` has string `def_id` and integer
`col` and `row`. `RecruitBatch` is optional driver assistance: it has string
`def_id` and positive integer `count`; the driver attempts up to that many legal
placements and reports the actual `recruited` count and `partial` flag.
It is rejected when the driver is started with `--disable-recruit-batch`.
`Advance` has integer `unit_id` and exactly one selector: integer `target_index`
or string `def_id`; `target_index` indexes that unit's `advances_to` list in the
order shown in the board data. `EndTurn` has only `action`.

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

Every submitted action, including `EndTurn`, is accepted only when the configured
model side equals the active faction and every referenced unit belongs to that
faction. An unauthorized action is rejected without state, event, or side-turn
mutation. The model never submits the opponent's turn.

After a successful model `EndTurn`, the driver automatically performs one greedy
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

Balance tests are explicitly excluded from this client milestone and must not be
run.
