//! Core game state — units, board, turn tracking, and action application.

use std::collections::HashMap;

use crate::board::Board;
use crate::combat::{resolve_attack, time_of_day, tod_damage_modifier, Rng};
use crate::hex::Hex;
use crate::pathfinding::{find_path, get_zoc_hexes};
use crate::unit::Unit;

/// Errors returned by `apply_action` and `apply_recruit` when an action is invalid.
#[derive(Debug, PartialEq, Eq)]
pub enum ActionError {
    UnitNotFound(u32),
    NotYourTurn,
    DestinationOutOfBounds,
    DestinationOccupied,
    UnitAlreadyMoved,
    DestinationUnreachable,
    NotAdjacent,
    NotEnoughGold,
    DestinationNotCastle,
    LeaderNotOnKeep,
}

/// A unit waiting to be spawned when a trigger zone fires.
#[derive(Debug, Clone)]
pub struct PendingSpawn {
    pub unit: Unit,
    pub destination: Hex,
}

/// A hex that spawns enemies when a unit of the designated faction enters it.
#[derive(Debug, Clone)]
pub struct TriggerZone {
    pub trigger_hex: Hex,
    pub trigger_faction: u8,
    pub spawns: Vec<PendingSpawn>,
    pub triggered: bool,
}

/// Discrete state changes that may be applied to a `GameState`.
#[derive(Debug, Clone)]
pub enum Action {
    Move { unit_id: u32, destination: Hex },
    Attack { attacker_id: u32, defender_id: u32 },
    EndTurn,
}

/// Complete snapshot of a game in progress.
#[derive(Debug, Clone)]
pub struct GameState {
    pub board: Board,
    pub units: HashMap<u32, Unit>,
    pub positions: HashMap<u32, Hex>,
    pub turn: u32,
    pub active_faction: u8,
    pub rng: Rng,
    /// Maps village hexes (healing > 0) to the owning faction (-1 = unowned stored as i8::MAX).
    pub village_owners: HashMap<Hex, i8>,
    /// Gold per faction: [faction_0_gold, faction_1_gold]. Starting value 10 each.
    pub gold: [u32; 2],
    /// Objective hex — if a unit reaches this hex, that unit's faction wins.
    pub objective_hex: Option<Hex>,
    /// Maximum number of turns. If exceeded, defender (faction 1) wins by timeout.
    pub max_turns: Option<u32>,
    /// Trigger zones — spawn enemies when a unit of the designated faction enters.
    pub trigger_zones: Vec<TriggerZone>,
    /// Next available unit ID for auto-assigned units (trigger spawns, etc.).
    pub next_unit_id: u32,
}

impl GameState {
    /// Create a new game state with the given board and a random RNG seed.
    pub fn new(board: Board) -> Self {
        Self {
            board,
            units: HashMap::new(),
            positions: HashMap::new(),
            turn: 1,
            active_faction: 0,
            rng: Rng::new(12345),
            village_owners: HashMap::new(),
            gold: [10, 10],
            objective_hex: None,
            max_turns: None,
            trigger_zones: Vec::new(),
            next_unit_id: 1,
        }
    }

    /// Create a `GameState` with a specific RNG seed (for reproducible tests).
    pub fn new_seeded(board: Board, rng_seed: u64) -> Self {
        let mut s = Self::new(board);
        s.rng = Rng::new(rng_seed);
        s
    }

    /// Check for a winner. Returns Some(faction) if someone has won, None otherwise.
    ///
    /// Priority: 1) objective hex reached, 2) turn limit exceeded, 3) elimination.
    pub fn check_winner(&self) -> Option<u8> {
        // 1. Objective hex: attacker (faction 0) wins by reaching it.
        //    Defender units already on the objective don't count.
        if let Some(obj) = self.objective_hex {
            for (&uid, &hex) in &self.positions {
                if hex == obj {
                    if let Some(unit) = self.units.get(&uid) {
                        if unit.faction == 0 {
                            return Some(0);
                        }
                    }
                }
            }
        }

        // 2. Turn limit: defender (faction 1) wins by timeout
        if let Some(max) = self.max_turns {
            if self.turn > max {
                return Some(1);
            }
        }

        // 3. Elimination: if one side has no units, the other wins
        let has_0 = self.units.values().any(|u| u.faction == 0);
        let has_1 = self.units.values().any(|u| u.faction == 1);
        match (has_0, has_1) {
            (true, false) => Some(0),
            (false, true) => Some(1),
            _ => None,
        }
    }

    /// Place a unit on the board at `hex`.
    ///
    /// Panics if the hex is out of bounds or already occupied.
    pub fn place_unit(&mut self, unit: Unit, hex: Hex) {
        assert!(self.board.contains(hex), "place_unit: hex out of bounds");
        assert!(
            !self.positions.values().any(|&h| h == hex),
            "place_unit: hex already occupied"
        );
        let id = unit.id;
        self.positions.insert(id, hex);
        self.units.insert(id, unit);
    }
}

/// Validate and apply `action` to `state`, mutating it in place.
///
/// Returns `Ok(())` on success or an `ActionError` describing why the
/// action was rejected. State is unchanged on error.
pub fn apply_action(state: &mut GameState, action: Action) -> Result<(), ActionError> {
    match action {
        Action::Move { unit_id, destination } => {
            let unit = state
                .units
                .get(&unit_id)
                .ok_or(ActionError::UnitNotFound(unit_id))?;

            if unit.faction != state.active_faction {
                return Err(ActionError::NotYourTurn);
            }
            if unit.moved {
                return Err(ActionError::UnitAlreadyMoved);
            }
            if !state.board.contains(destination) {
                return Err(ActionError::DestinationOutOfBounds);
            }
            if state.positions.values().any(|&h| h == destination) {
                return Err(ActionError::DestinationOccupied);
            }

            // Pathfinding validation — only when unit has a movement budget
            let movement = state.units[&unit_id].movement;
            if movement > 0 {
                let zoc = get_zoc_hexes(state, state.units[&unit_id].faction);
                let costs = state.units[&unit_id].movement_costs.clone();
                let start = state.positions[&unit_id];
                let reachable = find_path(
                    &state.board,
                    &costs,
                    1,
                    start,
                    destination,
                    movement,
                    &zoc,
                    false,
                );
                if reachable.is_none() {
                    return Err(ActionError::DestinationUnreachable);
                }
            }

            state.positions.insert(unit_id, destination);
            state.units.get_mut(&unit_id).unwrap().moved = true;

            // Check trigger zones: spawn enemies if a matching zone is entered
            let mover_faction = state.active_faction;
            let mut spawns_to_place: Vec<PendingSpawn> = Vec::new();
            for tz in &mut state.trigger_zones {
                if !tz.triggered && tz.trigger_hex == destination && tz.trigger_faction == mover_faction {
                    tz.triggered = true;
                    spawns_to_place.extend(tz.spawns.drain(..));
                }
            }
            for spawn in spawns_to_place {
                if state.board.contains(spawn.destination)
                    && !state.positions.values().any(|&h| h == spawn.destination)
                {
                    state.place_unit(spawn.unit, spawn.destination);
                }
            }

            Ok(())
        }

        Action::Attack { attacker_id, defender_id } => {
            // Validate attacker belongs to the active faction
            {
                let attacker = state
                    .units
                    .get(&attacker_id)
                    .ok_or(ActionError::UnitNotFound(attacker_id))?;
                if attacker.faction != state.active_faction {
                    return Err(ActionError::NotYourTurn);
                }
                if attacker.attacked {
                    return Err(ActionError::UnitAlreadyMoved);
                }
            }

            let attacker_pos = state.positions[&attacker_id];

            // Defender must exist — position needed to determine engagement range
            let defender_pos = state
                .positions
                .get(&defender_id)
                .copied()
                .ok_or(ActionError::UnitNotFound(defender_id))?;

            // Select attack matching the engagement distance (melee=1, ranged=2)
            let dist = attacker_pos.distance(defender_pos);
            let range_needed = match dist {
                1 => "melee",
                2 => "ranged",
                _ => return Err(ActionError::NotAdjacent),
            };

            let attack = {
                let unit = state.units.get(&attacker_id).unwrap();
                if unit.attacks.is_empty() {
                    state.units.get_mut(&attacker_id).unwrap().attacked = true;
                    return Ok(());
                }
                unit.attacks.iter()
                    .find(|a| a.range == range_needed)
                    .cloned()
                    .ok_or(ActionError::NotAdjacent)?
            };

            // Determine defender terrain defense
            let terrain_defense = {
                let defender = state
                    .units
                    .get(&defender_id)
                    .ok_or(ActionError::UnitNotFound(defender_id))?;
                let terrain_id = state.board.terrain_at(defender_pos).unwrap_or("");
                defender.defense.get(terrain_id).copied()
                    .unwrap_or_else(|| {
                        state.board.tile_at(defender_pos)
                            .map(|t| t.defense)
                            .unwrap_or(defender.default_defense)
                    })
            };

            // Time of Day modifier from attacker's alignment
            let tod_mod = {
                let attacker = state.units.get(&attacker_id).unwrap();
                tod_damage_modifier(attacker.alignment, time_of_day(state.turn))
            };

            // Resistance modifier: defender's resistance to the attacker's attack type
            let resistance = {
                let defender = state.units.get(&defender_id).unwrap();
                defender.resistances.get(&attack.attack_type).copied().unwrap_or(0)
            };
            let effective_damage =
                ((attack.damage as i64 * (100 + resistance as i64)) / 100).max(0) as u32;

            // Resolve — requires mutable borrow of rng only
            let damage =
                resolve_attack(&mut state.rng, effective_damage, attack.strikes, terrain_defense, tod_mod);

            // Apply damage and mark attacker as having attacked
            state.units.get_mut(&attacker_id).unwrap().attacked = true;
            let defender_hp = {
                let def = state.units.get_mut(&defender_id).unwrap();
                def.hp = def.hp.saturating_sub(damage);
                def.hp
            };

            // Purge dead defender
            if defender_hp == 0 {
                state.units.remove(&defender_id);
                state.positions.remove(&defender_id);
            }

            // XP grant: attacker earns 1 for a hit, +8 bonus for a kill.
            if state.units.contains_key(&attacker_id) {
                let xp_earned = if damage > 0 { 1 } else { 0 }
                    + if defender_hp == 0 { 8 } else { 0 };
                if xp_earned > 0 {
                    let a = state.units.get_mut(&attacker_id).unwrap();
                    a.xp += xp_earned;
                    if a.xp_needed > 0 && a.xp >= a.xp_needed {
                        a.advancement_pending = true;
                    }
                }
            }

            // Retaliation: defender strikes back if still alive and has attacks
            if state.units.contains_key(&defender_id) {
                let ret_attack = state.units.get(&defender_id)
                    .and_then(|d| d.attacks.iter().find(|a| a.range == range_needed))
                    .cloned();

                if let Some(def_attack) = ret_attack {
                    let ret_defense = {
                        let a = state.units.get(&attacker_id).unwrap();
                        let terrain_id = state.board.terrain_at(attacker_pos).unwrap_or("");
                        a.defense.get(terrain_id).copied()
                            .unwrap_or_else(|| {
                                state.board.tile_at(attacker_pos)
                                    .map(|t| t.defense)
                                    .unwrap_or(a.default_defense)
                            })
                    };
                    let ret_tod = {
                        let d = state.units.get(&defender_id).unwrap();
                        tod_damage_modifier(d.alignment, time_of_day(state.turn))
                    };
                    let ret_resistance = {
                        let a = state.units.get(&attacker_id).unwrap();
                        a.resistances.get(&def_attack.attack_type).copied().unwrap_or(0)
                    };
                    let ret_effective_damage =
                        ((def_attack.damage as i64 * (100 + ret_resistance as i64)) / 100).max(0) as u32;
                    let ret_damage = resolve_attack(
                        &mut state.rng,
                        ret_effective_damage,
                        def_attack.strikes,
                        ret_defense,
                        ret_tod,
                    );
                    state.units.get_mut(&defender_id).unwrap().attacked = true;
                    let attacker_killed = if state.units.contains_key(&attacker_id) {
                        let attacker_hp = {
                            let a = state.units.get_mut(&attacker_id).unwrap();
                            a.hp = a.hp.saturating_sub(ret_damage);
                            a.hp
                        };
                        if attacker_hp == 0 {
                            state.units.remove(&attacker_id);
                            state.positions.remove(&attacker_id);
                        }
                        attacker_hp == 0
                    } else {
                        false
                    };

                    // XP grant: defender earns 1 for a retaliation hit, +8 if they killed the attacker.
                    if state.units.contains_key(&defender_id) {
                        let def_xp = if ret_damage > 0 { 1 } else { 0 }
                            + if attacker_killed { 8 } else { 0 };
                        if def_xp > 0 {
                            let d = state.units.get_mut(&defender_id).unwrap();
                            d.xp += def_xp;
                            if d.xp_needed > 0 && d.xp >= d.xp_needed {
                                d.advancement_pending = true;
                            }
                        }
                    }
                }
            }

            Ok(())
        }

        Action::EndTurn => {
            // Capture villages where the ending faction's units are standing.
            let ending_faction = state.active_faction as i8;
            let captures: Vec<Hex> = state.units.iter()
                .filter(|(_, u)| u.faction == state.active_faction)
                .filter_map(|(id, _)| state.positions.get(id).copied())
                .filter(|&hex| state.board.tile_at(hex).map(|t| t.healing > 0).unwrap_or(false))
                .collect();
            for hex in captures {
                state.village_owners.insert(hex, ending_faction);
            }

            state.active_faction = 1 - state.active_faction;
            if state.active_faction == 0 {
                state.turn += 1;
            }

            // Village income: newly-active faction earns 2 gold per owned village
            let active_i8 = state.active_faction as i8;
            let income = state.village_owners.values()
                .filter(|&&owner| owner == active_i8)
                .count() as u32 * 2;
            state.gold[state.active_faction as usize] += income;

            for unit in state.units.values_mut() {
                unit.moved = false;
                unit.attacked = false;
            }

            // Heal units of the newly-active faction based on their terrain.
            let active = state.active_faction;
            let to_heal: Vec<u32> = state.units.iter()
                .filter(|(_, u)| u.faction == active)
                .map(|(id, _)| *id)
                .collect();
            for uid in to_heal {
                if let Some(&hex) = state.positions.get(&uid) {
                    let healing = state.board.tile_at(hex).map(|t| t.healing).unwrap_or(0);
                    if healing > 0 {
                        let unit = state.units.get_mut(&uid).unwrap();
                        unit.hp = (unit.hp + healing).min(unit.max_hp);
                    }
                }
            }

            Ok(())
        }
    }
}

/// Recruit a unit onto a castle hex, deducting its gold cost from the active faction.
///
/// Validates: destination in bounds, is a castle hex, is unoccupied, faction has enough gold.
/// On success: deducts `cost` from `state.gold[unit.faction as usize]` and places the unit.
pub fn apply_recruit(
    state: &mut GameState,
    unit: Unit,
    destination: Hex,
    cost: u32,
) -> Result<(), ActionError> {
    if !state.board.contains(destination) {
        return Err(ActionError::DestinationOutOfBounds);
    }
    // The active faction's leader (unit with "leader" ability) must be on a keep tile.
    let active = state.active_faction;
    let keep_hex = state.positions.iter().find_map(|(&uid, &hex)| {
        let unit = state.units.get(&uid)?;
        if unit.faction != active { return None; }
        if !unit.abilities.iter().any(|a| a == "leader") { return None; }
        state.board.tile_at(hex).filter(|t| t.terrain_id == "keep").map(|_| hex)
    });
    let keep_hex = keep_hex.ok_or(ActionError::LeaderNotOnKeep)?;
    // Destination must be a castle tile adjacent to the keep.
    match state.board.tile_at(destination) {
        Some(tile) if tile.terrain_id == "castle" => {}
        _ => return Err(ActionError::DestinationNotCastle),
    }
    if keep_hex.distance(destination) != 1 {
        return Err(ActionError::DestinationNotCastle);
    }
    if state.positions.values().any(|&h| h == destination) {
        return Err(ActionError::DestinationOccupied);
    }
    let faction = unit.faction as usize;
    if state.gold[faction] < cost {
        return Err(ActionError::NotEnoughGold);
    }
    state.gold[faction] -= cost;
    state.place_unit(unit, destination);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::AttackDef;

    #[test]
    fn test_gamestate_unit_placement() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);
        let unit = Unit::new(1, "fighter", 30, 0);
        let origin = Hex::ORIGIN;
        state.place_unit(unit, origin);
        assert!(state.units.contains_key(&1));
        assert_eq!(state.positions[&1], origin);
    }

    #[test]
    fn test_valid_move_updates_position() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);
        state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::ORIGIN);
        let dest = Hex::from_offset(1, 0);
        let result = apply_action(&mut state, Action::Move { unit_id: 1, destination: dest });
        assert_eq!(result, Ok(()));
        assert_eq!(state.positions[&1], dest);
        assert!(state.units[&1].moved);
    }

    #[test]
    fn test_move_out_of_bounds_returns_error() {
        let board = Board::new(5, 5);
        let mut state = GameState::new(board);
        state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::ORIGIN);
        let out = Hex::from_offset(5, 0);
        let result = apply_action(&mut state, Action::Move { unit_id: 1, destination: out });
        assert_eq!(result, Err(ActionError::DestinationOutOfBounds));
        assert_eq!(state.positions[&1], Hex::ORIGIN);
    }

    #[test]
    fn test_end_turn_resets_flags_and_flips_faction() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);
        state.place_unit(Unit::new(1, "fighter", 30, 0), Hex::ORIGIN);
        apply_action(
            &mut state,
            Action::Move { unit_id: 1, destination: Hex::from_offset(1, 0) },
        )
        .unwrap();
        assert!(state.units[&1].moved);
        apply_action(&mut state, Action::EndTurn).unwrap();
        assert_eq!(state.active_faction, 1);
        assert!(!state.units[&1].moved);
    }

    #[test]
    fn test_move_unreachable_returns_error() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);
        let mut unit = Unit::new(1, "fighter", 30, 0);
        unit.movement = 2; // budget = 2 steps
        state.place_unit(unit, Hex::ORIGIN);
        // 4 steps away — exceeds budget
        let far = Hex::from_offset(0, 4);
        let result = apply_action(&mut state, Action::Move { unit_id: 1, destination: far });
        assert_eq!(result, Err(ActionError::DestinationUnreachable));
        assert_eq!(state.positions[&1], Hex::ORIGIN); // position unchanged
    }

    #[test]
    fn test_attack_kills_defender() {
        let board = Board::new(10, 10);
        let mut state = GameState::new_seeded(board, 42);

        // Attacker: 100-damage, 1-strike melee attack
        let attack = AttackDef {
            id: "sword".to_string(),
            name: "Sword".to_string(),
            damage: 100,
            strikes: 1,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![attack];

        // Defender: 30 HP, default_defense = 0 (always hit), no terrain
        let mut defender = Unit::new(2, "archer", 30, 1);
        defender.default_defense = 0;

        state.place_unit(attacker, Hex::ORIGIN);
        state.place_unit(defender, Hex::from_offset(1, 0));

        let result =
            apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 });
        assert_eq!(result, Ok(()));
        assert!(!state.units.contains_key(&2), "defender must be removed after death");
        assert!(!state.positions.contains_key(&2), "defender position must be cleared");
    }

    #[test]
    fn test_attacker_gains_xp_on_hit() {
        let board = Board::new(10, 10);
        let mut state = GameState::new_seeded(board, 42);
        let attack = AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 1, strikes: 1,
            attack_type: "blade".to_string(), range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![attack];
        attacker.xp_needed = 40;
        let mut defender = Unit::new(2, "archer", 30, 1);
        defender.default_defense = 0; // always hit
        state.place_unit(attacker, Hex::ORIGIN);
        state.place_unit(defender, Hex::from_offset(1, 0));

        apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

        assert!(state.units[&1].xp >= 1, "attacker should gain at least 1 XP for a hit");
    }

    #[test]
    fn test_attacker_gains_kill_bonus_xp() {
        let board = Board::new(10, 10);
        let mut state = GameState::new_seeded(board, 42);
        let attack = AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 100, strikes: 1,
            attack_type: "blade".to_string(), range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![attack];
        attacker.xp_needed = 40;
        let mut defender = Unit::new(2, "archer", 5, 1);
        defender.default_defense = 0;
        state.place_unit(attacker, Hex::ORIGIN);
        state.place_unit(defender, Hex::from_offset(1, 0));

        apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

        assert!(!state.units.contains_key(&2), "defender must be dead");
        assert_eq!(state.units[&1].xp, 9, "1 hit XP + 8 kill bonus = 9");
    }

    #[test]
    fn test_advancement_pending_triggers_at_threshold() {
        let board = Board::new(10, 10);
        let mut state = GameState::new_seeded(board, 42);
        let attack = AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 100, strikes: 1,
            attack_type: "blade".to_string(), range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![attack];
        attacker.xp = 39;
        attacker.xp_needed = 40;
        let mut defender = Unit::new(2, "archer", 5, 1);
        defender.default_defense = 0;
        state.place_unit(attacker, Hex::ORIGIN);
        state.place_unit(defender, Hex::from_offset(1, 0));

        apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

        assert!(state.units[&1].xp >= 40, "xp should reach threshold");
        assert!(state.units[&1].advancement_pending, "advancement_pending must be set");
    }

    #[test]
    fn test_defender_gains_xp_from_retaliation() {
        let board = Board::new(10, 10);
        let mut state = GameState::new_seeded(board, 42);
        let attack = AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 1, strikes: 1,
            attack_type: "blade".to_string(), range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![attack];
        attacker.default_defense = 0;
        let ret_attack = AttackDef {
            id: "bow".to_string(), name: "Bow".to_string(),
            damage: 1, strikes: 1,
            attack_type: "pierce".to_string(), range: "melee".to_string(),
            ..Default::default()
        };
        let mut defender = Unit::new(2, "archer", 30, 1);
        defender.attacks = vec![ret_attack];
        defender.default_defense = 0;
        defender.xp_needed = 40;
        state.place_unit(attacker, Hex::ORIGIN);
        state.place_unit(defender, Hex::from_offset(1, 0));

        apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

        assert!(state.units[&2].xp >= 1, "defender should gain at least 1 XP for retaliation hit");
    }

    #[test]
    fn test_ranged_attacker_gets_no_retaliation_from_melee_only_defender() {
        // Archer (ranged) attacks Grunt (melee-only) from distance 2.
        // Grunt has no ranged weapon → no retaliation → attacker HP unchanged.
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);

        let bow = AttackDef {
            id: "bow".to_string(), name: "Bow".to_string(),
            damage: 5, strikes: 4,
            attack_type: "pierce".to_string(), range: "ranged".to_string(),
            ..Default::default()
        };
        let mut archer = Unit::new(1, "archer", 30, 0);
        archer.attacks = vec![bow];
        archer.default_defense = 0;

        let sword = AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 7, strikes: 3,
            attack_type: "blade".to_string(), range: "melee".to_string(),
            ..Default::default()
        };
        let mut grunt = Unit::new(2, "grunt", 30, 1);
        grunt.attacks = vec![sword];
        grunt.default_defense = 0;

        // Distance 2 — ranged engagement
        state.place_unit(archer, Hex::ORIGIN);
        state.place_unit(grunt, Hex::from_offset(2, 0));

        apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

        assert_eq!(state.units[&1].hp, 30, "archer should take no retaliation from melee-only defender at range");
    }

    #[test]
    fn test_end_turn_captures_village() {
        use crate::board::Tile;
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);

        // Place a village tile
        let village_hex = Hex::from_offset(2, 2);
        state.board.set_tile(village_hex, Tile {
            terrain_id: "village".to_string(),
            movement_cost: 1,
            defense: 40,
            healing: 8,
            color: "#8b7355".to_string(),
        });

        // Faction 0 unit standing on the village
        state.place_unit(Unit::new(1, "fighter", 30, 0), village_hex);

        // Before EndTurn: no owner
        assert!(state.village_owners.is_empty());

        apply_action(&mut state, Action::EndTurn).unwrap();

        // After EndTurn: faction 0 owns the village
        assert_eq!(state.village_owners.get(&village_hex).copied(), Some(0i8));
    }

    #[test]
    fn test_village_changes_owner_on_capture() {
        use crate::board::Tile;
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);

        let village_hex = Hex::from_offset(3, 1);
        state.board.set_tile(village_hex, Tile {
            terrain_id: "village".to_string(),
            movement_cost: 1,
            defense: 40,
            healing: 8,
            color: "#8b7355".to_string(),
        });

        // Faction 0 captures on turn 1
        state.place_unit(Unit::new(1, "fighter", 30, 0), village_hex);
        apply_action(&mut state, Action::EndTurn).unwrap();
        assert_eq!(state.village_owners.get(&village_hex).copied(), Some(0i8));

        // Faction 1 moves in and captures on their turn
        state.place_unit(Unit::new(2, "archer", 25, 1), Hex::from_offset(3, 2));
        // Move unit 1 away so faction 1 can capture
        state.positions.insert(1, Hex::from_offset(0, 0));
        state.positions.insert(2, village_hex);
        apply_action(&mut state, Action::EndTurn).unwrap();
        assert_eq!(state.village_owners.get(&village_hex).copied(), Some(1i8));
    }

    #[test]
    fn test_tile_defense_used_in_combat() {
        use crate::board::Tile;

        // --- Scenario A: Tile.defense used as fallback when unit has no terrain entry ---
        {
            let board = Board::new(10, 10);
            let mut state = GameState::new_seeded(board, 42);

            let attack = AttackDef {
                id: "sword".to_string(),
                name: "Sword".to_string(),
                damage: 10,
                strikes: 10,
                attack_type: "blade".to_string(),
                range: "melee".to_string(),
                ..Default::default()
            };
            let mut attacker = Unit::new(1, "fighter", 50, 0);
            attacker.attacks = vec![attack];
            attacker.default_defense = 0;

            // Defender has no terrain-specific entries; default_defense = 0 (would always be hit)
            let mut defender = Unit::new(2, "grunt", 50, 1);
            defender.default_defense = 0;
            // defense map is empty — Tile.defense should be used as fallback

            let defender_pos = Hex::from_offset(1, 0);
            state.place_unit(attacker, Hex::ORIGIN);
            state.place_unit(defender, defender_pos);

            // Place a tile at the defender's position with defense = 100 (never hit)
            state.board.set_tile(defender_pos, Tile {
                terrain_id: "hills".to_string(),
                movement_cost: 2,
                defense: 100,
                healing: 0,
                color: "#8b7355".to_string(),
            });

            apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

            // With tile.defense = 100, hit_pct = 0, so 0 damage every strike
            assert_eq!(
                state.units[&2].hp, 50,
                "Tile.defense=100 must block all damage when unit has no terrain entry"
            );
        }

        // --- Scenario B: Unit-specific defense entry beats Tile.defense ---
        {
            let board = Board::new(10, 10);
            let mut state = GameState::new_seeded(board, 42);

            let attack = AttackDef {
                id: "sword".to_string(),
                name: "Sword".to_string(),
                damage: 10,
                strikes: 10,
                attack_type: "blade".to_string(),
                range: "melee".to_string(),
                ..Default::default()
            };
            let mut attacker = Unit::new(1, "fighter", 50, 0);
            attacker.attacks = vec![attack];
            attacker.default_defense = 0;

            // Defender has hills = 0 in defense map (always hit on hills)
            let mut defender = Unit::new(2, "grunt", 50, 1);
            defender.default_defense = 0;
            defender.defense.insert("hills".to_string(), 0); // unit entry: 0% defense on hills

            let defender_pos = Hex::from_offset(1, 0);
            state.place_unit(attacker, Hex::ORIGIN);
            state.place_unit(defender, defender_pos);

            // Tile has defense = 100 — but unit-specific entry (0) should take priority
            state.board.set_tile(defender_pos, Tile {
                terrain_id: "hills".to_string(),
                movement_cost: 2,
                defense: 100,
                healing: 0,
                color: "#8b7355".to_string(),
            });

            apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 }).unwrap();

            // Unit's defense["hills"] = 0 overrides tile.defense = 100 — damage must land
            // Use get() in case all 10 strikes killed the defender
            let hp_after = state.units.get(&2).map(|u| u.hp).unwrap_or(0);
            assert!(
                hp_after < 50,
                "Unit-specific defense=0 on hills must override Tile.defense=100"
            );
        }
    }

    #[test]
    fn test_attack_not_adjacent_returns_error() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);

        let attack = AttackDef {
            id: "sword".to_string(),
            name: "Sword".to_string(),
            damage: 7,
            strikes: 3,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![attack];
        let defender = Unit::new(2, "archer", 30, 1);

        // Place units 2 hexes apart — not adjacent
        state.place_unit(attacker, Hex::ORIGIN);
        state.place_unit(defender, Hex::from_offset(2, 0));

        let result =
            apply_action(&mut state, Action::Attack { attacker_id: 1, defender_id: 2 });
        assert_eq!(result, Err(ActionError::NotAdjacent));
        // Neither unit should be modified
        assert_eq!(state.units[&2].hp, 30, "defender HP must be unchanged");
    }

    #[test]
    fn test_village_income_adds_gold() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);

        // Verify starting gold
        assert_eq!(state.gold, [10, 10]);

        // Give faction 0 ownership of one village directly
        let village_hex = Hex::from_offset(3, 3);
        state.village_owners.insert(village_hex, 0);

        // faction 0 ends turn → faction 1 becomes active → faction 1 gets income (0 villages = 0g)
        apply_action(&mut state, Action::EndTurn).unwrap();
        assert_eq!(state.active_faction, 1);
        assert_eq!(state.gold[1], 10, "faction 1 owns no villages, gold unchanged");

        // faction 1 ends turn → faction 0 becomes active → faction 0 gets income (1 village = 2g)
        apply_action(&mut state, Action::EndTurn).unwrap();
        assert_eq!(state.active_faction, 0);
        assert_eq!(state.gold[0], 12, "faction 0 owns 1 village: 10 + 2 = 12");
    }
}
