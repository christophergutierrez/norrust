# Stack 1 prompt-cache evidence

Baseline source identity: `58ea306` (`tools/llm_client.py` from this checkout;
no credentials or model calls). New layout source is the amended commit below.

The deterministic fixture matrix is exercised by
`tools.test_prompt_cache_layout`: live turn/economy/HP/position/agenda changes
keep the fixed-prefix hash unchanged; geometry changes it; type profiles are
sorted by definition while nested attack order is preserved. Measurements from
the fixture are reported as UTF-8 bytes by `tools.prompt_cache_report`; missing
prompts are excluded from adjacent comparisons and counted in coverage.

The canonical comparison scope is the complete user prompt string. Full API
message-prefix equivalence is unavailable to this offline helper and is labeled
accordingly; byte lengths are never token counts or cache hits.

Focused tests: the independent acceptance suite passed all 13 tests, including
the real-driver partial/repair/archive/SQLite/idempotence path; the client and
layout suites also pass. The coordinator's real-engine probe at
`/mnt/storage/git_home/norrust/tmp/cache-review/` passed with three requests per
run, one partial boundary, one action repair, exit 0, exact backend/archive
prompt bytes, and identical driver events against the original 58ea306
baseline. Full gate `python3 -m tools.fast_check` passed on the final tree:
462 Python tests, all Rust suites, LuaJIT bridge/replay/recorded-game checks,
and `git diff --check`.

Measured UTF-8 bytes (original 58ea306 → candidate): synthetic opening compact
16,241 → 16,531 (+290), diagnostic 16,140 → 16,549 (+409); the agenda-change
case shared-prefix region is compact 14,006 → 14,623 and diagnostic 14,025 →
14,787. Real engine-input fixture opening compact is 22,086 → 22,360 (+274),
and diagnostic is 63,877 → 65,395 (+1,518, within the 5% diagnostic budget).
The matrix covers six cases in both modes; fixed-prefix hashes are equal for
all live mutations and shared prefixes reach the fixed section, while changed
geometry/visibility/rules change the hash. The fixture records producer source
identity `58ea306`.

Known limitation: this fixture does not make a provider call or claim a live
cache hit; Fireworks routing and measured SQLite reporting are Stack 2.
