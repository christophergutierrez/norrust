use std::collections::{HashMap, HashSet};

use norrust_core::ai::ai_take_turn;
use norrust_core::board::Board;
use norrust_core::game_state::{apply_action, Action, ActionError, GameState};
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::schema::{AttackDef, UnitDef};
use norrust_core::unit::{advance_unit, Unit};

#[test]
fn test_headless_match_scenario() {
    // ── Setup: 5×5 board, all flat ───────────────────────────
    let mut board = Board::new(5, 5);
    for col in 0..5_i32 {
        for row in 0..5_i32 {
            board.set_terrain(Hex::from_offset(col, row), "flat");
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
        ..Default::default()
    };
    let mut unit1 = Unit::new(1, "fighter", 30, 0);
    unit1.movement = 4;
    unit1.movement_costs = {
        let mut m = HashMap::new();
        m.insert("flat".to_string(), 1u32);
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
        ..Default::default()
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
        ..Default::default()
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
        ..Default::default()
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
                        range: "melee".to_string(), ..Default::default() },
        ],
        resistances: HashMap::new(),
        movement_costs: HashMap::new(),
        defense: HashMap::new(),
        level: 2,
        experience: 80,
        advances_to: vec![],
        ..Default::default()
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

#[test]
fn test_ai_vs_ai_terminates() {
    fn game_winner(state: &GameState) -> Option<u8> {
        let has_0 = state.units.values().any(|u| u.faction == 0);
        let has_1 = state.units.values().any(|u| u.faction == 1);
        match (has_0, has_1) {
            (true, false) => Some(0),
            (false, true) => Some(1),
            _ => None,
        }
    }

    // 8×5 board with uniform flat terrain.
    // Uniform terrain ensures movement=5 units can reach adjacent to opponents
    // on turn 1 (closest faction-1 units are at distance 5 from faction-0 col-1 units).
    let mut board = Board::new(8, 5);
    for col in 0..8_i32 {
        for row in 0..5_i32 {
            board.set_terrain(Hex::from_offset(col, row), "flat");
        }
    }
    let mut state = GameState::new_seeded(board, 42);

    let sword = AttackDef {
        id: "sword".to_string(),
        name: "Sword".to_string(),
        damage: 7,
        strikes: 3,
        attack_type: "blade".to_string(),
        range: "melee".to_string(),
        ..Default::default()
    };
    let mut movement_costs = HashMap::new();
    movement_costs.insert("flat".to_string(), 1u32);
    let mut defense_map = HashMap::new();
    defense_map.insert("flat".to_string(), 40u32);

    let make_unit = |id: u32, faction: u8| -> Unit {
        let mut u = Unit::new(id, "fighter", 30, faction);
        u.attacks = vec![sword.clone()];
        u.movement = 5;
        u.movement_costs = movement_costs.clone();
        u.defense = defense_map.clone();
        u.default_defense = 40;
        u.xp_needed = 40;
        u
    };

    // Faction 0: left side
    let f0_positions = [(0, 0), (0, 2), (0, 4), (1, 1), (1, 3)];
    for (i, (col, row)) in f0_positions.iter().enumerate() {
        state.place_unit(make_unit(i as u32 + 1, 0), Hex::from_offset(*col, *row));
    }

    // Faction 1: right side
    let f1_positions = [(7, 0), (7, 2), (7, 4), (6, 1), (6, 3)];
    for (i, (col, row)) in f1_positions.iter().enumerate() {
        state.place_unit(make_unit(i as u32 + 6, 1), Hex::from_offset(*col, *row));
    }

    // Run AI vs AI for up to 100 turns (each call to ai_take_turn includes EndTurn).
    for _ in 0..100 {
        let faction = state.active_faction;
        ai_take_turn(&mut state, faction);
        if game_winner(&state).is_some() {
            break;
        }
    }

    assert!(
        game_winner(&state).is_some(),
        "AI vs AI game must have a winner within 100 turns; {} faction-0 units, {} faction-1 units remain",
        state.units.values().filter(|u| u.faction == 0).count(),
        state.units.values().filter(|u| u.faction == 1).count(),
    );
}

#[test]
fn test_ai_marches_toward_enemy_when_no_attack() {
    // 8×1 board (single row) — forces purely horizontal movement.
    // Faction 0 at col 0, faction 1 at col 7: distance = 7, movement = 5.
    // No attack possible. AI should march to col 5 (max reachable toward enemy).
    let mut board = Board::new(8, 1);
    for col in 0..8_i32 {
        board.set_terrain(Hex::from_offset(col, 0), "flat");
    }
    let mut state = GameState::new_seeded(board, 42);

    let sword = AttackDef {
        id: "sword".to_string(), name: "Sword".to_string(),
        damage: 7, strikes: 3,
        attack_type: "blade".to_string(), range: "melee".to_string(),
        ..Default::default()
    };
    let mut costs = HashMap::new();
    costs.insert("flat".to_string(), 1u32);

    let mut f0 = Unit::new(1, "fighter", 30, 0);
    f0.attacks = vec![sword.clone()];
    f0.movement = 5;
    f0.movement_costs = costs.clone();

    let mut f1 = Unit::new(2, "fighter", 30, 1);
    f1.attacks = vec![sword];
    f1.movement = 5;
    f1.movement_costs = costs;

    state.place_unit(f0, Hex::from_offset(0, 0));
    state.place_unit(f1, Hex::from_offset(7, 0));

    ai_take_turn(&mut state, 0);

    let (col, _) = state.positions[&1].to_offset();
    assert!(col > 0, "unit should have advanced from col 0, now at col {}", col);
    assert_eq!(col, 5, "should have marched to col 5 (furthest reachable toward enemy)");
}

#[test]
fn test_wesnoth_units_load() {
    let data_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("norrust_core has a parent dir")
        .join("data/units");

    let registry = Registry::<UnitDef>::load_from_dir(&data_dir)
        .expect("all unit TOMLs must load without error");

    // 4 custom units + 200+ scraped Wesnoth units
    assert!(
        registry.len() >= 200,
        "expected >= 200 units, got {}",
        registry.len()
    );

    // Spot-check: Spearman must load with correct stats
    let spearman = registry
        .get("Spearman")
        .expect("Spearman must be in registry");
    assert_eq!(spearman.max_hp, 36, "Spearman max_hp");
    assert_eq!(spearman.movement, 5, "Spearman movement");
    assert_eq!(spearman.level, 1, "Spearman level");
    assert_eq!(spearman.alignment, "lawful", "Spearman alignment");
    assert!(
        spearman.attacks.iter().any(|a| a.attack_type == "pierce"),
        "Spearman must have a pierce attack"
    );
}

#[test]
fn test_terrain_wiring() {
    // Board: flat | flat | hills | hills | flat  (1-row, 5 cols)
    let mut board = Board::new(5, 1);
    for col in 0..5_i32 {
        let t = if col >= 2 && col <= 3 { "hills" } else { "flat" };
        board.set_terrain(Hex::from_offset(col, 0), t);
    }
    let mut state = GameState::new_seeded(board, 1);

    // Build a unit with Spearman-style movement costs (flat=1, hills=2)
    let mut unit = Unit::new(1, "Spearman", 36, 0);
    unit.movement = 5;
    let mut movement_costs = HashMap::new();
    movement_costs.insert("flat".to_string(), 1u32);
    movement_costs.insert("hills".to_string(), 2u32);
    unit.movement_costs = movement_costs;
    state.place_unit(unit, Hex::from_offset(0, 0));

    // flat(0→1)=1 + hills(1→2)=2 + hills(2→3)=2 = total 5 ≤ budget 5 → reachable
    let r = apply_action(&mut state, Action::Move {
        unit_id: 1,
        destination: Hex::from_offset(3, 0),
    });
    assert!(r.is_ok(), "should reach col 3: flat(1)+hills(2)+hills(2)=5 = budget");

    // Rebuild unit at col 0 for next assertion
    let mut unit2 = Unit::new(2, "Spearman", 36, 0);
    unit2.movement = 5;
    let mut mc2 = HashMap::new();
    mc2.insert("flat".to_string(), 1u32);
    mc2.insert("hills".to_string(), 2u32);
    unit2.movement_costs = mc2;
    state.place_unit(unit2, Hex::from_offset(0, 0));

    // flat(1) + hills(2) + hills(2) + flat(1) = 6 > budget 5 → unreachable
    let r2 = apply_action(&mut state, Action::Move {
        unit_id: 2,
        destination: Hex::from_offset(4, 0),
    });
    assert_eq!(r2, Err(ActionError::DestinationUnreachable),
        "col 4 costs 6 MP total, exceeds budget 5");
}

#[test]
fn test_generate_map() {
    use norrust_core::mapgen::generate_map;

    let mut board = Board::new(8, 5);
    generate_map(&mut board, 42);

    // AC-1: All 40 hexes must have terrain
    for col in 0..8_i32 {
        for row in 0..5_i32 {
            assert!(
                board.terrain_at(Hex::from_offset(col, row)).is_some(),
                "hex ({col},{row}) must have terrain assigned"
            );
        }
    }

    // AC-2: Spawn zones (cols 0-1 and 6-7) always flat
    for row in 0..5_i32 {
        for spawn_col in [0, 1, 6, 7] {
            assert_eq!(
                board.terrain_at(Hex::from_offset(spawn_col, row)),
                Some("flat"),
                "spawn zone col {spawn_col} row {row} must be flat"
            );
        }
    }

    // AC-3: Villages at structural positions (8 cols: v1=2, v2=5; mid_row=2)
    assert_eq!(board.terrain_at(Hex::from_offset(2, 2)), Some("village"),
        "village must be at (2,2)");
    assert_eq!(board.terrain_at(Hex::from_offset(5, 2)), Some("village"),
        "village must be at (5,2)");

    // AC-4: Contested zone has at least 2 distinct terrain types
    let contested: HashSet<&str> = (2..6_i32)
        .flat_map(|col| (0..5_i32).map(move |row| (col, row)))
        .filter(|&(col, row)| !(col == 2 && row == 2) && !(col == 5 && row == 2))
        .filter_map(|(col, row)| board.terrain_at(Hex::from_offset(col, row)))
        .collect();
    assert!(
        contested.len() >= 2,
        "contested zone must have at least 2 terrain types, got: {:?}", contested
    );
    // All terrain IDs must be from the valid set
    let valid: HashSet<&str> = ["flat", "forest", "hills", "mountains"].into();
    for t in &contested {
        assert!(valid.contains(t), "unexpected terrain '{t}' in contested zone");
    }
}
