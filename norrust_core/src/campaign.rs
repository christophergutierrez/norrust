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
use crate::hex::Hex;

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

    /// Build VeteranInfo list from current veterans + roster for deployment UI.
    pub fn build_veteran_info(&self, available_slots: usize) -> Vec<VeteranInfo> {
        let living: Vec<&RosterEntry> = self.get_living();
        self.veterans
            .iter()
            .enumerate()
            .map(|(i, vet)| {
                let uuid = living.get(i).map(|e| e.uuid.clone());
                VeteranInfo {
                    def_id: vet.def_id.clone(),
                    hp: vet.hp,
                    max_hp: vet.max_hp,
                    xp: vet.xp,
                    xp_needed: vet.xp_needed,
                    advancement_pending: vet.advancement_pending,
                    uuid,
                    deployed: i < available_slots,
                }
            })
            .collect()
    }

    /// Populate the roster from all faction-0 units in the game state (first scenario).
    pub fn populate_initial_roster(&mut self, state: &GameState, faction: u8) {
        for (_, unit) in &state.units {
            if unit.faction == faction {
                self.add_unit(
                    &unit.def_id,
                    unit.id,
                    unit.hp,
                    unit.max_hp,
                    unit.xp,
                    unit.xp_needed,
                    unit.advancement_pending,
                    unit.abilities.clone(),
                );
            }
        }
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

/// Result of veteran placement attempt.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub enum PlaceResult {
    /// All veterans placed successfully.
    Placed,
    /// More veterans than available slots — deployment screen needed.
    DeployNeeded {
        slots: usize,
        veterans: Vec<VeteranInfo>,
    },
}

/// Veteran info for the deployment UI (includes roster UUID).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VeteranInfo {
    pub def_id: String,
    pub hp: u32,
    pub max_hp: u32,
    pub xp: u32,
    pub xp_needed: u32,
    pub advancement_pending: bool,
    pub uuid: Option<String>,
    pub deployed: bool,
}

/// Result of loading the next campaign scenario.
#[derive(Debug, Clone, PartialEq, Serialize)]
pub enum ScenarioLoadResult {
    /// Scenario loaded and ready to play.
    Playing,
    /// Deploy screen needed — more veterans than available castle slots.
    DeployNeeded {
        slots: usize,
        veterans: Vec<VeteranInfo>,
    },
    /// Campaign is finished (no more scenarios).
    CampaignComplete,
    /// Error during loading.
    Error(String),
}

/// Find the player keep hex and adjacent castle hexes on the board.
///
/// For faction 0, selects the leftmost keep; for faction 1, the rightmost.
/// Returns (keep_hex, castle_hexes) where castle_hexes are adjacent to the keep.
pub fn find_keep_and_castles(state: &GameState, faction: u8) -> (Option<Hex>, Vec<Hex>) {
    let board = &state.board;
    let width = board.width as i32;
    let height = board.height as i32;

    // Scan all hexes for keeps
    let mut keep_hex: Option<Hex> = None;
    for col in 0..width {
        for row in 0..height {
            let hex = Hex::from_offset(col, row);
            if board.terrain_at(hex) == Some("keep") {
                let (kcol, _) = hex.to_offset();
                match keep_hex {
                    None => keep_hex = Some(hex),
                    Some(current) => {
                        let (cur_col, _) = current.to_offset();
                        if faction == 0 && kcol < cur_col {
                            keep_hex = Some(hex);
                        } else if faction == 1 && kcol > cur_col {
                            keep_hex = Some(hex);
                        }
                    }
                }
            }
        }
    }

    let Some(keep) = keep_hex else {
        return (None, Vec::new());
    };

    // Collect adjacent castle hexes
    let mut castle_hexes = Vec::new();
    for col in 0..width {
        for row in 0..height {
            let hex = Hex::from_offset(col, row);
            if board.terrain_at(hex) == Some("castle") && keep.distance(hex) == 1 {
                castle_hexes.push(hex);
            }
        }
    }

    (Some(keep), castle_hexes)
}

/// Count available (unoccupied) placement slots on keep + adjacent castles.
pub fn count_available_slots(state: &GameState, keep: Hex, castles: &[Hex]) -> usize {
    let mut count = 0;
    if !state.hex_to_unit.contains_key(&keep) {
        count += 1;
    }
    for &hex in castles {
        if !state.hex_to_unit.contains_key(&hex) {
            count += 1;
        }
    }
    count
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
            faction_1: "northerners".to_string(),
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

    #[test]
    fn test_find_keep_and_castles_faction_0() {
        // Create a board with two keeps and castles
        let mut board = Board::new(16, 10);
        // Left keep at (1, 5)
        board.set_terrain(Hex::from_offset(1, 5), "keep");
        // Adjacent castles to left keep
        board.set_terrain(Hex::from_offset(0, 4), "castle");
        board.set_terrain(Hex::from_offset(0, 5), "castle");
        board.set_terrain(Hex::from_offset(1, 4), "castle");
        board.set_terrain(Hex::from_offset(2, 5), "castle");
        board.set_terrain(Hex::from_offset(1, 6), "castle");
        // Right keep at (13, 5)
        board.set_terrain(Hex::from_offset(13, 5), "keep");
        board.set_terrain(Hex::from_offset(13, 4), "castle");
        board.set_terrain(Hex::from_offset(14, 5), "castle");

        let state = GameState::new(board);

        // Faction 0: should pick leftmost keep
        let (keep, castles) = find_keep_and_castles(&state, 0);
        assert!(keep.is_some());
        let (kcol, krow) = keep.unwrap().to_offset();
        assert_eq!((kcol, krow), (1, 5));
        // Should have adjacent castle hexes (distance == 1 from keep)
        assert!(castles.len() >= 4);
        for c in &castles {
            assert_eq!(keep.unwrap().distance(*c), 1);
        }
    }

    #[test]
    fn test_find_keep_and_castles_faction_1() {
        let mut board = Board::new(16, 10);
        board.set_terrain(Hex::from_offset(1, 5), "keep");
        board.set_terrain(Hex::from_offset(13, 5), "keep");
        board.set_terrain(Hex::from_offset(13, 4), "castle");
        board.set_terrain(Hex::from_offset(14, 5), "castle");

        let state = GameState::new(board);

        // Faction 1: should pick rightmost keep
        let (keep, castles) = find_keep_and_castles(&state, 1);
        assert!(keep.is_some());
        let (kcol, _) = keep.unwrap().to_offset();
        assert_eq!(kcol, 13);
        assert_eq!(castles.len(), 2);
    }

    #[test]
    fn test_find_keep_and_castles_no_keep() {
        let board = Board::new(8, 5);
        let state = GameState::new(board);
        let (keep, castles) = find_keep_and_castles(&state, 0);
        assert!(keep.is_none());
        assert!(castles.is_empty());
    }

    #[test]
    fn test_count_available_slots() {
        let mut board = Board::new(8, 5);
        board.set_terrain(Hex::from_offset(1, 2), "keep");
        board.set_terrain(Hex::from_offset(0, 2), "castle");
        board.set_terrain(Hex::from_offset(2, 2), "castle");

        let mut state = GameState::new(board);
        let keep = Hex::from_offset(1, 2);
        let castles = vec![Hex::from_offset(0, 2), Hex::from_offset(2, 2)];

        // All empty: 3 slots (keep + 2 castles)
        assert_eq!(count_available_slots(&state, keep, &castles), 3);

        // Occupy the keep
        state.place_unit(Unit::new(1, "leader", 30, 0), keep);
        assert_eq!(count_available_slots(&state, keep, &castles), 2);

        // Occupy one castle
        state.place_unit(Unit::new(2, "fighter", 30, 0), Hex::from_offset(0, 2));
        assert_eq!(count_available_slots(&state, keep, &castles), 1);
    }

    #[test]
    fn test_build_veteran_info() {
        let def = make_campaign_def();
        let mut cs = CampaignState::new(def);

        // Simulate having veterans
        cs.veterans = vec![
            VeteranUnit {
                def_id: "fighter".to_string(),
                hp: 30, max_hp: 30, xp: 15, xp_needed: 40,
                advancement_pending: false, abilities: vec![],
            },
            VeteranUnit {
                def_id: "archer".to_string(),
                hp: 20, max_hp: 25, xp: 5, xp_needed: 32,
                advancement_pending: false, abilities: vec![],
            },
            VeteranUnit {
                def_id: "spearman".to_string(),
                hp: 28, max_hp: 28, xp: 0, xp_needed: 36,
                advancement_pending: false, abilities: vec![],
            },
        ];

        // With 2 available slots, first 2 should be deployed
        let info = cs.build_veteran_info(2);
        assert_eq!(info.len(), 3);
        assert!(info[0].deployed);
        assert!(info[1].deployed);
        assert!(!info[2].deployed);

        // With enough slots, all deployed
        let info = cs.build_veteran_info(5);
        assert!(info.iter().all(|v| v.deployed));
    }

    #[test]
    fn test_populate_initial_roster() {
        let def = make_campaign_def();
        let mut cs = CampaignState::new(def);

        let board = Board::new(8, 5);
        let mut state = GameState::new(board);

        let u1 = Unit::new(1, "fighter", 30, 0);
        state.place_unit(u1, Hex::from_offset(0, 0));

        let u2 = Unit::new(2, "archer", 25, 0);
        state.place_unit(u2, Hex::from_offset(1, 0));

        // Enemy — should not be in roster
        let u3 = Unit::new(3, "grunt", 30, 1);
        state.place_unit(u3, Hex::from_offset(2, 0));

        cs.populate_initial_roster(&state, 0);

        assert_eq!(cs.roster.len(), 2);
        assert_eq!(cs.id_map.len(), 2);
        assert!(cs.id_map.contains_key(&1));
        assert!(cs.id_map.contains_key(&2));
        assert!(!cs.id_map.contains_key(&3));
    }
}
