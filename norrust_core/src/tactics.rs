//! Read-only, engine-owned tactical candidates shared by AI and adapters.

use serde::Serialize;

use crate::combat::{combat_parameters, exact_exchange, ExchangeForecast};
use crate::game_state::{legal_moves, legal_targets, ActionError, GameState};
use crate::hex::Hex;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Engagement {
    pub defender_id: u32,
    pub forecast: ExchangeForecast,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct OriginCandidate {
    pub col: i32,
    pub row: i32,
    pub current: bool,
    pub movable: bool,
    pub engagements: Vec<Engagement>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UnitTactics {
    pub unit_id: u32,
    pub origins: Vec<OriginCandidate>,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum TacticsError {
    #[error(transparent)]
    Action(#[from] ActionError),
    #[error(transparent)]
    Combat(#[from] crate::combat::PreviewError),
}

fn origin(
    state: &GameState,
    unit_id: u32,
    hex: Hex,
    current: bool,
    movable: bool,
) -> Result<OriginCandidate, TacticsError> {
    let mut defender_ids = legal_targets(state, unit_id, hex)?;
    defender_ids.sort_unstable();
    let engagements = defender_ids
        .into_iter()
        .map(|defender_id| {
            let parameters = combat_parameters(state, unit_id, defender_id, hex)?;
            Ok(Engagement {
                defender_id,
                forecast: exact_exchange(&parameters),
            })
        })
        .collect::<Result<Vec<_>, TacticsError>>()?;
    let (col, row) = hex.to_offset();
    Ok(OriginCandidate {
        col,
        row,
        current,
        movable,
        engagements,
    })
}

/// Return all currently legal move/attack origins for one active-side unit.
/// The standing origin is never a legal Move destination.
pub fn unit_tactics(state: &GameState, unit_id: u32) -> Result<UnitTactics, TacticsError> {
    let unit = state
        .units
        .get(&unit_id)
        .ok_or(ActionError::UnitNotFound(unit_id))?;
    if unit.faction != state.active_faction {
        return Err(ActionError::NotYourTurn.into());
    }
    let current = *state
        .positions
        .get(&unit_id)
        .ok_or(ActionError::UnitNotFound(unit_id))?;
    let mut origins = Vec::new();
    if !unit.attacked {
        origins.push(origin(state, unit_id, current, true, false)?);
    }
    if !unit.moved {
        for destination in legal_moves(state, unit_id)? {
            origins.push(origin(state, unit_id, destination, false, true)?);
        }
    }
    Ok(UnitTactics { unit_id, origins })
}

/// Aggregate the candidates for every actionable unit in deterministic ID order.
pub fn turn_tactics(state: &GameState, side: u8) -> Result<Vec<UnitTactics>, TacticsError> {
    if side != state.active_faction {
        return Ok(Vec::new());
    }
    let mut ids: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| {
            (unit.faction == side && (!unit.moved || !unit.attacked)).then_some(id)
        })
        .collect();
    ids.sort_unstable();
    ids.into_iter().map(|id| unit_tactics(state, id)).collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::unit::Unit;

    #[test]
    fn standing_origin_is_not_movable() {
        let mut board = Board::new(4, 4);
        board.set_terrain(Hex::from_offset(0, 0), "flat");
        let mut state = GameState::new(board);
        let unit = Unit::new(1, "fighter", 20, 0);
        state.place_unit(unit, Hex::from_offset(0, 0));
        let tactics = unit_tactics(&state, 1).unwrap();
        assert!(tactics.origins.iter().any(|o| o.current && !o.movable));
        assert!(tactics.origins.iter().filter(|o| o.current).count() == 1);
    }
}
