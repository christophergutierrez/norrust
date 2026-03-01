use std::collections::HashMap;

use norrust_core::board::Board;
use norrust_core::game_state::{apply_action, Action, GameState};
use norrust_core::hex::Hex;
use norrust_core::schema::{AttackDef, UnitDef};
use norrust_core::unit::{advance_unit, Unit};

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

#[test]
fn test_headless_advancement_scenario() {
    // ── Setup: fighter with xp_needed=40 vs. repeated weak enemies ──
    let board = Board::new(5, 5);
    let mut state = GameState::new_seeded(board, 7);

    let sword = AttackDef {
        id: "sword".to_string(), name: "Sword".to_string(),
        damage: 100, strikes: 1,
        attack_type: "blade".to_string(), range: "melee".to_string(),
    };
    let mut fighter = Unit::new(1, "fighter", 30, 0);
    fighter.attacks = vec![sword.clone()];
    fighter.xp_needed = 40;
    state.place_unit(fighter, Hex::from_offset(0, 0));

    // Kill 5 enemies: each kill = 9 XP (1 hit + 8 kill bonus) → 45 XP total
    for enemy_id in 2u32..=6 {
        let mut enemy = Unit::new(enemy_id, "enemy", 1, 1);
        enemy.default_defense = 0;
        state.place_unit(enemy, Hex::from_offset(1, 0));

        apply_action(
            &mut state,
            Action::Attack { attacker_id: 1, defender_id: enemy_id },
        )
        .expect("attack should succeed");

        // Two EndTurns: return to faction 0 and reset attacked flag
        apply_action(&mut state, Action::EndTurn).expect("EndTurn should succeed");
        apply_action(&mut state, Action::EndTurn).expect("EndTurn should succeed");
    }

    assert!(state.units[&1].xp >= 40, "fighter should have accumulated 40+ XP");
    assert!(state.units[&1].advancement_pending, "advancement_pending must be set");

    // ── Advance the fighter to hero ──────────────────────────────────
    let hero_def = UnitDef {
        id: "hero".to_string(),
        name: "Hero".to_string(),
        max_hp: 45,
        movement: 5,
        attacks: vec![sword],
        resistances: HashMap::new(),
        movement_costs: HashMap::new(),
        defense: HashMap::new(),
        level: 2,
        experience: 80,
        advances_to: vec![],
    };

    advance_unit(state.units.get_mut(&1).unwrap(), &hero_def);

    assert_eq!(state.units[&1].def_id, "hero");
    assert_eq!(state.units[&1].max_hp, 45);
    assert_eq!(state.units[&1].hp, 45);
    assert_eq!(state.units[&1].xp, 0);
    assert_eq!(state.units[&1].xp_needed, 80);
    assert!(!state.units[&1].advancement_pending);
}

#[test]
fn test_fighter_advancement_with_real_stats() {
    // Verify the full advancement pipeline using actual fighter.toml stats:
    //   damage=7, strikes=3, xp_needed=40, advances to hero (max_hp=45, xp_needed=80).
    // Enemies have 1 HP and 0% defense so kills are guaranteed (7 damage > 1 HP).
    // Each kill: 1 hit XP + 8 kill bonus = 9 XP.  5 kills → 45 XP → advancement_pending.
    //
    // This matches the in-game scenario: place_unit_at copies xp_needed=40 from
    // fighter.toml `experience` field.  The game requires ~5 kills to advance.
    let board = Board::new(5, 5);
    let mut state = GameState::new_seeded(board, 42);

    // Fighter with actual TOML weapon stats (damage=7 strikes=3)
    let sword = AttackDef {
        id: "sword".to_string(), name: "Sword".to_string(),
        damage: 7, strikes: 3,
        attack_type: "blade".to_string(), range: "melee".to_string(),
    };
    let mut fighter = Unit::new(1, "fighter", 30, 0);
    fighter.attacks = vec![sword.clone()];
    fighter.xp_needed = 40; // from fighter.toml experience = 40
    state.place_unit(fighter, Hex::from_offset(0, 0));

    // Kill 5 enemies (1 HP, 0% defense) — each guarantees a kill (7 dmg > 1 HP)
    for enemy_id in 2u32..=6 {
        let mut enemy = Unit::new(enemy_id, "enemy", 1, 1);
        enemy.default_defense = 0;
        state.place_unit(enemy, Hex::from_offset(1, 0));

        apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: enemy_id })
            .expect("attack should succeed");
        apply_action(&mut state, Action::EndTurn).expect("EndTurn 1 should succeed");
        apply_action(&mut state, Action::EndTurn).expect("EndTurn 2 should succeed");
    }

    assert!(state.units[&1].xp >= 40, "45 XP expected (5 kills × 9 XP each)");
    assert_eq!(state.units[&1].xp, 45);
    assert!(state.units[&1].advancement_pending, "advancement_pending must be set after 45 XP");

    // Advance to hero using actual hero.toml stats
    let hero_def = UnitDef {
        id: "hero".to_string(),
        name: "Hero".to_string(),
        max_hp: 45,
        movement: 5,
        attacks: vec![
            AttackDef { id: "sword".to_string(), name: "Sword".to_string(),
                        damage: 9, strikes: 4, attack_type: "blade".to_string(),
                        range: "melee".to_string() },
        ],
        resistances: HashMap::new(),
        movement_costs: HashMap::new(),
        defense: HashMap::new(),
        level: 2,
        experience: 80,
        advances_to: vec![],
    };

    advance_unit(state.units.get_mut(&1).unwrap(), &hero_def);

    assert_eq!(state.units[&1].def_id, "hero",        "def_id must update to hero");
    assert_eq!(state.units[&1].max_hp, 45,            "hero max_hp = 45");
    assert_eq!(state.units[&1].hp,     45,            "full heal on advancement");
    assert_eq!(state.units[&1].xp,      0,            "xp resets to 0");
    assert_eq!(state.units[&1].xp_needed, 80,         "xp_needed set from hero.toml experience");
    assert!(!state.units[&1].advancement_pending,      "advancement_pending cleared");
    // Verify weapon updated: hero sword does 9×4
    assert_eq!(state.units[&1].attacks[0].damage, 9);
    assert_eq!(state.units[&1].attacks[0].strikes, 4);
}
