---
phase: 106-save-ux-cleanup
plan: 01
subsystem: save-system
tags: [ffi, json, lua, save-load]

requires:
  - phase: 105-json-save-format
    provides: norrust_save_json/norrust_load_json FFI functions in Rust
provides:
  - Lua wrappers for single-call save/load FFI
  - Simplified write_save (single FFI call replaces manual data building)
  - Simplified load_save (single FFI call for JSON saves)
  - Legacy TOML/old-JSON load backward compatibility
affects: []

tech-stack:
  added: []
  patterns: [single-FFI-call save/load, format detection via top-level field presence]

key-files:
  modified: [norrust_love/norrust.lua, norrust_love/save.lua, norrust_love/input.lua, norrust_love/main.lua]

key-decisions:
  - "Format detection via data.board_path presence (new) vs data.game (old)"
  - "Roster status lowercase conversion for Rust Alive/Dead → Lua alive/dead"
  - "list_saves and update_display_name updated for dual-format support (not in original plan)"

patterns-established:
  - "New save format: top-level fields from Rust SaveState (board_path, turn, campaign)"
  - "Legacy restore extracted to save._legacy_restore() for old JSON and TOML"

duration: ~45min
completed: 2026-03-10
---

# Phase 106 Plan 01: Save UX Cleanup Summary

**Wired Rust save/load FFI into Lua, replacing ~14 manual FFI calls with single save_json/load_json calls. Deleted TOML serialization dead code.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-10 |
| Tasks | 4 completed (3 auto + 1 human-verify) |
| Files modified | 4 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Save uses single FFI call | Pass | write_save calls norrust.save_json(engine) |
| AC-2: Load uses single FFI call | Pass | load_save calls norrust.load_json(engine, text) for JSON saves |
| AC-3: Legacy TOML saves still load | Pass | _legacy_restore preserves full multi-call path |
| AC-4: Save list UI works with new format | Pass | list_saves detects format via data.board_path |
| AC-5: Dead code removed | Pass | toml_value, toml_array, serialize_toml deleted; parse_save_toml kept for legacy |

## Accomplishments

- Single FFI call save: `norrust.save_json(engine)` replaces manual data table building + json_encode
- Single FFI call load: `norrust.load_json(engine, text)` replaces ~14 separate restore calls
- Deleted ~120 lines of TOML serialization code (toml_value, toml_array, serialize_toml)
- Backward compatibility for old JSON and TOML saves via _legacy_restore
- restore_from_save handles both new (top-level fields) and old (nested game.*) formats
- Campaign roster reconstruction from Rust format (HashMap → Lua entries table, string→number id_map keys)

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/norrust.lua` | Modified | Added FFI declarations + Lua wrappers for save_json, load_json, set_display_name |
| `norrust_love/save.lua` | Modified | Simplified write_save, new load_save with FFI, updated list_saves/update_display_name, deleted TOML serializer |
| `norrust_love/input.lua` | Modified | Updated restore_from_save for new format, removed build_save_campaign_ctx, updated write_save callers |
| `norrust_love/main.lua` | Modified | Updated auto-save write_save call (removed extra params) |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Format detection via `data.board_path` | New saves have top-level board_path; old have data.game.board_path | Clean branching without version flags |
| Extract `_legacy_restore()` helper | Reuse for both old JSON and TOML saves | Avoids code duplication |
| Update list_saves for dual format | New saves have different field paths (turn at top-level, campaign.campaign_def.name) | Not in original plan but necessary for correctness |
| Lowercase Rust enum status | Rust serializes RosterStatus as "Alive"/"Dead", Lua expects "alive"/"dead" | Prevents roster restore bugs |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential for correctness |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Essential fixes, no scope creep.

### Auto-fixed Issues

**1. list_saves dual-format support**
- **Found during:** Task 2 (save simplification)
- **Issue:** list_saves metadata extraction assumed old JSON format (data.game.turn). New saves have data.turn.
- **Fix:** Added format detection branch in list_saves for new vs old JSON
- **Files:** norrust_love/save.lua
- **Verification:** luajit syntax check passes

**2. update_display_name dual-format support**
- **Found during:** Task 2
- **Issue:** update_display_name assumed data.game.display_name. New saves have data.display_name.
- **Fix:** Added format detection branch for new vs old JSON
- **Files:** norrust_love/save.lua
- **Verification:** luajit syntax check passes

## Verification Results

- `luajit -bl norrust_love/save.lua /dev/null` — Pass
- `luajit -bl norrust_love/norrust.lua /dev/null` — Pass
- `luajit -bl norrust_love/input.lua /dev/null` — Pass
- `luajit -bl norrust_love/input_saves.lua /dev/null` — Pass
- `cargo build` — Pass (cdylib unchanged)
- `cargo test` — 118 unit tests passing
- Human verification — Approved

## Next Phase Readiness

**Ready:**
- v3.7 Save System Overhaul milestone complete (phases 104-106 all done)
- Save/load uses clean single-call FFI
- Legacy saves still loadable

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 106-save-ux-cleanup, Plan: 01*
*Completed: 2026-03-10*
