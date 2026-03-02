# Milestones

Completed milestone log for this project.

| Milestone | Completed | Duration | Stats |
|-----------|-----------|----------|-------|
| v0.1 Initial Release | 2026-02-27 | ~1 day | 5 phases, 13 plans |
| v0.2 Bridge Unification | 2026-02-28 | ~1 day | 1 phase, 1 plan |
| v0.3 Unit Advancement | 2026-02-28 | ~1 day | 3 phases, 4 plans |
| v0.4 AI Opponent | 2026-02-28 | ~1 day | 2 phases, 2 plans |
| v0.5 Unit Content | 2026-03-01 | ~1 day | 2 phases, 2 plans |
| v0.6 Terrain System | 2026-03-01 | ~1 day | 3 phases, 3 plans |
| v0.7 Scenario System | 2026-03-01 | ~1 day | 2 phases, 2 plans |
| v0.8 Combat Completeness | 2026-03-02 | ~1 day | 1 phase, 1 plan |
| v0.9 Game Mechanics | 2026-03-02 | ~1 day | 2 phases, 3 plans |

---

## ✅ v0.9 Game Mechanics

**Completed:** 2026-03-02
**Duration:** ~1 day (same session as v0.8)

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 3 |
| Files changed | ~10 |
| Tests | 69 (55 lib + 14 integration) |

### Key Accomplishments

- **Per-faction gold economy** — `GameState.gold [u32; 2]` starting at [10,10]; villages pay 2g/turn on EndTurn; gold exposed via `StateSnapshot.gold` in JSON
- **FactionDef TOML schema** with `starting_gold` field — applied from faction data at PLAYING transition via `apply_starting_gold()` bridge
- **Full GDScript faction setup flow** — faction picker → leader placement → unit palette placement → PLAYING (all existing; confirmed and extended)
- **`apply_recruit()` pure Rust function** — castle hex validation, gold check (can't go negative), gold deduction, unit placement; fully testable headlessly
- **`ActionError::NotEnoughGold` + `::DestinationNotCastle`** — error codes -8 and -9 extending the existing -1..-7 range
- **`recruit_unit_at()` + `get_unit_cost()` GDExtension bridges** — GDScript recruitment path; same stat-copy pattern as `place_unit_at()`
- **`ActionRequest::Recruit`** in JSON API — AI agents can now recruit units via the external JSON action interface
- **Castle hexes in `scenarios/contested.toml`** — col 0 (faction 0) and col 7 (faction 1) are castle terrain; 5 recruit slots per side
- **GDScript 'R' key recruit panel** — castle hexes highlighted teal, sidebar with unit list + costs, 1-9 key selection, click-to-place, exits mode after placement

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| `gold: [u32; 2]` array (not HashMap) | Exactly 2 factions; array simpler, cheaper than map |
| Village income on newly-active faction's turn | "Gold at start of turn" semantics; consistent with Wesnoth |
| Starting gold 100 per faction (Wesnoth standard) | Enough for several recruits; meaningful economic decisions |
| `apply_starting_gold()` as separate bridge call | GDScript knows both faction IDs only at PLAYING transition |
| `apply_recruit()` free function (not Action variant) | Advance pattern: registry-free, headlessly testable; bridge handles cost lookup |
| Castle validity = terrain_id == "castle" only | No leader adjacency check — minimal and correct |
| Recruit exits mode after one placement | Simpler state; R again to recruit another unit |

---

## ✅ v0.8 Combat Completeness

**Completed:** 2026-03-02
**Duration:** ~1 day

### Stats

| Metric | Value |
|--------|-------|
| Phases | 1 |
| Plans | 1 |
| Files changed | 1 |
| Tests | 65 (54 lib + 11 integration) → 64+1 |

### Key Accomplishments

- **`Tile.defense` wired into combat resolution** as the authoritative middle tier: `unit.defense[terrain_id]` → `tile.defense` → `unit.default_defense`
- Fallback chain applies to **both attack and retaliation** paths
- `test_tile_defense_used_in_combat` — Scenario A (100% tile defense blocks all hits) + Scenario B (0% unit entry overrides tile) both verified

---

## ✅ v0.7 Scenario System

**Completed:** 2026-03-01

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 2 |
| Tests | 56 (46 lib + 10 integration) |

### Key Accomplishments

- `BoardDef` TOML schema + `scenario::load_board()` pure Rust — board dimensions and terrain from file
- `UnitPlacement`/`UnitsDef` TOML schema + `scenario::load_units()` — unit starting positions from file
- `scenarios/contested.toml` + `scenarios/contested_units.toml` — first hand-authored scenario
- game.gd startup: 14+ lines of hardcoded setup replaced by `load_board()` + `load_units()`

---

## ✅ v0.6 Terrain System

**Completed:** 2026-03-01

### Stats

| Metric | Value |
|--------|-------|
| Phases | 3 |
| Plans | 3 |
| Tests | 53 (45 lib + 8 integration) |

### Key Accomplishments

- `Tile` runtime struct — per-hex autonomous properties (terrain_id, movement_cost, defense, healing, color)
- `generate_map()` procedural map generator with deterministic XOR noise seed
- Full color data chain: `TerrainDef.color` → `Tile.color` → `TileSnapshot.color` → GDScript rendering
- 14 terrain TOMLs with distinct hex color values

---

## ✅ v0.5 Unit Content

**Completed:** 2026-03-01

### Stats

| Metric | Value |
|--------|-------|
| Phases | 2 |
| Plans | 2 |
| Tests | 50 (44 lib + 6 integration) |

### Key Accomplishments

- `UnitDef` schema expanded: race, cost, usage, abilities, alignment (all serde default)
- `parse_alignment()` single conversion point; alignment wired from TOML to Unit at spawn and advance
- `tools/scrape_wesnoth.py` — stdlib-only WML → TOML scraper
- 318 Wesnoth unit TOMLs generated; all 322 units load via Registry<UnitDef>

---

## ✅ v0.4 AI Opponent

**Completed:** 2026-02-28

### Key Accomplishments

- `ai_take_turn(state, faction)` — greedy expected-damage scorer with march fallback; pure Rust
- Human vs AI opponent fully playable: 'E' auto-triggers faction 1 AI

---

## ✅ v0.3 Unit Advancement

**Completed:** 2026-02-28

### Key Accomplishments

- XP gain (1/hit + 8 kill bonus, both sides), `advancement_pending` auto-set
- `advance_unit()` free function + `apply_advance()` bridge + `ActionRequest::Advance` JSON API
- Visual: gold arc ring on pending units, XP progress text, 'A' key handler

---

## ✅ v0.2 Bridge Unification

**Completed:** 2026-02-28

### Key Accomplishments

- `StateSnapshot` JSON as sole unit data source — removed all flat array bridge methods
- `_parse_state()` helper parses JSON once per frame/input cycle

---

## ✅ v0.1 Initial Release

**Completed:** 2026-02-27

### Key Accomplishments

- Rust headless simulation core: hex grid (cubic coordinates), GameState, A* pathfinding, ZOC, combat resolution
- GDExtension bridge connecting Rust core to Redot presentation
- TOML data schemas + generic Registry<T> loader
- Full Wesnoth-style combat: adjacency enforcement, bidirectional retaliation, time-of-day modifiers, resistances

---
*MILESTONES.md — Updated: 2026-03-02 (v0.9 Game Mechanics)*
