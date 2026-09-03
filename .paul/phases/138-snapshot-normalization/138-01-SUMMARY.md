# Phase 138 — Snapshot normalization summary

Added `CompactStateSnapshot` and catalog/instance types in `snapshot.rs`, plus
`StateSnapshot::compact_from_game_state`. The existing fat snapshot remains
unchanged for FFI consumers; compact snapshots retain terrain color and all
unit instance fields required for a lossless join. `state_revision` is present
on both snapshot forms.

Verification: `cargo test --lib snapshot::tests` — 14 tests passed.

The driver selector and Love2D migration remain pending; the compatibility
path is intentionally still fat.
