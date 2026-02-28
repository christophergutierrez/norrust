use serde::Deserialize;
use std::collections::HashMap;

#[derive(Debug, Clone, Deserialize)]
pub struct AttackDef {
    pub id: String,
    pub name: String,
    pub damage: u32,
    pub strikes: u32,
    /// blade | pierce | impact | fire | cold | arcane
    pub attack_type: String,
    /// melee | ranged
    pub range: String,
}

#[derive(Debug, Clone, Deserialize)]
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
