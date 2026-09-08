# Game history

Each imported side turn keeps its start/end revisions and compressed state blobs.
Model requests and forwarded action batches carry `side_turn_id` when the log
contains a provable state revision, side-turn, or stable review identity. Missing
linkage remains NULL; imports never attach the nth review or snapshot by position.
Review IDs, candidate digests, forced partial-limit finishes, and review outcomes
remain in the archived log/metrics JSON for ad hoc analysis and training-data
selection.

Match logs are append-only evidence. Import them after a game into a SQLite
catalog; gameplay does not depend on the catalog being available.

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
