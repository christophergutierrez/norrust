//! Read-only deterministic selection for the strategy `routine_next` query.
//! Selection never mutates live state; the driver submits returned actions.

use crate::combat::tod_label;
use crate::game_state::{
    apply_action, apply_recruit, legal_moves_with_costs, legal_recruitment_placements, Action,
    GameState,
};
use crate::hex::Hex;
use crate::loader::Registry;
use crate::pathfinding::{find_path, get_zoc_hexes};
use crate::routine_decision::{
    actionability_from_flags, generate_outside_helper_options, generate_tactical_options,
    involved_option_flags, ContactActionability, TacticalOption,
};
use crate::schema::UnitDef;
use crate::tactics::{
    recruiter_threats_after_end_turn, turn_tactics, unit_threats_after_end_turn, RecruiterThreats,
    TacticsError, ThreatSurface, UnitThreatSummary, UnitThreatSurface,
};
use crate::unit::Unit;
use serde::Serialize;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
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

fn rally_coord(rally: Option<Hex>) -> Value {
    rally.map(coord).unwrap_or(Value::Null)
}

fn capacity_relief(
    status: &'static str,
    rally: Option<Hex>,
    eligible: &[u32],
    checked: &[u32],
    coverage: &'static str,
    unit_causes: Option<Vec<Value>>,
    omitted: Option<usize>,
) -> Value {
    let mut body = json!({
        "status": status,
        "rally": rally_coord(rally),
        "eligible_unit_ids": eligible,
        "checked_unit_ids": checked,
        "coverage": coverage,
    });
    if let Some(causes) = unit_causes {
        body["unit_causes"] = Value::Array(causes);
    }
    if let Some(count) = omitted {
        body["omitted"] = json!(count);
    }
    body
}

fn castle_travel_ids(state: &GameState, side: u8, scouts: &[u32], policy: &RoutinePolicy) -> Vec<u32> {
    let mut ids: Vec<u32> = state
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
    ids.sort_unstable();
    ids
}

fn moved_castle_travel_exists(
    state: &GameState,
    side: u8,
    scouts: &[u32],
    policy: &RoutinePolicy,
) -> bool {
    state.units.iter().any(|(id, unit)| {
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
    })
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

/// Compute the village workload against scout capacity (Stack 1 contract).
///
/// `required_assignments` = distinct `policy.villages` that are not in
/// `progress.completed_villages`, not owned by `side` in
/// `state.village_owners`, and not the village of any
/// `progress.scout_assignments` entry.
///
/// `scout_capacity` = effective live eligible scouts (`scout_ids(policy,
/// progress)` filtered to live units of `side`, excluding `policy.holds` and
/// recruiters) that have no entry in `progress.scout_assignments`, plus
/// remaining scout-role recruits (`count - recruited_done` per queue index,
/// saturating). A scout that has already moved still counts. A recruited unit
/// is never counted both as live capacity and as a remaining recruit.
fn village_scout_capacity(
    state: &GameState,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    side: u8,
) -> (u32, u32) {
    let completed: HashSet<Hex> = progress.completed_villages.iter().copied().collect();
    let assigned_villages: HashSet<Hex> = progress
        .scout_assignments
        .iter()
        .map(|a| a.village)
        .collect();
    let required_assignments = policy
        .villages
        .iter()
        .filter(|village| {
            !completed.contains(village)
                && state.village_owners.get(village).copied() != Some(side as i8)
                && !assigned_villages.contains(village)
        })
        .count() as u32;

    let assigned_units: HashSet<u32> = progress
        .scout_assignments
        .iter()
        .map(|a| a.unit_id)
        .collect();
    let live_unassigned_scouts = scout_ids(policy, progress)
        .into_iter()
        .filter(|id| {
            state
                .units
                .get(id)
                .is_some_and(|unit| unit.faction == side && state.positions.contains_key(id))
                && !policy.holds.contains(id)
                && !state.units.get(id).is_some_and(recruiter)
                && !assigned_units.contains(id)
        })
        .count() as u32;
    let remaining_recruits: u32 = policy
        .recruits
        .iter()
        .enumerate()
        .filter(|(_, entry)| entry.role == "scout")
        .map(|(index, entry)| entry.count.saturating_sub(recruited_done(progress, index)))
        .sum();

    (
        required_assignments,
        live_unassigned_scouts + remaining_recruits,
    )
}

/// Cause label for an insufficient-capacity exception: distinguishes a fresh
/// installation (no committed recruits, scout assignments or completions)
/// from capacity lost/consumed during execution.
fn village_scout_capacity_cause(progress: &RoutineProgress) -> &'static str {
    let fresh = progress.recruited.iter().all(|entry| entry.done == 0)
        && progress.scout_assignments.is_empty()
        && progress.completed_villages.is_empty();
    if fresh {
        "insufficient_scout_capacity"
    } else {
        "scout_capacity_exhausted"
    }
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
    pub contact_actionability: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub contact_state_key: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
struct ContactUnitKey {
    id: u32,
    col: i32,
    row: i32,
    hp: u32,
    moved: bool,
    attacked: bool,
    advancement_pending: bool,
    poisoned: bool,
    slowed: bool,
}

#[derive(Serialize)]
struct ContactStateKeyPayload<'a> {
    active_side: u8,
    combat_phase: &'a str,
    sides_acted_this_round: u8,
    trigger: &'a str,
    friendlies: Vec<ContactUnitKey>,
    enemies: Vec<ContactUnitKey>,
    unit_threats: Vec<&'a UnitThreatSummary>,
    recruiter_threats: Vec<&'a RecruiterThreats>,
    involved_actionability: &'a [(u32, bool)],
}

fn contact_unit_key(state: &GameState, id: u32) -> Option<ContactUnitKey> {
    let unit = state.units.get(&id)?;
    let hex = state.positions.get(&id)?;
    let (col, row) = hex.to_offset();
    Some(ContactUnitKey {
        id,
        col,
        row,
        hp: unit.hp,
        moved: unit.moved,
        attacked: unit.attacked,
        advancement_pending: unit.advancement_pending,
        poisoned: unit.poisoned,
        slowed: unit.slowed,
    })
}

fn contact_state_key(
    state: &GameState,
    side: u8,
    trigger: &str,
    friendly_unit_ids: &[u32],
    enemy_unit_ids: &[u32],
    unit_surface: &UnitThreatSurface,
    recruiter_surface: &ThreatSurface,
    involved_actionability: &[(u32, bool)],
) -> Option<String> {
    let mut friendlies = Vec::with_capacity(friendly_unit_ids.len());
    for &id in friendly_unit_ids {
        friendlies.push(contact_unit_key(state, id)?);
    }
    let mut enemies = Vec::with_capacity(enemy_unit_ids.len());
    for &id in enemy_unit_ids {
        enemies.push(contact_unit_key(state, id)?);
    }

    let involved: HashSet<u32> = friendly_unit_ids.iter().copied().collect();
    let unit_threats: Vec<&UnitThreatSummary> = unit_surface
        .units
        .iter()
        .filter(|summary| involved.contains(&summary.unit_id))
        .collect();
    if unit_threats.len() != friendly_unit_ids.len() {
        return None;
    }

    let mut recruiter_threats: Vec<&RecruiterThreats> = recruiter_surface
        .recruiters
        .iter()
        .filter(|summary| involved.contains(&summary.recruiter_id))
        .collect();
    recruiter_threats.sort_by_key(|summary| summary.recruiter_id);
    for &id in friendly_unit_ids {
        let unit = state.units.get(&id)?;
        if unit.can_recruit
            && !recruiter_threats
                .iter()
                .any(|summary| summary.recruiter_id == id)
        {
            return None;
        }
    }

    let payload = ContactStateKeyPayload {
        active_side: side,
        combat_phase: tod_label(state.turn),
        sides_acted_this_round: state.sides_acted_this_round,
        trigger,
        friendlies,
        enemies,
        unit_threats,
        recruiter_threats,
        involved_actionability,
    };
    let bytes = serde_json::to_vec(&payload).ok()?;
    Some(format!("{:x}", Sha256::digest(&bytes)))
}

fn contact_exception_evidence(facts: &CurrentContactFacts) -> Value {
    let mut evidence = json!({
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
        "contact_actionability": facts.contact_actionability,
    });
    if let Some(key) = &facts.contact_state_key {
        evidence["contact_state_key"] = json!(key);
    }
    evidence
}

/// Classify involved-unit actionability and emit a key only when every required
/// fact is present. Incomplete facts are unknown and never exhausted.
pub(crate) fn classify_contact_state(
    state: &GameState,
    side: u8,
    trigger: &str,
    friendly_unit_ids: &[u32],
    enemy_unit_ids: &[u32],
    unit_surface: &UnitThreatSurface,
    recruiter_surface: &ThreatSurface,
) -> (ContactActionability, Option<String>) {
    let Some(flags) = involved_option_flags(state, friendly_unit_ids) else {
        return (ContactActionability::Unknown, None);
    };
    let key = contact_state_key(
        state,
        side,
        trigger,
        friendly_unit_ids,
        enemy_unit_ids,
        unit_surface,
        recruiter_surface,
        &flags,
    );
    if key.is_none() {
        return (ContactActionability::Unknown, None);
    }
    (actionability_from_flags(&flags), key)
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

    let unit_surface = unit_threats_after_end_turn(state, side)?;
    let recruiter_surface = recruiter_threats_after_end_turn(state, side)?;
    let mut exposure_friendly = Vec::new();
    let mut exposure_enemy = Vec::new();
    for u in &unit_surface.units {
        if u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0 {
            exposure_friendly.push(u.unit_id);
            exposure_enemy.extend(u.attacker_ids.iter().copied());
        }
    }
    for r in &recruiter_surface.recruiters {
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

    let (actionability, contact_state_key) = classify_contact_state(
        state,
        side,
        trigger,
        &friendly_unit_ids,
        &enemy_unit_ids,
        &unit_surface,
        &recruiter_surface,
    );

    let tactical_decision = match actionability {
        ContactActionability::Exhausted => {
            generate_outside_helper_options(state, side, &friendly_unit_ids)?
        }
        ContactActionability::Actionable | ContactActionability::Unknown => {
            generate_tactical_options(state, side)?
        }
    };

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
        contact_actionability: actionability.as_str(),
        contact_state_key,
    }))
}
/// Bound on friendly (non-recruiter) units rendered in projected-threat
/// evidence for a rejected routine move.
const MAX_PROJECTED_UNITS: usize = 8;

/// Verdict and full evidence for one proposed legal Move, computed from a
/// single post-move projected clone. This is the only safety algorithm: a
/// caller that only needs the verdict reads `.safe`; a caller that must
/// explain a rejected move renders `.exposed_units`/`.exposed_recruiters`.
struct ProjectedThreats {
    safe: bool,
    projected_time_of_day: &'static str,
    /// Non-recruiter friendlies with a nonzero attacker count in either view.
    exposed_units: Vec<UnitThreatSummary>,
    /// Recruiters with a nonzero attacker count in either view. A recruiter
    /// never also appears in `exposed_units`.
    exposed_recruiters: Vec<RecruiterThreats>,
}

/// Clone `state`, apply the proposed Move once, and read every projected
/// threat to `side` from that single post-move clone.
fn project_move_safety(
    state: &GameState,
    side: u8,
    action: Action,
) -> Result<ProjectedThreats, TacticsError> {
    let mut clone = state.clone();
    apply_action(&mut clone, action)?;
    let unit_surface = unit_threats_after_end_turn(&clone, side)?;
    let recruiter_surface = recruiter_threats_after_end_turn(&clone, side)?;

    let unsafe_unit = unit_surface
        .units
        .iter()
        .any(|u| u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0);
    let unsafe_recruiter = recruiter_surface
        .recruiters
        .iter()
        .any(|r| r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0);
    let recruiter_ids: HashSet<u32> = recruiter_surface
        .recruiters
        .iter()
        .map(|r| r.recruiter_id)
        .collect();
    let projected_time_of_day = unit_surface.projected_time_of_day;

    let exposed_units = unit_surface
        .units
        .into_iter()
        .filter(|u| !recruiter_ids.contains(&u.unit_id))
        .filter(|u| u.distinct_attacker_count > 0 || u.open_distinct_attacker_count > 0)
        .collect();
    let exposed_recruiters = recruiter_surface
        .recruiters
        .into_iter()
        .filter(|r| r.distinct_attacker_count > 0 || r.open_distinct_attacker_count > 0)
        .collect();

    Ok(ProjectedThreats {
        safe: !unsafe_unit && !unsafe_recruiter,
        projected_time_of_day,
        exposed_units,
        exposed_recruiters,
    })
}

/// "both" | "occupied_only" | "open_only" for one unit/recruiter's exposure.
fn threat_views(occupied_count: u32, open_count: u32) -> &'static str {
    match (occupied_count > 0, open_count > 0) {
        (true, true) => "both",
        (true, false) => "occupied_only",
        (false, true) => "open_only",
        (false, false) => "occupied_only",
    }
}

fn projected_unit_json(mover_id: u32, unit: &UnitThreatSummary) -> Value {
    json!({
        "unit_id": unit.unit_id,
        "is_mover": unit.unit_id == mover_id,
        "hp": unit.hp,
        "col": unit.col,
        "row": unit.row,
        "attacker_ids_any_view": unit.attacker_ids,
        "occupied": {
            "distinct_attacker_count": unit.distinct_attacker_count,
            "max_incoming_sum": unit.max_incoming_sum,
            "lethal_attackers_needed": unit.lethal_attackers_needed,
            "origins_conflict": unit.origins_conflict,
            "focus_kill_bps": unit.focus_kill_bps,
            "focus_expected_damage_tenths": unit.focus_expected_damage_tenths,
        },
        "open": {
            "distinct_attacker_count": unit.open_distinct_attacker_count,
            "max_incoming_sum": unit.open_max_incoming_sum,
            "lethal_attackers_needed": unit.open_lethal_attackers_needed,
            "origins_conflict": unit.open_origins_conflict,
        },
        "views": threat_views(unit.distinct_attacker_count, unit.open_distinct_attacker_count),
    })
}

fn projected_recruiter_json(recruiter: &RecruiterThreats) -> Value {
    json!({
        "recruiter_id": recruiter.recruiter_id,
        "hp": recruiter.hp,
        "col": recruiter.col,
        "row": recruiter.row,
        "occupied": {
            "distinct_attacker_count": recruiter.distinct_attacker_count,
            "max_incoming_sum": recruiter.max_incoming_sum,
            "lethal_attackers_needed": recruiter.lethal_attackers_needed,
            "origins_conflict": recruiter.origins_conflict,
            "attacker_max_damage": recruiter.attacker_max_damage,
            "focus_kill_bps": recruiter.focus_kill_bps,
            "focus_expected_damage_tenths": recruiter.focus_expected_damage_tenths,
        },
        "open": {
            "distinct_attacker_count": recruiter.open_distinct_attacker_count,
            "max_incoming_sum": recruiter.open_max_incoming_sum,
            "lethal_attackers_needed": recruiter.open_lethal_attackers_needed,
            "origins_conflict": recruiter.open_origins_conflict,
            "attacker_max_damage": recruiter.open_attacker_max_damage,
        },
        "views": threat_views(
            recruiter.distinct_attacker_count,
            recruiter.open_distinct_attacker_count,
        ),
    })
}

/// Build the enriched `contact`/`proposed_destination` evidence for a rejected
/// routine move from the verdict/evidence produced by `project_move_safety`.
/// Never adds `contact_state_key` or `contact_actionability`: their presence
/// would make a client consume a contact key and apply final-only closure.
fn proposed_destination_evidence(
    mover_id: u32,
    destination: Hex,
    objective_kind: &'static str,
    objective_target: Option<Hex>,
    evidence: &ProjectedThreats,
) -> Value {
    let mut units: Vec<&UnitThreatSummary> = evidence.exposed_units.iter().collect();
    units.sort_by_key(|u| u.unit_id);
    let units_listed = units.len().min(MAX_PROJECTED_UNITS);
    let units_omitted = units.len().saturating_sub(units_listed);
    let rendered_units: Vec<Value> = units
        .into_iter()
        .take(MAX_PROJECTED_UNITS)
        .map(|u| projected_unit_json(mover_id, u))
        .collect();
    let mut recruiters: Vec<&RecruiterThreats> = evidence.exposed_recruiters.iter().collect();
    recruiters.sort_by_key(|r| r.recruiter_id);
    let rendered_recruiters: Vec<Value> =
        recruiters.into_iter().map(projected_recruiter_json).collect();
    let (col, row) = destination.to_offset();
    json!({
        "stage": "proposed_destination",
        "unit_id": mover_id,
        "destination": coord(destination),
        "proposed_action": {"action":"Move","unit_id":mover_id,"col":col,"row":row},
        "objective": {
            "kind": objective_kind,
            "target": rally_coord(objective_target),
        },
        "projected_threats": {
            "projected_time_of_day": evidence.projected_time_of_day,
            "units": rendered_units,
            "recruiters": rendered_recruiters,
        },
        "coverage": {
            "facts": "complete",
            "units_listed": units_listed,
            "units_omitted": units_omitted,
        },
    })
}

/// Return legal endpoints on a shortest terrain-cost route, ordered from
/// furthest to nearest. The engine permits occupied intermediate hexes; only
/// the submitted endpoint must be empty.
///
/// When that shortest-path prefix has no empty in-budget stop (own units can
/// occupy every hex the unit can reach along it), fall back to a legal empty
/// hex that strictly reduces remaining path cost to a goal. Callers still
/// exclude scouts, holds, recruiters, and already-moved units.
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
    if candidates.is_empty() {
        if let Ok(legal) = legal_moves_with_costs(state, unit_id) {
            for &goal in goals {
                let Some((_, start_remaining)) = find_path(
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
                for (hex, move_cost) in &legal {
                    let Some((_, remaining)) = find_path(
                        &state.board,
                        &unit.movement_costs,
                        1,
                        *hex,
                        goal,
                        u32::MAX / 4,
                        &zoc,
                        false,
                    ) else {
                        continue;
                    };
                    if remaining < start_remaining {
                        candidates.push((*hex, *move_cost, remaining));
                    }
                }
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
    // Computed once and reused by both the current-contact gate below (which
    // must not offer an independent routine move when capacity is already
    // insufficient) and the post-contact capacity exit. Threat/promotion
    // checks must still take priority over the capacity exception itself, so
    // this does not return early.
    let (required_assignments, scout_capacity) =
        village_scout_capacity(state, policy, progress, side);
    let capacity_sufficient = required_assignments <= scout_capacity;
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
            if capacity_sufficient {
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
            }

            return RoutineOutcome::Exception {
                reason: "contact",
                evidence: contact_exception_evidence(&facts),
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
    if !capacity_sufficient {
        return RoutineOutcome::Exception {
            reason: "no_executable_orders",
            evidence: json!({
                "cause": village_scout_capacity_cause(progress),
                "required_assignments": required_assignments,
                "scout_capacity": scout_capacity,
                "villages": policy.villages.iter().map(|v| coord(*v)).collect::<Vec<_>>(),
            }),
        };
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
            let mut unsafe_move: Option<(Hex, ProjectedThreats)> = None;
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
                match project_move_safety(state, side, action) {
                    Ok(evidence) if evidence.safe => {
                        effects.shrink_to_fit();
                        return RoutineOutcome::Action {
                            action: json!({"action":"Move","unit_id":id,"col":destination.to_offset().0,"row":destination.to_offset().1}),
                            progress_update: progress_update(effects),
                            reason: "village",
                            independent_move: None,
                        };
                    }
                    Ok(evidence) => unsafe_move = Some((destination, evidence)),
                    Err(e) => {
                        return RoutineOutcome::Exception {
                            reason: "threat_unavailable",
                            evidence: json!({"stage":"proposed_destination","detail":e.to_string()}),
                        }
                    }
                }
            }
            if let Some((destination, evidence)) = unsafe_move {
                return RoutineOutcome::Exception {
                    reason: "contact",
                    evidence: proposed_destination_evidence(
                        id,
                        destination,
                        "village",
                        Some(village),
                        &evidence,
                    ),
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
            let eligible = castle_travel_ids(state, side, &scouts, policy);
            let mut checked: Vec<u32> = Vec::new();
            let mut unit_causes: Vec<(u32, &'static str)> = Vec::new();
            if let Some(rally) = policy.rally {
                let goals = rally_goals(state, rally);
                let mut unsafe_move: Option<(u32, Hex, ProjectedThreats)> = None;
                for id in &eligible {
                    checked.push(*id);
                    let endpoints = route_endpoints(state, *id, &goals);
                    if endpoints.is_empty() {
                        unit_causes.push((*id, "no_route_endpoint"));
                        continue;
                    }
                    let mut saw_step = false;
                    let mut saw_unsafe = false;
                    for (destination, arrived) in endpoints {
                        if arrived {
                            continue;
                        }
                        saw_step = true;
                        let action = Action::Move {
                            unit_id: *id,
                            destination,
                        };
                        match project_move_safety(state, side, action) {
                            Ok(evidence) if evidence.safe => {
                                return RoutineOutcome::Action {
                                    action: json!({"action":"Move","unit_id":id,"col":destination.to_offset().0,"row":destination.to_offset().1}),
                                    progress_update: progress_update(Vec::new()),
                                    reason: "castle_capacity",
                                    independent_move: None,
                                }
                            }
                            Ok(evidence) => {
                                saw_unsafe = true;
                                unsafe_move = Some((*id, destination, evidence));
                            }
                            Err(error) => {
                                return RoutineOutcome::Exception {
                                    reason: "threat_unavailable",
                                    evidence: json!({"stage":"proposed_destination","detail":error.to_string()}),
                                }
                            }
                        }
                    }
                    if saw_unsafe {
                        unit_causes.push((*id, "no_safe_endpoint"));
                    } else if !saw_step {
                        unit_causes.push((*id, "no_route_endpoint"));
                    }
                }
                if let Some((id, destination, evidence)) = unsafe_move {
                    return RoutineOutcome::Exception {
                        reason: "contact",
                        evidence: proposed_destination_evidence(
                            id,
                            destination,
                            "castle_capacity",
                            Some(rally),
                            &evidence,
                        ),
                    };
                }
                if moved_castle_travel_exists(state, side, &scouts, policy) {
                    return RoutineOutcome::Finish {
                        reason: "no_remaining_routine_steps",
                        progress_update: progress_update(Vec::new()),
                    };
                }
            }
            let status = if policy.rally.is_none() {
                "no_rally"
            } else if eligible.is_empty() {
                "no_eligible_unit"
            } else {
                let distinct: HashSet<&'static str> =
                    unit_causes.iter().map(|(_, cause)| *cause).collect();
                if distinct.len() > 1 {
                    "mixed_blockers"
                } else if distinct.contains("no_safe_endpoint") {
                    "no_safe_endpoint"
                } else if distinct.contains("no_route_endpoint") || distinct.is_empty() {
                    "no_route_endpoint"
                } else {
                    "unknown"
                }
            };
            let mixed = status == "mixed_blockers";
            let causes = if mixed {
                Some(
                    unit_causes
                        .iter()
                        .map(|(id, cause)| json!({"unit_id": id, "status": cause}))
                        .collect(),
                )
            } else {
                None
            };
            return RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({
                    "def_id": entry.def_id,
                    "cause": "no_placement_hex",
                    "capacity_relief": capacity_relief(
                        status,
                        policy.rally,
                        &eligible,
                        &checked,
                        "complete",
                        causes,
                        None,
                    ),
                }),
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
            let mut unsafe_move: Option<(Hex, ProjectedThreats)> = None;
            for (destination, arrived) in endpoints {
                if arrived {
                    continue;
                }
                let action = Action::Move {
                    unit_id: id,
                    destination,
                };
                match project_move_safety(state, side, action) {
                    Ok(evidence) if evidence.safe => {
                        return RoutineOutcome::Action {
                            action: json!({"action":"Move","unit_id":id,"col":destination.to_offset().0,"row":destination.to_offset().1}),
                            progress_update: progress_update(Vec::new()),
                            reason: "rally",
                            independent_move: None,
                        }
                    }
                    Ok(evidence) => unsafe_move = Some((destination, evidence)),
                    Err(e) => {
                        return RoutineOutcome::Exception {
                            reason: "threat_unavailable",
                            evidence: json!({"stage":"proposed_destination","detail":e.to_string()}),
                        }
                    }
                }
            }
            if let Some((destination, evidence)) = unsafe_move {
                return RoutineOutcome::Exception {
                    reason: "contact",
                    evidence: proposed_destination_evidence(
                        id,
                        destination,
                        "rally",
                        Some(rally),
                        &evidence,
                    ),
                };
            }
            return RoutineOutcome::Exception {
                reason: "unsafe_route",
                evidence: json!({"unit_id":id,"target":coord(rally),"cause":"no_safe_endpoint"}),
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
        match outcome {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "recruitment_blocked");
                assert_eq!(evidence["cause"], "no_placement_hex");
                assert_eq!(evidence["capacity_relief"]["status"], "no_eligible_unit");
                assert_eq!(evidence["capacity_relief"]["rally"], json!({"col":7,"row":6}));
                assert_eq!(evidence["capacity_relief"]["eligible_unit_ids"], json!([]));
                assert_eq!(evidence["capacity_relief"]["coverage"], "complete");
            }
            other => panic!("expected recruitment_blocked, got {other:?}"),
        }
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
    fn village_policy_no_longer_requires_scout_structurally() {
        // Stack 1: the blanket "villages require a scout or scout-role
        // recruit" structural rule is removed from parse_policy. Whether a
        // policy has enough scout capacity for its villages is now a
        // state-aware check in `village_scout_capacity`/`routine_next`, not
        // a parse-time rejection. Zero scouts and zero scout-role recruits
        // with villages listed now parses successfully.
        let no_scouts_no_recruits = json!({
            "reserve_gold": 0,
            "recruits": [{"def_id": "Skeleton", "count": 1, "role": "army"}],
            "scouts": [],
            "villages": [{"col": 2, "row": 3}],
            "rally": null,
            "holds": []
        });
        assert!(parse_policy(&no_scouts_no_recruits).is_ok());

        // Scout recruit still allows villages with empty initial scouts.
        let with_recruit = json!({
            "reserve_gold": 0,
            "recruits": [{"def_id": "Ghost", "count": 1, "role": "scout"}],
            "scouts": [],
            "villages": [{"col": 2, "row": 3}],
            "rally": null,
            "holds": []
        });
        assert!(parse_policy(&with_recruit).is_ok());

        // Existing scout still allows villages with empty recruits.
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
                assert_eq!(evidence["contact_actionability"], "actionable");
                assert!(evidence["contact_state_key"].as_str().unwrap().len() == 64);
                assert!(
                    evidence["trigger"] == "attack"
                        || evidence["trigger"] == "exposure"
                        || evidence["trigger"] == "attack_and_exposure"
                );
            }
            other => panic!("expected contact exception, got {other:?}"),
        }
    }

    fn fill_keep_castles(s: &mut GameState, registry: &Registry<UnitDef>, start_id: u32) -> Vec<u32> {
        let keep = Hex::from_offset(1, 1);
        let mut id = start_id;
        let mut ids = Vec::new();
        for castle in keep.neighbors() {
            if s.board.contains(castle)
                && s.hex_to_unit.get(&castle).is_none()
                && s.board
                    .tile_at(castle)
                    .is_some_and(|tile| tile.terrain_id == "castle")
            {
                s.place_unit(
                    Unit::from_def(id, registry.get("Skeleton").unwrap(), 0),
                    castle,
                );
                ids.push(id);
                id += 1;
            }
        }
        ids
    }

    #[test]
    fn no_rally_reports_capacity_relief_without_auto_vacate() {
        let registry = units();
        let mut s = state();
        let ids = fill_keep_castles(&mut s, &registry, 10);
        assert!(!ids.is_empty());
        let before = s.positions.clone();
        let p = policy(&[("Skeleton", 1, "army")]);
        match routine_next(
            &s,
            0,
            &p,
            &RoutineProgress::default(),
            &["Skeleton".into()],
            &registry,
        ) {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "recruitment_blocked");
                assert_eq!(evidence["cause"], "no_placement_hex");
                assert_eq!(evidence["capacity_relief"]["status"], "no_rally");
                assert_eq!(evidence["capacity_relief"]["rally"], Value::Null);
                assert_eq!(evidence["capacity_relief"]["eligible_unit_ids"], json!(ids));
                assert_eq!(evidence["capacity_relief"]["checked_unit_ids"], json!([]));
            }
            other => panic!("expected recruitment_blocked, got {other:?}"),
        }
        assert_eq!(s.positions, before);
    }

    #[test]
    fn unreachable_rally_reports_no_route_endpoint() {
        let registry = units();
        let mut s = state();
        fill_keep_castles(&mut s, &registry, 10);
        for unit in s.units.values_mut() {
            unit.movement_costs.insert("void".into(), 99);
        }
        for r in 0..8 {
            for c in 5..10 {
                s.board.set_tile(Hex::from_offset(c, r), Tile::new("void"));
            }
        }
        let rally = Hex::from_offset(8, 4);
        let mut p = policy(&[("Skeleton", 1, "army")]);
        p.rally = Some(rally);
        match routine_next(
            &s,
            0,
            &p,
            &RoutineProgress::default(),
            &["Skeleton".into()],
            &registry,
        ) {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "recruitment_blocked");
                assert_eq!(evidence["cause"], "no_placement_hex");
                assert_eq!(evidence["capacity_relief"]["status"], "no_route_endpoint");
                assert_eq!(evidence["capacity_relief"]["rally"], json!({"col":8,"row":4}));
                assert_eq!(evidence["capacity_relief"]["coverage"], "complete");
                assert!(!evidence["capacity_relief"]["eligible_unit_ids"]
                    .as_array()
                    .unwrap()
                    .is_empty());
            }
            other => panic!("expected recruitment_blocked, got {other:?}"),
        }
    }

    #[test]
    fn safe_rally_route_frees_capacity_without_a_model_call() {
        let registry = units();
        let mut s = state();
        let ids = fill_keep_castles(&mut s, &registry, 10);
        let mut p = policy(&[("Skeleton", 1, "army")]);
        p.rally = Some(Hex::from_offset(8, 6));
        match routine_next(
            &s,
            0,
            &p,
            &RoutineProgress::default(),
            &["Skeleton".into()],
            &registry,
        ) {
            RoutineOutcome::Action {
                action,
                reason: "castle_capacity",
                ..
            } => {
                assert_eq!(action["action"], "Move");
                let unit_id = action["unit_id"].as_u64().unwrap() as u32;
                assert!(ids.contains(&unit_id));
                let dest = Hex::from_offset(
                    action["col"].as_i64().unwrap() as i32,
                    action["row"].as_i64().unwrap() as i32,
                );
                assert_ne!(
                    s.board.tile_at(dest).map(|tile| tile.terrain_id.as_str()),
                    Some("castle")
                );
            }
            other => panic!("expected castle_capacity move, got {other:?}"),
        }
    }

    #[test]
    fn jammed_shortest_path_still_steps_toward_rally() {
        let registry = units();
        let mut s = state();
        let ids = fill_keep_castles(&mut s, &registry, 10);
        let mut blocker = 40;
        for col in 3..8 {
            let hex = Hex::from_offset(col, 1);
            let mut unit = Unit::from_def(blocker, registry.get("Skeleton").unwrap(), 0);
            unit.moved = true;
            s.place_unit(unit, hex);
            blocker += 1;
        }
        let mut p = policy(&[("Skeleton", 1, "army")]);
        p.rally = Some(Hex::from_offset(9, 1));
        match routine_next(
            &s,
            0,
            &p,
            &RoutineProgress::default(),
            &["Skeleton".into()],
            &registry,
        ) {
            RoutineOutcome::Action {
                action,
                reason: "castle_capacity",
                ..
            } => {
                let unit_id = action["unit_id"].as_u64().unwrap() as u32;
                assert!(ids.contains(&unit_id));
                let dest = Hex::from_offset(
                    action["col"].as_i64().unwrap() as i32,
                    action["row"].as_i64().unwrap() as i32,
                );
                let start = s.positions[&unit_id];
                assert!(dest.distance(Hex::from_offset(9, 1)) < start.distance(Hex::from_offset(9, 1)));
            }
            other => panic!("expected castle_capacity detour, got {other:?}"),
        }
    }

    // Stack 1: shared Python/Rust agreement fixture for village-scout
    // capacity. Frozen by the integrator; never edit the JSON file. Run
    // every case whose `applies` array contains "rust".
    fn scout_capacity_fixture() -> Value {
        serde_json::from_str(include_str!(
            "../../tools/fixtures/proposed_movement/scout_capacity_cases.json"
        ))
        .expect("fixture must be valid JSON")
    }

    fn capacity_case_state(case: &Value) -> (GameState, RoutinePolicy, RoutineProgress) {
        let mut b = Board::new(30, 20);
        for r in 0..20 {
            for c in 0..30 {
                b.set_tile(Hex::from_offset(c, r), Tile::new("flat"));
            }
        }
        let village_hex = |v: &Value| {
            Hex::from_offset(
                v["col"].as_i64().unwrap() as i32,
                v["row"].as_i64().unwrap() as i32,
            )
        };
        for v in case["villages"].as_array().unwrap() {
            b.set_tile(village_hex(v), Tile::new("village"));
        }
        let mut s = GameState::new(b);
        s.gold = [1000, 1000];
        for owned in case["owned"].as_array().unwrap_or(&Vec::new()) {
            s.village_owners.insert(village_hex(owned), 0);
        }
        for unit in case["units"].as_array().unwrap() {
            let id = unit["id"].as_u64().unwrap() as u32;
            let faction = unit["faction"].as_u64().unwrap() as u8;
            let recruiter = unit["recruiter"].as_bool().unwrap_or(false);
            let moved = unit["moved"].as_bool().unwrap_or(false);
            let mut u = Unit::new(id, "Fixture", 10, faction);
            u.can_recruit = recruiter;
            u.moved = moved;
            // Units are placed off in col 0, distinct per id, clear of every
            // fixture village (all fixture villages have col >= 2).
            s.place_unit(u, Hex::from_offset(0, id as i32));
        }
        let policy_json = &case["policy"];
        let mut villages_json = Vec::new();
        for v in case["villages"].as_array().unwrap() {
            villages_json.push(json!({"col": v["col"], "row": v["row"]}));
        }
        let policy = parse_policy(&json!({
            "reserve_gold": 0,
            "recruits": policy_json["recruits"],
            "scouts": policy_json["scouts"],
            "villages": villages_json,
            "rally": null,
            "holds": policy_json["holds"],
        }))
        .expect("fixture policy must parse");
        let progress = if case["progress"].is_null() {
            RoutineProgress::default()
        } else {
            let p = &case["progress"];
            let recruited = p["recruited"]
                .as_array()
                .unwrap()
                .iter()
                .map(|r| RecruitProgress {
                    queue_index: r["queue_index"].as_u64().unwrap() as usize,
                    done: r["done"].as_u64().unwrap() as u32,
                })
                .collect();
            let scout_ids = p["scout_ids"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_u64().unwrap() as u32)
                .collect();
            let scout_assignments = p["scout_assignments"]
                .as_array()
                .unwrap()
                .iter()
                .map(|a| ScoutAssignment {
                    unit_id: a["unit_id"].as_u64().unwrap() as u32,
                    village: village_hex(a),
                })
                .collect();
            let completed_villages = p["completed_villages"]
                .as_array()
                .unwrap()
                .iter()
                .map(village_hex)
                .collect();
            RoutineProgress {
                installation_id: None,
                recruited,
                scout_ids,
                scout_assignments,
                completed_villages,
                policy_complete: false,
                parse_issue: None,
            }
        };
        (s, policy, progress)
    }

    #[test]
    fn scout_capacity_fixture_agreement() {
        let registry = units();
        let fixture = scout_capacity_fixture();
        let cases = fixture["cases"].as_array().unwrap();
        let mut ran = 0;
        for case in cases {
            let applies: Vec<&str> = case["applies"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| v.as_str().unwrap())
                .collect();
            if !applies.contains(&"rust") {
                continue;
            }
            ran += 1;
            let name = case["name"].as_str().unwrap();
            let (state, policy, progress) = capacity_case_state(case);
            let expected = &case["expected"];

            if name == "dead_listed_scout_uses_existing_identity_handling" {
                let outcome = routine_next(
                    &state,
                    0,
                    &policy,
                    &progress,
                    &["Vampire Bat".into(), "Skeleton".into()],
                    &registry,
                );
                match outcome {
                    RoutineOutcome::Exception { reason, evidence } => {
                        // Existing identity handling reports this via
                        // reason "invalid_assignment" (validate_identity),
                        // not the capacity reason "no_executable_orders".
                        assert_eq!(
                            reason, "invalid_assignment",
                            "case {name}: expected the existing identity-validation \
                             reason string 'invalid_assignment'"
                        );
                        assert_ne!(
                            reason, "no_executable_orders",
                            "case {name}: must not be a capacity cause"
                        );
                        assert_eq!(
                            evidence["cause"], expected["rust_cause"],
                            "case {name}: cause mismatch"
                        );
                    }
                    other => panic!("case {name}: expected Exception, got {other:?}"),
                }
                continue;
            }

            let (required, capacity) = village_scout_capacity(&state, &policy, &progress, 0);
            if let Some(expected_required) = expected.get("required_assignments") {
                assert_eq!(
                    required as u64,
                    expected_required.as_u64().unwrap(),
                    "case {name}: required_assignments mismatch"
                );
            }
            if let Some(expected_capacity) = expected.get("scout_capacity") {
                assert_eq!(
                    capacity as u64,
                    expected_capacity.as_u64().unwrap(),
                    "case {name}: scout_capacity mismatch"
                );
            }

            let outcome = routine_next(
                &state,
                0,
                &policy,
                &progress,
                &["Vampire Bat".into(), "Skeleton".into()],
                &registry,
            );
            let ok = expected["ok"].as_bool().unwrap();
            if ok {
                if let RoutineOutcome::Exception { reason, .. } = &outcome {
                    assert_ne!(
                        *reason, "no_executable_orders",
                        "case {name}: expected no capacity exception, got {outcome:?}"
                    );
                }
            } else {
                match outcome {
                    RoutineOutcome::Exception { reason, evidence } => {
                        assert_eq!(
                            reason,
                            expected["rust_reason"].as_str().unwrap(),
                            "case {name}: reason mismatch"
                        );
                        assert_eq!(
                            evidence["cause"], expected["rust_cause"],
                            "case {name}: cause mismatch"
                        );
                        assert_eq!(
                            evidence["required_assignments"].as_u64().unwrap(),
                            required as u64
                        );
                        assert_eq!(
                            evidence["scout_capacity"].as_u64().unwrap(),
                            capacity as u64
                        );
                    }
                    other => panic!("case {name}: expected no_executable_orders, got {other:?}"),
                }
            }
        }
        assert!(
            ran >= 11,
            "expected at least 11 rust-tagged cases, ran {ran}"
        );
    }

    // Ordering regressions: capacity loss during execution must not mask
    // higher-priority safety checks (promotion, live current-board contact),
    // but must still be caught before any new routine step (scout travel,
    // recruitment, rally) once those checks are clear.
    fn insufficient_capacity_policy() -> RoutinePolicy {
        // Two unowned villages, zero scouts, zero scout-role recruits:
        // required_assignments=2, scout_capacity=0.
        RoutinePolicy {
            villages: vec![Hex::from_offset(5, 4), Hex::from_offset(6, 5)],
            scouts: Vec::new(),
            ..policy(&[])
        }
    }

    fn insufficient_capacity_board() -> GameState {
        let mut s = state();
        for v in [Hex::from_offset(5, 4), Hex::from_offset(6, 5)] {
            s.board.set_tile(v, Tile::new("village"));
        }
        s
    }

    #[test]
    fn promotion_pending_takes_precedence_over_insufficient_capacity() {
        let registry = units();
        let mut s = insufficient_capacity_board();
        let mut veteran = Unit::from_def(5, registry.get("Fighter").unwrap(), 0);
        veteran.advancement_pending = true;
        s.place_unit(veteran, Hex::from_offset(2, 2));
        let p = insufficient_capacity_policy();
        assert!(matches!(
            routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry),
            RoutineOutcome::Exception { reason: "promotion_pending", evidence }
                if evidence["unit_ids"] == json!([5])
        ));
    }

    #[test]
    fn live_current_contact_takes_precedence_over_insufficient_capacity_and_suppresses_independent_move(
    ) {
        let registry = units();
        let mut s = insufficient_capacity_board();
        // Same friendly/enemy adjacency as
        // `current_state_contact_emits_deterministic_facts`, which reliably
        // yields a current-state contact exception.
        let friendly = Unit::from_def(3, registry.get("Skeleton").unwrap(), 0);
        s.place_unit(friendly, Hex::from_offset(3, 3));
        let enemy = Unit::from_def(7, registry.get("Skeleton").unwrap(), 1);
        s.place_unit(enemy, Hex::from_offset(3, 4));
        let p = insufficient_capacity_policy();
        match routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry) {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "contact");
                assert_eq!(evidence["stage"], "current_state");
                assert_ne!(reason, "no_executable_orders");
            }
            other => panic!(
                "expected the existing current-state contact exception \
                 (capacity insufficiency must not be masked by an \
                 independent move), got {other:?}"
            ),
        }
    }

    #[test]
    fn insufficient_capacity_blocks_routine_steps_when_no_promotion_or_contact() {
        let registry = units();
        let s = insufficient_capacity_board();
        let p = insufficient_capacity_policy();
        match routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry) {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "no_executable_orders");
                assert_eq!(evidence["cause"], "insufficient_scout_capacity");
                assert_eq!(evidence["required_assignments"], 2);
                assert_eq!(evidence["scout_capacity"], 0);
            }
            other => panic!(
                "expected no_executable_orders capacity exception \
                 (no scout/recruit/rally action should be returned), got {other:?}"
            ),
        }
    }

    // -- Stack 2: projected-threat evidence for rejected routine moves --

    #[test]
    fn threat_views_labels_each_combination() {
        assert_eq!(threat_views(1, 1), "both");
        assert_eq!(threat_views(1, 0), "occupied_only");
        assert_eq!(threat_views(0, 1), "open_only");
    }

    #[test]
    fn project_move_safety_is_safe_when_no_projected_threat_exists() {
        let registry = units();
        let mut s = state();
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(2, 2));
        let action = Action::Move {
            unit_id: 2,
            destination: Hex::from_offset(3, 2),
        };
        let evidence = project_move_safety(&s, 0, action).unwrap();
        assert!(evidence.safe);
        assert!(evidence.exposed_units.is_empty());
        assert!(evidence.exposed_recruiters.is_empty());
    }

    #[test]
    fn project_move_safety_reports_mover_exposure() {
        let registry = units();
        let mut s = state();
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(2, 2));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(4, 3));
        let action = Action::Move {
            unit_id: 2,
            destination: Hex::from_offset(3, 2),
        };
        let evidence = project_move_safety(&s, 0, action).unwrap();
        assert!(!evidence.safe);
        assert!(evidence.exposed_recruiters.is_empty());
        let mover_summary = evidence
            .exposed_units
            .iter()
            .find(|u| u.unit_id == 2)
            .expect("mover must be listed as exposed");
        assert!(
            mover_summary.distinct_attacker_count > 0
                || mover_summary.open_distinct_attacker_count > 0
        );
    }

    #[test]
    fn other_friendly_exposure_names_that_unit_not_the_safe_mover() {
        let registry = units();
        let mut s = state();
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(8, 6));
        let mut bystander = Unit::from_def(5, registry.get("Skeleton").unwrap(), 0);
        bystander.attacks.clear();
        s.place_unit(bystander, Hex::from_offset(3, 2));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(4, 3));
        let action = Action::Move {
            unit_id: 2,
            destination: Hex::from_offset(8, 5),
        };
        let evidence = project_move_safety(&s, 0, action).unwrap();
        assert!(!evidence.safe);
        assert!(evidence.exposed_units.iter().all(|u| u.unit_id != 2));
        assert!(evidence.exposed_units.iter().any(|u| u.unit_id == 5));
    }

    #[test]
    fn recruiter_exposure_appears_only_under_recruiters_not_units() {
        let registry = units();
        // `state()` places a can_recruit leader (id 1) on the keep at (1,1).
        let mut s = state();
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(8, 6));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(2, 2));
        let action = Action::Move {
            unit_id: 2,
            destination: Hex::from_offset(8, 5),
        };
        let evidence = project_move_safety(&s, 0, action).unwrap();
        assert!(!evidence.safe);
        assert!(evidence.exposed_units.iter().all(|u| u.unit_id != 1));
        assert!(evidence
            .exposed_recruiters
            .iter()
            .any(|r| r.recruiter_id == 1));
    }

    #[test]
    fn open_only_exposure_is_labeled_open_only() {
        use crate::schema::AttackDef;
        let mut board = Board::new(2, 7);
        for row in 0..7 {
            for col in 0..2 {
                board.set_tile(Hex::from_offset(col, row), Tile::new("flat"));
            }
        }
        let mut s = GameState::new_seeded(board, 5001);
        s.place_unit(Unit::new(5, "target", 20, 0), Hex::from_offset(0, 5));
        s.place_unit(Unit::new(3, "screen", 20, 0), Hex::from_offset(0, 2));
        let mut mover = Unit::new(2, "mover", 10, 0);
        mover.movement = 1;
        mover.movement_costs.insert("flat".into(), 1);
        s.place_unit(mover, Hex::from_offset(1, 6));
        let mut archer = Unit::new(9, "adept", 20, 1);
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
        s.place_unit(archer, Hex::from_offset(0, 0));

        // The mover's own step is unrelated to the screened column and stays safe.
        let action = Action::Move {
            unit_id: 2,
            destination: Hex::from_offset(1, 5),
        };
        let evidence = project_move_safety(&s, 0, action).unwrap();
        assert!(!evidence.safe);
        let target = evidence
            .exposed_units
            .iter()
            .find(|u| u.unit_id == 5)
            .expect("screened target must be reported exposed via the open view");
        assert_eq!(target.distinct_attacker_count, 0);
        assert!(target.open_distinct_attacker_count > 0);
        assert_eq!(
            threat_views(
                target.distinct_attacker_count,
                target.open_distinct_attacker_count
            ),
            "open_only"
        );
    }

    #[test]
    fn village_exit_contact_carries_projected_threats_and_objective() {
        let registry = units();
        let mut s = state();
        let village = Hex::from_offset(6, 2);
        s.board.set_tile(village, Tile::new("village"));
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.movement = 1;
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(2, 2));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(4, 3));
        let p = RoutinePolicy {
            scouts: vec![2],
            villages: vec![village],
            ..policy(&[])
        };
        let outcome = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        match outcome {
            RoutineOutcome::Exception {
                reason: "contact",
                evidence,
            } => {
                assert_eq!(evidence["stage"], "proposed_destination");
                assert_eq!(evidence["unit_id"], 2);
                assert_eq!(
                    evidence["objective"],
                    json!({"kind":"village","target":coord(village)})
                );
                assert_eq!(evidence["proposed_action"]["action"], "Move");
                assert_eq!(evidence["proposed_action"]["unit_id"], 2);
                let unit_list = evidence["projected_threats"]["units"].as_array().unwrap();
                assert!(unit_list
                    .iter()
                    .any(|u| u["unit_id"] == 2 && u["is_mover"] == true));
                assert_eq!(evidence["projected_threats"]["recruiters"], json!([]));
                assert!(evidence.get("contact_state_key").is_none());
                assert!(evidence.get("contact_actionability").is_none());
            }
            other => panic!("expected contact with projected threats, got {other:?}"),
        }
    }

    #[test]
    fn castle_capacity_exit_contact_carries_projected_threats_and_objective() {
        let registry = units();
        // A larger board than the keep's immediate castle ring so the enemy
        // can sit out of its distance-2 ranged reach of every currently
        // placed friendly (no current-state contact) while still reaching
        // both single-step travel endpoints once the traveler steps toward
        // them (a genuine projected, not current, danger).
        let mut board = Board::new(4, 3);
        for row in 0..3 {
            for col in 0..4 {
                board.set_tile(Hex::from_offset(col, row), Tile::new("flat"));
            }
        }
        let keep = Hex::from_offset(0, 0);
        board.set_tile(keep, Tile::new("keep"));
        for castle in [Hex::from_offset(1, 0), Hex::from_offset(0, 1)] {
            board.set_tile(castle, Tile::new("castle"));
        }
        let mut s = GameState::new_seeded(board, 5100);
        s.gold = [1000, 1000];
        let mut leader = Unit::from_def(1, registry.get("Fighter").unwrap(), 0);
        leader.can_recruit = true;
        leader.attacks.clear();
        s.place_unit(leader, keep);
        let mut blocker = Unit::from_def(3, registry.get("Fighter").unwrap(), 0);
        blocker.attacks.clear();
        s.place_unit(blocker, Hex::from_offset(0, 1));
        let mut traveler = Unit::from_def(2, registry.get("Fighter").unwrap(), 0);
        traveler.movement = 1;
        traveler.attacks.clear();
        s.place_unit(traveler, Hex::from_offset(1, 0));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(3, 1));
        let rally = Hex::from_offset(2, 2);
        let p = RoutinePolicy {
            rally: Some(rally),
            holds: vec![3],
            ..policy(&[("Skeleton", 1, "army")])
        };
        let outcome = routine_next(
            &s,
            0,
            &p,
            &RoutineProgress::default(),
            &["Skeleton".into()],
            &registry,
        );
        match outcome {
            RoutineOutcome::Exception {
                reason: "contact",
                evidence,
            } => {
                assert_eq!(evidence["stage"], "proposed_destination");
                assert_eq!(evidence["unit_id"], 2);
                assert_eq!(
                    evidence["objective"],
                    json!({"kind":"castle_capacity","target":coord(rally)})
                );
                assert_eq!(evidence["proposed_action"]["action"], "Move");
                assert_eq!(evidence["proposed_action"]["unit_id"], 2);
                let unit_list = evidence["projected_threats"]["units"].as_array().unwrap();
                assert!(unit_list.iter().any(|u| u["unit_id"] == 2));
                assert!(evidence.get("contact_state_key").is_none());
                assert!(evidence.get("contact_actionability").is_none());
            }
            other => panic!("expected contact with projected threats, got {other:?}"),
        }
    }

    #[test]
    fn rally_exit_contact_carries_projected_threats_and_objective() {
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
        match outcome {
            RoutineOutcome::Exception {
                reason: "contact",
                evidence,
            } => {
                assert_eq!(evidence["stage"], "proposed_destination");
                assert_eq!(evidence["unit_id"], 2);
                assert_eq!(
                    evidence["objective"],
                    json!({"kind":"rally","target":coord(rally)})
                );
                assert_eq!(evidence["proposed_action"]["action"], "Move");
                assert_eq!(evidence["proposed_action"]["unit_id"], 2);
                let unit_list = evidence["projected_threats"]["units"].as_array().unwrap();
                assert!(unit_list
                    .iter()
                    .any(|u| u["unit_id"] == 2 && u["is_mover"] == true));
                assert_eq!(evidence["projected_threats"]["recruiters"], json!([]));
                assert!(evidence.get("contact_state_key").is_none());
                assert!(evidence.get("contact_actionability").is_none());
            }
            other => panic!("expected contact with projected threats, got {other:?}"),
        }
    }

    #[test]
    fn repeated_contact_query_leaves_state_unchanged() {
        let registry = units();
        let mut s = state();
        let village = Hex::from_offset(6, 2);
        s.board.set_tile(village, Tile::new("village"));
        let mut mover = Unit::from_def(2, registry.get("Skeleton").unwrap(), 0);
        mover.movement = 1;
        mover.attacks.clear();
        s.place_unit(mover, Hex::from_offset(2, 2));
        let mut enemy = Unit::from_def(9, registry.get("Skeleton Archer").unwrap(), 1);
        enemy.movement = 0;
        s.place_unit(enemy, Hex::from_offset(4, 3));
        let p = RoutinePolicy {
            scouts: vec![2],
            villages: vec![village],
            ..policy(&[])
        };
        let digest = |state: &GameState| format!("{:x}", Sha256::digest(format!("{state:?}")));
        let before = (
            s.rng.state(),
            s.next_unit_id,
            s.state_revision,
            s.gold,
            s.units.len(),
            digest(&s),
        );
        let first = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        let second = routine_next(&s, 0, &p, &RoutineProgress::default(), &[], &registry);
        assert!(matches!(
            first,
            RoutineOutcome::Exception {
                reason: "contact",
                ..
            }
        ));
        assert!(matches!(
            second,
            RoutineOutcome::Exception {
                reason: "contact",
                ..
            }
        ));
        assert_eq!(
            (
                s.rng.state(),
                s.next_unit_id,
                s.state_revision,
                s.gold,
                s.units.len(),
                digest(&s),
            ),
            before
        );
    }
}
