use serde::Deserialize;
use std::collections::HashMap;

fn default_level() -> u8 { 1 }
fn default_alignment() -> String { "liminal".to_string() }

#[derive(Debug, Clone, Default, Deserialize)]
pub struct AttackDef {
    pub id: String,
    pub name: String,
    pub damage: u32,
    pub strikes: u32,
    /// blade | pierce | impact | fire | cold | arcane
    pub attack_type: String,
    /// melee | ranged
    pub range: String,
    /// Attack specials (e.g. "poison", "slow") — stored, no gameplay effect yet.
    #[serde(default)]
    pub specials: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct UnitDef {
    pub id: String,
    pub name: String,
    pub max_hp: u32,
    pub movement: u32,
    pub attacks: Vec<AttackDef>,
    /// damage_type -> resistance modifier in percent (negative = weakness)
    pub resistances: HashMap<String, i32>,
    /// terrain_id -> movement point cost (99 = impassable)
    pub movement_costs: HashMap<String, u32>,
    /// terrain_id -> defense percentage
    pub defense: HashMap<String, u32>,
    /// Unit tier — 1 = base, 2 = advanced, etc.
    #[serde(default = "default_level")]
    pub level: u8,
    /// XP required to advance to the next unit type.
    #[serde(default)]
    pub experience: u32,
    /// Unit type IDs this unit can advance into (empty = no advancement).
    #[serde(default)]
    pub advances_to: Vec<String>,
    /// Race (e.g. "human", "elf") — metadata, no gameplay effect.
    #[serde(default)]
    pub race: String,
    /// Gold recruitment cost — stored for future UI, not used by Rust engine.
    #[serde(default)]
    pub cost: u32,
    /// Usage hint (e.g. "fighter", "archer") — stored for future AI/recruitment.
    #[serde(default)]
    pub usage: String,
    /// Abilities (e.g. "regenerates") — stored, no gameplay effect yet.
    #[serde(default)]
    pub abilities: Vec<String>,
    /// Alignment: "lawful" | "chaotic" | "liminal" | "neutral".
    /// Determines Time-of-Day damage modifier. Copied to Unit at spawn.
    #[serde(default = "default_alignment")]
    pub alignment: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TerrainDef {
    pub id: String,
    pub name: String,
    /// Single character used in ASCII map representations (e.g., "g", "f")
    pub symbol: String,
    /// Fallback defense % for units with no terrain-specific entry
    pub default_defense: u32,
    /// Fallback movement cost for units with no terrain-specific entry
    pub default_movement_cost: u32,
    /// HP restored to units of the active faction at the start of their turn (0 = no healing).
    #[serde(default)]
    pub healing: u32,
}
