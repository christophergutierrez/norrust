//! Campaign system: multi-scenario sequences with unit and gold carry-over.
//!
//! Campaigns are defined in TOML files under `campaigns/`. The client (Love2D)
//! manages campaign progression; the engine provides data extraction (survivors,
//! gold calculation) but does not store campaign state.

use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::game_state::GameState;

/// A single scenario entry within a campaign definition.
#[derive(Debug, Clone, Deserialize)]
pub struct CampaignScenarioDef {
    pub board: String,
    pub units: String,
    #[serde(default)]
    pub preset_units: bool,
}

/// Top-level campaign definition loaded from TOML.
#[derive(Debug, Clone, Deserialize)]
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
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VeteranUnit {
    pub def_id: String,
    pub hp: u32,
    pub max_hp: u32,
    pub xp: u32,
    pub xp_needed: u32,
    pub advancement_pending: bool,
    pub abilities: Vec<String>,
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
    use crate::unit::Unit;
    use crate::hex::Hex;

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
}
