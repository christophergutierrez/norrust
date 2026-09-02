use serde::Serialize;

/// Offset coordinates used on the wire.  The engine's Hex is cubic and is
/// intentionally not serialized directly.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OffsetHex {
    pub col: i32,
    pub row: i32,
}

impl OffsetHex {
    pub fn new(col: i32, row: i32) -> Self { Self { col, row } }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AttackUnitEvent {
    pub unit: u32,
    pub hp: u32,
    pub xp: u32,
    pub killed: bool,
    pub poisoned: bool,
    pub slowed: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum GameEvent {
    Move { unit: u32, from: OffsetHex, to: OffsetHex },
    Attack {
        attacker: AttackUnitEvent,
        defender: AttackUnitEvent,
        damage_to_defender: u32,
        damage_to_attacker: u32,
    },
    Recruit { unit: u32, def_id: String, faction: u8, col: i32, row: i32, cost: u32 },
    Vacate { unit: u32, from: OffsetHex, to: OffsetHex },
    Spawn { unit: u32, def_id: String, faction: u8, col: i32, row: i32, trigger: usize },
    Village { col: i32, row: i32, owner: u8 },
    Poison { unit: u32, damage: u32, hp: u32, cured: bool, killed: bool },
    Slow { unit: u32, slowed: bool, reason: String },
    Heal { unit: u32, amount: u32, hp: u32, reason: String },
    Gold { faction: u8, delta: i32, balance: u32, reason: String },
    Advance { unit: u32, from_def: String, to_def: String },
    EndTurn { ended_faction: u8, active_faction: u8, turn: u32 },
}
