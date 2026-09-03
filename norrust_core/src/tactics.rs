//! Read-only, engine-owned tactical candidates shared by AI and adapters.

use serde::Serialize;

use crate::combat::{combat_parameters, exact_exchange, tod_label, ExchangeForecast};
use crate::game_state::{apply_action, legal_moves, legal_targets, Action, ActionError, GameState};
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

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RecruiterThreat {
    pub attacker_id: u32,
    pub origin_col: i32,
    pub origin_row: i32,
    pub moved: bool,
    pub forecast: ExchangeForecast,
    pub max_damage: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RecruiterThreats {
    pub recruiter_id: u32,
    pub hp: u32,
    pub col: i32,
    pub row: i32,
    pub threats: Vec<RecruiterThreat>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ThreatSurface {
    pub visibility: &'static str,
    pub projected_time_of_day: &'static str,
    pub recruiters: Vec<RecruiterThreats>,
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

/// Calculate threats to the side's recruiters if it ended its turn now.
///
/// The opponent's policy is intentionally not simulated. The clone advances
/// only through EndTurn, then enumerates every legal opponent move/attack
/// origin and computes exact, non-random exchange forecasts.
pub fn recruiter_threats_after_end_turn(
    state: &GameState,
    side: u8,
) -> Result<ThreatSurface, TacticsError> {
    if side != state.active_faction {
        return Ok(ThreatSurface {
            visibility: "full",
            projected_time_of_day: tod_label(state.turn),
            recruiters: Vec::new(),
        });
    }
    let recruiter_ids: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == side && unit.can_recruit).then_some(id))
        .collect();
    let mut projected = state.clone();
    apply_action(&mut projected, Action::EndTurn)?;
    let mut recruiters = Vec::new();
    for recruiter_id in recruiter_ids {
        let Some(recruiter) = projected.units.get(&recruiter_id) else {
            continue;
        };
        let Some(&hex) = projected.positions.get(&recruiter_id) else {
            continue;
        };
        let (col, row) = hex.to_offset();
        let mut threats = Vec::new();
        let mut attacker_ids: Vec<u32> = projected
            .units
            .iter()
            .filter_map(|(&id, unit)| (unit.faction == projected.active_faction).then_some(id))
            .collect();
        attacker_ids.sort_unstable();
        for attacker_id in attacker_ids {
            let tactics = unit_tactics(&projected, attacker_id)?;
            for origin in tactics.origins {
                let Some(engagement) = origin
                    .engagements
                    .into_iter()
                    .find(|engagement| engagement.defender_id == recruiter_id)
                else {
                    continue;
                };
                let parameters = combat_parameters(
                    &projected,
                    attacker_id,
                    recruiter_id,
                    Hex::from_offset(origin.col, origin.row),
                )?;
                threats.push(RecruiterThreat {
                    attacker_id,
                    origin_col: origin.col,
                    origin_row: origin.row,
                    moved: origin.movable,
                    max_damage: parameters
                        .attacker_damage_per_hit
                        .saturating_mul(parameters.attacker_strikes),
                    forecast: engagement.forecast,
                });
            }
        }
        threats.sort_by_key(|threat| {
            (threat.attacker_id, threat.origin_row, threat.origin_col)
        });
        recruiters.push(RecruiterThreats {
            recruiter_id,
            hp: recruiter.hp,
            col,
            row,
            threats,
        });
    }
    recruiters.sort_by_key(|recruiter| recruiter.recruiter_id);
    Ok(ThreatSurface {
        visibility: "full",
        projected_time_of_day: tod_label(projected.turn),
        recruiters,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::schema::AttackDef;
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

    #[test]
    fn recruiter_threat_includes_exact_origin_and_forecast() {
        let mut board = Board::new(7, 5);
        for col in 0..7 {
            for row in 0..5 {
                board.set_tile(Hex::from_offset(col, row), crate::board::Tile::new("flat"));
            }
        }
        let mut state = GameState::new_seeded(board, 99);
        let mut recruiter = Unit::new(1, "leader", 20, 0);
        recruiter.can_recruit = true;
        state.place_unit(recruiter, Hex::from_offset(2, 2));
        let mut archer = Unit::new(2, "adept", 20, 1);
        archer.movement = 2;
        archer.movement_costs.insert("flat".into(), 1);
        archer.attacks.push(AttackDef {
            id: "bolt".into(),
            name: "bolt".into(),
            damage: 10,
            strikes: 2,
            attack_type: "arcane".into(),
            range: "ranged".into(),
            specials: Vec::new(),
        });
        state.place_unit(archer, Hex::from_offset(4, 2));
        let revision = state.state_revision;
        let result = recruiter_threats_after_end_turn(&state, 0).unwrap();
        let threats = &result.recruiters[0].threats;
        assert!(threats.iter().any(|threat| {
            threat.attacker_id == 2
                && threat.origin_col == 4
                && threat.origin_row == 2
                && !threat.moved
                && threat.max_damage == 20
        }));
        assert_eq!(result.visibility, "full");
        assert_eq!(state.active_faction, 0);
        assert_eq!(state.state_revision, revision);
        assert_eq!(state.turn, 1);
    }
}
