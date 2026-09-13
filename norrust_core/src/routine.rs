//! Deterministic routine step selection for the strategy/routine-execution
//! driver query (`routine_next`). Stack 1 implements recruitment only:
//! `scouts`, `villages`, and `holds` must arrive empty and `rally` must be
//! null; a nonempty future field is a defensive contract violation the
//! caller must reject with `code:"parse"` rather than accepting and
//! ignoring it (see docs/plans/strategy-and-routine-execution.md, Stack 1).
//!
//! This module is read-only: every function here inspects `&GameState` or a
//! throwaway `.clone()` and never mutates the live game. The driver alone
//! owns mutation, via the ordinary transactional executor.

use std::collections::HashMap;

use serde_json::{json, Value};

use crate::game_state::{apply_recruit, legal_recruitment_placements, GameState};
use crate::loader::Registry;
use crate::schema::UnitDef;
use crate::tactics::{
    recruiter_threats_after_end_turn, turn_tactics, unit_threats_after_end_turn, TacticsError,
};
use crate::unit::Unit;

/// One entry of a policy's finite recruitment queue.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecruitEntry {
    pub def_id: String,
    pub count: u32,
    pub role: String,
}

/// The Stack 1 subset of a validated `set_policy` payload: only the fields
/// this stack acts on. `scouts`/`villages`/`holds`/`rally` are checked for
/// emptiness by `parse_stack1_policy` and then discarded.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RoutinePolicy {
    pub reserve_gold: u32,
    pub recruits: Vec<RecruitEntry>,
}

/// Committed recruitment progress carried by the caller across routine
/// steps. `(def_id, done)` pairs; a def_id may repeat only if the caller's
/// bookkeeping merges counts, which this module does not assume — it sums
/// duplicates defensively in `next_unfinished_entry`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RoutineProgress {
    pub recruited: Vec<(String, u32)>,
}

/// The exact `routine_next` result union from the frozen contract.
#[derive(Debug, Clone, PartialEq)]
pub enum RoutineOutcome {
    Action {
        action: Value,
        progress_update: Value,
        reason: &'static str,
    },
    Finish {
        reason: &'static str,
    },
    Exception {
        reason: &'static str,
        evidence: Value,
    },
}

/// A policy or progress payload that Stack 1 must reject outright, as a
/// query-level `code:"parse"` failure rather than any `routine_next` result
/// shape. Carries a human-readable cause for the status message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyRejected(pub String);

fn reject(message: impl Into<String>) -> PolicyRejected {
    PolicyRejected(message.into())
}

/// Validate a `set_policy`-shaped JSON value under the Stack 1 contract:
/// only `reserve_gold` and `recruits` are meaningful, and `scouts`,
/// `villages`, `holds` must be empty while `rally` must be null/absent.
pub fn parse_stack1_policy(policy: &Value) -> Result<RoutinePolicy, PolicyRejected> {
    let object = policy
        .as_object()
        .ok_or_else(|| reject("policy must be an object"))?;

    let reserve_gold = object
        .get("reserve_gold")
        .and_then(Value::as_u64)
        .filter(|value| *value <= u32::MAX as u64)
        .ok_or_else(|| reject("reserve_gold must be a non-negative integer"))?
        as u32;

    let recruits_value = object
        .get("recruits")
        .and_then(Value::as_array)
        .ok_or_else(|| reject("recruits must be an array"))?;
    if recruits_value.len() > 8 {
        return Err(reject("recruits must contain at most 8 entries"));
    }
    let mut recruits = Vec::with_capacity(recruits_value.len());
    for entry in recruits_value {
        let entry_object = entry
            .as_object()
            .ok_or_else(|| reject("recruit entry must be an object"))?;
        let def_id = entry_object
            .get("def_id")
            .and_then(Value::as_str)
            .ok_or_else(|| reject("recruit entry def_id must be a string"))?
            .to_string();
        let count = entry_object
            .get("count")
            .and_then(Value::as_u64)
            .filter(|count| (1..=32).contains(count))
            .ok_or_else(|| reject("recruit entry count must be an integer in 1..=32"))?
            as u32;
        let role = entry_object
            .get("role")
            .and_then(Value::as_str)
            .filter(|role| matches!(*role, "scout" | "army"))
            .ok_or_else(|| reject("recruit entry role must be \"scout\" or \"army\""))?
            .to_string();
        recruits.push(RecruitEntry {
            def_id,
            count,
            role,
        });
    }

    for field in ["scouts", "villages", "holds"] {
        let empty = match object.get(field) {
            None => true,
            Some(Value::Array(items)) => items.is_empty(),
            Some(Value::Null) => true,
            _ => false,
        };
        if !empty {
            return Err(reject(format!(
                "{field} must be empty in this stack; the Python layer must reject nonempty {field} before this query"
            )));
        }
    }
    let rally_is_null = matches!(object.get("rally"), None | Some(Value::Null));
    if !rally_is_null {
        return Err(reject(
            "rally must be null in this stack; the Python layer must reject a nonempty rally before this query",
        ));
    }

    Ok(RoutinePolicy {
        reserve_gold,
        recruits,
    })
}

/// Parse the `progress` object carried on every `routine_next` request. Only
/// `recruited` is meaningful for Stack 1; the other fields
/// (`scout_assignments`, `completed_villages`, `scout_ids`,
/// `installation_id`) are accepted-and-ignored empty lists per the frozen
/// contract, so this never fails — a missing/malformed `recruited` list is
/// treated as an empty one rather than a parse error, since a fresh policy
/// installation legitimately starts with no committed progress.
pub fn parse_progress(progress: &Value) -> RoutineProgress {
    let mut recruited = Vec::new();
    if let Some(items) = progress.get("recruited").and_then(Value::as_array) {
        for item in items {
            let def_id = item.get("def_id").and_then(Value::as_str);
            let done = item.get("done").and_then(Value::as_u64);
            if let (Some(def_id), Some(done)) = (def_id, done) {
                recruited.push((def_id.to_string(), done as u32));
            }
        }
    }
    RoutineProgress { recruited }
}

/// Find the first queue entry with outstanding count, walking the queue in
/// order and consuming committed `progress.recruited` counts against it.
/// Duplicate `def_id` queue entries are supported: progress against a
/// def_id is consumed by earlier entries first, so a later entry sharing
/// the same def_id only sees the leftover.
fn next_unfinished_entry<'a>(
    policy: &'a RoutinePolicy,
    progress: &RoutineProgress,
) -> Option<&'a RecruitEntry> {
    let mut remaining: HashMap<&str, u32> = HashMap::new();
    for (def_id, done) in &progress.recruited {
        *remaining.entry(def_id.as_str()).or_insert(0) += *done;
    }
    for entry in &policy.recruits {
        let claimed = remaining.entry(entry.def_id.as_str()).or_insert(0);
        if *claimed < entry.count {
            return Some(entry);
        }
        *claimed -= entry.count;
    }
    None
}

/// Any legal friendly attack, or any friendly attackable in either exposure
/// view, on the CURRENT (pre-step) state. `Ok(true)` means pause for
/// contact; `Ok(false)` means an explicitly evaluated zero.
fn current_contact(state: &GameState, side: u8) -> Result<bool, TacticsError> {
    let tactics = turn_tactics(state, side)?;
    if tactics
        .iter()
        .any(|unit| unit.origins.iter().any(|origin| !origin.engagements.is_empty()))
    {
        return Ok(true);
    }
    let exposure = unit_threats_after_end_turn(state, side)?;
    Ok(exposure
        .units
        .iter()
        .any(|unit| unit.distinct_attacker_count > 0 || unit.open_distinct_attacker_count > 0))
}

/// Whether placing `def` for `side` at `placement` would itself be
/// attackable in either exposure view, or would newly expose the recruiter,
/// evaluated on a discarded clone. Never mutates `state`.
fn placement_contact(
    state: &GameState,
    side: u8,
    def: &UnitDef,
    placement: crate::hex::Hex,
) -> Result<bool, TacticsError> {
    let mut clone = state.clone();
    let temp_id = clone.units.keys().copied().max().unwrap_or(0).saturating_add(1);
    let candidate = Unit::from_def(temp_id, def, side);
    apply_recruit(&mut clone, candidate, placement, def.cost)?;

    let exposure = unit_threats_after_end_turn(&clone, side)?;
    let placed_exposed = exposure.units.iter().any(|unit| {
        unit.unit_id == temp_id
            && (unit.distinct_attacker_count > 0 || unit.open_distinct_attacker_count > 0)
    });
    if placed_exposed {
        return Ok(true);
    }

    let recruiter_threats = recruiter_threats_after_end_turn(&clone, side)?;
    Ok(recruiter_threats
        .recruiters
        .iter()
        .any(|recruiter| recruiter.distinct_attacker_count > 0 || recruiter.open_distinct_attacker_count > 0))
}

/// Select exactly one routine step (or finish, or a typed exception) from
/// the fresh revision. Never mutates `state`; any lookahead uses a clone.
///
/// `recruit_ids` is the active faction's recruitable definition list
/// (`Faction::recruits` in the driver), passed in rather than the driver's
/// own `Faction`/`factions` types so this module stays engine-only.
pub fn routine_next(
    state: &GameState,
    side: u8,
    policy: &RoutinePolicy,
    progress: &RoutineProgress,
    recruit_ids: &[String],
    units: &Registry<UnitDef>,
) -> RoutineOutcome {
    // Promotion pending is checked first and unconditionally: it does not
    // depend on threat computation and must never be masked by a contact
    // pause when both are true.
    let mut pending_units: Vec<u32> = state
        .units
        .iter()
        .filter_map(|(&id, unit)| (unit.faction == side && unit.advancement_pending).then_some(id))
        .collect();
    pending_units.sort_unstable();
    if !pending_units.is_empty() {
        return RoutineOutcome::Exception {
            reason: "promotion_pending",
            evidence: json!({"unit_ids": pending_units}),
        };
    }

    match current_contact(state, side) {
        Ok(true) => {
            return RoutineOutcome::Exception {
                reason: "contact",
                evidence: json!({"stage": "current_state"}),
            };
        }
        Ok(false) => {}
        Err(error) => {
            return RoutineOutcome::Exception {
                reason: "threat_unavailable",
                evidence: json!({"stage": "current_state", "detail": error.to_string()}),
            };
        }
    }

    let Some(entry) = next_unfinished_entry(policy, progress) else {
        return RoutineOutcome::Finish {
            reason: "no_remaining_routine_steps",
        };
    };

    let Some(def) = units.get(&entry.def_id) else {
        return RoutineOutcome::Exception {
            reason: "recruitment_blocked",
            evidence: json!({"def_id": entry.def_id, "cause": "unknown_definition"}),
        };
    };
    if !recruit_ids.iter().any(|id| id == &entry.def_id) {
        return RoutineOutcome::Exception {
            reason: "recruitment_blocked",
            evidence: json!({"def_id": entry.def_id, "cause": "not_recruitable"}),
        };
    }

    let gold = state.gold[side as usize];
    let available = gold.saturating_sub(policy.reserve_gold);
    if available < def.cost {
        let income = crate::tactics::economy_facts(state, side)
            .map(|(income, _)| income)
            .unwrap_or(0);
        if income > 0 {
            // Owned villages will eventually fund this entry; end the turn
            // rather than declaring a permanent block on a transient state.
            return RoutineOutcome::Finish {
                reason: "no_remaining_routine_steps",
            };
        }
        return RoutineOutcome::Exception {
            reason: "recruitment_blocked",
            evidence: json!({
                "def_id": entry.def_id,
                "cost": def.cost,
                "available": available,
                "reserve_gold": policy.reserve_gold,
                "cause": "insufficient_gold_no_income",
            }),
        };
    }

    let mut placements = legal_recruitment_placements(state, side);
    placements.sort_by_key(|hex| {
        let (col, row) = hex.to_offset();
        (row, col)
    });
    let Some(&placement) = placements.first() else {
        return RoutineOutcome::Exception {
            reason: "recruitment_blocked",
            evidence: json!({"def_id": entry.def_id, "cause": "no_placement_hex"}),
        };
    };

    match placement_contact(state, side, def, placement) {
        Ok(true) => {
            let (col, row) = placement.to_offset();
            RoutineOutcome::Exception {
                reason: "contact",
                evidence: json!({"stage": "proposed_placement", "col": col, "row": row}),
            }
        }
        Ok(false) => {
            let (col, row) = placement.to_offset();
            RoutineOutcome::Action {
                action: json!({"action": "Recruit", "def_id": entry.def_id, "col": col, "row": row}),
                progress_update: json!({"kind": "recruited", "def_id": entry.def_id}),
                reason: "recruit",
            }
        }
        Err(error) => RoutineOutcome::Exception {
            reason: "threat_unavailable",
            evidence: json!({"stage": "proposed_placement", "detail": error.to_string()}),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Tile};
    use crate::hex::Hex;
    use std::path::PathBuf;

    fn data_dir() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .expect("norrust_core has a parent dir")
            .join("data")
    }

    fn unit_registry() -> Registry<UnitDef> {
        Registry::load_from_dir(&data_dir().join("units")).expect("units load")
    }

    /// A quiet 10x8 board: one keep for each side, far apart, with castle
    /// hexes around each keep. No enemy units are placed unless a test asks
    /// for them, so this is a genuinely threat-free fixture by default.
    fn quiet_board() -> (Board, Hex, Hex) {
        let mut board = Board::new(10, 8);
        for row in 0..8 {
            for col in 0..10 {
                board.set_tile(Hex::from_offset(col, row), Tile::new("flat"));
            }
        }
        let keep0 = Hex::from_offset(1, 1);
        let keep1 = Hex::from_offset(8, 6);
        for keep in [keep0, keep1] {
            board.set_tile(keep, Tile::new("keep"));
            for castle in keep.neighbors() {
                if board.contains(castle) {
                    board.set_tile(castle, Tile::new("castle"));
                }
            }
        }
        (board, keep0, keep1)
    }

    fn quiet_state(gold: u32) -> (GameState, Hex) {
        let (board, keep0, _keep1) = quiet_board();
        let mut state = GameState::new(board);
        state.gold = [gold, gold];
        state.active_faction = 0;
        let mut leader = Unit::new(1, "Leader", 30, 0);
        leader.abilities = vec!["leader".into()];
        state.place_unit(leader, keep0);
        (state, keep0)
    }

    fn policy(reserve_gold: u32, recruits: &[(&str, u32, &str)]) -> RoutinePolicy {
        RoutinePolicy {
            reserve_gold,
            recruits: recruits
                .iter()
                .map(|(def_id, count, role)| RecruitEntry {
                    def_id: def_id.to_string(),
                    count: *count,
                    role: role.to_string(),
                })
                .collect(),
        }
    }

    fn no_progress() -> RoutineProgress {
        RoutineProgress::default()
    }

    fn digest(state: &GameState) -> (u64, [u32; 2], usize) {
        (state.state_revision, state.gold, state.units.len())
    }

    #[test]
    fn parse_stack1_policy_rejects_nonempty_future_fields() {
        for field in ["scouts", "villages", "holds"] {
            let mut value = json!({
                "reserve_gold": 0,
                "recruits": [],
                "scouts": [],
                "villages": [],
                "holds": [],
                "rally": null,
            });
            value[field] = json!([{"col": 1, "row": 1}]);
            assert!(
                parse_stack1_policy(&value).is_err(),
                "{field} must be rejected when nonempty"
            );
        }
        let mut with_rally = json!({
            "reserve_gold": 0, "recruits": [], "scouts": [], "villages": [], "holds": [],
            "rally": null,
        });
        with_rally["rally"] = json!({"col": 1, "row": 1});
        assert!(parse_stack1_policy(&with_rally).is_err());
    }

    #[test]
    fn parse_stack1_policy_accepts_a_finite_queue() {
        let value = json!({
            "reserve_gold": 60,
            "recruits": [
                {"def_id": "Ghost", "count": 3, "role": "scout"},
                {"def_id": "Skeleton", "count": 6, "role": "army"},
            ],
            "scouts": [], "villages": [], "holds": [], "rally": null,
        });
        let parsed = parse_stack1_policy(&value).expect("valid policy");
        assert_eq!(parsed.reserve_gold, 60);
        assert_eq!(parsed.recruits.len(), 2);
        assert_eq!(parsed.recruits[0].def_id, "Ghost");
        assert_eq!(parsed.recruits[1].count, 6);
    }

    #[test]
    fn ordered_finite_queue_is_consumed_exactly_once() {
        let units = unit_registry();
        let (state, _keep) = quiet_state(1000);
        let recruit_ids = vec!["Skeleton".to_string(), "Ghost".to_string()];
        let pol = policy(0, &[("Skeleton", 2, "army")]);

        // Nothing recruited yet: first Skeleton is next.
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        match outcome {
            RoutineOutcome::Action { progress_update, reason, .. } => {
                assert_eq!(reason, "recruit");
                assert_eq!(progress_update["def_id"], "Skeleton");
            }
            other => panic!("expected an action, got {other:?}"),
        }

        // One recruited: still one left.
        let progress_one = RoutineProgress {
            recruited: vec![("Skeleton".to_string(), 1)],
        };
        let outcome = routine_next(&state, 0, &pol, &progress_one, &recruit_ids, &units);
        assert!(matches!(outcome, RoutineOutcome::Action { .. }));

        // Both recruited: queue exhausted, nothing else in Stack 1 -> finish.
        let progress_done = RoutineProgress {
            recruited: vec![("Skeleton".to_string(), 2)],
        };
        let outcome = routine_next(&state, 0, &pol, &progress_done, &recruit_ids, &units);
        assert_eq!(
            outcome,
            RoutineOutcome::Finish {
                reason: "no_remaining_routine_steps"
            }
        );
    }

    #[test]
    fn reserve_gold_is_preserved() {
        let units = unit_registry();
        let cost = units.get("Skeleton").unwrap().cost;
        let recruit_ids = vec!["Skeleton".to_string()];
        // Exactly enough to cover cost + reserve.
        let (state, _keep) = quiet_state(cost + 50);
        let pol = policy(50, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        assert!(matches!(outcome, RoutineOutcome::Action { .. }));

        // One gold short of covering cost while keeping the reserve.
        let (state_short, _keep) = quiet_state(cost + 49);
        let outcome = routine_next(&state_short, 0, &pol, &no_progress(), &recruit_ids, &units);
        assert_eq!(
            outcome,
            RoutineOutcome::Exception {
                reason: "recruitment_blocked",
                evidence: json!({
                    "def_id": "Skeleton",
                    "cost": cost,
                    "available": 14,
                    "reserve_gold": 50,
                    "cause": "insufficient_gold_no_income",
                }),
            }
        );
    }

    #[test]
    fn occupied_castle_causes_no_auto_vacate() {
        let units = unit_registry();
        let recruit_ids = vec!["Skeleton".to_string()];
        let (mut state, keep) = quiet_state(1000);
        // Occupy every castle hex around the keep so no placement remains.
        let mut next_blocker_id = 100u32;
        for castle in keep.neighbors() {
            if state.board.contains(castle) {
                let blocker = Unit::new(next_blocker_id, "Fighter", 1, 1);
                next_blocker_id += 1;
                state.place_unit(blocker, castle);
            }
        }
        let pol = policy(0, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        match outcome {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "recruitment_blocked");
                assert_eq!(evidence["cause"], "no_placement_hex");
            }
            other => panic!("expected recruitment_blocked, got {other:?}"),
        }
        // No unit was ever placed or removed: no auto-vacate occurred.
        let occupants: std::collections::HashSet<_> = state.units.values().map(|u| u.id).collect();
        assert_eq!(occupants.len(), 1 + keep.neighbors().iter().filter(|h| state.board.contains(**h)).count());
    }

    #[test]
    fn zero_threats_produces_an_ordinary_recruit_action_not_an_exception() {
        let units = unit_registry();
        let recruit_ids = vec!["Skeleton".to_string()];
        let (state, _keep) = quiet_state(1000);
        let pol = policy(0, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        assert!(matches!(outcome, RoutineOutcome::Action { .. }));
    }

    #[test]
    fn contact_pauses_before_any_recruit_step() {
        let units = unit_registry();
        let recruit_ids = vec!["Skeleton".to_string()];
        let (mut state, keep) = quiet_state(1000);
        // Place a friendly adjacent to an enemy so a legal attack exists.
        let mut friendly = Unit::new(2, "Fighter", 30, 0);
        friendly.attacks = units.get("Skeleton").unwrap().attacks.clone();
        let front = Hex::from_offset(4, 4);
        state.place_unit(friendly, front);
        let mut enemy = Unit::new(3, "Fighter", 30, 1);
        enemy.attacks = units.get("Skeleton").unwrap().attacks.clone();
        state.place_unit(enemy, front.neighbors()[0]);
        let _ = keep;
        let pol = policy(0, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        match outcome {
            RoutineOutcome::Exception { reason, .. } => assert_eq!(reason, "contact"),
            other => panic!("expected contact, got {other:?}"),
        }
    }

    #[test]
    fn recruitment_blocked_when_definition_is_not_recruitable() {
        let units = unit_registry();
        let recruit_ids = vec!["Ghost".to_string()]; // Skeleton not in this faction's list.
        let (state, _keep) = quiet_state(1000);
        let pol = policy(0, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        match outcome {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "recruitment_blocked");
                assert_eq!(evidence["cause"], "not_recruitable");
            }
            other => panic!("expected recruitment_blocked, got {other:?}"),
        }
    }

    #[test]
    fn promotion_pending_pauses_before_recruitment() {
        let units = unit_registry();
        let recruit_ids = vec!["Skeleton".to_string()];
        let (mut state, _keep) = quiet_state(1000);
        let mut veteran = Unit::new(5, "Fighter", 30, 0);
        veteran.advancement_pending = true;
        state.place_unit(veteran, Hex::from_offset(5, 5));
        let pol = policy(0, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        match outcome {
            RoutineOutcome::Exception { reason, evidence } => {
                assert_eq!(reason, "promotion_pending");
                assert_eq!(evidence["unit_ids"], json!([5]));
            }
            other => panic!("expected promotion_pending, got {other:?}"),
        }
    }

    #[test]
    fn no_executable_orders_when_recruits_queue_is_empty_and_nothing_else_remains() {
        let units = unit_registry();
        let recruit_ids = vec!["Skeleton".to_string()];
        let (state, _keep) = quiet_state(1000);
        let pol = policy(0, &[]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        assert_eq!(
            outcome,
            RoutineOutcome::Finish {
                reason: "no_remaining_routine_steps"
            }
        );
    }

    #[test]
    fn query_style_lookahead_mutates_nothing() {
        let units = unit_registry();
        let recruit_ids = vec!["Skeleton".to_string()];
        let (state, _keep) = quiet_state(1000);
        let before = digest(&state);
        let pol = policy(0, &[("Skeleton", 1, "army")]);
        let outcome = routine_next(&state, 0, &pol, &no_progress(), &recruit_ids, &units);
        assert!(matches!(outcome, RoutineOutcome::Action { .. }));
        assert_eq!(digest(&state), before, "routine_next must not mutate state");
    }

    // `FinishWithGreedy{groups:[],holds:[]}` no-sweep verification lives in
    // `norrust_core/src/bin/greedy_driver.rs`'s test module: `FinishWithGreedy`
    // is a driver-level JSON macro (handled in `execute_model_batch`), not a
    // variant of the engine's own `Action` enum that this lib-only module can
    // construct or apply directly. See
    // `finish_with_greedy_empty_groups_and_holds_performs_no_sweep` there.
}
