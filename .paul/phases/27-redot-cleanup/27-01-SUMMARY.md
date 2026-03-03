---
phase: 27-redot-cleanup
plan: 01
subsystem: cleanup
tags: [redot, godot, gdextension, cleanup, migration]

requires:
  - phase: 26-love2d-client
    provides: Verified Love2D client with full game.gd feature parity

provides:
  - Clean codebase with single integration path (C ABI + LuaJIT FFI)
  - No Godot/Redot dependencies in Rust core
  - Simplified build (no godot crate compilation)

affects: [build-system, project-structure]

tech-stack:
  removed: [Redot 26.1, GDScript, GDExtension (godot crate 0.2.4)]
  patterns: [single-bridge architecture (C ABI only)]

key-files:
  deleted: [norrust_core/src/gdext_node.rs, norrust_client/ (9 tracked files)]
  modified: [norrust_core/src/lib.rs, norrust_core/Cargo.toml, .gitignore]

key-decisions:
  - "cdylib crate-type retained — still needed for .so loading by LuaJIT FFI"
  - "Clean deletion — no compatibility shims or re-exports for removed code"

patterns-established:
  - "Single integration path: C ABI (ffi.rs) → LuaJIT FFI (norrust.lua) → Love2D (main.lua)"

duration: ~5min
completed: 2026-03-03
---

# Phase 27 Plan 01: Redot Cleanup Summary

**Removed Redot/GDExtension layer (gdext_node.rs + norrust_client/ + godot dependency) — single C ABI + Love2D integration path remains.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~5min |
| Completed | 2026-03-03 |
| Tasks | 2 completed (both auto) |
| Files deleted | 10 (1 Rust + 9 Redot project) |
| Files modified | 3 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: norrust_client Directory Removed | Pass | `ls norrust_client/` returns "No such file or directory" |
| AC-2: GDExtension Bridge Removed | Pass | gdext_node.rs deleted; lib.rs no longer declares module |
| AC-3: Godot Dependency Removed | Pass | `godot = "0.2"` removed from Cargo.toml; `cargo build` succeeds |
| AC-4: All Tests Pass | Pass | 73 tests (56 lib + 16 integration + 1 FFI) all pass |
| AC-5: .gitignore Cleaned | Pass | No norrust_client references remain in .gitignore |
| AC-6: Love2D Client Still Works | Pass | `love norrust_love` launches, runs 3 seconds without errors |

## Accomplishments

- Deleted `norrust_core/src/gdext_node.rs` (GDExtension bridge)
- Removed `godot = "0.2"` dependency from `Cargo.toml`
- Removed `pub mod gdext_node;` from `lib.rs`
- Deleted entire `norrust_client/` directory (9 tracked files)
- Cleaned `.gitignore` of all Redot-specific entries

## Files Deleted/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/gdext_node.rs` | Deleted | GDExtension bridge — replaced by ffi.rs C ABI |
| `norrust_client/` (9 files) | Deleted | Redot project — replaced by norrust_love/ |
| `norrust_core/src/lib.rs` | Modified | Removed `pub mod gdext_node;` |
| `norrust_core/Cargo.toml` | Modified | Removed `godot = "0.2"` dependency |
| `.gitignore` | Modified | Removed norrust_client/ specific entries |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Keep cdylib crate-type | Still needed for .so that LuaJIT FFI loads | Build produces libnorrust_core.so for Love2D |
| Clean deletion (no shims) | gdext_node.rs was the only godot consumer; no other code imports it | Zero breakage; clean removal |

## Deviations from Plan

None. Plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- v1.2 Love2D Migration milestone is complete (all 3 phases done)
- Single integration path: Rust → C ABI → LuaJIT FFI → Love2D
- 73 tests passing; Love2D client verified working

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 27-redot-cleanup, Plan: 01*
*Completed: 2026-03-03*
