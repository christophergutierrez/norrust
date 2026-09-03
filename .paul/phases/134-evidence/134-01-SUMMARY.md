# Phase 134 — Evidence summary

The client now drains driver stderr into a bounded tail, records typed EOF and
broken-pipe terminals, preserves the last event count, defaults
`--turn-timeout` to 930 seconds, warns when it is below the configured query
and two-call model budget, and records `rejected_batches` plus
`rejected_action_items`. Per-model records include prompt byte fields; legacy
region splits remain null.

## Verification

Command: `python3 -m unittest tools.test_llm_client -v`

Source commit before this phase: `82946d1`.

Result: 32 tests passed.

The historical eight-call observation corpus described by the implementation
plan is not present in this checkout (only `tmp/test_match.ndjson`, a seed-42
one-call smoke log, exists), so its historical byte figures were not recreated
or fabricated. A new authoritative corpus remains a follow-up measurement.

Seed-2001 smoke fixture SHA-256:
`6dc79a10446e57af5dee38604baa0196c4d86a720807dcee2d0214f3c799a40f`.
