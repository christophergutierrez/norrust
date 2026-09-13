# Strategy routine real-driver fixtures

quiet.json derives from the checked-in task_harness/defense_variant1.json.
The embedded note records source hash and explicit mutations. Its RNG state is
preserved; this is a deterministic quiet position, not a live fresh-seed match.
Only two recruiters remain; the opponent has zero gold and no villages. Tests
resolve __SCENARIO_BOARD__ to the current board after checking its SHA256.

quiet_policy.json requests three actual-ID-bound scouts for the three named
western villages and three skeletons travelling to a distant rally. Rally travel
is intended to remain unfinished through the three-turn observation window.
All moves/recruits/captures and source attribution must be checked in actual
engine events/SQLite; scripted model calls are policy inputs only.
