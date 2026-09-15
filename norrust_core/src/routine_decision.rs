//! Bounded tactical choices for current-state contact decisions.

use std::collections::HashMap;

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
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TacticalDecisionFacts {
    pub primary_actor_id: Option<u32>,
    pub options: Vec<TacticalOption>,
    pub options_truncated: bool,
    /// Present only when no primary actor has an executable offered action.
    /// Availability is independent of tactical-option enumeration coverage.
    pub options_empty_reason: Option<String>,
}

fn has_executable_attack(state: &GameState, actor_id: u32) -> Result<bool, TacticsError> {
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

fn has_executable_relocation(state: &GameState, actor_id: u32) -> Result<bool, TacticsError> {
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

fn has_executable_options(state: &GameState, actor_id: u32) -> Result<bool, TacticsError> {
    // Moving is cheaper to establish and remains available after an attack.
    Ok(has_executable_relocation(state, actor_id)? || has_executable_attack(state, actor_id)?)
}

/// Choose one primary friendly actor deterministically:
/// 1. Lowest-ID threatened recruiter with an executable tactical option
/// 2. Lowest-ID threatened friendly unit with an executable tactical option
/// 3. Lowest-ID unit with an executable attack opportunity
pub fn select_primary_actor(
    state: &GameState,
    side: u8,
) -> Result<Option<u32>, TacticsError> {
    // 1. Threatened recruiters
    let recruiter_surface = recruiter_threats_after_end_turn(state, side)?;
    let mut threatened_recruiters: Vec<u32> = recruiter_surface
        .recruiters
        .into_iter()
        .filter(|r| r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0)
        .map(|r| r.recruiter_id)
        .collect();
    threatened_recruiters.sort_unstable();
    for actor_id in threatened_recruiters {
        if has_executable_options(state, actor_id)? {
            return Ok(Some(actor_id));
        }
    }

    // 2. Lowest-ID threatened friendly unit
    let unit_surface = unit_threats_after_end_turn(state, side)?;
    let mut threatened_units: Vec<u32> = unit_surface
        .units
        .into_iter()
        .filter(|u| u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0)
        .map(|u| u.unit_id)
        .collect();
    threatened_units.sort_unstable();
    for actor_id in threatened_units {
        if has_executable_options(state, actor_id)? {
            return Ok(Some(actor_id));
        }
    }

    // 3. Lowest-ID unit with an attack opportunity
    let mut attack_units: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == side && !unit.attacked).then_some(id))
        .collect();
    attack_units.sort_unstable();
    for actor_id in attack_units {
        if has_executable_attack(state, actor_id)? {
            return Ok(Some(actor_id));
        }
    }

    Ok(None)
}

/// Generate at most 4 bounded tactical options (up to 2 attacks, up to 2 relocations)
/// for the deterministically selected primary actor.
pub fn generate_tactical_options(
    state: &GameState,
    side: u8,
) -> Result<TacticalDecisionFacts, TacticsError> {
    let Some(actor_id) = select_primary_actor(state, side)? else {
        return Ok(TacticalDecisionFacts {
            primary_actor_id: None,
            options: Vec::new(),
            options_truncated: false,
            options_empty_reason: Some("no_executable_options".to_string()),
        });
    };

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

    for (i, atk) in top_attacks.into_iter().enumerate() {
        options.push(TacticalOption {
            option_id: format!("attack_{}", i + 1),
            category: "attack".to_string(),
            actor_id,
            target_id: Some(atk.2),
            actions: atk.5,
            movement_cost: atk.6,
            destination: None,
            forecast: Some(atk.7),
            exposure: None,
            coverage: "complete".to_string(),
        });
    }

    for (i, reloc) in top_relocations.into_iter().enumerate() {
        options.push(TacticalOption {
            option_id: format!("relocate_{}", i + 1),
            category: "relocation".to_string(),
            actor_id,
            target_id: None,
            actions: reloc.5,
            movement_cost: reloc.2,
            destination: Some(reloc.6),
            forecast: None,
            exposure: Some(reloc.7),
            coverage: "complete".to_string(),
        });
    }

    Ok(TacticalDecisionFacts {
        primary_actor_id: Some(actor_id),
        options_empty_reason: options
            .is_empty()
            .then(|| "no_executable_options".to_string()),
        options,
        options_truncated,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Tile};
    use crate::loader::Registry;
    use crate::schema::UnitDef;
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

        let actor = select_primary_actor(&s, 0).unwrap();
        assert_eq!(actor, Some(50), "recruiter priority beats lower-ID friends");
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

        let actor = select_primary_actor(&s, 0).unwrap();
        assert_eq!(actor, Some(2), "lowest-ID threatened unit must be chosen");
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
        assert_eq!(facts.primary_actor_id, Some(6));
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
        assert_eq!(facts.primary_actor_id, Some(2));
        assert!(facts.options.iter().any(|option| option.category == "attack"));
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
        assert_eq!(facts.primary_actor_id, Some(2));
        assert!(facts.options.iter().any(|option| option.category == "relocation"));
    }

    #[test]
    fn all_exhausted_contact_has_explicit_empty_options_reason_and_complete_coverage() {
        let registry = units();
        let mut s = large_test_state();
        for (friendly_id, enemy_id, friendly_hex, enemy_hex) in [
            (5, 7, (15, 14), (15, 15)),
            (6, 8, (18, 14), (18, 15)),
        ] {
            let mut friendly = Unit::from_def(friendly_id, registry.get("Skeleton").unwrap(), 0);
            friendly.moved = true;
            friendly.attacked = true;
            s.place_unit(friendly, Hex::from_offset(friendly_hex.0, friendly_hex.1));
            let enemy = Unit::from_def(enemy_id, registry.get("Skeleton").unwrap(), 1);
            s.place_unit(enemy, Hex::from_offset(enemy_hex.0, enemy_hex.1));
        }

        let facts = crate::routine::current_contact(&s, 0).unwrap().unwrap();
        assert_eq!(facts.friendly_unit_ids, vec![5, 6]);
        assert_eq!(facts.primary_actor_id, None);
        assert!(facts.options.is_empty());
        assert_eq!(facts.options_empty_reason.as_deref(), Some("no_executable_options"));
        assert!(!facts.options_truncated);
        assert_eq!(facts.coverage, "complete");
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

        let actor = select_primary_actor(&s, 0).unwrap();
        assert_eq!(actor, Some(3), "lowest-ID unit with attack opportunity must be chosen");
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
        assert!(facts.primary_actor_id.is_some());
        assert!(facts.options.len() <= 4);

        let attack_count = facts.options.iter().filter(|o| o.category == "attack").count();
        let reloc_count = facts.options.iter().filter(|o| o.category == "relocation").count();
        assert!(attack_count <= 2, "at most 2 attack options");
        assert!(reloc_count <= 2, "at most 2 relocation options");

        // Options must have deterministic IDs
        for opt in &facts.options {
            assert!(opt.option_id.starts_with("attack_") || opt.option_id.starts_with("relocate_"));
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
            let exposures: Vec<u32> = facts.options.iter()
                .filter(|option| option.category == "relocation")
                .filter_map(|option| option.exposure.as_ref())
                .map(|exposure| exposure.expected_incoming_damage_tenths)
                .collect();
            assert!(!exposures.is_empty(), "attacker_count={attacker_count} produced no relocation");
            assert!(exposures.iter().any(|value| *value > 0),
                    "attacker_count={attacker_count} lost all supported expected damage: {exposures:?}");
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

        assert_eq!(facts1, facts2, "repeated queries at same state must return identical options");

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
                        let res = apply_action(&mut sim, Action::Move {
                            unit_id,
                            destination: Hex::from_offset(col, row),
                        });
                        assert!(res.is_ok(), "Move action in option must be legal: {res:?}");
                    }
                    "Attack" => {
                        let attacker_id = act_val["attacker_id"].as_u64().unwrap() as u32;
                        let defender_id = act_val["defender_id"].as_u64().unwrap() as u32;
                        let res = apply_action(&mut sim, Action::Attack {
                            attacker_id,
                            defender_id,
                        });
                        assert!(res.is_ok(), "Attack action in option must be legal: {res:?}");
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
        assert_eq!(facts.primary_actor_id, Some(2));
        assert!(facts.options_truncated, "high movement unit must trigger options_truncated");
        assert!(facts.options.iter().any(|o| o.category == "relocation"));
    }
}
