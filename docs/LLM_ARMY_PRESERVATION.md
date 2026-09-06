# Luna army-preservation evaluation

The army-preservation layers are implemented in commits `13e17be`, `aa62f98`,
`0bfd720`, `74aeffe`, `25397b0`, and `8517ab0`. Forecast previews are explicitly
pre-sweep and nonsampling; bounded comparisons identify their rollout mode.
Reviews have stable IDs and candidate digests, forced partial-limit finishes are
separate from model awareness, and imported requests/actions use provable
side-turn linkage when available.

The final cohort is archived under `tmp/llm_luna_army_preservation_final/` with
seeds 2031, 2032, and 2033. All three games were gameplay-valid and had no
infrastructure failure. Luna won 2031 and 2033; Greedy won 2032. The separate
SQLite catalog contains 3 games, 34 side-turns, 139 model requests, 73 action
batches, and 135 actions, and passed foreign-key and integrity verification.

Per-game wall time and usage totals are retained in each `match.ndjson` and in
the catalog. Token usage is measured by the native backend for this cohort.
