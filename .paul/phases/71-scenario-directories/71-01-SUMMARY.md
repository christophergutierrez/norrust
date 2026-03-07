---
phase: 71-scenario-directories
plan: 01
type: summary
---

## What Was Built

Scenario directory restructure — each scenario is now self-contained:

- **5 scenario directories** — contested/, crossing/, ambush/, night_orcs/, final_battle/ each containing board.toml, units.toml, and optionally dialogue.toml
- **Campaign TOML updated** — paths now use directory format: "crossing/board.toml", "crossing/units.toml"
- **Dialogue derivation updated** — `board.toml` → `dialogue.toml` in same directory (was `_dialogue.toml` suffix)
- **Save filename updated** — extracts scenario directory name instead of old flat filename
- **Scenario validation updated** — auto-discovery scans subdirectories for board.toml + units.toml pairs
- **All Rust test paths updated** — 8 files with hardcoded scenario paths corrected
- **Symlink pattern for Love2D** — `norrust_love/data -> ../data` with `setSymlinksEnabled(true)` in conf.lua; Love2D's physfs cannot mount plain directories, symlinks are the standard solution

## Acceptance Criteria Results

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | Scenarios in per-directory layout | PASS |
| AC-2 | Campaign loads correctly | PASS |
| AC-3 | Dialogue derives from board directory | PASS |
| AC-4 | All 121 tests pass | PASS |
| AC-5 | Standalone scenario selection works | PASS |

## Files Modified

- `scenarios/` — 5 scenarios restructured from flat files to directories
- `campaigns/tutorial.toml` — updated board/units paths
- `norrust_love/main.lua` — SCENARIOS table, dialogue path derivation
- `norrust_love/save.lua` — scenario name extraction from directory path
- `norrust_love/conf.lua` — added `love.filesystem.setSymlinksEnabled(true)`
- `norrust_love/data` — NEW: symlink to `../data` for Love2D VFS access
- `norrust_love/viewer.lua` — removed failed mount code
- `norrust_core/src/campaign.rs` — updated test assertions
- `norrust_core/src/dialogue.rs` — updated test path
- `norrust_core/tests/campaign.rs` — updated all scenario path assertions
- `norrust_core/tests/dialogue.rs` — updated dialogue path
- `norrust_core/tests/simulation.rs` — updated scenario paths
- `norrust_core/tests/test_ffi.rs` — updated scenario paths
- `norrust_core/tests/scenario_validation.rs` — subdirectory-based discovery

## Tests

- 121 total Rust tests passing
- luajit syntax check: clean

## Decisions

- Symlink pattern: `norrust_love/<dir> -> ../<dir>` + `setSymlinksEnabled(true)` for Love2D access to project-level content directories. `love.filesystem.mount` does not support plain directories on this physfs build.
- Dialogue path: sibling `dialogue.toml` in same directory as `board.toml` (replaces `_dialogue.toml` suffix convention)
- Save filename: extract directory name from `"crossing/board.toml"` → `"crossing"` for save file naming
- Scenario discovery: scan subdirectories for `board.toml` + `units.toml` pairs (replaces flat file suffix matching)

## Deferred Issues

None.
