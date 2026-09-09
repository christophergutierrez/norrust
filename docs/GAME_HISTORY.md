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

A single snapshot can hold both roles. When a match ends before any state
change — a turn-one resignation, or a win on the opening position — the opening
and the terminal coalesce into one proven state. `boundary_kind` carries only
one label, so the opening role is tracked separately rather than inferred from
it; `coverage.opening_present` and `terminal_present` are then both true for
that one snapshot.

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
`tmp/**/history.sqlite` catalogs read-only. It deduplicates exact game IDs and
uses an adjacent `identity.json` only to fill missing requested model identity;
that sidecar is not runtime confirmation. Corrupt or unrelated SQLite files are
skipped with a diagnostic. The browser exports the selected game through the
same `tools.replay_game` path as the command line launcher.

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
