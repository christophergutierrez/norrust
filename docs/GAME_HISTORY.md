# Game history

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
