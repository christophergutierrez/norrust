use std::collections::{HashMap, HashSet};

use norrust_core::ai::ai_take_turn;
use norrust_core::board::Board;
use norrust_core::game_state::{
    apply_action, apply_recruit, Action, ActionError, GameState, PendingSpawn, TriggerZone,
};
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::schema::{AttackDef, FactionDef, UnitDef};
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
fn test_load_board_from_file() {
    use norrust_core::scenario::load_board;

    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("norrust_core has a parent dir")
        .join("scenarios/contested/board.toml");

    let loaded = load_board(&path).expect("contested.toml must load without error");
    let board = &loaded.board;

    // No objective or max_turns for contested scenario
    assert!(loaded.objective_hex.is_none(), "contested has no objective_hex");
    assert!(loaded.max_turns.is_none(), "contested has no max_turns");

    // AC-1: Dimensions correct
    assert_eq!(board.width, 8, "board width must be 8");
    assert_eq!(board.height, 5, "board height must be 5");

    // AC-2: All 40 hexes have terrain
    for col in 0..8_i32 {
        for row in 0..5_i32 {
            assert!(
                board.terrain_at(Hex::from_offset(col, row)).is_some(),
                "hex ({col},{row}) must have terrain"
            );
        }
    }

    // AC-3: Keep positions
    assert_eq!(board.terrain_at(Hex::from_offset(1, 2)), Some("keep"), "Blue keep at (1,2)");
    assert_eq!(board.terrain_at(Hex::from_offset(6, 2)), Some("keep"), "Red keep at (6,2)");

    // AC-4: Castle hexes adjacent to each keep
    for (col, row) in [(0,1),(0,2),(0,3),(1,1),(1,3),(2,2)] {
        assert_eq!(
            board.terrain_at(Hex::from_offset(col, row)),
            Some("castle"),
            "Blue castle at ({col},{row})"
        );
    }
    for (col, row) in [(5,1),(5,2),(5,3),(6,1),(6,3),(7,2)] {
        assert_eq!(
            board.terrain_at(Hex::from_offset(col, row)),
            Some("castle"),
            "Red castle at ({col},{row})"
        );
    }

    // AC-5: Corner hexes are flat
    for (col, row) in [(0,0),(1,0),(0,4),(1,4),(6,0),(7,0),(6,4),(7,4)] {
        assert_eq!(
            board.terrain_at(Hex::from_offset(col, row)),
            Some("flat"),
            "corner flat at ({col},{row})"
        );
    }

    // Spot-check interior: village at (3,1) and (4,3)
    assert_eq!(board.terrain_at(Hex::from_offset(3, 1)), Some("village"));
    assert_eq!(board.terrain_at(Hex::from_offset(4, 3)), Some("village"));
}

#[test]
fn test_load_units_from_file() {
    use norrust_core::scenario::load_units;

    let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("norrust_core has a parent dir")
        .join("scenarios/contested/units.toml");

    let placements = load_units(&path).expect("contested_units.toml must load");

    // AC-1: Count and faction balance
    assert_eq!(placements.len(), 10, "10 units total");
    let f0 = placements.iter().filter(|p| p.faction == 0).count();
    let f1 = placements.iter().filter(|p| p.faction == 1).count();
    assert_eq!(f0, 5, "5 faction 0 units");
    assert_eq!(f1, 5, "5 faction 1 units");

    // AC-2: Valid positions and non-empty unit types
    for p in &placements {
        assert!(!p.unit_type.is_empty(), "unit_type must not be empty for id={}", p.id);
        assert!(p.col >= 0 && p.col < 8, "col out of range for id={}", p.id);
        assert!(p.row >= 0 && p.row < 5, "row out of range for id={}", p.id);
    }

    // AC-2: Unique IDs
    let ids: HashSet<u32> = placements.iter().map(|p| p.id).collect();
    assert_eq!(ids.len(), placements.len(), "all unit IDs must be unique");
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

#[test]
fn test_faction_def_starting_gold_loads() {
    let data_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .join("data");
    let registry = Registry::<FactionDef>::load_from_dir(&data_path.join("factions"))
        .expect("factions must load");
    // At least the three shipped factions must be present
    assert!(registry.len() >= 3, "expected >= 3 factions, got {}", registry.len());
    let loyalists = registry.get("loyalists").expect("loyalists must exist");
    assert_eq!(loyalists.starting_gold, 100, "loyalists starting_gold should be 100");
    // All loaded factions should have positive starting gold
    assert!(
        registry.all().all(|f| f.starting_gold > 0),
        "all factions must have positive starting_gold"
    );
}

/// Set up a minimal board with a keep at (0,0) and an adjacent castle at (1,0).
/// Places a leader unit on the keep for the active faction.
/// (1,0) is adjacent to (0,0): both convert to Hex distance 1.)
fn setup_recruit_board() -> (GameState, Hex, Hex) {
    use norrust_core::board::Tile;
    use norrust_core::unit::Unit;
    let keep_hex    = Hex::from_offset(0, 0);
    let castle_hex  = Hex::from_offset(1, 0);
    let mut board = Board::new(4, 3);
    board.set_tile(keep_hex, Tile {
        terrain_id: "keep".to_string(), movement_cost: 1, defense: 40, healing: 0,
        color: "#c8a030".to_string(),
    });
    board.set_tile(castle_hex, Tile {
        terrain_id: "castle".to_string(), movement_cost: 1, defense: 40, healing: 0,
        color: "#c8b47a".to_string(),
    });
    let mut state = GameState::new(board);
    // Place a leader (with "leader" ability) on the keep so recruitment is allowed
    let mut leader = Unit::new(99, "leader", 30, 0);
    leader.abilities = vec!["leader".to_string()];
    state.place_unit(leader, keep_hex);
    (state, keep_hex, castle_hex)
}

#[test]
fn test_recruit_deducts_gold() {
    use norrust_core::unit::Unit;
    let (mut state, _keep, castle_hex) = setup_recruit_board();
    state.gold = [50, 50];

    let unit = Unit::new(1, "spearman", 33, 0);
    apply_recruit(&mut state, unit, castle_hex, 14).expect("recruit must succeed");

    assert_eq!(state.gold[0], 36, "gold should be 50 - 14 = 36");
    assert!(state.units.contains_key(&1), "unit must be placed on the board");
}

#[test]
fn test_recruit_fails_not_enough_gold() {
    use norrust_core::unit::Unit;
    let (mut state, _keep, castle_hex) = setup_recruit_board();
    state.gold = [0, 0];

    let result = apply_recruit(&mut state, Unit::new(1, "spearman", 33, 0), castle_hex, 14);

    assert_eq!(result, Err(ActionError::NotEnoughGold));
    // Unit 99 (leader) is placed; recruited unit must not be
    assert!(!state.units.contains_key(&1), "recruit unit must not be placed on failure");
}

#[test]
fn test_recruit_fails_not_castle_hex() {
    use norrust_core::unit::Unit;
    // Leader on keep; destination is flat — must fail with DestinationNotCastle
    let (mut state, _keep, _castle) = setup_recruit_board();
    state.board.set_terrain(Hex::from_offset(2, 0), "flat");
    state.gold = [100, 100];

    let result = apply_recruit(&mut state, Unit::new(1, "spearman", 33, 0), Hex::from_offset(2, 0), 14);
    assert_eq!(result, Err(ActionError::DestinationNotCastle));
}

#[test]
fn test_recruit_fails_leader_not_on_keep() {
    use norrust_core::board::Tile;
    use norrust_core::unit::Unit;
    // Castle hex present but no leader on a keep → LeaderNotOnKeep
    let mut board = Board::new(4, 3);
    let castle_hex = Hex::from_offset(0, 0);
    board.set_tile(castle_hex, Tile {
        terrain_id: "castle".to_string(), movement_cost: 1, defense: 40, healing: 0,
        color: "#c8b47a".to_string(),
    });
    let mut state = GameState::new(board);
    state.gold = [100, 100];

    let result = apply_recruit(&mut state, Unit::new(1, "spearman", 33, 0), castle_hex, 14);
    assert_eq!(result, Err(ActionError::LeaderNotOnKeep));
}

#[test]
fn test_recruit_fails_non_leader_on_keep() {
    use norrust_core::board::Tile;
    use norrust_core::unit::Unit;
    // A regular unit (no "leader" ability) on a keep must NOT allow recruitment.
    let keep_hex = Hex::from_offset(0, 0);
    let castle_hex = Hex::from_offset(1, 0);
    let mut board = Board::new(4, 3);
    board.set_tile(keep_hex, Tile {
        terrain_id: "keep".to_string(), movement_cost: 1, defense: 40, healing: 0,
        color: "#c8a030".to_string(),
    });
    board.set_tile(castle_hex, Tile {
        terrain_id: "castle".to_string(), movement_cost: 1, defense: 40, healing: 0,
        color: "#c8b47a".to_string(),
    });
    let mut state = GameState::new(board);
    state.gold = [100, 100];
    // Non-leader unit on keep — abilities is empty
    state.place_unit(Unit::new(99, "grunt", 30, 0), keep_hex);

    let result = apply_recruit(&mut state, Unit::new(1, "spearman", 33, 0), castle_hex, 14);
    assert_eq!(result, Err(ActionError::LeaderNotOnKeep));
}

#[test]
fn test_objective_hex_win() {
    // A faction 0 unit reaching the objective hex should trigger a win.
    let board = Board::new(5, 1);
    let mut state = GameState::new(board);
    state.objective_hex = Some(Hex::from_offset(4, 0));

    state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::from_offset(0, 0));
    state.place_unit(Unit::new(2, "enemy", 30, 1), Hex::from_offset(4, 0));

    // Defender on objective does NOT trigger a win
    assert_eq!(state.check_winner(), None, "defender on objective must not win");

    // Move attacker to objective hex
    state.positions.insert(1, Hex::from_offset(4, 0));
    state.positions.insert(2, Hex::from_offset(3, 0)); // move defender off

    // Faction 0 should win
    assert_eq!(state.check_winner(), Some(0), "faction 0 unit on objective hex must win");
}

#[test]
fn test_turn_limit_loss() {
    // Exceeding max_turns should give victory to the defender (faction 1).
    let board = Board::new(5, 1);
    let mut state = GameState::new(board);
    state.max_turns = Some(2);

    state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::from_offset(0, 0));
    state.place_unit(Unit::new(2, "enemy", 30, 1), Hex::from_offset(4, 0));

    // Turn 1 — within limit
    assert_eq!(state.check_winner(), None);

    // Turn 2 — still within limit
    state.turn = 2;
    assert_eq!(state.check_winner(), None);

    // Turn 3 — exceeds max_turns=2, defender wins
    state.turn = 3;
    assert_eq!(state.check_winner(), Some(1), "defender must win when turn > max_turns");
}

#[test]
fn test_trigger_zone_spawns_units() {
    // Moving a faction-0 unit into a trigger hex should spawn the designated enemies.
    let board = Board::new(5, 5);
    let mut state = GameState::new(board);

    // Faction 0 mover at (0,0)
    let mut mover = Unit::new(1, "fighter", 30, 0);
    mover.movement = 5;
    state.place_unit(mover, Hex::from_offset(0, 0));

    // Faction 1 unit elsewhere (so game doesn't end by elimination)
    state.place_unit(Unit::new(2, "enemy", 30, 1), Hex::from_offset(4, 4));

    // Set up trigger zone at (1,0) that spawns two enemy units
    let spawn_a = PendingSpawn {
        unit: Unit::new(10, "ambusher_a", 25, 1),
        destination: Hex::from_offset(1, 1),
    };
    let spawn_b = PendingSpawn {
        unit: Unit::new(11, "ambusher_b", 25, 1),
        destination: Hex::from_offset(2, 0),
    };
    state.trigger_zones.push(TriggerZone {
        trigger_hex: Hex::from_offset(1, 0),
        trigger_faction: 0,
        spawns: vec![spawn_a, spawn_b],
        triggered: false,
    });

    // Move into trigger hex
    apply_action(&mut state, Action::Move { unit_id: 1, destination: Hex::from_offset(1, 0) })
        .expect("move into trigger hex should succeed");

    // Verify spawns
    assert!(state.units.contains_key(&10), "ambusher_a must be spawned");
    assert!(state.units.contains_key(&11), "ambusher_b must be spawned");
    assert_eq!(state.positions[&10], Hex::from_offset(1, 1));
    assert_eq!(state.positions[&11], Hex::from_offset(2, 0));
    assert!(state.trigger_zones[0].triggered, "trigger zone must be marked triggered");
}

#[test]
fn test_trigger_fires_only_once() {
    // A triggered zone must not spawn units again when re-entered.
    let board = Board::new(5, 5);
    let mut state = GameState::new(board);

    let mut mover = Unit::new(1, "fighter", 30, 0);
    mover.movement = 5;
    state.place_unit(mover, Hex::from_offset(0, 0));
    state.place_unit(Unit::new(2, "enemy", 30, 1), Hex::from_offset(4, 4));

    state.trigger_zones.push(TriggerZone {
        trigger_hex: Hex::from_offset(1, 0),
        trigger_faction: 0,
        spawns: vec![PendingSpawn {
            unit: Unit::new(10, "ambusher", 25, 1),
            destination: Hex::from_offset(2, 1),
        }],
        triggered: false,
    });

    // First entry — triggers spawn
    apply_action(&mut state, Action::Move { unit_id: 1, destination: Hex::from_offset(1, 0) })
        .expect("first move should succeed");
    assert!(state.units.contains_key(&10), "ambusher must be spawned on first entry");
    let unit_count_after_first = state.units.len();

    // End turns to reset moved flag, then move away and back
    apply_action(&mut state, Action::EndTurn).unwrap();
    apply_action(&mut state, Action::EndTurn).unwrap();
    apply_action(&mut state, Action::Move { unit_id: 1, destination: Hex::from_offset(0, 0) })
        .expect("move away should succeed");
    apply_action(&mut state, Action::EndTurn).unwrap();
    apply_action(&mut state, Action::EndTurn).unwrap();

    // Second entry — must NOT spawn again
    apply_action(&mut state, Action::Move { unit_id: 1, destination: Hex::from_offset(1, 0) })
        .expect("second move should succeed");
    assert_eq!(state.units.len(), unit_count_after_first, "no new units on re-entry");
}

#[test]
fn test_trigger_skips_occupied_hex() {
    // If a spawn destination is already occupied, that spawn is silently skipped.
    let board = Board::new(5, 5);
    let mut state = GameState::new(board);

    let mut mover = Unit::new(1, "fighter", 30, 0);
    mover.movement = 5;
    state.place_unit(mover, Hex::from_offset(0, 0));

    // Place a unit on the spawn destination to block it
    state.place_unit(Unit::new(2, "blocker", 30, 1), Hex::from_offset(1, 1));

    state.trigger_zones.push(TriggerZone {
        trigger_hex: Hex::from_offset(1, 0),
        trigger_faction: 0,
        spawns: vec![
            PendingSpawn {
                unit: Unit::new(10, "blocked_spawn", 25, 1),
                destination: Hex::from_offset(1, 1), // occupied by blocker
            },
            PendingSpawn {
                unit: Unit::new(11, "free_spawn", 25, 1),
                destination: Hex::from_offset(2, 0), // unoccupied
            },
        ],
        triggered: false,
    });

    apply_action(&mut state, Action::Move { unit_id: 1, destination: Hex::from_offset(1, 0) })
        .expect("move should succeed");

    assert!(!state.units.contains_key(&10), "blocked spawn must be skipped");
    assert!(state.units.contains_key(&11), "free spawn must be placed");
    assert!(state.trigger_zones[0].triggered, "zone must still be marked triggered");
}

#[test]
fn test_trigger_faction_filter() {
    // A trigger zone with trigger_faction=0 must NOT fire when faction 1 moves into it.
    let board = Board::new(5, 5);
    let mut state = GameState::new(board);

    // Faction 0 unit elsewhere
    state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::from_offset(4, 4));

    // Faction 1 mover
    let mut mover = Unit::new(2, "enemy_scout", 30, 1);
    mover.movement = 5;
    state.place_unit(mover, Hex::from_offset(0, 0));
    state.active_faction = 1; // faction 1's turn

    state.trigger_zones.push(TriggerZone {
        trigger_hex: Hex::from_offset(1, 0),
        trigger_faction: 0, // only fires for faction 0
        spawns: vec![PendingSpawn {
            unit: Unit::new(10, "ambusher", 25, 1),
            destination: Hex::from_offset(2, 0),
        }],
        triggered: false,
    });

    apply_action(&mut state, Action::Move { unit_id: 2, destination: Hex::from_offset(1, 0) })
        .expect("faction 1 move should succeed");

    assert!(!state.units.contains_key(&10), "trigger must NOT fire for wrong faction");
    assert!(!state.trigger_zones[0].triggered, "zone must remain untriggered");
}

#[test]
fn test_elimination_still_works() {
    // With no objective_hex or max_turns, elimination win condition should work as before.
    let board = Board::new(5, 1);
    let mut state = GameState::new(board);

    // No objective or turn limit
    assert!(state.objective_hex.is_none());
    assert!(state.max_turns.is_none());

    state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::from_offset(0, 0));
    state.place_unit(Unit::new(2, "enemy", 30, 1), Hex::from_offset(4, 0));

    // Both factions alive — no winner
    assert_eq!(state.check_winner(), None);

    // Remove faction 1 unit — faction 0 wins by elimination
    state.units.remove(&2);
    state.positions.remove(&2);
    assert_eq!(state.check_winner(), Some(0), "faction 0 wins by elimination");
}
