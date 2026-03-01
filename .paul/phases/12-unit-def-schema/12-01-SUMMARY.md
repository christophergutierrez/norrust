---
phase: 12-unit-def-schema
plan: 01
subsystem: simulation
tags: [rust, schema, serde, unitdef, attackdef, alignment, toml]

requires:
  - phase: 11-ai-bridge-gdscript
    plan: 01
    provides: stable GDExtension bridge, place_unit_at() API, 49 passing tests

provides:
  - UnitDef expanded with race, cost, usage, abilities, alignment (all serde default)
  - AttackDef expanded with specials (serde default)
  - parse_alignment() pub helper in unit.rs
  - alignment wired: TOML string → parse_alignment() → Unit.alignment at spawn and advance
  - 4 unit TOMLs updated with alignment field

affects: [13-wesnoth-data-import]

tech-stack:
  added: []
  patterns:
    - "#[derive(Default)] on schema structs + ..Default::default() in test constructions"
    - "parse_alignment() as single conversion point from string to Alignment enum"
    - "default_alignment() fn for #[serde(default = \"default_alignment\")] — non-Default default"

key-files:
  created: []
  modified:
    - norrust_core/src/schema.rs
    - norrust_core/src/unit.rs
    - norrust_core/src/gdext_node.rs
    - norrust_core/src/game_state.rs
    - norrust_core/src/ai.rs
    - norrust_core/tests/simulation.rs
    - data/units/fighter.toml
    - data/units/archer.toml
    - data/units/hero.toml
    - data/units/ranger.toml

key-decisions:
  - "#[derive(Default)] on AttackDef and UnitDef enables ..Default::default() in all test constructions"
  - "parse_alignment() maps 'neutral' → Liminal (same ToD modifier); Neutral variant deferred"
  - "alignment default_alignment() fn returns 'liminal' — serde default, not Rust Default (which would be '')"

patterns-established:
  - "New schema fields: #[serde(default)] for zero-value fields, #[serde(default = 'fn')] for non-zero defaults"
  - "Stat copy at place_unit_at(): extend tuple destructure, add parse/copy line — same pattern as xp_needed"

duration: ~15min
started: 2026-03-01T00:00:00Z
completed: 2026-03-01T00:00:00Z
---

# Phase 12 Plan 01: UnitDef Schema Expansion Summary

**UnitDef and AttackDef expanded with 6 new serde-default fields; alignment wired from TOML registry to Unit at spawn and advance — 49 tests pass, no regressions.**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~15 min |
| Started | 2026-03-01 |
| Completed | 2026-03-01 |
| Tasks | 2 auto |
| Files modified | 10 |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: New Fields Load via Serde Without Breaking Existing TOMLs | Pass | All 4 TOMLs load; `#[serde(default)]` fills new fields transparently ✓ |
| AC-2: Alignment Wired from Registry to Runtime Unit | Pass | `place_unit_at()` calls `parse_alignment(&def.alignment)` → `Unit.alignment` ✓ |
| AC-3: advance_unit Copies Alignment from Target Def | Pass | `advance_unit()` copies `parse_alignment(&new_def.alignment)` after resistances ✓ |
| AC-4: No Regressions | Pass | 44 lib + 5 integration = 49 tests, all pass ✓ |

## Accomplishments

- `AttackDef`: added `specials: Vec<String>` with `#[serde(default)]`; `#[derive(Default)]` added
- `UnitDef`: added `race`, `cost`, `usage`, `abilities` (all `#[serde(default)]`); `alignment` with `#[serde(default = "default_alignment")]`; `#[derive(Default)]` added
- `parse_alignment(s: &str) -> Alignment`: "lawful"→Lawful, "chaotic"→Chaotic, anything else→Liminal; added as `pub` in `unit.rs`
- `place_unit_at()`: extended def_stats tuple to include `alignment`; `unit.alignment = parse_alignment(&alignment)` set at spawn
- `advance_unit()`: `unit.alignment = parse_alignment(&new_def.alignment)` added after resistances copy
- `..Default::default()` added to 16 struct literal constructions across 5 files (game_state.rs ×7, simulation.rs ×6, ai.rs ×1, unit.rs ×2)
- All 4 unit TOMLs updated: fighter/hero = "lawful", archer/ranger = "neutral"

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_core/src/schema.rs` | Modified | Added `#[derive(Default)]` to both structs; `specials` to AttackDef; `race/cost/usage/abilities/alignment` to UnitDef; `default_alignment()` fn |
| `norrust_core/src/unit.rs` | Modified | Added `parse_alignment()` pub fn; `advance_unit()` copies alignment |
| `norrust_core/src/gdext_node.rs` | Modified | Import `parse_alignment`; extend `place_unit_at()` def_stats tuple; copy alignment at spawn |
| `norrust_core/src/game_state.rs` | Modified | Added `..Default::default()` to 7 AttackDef test constructions |
| `norrust_core/src/ai.rs` | Modified | Added `..Default::default()` to 1 AttackDef test construction |
| `norrust_core/tests/simulation.rs` | Modified | Added `..Default::default()` to 6 AttackDef + 2 UnitDef test constructions |
| `data/units/fighter.toml` | Modified | `alignment = "lawful"` added |
| `data/units/archer.toml` | Modified | `alignment = "neutral"` added |
| `data/units/hero.toml` | Modified | `alignment = "lawful"` added |
| `data/units/ranger.toml` | Modified | `alignment = "neutral"` added |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| `#[derive(Default)]` on AttackDef and UnitDef | Enables `..Default::default()` in ~16 test constructions without touching each field | Future schema additions need only 1 line per test file |
| "neutral" maps to Liminal | Same ToD modifier (no bonus/penalty); Neutral variant deferred until dusk/dawn time periods added | No Neutral enum variant; parse_alignment() boundary is clean |
| `default_alignment()` fn returns "liminal" | `#[serde(default = "fn")` for non-zero defaults; Rust Default gives "" which would also parse to Liminal but is semantically wrong | TOML files without alignment field get Liminal correctly |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 0 | — |
| Scope additions | 0 | — |
| Deferred | 0 | — |

**Total impact:** Zero deviations — plan executed exactly as written.

## Issues Encountered

None.

## Next Phase Readiness

**Ready:**
- Schema accepts 218-unit TOML set from Phase 13 (all Wesnoth fields present with serde defaults)
- alignment ToD pipeline complete: TOML string → Alignment enum at spawn and advance
- 49 tests provide full regression coverage

**Concerns:**
- None identified.

**Blockers:**
- None — Phase 12 complete, Phase 13 (Wesnoth Data Import) unblocked.

---
*Phase: 12-unit-def-schema, Plan: 01*
*Completed: 2026-03-01*
