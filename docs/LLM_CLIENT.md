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
Prompt layout `prompt_layout_v2` keeps canonical rules first, followed by fixed
match facts, geometry-only terrain, and available unit types. History and live
board data follow those sections. `V-` marks a village in geometry; ownership
and occupancy remain live mappings. Maintained transports receive the complete
assembled prompt unchanged. Request records include fixed-prefix UTF-8 bytes
and a hash; these show cache eligibility, never a provider hit. Offline byte
comparisons use `python3 -m tools.prompt_cache_report --archive PATH`.
SQLite reports use `python3 -m tools.prompt_cache_report --db DB --game-id ID`
with optional `--model MODEL` and `--layout LAYOUT`; these filters select the
same physical calls as their linked prompt rows. Fireworks sends the supported
`x-session-affinity` header only when request context supplies a durable
conversation ID. Its value is stable for an in-place game/model resume and
changes for a fresh game or checkpoint branch. Missing context leaves affinity
unknown. Equal prompt prefixes and elapsed time do not establish cache hits or
processing speedups.

Preserve rule IDs when editing wording so recorded citations remain comparable;
the archived guide hash identifies the exact text used by a game.

### Decision annotations

Action responses may carry `{"actions":[...],"decisions":[...]}`. In batch mode,
decision groups should cover every authored action; focused mode may annotate
only consequential authored actions. The actions remain the ordinary action contract. Decision groups cite one to four stable
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

`MoveGroupToward` is the corresponding nonfinal movement macro. It accepts one to
eight unique living friendly IDs and an in-bounds rally hex, processes IDs in the
submitted order, and takes at most one legal step per unit strictly closer to the
target. The target may be occupied because it is a direction. It reports moved
and skipped IDs and returns control for another action in the same side turn. It
performs no attacks, recruiting, promotion, greedy sweep, EndTurn, or opponent
activation. Geometric progress does not establish safety, screen quality, or a
route around blockers. Explicitly listed recruiters may move and carry the same
loss-of-keep consequence as a manual move; omitted units are never added.

Advance ranged support with its screen, and use specific rescues and guards
while letting routine healthy units contribute. Hold only for a concrete
purpose, and explain consequential idle units or deliberate saving in the
existing hold reason and decision fields. Such explanations are evidence;
they do not create executable holds or add model calls. Material disadvantage
alone is insufficient justification for hopelessness, but resignation remains
an immediate standalone action.

The reusable fixed prompt section contains static `MAP_TERRAIN` geometry. Its
village glyph is always `V-`; ownership is supplied in the live data. The live
briefing retains `MAP_UNITS` occupancy and the strategic village owner rows.
Unit cells use `faction:id`, and `....` is empty. Odd rows are indented to
preserve the engine's odd-r hex geometry. The unit roster remains authoritative
for exact type, HP, and status. New fields that can change during a game belong
after `PROMPT_FIXED_CONTEXT_END` so they do not invalidate the reusable prefix.
Village totals are counted from live `terrain` tiles whose `terrain_id` is
`village` and their `owner` (`-1` is neutral). Missing terrain or ownership is
unknown; it is never reported as zero.

For pending friendly promotions, the compact roster includes the engine's
ordered `advances_to` choices. Use their exact definition names or zero-based
indices: `{"action":"Advance","unit_id":13,"def_id":"Bone Shooter"}` or
`{"action":"Advance","unit_id":13,"target_index":0}`. Supply exactly one
selector. A missing list is unknown, an empty list supplies no choice, and a
unit without a pending promotion cannot advance merely because its type has
an upgrade. The driver validates the action against the current state.

For an opt-in incremental turn, add `--incremental-turns`. The driver permits
accepted partial action arrays without `EndTurn`, returns a fresh state after
each one, and then requires a final array ending in `EndTurn`. The cap is
governed by `--max-partial-batches-per-turn` (default 3 in batch mode, 64 in
focused mode, configurable up to 1024 without overflow).
The state includes `turn_boundary`, `accepted_partial_batches`,
`remaining_partial_batches`, and `final_only`. A partial observation does not
run the opponent or reset the model turn; a failed partial batch is rolled back
without discarding earlier accepted batches. Checkpoints are published before
an accepted partial is acknowledged when `--log` is supplied.

### Decision modes and action encoding

`--decision-mode {batch,focused}` configures turn granularity:
- `batch` (default): full-turn planning. Incremental turns require explicit
  `--incremental-turns` and default to 3 partial batches, 8 model calls per turn,
  and 4 tool calls per turn. Decision annotations must cover all authored orders.
- `focused`: focused task loop over bounded incremental turns. Incremental turns
  are enabled by default, with defaults of up to 64 partial batches, 128 model
  calls, and 64 tool calls per turn. The model pursues at most one active task
  at a time, and decision annotations may cover only consequential actions.
  Exhausted tool calls do not force a premature `EndTurn` while `final_only` is False.
  The two tiers choose one small objective, inspect its target or preferably at
  most four relevant units when a missing fact matters, then enter a local
  execution phase. Inspect the target for an uncertain attack or the specific
  unit for an uncertain retreat; inspection is optional when the supplied legal
  actions already establish the objective. Any inspect_target, inspect_targets,
  or inspect_hex request may also carry one optional `purpose`: a string of at
  most 120 characters explaining why that inspection was requested. It is
  provisional and unverified, carried only alongside that inspection's local
  context, and rendered back with explicit untrusted-data framing; it is never
  a committed intent, rule, hold, or garrison, and the client never infers an
  action from it. The next request replaces the full tactical option rows with
  the exact inspected options and that purpose in an explicit untrusted-data
  block, plus compact revision-pinned live rows for referenced targets and
  matching support, named village ownership, and guardrails (side, current
  phase, the opponent's imminent phase this round, next round's phase,
  recruiter danger, economy, army IDs, and pending promotions). The projection
  also states its own scope explicitly, so a plan that reaches beyond the
  inspected entities is recognizable as unsupported by that local view alone.
  A matching assigned task is preferred; an unrelated task is reported as no
  match. A fresh inspection replaces that local task and its purpose. Accepted
  partial actions invalidate the local context and its purpose; an engine
  validation rollback keeps both for repair and another permitted inspection.
  An unavailable inspection result clears the local context and purpose rather
  than leaving a stale one. A rejected draft never promotes its purpose into
  committed memory, and neither survives into the next side turn. Legal action
  envelopes remain accepted without an inspection. Intent and agenda retain
  origin request, turn, and revision internally when available, and remain
  provisional rationale rather than rules or permanent garrisons.

`--action-encoding {coordinates,choices}` selects how actions are represented
(default `coordinates`).

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

An explicit `terminal` record and a classified typed terminal failure
(`model_error`, `budget_interrupted`, `query_error`, `checkpoint_error`,
`preflight_error`, or `observer_interrupted`) use the same resume guard.
Gameplay, model-invalid, budget, and intentional observer-interrupted outcomes
cannot be resumed in place; an infrastructure outcome remains eligible for
recovery. A durable watchdog stop is written before cancellation, and a
supervisor marks it `accepted` only after checking the current run and cited
evidence. A pending stale request is resolved and cannot fence a later run.

For an operator or a validated observer to request a stop, use the run ID from
the watchdog state sidecar and the run's artifact parent:

```bash
python3 -m tools.watchdog_stop request \
  --run-id RUN_ID --root /path/to/artifacts \
  --reason-code manual_operator_stop --observed-sequence 0
```

The request is idempotent and does not signal processes itself. The supervisor
owns the client session and its nested provider/driver processes, attempts
graceful shutdown for five seconds, then force-cleans remaining owned
processes. It records `observer_interrupted` with the last proven checkpoint,
partial evidence coverage, and `remote_cancellation: unknown`; a remote request
may continue billing after local cancellation. A natural gameplay terminal
wins a stop race and is recorded as an ignored late recommendation. When a
checkpoint or action submission may have crossed the driver acknowledgement
boundary, the terminal also records `action_boundary_status: unknown`; resume
and reconciliation must preserve that uncertainty.

An in-place resume appends to the same archive and retains the conversation ID.
Request and batch IDs continue after archived attempts, including failures, and
the latest client failure metadata supplies cumulative counters.

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
batch is accepted. Rejected metadata keeps the committed agenda and adds a
correction to subsequent requests, linked to its original request and revision.
For a complete valid finish with no own delegated sweep, use
`{"actions":[{"action":"FinishWithGreedy","groups":[],"holds":[]}]}`.
It still ends the turn and permits the opponent response; executable holds
apply only to that finish.
The correction expires on an accepted replacement or the end of that side turn.
An error in the ending response is delivered once on the next own turn;
checkpoint resume preserves pending feedback without resurrecting expired errors.
The correction does not claim that rejected or rolled-back actions executed.
Each observation includes a compact `current_turn_readiness` card unless
`--disable-agenda-sweep` is passed. It is live to the displayed `turn` and
`state_revision`, with explicit `moved_this_turn`, `attacked_this_turn`,
`agenda_unassigned`, and `agenda_holds` lists; it is not prior finish
provenance. In a selective finish, only listed group IDs are swept and listed
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

## Usage accounting: launch, handoff, collection, and final report

### Bounded watchdog observer

The optional watchdog is a separate, tool-free observer channel.  It is
disabled by default and may run in `observe` mode (recommendations recorded)
or `enforce` mode (a validated durable stop may be submitted).  Its direct
OpenAI Responses backend uses `NORRUST_OPENAI_API_KEY`, model
`gpt-5.4-nano`, reasoning effort `none`, `max_output_tokens=512`, and a
30-second request deadline.  These fields and the candidate model's Responses
support are verified against the [official GPT-5.4 nano model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-nano)
and [Responses create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).
It sends a fresh bounded status packet on each
check, never the player's canonical prompt or conversation history, and makes
no automatic retries.  The controller reserves each physical call and its
512-token allowance in a run-owned state file before dispatch; the ceiling is
20 calls including failures and one investigation follow-up.  An unavailable
observer disables advisory checks while the independent game watchdog keeps
running.

Observer usage is written as `call_role: "observer"` in the run-owned usage
sidecar.  Player calls retain `call_role: "player"`; historical rows without
that field remain `unknown`.  SQLite usage reports expose player, observer,
unknown, and combined coverage separately, and the player's online token
budget and prompt-cache/bakeoff reports exclude explicit observer calls.
Unknown usage has no fabricated cost.  A semantic stop in enforce mode requires
an `inspect` investigation and repeated non-progress evidence across two fresh
observations with no recovery; a long request, poor tactics, or a negative
material balance alone cannot stop a healthy game.  The observer's `run_id` is
separate from the catalog `game_id`; launchers must pass the proven catalog ID
when they want its sidecar imported.

The maintained supervisor exposes the same opt-in channel for real runs:

```bash
python3 -m tools.llm_supervisor --log /absolute/run/match.ndjson \
  --watchdog-mode observe --watchdog-model gpt-5.4-nano -- \
  python3 -m tools.llm_client --log /absolute/run/match.ndjson ...
```

`--watchdog-mode` defaults to `off`; `enforce` is the only mode that can
write a durable stop intent. The supervisor attaches lazily after the
recorder has published a proven catalog conversation identity, polls the
recorder packet without blocking the player, and closes the observer promptly
when the child exits. Offline evaluation injects `FakeObserverBackend` through
the Python `run(..., observer_backend=...)` API and may set
`observer_max_calls=3`; this never authorizes a paid request.

Every model game must produce measured or explicitly UNKNOWN token usage --
never a silently omitted or fabricated number. This is the authoritative
procedure; whatever launches a game (a script, an agent, or a human) follows
it regardless of which player shape it drives. `docs/GAME_HISTORY.md`
documents the query/coverage semantics this procedure feeds;
`docs/AGENT_GUIDE.md` distinguishes catalog absence from recoverable host
evidence; `AGENTS.md` only routes launchers to this section, it does not
duplicate it.

### What the client and a maintained adapter record automatically

For a matched offline or live comparison, use the maintained
`tools.model_bakeoff` entry point described in [`MODEL_BAKEOFF.md`](MODEL_BAKEOFF.md).
Its report joins usage by physical `model_calls` identities from the SQLite
catalog. A proposal in `forwarded_orders` is counted as a committed useful
action only when the driver records the corresponding `source=llm` event;
missing event or token evidence stays unknown.

`tools/llm_client.py` allocates a stable harness request ID before every
dispatch and publishes it -- with the current side-turn identity, live
revision, controlled side, and requested settings -- to
`NORRUST_REQUEST_CONTEXT_FILE` (`write_request_context`) before the model
command runs, so a call that never returns is still attributable. It also
durably records `side_turn_started` the moment a side turn opens, with a
stable `side_turn_id`, before that turn's first model request, so usage
spent on a turn that is interrupted before `EndTurn` still belongs to an
open turn rather than being lost.

A maintained API adapter records its own usage automatically, including on
failure. `tools/fireworks_backend.py` appends a `"dispatch"` line to a
match-owned `usage.ndjson` sidecar immediately before its network call and a
`"final"` line immediately after a response or error is known -- covering
empty content, `finish_reason: length`, HTTP errors, and malformed bodies.
`tools.game_history.import_game` reads that sidecar automatically as part of
a normal import; no separate collection step exists or is needed for this
shape. This is the **direct API player**: launch `tools/llm_client.py` with
`--model-command 'python3 -m tools.fireworks_backend ...'`, run the game to
completion or interruption, then import -- usage is already durable on disk
however the game ended.

For long Fireworks replies, add `--stream` to the maintained model command:

```bash
python3 -m tools.llm_client \
  --model-command 'python3 -m tools.fireworks_backend --stream' \
  --model accounts/fireworks/models/deepseek-v4-flash-0731 \
  --log /absolute/run/match.ndjson
```

The adapter requests `stream_options: {"include_usage": true}` and waits for
both a supported finish reason and `data: [DONE]` before emitting its one JSON
reply. Content and provider reasoning are accumulated separately; a timeout,
EOF, malformed frame, HTTP error, or missing credentials produces no action
reply and is recorded as unknown or locally blocked according to the normal
usage policy. Use `--evidence-dir /absolute/run/fireworks-evidence` (or
`NORRUST_EVIDENCE_DIR`) to retain the exact prompt, hash, request payload and
context, flushed received chunks, and a completed or incomplete receipt. An
interrupted stream is never retried by the adapter; the client may apply its
existing output-limit policy only to a provider `finish_reason: length`.
The transport follows Fireworks' [chat completions API](https://docs.fireworks.ai/api-reference/post-chatcompletions)
and its [reasoning stream fields](https://docs.fireworks.ai/guides/reasoning).
Raw provider `reasoning_content` is retained in each evidence receipt's
assembled response or partial receipt; it is diagnostic provider evidence and
is not imported as SQLite decision annotations. Decision annotations remain
the separately authored and archived `decisions` records.

#### Reasoning effort: explicit pass-through and provenance

`tools.llm_client`'s `--reasoning-effort` is a generic client-level option;
`tools/fireworks_backend.py` sends only the values it has verified are
meaningful for the model actually being played, and rejects anything else
before any network call. As of 2026-09-11, verified against the
[Z.ai GLM-5.3-Flash model card](https://huggingface.co/zai-org/GLM-5.3-Flash),
the [vLLM recipe](https://recipes.vllm.ai/zai-org/GLM-5.3-Flash), and
[Fireworks' reasoning guide](https://docs.fireworks.ai/guides/reasoning) plus
its [chat completions reference](https://docs.fireworks.ai/api-reference/post-chatcompletions),
the adapter accepts exactly `low`, `high`, and `max` -- GLM-5.3-Flash's own
three documented levels, defaulting to `max` when the field is omitted.
Fireworks' generic `reasoning_effort` surface additionally lists `medium` for
other reasoning models, but GLM-5.3-Flash's chat template silently resolves
any value outside `{low, high, max}` to `max`; sending `medium` here would be
exactly the silent nearby-value substitution this adapter must not perform,
so it is rejected like any other unsupported value.

Pass the option once, on the client:

```bash
python3 -m tools.llm_client \
  --model-command 'python3 -m tools.fireworks_backend' \
  --model accounts/fireworks/models/glm-5p3-flash \
  --reasoning-effort low \
  --log /absolute/run/match.ndjson
```

The client writes the requested value into the per-dispatch request context
(`requested_reasoning_effort`) alongside the existing `output_limit`, and the
adapter reads it from there -- the same pattern `--max-output-tokens` uses.
Configuring it a second time inside `--model-command` (its own
`--reasoning-effort` flag, meant for standalone/manual runs with no harness
context present) is rejected, exactly like the existing `--max-output-tokens`
conflict check.

**Omitting the option is the byte-identical default.** With no requested
effort, the request payload carries no `reasoning_effort` field at all --
identical to every payload this adapter sent before this option existed --
so the provider/model default (`max`, per GLM-5.3-Flash's own documentation)
applies. This is required for a retest that is authorized to compare
providers only under otherwise-unchanged settings; do not pass an explicit
effort into that retest.

**Requested and reported provenance are separate fields, and are not the
same claim.** `requested_reasoning_effort` is exactly what the adapter sent
(or `None`/unknown when the option was omitted). `runtime_reasoning_effort`
is what the provider reported having actually applied; Fireworks' response
schema carries no such field (verified against the API reference above), so
this stays `None`/unknown regardless of what was requested -- the adapter
never claims a runtime effort the provider did not report. Both fields flow
through the existing reply cache (`tools.llm_client.apply_backend_settings`,
which also raises if a backend's requested/runtime effort conflicts with what
the client asked for), into the usage sidecar (`ModelCall.requested_reasoning_effort`
/ `reported_reasoning_effort`), and from there into a normal
`tools.game_history` import.

Comparing low/high reasoning effort on fixed positions is a separate,
subsequent experiment requiring its own authorization; implementing the
pass-through is not itself a live bakeoff, and this adapter never makes a
paid provider call as part of its own tests.

### Binding a host thread: the launching parent's job

A **parent agent driving a player** whose own inference calls the harness
cannot see directly (a Codex-native session today; any future host with its
own evidence tomorrow) is not exempt from accounting just because it isn't a
subagent -- "no subagent" never exempts a run from usage collection; a direct
agent player follows the same binding and collection procedure. Before or at
launch, the parent captures an explicit, match-owned binding: the game's
`game_id`, the actual host thread ID, the exact path to that host's evidence
file, the game's own log path, and the request-handshake directory (the
file-transport `requests/` directory that accumulates
`handshake_log.ndjson`, written by `tools/file_backend.py`). Never infer this
binding from "the most recently active session" or from a model name --
`tools/collect_model_usage.py`'s `load_manifest` refuses to guess it, and a
launcher must not either.

After the game completes OR is interrupted, and BEFORE import and the final
report, the parent collects and reconciles host usage:

```bash
python3 -m tools.collect_model_usage --manifest /absolute/path/manifest.json \
  --write-sidecar /absolute/run/usage.ndjson
```

`--manifest` names a JSON file with exactly `game_id`, `host_thread_id`,
`host_evidence_path`, `game_log_path`, and `request_handshake_dir`. This is
currently implemented for Codex host sessions: it reads `token_usage_record`
entries from the host's own rollout evidence and normalizes them through the
Stack 1 contract (`tools.model_usage.CODEX_USAGE_MAP`); cumulative
`token_count`/turn/thread totals are reconciliation evidence only and are
never summed into call rows. It links a call to its owning harness request
only through a proven handshake window -- the file-transport's own
`published_at`/`answered_at` timestamps in `handshake_log.ndjson`, never
timestamp proximity or nth-call pairing (`link_calls_via_handshake`). An
unproven call is written unlinked and still counts toward the game total.

Check `is_thread_finalized`, or the command's own `finalized` field, before
treating collection as complete: an unfinalized thread (no `task_complete`
observed) means collection is provisional and should be repeated once the
host thread actually finishes. Restarting the collector against the same
manifest and evidence file is idempotent -- it produces the same call IDs and
rows every time, so repeating it after an interruption is always safe.

For a host with no maintained collector (there is currently only the
Codex-native one), host usage for that player's own inference is UNKNOWN --
say so explicitly in the final report rather than reporting an empty or
invented total.

### The persistent player subagent

A player subagent (see `tmp/quick-play.md` for a worked recipe) uses the
maintained file transport: `tools/file_backend.py` writes the harness's
request context alongside its own transport handshake
(`handshake_log.ndjson`), and the subagent publishes its reply only through
`tools.publish_reply`, never by writing `reply_<ID>.txt` directly. This
preserves the request IDs and timing windows that later usage collection
depends on.

The subagent must never estimate, self-report, or invent its own token
counts, and must never place usage fields in its action JSON -- a model's
self-claimed usage is exactly as unreliable as its self-claimed identity (see
"Record who played" below), and inventing counts to fill a gap is worse than
reporting the gap honestly. If a tool/context interruption stops the
subagent mid-game, it reports its last processed request ID so the SAME
subagent can be resumed with that context; the parent does not start a
replacement subagent or treat the interruption as closing out the game's
usage accounting.

### Final report

Whatever launched the game -- direct API player, parent-bound host session,
or persistent subagent -- the final report always includes usage totals and
coverage: run `python3 -m tools.game_history usage --db DB GAME_ID
--group-by game` (or `--json` for the structured form) after import and
quote its `measured` totals, `aggregate_only_request_ids`, and
`unassigned_calls`. An unsupported host, a not-yet-collected host thread, or
any other missing accounting is reported as explicitly UNKNOWN in the report
text -- never printed as zero, and never left out because "no number was
available."

## Build and run

### Output-token limits and retries

The shared harness starts supported API responses at **131,072 output tokens
(128k)**. Set `--max-output-tokens` on `tools.llm_client` to change that initial
limit; do not put the option inside its `--model-command`. The standalone
Fireworks adapter also defaults to 128k and accepts its own option when no
harness context is present.

When the provider explicitly ends a response with `finish_reason: length`,
the harness discards it as an action response, raises the limit directly to
**524,288 (512k)**, and retries the identical canonical prompt. The larger
limit remains in effect for the rest of the game. **Three output-exhaustion
failures at 512k stop the game**, including failures across different requests;
successful calls do not reset the count. The initial 128k failure is not one
of those three. This is a limit on repeated output exhaustion, not a cap on
all successful calls or a monetary budget.

In-place resume retains the raised limit and failure count. Durable
`model_output_limit` archive events record policy changes before another
attempt. The conventional `usage.ndjson` beside the game log also recovers
provider failures written just before a client interruption. A checkpoint
branch is a new game and starts with a new budget. Preserve the archive and
usage sidecar together; a harness-run Fireworks adapter requires that sidecar
location so resume and normal import use the same evidence.

Each attempt keeps the same harness request ID and exact prompt bytes, but has
its own physical call ID, recorded output limit and usage. A retry's
`retry_of_call_id` identifies the preceding exhausted call. Request usage sums
the attempts, including failures; missing counts remain unknown. Truncated
content is preserved as evidence even when it happens to be valid JSON.

The command-backend protocol represents exhaustion as a JSON envelope with
`error: {code: "output_limit", output_limit: N, call_id: "..."}`, plus optional
`text`, `usage`, and `cache`. Adapters read `output_limit` and
`retry_of_call_id` from `NORRUST_REQUEST_CONTEXT_FILE`. A reported limit that
does not match the harness request stops the run. Other provider errors,
unsupported limits/context sizes, malformed replies and timeouts do not
trigger token-limit escalation. There is no silent provider-specific clamp.

Existing `--model-timeout`, `--turn-timeout` and explicit usage checks remain
independent and can stop earlier. Large completions can exceed the usual short
game timeouts: choose suitable timeouts when launching such a run. Fireworks
uses the harness's per-attempt timeout, minus five seconds to report failures,
rather than a fixed 840-second HTTP timeout. No timeout is automatically
extended by an output-limit retry.

File, interactive and native-host players receive request context where
supported, but their hosts do not expose a maintained output-limit control or
typed exhaustion result here. The harness must not claim to enforce these
token limits or retry unknown host outcomes for them. This policy changes no
model-facing tactics, reasoning-effort settings, or chat roles.

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

### Cumulative game token ceiling

`--max-game-total-tokens N` optionally stops further dispatch after the existing
physical-call usage sidecar reports at least N total tokens for this game. It
counts failed calls and output-limit attempts once, without adding their combined
request totals. At most the current direct API call can overshoot. Existing
`--token-*-limit` flags still constrain replies, and the 131,072 → 524,288 output
escalation policy remains separate.

The guard reads durable evidence before each dispatch and after each attempt,
including a failed adapter response. An in-place restart retains the same game
identity, ceiling, and spend. A checkpoint branch is a new game with a fresh
budget. A host with post-run-only usage collection, missing usage, or an unmatched
request has `game_token_limit_enforced: false`; this is not a guaranteed spend
cap for that player. Hard call/time bounds still apply. Players must not estimate
or self-report tokens to fill those gaps. Budget stops are recorded interruptions,
not gameplay losses, and their open side-turn usage remains attributable.
Each dispatched request also receives a volatile budget snapshot with measured
spend, remaining allowance, and unknown sidecar calls or gaps. Unknown usage is
reported as a bounded upper allowance; output-limit retries reuse the same
snapshot and prompt bytes, while the next logical request refreshes it.

For matched task experiments, see [MODEL_BAKEOFF.md](MODEL_BAKEOFF.md). The launcher
still follows this document's usage-accounting procedure, including host binding,
collection after completion/interruption, import, and final coverage reporting.
The canonical client prompt supplies focused-mode instructions; a player need
not read the benchmark implementation or fixtures.

### Running a real match against a live model

Replace `--orders-file` with exactly one of `--interactive-model` or
`--model-command 'COMMAND'`.

**Record who played.** Pass `--player-model <id>` whenever the LLM side is a real
model. The client stores it as requested identity in the archive, the importer
copies it to `game_players.model_requested`, and the recorded-game browser and
replay both label the player from there. A backend that reports the host's model
overrides it; `model_reported` is only ever filled by such a backend, never from
this flag.

Transports differ in what they can report. The Codex adapter reports its own
runtime model. `tools/file_backend.py` cannot: it is a file adapter with no model
behind it, so a subagent or human player driving that transport is invisible to
the catalog unless the launcher names it. Without the flag the client prints a
warning at the end of the run and the game imports as an unnamed player, showing
as `LLM (model unavailable)` everywhere.

Do not have the player state its own model instead. A model's self-claim is
neither requested nor reported identity: it is unverified, models misidentify
their own version and variant, and putting a player's identity in its own context
contaminates any matched comparison it takes part in.

An `identity.json` sidecar beside the archive remains supported for recordings
already made without the flag. It supplies requested identity only, and is
ignored unless the seed, scenario, gold, cap and factions it repeats all match
the catalog, so a stale or copied sidecar cannot relabel a different game. Prefer
`--player-model`: it travels inside the archive and cannot be separated from it.

Model identity resolution distinguishes between verified canonical model matches,
unverified display labels (e.g. `Qwen 3.8 Max` vs canonical
`accounts/fireworks/models/qwen3p8-max`), and conflicting canonical IDs (e.g.
`accounts/fireworks/models/llama-v3p3-70b-instruct`). Display labels and leaf slugs
are treated as unverified labels without discarding output limits or treating them
as conflicting mismatches. An actual conflicting canonical ID is reported as a
mismatch while preserving raw identity evidence.

**`--model-command`** runs an automated backend. The command receives the full
prompt on **stdin** and must write **one JSON object** to **stdout**:

```json
{"text": "[{\"action\":\"EndTurn\"}]"}
```

`text` is the model's raw reply: an action envelope or an allowed inspection
request, as described below. The client also accepts bare action arrays and
records their annotations as missing. Read-only tools are bare objects with only
their documented keys and carry no actions, choices, intent, agenda, or decisions.
After a tool result, return final actions or request another permitted inspection
within the tool budget.
The command-backend envelope remains unchanged for these calls:
`{"text":"..."}`. Optionally include `usage`
(`{"input_tokens":N,"output_tokens":N}`); when absent, token budgets are recorded
as estimated rather than measured. A minimal backend:

```python
#!/usr/bin/env python3
import json, sys
prompt = sys.stdin.read()
reply = call_your_provider(prompt)        # returns a string
sys.stdout.write(json.dumps({"text": reply}))
```

The harness normalizes responses through a shared parser: both raw JSON and a
single complete fenced JSON payload surrounded by explanatory prose are accepted.
Do not emit multiple candidate code blocks, unclosed/truncated fences, or
unfenced JSON with surrounding text (greedy brace extraction is not used).

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

A focused task evaluation enables incremental turns by default and uses focused mode:

```bash
python -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --model-command 'python3 /path/to/your_backend.py' \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 2001 --llm-side 0 --max-turns 25 \
  --decision-mode focused --log /path/to/isolated/match.ndjson
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
repairs. In batch mode, inspection results requested during pre-submit repair
remain in every subsequent repair prompt, including across multiple inspections
and malformed responses. Focused mode keeps the structured local projection and
replaces its inspected operation when a new inspection succeeds; raw requests
and results remain in the archive without accumulating prompt copies. Tool
requests have their own four-request cap; physical model calls remain separately
recorded. Repeated illegal proposals remain a model-invalid result and are
recorded separately from infrastructure failures.

Execution parsing remains strict: a complete inspection object followed by
unfenced rationale is rejected as a model response. For the one existing syntax
repair, the client may classify only a complete recognized bare-tool object at
the beginning of that malformed response so it can preserve the pending lookup.
It never executes that prefix or an arbitrary brace fragment. A fully parsed
corrected bare-tool response is required before dispatch; final-only responses,
exhausted budgets, and the per-turn inspection limits still apply.

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
| `model_error` after one repair | backend emitted multiple candidate blocks, truncated fences, or invalid JSON | emit a single valid JSON payload (raw or single-fenced) |
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

Each candidate follows the same action-batch rules as a final response and
must end with exactly one of `DoneWithImportantMoves`, `EndTurn`, or
`FinishWithGreedy`; a candidate without a complete finish is rejected. The
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
actions. Automatic review also renders a compact sampled transition for the
actual proposed candidate: friendly movement through the own-finish stage and
friendly casualty IDs between the post-finish and post-opponent stages. Each
line identifies the friendly side, originating live revision, candidate index,
and whether it covers the initial-to-own-finish or own-finish-to-opponent-
response interval. A missing stage, side identity,
invalid candidate, or false coverage remains unknown; an empty fully covered
post-opponent roster means the sampled units were absent in that branch. These
are simulation facts only and do not veto or mutate a legal draft. The model
may inspect a small friendly group in one read-only request:

The preview result retains the query envelope's authoritative `state_revision`
at its top level, and nested per-candidate sampled-transition rows carry that
same envelope revision rather than reading a `state_revision` the driver put
only beside its body -- both the automatic-review preview
(`query_preview_batch`) and a player-requested `preview_batch` tool call
(`query_bounded_comparison`) apply this carry the same way. Automatic
`draft_review`, `draft_review_repair`, and `draft_review_decision` records
carry the generated `review_id` plus the exact request and `side_turn_id`
that produced them. This makes an automatic review auditable without
assigning it by call position; missing executor danger data continues to
render as unknown.

During the automatic review, the model may request at most one bounded
inspection (`inspect_target`, `inspect_units`, `inspect_targets`, or
`inspect_hex`) instead of returning final actions immediately -- resolving,
for example, an alternative attack the review's facts did not already cover.
It draws from the same `--max-tool-calls-per-turn` and
`--max-model-calls-per-turn` budgets as any other tool call (an inspection
plus its own follow-up completion both cost a model call, so at least two
calls must remain before the option is even offered); an exhausted budget
falls back to a tools-disallowed review exactly as before, with a
`draft_review_inspection` record naming the reason. The granted inspection's
compact result is appended to the same review prompt before one final
tools-disallowed completion -- never a second review slot, never a recursive
review cycle, and never more than the review's one existing commit. A
`draft_review_inspection` record (`granted`, `tool`, and `reason`) is written
either way, carrying the review's `review_id`, the triggering request's
identity, and the draft's own candidate digest and index, so normalized
review coverage stays complete alongside `draft_review`/`draft_review_repair`/
`draft_review_decision`.

If the driver rejects a preview candidate with one of the supported candidate
codes (`parse`, `batch_too_large`, `action_limit`, `partial_limit`,
`unauthorized_unit`, or `UnitNotFound`), the client records the code, message,
candidate index, and rejected draft, then gives the model one bounded repair
from the unchanged live revision. Transport, protocol, checkpoint, and unknown
codes remain infrastructure errors; they are never treated as a valid preview.

```json
{"tool":"inspect_units","unit_ids":[12,13]}
```

The request accepts one to eight unique, living, friendly IDs. A one-element
list inspects one unit through the same contract. The complete request is
validated before the driver is queried; a dead, enemy, malformed, or stale ID
fails the whole request and yields no partial result. Every successful member
is read at the same live revision. The result contains each unit's legal
destinations and legal targets from each origin with exact exchange forecasts.
It also includes `destination_threats`,
the next-turn threat summary for each legal position; these are facts, not
ranked move recommendations. Two other factual inspections are
available:

```json
{"tool":"inspect_target","unit_id":19,"purpose":"optional string, at most 120 characters"}
{"tool":"inspect_hex","col":4,"row":7,"phase":"next_opponent_turn","purpose":"optional string, at most 120 characters"}
```

`inspect_target` lists friendly attackers and origins for one enemy.

`inspect_targets` accepts `unit_ids` with one to eight unique visible enemy IDs
and returns the same inspections in one read-only query. It is separate from
the friendly `inspect_units` contract.
`inspect_hex` lists attack coverage for one hex either now or after the
deterministic next `EndTurn`; empty hexes have no invented combat forecast.
All three accept the same optional `purpose` string; any other key is still
rejected with today's "bare tool requests carry no action metadata" message.
Tool calls are read-only and revision pinned. `--max-tool-calls-per-turn` bounds
them (default 4), while `--max-model-calls-per-turn` remains the overall
model-call bound. Every tool follow-up reports the remaining budget. When no
tool call remains, the follow-up requires final actions only. If the model requests
another tool anyway, the client does not execute it; its correction prompt
retains all prior tool results and requires final actions. A second
`preview_batch` request is still not accepted. Review and repair prompts carry
the draft action list beside a bounded `DRAFT_RATIONALE_UNTRUSTED_DATA` block
containing only validated intent and decision metadata; an absent marker is
used when that rationale is unavailable. Rejected drafts are never committed
as continuity memory.

The normal card summarizes each unit with its current odd-r `(col,row)` hex,
legal movement destinations, live moved/attacked flags, attackable target IDs,
and attacks available from its current hex. Inspect the
active-task units together when a specific decision needs detailed origins; do
not inspect the whole army by default. Movable origins and their target
combinations are returned by `inspect_units`; `--diagnostic` retains the
complete JSON surface.
The default `EVENTS` block is an `EVENT_DIGEST`: compact grouped movement,
recruitment, attack, gold, village, and turn-boundary facts. Diagnostic mode
retains the raw event objects.
`--decision-metrics` adds one read-only preview of the final model-authored
batch to the log so evaluations can compare recruiter danger and remaining
recruitment before and after the decision.
The tactical card's readable focus fields report kill probabilities and
expected cumulative damage for the best origin-compatible volleys of one, two,
and three distinct attackers across all supplied legal attack origins. Equal
kill probabilities are ranked by expected damage. Each attacker is assumed to
deliver its full volley; damage per successful strike is fixed after modifiers,
with no random damage dice. Retaliation and subsequent board changes are
ignored. Unit TYPE alignment/profile and inspected retaliation are authoritative.
A zero can mean no compatible sequence of that size; it does not establish
safety against additional attackers or routes opened by earlier actions.
Maximum incoming and maximum damage values are displayed in whole HP. Exchange
outcomes are named defender-killed, both-survive, and attacker-killed; expected
damage names damage to the defender and attacker retaliation. Focus values are
named kill-by-1/2/3 attackers and damage-from-1/2/3 attackers. The underlying
`outcome_bps`, `expected_damage_tenths`, and `max_damage` fields remain raw
integers in engine/archive data. Preview outcomes are hypothetical, and sampled combat results
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
{"action":"MoveGroupToward","unit_ids":[12,13],"col":8,"row":6}
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
fields; give a concrete purpose and a condition for revisiting or releasing a
hold. A hold is turn-local execution policy, not a permanent garrison.

`MoveGroupToward` has integer `col` and `row`, plus a `unit_ids` array
containing one to eight unique living friendly IDs. It is a nonfinal
movement-only macro; the client forwards it as one authored action and the
driver expands it into ordinary legal moves. A unit with no improving
destination or spent movement is reported as skipped. The generated moves
retain delegated provenance and are not separately authored actions or decision
annotation indices.

The client rejects malformed JSON, unknown fields, missing fields, non-integer
numeric fields, non-positive batch counts, and invalid batch structure before
forwarding it. A malformed bare tool receives one type-preserving repair request;
its tool and candidates/IDs remain pending until corrected. A malformed action
validation failure may receive one repair call from the model;
if the driver rejects a submitted batch, the entire batch was rolled back. The
repair prompt reports that no prefix action committed and requires replanning
from the unchanged observation using authoritative options.
provider/model/query failures are infrastructure-invalid results with a nonzero
client exit, not gameplay losses or draws. A driver status rejection after
forwarding an action is also recorded as infrastructure-invalid so the client
cannot wait indefinitely for a new boundary.

`Engage` may use an attacker already on a legal current attack hex: put that
current coordinate in its step and do not add a `Move`. A driver validation
`failed_index` identifies the submitted top-level action-array entry before
`Engage` or `MoveGroupToward` expands internal steps. It is not a choices
handle index when an `expansion_mapping` is present; nested failures retain
their step/index and subaction context. In incremental mode, observe fresh
state after each accepted batch. Primitive actions within one batch execute
against its transactional observation without an intermediate model update.

Committed continuity reports authored and delegated events separately from the
automatic opponent response. Casualty IDs are qualified by `llm`,
`delegated_greedy`, or `greedy`; an absent or unfamiliar source remains
`unknown` rather than being attributed to the authored batch.

### Choices mode and action handles

When `--action-encoding choices` is enabled, the prompt and unit inspection results
expose legal operations with deterministic, revision-bound handles in the format
`c_<revision>_<hash>`.

The model may reply with a choices envelope instead of explicit primitive actions:

```json
{"choices": ["c_338_1a2b3c4d"], "decisions": [{"orders": [0], "rules": ["T2"], "expected": "Attack adjacent target", "risk": "none"}]}
```

Key semantics for choices mode:
- **Mutual exclusivity**: An envelope contains either `choices` or `actions`, never both.
- **Revision binding**: Handles are bound to the exact engine `state_revision`. When the state advances (after an accepted action batch or turn transition), previous handles are invalidated. Repeated inspections at the same revision produce identical, stable handles.
- **Resolution**: Handles resolve deterministically to engine operations: moves, standing attacks, move-and-attack sequences, recruitment, or advancement. Decision indices (`orders`) refer to authored choices, and the client records the expansion mapping back to the primitive actions.
- **Coordinate fallback**: Coordinate actions remain permitted via the `actions` envelope (for instance, to issue `DoneWithImportantMoves`, `EndTurn`, `Resign`, or macros). Every such use is recorded in telemetry as a coordinate fallback.
- **Validation**: Unknown, stale, cross-game, or malformed handles are rejected before submission. Conflicting choices (such as two units moving to the same destination) roll back transactionally without changing state revision, allowing repair.

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
`TYPE` ability cards preserve known empty abilities as `none`; an absent ability
field is `unknown`. Known meanings are supplied by the driver, including
`regenerates_N` (heals N HP at the start of that side's turn and cures poison)
and `leadership` (adjacent lower-level allies deal 25% more damage per level
difference). Unrecognized abilities retain their name with `meaning unknown`.
The tactical surface also supplies both faction names and their known recruit
pools, plus the engine's phase table: Dawn and Dusk are neutral, Day is
lawful +25% / chaotic -25%, and Night reverses those modifiers; neutral
alignment is unaffected. Current, imminent-opponent, and next-round phases are
shown separately.

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
An explicit `budget_interrupted` stop is a separate non-gameplay, non-model-fault
outcome (exit 3). It preserves no winner and is not eligible for automatic
resume; a fresh game or explicitly prepared checkpoint branch must choose a new
budget. The client uses it for the game token ceiling and model/tool call budget
stops, including a stop reached while repairing a response.
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


## Automatic progress recording

`tools.llm_supervisor` records progress during open provider requests without
calling another model. It creates `<log stem>.watchdog/` beside the game log
and supplies run-owned request-context and streaming-evidence paths to the client.
Each run receives a persisted unique watchdog ID; it is separate from the
player conversation and the SQLite game ID. Use a separate directory per game.

```bash
python3 -m tools.llm_supervisor --log /absolute/run/match.ndjson -- \
  python3 -m tools.llm_client --log /absolute/run/match.ndjson \
  --model-command 'python3 -m tools.fireworks_backend --stream'
python3 -m tools.run_watchdog status /absolute/run/match.watchdog
python3 -m tools.run_watchdog read /absolute/run/match.watchdog EVIDENCE_ID --limit 2048
```

Status reads return the last published packet without becoming a second recorder.
The packet separates confirmed live progress, proposed orders, request activity,
and received stream bytes. Evidence reads validate the recorded source range;
stream references expose decoded content with raw provenance. Available provider
receipts supply usage; missing or dispatched-only receipts remain unknown. The
raw archive is preserved for one later review. The `watch` command is for an
unsupervised/offline log only; do not run a second recorder alongside a supervisor.
