---
phase: 07-advancement-schema
plan: 01
subsystem: schema
tags: [rust, serde, toml, unit, snapshot, gdextension]

requires:
  - phase: 06-bridge-unification
    provides: StateSnapshot JSON as sole unit data source; UnitSnapshot struct

provides:
  - UnitDef.level / .experience / .advances_to fields (TOML-loaded, serde default)
  - hero.toml and ranger.toml — level-2 unit definitions
  - Unit.xp / .xp_needed / .advancement_pending runtime fields
  - place_unit_at() copies xp_needed from registry at spawn time
  - UnitSnapshot JSON exposes xp, xp_needed, advancement_pending to GDScript/AI

affects: [08-xp-advancement-logic, 09-advancement-presentation]

tech-stack:
  added: []
  patterns:
    - "#[serde(default)] on new TOML fields — backward-compat; existing files without field still load"
    - "xp_needed set at spawn (place_unit_at) from registry — Unit is registry-free at runtime"
    - "UnitSnapshot maps all Unit fields — JSON is complete picture of unit state"

key-files:
  created:
    - data/units/hero.toml
    - data/units/ranger.toml
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/unit.rs
    - norrust_core/src/snapshot.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/src/loader.rs
    - data/units/fighter.toml
    - data/units/archer.toml

key-decisions:
  - "#[serde(default)] on all three UnitDef fields — old TOML files remain valid without changes"
  - "xp_needed copied from def.experience at place_unit_at() — runtime Unit stays registry-free"
  - "advancement_pending field is data only in this phase — logic to set/clear it comes in Phase 8"

patterns-established:
  - "New TOML fields use #[serde(default)] or #[serde(default = \"fn\")] to preserve backward compat"
  - "All Unit state is mirrored in UnitSnapshot — GDScript and AI always have complete picture"

duration: ~20min
started: 2026-02-28T00:00:00Z
completed: 2026-02-28T00:00:00Z
---

# Phase 7 Plan 01: Advancement Schema Summary

**Extended UnitDef, Unit, and UnitSnapshot with advancement fields; created hero.toml and ranger.toml as level-2 unit definitions with dual-attack loadouts.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~20 min |
| Started | 2026-02-28 |
| Completed | 2026-02-28 |
| Tasks | 3 completed (all auto) |
| Files modified | 9 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: UnitDef Schema Has Advancement Fields | Pass | `level`, `experience`, `advances_to` added with `#[serde(default)]` |
| AC-2: TOML Files Carry Advancement Data | Pass | fighter/archer updated; hero.toml and ranger.toml created |
| AC-3: Unit Runtime Struct Has XP Fields | Pass | `xp`, `xp_needed`, `advancement_pending` on Unit; place_unit_at() sets xp_needed |
| AC-4: UnitSnapshot JSON Includes XP Fields | Pass | New test confirms `"xp":0`, `"xp_needed":0`, `"advancement_pending":false` in JSON |
| AC-5: All Existing Tests Still Pass | Pass | 37 tests pass (36 lib + 1 integration); 0 failures |

## Accomplishments

- Advancement chain complete end-to-end in data: fighter→hero (level 2, 45hp, sword+shield), archer→ranger (level 2, 38hp, bow+sword)
- All new UnitDef fields use `#[serde(default)]` so every existing TOML and test continues to work unchanged
- `xp_needed` set from registry at spawn time; runtime `Unit` stays fully registry-free (consistent with prior decisions)
- `UnitSnapshot` JSON is now a complete picture of unit state including advancement readiness

## Task Commits

No atomic task commits (batched into phase commit).

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/schema.rs` | Modified | Added `level`, `experience`, `advances_to` to `UnitDef` + `default_level()` helper |
| `norrust_core/src/unit.rs` | Modified | Added `xp`, `xp_needed`, `advancement_pending` to `Unit` struct and `Unit::new()` |
| `norrust_core/src/snapshot.rs` | Modified | Added three XP fields to `UnitSnapshot`; updated `from_game_state()`; added serialization test |
| `norrust_core/src/gdext_node.rs` | Modified | `place_unit_at()` extracts and copies `def.experience` into `unit.xp_needed` |
| `norrust_core/src/loader.rs` | Modified | Updated `test_unit_registry_loads`: count 4→4, asserted new fields, added hero/ranger assertions |
| `data/units/fighter.toml` | Modified | Added `level=1`, `experience=40`, `advances_to=["hero"]` |
| `data/units/archer.toml` | Modified | Added `level=1`, `experience=40`, `advances_to=["ranger"]` |
| `data/units/hero.toml` | Created | Level-2 fighter: 45hp, sword (9×4) + shield bash (6×2), blade resistance +20 |
| `data/units/ranger.toml` | Created | Level-2 archer: 38hp, bow (7×4) + short sword (5×2), forest movement=1 |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `#[serde(default)]` on all three UnitDef fields | Existing TOML files (and test fixtures) load without changes | Future unit types without advancement defined still load safely |
| `xp_needed` set from `def.experience` at `place_unit_at()` | Keeps runtime Unit registry-free — consistent with `attacks`, `resistances`, etc. | Phase 8 can check `unit.xp >= unit.xp_needed` without registry access |
| `advancement_pending` is data-only in Phase 7 | Logic to set/clear it (on combat XP gain / Advance action) belongs in Phase 8 | No premature logic; field defaults to false, ready for Phase 8 to drive |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 1 | Minor — test update required by scope of data changes |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Single necessary test update; no scope creep.

### Auto-fixed Issues

**1. loader.rs test hardcoded registry count = 2**
- **Found during:** Task 2 verify (`cargo test`)
- **Issue:** `test_unit_registry_loads` asserted `registry.len() == 2`; adding hero.toml + ranger.toml made it 4
- **Fix:** Updated assertion to `== 4`; added assertions for hero/ranger presence and new advancement fields on fighter
- **Files:** `norrust_core/src/loader.rs`
- **Verification:** `cargo test` → 37 passed, 0 failed

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- `Unit.xp`, `Unit.xp_needed`, `Unit.advancement_pending` exist — Phase 8 can implement XP gain and `Action::Advance`
- `UnitSnapshot` JSON already exposes advancement state — GDScript and AI clients receive it without further bridge changes
- Advancement chains defined in data: fighter→hero, archer→ranger — Phase 8 can look up `def.advances_to` for the target type

**Concerns:**
- None

**Blockers:**
- None — Phase 8 (XP & Advancement Logic) may begin immediately

---
*Phase: 07-advancement-schema, Plan: 01*
*Completed: 2026-02-28*
