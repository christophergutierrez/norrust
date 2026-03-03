use std::ffi::{CStr, CString};

use norrust_core::ffi::*;

/// Helper: create a CString and return its pointer (caller must keep CString alive).
fn c(s: &str) -> CString {
    CString::new(s).unwrap()
}

#[test]
fn test_ffi_full_game_cycle() {
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let project_root = std::path::Path::new(manifest_dir)
        .parent()
        .expect("norrust_core has a parent dir");

    let data_path = project_root.join("data");
    let board_path = project_root.join("scenarios/contested.toml");
    let units_path = project_root.join("scenarios/contested_units.toml");

    let c_data = c(data_path.to_str().unwrap());
    let c_board = c(board_path.to_str().unwrap());
    let c_units = c(units_path.to_str().unwrap());

    unsafe {
        // ── Lifecycle: create engine ────────────────────────────────
        let engine = norrust_new();
        assert!(!engine.is_null(), "norrust_new must return non-null");

        // ── Load data (unit + terrain registries) ──────────────────
        let ok = norrust_load_data(engine, c_data.as_ptr());
        assert_eq!(ok, 1, "norrust_load_data must succeed");

        // ── Load board ─────────────────────────────────────────────
        let ok = norrust_load_board(engine, c_board.as_ptr(), 42);
        assert_eq!(ok, 1, "norrust_load_board must succeed");

        // ── Load factions ──────────────────────────────────────────
        let ok = norrust_load_factions(engine, c_data.as_ptr());
        assert_eq!(ok, 1, "norrust_load_factions must succeed");

        // ── Load units ─────────────────────────────────────────────
        let ok = norrust_load_units(engine, c_units.as_ptr());
        assert_eq!(ok, 1, "norrust_load_units must succeed");

        // ── Apply starting gold ────────────────────────────────────
        let f0 = c("loyalists");
        let f1 = c("orcs");
        let ok = norrust_apply_starting_gold(engine, f0.as_ptr(), f1.as_ptr());
        assert_eq!(ok, 1, "norrust_apply_starting_gold must succeed");

        // ── Query state JSON ───────────────────────────────────────
        let json_ptr = norrust_get_state_json(engine);
        assert!(!json_ptr.is_null(), "state JSON must not be null");
        let json = CStr::from_ptr(json_ptr).to_str().unwrap();
        assert!(json.contains("units"), "state JSON must contain 'units'");
        assert!(json.contains("terrain"), "state JSON must contain 'terrain'");
        norrust_free_string(json_ptr);

        // ── Query active faction ───────────────────────────────────
        let faction = norrust_get_active_faction(engine);
        assert_eq!(faction, 0, "initial active faction must be 0");

        // ── Query turn ─────────────────────────────────────────────
        let turn = norrust_get_turn(engine);
        assert!(turn >= 1, "turn must be >= 1");

        // ── Get reachable hexes for a unit ─────────────────────────
        // Unit ID 1 should exist (first unit in contested_units.toml)
        let mut out_len: i32 = 0;
        let hexes_ptr = norrust_get_reachable_hexes(engine, 1, &mut out_len);
        assert!(out_len > 0, "reachable hexes must be non-empty for unit 1");
        assert!(!hexes_ptr.is_null(), "reachable hexes pointer must not be null");
        // Read first pair to verify format (col, row)
        let first_col = *hexes_ptr;
        let first_row = *hexes_ptr.add(1);
        assert!(first_col >= 0 && first_col < 8, "reachable col in bounds");
        assert!(first_row >= 0 && first_row < 5, "reachable row in bounds");
        norrust_free_int_array(hexes_ptr, out_len);

        // ── Apply move: move unit 1 to a reachable hex ─────────────
        // Collect reachable hexes, then try each until we find an unoccupied one
        let mut move_out_len: i32 = 0;
        let move_hexes = norrust_get_reachable_hexes(engine, 1, &mut move_out_len);
        assert!(move_out_len >= 2, "need at least one reachable hex pair");
        let mut destinations = Vec::new();
        for i in (0..move_out_len as usize).step_by(2) {
            destinations.push((*move_hexes.add(i), *move_hexes.add(i + 1)));
        }
        norrust_free_int_array(move_hexes, move_out_len);

        let mut moved = false;
        for (col, row) in &destinations {
            if norrust_apply_move(engine, 1, *col, *row) == 0 {
                moved = true;
                break;
            }
        }
        assert!(moved, "at least one reachable hex must be a valid move destination");

        // ── End turn ───────────────────────────────────────────────
        let result = norrust_end_turn(engine);
        assert_eq!(result, 0, "norrust_end_turn must succeed");

        // Faction should now be 1
        let faction = norrust_get_active_faction(engine);
        assert_eq!(faction, 1, "after end_turn, active faction must be 1");

        // ── End turn again to cycle back to faction 0 ──────────────
        let result = norrust_end_turn(engine);
        assert_eq!(result, 0, "second end_turn must succeed");

        let turn = norrust_get_turn(engine);
        assert!(turn >= 2, "turn must have incremented");

        // ── Get winner (should be -1, game still ongoing) ──────────
        let winner = norrust_get_winner(engine);
        assert_eq!(winner, -1, "no winner yet");

        // ── Time of day ────────────────────────────────────────────
        let tod_ptr = norrust_get_time_of_day_name(engine);
        assert!(!tod_ptr.is_null());
        let tod = CStr::from_ptr(tod_ptr).to_str().unwrap();
        assert!(!tod.is_empty(), "time of day name must not be empty");
        norrust_free_string(tod_ptr);

        // ── Version string ─────────────────────────────────────────
        let ver_ptr = norrust_get_core_version();
        assert!(!ver_ptr.is_null());
        let ver = CStr::from_ptr(ver_ptr).to_str().unwrap();
        assert_eq!(ver, "0.1.0");
        norrust_free_string(ver_ptr);

        // ── Faction queries ────────────────────────────────────────
        let ids_ptr = norrust_get_faction_ids_json(engine);
        let ids_json = CStr::from_ptr(ids_ptr).to_str().unwrap();
        assert!(ids_json.contains("loyalists"), "faction IDs must include loyalists");
        norrust_free_string(ids_ptr);

        let leader_ptr = norrust_get_faction_leader(engine, f0.as_ptr());
        let leader = CStr::from_ptr(leader_ptr).to_str().unwrap();
        assert!(!leader.is_empty(), "loyalists must have a leader");
        norrust_free_string(leader_ptr);

        let recruits_ptr = norrust_get_faction_recruits_json(engine, f0.as_ptr(), 1);
        let recruits = CStr::from_ptr(recruits_ptr).to_str().unwrap();
        assert!(recruits.starts_with('['), "recruits must be a JSON array");
        norrust_free_string(recruits_ptr);

        // ── Terrain query ──────────────────────────────────────────
        let terrain_ptr = norrust_get_terrain_at(engine, 1, 2);
        let terrain = CStr::from_ptr(terrain_ptr).to_str().unwrap();
        assert_eq!(terrain, "keep", "contested board has keep at (1,2)");
        norrust_free_string(terrain_ptr);

        // ── Unit registry queries ──────────────────────────────────
        let c_spearman = c("Spearman");
        let cost = norrust_get_unit_cost(engine, c_spearman.as_ptr());
        assert!(cost > 0, "Spearman cost must be positive");

        let level = norrust_get_unit_level(engine, c_spearman.as_ptr());
        assert_eq!(level, 1, "Spearman is level 1");

        let max_hp = norrust_get_unit_max_hp(engine, c_spearman.as_ptr());
        assert_eq!(max_hp, 36, "Spearman max_hp = 36");

        // ── Cleanup ────────────────────────────────────────────────
        norrust_free(engine);
    }
}
