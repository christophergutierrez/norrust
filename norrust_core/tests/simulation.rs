use std::collections::HashMap;

use norrust_core::board::Board;
use norrust_core::game_state::{apply_action, Action, GameState};
use norrust_core::hex::Hex;
use norrust_core::schema::AttackDef;
use norrust_core::unit::Unit;

#[test]
fn test_headless_match_scenario() {
    // ── Setup: 5×5 board, all grassland ──────────────────────
    let mut board = Board::new(5, 5);
    for col in 0..5_i32 {
        for row in 0..5_i32 {
            board.set_terrain(Hex::from_offset(col, row), "grassland");
        }
    }
    let mut state = GameState::new_seeded(board, 99);

    // ── Unit 1: Faction 0 fighter at (0,0) ───────────────────
    let sword = AttackDef {
        id: "sword".to_string(),
        name: "Sword".to_string(),
        damage: 30,
        strikes: 1,
        attack_type: "blade".to_string(),
        range: "melee".to_string(),
    };
    let mut unit1 = Unit::new(1, "fighter", 30, 0);
    unit1.movement = 4;
    unit1.movement_costs = {
        let mut m = HashMap::new();
        m.insert("grassland".to_string(), 1u32);
        m
    };
    unit1.attacks = vec![sword];

    // ── Unit 2: Faction 1 archer at (2,0) — 20 HP, 0% defense ─
    let mut unit2 = Unit::new(2, "archer", 20, 1);
    unit2.movement = 4;
    unit2.default_defense = 0; // always hit

    state.place_unit(unit1, Hex::from_offset(0, 0));
    state.place_unit(unit2, Hex::from_offset(2, 0));

    // ── Turn 1, Faction 0 ─────────────────────────────────────
    // Action 1: Move unit 1 to (1,0) — adjacent to unit 2
    apply_action(
        &mut state,
        Action::Move { unit_id: 1, destination: Hex::from_offset(1, 0) },
    )
    .expect("Move unit 1 to (1,0) should succeed");

    // Action 2: Attack unit 2 with unit 1 (30 dmg > 20 HP → dead)
    apply_action(
        &mut state,
        Action::Attack { attacker_id: 1, defender_id: 2 },
    )
    .expect("Attack on unit 2 should succeed");

    // Action 3: End turn
    apply_action(&mut state, Action::EndTurn).expect("EndTurn should succeed");

    // ── Verify final state ────────────────────────────────────
    assert_eq!(state.units.len(), 1, "only one unit should survive");
    assert!(state.units.contains_key(&1), "unit 1 (attacker) must survive");
    assert!(!state.units.contains_key(&2), "unit 2 (defender) must be dead");
    assert!(!state.positions.contains_key(&2), "unit 2 position must be cleared");
}
