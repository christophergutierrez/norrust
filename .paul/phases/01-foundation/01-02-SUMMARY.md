---
phase: 01-foundation
plan: 02
subsystem: infra
tags: [rust, gdextension, gdext, godot, redot, cdylib, gdscript]

requires:
  - phase: 01-foundation plan 01
    provides: norrust_core Rust library initialized with serde/toml deps

provides:
  - norrust_core compiles as cdylib (libnorrust_core.so) for Redot loading
  - NorRustCore GodotClass with get_core_version() exposed to GDScript
  - norrust_client/ Redot project scaffold with directory structure
  - .gdextension config wiring Rust library into Redot
  - Proven cross-language call: GDScript → Rust → GDScript (value return)

affects: [01-03-data-flow, 02-headless-core, 03-presentation-layer]

tech-stack:
  added: [godot 0.2.4 (gdext bindings)]
  patterns:
    - crate-type = ["cdylib", "rlib"] enables both Redot loading and cargo test
    - GDExtension entry point in dedicated gdext_node.rs (not lib.rs)
    - bin/ directory inside norrust_client/ for compiled .so (gitignored)
    - Symlink or copy workflow: cargo build → cp .so → norrust_client/bin/

key-files:
  created:
    - norrust_core/src/gdext_node.rs
    - norrust_client/project.godot
    - norrust_client/norrust_core.gdextension
    - norrust_client/scripts/test_bridge.gd
    - norrust_client/scenes/test_scene.tscn
    - .gitignore
  modified:
    - norrust_core/Cargo.toml
    - norrust_core/src/lib.rs

key-decisions:
  - "crate-type [cdylib, rlib]: both needed — cdylib for Redot, rlib for cargo test"
  - "GDExtension node in gdext_node.rs, not lib.rs — keeps bridge code isolated"
  - "bin/ copy workflow over res:// relative paths — Godot res:// cannot traverse .."
  - "godot crate 0.2.4 compatible with Redot 26.1 (Godot 4.x fork)"

patterns-established:
  - "Redot project lives in norrust_client/, Rust library in norrust_core/"
  - "After cargo build: cp target/debug/libnorrust_core.so ../norrust_client/bin/"
  - "Redot version is 26.1 — use compatibility_minimum = 4.2 in .gdextension"

duration: ~30min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 1 Plan 02: GDExtension Bridge — Summary

**Rust function called from Redot GDScript: `NorRustCore.get_core_version()` prints "Core version: 0.1.0" — cross-language architecture validated.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~30 min |
| Completed | 2026-02-27 |
| Tasks | 3 completed (incl. 1 human-verify checkpoint) |
| Files created | 7 |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: norrust_core compiles as cdylib | Pass | `libnorrust_core.so` (77M debug build); `cargo test` 3/3 still pass |
| AC-2: Redot loads extension without errors | Pass | Extension loaded cleanly; NorRustCore class available in GDScript |
| AC-3: Rust function executes from GDScript | Pass | Output panel showed "Core version: 0.1.0" |

## Accomplishments

- Configured `norrust_core` as both `cdylib` (for Redot) and `rlib` (for tests) — no test regressions
- Implemented `NorRustCore` GodotClass with `get_core_version()` using gdext 0.2.4
- Created complete `norrust_client/` Redot project scaffold with assets/, scenes/, scripts/ structure
- Wired `.gdextension` config to load `bin/libnorrust_core.so` from within the Redot project
- Confirmed Redot 26.1 (Godot 4.x fork) is fully compatible with the godot 0.2.4 crate

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/Cargo.toml` | Modified | Added `[lib] crate-type`, `godot = "0.2"` dependency |
| `norrust_core/src/lib.rs` | Modified | Added `pub mod gdext_node` declaration |
| `norrust_core/src/gdext_node.rs` | Created | `NorRustExtension` entry point + `NorRustCore` GodotClass |
| `norrust_client/project.godot` | Created (editor-reformatted) | Redot project config; main_scene = test_scene.tscn |
| `norrust_client/norrust_core.gdextension` | Created | Maps entry_symbol to platform-specific .so/.dll/.dylib |
| `norrust_client/scripts/test_bridge.gd` | Created | GDScript instantiating NorRustCore + calling get_core_version() |
| `norrust_client/scenes/test_scene.tscn` | Created | Minimal scene with test_bridge.gd attached |
| `norrust_client/bin/.gitkeep` | Created | Tracks bin/ dir; compiled .so goes here (gitignored) |
| `.gitignore` | Created | Ignores target/, .godot/, .redot/, bin/*.so |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `bin/` copy workflow | `res://` in .gdextension cannot traverse `..` outside the project dir | After every `cargo build`, run `cp target/debug/libnorrust_core.so ../norrust_client/bin/` |
| `gdext_node.rs` isolated from `lib.rs` | Keeps GDExtension bridge separate from pure headless logic | All future GDExtension classes added to gdext_node.rs or new files under a `gdext/` module |
| `compatibility_minimum = "4.2"` | Redot 26.1 is a Godot 4.x fork; 4.2 covers the feature set in use | Should work on any Redot 26.x release |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Editor reformats | 1 | None — cosmetic only |
| Scope additions | 0 | — |
| Deferred | 1 | Logged below |

**1. project.godot reformatted by Redot editor**
- Found during: Task 3 checkpoint (editor opened project)
- Issue: Redot reformatted the file, added `"26.1", "Redot"` to features, removed explicit `config/features` from our template
- Fix: Accepted — the editor-managed format is canonical. Source file updated.
- Impact: None; file content is functionally equivalent

### Deferred Items

- Build automation (Makefile or build.sh for `cargo build && cp .so bin/`) — YAGNI for now; manual copy is acceptable for Phase 1

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| None | — |

## Next Phase Readiness

**Ready:**
- `NorRustCore` GodotClass can be extended with any `#[func]` methods
- `bin/` workflow established — all future Rust builds copy .so to same location
- Redot 26.1 + godot 0.2.4 compatibility confirmed

**Concerns:**
- Manual `cp .so` step required after every `cargo build` — friction during active development; a build script will help once Phase 1 is complete
- Debug .so is 77M — release build will be much smaller when shipping

**Blockers:** None

---
*Phase: 01-foundation, Plan: 02*
*Completed: 2026-02-27*
