---
phase: 01-foundation
plan: 03
subsystem: data
tags: [rust, gdextension, registry, toml, gdscript, end-to-end]

requires:
  - phase: 01-foundation plan 01
    provides: Registry<T> data loader, UnitDef/TerrainDef structs
  - phase: 01-foundation plan 02
    provides: NorRustCore GodotClass, Redot project scaffold

provides:
  - NorRustCore.load_data(path) — loads Registry<UnitDef> + Registry<TerrainDef> from disk
  - NorRustCore.get_unit_max_hp(id) — queries unit data from GDScript
  - Full round-trip validated: Disk → TOML → Rust → GDExtension → Redot console

affects: [02-headless-core, 03-presentation-layer]

tech-stack:
  added: []
  patterns:
    - GDScript passes absolute path via ProjectSettings.globalize_path("res://") + "/../data"
    - Rust Option<Registry<T>> fields on GodotClass — None until load_data() called
    - Return -1 (not panic/error) for not-found queries from GDScript

key-files:
  modified:
    - norrust_core/src/gdext_node.rs
    - norrust_client/scripts/test_bridge.gd

key-decisions:
  - "load_data(path: GString) takes path from GDScript — Rust stays path-agnostic"
  - "Return -1 for not-found rather than Option<i32> — GDScript has no Option type"
  - "godot_print! for load_data confirmation — visible in Redot Output panel"

patterns-established:
  - "All GDScript → Rust data queries: pass absolute paths, return sentinel values for not-found"
  - "GDScript uses ProjectSettings.globalize_path('res://') to build absolute OS paths"

duration: ~15min
started: 2026-02-27T00:00:00Z
completed: 2026-02-27T00:00:00Z
---

# Phase 1 Plan 03: End-to-End Data Flow — Summary

**Full Disk → TOML → Rust Registry → GDExtension → Redot round-trip validated: Fighter HP=30, Archer HP=25 confirmed from TOML files.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Completed | 2026-02-27 |
| Tasks | 3 (incl. 1 human-verify checkpoint) |
| Files modified | 2 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Registry loads via GDExtension | Pass | `load_data()` returns true; 2 units, 2 terrain loaded |
| AC-2: Unit data queryable from GDScript | Pass | fighter=30, archer=25, dragon=-1 all correct |
| AC-3: Full round-trip in Redot console | Pass | All 5 expected lines confirmed in Output panel |

## Confirmed Output

```
Core version: 0.1.0
load_data: loaded 2 units, 2 terrain types
Fighter HP: 30
Archer HP: 25
Dragon HP: -1
```

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/gdext_node.rs` | Modified | Added `units`/`terrain` Registry fields, `load_data()`, `get_unit_max_hp()` |
| `norrust_client/scripts/test_bridge.gd` | Modified | Calls `load_data()` and queries HP for 3 unit IDs |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `load_data(path: GString)` takes path from GDScript | Rust stays path-agnostic; GDScript knows project layout | All future data queries use same pattern |
| Return `-1` for not-found | GDScript has no `Option` type; -1 is a clear sentinel | Convention: negative values = not-found/error from Rust |
| `ProjectSettings.globalize_path("res://") + "/../data"` | Builds absolute OS path; works regardless of Redot's cwd | All future GDScript → OS path conversions use this pattern |

## Deviations from Plan

None — executed exactly as planned.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- `NorRustCore` is now a data query interface — Phase 2 adds simulation methods to it
- Path-to-data pattern established for all future GDScript integrations
- Registry<UnitDef> and Registry<TerrainDef> load confirmed working in Redot context

**Concerns:**
- `factions.toml` schema still not designed — needed before Phase 4 recruitment
- Only `max_hp` queried from GDScript — Phase 3 will need movement_costs, defense, attacks

**Blockers:** None

---
*Phase: 01-foundation, Plan: 03*
*Completed: 2026-02-27*
*Phase 1 COMPLETE — all 3 plans unified*
