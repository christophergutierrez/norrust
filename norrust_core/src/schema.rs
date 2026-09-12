//! TOML-deserialized data schemas for units, terrain, factions, boards, and scenarios.

use serde::Deserialize;
use std::collections::HashMap;

fn default_level() -> u8 {
    1
}
fn default_alignment() -> String {
    "liminal".to_string()
}
fn default_starting_gold() -> u32 {
    100
}

/// Attack definition loaded from TOML unit files.
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
    /// Attack specials (e.g. "poison", "slow", "drain", "charge", "backstab", "first_strike").
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
    /// damage_type -> resistance modifier in percent.
    /// Negative = resistance (less damage taken), positive = weakness (more damage taken).
    pub resistances: HashMap<String, i32>,
    /// terrain_id -> movement point cost (99 = impassable)
    pub movement_costs: HashMap<String, u32>,
    /// terrain_id -> avoidance percentage (higher means safer)
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
    /// Gold recruitment cost — deducted from faction gold on recruitment.
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
    /// Vision range in hexes for fog of war. 0 = use movement as vision range.
    #[serde(default)]
    pub vision_range: u32,
}

/// Effective movement point cost to enter `terrain_id`, in the engine's real
/// fallback order: the mover's own per-terrain override
/// (`UnitDef.movement_costs` or the runtime `Unit`'s copy of it), else a
/// flat cost of 1. 99 = impassable.
///
/// The fallback is a hardcoded 1, NOT the board tile's own `movement_cost` --
/// every real caller of `pathfinding::reachable_hexes`/`find_path`
/// (game_state.rs, ffi.rs, ai.rs, greedy_driver.rs, self_play.rs) passes
/// `default_movement_cost: 1`, so a terrain id absent from the unit's own
/// map is charged 1 movement point regardless of the tile's own cost. This
/// is the single source of truth that `norrust_get_unit_terrain_info` and
/// the prompt-facing unit type profile must both agree with -- both take a
/// plain `&HashMap` so this works for either the static `UnitDef` or the
/// spawned `Unit`.
pub fn effective_movement_cost(movement_costs: &HashMap<String, u32>, terrain_id: &str) -> u32 {
    movement_costs.get(terrain_id).copied().unwrap_or(1)
}

/// Effective avoidance percentage on `terrain_id` (higher = safer), in the
/// engine's real fallback order: the mover's own override, else the board
/// tile's own defense. See `effective_movement_cost` for why this takes a
/// plain map.
pub fn effective_defense(
    defense: &HashMap<String, u32>,
    terrain_id: &str,
    tile_defense: u32,
) -> u32 {
    defense.get(terrain_id).copied().unwrap_or(tile_defense)
}

/// Unit placement entry for scenario unit files.
#[derive(Debug, Clone, Deserialize)]
pub struct UnitPlacement {
    pub id: u32,
    pub unit_type: String,
    pub faction: u8,
    pub col: i32,
    pub row: i32,
}

/// Spawn definition within a trigger zone.
#[derive(Debug, Clone, Deserialize)]
pub struct TriggerSpawnDef {
    pub unit_type: String,
    pub faction: u8,
    pub col: i32,
    pub row: i32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TriggerDef {
    pub trigger_col: i32,
    pub trigger_row: i32,
    /// Which faction's units trigger this zone (default 0 = player).
    #[serde(default)]
    pub trigger_faction: u8,
    pub spawns: Vec<TriggerSpawnDef>,
}

/// Container for unit placements and trigger zones loaded from scenario TOML.
#[derive(Debug, Clone, Deserialize)]
pub struct UnitsDef {
    pub units: Vec<UnitPlacement>,
    #[serde(default)]
    pub triggers: Vec<TriggerDef>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct BoardDef {
    pub width: u32,
    pub height: u32,
    /// Flat row-major array of terrain IDs. Length must equal width × height.
    pub tiles: Vec<String>,
    /// Objective hex column — if set with objective_row, reaching this hex wins.
    #[serde(default)]
    pub objective_col: Option<i32>,
    /// Objective hex row — if set with objective_col, reaching this hex wins.
    #[serde(default)]
    pub objective_row: Option<i32>,
    /// Maximum turns before defender wins by timeout.
    #[serde(default)]
    pub max_turns: Option<u32>,
}

/// Named group of recruitable unit types for faction definitions.
#[derive(Debug, Clone, Deserialize)]
pub struct RecruitGroup {
    pub id: String,
    pub members: Vec<String>,
}

/// Faction definition loaded from TOML — leader, recruits, and starting gold.
#[derive(Debug, Clone, Deserialize)]
pub struct FactionDef {
    pub id: String,
    pub name: String,
    pub leader_def: String,
    pub recruits: Vec<String>, // mix of group ids and unit def ids; expanded at load time
    #[serde(default = "default_starting_gold")]
    pub starting_gold: u32,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TerrainDef {
    pub id: String,
    pub name: String,
    /// Single character used in ASCII map representations (e.g., "g", "f")
    pub symbol: String,
    /// Fallback avoidance % for units with no terrain-specific entry
    pub default_defense: u32,
    /// Fallback movement cost for units with no terrain-specific entry
    pub default_movement_cost: u32,
    /// HP restored to units of the active faction at the start of their turn (0 = no healing).
    #[serde(default)]
    pub healing: u32,
    /// Hex color string for rendering (e.g. "#4a7c4e"). Empty string = use fallback.
    #[serde(default)]
    pub color: String,
}
