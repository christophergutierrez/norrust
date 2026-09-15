//! Read-only deterministic selection for the strategy `routine_next` query.
//! Selection never mutates live state; the driver submits returned actions.

use crate::game_state::{
    apply_action, apply_recruit, legal_recruitment_placements, Action, GameState,
};
use crate::hex::Hex;
use crate::loader::Registry;
use crate::pathfinding::{find_path, get_zoc_hexes};
use crate::routine_decision::{generate_tactical_options, TacticalOption};
use crate::schema::UnitDef;
use crate::tactics::{
    recruiter_threats_after_end_turn, turn_tactics, unit_threats_after_end_turn, TacticsError,
};
use crate::unit::Unit;
use serde_json::{json, Value};
use std::collections::HashSet;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecruitEntry {
    pub def_id: String,
    pub count: u32,
    pub role: String,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RoutinePolicy {
    pub reserve_gold: u32,
    pub recruits: Vec<RecruitEntry>,
    pub scouts: Vec<u32>,
    pub villages: Vec<Hex>,
    pub rally: Option<Hex>,
    pub holds: Vec<u32>,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecruitProgress {
    pub queue_index: usize,
    pub done: u32,
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScoutAssignment {
    pub unit_id: u32,
    pub village: Hex,
}
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RoutineProgress {
    pub installation_id: Option<String>,
    pub recruited: Vec<RecruitProgress>,
    pub scout_ids: Vec<u32>,
    pub scout_assignments: Vec<ScoutAssignment>,
    pub completed_villages: Vec<Hex>,
    pub policy_complete: bool,
    pub parse_issue: Option<String>,
}
#[derive(Debug, Clone, PartialEq)]
pub enum RoutineOutcome {
    Action {
        action: Value,
        progress_update: Value,
        reason: &'static str,
        independent_move: Option<Value>,
    },
    Finish {
        reason: &'static str,
        progress_update: Value,
    },
    Exception {
        reason: &'static str,
        evidence: Value,
    },
}
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyRejected(pub String);
fn reject(message: impl Into<String>) -> PolicyRejected {
    PolicyRejected(message.into())
}

fn parse_coordinate(value: Option<&Value>, name: &str) -> Result<Hex, PolicyRejected> {
    let object = value
        .and_then(Value::as_object)
        .ok_or_else(|| reject(format!("{name} must be an object")))?;
    let col = object
        .get("col")
        .and_then(Value::as_i64)
        .filter(|v| (i32::MIN as i64..=i32::MAX as i64).contains(v))
        .ok_or_else(|| reject(format!("{name}.col must be an integer")))? as i32;
    let row = object
        .get("row")
        .and_then(Value::as_i64)
        .filter(|v| (i32::MIN as i64..=i32::MAX as i64).contains(v))
        .ok_or_else(|| reject(format!("{name}.row must be an integer")))? as i32;
    Ok(Hex::from_offset(col, row))
}

/// Parse the complete Stack 2 policy. Board/identity facts are checked by
/// `routine_next`, where the authoritative state is available.
pub fn parse_policy(policy: &Value) -> Result<RoutinePolicy, PolicyRejected> {
    let object = policy
        .as_object()
        .ok_or_else(|| reject("policy must be an object"))?;
    let reserve_gold = object
        .get("reserve_gold")
        .and_then(Value::as_u64)
        .filter(|v| *v <= u32::MAX as u64)
        .ok_or_else(|| reject("reserve_gold must be a non-negative integer"))?
        as u32;
    let values = object
        .get("recruits")
        .and_then(Value::as_array)
        .ok_or_else(|| reject("recruits must be an array"))?;
    if values.len() > 8 {
        return Err(reject("recruits must contain at most 8 entries"));
    }
    let mut recruits = Vec::with_capacity(values.len());
    for value in values {
        let entry = value
            .as_object()
            .ok_or_else(|| reject("recruit entry must be an object"))?;
        let def_id = entry
            .get("def_id")
            .and_then(Value::as_str)
            .ok_or_else(|| reject("recruit entry def_id must be a string"))?
            .to_owned();
        let count = entry
            .get("count")
            .and_then(Value::as_u64)
            .filter(|v| (1..=32).contains(v))
            .ok_or_else(|| reject("recruit entry count must be an integer in 1..=32"))?
            as u32;
        let role = entry
            .get("role")
            .and_then(Value::as_str)
            .filter(|v| matches!(*v, "scout" | "army"))
            .ok_or_else(|| reject("recruit entry role must be \"scout\" or \"army\""))?
            .to_owned();
        recruits.push(RecruitEntry {
            def_id,
            count,
            role,
        });
    }
    let parse_ids = |field: &str, limit: usize| -> Result<Vec<u32>, PolicyRejected> {
        let values = match object.get(field) {
            None | Some(Value::Null) => Vec::new(),
            Some(v) => v
                .as_array()
                .ok_or_else(|| reject(format!("{field} must be an array")))?
                .clone(),
        };
        if values.len() > limit {
            return Err(reject(format!(
                "{field} must contain at most {limit} entries"
            )));
        }
        let ids: Vec<u32> = values
            .into_iter()
            .map(|v| {
                v.as_u64()
                    .filter(|id| *id <= u32::MAX as u64)
                    .map(|id| id as u32)
                    .ok_or_else(|| reject(format!("{field} entries must be unit IDs")))
            })
            .collect::<Result<_, _>>()?;
        let mut unique = ids.clone();
        unique.sort_unstable();
        unique.dedup();
        if unique.len() != ids.len() {
            return Err(reject(format!("{field} must contain distinct IDs")));
        }
        Ok(ids)
    };
    let scouts = parse_ids("scouts", 8)?;
    let holds = parse_ids("holds", usize::MAX)?;
    if scouts.iter().any(|id| holds.contains(id)) {
        return Err(reject("held IDs cannot be scouts"));
    }
    let village_values = match object.get("villages") {
        None | Some(Value::Null) => Vec::new(),
        Some(v) => v
            .as_array()
            .ok_or_else(|| reject("villages must be an array"))?
            .clone(),
    };
    if village_values.len() > 4 {
        return Err(reject("villages must contain at most 4 entries"));
    }
    let villages: Vec<Hex> = village_values
        .iter()
        .enumerate()
        .map(|(i, v)| parse_coordinate(Some(v), &format!("villages[{i}]")))
        .collect::<Result<_, _>>()?;
    let mut unique_villages = villages.clone();
    unique_villages.sort_unstable();
    unique_villages.dedup();
    if unique_villages.len() != villages.len() {
        return Err(reject("villages must contain distinct coordinates"));
    }
    let scout_requests: u32 = recruits
        .iter()
        .filter(|r| r.role == "scout")
        .map(|r| r.count)
        .sum();
    if !villages.is_empty() && scouts.is_empty() && scout_requests == 0 {
        return Err(reject(
            "policy with villages must specify at least one scout or scout-role recruit",
        ));
    }
    let rally = match object.get("rally") {
        None | Some(Value::Null) => None,
        Some(v) => Some(parse_coordinate(Some(v), "rally")?),
    };
    Ok(RoutinePolicy {
        reserve_gold,
        recruits,
        scouts,
        villages,
        rally,
        holds,
    })
}

pub fn parse_progress(progress: &Value) -> RoutineProgress {
    let mut result = RoutineProgress::default();
    let Some(object) = progress.as_object() else {
        result.parse_issue = Some("progress must be an object".into());
        return result;
    };
    result.installation_id = object
        .get("installation_id")
        .and_then(Value::as_str)
        .map(str::to_owned);
    if let Some(values) = object.get("recruited") {
        if let Some(values) = values.as_array() {
            for value in values {
                let index = value.get("queue_index").and_then(Value::as_u64);
                let done = value.get("done").and_then(Value::as_u64);
                match (index, done) {
                    (Some(index), Some(done))
                        if index <= usize::MAX as u64 && done <= u32::MAX as u64 =>
                    {
                        result.recruited.push(RecruitProgress {
                            queue_index: index as usize,
                            done: done as u32,
                        })
                    }
                    _ => {
                        result.parse_issue =
                            Some("recruited entries require queue_index and done".into())
                    }
                }
            }
        } else {
            result.parse_issue = Some("recruited must be an array".into());
        }
    }
    if let Some(values) = object.get("scout_ids") {
        if let Some(values) = values.as_array() {
            for value in values {
                match value.as_u64().filter(|id| *id <= u32::MAX as u64) {
                    Some(id) => result.scout_ids.push(id as u32),
                    None => {
                        result.parse_issue = Some("scout_ids contains an invalid unit ID".into())
                    }
                }
            }
        } else {
            result.parse_issue = Some("scout_ids must be an array".into());
        }
    }
    if let Some(values) = object.get("scout_assignments") {
        if let Some(values) = values.as_array() {
            for value in values {
                let id = value
                    .get("unit_id")
                    .and_then(Value::as_u64)
                    .filter(|id| *id <= u32::MAX as u64);
                match (id, parse_coordinate(Some(value), "scout assignment")) {
                    (Some(id), Ok(village)) => result.scout_assignments.push(ScoutAssignment {
                        unit_id: id as u32,
                        village,
                    }),
                    _ => {
                        result.parse_issue =
                            Some("scout_assignments contains an invalid entry".into())
                    }
                }
            }
        } else {
            result.parse_issue = Some("scout_assignments must be an array".into());
        }
    }
    if let Some(values) = object.get("completed_villages") {
        if let Some(values) = values.as_array() {
            for value in values {
                match parse_coordinate(Some(value), "completed village") {
                    Ok(village) => result.completed_villages.push(village),
                    Err(_) => {
                        result.parse_issue =
                            Some("completed_villages contains an invalid coordinate".into())
                    }
                }
            }
        } else {
            result.parse_issue = Some("completed_villages must be an array".into());
        }
    }
    result.policy_complete = object
        .get("policy_complete")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    result
}

fn progress_update(effects: Vec<Value>) -> Value {
    json!({"effects": effects})
}

fn finish_effects(state: &GameState, policy: &RoutinePolicy, side: u8) -> Vec<Value> {
    policy
        .villages
        .iter()
        .filter(|village| {
            state.village_owners.get(village).copied() != Some(side as i8)
                && state.units.iter().any(|(id, unit)| {
                    unit.faction == side && state.positions.get(id) == Some(village)
                })
        })
        .map(|village| {
            json!({
                "kind":"completed_village",
                "col":village.to_offset().0,
                "row":village.to_offset().1
            })
        })
        .collect()
}
fn recruited_done(progress: &RoutineProgress, queue_index: usize) -> u32 {
    progress
        .recruited
        .iter()
        .filter(|p| p.queue_index == queue_index)
        .map(|p| p.done)
        .sum()
}
fn next_recruit<'a>(
    policy: &'a RoutinePolicy,
    progress: &RoutineProgress,
) -> Option<(usize, &'a RecruitEntry)> {
    policy
        .recruits
        .iter()
        .enumerate()
        .find(|(i, e)| recruited_done(progress, *i) < e.count)
}
pub(crate) fn coord(hex: Hex) -> Value {
    let (col, row) = hex.to_offset();
    json!({"col":col,"row":row})
}
pub(crate) fn is_recruiter(unit: &Unit) -> bool {
    unit.can_recruit || unit.abilities.iter().any(|a| a == "leader")
}
fn recruiter(unit: &Unit) -> bool {
    is_recruiter(unit)
}
fn scout_ids(policy: &RoutinePolicy, progress: &RoutineProgress) -> Vec<u32> {
    let mut ids = policy.scouts.clone();
    ids.extend(progress.scout_ids.iter().copied());
    ids.sort_unstable();
    ids.dedup();
    ids
}

fn validate_identity(
    state: &GameState,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    side: u8,
) -> Result<Vec<u32>, Value> {
    if let Some(issue) = &progress.parse_issue {
        return Err(json!({"cause":"malformed_progress","detail":issue}));
    }
    let scouts = scout_ids(policy, progress);
    for id in scouts.iter().chain(policy.holds.iter()) {
        match state.units.get(id) {
            Some(unit) if unit.faction == side && state.positions.contains_key(id) => {}
            _ => return Err(json!({"cause":"dead_or_foreign_unit","unit_id":id})),
        }
    }
    if policy
        .scouts
        .iter()
        .any(|id| state.units.get(id).is_some_and(recruiter))
    {
        return Err(json!({"cause":"scout_is_recruiter"}));
    }
    let mut assigned_units = HashSet::new();
    let mut assigned_villages = HashSet::new();
    for assignment in &progress.scout_assignments {
        if !assigned_units.insert(assignment.unit_id)
            || !assigned_villages.insert(assignment.village)
        {
            return Err(
                json!({"cause":"duplicate_scout_assignment","unit_id":assignment.unit_id,"village":coord(assignment.village)}),
            );
        }
        if !scouts.contains(&assignment.unit_id) || policy.holds.contains(&assignment.unit_id) {
            return Err(
                json!({"cause":"assignment_unit_not_eligible","unit_id":assignment.unit_id}),
            );
        }
        if !policy.villages.contains(&assignment.village) {
            return Err(
                json!({"cause":"assignment_village_not_selected","unit_id":assignment.unit_id,"village":coord(assignment.village)}),
            );
        }
    }
    if let Some(village) = progress
        .completed_villages
        .iter()
        .find(|village| !policy.villages.contains(village))
    {
        return Err(json!({"cause":"completed_village_not_selected","village":coord(*village)}));
    }
    Ok(scouts)
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct CurrentContactFacts {
    pub trigger: &'static str,
    pub friendly_unit_ids: Vec<u32>,
    pub enemy_unit_ids: Vec<u32>,
    pub actor_ids: Vec<u32>,
    pub eligible_actor_count: u32,
    pub actors_truncated: bool,
    pub options: Vec<TacticalOption>,
    pub options_truncated: bool,
    pub options_empty_reason: Option<String>,
    pub coverage: &'static str,
}

pub(crate) fn current_contact(
    state: &GameState,
    side: u8,
) -> Result<Option<CurrentContactFacts>, TacticsError> {
    let mut attack_friendly = Vec::new();
    let mut attack_enemy = Vec::new();
    for u in turn_tactics(state, side)? {
        let mut has_eng = false;
        for o in &u.origins {
            for e in &o.engagements {
                has_eng = true;
                attack_enemy.push(e.defender_id);
            }
        }
        if has_eng {
            attack_friendly.push(u.unit_id);
        }
    }

    let mut exposure_friendly = Vec::new();
    let mut exposure_enemy = Vec::new();
    for u in unit_threats_after_end_turn(state, side)?.units {
        if u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0 {
            exposure_friendly.push(u.unit_id);
            exposure_enemy.extend(u.attacker_ids);
        }
    }
    for r in recruiter_threats_after_end_turn(state, side)?.recruiters {
        if r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0 {
            exposure_friendly.push(r.recruiter_id);
            for t in &r.threats {
                exposure_enemy.push(t.attacker_id);
            }
            for t in &r.open_threats {
                exposure_enemy.push(t.attacker_id);
            }
        }
    }

    let has_attack = !attack_friendly.is_empty();
    let has_exposure = !exposure_friendly.is_empty();

    if !has_attack && !has_exposure {
        return Ok(None);
    }

    let trigger = match (has_attack, has_exposure) {
        (true, true) => "attack_and_exposure",
        (true, false) => "attack",
        (false, true) => "exposure",
        (false, false) => unreachable!(),
    };

    let mut friendly_unit_ids: Vec<u32> = attack_friendly
        .into_iter()
        .chain(exposure_friendly)
        .collect();
    friendly_unit_ids.sort_unstable();
    friendly_unit_ids.dedup();

    let mut enemy_unit_ids: Vec<u32> = attack_enemy.into_iter().chain(exposure_enemy).collect();
    enemy_unit_ids.sort_unstable();
    enemy_unit_ids.dedup();

    let tactical_decision = generate_tactical_options(state, side)?;

    Ok(Some(CurrentContactFacts {
        trigger,
        friendly_unit_ids,
        enemy_unit_ids,
        actor_ids: tactical_decision.actor_ids,
        eligible_actor_count: tactical_decision.eligible_actor_count,
        actors_truncated: tactical_decision.actors_truncated,
        options: tactical_decision.options,
        options_truncated: tactical_decision.options_truncated,
        options_empty_reason: tactical_decision.options_empty_reason,
        coverage: "complete",
    }))
}
fn post_step_safe(state: &GameState, side: u8, action: Action) -> Result<bool, TacticsError> {
    let mut clone = state.clone();
    apply_action(&mut clone, action)?;
    if unit_threats_after_end_turn(&clone, side)?
        .units
        .iter()
        .any(|u| u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0)
    {
        return Ok(false);
    }
    Ok(!recruiter_threats_after_end_turn(&clone, side)?
        .recruiters
        .iter()
        .any(|u| u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0))
}

/// Return legal endpoints on a shortest terrain-cost route, ordered from
/// furthest to nearest. The engine permits occupied intermediate hexes; only
/// the submitted endpoint must be empty.
pub(crate) fn route_endpoints(state: &GameState, unit_id: u32, goals: &[Hex]) -> Vec<(Hex, bool)> {
    let Some(unit) = state.units.get(&unit_id) else {
        return Vec::new();
    };
    if unit.moved {
        return Vec::new();
    }
    let Some(start) = state.positions.get(&unit_id).copied() else {
        return Vec::new();
    };
    if goals.contains(&start) {
        return vec![(start, true)];
    }
    let budget = if unit.slowed {
        unit.movement / 2
    } else {
        unit.movement
    };
    let zoc = get_zoc_hexes(state, unit.faction);
    let mut candidates = Vec::new();
    for &goal in goals {
        let Some((path, total)) = find_path(
            &state.board,
            &unit.movement_costs,
            1,
            start,
            goal,
            u32::MAX / 4,
            &zoc,
            false,
        ) else {
            continue;
        };
        let mut cost = 0;
        for endpoint in path.iter().skip(1) {
            let terrain = state.board.terrain_at(*endpoint).unwrap_or("");
            cost += unit.movement_costs.get(terrain).copied().unwrap_or(1);
            if cost > budget {
                break;
            };
            if !state.hex_to_unit.contains_key(endpoint) {
                candidates.push((*endpoint, cost, total));
            }
        }
    }
    candidates.sort_by_key(|(h, cost, total)| {
        let (c, r) = h.to_offset();
        (*total, std::cmp::Reverse(*cost), r, c)
    });
    candidates.into_iter().map(|(h, _, _)| (h, false)).collect()
}

fn scout_goal(
    state: &GameState,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    side: u8,
    scouts: &[u32],
) -> Result<Option<(u32, Hex, Vec<Value>)>, Value> {
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
                || state.units.get(&id).is_some_and(recruiter)
            {
                continue;
            };
            let Some(start) = state.positions.get(&id).copied() else {
                continue;
            };
            let unit = state.units.get(&id).unwrap();
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
    if let Some((_, village, id)) = pairs.first().copied() {
        return Ok(Some((
            id,
            village,
            vec![
                json!({"kind":"scout_assigned","unit_id":id,"col":village.to_offset().0,"row":village.to_offset().1}),
            ],
        )));
    }
    for a in assignments {
        if policy.holds.contains(&a.unit_id) {
            continue;
        };
        if let Some(unit) = state.units.get(&a.unit_id) {
            if let Some(start) = state.positions.get(&a.unit_id) {
                if *start != a.village
                    && !state
                        .village_owners
                        .get(&a.village)
                        .is_some_and(|o| *o == side as i8)
                {
                    if unit.moved {
                        continue;
                    };
                    return Ok(Some((a.unit_id, a.village, Vec::new())));
                }
            }
        }
    }
    Ok(None)
}

/// Find a still-unassigned village for which at least one eligible, unmoved
/// scout exists but the engine cannot produce any terrain/ZOC route. This is
/// distinct from a scout that has spent movement and therefore merely needs a
/// boundary before it can continue.
fn unreachable_unassigned_village(
    state: &GameState,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    side: u8,
    scouts: &[u32],
) -> Option<Hex> {
    let completed: HashSet<Hex> = progress.completed_villages.iter().copied().collect();
    let owned: HashSet<Hex> = state
        .village_owners
        .iter()
        .filter_map(|(hex, owner)| (*owner == side as i8).then_some(*hex))
        .collect();
    let assigned: HashSet<Hex> = progress
        .scout_assignments
        .iter()
        .map(|a| a.village)
        .collect();
    for &village in &policy.villages {
        if completed.contains(&village) || owned.contains(&village) || assigned.contains(&village) {
            continue;
        }
        let mut eligible = false;
        let mut reachable = false;
        for &id in scouts {
            if progress.scout_assignments.iter().any(|a| a.unit_id == id)
                || policy.holds.contains(&id)
                || state.units.get(&id).is_some_and(recruiter)
            {
                continue;
            }
            let Some(unit) = state.units.get(&id) else {
                continue;
            };
            if unit.moved || state.positions.get(&id).is_none() {
                continue;
            }
            eligible = true;
            if find_path(
                &state.board,
                &unit.movement_costs,
                1,
                state.positions[&id],
                village,
                u32::MAX / 4,
                &get_zoc_hexes(state, side),
                false,
            )
            .is_some()
            {
                reachable = true;
                break;
            }
        }
        if eligible && !reachable {
            return Some(village);
        }
    }
    None
}
pub(crate) fn rally_goals(state: &GameState, rally: Hex) -> Vec<Hex> {
    if !state.hex_to_unit.contains_key(&rally) {
        return vec![rally];
    }
    let mut goals: Vec<Hex> = rally
        .neighbors()
        .into_iter()
        .filter(|h| state.board.contains(*h) && !state.hex_to_unit.contains_key(h))
        .collect();
    goals.sort_by_key(|h| {
        let (c, r) = h.to_offset();
        (r, c)
    });
    goals
}

pub fn routine_next(
    state: &GameState,
    side: u8,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    recruit_ids: &[String],
    units: &Registry<UnitDef>,
) -> RoutineOutcome {
    if let Some(village) = policy.villages.iter().find(|v| {
        !state.board.contains(**v)
            || state
                .board
                .tile_at(**v)
                .is_none_or(|tile| tile.terrain_id != "village")
    }) {
        return RoutineOutcome::Exception {
            reason: "invalid_assignment",
            evidence: json!({"cause":"invalid_village_objective","village":coord(*village)}),
        };
    }
    if policy
        .rally
        .is_some_and(|rally| !state.board.contains(rally))
    {
        return RoutineOutcome::Exception {
            reason: "invalid_assignment",
            evidence: json!({"cause":"invalid_rally"}),
        };
    }
    let scouts = match validate_identity(state, policy, progress, side) {
        Ok(v) => v,
        Err(e) => {
            return RoutineOutcome::Exception {
                reason: "invalid_assignment",
                evidence: e,
            }
        }
    };
    let pending: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(id, u)| (u.faction == side && u.advancement_pending).then_some(*id))
        .collect();
    if !pending.is_empty() {
        return RoutineOutcome::Exception {
            reason: "promotion_pending",
            evidence: json!({"unit_ids":pending}),
        };
    }
    match current_contact(state, side) {
        Ok(Some(facts)) => {
            match crate::routine_independent::find_independent_move(
                state, side, policy, progress, &scouts, &facts,
            ) {
                Ok(Some(indep)) => {
                    let (col, row) = indep.candidate.destination.to_offset();
                    let (obj_col, obj_row) = indep.candidate.objective_target.to_offset();
                    let deferred_incident_key = json!({
                        "reason": "contact",
                        "stage": "current_state",
                        "trigger": facts.trigger,
                        "friendly_unit_ids": facts.friendly_unit_ids,
                        "enemy_unit_ids": facts.enemy_unit_ids,
                    });
                    let independent_move_meta = json!({
                        "policy_objective": {
                            "type": indep.candidate.objective_kind,
                            "target": {"col": obj_col, "row": obj_row},
                        },
                        "coverage": "complete",
                        "pre_tactical_hash": indep.pre_tactical_hash,
                        "post_tactical_hash": indep.post_tactical_hash,
                        "deferred_incident_key": deferred_incident_key,
                    });
                    return RoutineOutcome::Action {
                        action: json!({"action":"Move","unit_id":indep.candidate.unit_id,"col":col,"row":row}),
                        progress_update: progress_update(indep.candidate.progress_effects),
                        reason: indep.candidate.reason,
                        independent_move: Some(independent_move_meta),
                    };
                }
                Ok(None) => {}
                Err(e) => {
                    return RoutineOutcome::Exception {
                        reason: "threat_unavailable",
                        evidence: json!({"stage":"current_state","detail":e.to_string()}),
                    };
                }
            }

            return RoutineOutcome::Exception {
                reason: "contact",
                evidence: json!({
                    "stage": "current_state",
                    "trigger": facts.trigger,
                    "friendly_unit_ids": facts.friendly_unit_ids,
                    "enemy_unit_ids": facts.enemy_unit_ids,
                    "actor_ids": facts.actor_ids,
                    "eligible_actor_count": facts.eligible_actor_count,
                    "actors_truncated": facts.actors_truncated,
                    "options": facts.options,
                    "options_truncated": facts.options_truncated,
                    "options_empty_reason": facts.options_empty_reason,
                    "coverage": facts.coverage,
                }),
            };
        }
        Ok(None) => {}
        Err(e) => {
            return RoutineOutcome::Exception {
                reason: "threat_unavailable",
                evidence: json!({"stage":"current_state","detail":e.to_string()}),
            };
        }
    }
    if progress.policy_complete {
        return RoutineOutcome::Exception {
            reason: "objectives_complete",
            evidence: json!({"policy_complete":true}),
        };
    }
    match scout_goal(state, policy, progress, side, &scouts) {
        Err(e) => {
            return RoutineOutcome::Exception {
                reason: "invalid_assignment",
                evidence: e,
            }
        }
        Ok(Some((id, village, mut effects))) => {
            let endpoints = route_endpoints(state, id, &[village]);
            if endpoints.is_empty() {
                if state.units.get(&id).is_some_and(|u| u.moved) {
                    return RoutineOutcome::Finish {
                        reason: "no_remaining_routine_steps",
                        progress_update: progress_update(Vec::new()),
                    };
                };
                return RoutineOutcome::Exception {
                    reason: "route_unavailable",
                    evidence: json!({"unit_id":id,"target":coord(village),"cause":"unreachable_or_no_legal_endpoint"}),
                };
            }
            let mut unsafe_destination = None;
            for (destination, arrived) in endpoints {
                if arrived {
                    effects.extend(finish_effects(state, policy, side));
                    return RoutineOutcome::Finish {
                        reason: "no_remaining_routine_steps",
                        progress_update: progress_update(effects),
                    };
                }
                let action = Action::Move {
                    unit_id: id,
                    destination,
                };
                match post_step_safe(state, side, action) {
                    Ok(true) => {
                        effects.shrink_to_fit();
                        return RoutineOutcome::Action {
                            action: json!({"action":"Move","unit_id":id,"col":destination.to_offset().0,"row":destination.to_offset().1}),
                            progress_update: progress_update(effects),
                            reason: "village",
                            independent_move: None,
                        };
                    }
                    Ok(false) => unsafe_destination = Some(destination),
                    Err(e) => {
                        return RoutineOutcome::Exception {
                            reason: "threat_unavailable",
                            evidence: json!({"stage":"proposed_destination","detail":e.to_string()}),
                        }
                    }
                }
            }
            if let Some(destination) = unsafe_destination {
                return RoutineOutcome::Exception {
                    reason: "contact",
                    evidence: json!({"stage":"proposed_destination","unit_id":id,"destination":coord(destination)}),
                };
            }
            return RoutineOutcome::Exception {
                reason: "unsafe_route",
                evidence: json!({"unit_id":id,"target":coord(village),"cause":"no_safe_endpoint"}),
            };
        }
        Ok(None) => {}
    }
    if let Some(village) = unreachable_unassigned_village(state, policy, progress, side, &scouts) {
        return RoutineOutcome::Exception {
            reason: "route_unavailable",
            evidence: json!({"target":coord(village),"cause":"unreachable_or_no_legal_endpoint"}),
        };
    }
    if let Some((index, entry)) = next_recruit(policy, progress) {
        let Some(def) = units.get(&entry.def_id) else {
            return RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({"def_id":entry.def_id,"cause":"unknown_definition"}),
            };
        };
        if !recruit_ids.iter().any(|id| id == &entry.def_id) {
            return RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({"def_id":entry.def_id,"cause":"not_recruitable"}),
            };
        }
        let available = state.gold[side as usize].saturating_sub(policy.reserve_gold);
        if available < def.cost {
            let income = crate::tactics::economy_facts(state, side)
                .map(|(i, _)| i)
                .unwrap_or(0);
            let occupied_village = state.units.iter().any(|(id, unit)| {
                unit.faction == side
                    && state.positions.get(id).is_some_and(|position| {
                        state
                            .board
                            .tile_at(*position)
                            .is_some_and(|tile| tile.terrain_id == "village")
                            && state.village_owners.get(position).copied() != Some(side as i8)
                    })
            });
            if income > 0 || occupied_village {
                return RoutineOutcome::Finish {
                    reason: "no_remaining_routine_steps",
                    progress_update: progress_update(Vec::new()),
                };
            }
            return RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({"def_id":entry.def_id,"cost":def.cost,"available":available,"cause":"insufficient_gold_no_income"}),
            };
        }
        let mut placements = legal_recruitment_placements(state, side);
        placements.sort_by_key(|h| {
            let (c, r) = h.to_offset();
            (r, c)
        });
        let Some(placement) = placements.first().copied() else {
            // A full keep may be relieved only by ordinary army travel. This
            // is deliberately below recruitment in the priority order and
            // never vacates a scout, hold, or recruiter implicitly.
            if let Some(rally) = policy.rally {
                let mut vacatable: Vec<u32> = state
                    .units
                    .iter()
                    .filter_map(|(id, unit)| {
                        let position = state.positions.get(id)?;
                        (unit.faction == side
                            && !unit.moved
                            && !recruiter(unit)
                            && !scouts.contains(id)
                            && !policy.holds.contains(id)
                            && state
                                .board
                                .tile_at(*position)
                                .is_some_and(|tile| tile.terrain_id == "castle"))
                        .then_some(*id)
                    })
                    .collect();
                vacatable.sort_unstable();
                let goals = rally_goals(state, rally);
                let mut unsafe_destination = None;
                for id in vacatable {
                    for (destination, arrived) in route_endpoints(state, id, &goals) {
                        if arrived {
                            continue;
                        }
                        let action = Action::Move {
                            unit_id: id,
                            destination,
                        };
                        match post_step_safe(state, side, action) {
                            Ok(true) => {
                                return RoutineOutcome::Action {
                                    action: json!({"action":"Move","unit_id":id,"col":destination.to_offset().0,"row":destination.to_offset().1}),
                                    progress_update: progress_update(Vec::new()),
                                    reason: "castle_capacity",
                                    independent_move: None,
                                }
                            }
                            Ok(false) => unsafe_destination = Some((id, destination)),
                            Err(error) => {
                                return RoutineOutcome::Exception {
                                    reason: "threat_unavailable",
                                    evidence: json!({"stage":"proposed_destination","detail":error.to_string()}),
                                }
                            }
                        }
                    }
                }
                if let Some((id, destination)) = unsafe_destination {
                    return RoutineOutcome::Exception {
                        reason: "contact",
                        evidence: json!({"stage":"proposed_destination","unit_id":id,"destination":coord(destination)}),
                    };
                }
                if state.units.iter().any(|(id, unit)| {
                    let Some(position) = state.positions.get(id) else {
                        return false;
                    };
                    unit.faction == side
                        && unit.moved
                        && !recruiter(unit)
                        && !scouts.contains(id)
                        && !policy.holds.contains(id)
                        && state
                            .board
                            .tile_at(*position)
                            .is_some_and(|tile| tile.terrain_id == "castle")
                }) {
                    return RoutineOutcome::Finish {
                        reason: "no_remaining_routine_steps",
                        progress_update: progress_update(Vec::new()),
                    };
                }
            }
            return RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({"def_id":entry.def_id,"cause":"no_placement_hex"}),
            };
        };
        let mut clone = state.clone();
        let temp = clone
            .units
            .keys()
            .copied()
            .max()
            .unwrap_or(0)
            .saturating_add(1);
        if apply_recruit(
            &mut clone,
            Unit::from_def(temp, def, side),
            placement,
            def.cost,
        )
        .is_err()
        {
            return RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({"def_id":entry.def_id,"cause":"placement_rejected"}),
            };
        };
        match unit_threats_after_end_turn(&clone, side) {
            Ok(surface)
                if surface.units.iter().any(|u| {
                    u.unit_id == temp
                        && (u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0)
                }) =>
            {
                return RoutineOutcome::Exception {
                    reason: "contact",
                    evidence: json!({"stage":"proposed_placement","target":coord(placement)}),
                }
            }
            Err(e) => {
                return RoutineOutcome::Exception {
                    reason: "threat_unavailable",
                    evidence: json!({"stage":"proposed_placement","detail":e.to_string()}),
                }
            }
            _ => {}
        }
        match recruiter_threats_after_end_turn(&clone, side) {
            Ok(surface)
                if surface.recruiters.iter().any(|u| {
                    u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0
                }) =>
            {
                return RoutineOutcome::Exception {
                    reason: "contact",
                    evidence: json!({"stage":"proposed_placement_recruiter","target":coord(placement)}),
                }
            }
            Err(e) => {
                return RoutineOutcome::Exception {
                    reason: "threat_unavailable",
                    evidence: json!({"stage":"proposed_placement_recruiter","detail":e.to_string()}),
                }
            }
            _ => {}
        }
        return RoutineOutcome::Action {
            action: json!({"action":"Recruit","def_id":entry.def_id,"col":placement.to_offset().0,"row":placement.to_offset().1}),
            progress_update: progress_update(vec![json!({"kind":"recruited","queue_index":index})]),
            reason: "recruit",
            independent_move: None,
        };
    }
    if let Some(rally) = policy.rally {
        let mut ids: Vec<u32> = state
            .units
            .iter()
            .filter_map(|(id, u)| {
                (u.faction == side
                    && !u.moved
                    && !recruiter(u)
                    && !scouts.contains(id)
                    && !policy.holds.contains(id))
                .then_some(*id)
            })
            .collect();
        ids.sort_unstable();
        let goals = rally_goals(state, rally);
        for id in ids {
            if state
                .positions
                .get(&id)
                .is_some_and(|position| position.distance(rally) <= 1)
            {
                continue;
            }
            let endpoints = route_endpoints(state, id, &goals);
            if endpoints.is_empty() {
                if state.units.get(&id).is_some_and(|u| u.moved) {
                    continue;
                }
                return RoutineOutcome::Exception {
                    reason: "route_unavailable",
                    evidence: json!({"unit_id":id,"target":coord(rally),"cause":"unreachable_or_no_legal_endpoint"}),
                };
            }
            let mut unsafe_destination = None;
            for (destination, arrived) in endpoints {
                if arrived {
                    continue;
                }
                let action = Action::Move {
                    unit_id: id,
                    destination,
                };
                match post_step_safe(state, side, action) {
                    Ok(true) => {
                        return RoutineOutcome::Action {
                            action: json!({"action":"Move","unit_id":id,"col":destination.to_offset().0,"row":destination.to_offset().1}),
                            progress_update: progress_update(Vec::new()),
                            reason: "rally",
                            independent_move: None,
                        }
                    }
                    Ok(false) => unsafe_destination = Some(destination),
                    Err(e) => {
                        return RoutineOutcome::Exception {
                            reason: "threat_unavailable",
                            evidence: json!({"stage":"proposed_destination","detail":e.to_string()}),
                        }
                    }
                }
            }
            if let Some(destination) = unsafe_destination {
                return RoutineOutcome::Exception {
                    reason: "contact",
                    evidence: json!({"stage":"proposed_destination","unit_id":id,"destination":coord(destination)}),
                };
            }
            return RoutineOutcome::Exception {
                reason: "unsafe_route",
                evidence: json!({"unit_id":id,"target":coord(rally),"cause":"no_safe_endpoint"}),
            };
        }
    }
    let pending_village = policy.villages.iter().any(|village| {
        progress
            .completed_villages
            .iter()
            .all(|done| done != village)
            && state.village_owners.get(village).copied() != Some(side as i8)
    });
    if pending_village && scouts.is_empty() {
        return RoutineOutcome::Exception {
            reason: "no_executable_orders",
            evidence: json!({"cause":"village_requires_scout","villages":policy.villages.iter().map(|v|coord(*v)).collect::<Vec<_>>() }),
        };
    }
    if pending_village {
        let assigned_ids: HashSet<u32> = progress
            .scout_assignments
            .iter()
            .map(|assignment| assignment.unit_id)
            .collect();
        let unassigned_unspent = scouts.iter().any(|id| {
            !assigned_ids.contains(id)
                && !policy.holds.contains(id)
                && !state.units.get(id).is_some_and(recruiter)
                && state.units.get(id).is_some_and(|unit| !unit.moved)
        });
        let unassigned_spent = scouts.iter().any(|id| {
            !assigned_ids.contains(id)
                && !policy.holds.contains(id)
                && !state.units.get(id).is_some_and(recruiter)
                && state.units.get(id).is_some_and(|unit| unit.moved)
        });
        let assigned_pending = progress.scout_assignments.iter().any(|assignment| {
            !progress.completed_villages.contains(&assignment.village)
                && state.village_owners.get(&assignment.village).copied() != Some(side as i8)
        });
        let standing_capture = !finish_effects(state, policy, side).is_empty();
        if !unassigned_unspent && !unassigned_spent && !assigned_pending && !standing_capture {
            return RoutineOutcome::Exception {
                reason: "no_executable_orders",
                evidence: json!({"cause":"no_scout_available_for_village","villages":policy.villages.iter().map(|v|coord(*v)).collect::<Vec<_>>() }),
            };
        }
    }
    let queue_complete = next_recruit(policy, progress).is_none();
    let finishing_villages = finish_effects(state, policy, side);
    let finishing_village_coords: HashSet<Hex> = finishing_villages
        .iter()
        .filter_map(|effect| {
            Some(Hex::from_offset(
                effect.get("col")?.as_i64()? as i32,
                effect.get("row")?.as_i64()? as i32,
            ))
        })
        .collect();
    let villages_complete = policy.villages.iter().all(|village| {
        state.village_owners.get(village).copied() == Some(side as i8)
            || finishing_village_coords.contains(village)
    });
    let rally_complete = policy.rally.is_none_or(|rally| {
        state.units.iter().all(|(id, unit)| {
            if unit.faction != side
                || recruiter(unit)
                || scouts.contains(id)
                || policy.holds.contains(id)
            {
                return true;
            }
            state
                .positions
                .get(id)
                .is_some_and(|position| position.distance(rally) <= 1)
        })
    });
    if queue_complete && villages_complete && rally_complete {
        let mut effects = finishing_villages;
        effects.push(json!({"kind":"policy_completed"}));
        return RoutineOutcome::Finish {
            reason: "objectives_complete",
            progress_update: progress_update(effects),
        };
    }
    RoutineOutcome::Finish {
        reason: "no_remaining_routine_steps",
        progress_update: progress_update(finish_effects(state, policy, side)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Tile};
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
    fn state() -> GameState {
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

    fn policy(recruits: &[(&str, u32, &str)]) -> RoutinePolicy {
        RoutinePolicy {
            reserve_gold: 0,
            recruits: recruits
                .iter()
                .map(|(def_id, count, role)| RecruitEntry {
                    def_id: (*def_id).into(),
                    count: *count,
                    role: (*role).into(),
                })
                .collect(),
            scouts: Vec::new(),
            villages: Vec::new(),
            rally: None,
            holds: Vec::new(),
        }
    }

    fn village_state() -> (GameState, Hex) {
        let mut s = state();
        let village = Hex::from_offset(5, 4);
        s.board.set_tile(village, Tile::new("village"));
        (s, village)
    }
    #[test]
    fn parses_stack2_policy() {
        let p=parse_policy(&json!({"reserve_gold":4,"recruits":[],"scouts":[9],"villages":[{"col":2,"row":3}],"rally":{"col":6,"row":5},"holds":[8]})).unwrap();
        assert_eq!(p.villages[0], Hex::from_offset(2, 3));
        assert_eq!(p.rally, Some(Hex::from_offset(6, 5)));
    }
    #[test]
    fn duplicate_queue_definitions_use_indexes() {
        let s = state();
        let p=parse_policy(&json!({"reserve_gold":0,"recruits":[{"def_id":"Skeleton","count":1,"role":"army"},{"def_id":"Skeleton","count":1,"role":"army"}],"scouts":[],"villages":[],"rally":null,"holds":[]})).unwrap();
        let r = RoutineProgress {
            recruited: vec![RecruitProgress {
                queue_index: 0,
                done: 1,
            }],
            ..Default::default()
        };
        assert!(
            matches!(routine_next(&s,0,&p,&r,&["Skeleton".into()],&units()),RoutineOutcome::Action{progress_update,..} if progress_update["effects"][0]["queue_index"]==1)
        );
    }
    #[test]
    fn finish_has_effects_array() {
        let s = state();
        let p=parse_policy(&json!({"reserve_gold":0,"recruits":[],"scouts":[],"villages":[],"rally":null,"holds":[]})).unwrap();
        assert!(
            matches!(routine_next(&s,0,&p,&RoutineProgress::default(),&[],&units()),RoutineOutcome::Finish{progress_update,..} if progress_update["effects"].is_array())
        );
    }

    #[test]
    fn old_stack1_queue_reserve_and_roster_guards_remain() {
        let registry = units();
        let recruit_ids = vec!["Skeleton".to_owned()];
        let mut p = policy(&[("Skeleton", 2, "army")]);
        let mut s = state();
        s.gold[0] = registry.get("Skeleton").unwrap().cost;
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &recruit_ids,
                &registry
            ),
            RoutineOutcome::Action {
                reason: "recruit",
                ..
            }
        ));
        s.gold[0] = registry.get("Skeleton").unwrap().cost - 1;
        p.reserve_gold = 0;
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &recruit_ids,
                &registry
            ),
            RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                ..
            }
        ));
        p.recruits[0].def_id = "Ghost".into();
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &recruit_ids,
                &registry
            ),
            RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                ..
            }
        ));
    }

    #[test]
    fn recruiter_exposure_pauses_before_recruitment() {
        let registry = units();
        let mut s = state();
        let enemy_hex = Hex::from_offset(2, 1);
        let mut enemy = Unit::from_def(9, registry.get("Skeleton").unwrap(), 1);
        enemy.attacks = registry.get("Skeleton").unwrap().attacks.clone();
        s.place_unit(enemy, enemy_hex);
        let p = policy(&[("Skeleton", 1, "army")]);
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &["Skeleton".into()],
                &registry
            ),
            RoutineOutcome::Exception {
                reason: "contact",
                ..
            }
        ));
    }

    #[test]
    fn routine_query_preserves_rng_ids_and_state_revision() {
        let registry = units();
        let s = state();
        let before = (
            s.rng.state(),
            s.next_unit_id,
            s.state_revision,
            s.gold,
            s.units.len(),
        );
        let p = policy(&[("Skeleton", 1, "army")]);
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &["Skeleton".into()],
                &registry
            ),
            RoutineOutcome::Action { .. }
        ));
        assert_eq!(
            (
                s.rng.state(),
                s.next_unit_id,
                s.state_revision,
                s.gold,
                s.units.len()
            ),
            before
        );
    }

    #[test]
    fn three_distinct_scouts_and_held_units_are_filtered_deterministically() {
        let registry = units();
        let (mut s, village) = village_state();
        for (id, position) in [
            (2, Hex::from_offset(3, 4)),
            (3, Hex::from_offset(3, 5)),
            (4, Hex::from_offset(3, 6)),
        ] {
            s.place_unit(
                Unit::from_def(id, registry.get("Ghost").unwrap(), 0),
                position,
            );
        }
        let p = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            scouts: vec![2, 3, 4],
            villages: vec![village],
            rally: None,
            holds: vec![3],
        };
        let outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        assert!(
            matches!(outcome, RoutineOutcome::Action { action, progress_update, .. }
            if action["unit_id"] == 2 && progress_update["effects"][0]["unit_id"] == 2)
        );
    }

    #[test]
    fn dead_assignment_is_typed_and_does_not_fall_through_to_recruitment() {
        let registry = units();
        let (s, village) = village_state();
        let p = RoutinePolicy {
            reserve_gold: 0,
            recruits: vec![RecruitEntry {
                def_id: "Skeleton".into(),
                count: 1,
                role: "army".into(),
            }],
            scouts: vec![2],
            villages: vec![village],
            rally: None,
            holds: Vec::new(),
        };
        let progress = RoutineProgress {
            scout_ids: vec![2],
            scout_assignments: vec![ScoutAssignment {
                unit_id: 2,
                village,
            }],
            ..Default::default()
        };
        assert!(matches!(
            routine_next(&s, 0, &p, &progress, &["Skeleton".into()], &registry),
            RoutineOutcome::Exception { reason: "invalid_assignment", evidence }
                if evidence["cause"] == "dead_or_foreign_unit"
        ));
    }

    #[test]
    fn moved_assigned_scout_finishes_without_claiming_capture() {
        let registry = units();
        let (mut s, village) = village_state();
        let mut scout = Unit::from_def(2, registry.get("Ghost").unwrap(), 0);
        scout.moved = true;
        s.place_unit(scout, Hex::from_offset(3, 4));
        let p = RoutinePolicy {
            reserve_gold: 0,
            recruits: Vec::new(),
            scouts: vec![2],
            villages: vec![village],
            rally: None,
            holds: Vec::new(),
        };
        let progress = RoutineProgress {
            scout_assignments: vec![ScoutAssignment {
                unit_id: 2,
                village,
            }],
            ..Default::default()
        };
        let moved_outcome = routine_next(&s, 0, &p, &progress, &[], &registry);
        assert!(matches!(
            moved_outcome,
            RoutineOutcome::Finish { reason: "no_remaining_routine_steps", progress_update }
                if progress_update["effects"].as_array().unwrap().is_empty()
        ));
    }

    #[test]
    fn occupied_castles_do_not_vacate_held_units_or_recruiter() {
        let registry = units();
        let mut s = state();
        let keep = Hex::from_offset(1, 1);
        let held = keep
            .neighbors()
            .into_iter()
            .find(|h| s.board.contains(*h))
            .unwrap();
        s.place_unit(Unit::from_def(2, registry.get("Fighter").unwrap(), 0), held);
        let mut blocker = 10;
        let mut holds = vec![2];
        for castle in keep.neighbors() {
            if s.board.contains(castle) && s.hex_to_unit.get(&castle).is_none() {
                s.place_unit(
                    Unit::from_def(blocker, registry.get("Fighter").unwrap(), 0),
                    castle,
                );
                holds.push(blocker);
                blocker += 1;
            }
        }
        let before = s.positions.clone();
        let mut p = policy(&[("Skeleton", 1, "army")]);
        p.scouts = Vec::new();
        p.holds = holds;
        p.rally = Some(Hex::from_offset(7, 6));
        let outcome = routine_next(
            &s,
            0,
            &p,
            &RoutineProgress::default(),
            &["Skeleton".into()],
            &registry,
        );
        assert!(matches!(
            outcome,
            RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                ..
            }
        ));
        assert_eq!(s.positions, before);
    }

    #[test]
    fn occupied_rally_is_a_direction_with_an_empty_adjacent_endpoint() {
        let registry = units();
        let mut s = state();
        let rally = Hex::from_offset(7, 5);
        s.place_unit(
            Unit::from_def(2, registry.get("Skeleton").unwrap(), 0),
            Hex::from_offset(5, 5),
        );
        s.place_unit(
            Unit::from_def(3, registry.get("Skeleton").unwrap(), 0),
            rally,
        );
        let p = RoutinePolicy {
            rally: Some(rally),
            ..policy(&[])
        };
        let outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        assert!(
            matches!(outcome, RoutineOutcome::Action { action, reason: "rally", .. }
            if action["unit_id"] == 2
                && !(action["col"] == rally.to_offset().0 && action["row"] == rally.to_offset().1)
                && Hex::from_offset(action["col"].as_i64().unwrap() as i32, action["row"].as_i64().unwrap() as i32).distance(rally) <= 1)
        );
    }

    #[test]
    fn standing_on_a_village_reports_capture_only_at_finish() {
        let registry = units();
        let (mut s, village) = village_state();
        s.place_unit(
            Unit::from_def(2, registry.get("Ghost").unwrap(), 0),
            village,
        );
        let p = RoutinePolicy {
            villages: vec![village],
            scouts: vec![2],
            ..policy(&[])
        };
        let progress = RoutineProgress {
            scout_assignments: vec![ScoutAssignment {
                unit_id: 2,
                village,
            }],
            ..Default::default()
        };
        let outcome = routine_next(&s, 0, &p, &progress, &[], &registry);
        assert!(
            matches!(outcome, RoutineOutcome::Finish { reason: "objectives_complete", progress_update }
            if progress_update["effects"][0]["kind"] == "completed_village"
                && progress_update["effects"][1]["kind"] == "policy_completed")
        );
        assert_ne!(s.village_owners.get(&village), Some(&0));
        s.village_owners.insert(village, 0);
        let progress = RoutineProgress {
            completed_villages: vec![village],
            ..progress
        };
        assert!(matches!(routine_next(&s, 0, &p, &progress, &[], &registry),
            RoutineOutcome::Finish { reason: "objectives_complete", progress_update }
                if progress_update["effects"][0]["kind"] == "policy_completed"));
    }

    #[test]
    fn rally_route_uses_terrain_costs_and_can_cross_a_friendly_intermediate() {
        let registry = units();
        let mut s = state();
        let start = Hex::from_offset(3, 4);
        let rally = Hex::from_offset(7, 4);
        for col in 4..7 {
            s.board
                .set_tile(Hex::from_offset(col, 4), Tile::new("shallow_water"));
        }
        s.place_unit(
            Unit::from_def(2, registry.get("Skeleton").unwrap(), 0),
            start,
        );
        // The shortest legal terrain-cost route can cross this occupied
        // intermediate hex; the submitted endpoint must still be empty.
        s.place_unit(
            Unit::from_def(3, registry.get("Skeleton").unwrap(), 0),
            Hex::from_offset(4, 4),
        );
        let p = RoutinePolicy {
            rally: Some(rally),
            ..policy(&[])
        };
        let outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        assert!(
            matches!(outcome, RoutineOutcome::Action { action, reason: "rally", .. }
            if action["unit_id"] == 2
                && action["col"] == 7
                && action["row"] == 4)
        );
    }

    #[test]
    fn unavailable_threat_facts_pause_as_threat_unavailable() {
        let registry = units();
        let mut s = state();
        // A live active-side unit without a placement is a malformed engine
        // snapshot. Tactical projection cannot provide a complete threat
        // surface, so routine execution must not treat it as safe.
        s.units.insert(2, Unit::new(2, "broken", 10, 0));
        let p = policy(&[("Skeleton", 1, "army")]);
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &["Skeleton".into()],
                &registry
            ),
            RoutineOutcome::Exception { reason: "threat_unavailable", evidence }
                if evidence["stage"] == "current_state"
        ));
    }

    #[test]
    fn unreachable_village_and_rally_are_route_unavailable() {
        let registry = units();
        let (mut s, village) = village_state();
        let mut scout = Unit::from_def(2, registry.get("Ghost").unwrap(), 0);
        scout.attacks.clear();
        s.place_unit(scout, Hex::from_offset(3, 4));
        // A wall of enemy zones of control blocks every route across column 4.
        for row in 0..8 {
            let mut enemy = Unit::from_def(100 + row as u32, registry.get("Fighter").unwrap(), 1);
            enemy.attacks.clear();
            s.place_unit(enemy, Hex::from_offset(4, row));
        }
        let village_policy = RoutinePolicy {
            villages: vec![village],
            scouts: vec![2],
            ..policy(&[])
        };
        let assigned = RoutineProgress {
            scout_assignments: vec![ScoutAssignment {
                unit_id: 2,
                village,
            }],
            ..Default::default()
        };
        assert!(matches!(
            routine_next(&s, 0, &village_policy, &assigned, &[], &registry),
            RoutineOutcome::Exception { reason: "route_unavailable", evidence }
                if evidence["cause"] == "unreachable_or_no_legal_endpoint"
        ));
        let rally_policy = RoutinePolicy {
            rally: Some(village),
            ..policy(&[])
        };
        assert!(matches!(
            routine_next(
                &s,
                0,
                &rally_policy,
                &RoutineProgress::default(),
                &[],
                &registry
            ),
            RoutineOutcome::Exception { reason: "route_unavailable", evidence }
                if evidence["cause"] == "unreachable_or_no_legal_endpoint"
        ));
    }

    #[test]
    fn shorter_safe_endpoint_is_selected_when_furthest_endpoint_is_threatened() {
        let registry = units();
        let mut s = state();
        let rally = Hex::from_offset(7, 2);
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(2, 2));
        let mut enemy = Unit::from_def(9, registry.get("Fighter").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(8, 2));
        let p = RoutinePolicy {
            rally: Some(rally),
            ..policy(&[])
        };
        let shorter_outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        assert!(matches!(
            shorter_outcome,
            RoutineOutcome::Action { action, reason: "rally", .. }
                if action["unit_id"] == 2 && action["col"] == 6 && action["row"] == 2
        ));
    }

    #[test]
    fn reachable_but_dangerous_endpoint_reports_contact() {
        let registry = units();
        let mut s = state();
        let rally = Hex::from_offset(6, 2);
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.movement = 1;
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(2, 2));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(4, 3));
        let p = RoutinePolicy {
            rally: Some(rally),
            ..policy(&[])
        };
        let outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        assert!(matches!(
            outcome,
            RoutineOutcome::Exception { reason: "contact", evidence }
                if evidence["stage"] == "proposed_destination"
                    && evidence["unit_id"] == 2
        ));
    }

    #[test]
    fn pending_promotion_remains_before_all_routine_steps() {
        let registry = units();
        let mut s = state();
        let mut veteran = Unit::from_def(5, registry.get("Fighter").unwrap(), 0);
        veteran.advancement_pending = true;
        s.place_unit(veteran, Hex::from_offset(5, 5));
        let p = policy(&[("Skeleton", 1, "army")]);
        assert!(matches!(
            routine_next(
                &s,
                0,
                &p,
                &RoutineProgress::default(),
                &["Skeleton".into()],
                &registry
            ),
            RoutineOutcome::Exception { reason: "promotion_pending", evidence }
                if evidence["unit_ids"] == json!([5])
        ));
    }

    #[test]
    fn village_policy_requires_scout_or_scout_recruit() {
        // Zero scouts and zero scout recruits with villages rejects.
        let invalid = json!({
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
            "scouts": [],
            "villages": [{"col": 2, "row": 3}],
            "rally": null,
            "holds": []
        });
        assert!(parse_policy(&invalid).is_err());

        // Scout recruit allows villages even with empty initial scouts.
        let with_recruit = json!({
            "reserve_gold": 0,
            "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}],
            "scouts": [],
            "villages": [{"col": 2, "row": 3}],
            "rally": null,
            "holds": []
        });
        assert!(parse_policy(&with_recruit).is_ok());

        // Existing scout allows villages with empty recruits.
        let with_scout = json!({
            "reserve_gold": 0,
            "recruits": [],
            "scouts": [3],
            "villages": [{"col": 2, "row": 3}],
            "rally": null,
            "holds": []
        });
        assert!(parse_policy(&with_scout).is_ok());
    }

    #[test]
    fn current_state_contact_emits_deterministic_facts() {
        let registry = units();
        let mut s = state();
        // Place friendly unit at (3, 3) and enemy at (3, 4)
        let friendly = Unit::from_def(3, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(friendly, Hex::from_offset(3, 3));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(3, 4));

        let p = policy(&[]);
        let outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        match outcome {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "contact");
                assert_eq!(evidence["stage"], "current_state");
                assert_eq!(evidence["coverage"], "complete");
                assert_eq!(evidence["friendly_unit_ids"], json!([1, 3]));
                assert_eq!(evidence["enemy_unit_ids"], json!([7]));
                assert!(
                    evidence["trigger"] == "attack"
                        || evidence["trigger"] == "exposure"
                        || evidence["trigger"] == "attack_and_exposure"
                );
            }
            other => panic!("expected contact exception, got {other:?}"),
        }
    }
}
