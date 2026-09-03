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
    pub attacker_max_damage: Vec<AttackerMaxDamage>,
    pub distinct_attacker_count: u32,
    pub max_incoming_sum: u32,
    pub lethal_attackers_needed: Option<u32>,
    pub origins_conflict: bool,
}

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
        threats.sort_by_key(|threat| (threat.attacker_id, threat.origin_row, threat.origin_col));
        let (attacker_max_damage, max_incoming_sum, lethal_attackers_needed, origins_conflict) =
            summarize_threats(recruiter.hp, &threats);
        recruiters.push(RecruiterThreats {
            recruiter_id,
            hp: recruiter.hp,
            col,
            row,
            threats,
            distinct_attacker_count: attacker_max_damage.len() as u32,
            attacker_max_damage,
            max_incoming_sum,
            lethal_attackers_needed,
            origins_conflict,
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
