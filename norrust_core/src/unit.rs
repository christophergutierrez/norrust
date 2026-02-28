use std::collections::HashMap;

use crate::schema::AttackDef;

/// Unit alignment — determines Time of Day damage modifier.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Alignment {
    Lawful,
    Chaotic,
    Liminal,
}

/// A runtime unit instance within a game.
///
/// `Unit` holds mutable per-game state (hp, flags) and the combat data needed
/// to resolve attacks without consulting the registry. Static blueprints
/// (name, resistances, movement costs) live in `UnitDef`, referenced by `def_id`.
#[derive(Debug, Clone)]
pub struct Unit {
    pub id: u32,
    pub def_id: String,
    pub hp: u32,
    pub max_hp: u32,
    pub faction: u8,
    pub moved: bool,
    pub attacked: bool,
    pub alignment: Alignment,
    /// Attack definitions available to this unit (copied from UnitDef at spawn).
    pub attacks: Vec<AttackDef>,
    /// Terrain-specific defense percentages (terrain_id → pct).
    pub defense: HashMap<String, u32>,
    /// Fallback defense when no terrain-specific entry exists.
    pub default_defense: u32,
    /// Movement budget in movement points (0 = unconstrained, skip pathfinding check).
    pub movement: u32,
    /// Terrain movement costs: terrain_id → movement point cost.
    pub movement_costs: HashMap<String, u32>,
    /// Damage type resistance modifiers: attack_type → modifier in percent.
    /// Negative = weakness (more damage taken), positive = resistance (less damage taken).
    pub resistances: HashMap<String, i32>,
}

impl Unit {
    pub fn new(id: u32, def_id: impl Into<String>, hp: u32, faction: u8) -> Self {
        Self {
            id,
            def_id: def_id.into(),
            hp,
            max_hp: hp,
            faction,
            moved: false,
            attacked: false,
            alignment: Alignment::Liminal,
            attacks: Vec::new(),
            defense: HashMap::new(),
            default_defense: 40,
            movement: 0,
            movement_costs: HashMap::new(),
            resistances: HashMap::new(),
        }
    }
}
