# Phase 139 — Tools and revisions summary

`GameState` now owns a monotonic `state_revision`, initialized after setup and
incremented once by successful `apply_action`, `apply_recruit`, and
`apply_advance` calls. Failed calls and setup placement do not increment it;
transactional clones naturally discard increments on rollback. State snapshots,
query responses, and action-batch statuses expose the authoritative revision.

The read-only tool loop, stale-response rejection, combat-preview measurement,
and validate-batch protocol are not implemented in this run.

Verification: `cargo test --lib`, the prescribed integration tests, and
`python3 -m unittest tools.test_llm_client -v` pass.
