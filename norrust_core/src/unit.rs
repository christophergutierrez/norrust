//! Runtime unit instances — mutable per-game state derived from static `UnitDef` blueprints.

use std::collections::HashMap;

use crate::schema::{AttackDef, UnitDef};

/// Unit alignment — determines Time of Day damage modifier.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Alignment {
    Lawful,
    Chaotic,
    Liminal,
}

/// Parse a UnitDef alignment string into the runtime Alignment enum.
/// "lawful" → Lawful, "chaotic" → Chaotic, anything else → Liminal.
/// "neutral" and "" both map to Liminal (same ToD modifier — no bonus/penalty).
pub fn parse_alignment(s: &str) -> Alignment {
    match s {
        "lawful"  => Alignment::Lawful,
        "chaotic" => Alignment::Chaotic,
        _         => Alignment::Liminal,
    }
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
    /// Negative = resistance (less damage taken), positive = weakness (more damage taken).
    pub resistances: HashMap<String, i32>,
    /// Current experience points earned through combat.
    pub xp: u32,
    /// XP threshold to trigger advancement (copied from UnitDef.experience at spawn).
    pub xp_needed: u32,
    /// Set true when xp >= xp_needed; cleared by Action::Advance (Phase 8).
    pub advancement_pending: bool,
    /// Unit tier — 1 = base, 2 = advanced, etc. Used for leadership level comparison.
    pub level: u8,
    /// Abilities copied from UnitDef at spawn (e.g. "leader", "leadership", "regenerates").
    pub abilities: Vec<String>,
    /// Poisoned status — takes 8 damage per turn, cured at villages.
    pub poisoned: bool,
    /// Slowed status — halves movement and damage, cleared at start of faction turn.
    pub slowed: bool,
}

/// Advance `unit` to the stats defined by `new_def`.
///
/// Copies all stat fields from `new_def`, heals to full, resets xp to 0,
/// clears advancement_pending, and updates def_id. Registry-free: caller
/// resolves the target UnitDef before calling.
pub fn advance_unit(unit: &mut Unit, new_def: &UnitDef) {
    unit.def_id = new_def.id.clone();
    unit.max_hp = new_def.max_hp;
    unit.hp = new_def.max_hp;
    unit.movement = new_def.movement;
    unit.movement_costs = new_def.movement_costs.clone();
    unit.attacks = new_def.attacks.clone();
    unit.defense = new_def.defense.clone();
    unit.resistances = new_def.resistances.clone();
    unit.alignment = parse_alignment(&new_def.alignment);
    unit.xp_needed = new_def.experience;
    unit.level = new_def.level;
    unit.abilities = new_def.abilities.clone();
    unit.xp = 0;
    unit.advancement_pending = false;
    unit.poisoned = false;
    unit.slowed = false;
}

impl Unit {
    /// Create a unit from a UnitDef blueprint, fully populated with stats.
    pub fn from_def(id: u32, def: &UnitDef, faction: u8) -> Self {
        let mut u = Self::new(id, &def.id, def.max_hp, faction);
        u.max_hp = def.max_hp;
        u.hp = def.max_hp;
        u.movement = def.movement;
        u.movement_costs = def.movement_costs.clone();
        u.attacks = def.attacks.clone();
        u.defense = def.defense.clone();
        u.resistances = def.resistances.clone();
        u.xp_needed = def.experience;
        u.alignment = parse_alignment(&def.alignment);
        u.level = def.level;
        u.abilities = def.abilities.clone();
        u
    }

    /// Create a new unit with the given ID, definition ID, starting HP, and faction.
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
            xp: 0,
            xp_needed: 0,
            advancement_pending: false,
            level: 1,
            abilities: Vec::new(),
            poisoned: false,
            slowed: false,
        }
    }
}

/// Check if an attack definition has a named special (e.g. "drain", "poison").
pub fn has_special(attack: &AttackDef, name: &str) -> bool {
    attack.specials.iter().any(|s| s == name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schema::AttackDef;

    #[test]
    fn test_advance_unit_updates_stats_and_resets_xp() {
        let mut unit = Unit::new(1, "fighter", 30, 0);
        unit.xp = 40;
        unit.xp_needed = 40;
        unit.advancement_pending = true;

        let hero_def = UnitDef {
            id: "hero".to_string(),
            name: "Hero".to_string(),
            max_hp: 45,
            movement: 5,
            attacks: vec![AttackDef {
                id: "sword".to_string(), name: "Sword".to_string(),
                damage: 9, strikes: 4,
                attack_type: "blade".to_string(), range: "melee".to_string(),
                ..Default::default()
            }],
            resistances: HashMap::new(),
            movement_costs: HashMap::new(),
            defense: HashMap::new(),
            level: 2,
            experience: 80,
            advances_to: vec![],
            ..Default::default()
        };

        advance_unit(&mut unit, &hero_def);

        assert_eq!(unit.def_id, "hero");
        assert_eq!(unit.max_hp, 45);
        assert_eq!(unit.hp, 45);
        assert_eq!(unit.movement, 5);
        assert_eq!(unit.attacks[0].damage, 9);
        assert_eq!(unit.xp, 0);
        assert_eq!(unit.xp_needed, 80);
        assert!(!unit.advancement_pending);
    }
}
