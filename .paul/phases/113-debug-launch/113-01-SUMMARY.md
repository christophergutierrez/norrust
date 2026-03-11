---
phase: 113-debug-launch
plan: 01
subsystem: debug, ui
tags: [love2d, ffi, debug-mode, cheat-keys]

requires:
  - phase: 112-debug-config
    provides: debug/data/ generated from config
provides:
  - "--debug launch flag for Love2D"
  - "X/G/T cheat keys gated behind debug flag"
  - "3 cheat FFI functions (set_xp, add_gold, set_turn)"
affects: [114-test-scenarios]

tech-stack:
  added: []
  patterns: ["debug-gated cheat keys via shared.debug_mode"]

key-files:
  created: ["norrust_love/debug (symlink -> ../debug)"]
  modified: ["norrust_love/main.lua", "norrust_love/input.lua", "norrust_love/norrust.lua", "norrust_core/src/ffi.rs"]

key-decisions:
  - "Added 3 FFI cheat functions as pure additions (no existing code modified)"
  - "Used with_game_mut! macro pattern for cheat FFI (not catch_panic)"
  - "Debug flag parsed in both early and late arg blocks for data path + runtime flag"

patterns-established:
  - "Debug-gated features: check shared.debug_mode before enabling"
  - "Cheat FFI functions: simple state mutations via with_game_mut! macro"

duration: ~30min
completed: 2026-03-11
---

# Phase 113 Plan 01: Debug Launch Mode + Cheat Keys Summary

**--debug flag switches Love2D to debug/data/, cheat keys X/G/T enable rapid gameplay testing**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-11 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files modified | 4 + 1 symlink |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Debug flag switches data path | Pass | data_rel switches to "debug/data", FFI gets absolute path, assets use relative |
| AC-2: Cheat key X maxes XP | Pass | Sets xp = xp_needed, advancement_pending = true; gold ring appears |
| AC-3: Cheat key G adds gold | Pass | Adds 1000 gold to active faction |
| AC-4: Cheat key T cycles ToD | Pass | Advances turn by 1 |
| AC-5: Cheat keys inactive in production | Pass | Gated behind shared.debug_mode check |

## Accomplishments

- --debug flag in Love2D switches both FFI data_path (absolute) and asset path (relative via symlink)
- 3 cheat FFI functions added as pure additions to ffi.rs using with_game_mut! macro
- Cheat keys fully gated behind shared.debug_mode — zero effect in production
- Human verification confirmed: Mage advancement works perfectly via X + 'a' flow

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/main.lua` | Modified | --debug flag detection, data path switching, status message |
| `norrust_love/input.lua` | Modified | X/G/T cheat key handlers gated behind shared.debug_mode |
| `norrust_love/norrust.lua` | Modified | FFI declarations + Lua wrappers for 3 cheat functions |
| `norrust_core/src/ffi.rs` | Modified | 3 cheat FFI functions: cheat_set_xp, cheat_add_gold, cheat_set_turn |
| `norrust_love/debug` | Created | Symlink -> ../debug (follows existing data symlink pattern) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Pure-addition FFI for cheats | No existing code modified; cheat functions isolated | Clean separation, no regression risk |
| with_game_mut! macro | Consistent with codebase pattern (not catch_panic) | Required fix during apply |
| Two-block arg parsing | --debug needed in early block (data path) and late block (runtime flag) | Slightly redundant but follows existing pattern |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Essential fix, no scope creep |
| Deferred | 1 | Logged for future work |

### Auto-fixed Issues

**1. FFI macro pattern mismatch**
- **Found during:** Task 2 (cheat key FFI)
- **Issue:** Initially used nonexistent `catch_panic` helper; then u32/i32 type mismatch on unit keys
- **Fix:** Rewrote to use `with_game_mut!` macro with `let uid = unit_id as u32` cast
- **Verification:** cargo test --lib passes (118 tests)

### Deferred Items

- Missing advancement target units (e.g., General for Lieutenant, many level 3+ units) — advancement silently fails when target def doesn't exist. Not a debug mode bug; affects normal mode too. Backlog item for unit expansion.

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| Lieutenant won't advance via 'a' key | Missing "General" unit definition — advances_to target doesn't exist in registry. Not a Phase 113 bug. |
| Sprites show as circles in debug mode | Expected — many units lack sprite images. Debug data copies TOMLs but sprites don't exist for most units. |
| Heavy Inf auto-advances without choice | Expected — single advances_to target auto-picks index 0. Multi-target choice UI is v4.0 scope. |

## Next Phase Readiness

**Ready:**
- Debug sandbox workflow complete: edit config → generate → launch --debug → test with cheat keys
- Foundation for Phase 114 test scenarios established

**Concerns:**
- Many advancement chains broken due to missing unit definitions (level 3+ units)

**Blockers:**
- None

---
*Phase: 113-debug-launch, Plan: 01*
*Completed: 2026-03-11*
