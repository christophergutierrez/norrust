# Prompt cache Stack 2 handoff

Stack 1 base: `15447c6eb0145491e7dd3300499222f518035504`.

Stack 2 adds durable Fireworks `x-session-affinity` routing from the harness
conversation ID and actual requested model, records affinity and prompt layout
on dispatch/final physical call rows, and imports those fields through the
existing `model_calls` ledger. In-place resume retains the conversation ID;
checkpoint branches create a new one. Missing standalone context leaves the
affinity unavailable. Fireworks prompt/cache response headers are allowlisted
and normalized only when they are valid decimal counts. No timing field is
treated as TTFT.

`prompt_cache_report --db` opens SQLite read-only, rejects unknown game IDs,
filters physical calls and linked prompts by actual model/layout, and groups
usage by model/layout/transport/scope. Cache ratios use only calls with both
measured input and cache counts and `cached <= input`; unknown, conflicting,
and contradictory calls are labeled/excluded. All token fields retain aggregate
sum plus known/unknown coverage. A mixed fixture reports Fireworks 800/2200 =
36.36% and native Codex host 0% separately; its missing-cache input sum is 900.

Evidence and tests:

- Focused Stack 2 suites (`python3 -m unittest tools.test_prompt_cache_routing_acceptance tools.test_fireworks_backend tools.test_prompt_cache_report tools.test_game_history tools.test_model_usage`): 95 tests passed, including the six-test independent
  routing/report acceptance module.
- Independent routing/report acceptance: 6 tests passed, covering interrupted
  dispatch, same-log resume, fresh/branch affinity, exact wire payloads,
  provenance import, SQLite reporting, and idempotence.
- Full `python3 -m tools.fast_check` (log: `tmp/cache-exec/stack2_fast_check.log`):
  473 Python tests passed, all Rust suites,
  LuaJIT bridge/replay/recorded-games checks, and `git diff --check` passed.
- Stack 1 real-engine evidence remains in `/mnt/storage/git_home/norrust/tmp/cache-review/`;
  no provider calls or paid games were made for Stack 2.

Limitations: Fireworks affinity is a replica-routing hint, not a cache-hit
guarantee. Provider cache fields are unknown when absent. Full API message
prefix equivalence is unavailable to the offline byte report; equal canonical
prompt bytes do not establish a provider hit or speedup.
