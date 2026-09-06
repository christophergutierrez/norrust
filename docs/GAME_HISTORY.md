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

Example commands:

    python3 -m tools.game_history import --db .norrust_history/history.sqlite --cohort cohort-name path/to/game-directory
    python3 -m tools.game_history game --db .norrust_history/history.sqlite GAME_ID
    python3 -m tools.game_history turns --db .norrust_history/history.sqlite GAME_ID

The catalog stores game metadata, players, accepted model boundaries, model
request records, submitted action batches, primitive authored actions, evaluation
runs, and decision evaluations. State and request payloads are compressed and
hashed. Reimporting a game with the same ID is idempotent.

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
