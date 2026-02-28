use std::collections::HashMap;

use crate::board::Board;
use crate::combat::{resolve_attack, time_of_day, tod_damage_modifier, Rng};
use crate::hex::Hex;
use crate::pathfinding::{find_path, get_zoc_hexes};
use crate::unit::Unit;

/// Errors returned by `apply_action` when an action is invalid.
#[derive(Debug, PartialEq, Eq)]
pub enum ActionError {
    UnitNotFound(u32),
    NotYourTurn,
    DestinationOutOfBounds,
    DestinationOccupied,
    UnitAlreadyMoved,
    DestinationUnreachable,
    NotAdjacent,
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
}

impl GameState {
    pub fn new(board: Board) -> Self {
        Self {
            board,
            units: HashMap::new(),
            positions: HashMap::new(),
            turn: 1,
            active_faction: 0,
            rng: Rng::new(12345),
        }
    }

    /// Create a `GameState` with a specific RNG seed (for reproducible tests).
    pub fn new_seeded(board: Board, rng_seed: u64) -> Self {
        let mut s = Self::new(board);
        s.rng = Rng::new(rng_seed);
        s
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

            // Capture attacker position for adjacency check (after validation block)
            let attacker_pos = state.positions[&attacker_id];

            // Clone the attack definition (if any) to drop the immutable borrow
            let attack = match state.units.get(&attacker_id).unwrap().attacks.first() {
                Some(a) => a.clone(),
                None => {
                    // No attacks defined — mark as attacked and succeed
                    state.units.get_mut(&attacker_id).unwrap().attacked = true;
                    return Ok(());
                }
            };

            // Defender must exist
            let defender_pos = state
                .positions
                .get(&defender_id)
                .copied()
                .ok_or(ActionError::UnitNotFound(defender_id))?;

            // Enforce melee adjacency
            if !attacker_pos.neighbors().contains(&defender_pos) {
                return Err(ActionError::NotAdjacent);
            }

            // Determine defender terrain defense
            let terrain_defense = {
                let defender = state
                    .units
                    .get(&defender_id)
                    .ok_or(ActionError::UnitNotFound(defender_id))?;
                let terrain_id = state.board.terrain_at(defender_pos).unwrap_or("");
                defender.defense.get(terrain_id).copied().unwrap_or(defender.default_defense)
            };

            // Time of Day modifier from attacker's alignment
            let tod_mod = {
                let attacker = state.units.get(&attacker_id).unwrap();
                tod_damage_modifier(attacker.alignment, time_of_day(state.turn))
            };

            // Resolve — requires mutable borrow of rng only
            let damage =
                resolve_attack(&mut state.rng, attack.damage, attack.strikes, terrain_defense, tod_mod);

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

            // Retaliation: defender strikes back if still alive and has attacks
            if state.units.contains_key(&defender_id) {
                let ret_attack = state.units.get(&defender_id)
                    .and_then(|d| d.attacks.first())
                    .cloned();

                if let Some(def_attack) = ret_attack {
                    let ret_defense = {
                        let a = state.units.get(&attacker_id).unwrap();
                        let terrain_id = state.board.terrain_at(attacker_pos).unwrap_or("");
                        a.defense.get(terrain_id).copied().unwrap_or(a.default_defense)
                    };
                    let ret_tod = {
                        let d = state.units.get(&defender_id).unwrap();
                        tod_damage_modifier(d.alignment, time_of_day(state.turn))
                    };
                    let ret_damage = resolve_attack(
                        &mut state.rng,
                        def_attack.damage,
                        def_attack.strikes,
                        ret_defense,
                        ret_tod,
                    );
                    state.units.get_mut(&defender_id).unwrap().attacked = true;
                    if state.units.contains_key(&attacker_id) {
                        let attacker_hp = {
                            let a = state.units.get_mut(&attacker_id).unwrap();
                            a.hp = a.hp.saturating_sub(ret_damage);
                            a.hp
                        };
                        if attacker_hp == 0 {
                            state.units.remove(&attacker_id);
                            state.positions.remove(&attacker_id);
                        }
                    }
                }
            }

            Ok(())
        }

        Action::EndTurn => {
            state.active_faction = 1 - state.active_faction;
            if state.active_faction == 0 {
                state.turn += 1;
            }
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
                    let healing = state.board
                        .terrain_at(hex)
                        .map(|t| state.board.healing_for(t))
                        .unwrap_or(0);
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
}
