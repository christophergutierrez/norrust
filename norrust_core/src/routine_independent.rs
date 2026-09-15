//! Conservative independent policy movement during current-state contact.

use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use crate::game_state::{apply_action, Action, GameState};
use crate::hex::Hex;
use crate::pathfinding::{find_path, get_zoc_hexes};
use crate::routine::{
    current_contact, is_recruiter, rally_goals, route_endpoints, CurrentContactFacts,
    RoutinePolicy, RoutineProgress,
};
use crate::tactics::{
    recruiter_threats_after_end_turn, unit_tactics, unit_threats_after_end_turn, TacticsError,
};

#[derive(Debug, Clone)]
pub struct CandidateIndependentMove {
    pub unit_id: u32,
    pub destination: Hex,
    pub progress_effects: Vec<Value>,
    pub reason: &'static str,
    pub objective_kind: &'static str,
    pub objective_target: Hex,
}

#[derive(Debug, Clone)]
pub struct IndependentMoveExecution {
    pub candidate: CandidateIndependentMove,
    pub pre_tactical_hash: String,
    pub post_tactical_hash: String,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct AttackSignature {
    pub origin_col: i32,
    pub origin_row: i32,
    pub defender_id: u32,
    pub outcome_bps: [u32; 3],
    pub expected_damage_tenths: [u32; 2],
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct UnitThreatSignature {
    pub unit_id: u32,
    pub distinct_attacker_count: u32,
    pub open_distinct_attacker_count: u32,
    pub max_incoming_sum: u32,
    pub open_max_incoming_sum: u32,
    pub lethal_attackers_needed: Option<u32>,
    pub open_lethal_attackers_needed: Option<u32>,
    pub origins_conflict: bool,
    pub open_origins_conflict: bool,
    pub focus_kill_bps: Vec<u32>,
    pub focus_expected_damage_tenths: Vec<u32>,
    pub attacker_ids: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct RecruiterThreatSignature {
    pub recruiter_id: u32,
    pub distinct_attacker_count: u32,
    pub open_distinct_attacker_count: u32,
    pub max_incoming_sum: u32,
    pub open_max_incoming_sum: u32,
    pub lethal_attackers_needed: Option<u32>,
    pub open_lethal_attackers_needed: Option<u32>,
    pub origins_conflict: bool,
    pub open_origins_conflict: bool,
    pub focus_kill_bps: Vec<u32>,
    pub focus_expected_damage_tenths: Vec<u32>,
    pub threats: Vec<(u32, i32, i32, u32, [u32; 3], [u32; 2])>,
    pub open_threats: Vec<(u32, i32, i32, u32, [u32; 3], [u32; 2])>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FullTacticalStateSignature {
    pub attacks: Vec<(u32, Vec<AttackSignature>)>,
    pub unit_threats: Vec<UnitThreatSignature>,
    pub recruiter_threats: Vec<RecruiterThreatSignature>,
}

fn compute_tactical_signature(
    state: &GameState,
    side: u8,
) -> Result<FullTacticalStateSignature, TacticsError> {
    let mut friendly_ids: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, u)| (u.faction == side).then_some(id))
        .collect();
    friendly_ids.sort_unstable();

    let mut attacks = Vec::with_capacity(friendly_ids.len());
    for &id in &friendly_ids {
        let mut unit_attacks = Vec::new();
        if let Ok(tactics) = unit_tactics(state, id) {
            for origin in tactics.origins {
                for eng in origin.engagements {
                    unit_attacks.push(AttackSignature {
                        origin_col: origin.col,
                        origin_row: origin.row,
                        defender_id: eng.defender_id,
                        outcome_bps: eng.forecast.outcome_bps,
                        expected_damage_tenths: eng.forecast.expected_damage_tenths,
                    });
                }
            }
        }
        unit_attacks.sort_unstable();
        attacks.push((id, unit_attacks));
    }

    let unit_threat_surface = unit_threats_after_end_turn(state, side)?;
    let mut unit_threats = Vec::with_capacity(unit_threat_surface.units.len());
    for u in unit_threat_surface.units {
        let mut attacker_ids = u.attacker_ids;
        attacker_ids.sort_unstable();
        unit_threats.push(UnitThreatSignature {
            unit_id: u.unit_id,
            distinct_attacker_count: u.distinct_attacker_count,
            open_distinct_attacker_count: u.open_distinct_attacker_count,
            max_incoming_sum: u.max_incoming_sum,
            open_max_incoming_sum: u.open_max_incoming_sum,
            lethal_attackers_needed: u.lethal_attackers_needed,
            open_lethal_attackers_needed: u.open_lethal_attackers_needed,
            origins_conflict: u.origins_conflict,
            open_origins_conflict: u.open_origins_conflict,
            focus_kill_bps: u.focus_kill_bps,
            focus_expected_damage_tenths: u.focus_expected_damage_tenths,
            attacker_ids,
        });
    }
    unit_threats.sort_by_key(|u| u.unit_id);

    let recruiter_surface = recruiter_threats_after_end_turn(state, side)?;
    let mut recruiter_threats = Vec::with_capacity(recruiter_surface.recruiters.len());
    for r in recruiter_surface.recruiters {
        let mut threats: Vec<(u32, i32, i32, u32, [u32; 3], [u32; 2])> = r
            .threats
            .iter()
            .map(|t| {
                (
                    t.attacker_id,
                    t.origin_col,
                    t.origin_row,
                    t.max_damage,
                    t.forecast.outcome_bps,
                    t.forecast.expected_damage_tenths,
                )
            })
            .collect();
        threats.sort_unstable();

        let mut open_threats: Vec<(u32, i32, i32, u32, [u32; 3], [u32; 2])> = r
            .open_threats
            .iter()
            .map(|t| {
                (
                    t.attacker_id,
                    t.origin_col,
                    t.origin_row,
                    t.max_damage,
                    t.forecast.outcome_bps,
                    t.forecast.expected_damage_tenths,
                )
            })
            .collect();
        open_threats.sort_unstable();

        recruiter_threats.push(RecruiterThreatSignature {
            recruiter_id: r.recruiter_id,
            distinct_attacker_count: r.distinct_attacker_count,
            open_distinct_attacker_count: r.open_distinct_attacker_count,
            max_incoming_sum: r.max_incoming_sum,
            open_max_incoming_sum: r.open_max_incoming_sum,
            lethal_attackers_needed: r.lethal_attackers_needed,
            open_lethal_attackers_needed: r.open_lethal_attackers_needed,
            origins_conflict: r.origins_conflict,
            open_origins_conflict: r.open_origins_conflict,
            focus_kill_bps: r.focus_kill_bps,
            focus_expected_damage_tenths: r.focus_expected_damage_tenths,
            threats,
            open_threats,
        });
    }
    recruiter_threats.sort_by_key(|r| r.recruiter_id);

    Ok(FullTacticalStateSignature {
        attacks,
        unit_threats,
        recruiter_threats,
    })
}

fn hash_signature(sig: &FullTacticalStateSignature) -> String {
    let bytes = serde_json::to_vec(sig).unwrap_or_default();
    format!("{:x}", Sha256::digest(&bytes))
}

pub fn collect_candidate_moves(
    state: &GameState,
    side: u8,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    scouts: &[u32],
) -> Vec<CandidateIndependentMove> {
    let mut candidates = Vec::new();
    let mut seen_units = HashSet::new();

    // 1. Village candidates
    let assignments = progress.scout_assignments.clone();
    let completed: HashSet<Hex> = progress.completed_villages.iter().copied().collect();
    let owned: HashSet<Hex> = state
        .village_owners
        .iter()
        .filter_map(|(h, o)| (*o == side as i8).then_some(*h))
        .collect();
    let assigned: HashSet<Hex> = assignments.iter().map(|a| a.village).collect();
    let mut villages: Vec<Hex> = policy
        .villages
        .iter()
        .copied()
        .filter(|h| !completed.contains(h) && !owned.contains(h) && !assigned.contains(h))
        .collect();
    villages.sort_by_key(|h| {
        let (c, r) = h.to_offset();
        (r, c)
    });

    let mut pairs = Vec::new();
    for village in villages {
        for &id in scouts {
            if assignments.iter().any(|a| a.unit_id == id)
                || policy.holds.contains(&id)
                || state.units.get(&id).is_some_and(is_recruiter)
            {
                continue;
            };
            let Some(start) = state.positions.get(&id).copied() else {
                continue;
            };
            let Some(unit) = state.units.get(&id) else {
                continue;
            };
            if unit.moved {
                continue;
            }
            if let Some((_, cost)) = find_path(
                &state.board,
                &unit.movement_costs,
                1,
                start,
                village,
                u32::MAX / 4,
                &get_zoc_hexes(state, side),
                false,
            ) {
                pairs.push((cost, village, id));
            }
        }
    }
    pairs.sort_by_key(|(cost, village, id)| {
        let (c, r) = village.to_offset();
        (*cost, r, c, *id)
    });

    // Unassigned scout candidates
    for (_, village, id) in pairs {
        if seen_units.contains(&id) {
            continue;
        }
        let endpoints = route_endpoints(state, id, &[village]);
        for (destination, arrived) in endpoints {
            if !arrived {
                seen_units.insert(id);
                candidates.push(CandidateIndependentMove {
                    unit_id: id,
                    destination,
                    progress_effects: vec![json!({
                        "kind": "scout_assigned",
                        "unit_id": id,
                        "col": village.to_offset().0,
                        "row": village.to_offset().1,
                    })],
                    reason: "village",
                    objective_kind: "village",
                    objective_target: village,
                });
                break;
            }
        }
        if candidates.len() >= 8 {
            return candidates;
        }
    }

    // Assigned scout candidates
    let mut sorted_assignments = assignments;
    sorted_assignments.sort_by_key(|a| a.unit_id);
    for a in sorted_assignments {
        if seen_units.contains(&a.unit_id) || policy.holds.contains(&a.unit_id) {
            continue;
        }
        if let Some(unit) = state.units.get(&a.unit_id) {
            if unit.moved || is_recruiter(unit) {
                continue;
            }
            if let Some(start) = state.positions.get(&a.unit_id) {
                if *start != a.village
                    && !state
                        .village_owners
                        .get(&a.village)
                        .is_some_and(|o| *o == side as i8)
                {
                    let endpoints = route_endpoints(state, a.unit_id, &[a.village]);
                    for (destination, arrived) in endpoints {
                        if !arrived {
                            seen_units.insert(a.unit_id);
                            candidates.push(CandidateIndependentMove {
                                unit_id: a.unit_id,
                                destination,
                                progress_effects: Vec::new(),
                                reason: "village",
                                objective_kind: "village",
                                objective_target: a.village,
                            });
                            break;
                        }
                    }
                    if candidates.len() >= 8 {
                        return candidates;
                    }
                }
            }
        }
    }

    // 2. Rally candidates
    if let Some(rally) = policy.rally {
        let mut ids: Vec<u32> = state
            .units
            .iter()
            .filter_map(|(id, u)| {
                (u.faction == side
                    && !u.moved
                    && !is_recruiter(u)
                    && !scouts.contains(id)
                    && !policy.holds.contains(id))
                .then_some(*id)
            })
            .collect();
        ids.sort_unstable();
        let goals = rally_goals(state, rally);
        for id in ids {
            if seen_units.contains(&id) {
                continue;
            }
            if state
                .positions
                .get(&id)
                .is_some_and(|position| position.distance(rally) <= 1)
            {
                continue;
            }
            let endpoints = route_endpoints(state, id, &goals);
            for (destination, arrived) in endpoints {
                if !arrived {
                    seen_units.insert(id);
                    candidates.push(CandidateIndependentMove {
                        unit_id: id,
                        destination,
                        progress_effects: Vec::new(),
                        reason: "rally",
                        objective_kind: "rally",
                        objective_target: rally,
                    });
                    break;
                }
            }
            if candidates.len() >= 8 {
                return candidates;
            }
        }
    }

    candidates
}

/// Verify all conservative independence checks for one candidate move.
pub fn evaluate_candidate(
    state: &GameState,
    side: u8,
    candidate: &CandidateIndependentMove,
    contact_facts: &CurrentContactFacts,
    pre_sig: &FullTacticalStateSignature,
) -> Result<Option<(String, String)>, TacticsError> {
    let u = candidate.unit_id;

    // Moving unit cannot be a recruiter or on hold
    let Some(unit) = state.units.get(&u) else {
        return Ok(None);
    };
    if is_recruiter(unit) {
        return Ok(None);
    }
    let Some(&start_pos) = state.positions.get(&u) else {
        return Ok(None);
    };

    // 1. Moving unit before the move: no attack opportunity, no threats
    if let Some((_, unit_attacks)) = pre_sig.attacks.iter().find(|(id, _)| *id == u) {
        if !unit_attacks.is_empty() {
            return Ok(None);
        }
    }
    if let Some(summary) = pre_sig.unit_threats.iter().find(|s| s.unit_id == u) {
        if summary.distinct_attacker_count > 0 || summary.open_distinct_attacker_count > 0 {
            return Ok(None);
        }
    }

    // Objective progress: destination must be strictly closer to target than start
    if candidate.destination.distance(candidate.objective_target)
        >= start_pos.distance(candidate.objective_target)
    {
        return Ok(None);
    }

    // 2. Clone state and apply the candidate move
    let mut clone = state.clone();
    if apply_action(
        &mut clone,
        Action::Move {
            unit_id: u,
            destination: candidate.destination,
        },
    )
    .is_err()
    {
        return Ok(None);
    }

    // 3. Moving unit after the move: no attack opportunity from new hex, no threats
    if let Ok(tactics_after) = unit_tactics(&clone, u) {
        if tactics_after
            .origins
            .iter()
            .any(|o| !o.engagements.is_empty())
        {
            return Ok(None);
        }
    } else {
        return Ok(None);
    }

    let post_sig = compute_tactical_signature(&clone, side)?;

    if let Some((_, unit_attacks_after)) = post_sig.attacks.iter().find(|(id, _)| *id == u) {
        if !unit_attacks_after.is_empty() {
            return Ok(None);
        }
    }
    if let Some(summary_after) = post_sig.unit_threats.iter().find(|s| s.unit_id == u) {
        if summary_after.distinct_attacker_count > 0
            || summary_after.open_distinct_attacker_count > 0
        {
            return Ok(None);
        }
    }

    // 4. All other friendly units: attack surfaces and threat summaries unchanged
    for &(id, ref before_attacks) in &pre_sig.attacks {
        if id == u {
            continue;
        }
        let after_attacks = post_sig
            .attacks
            .iter()
            .find(|(i, _)| *i == id)
            .map(|(_, a)| a);
        if Some(before_attacks) != after_attacks {
            return Ok(None); // Attack surface changed!
        }
    }

    for before_threat in &pre_sig.unit_threats {
        if before_threat.unit_id == u {
            continue;
        }
        let after_threat = post_sig
            .unit_threats
            .iter()
            .find(|s| s.unit_id == before_threat.unit_id);
        if Some(before_threat) != after_threat {
            return Ok(None); // Threat summary changed!
        }
    }

    // Recruiter threat summaries must be identical
    if pre_sig.recruiter_threats != post_sig.recruiter_threats {
        return Ok(None); // Recruiter threat changed!
    }

    // 5. Contact participants must not increase
    if let Some(new_facts) = current_contact(&clone, side)? {
        for f_id in &new_facts.friendly_unit_ids {
            if !contact_facts.friendly_unit_ids.contains(f_id) {
                return Ok(None); // New friendly contact participant!
            }
        }
        for e_id in &new_facts.enemy_unit_ids {
            if !contact_facts.enemy_unit_ids.contains(e_id) {
                return Ok(None); // New enemy contact participant!
            }
        }
    }

    // 6. Board invariants
    for (&id, original_unit) in &state.units {
        if original_unit.faction == side {
            if let Some(cloned_unit) = clone.units.get(&id) {
                if cloned_unit.hp != original_unit.hp {
                    return Ok(None);
                }
            } else {
                return Ok(None);
            }
        }
    }
    if clone.gold[side as usize] != state.gold[side as usize] {
        return Ok(None);
    }
    if clone.village_owners != state.village_owners {
        return Ok(None);
    }

    let pre_hash = hash_signature(pre_sig);
    let post_hash = hash_signature(&post_sig);
    Ok(Some((pre_hash, post_hash)))
}

/// Find at most one conservative independent move during current contact.
pub fn find_independent_move(
    state: &GameState,
    side: u8,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    scouts: &[u32],
    contact_facts: &CurrentContactFacts,
) -> Result<Option<IndependentMoveExecution>, TacticsError> {
    // Check recruiter danger first: if recruiter has any threat, return None immediately!
    let recruiter_surface = recruiter_threats_after_end_turn(state, side)?;
    if recruiter_surface
        .recruiters
        .iter()
        .any(|r| r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0)
    {
        return Ok(None);
    }

    // Scan at most 8 candidates
    let candidates = collect_candidate_moves(state, side, policy, progress, scouts);
    if candidates.is_empty() {
        return Ok(None);
    }

    let pre_sig = compute_tactical_signature(state, side)?;

    for candidate in candidates {
        if let Some((pre_hash, post_hash)) =
            evaluate_candidate(state, side, &candidate, contact_facts, &pre_sig)?
        {
            return Ok(Some(IndependentMoveExecution {
                candidate,
                pre_tactical_hash: pre_hash,
                post_tactical_hash: post_hash,
            }));
        }
    }

    Ok(None)
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

    fn test_state(width: u32, height: u32) -> GameState {
        let mut b = Board::new(width, height);
        for r in 0..height {
            for c in 0..width {
                b.set_tile(Hex::from_offset(c as i32, r as i32), Tile::new("flat"));
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
    fn test_recruiter_danger_precludes_independent_movement() {
        let registry = units();
        let mut s = test_state(20, 20);

        // Distant scout at (15, 15)
        let f2 = Unit::from_def(2, registry.get("Ghost").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(15, 15));

        // Enemy right next to recruiter (at 0, 0) -> placed at (0, 1)
        let e1 = Unit::from_def(10, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(0, 1));

        let policy = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            villages: vec![Hex::from_offset(18, 18)],
            rally: None,
            holds: Vec::new(),
            scouts: vec![2],
        };
        let progress = RoutineProgress::default();
        let scouts = vec![2];
        let contact_facts = CurrentContactFacts {
            trigger: "exposure",
            friendly_unit_ids: vec![1],
            enemy_unit_ids: vec![10],
            actor_ids: vec![1],
            eligible_actor_count: 1,
            actors_truncated: false,
            options: Vec::new(),
            options_truncated: false,
            options_empty_reason: None,
            coverage: "complete",
        };

        // Recruiter is in danger -> find_independent_move MUST return None
        let result = find_independent_move(&s, 0, &policy, &progress, &scouts, &contact_facts);
        assert!(result.is_ok());
        assert!(
            result.unwrap().is_none(),
            "Recruiter danger must preclude distant movement"
        );
    }

    #[test]
    fn test_distant_scout_can_move_independently_when_threatened_unit_is_not_recruiter() {
        let registry = units();
        let mut s = test_state(25, 25);

        // Friendly warrior at (5, 5) engaged with enemy at (5, 6)
        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(5, 5));

        let e1 = Unit::from_def(10, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(5, 6));

        // Distant scout at (20, 20) with village target at (24, 24)
        s.board
            .set_tile(Hex::from_offset(24, 24), Tile::new("village"));
        let f3 = Unit::from_def(3, registry.get("Ghost").unwrap(), 0);
        s.place_unit(f3, Hex::from_offset(20, 20));

        let policy = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            villages: vec![Hex::from_offset(24, 24)],
            rally: None,
            holds: Vec::new(),
            scouts: vec![3],
        };
        let progress = RoutineProgress::default();
        let scouts = vec![3];
        let contact_facts = CurrentContactFacts {
            trigger: "exposure",
            friendly_unit_ids: vec![2],
            enemy_unit_ids: vec![10],
            actor_ids: vec![2],
            eligible_actor_count: 1,
            actors_truncated: false,
            options: Vec::new(),
            options_truncated: false,
            options_empty_reason: None,
            coverage: "complete",
        };

        let result = find_independent_move(&s, 0, &policy, &progress, &scouts, &contact_facts);
        assert!(result.is_ok());
        let indep = result.unwrap();
        assert!(
            indep.is_some(),
            "Distant scout should be permitted to advance independently"
        );
        let execution = indep.unwrap();
        assert_eq!(execution.candidate.unit_id, 3);
        assert_eq!(execution.candidate.reason, "village");
        assert!(!execution.pre_tactical_hash.is_empty());
        assert!(!execution.post_tactical_hash.is_empty());
    }

    #[test]
    fn test_candidate_with_attack_opportunity_is_refused() {
        let registry = units();
        let mut s = test_state(25, 25);

        // Friendly warrior at (5, 5) engaged with enemy at (5, 6)
        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(5, 5));

        let e1 = Unit::from_def(10, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(5, 6));

        // Scout at (10, 10) also adjacent to another enemy at (10, 11) -> has attack opportunity!
        let f3 = Unit::from_def(3, registry.get("Ghost").unwrap(), 0);
        s.place_unit(f3, Hex::from_offset(10, 10));

        let e2 = Unit::from_def(11, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e2, Hex::from_offset(10, 11));

        s.board
            .set_tile(Hex::from_offset(24, 24), Tile::new("village"));

        let policy = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            villages: vec![Hex::from_offset(24, 24)],
            rally: None,
            holds: Vec::new(),
            scouts: vec![3],
        };
        let progress = RoutineProgress::default();
        let scouts = vec![3];
        let contact_facts = CurrentContactFacts {
            trigger: "attack_and_exposure",
            friendly_unit_ids: vec![2, 3],
            enemy_unit_ids: vec![10, 11],
            actor_ids: vec![2],
            eligible_actor_count: 1,
            actors_truncated: false,
            options: Vec::new(),
            options_truncated: false,
            options_empty_reason: None,
            coverage: "complete",
        };

        // Scout 3 has an attack opportunity, so it must NOT be moved independently
        let result = find_independent_move(&s, 0, &policy, &progress, &scouts, &contact_facts);
        assert!(result.is_ok());
        assert!(
            result.unwrap().is_none(),
            "Unit with attack opportunity must not move independently"
        );
    }

    #[test]
    fn test_candidate_move_exposing_recruiter_is_refused() {
        let registry = units();
        let mut s = test_state(25, 25);

        // Friendly warrior at (15, 15) in contact with enemy at (15, 16)
        let f2 = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(f2, Hex::from_offset(15, 15));

        let e1 = Unit::from_def(10, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e1, Hex::from_offset(15, 16));

        // Friendly scout at (0, 1) is currently screening recruiter at (0, 0).
        // Enemy at (0, 2) has melee attack. If scout moves away from (0, 1), enemy can reach recruiter!
        let f3 = Unit::from_def(3, registry.get("Ghost").unwrap(), 0);
        s.place_unit(f3, Hex::from_offset(0, 1));

        let e2 = Unit::from_def(11, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(e2, Hex::from_offset(0, 2));

        s.board
            .set_tile(Hex::from_offset(24, 24), Tile::new("village"));

        let policy = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            villages: vec![Hex::from_offset(24, 24)],
            rally: None,
            holds: Vec::new(),
            scouts: vec![3],
        };
        let progress = RoutineProgress::default();
        let scouts = vec![3];
        let contact_facts = CurrentContactFacts {
            trigger: "exposure",
            friendly_unit_ids: vec![2, 3],
            enemy_unit_ids: vec![10, 11],
            actor_ids: vec![2],
            eligible_actor_count: 1,
            actors_truncated: false,
            options: Vec::new(),
            options_truncated: false,
            options_empty_reason: None,
            coverage: "complete",
        };

        // Scout 3 moving away would expose recruiter (or scout 3 is already threatened by e2) -> refused!
        let result = find_independent_move(&s, 0, &policy, &progress, &scouts, &contact_facts);
        assert!(result.is_ok());
        assert!(
            result.unwrap().is_none(),
            "Move that exposes recruiter or is threatened must be refused"
        );
    }

    #[test]
    fn test_candidates_capped_at_eight() {
        let registry = units();
        let mut s = test_state(30, 30);

        // Place 10 scouts
        let mut scout_ids = Vec::new();
        let mut villages = Vec::new();
        for i in 2..=11 {
            let scout = Unit::from_def(i, registry.get("Ghost").unwrap(), 0);
            s.place_unit(scout, Hex::from_offset(i as i32 * 2, 2));
            scout_ids.push(i);

            let v = Hex::from_offset(i as i32 * 2, 10);
            s.board.set_tile(v, Tile::new("village"));
            villages.push(v);
        }

        let policy = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            villages,
            rally: None,
            holds: Vec::new(),
            scouts: scout_ids.clone(),
        };
        let progress = RoutineProgress::default();

        let candidates = collect_candidate_moves(&s, 0, &policy, &progress, &scout_ids);
        assert!(
            candidates.len() <= 8,
            "Candidates must be capped at 8, got {}",
            candidates.len()
        );
        assert_eq!(candidates.len(), 8);
    }
}
