# Norrust LLM client

## Start here for a model game

The parent process should read this document, choose isolated artifact paths, and
launch one client per game. The player receives the complete canonical prompt on
each request and does not need to read repository files. A model-subagent request
can be as short as:

> Play the configured Norrust game from the complete client prompt. Return only
> the JSON action or inspection request allowed by that prompt. Do not use shell,
> web, files, skills, or unrelated tools.

Do not read `.paul`, old temporary backends, or unrelated development documents
unless diagnosing a specific setup failure. Preserve the prompt bytes and hash in
the request archive. A transport receipt proves delivery, not comprehension.

### Prompt maintenance

The canonical prompt starts with the numbered
[MEMORYLESS TACTICAL PLAYBOOK](LLM_TACTICAL_PLAYBOOK.md). Keep strategic choices
there; `prompt_for` in `tools/llm_client.py` supplies engine rules, match rules,
response schemas, tool semantics, and forecast definitions.

`ENGINE_RULES` in `tools/llm_client.py` states the engine mechanics a player
cannot infer from the board: attack reach, matching-range retaliation, terrain
movement costs, destination occupancy, the zone-of-control stop rule, and batch
rollback. These are facts, not advice — keep tactical judgement in the playbook.
Every line is locked by a `test_documented_rule_*` fixture in
`norrust_core/src/game_state.rs`; change the block and its fixtures together, and
add a fixture before adding a fact. A confidently stated wrong rule is worse than
an omitted one, because a player that would otherwise inspect the board believes
it instead. Structured live data follows,
and request-specific follow-ups supply the current call budget and live revision.
Players need only the assembled prompt. Keep each instruction in one place
within it; use concise conditional tactics and avoid repeated checklists.
Preserve rule IDs when editing wording so recorded citations remain comparable;
the archived guide hash identifies the exact text used by a game.

### Decision annotations

The prompt requests `{"actions":[...],"decisions":[...]}` on every action response. The actions
remain the ordinary action contract. Decision groups cite one to four stable
playbook IDs and provide expected effect and risk text; their zero-based order
indices cover each authored action exactly once. The client validates this
metadata and never sends annotation fields to the Rust driver. Missing or
malformed annotations can still execute legally, but count as missing or
invalid evidence. Tool-only requests and generated greedy actions are
`not_applicable`.

The audit log preserves the exact prompt, raw response, request ID, state
revision, and annotation status. Repaired or revised responses carry the
annotation belonging to their own final orders. SQLite stores valid data as
compressed `decision_annotation_v1` rationale; approved training export includes
it only when the decision was explicitly approved.

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

The existing draft review distinguishes explicit delegation, explicit holds,
and omitted observed friendly units for a selective finish. A recruiter in an
explicit group is delegated too and may leave the keep; automatic completion
excludes the recruiter. These categories describe the candidate's boundary
instructions, not guaranteed positions or safety. They do not cancel earlier
authored moves, recruitment vacates, or subsequent enemy actions. The submitted
batch log carries a fresh handoff audit of its final orders after review/repair;
the draft review retains the original candidate's audit.

Advance ranged support with its screen, and use specific rescues and guards
while letting routine healthy units contribute. Explain consequential holds
with a current job, the action or pressure forgone, and a release condition in
the existing hold reason and decision fields. Such explanations are evidence;
they do not create executable holds or add model calls. Material disadvantage
alone is insufficient justification for hopelessness, but resignation remains
an immediate standalone action.

The compact board briefing includes `MAP_TERRAIN` and `MAP_UNITS` layers. Terrain
uses two-character cells (`F.` forest, `H.` hills, `C.` castle, `K.` keep, `..`
flat, and `V0`/`V1`/`V-` villages); unit cells use `faction:id`, and `....` is
empty. Odd rows are indented to preserve the engine's odd-r hex geometry. The
unit roster remains authoritative for exact type, HP, and status.

For pending friendly promotions, the compact roster includes the engine's
ordered `advances_to` choices. Use their exact definition names or zero-based
indices: `{"action":"Advance","unit_id":13,"def_id":"Bone Shooter"}` or
`{"action":"Advance","unit_id":13,"target_index":0}`. Supply exactly one
selector. A missing list is unknown, an empty list supplies no choice, and a
unit without a pending promotion cannot advance merely because its type has
an upgrade. The driver validates the action against the current state.

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
carries a bounded transcript for generic backends. The Codex adapter additionally
stores a native Codex thread ID in the match-owned `NORRUST_CODEX_SESSION_FILE`
sidecar and resumes that exact thread; it never uses `--last` or ephemeral
sessions. Engine state, revision, and fresh options remain authoritative after
every accepted batch.

Checkpoint branches may choose a new `--max-turns` cap for a controlled probe as
long as the cap is not below the checkpoint's completed side-turn count.

To continue an interrupted match, use the latest checkpoint directly and write a
new audit log. This preserves the original log and its checkpoint archive:

```bash
python -m tools.llm_client \
  --driver norrust_core/target/release/greedy_driver \
  --model-command 'YOUR_MODEL_COMMAND' \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 2038 --llm-side 0 --max-turns 50 \
  --incremental-turns \
  --resume-checkpoint /path/to/match.ckpt/LATEST_CHECKPOINT.json \
  --log /path/to/resumed-match.ndjson
```

Keep the scenario, factions, gold, seed, side, and turn format identical to the
interrupted run. The checkpoint restores authoritative engine state and the
bounded client transcript; a new log is required for `--resume-checkpoint` and
records the parent checkpoint. `--resume-log PATH` is available when continuing
the same incomplete log in place, but a new branch is safer for experiments.
The client rejects a resume whose turn cap is below the checkpoint's completed
side-turn count or whose match identity does not match. The Codex adapter also resumes its
match-owned native session when the session sidecar is available; generic model
commands receive the restored state and bounded transcript through the new
backend process.

Responses may include an optional full `agenda` replacement. The accepted value
is an object with exactly `tasks` and `holds`; `tasks`
is a list of at most eight objects with exactly `id` (unique non-empty string),
`goal` (at most 160 UTF-8 bytes), `units` (integer friendly IDs), and `status`
(`pending`, `active`, `done`, or `deferred`). At most one task may be `active`.
`holds` is a list of integer friendly IDs. For example:

```json
{"actions":[{"action":"FinishWithGreedy","groups":[{"mode":"greedy","unit_ids":[12]}],"holds":[{"unit_id":14,"reason":"guard keep"}]}],"agenda":{"tasks":[{"id":"front","goal":"Keep the screen on the keep","units":[12,14],"status":"active"}],"holds":[14]},"decisions":[{"orders":[0],"rules":["T7"],"expected":"Delegate U12 and keep U14 at its current hex.","risk":"U12 may choose an unsafe delegated destination."}]}
```

The agenda is a full replacement, limited to 4096 compact JSON bytes. Agenda
data, `intent`, and decision annotation prose are bookkeeping and never create
engine actions or normal holds. Agenda holds are reported in observations and
can be preserved by timeout fallback within that turn; they reset at a new turn,
while agenda tasks persist. They do not restrict the ordinary automatic
sweep. Only a `FinishWithGreedy` hold is an explicit executable instruction in
the submitted action batch. Malformed agenda data is logged and ignored while
valid actions continue, and a proposed agenda is published only after its action
batch is accepted. Each observation includes a compact whole-army sweep unless
`--disable-agenda-sweep` is passed; this adds no review call and never prevents
`EndTurn`. In a selective finish, only listed group IDs are swept and listed
hold IDs are kept; other units remain unswept. Neither mechanism prevents
earlier authored moves or recruitment, auto-vacating, or later opponent attacks.
Delegated destinations remain a tactical choice and are not guaranteed safe.

### Publishing a file-transport reply

`tools/file_backend.py` is the file-transport `--model-command` adapter: it writes
the complete prompt unchanged to `prompt_<ID>.txt`, publishes a `waiting_<ID>`
marker, and blocks until `reply_<ID>.txt` appears. A human or agent player using
that transport must never write `reply_<ID>.txt` directly. Draft the reply to a
temporary file in the same directory, then publish it with `tools/publish_reply.py`:

```bash
python3 -m tools.publish_reply --directory /absolute/run/requests --pending /absolute/run/requests/draft.tmp
```

`--request-id` is optional; it is inferred from the single `waiting_*` marker in
the directory when omitted, and required only when more than one is present.
`publish_reply` validates the draft with the same `tools.decision_annotations`
validator the client applies after publication — malformed JSON, an unknown rule
ID, uncovered actions, empty risk/expected text, and text over the 240 UTF-8 byte
cap are all rejected before publication, with the exact error printed and nothing
written to `reply_<ID>.txt`. Tool-only requests and replies with no decisions
(including a bare action array) remain eligible: missing annotations can still
execute legally, so only genuinely malformed evidence blocks publication. On
success it publishes atomically with an exclusive filesystem link, so a duplicate
or concurrent publish attempt can never replace an already-published reply.

Every attempt — accepted or rejected — is appended to `validation_log.ndjson` in
the same directory as one JSON object per line: `request_id`, `timestamp`,
`status`, `error`, `attempt_sha256`, and `attempt_bytes`. The raw rejected bytes
are preserved there, never shortened or rewritten, even though they never reach
the driver. Pass that log to `tools/match_report.py --publication-log PATH` to
aggregate first-attempt-valid, repaired, and unresolved publication counts
alongside the existing final-annotation coverage; a request with no local
validation record at all is reported as unknown, not scored as a perfect
first attempt. A reply that bypasses `publish_reply` entirely (written straight
to `reply_<ID>.txt` by some other backend or script) still gets diagnosed by the
same `annotation_for_response` validator inside the client itself, so reading an
annotation error never requires having used this helper.

## Build and run

Build the driver from the repository root:

```bash
cargo build --bin greedy_driver --manifest-path norrust_core/Cargo.toml
```

An executable deterministic run uses the committed orders fixture:

```bash
python -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --orders-file tools/fixtures/invalid_move_then_end_turn.jsonl \
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

`text` is the model's raw reply: an annotated action envelope or an allowed
inspection request, as described below. The client also accepts bare action arrays
and records their annotations as missing. After inspection, return final actions
with decisions or request another permitted inspection within the tool budget.
The command-backend envelope remains unchanged for these calls:
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

Use `tools.codex_backend` for native Codex sessions and provide a unique session
sidecar for every match. Set `NORRUST_CODEX_MODEL` to the model identifier and
`NORRUST_CODEX_REASONING_EFFORT` to the desired effort (default `high`). The
adapter name identifies the Codex runtime; it does not select a model. With the
driver built as above, replace `MODEL_ID` and the match directory before running:

```bash
NORRUST_CODEX_MODEL=MODEL_ID \
NORRUST_CODEX_REASONING_EFFORT=high \
NORRUST_CODEX_SESSION_FILE=/path/to/match/session.json \
python3 -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --model-command 'python3 -m tools.codex_backend' \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 2001 --llm-side 0 --max-turns 50 \
  --reasoning-effort high --model-timeout 900 --turn-timeout 2100 \
  --log /path/to/match/match.ndjson
```

The model and effort are configuration values. The adapter uses read-only sandboxing
when creating the thread and records the native thread, resolved requested
settings, and transport. Runtime model/effort remain unknown because the consumed
native events do not confirm them. Unknown settings do not fail the client's
comparison; known contradictory requested/reported settings do. The prompt rejects
unrelated shell, web, file, skill, and connector use; the adapter fails if a
native response reports one of those tool classes.

`NORRUST_CODEX_ARTIFACT_DIR` selects the prompt/result/journal directory (default
`artifacts/` beside the session sidecar); `NORRUST_CODEX_MATCH_ID` selects its
logical match identity (default the resolved sidecar path). `NORRUST_CODEX_TIMEOUT`
sets the native request timeout in seconds (default 840). Give every concurrent
match its own sidecar, artifacts, and identity. These commands require POSIX
process groups and `fcntl` locking.

The example gives the backend's 840-second timeout room to finish before the
client's 900-second command timeout. Its 2100-second turn budget covers the
default 300-second query budget and two model calls for an action repair.

The client records its `--reasoning-effort` expectation separately; configure the
backend's effort too. The journal, result, and session sidecar record
`requested_model` and `requested_reasoning_effort` separately from runtime fields.
In client metadata, the backend values are named `backend_requested_model` and
`backend_requested_reasoning_effort`; `requested_reasoning_effort` holds the
client's expectation. The backend result, sidecar, and reply `cache` use
`runtime_model: null`, `runtime_reasoning_effort: null`, and
`runtime_settings_source: "not_reported"` until the native evidence confirms
runtime settings. A requested value is not runtime confirmation.

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

To concede, use `[{"action":"Resign"}]` as the envelope's `actions`, with a
decision group citing T8. Bare resignation arrays are also accepted, with missing
annotations. Resign must be the only action and has
no additional fields. The driver immediately records `reason: "resignation"`,
`resigned_side`, and the opponent as `winner`. It runs no greedy sweep or opponent
turn and does not increment completed side-turns or the state revision.
Resignation is accepted in both turn modes, including after committed partial
batches; those earlier actions remain recorded. It is a gameplay-valid loss
(client exit 0), and the completed log cannot be resumed in place.

The model should concede when the current evidence shows no credible route to
recovery or victory, rather than prolonging a clearly lost game. Being behind,
a bad combat roll, or a temporary threat alone is insufficient. These instructions
are included in every prompt through [LLM_TACTICAL_PLAYBOOK.md](LLM_TACTICAL_PLAYBOOK.md).
A resignation needs no tactical preview, draft review, or confirmation; it can
also replace a draft during review or repair. `preview_batch` rejects resignation
candidates because concession is a match decision rather than a tactical forecast.

On its first response for a turn, the model returns either its final action envelope
or one read-only preview request containing one or two complete candidate arrays:

```json
{"tool":"preview_batch","candidates":[[{"action":"EndTurn"}],[{"action":"Move","unit_id":12,"col":4,"row":7},{"action":"EndTurn"}]]}
```

Each candidate follows the same action-batch rules as a final response. The
preview does not submit actions or mutate the live state. A player-requested
preview uses `mode=bounded_rollout`, giving a labeled sampled comparison of one
or two candidates through the candidate finish and at most one Greedy opponent
response. The engine's ordinary `mode=forecast` remains available to internal
consumers. During the existing single draft review, the client may request
`mode=bounded_rollout`: that isolated query
uses a fixed evaluation seed, applies the candidate's exact finish, and runs at
most one driver-greedy opponent response. It reports post-finish and
post-opponent snapshots as an illustration, with policy, seed, sampling, and
coverage labels. Both player-requested previews and automatic draft reviews enclose
simulated outcomes in `SIMULATION — NOT EXECUTED BEGIN`/`END` markers, followed
by the authoritative live-state reminder. Simulated rosters, gold, casualties,
villages, and winners are hypothetical and do not
replace the live observation. It never mutates live state or claims that one
sampled branch is a probability or a best move. Queries themselves execute no
actions. The model may also inspect one friendly unit at a time:

If the driver rejects a preview candidate with one of the supported candidate
codes (`parse`, `batch_too_large`, `action_limit`, `partial_limit`,
`unauthorized_unit`, or `UnitNotFound`), the client records the code, message,
candidate index, and rejected draft, then gives the model one bounded repair
from the unchanged live revision. Transport, protocol, checkpoint, and unknown
codes remain infrastructure errors; they are never treated as a valid preview.

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
The tactical card's `focus_p` and `focus_e` report kill probabilities and
expected cumulative damage for the best origin-compatible volleys of one, two,
and three distinct attackers across all supplied legal attack origins. Equal
kill probabilities are ranked by expected damage. Each attacker is assumed to
deliver its full volley: retaliation and subsequent board changes are ignored.
A zero can mean no compatible sequence of that size; it does not establish
safety against additional attackers or routes opened by earlier actions.
`max_sum` separately adds maximum volleys without enforcing origin compatibility.
All compact forecast `e`/`focus_e` values use tenths of HP (`24` means `2.4` HP);
`p`/`focus_p` use basis points (`6400` means `64%`). Direct `m`/`max_damage` values
remain whole HP. Preview outcomes are hypothetical, and sampled combat results
do not establish certain outcomes.
Automatic draft review compares
the draft with an unchanged `EndTurn` baseline and labels reply exposure with
the assumption that forecast combatants survive in place. Whole-force `FORCE`
and mechanical `RECRUIT` lines are observations; they do not force recruitment
and saving gold remains legal.

A final action array is a non-empty JSON array of at most 256 objects. Every
object has exactly the fields shown below. Except for standalone resignation,
there is exactly one final
`DoneWithImportantMoves`, `EndTurn`, or `FinishWithGreedy` boundary; no action follows it.
On turns where a submitted draft leaves the recruiter in projected lethal
danger, the client sends one read-only draft result back to the model. The
model may repeat the draft to confirm it or return a revised final array; the
client never refuses a confirmed dangerous batch.
Immediately before requesting final actions, the prompt includes one
authoritative `LIVE_STATE` reminder derived from the latest engine observation.
Use its revision, controlled side, both sides' gold and unit/HP totals, and the
friendly unit and recruiter IDs/HP/positions. A preview or model text cannot
replace these facts. A revised batch starts from this live revision; a rolled-back
batch leaves it unchanged. After an accepted partial batch, the reminder is
refreshed from the new live observation.
Recruitment and deployment priorities live in [T0](LLM_TACTICAL_PLAYBOOK.md).
The client supplies legal capacity and macro semantics; saving gold is legal.

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
It may exceed the initially empty castle spaces: the driver can vacate eligible
occupants, recruit into freed placements, and repeat while gold and legal
capacity permit. This trades the vacating units' movement and positional safety
for additional recruitment; it does not invent capacity or promise the
requested count.
`Advance` has integer `unit_id` and exactly one selector: integer `target_index`
or string `def_id`; `target_index` indexes that unit's `advances_to` list in the
order shown in the board data. `DoneWithImportantMoves` and `EndTurn` have only
`action`. `FinishWithGreedy` accepts explicit groups and holds; its groups may
be empty when every remaining unit is protected. Each hold reason is a string
of at most 120 characters (the client counts characters, not UTF-8 bytes), and
held IDs must be disjoint from delegated group IDs and from other held IDs.
Explain consequential holds with the existing reason, expected, and risk
fields.

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

`TYPE` resistance descriptions use signed incoming-damage modifiers. Positive
values are vulnerabilities (`arcane: takes 40% more damage`); negative values
are resistances (`cold: takes 60% less damage`); zero means unchanged damage.
Missing resistance data is unknown. These descriptions are the base modifier
before other combat effects, and engine forecasts remain authoritative. Raw
signed fields remain available in diagnostic output and archives.

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

Terminal reasons `winner`, `max_turns`, and `resignation` are gameplay-valid. A rejected batch
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
