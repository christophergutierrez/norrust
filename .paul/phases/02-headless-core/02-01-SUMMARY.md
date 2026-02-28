---
phase: 02-headless-core
plan: 01
subsystem: core
tags: [hex, coordinates, cubic, offset, board, geometry]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: Rust library scaffold, Cargo.toml with crate-type = ["cdylib", "rlib"]
provides:
  - Hex struct with cubic coordinates and operator overloads
  - Board struct with offset-space boundary validation
  - 12 unit tests covering all acceptance criteria

affects: [02-02-gamestate, 02-03-pathfinding, 02-04-combat]

# Tech stack
tech-stack:
  added: [std::ops::Add, std::ops::Sub via trait impl]
  patterns:
    - Cubic hex coordinates (x+y+z=0) as canonical internal representation
    - Odd-r offset coordinates for Wesnoth-compatible map layout
    - Operator overloads (+ / -) instead of named add/subtract methods

key-files:
  created:
    - norrust_core/src/hex.rs
    - norrust_core/src/board.rs
  modified:
    - norrust_core/src/lib.rs

key-decisions:
  - "Implement std::ops::Add + Sub instead of named add/subtract — clippy::should_implement_trait"
  - "Odd-r offset (pointy-top) convention — matches Wesnoth map format"

patterns-established:
  - "All hex math uses cubic coords internally; offset used only at I/O boundaries"
  - "Board::contains() converts to offset then bounds-checks — no cubic bounding needed"

# Metrics
duration: ~20min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 2 Plan 01: Hex Coordinate System + Board Summary

**Cubic `Hex` struct with Add/Sub operator overloads, odd-r offset conversion, and `Board` boundary validation — 15 tests passing, clippy clean.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Completed | 2026-02-27 |
| Tasks | 2 completed |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Hex Distance Calculation | Pass | `distance((0,0,0), (2,-1,-1)) == 2` verified by `test_distance_two` |
| AC-2: Hex Neighbor Retrieval | Pass | 6 neighbors, all satisfy x+y+z=0, all distance=1 from origin |
| AC-3: Offset Coordinate Round-Trip | Pass | 121 hexes (11×11 cubic neighborhood) all roundtrip losslessly |

## Accomplishments

- `Hex` struct with cubic coordinates, `Add`/`Sub` operator overloads, `distance()`, `neighbors()`, `to_offset()`, `from_offset()`
- `Board` struct with `contains(hex)` boundary check in offset space (Wesnoth-compatible)
- 15 tests total: 7 hex, 5 board, 3 existing loader tests — all pass
- `cargo clippy -- -D warnings` clean

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/hex.rs` | Created | Hex cubic coordinate type with math ops and offset conversion |
| `norrust_core/src/board.rs` | Created | Board dimensions + hex boundary validation |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod hex;` and `pub mod board;` |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Implement `std::ops::Add` and `Sub` instead of `.add()` / `.subtract()` methods | clippy `-D warnings` rejects named `add` without trait impl | All hex arithmetic now uses `+` / `-` operators; more idiomatic Rust |
| Odd-r offset coordinates (pointy-top) | Matches Wesnoth map file convention | Board, map loading, and future terrain lookup all use consistent offset layout |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Clippy compliance — idiomatic improvement |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** One essential clippy fix, no scope creep.

### Auto-fixed Issues

**1. Clippy: named `add` method without `Add` trait implementation**
- **Found during:** Task 1 verification (`cargo clippy -- -D warnings`)
- **Issue:** `pub fn add(self, other: Hex) -> Hex` triggers `clippy::should_implement_trait`
- **Fix:** Replaced `.add()` / `.subtract()` methods with `impl std::ops::Add` and `impl std::ops::Sub`; updated all call sites to use `+` / `-` operators
- **Files:** `norrust_core/src/hex.rs`
- **Verification:** `cargo clippy -- -D warnings` exits 0; all 15 tests still pass

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `cargo clippy -- -D warnings` failed on `add` method name | Implemented `Add`/`Sub` operator traits, removed named methods |

## Next Phase Readiness

**Ready:**
- `Hex` + `Board` are the geometry primitives every Phase 2 system builds on
- All operations tested and clippy-clean
- Module declarations in `lib.rs` expose both types crate-wide

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 02-headless-core, Plan: 01*
*Completed: 2026-02-27*
