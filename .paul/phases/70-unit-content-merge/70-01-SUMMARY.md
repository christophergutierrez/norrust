---
phase: 70-unit-content-merge
plan: 01
type: summary
---

## What Was Built

Unit content merge — sprites now live alongside unit TOMLs in `data/units/<name>/`:

- **Registry loader updated** — `Registry::load_from_dir` now scans both flat `.toml` files and immediate subdirectories (`<dirname>/<dirname>.toml`), transparent to callers
- **16 sprite units restructured** — moved from `norrust_love/assets/units/<name>/` into `data/units/<name>/` alongside each unit's TOML definition
- **Asset loader path updated** — `assets.load_unit_sprites` now loads from `data/units/` via `love.filesystem.mount`, terrain tiles remain in `assets/terrain/`
- **`norrust_love/assets/units/` deleted** — no longer needed

## Acceptance Criteria Results

| AC | Description | Result |
|----|-------------|--------|
| AC-1 | Registry loads from both flat TOMLs and subdirectories | PASS |
| AC-2 | Sprites load from data/units/ | PASS |
| AC-3 | Game renders identically | PASS |
| AC-4 | All 121 tests pass | PASS |

## Files Modified

- `norrust_core/src/loader.rs` — `load_from_dir` scans subdirectories for `<dirname>.toml`
- `norrust_love/main.lua` — mount data/ dir, pass "data" to load_unit_sprites
- `norrust_love/viewer.lua` — same mount + path update for asset viewer
- `data/units/` — 16 units converted from flat TOML to self-contained directories
- `norrust_love/assets/units/` — deleted (sprites moved to data/units/)

## Tests

- 121 total Rust tests passing (lib + integration + scenario validation)
- luajit syntax check: clean (main.lua, assets.lua, viewer.lua)

## Decisions

- `love.filesystem.mount(source .. "/../data", "data")` to make data/ accessible in Love2D VFS
- Subdirectory TOML lookup uses `<dirname>/<dirname>.toml` naming convention (not arbitrary single TOML)
- 306 flat unit TOMLs unchanged — only units with sprites get directories

## Deferred Issues

None.
