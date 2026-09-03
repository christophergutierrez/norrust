# Phase 137 — Stable preamble summary

Prompt records now report deterministic region byte sizes. The preamble is
derived solely from the tactical playbook and static action contract, while
dynamic snapshot/options/events remain in later regions. Orders-file and
generic command backends record cache telemetry as `unreported` unless the
backend supplies an explicit cache object.

Verification: `python3 -m py_compile tools/llm_client.py` and
`python3 -m unittest tools.test_llm_client` — 32 tests passed.
