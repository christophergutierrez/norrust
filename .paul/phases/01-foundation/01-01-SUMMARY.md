---
phase: 01-foundation
plan: 01
subsystem: data
tags: [rust, serde, toml, registry, schema]

requires: []

provides:
  - norrust_core Rust library (cargo --lib, edition 2021)
  - UnitDef, TerrainDef, AttackDef serde structs
  - Generic Registry<T> data loader from TOML directories
  - Mock data: fighter, archer (units), grassland, forest (terrain)
  - GameState stub (empty, for GDExtension API boundary)

affects: [02-headless-core, 01-02-gdextension]

tech-stack:
  added: [serde 1, toml 0.8, thiserror 2]
  patterns:
    - Per-file TOML layout (one entity per .toml file)
    - Generic Registry<T: DeserializeOwned + IdField> keyed by entity id
    - CARGO_MANIFEST_DIR for test-time path resolution

key-files:
  created:
    - norrust_core/Cargo.toml
    - norrust_core/src/lib.rs
    - norrust_core/src/schema.rs
    - norrust_core/src/loader.rs
    - data/units/fighter.toml
    - data/units/archer.toml
    - data/terrain/grassland.toml
    - data/terrain/forest.toml

key-decisions:
  - "Per-file TOML: one entity per file (not arrays-of-tables)"
  - "Generic Registry<T> with IdField trait avoids duplicating loader logic"
  - "symbol: String not char — serde/toml char deserialization is fragile"
  - "No gdext in this plan — headless core must compile without Redot dependency"

patterns-established:
  - "Data files live at repo root data/{type}/{id}.toml"
  - "CARGO_MANIFEST_DIR used in tests for absolute path resolution"
  - "thiserror for all error types in norrust_core"

duration: ~15min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 1 Plan 01: Foundation & Data Schema — Summary

**Generic `Registry<T>` loader and Serde TOML schemas established; 3 unit tests pass, clippy clean.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Completed | 2026-02-27 |
| Tasks | 3 completed |
| Files created | 8 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: TOML Schemas Round-Trip Through Serde | Pass | `test_unit_registry_loads` and `test_terrain_registry_loads` both pass |
| AC-2: Registry Loads All Files From a Directory | Pass | `registry.len() == 2` for both unit and terrain dirs; `get("nonexistent")` returns None |
| AC-3: Cargo Build and Tests Pass Clean | Pass | `cargo test`: 3/3 passed; `cargo clippy -- -D warnings`: 0 warnings |

## Accomplishments

- Initialized `norrust_core` Rust library with serde, toml, thiserror dependencies
- Defined `UnitDef`, `TerrainDef`, `AttackDef` structs with full Wesnoth-inspired schema (resistances, movement costs, defense by terrain)
- Implemented `Registry<T>` — a generic, reusable keyed store loaded from a directory of TOML files
- Created 4 mock data files (2 units, 2 terrain) with values matching Wesnoth conventions
- Established `GameState {}` stub as the future GDExtension API boundary

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/Cargo.toml` | Created | Library manifest with serde/toml/thiserror deps |
| `norrust_core/rustfmt.toml` | Created | Code style: edition 2021, max_width 100 |
| `norrust_core/src/lib.rs` | Created | Module declarations + `GameState {}` stub |
| `norrust_core/src/schema.rs` | Created | `UnitDef`, `TerrainDef`, `AttackDef` structs |
| `norrust_core/src/loader.rs` | Created | `Registry<T>`, `RegistryError`, `IdField` trait + 3 tests |
| `data/units/fighter.toml` | Created | Fighter: hp=30, sword 7×3 blade/melee |
| `data/units/archer.toml` | Created | Archer: hp=25, bow 5×4 pierce/ranged |
| `data/terrain/grassland.toml` | Created | Grassland: def=40, cost=1 |
| `data/terrain/forest.toml` | Created | Forest: def=60, cost=2 |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Per-file TOML layout | Cleaner than arrays-of-tables; adding a unit = adding one file | All future data follows this convention |
| `Registry<T>` with `IdField` trait | Reusable for units, terrain, factions — avoids duplicating loader logic | Plan 01-02+ can load faction.toml with zero new loader code |
| `symbol: String` not `char` | Serde/toml char deserialization is unreliable; String avoids runtime panics | TerrainDef.symbol accessed as `&str` in future rendering |
| `CARGO_MANIFEST_DIR` in tests | Absolute path independent of working directory | Tests will pass from any invocation context |
| No gdext dependency | Headless core must compile without Redot; GDExtension added in 01-02 | `cargo build` stays fast, no C++ toolchain needed for pure logic work |

## Deviations from Plan

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | None — proactive, not reactive |
| Scope additions | 0 | — |
| Deferred | 2 | Logged below |

**1. Type change: `symbol: char` → `symbol: String`**
- Found during: Task 2 (schema definition), before compilation
- Issue: TOML's serde deserializer doesn't reliably handle `char` — a single-char string parses fine but `char` deserialization behavior is deserializer-dependent
- Fix: Changed `TerrainDef.symbol` to `String`; updated TOML data files accordingly
- Verification: All 3 tests pass without char-related panics

### Deferred Items

- `factions.toml` schema not designed — deferred to Phase 2 when recruitment logic is implemented
- Shared attack templates (a separate `attacks.toml`) — YAGNI for now; unit attacks embedded in unit files

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| `loader.rs` not yet created when `cargo build` first ran | Expected — build confirmed schema compiled before adding loader |

## Next Phase Readiness

**Ready:**
- `Registry<UnitDef>` and `Registry<TerrainDef>` usable immediately in Phase 2 game logic
- `GameState {}` stub in place for GDExtension boundary definition
- Data schema patterns established — factions/attacks follow same per-file TOML convention

**Concerns:**
- `factions.toml` schema needs design before recruitment system (Phase 4)
- `symbol: String` on TerrainDef means callers must validate it's a single char if needed for ASCII rendering

**Blockers:** None

---
*Phase: 01-foundation, Plan: 01*
*Completed: 2026-02-27*
