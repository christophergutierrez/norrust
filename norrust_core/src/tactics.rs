//! Read-only, engine-owned tactical candidates shared by AI and adapters.

use std::collections::{HashMap, HashSet};

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
pub struct TargetAttackOption {
    pub attacker_id: u32,
    pub origin_col: i32,
    pub origin_row: i32,
    pub moved: bool,
    pub forecast: ExchangeForecast,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TargetInspection {
    pub target_id: u32,
    pub hp: u32,
    pub col: i32,
    pub row: i32,
    pub terrain: String,
    pub attacks: Vec<TargetAttackOption>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HexAttackOption {
    pub attacker_id: u32,
    pub origin_col: i32,
    pub origin_row: i32,
    pub moved: bool,
    pub max_damage: Option<u32>,
    pub forecast: Option<ExchangeForecast>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HexInspection {
    pub col: i32,
    pub row: i32,
    pub occupant_id: Option<u32>,
    pub attacks: Vec<HexAttackOption>,
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
    pub terrain: String,
    pub threats: Vec<RecruiterThreat>,
    pub attacker_max_damage: Vec<AttackerMaxDamage>,
    pub distinct_attacker_count: u32,
    pub max_incoming_sum: u32,
    pub lethal_attackers_needed: Option<u32>,
    pub origins_conflict: bool,
    pub open_threats: Vec<RecruiterThreat>,
    pub open_attacker_max_damage: Vec<AttackerMaxDamage>,
    pub open_distinct_attacker_count: u32,
    pub open_max_incoming_sum: u32,
    pub open_lethal_attackers_needed: Option<u32>,
    pub open_origins_conflict: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UnitDestinationThreat {
    pub col: i32,
    pub row: i32,
    pub current: bool,
    pub threats: Vec<RecruiterThreat>,
    pub distinct_attacker_count: u32,
    pub max_incoming_sum: u32,
    pub lethal_attackers_needed: Option<u32>,
    pub origins_conflict: bool,
    pub attacker_max_damage: Vec<AttackerMaxDamage>,
    pub open_threats: Vec<RecruiterThreat>,
    pub open_attacker_max_damage: Vec<AttackerMaxDamage>,
    pub open_distinct_attacker_count: u32,
    pub open_max_incoming_sum: u32,
    pub open_lethal_attackers_needed: Option<u32>,
    pub open_origins_conflict: bool,
}

pub type RecruiterDestinationThreat = UnitDestinationThreat;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AttackerMaxDamage {
    pub attacker_id: u32,
    pub max_damage: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ThreatSurface {
    pub visibility: &'static str,
    pub projected_time_of_day: &'static str,
    pub recruiters: Vec<RecruiterThreats>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UnitThreatSummary {
    pub unit_id: u32,
    pub hp: u32,
    pub col: i32,
    pub row: i32,
    pub terrain: String,
    pub distinct_attacker_count: u32,
    pub max_incoming_sum: u32,
    pub lethal_attackers_needed: Option<u32>,
    pub origins_conflict: bool,
    pub open_distinct_attacker_count: u32,
    pub open_max_incoming_sum: u32,
    pub open_lethal_attackers_needed: Option<u32>,
    pub open_origins_conflict: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct UnitThreatSurface {
    pub visibility: &'static str,
    pub projected_time_of_day: &'static str,
    pub units: Vec<UnitThreatSummary>,
}

fn summarize_threats(
    hp: u32,
    threats: &[RecruiterThreat],
) -> (Vec<AttackerMaxDamage>, u32, Option<u32>, bool) {
    let mut maxima = HashMap::<u32, u32>::new();
    let mut moved_origins = HashMap::<(i32, i32), HashSet<u32>>::new();
    for threat in threats {
        maxima
            .entry(threat.attacker_id)
            .and_modify(|damage| *damage = (*damage).max(threat.max_damage))
            .or_insert(threat.max_damage);
        if threat.moved {
            moved_origins
                .entry((threat.origin_col, threat.origin_row))
                .or_default()
                .insert(threat.attacker_id);
        }
    }
    let mut attacker_max_damage = maxima
        .into_iter()
        .map(|(attacker_id, max_damage)| AttackerMaxDamage {
            attacker_id,
            max_damage,
        })
        .collect::<Vec<_>>();
    attacker_max_damage.sort_by_key(|item| item.attacker_id);
    let mut damages = attacker_max_damage
        .iter()
        .map(|item| item.max_damage)
        .collect::<Vec<_>>();
    damages.sort_unstable_by(|left, right| right.cmp(left));
    let max_incoming_sum = damages
        .iter()
        .fold(0u32, |sum, damage| sum.saturating_add(*damage));
    let mut cumulative = 0u32;
    let lethal_attackers_needed = damages.iter().position(|damage| {
        cumulative = cumulative.saturating_add(*damage);
        cumulative >= hp
    });
    (
        attacker_max_damage,
        max_incoming_sum,
        lethal_attackers_needed.map(|index| index as u32 + 1),
        moved_origins.values().any(|attackers| attackers.len() > 1),
    )
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Coordinate {
    pub col: i32,
    pub row: i32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct VacatableCastle {
    pub unit_id: u32,
    pub col: i32,
    pub row: i32,
    pub destinations: Vec<Coordinate>,
}

/// Return current village income and castle occupants that can legally move
/// off castle terrain. This reports facts only; it does not recommend moving.
pub fn economy_facts(
    state: &GameState,
    side: u8,
) -> Result<(u32, Vec<VacatableCastle>), TacticsError> {
    let income = state
        .village_owners
        .values()
        .filter(|&&owner| owner == side as i8)
        .count() as u32
        * 2;
    let mut result = Vec::new();
    let mut ids: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == side && !unit.can_recruit).then_some(id))
        .collect();
    ids.sort_unstable();
    for unit_id in ids {
        let Some(&hex) = state.positions.get(&unit_id) else {
            continue;
        };
        if !state
            .board
            .tile_at(hex)
            .is_some_and(|tile| tile.terrain_id == "castle")
        {
            continue;
        }
        let destinations = legal_moves(state, unit_id)?
            .into_iter()
            .filter(|destination| {
                !state
                    .board
                    .tile_at(*destination)
                    .is_some_and(|tile| tile.terrain_id == "castle")
            })
            .map(|destination| {
                let (col, row) = destination.to_offset();
                Coordinate { col, row }
            })
            .collect::<Vec<_>>();
        if destinations.is_empty() {
            continue;
        }
        let (col, row) = hex.to_offset();
        result.push(VacatableCastle {
            unit_id,
            col,
            row,
            destinations,
        });
    }
    Ok((income, result))
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

/// Invert the active side's tactical surface for one enemy target.
pub fn target_inspection(
    state: &GameState,
    side: u8,
    target_id: u32,
) -> Result<TargetInspection, TacticsError> {
    let target = state
        .units
        .get(&target_id)
        .ok_or(ActionError::UnitNotFound(target_id))?;
    if side != state.active_faction {
        return Err(ActionError::NotYourTurn.into());
    }
    if target.faction == side {
        return Err(ActionError::FriendlyTarget.into());
    }
    let target_hex = *state
        .positions
        .get(&target_id)
        .ok_or(ActionError::UnitNotFound(target_id))?;
    let mut attacks = Vec::new();
    for unit in turn_tactics(state, side)? {
        for origin in unit.origins {
            if let Some(engagement) = origin
                .engagements
                .into_iter()
                .find(|engagement| engagement.defender_id == target_id)
            {
                attacks.push(TargetAttackOption {
                    attacker_id: unit.unit_id,
                    origin_col: origin.col,
                    origin_row: origin.row,
                    moved: origin.movable,
                    forecast: engagement.forecast,
                });
            }
        }
    }
    attacks.sort_by_key(|attack| (attack.attacker_id, attack.origin_row, attack.origin_col));
    let (col, row) = target_hex.to_offset();
    Ok(TargetInspection {
        target_id,
        hp: target.hp,
        col,
        row,
        terrain: state
            .board
            .tile_at(target_hex)
            .map(|tile| tile.terrain_id.clone())
            .unwrap_or_default(),
        attacks,
    })
}

/// Return active-side attack origins that cover one board hex. Forecasts and
/// damage are present only when the hex currently contains an enemy.
pub fn hex_inspection(state: &GameState, hex: Hex) -> Result<HexInspection, TacticsError> {
    if !state.board.contains(hex) {
        return Err(ActionError::DestinationOutOfBounds.into());
    }
    let occupant_id = state.hex_to_unit.get(&hex).copied();
    let occupant_is_enemy = occupant_id.is_some_and(|id| {
        state
            .units
            .get(&id)
            .is_some_and(|unit| unit.faction != state.active_faction)
    });
    let mut attacks = Vec::new();
    for unit in turn_tactics(state, state.active_faction)? {
        let attacker = &state.units[&unit.unit_id];
        for origin in unit.origins {
            let origin_hex = Hex::from_offset(origin.col, origin.row);
            let distance = origin_hex.distance(hex);
            let range = match distance {
                1 => "melee",
                2 => "ranged",
                _ => continue,
            };
            if !attacker.attacks.iter().any(|attack| attack.range == range) {
                continue;
            }
            if occupant_id.is_some() && !occupant_is_enemy {
                continue;
            }
            let (forecast, max_damage) = if let Some(defender_id) = occupant_id {
                let parameters = combat_parameters(state, unit.unit_id, defender_id, origin_hex)?;
                (
                    Some(exact_exchange(&parameters)),
                    Some(
                        parameters
                            .attacker_damage_per_hit
                            .saturating_mul(parameters.attacker_strikes),
                    ),
                )
            } else {
                (None, None)
            };
            attacks.push(HexAttackOption {
                attacker_id: unit.unit_id,
                origin_col: origin.col,
                origin_row: origin.row,
                moved: origin.movable,
                max_damage,
                forecast,
            });
        }
    }
    attacks.sort_by_key(|attack| (attack.attacker_id, attack.origin_row, attack.origin_col));
    let (col, row) = hex.to_offset();
    Ok(HexInspection {
        col,
        row,
        occupant_id,
        attacks,
    })
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
    let mut recruiters = recruiter_ids
        .into_iter()
        .filter_map(|recruiter_id| {
            target_threats_in_projected(&projected, recruiter_id, false).transpose()
        })
        .collect::<Result<Vec<_>, TacticsError>>()?;
    for recruiter in &mut recruiters {
        let Some(open) = target_threats_in_projected(&projected, recruiter.recruiter_id, true)?
        else {
            continue;
        };
        recruiter.open_threats = open.threats;
        recruiter.open_attacker_max_damage = open.attacker_max_damage;
        recruiter.open_distinct_attacker_count = open.distinct_attacker_count;
        recruiter.open_max_incoming_sum = open.max_incoming_sum;
        recruiter.open_lethal_attackers_needed = open.lethal_attackers_needed;
        recruiter.open_origins_conflict = open.origins_conflict;
    }
    recruiters.sort_by_key(|recruiter| recruiter.recruiter_id);
    Ok(ThreatSurface {
        visibility: "full",
        projected_time_of_day: tod_label(projected.turn),
        recruiters,
    })
}

/// Calculate next-opponent-turn exposure for every active-side unit.
///
/// This is a factual aggregate, not a recommendation. Units with no threat in
/// either occupancy model are retained so a consumer can distinguish an empty
/// result from a missing calculation.
pub fn unit_threats_after_end_turn(
    state: &GameState,
    side: u8,
) -> Result<UnitThreatSurface, TacticsError> {
    if side != state.active_faction {
        return Ok(UnitThreatSurface {
            visibility: "full",
            projected_time_of_day: tod_label(state.turn),
            units: Vec::new(),
        });
    }
    let mut target_ids: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == side).then_some(id))
        .collect();
    target_ids.sort_unstable();
    let mut projected = state.clone();
    apply_action(&mut projected, Action::EndTurn)?;
    let projected_time_of_day = tod_label(projected.turn);
    let mut units = Vec::with_capacity(target_ids.len());
    for unit_id in target_ids {
        let Some(direct) = target_threats_in_projected(&projected, unit_id, false)? else {
            continue;
        };
        let Some(open) = target_threats_in_projected(&projected, unit_id, true)? else {
            continue;
        };
        units.push(UnitThreatSummary {
            unit_id,
            hp: direct.hp,
            col: direct.col,
            row: direct.row,
            terrain: direct.terrain,
            distinct_attacker_count: direct.distinct_attacker_count,
            max_incoming_sum: direct.max_incoming_sum,
            lethal_attackers_needed: direct.lethal_attackers_needed,
            origins_conflict: direct.origins_conflict,
            open_distinct_attacker_count: open.distinct_attacker_count,
            open_max_incoming_sum: open.max_incoming_sum,
            open_lethal_attackers_needed: open.lethal_attackers_needed,
            open_origins_conflict: open.origins_conflict,
        });
    }
    Ok(UnitThreatSurface {
        visibility: "full",
        projected_time_of_day,
        units,
    })
}

fn target_threats_in_projected(
    projected: &GameState,
    target_id: u32,
    open_board: bool,
) -> Result<Option<RecruiterThreats>, TacticsError> {
    let Some(target) = projected.units.get(&target_id) else {
        return Ok(None);
    };
    let Some(&hex) = projected.positions.get(&target_id) else {
        return Ok(None);
    };
    let (col, row) = hex.to_offset();
    let terrain = projected
        .board
        .tile_at(hex)
        .map(|tile| tile.terrain_id.clone())
        .unwrap_or_else(|| "unknown".to_string());
    let mut threats = Vec::new();
    let mut attacker_ids: Vec<u32> = projected
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == projected.active_faction).then_some(id))
        .collect();
    attacker_ids.sort_unstable();
    for attacker_id in attacker_ids {
        let open_state;
        let tactics_state = if open_board {
            open_state = open_board_state(projected, attacker_id, target_id);
            &open_state
        } else {
            projected
        };
        let tactics = unit_tactics(tactics_state, attacker_id)?;
        for origin in tactics.origins {
            let Some(engagement) = origin
                .engagements
                .into_iter()
                .find(|engagement| engagement.defender_id == target_id)
            else {
                continue;
            };
            let parameters = combat_parameters(
                tactics_state,
                attacker_id,
                target_id,
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
    threats.sort_by_key(|threat| (threat.attacker_id, threat.origin_row, threat.origin_col));
    let (attacker_max_damage, max_incoming_sum, lethal_attackers_needed, origins_conflict) =
        summarize_threats(target.hp, &threats);
    Ok(Some(RecruiterThreats {
        recruiter_id: target_id,
        hp: target.hp,
        col,
        row,
        terrain,
        threats,
        distinct_attacker_count: attacker_max_damage.len() as u32,
        attacker_max_damage,
        max_incoming_sum,
        lethal_attackers_needed,
        origins_conflict,
        open_threats: Vec::new(),
        open_attacker_max_damage: Vec::new(),
        open_distinct_attacker_count: 0,
        open_max_incoming_sum: 0,
        open_lethal_attackers_needed: None,
        open_origins_conflict: false,
    }))
}

/// Clone a projected board while removing every unit except the examined
/// attacker and target. This is a conservative geometry bound: it answers
/// whether the attacker could reach the target if intervening units moved or
/// died earlier in the opponent turn. It is not an executable opponent plan.
fn open_board_state(projected: &GameState, attacker_id: u32, target_id: u32) -> GameState {
    let mut open = projected.clone();
    open.units
        .retain(|&id, _| id == attacker_id || id == target_id);
    open.positions
        .retain(|&id, _| id == attacker_id || id == target_id);
    open.hex_to_unit
        .retain(|_, id| *id == attacker_id || *id == target_id);
    open
}

/// Report the opponent threat forecast for each legal position of a recruiter.
/// Each position is evaluated independently; no destination is ranked or recommended.
pub fn recruiter_destination_threats(
    state: &GameState,
    recruiter_id: u32,
) -> Result<Vec<RecruiterDestinationThreat>, TacticsError> {
    unit_destination_threats(state, recruiter_id)
}

/// Report opponent threat forecasts for every legal position of an active-side unit.
/// Each position is evaluated independently; no destination is ranked or recommended.
pub fn unit_destination_threats(
    state: &GameState,
    unit_id: u32,
) -> Result<Vec<UnitDestinationThreat>, TacticsError> {
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
    let mut destinations = vec![(current, true)];
    if !unit.moved {
        destinations.extend(
            legal_moves(state, unit_id)?
                .into_iter()
                .map(|hex| (hex, false)),
        );
    }
    let mut result = Vec::with_capacity(destinations.len());
    for (destination, is_current) in destinations {
        let mut projected = state.clone();
        if !is_current {
            apply_action(
                &mut projected,
                Action::Move {
                    unit_id,
                    destination,
                },
            )?;
        }
        apply_action(&mut projected, Action::EndTurn)?;
        let summary = target_threats_in_projected(&projected, unit_id, false)?
            .ok_or(ActionError::UnitNotFound(unit_id))?;
        let open = target_threats_in_projected(&projected, unit_id, true)?
            .ok_or(ActionError::UnitNotFound(unit_id))?;
        let (col, row) = destination.to_offset();
        result.push(UnitDestinationThreat {
            col,
            row,
            current: is_current,
            threats: summary.threats,
            distinct_attacker_count: summary.distinct_attacker_count,
            max_incoming_sum: summary.max_incoming_sum,
            lethal_attackers_needed: summary.lethal_attackers_needed,
            origins_conflict: summary.origins_conflict,
            attacker_max_damage: summary.attacker_max_damage,
            open_threats: open.threats,
            open_attacker_max_damage: open.attacker_max_damage,
            open_distinct_attacker_count: open.distinct_attacker_count,
            open_max_incoming_sum: open.max_incoming_sum,
            open_lethal_attackers_needed: open.lethal_attackers_needed,
            open_origins_conflict: open.origins_conflict,
        });
    }
    result.sort_by_key(|destination| (!destination.current, destination.row, destination.col));
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::schema::AttackDef;
    use crate::unit::Unit;

    #[test]
    fn threat_summary_uses_distinct_attacker_maxima() {
        let forecast = ExchangeForecast {
            outcome_bps: [0, 10_000, 0],
            expected_damage_tenths: [84, 0],
        };
        let threats = vec![
            RecruiterThreat {
                attacker_id: 10,
                origin_col: 3,
                origin_row: 4,
                moved: true,
                forecast: forecast.clone(),
                max_damage: 14,
            },
            RecruiterThreat {
                attacker_id: 10,
                origin_col: 4,
                origin_row: 4,
                moved: true,
                forecast: forecast.clone(),
                max_damage: 14,
            },
            RecruiterThreat {
                attacker_id: 11,
                origin_col: 3,
                origin_row: 4,
                moved: true,
                forecast: forecast.clone(),
                max_damage: 14,
            },
            RecruiterThreat {
                attacker_id: 12,
                origin_col: 5,
                origin_row: 4,
                moved: true,
                forecast,
                max_damage: 14,
            },
        ];

        let (maxima, sum, lethal, conflict) = summarize_threats(38, &threats);
        assert_eq!(
            maxima,
            vec![
                AttackerMaxDamage {
                    attacker_id: 10,
                    max_damage: 14
                },
                AttackerMaxDamage {
                    attacker_id: 11,
                    max_damage: 14
                },
                AttackerMaxDamage {
                    attacker_id: 12,
                    max_damage: 14
                },
            ]
        );
        assert_eq!((sum, lethal, conflict), (42, Some(3), true));
        assert_eq!(summarize_threats(43, &threats).2, None);
    }

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
    fn target_and_hex_inspections_reuse_legal_origins() {
        let mut board = Board::new(5, 5);
        for col in 0..5 {
            for row in 0..5 {
                board.set_tile(Hex::from_offset(col, row), crate::board::Tile::new("flat"));
            }
        }
        let mut state = GameState::new(board);
        let mut archer = Unit::new(1, "archer", 20, 0);
        archer.movement = 1;
        archer.movement_costs.insert("flat".into(), 1);
        archer.attacks.push(AttackDef {
            id: "bow".into(),
            name: "bow".into(),
            damage: 7,
            strikes: 2,
            attack_type: "pierce".into(),
            range: "ranged".into(),
            specials: Vec::new(),
        });
        state.place_unit(archer, Hex::from_offset(0, 2));
        state.place_unit(Unit::new(2, "target", 18, 1), Hex::from_offset(2, 2));

        let target = target_inspection(&state, 0, 2).unwrap();
        assert_eq!(
            (target.col, target.row, target.terrain.as_str()),
            (2, 2, "flat")
        );
        assert!(target.attacks.iter().any(|attack| {
            attack.attacker_id == 1 && attack.origin_col == 0 && attack.origin_row == 2
        }));
        let occupied = hex_inspection(&state, Hex::from_offset(2, 2)).unwrap();
        assert!(occupied
            .attacks
            .iter()
            .any(|attack| attack.forecast.is_some()));

        state.units.remove(&2);
        state.positions.remove(&2);
        state.hex_to_unit.remove(&Hex::from_offset(2, 2));
        let empty = hex_inspection(&state, Hex::from_offset(2, 2)).unwrap();
        assert!(empty.attacks.iter().any(|attack| {
            attack.attacker_id == 1 && attack.forecast.is_none() && attack.max_damage.is_none()
        }));
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

    #[test]
    fn open_board_threat_finds_route_hidden_by_a_screen() {
        let mut board = Board::new(1, 6);
        for row in 0..6 {
            board.set_tile(Hex::from_offset(0, row), crate::board::Tile::new("flat"));
        }
        let mut state = GameState::new_seeded(board, 103);
        let mut recruiter = Unit::new(1, "leader", 20, 0);
        recruiter.can_recruit = true;
        state.place_unit(recruiter, Hex::from_offset(0, 5));
        state.place_unit(Unit::new(3, "screen", 20, 0), Hex::from_offset(0, 2));

        let mut archer = Unit::new(2, "adept", 20, 1);
        archer.movement = 3;
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
        state.place_unit(archer, Hex::from_offset(0, 0));

        let result = recruiter_threats_after_end_turn(&state, 0).unwrap();
        let recruiter = &result.recruiters[0];
        assert!(recruiter.threats.is_empty());
        assert!(recruiter.open_threats.iter().any(|threat| {
            threat.attacker_id == 2
                && threat.origin_col == 0
                && threat.origin_row == 3
                && threat.moved
        }));
        assert_eq!(recruiter.open_distinct_attacker_count, 1);
        assert_eq!(recruiter.open_max_incoming_sum, 20);
        assert_eq!(recruiter.open_lethal_attackers_needed, Some(1));
    }

    #[test]
    fn unit_threat_surface_includes_all_friendly_units() {
        let mut board = Board::new(7, 5);
        for col in 0..7 {
            for row in 0..5 {
                board.set_tile(Hex::from_offset(col, row), crate::board::Tile::new("flat"));
            }
        }
        let mut state = GameState::new_seeded(board, 104);
        let mut recruiter = Unit::new(1, "leader", 20, 0);
        recruiter.can_recruit = true;
        state.place_unit(recruiter, Hex::from_offset(2, 2));
        state.place_unit(Unit::new(3, "fighter", 20, 0), Hex::from_offset(2, 1));
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

        let surface = unit_threats_after_end_turn(&state, 0).unwrap();
        assert_eq!(
            surface
                .units
                .iter()
                .map(|unit| unit.unit_id)
                .collect::<Vec<_>>(),
            vec![1, 3]
        );
        let recruiters = recruiter_threats_after_end_turn(&state, 0).unwrap();
        let leader = surface.units.iter().find(|unit| unit.unit_id == 1).unwrap();
        let recruiter = &recruiters.recruiters[0];
        assert_eq!(
            leader.distinct_attacker_count,
            recruiter.distinct_attacker_count
        );
        assert_eq!(leader.max_incoming_sum, recruiter.max_incoming_sum);
        assert_eq!(
            leader.open_distinct_attacker_count,
            recruiter.open_distinct_attacker_count
        );
    }

    #[test]
    fn recruiter_destination_threats_match_independent_move_projections() {
        let mut board = Board::new(7, 5);
        for col in 0..7 {
            for row in 0..5 {
                board.set_tile(Hex::from_offset(col, row), crate::board::Tile::new("flat"));
            }
        }
        let mut state = GameState::new_seeded(board, 101);
        let mut recruiter = Unit::new(1, "leader", 20, 0);
        recruiter.can_recruit = true;
        recruiter.movement = 1;
        recruiter.movement_costs.insert("flat".into(), 1);
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
        let turn = state.turn;
        let destinations = recruiter_destination_threats(&state, 1).unwrap();
        assert!(destinations.iter().any(|destination| destination.current));
        assert!(destinations.iter().any(|destination| !destination.current));
        for destination in &destinations {
            let mut projected = state.clone();
            if !destination.current {
                apply_action(
                    &mut projected,
                    Action::Move {
                        unit_id: 1,
                        destination: Hex::from_offset(destination.col, destination.row),
                    },
                )
                .unwrap();
            }
            let expected = recruiter_threats_after_end_turn(&projected, 0).unwrap();
            let summary = &expected.recruiters[0];
            assert_eq!(
                destination.distinct_attacker_count,
                summary.distinct_attacker_count
            );
            assert_eq!(destination.max_incoming_sum, summary.max_incoming_sum);
            assert_eq!(
                destination.lethal_attackers_needed,
                summary.lethal_attackers_needed
            );
        }
        assert_eq!(state.state_revision, revision);
        assert_eq!(state.turn, turn);
    }

    #[test]
    fn unit_destination_threats_cover_non_recruiters() {
        let mut board = Board::new(7, 5);
        for col in 0..7 {
            for row in 0..5 {
                board.set_tile(Hex::from_offset(col, row), crate::board::Tile::new("flat"));
            }
        }
        let mut state = GameState::new_seeded(board, 102);
        let mut fighter = Unit::new(1, "fighter", 20, 0);
        fighter.movement = 1;
        fighter.movement_costs.insert("flat".into(), 1);
        state.place_unit(fighter, Hex::from_offset(2, 2));
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

        let destinations = unit_destination_threats(&state, 1).unwrap();
        let current = destinations
            .iter()
            .find(|destination| destination.current)
            .unwrap();
        assert_eq!(current.distinct_attacker_count, 1);
        assert_eq!(current.max_incoming_sum, 20);
        assert_eq!(current.lethal_attackers_needed, Some(1));
        assert!(current
            .threats
            .iter()
            .any(|threat| { threat.attacker_id == 2 && threat.max_damage == 20 }));
        assert!(destinations.iter().any(|destination| !destination.current));
    }

    #[test]
    fn economy_facts_report_income_and_only_movable_non_recruiters() {
        let mut board = Board::new(4, 4);
        for col in 0..4 {
            for row in 0..4 {
                board.set_tile(Hex::from_offset(col, row), crate::board::Tile::new("flat"));
            }
        }
        board.set_tile(Hex::from_offset(1, 1), crate::board::Tile::new("castle"));
        let mut state = GameState::new(board);
        state.village_owners.insert(Hex::from_offset(0, 0), 0);
        let mut unit = Unit::new(2, "skeleton", 10, 0);
        unit.movement = 1;
        unit.movement_costs.insert("flat".into(), 1);
        state.place_unit(unit, Hex::from_offset(1, 1));
        let (income, vacatable) = economy_facts(&state, 0).unwrap();
        assert_eq!(income, 2);
        assert_eq!(vacatable.len(), 1);
        assert_eq!(vacatable[0].unit_id, 2);
        assert!(vacatable[0]
            .destinations
            .iter()
            .all(|destination| destination.col != 1 || destination.row != 1));
    }
}
