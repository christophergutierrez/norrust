use serde::{Deserialize, Serialize};

use crate::game_state::{Action, GameState};
use crate::hex::Hex;

/// Flat representation of a single hex tile's terrain.
#[derive(Debug, Serialize)]
pub struct TileSnapshot {
    pub col: i32,
    pub row: i32,
    pub terrain_id: String,
    pub color: String,
    /// Owning faction (0 or 1), or -1 if unowned / not a village.
    pub owner: i32,
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
}

impl StateSnapshot {
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
                })
            })
            .collect();

        StateSnapshot { turn: state.turn, active_faction: state.active_faction, cols, rows, terrain, units, gold: state.gold }
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
    Advance { unit_id: u32 },
    Recruit { unit_id: u32, def_id: String, col: i32, row: i32 },
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
                unreachable!("Advance is handled by apply_advance() before into()")
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
}
