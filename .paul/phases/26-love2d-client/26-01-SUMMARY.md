---
phase: 26-love2d-client
plan: 01
subsystem: presentation
tags: [love2d, luajit-ffi, lua, hex-rendering, game-client]

requires:
  - phase: 25-c-abi-bridge
    provides: 36 extern "C" functions callable via LuaJIT FFI
provides:
  - Complete Love2D game client with full feature parity to game.gd
  - LuaJIT FFI bindings module wrapping all 36 C ABI functions
  - Inline pure-Lua JSON decoder for StateSnapshot parsing
affects: [redot-cleanup]

tech-stack:
  added: [Love2D 11.5, LuaJIT FFI]
  patterns: [ffi.gc destructor attachment, push/pop camera transform, candidate-based pixel_to_hex]

key-files:
  created: [norrust_love/conf.lua, norrust_love/norrust.lua, norrust_love/main.lua]
  modified: [norrust_core/tests/test_ffi.rs]

key-decisions:
  - "hex_to_pixel/pixel_to_hex replaces Godot TileMap — pure math, no engine dependency"
  - "Inline JSON decoder (~90 lines) in norrust.lua — zero external dependencies"
  - "push/pop transform splits board-space drawing from screen-space UI"
  - "ffi.gc attaches norrust_free as destructor — automatic engine cleanup"
  - "reachable_set string-key lookup for O(1) hex containment checks"

patterns-established:
  - "Love2D module pattern: norrust.lua returns M table with Lua-native wrapper functions"
  - "Candidate-based pixel_to_hex: estimate row/col, check 4 nearest hex centers, pick closest"
  - "State parsed once per draw frame (norrust.get_state); passed to all drawing helpers"

duration: ~30min
completed: 2026-03-03
---

# Phase 26 Plan 01: Love2D Client Summary

**Complete Love2D game client (1202 lines across 3 files) porting all game.gd features via LuaJIT FFI — fully playable hex strategy game verified by user.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30min |
| Completed | 2026-03-03 |
| Tasks | 3 completed (2 auto + 1 human-verify) |
| Files created | 3 |
| Files modified | 1 |
| Total Lua lines | 1202 (6 + 365 + 831) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Love2D Window Launches | Pass | `love norrust_love` opens window, .so loads without errors |
| AC-2: Hex Grid Renders With Terrain Colors | Pass | 40 hexes (8x5) with terrain-driven colors from TerrainDef |
| AC-3: Units Render With Faction Colors and Labels | Pass | Blue/red circles, type abbreviations, HP, XP, exhaustion dimming, advancement ring |
| AC-4: Click-Select-Move-Attack Works | Pass | Select → yellow highlights → move → attack all functional |
| AC-5: HUD and Game State Display | Pass | Turn/ToD/Faction/Gold HUD; E key ends turn; win detection with overlay |
| AC-6: AI Opponent Plays Automatically | Pass | AI recruits + plays after player end turn; control returns |
| AC-7: Full Feature Parity | Pass | Setup mode, recruitment, unit panel, camera, advancement all present |
| AC-8: No Rust Core Changes | Pass | 73 tests passing (56 lib + 16 integration + 1 FFI) |

## Accomplishments

- `norrust_love/norrust.lua`: LuaJIT FFI bindings wrapping all 36 C ABI functions with Lua-native types + inline JSON decoder
- `norrust_love/main.lua`: Complete game client (831 lines) porting all game.gd features — hex rendering, input, HUD, panels, camera, AI
- `norrust_love/conf.lua`: Love2D window configuration (1280x720, resizable)
- Pure hex math (hex_to_pixel, pixel_to_hex, hex_polygon) replaces Godot TileMap dependency

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/conf.lua` | Created | Love2D window configuration (title, size, resizable) |
| `norrust_love/norrust.lua` | Created | LuaJIT FFI bindings: 36 C function declarations, .so loading, Lua wrappers, JSON decoder |
| `norrust_love/main.lua` | Created | Complete game client: constants, state, hex math, camera, drawing, input, AI trigger |
| `norrust_core/tests/test_ffi.rs` | Modified | Fixed flaky move test: iterate reachable hexes instead of assuming first is unoccupied |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| hex_to_pixel/pixel_to_hex pure math | Godot TileMap unavailable in Love2D; pointy-top odd-r offset formulas are well-defined | No engine dependency for coordinate conversion |
| Inline JSON decoder in norrust.lua | Love2D/LuaJIT has no JSON parser; external deps prohibited | ~90 lines, handles all StateSnapshot types |
| push/pop camera transform | Separates board-space hex drawing from screen-space UI | Clean architecture; recruit highlights in board space, sidebar in screen space |
| ffi.gc destructor on engine pointer | Automatic cleanup on GC; no explicit free required | Memory-safe even if love.quit not called |
| reachable_set as string-keyed lookup | Array iteration O(n) insufficient for click handler with many hexes | O(1) lookup: "col,row" → true |
| Setup mode (not load_units) | Plan mentioned load_units but game.gd uses interactive setup; game.gd IS the specification | Full setup experience: faction picker → leader placement → playing |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | FFI test reliability |
| Plan vs actual | 1 | Followed game.gd spec over plan detail |

**Total impact:** Minimal — both deviations are improvements.

### Auto-fixed Issues

**1. Flaky FFI integration test**
- **Found during:** Task 2 verification (cargo test)
- **Issue:** `test_ffi_full_game_cycle` assumed first reachable hex was unoccupied; non-deterministic HashMap iteration order caused intermittent DestinationOccupied (-4) failures
- **Fix:** Iterate through all reachable hexes, try each until one succeeds
- **Files:** norrust_core/tests/test_ffi.rs
- **Verification:** All 73 tests pass reliably

### Plan vs Actual

**1. love.load() does not call load_units()**
- **Plan said:** "Load units: norrust.load_units (contested_units.toml)"
- **Actual:** Followed game.gd specification which uses interactive setup mode (faction picker + leader placement)
- **Rationale:** Plan explicitly states "The game.gd IS the specification"; AC-7 requires setup mode
- **Impact:** Correct behavior — matches game.gd exactly

### Deferred Items

None.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Love2D client fully functional — Redot can be safely removed
- All game features verified in Love2D environment
- C ABI bridge proven in production use (not just test)

**Concerns:**
- None

**Blockers:**
- None

---
*Phase: 26-love2d-client, Plan: 01*
*Completed: 2026-03-03*
