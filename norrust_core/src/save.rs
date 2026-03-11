//! Save/load serialization — captures full engine state as a JSON-compatible struct.
//!
//! `SaveState` is the serialization boundary for game saves. It captures all
//! restorable state without requiring `Serialize`/`Deserialize` on internal types
//! like `GameState` or `Unit`. Units are reconstructed from the registry on load.

use serde::{Deserialize, Serialize};

use crate::campaign::CampaignState;
use crate::dialogue::DialogueState;
use crate::game_state::GameState;
use crate::hex::Hex;
use crate::unit::Unit;

/// Serializable snapshot of a single unit's runtime state.
///
/// Attacks, defense, resistances, and movement costs are NOT saved — they come
/// from the registry via `unit_from_registry()` on restore. This keeps saves
/// compact and forward-compatible (stat changes apply to existing saves).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SaveUnit {
    pub id: u32,
    pub def_id: String,
    pub faction: u8,
    pub col: i32,
    pub row: i32,
    pub hp: u32,
    pub max_hp: u32,
    pub xp: u32,
    pub xp_needed: u32,
    pub advancement_pending: bool,
    pub moved: bool,
    pub attacked: bool,
    pub poisoned: bool,
    pub slowed: bool,
    pub abilities: Vec<String>,
    pub level: u8,
}

impl SaveUnit {
    /// Capture a unit's runtime state along with its hex position.
    pub fn from_unit(unit: &Unit, hex: &Hex) -> Self {
        let (col, row) = hex.to_offset();
        Self {
            id: unit.id,
            def_id: unit.def_id.clone(),
            faction: unit.faction,
            col,
            row,
            hp: unit.hp,
            max_hp: unit.max_hp,
            xp: unit.xp,
            xp_needed: unit.xp_needed,
            advancement_pending: unit.advancement_pending,
            moved: unit.moved,
            attacked: unit.attacked,
            poisoned: unit.poisoned,
            slowed: unit.slowed,
            abilities: unit.abilities.clone(),
            level: unit.level,
        }
    }
}

/// Complete serializable save state for the engine.
///
/// Board terrain and trigger zone geometry are NOT stored — they come from
/// `board_path` on reload. Only mutable runtime state is captured.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SaveState {
    /// Path to board.toml (reloaded on restore to rebuild terrain + trigger zones).
    pub board_path: String,
    /// RNG state for combat reproducibility.
    pub rng_state: u64,
    /// Current turn number.
    pub turn: u32,
    /// Currently active faction (0 or 1).
    pub active_faction: u8,
    /// Gold per faction.
    pub gold: [u32; 2],
    /// Turn limit (None = unlimited).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_turns: Option<u32>,
    /// Objective hex as (col, row) if set.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub objective_hex: Option<(i32, i32)>,
    /// All units with their positions and runtime state.
    pub units: Vec<SaveUnit>,
    /// Next auto-assigned unit ID.
    pub next_unit_id: u32,
    /// Fired state per trigger zone (indexed by position in the zones vec).
    pub trigger_zones_fired: Vec<bool>,
    /// Village ownership: (col, row, owner_faction). Only villages with an owner.
    pub village_owners: Vec<(i32, i32, i8)>,
    /// Path to dialogue.toml (reloaded on restore).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub dialogue_path: Option<String>,
    /// IDs of dialogue entries that have already fired.
    pub dialogue_fired: Vec<String>,
    /// Campaign state (None for standalone scenarios).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub campaign: Option<CampaignState>,
    /// Human-readable scenario name for the save list UI.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub display_name: Option<String>,
}

impl SaveState {
    /// Build a SaveState from the engine's current state.
    ///
    /// This is the primary save entry point. All restorable state is captured
    /// in a single struct that can be serialized to JSON.
    pub fn build(
        state: &GameState,
        board_path: &str,
        dialogue_state: Option<&DialogueState>,
        dialogue_path: Option<&str>,
        campaign: Option<&CampaignState>,
        display_name: Option<&str>,
    ) -> Self {
        // Capture all units with their positions
        let mut units: Vec<SaveUnit> = state
            .positions
            .iter()
            .filter_map(|(&uid, &hex)| {
                state.units.get(&uid).map(|unit| SaveUnit::from_unit(unit, &hex))
            })
            .collect();
        // Sort by ID for deterministic output
        units.sort_by_key(|u| u.id);

        // Capture trigger zone fired state
        let trigger_zones_fired: Vec<bool> = state
            .trigger_zones
            .iter()
            .map(|tz| tz.triggered)
            .collect();

        // Capture village owners (only those with an actual owner)
        let mut village_owners: Vec<(i32, i32, i8)> = state
            .village_owners
            .iter()
            .filter(|(_, &owner)| owner >= 0)
            .map(|(hex, &owner)| {
                let (col, row) = hex.to_offset();
                (col, row, owner)
            })
            .collect();
        // Sort for deterministic output
        village_owners.sort();

        // Capture objective hex
        let objective_hex = state.objective_hex.map(|h| h.to_offset());

        // Capture dialogue fired IDs
        let dialogue_fired: Vec<String> = dialogue_state
            .map(|ds| ds.fired_ids().into_iter().cloned().collect())
            .unwrap_or_default();

        Self {
            board_path: board_path.to_string(),
            rng_state: state.rng.state(),
            turn: state.turn,
            active_faction: state.active_faction,
            gold: state.gold,
            max_turns: state.max_turns,
            objective_hex,
            units,
            next_unit_id: state.next_unit_id,
            trigger_zones_fired,
            village_owners,
            dialogue_path: dialogue_path.map(|s| s.to_string()),
            dialogue_fired,
            campaign: campaign.cloned(),
            display_name: display_name.map(|s| s.to_string()),
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
    fn test_save_unit_from_unit() {
        let mut unit = Unit::new(5, "fighter", 28, 0);
        unit.max_hp = 30;
        unit.xp = 12;
        unit.xp_needed = 40;
        unit.poisoned = true;
        unit.moved = true;
        unit.level = 1;
        unit.abilities = vec!["leader".to_string()];

        let hex = Hex::from_offset(3, 7);
        let save = SaveUnit::from_unit(&unit, &hex);

        assert_eq!(save.id, 5);
        assert_eq!(save.def_id, "fighter");
        assert_eq!(save.faction, 0);
        assert_eq!(save.col, 3);
        assert_eq!(save.row, 7);
        assert_eq!(save.hp, 28);
        assert_eq!(save.max_hp, 30);
        assert_eq!(save.xp, 12);
        assert_eq!(save.xp_needed, 40);
        assert!(save.poisoned);
        assert!(!save.slowed);
        assert!(save.moved);
        assert!(!save.attacked);
        assert_eq!(save.abilities, vec!["leader"]);
        assert_eq!(save.level, 1);
    }

    #[test]
    fn test_save_state_serde_round_trip() {
        let save = SaveState {
            board_path: "scenarios/crossing/board.toml".to_string(),
            rng_state: 42,
            turn: 5,
            active_faction: 1,
            gold: [80, 120],
            max_turns: Some(20),
            objective_hex: Some((10, 4)),
            units: vec![
                SaveUnit {
                    id: 1, def_id: "fighter".to_string(), faction: 0,
                    col: 2, row: 3, hp: 25, max_hp: 30,
                    xp: 10, xp_needed: 40, advancement_pending: false,
                    moved: true, attacked: false,
                    poisoned: false, slowed: true,
                    abilities: vec!["leader".to_string()], level: 1,
                },
                SaveUnit {
                    id: 2, def_id: "archer".to_string(), faction: 1,
                    col: 8, row: 5, hp: 20, max_hp: 24,
                    xp: 0, xp_needed: 40, advancement_pending: false,
                    moved: false, attacked: false,
                    poisoned: true, slowed: false,
                    abilities: vec![], level: 1,
                },
            ],
            next_unit_id: 3,
            trigger_zones_fired: vec![true, false],
            village_owners: vec![(4, 2, 0), (6, 3, 1)],
            dialogue_path: Some("scenarios/crossing/dialogue.toml".to_string()),
            dialogue_fired: vec!["crossing_start".to_string(), "crossing_bridge".to_string()],
            campaign: None,
            display_name: Some("The Crossing".to_string()),
        };

        let json = serde_json::to_string(&save).expect("serialize");
        let restored: SaveState = serde_json::from_str(&json).expect("deserialize");

        assert_eq!(save, restored);
    }

    #[test]
    fn test_save_state_build() {
        let board = Board::new(10, 8);
        let mut state = GameState::new(board);

        // Place units
        let u1 = Unit::new(1, "fighter", 30, 0);
        let u2 = Unit::new(2, "archer", 24, 1);
        state.place_unit(u1, Hex::from_offset(2, 3));
        state.place_unit(u2, Hex::from_offset(8, 5));

        // Set game metadata
        state.gold = [80, 120];
        state.turn = 5;
        state.active_faction = 1;
        state.max_turns = Some(20);
        state.objective_hex = Some(Hex::from_offset(10, 4));

        // Set village owner
        state.village_owners.insert(Hex::from_offset(4, 2), 0);

        let save = SaveState::build(
            &state,
            "scenarios/crossing/board.toml",
            None,
            None,
            None,
            Some("The Crossing"),
        );

        assert_eq!(save.board_path, "scenarios/crossing/board.toml");
        assert_eq!(save.turn, 5);
        assert_eq!(save.active_faction, 1);
        assert_eq!(save.gold, [80, 120]);
        assert_eq!(save.max_turns, Some(20));
        assert_eq!(save.objective_hex, Some((10, 4)));
        assert_eq!(save.units.len(), 2);
        assert_eq!(save.next_unit_id, state.next_unit_id);
        assert_eq!(save.village_owners, vec![(4, 2, 0)]);
        assert_eq!(save.display_name, Some("The Crossing".to_string()));

        // Verify unit order (sorted by ID)
        assert_eq!(save.units[0].id, 1);
        assert_eq!(save.units[0].def_id, "fighter");
        assert_eq!(save.units[1].id, 2);
        assert_eq!(save.units[1].def_id, "archer");
    }

    #[test]
    fn test_save_load_round_trip() {
        // Load a real board
        let project_root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        let board_path = project_root.join("scenarios/crossing/board.toml");
        let loaded = crate::scenario::load_board(&board_path).expect("load crossing board");

        let mut state = GameState::new_seeded(loaded.board, 42);
        state.objective_hex = loaded.objective_hex;
        state.max_turns = loaded.max_turns;

        // Place 3 units
        let mut u1 = Unit::new(1, "fighter", 30, 0);
        u1.xp = 15;
        u1.moved = true;
        u1.poisoned = true;
        let mut u2 = Unit::new(2, "archer", 24, 0);
        u2.attacked = true;
        u2.slowed = true;
        let u3 = Unit::new(3, "fighter", 30, 1);

        state.place_unit(u1, Hex::from_offset(2, 3));
        state.place_unit(u2, Hex::from_offset(4, 5));
        state.place_unit(u3, Hex::from_offset(8, 2));
        state.next_unit_id = 10;

        // Set game metadata
        state.gold = [80, 120];
        state.turn = 5;
        state.active_faction = 1;

        // Set village owner
        state.village_owners.insert(Hex::from_offset(4, 2), 0);

        // Set trigger zone fired (if any exist)
        if let Some(tz) = state.trigger_zones.first_mut() {
            tz.triggered = true;
        }

        // Load dialogue and fire one
        let dlg_path = project_root.join("scenarios/crossing/dialogue.toml");
        let mut dialogue = crate::dialogue::DialogueState::load(&dlg_path).unwrap();
        let _ = dialogue.get_pending("scenario_start", 1, 0, None, None);

        // Build campaign state
        let campaign_path = project_root.join("campaigns/tutorial.toml");
        let campaign_def = crate::campaign::load_campaign(&campaign_path).unwrap();
        let campaign = CampaignState::new(campaign_def);

        // Build SaveState
        let board_path_str = board_path.to_str().unwrap();
        let dlg_path_str = dlg_path.to_str().unwrap();
        let save = SaveState::build(
            &state,
            board_path_str,
            Some(&dialogue),
            Some(dlg_path_str),
            Some(&campaign),
            Some("The Crossing"),
        );

        // Serialize to JSON
        let json = serde_json::to_string_pretty(&save).expect("serialize to JSON");
        assert!(!json.is_empty());
        assert!(json.contains("\"board_path\""));
        assert!(json.contains("\"fighter\""));

        // Deserialize back
        let restored: SaveState = serde_json::from_str(&json).expect("deserialize from JSON");

        // Verify all fields match
        assert_eq!(restored.board_path, save.board_path);
        assert_eq!(restored.rng_state, save.rng_state);
        assert_eq!(restored.turn, 5);
        assert_eq!(restored.active_faction, 1);
        assert_eq!(restored.gold, [80, 120]);
        assert_eq!(restored.units.len(), 3);
        assert_eq!(restored.next_unit_id, 10);
        assert_eq!(restored.display_name, Some("The Crossing".to_string()));

        // Verify unit state preservation
        let u1_save = restored.units.iter().find(|u| u.id == 1).unwrap();
        assert_eq!(u1_save.def_id, "fighter");
        assert_eq!(u1_save.hp, 30);
        assert_eq!(u1_save.xp, 15);
        assert!(u1_save.moved);
        assert!(u1_save.poisoned);
        assert!(!u1_save.slowed);

        let u2_save = restored.units.iter().find(|u| u.id == 2).unwrap();
        assert!(u2_save.attacked);
        assert!(u2_save.slowed);

        // Verify village owners
        assert!(!restored.village_owners.is_empty());

        // Verify trigger zones
        assert_eq!(restored.trigger_zones_fired, save.trigger_zones_fired);

        // Verify dialogue fired
        assert!(!restored.dialogue_fired.is_empty());

        // Verify campaign
        assert!(restored.campaign.is_some());
        let c = restored.campaign.unwrap();
        assert_eq!(c.scenario_index, 0);
    }

    #[test]
    fn test_save_unit_preserves_status_effects() {
        let mut unit = Unit::new(1, "fighter", 30, 0);
        unit.poisoned = true;
        unit.slowed = true;
        unit.advancement_pending = true;
        unit.xp = 40;
        unit.xp_needed = 40;

        let hex = Hex::from_offset(5, 5);
        let save = SaveUnit::from_unit(&unit, &hex);

        // Round-trip through JSON
        let json = serde_json::to_string(&save).expect("serialize");
        let restored: SaveUnit = serde_json::from_str(&json).expect("deserialize");

        assert!(restored.poisoned);
        assert!(restored.slowed);
        assert!(restored.advancement_pending);
        assert_eq!(restored.xp, 40);
        assert_eq!(restored.xp_needed, 40);
    }
}
