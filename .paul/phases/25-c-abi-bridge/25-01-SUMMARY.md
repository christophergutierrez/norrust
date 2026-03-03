---
phase: 25-c-abi-bridge
plan: 01
subsystem: ffi
tags: [rust, c-abi, luajit-ffi, extern-c, opaque-pointer]

requires:
  - phase: 24-scrollable-camera
    provides: stable game with all features (32 GDExtension bridge methods)
provides:
  - C ABI bridge (36 extern "C" functions) callable from any FFI-capable language
  - NorRustEngine opaque pointer with caller-frees memory management
  - Integration test proving full game cycle via C ABI
affects: [love2d-client, redot-cleanup]

tech-stack:
  added: []
  patterns: [opaque pointer FFI, caller-frees string/array memory, CString::into_raw/from_raw]

key-files:
  created: [norrust_core/src/ffi.rs, norrust_core/tests/test_ffi.rs]
  modified: [norrust_core/src/lib.rs]

key-decisions:
  - "NorRustEngine fields simplified vs gdext_node: factions stored as Vec<(FactionDef, Vec<String>)> (pre-expanded)"
  - "norrust_free_int_array takes (arr, len) — length needed for Box::from_raw on slice"
  - "Both bridges (GDExtension + C ABI) coexist — no conditional compilation"

patterns-established:
  - "Opaque pointer pattern: norrust_new() → *mut NorRustEngine, all functions take engine as first param"
  - "Caller-frees strings: CString::into_raw() for returns, CString::from_raw() in norrust_free_string()"
  - "Null engine check via engine.as_ref()/as_mut() with early return on None"

duration: ~20min
completed: 2026-03-03
---

# Phase 25 Plan 01: C ABI Bridge Summary

**C ABI bridge exposing all 32 game engine functions via `extern "C"` for LuaJIT FFI — full game cycle verified by integration test, 73 tests passing.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20min |
| Completed | 2026-03-03 |
| Tasks | 2 completed (2 auto) |
| Files created | 2 |
| Files modified | 1 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: NorRustEngine Lifecycle | Pass | norrust_new() returns non-null; norrust_free() deallocates without error |
| AC-2: Full Data Loading Chain | Pass | load_data, load_board, load_factions, load_units all return 1; state JSON contains units+terrain |
| AC-3: Game Actions Via C ABI | Pass | apply_move returns 0; end_turn returns 0; faction changes verified; turn increments |
| AC-4: String Memory Management | Pass | All string returns freed via norrust_free_string; valid UTF-8 null-terminated |
| AC-5: Reachable Hexes Array | Pass | Returns flat [col, row, ...] i32 array; out_len populated; freed via norrust_free_int_array |
| AC-6: All 72 Existing Tests Still Pass | Pass | 73 total: 56 lib + 16 integration + 1 new FFI test |

## Accomplishments

- `ffi.rs`: 36 `extern "C"` functions (4 lifecycle + 32 bridge) mirroring gdext_node.rs — callable from any FFI-capable language
- `NorRustEngine` opaque struct with caller-frees memory management for strings (`norrust_free_string`) and int arrays (`norrust_free_int_array`)
- `test_ffi_full_game_cycle`: comprehensive integration test exercising create → load → query → move → end_turn → faction queries → cleanup
- Zero changes to existing modules — both GDExtension and C ABI bridges coexist

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/ffi.rs` | Created | C ABI bridge: NorRustEngine + 36 extern "C" functions + helpers |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod ffi;` |
| `norrust_core/tests/test_ffi.rs` | Created | Integration test for full game cycle via C ABI |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| NorRustEngine simplified fields (units/terrain/game/factions) | Matches gdext_node data model without separate registries for recruit groups | Simpler struct; recruit groups expanded at load_factions() time |
| norrust_free_int_array(arr, len) takes length param | Box::from_raw needs slice length to reconstruct the boxed slice | LuaJIT caller must pass array length when freeing |
| Cargo.toml unchanged | cdylib crate-type already configured from Phase 1; no new dependencies needed | Plan listed it as modified but no changes required |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Dead function removed during implementation |
| Plan vs actual | 1 | Cargo.toml not modified (already correct) |

**Total impact:** Minimal — both deviations are simplifications.

### Auto-fixed Issues

**1. Dead upgrade_tiles() function**
- **Found during:** Task 1
- **Issue:** Initial `upgrade_tiles(&NorRustEngine)` had borrow issues (immutable→mutable transition)
- **Fix:** Replaced with `upgrade_tiles_mut(&mut NorRustEngine)` using collect-then-apply pattern
- **Files:** norrust_core/src/ffi.rs
- **Verification:** cargo build succeeds with zero warnings

### Deferred Items

None.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- C ABI bridge fully functional — Love2D client can call all 32 game functions via LuaJIT FFI
- Opaque pointer + caller-frees patterns established for Phase 26
- All 73 tests passing; zero warnings

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 25-c-abi-bridge, Plan: 01*
*Completed: 2026-03-03*
