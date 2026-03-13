//! JSON-serializable game state snapshots for the FFI boundary.

use serde::{Deserialize, Serialize};

use crate::game_state::{Action, GameState};
use crate::hex::Hex;
use crate::visibility::compute_visibility;

/// Flat representation of a single hex tile's terrain.
#[derive(Debug, Serialize)]
pub struct TileSnapshot {
    pub col: i32,
    pub row: i32,
    pub terrain_id: String,
    pub color: String,
    /// Owning faction (0 or 1), or -1 if unowned / not a village.
    pub owner: i32,
    /// Base defense % for this terrain (e.g. 60 for forest).
    pub defense: u32,
    /// Base movement cost for this terrain (e.g. 2 for forest).
    pub movement_cost: u32,
    /// HP healed per turn on this terrain (0 for most, 8 for village).
    pub healing: u32,
}

/// Flat representation of a single attack in a unit's loadout.
#[derive(Debug, Serialize)]
pub struct AttackSnapshot {
    pub id:      String,
    pub name:    String,
    pub damage:  u32,
    pub strikes: u32,
    pub range:   String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub specials: Vec<String>,
}

/// Flat representation of a single runtime unit.
#[derive(Debug, Serialize)]
pub struct UnitSnapshot {
    pub id: u32,
    pub def_id: String,
    pub col: i32,
    pub row: i32,
    pub faction: u8,
    pub hp: u32,
    pub max_hp: u32,
    pub moved: bool,
    pub attacked: bool,
    pub xp: u32,
    pub xp_needed: u32,
    pub advancement_pending: bool,
    pub movement: u32,
    pub level: u8,
    pub attacks: Vec<AttackSnapshot>,
    pub abilities: Vec<String>,
    pub poisoned: bool,
    pub slowed: bool,
}

/// A visible hex position for fog-of-war snapshots.
#[derive(Debug, Serialize)]
pub struct VisibleHex {
    pub col: i32,
    pub row: i32,
}

/// Complete serializable snapshot of a GameState for external consumers.
///
/// Uses `cols`/`rows` terminology (matching the GDScript and bridge API)
/// even though `Board` stores them as `width`/`height` internally.
#[derive(Debug, Serialize)]
pub struct StateSnapshot {
    pub turn: u32,
    pub active_faction: u8,
    pub cols: u32,
    pub rows: u32,
    pub terrain: Vec<TileSnapshot>,
    pub units: Vec<UnitSnapshot>,
    pub gold: [u32; 2],
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_turns: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub objective_col: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub objective_row: Option<i32>,
    /// Visible hexes for fog-of-war queries (None for unfiltered snapshots).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub visible_hexes: Option<Vec<VisibleHex>>,
}

impl StateSnapshot {
    /// Build a snapshot from the current game state, capturing all units, terrain, gold, and win condition data.
    pub fn from_game_state(state: &GameState) -> Self {
        let cols = state.board.width;
        let rows = state.board.height;

        // Collect all hexes that have terrain set
        let terrain = (0..cols as i32)
            .flat_map(|col| (0..rows as i32).map(move |row| (col, row)))
            .filter_map(|(col, row)| {
                let hex = Hex::from_offset(col, row);
                state.board.tile_at(hex).map(|tile| TileSnapshot {
                    col,
                    row,
                    terrain_id: tile.terrain_id.clone(),
                    color: tile.color.clone(),
                    owner: state.village_owners.get(&hex).copied().map(|o| o as i32).unwrap_or(-1),
                    defense: tile.defense,
                    movement_cost: tile.movement_cost,
                    healing: tile.healing,
                })
            })
            .collect();

        // Collect all units with their positions
        let units = state
            .positions
            .iter()
            .filter_map(|(&uid, &hex)| {
                let unit = state.units.get(&uid)?;
                let (col, row) = hex.to_offset();
                Some(UnitSnapshot {
                    id: uid,
                    def_id: unit.def_id.clone(),
                    col,
                    row,
                    faction: unit.faction,
                    hp: unit.hp,
                    max_hp: unit.max_hp,
                    moved: unit.moved,
                    attacked: unit.attacked,
                    xp: unit.xp,
                    xp_needed: unit.xp_needed,
                    advancement_pending: unit.advancement_pending,
                    movement: unit.movement,
                    level: unit.level,
                    attacks: unit.attacks.iter().map(|a| AttackSnapshot {
                        id:      a.id.clone(),
                        name:    a.name.clone(),
                        damage:  a.damage,
                        strikes: a.strikes,
                        range:   a.range.clone(),
                        specials: a.specials.clone(),
                    }).collect(),
                    abilities: unit.abilities.clone(),
                    poisoned: unit.poisoned,
                    slowed: unit.slowed,
                })
            })
            .collect();

        let (objective_col, objective_row) = match state.objective_hex {
            Some(hex) => {
                let (c, r) = hex.to_offset();
                (Some(c), Some(r))
            }
            None => (None, None),
        };

        StateSnapshot {
            turn: state.turn,
            active_faction: state.active_faction,
            cols,
            rows,
            terrain,
            units,
            gold: state.gold,
            max_turns: state.max_turns,
            objective_col,
            objective_row,
            visible_hexes: None,
        }
    }

    /// Build a fog-of-war snapshot for `faction`: enemy units on non-visible hexes are hidden,
    /// and the visible hex set is included.
    pub fn from_game_state_fow(state: &GameState, faction: u8) -> Self {
        let visible = compute_visibility(state, faction);

        let cols = state.board.width;
        let rows = state.board.height;

        // Terrain is always fully visible
        let terrain = (0..cols as i32)
            .flat_map(|col| (0..rows as i32).map(move |row| (col, row)))
            .filter_map(|(col, row)| {
                let hex = Hex::from_offset(col, row);
                state.board.tile_at(hex).map(|tile| TileSnapshot {
                    col, row,
                    terrain_id: tile.terrain_id.clone(),
                    color: tile.color.clone(),
                    owner: state.village_owners.get(&hex).copied().map(|o| o as i32).unwrap_or(-1),
                    defense: tile.defense,
                    movement_cost: tile.movement_cost,
                    healing: tile.healing,
                })
            })
            .collect();

        // Units: include friendly always, enemy only if on visible hex
        let units = state.positions.iter()
            .filter_map(|(&uid, &hex)| {
                let unit = state.units.get(&uid)?;
                if unit.faction != faction && !visible.contains(&hex) {
                    return None; // hidden enemy
                }
                let (col, row) = hex.to_offset();
                Some(UnitSnapshot {
                    id: uid,
                    def_id: unit.def_id.clone(),
                    col, row,
                    faction: unit.faction,
                    hp: unit.hp, max_hp: unit.max_hp,
                    moved: unit.moved, attacked: unit.attacked,
                    xp: unit.xp, xp_needed: unit.xp_needed,
                    advancement_pending: unit.advancement_pending,
                    movement: unit.movement, level: unit.level,
                    attacks: unit.attacks.iter().map(|a| AttackSnapshot {
                        id: a.id.clone(), name: a.name.clone(),
                        damage: a.damage, strikes: a.strikes,
                        range: a.range.clone(), specials: a.specials.clone(),
                    }).collect(),
                    abilities: unit.abilities.clone(),
                    poisoned: unit.poisoned, slowed: unit.slowed,
                })
            })
            .collect();

        let (objective_col, objective_row) = match state.objective_hex {
            Some(hex) => { let (c, r) = hex.to_offset(); (Some(c), Some(r)) }
            None => (None, None),
        };

        let visible_hexes: Vec<VisibleHex> = visible.iter()
            .map(|h| { let (col, row) = h.to_offset(); VisibleHex { col, row } })
            .collect();

        StateSnapshot {
            turn: state.turn,
            active_faction: state.active_faction,
            cols, rows, terrain, units,
            gold: state.gold,
            max_turns: state.max_turns,
            objective_col, objective_row,
            visible_hexes: Some(visible_hexes),
        }
    }
}

/// JSON-deserializable action request for external clients (AI agents, socket relay, etc.).
///
/// Expected JSON formats:
///   `{"action":"Move","unit_id":1,"col":3,"row":2}`
///   `{"action":"Attack","attacker_id":1,"defender_id":2}`
///   `{"action":"EndTurn"}`
#[derive(Debug, Deserialize)]
#[serde(tag = "action")]
pub enum ActionRequest {
    Move { unit_id: u32, col: i32, row: i32 },
    Attack { attacker_id: u32, defender_id: u32 },
    EndTurn,
    Advance { unit_id: u32, #[serde(default)] target_index: u32 },
    Recruit { def_id: String, col: i32, row: i32 },
}

impl From<ActionRequest> for Action {
    fn from(req: ActionRequest) -> Self {
        match req {
            ActionRequest::Move { unit_id, col, row } => Action::Move {
                unit_id,
                destination: Hex::from_offset(col, row),
            },
            ActionRequest::Attack { attacker_id, defender_id } => {
                Action::Attack { attacker_id, defender_id }
            }
            ActionRequest::EndTurn => Action::EndTurn,
            ActionRequest::Advance { .. } => {
                unreachable!("Advance is handled by norrust_apply_advance() before into()")
            }
            ActionRequest::Recruit { .. } => {
                unreachable!("Recruit is handled by recruit_unit_at() before into()")
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::game_state::GameState;
    use crate::unit::Unit;

    #[test]
    fn test_state_snapshot_fields() {
        let board = Board::new(8, 5);
        let mut state = GameState::new(board);
        state.board.set_terrain(Hex::from_offset(0, 0), "flat");
        state.board.set_terrain(Hex::from_offset(1, 0), "forest");
        let unit = Unit::new(1, "fighter", 30, 0);
        state.place_unit(unit, Hex::from_offset(0, 0));

        let snap = StateSnapshot::from_game_state(&state);
        assert_eq!(snap.turn, 1);
        assert_eq!(snap.active_faction, 0);
        assert_eq!(snap.cols, 8);
        assert_eq!(snap.rows, 5);
        assert_eq!(snap.terrain.len(), 2);
        assert_eq!(snap.units.len(), 1);
        assert_eq!(snap.units[0].id, 1);
        assert_eq!(snap.units[0].hp, 30);
        assert!(!snap.units[0].moved);
        assert_eq!(snap.units[0].xp, 0);
        assert_eq!(snap.units[0].xp_needed, 0);
        assert!(!snap.units[0].advancement_pending);
    }

    #[test]
    fn test_snapshot_xp_fields_serialize() {
        let board = Board::new(4, 3);
        let mut state = GameState::new(board);
        let unit = Unit::new(1, "fighter", 30, 0);
        state.place_unit(unit, Hex::from_offset(0, 0));
        let snap = StateSnapshot::from_game_state(&state);
        let json = serde_json::to_string(&snap).expect("serialization must succeed");
        assert!(json.contains("\"xp\":0"));
        assert!(json.contains("\"xp_needed\":0"));
        assert!(json.contains("\"advancement_pending\":false"));
    }

    #[test]
    fn test_state_snapshot_serializes_to_json() {
        let board = Board::new(4, 3);
        let state = GameState::new(board);
        let snap = StateSnapshot::from_game_state(&state);
        let json = serde_json::to_string(&snap).expect("serialization must succeed");
        assert!(json.contains("\"turn\":1"));
        assert!(json.contains("\"active_faction\":0"));
        assert!(json.contains("\"cols\":4"));
        assert!(json.contains("\"rows\":3"));
    }

    #[test]
    fn test_action_request_end_turn() {
        let req: ActionRequest =
            serde_json::from_str(r#"{"action":"EndTurn"}"#).expect("parse must succeed");
        let action: Action = req.into();
        assert!(matches!(action, Action::EndTurn));
    }

    #[test]
    fn test_action_request_move() {
        let req: ActionRequest =
            serde_json::from_str(r#"{"action":"Move","unit_id":1,"col":3,"row":2}"#)
                .expect("parse must succeed");
        let action: Action = req.into();
        assert!(matches!(action, Action::Move { unit_id: 1, .. }));
    }

    #[test]
    fn test_action_request_attack() {
        let req: ActionRequest =
            serde_json::from_str(r#"{"action":"Attack","attacker_id":1,"defender_id":2}"#)
                .expect("parse must succeed");
        let action: Action = req.into();
        assert!(matches!(action, Action::Attack { attacker_id: 1, defender_id: 2 }));
    }

    #[test]
    fn test_unit_terrain_defense_fallback() {
        // Verify the defense fallback chain:
        // unit.defense[terrain_id] → tile.defense → unit.default_defense
        use crate::board::Tile;
        use std::collections::HashMap;

        let board = Board::new(4, 3);
        let mut state = GameState::new(board);

        // Forest tile with 60% default defense
        state.board.set_tile(Hex::from_offset(0, 0), Tile {
            terrain_id: "forest".to_string(),
            movement_cost: 2,
            defense: 60,
            healing: 0,
            color: "#2d5a27".to_string(),
        });

        // Unit with custom forest defense of 50%
        let mut unit = Unit::new(1, "swordsman", 55, 0);
        unit.defense = HashMap::from([("forest".to_string(), 50)]);
        unit.default_defense = 40;
        state.place_unit(unit, Hex::from_offset(0, 0));

        // Unit-specific defense should be 50 (from unit.defense["forest"])
        let unit = state.units.get(&1).unwrap();
        let tile = state.board.tile_at(Hex::from_offset(0, 0)).unwrap();
        let effective = unit.defense.get(&tile.terrain_id).copied()
            .unwrap_or(tile.defense);
        assert_eq!(effective, 50, "unit.defense[forest] = 50 should override tile.defense = 60");

        // On a terrain not in unit.defense map, falls back to tile.defense
        state.board.set_tile(Hex::from_offset(1, 0), Tile {
            terrain_id: "hills".to_string(),
            movement_cost: 2,
            defense: 50,
            healing: 0,
            color: "#8b7355".to_string(),
        });
        let tile_hills = state.board.tile_at(Hex::from_offset(1, 0)).unwrap();
        let unit = state.units.get(&1).unwrap();
        let effective_hills = unit.defense.get(&tile_hills.terrain_id).copied()
            .unwrap_or(tile_hills.defense);
        assert_eq!(effective_hills, 50, "no unit entry for hills → tile.defense = 50");
    }

    #[test]
    fn test_action_request_invalid_returns_error() {
        let result: Result<ActionRequest, _> = serde_json::from_str("not valid json");
        assert!(result.is_err());
    }

    #[test]
    fn test_tile_snapshot_owner_field() {
        use crate::board::Tile;
        use crate::game_state::Action;
        use crate::unit::Unit;

        let board = Board::new(4, 3);
        let mut state = GameState::new(board);

        let village_hex = Hex::from_offset(1, 1);
        state.board.set_tile(village_hex, Tile {
            terrain_id: "village".to_string(),
            movement_cost: 1,
            defense: 40,
            healing: 8,
            color: "#8b7355".to_string(),
        });
        state.place_unit(Unit::new(1, "fighter", 30, 0), village_hex);

        // Before capture: owner is -1
        let snap = StateSnapshot::from_game_state(&state);
        let village_tile = snap.terrain.iter().find(|t| t.terrain_id == "village").unwrap();
        assert_eq!(village_tile.owner, -1);

        // After EndTurn: faction 0 captures
        crate::game_state::apply_action(&mut state, Action::EndTurn).unwrap();
        let snap2 = StateSnapshot::from_game_state(&state);
        let village_tile2 = snap2.terrain.iter().find(|t| t.terrain_id == "village").unwrap();
        assert_eq!(village_tile2.owner, 0);

        // JSON must include the owner field
        let json = serde_json::to_string(&snap2).unwrap();
        assert!(json.contains("\"owner\":0"));
    }

    #[test]
    fn test_unit_snapshot_includes_movement_attacks_abilities() {
        use crate::schema::AttackDef;

        let board = Board::new(4, 3);
        let mut state = GameState::new(board);
        let mut unit = Unit::new(1, "Lieutenant", 40, 0);
        unit.movement = 6;
        unit.attacks = vec![AttackDef {
            id: "sword".to_string(), name: "sword".to_string(),
            damage: 8, strikes: 3,
            attack_type: "blade".to_string(), range: "melee".to_string(),
            ..Default::default()
        }];
        unit.abilities = vec!["leader".to_string(), "leadership".to_string()];
        state.place_unit(unit, Hex::from_offset(0, 0));

        let snap = StateSnapshot::from_game_state(&state);
        let u = &snap.units[0];
        assert_eq!(u.movement, 6);
        assert_eq!(u.attacks.len(), 1);
        assert_eq!(u.attacks[0].name, "sword");
        assert_eq!(u.attacks[0].damage, 8);
        assert_eq!(u.attacks[0].strikes, 3);
        assert_eq!(u.attacks[0].range, "melee");
        assert_eq!(u.abilities, vec!["leader", "leadership"]);

        let json = serde_json::to_string(&snap).expect("serialization must succeed");
        assert!(json.contains("\"movement\":6"), "movement must appear in JSON");
        assert!(json.contains("\"attacks\":["), "attacks array must appear in JSON");
        assert!(json.contains("\"abilities\":["), "abilities array must appear in JSON");
    }

    #[test]
    fn test_tile_snapshot_includes_terrain_stats() {
        use crate::board::Tile;

        let board = Board::new(4, 3);
        let mut state = GameState::new(board);
        let tile = Tile {
            terrain_id: "forest".to_string(),
            movement_cost: 2,
            defense: 60,
            healing: 0,
            color: "#2d5a27".to_string(),
        };
        state.board.set_tile(Hex::from_offset(1, 1), tile);

        let snap = StateSnapshot::from_game_state(&state);
        let forest = snap.terrain.iter().find(|t| t.terrain_id == "forest").unwrap();
        assert_eq!(forest.defense, 60);
        assert_eq!(forest.movement_cost, 2);
        assert_eq!(forest.healing, 0);

        let json = serde_json::to_string(&snap).expect("serialization must succeed");
        assert!(json.contains("\"defense\":60"), "defense must appear in JSON");
        assert!(json.contains("\"movement_cost\":2"), "movement_cost must appear in JSON");
    }

    #[test]
    fn test_tile_snapshot_includes_color() {
        use crate::board::Tile;

        let board = Board::new(4, 3);
        let mut state = GameState::new(board);
        let tile = Tile {
            terrain_id: "flat".to_string(),
            movement_cost: 1,
            defense: 60,
            healing: 0,
            color: "#4a7c4e".to_string(),
        };
        state.board.set_tile(Hex::from_offset(0, 0), tile);

        let snap = StateSnapshot::from_game_state(&state);
        assert_eq!(snap.terrain.len(), 1);
        assert_eq!(snap.terrain[0].terrain_id, "flat");
        assert_eq!(snap.terrain[0].color, "#4a7c4e");

        let json = serde_json::to_string(&snap).expect("serialization must succeed");
        assert!(json.contains("\"color\":\"#4a7c4e\""), "color must appear in JSON output");
    }

    #[test]
    fn test_fow_snapshot_hides_invisible_enemies() {
        let board = Board::new(10, 1);
        let mut state = GameState::new(board);
        for col in 0..10 {
            state.board.set_terrain(Hex::from_offset(col, 0), "flat");
        }

        // Faction 0 at col 0 with vision_range=2
        let mut u0 = Unit::new(1, "scout", 20, 0);
        u0.movement = 4;
        u0.vision_range = 2;
        state.place_unit(u0, Hex::from_offset(0, 0));

        // Faction 1 at col 9 — well beyond vision
        let mut u1 = Unit::new(2, "enemy", 20, 1);
        u1.movement = 4;
        state.place_unit(u1, Hex::from_offset(9, 0));

        // Filtered: faction 0 should NOT see enemy at col 9
        let fow = StateSnapshot::from_game_state_fow(&state, 0);
        assert_eq!(fow.units.len(), 1, "only friendly unit visible");
        assert_eq!(fow.units[0].faction, 0);
        assert!(fow.visible_hexes.is_some());

        // Unfiltered: both units present (regression check)
        let full = StateSnapshot::from_game_state(&state);
        assert_eq!(full.units.len(), 2);
        assert!(full.visible_hexes.is_none());
    }

    #[test]
    fn test_fow_snapshot_includes_visible_enemies() {
        let board = Board::new(5, 1);
        let mut state = GameState::new(board);
        for col in 0..5 {
            state.board.set_terrain(Hex::from_offset(col, 0), "flat");
        }

        // Faction 0 at col 0 with vision_range=3
        let mut u0 = Unit::new(1, "scout", 20, 0);
        u0.movement = 4;
        u0.vision_range = 3;
        state.place_unit(u0, Hex::from_offset(0, 0));

        // Faction 1 at col 2 — within vision range 3
        let mut u1 = Unit::new(2, "enemy", 20, 1);
        u1.movement = 4;
        state.place_unit(u1, Hex::from_offset(2, 0));

        let fow = StateSnapshot::from_game_state_fow(&state, 0);
        assert_eq!(fow.units.len(), 2, "both units should be visible");
    }
}
