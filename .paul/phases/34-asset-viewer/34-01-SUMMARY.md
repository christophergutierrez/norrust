---
phase: 34-asset-viewer
plan: 01
type: summary
---

## What Was Built

Standalone asset viewer app within the Love2D project, launchable via `--viewer` CLI flag:

- **Left sidebar** (220px): scrollable list of terrain tiles + unit sprites, section headers, keyboard navigation
- **Terrain preview**: raw image centered + hex-clipped version using stencil pattern, metadata (terrain_id, dimensions)
- **Unit animation preview**: large animated frame with spritesheet strip, current frame highlighted, portrait display
- **Controls**: Up/Down navigate list, Left/Right cycle animation states, +/- zoom (0.25x–4.0x), F flip, R reset, 1-5 jump to state, Escape quit
- **Metadata display**: def_id, current animation state, frame N/total, FPS, frame dimensions
- **CLI wiring**: `--viewer` flag in main.lua overrides love callbacks to viewer module (no game code loaded)

## Files Modified

| File | Change |
|------|--------|
| `norrust_love/viewer.lua` | NEW — 443 lines, standalone viewer module |
| `norrust_love/main.lua` | Added `--viewer` CLI flag block (7 lines) |

## Acceptance Criteria Results

| AC | Result | Notes |
|----|--------|-------|
| AC-1: Viewer Launches | ✅ Pass | `love . --viewer` shows asset list, first item selected |
| AC-2: Terrain Preview | ✅ Pass | Raw image + hex-clipped version + metadata |
| AC-3: Unit Animation Preview | ✅ Pass | All 5 states cycle, portrait shown, metadata displayed |
| AC-4: Zoom and Flip | ✅ Pass | +/- zoom, F flip, R reset, mouse wheel zoom |
| AC-5: Game Still Works | ✅ Pass | `love .` launches game normally |

## Decisions Made

| Decision | Rationale |
|----------|-----------|
| Love callback override pattern (not viewer_mode flag) | Cleaner — viewer.load() returns, love.update/draw/keypressed/wheelmoved all redirected |
| Mouse wheel zoom in viewer | Natural zoom UX alongside +/- keyboard |
| Sidebar auto-scroll to keep selection visible | Usability for long asset lists |
| Spritesheet strip below preview (current frame highlighted) | Visual debugging of frame alignment |

## Verification

- [x] `love . --viewer` launches and displays asset list
- [x] Terrain tiles preview with hex-clipped version
- [x] Spearman animations cycle through all states
- [x] Zoom and flip controls work
- [x] `love .` still launches the game normally
- [x] `luajit -bl viewer.lua /dev/null` passes syntax check
- [x] 94 Rust tests passing (unchanged)
- [x] Human verification: approved

## Deferred Issues

None.
