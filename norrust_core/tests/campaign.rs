//! Integration tests for campaign carry-over system.

use std::path::PathBuf;

use norrust_core::campaign::{calculate_carry_gold, get_survivors, load_campaign};
use norrust_core::board::Board;
use norrust_core::game_state::GameState;
use norrust_core::hex::Hex;
use norrust_core::unit::Unit;

fn project_root() -> PathBuf {
    let manifest = std::env::var("CARGO_MANIFEST_DIR").unwrap();
    PathBuf::from(manifest).parent().unwrap().to_path_buf()
}

#[test]
fn test_load_campaign_toml() {
    let path = project_root().join("campaigns/tutorial.toml");
    let campaign = load_campaign(&path).expect("should load tutorial campaign");
    assert_eq!(campaign.id, "tutorial");
    assert_eq!(campaign.name, "The Road to Norrust");
    assert_eq!(campaign.gold_carry_percent, 80);
    assert_eq!(campaign.early_finish_bonus, 5);
    assert_eq!(campaign.scenarios.len(), 4);
    assert_eq!(campaign.scenarios[0].board, "crossing/board.toml");
    assert!(campaign.scenarios[0].preset_units);
    assert_eq!(campaign.scenarios[1].board, "ambush/board.toml");
    assert!(campaign.scenarios[1].preset_units);
    assert_eq!(campaign.scenarios[2].board, "night_orcs/board.toml");
    assert!(campaign.scenarios[2].preset_units);
    assert_eq!(campaign.scenarios[3].board, "final_battle/board.toml");
    assert!(campaign.scenarios[3].preset_units);
}

#[test]
fn test_campaign_scenario_sequence() {
    let path = project_root().join("campaigns/tutorial.toml");
    let campaign = load_campaign(&path).unwrap();

    let expected = vec![
        ("crossing/board.toml", "crossing/units.toml"),
        ("ambush/board.toml", "ambush/units.toml"),
    ];
    for (i, (board, units)) in expected.iter().enumerate() {
        assert_eq!(campaign.scenarios[i].board, *board);
        assert_eq!(campaign.scenarios[i].units, *units);
    }
}

#[test]
fn test_get_survivors() {
    let board = Board::new(10, 10);
    let mut state = GameState::new(board);

    // Faction 0: two units — one full health, one wounded with XP
    let mut fighter = Unit::new(1, "fighter", 30, 0);
    fighter.xp = 15;
    fighter.xp_needed = 40;
    fighter.abilities = vec!["leader".to_string()];
    state.place_unit(fighter, Hex::from_offset(0, 0));

    let mut archer = Unit::new(2, "archer", 25, 0);
    archer.hp = 12; // wounded
    archer.xp = 5;
    archer.xp_needed = 32;
    archer.advancement_pending = false;
    state.place_unit(archer, Hex::from_offset(1, 0));

    // Faction 1: enemy — should not appear in faction 0 survivors
    state.place_unit(Unit::new(3, "grunt", 30, 1), Hex::from_offset(2, 0));

    let survivors = get_survivors(&state, 0);
    assert_eq!(survivors.len(), 2, "faction 0 has 2 units");

    let fighter_v = survivors.iter().find(|v| v.def_id == "fighter").unwrap();
    assert_eq!(fighter_v.hp, 30);
    assert_eq!(fighter_v.max_hp, 30);
    assert_eq!(fighter_v.xp, 15);
    assert_eq!(fighter_v.xp_needed, 40);
    assert!(!fighter_v.advancement_pending);
    assert_eq!(fighter_v.abilities, vec!["leader"]);

    let archer_v = survivors.iter().find(|v| v.def_id == "archer").unwrap();
    assert_eq!(archer_v.hp, 12, "wounded HP carries");
    assert_eq!(archer_v.max_hp, 25);
    assert_eq!(archer_v.xp, 5);
    assert_eq!(archer_v.xp_needed, 32);
}

#[test]
fn test_calculate_carry_gold() {
    // 150 gold at 80% = 120
    assert_eq!(calculate_carry_gold(150, 80, 0, 0), 120);

    // 150 gold at 80% + 10 remaining turns * 5 bonus = 170
    assert_eq!(calculate_carry_gold(150, 80, 10, 5), 170);
}

#[test]
fn test_calculate_carry_gold_caps_at_100_percent() {
    assert_eq!(calculate_carry_gold(100, 100, 0, 0), 100);
    assert_eq!(calculate_carry_gold(250, 100, 0, 0), 250);
}

// ── FFI tests ───────────────────────────────────────────────────────────────

use norrust_core::ffi::*;
use std::ffi::CString;

unsafe fn c(s: &str) -> CString {
    CString::new(s).unwrap()
}

unsafe fn ffi_string(ptr: *mut std::ffi::c_char) -> String {
    if ptr.is_null() {
        return String::new();
    }
    let s = std::ffi::CStr::from_ptr(ptr).to_string_lossy().into_owned();
    norrust_free_string(ptr);
    s
}

#[test]
fn test_veteran_placement_via_ffi() {
    unsafe {
        let engine = norrust_new();
        let data_path = c(&project_root().join("data").to_string_lossy());
        assert_eq!(norrust_load_data(engine, data_path.as_ptr()), 1);

        // Load a board
        let board_path = c(&project_root().join("scenarios/contested/board.toml").to_string_lossy());
        assert_eq!(norrust_load_board(engine, board_path.as_ptr(), 42), 1);

        // Place a veteran fighter with custom stats
        let def_id = c("fighter");
        let result = norrust_place_veteran_unit(
            engine,
            99,             // unit_id
            def_id.as_ptr(),
            0,              // faction
            1, 1,           // col, row
            18,             // hp (wounded)
            25,             // xp
            40,             // xp_needed
            0,              // advancement_pending = false
        );
        assert_eq!(result, 0, "veteran placement should succeed");

        // Verify via state JSON that the unit has carried stats
        let json_str = ffi_string(norrust_get_state_json(engine));
        assert!(!json_str.is_empty());
        // The unit should have hp=18 (not registry default 36 for Spearman or whatever)
        assert!(json_str.contains("\"hp\":18"), "veteran HP should be 18, not registry default");
        assert!(json_str.contains("\"xp\":25"), "veteran XP should be 25");
        assert!(json_str.contains("\"xp_needed\":40"), "veteran xp_needed should be 40");

        norrust_free(engine);
    }
}

#[test]
fn test_load_campaign_via_ffi() {
    unsafe {
        let engine = norrust_new();
        let path = c(&project_root().join("campaigns/tutorial.toml").to_string_lossy());
        let json_str = ffi_string(norrust_load_campaign(engine, path.as_ptr()));
        assert!(!json_str.is_empty(), "campaign JSON should not be empty");
        assert!(json_str.contains("\"id\":\"tutorial\""));
        assert!(json_str.contains("\"gold_carry_percent\":80"));
        assert!(json_str.contains("\"early_finish_bonus\":5"));
        assert!(json_str.contains("\"crossing/board.toml\""));
        assert!(json_str.contains("\"ambush/board.toml\""));

        norrust_free(engine);
    }
}

#[test]
fn test_survivors_and_carry_gold_via_ffi() {
    unsafe {
        let engine = norrust_new();
        let data_path = c(&project_root().join("data").to_string_lossy());
        assert_eq!(norrust_load_data(engine, data_path.as_ptr()), 1);

        // Load crossing scenario
        let board_path = c(&project_root().join("scenarios/crossing/board.toml").to_string_lossy());
        assert_eq!(norrust_load_board(engine, board_path.as_ptr(), 42), 1);

        let units_path = c(&project_root().join("scenarios/crossing/units.toml").to_string_lossy());
        assert_eq!(norrust_load_units(engine, units_path.as_ptr()), 1);

        // Get survivors for faction 0
        let survivors_json = ffi_string(norrust_get_survivors_json(engine, 0));
        assert!(survivors_json.starts_with('['), "survivors should be a JSON array");
        assert!(survivors_json.contains("\"def_id\""), "survivors should have unit data");

        // Get carry gold (80%, 5 bonus per remaining turn)
        let gold = norrust_get_carry_gold(engine, 0, 80, 5);
        assert!(gold >= 0, "carry gold should be non-negative");

        norrust_free(engine);
    }
}
