# Game history

Each game has one authoritative `snapshots` collection: an ordered, deduplicated
timeline of every provable board state the archive contains, built from logged
`state` records and validated driver checkpoints. Snapshots are ordered by where
their evidence first appears in the archive, not by revision number, since a
resumed game can restart the revision counter. A checkpoint is folded onto an
existing snapshot only when it proves the same execution state (matching
revision and, when both are known, matching completed side-turn count);
otherwise the importer tries to make it a renderable snapshot in its own right
by running the read-only `dump_checkpoint` binary (built alongside
`greedy_driver`; located via `NORRUST_DUMP_CHECKPOINT_BIN` or the conventional
Cargo target directory), which restores the checkpoint's `SaveState` against
the current unit/terrain registries and prints the same state shape a logged
`state` line carries. When that tool is unavailable, or a checkpoint names a
unit/terrain definition that registry no longer has, the checkpoint still
becomes its own snapshot -- carrying identity, round, side, and
completed-turn-count evidence -- but without a renderable state, and the
reason (`checkpoint_not_renderable:<path>:<reason>`) is recorded as a coverage
gap rather than silently rendered from today's data or silently dropped. A
`boundary_kind` of `opening`, `partial`, `side_turn_end`, `terminal`,
or `resume_checkpoint` labels what each snapshot represents. `side_turns` rows
reference `start_snapshot_id`/`end_snapshot_id` rather than holding a second
authoritative copy of the states; `endpoint_link_kind` is `evidence` when both
endpoints are renderable, `checkpoint_proof` when linked only through a
checkpoint, or `unknown` when no exact-revision snapshot exists on one side.
There is no "closest preceding state" fallback: a boundary without a proven
endpoint stays unknown.

Each game's `coverage_json` (also exported as `metadata.coverage` in a replay
bundle) separates the recorded engine result from replay coverage:
`opening_present`, `terminal_present`, and bounded `gaps`/`conflicts` lists
(e.g. `checkpoint_unavailable:<path>:<reason>`, `conflict:revision:<n>:...`,
`unresolved_turn_endpoints:<n>`). Completeness is never a guessed ratio. A
complete game whose archive never proves an ending stays `terminal_present:
false` — an incomplete replay, not a fabricated one.

Model requests and forwarded action batches carry `side_turn_id` when the log
contains a provable state revision, side-turn, or stable review identity. Missing
linkage remains NULL; imports never attach the nth review or snapshot by position.
Review IDs, candidate digests, forced partial-limit finishes, and review outcomes
remain in the archived log/metrics JSON for ad hoc analysis and training-data
selection.

Each accepted `turn_boundary` record carries the side, round, and both an
explicit `start_revision` (the state revision at which that side's turn
began, from the most recent full boundary) and `state_revision` (the revision
right after that side's own batch, before any opponent response). Recording
both lets a completed turn bind to an exact snapshot on both ends instead of
leaving `start_revision` unresolved on every turn. A game's terminal record
(`type:"terminal"` in the log) always carries an explicit `state_revision` and
`side_turns`, whatever ended the match — a model or Greedy win, the turn cap,
a timeout, an infrastructure failure, or a clean EOF — so a boundary count is
never confused with a round count or misread as a gameplay win. When the
match ended without the driver having already printed a matching `state`
line (a winning partial batch that never called `EndTurn`, or a win that
lands before the next boundary would otherwise print), the driver embeds the
exact ending snapshot inside its `game_end` line under `state` instead of
printing a second top-level `type:"state"` line — a live client reads any
bare one as "keep playing" and would query the now-exiting process. The
importer treats an embedded terminal `state` exactly like a logged `state`
line for snapshot purposes.

The opening is recorded the same way, for the same reason. Before either side
acts, the driver prints a `game_start` line carrying the pre-action snapshot
under `state`. Without it a game whose model side never receives a turn — the
opponent moving first, or winning outright on the opening position — would have
no provable opening at all. Consumers that read the stream positionally must
expect this record between `protocol` and the first playable `state`.

`coverage` counts a turn boundary as an unresolved endpoint when either end
lacks an exact-revision snapshot, and additionally reports
`unresolved_turn_starts` and `unresolved_turn_ends` separately. The split
matters for archives recorded before the driver emitted `start_revision`: those
games can recover every turn ENDING from their saved checkpoints while no turn
START is provable, and the combined count alone would make a fully recovered
legacy timeline look as broken as one with no endings at all.

A single snapshot can hold both roles. When a match ends before any state
change — a turn-one resignation, or a win on the opening position — the opening
and the terminal coalesce into one proven state. `boundary_kind` carries only
one label, so the opening role is tracked separately rather than inferred from
it; `coverage.opening_present` and `terminal_present` are then both true for
that one snapshot.

## Executed events

Each game has an `events` table holding every individually executed driver
event in original archive order -- moves, attacks, recruitment, healing, gold
changes, and so on -- separate from the `snapshots` timeline. Importing events
does not turn them into board frames: playback still visits saved snapshots,
and this table adds no animation and no intermediate state reconstruction. The
primary key is `(game_id, event_sequence)`, 1-based across every event
imported for that game; `(game_id, record_sequence, event_index)` is unique
and traces each row back to its exact source position (the 1-based NDJSON
record and the 0-based position within that record's `events` array) -- an
identical event payload recorded at a different log position is a second row,
never a merged duplicate. `side_turn_id` indexes into `side_turns` for turn
queries.

The importer reads only real `type: driver` records whose `line.type` is
`"events"` -- never proposed actions, preview/simulation payloads, or moves
inferred from snapshot differences. A move stores the moved unit's ID and its
`(col,row)` endpoints, not every traversed hex; an attack stores the recorded
exchange result (both units' resulting HP/XP/kill/status and the damage each
side took), not individual weapon-strike rolls. `kind` is the recorded event
kind (`move`, `attack`, `recruit`, `vacate`, `spawn`, `village`, `poison`,
`slow`, `heal`, `gold`, `advance`, `end_turn`, or any future kind, preserved
verbatim); `source` prefers the event's own recorded source, falling back to
its enclosing record's, and stays NULL when neither is known. `actions`
remains the authored orders table; it is not also given a duplicate copy of
event data in its unused `events_json` column.

`batch_id`/`side_turn_id` are attached only through explicit evidence, never
inferred by counting nearby records: a `forwarded_orders` record's own
`batch_id` covers the events the driver emits from executing that one batch
(its own authored events, source `llm` or `model`, and anything it delegates
within the same batch, source `delegated_greedy`) -- because the driver
protocol is strictly synchronous, only one batch is ever in flight, so this is
a committed execution relationship, not a position guess. An opponent's own
turn (source `greedy`) is never attached to the preceding model batch merely
because it is nearby; its `batch_id` stays NULL. The side turn a batch belongs
to resolves only when the batch's own recorded `state_revision` matches a
proven turn-boundary endpoint; when it doesn't, `side_turn_id` stays NULL
rather than guessing the nth turn. A malformed event record (a non-list
`events` field, or an event without a string `kind`) is never silently
dropped: its exact source position is recorded, the well-formed events around
it still import, and the game's `coverage_json.events_status` becomes
`"incomplete"` with an `event_malformed:<position>` gap. Zero observed events
for an otherwise-available archive reports `events_status: "no_event_evidence"`
-- never proof that execution was fully captured.

Normal import rebuilds a game's event rows deterministically and
transactionally, in step with its snapshot/turn rebuild, so nullable links
never dangle; reimporting unchanged evidence produces identical rows, and
append-only log growth adds only the new rows.

Backfill existing catalog games that predate this table (or need
recomputation) without touching any other table:

    python3 -m tools.game_history backfill-events --db PATH/history.sqlite --game-id GAME_ID [--game-id GAME_ID ...]
    python3 -m tools.game_history backfill-events --db PATH/history.sqlite --all

Each selected game is resolved from its stored catalog `artifact_path` (never
importing a relocated path as a second game) and processed in its own
transaction. A missing/unreadable archive is reported `unavailable`; a
malformed event record fails only that game, rolling back so its prior event
rows are left exactly as they were, while independent games continue. The
command reports attempted/imported/unavailable/failed games, event totals, and
exits nonzero if any selected game could not be backfilled. Repeating it is
idempotent.

Example query, once a game's events are imported:

```sql
SELECT kind, COUNT(*)
FROM events
WHERE game_id = 'GAME_ID'
GROUP BY kind
ORDER BY kind;
```

`inventory`, `verify_history`, and `delete` all cover the `events` table:
inventory and verification are read-only over an existing catalog and never
mutate it merely by being browsed; deleting a game or cohort removes its
event rows without touching any other game, and verification reports the
count of `side_turn_id`/`batch_id` links that would dangle (expected zero).

Match logs are append-only evidence. Import them after a game into a SQLite
catalog; gameplay does not depend on the catalog being available. Importing a
game is transactional and rebuilds only that game's derived timeline
(`snapshots` and `side_turns`); requests, batches, actions, evaluations, review
links, and the original archive are never dropped or recomputed. Each game
records the `importer_version` that produced its timeline. A catalog row from
before this importer (or from an interrupted import) has no matching
`importer_version` and cannot be replayed until reimported — see
[REPLAY.md](REPLAY.md).

The Love2D **Recorded Games** browser reads the default catalog and valid
`tmp/**/*.sqlite` catalogs read-only. It deduplicates exact game IDs and
uses an adjacent `identity.json` only to fill missing requested model identity;
that sidecar is not runtime confirmation. Corrupt or unrelated SQLite files are
skipped with a diagnostic. The browser exports the selected game through the
same `tools.replay_game` path as the command line launcher.

Browser boundary counts currently count imported model boundaries, not total
completed side turns. They must not be interpreted as game duration. The browser's
Gold/Turns column reads the engine ending from the selected page's archives;
missing ending evidence remains unknown (see [counting conventions](REPLAY.md)). Outcome
classification and complete recording coverage remain pending browser work;
see [the browser review](experiments/recorded-game-browser-review.md).

A model concession is stored with termination reason `resignation` and the
opponent as winner. The `Resign` action remains attributed to the model; it does
not create a completed side-turn. The raw terminal also records `resigned_side`
and the unchanged completed-side-turn count and state revision.

Example commands:

    python3 -m tools.game_history import --db .norrust_history/history.sqlite --cohort cohort-name path/to/game-directory
    python3 -m tools.game_history game --db .norrust_history/history.sqlite GAME_ID
    python3 -m tools.game_history turns --db .norrust_history/history.sqlite GAME_ID

The catalog stores game metadata, players, accepted model boundaries, model
request records, submitted action batches, primitive authored actions, evaluation
runs, and decision evaluations. State and request payloads are compressed and
hashed. Reimporting a game with the same ID is idempotent.

`python3 -m tools.prompt_cache_report --db PATH --game-id ID [--model MODEL]
[--layout LAYOUT]` reports canonical prompt byte-prefix comparisons and
provider cache usage from physical `model_calls`. Filters apply to those calls
and their linked prompts. Results are grouped by actual model, layout,
transport, and scope; unknown values remain separate. The cache ratio includes
only calls with both measured input and cached-input tokens and valid
`cached_input_tokens <= input_tokens`; unknown or conflicting calls are
excluded and labeled. Zero cached tokens are measured evidence. Byte equality
is cache eligibility evidence, never a measured hit, and tokens are never
inferred from bytes. Historical catalogs without call provenance remain
explicitly unknown.

Fireworks calls record the requested `x-session-affinity` value and prompt
layout in each physical call's provenance, including dispatch-only and failed
calls. The value is derived from the durable conversation ID and actual model,
so in-place resume keeps it while a fresh game or checkpoint branch changes it.
No affinity is sent when standalone adapter context is unavailable.

For annotation-enabled logs, each model request stores the exact UTF-8 prompt and
raw response (compressed and hashed), its explicit `state_revision`, and
`annotation_status`. A valid `decision_annotation` is retained as canonical
compressed JSON in `reasoning_blob`, with `reasoning_kind=decision_annotation_v1`
and `reasoning_source=model_response`; missing or invalid annotations retain no
rationale blob. Forwarded batches and authored actions carry the explicit
`request_id`, and batches carry their `before_revision`. No positional or
inferred explanation links are created.

`tools.match_report.classify` includes `decision_annotations` coverage. It counts
only authored forwarded batches with an explicit request ID, excluding tool-only
responses and generated fallback orders. Coverage is valid annotations divided
by applicable submitted batches, or `null` when there are none; rule counts are
counts of cited rule IDs in valid final annotations.

`inventory`, `game`, `turns`, and the Python `verify_history(path)` helper open
an existing catalog read-only. A missing path fails instead of creating a new
database. Quote shell paths containing spaces or characters such as `#`, `?`,
and `%`; the catalog opener handles their SQLite URI encoding. Import, review,
payload-coverage evaluation, and deletion are write operations.

The initial importer exposes the evidence present in existing NDJSON logs. Missing
request IDs, opponent boundary states, and usage measurements remain unknown.
It does not infer tactical quality from a winner or from a model action. Use the
original log, request journal, and checkpoint directory as the source archive.

## Model calls vs. harness requests

`model_requests` is the harness-request ledger: one row per prompt the client
sent and (when the request completed) the reply it got back, with whatever
usage the backend happened to report inline. A harness request can involve
several underlying provider/host inference calls -- a publication attempt,
an inspection/tool call, a retried call after a transport error -- so
`model_requests` is too coarse to be the detailed usage ledger.

`model_calls` is that detailed ledger. Each row is one actual provider/host
inference response, or one observable dispatched attempt whose outcome is
unknown; a locally blocked request that never reached a provider owns zero
call rows, never a synthetic one. Calls are never deduplicated by prompt
hash: two paid retries of the same prompt are two distinct `call_id`s.
Repeated lifecycle records for the same call (a "dispatch" line, then a
"final" line once the provider replies) UPSERT that one row; two "final"
records that disagree on a token count are recorded as an explicit
`normalization_gaps` conflict entry rather than the later value silently
overwriting the earlier one. Token counts are normalized strictly: booleans,
negative numbers, and numeric strings are rejected as measured counts and
kept as reported gaps, never coerced to zero, and `total_tokens` is only ever
what the provider itself reported -- it is never computed by summing input,
cached, output, and reasoning tokens.

A `model_calls` row links to its owning request through a nullable
`request_id` (unlinked calls -- e.g. one whose association couldn't be
proven -- still count toward the game total) and derives its side-turn only
through that request's own proven side-turn link; there is no second,
independently-maintained turn link on the call itself.

Historical archives recorded before this table existed have no per-call
detail at all -- only the request's own aggregate usage columns. Querying
those surfaces that total as an explicitly labeled `request_aggregate`,
used only for reconciliation. It is never invented into a synthetic call and
never added to a request's measured child-call total, even when both exist
for the same request; a genuine conflict between the two is reported, not
silently favored one way.

### Usage sidecar

A maintained backend (`tools/fireworks_backend.py`) writes its own durable
usage evidence to a match-owned NDJSON sidecar as calls are dispatched and
resolved -- before returning a reply or raising on failure, so an emptied or
malformed provider response still leaves exact counts on disk. The
conventional path is `usage.ndjson` next to the archive's own `match.ndjson`
(`tools.game_history.usage_sidecar_path`); a relocated archive copy keeps its
usage evidence alongside it since the path is derived from the archive
location, never from cwd or a launcher-specific setting.

Each sidecar line is one lifecycle record for one call: a `"dispatch"` line
written immediately before the network call, and a `"final"` line -- sharing
the same `call_id` -- written immediately after a response or error is known.
A process killed between the two still leaves the dispatch line as evidence:
importing it produces one call row with unknown final usage, not zero calls
and not a fabricated normal outcome. `tools.game_history.import_game` reads
this sidecar automatically as part of a normal import (no separate step);
`tools.game_history.import_usage_sidecar(conn, game_id, path)` is the
standalone entry point for importing usage evidence recorded elsewhere.
Reimporting an unchanged sidecar, or one containing duplicate dispatch/final
notifications, produces identical `model_calls` rows -- never extra ones.

### Querying usage

    python3 -m tools.game_history usage --db PATH/history.sqlite GAME_ID --group-by call
    python3 -m tools.game_history usage --db PATH/history.sqlite GAME_ID --group-by request
    python3 -m tools.game_history usage --db PATH/history.sqlite GAME_ID --group-by game --json

`--group-by call` lists every detailed row (raw usage JSON, lifecycle,
settings) plus per-field coverage across the game. `--group-by request`
groups detailed calls under their harness request and attaches any
historical `request_aggregate` for that request as reconciliation-only
context. `--group-by game` (the default) reports one measured aggregate
across every call, which requests have only an aggregate-only historical
total, and how many calls carry no request link. `--json` prints the same
structure the human-readable text output is built from -- there is no
separate stored summary; both read live from `model_calls` and
`model_requests`. A field's aggregate `sum` is labeled `PARTIAL` whenever any
call in its group has that field unmeasured, so a partial total can never be
mistaken for a complete one.

    python3 -m tools.game_history usage --db PATH/history.sqlite GAME_ID --group-by turn --json

`--group-by turn` groups measured calls by their request's own proven
side-turn link rather than maintaining a second, independent turn link on
the call itself: a call reaches a turn only when its request carries a
`model_requests.side_turn_id`, which is itself set only when that request's
recorded `state_revision` matches a proven turn-boundary endpoint. It reports
`completed_turns` and `open_turns` as separate lists -- averaging an
interrupted, still-open turn's usage into completed-turn figures would
distort both -- plus one `unassigned` group holding every call whose request
has no proven turn link, including a call with no `request_id` at all; an
unassigned call still counts toward the game total, it just cannot be placed
on a turn. Each turn or the `unassigned` group carries its member `call_ids`
and an `aggregate_calls` `detail` block (the same per-field sum/coverage
shape as the other groupings). `attribution_coverage` reports `linked_calls`,
`unassigned_calls`, `total_calls`, and `linked_fraction` -- `None`, not `1.0`,
for a game with zero calls, since no evidence is not full coverage. As with
`--group-by request`, a turn's calls are its measured detail only; a
request's own historical `request_aggregate` is never summed into that
detail.

`inventory`, `verify_history`, and `delete` all cover `model_calls`:
inventory and verification are read-only and never mutate a catalog merely by
being browsed; deleting a game or cohort removes its call rows without
touching any other game's usage; verification reports dangling
call-to-request links and any call attributed across a game boundary
(`dangling_call_request_links`, `cross_game_call_links`; both expected zero).

### Backfilling historical usage

`tools/usage_backfill.py` recovers usage for games catalogued before live
usage collection existed, from preserved evidence: Fireworks
`requests/*/request.json` + `response.json` + `receipt.json` (plus
`reply.json` on success or `error.json` on an old rejected/empty answer), and
explicitly bound Codex host sessions collected the same way Stack 2's
`tools/collect_model_usage.py` does. It never imports a new game -- a
selected game must already be in the catalog, and is resolved only by its
stored `games.artifact_path` identity, so a relocated copy of the same
archive can never become a second game.

An explicit JSON manifest names exactly which games are eligible and how to
recover each one's evidence:

```json
{
  "games": {
    "quick-play-deepseek-v4-flash-yooojyos": {
      "kind": "fireworks_requests",
      "requests_dir": "tmp/quick-play-deepseek-v4-flash-yooojyos/requests"
    },
    "quick-play-jai2s3hp": {
      "kind": "host_session",
      "host_thread_id": "01a082a9-c696-7e21-9e6e-9bc749985b49",
      "host_evidence_path": "/home/USER/.codex/sessions/2026/09/08/rollout-....jsonl",
      "game_log_path": "tmp/quick-play-jai2s3hp/match.ndjson",
      "request_handshake_dir": "tmp/quick-play-jai2s3hp/requests"
    }
  }
}
```

Only the games a manifest maps are ever eligible, including for `--all` --
it never scans every catalogued game, only the manifest's own list:

    python3 -m tools.game_history backfill-usage --db PATH/history.sqlite --manifest MANIFEST.json --game-id GAME_ID [--game-id GAME_ID ...]
    python3 -m tools.game_history backfill-usage --db PATH/history.sqlite --manifest MANIFEST.json --all

Without `--execute` the command only reports what it would import (inventory
mode, the default); nothing is written until `--execute` is given. Backfill is
additive: newly discovered calls are merged into whatever `model_calls` rows
a game already has (through the same `import_usage_sidecar` UPSERT-by-identity
path Stack 1/2 already use), never a blanket replace -- usage already imported
from live collection survives a later backfill run untouched. Two preserved
copies of the same evidence collapse to one call by shared identity (the
provider response ID, or the source-derived attempt directory name when no
response ID exists) rather than becoming a second paid retry; a genuine
disagreement between two records for the same identity is reported as a
conflict, never silently resolved by last-writer-wins.

Each selected game is independent and transactional: a missing evidence path
is reported `unavailable`; a source that produced no usable calls at all
despite being reachable (e.g. corrupt JSON throughout) is reported `failed`
and leaves that game's previously imported usage completely untouched;
`unavailable`/`failed` games never block or roll back an independent game
that succeeded in the same batch. The command exits nonzero if any selected
game could not be backfilled. Rerunning against unchanged evidence is
idempotent -- the same call IDs, the same rows.

    python3 -m tools.game_history compare-usage --db PATH/history.sqlite --game-id GAME_ID [--game-id GAME_ID ...] --json

`compare-usage` requires an explicit game selection -- there is no "compare
everything in the catalog" mode. It reports, per game and using the same
`query_usage` aggregation the `usage` command uses: measured/aggregate-only
totals and attribution coverage; per-request and per-completed-side-turn
output/reasoning median and max, computed only over fully measured groups,
with `included_count`/`excluded_count` alongside every percentile so a
partial-coverage comparison is never mistaken for a complete one; open-turn
usage and failed-call usage reported as their own sections, never folded into
completed-turn averages; requested/reported model and reasoning effort,
output limits, transport, source commit, and resume continuity
(`parent_game_id`/`lineage_root_id`). It computes no model ranking and no
"fair comparison" score -- raw token counts are measurements from different
tokenizers, not equal units of compute, and a lower count alone says nothing
about strength. System-instruction identity is not separately tracked;
`distinct_prompt_hashes` is reported as a proxy only, never proof that two
games ran under identical or differing instructions. Without `--json` it
prints a compact per-game summary built from the same structure.

## Runtime health and maintenance

An engine winner does not by itself make a model evaluation valid. Inspect the
terminal `terminal_class`, `infrastructure_invalid`, model request statuses, and
fallback counts. A clean model run should show successful resumed requests and
zero infrastructure failures. Native usage is copied from completed requests when
the adapter provides it; missing usage remains NULL.

Distinguish requested settings from runtime evidence. The Codex adapter records
`requested_model` and `requested_reasoning_effort` in its request metadata,
results, and session sidecar. The client copies those values to
`backend_requested_model` and `backend_requested_reasoning_effort` in match
metadata, while `requested_reasoning_effort` records the client's expectation.
The current native events do not confirm runtime model or effort, so the adapter
records null runtime fields and `runtime_settings_source: "not_reported"`.
Do not fill missing runtime fields from a requested setting or an archive name.

Inventory a catalog before deleting anything:

    python3 tools/game_history.py inventory --db PATH/history.sqlite

Delete an exact cohort or explicit game IDs with a transaction. Add `--compact`
to checkpoint the WAL and run SQLite `VACUUM` after deletion:

    python3 tools/game_history.py delete --db PATH/history.sqlite --cohort COHORT_ID --compact
    python3 tools/game_history.py delete --db PATH/history.sqlite --game-id GAME_ID --compact

`--reset` is an explicit whole-catalog data reset and preserves the schema. Use it
only when inventory proves the catalog contains no unrelated games. Delete or
regenerate backups and raw archives separately; SQLite deletion does not remove
the original NDJSON, native request artifacts, or checkpoints. Verify both the
catalog and any surviving backup after maintenance:

    python3 - <<'PY'
    from tools.game_history import verify_history
    print(verify_history("PATH/history.sqlite"))
    PY

The maintenance command rejects missing game IDs and ambiguous selectors. It
removes dependent evaluation rows safely while preserving unrelated cohorts.
