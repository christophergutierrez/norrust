//! Campaign system: multi-scenario sequences with unit and gold carry-over.
//!
//! Campaigns are defined in TOML files under `campaigns/`. The engine owns
//! campaign progression state via `CampaignState`, including the UUID-based
//! roster for persistent unit identity across scenarios.

use std::collections::HashMap;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::combat::Rng;
use crate::game_state::GameState;

/// A single scenario entry within a campaign definition.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CampaignScenarioDef {
    pub board: String,
    pub units: String,
    #[serde(default)]
    pub preset_units: bool,
}

/// Top-level campaign definition loaded from TOML.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CampaignDef {
    pub id: String,
    pub name: String,
    /// Faction ID for player (faction 0). If empty, client assigns.
    #[serde(default)]
    pub faction_0: String,
    /// Faction ID for enemy (faction 1). If empty, client assigns.
    #[serde(default)]
    pub faction_1: String,
    /// Percentage of gold that carries over between scenarios (0-100).
    #[serde(default = "default_carry_percent")]
    pub gold_carry_percent: u32,
    /// Bonus gold per remaining turn when finishing early.
    #[serde(default)]
    pub early_finish_bonus: u32,
    /// Ordered list of scenarios in this campaign.
    pub scenarios: Vec<CampaignScenarioDef>,
}

fn default_carry_percent() -> u32 {
    100
}

/// Wrapper for TOML deserialization — campaign TOML has `[campaign]` + `[[scenarios]]`.
#[derive(Debug, Deserialize)]
struct CampaignFile {
    campaign: CampaignMeta,
    scenarios: Vec<CampaignScenarioDef>,
}

#[derive(Debug, Deserialize)]
struct CampaignMeta {
    id: String,
    name: String,
    #[serde(default)]
    faction_0: String,
    #[serde(default)]
    faction_1: String,
    #[serde(default = "default_carry_percent")]
    gold_carry_percent: u32,
    #[serde(default)]
    early_finish_bonus: u32,
}

/// A surviving unit's portable state for carry-over between scenarios.
///
/// Contains only the fields that vary from registry defaults (hp, xp, advancement).
/// Combat stats (attacks, defense, movement_costs, resistances) are re-derived from
/// the registry when the veteran is placed in the next scenario.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VeteranUnit {
    pub def_id: String,
    pub hp: u32,
    pub max_hp: u32,
    pub xp: u32,
    pub xp_needed: u32,
    pub advancement_pending: bool,
    pub abilities: Vec<String>,
}

/// Whether a rostered unit is alive or dead.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum RosterStatus {
    Alive,
    Dead,
}

/// A rostered unit with persistent UUID identity across scenarios.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RosterEntry {
    pub uuid: String,
    pub def_id: String,
    pub hp: u32,
    pub max_hp: u32,
    pub xp: u32,
    pub xp_needed: u32,
    pub advancement_pending: bool,
    pub abilities: Vec<String>,
    pub status: RosterStatus,
}

/// Runtime campaign progression state owned by the engine.
///
/// Tracks scenario index, carry-over gold, veterans, and the UUID-based roster
/// for persistent unit identity across scenarios.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct CampaignState {
    pub campaign_def: CampaignDef,
    pub scenario_index: usize,
    pub carry_gold: u32,
    pub veterans: Vec<VeteranUnit>,
    pub roster: HashMap<String, RosterEntry>,
    /// Maps engine unit IDs to roster UUIDs for the current scenario.
    pub id_map: HashMap<u32, String>,
    /// RNG seed counter for UUID generation.
    #[serde(skip)]
    uuid_counter: u64,
}

impl CampaignState {
    /// Create a new campaign state from a campaign definition.
    pub fn new(def: CampaignDef) -> Self {
        Self {
            campaign_def: def,
            scenario_index: 0,
            carry_gold: 0,
            veterans: Vec::new(),
            roster: HashMap::new(),
            id_map: HashMap::new(),
            uuid_counter: 1,
        }
    }

    /// Generate an 8-character hex UUID using xorshift64.
    pub fn generate_uuid(&mut self) -> String {
        let mut rng = Rng::new(self.uuid_counter);
        self.uuid_counter += 1;
        let val = rng.next_u64();
        format!("{:08x}", val as u32)
    }

    /// Add a unit to the roster, returning the assigned UUID.
    pub fn add_unit(
        &mut self,
        def_id: &str,
        engine_id: u32,
        hp: u32,
        max_hp: u32,
        xp: u32,
        xp_needed: u32,
        advancement_pending: bool,
        abilities: Vec<String>,
    ) -> String {
        let uuid = self.generate_uuid();
        let entry = RosterEntry {
            uuid: uuid.clone(),
            def_id: def_id.to_string(),
            hp,
            max_hp,
            xp,
            xp_needed,
            advancement_pending,
            abilities,
            status: RosterStatus::Alive,
        };
        self.roster.insert(uuid.clone(), entry);
        self.id_map.insert(engine_id, uuid.clone());
        uuid
    }

    /// Map an engine unit ID to an existing roster UUID (for veteran placement).
    pub fn map_id(&mut self, engine_id: u32, uuid: &str) {
        self.id_map.insert(engine_id, uuid.to_string());
    }

    /// Clear the engine ID → UUID mappings between scenarios.
    pub fn clear_id_map(&mut self) {
        self.id_map.clear();
    }

    /// Sync roster entries from the current game state.
    ///
    /// Updates hp/xp/advancement for living units in the id_map.
    /// Units in the id_map that are missing from the game state are marked Dead.
    pub fn sync_from_state(&mut self, state: &GameState, faction: u8) {
        // Collect all engine IDs for this faction from the id_map
        let mapped_ids: Vec<(u32, String)> = self
            .id_map
            .iter()
            .map(|(eid, uuid)| (*eid, uuid.clone()))
            .collect();

        for (engine_id, uuid) in mapped_ids {
            if let Some(entry) = self.roster.get_mut(&uuid) {
                if let Some(unit) = state.units.get(&engine_id) {
                    if unit.faction == faction {
                        entry.hp = unit.hp;
                        entry.max_hp = unit.max_hp;
                        entry.xp = unit.xp;
                        entry.xp_needed = unit.xp_needed;
                        entry.advancement_pending = unit.advancement_pending;
                        entry.abilities = unit.abilities.clone();
                        entry.status = RosterStatus::Alive;
                    }
                } else {
                    // Unit not in game state — it died
                    entry.status = RosterStatus::Dead;
                }
            }
        }
    }

    /// Return references to all living roster entries.
    pub fn get_living(&self) -> Vec<&RosterEntry> {
        self.roster
            .values()
            .filter(|e| e.status == RosterStatus::Alive)
            .collect()
    }

    /// Record a victory: sync roster, extract veterans, calculate gold, advance index.
    pub fn record_victory(&mut self, state: &GameState, faction: u8) {
        self.sync_from_state(state, faction);
        self.veterans = get_survivors(state, faction);

        let current_gold = state.gold[faction as usize];
        let turns_remaining = state
            .max_turns
            .map(|max| max.saturating_sub(state.turn))
            .unwrap_or(0);
        self.carry_gold = calculate_carry_gold(
            current_gold,
            self.campaign_def.gold_carry_percent,
            turns_remaining,
            self.campaign_def.early_finish_bonus,
        );

        self.scenario_index += 1;
    }

    /// Return the current scenario definition, or None if campaign is finished.
    pub fn current_scenario(&self) -> Option<&CampaignScenarioDef> {
        self.campaign_def.scenarios.get(self.scenario_index)
    }
}

/// Load a campaign definition from a TOML file.
pub fn load_campaign(path: &Path) -> Result<CampaignDef, String> {
    let content = std::fs::read_to_string(path)
        .map_err(|e| format!("Failed to read campaign file: {}", e))?;
    let file: CampaignFile = toml::from_str(&content)
        .map_err(|e| format!("Failed to parse campaign TOML: {}", e))?;
    Ok(CampaignDef {
        id: file.campaign.id,
        name: file.campaign.name,
        faction_0: file.campaign.faction_0,
        faction_1: file.campaign.faction_1,
        gold_carry_percent: file.campaign.gold_carry_percent,
        early_finish_bonus: file.campaign.early_finish_bonus,
        scenarios: file.scenarios,
    })
}

/// Extract surviving units of the given faction from the current game state.
pub fn get_survivors(state: &GameState, faction: u8) -> Vec<VeteranUnit> {
    state
        .units
        .values()
        .filter(|u| u.faction == faction)
        .map(|u| VeteranUnit {
            def_id: u.def_id.clone(),
            hp: u.hp,
            max_hp: u.max_hp,
            xp: u.xp,
            xp_needed: u.xp_needed,
            advancement_pending: u.advancement_pending,
            abilities: u.abilities.clone(),
        })
        .collect()
}

/// Calculate carry-over gold for the next scenario.
///
/// Formula: `current_gold * (gold_carry_percent / 100) + turns_remaining * early_finish_bonus`
pub fn calculate_carry_gold(
    current_gold: u32,
    gold_carry_percent: u32,
    turns_remaining: u32,
    early_finish_bonus: u32,
) -> u32 {
    let base = current_gold * gold_carry_percent / 100;
    base + turns_remaining * early_finish_bonus
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::hex::Hex;
    use crate::unit::Unit;

    #[test]
    fn test_load_campaign_toml() {
        let root = std::env::var("CARGO_MANIFEST_DIR").unwrap();
        let path = std::path::Path::new(&root)
            .parent()
            .unwrap()
            .join("campaigns/tutorial.toml");
        let campaign = load_campaign(&path).expect("should load tutorial campaign");
        assert_eq!(campaign.id, "tutorial");
        assert_eq!(campaign.name, "The Road to Norrust");
        assert_eq!(campaign.gold_carry_percent, 80);
        assert_eq!(campaign.early_finish_bonus, 5);
        assert_eq!(campaign.scenarios.len(), 4);
        assert_eq!(campaign.scenarios[0].board, "crossing/board.toml");
        assert_eq!(campaign.scenarios[1].board, "ambush/board.toml");
        assert_eq!(campaign.scenarios[2].board, "night_orcs/board.toml");
        assert_eq!(campaign.scenarios[3].board, "final_battle/board.toml");
    }

    #[test]
    fn test_get_survivors() {
        let board = Board::new(10, 10);
        let mut state = GameState::new(board);

        let mut u1 = Unit::new(1, "fighter", 30, 0);
        u1.xp = 15;
        u1.xp_needed = 40;
        state.place_unit(u1, Hex::from_offset(0, 0));

        let mut u2 = Unit::new(2, "archer", 20, 0);
        u2.hp = 12; // wounded
        u2.xp = 5;
        u2.xp_needed = 32;
        state.place_unit(u2, Hex::from_offset(1, 0));

        // Enemy unit — should not appear in faction 0 survivors
        state.place_unit(Unit::new(3, "grunt", 30, 1), Hex::from_offset(2, 0));

        let survivors = get_survivors(&state, 0);
        assert_eq!(survivors.len(), 2);

        let fighter = survivors.iter().find(|v| v.def_id == "fighter").unwrap();
        assert_eq!(fighter.hp, 30);
        assert_eq!(fighter.xp, 15);
        assert_eq!(fighter.xp_needed, 40);

        let archer = survivors.iter().find(|v| v.def_id == "archer").unwrap();
        assert_eq!(archer.hp, 12);
        assert_eq!(archer.xp, 5);
    }

    #[test]
    fn test_calculate_carry_gold() {
        // 150 gold at 80% = 120
        assert_eq!(calculate_carry_gold(150, 80, 0, 0), 120);

        // 150 gold at 80% + 10 remaining turns * 5 bonus = 120 + 50 = 170
        assert_eq!(calculate_carry_gold(150, 80, 10, 5), 170);

        // 100% carry = no loss
        assert_eq!(calculate_carry_gold(100, 100, 0, 0), 100);

        // 0% carry = all lost (but bonus still applies)
        assert_eq!(calculate_carry_gold(100, 0, 5, 10), 50);
    }

    fn make_campaign_def() -> CampaignDef {
        CampaignDef {
            id: "test".to_string(),
            name: "Test Campaign".to_string(),
            faction_0: "loyalists".to_string(),
            faction_1: "orcs".to_string(),
            gold_carry_percent: 80,
            early_finish_bonus: 5,
            scenarios: vec![
                CampaignScenarioDef {
                    board: "crossing/board.toml".to_string(),
                    units: "crossing/units.toml".to_string(),
                    preset_units: true,
                },
                CampaignScenarioDef {
                    board: "ambush/board.toml".to_string(),
                    units: "ambush/units.toml".to_string(),
                    preset_units: true,
                },
            ],
        }
    }

    #[test]
    fn test_campaign_state_new() {
        let def = make_campaign_def();
        let cs = CampaignState::new(def);
        assert_eq!(cs.scenario_index, 0);
        assert_eq!(cs.carry_gold, 0);
        assert!(cs.veterans.is_empty());
        assert!(cs.roster.is_empty());
        assert!(cs.id_map.is_empty());
        assert!(cs.current_scenario().is_some());
        assert_eq!(
            cs.current_scenario().unwrap().board,
            "crossing/board.toml"
        );
    }

    #[test]
    fn test_roster_add_and_get_living() {
        let def = make_campaign_def();
        let mut cs = CampaignState::new(def);

        let uuid1 = cs.add_unit("fighter", 1, 30, 30, 0, 40, false, vec![]);
        let uuid2 = cs.add_unit("archer", 2, 25, 25, 5, 32, false, vec![]);
        let uuid3 = cs.add_unit("spearman", 3, 28, 28, 0, 36, false, vec![]);

        assert_eq!(cs.roster.len(), 3);
        assert_eq!(cs.get_living().len(), 3);

        // Mark one as dead
        cs.roster.get_mut(&uuid3).unwrap().status = RosterStatus::Dead;
        assert_eq!(cs.get_living().len(), 2);

        // Verify id_map
        assert_eq!(cs.id_map.get(&1), Some(&uuid1));
        assert_eq!(cs.id_map.get(&2), Some(&uuid2));
    }

    #[test]
    fn test_roster_sync_marks_dead() {
        let def = make_campaign_def();
        let mut cs = CampaignState::new(def);

        let uuid1 = cs.add_unit("fighter", 1, 30, 30, 0, 40, false, vec![]);
        let uuid2 = cs.add_unit("archer", 2, 25, 25, 0, 32, false, vec![]);

        // Create a state with only unit 1 alive (unit 2 died)
        let board = Board::new(8, 5);
        let mut state = GameState::new(board);
        let mut u1 = Unit::new(1, "fighter", 30, 0);
        u1.hp = 20; // wounded
        u1.xp = 10;
        state.place_unit(u1, Hex::from_offset(0, 0));
        // Unit 2 is NOT in game state — it's dead

        cs.sync_from_state(&state, 0);

        // Unit 1 should be alive with updated stats
        let entry1 = cs.roster.get(&uuid1).unwrap();
        assert_eq!(entry1.status, RosterStatus::Alive);
        assert_eq!(entry1.hp, 20);
        assert_eq!(entry1.xp, 10);

        // Unit 2 should be marked dead
        let entry2 = cs.roster.get(&uuid2).unwrap();
        assert_eq!(entry2.status, RosterStatus::Dead);
    }

    #[test]
    fn test_generate_uuid() {
        let def = make_campaign_def();
        let mut cs = CampaignState::new(def);

        let uuid1 = cs.generate_uuid();
        let uuid2 = cs.generate_uuid();

        // 8 hex chars
        assert_eq!(uuid1.len(), 8);
        assert_eq!(uuid2.len(), 8);
        // All hex digits
        assert!(uuid1.chars().all(|c| c.is_ascii_hexdigit()));
        assert!(uuid2.chars().all(|c| c.is_ascii_hexdigit()));
        // Different
        assert_ne!(uuid1, uuid2);
    }

    #[test]
    fn test_campaign_lifecycle() {
        let root = std::env::var("CARGO_MANIFEST_DIR").unwrap();
        let path = std::path::Path::new(&root)
            .parent()
            .unwrap()
            .join("campaigns/tutorial.toml");
        let def = load_campaign(&path).expect("should load tutorial campaign");
        let mut cs = CampaignState::new(def);

        // Verify initial state
        assert_eq!(cs.scenario_index, 0);
        assert_eq!(
            cs.current_scenario().unwrap().board,
            "crossing/board.toml"
        );

        // Simulate scenario 1: place 3 faction-0 units
        let board = Board::new(16, 10);
        let mut state = GameState::new(board);
        state.gold = [150, 100];
        state.max_turns = Some(30);
        state.turn = 20; // finished on turn 20 → 10 remaining

        let mut u1 = Unit::new(1, "fighter", 30, 0);
        u1.xp = 15;
        u1.xp_needed = 40;
        state.place_unit(u1, Hex::from_offset(0, 0));

        let mut u2 = Unit::new(2, "archer", 25, 0);
        u2.hp = 12; // wounded
        u2.xp = 20;
        u2.xp_needed = 32;
        state.place_unit(u2, Hex::from_offset(1, 0));

        let u3 = Unit::new(3, "spearman", 36, 0);
        state.place_unit(u3, Hex::from_offset(2, 0));

        // Add all 3 to roster
        cs.add_unit("fighter", 1, 30, 30, 0, 40, false, vec![]);
        cs.add_unit("archer", 2, 25, 25, 0, 32, false, vec![]);
        let uuid3 = cs.add_unit("spearman", 3, 36, 36, 0, 36, false, vec![]);

        // "Kill" unit 3 by removing from state
        let pos3 = *state.positions.get(&3).unwrap();
        state.hex_to_unit.remove(&pos3);
        state.units.remove(&3);
        state.positions.remove(&3);

        // Record victory
        cs.record_victory(&state, 0);

        // Verify progression
        assert_eq!(cs.scenario_index, 1);
        assert_eq!(cs.veterans.len(), 2); // 2 survivors
        // Gold: 150 * 80% + 10 * 5 = 120 + 50 = 170
        assert_eq!(cs.carry_gold, 170);

        // Verify roster
        assert_eq!(cs.roster.len(), 3); // all 3 tracked
        assert_eq!(cs.get_living().len(), 2); // 2 alive
        let dead_entry = cs.roster.get(&uuid3).unwrap();
        assert_eq!(dead_entry.status, RosterStatus::Dead);

        // Verify next scenario
        assert_eq!(
            cs.current_scenario().unwrap().board,
            "ambush/board.toml"
        );

        // Test clear_id_map and map_id for scenario 2
        cs.clear_id_map();
        assert!(cs.id_map.is_empty());

        // Map veterans to new engine IDs in scenario 2
        let living_uuids: Vec<String> = cs
            .get_living()
            .iter()
            .map(|e| e.uuid.clone())
            .collect();
        assert_eq!(living_uuids.len(), 2);
        for (i, uuid) in living_uuids.iter().enumerate() {
            cs.map_id((i + 10) as u32, uuid);
        }
        assert_eq!(cs.id_map.len(), 2);
    }
}
