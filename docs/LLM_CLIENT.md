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

For a live provider-neutral session, replace `--orders-file` with exactly one of
`--interactive-model` or `--model-command 'COMMAND'`. The command backend must
write a JSON object such as `{"text":"[{\"action\":\"EndTurn\"}]"}` to stdout.

## Model action batch

The model returns only a non-empty JSON array of at most 256 objects. Every object
has exactly the fields shown below. There is exactly one final
`{"action":"EndTurn"}`; `EndTurn` is not optional and no action follows it.

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

Terminal reasons `winner` and `max_turns` are gameplay-valid. `setup_error`,
`timeout`, `eof`, `infrastructure_failure`, and unknown or malformed terminal
reasons are infrastructure-invalid; the client records
`infrastructure_invalid: true` and exits nonzero. An LLM win is neither guaranteed
nor required for a valid run. The terminal metadata records the configured cap and
match conditions.

Balance tests are explicitly excluded from this client milestone and must not be
run.
