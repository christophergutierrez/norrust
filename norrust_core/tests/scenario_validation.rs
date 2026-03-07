//! Headless scenario validation tests.
//!
//! Every shipped scenario in `scenarios/` is automatically discovered and
//! validated against structural invariants and gameplay correctness.
//! Adding a new scenario automatically gets validated.

use std::collections::HashSet;
use std::ffi::CString;
use std::path::PathBuf;

use norrust_core::board::Tile;
use norrust_core::ffi::*;
use norrust_core::game_state::GameState;
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::scenario::{load_board, load_triggers, load_units};
use norrust_core::schema::{TerrainDef, UnitDef};
use norrust_core::unit::Unit;

// ── Path helpers ─────────────────────────────────────────────────────────────

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_path_buf()
}

fn data_dir() -> PathBuf {
    project_root().join("data")
}

fn scenario_dir() -> PathBuf {
    project_root().join("scenarios")
}

// ── Discovery ────────────────────────────────────────────────────────────────

struct ScenarioPair {
    name: String,
    board_path: PathBuf,
    units_path: PathBuf,
}

/// Find all scenario pairs in `scenarios/`.
/// Each scenario is a subdirectory containing `board.toml` and `units.toml`.
fn discover_scenarios() -> Vec<ScenarioPair> {
    let dir = scenario_dir();
    let mut pairs = Vec::new();

    for entry in std::fs::read_dir(&dir).expect("cannot read scenarios/") {
        let entry = entry.unwrap();
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let board_path = path.join("board.toml");
        let units_path = path.join("units.toml");
        if board_path.exists() && units_path.exists() {
            let name = path.file_name().unwrap().to_str().unwrap().to_string();
            pairs.push(ScenarioPair {
                name,
                board_path,
                units_path,
            });
        }
    }

    pairs.sort_by(|a, b| a.name.cmp(&b.name));
    pairs
}

// ── Structural validation ────────────────────────────────────────────────────

/// Check all structural invariants for a scenario (board + units pair).
/// Returns a list of error messages; empty means all invariants pass.
fn validate_scenario(pair: &ScenarioPair) -> Vec<String> {
    let mut errors = Vec::new();

    let loaded = match load_board(&pair.board_path) {
        Ok(b) => b,
        Err(e) => {
            errors.push(format!("Board load failed: {}", e));
            return errors;
        }
    };
    let board = &loaded.board;

    let placements = match load_units(&pair.units_path) {
        Ok(u) => u,
        Err(e) => {
            errors.push(format!("Units load failed: {}", e));
            return errors;
        }
    };

    let triggers = load_triggers(&pair.units_path).unwrap_or_default();

    let terrain_reg = Registry::<TerrainDef>::load_from_dir(&data_dir().join("terrain"))
        .expect("terrain registry load failed");
    let unit_reg = Registry::<UnitDef>::load_from_dir(&data_dir().join("units"))
        .expect("unit registry load failed");

    // 1. All hexes have terrain assigned
    for row in 0..board.height as i32 {
        for col in 0..board.width as i32 {
            let hex = Hex::from_offset(col, row);
            if board.terrain_at(hex).is_none() {
                errors.push(format!("Hex ({},{}) has no terrain assigned", col, row));
            }
        }
    }

    // 2. All terrain_ids exist in terrain registry
    for row in 0..board.height as i32 {
        for col in 0..board.width as i32 {
            let hex = Hex::from_offset(col, row);
            if let Some(tid) = board.terrain_at(hex) {
                if terrain_reg.get(tid).is_none() {
                    errors.push(format!(
                        "Hex ({},{}) terrain '{}' not in registry",
                        col, row, tid
                    ));
                }
            }
        }
    }

    // 3. All unit_type values exist in unit registry
    for p in &placements {
        if unit_reg.get(&p.unit_type).is_none() {
            errors.push(format!(
                "Unit {} type '{}' not in registry",
                p.id, p.unit_type
            ));
        }
    }

    // 4. All unit positions within board bounds
    for p in &placements {
        let hex = Hex::from_offset(p.col, p.row);
        if !board.contains(hex) {
            errors.push(format!(
                "Unit {} at ({},{}) out of bounds",
                p.id, p.col, p.row
            ));
        }
    }

    // 5. No duplicate positions or IDs
    {
        let mut seen_ids: HashSet<u32> = HashSet::new();
        let mut seen_pos: HashSet<(i32, i32)> = HashSet::new();
        for p in &placements {
            if !seen_ids.insert(p.id) {
                errors.push(format!("Duplicate unit ID {}", p.id));
            }
            if !seen_pos.insert((p.col, p.row)) {
                errors.push(format!("Duplicate position ({},{})", p.col, p.row));
            }
        }
    }

    // 6. Each faction's leader is on a "keep" tile
    //    (only checked if the faction has a leader-capable unit)
    {
        let factions: HashSet<u8> = placements.iter().map(|p| p.faction as u8).collect();
        for &faction in &factions {
            let faction_leaders: Vec<_> = placements
                .iter()
                .filter(|p| {
                    p.faction as u8 == faction
                        && unit_reg
                            .get(&p.unit_type)
                            .map(|def| def.abilities.iter().any(|a| a == "leader"))
                            .unwrap_or(false)
                })
                .collect();
            if faction_leaders.is_empty() {
                continue; // no leader units — recruitment not supported
            }
            let any_on_keep = faction_leaders.iter().any(|p| {
                let hex = Hex::from_offset(p.col, p.row);
                board.terrain_at(hex) == Some("keep")
            });
            if !any_on_keep {
                errors.push(format!(
                    "Faction {} leader(s) not on a keep tile",
                    faction
                ));
            }
        }
    }

    // 7. Each keep has 6 adjacent castle hexes
    for row in 0..board.height as i32 {
        for col in 0..board.width as i32 {
            let hex = Hex::from_offset(col, row);
            if board.terrain_at(hex) == Some("keep") {
                let castle_count = hex
                    .neighbors()
                    .iter()
                    .filter(|&&n| {
                        board.contains(n) && board.terrain_at(n) == Some("castle")
                    })
                    .count();
                if castle_count < 6 {
                    errors.push(format!(
                        "Keep at ({},{}) has only {}/6 adjacent castle hexes",
                        col, row, castle_count
                    ));
                }
            }
        }
    }

    // 8. Objective hex within bounds
    if let Some(obj) = loaded.objective_hex {
        if !board.contains(obj) {
            let (c, r) = obj.to_offset();
            errors.push(format!("Objective hex ({},{}) out of bounds", c, r));
        }
    }

    // 9. Trigger hexes + spawn hexes within bounds
    for (i, t) in triggers.iter().enumerate() {
        let thex = Hex::from_offset(t.trigger_col, t.trigger_row);
        if !board.contains(thex) {
            errors.push(format!(
                "Trigger {} hex ({},{}) out of bounds",
                i, t.trigger_col, t.trigger_row
            ));
        }
        for (j, s) in t.spawns.iter().enumerate() {
            let shex = Hex::from_offset(s.col, s.row);
            if !board.contains(shex) {
                errors.push(format!(
                    "Trigger {} spawn {} at ({},{}) out of bounds",
                    i, j, s.col, s.row
                ));
            }
        }
    }

    // 10. Trigger spawn unit_types exist in registry
    for (i, t) in triggers.iter().enumerate() {
        for (j, s) in t.spawns.iter().enumerate() {
            if unit_reg.get(&s.unit_type).is_none() {
                errors.push(format!(
                    "Trigger {} spawn {} type '{}' not in registry",
                    i, j, s.unit_type
                ));
            }
        }
    }

    errors
}

// ── No false winner ──────────────────────────────────────────────────────────

/// Load a scenario into a real GameState and verify check_winner() returns None.
fn validate_no_false_winner(pair: &ScenarioPair) -> Option<String> {
    let loaded = load_board(&pair.board_path).ok()?;
    let placements = load_units(&pair.units_path).ok()?;
    let unit_reg =
        Registry::<UnitDef>::load_from_dir(&data_dir().join("units")).ok()?;
    let terrain_reg =
        Registry::<TerrainDef>::load_from_dir(&data_dir().join("terrain")).ok()?;

    let mut state = GameState::new_seeded(loaded.board, 42);
    state.objective_hex = loaded.objective_hex;
    state.max_turns = loaded.max_turns;

    // Upgrade tiles from terrain registry
    for row in 0..state.board.height as i32 {
        for col in 0..state.board.width as i32 {
            let hex = Hex::from_offset(col, row);
            if let Some(tid) = state.board.terrain_at(hex).map(|s| s.to_string()) {
                if let Some(def) = terrain_reg.get(&tid) {
                    state.board.set_tile(hex, Tile::from_def(def));
                }
            }
        }
    }

    // Place units with full stats from registry
    for p in &placements {
        let mut unit = Unit::new(p.id, &p.unit_type, 0, p.faction as u8);
        if let Some(def) = unit_reg.get(&p.unit_type) {
            unit.max_hp = def.max_hp;
            unit.hp = def.max_hp;
            unit.movement = def.movement;
            unit.movement_costs = def.movement_costs.clone();
            unit.attacks = def.attacks.clone();
            unit.defense = def.defense.clone();
            unit.resistances = def.resistances.clone();
            unit.abilities = def.abilities.clone();
        }
        state.place_unit(unit, Hex::from_offset(p.col, p.row));
    }

    match state.check_winner() {
        None => None,
        Some(w) => Some(format!("False winner at start: faction {}", w)),
    }
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[test]
fn test_all_scenarios_valid() {
    let scenarios = discover_scenarios();
    assert!(!scenarios.is_empty(), "No scenarios discovered in scenarios/");

    let mut all_errors = Vec::new();

    for pair in &scenarios {
        println!("Validating scenario: {}", pair.name);

        let errors = validate_scenario(pair);
        if !errors.is_empty() {
            all_errors.push(format!("{}:\n  {}", pair.name, errors.join("\n  ")));
        }

        if let Some(err) = validate_no_false_winner(pair) {
            all_errors.push(format!("{}: {}", pair.name, err));
        }
    }

    if !all_errors.is_empty() {
        panic!(
            "Scenario validation failures:\n{}",
            all_errors.join("\n")
        );
    }
}

// ── FFI symbol completeness ──────────────────────────────────────────────────

/// Exercise every FFI function declared in norrust.lua's cdef block.
/// This catches missing symbols that would only surface at dlopen time in Love2D.
#[test]
fn test_ffi_all_symbols_exercised() {
    unsafe {
        let engine = norrust_new();
        assert!(!engine.is_null());

        // Data loading
        let version = norrust_get_core_version();
        assert!(!version.is_null());
        norrust_free_string(version);

        let data_path = CString::new(data_dir().to_str().unwrap()).unwrap();
        let loaded = norrust_load_data(engine, data_path.as_ptr());
        assert_eq!(loaded, 1, "norrust_load_data must succeed");

        let lt = CString::new("Lieutenant").unwrap();
        let hp = norrust_get_unit_max_hp(engine, lt.as_ptr());
        assert!(hp > 0);

        let cost = norrust_get_unit_cost(engine, lt.as_ptr());
        assert!(cost >= 0);

        let level = norrust_get_unit_level(engine, lt.as_ptr());
        assert!(level >= 1);

        // Factions
        let factions_loaded = norrust_load_factions(engine, data_path.as_ptr());
        assert_eq!(factions_loaded, 1);

        let factions_json = norrust_get_faction_ids_json(engine);
        assert!(!factions_json.is_null());
        norrust_free_string(factions_json);

        let loyalists = CString::new("loyalists").unwrap();
        let leader = norrust_get_faction_leader(engine, loyalists.as_ptr());
        assert!(!leader.is_null());
        norrust_free_string(leader);

        let recruits = norrust_get_faction_recruits_json(engine, loyalists.as_ptr(), 1);
        assert!(!recruits.is_null());
        norrust_free_string(recruits);

        // Game creation
        let created = norrust_create_game(engine, 10, 10, 42);
        assert_eq!(created, 1);

        // Terrain
        let flat = CString::new("flat").unwrap();
        norrust_set_terrain_at(engine, 0, 0, flat.as_ptr());

        let terrain = norrust_get_terrain_at(engine, 0, 0);
        assert!(!terrain.is_null());
        norrust_free_string(terrain);

        // Map generation
        let gen = norrust_generate_map(engine, 99);
        assert_eq!(gen, 1);

        // Board loading (re-creates game state)
        let scenarios = discover_scenarios();
        assert!(!scenarios.is_empty());
        let board_path =
            CString::new(scenarios[0].board_path.to_str().unwrap()).unwrap();
        let board_loaded = norrust_load_board(engine, board_path.as_ptr(), 42);
        assert_eq!(board_loaded, 1);

        // Units loading
        let units_path =
            CString::new(scenarios[0].units_path.to_str().unwrap()).unwrap();
        let units_loaded = norrust_load_units(engine, units_path.as_ptr());
        assert_eq!(units_loaded, 1);

        // Starting gold
        let f0 = CString::new("loyalists").unwrap();
        let f1 = CString::new("orcs").unwrap();
        norrust_apply_starting_gold(engine, f0.as_ptr(), f1.as_ptr());

        // State queries
        let faction = norrust_get_active_faction(engine);
        assert_eq!(faction, 0);

        let turn = norrust_get_turn(engine);
        assert_eq!(turn, 1);

        let tod = norrust_get_time_of_day_name(engine);
        assert!(!tod.is_null());
        norrust_free_string(tod);

        let _winner = norrust_get_winner(engine);

        let state_json = norrust_get_state_json(engine);
        assert!(!state_json.is_null());
        norrust_free_string(state_json);

        // Objective + max turns
        norrust_set_objective_hex(engine, 5, 5);
        norrust_set_max_turns(engine, 30);

        // Unit management
        let fighter = CString::new("Fighter").unwrap();
        norrust_place_unit_at(engine, 99, fighter.as_ptr(), 30, 0, 0, 0);
        norrust_remove_unit_at(engine, 0, 0);

        // Next unit ID
        let next_id = norrust_get_next_unit_id(engine);
        assert!(next_id >= 1);

        // Actions — move, attack, end_turn, advance, action_json
        // These may return error codes; we just verify they don't crash.
        norrust_apply_move(engine, 1, 0, 0);
        norrust_apply_attack(engine, 1, 2);
        norrust_apply_advance(engine, 1);
        norrust_end_turn(engine);

        let action = CString::new(r#"{"EndTurn":{}}"#).unwrap();
        norrust_apply_action_json(engine, action.as_ptr());

        // Recruitment
        let spearman = CString::new("Spearman").unwrap();
        norrust_recruit_unit_at(engine, 50, spearman.as_ptr(), 0, 0);

        norrust_ai_recruit(engine, loyalists.as_ptr(), 100);

        // Pathfinding
        let mut out_len: i32 = 0;
        let hexes = norrust_get_reachable_hexes(engine, 1, &mut out_len);
        if !hexes.is_null() && out_len > 0 {
            norrust_free_int_array(hexes, out_len);
        }

        // AI
        norrust_ai_take_turn(engine, 1);

        norrust_free(engine);
    }
}

// ── Per-scenario FFI smoke test ──────────────────────────────────────────────

/// For each scenario: load via FFI, verify no winner at start, run 2 AI turns,
/// verify state is still queryable. Catches runtime crashes through the FFI path.
#[test]
fn test_all_scenarios_ffi_smoke() {
    let scenarios = discover_scenarios();
    assert!(!scenarios.is_empty());

    let data_path = CString::new(data_dir().to_str().unwrap()).unwrap();

    for pair in &scenarios {
        println!("FFI smoke: {}", pair.name);

        unsafe {
            let engine = norrust_new();
            assert!(!engine.is_null(), "{}: norrust_new failed", pair.name);

            let loaded = norrust_load_data(engine, data_path.as_ptr());
            assert_eq!(loaded, 1, "{}: load_data failed", pair.name);

            let board_cstr =
                CString::new(pair.board_path.to_str().unwrap()).unwrap();
            let board_ok = norrust_load_board(engine, board_cstr.as_ptr(), 42);
            assert_eq!(board_ok, 1, "{}: load_board failed", pair.name);

            let units_cstr =
                CString::new(pair.units_path.to_str().unwrap()).unwrap();
            let units_ok = norrust_load_units(engine, units_cstr.as_ptr());
            assert_eq!(units_ok, 1, "{}: load_units failed", pair.name);

            // No winner at start
            let winner = norrust_get_winner(engine);
            assert_eq!(
                winner, -1,
                "{}: false winner {} at start via FFI",
                pair.name, winner
            );

            // Run 2 full rounds (faction 0 turn, faction 1 turn, × 2)
            for _ in 0..2 {
                let active = norrust_get_active_faction(engine);
                norrust_ai_take_turn(engine, active);
                norrust_end_turn(engine);
            }

            // State still queryable after AI turns
            let json = norrust_get_state_json(engine);
            assert!(!json.is_null(), "{}: state_json null after AI turns", pair.name);
            norrust_free_string(json);

            let turn = norrust_get_turn(engine);
            assert!(turn >= 1, "{}: turn counter invalid after AI", pair.name);

            norrust_free(engine);
        }
    }
}
