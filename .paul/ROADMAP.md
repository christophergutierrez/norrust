# Roadmap: The Clash for Norrust

## Overview

A hex-based strategy game with a headless Rust simulation core and Love2D presentation layer. The Rust core handles all game logic; Love2D renders state via LuaJIT FFI through a C ABI bridge.

## Current Milestone

**v4.0 Unit Content Completeness**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 115 | Missing Units + Cleanup | 1/1 | ✅ Complete | 2026-03-11 |
| 116 | Stat Verification | 1/1 | ✅ Complete | 2026-03-11 |
| 117 | Integration Validation | 1/1 | ✅ Complete | 2026-03-11 |

## v4.0 Phase Details

### Phase 115: Missing Units + Cleanup

Focus: Create General TOML (Lieutenant → General), remove legacy orphan units (hero, fighter, archer), verify all advances_to chains resolve to real unit definitions.
Depends on: None
Constraints: Data-only; zero Rust code changes. Wesnoth WML is reference source.

### Phase 116: Stat Verification

Focus: Audit all ~114 unit stats against Wesnoth WML source data. Fix incorrect movement_costs, defense, resistances, attacks, abilities values.
Depends on: Phase 115 (clean unit tree)
Constraints: scrape_wesnoth.py available for bulk re-scraping if needed.

### Phase 117: Integration Validation

Focus: Run full test suite, verify all factions recruit and advance correctly in-game via debug scenarios. Regenerate debug data.
Depends on: Phase 116 (correct stats)

---

## Previous Milestones

**v4.0 Unit Content Completeness**
Status: ✅ Complete
Phases: 3 of 3 complete
Completed: 2026-03-11

**v3.9 Debug Sandbox**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 112 | Debug Config + Generator Tool | 1 | ✅ Complete | 2026-03-11 |
| 113 | Debug Launch Mode + Cheat Keys | 1 | ✅ Complete | 2026-03-11 |
| 114 | Test Scenarios + Polish | 1 | ✅ Complete | 2026-03-11 |

## v3.9 Phase Details

### Phase 112: Debug Config + Generator Tool

Focus: Create debug_config.toml schema with defaults (xp_to_advance, starting_gold, HP overrides). Python generator tool reads config, copies real unit/scenario TOMLs into debug/data/, patches overridden fields. Lives in tools/ alongside existing generators.
Depends on: None
Constraints: Zero changes to norrust_core. Generator is standalone Python tool.
Plans: 1 (112-01: execute — complete)
Result: generate_debug.py produces 131 units (114 patched), 4 factions, 15 terrain, 4 recruit groups with per-unit override support

### Phase 113: Debug Launch Mode + Cheat Keys

Focus: --debug flag or similar launch mechanism switches Love2D data path from data/ to debug/data/. Minimal conf.lua touch (one if). debug.lua loaded only in debug mode with cheat keys: X = max XP, G = add gold, T = cycle ToD.
Depends on: Phase 112 (debug data must exist to load)
Plans: 1 (113-01: execute — complete)
Result: --debug flag switches data paths, 3 cheat FFI functions added, X/G/T keys gated behind debug_mode

### Phase 114: Test Scenarios + Polish

Focus: Pre-built debug scenarios for common test cases (small board, units adjacent, multi-advancement paths). Verify end-to-end debug workflow. Documentation.
Depends on: Phase 113 (launch mode must work)
Plans: 1 (114-01: execute — complete)
Result: 2 debug scenarios (advance + recruit) with 8x5 boards, attack damage patching, Dark Sorcerer leader ability fix

---

## v3.8 Phase Details

### Phase 107: Unit Tree Audit

Focus: Enumerate all ~90 units across 4 factions (Loyalists, Rebels, Northerners, Undead). Verify which TOMLs exist, which are missing, which have incorrect stats or advancement wiring. Produce definitive unit list as reference for subsequent phases.
Depends on: None
Plans: 1 (107-01: research — complete)
Result: 95 unique units identified, UNIT-REGISTRY.md created with status audit and proposed directory tree

### Phase 108: Directory Reorganization + Recursive Loader

Focus: Move units into tree-structured directories mirroring advancement paths (e.g., `data/units/spearman/swordsman/royal_guard/`). Update registry loader (`load_from_dir`) to recurse arbitrarily deep. All existing tests pass with new directory layout.
Depends on: Phase 107 (need definitive unit list before reorganizing)

### Phase 109: TOML Completion + Advancement Wiring

Focus: Create/fix all ~90 unit TOMLs with correct stats, attacks, and `advances_to` fields. Update faction recruit groups to include all missing units (Horseman, Fencer, Merman Fighter, Wose, Merman Hunter, Troll Whelp, Wolf Rider, Naga Fighter, Goblin Spearman). Create Undead faction TOML + recruit group. Test advancement chains end-to-end.
Depends on: Phase 108 (TOMLs must be in correct directory structure)

### Phase 110: Sprite Generation

Focus: Batch generate sprites for all units missing them (~70+ units) using existing `tools/generate_sprites.py` pipeline. Verify all sprites in asset viewer. Update `unit_prompts.toml` with descriptions for each new unit.
Depends on: Phase 109 (all TOMLs must exist before generating sprites for them)

### Phase 111: Faction Integration + Polish

Focus: Undead faction fully playable. Faction selection shows 4 factions. Update scenarios if needed for new faction support. End-to-end testing of all advancement paths across all 4 factions.
Depends on: Phase 110 (sprites must exist for visual completeness)
Plans: 1 (111-01: execute — complete)
Result: Fixed campaign "orcs" → "northerners", all 145 tests pass, all 4 factions operational

---

## Completed Milestones

### v3.8 Unit Expansion

Status: ✅ Complete
Completed: 2026-03-11
Phases: 5 of 5 complete

### v3.7 Save System Overhaul

Status: ✅ Complete
Completed: 2026-03-10
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 104 | Campaign State in Rust | 1/1 | ✅ Complete | 2026-03-10 |
| 105 | JSON Save Format | 1/1 | ✅ Complete | 2026-03-10 |
| 106 | Save UX Cleanup | 1/1 | ✅ Complete | 2026-03-10 |

### v3.6 AI Leader Intelligence

Status: ✅ Complete
Completed: 2026-03-10
Phases: 2 of 2 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 102 | Recruit-First Ordering | 1/1 | ✅ Complete | 2026-03-10 |
| 103 | Leader 2-Ply Lookahead | 1/1 | ✅ Complete | 2026-03-10 |

### v3.5 AI Overhaul

Status: ✅ Complete
Phases: 5 of 5 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 97 | Recruit Discipline | 1/1 | ✅ Complete | 2026-03-10 |
| 98 | State Evaluation | 1/1 | ✅ Complete | 2026-03-10 |
| 99 | 1-Ply Unit Lookahead | 1/1 | ✅ Complete | 2026-03-10 |
| 100 | Turn Planning | 1/1 | ✅ Complete | 2026-03-10 |
| 101 | Ranged & Tactical Behavior | 1/1 | ✅ Complete | 2026-03-10 |

## v3.5 Phase Details

### Phase 97: Recruit Discipline

Focus: AI fills all castle slots before moving leader away from keep. Mixed unit type recruitment instead of always picking the most expensive unit.
Plans: TBD (defined during /paul:plan)

### Phase 98: State Evaluation

Focus: Evaluation function scoring game states by HP totals, unit count, village control, positional value (proximity to objectives/enemies), leader safety.
Depends on: None (independent utility module)
Plans: TBD (defined during /paul:plan)

### Phase 99: 1-Ply Unit Lookahead

Focus: Clone GameState per unit, try all move+attack combos, pick the action that produces the best evaluated state. Replaces greedy expected-damage scoring.
Depends on: Phase 98 (needs eval function)
Plans: TBD (defined during /paul:plan)

### Phase 100: Turn Planning

Focus: Simulate entire turn across all units. Try different unit orderings and move combinations. Beam search keeping top N candidate states to find best coordinated plan.
Depends on: Phase 99 (needs per-unit lookahead as building block)
Plans: TBD (defined during /paul:plan)

### Phase 101: Ranged & Tactical Behavior

Focus: Ranged units prefer attacking from distance and avoid adjacent positioning. Focus fire on wounded enemies to secure kills. Retreat badly wounded units toward villages/healing terrain.
Depends on: Phase 100 (tactical behaviors layer on top of turn planner)
Plans: TBD (defined during /paul:plan)

---

## Previous Milestone

**v3.4 Sprite Pipeline v2**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 94 | Pipeline Core | 2 | ✅ Complete | 2026-03-09 |
| 95 | Death Removal + Viewer | 1 | ✅ Complete | 2026-03-09 |
| 96 | Batch Generation + Cleanup | 1 | ✅ Complete | 2026-03-09 |

## v3.4 Phase Details

### Phase 94: Pipeline Core

**Goal:** Build generate/process/validate functions as composable pipeline. Single-pose-per-call via Gemini API with reference image feedback. Validation loop with direction check (auto-flip), multi-blob detection, size enforcement (<30KB hard limit), edge quality. Portrait pipeline with separate prompt (painterly, black bg, close-up). CLI tool with --unit, --redo, --base flags.
**Depends on:** None (prototype exists in generate_sprites_v2.py)

**Plans:**
- 94-01: Sprite validation + retry loop (direction auto-flip, multi-blob, size, edges)
- 94-02: Portrait pipeline (separate prompt, black bg, process + validate)

### Phase 95: Death Removal + Viewer

**Goal:** Remove death pose from generation pipeline. Derive death animation at render time from idle (rotate + fade). Finalize viewer all-poses side-by-side view as default. Clean up viewer crash fixes (mouse/resize handlers).
**Depends on:** Phase 94 (pipeline must be stable before removing death)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 96: Batch Generation

**Goal:** Run the validated pipeline for all 17 units. Per-unit defend descriptions with correct equipment. Manual review pass via viewer. Fix outliers with --redo. Generate portraits for all units.
**Depends on:** Phase 95 (death removal + viewer must be done for review)

**Plans:**
- TBD (defined during /paul:plan)

---

**v3.3 Exit Buttons**
Status: ✅ Complete
Phases: 1 of 1 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 93 | Exit Buttons | 1/1 | ✅ Complete | 2026-03-08 |

## Previous v3.3 Phase Details

### Phase 93: Exit Buttons

**Goal:** Clean exit paths — exit button on game board sidebar (with save prompt) and exit button on main menu screen (quit app). Plus 26 code review fixes from three-agent architectural review.
**Depends on:** None

---

## Previous Milestone

**v3.2 Campaign Management**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 90 | Save Management UI | 1/1 | ✅ Complete | 2026-03-08 |
| 91 | Save Naming | 1/1 | ✅ Complete | 2026-03-08 |
| 92 | Veteran Deployment | 1/1 | ✅ Complete | 2026-03-08 |

## Previous v3.2 Phase Details

### Phase 90: Save Management UI

**Goal:** Screen listing all saves reverse-chronological, displaying metadata (campaign name, scenario, turn, date). Player picks one to load or delete. Accessible from main menu.
**Depends on:** None

### Phase 91: Save Naming

**Goal:** Add `display_name` field to save TOML. UI prompt for adding/editing display labels. Show label in save list, defaulting to auto-generated info (campaign + scenario + turn).
**Depends on:** Phase 90 (save list UI must exist first)

### Phase 92: Veteran Deployment

**Goal:** When campaign veterans exceed available keep+castle slots, bench/deploy selection UI before scenario starts. Player chooses which veterans to field. Visual roster with deploy toggles.
**Depends on:** None (can parallel with 90-91, but logically last)

---

## Previous Milestone

**v3.1 Main.lua Modularization**
Status: Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 87 | Extract State | 1/1 | ✅ Complete | 2026-03-07 |
| 88 | Extract Camera | 1/1 | ✅ Complete | 2026-03-07 |
| 89 | Extract Combat | 1/1 | ✅ Complete | 2026-03-07 |

---

## Previous Milestone

**v3.0 Upvalue Reduction & UX Polish**
Status: Complete
Phases: 2 of 2 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 85 | Upvalue Reduction | 1/1 | ✅ Complete | 2026-03-07 |
| 86 | UX Fixes | 1/1 | ✅ Complete | 2026-03-07 |

## v3.0 Phase Details

### Phase 85: Upvalue Reduction

**Goal:** Bundle mode constants into MODES table, helper functions into helpers table, and module references into mods table. Reduce love.load upvalues from 55 to ~28, giving permanent headroom for future features.
**Depends on:** None

### Phase 86: UX Fixes

**Goal:** Fix 4 small UX issues: recruit castle highlight (only adjacent), combat preview ToD modifier label, 'A' key advancement UI hint, setup placement prompt zoom position.
**Depends on:** Phase 85 (input.lua references change)

---

## Previous Milestone

**v2.9 Audit Fixes**
Status: Complete
Phases: 2 of 2 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 83 | Bug Fixes & Dead Code | 1/1 | ✅ Complete | 2026-03-07 |
| 84 | Draw Cleanup | 1/1 | ✅ Complete | 2026-03-07 |

## v2.9 Phase Details

### Phase 83: Bug Fixes & Dead Code

**Goal:** Fix fonts.medium bug (nil key), status message UI_SCALE transform, remove dead code (shared.handle_sidebar_button, unused input.lua locals, redundant sidebar check), clean stale comments.
**Depends on:** None

### Phase 84: Draw Cleanup

**Goal:** Use C_GOLD constant for inline gold color tuples, deduplicate ghost unit fallback rendering (~25 lines), simplify play_sfx indirection to direct sound.play, expand faction_color() usage.
**Depends on:** Phase 83

---

## Previous Milestone

**v2.8 Code Cleanup & Architecture**
Status: Complete
Phases: 5 of 5 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 78 | Upvalue Contexts | 1/1 | ✅ Complete | 2026-03-07 |
| 79 | Input Handlers | 1/1 | ✅ Complete | 2026-03-07 |
| 80 | Draw Constants | 1/1 | ✅ Complete | 2026-03-07 |
| 81 | FFI Hardening | 1/1 | ✅ Complete | 2026-03-07 |
| 82 | Shared Table Split | 1/1 | ✅ Complete | 2026-03-07 |

## v2.8 Phase Details

### Phase 78: Upvalue Contexts

**Goal:** Group main.lua's 62 local variables into context tables by concern (camera_ctx, ghost_ctx, campaign_ctx, dialogue_ctx, scenario_ctx, selection_ctx). Reduces upvalue pressure from 62 to ~20, eliminating the recurring LuaJIT 60-upvalue limit problem.
**Depends on:** None

### Phase 79: Input Handlers

**Goal:** Extract love.keypressed (403 lines) and love.mousepressed (286 lines) into handler modules. Create handlers for global hotkeys, mode selection, gameplay actions, combat, and recruitment. main.lua becomes a dispatcher.
**Depends on:** Phase 78 (context tables are what handlers receive)

### Phase 80: Draw Constants

**Goal:** Consolidate draw.lua magic numbers and duplication. Extract sidebar width (200), colors (73 hardcoded RGB tuples), font size constants, and repeated patterns (faction color selection x8, sidebar background x6, unit rendering duplication). Cache tile colors at load time instead of per-frame.
**Depends on:** None

### Phase 81: FFI Hardening

**Goal:** Replace 6 unsafe unwrap() calls in ffi.rs with proper error returns (lines 295, 414, 419, 472, 476, 744). Add bounds checking on array index parameters. Unify manual JSON construction with consistent quote escaping.
**Depends on:** None

### Phase 82: Shared Table Split

**Goal:** Split the shared table (8+ unrelated concerns) into focused modules: ui_state (help, buttons, recruit_palette), ai_controller (ai_vs_ai, ai_delay, ai_timer), and keep agent/sound as direct requires. Clean module boundaries instead of a catch-all table.
**Depends on:** Phase 78 (upvalue contexts reduce what shared needs to hold), Phase 79 (handlers define what state they need)

---

## Previous Milestone

**v2.7 Controls & Help**
Status: Complete
Phases: 2 of 2 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 76 | Help Overlay | 1/1 | Complete | 2026-03-07 |
| 77 | Mouse Actions | 1/1 | Complete | 2026-03-07 |

## Previous Milestone

**v2.6 Music**
Status: Complete
Phases: 1 of 1 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 75 | Background Music | 1/1 | Complete | 2026-03-07 |

## v2.6 Phase Details

### Phase 75: Background Music

**Goal:** Add menu music (battle_background.ogg loops on scenario select screen), per-scenario music transitions (stop menu music when scenario starts, resume when returning to menu).
**Depends on:** Phase 72 (sound.lua play_music/stop_music infrastructure)

**Plans:**
- 75-01: Menu music + transitions (complete)

---

## Previous Milestone

**v2.5 Animation Fixes**
Status: Complete
Phases: 1 of 1 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 74 | Idle & Death Animation Fixes | 1/1 | Complete | 2026-03-07 |

## v2.5 Phase Details

### Phase 74: Idle & Death Animation Fixes

**Goal:** Fix idle animation frame cycling (sprite key normalization) and death animation visibility (keep dead units rendered during death animation before cleanup).
**Depends on:** None

**Plans:**
- TBD (defined during /paul:plan)

---

## Previous Milestone

**v2.4 Content Organization**
Status: Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 70 | Unit Content Merge | 1/1 | Complete | 2026-03-07 |
| 71 | Scenario Directories | 1/1 | Complete | 2026-03-07 |
| 72 | Sound Assets | 1/1 | Complete | 2026-03-07 |
| 73 | Contributor Guides | 1/1 | Complete | 2026-03-07 |

## v2.4 Phase Details

### Phase 70: Unit Content Merge

**Goal:** Move sprite assets from `norrust_love/assets/units/` into `data/units/<name>/` alongside each unit's TOML. Update `assets.lua` loader to read from the new location. A unit becomes fully self-contained in one directory.
**Depends on:** None

**Plans:**
- TBD (defined during /paul:plan)

### Phase 71: Scenario Directories

**Goal:** Convert flat `scenarios/*.toml` files into per-scenario directories (`scenarios/<name>/board.toml`, `units.toml`, `dialogue.toml`). Update Rust loaders, Lua references, and campaign TOML paths.
**Depends on:** Phase 70 (content layout pattern established)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 72: Sound Assets

**Goal:** Create `data/sounds/` for global SFX files. Update `sound.lua` to load audio files with procedural fallback when files are missing. Support per-scenario music path in scenario directories.
**Depends on:** Phase 71 (scenario directories established for per-scenario music)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 73: Contributor Guides

**Goal:** Write CONTRIBUTING.md with how-to guides for non-programmers: add a unit, create a scenario, define a faction, add sounds. Reference the new content layout.
**Depends on:** Phase 72 (all content reorganization complete)

**Plans:**
- TBD (defined during /paul:plan)

---

## Previous Milestone

**v2.3 Combat Depth & Campaign**
Status: Complete
Phases: 5 of 5 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 65 | Weapon Specials | 1/1 | Complete | 2026-03-07 |
| 66 | Unit Abilities | 1/1 | Complete | 2026-03-07 |
| 67 | Sound & Music | 1/1 | Complete | 2026-03-07 |
| 68 | Scenario 3: Night Orcs | 1/1 | Complete | 2026-03-07 |
| 69 | Scenario 4: Final Battle | 1/1 | Complete | 2026-03-07 |

## v2.3 Phase Details

### Phase 65: Weapon Specials

**Goal:** Implement 6 weapon specials in Rust combat system: drain, poison, charge, backstab, slow, first strike. Add status effect tracking (poisoned, slowed) on Unit with per-turn resolution and village curing.
**Depends on:** Phase 64 (v2.2 complete)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 66: Unit Abilities

**Goal:** Implement 3 unit abilities in Rust: leadership (+25% damage to adjacent lower-level allies), regenerates (self-heal per turn), steadfast (double resistances on defense). Add UI indicators for status effects and active abilities.
**Depends on:** Phase 65 (status effect system from weapon specials)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 67: Sound & Music

**Goal:** Add sound effects (combat hit/miss/death, movement, recruitment, turn end) and optional background music per scenario via love.audio. Volume/mute control.
**Depends on:** Phase 66 (all mechanics complete before audio)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 68: Scenario 3: Night Orcs

**Goal:** Large night board (20x12+) vs orc faction. Showcases ToD alignment advantage, poison, leadership. Dialogue about orc night advantage. Extends tutorial campaign as 3rd scenario.
**Depends on:** Phase 67 (sound available for new scenarios)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 69: Scenario 4: Final Battle

**Goal:** Largest board yet — campaign finale using full mechanic set. Extends tutorial campaign to 4 scenarios total (crossing → ambush → night orcs → final battle).
**Depends on:** Phase 68 (scenario 3 complete)

**Plans:**
- TBD (defined during /paul:plan)

---

## Previous Milestone

**v2.2 AI & Agents**
Status: Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 62 | Campaign UX Polish | 1/1 | Complete | 2026-03-06 |
| 63 | TCP Agent Server | 1/1 | Complete | 2026-03-06 |
| 64 | AI vs AI Mode | 1/1 | Complete | 2026-03-06 |

## v2.2 Phase Details

### Phase 62: Campaign UX Polish

**Goal:** Veteran recruitment in the recruit panel (living roster entries as recruitable options) and fix enemy faction picker (always selects Loyalists regardless of user choice).
**Depends on:** Phase 61 (roster system working)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 63: TCP Agent Server

**Goal:** Socket/TCP server exposing the existing JSON action API (ActionRequest/StateSnapshot) to external Python agents. Python client library for programmatic play.
**Depends on:** Phase 62 (campaign UX solid)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 64: AI vs AI Mode

**Goal:** Automated games where both factions are AI-controlled. Works both headless (Rust-only) and visual (Love2D with accelerated turns). Enables Claude to test gameplay directly.
**Depends on:** Phase 63 (TCP server working)

**Plans:**
- TBD (defined during /paul:plan)

---

## Previous Milestone

**v2.1 Save System**
Status: Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 58 | Save/Load Basics | 1/1 | Complete | 2026-03-06 |
| 59 | Save/Load Combat State | 0 (folded into 58-01) | Complete | 2026-03-06 |
| 60 | Campaign Save/Load | 1/1 | Complete | 2026-03-06 |
| 61 | UUID + Roster | 1/1 | Complete | 2026-03-06 |

---

## Previous Milestone

**v2.0 Dialogue System**
Status: Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 54 | Dialogue Data & Engine | 1 | Complete | 2026-03-05 |
| 55 | Dialogue Display | 1 | Complete | 2026-03-05 |
| 56 | Dialogue History | 1 | Complete | 2026-03-05 |
| 57 | Gameplay Triggers | 1 | Complete | 2026-03-05 |

---

## Previous Milestone

**v1.9 UI Polish**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 51 | Fullscreen & Faction Order | 1 | ✅ Complete | 2026-03-05 |
| 52 | Board Zoom | 1 | ✅ Complete | 2026-03-05 |
| 53 | Viewport Clipping | 1 | ✅ Complete | 2026-03-05 |

---

## Previous Milestone

**v1.8 Movement & Animation Polish**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 48 | Ghost Path Visualization | 1 | ✅ Complete | 2026-03-05 |
| 49 | Movement Interpolation | 1 | ✅ Complete | 2026-03-05 |
| 50 | Combat Movement | 1 | ✅ Complete | 2026-03-05 |

---

## Previous Milestone

**v1.7 Enhanced Unit Sprites**
Status: ✅ Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 44 | Mage Pipeline | 1 | ✅ Complete | 2026-03-05 |
| 45 | Pipeline Refinement | 1 | ✅ Complete | 2026-03-05 |
| 46 | Full Unit Generation | 1 | ✅ Complete | 2026-03-05 |
| 47 | Polish & Verification | 1 | ✅ Complete | 2026-03-05 |

## v1.7 Phase Details

### Phase 44: Mage Pipeline

**Goal:** Build initial AI sprite generation tooling using Gemini Imagen. Craft prompts, handle background removal, assemble spritesheets. Generate all 6 Mage sprite files as prototype. Human verify.
**Depends on:** Phase 43 (v1.6 complete, documented codebase)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 45: Pipeline Refinement

**Goal:** Fix issues from Phase 44: prompt tuning, style consistency across animation states, post-processing improvements. Re-generate Mage if needed. Human verify.
**Depends on:** Phase 44 (initial pipeline working)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 46: Full Unit Generation

**Goal:** Run the proven pipeline for all 16 units (or remaining 15). Batch generation and integration of all sprite files.
**Depends on:** Phase 45 (pipeline refined and verified)

**Plans:**
- TBD (defined during /paul:plan)

### Phase 47: Polish & Verification

**Goal:** Visual review all units in-game, fix outliers, verify all animations and portraits render correctly in game and viewer.
**Depends on:** Phase 46 (all units generated)

**Plans:**
- TBD (defined during /paul:plan)

---

## Previous Milestone

**v1.6 Codebase Cleanup**
Status: ✅ Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 40 | Asset Directory Naming | 1/1 | ✅ Complete | 2026-03-04 |
| 41 | Split main.lua | 1/1 | ✅ Complete | 2026-03-04 |
| 42 | Rust Documentation | 1/1 | ✅ Complete | 2026-03-04 |
| 43 | Lua Documentation | 1/1 | ✅ Complete | 2026-03-04 |

## v1.6 Phase Details

### Phase 40: Asset Directory Naming ✅

**Goal:** Rename 16 unit asset directories from PascalCase (some with spaces) to snake_case. Update all Lua path construction with normalize function. Fix MISSSION_CONTROL.md typo.
**Depends on:** Phase 39 (v1.5 complete, stable codebase)
**Completed:** 2026-03-04

**Plans:**
- [x] 40-01: Directory renames + normalize_unit_dir() + sprite.toml updates + human verification

**Delivered:**
- 16 unit asset directories renamed to snake_case via git mv
- `normalize_unit_dir()` in assets.lua: def_id:lower():gsub(" ", "_") for lookup
- `normalize_dir()` in generate_sprites.lua for output paths
- sprite.toml id fields updated to match directory names
- MISSSION_CONTROL.md → MISSION_CONTROL.md typo fix
- 97 tests passing (no Rust changes)

### Phase 41: Split main.lua ✅

**Goal:** Extract main.lua (~1,728 lines) into focused modules. Separate rendering, UI panels, input handling, hex math, and game state machine into individual Lua files. main.lua becomes a thin Love2D callback dispatcher. Refactor only — identical behavior.
**Depends on:** Phase 40 (naming cleanup done before restructuring)
**Completed:** 2026-03-04

**Plans:**
- [x] 41-01: Extract hex.lua, draw.lua, campaign_client.lua with ctx table pattern

**Delivered:**
- hex.lua (64 lines): pure hex math — to_pixel, from_pixel, polygon, neighbors + constants
- draw.lua (732 lines): all rendering — 6 panel functions + draw_frame dispatch
- campaign_client.lua (141 lines): scenario/campaign loading with mutable ctx writeback
- main.lua reduced from 1,728 to 911 lines (47% reduction)
- ctx table pattern for cross-module state sharing
- 97 tests passing (no Rust changes)

### Phase 42: Rust Documentation ✅

**Goal:** Add doc comments (///) to all ~27 undocumented public items across 10 Rust files. Priority: ffi.rs (C API boundary), game_state.rs, board.rs, snapshot.rs, combat.rs. Follow existing style in hex.rs/pathfinding.rs/ai.rs.
**Depends on:** Phase 41 (code structure stable before documenting)
**Completed:** 2026-03-04

**Plans:**
- [x] 42-01: Module-level docs on all 15 files + /// docs on all ~27 undocumented public items

**Delivered:**
- //! module-level docs on all 15 .rs files
- /// doc comments on all public items (structs, traits, methods)
- 97 tests passing (documentation only, no logic changes)

### Phase 43: Lua Documentation ✅

**Goal:** Add function-level documentation (@param, @return, purpose) to all Lua files. Now smaller and cleaner after Phase 41 split. Follow existing style in assets.lua/animation.lua/toml_parser.lua.
**Depends on:** Phase 42 (Rust docs done; Lua modules in final form after Phase 41)
**Completed:** 2026-03-04

**Plans:**
- [x] 43-01: Doc comments on ~120 functions across 6 Lua files

**Delivered:**
- --- doc comments on all functions in main.lua, conf.lua, norrust.lua, viewer.lua, generate_tiles.lua, generate_sprites.lua
- draw.lua already documented from Phase 41 extraction
- Multi-line @param docs for complex functions (draw_humanoid, generate_spritesheet, draw_portrait_generic)
- 97 tests passing (documentation only, no logic changes)

---

## Previous Milestone

**v1.5 Tactical Planning**
Status: ✅ Complete
Phases: 4 of 4 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 36 | Terrain Info Panel | 1/1 | ✅ Complete | 2026-03-04 |
| 37 | Ghost Movement | 1/1 | ✅ Complete | 2026-03-04 |
| 38 | Combat Preview | 1/1 | ✅ Complete | 2026-03-04 |
| 39 | Commit/Cancel Flow | 1/1 | ✅ Complete | 2026-03-04 |

## v1.5 Phase Details

### Phase 36: Terrain Info Panel ✅

**Goal:** Click any hex to see terrain type, defense %, and movement cost in a sidebar panel. When a unit is selected, show that unit's specific terrain interaction (e.g., "Swordsman on Forest: 50% defense, 2 MP cost"). Foundation for all tactical decision-making.
**Depends on:** Phase 35 (v1.4 complete, stable Love2D client with sidebar panels)
**Completed:** 2026-03-04

**Plans:**
- [x] 36-01: TileSnapshot extension + unit-terrain FFI + right-click terrain panel

**Delivered:**
- TileSnapshot extended with defense/movement_cost/healing fields
- `norrust_get_unit_terrain_info()` FFI function with unit.defense[terrain] → tile.defense fallback
- Right-click terrain inspection panel in sidebar (base stats + unit-specific effective stats)
- 96 tests passing (61 lib + 8 campaign + 3 validation + 23 simulation + 1 FFI)

### Phase 37: Ghost Movement ✅

**Goal:** Replace immediate move-on-click with tentative "ghost" positioning. When a unit is selected and the player clicks a reachable hex, the unit appears translucently at the new position without committing the move. From the ghost position, attackable enemies are highlighted. Click a different reachable hex to re-ghost. Escape cancels and returns to selection.
**Depends on:** Phase 36 (terrain panel shows info for ghost position)
**Completed:** 2026-03-04

**Plans:**
- [x] 37-01: Ghost state machine + translucent rendering + commit/cancel flow

**Delivered:**
- Ghost state machine: Select → Ghost → (Attack/Re-ghost/Cancel/Commit)
- Translucent unit at ghost position with dim outline at original
- Adjacent enemy highlighting (red/orange borders) from ghost position
- Escape cancels, Enter commits, click enemy = move+attack
- Purely client-side — no Rust changes, 96 tests passing

### Phase 38: Combat Preview ✅

**Goal:** From a ghost position, clicking a highlighted enemy runs a Monte Carlo simulation (~100 attacks) and displays the outcome distribution: expected damage dealt/received, kill probability for both sides, damage spread (min/median/max). Preview reflects defender terrain defense, resistance modifiers, time of day, and whether retaliation occurs (range matching). New Rust FFI function needed to simulate attacks without mutating game state.
**Depends on:** Phase 37 (ghost position determines attack range and attacker terrain)
**Completed:** 2026-03-04

**Plans:**
- [x] 38-01: simulate_combat() + FFI + combat preview panel + click handler changes

**Delivered:**
- CombatPreview struct + simulate_combat() pure Rust function (100 Monte Carlo trials, independent RNG per trial)
- norrust_simulate_combat() FFI: range-aware (distance → melee/ranged), terrain defense fallback, JSON return
- Combat preview panel: attack name, damage×strikes, hit %, damage range (min-mean-max), kill % with color coding
- Preview for both ghost attacks and direct adjacent attacks; double-click or Enter to confirm
- 97 tests passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

### Phase 39: Commit/Cancel Flow ✅

**Goal:** Wire up the full planning loop: confirm = execute move (+ optional attack), cancel = unit returns to original hex. Player can ghost to multiple hexes adjacent to a target and compare combat previews ("attack from" comparison). Different hexes mean different terrain defense for the attacker during retaliation. Complete state machine: Select → Ghost → See Targets → Preview Combat → Commit/Cancel or Re-ghost.
**Depends on:** Phase 38 (combat preview must exist to make commit meaningful)
**Constraints:** Replaces current immediate-move behavior entirely. Must handle edge cases: ghost to hex with no enemies adjacent, ghost then cancel, commit move without attack, commit move + attack.
**Completed:** 2026-03-04

**Plans:**
- [x] 39-01: Terrain defense in CombatPreview + auto-preview on re-ghost + human verification

**Delivered:**
- `attacker_terrain_defense` and `defender_terrain_defense` fields on CombatPreview struct and FFI JSON
- Combat preview panel shows terrain defense % for both attacker and defender positions
- Auto-preview on re-ghost: moving to hex adjacent to same enemy auto-updates combat preview
- "Attack from" comparison: player ghosts to different hexes, sees how terrain changes affect combat
- 97 tests passing (62 unit + 8 campaign + 3 validation + 23 simulation + 1 FFI)

---

## Previous Milestone

**v1.4 Visual Asset System**
Status: ✅ Complete
Phases: 5 of 5 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 31 | Asset Specification & Infrastructure | 1 | ✅ Complete | 2026-03-03 |
| 32 | Terrain Art | 1 | ✅ Complete | 2026-03-03 |
| 33 | Unit Sprite Pipeline | 1 | ✅ Complete | 2026-03-04 |
| 34 | Asset Viewer | 1 | ✅ Complete | 2026-03-04 |
| 35 | Unit Art Expansion | 1 | ✅ Complete | 2026-03-04 |

## v1.4 Phase Details (Complete)

### Phase 31: Asset Specification & Infrastructure ✅

**Goal:** Document the asset format specification (sprite.toml schema, directory layout, naming conventions). Create asset loader module in Love2D (`assets.lua`). Fallback rendering: sprite when available, colored circle when not. Terrain tile loading and hex rendering replacement.
**Depends on:** Phase 30 (campaign system complete, Love2D client stable)
**Constraints:** No Rust changes expected — sprites are purely client-side. First deliverable is a written spec document.
**Completed:** 2026-03-03

**Plans:**
- [x] 31-01: Asset spec document + assets.lua loader + main.lua wiring with fallback

**Delivered:**
- `docs/ASSET-SPEC.md`: 7-section spec (directory layout, terrain format, sprite.toml schema, team coloring, animation states, naming conventions, pipeline workflow)
- `norrust_love/assets.lua`: asset loader module (load_terrain_tiles, load_unit_sprites, draw_terrain_hex, draw_unit_sprite with fallback)
- `norrust_love/main.lua`: wired through assets.lua for terrain + unit rendering; zero visual regression without assets
- 94 tests passing (unchanged — no Rust changes)

### Phase 32: Terrain Art ✅

**Goal:** Generate hex terrain tiles for all 15 terrain types. Replace colored hex polygons with textured terrain images. Add hex stencil masking for proper clipping.
**Depends on:** Phase 31 (asset spec and loader must exist)
**Constraints:** 15 terrain types in game. Hex-shaped tiles via stencil clipping.
**Completed:** 2026-03-03

**Plans:**
- [x] 32-01: Hex stencil masking + 15 programmatic terrain tiles + human verification

**Delivered:**
- Hex stencil masking in `assets.lua`: stencil(polygon, replace, 1) → draw image → clear
- 15 terrain tile PNGs (512x512, ~6.3 MB total) with distinct patterns per terrain type
- `generate_tiles.lua`: programmatic tile generator with `--generate-tiles` CLI flag
- Colored polygons replaced by textured terrain in all scenarios

### Phase 33: Unit Sprite Pipeline

**Goal:** Pick one unit (Spearman) and build complete visual pipeline end-to-end. Generate idle, attack-melee, attack-ranged, defend, death sprites. Create sprite.toml metadata with animation definitions. Implement animation state machine (anim8 integration). Team coloring via colored underlay. Facing/flip logic. Portrait in unit panel sidebar.
**Depends on:** Phase 32 (terrain art proves the loading pipeline)
**Constraints:** One unit only — validate pipeline before mass production.

**Completed:** 2026-03-04

**Plans:**
- [x] 33-01: Spearman sprites + TOML parser + animation module + main.lua wiring + human verification

**Delivered:**
- Programmatic Spearman spritesheets (idle, attack-melee, attack-ranged, defend, death, portrait)
- `toml_parser.lua`: minimal TOML parser for sprite.toml metadata
- `animation.lua`: Quad-based spritesheet animation with per-unit state tracking
- Animation-aware `assets.lua` with portrait rendering
- Facing/flip based on board position; fallback preserved for all other units
- 94 tests passing (no Rust changes)

### Phase 34: Asset Viewer ✅

**Goal:** Standalone Love2D app to browse and preview unit/terrain assets. Cycle through animation states, zoom, flip. Validate sprite.toml metadata visually. Test terrain tiles in hex grid context.
**Depends on:** Phase 33 (unit sprite pipeline must exist to preview)
**Constraints:** Standalone app, separate from main game.
**Completed:** 2026-03-04

**Plans:**
- [x] 34-01: Standalone viewer.lua + --viewer CLI flag + human verification

**Delivered:**
- `viewer.lua`: 443-line standalone asset viewer (sidebar, preview, animation, zoom/flip, metadata)
- `--viewer` CLI flag in main.lua overriding love callbacks
- Terrain preview with hex-clipped stencil version
- Unit animation cycling through all states with spritesheet strip and portrait
- 94 tests passing (no Rust changes)

### Phase 35: Unit Art Expansion ✅

**Goal:** Generate sprites for remaining priority units (faction leaders, common recruits). Batch generation workflow using Nano Banana. Validate via asset viewer.
**Depends on:** Phase 34 (asset viewer for validation)
**Constraints:** Priority units first, not all 322.
**Completed:** 2026-03-04

**Plans:**
- [x] 35-01: Generic humanoid drawing system + 16 unit sprites + human verification

**Delivered:**
- Generic `draw_humanoid()` with configurable colors, body_scale, weapon callbacks
- 8 weapon draw functions (spear, sword, greatsword, bow, staff, mace, dagger, crossbow)
- 16 units with full animation sets (92 PNGs + 16 sprite.toml files)
- Loyalists (7), Elves (5), Orcs (4) — all leaders and recruits covered
- 94 tests passing (no Rust changes)

---

**v1.3 Campaign Mode**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 28 | Map Crossing | 1 | ✅ Complete | 2026-03-03 |
| 29 | Second Scenario | 1 | ✅ Complete | 2026-03-03 |
| 30 | Campaign Chain | 1 | ✅ Complete | 2026-03-03 |

## v1.3 Phase Details

### Phase 28: Map Crossing ✅

**Goal:** Create a large board scenario (e.g. 16x12) with a "reach enemy keep" win condition. Player starts at one keep, must cross the map to reach the enemy keep on the opposite side. Enemy AI starts with gold, recruits defenders, and plays aggressively. Turn limit enforces forward pressure.
**Depends on:** Phase 27 (Love2D client stable)
**Constraints:** Reuse existing AI + recruitment. New win condition type alongside existing "eliminate all". Each scenario standalone playable.
**Completed:** 2026-03-03

**Plans:**
- [x] 28-01: Objective hex + turn limit win conditions, LoadedBoard, crossing scenario, scenario selection

**Delivered:**
- `check_winner()` method on GameState: 3-tier priority (objective hex → turn limit → elimination)
- `LoadedBoard` struct: `load_board()` returns board + objective_hex + max_turns from TOML
- `norrust_set_objective_hex()` + `norrust_set_max_turns()` FFI functions
- `scenarios/crossing.toml`: 16×10 board with keeps, castles, mixed terrain, objective + 30-turn limit
- `scenarios/crossing_units.toml`: Blue leader vs red leader + 3 defenders (preset)
- Love2D: scenario selection screen, dynamic board dimensions, objective hex highlight, "Turn X / Y" HUD
- `preset_units` flag for scenarios with TOML-defined units (skip manual setup)
- 3 new integration tests; 76 tests passing (56 lib + 19 integration + 1 FFI)

### Phase 29: Second Scenario ✅

**Goal:** Create a second standalone board with different layout and terrain. Possibly introduce trigger zones where enemies spawn when player units enter an area. Must be independently playable as a single scenario.
**Depends on:** Phase 28 (map crossing win condition must work)
**Constraints:** New board design, different feel from Phase 28. Standalone — no carry-over dependency.
**Completed:** 2026-03-03

**Plans:**
- [x] 29-01: TriggerZone system + ambush scenario + headless validation

**Delivered:**
- `TriggerZone` system: `TriggerDef`/`TriggerSpawnDef` schema, `PendingSpawn`/`TriggerZone` runtime, fire-on-Move with two-phase drain
- `load_triggers()` function + trigger loading wired into `norrust_load_units()` FFI
- `norrust_get_next_unit_id()` FFI function for ID conflict avoidance
- `scenarios/ambush.toml`: 12×8 forest-heavy board with keeps, castles, objective (10,4), 25-turn limit
- `scenarios/ambush_units.toml`: 6 units + 3 trigger zones spawning 5 hidden enemies
- Love2D: ambush in scenario selection, get_next_unit_id wiring
- Headless scenario validation: auto-discovery, 10 invariants, false-winner detection, FFI tests
- Crossing scenario bugfixes: Blue castle ring + Red keep position
- 83 tests passing (56 lib + 23 integration + 3 scenario_validation + 1 FFI)

### Phase 30: Campaign Chain ✅

**Goal:** Link scenarios into a campaign sequence. Campaign defined in TOML (scenario list, starting conditions). Units that survive scenario 1 carry to scenario 2 with XP/level/advancement. Gold carries over with percentage penalty (e.g. 80%). Early finish bonus gold.
**Depends on:** Phase 29 (both scenarios must exist to chain)
**Constraints:** Campaign TOML file consistent with existing data-driven approach. Both individual scenarios and campaign mode must work.
**Completed:** 2026-03-03

**Plans:**
- [x] 30-01: Campaign schema + carry-over logic + FFI + Love2D flow

**Delivered:**
- `campaigns/tutorial.toml`: campaign definition (crossing → ambush, 80% gold carry, 5g/turn early bonus)
- `campaign.rs`: CampaignDef, VeteranUnit, load_campaign(), get_survivors(), calculate_carry_gold()
- 5 new FFI functions: norrust_load_campaign, norrust_get_survivors_json, norrust_get_carry_gold, norrust_place_veteran_unit, norrust_set_faction_gold
- Love2D campaign flow: C key selection, load_campaign_scenario(), victory/defeat overlays, veteran placement on keep+castles
- 8 campaign integration tests (3 pure Rust + 5 FFI); 94 total tests passing

---

**v1.2 Love2D Migration**
Status: ✅ Complete
Phases: 3 of 3 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 25 | C ABI Bridge | 1 | ✅ Complete | 2026-03-03 |
| 26 | Love2D Client | 1 | ✅ Complete | 2026-03-03 |
| 27 | Redot Cleanup | 1 | ✅ Complete | 2026-03-03 |

## v1.2 Phase Details

### Phase 25: C ABI Bridge ✅

**Goal:** Replace GDExtension bridge with `#[no_mangle] pub extern "C"` functions callable via LuaJIT FFI. Expose all existing bridge methods (load_data, load_board, load_units, load_factions, get_state_json, apply_action_json, apply_move, apply_attack, end_turn, ai_take_turn, recruit, advance, etc.) through C ABI. Existing Rust tests continue passing — the core is unchanged; only the bridge layer changes.
**Depends on:** Phase 24 (stable game with all features)
**Constraints:** Core logic untouched; only bridge/FFI layer added. GDExtension bridge preserved until Phase 27.
**Completed:** 2026-03-03

**Plans:**
- [x] 25-01: NorRustEngine opaque struct + 36 extern "C" functions + integration test

**Delivered:**
- `ffi.rs`: 36 `extern "C"` functions (4 lifecycle + 32 bridge) with `norrust_` prefix
- `NorRustEngine` opaque pointer with caller-frees memory management (strings + int arrays)
- `test_ffi_full_game_cycle`: comprehensive integration test covering create → load → query → move → end_turn → cleanup
- Zero changes to existing modules; both GDExtension and C ABI bridges coexist
- 73 tests passing (56 lib + 16 integration + 1 new FFI test)

### Phase 26: Love2D Client ✅

**Goal:** Port `norrust_client/scripts/game.gd` to Love2D `main.lua`. Full feature parity: hex rendering, unit circles with labels, camera panning (drag + arrow keys), HUD, sidebar unit panel, recruit panel, setup mode (faction pick + leader placement), AI opponent, win detection. Uses LuaJIT FFI to call C ABI bridge from Phase 25.
**Depends on:** Phase 25 (C ABI bridge must exist for Love2D to call Rust)
**Constraints:** Pure Lua + Love2D; no external Lua dependencies beyond Love2D stdlib.
**Completed:** 2026-03-03

**Plans:**
- [x] 26-01: LuaJIT FFI bindings (norrust.lua) + complete game client (main.lua) + conf.lua

**Delivered:**
- `norrust_love/norrust.lua`: LuaJIT FFI bindings wrapping all 36 C ABI functions with Lua-native types + inline JSON decoder (~90 lines)
- `norrust_love/main.lua`: Complete game client (831 lines) — hex rendering, input, HUD, sidebar panel, recruitment, camera, AI opponent, setup mode, win detection
- `norrust_love/conf.lua`: Love2D window configuration (1280×720, resizable)
- Pure hex math (hex_to_pixel, pixel_to_hex) replacing Godot TileMap; push/pop camera transform; reachable_set O(1) lookup
- 1202 total Lua lines across 3 files; all 8 acceptance criteria passed; 73 Rust tests passing

### Phase 27: Redot Cleanup ✅

**Goal:** Remove `norrust_client/` directory (Redot project), remove `gdext` dependency from Cargo.toml, update PROJECT.md tech stack to reflect Love2D, document the migration in ROADMAP.md history.
**Depends on:** Phase 26 (Love2D client at full parity before removing Redot)
**Constraints:** Only remove after Love2D client is verified working.
**Completed:** 2026-03-03

**Plans:**
- [x] 27-01: Delete gdext_node.rs + godot dependency + norrust_client/ + clean .gitignore

**Delivered:**
- `gdext_node.rs` deleted; `godot = "0.2"` dependency removed from Cargo.toml
- Entire `norrust_client/` directory removed (9 tracked files)
- `.gitignore` cleaned of Redot-specific entries
- Single integration path remains: C ABI (ffi.rs) → LuaJIT FFI → Love2D
- 73 Rust tests passing; Love2D client verified working post-cleanup

---

## Previous Milestone

**v1.1 Camera & Viewport**
Status: ✅ Complete
Phases: 1 of 1 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 24 | Scrollable Camera | 1 | ✅ Complete | 2026-03-03 |

## v1.1 Phase Details

### Phase 24: Scrollable Camera ✅

**Goal:** Make the board scrollable and hexes larger so the game is visually comfortable at any board size. Increase HEX_RADIUS from 64 to 96px, add drag-to-pan and arrow key panning, clamp camera to board bounds, and soft-pan camera to follow unit selection. HUD and sidebar panel remain screen-anchored.
**Depends on:** Phase 23 (in-hex readability complete; all rendering uses world coords via _tile_map)
**Constraints:** Pure GDScript/Redot changes — no Rust or bridge changes
**Completed:** 2026-03-03

**Plans:**
- [x] 24-01: HEX_RADIUS 64→96 + drag-to-pan + arrow key pan + board clamp + selection-follow

**Delivered:**
- HEX_RADIUS 96px; HEX_CELL_W=166, HEX_CELL_H=192; labels scaled 1.5× (name 14pt, HP 18pt, XP 14pt)
- Drag-to-pan on empty board space; arrow key continuous pan at 500px/sec
- Board-edge clamping with half-viewport + HEX_RADIUS margin
- Smooth camera lerp (factor 8.0) to center selected unit; keyboard pan cancels lerp
- _select_unit() helper; _apply_camera_offset() clamp helper; _process(delta) for continuous input
- Zero Rust changes; 72 tests passing (56 lib + 16 integration)

---

## Previous Milestone

**v1.0 Game Readability**
Status: ✅ Complete
Phases: 2 of 2 complete

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 22 | Selection Panel | 1 | ✅ Complete | 2026-03-02 |
| 23 | In-Hex Readability | 1 | ✅ Complete | 2026-03-02 |

## v1.0 Phase Details

### Phase 22: Selection Panel ✅

**Goal:** Clicking any unit (friendly or enemy) opens a stat panel showing full details from the existing JSON snapshot: unit name/type, level, HP (current/max), XP progress, movement budget remaining, all attacks (name, damage, strikes, range), terrain defense % at current position, and abilities list. Panel is read-only for enemy units. No new Rust bridges required — all data already in StateSnapshot JSON.
**Depends on:** Phase 21 (stable GameState + JSON snapshot with all unit fields)
**Completed:** 2026-03-02

**Plans:**
- [x] 22-01: UnitSnapshot JSON extension + _inspect_unit_id state + _draw_unit_panel() in game.gd

**Delivered:**
- `AttackSnapshot` struct + `UnitSnapshot.movement`, `.attacks`, `.abilities` — full loadout in StateSnapshot JSON
- `_inspect_unit_id` inspection state in game.gd independent of selection state
- `_draw_unit_panel()`: faction-colored header, HP, XP (conditional), movement+exhaustion, per-attack breakdown, abilities list
- Click-any-unit (friendly or enemy) shows panel; empty hex clears; recruit mode takes priority
- 72 tests passing (1 new: test_unit_snapshot_includes_movement_attacks_abilities)

### Phase 23: In-Hex Readability ✅

**Goal:** Show the unit's type name (or meaningful abbreviation) inside each hex at all times so units are identifiable without clicking.
**Depends on:** Phase 22 (selection panel complete; UnitSnapshot with def_id already in JSON)
**Completed:** 2026-03-02

**Plans:**
- [x] 23-01: In-hex name abbreviation in _draw_units()

**Delivered:**
- `_draw_units()`: `def_id.split("_")[0].capitalize().left(7)` drawn centered at 9px font above HP text
- "Fighter", "Elvish", "Orcish" etc. visible in every hex at all times — no click required
- HP/XP baseline shifted 2px down; HEX_RADIUS unchanged; zero Rust changes
- 72 tests passing (56 lib + 16 integration)

---

## v0.9 Phase Details

### Phase 20: Gold Economy ✅

**Goal:** Add per-faction gold tracking to GameState. On EndTurn, each faction earns 2 gold per village it owns (village_owners already tracked). Starting gold hardcoded at 10 per faction. StateSnapshot JSON exposes gold per faction. HUD displays current gold.
**Depends on:** Phase 19 (Tile system stable; village_owners already in GameState)
**Completed:** 2026-03-02

**Plans:**
- [x] 20-01: GameState.gold, EndTurn income, StateSnapshot + HUD

**Delivered:**
- `GameState.gold: [u32; 2]` — per-faction gold, starting [10, 10]
- EndTurn income: 2g × owned village count to newly-active faction
- `StateSnapshot.gold` in JSON — AI clients and GDScript both see it
- HUD: "Turn 1 · Day · Blue's Turn · 10g"
- 65 tests passing (55 lib + 10 integration)

### Phase 21: Factions + Recruitment

**Goal:** Define FactionDef TOML schema (id, name, starting_gold, recruitable_units[]). Load factions via Registry<FactionDef> + load_factions() bridge, replacing hardcoded starting gold. Add castle hexes to contested.toml. Implement Action::Recruit with can't-go-negative guard. Wire 'R' key in GDScript to recruit first affordable unit from faction list on selected castle hex.
**Depends on:** Phase 20 (gold tracking must exist before recruitment can spend it)

**Plans:**
- [x] 21-01: FactionDef.starting_gold + apply_starting_gold() bridge + game.gd wiring
- [x] 21-02: Action::Recruit + castle scenario + GDScript 'R' key + headless tests

**Delivered:**
- `FactionDef.starting_gold: u32` (default 100) — set into state.gold at game start via bridge
- `apply_recruit(state, unit, destination, cost)` — pure Rust, registry-free, headlessly testable
- `ActionError::NotEnoughGold` + `::DestinationNotCastle` (-8/-9 error codes)
- `recruit_unit_at()` + `get_unit_cost()` GDExtension bridges
- `ActionRequest::Recruit` — JSON API path for AI agent recruitment
- `scenarios/contested.toml` — col 0 + col 7 are castle (recruit zones); col 1 + 6 flat corridors
- GDScript 'R' key: recruit panel with teal castle highlights, unit list with costs, click-to-place
- 69 tests passing (55 lib + 14 integration)

---

## Previous Milestone

**v0.8 Combat Completeness** (v0.8.0)
Status: ✅ Complete
Phases: 1 of 1 complete
Released: 2026-03-02

## v0.8 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 19 | Tile Defense Combat Wiring | 1 | ✅ Complete | 2026-03-02 |

## v0.8 Phase Details

### Phase 19: Tile Defense Combat Wiring

**Goal:** Wire `Tile.defense` into combat resolution as the authoritative terrain defense value, replacing `Unit.default_defense`. The per-hex defense stat is already stored on `Tile` (populated from `TerrainDef` at `set_terrain_at()`) but is not yet consulted during attack calculations. This phase makes combat fully data-driven from TOML terrain definitions.
**Depends on:** Phase 18 (Tile system stable, terrain IDs reconciled)
**Completed:** 2026-03-02

**Plans:**
- [x] 19-01: Wire Tile.defense into combat fallback chain (attack + retaliation), test_tile_defense_used_in_combat

**Delivered:**
- Fallback chain `unit.defense[terrain_id] → tile.defense → unit.default_defense` in both attack and retaliation paths
- `test_tile_defense_used_in_combat`: Scenario A (tile blocks all hits at 100%) and Scenario B (unit entry wins at 0%) both verified
- 64 tests passing (54 lib + 10 integration)

---

## Previous Milestone

**v0.7 Scenario System** (v0.7.0)
Status: ✅ Complete
Phases: 2 of 2 complete
Released: 2026-03-01

## v0.7 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 17 | Board File Format | 1 | ✅ Complete | 2026-03-01 |
| 18 | Unit Placement + Wiring | 1 | ✅ Complete | 2026-03-01 |

## v0.7 Phase Details

### Phase 17: Board File Format

**Goal:** Define a TOML schema for board files (`width`, `height`, flat `tiles` array of terrain IDs). Add `load_board()` GDExtension bridge method that reads the file, looks up each terrain ID in the TerrainDef registry, and populates the board. Headless integration test verifying terrain loads correctly from file.
**Depends on:** Phase 16 (Tile struct and terrain color chain stable)
**Completed:** 2026-03-01

**Plans:**
- [x] 17-01: Board TOML schema, `load_board()` bridge, headless test

**Delivered:**
- `BoardDef` TOML struct: width, height, flat row-major tiles array
- `scenario::load_board(path)` pure Rust: reads TOML, validates tile count, populates Board
- `scenarios/contested.toml`: 8×5 board with flat spawn zones, forest/hills/mountains interior, 2 villages
- `load_board(path, seed)` GDExtension bridge: creates GameState, upgrades tiles from registry
- 55 tests passing (46 lib + 9 integration)

### Phase 18: Unit Placement + Wiring

**Goal:** Define a separate TOML schema for unit placement files (`[[units]]` array with `unit_type`, `faction`, `col`, `row`). Add `load_units()` bridge method. Wire both `load_board()` and `load_units()` into game.gd startup, replacing `generate_map()` and the hardcoded spawn block. Create first hand-authored scenario in `scenarios/`.
**Depends on:** Phase 17 (`load_board()` bridge stable)
**Completed:** -

**Plans:**
- [x] 18-01: Unit placement TOML schema, `load_units()` bridge, game.gd wiring, first scenario

**Delivered:**
- `UnitPlacement` + `UnitsDef` TOML structs: `[[units]]` array-of-tables with id, unit_type, faction, col, row
- `scenario::load_units(path)` pure Rust: reads TOML, returns `Vec<UnitPlacement>` (registry-free)
- `scenarios/contested_units.toml`: 10 fighters, 5 per faction, left/right spawn zones
- `load_units()` GDExtension bridge: iterates placements, calls `place_unit_at()` per entry
- `game.gd` startup: 14 hardcoded lines replaced by `load_board()` + `load_units()` — no hardcoded state
- 56 tests passing (46 lib + 10 integration)

---

## Previous Milestone

**v0.6 Terrain System** (v0.6.0)
Status: ✅ Complete
Phases: 3 of 3 complete
Released: 2026-03-01

## v0.6 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 14 | Tile Runtime + Terrain Wiring | 1 | ✅ Complete | 2026-03-01 |
| 15 | Map Generator | 1 | ✅ Complete | 2026-03-01 |
| 16 | Terrain Presentation | 1 | ✅ Complete | 2026-03-01 |

## v0.6 Phase Details

### Phase 14: Tile Runtime + Terrain Wiring ✅

**Goal:** Replace `HashMap<Hex, String>` with `HashMap<Hex, Tile>` on Board. `Tile` is a runtime struct instantiated from `TerrainDef` at `set_terrain_at()` — same pattern as `Unit`/`UnitDef`. Reconcile terrain IDs to Wesnoth vocabulary. Wire movement costs and defense into pathfinding and combat from `Tile` properties.
**Depends on:** Phase 13 (TerrainDef TOMLs for all Wesnoth terrain types exist)
**Completed:** 2026-03-01

**Plans:**
- [x] 14-01: Tile struct, Board refactor, terrain ID reconciliation, test_terrain_wiring

**Delivered:**
- `Tile` struct: terrain_id, movement_cost, defense, healing — instantiated from TerrainDef at placement
- `Board` stores `HashMap<Hex, Tile>`; `tile_at()` query; `terrain_at()` backward-compatible
- `healing_map` removed; EndTurn healing reads `tile.healing` directly
- `set_terrain_at()` bridge: `Tile::from_def()` when TerrainDef found, `Tile::new()` fallback
- Terrain IDs reconciled: "flat", "mountains", "shallow_water" in all custom unit TOMLs, tests, game.gd
- `test_terrain_wiring`: hills cost 2 MP, flat costs 1 MP — movement costs verified end-to-end
- 51 tests passing (44 lib + 7 integration)

### Phase 15: Map Generator ✅

**Goal:** Procedural map generation with geographically sensible terrain placement. Spawn zones flat, contested zone mixed flat/forest/hills/mountains, villages at structural positions. Board initialized from generator rather than hardcoded GDScript calls.
**Depends on:** Phase 14 (Tile system and terrain IDs in place)
**Completed:** 2026-03-01

**Plans:**
- [x] 15-01: mapgen.rs with generate_map(board, seed), GDExtension bridge, game.gd wiring

**Delivered:**
- `mapgen.rs`: `generate_map(board, seed)` with XOR noise hash; outer 2 cols = flat (spawn zones); villages at (cols/3, rows/2) and (cols*2/3, rows/2); contested zone = flat/forest/hills/mountains
- `generate_map(seed: i64) -> bool` GDExtension bridge — calls generator, upgrades tiles from registry
- `game.gd`: single `_core.generate_map(42)` replaces 7 lines of manual terrain setup
- `test_generate_map`: integration test verifying all ACs headlessly (no registry)
- 52 tests passing (44 lib + 8 integration)

### Phase 16: Terrain Presentation ✅

**Goal:** Per-tile color from TOML data through Tile/TileSnapshot to GDScript rendering. Replace hardcoded terrain-to-color switch with data-driven lookup.
**Depends on:** Phase 15 (map generator produces varied terrain to display)
**Completed:** 2026-03-01

**Plans:**
- [x] 16-01: TerrainDef.color + Tile.color + TileSnapshot.color + 14 terrain TOMLs + game.gd data-driven rendering

**Delivered:**
- `TerrainDef.color`, `Tile.color`, `TileSnapshot.color` — full data chain from TOML to JSON
- All 14 terrain TOMLs updated with distinct hex color values
- game.gd: `tile_colors` map from `state["terrain"]`; `COLOR_FOREST`/`COLOR_VILLAGE` constants removed
- Hills (#8b7355) and mountains (#6b6b6b) now render distinctly from flat (#4a7c4e)
- `test_tile_snapshot_includes_color`: new unit test verifying color in JSON output
- 53 tests passing (45 lib + 8 integration)

---

## Previous Milestone

**v0.5 Unit Content** (v0.5.0)
Status: ✅ Complete
Phases: 2 of 2 complete
Released: 2026-03-01

## v0.5 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 12 | UnitDef Schema Expansion | 1 | ✅ Complete | 2026-03-01 |
| 13 | Wesnoth Data Import | 1 | ✅ Complete | 2026-03-01 |

## v0.5 Phase Details

### Phase 12: UnitDef Schema Expansion ✅

**Goal:** Extend `UnitDef` and `AttackDef` Rust structs with new fields — `alignment`, `race`, `cost`,
`usage`, `abilities`, attack `specials` — all with `#[serde(default)]` so existing TOMLs load unchanged.
Move `alignment` from GDScript spawn-time parameter to registry-sourced data.
**Depends on:** Phase 11 (stable GDExtension bridge, place_unit_at() API)
**Completed:** 2026-03-01

**Plans:**
- [x] 12-01: UnitDef/AttackDef schema expansion + alignment wired from TOML to Unit at spawn/advance

**Delivered:**
- `UnitDef`: race, cost, usage, abilities, alignment — all `#[serde(default)]`
- `AttackDef`: specials — `#[serde(default)]`
- `parse_alignment()`: "lawful"→Lawful, "chaotic"→Chaotic, else→Liminal — pub fn in unit.rs
- alignment wired: place_unit_at() + advance_unit() both call parse_alignment()
- 4 unit TOMLs updated: fighter/hero="lawful", archer/ranger="neutral"
- 49 tests passing (44 lib + 5 integration)

### Phase 13: Wesnoth Data Import ✅

**Goal:** Python scraper reads Wesnoth WML from `/home/chris/git_home/wesnoth/data/core/units/`,
expands movement type macros, and outputs unit TOMLs + terrain TOMLs. All units load via
`Registry::<UnitDef>::load_from_dir()` verified by integration test.
**Depends on:** Phase 12 (expanded UnitDef schema must exist before TOMLs are generated)
**Completed:** 2026-03-01

**Plans:**
- [x] 13-01: Python WML scraper + terrain TOMLs + Rust integration test

**Delivered:**
- `tools/scrape_wesnoth.py`: 270-line stdlib-only WML → TOML scraper; 38 movetypes, 328 unit_type blocks parsed
- 318 Wesnoth unit TOMLs generated (322 total with 4 custom); all load via Registry<UnitDef>
- 11 terrain TOMLs (flat, hills, mountains, cave, frozen, fungus, sand, shallow_water, reef, swamp_water, castle)
- `test_wesnoth_units_load`: asserts registry.len() >= 200; Spearman spot-check (hp=36, mv=5, pierce)
- 50 tests passing (44 lib + 6 integration)

---

## Previous Milestone

**v0.4 AI Opponent** (v0.4.0)
Status: ✅ Complete
Phases: 2 of 2 complete
Released: 2026-02-28

## v0.4 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 10 | AI Core (ai.rs) | 1 | ✅ Complete | 2026-02-28 |
| 11 | AI Bridge & GDScript | 1 | ✅ Complete | 2026-02-28 |

## v0.4 Phase Details

### Phase 10: AI Core (ai.rs) ✅

**Goal:** Implement the analytic greedy AI in a pure-Rust `ai.rs` module — expected-damage
scorer, move+attack planner, and headless AI-vs-AI integration test.
**Depends on:** Phase 9 (stable GameState, apply_action, pathfinding, combat APIs)
**Completed:** 2026-02-28

**Plans:**
- [x] 10-01: expected_outgoing_damage(), score_attack(), ai_take_turn(), test_ai_vs_ai_terminates

**Delivered:**
- `expected_outgoing_damage()`: analytic expected-value scorer (hit_chance × effective_dmg × strikes × tod)
- `score_attack()`: pair scorer using terrain defense, time-of-day, resistances; kill bonus ×3
- `ai_take_turn(state, faction)`: greedy move+attack for all faction units; EndTurn; registry-free
- `test_ai_vs_ai_terminates`: 5v5 headless integration test — game terminates with a winner in ≤100 turns
- 48 tests passing (44 lib + 4 integration)

### Phase 11: AI Bridge & GDScript ✅

**Goal:** Connect the Phase 10 Rust AI to the Redot presentation layer: march fallback, GDExtension bridge method, and GDScript auto-trigger — making human vs AI opponent fully playable.
**Depends on:** Phase 10 (ai_take_turn() pure Rust API)
**Completed:** 2026-02-28

**Plans:**
- [x] 11-01: March fallback, ai_take_turn() bridge, GDScript KEY_E wiring, human-verify

**Delivered:**
- March fallback in `ai_take_turn()`: units advance toward nearest enemy when no attack is reachable
- `fn ai_take_turn(faction: i32)` GDExtension bridge: callable from GDScript with faction validation
- GDScript auto-AI: after player 'E', faction 1 AI plays automatically; win detection follows
- `test_ai_marches_toward_enemy_when_no_attack`: 8×1 board, col 0 → col 5 with movement=5
- 49 tests passing (44 lib + 5 integration)

---

## Previous Milestone

**v0.3 Unit Advancement** (v0.3.0)
Status: ✅ Complete
Phases: 3 of 3 complete
Released: 2026-02-28

## v0.3 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 7 | Advancement Schema | 1 | ✅ Complete | 2026-02-28 |
| 8 | XP & Advancement Logic | 2 | ✅ Complete | 2026-02-28 |
| 9 | Advancement Presentation | 1 | ✅ Complete | 2026-02-28 |

## v0.3 Phase Details

### Phase 7: Advancement Schema ✅

**Goal:** Extend data definitions and runtime structs to carry advancement information — TOML files
gain `experience`, `advances_to`, `level`; `Unit` gains `xp`, `xp_needed`, and `advancement_pending`;
`UnitSnapshot` JSON exposes all three for GDScript and AI clients.
**Depends on:** Phase 6 (StateSnapshot JSON as sole unit data source)
**Completed:** 2026-02-28

**Plans:**
- [x] 07-01: UnitDef schema, TOML data files, Unit runtime struct, UnitSnapshot JSON

**Delivered:**
- `UnitDef`: `level`, `experience`, `advances_to` — all `#[serde(default)]`
- `data/units/fighter.toml` + `archer.toml`: level 1, experience=40, advances_to set
- `data/units/hero.toml` + `ranger.toml`: new level-2 definitions with dual-attack loadouts
- `Unit`: `xp`, `xp_needed`, `advancement_pending` runtime fields; `xp_needed` set at spawn
- `UnitSnapshot` JSON: exposes all XP/advancement fields; 37 tests passing

### Phase 8: XP & Advancement Logic ✅

**Goal:** Implement XP gain in combat, the advancement action, and headless balance simulation tests.
**Depends on:** Phase 7 (advancement fields on Unit and UnitDef)
**Completed:** 2026-02-28

**Plans:**
- [x] 08-01: XP gain in Attack branch (1 XP/hit + 8 kill bonus, both attacker and defender)
- [x] 08-02: advance_unit() + apply_advance() bridge + ActionRequest::Advance JSON API + simulation test

**Delivered:**
- XP grant in `Action::Attack` — attacker and defender earn XP symmetrically; `advancement_pending` auto-sets
- `advance_unit()` pure Rust free function — usable without registry or bridge
- `apply_advance()` GDExtension bridge method — GDScript callable with error codes
- `ActionRequest::Advance` JSON variant — AI clients can advance units via JSON API
- Headless simulation: 5-kill XP accumulation → hero promotion verified end-to-end
- 43 tests passing (41 lib + 2 integration)

### Phase 9: Advancement Presentation ✅

**Goal:** Surface XP and advancement state in the Redot layer — XP progress in the HUD,
visual indicator when a unit is ready to advance, and click-to-advance interaction.
**Depends on:** Phase 8 (Advance action implemented and tested)
**Completed:** 2026-02-28

**Plans:**
- [x] 09-01: XP text, gold arc ring, 'A' key advancement handler, 5-unit spawn, float fix

**Delivered:**
- XP progress text ("xp/xp_needed") drawn per unit; int() cast guards Redot float JSON values
- Gold draw_arc() ring on units with advancement_pending = true (visually distinct from hex outline)
- 'A' key handler: advances selected friendly unit; guards faction + pending + selection
- 5 fighters per side — advancement reachable in normal play (5 kills × 9 XP = 45 XP)
- test_fighter_advancement_with_real_stats: headless proof using actual 7×3 fighter sword stats
- 44 tests passing (41 lib + 3 integration)

---

## Previous Milestone

**v0.2 Bridge Unification** (v0.2.0)
Status: ✅ Complete
Phases: 1 of 1 complete
Released: 2026-02-28

## v0.2 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 6 | Bridge Unification | 1 | ✅ Complete | 2026-02-28 |

## v0.2 Phase Details

### Phase 6: Bridge Unification ✅

**Goal:** Eliminate dual state extraction and magic array indices — `StateSnapshot` JSON becomes
the sole source of truth for unit data in both GDScript and external AI clients.
**Depends on:** Phase 5 (get_state_json() bridge stable)
**Completed:** 2026-02-28

**Plans:**
- [x] 06-01: Remove flat array bridge methods, refactor GDScript to parse JSON snapshot

**Delivered:**
- `get_unit_data()` and `get_unit_positions()` removed from gdext_node.rs
- `_parse_state()` helper: single JSON parse per draw/input cycle
- `_draw_units()` and `_build_unit_pos_map()` use named dictionary keys (`unit["hp"]`, etc.)
- `RH_STRIDE`, `RH_COL`, `RH_ROW` constants guard `get_reachable_hexes()` boundary
- Visual regression: none — game renders identically

---

## Previous Milestone

**v0.1 Initial Release** (v0.1.0)
Status: ✅ Complete
Phases: 5 of 5 complete
Released: 2026-02-28

## v0.1 Phases

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & Data Schema | 3 | ✅ Complete | 2026-02-27 |
| 2 | The Headless Core | 5 | ✅ Complete | 2026-02-27 |
| 3 | The Presentation Layer | 3 | ✅ Complete | 2026-02-28 |
| 4 | The Game Loop & Polish | 4 | ✅ Complete | 2026-02-28 |
| 5 | AI Hooks & External APIs | 1 | ✅ Complete | 2026-02-28 |

## v0.1 Phase Details

### Phase 1: Foundation & Data Schema ✅

**Goal:** Define the language of the game — data schemas, project scaffolding, and a working GDExtension hello-world.
**Completed:** 2026-02-27

**Plans:**
- [x] 01-01: Rust core scaffold + TOML data schemas + Registry<T> loader
- [x] 01-02: GDExtension bridge (NorRustCore GodotClass, Redot 26.1 project)
- [x] 01-03: End-to-end data flow (Registry → GDExtension → Redot console)

**Delivered:**
- `norrust_core/` Rust library (cdylib + rlib, serde/toml/gdext)
- `data/units/` and `data/terrain/` TOML files
- Generic `Registry<T>` loader
- `NorRustCore` GodotClass with `load_data()` + `get_unit_max_hp()`
- Round-trip proven: Disk → TOML → Rust → GDScript

### Phase 2: The Headless Core ✅

**Goal:** Play the game in the terminal/tests — full simulation logic with no graphics.
**Completed:** 2026-02-27

**Delivered:**
- Cubic hex coordinate system (odd-r offset at I/O boundaries)
- `GameState` struct with A* pathfinding, ZOC, unit placement
- Combat resolution: RNG, terrain defense, time-of-day modifiers, resistances
- 30+ Rust unit tests

### Phase 3: The Presentation Layer ✅

**Goal:** See the game and click things — visual rendering connected to Rust core.
**Completed:** 2026-02-28

**Delivered:**
- Redot TileMap hex grid, mouse → hex coordinate input
- Unit spawning, faction colours, HP display, move range highlighting
- Action dispatch: Redot → Rust → visual update (move, attack, end turn)

### Phase 4: The Game Loop & Polish ✅

**Goal:** A complete, playable match from start to win/loss.
**Completed:** 2026-02-28

**Plans:**
- [x] 04-01: Adjacency enforcement, defender retaliation, win/loss detection
- [x] 04-02: Unit exhaustion indicators, per-terrain healing on EndTurn
- [x] 04-03: Resistance modifiers in combat, colored HUD (Turn · ToD · Faction)
- [x] 04-04: Village terrain (healing=8), 8×5 board, terrain-driven rendering

**Delivered:**
- Full Wesnoth-style combat: adjacency check, bidirectional retaliation, time-of-day modifiers, resistance types
- Turn structure: EndTurn with faction flip, per-terrain healing, time-of-day cycle
- Visual polish: exhausted unit dimming, colored HUD, village gold-tan hexes
- Rust as terrain source of truth: `get_terrain_at()` bridge drives `_draw()`

### Phase 5: AI Hooks & External APIs ✅

**Goal:** Open the doors for the machines — clean external interfaces for AI agents.
**Completed:** 2026-02-28

**Plans:**
- [x] 05-01: JSON state serialization (StateSnapshot) + action submission (ActionRequest) + GDExtension bridge

**Delivered:**
- `snapshot.rs`: `StateSnapshot`, `UnitSnapshot`, `TileSnapshot`, `ActionRequest`
- `get_state_json()` bridge: full game state as JSON string
- `apply_action_json(json)` bridge: action submission from external clients (-99 on parse error)
- 6 new unit tests; serde_json dependency added

---

## Completed Milestones

<details>
<summary>v0.9 Game Mechanics — 2026-03-02 (2 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 20 | Gold Economy | 1 | 2026-03-02 |
| 21 | Factions + Recruitment | 2 | 2026-03-02 |

Archive: `.paul/milestones/v0.9-ROADMAP.md`
</details>

<details>
<summary>v0.8 Combat Completeness — 2026-03-02 (1 phase)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 19 | Tile Defense Combat Wiring | 1 | 2026-03-02 |

Archive: `.paul/milestones/v0.8-ROADMAP.md`
</details>

<details>
<summary>v0.7 Scenario System — 2026-03-01 (2 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 17 | Board File Format | 1 | 2026-03-01 |
| 18 | Unit Placement + Wiring | 1 | 2026-03-01 |
</details>

<details>
<summary>v0.6 Terrain System — 2026-03-01 (3 phases)</summary>

| Phase | Name | Plans | Completed |
|-------|------|-------|-----------|
| 14 | Tile Runtime + Terrain Wiring | 1 | 2026-03-01 |
| 15 | Map Generator | 1 | 2026-03-01 |
| 16 | Terrain Presentation | 1 | 2026-03-01 |
</details>

<details>
<summary>Earlier milestones (v0.1–v0.5) — 2026-02-27 to 2026-03-01</summary>
See MILESTONES.md for full history.
</details>

---
*Roadmap updated: 2026-03-10 — v3.8 Unit Expansion created*
