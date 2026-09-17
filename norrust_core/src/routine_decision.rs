//! Bounded tactical choices for current-state contact decisions.

use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::game_state::{
    apply_action, legal_moves_with_costs, legal_targets, Action, ActionError, GameState,
};
use crate::hex::Hex;
use crate::tactics::{
    recruiter_threats_after_end_turn, target_threats_in_projected, unit_tactics,
    unit_threats_after_end_turn, TacticsError,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct CoordinateOffset {
    pub col: i32,
    pub row: i32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TacticalCombatForecast {
    pub kill_chance_bps: u32,
    pub expected_damage_dealt_tenths: u32,
    pub expected_damage_received_tenths: u32,
    pub outcome_bps: [u32; 3],
    pub expected_damage_tenths: [u32; 2],
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TacticalExposureFacts {
    pub distinct_attacker_count: u32,
    pub max_incoming_damage: u32,
    pub expected_incoming_damage_tenths: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TacticalOption {
    pub option_id: String,
    pub category: String,
    pub actor_id: u32,
    pub target_id: Option<u32>,
    pub actions: Vec<Value>,
    pub movement_cost: u32,
    pub destination: Option<CoordinateOffset>,
    pub forecast: Option<TacticalCombatForecast>,
    pub exposure: Option<TacticalExposureFacts>,
    pub coverage: String,
    /// Whether this option's destination reduces terrain-cost path distance
    /// to the active objective target. `None` when the objective target is
    /// unknown or unreachable. Absent from the wire format when `None`, so
    /// current-state options (which never set this) serialize unchanged.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub advances_objective: Option<bool>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TacticalDecisionFacts {
    /// Selected actor IDs in priority order, length 0–3.
    pub actor_ids: Vec<u32>,
    /// Distinct eligible actors before the three-actor cap.
    pub eligible_actor_count: u32,
    /// True iff `eligible_actor_count` exceeds `actor_ids.len()`.
    pub actors_truncated: bool,
    pub options: Vec<TacticalOption>,
    pub options_truncated: bool,
    /// Present only when no selected actor has an executable offered action.
    /// Availability is independent of tactical-option enumeration coverage.
    pub options_empty_reason: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ContactActionability {
    Actionable,
    Exhausted,
    Unknown,
}

impl ContactActionability {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Actionable => "actionable",
            Self::Exhausted => "exhausted",
            Self::Unknown => "unknown",
        }
    }
}

const MAX_SELECTED_ACTORS: usize = 3;

struct ActorGeneratedOptions {
    options: Vec<TacticalOption>,
    truncated: bool,
}

pub(crate) fn has_executable_attack(
    state: &GameState,
    actor_id: u32,
) -> Result<bool, TacticsError> {
    let actor = state
        .units
        .get(&actor_id)
        .ok_or(ActionError::UnitNotFound(actor_id))?;
    if actor.faction != state.active_faction || actor.attacked {
        return Ok(false);
    }
    let current = *state
        .positions
        .get(&actor_id)
        .ok_or(ActionError::UnitNotFound(actor_id))?;

    // A unit that already moved can still attack from its current hex.
    for defender_id in legal_targets(state, actor_id, current)? {
        let mut sim = state.clone();
        if apply_action(
            &mut sim,
            Action::Attack {
                attacker_id: actor_id,
                defender_id,
            },
        )
        .is_ok()
        {
            return Ok(true);
        }
    }
    if actor.moved {
        return Ok(false);
    }

    // Stop at the first executable move/attack pair. Eligibility does not
    // build forecasts or exposure-ranked menus for every threatened unit.
    let destinations = legal_moves_with_costs(state, actor_id)?;
    for destination in destinations.keys().copied() {
        let mut sim = state.clone();
        if apply_action(
            &mut sim,
            Action::Move {
                unit_id: actor_id,
                destination,
            },
        )
        .is_err()
        {
            continue;
        }
        for defender_id in legal_targets(&sim, actor_id, destination)? {
            let mut attack_sim = sim.clone();
            if apply_action(
                &mut attack_sim,
                Action::Attack {
                    attacker_id: actor_id,
                    defender_id,
                },
            )
            .is_ok()
            {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

pub(crate) fn has_executable_relocation(
    state: &GameState,
    actor_id: u32,
) -> Result<bool, TacticsError> {
    let actor = state
        .units
        .get(&actor_id)
        .ok_or(ActionError::UnitNotFound(actor_id))?;
    if actor.faction != state.active_faction || actor.moved {
        return Ok(false);
    }
    for destination in legal_moves_with_costs(state, actor_id)?.keys().copied() {
        let mut sim = state.clone();
        if apply_action(
            &mut sim,
            Action::Move {
                unit_id: actor_id,
                destination,
            },
        )
        .is_ok()
        {
            return Ok(true);
        }
    }
    Ok(false)
}

pub(crate) fn has_executable_options(
    state: &GameState,
    actor_id: u32,
) -> Result<bool, TacticsError> {
    // Moving is cheaper to establish and remains available after an attack.
    Ok(has_executable_relocation(state, actor_id)? || has_executable_attack(state, actor_id)?)
}

/// Per-involved-unit executable-option flags, before any option menu is built.
/// Missing units or legality errors are incomplete facts, not exhaustion.
pub(crate) fn involved_option_flags(
    state: &GameState,
    involved_ids: &[u32],
) -> Option<Vec<(u32, bool)>> {
    let mut flags = Vec::with_capacity(involved_ids.len());
    for &id in involved_ids {
        match has_executable_options(state, id) {
            Ok(actionable) => flags.push((id, actionable)),
            Err(_) => return None,
        }
    }
    Some(flags)
}

pub(crate) fn actionability_from_flags(flags: &[(u32, bool)]) -> ContactActionability {
    if flags.iter().any(|(_, actionable)| *actionable) {
        ContactActionability::Actionable
    } else {
        ContactActionability::Exhausted
    }
}

/// Enumerate eligible friendly actors once, in priority order:
/// 1. Threatened recruiters by ID
/// 2. Other threatened friendlies by ID
/// 3. Remaining friendlies with executable attack opportunities by ID
///
/// Actors are deduplicated. Eligibility uses legality helpers and does not
/// generate forecasts or ranked menus for every unit.
pub fn select_eligible_actors(state: &GameState, side: u8) -> Result<Vec<u32>, TacticsError> {
    let mut eligible = Vec::new();
    let mut seen = HashSet::new();

    let recruiter_surface = recruiter_threats_after_end_turn(state, side)?;
    let mut threatened_recruiters: Vec<u32> = recruiter_surface
        .recruiters
        .into_iter()
        .filter(|r| r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0)
        .map(|r| r.recruiter_id)
        .collect();
    threatened_recruiters.sort_unstable();
    for actor_id in threatened_recruiters {
        if !seen.insert(actor_id) {
            continue;
        }
        if has_executable_options(state, actor_id)? {
            eligible.push(actor_id);
        }
    }

    let unit_surface = unit_threats_after_end_turn(state, side)?;
    let mut threatened_units: Vec<u32> = unit_surface
        .units
        .into_iter()
        .filter(|u| u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0)
        .map(|u| u.unit_id)
        .collect();
    threatened_units.sort_unstable();
    for actor_id in threatened_units {
        if !seen.insert(actor_id) {
            continue;
        }
        if has_executable_options(state, actor_id)? {
            eligible.push(actor_id);
        }
    }

    let mut attack_units: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == side && !unit.attacked).then_some(id))
        .collect();
    attack_units.sort_unstable();
    for actor_id in attack_units {
        if !seen.insert(actor_id) {
            continue;
        }
        if has_executable_attack(state, actor_id)? {
            eligible.push(actor_id);
        }
    }

    Ok(eligible)
}

/// Offered menu for proven exhausted current-state contact: no automatic
/// outside-unit rescue search. Empty actor IDs describe this menu, not the
/// army's legal movers. Custom `act` remains available in Python.
pub(crate) fn exhausted_contact_menu_facts() -> TacticalDecisionFacts {
    TacticalDecisionFacts {
        actor_ids: Vec::new(),
        eligible_actor_count: 0,
        actors_truncated: false,
        options: Vec::new(),
        options_truncated: false,
        options_empty_reason: Some("exhausted_contact_no_automatic_rescue_menu".to_string()),
    }
}

fn empty_tactical_facts() -> TacticalDecisionFacts {
    TacticalDecisionFacts {
        actor_ids: Vec::new(),
        eligible_actor_count: 0,
        actors_truncated: false,
        options: Vec::new(),
        options_truncated: false,
        options_empty_reason: Some("no_executable_options".to_string()),
    }
}

fn generate_options_for_selected_actors(
    state: &GameState,
    selected: impl IntoIterator<Item = u32>,
    eligible_actor_count: u32,
) -> Result<TacticalDecisionFacts, TacticsError> {
    let mut actor_ids = Vec::new();
    let mut options = Vec::new();
    let mut options_truncated = false;
    for actor_id in selected.into_iter().take(MAX_SELECTED_ACTORS) {
        let generated = generate_actor_options(state, actor_id)?;
        if generated.options.is_empty() {
            continue;
        }
        options_truncated |= generated.truncated;
        options.extend(generated.options);
        actor_ids.push(actor_id);
    }

    if actor_ids.is_empty() {
        return Ok(TacticalDecisionFacts {
            eligible_actor_count,
            actors_truncated: eligible_actor_count > 0,
            ..empty_tactical_facts()
        });
    }

    Ok(TacticalDecisionFacts {
        actors_truncated: eligible_actor_count as usize > actor_ids.len(),
        actor_ids,
        eligible_actor_count,
        options_empty_reason: None,
        options,
        options_truncated,
    })
}

/// Generate at most 4 bounded tactical options (up to 2 attacks, up to 2 relocations)
/// for each of at most three selected eligible actors.
pub fn generate_tactical_options(
    state: &GameState,
    side: u8,
) -> Result<TacticalDecisionFacts, TacticsError> {
    let eligible = select_eligible_actors(state, side)?;
    let eligible_actor_count = eligible.len() as u32;
    if eligible.is_empty() {
        return Ok(empty_tactical_facts());
    }
    generate_options_for_selected_actors(state, eligible, eligible_actor_count)
}

fn compute_origin_exposure(
    state: &GameState,
    actor_id: u32,
    origin_hex: Hex,
) -> Result<Option<TacticalExposureFacts>, TacticsError> {
    let mut sim = state.clone();
    let current_pos = state.positions.get(&actor_id).copied();
    if current_pos != Some(origin_hex) {
        if apply_action(
            &mut sim,
            Action::Move {
                unit_id: actor_id,
                destination: origin_hex,
            },
        )
        .is_err()
        {
            return Ok(None);
        }
    }
    if apply_action(&mut sim, Action::EndTurn).is_err() {
        return Ok(None);
    }
    let summary = match target_threats_in_projected(&sim, actor_id, false)? {
        Some(s) => s,
        None => return Ok(None),
    };
    let distinct_attackers = summary.distinct_attacker_count;
    let max_incoming = summary.max_incoming_sum;
    let expected_incoming = summary
        .focus_expected_damage_tenths
        .iter()
        .copied()
        .max()
        .unwrap_or(0);
    Ok(Some(TacticalExposureFacts {
        distinct_attacker_count: distinct_attackers,
        max_incoming_damage: max_incoming,
        expected_incoming_damage_tenths: expected_incoming,
    }))
}

fn generate_actor_options(
    state: &GameState,
    actor_id: u32,
) -> Result<ActorGeneratedOptions, TacticsError> {
    let actor = state
        .units
        .get(&actor_id)
        .ok_or(ActionError::UnitNotFound(actor_id))?;

    // --- Attack Options ---
    let mut attack_candidates = Vec::new();
    if !actor.attacked {
        let tactics = unit_tactics(state, actor_id)?;
        let costs = if !actor.moved {
            legal_moves_with_costs(state, actor_id).unwrap_or_default()
        } else {
            HashMap::new()
        };

        for origin in tactics.origins {
            let origin_hex = Hex::from_offset(origin.col, origin.row);
            for engagement in origin.engagements {
                let engine_actions = if origin.current {
                    vec![Action::Attack {
                        attacker_id: actor_id,
                        defender_id: engagement.defender_id,
                    }]
                } else {
                    vec![
                        Action::Move {
                            unit_id: actor_id,
                            destination: origin_hex,
                        },
                        Action::Attack {
                            attacker_id: actor_id,
                            defender_id: engagement.defender_id,
                        },
                    ]
                };

                let wire_actions = if origin.current {
                    vec![json!({
                        "action": "Attack",
                        "attacker_id": actor_id,
                        "defender_id": engagement.defender_id,
                    })]
                } else {
                    vec![
                        json!({
                            "action": "Move",
                            "unit_id": actor_id,
                            "col": origin.col,
                            "row": origin.row,
                        }),
                        json!({
                            "action": "Attack",
                            "attacker_id": actor_id,
                            "defender_id": engagement.defender_id,
                        }),
                    ]
                };

                // Legality check on cloned state
                let mut sim = state.clone();
                let mut valid = true;
                for a in &engine_actions {
                    if apply_action(&mut sim, a.clone()).is_err() {
                        valid = false;
                        break;
                    }
                }
                if !valid {
                    continue;
                }

                let movement_cost = if origin.current {
                    0
                } else {
                    costs.get(&origin_hex).copied().unwrap_or(0)
                };
                let kill_bps = engagement.forecast.outcome_bps[0];
                let expected_damage_dealt = engagement.forecast.expected_damage_tenths[0];
                let expected_damage_received = engagement.forecast.expected_damage_tenths[1];

                attack_candidates.push((
                    kill_bps,
                    expected_damage_dealt,
                    engagement.defender_id,
                    origin.row,
                    origin.col,
                    wire_actions,
                    movement_cost,
                    TacticalCombatForecast {
                        kill_chance_bps: kill_bps,
                        expected_damage_dealt_tenths: expected_damage_dealt,
                        expected_damage_received_tenths: expected_damage_received,
                        outcome_bps: engagement.forecast.outcome_bps,
                        expected_damage_tenths: engagement.forecast.expected_damage_tenths,
                    },
                    origin_hex,
                ));
            }
        }
    }

    // Rank attack candidates:
    // target kill probability (descending), expected damage (descending),
    // target_id (ascending), origin_row (ascending), origin_col (ascending)
    attack_candidates.sort_by(|a, b| {
        b.0.cmp(&a.0)
            .then_with(|| b.1.cmp(&a.1))
            .then_with(|| a.2.cmp(&b.2))
            .then_with(|| a.3.cmp(&b.3))
            .then_with(|| a.4.cmp(&b.4))
    });

    attack_candidates.dedup_by(|a, b| a.5 == b.5);
    let top_attacks: Vec<_> = attack_candidates.into_iter().take(2).collect();

    // --- Relocation Options ---
    let mut evaluated_relocations = Vec::new();
    let mut options_truncated = false;

    if !actor.moved {
        let costs_map = legal_moves_with_costs(state, actor_id).unwrap_or_default();
        let mut destination_candidates: Vec<(Hex, u32)> = costs_map.into_iter().collect();

        // Sort candidates by movement cost ascending, then row ascending, then col ascending
        destination_candidates.sort_by(|(hex_a, cost_a), (hex_b, cost_b)| {
            let (col_a, row_a) = hex_a.to_offset();
            let (col_b, row_b) = hex_b.to_offset();
            cost_a
                .cmp(cost_b)
                .then_with(|| row_a.cmp(&row_b))
                .then_with(|| col_a.cmp(&col_b))
        });

        if destination_candidates.len() > 16 {
            options_truncated = true;
            destination_candidates.truncate(16);
        }

        for (dest_hex, cost) in destination_candidates {
            let (dest_col, dest_row) = dest_hex.to_offset();
            let engine_action = Action::Move {
                unit_id: actor_id,
                destination: dest_hex,
            };
            let wire_actions = vec![json!({
                "action": "Move",
                "unit_id": actor_id,
                "col": dest_col,
                "row": dest_row,
            })];

            let mut sim = state.clone();
            if apply_action(&mut sim, engine_action).is_err() {
                continue;
            }
            if apply_action(&mut sim, Action::EndTurn).is_err() {
                continue;
            }

            let summary = match target_threats_in_projected(&sim, actor_id, false)? {
                Some(s) => s,
                None => continue,
            };

            let distinct_attackers = summary.distinct_attacker_count;
            let max_incoming = summary.max_incoming_sum;
            // The focus vectors have fixed one-, two-, and three-attacker
            // slots. Unsupported larger slots are padded with zero, so the
            // last slot is not the aggregate for this relocation. Use the
            // greatest supported value and keep a genuine one-attacker
            // exposure (for example [84, 0, 0]) visible to the ranking.
            let expected_incoming = summary
                .focus_expected_damage_tenths
                .iter()
                .copied()
                .max()
                .unwrap_or(0);

            evaluated_relocations.push((
                expected_incoming,
                max_incoming,
                cost,
                dest_row,
                dest_col,
                wire_actions,
                CoordinateOffset {
                    col: dest_col,
                    row: dest_row,
                },
                TacticalExposureFacts {
                    distinct_attacker_count: distinct_attackers,
                    max_incoming_damage: max_incoming,
                    expected_incoming_damage_tenths: expected_incoming,
                },
            ));
        }

        // Rank relocation candidates:
        // lower projected incoming damage (ascending), movement cost (ascending),
        // row (ascending), col (ascending)
        evaluated_relocations.sort_by(|a, b| {
            a.0.cmp(&b.0)
                .then_with(|| a.1.cmp(&b.1))
                .then_with(|| a.2.cmp(&b.2))
                .then_with(|| a.3.cmp(&b.3))
                .then_with(|| a.4.cmp(&b.4))
        });
    }

    let top_relocations: Vec<_> = evaluated_relocations.into_iter().take(2).collect();

    // --- Combine into up to 4 options ---
    let mut options = Vec::with_capacity(top_attacks.len() + top_relocations.len());

    let is_recruiter = crate::routine::is_recruiter(actor);
    let mut origin_exposure_cache: HashMap<Hex, Option<TacticalExposureFacts>> = HashMap::new();

    for (i, atk) in top_attacks.into_iter().enumerate() {
        let exposure = if is_recruiter {
            let origin_hex = atk.8;
            if let Some(cached) = origin_exposure_cache.get(&origin_hex) {
                cached.clone()
            } else {
                let computed = compute_origin_exposure(state, actor_id, origin_hex)?;
                origin_exposure_cache.insert(origin_hex, computed.clone());
                computed
            }
        } else {
            None
        };
        options.push(TacticalOption {
            option_id: format!("u{actor_id}-attack-{}", i + 1),
            category: "attack".to_string(),
            actor_id,
            target_id: Some(atk.2),
            actions: atk.5,
            movement_cost: atk.6,
            destination: None,
            forecast: Some(atk.7),
            exposure,
            coverage: "complete".to_string(),
            advances_objective: None,
        });
    }

    for (i, reloc) in top_relocations.into_iter().enumerate() {
        options.push(TacticalOption {
            option_id: format!("u{actor_id}-relocate-{}", i + 1),
            category: "relocation".to_string(),
            actor_id,
            target_id: None,
            actions: reloc.5,
            movement_cost: reloc.2,
            destination: Some(reloc.6),
            forecast: None,
            exposure: Some(reloc.7),
            coverage: "complete".to_string(),
            advances_objective: None,
        });
    }

    Ok(ActorGeneratedOptions {
        options,
        truncated: options_truncated,
    })
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RecruiterThreatFacts {
    pub recruiter_id: u32,
    pub hp: u32,
    pub max_hp: u32,
    pub distinct_attacker_count: u32,
    pub open_distinct_attacker_count: u32,
    pub max_incoming_damage: u32,
    pub expected_incoming_damage_tenths: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ThreatenedRecruiterTacticalFacts {
    pub recruiter: RecruiterThreatFacts,
    pub actor_ids: Vec<u32>,
    pub eligible_actor_count: u32,
    pub actors_truncated: bool,
    pub options: Vec<TacticalOption>,
    pub options_truncated: bool,
    pub options_empty_reason: Option<String>,
}

/// Bounded tactical options for a threatened live friendly recruiter during
/// policy maintenance (e.g., `invalid_assignment`).
///
/// Identifies live friendly recruiters with known next-opponent exposure. If
/// any has executable actions, selects ONE recruiter (by deterministic ascending ID)
/// and generates at most 4 tactical options (<= 2 attacks, <= 2 relocations).
/// If threatened recruiters exist but none can act, reports explicit no-options
/// coverage (`exhausted_recruiter_no_tactical_options`). Returns `Ok(None)` if
/// no friendly recruiter is threatened.
pub fn generate_threatened_recruiter_options(
    state: &GameState,
    side: u8,
) -> Result<Option<ThreatenedRecruiterTacticalFacts>, TacticsError> {
    let surface = recruiter_threats_after_end_turn(state, side)?;
    let mut threatened: Vec<&crate::tactics::RecruiterThreats> = surface
        .recruiters
        .iter()
        .filter(|r| r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0)
        .collect();
    if threatened.is_empty() {
        return Ok(None);
    }
    threatened.sort_by_key(|r| r.recruiter_id);

    let mut actionable = Vec::new();
    for r in &threatened {
        if has_executable_options(state, r.recruiter_id)? {
            actionable.push(*r);
        }
    }

    if actionable.is_empty() {
        let first = threatened[0];
        let max_hp = state
            .units
            .get(&first.recruiter_id)
            .map(|u| u.max_hp)
            .unwrap_or(first.hp);
        let expected_incoming = first
            .focus_expected_damage_tenths
            .iter()
            .copied()
            .max()
            .unwrap_or(0);
        return Ok(Some(ThreatenedRecruiterTacticalFacts {
            recruiter: RecruiterThreatFacts {
                recruiter_id: first.recruiter_id,
                hp: first.hp,
                max_hp,
                distinct_attacker_count: first.distinct_attacker_count,
                open_distinct_attacker_count: first.open_distinct_attacker_count,
                max_incoming_damage: first.max_incoming_sum,
                expected_incoming_damage_tenths: expected_incoming,
            },
            actor_ids: Vec::new(),
            eligible_actor_count: 0,
            actors_truncated: false,
            options: Vec::new(),
            options_truncated: false,
            options_empty_reason: Some("exhausted_recruiter_no_tactical_options".to_string()),
        }));
    }

    let chosen = actionable[0];
    let eligible_actor_count = actionable.len() as u32;
    let actors_truncated = eligible_actor_count > 1;
    let generated = generate_actor_options(state, chosen.recruiter_id)?;
    let max_hp = state
        .units
        .get(&chosen.recruiter_id)
        .map(|u| u.max_hp)
        .unwrap_or(chosen.hp);
    let expected_incoming = chosen
        .focus_expected_damage_tenths
        .iter()
        .copied()
        .max()
        .unwrap_or(0);

    Ok(Some(ThreatenedRecruiterTacticalFacts {
        recruiter: RecruiterThreatFacts {
            recruiter_id: chosen.recruiter_id,
            hp: chosen.hp,
            max_hp,
            distinct_attacker_count: chosen.distinct_attacker_count,
            open_distinct_attacker_count: chosen.open_distinct_attacker_count,
            max_incoming_damage: chosen.max_incoming_sum,
            expected_incoming_damage_tenths: expected_incoming,
        },
        actor_ids: vec![chosen.recruiter_id],
        eligible_actor_count,
        actors_truncated,
        options: generated.options,
        options_truncated: generated.truncated,
        options_empty_reason: None,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Tile};
    use crate::loader::Registry;
    use crate::schema::UnitDef;
    use crate::tactics::{recruiter_threats_after_end_turn, unit_threats_after_end_turn};
    use crate::unit::Unit;
    use std::path::PathBuf;

    fn units() -> Registry<UnitDef> {
        Registry::load_from_dir(
            &PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .join("data/units"),
        )
        .unwrap()
    }

    fn test_state() -> GameState {
        let mut b = Board::new(10, 8);
        for r in 0..8 {
            for c in 0..10 {
                b.set_tile(Hex::from_offset(c, r), Tile::new("flat"));
            }
        }
        let k = Hex::from_offset(1, 1);
        b.set_tile(k, Tile::new("keep"));
        for h in k.neighbors() {
            if b.contains(h) {
                b.set_tile(h, Tile::new("castle"));
            }
        }
        let mut s = GameState::new(b);
        s.gold = [1000, 1000];
        let mut l = Unit::new(1, "Leader", 30, 0);
        l.can_recruit = true;
        s.place_unit(l, k);
        s
    }

    fn large_test_state() -> GameState {
        let mut b = Board::new(25, 25);
        for r in 0..25 {
            for c in 0..25 {
                b.set_tile(Hex::from_offset(c, r), Tile::new("flat"));
            }
        }
        let k = Hex::from_offset(0, 0);
        b.set_tile(k, Tile::new("keep"));
        let mut s = GameState::new(b);
        s.gold = [1000, 1000];
        let mut l = Unit::new(1, "Leader", 30, 0);
        l.can_recruit = true;
        s.place_unit(l, k);
        s
    }

    #[test]
    fn test_primary_actor_threatened_recruiter_first() {
        let registry = units();
        let mut s = test_state();

        // Lower-ID friendly unit 2 and its attacker.
        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(4, 4));

        // A second threatened recruiter has a higher ID than unit 2.
        let second_keep = Hex::from_offset(8, 1);
        s.board.set_tile(second_keep, Tile::new("keep"));
        for hex in second_keep.neighbors() {
            if s.board.contains(hex) {
                s.board.set_tile(hex, Tile::new("castle"));
            }
        }
        let mut second_recruiter = Unit::from_def(50, registry.get("Dark Sorcerer").unwrap(), 0);
        second_recruiter.can_recruit = true;
        s.place_unit(second_recruiter, second_keep);
        let e1 = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(8, 2));

        // Enemy threatening lower-ID unit 2: placed at (4, 5)
        let e2 = Unit::from_def(8, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e2, Hex::from_offset(4, 5));

        let actors = select_eligible_actors(&s, 0).unwrap();
        assert_eq!(
            actors.first().copied(),
            Some(50),
            "recruiter priority beats lower-ID friends"
        );
        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids.first().copied(), Some(50));
        assert!(!facts.actor_ids.is_empty());
        assert_eq!(facts.eligible_actor_count as usize, actors.len());
        assert_eq!(facts.actors_truncated, actors.len() > facts.actor_ids.len());
    }

    #[test]
    fn test_primary_actor_lowest_id_threatened_friendly() {
        let registry = units();
        let mut s = large_test_state();

        // Recruiter is safe at (0, 0) far away from enemies at (15, 15).
        // Friendly unit 4 at (15, 14)
        let f4 = Unit::from_def(4, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f4, Hex::from_offset(15, 14));

        // Friendly unit 2 at (18, 14)
        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(18, 14));

        // Enemy threatening unit 4 at (15, 15)
        let e1 = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(15, 15));

        // Enemy threatening unit 2 at (18, 15)
        let e2 = Unit::from_def(8, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e2, Hex::from_offset(18, 15));

        let actors = select_eligible_actors(&s, 0).unwrap();
        assert_eq!(
            actors.first().copied(),
            Some(2),
            "lowest-ID threatened unit must be chosen"
        );
        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids, vec![2, 4]);
        assert_eq!(facts.eligible_actor_count, 2);
        assert!(!facts.actors_truncated);
    }

    #[test]
    fn exhausted_low_id_threatened_unit_is_skipped_without_dropping_threat_facts() {
        let registry = units();
        let mut s = large_test_state();

        let mut exhausted = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        exhausted.moved = true;
        s.place_unit(exhausted, Hex::from_offset(15, 14));
        let actionable = Unit::from_def(6, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(actionable, Hex::from_offset(18, 14));

        let first_enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        // Close enough to threaten after moving, but not a standing target
        // for the moved unit on the current board.
        s.place_unit(first_enemy, Hex::from_offset(15, 17));
        let second_enemy = Unit::from_def(8, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(second_enemy, Hex::from_offset(18, 15));

        let facts = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(facts.friendly_unit_ids, vec![5, 6]);
        assert_eq!(facts.actor_ids, vec![6]);
        assert_eq!(facts.eligible_actor_count, 1);
        assert!(!facts.actors_truncated);
        assert!(!facts.options.is_empty());
        assert_eq!(facts.options_empty_reason, None);
    }

    #[test]
    fn moved_threatened_unit_with_adjacent_attack_remains_eligible() {
        let registry = units();
        let mut s = large_test_state();
        let mut moved = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        moved.moved = true;
        s.place_unit(moved, Hex::from_offset(15, 14));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(15, 15));

        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids, vec![2]);
        assert_eq!(facts.eligible_actor_count, 1);
        assert!(!facts.actors_truncated);
        assert!(facts
            .options
            .iter()
            .any(|option| option.category == "attack"));
        assert!(!facts.options.is_empty());
    }

    #[test]
    fn attacked_threatened_unit_with_remaining_move_remains_eligible() {
        let registry = units();
        let mut s = large_test_state();
        let mut attacked = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        attacked.attacked = true;
        s.place_unit(attacked, Hex::from_offset(15, 14));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(15, 15));

        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids, vec![2]);
        assert_eq!(facts.eligible_actor_count, 1);
        assert!(!facts.actors_truncated);
        assert!(facts
            .options
            .iter()
            .any(|option| option.category == "relocation"));
    }

    fn exhaust_unit(unit: &mut Unit) {
        unit.moved = true;
        unit.attacked = true;
    }

    #[test]
    fn all_exhausted_contact_has_explicit_empty_options_reason_and_complete_coverage() {
        let registry = units();
        let mut s = large_test_state();
        exhaust_unit(s.units.get_mut(&1).unwrap());
        for (friendly_id, enemy_id, friendly_hex, enemy_hex) in
            [(5, 7, (15, 14), (15, 15)), (6, 8, (18, 14), (18, 15))]
        {
            let mut friendly = Unit::from_def(friendly_id, registry.get("Skeleton").unwrap(), 0);
            exhaust_unit(&mut friendly);
            s.place_unit(friendly, Hex::from_offset(friendly_hex.0, friendly_hex.1));
            let enemy = Unit::from_def(enemy_id, registry.get("Skeleton").unwrap(), 1);
            s.place_unit(enemy, Hex::from_offset(enemy_hex.0, enemy_hex.1));
        }

        let facts = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(facts.friendly_unit_ids, vec![5, 6]);
        assert!(!facts.friendly_unit_ids.contains(&1));
        assert!(facts.actor_ids.is_empty());
        assert_eq!(facts.eligible_actor_count, 0);
        assert!(!facts.actors_truncated);
        assert!(facts.options.is_empty());
        assert_eq!(
            facts.options_empty_reason.as_deref(),
            Some("exhausted_contact_no_automatic_rescue_menu")
        );
        assert!(!facts.options_truncated);
        assert_eq!(facts.coverage, "complete");
        assert_eq!(facts.contact_actionability, "exhausted");
        assert!(facts.contact_state_key.as_ref().unwrap().len() == 64);
    }

    #[test]
    fn exhausted_involved_does_not_enumerate_outside_helpers() {
        let registry = units();
        let mut s = large_test_state();
        exhaust_unit(s.units.get_mut(&1).unwrap());
        for (friendly_id, enemy_id, friendly_hex, enemy_hex) in
            [(5, 7, (15, 14), (15, 15)), (6, 8, (18, 14), (18, 15))]
        {
            let mut friendly = Unit::from_def(friendly_id, registry.get("Skeleton").unwrap(), 0);
            exhaust_unit(&mut friendly);
            s.place_unit(friendly, Hex::from_offset(friendly_hex.0, friendly_hex.1));
            let enemy = Unit::from_def(enemy_id, registry.get("Skeleton").unwrap(), 1);
            s.place_unit(enemy, Hex::from_offset(enemy_hex.0, enemy_hex.1));
        }
        let helper = Unit::from_def(20, registry.get("Ghost").unwrap(), 0);
        s.place_unit(helper, Hex::from_offset(24, 24));

        let facts = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(facts.friendly_unit_ids, vec![5, 6]);
        assert!(!facts.friendly_unit_ids.contains(&20));
        assert_eq!(facts.contact_actionability, "exhausted");
        assert!(facts.actor_ids.is_empty());
        assert_eq!(facts.eligible_actor_count, 0);
        assert!(!facts.actors_truncated);
        assert!(facts.options.is_empty());
        assert!(!facts.options_truncated);
        assert_eq!(
            facts.options_empty_reason.as_deref(),
            Some("exhausted_contact_no_automatic_rescue_menu")
        );
        assert_ne!(
            facts.options_empty_reason.as_deref(),
            Some("no_executable_options")
        );
        assert!(facts.contact_state_key.is_some());
    }

    #[test]
    fn recruiter_with_adjacent_attack_remains_actionable() {
        let registry = units();
        let mut s = large_test_state();
        let keep = Hex::from_offset(0, 0);
        s.units.remove(&1);
        s.positions.remove(&1);
        s.hex_to_unit.remove(&keep);
        let mut recruiter = Unit::from_def(1, registry.get("Dark Sorcerer").unwrap(), 0);
        recruiter.can_recruit = true;
        s.place_unit(recruiter, keep);
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(1, 0));
        let facts = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(facts.contact_actionability, "actionable");
        assert!(facts.actor_ids.contains(&1));
        let atk_opt = facts
            .options
            .iter()
            .find(|option| option.actor_id == 1 && option.category == "attack")
            .unwrap();
        assert!(atk_opt.exposure.is_some());
        let exposure = atk_opt.exposure.as_ref().unwrap();
        assert_eq!(exposure.distinct_attacker_count, 1);
        assert!(exposure.max_incoming_damage > 0);
    }

    #[test]
    fn move_plus_attack_option_is_offered() {
        let registry = units();
        let mut s = large_test_state();
        let friendly = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(friendly, Hex::from_offset(15, 13));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(15, 15));
        let facts = generate_tactical_options(&s, 0).unwrap();
        assert!(facts.options.iter().any(|option| {
            let has_move = option.actions.iter().any(|action| {
                action.get("action").and_then(Value::as_str) == Some("Move")
                    && action.get("unit_id").and_then(Value::as_u64) == Some(5)
            });
            let has_attack = option.actions.iter().any(|action| {
                action.get("action").and_then(Value::as_str) == Some("Attack")
                    && action.get("attacker_id").and_then(Value::as_u64) == Some(5)
                    && action.get("defender_id").and_then(Value::as_u64) == Some(7)
            });
            has_move && has_attack
        }));
    }

    #[test]
    fn unknown_actionability_when_involved_facts_are_incomplete() {
        let registry = units();
        let mut s = large_test_state();
        let friendly = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(friendly, Hex::from_offset(15, 14));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(15, 15));

        let complete = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(complete.contact_actionability, "actionable");
        assert!(complete.contact_state_key.is_some());

        assert!(involved_option_flags(&s, &[999]).is_none());
        let unit_surface = unit_threats_after_end_turn(&s, 0).unwrap();
        let recruiter_surface = recruiter_threats_after_end_turn(&s, 0).unwrap();
        let (actionability, key) = crate::routine::classify_contact_state(
            &s,
            0,
            complete.trigger,
            &[999],
            &complete.enemy_unit_ids,
            &unit_surface,
            &recruiter_surface,
        );
        assert_eq!(actionability.as_str(), "unknown");
        assert_eq!(key, None);
        assert_ne!(actionability.as_str(), "exhausted");
    }

    #[test]
    fn contact_state_key_ignores_unrelated_remote_recruit() {
        let registry = units();
        let mut s = large_test_state();
        exhaust_unit(s.units.get_mut(&1).unwrap());
        let mut friendly = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        exhaust_unit(&mut friendly);
        s.place_unit(friendly, Hex::from_offset(15, 14));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(15, 15));

        let before = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(before.contact_actionability, "exhausted");
        let before_key = before.contact_state_key.clone().unwrap();

        let remote = Unit::from_def(20, registry.get("Ghost").unwrap(), 0);
        s.place_unit(remote, Hex::from_offset(24, 24));
        s.gold[0] += 50;
        s.state_revision += 1;

        let after = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(after.contact_actionability, "exhausted");
        assert_eq!(after.friendly_unit_ids, before.friendly_unit_ids);
        assert_eq!(
            after.contact_state_key.as_deref(),
            Some(before_key.as_str())
        );
        assert!(after.actor_ids.is_empty());
        assert!(after.options.is_empty());
        assert_eq!(
            after.options_empty_reason.as_deref(),
            Some("exhausted_contact_no_automatic_rescue_menu")
        );
    }

    #[test]
    fn contact_state_key_changes_with_involved_situation() {
        let registry = units();
        let mut s = large_test_state();
        let friendly = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(friendly, Hex::from_offset(15, 14));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(15, 15));

        let base = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        let base_key = base.contact_state_key.clone().unwrap();
        assert_eq!(base.contact_actionability, "actionable");

        let mut hp_state = s.clone();
        hp_state.units.get_mut(&5).unwrap().hp = 1;
        let hp_key = crate::routine::current_contact(&hp_state, 0)
            .unwrap()
            .unwrap()
            .contact_state_key
            .unwrap();
        assert_ne!(hp_key, base_key);

        let mut moved_state = s.clone();
        let from = *moved_state.positions.get(&5).unwrap();
        let dest = Hex::from_offset(14, 14);
        moved_state.positions.insert(5, dest);
        moved_state.hex_to_unit.remove(&from);
        moved_state.hex_to_unit.insert(dest, 5);
        let pos_key = crate::routine::current_contact(&moved_state, 0)
            .unwrap()
            .unwrap()
            .contact_state_key
            .unwrap();
        assert_ne!(pos_key, base_key);

        let mut extra_enemy = s.clone();
        let new_enemy = Unit::from_def(9, registry.get("Skeleton").unwrap(), 1);
        extra_enemy.place_unit(new_enemy, Hex::from_offset(16, 14));
        let extra = crate::routine::current_contact(&extra_enemy, 0)
            .unwrap()
            .unwrap();
        assert_ne!(extra.contact_state_key.as_deref(), Some(base_key.as_str()));
        assert!(extra.enemy_unit_ids.contains(&9));

        let mut threat_state = s.clone();
        threat_state.units.get_mut(&7).unwrap().hp = 1;
        let threat_key = crate::routine::current_contact(&threat_state, 0)
            .unwrap()
            .unwrap()
            .contact_state_key
            .unwrap();
        assert_ne!(threat_key, base_key);
    }

    #[test]
    fn test_primary_actor_lowest_id_attack_opportunity() {
        let registry = units();
        let mut s = large_test_state();

        // Recruiter is safe at (0, 0).
        // Friendly unit 5 at (15, 14) can attack enemy at (15, 15)
        let mut f5 = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        f5.hp = 100;
        s.place_unit(f5, Hex::from_offset(15, 14));

        // Friendly unit 3 at (18, 14) can attack enemy at (18, 15)
        let mut f3 = Unit::from_def(3, registry.get("Skeleton").unwrap(), 0);
        f3.hp = 100;
        s.place_unit(f3, Hex::from_offset(18, 14));

        // Enemies cannot reach friendly units, so friendly units are not threatened.
        // But friendly units are adjacent and can attack!
        let mut e1 = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        e1.hp = 100;
        s.place_unit(e1, Hex::from_offset(15, 15));

        let mut e2 = Unit::from_def(8, registry.get("Skeleton").unwrap(), 1);
        e2.hp = 100;
        s.place_unit(e2, Hex::from_offset(18, 15));

        let actors = select_eligible_actors(&s, 0).unwrap();
        assert_eq!(
            actors.first().copied(),
            Some(3),
            "lowest-ID unit with attack opportunity must be chosen"
        );
        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids.first().copied(), Some(3));
        assert!(!facts.actor_ids.is_empty());
        assert_eq!(facts.eligible_actor_count as usize, actors.len());
        assert_eq!(facts.actors_truncated, actors.len() > facts.actor_ids.len());
    }

    #[test]
    fn test_options_bounded_and_ranked() {
        let registry = units();
        let mut s = test_state();

        // Friendly unit 2 at (4, 4)
        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(4, 4));

        // Enemy at (4, 5)
        let e1 = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(4, 5));

        let facts = generate_tactical_options(&s, 0).unwrap();
        assert!(!facts.actor_ids.is_empty());
        assert!(facts.actor_ids.len() <= 3);
        assert!(facts.options.len() <= 4 * facts.actor_ids.len());

        for actor_id in &facts.actor_ids {
            let actor_options: Vec<_> = facts
                .options
                .iter()
                .filter(|o| o.actor_id == *actor_id)
                .collect();
            assert!(actor_options.len() <= 4);
            let attack_count = actor_options
                .iter()
                .filter(|o| o.category == "attack")
                .count();
            let reloc_count = actor_options
                .iter()
                .filter(|o| o.category == "relocation")
                .count();
            assert!(attack_count <= 2, "at most 2 attack options per actor");
            assert!(reloc_count <= 2, "at most 2 relocation options per actor");
        }

        let mut seen_ids = HashSet::new();
        for opt in &facts.options {
            assert!(
                seen_ids.insert(opt.option_id.clone()),
                "option IDs must be unique in the packet"
            );
            match opt.category.as_str() {
                "attack" => {
                    assert!(opt
                        .option_id
                        .starts_with(&format!("u{}-attack-", opt.actor_id)));
                }
                "relocation" => {
                    assert!(opt
                        .option_id
                        .starts_with(&format!("u{}-relocate-", opt.actor_id)));
                }
                other => panic!("unexpected option category: {other}"),
            }
            assert_eq!(opt.coverage, "complete");
        }
    }

    #[test]
    fn relocation_exposure_keeps_supported_focus_slots_for_one_two_and_three_attackers() {
        let registry = units();
        for attacker_count in 1..=3 {
            let mut s = large_test_state();
            let friendly = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
            s.place_unit(friendly, Hex::from_offset(15, 15));
            let enemy_hexes = [(15, 16), (16, 15), (14, 15)];
            for (offset, &(col, row)) in enemy_hexes.iter().take(attacker_count).enumerate() {
                let enemy = Unit::from_def(7 + offset as u32, registry.get("Skeleton").unwrap(), 1);
                s.place_unit(enemy, Hex::from_offset(col, row));
            }

            let facts = generate_tactical_options(&s, 0).unwrap();
            let exposures: Vec<u32> = facts
                .options
                .iter()
                .filter(|option| option.category == "relocation")
                .filter_map(|option| option.exposure.as_ref())
                .map(|exposure| exposure.expected_incoming_damage_tenths)
                .collect();
            assert!(
                !exposures.is_empty(),
                "attacker_count={attacker_count} produced no relocation"
            );
            assert!(
                exposures.iter().any(|value| *value > 0),
                "attacker_count={attacker_count} lost all supported expected damage: {exposures:?}"
            );
        }
    }

    #[test]
    fn test_options_are_executable_and_deterministic() {
        let registry = units();
        let mut s = test_state();

        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(4, 4));
        let e1 = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(4, 5));

        let facts1 = generate_tactical_options(&s, 0).unwrap();
        let facts2 = generate_tactical_options(&s, 0).unwrap();

        assert_eq!(
            facts1, facts2,
            "repeated queries at same state must return identical options"
        );

        // Verify each option's actions are executable on cloned state
        for opt in &facts1.options {
            let mut sim = s.clone();
            for act_val in &opt.actions {
                let action_type = act_val["action"].as_str().unwrap();
                match action_type {
                    "Move" => {
                        let unit_id = act_val["unit_id"].as_u64().unwrap() as u32;
                        let col = act_val["col"].as_i64().unwrap() as i32;
                        let row = act_val["row"].as_i64().unwrap() as i32;
                        let res = apply_action(
                            &mut sim,
                            Action::Move {
                                unit_id,
                                destination: Hex::from_offset(col, row),
                            },
                        );
                        assert!(res.is_ok(), "Move action in option must be legal: {res:?}");
                    }
                    "Attack" => {
                        let attacker_id = act_val["attacker_id"].as_u64().unwrap() as u32;
                        let defender_id = act_val["defender_id"].as_u64().unwrap() as u32;
                        let res = apply_action(
                            &mut sim,
                            Action::Attack {
                                attacker_id,
                                defender_id,
                            },
                        );
                        assert!(
                            res.is_ok(),
                            "Attack action in option must be legal: {res:?}"
                        );
                    }
                    other => panic!("unexpected action in option: {other}"),
                }
            }
        }
    }

    #[test]
    fn test_relocation_capped_at_16_destinations() {
        let mut b = Board::new(20, 20);
        for r in 0..20 {
            for c in 0..20 {
                b.set_tile(Hex::from_offset(c, r), Tile::new("flat"));
            }
        }
        let mut s = GameState::new(b);
        let registry = units();

        // Ghost has 7 movement on flat terrain -> way more than 16 reachable hexes!
        let ghost = Unit::from_def(2, registry.get("Ghost").unwrap(), 0);
        s.place_unit(ghost, Hex::from_offset(10, 10));

        // Place an enemy to trigger contact / exposure
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(10, 11));

        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids, vec![2]);
        assert_eq!(facts.eligible_actor_count, 1);
        assert!(!facts.actors_truncated);
        assert!(
            facts.options_truncated,
            "high movement unit must trigger options_truncated"
        );
        assert!(facts.options.iter().any(|o| o.category == "relocation"));
    }

    #[test]
    fn four_eligible_actors_select_three_and_truncate() {
        let registry = units();
        let mut s = large_test_state();
        for (friendly_id, enemy_id, col) in [(2, 12, 10), (3, 13, 12), (4, 14, 14), (5, 15, 16)] {
            let friendly = Unit::from_def(friendly_id, registry.get("Skeleton").unwrap(), 0);
            s.place_unit(friendly, Hex::from_offset(col, 14));
            let enemy = Unit::from_def(enemy_id, registry.get("Skeleton").unwrap(), 1);
            s.place_unit(enemy, Hex::from_offset(col, 15));
        }

        let eligible = select_eligible_actors(&s, 0).unwrap();
        assert_eq!(eligible, vec![2, 3, 4, 5]);

        let facts = generate_tactical_options(&s, 0).unwrap();
        assert_eq!(facts.actor_ids, vec![2, 3, 4]);
        assert_eq!(facts.eligible_actor_count, 4);
        assert!(facts.actors_truncated);
        assert!(facts.options.len() <= 12);
        assert!(facts.options.iter().all(|option| option.actor_id != 5));
        assert_eq!(facts.options_empty_reason, None);

        let mut seen_ids = HashSet::new();
        for opt in &facts.options {
            assert!(facts.actor_ids.contains(&opt.actor_id));
            assert!(seen_ids.insert(opt.option_id.clone()));
            assert!(
                opt.option_id
                    .starts_with(&format!("u{}-attack-", opt.actor_id))
                    || opt
                        .option_id
                        .starts_with(&format!("u{}-relocate-", opt.actor_id))
            );
        }
        for actor_id in &facts.actor_ids {
            let count = facts
                .options
                .iter()
                .filter(|option| option.actor_id == *actor_id)
                .count();
            assert!(count > 0 && count <= 4);
        }
    }

    fn base_test_state() -> GameState {
        let mut b = Board::new(10, 8);
        for r in 0..8 {
            for c in 0..10 {
                b.set_tile(Hex::from_offset(c, r), Tile::new("flat"));
            }
        }
        let k = Hex::from_offset(1, 1);
        b.set_tile(k, Tile::new("keep"));
        for h in k.neighbors() {
            if b.contains(h) {
                b.set_tile(h, Tile::new("castle"));
            }
        }
        let mut s = GameState::new(b);
        s.gold = [1000, 1000];
        s
    }

    #[test]
    fn test_threatened_recruiter_options_safe_returns_none() {
        let s = test_state();
        // Recruiter at (1, 1), no enemies
        let facts = generate_threatened_recruiter_options(&s, 0).unwrap();
        assert!(facts.is_none());
    }

    #[test]
    fn test_threatened_recruiter_options_threatened_and_actionable() {
        let registry = units();
        let mut s = base_test_state();
        let mut recruiter = Unit::from_def(1, registry.get("Dark Sorcerer").unwrap(), 0);
        recruiter.can_recruit = true;
        s.place_unit(recruiter, Hex::from_offset(1, 1));

        // Place enemy near recruiter (unit 1 at keep (1,1))
        let enemy = Unit::from_def(99, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(2, 1));

        let facts = generate_threatened_recruiter_options(&s, 0).unwrap().expect("should find threatened recruiter");
        assert_eq!(facts.actor_ids, vec![1]);
        assert_eq!(facts.eligible_actor_count, 1);
        assert!(!facts.actors_truncated);
        assert!(!facts.options.is_empty());
        assert!(facts.options.len() <= 4);
        assert_eq!(facts.options_empty_reason, None);
        assert!(facts.recruiter.distinct_attacker_count > 0 || facts.recruiter.open_distinct_attacker_count > 0);
        assert_eq!(facts.recruiter.recruiter_id, 1);

        let attacks = facts.options.iter().filter(|o| o.category == "attack").count();
        let relocations = facts.options.iter().filter(|o| o.category == "relocation").count();
        assert!(attacks <= 2);
        assert!(relocations <= 2);
    }

    #[test]
    fn test_threatened_recruiter_options_exhausted() {
        let registry = units();
        let mut s = base_test_state();
        let mut recruiter = Unit::from_def(1, registry.get("Dark Sorcerer").unwrap(), 0);
        recruiter.can_recruit = true;
        recruiter.moved = true;
        recruiter.attacked = true;
        s.place_unit(recruiter, Hex::from_offset(1, 1));

        let enemy = Unit::from_def(99, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(2, 1));

        let facts = generate_threatened_recruiter_options(&s, 0).unwrap().expect("should detect threatened recruiter");
        assert!(facts.options.is_empty());
        assert_eq!(
            facts.options_empty_reason.as_deref(),
            Some("exhausted_recruiter_no_tactical_options")
        );
        assert_eq!(facts.actor_ids.len(), 0);
        assert_eq!(facts.eligible_actor_count, 0);
        assert!(!facts.actors_truncated);
        assert!(facts.recruiter.distinct_attacker_count > 0 || facts.recruiter.open_distinct_attacker_count > 0);
    }

    #[test]
    fn test_threatened_recruiter_options_multiple_recruiters_truncation() {
        let registry = units();
        let mut s = base_test_state();
        // Unit 1 is recruiter at (1,1)
        let mut r1 = Unit::from_def(1, registry.get("Dark Sorcerer").unwrap(), 0);
        r1.can_recruit = true;
        s.place_unit(r1, Hex::from_offset(1, 1));

        // Add another recruiter unit 50 at (5, 5)
        let mut r2 = Unit::from_def(50, registry.get("Dark Sorcerer").unwrap(), 0);
        r2.can_recruit = true;
        s.place_unit(r2, Hex::from_offset(5, 5));

        // Threaten unit 1
        let e1 = Unit::from_def(98, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(2, 1));

        // Threaten unit 50
        let e2 = Unit::from_def(99, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e2, Hex::from_offset(5, 6));

        let facts = generate_threatened_recruiter_options(&s, 0).unwrap().expect("should find threatened recruiter");
        // Unit 1 (lowest ID) is selected
        assert_eq!(facts.actor_ids, vec![1]);
        assert_eq!(facts.eligible_actor_count, 2);
        assert!(facts.actors_truncated);
        assert_eq!(facts.recruiter.recruiter_id, 1);
    }
}
