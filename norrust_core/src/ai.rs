//! AI opponent logic using scored move evaluation with combat and terrain awareness.

use std::collections::HashSet;

use serde::Serialize;

use crate::board::Board;
use crate::combat::{time_of_day, tod_damage_modifier};
use crate::game_state::{apply_action, Action, GameState};
use crate::hex::Hex;
use crate::pathfinding::{get_zoc_hexes, reachable_hexes};
use crate::unit::Unit;

/// A recorded AI action for animated replay on the client side.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "action")]
pub enum ActionRecord {
    Move { unit_id: u32, to_col: i32, to_row: i32 },
    Attack { attacker_id: u32, defender_id: u32 },
}

/// Expected damage dealt by one attack exchange (floating-point HP).
///
/// `resistance` is the defender's resistance to this attack type — positive
/// means the defender is weak (takes more damage), negative means resistant.
fn expected_outgoing_damage(
    attacker_attack_damage: u32,
    attacker_attack_strikes: u32,
    terrain_defense: u32,
    tod_mod: i32,
    resistance: i32,
) -> f32 {
    let hit_chance = (100.0 - terrain_defense as f32) / 100.0;
    let effective_dmg = attacker_attack_damage as f32 * (100.0 + resistance as f32) / 100.0;
    let per_strike = (effective_dmg * (100.0 + tod_mod as f32) / 100.0).max(0.0);
    per_strike * hit_chance * attacker_attack_strikes as f32
}

/// Score how good it is for `attacker` (at `attacker_hex`) to attack `defender`
/// (at `defender_hex`). Higher is better.
///
/// Score = (dealt × kill_bonus) / received.max(1.0)
/// kill_bonus = 3.0 if expected dealt damage would kill the defender, else 1.0.
fn score_attack(
    attacker: &Unit,
    attacker_hex: Hex,
    defender: &Unit,
    defender_hex: Hex,
    state: &GameState,
) -> f32 {
    let tod = time_of_day(state.turn);
    let attacker_tod = tod_damage_modifier(attacker.alignment, tod);
    let defender_tod = tod_damage_modifier(defender.alignment, tod);

    let dist = attacker_hex.distance(defender_hex);
    let range_str = if dist == 1 { "melee" } else { "ranged" };
    let attacker_first_atk = match attacker.attacks.iter().find(|a| a.range == range_str) {
        Some(a) => a,
        None => return 0.0,
    };

    let defender_tile = state.board.tile_at(defender_hex);
    let attacker_tile = state.board.tile_at(attacker_hex);

    let defender_defense = defender_tile
        .and_then(|t| defender.defense.get(&t.terrain_id).copied().or(Some(t.defense)))
        .unwrap_or(defender.default_defense);
    let attacker_defense = attacker_tile
        .and_then(|t| attacker.defense.get(&t.terrain_id).copied().or(Some(t.defense)))
        .unwrap_or(attacker.default_defense);

    let atk_resistance = defender
        .resistances
        .get(&attacker_first_atk.attack_type)
        .copied()
        .unwrap_or(0);

    let dealt = expected_outgoing_damage(
        attacker_first_atk.damage,
        attacker_first_atk.strikes,
        defender_defense,
        attacker_tod,
        atk_resistance,
    );

    let received = match defender.attacks.iter().find(|a| a.range == range_str) {
        Some(def_atk) => {
            let def_resistance = attacker
                .resistances
                .get(&def_atk.attack_type)
                .copied()
                .unwrap_or(0);
            expected_outgoing_damage(
                def_atk.damage,
                def_atk.strikes,
                attacker_defense,
                defender_tod,
                def_resistance,
            )
        }
        None => 0.0,
    };

    let kill_bonus = if dealt >= defender.hp as f32 { 3.0 } else { 1.0 };
    dealt * kill_bonus / received.max(1.0)
}

// ── Leader discipline helpers ───────────────────────────────────────────────

/// Find the leader unit ID for the given faction.
fn find_leader(state: &GameState, faction: u8) -> Option<u32> {
    state.units.iter().find_map(|(&uid, u)| {
        if u.faction == faction && u.abilities.iter().any(|a| a == "leader") {
            Some(uid)
        } else {
            None
        }
    })
}

/// Find all keep hexes on the board.
fn find_keep_hexes(board: &Board) -> Vec<Hex> {
    let mut keeps = Vec::new();
    for col in 0..board.width as i32 {
        for row in 0..board.height as i32 {
            let hex = Hex::from_offset(col, row);
            if board.tile_at(hex).map(|t| t.terrain_id == "keep").unwrap_or(false) {
                keeps.push(hex);
            }
        }
    }
    keeps
}

/// Find the keep hex most associated with the given faction.
/// Prefers the keep the leader is standing on; otherwise picks the keep
/// closest to the leader's current position.
fn find_faction_keep(state: &GameState, faction: u8) -> Option<Hex> {
    let leader_id = find_leader(state, faction)?;
    let leader_hex = *state.positions.get(&leader_id)?;
    let keeps = find_keep_hexes(&state.board);
    if keeps.is_empty() {
        return None;
    }
    // If leader is on a keep, that's the one
    if keeps.contains(&leader_hex) {
        return Some(leader_hex);
    }
    // Otherwise pick the closest keep to the leader
    keeps.into_iter().min_by_key(|&k| k.distance(leader_hex))
}

/// Check if there are empty castle hexes adjacent to the given keep hex.
fn has_empty_castle_slots(state: &GameState, keep_hex: Hex) -> bool {
    keep_hex.neighbors().iter().any(|&h| {
        state.board.tile_at(h).map(|t| t.terrain_id == "castle").unwrap_or(false)
            && !state.hex_to_unit.contains_key(&h)
    })
}

/// Determine if the leader should stay on the keep (because recruiting is possible).
fn should_leader_stay(state: &GameState, faction: u8, cheapest_cost: u32) -> bool {
    if cheapest_cost == 0 {
        return false;
    }
    let leader_id = match find_leader(state, faction) {
        Some(id) => id,
        None => return false,
    };
    let leader_hex = match state.positions.get(&leader_id) {
        Some(&h) => h,
        None => return false,
    };
    // Leader must be on a keep tile
    let on_keep = state.board.tile_at(leader_hex)
        .map(|t| t.terrain_id == "keep")
        .unwrap_or(false);
    if !on_keep {
        return false;
    }
    // Must have gold and empty castle slots
    state.gold[faction as usize] >= cheapest_cost && has_empty_castle_slots(state, leader_hex)
}

/// Determine if the leader should move back to keep to enable recruitment.
/// Returns the keep hex to move toward, or None.
fn leader_should_return_to_keep(state: &GameState, faction: u8, cheapest_cost: u32) -> Option<Hex> {
    if cheapest_cost == 0 || state.gold[faction as usize] < cheapest_cost {
        return None;
    }
    let keep_hex = find_faction_keep(state, faction)?;
    // Only return if there are empty castle slots to recruit into
    if !has_empty_castle_slots(state, keep_hex) {
        return None;
    }
    // Leader must NOT already be on the keep
    let leader_id = find_leader(state, faction)?;
    let leader_hex = *state.positions.get(&leader_id)?;
    if leader_hex == keep_hex {
        return None; // Already on keep — should_leader_stay handles this case
    }
    Some(keep_hex)
}

// ── Core AI turn logic ──────────────────────────────────────────────────────

/// Greedy AI: for every unit of `faction`, find the best (destination, target)
/// pair by expected-damage scoring, apply Move + Attack, then end the turn.
///
/// `cheapest_recruit_cost`: the cost of the cheapest recruitable unit (0 = no recruit info).
/// When > 0, the leader will stay on keep if recruiting is possible, or move back to keep.
pub fn ai_take_turn(state: &mut GameState, faction: u8, cheapest_recruit_cost: u32) {
    let leader_id = find_leader(state, faction);
    let stay = should_leader_stay(state, faction, cheapest_recruit_cost);
    let return_keep = leader_should_return_to_keep(state, faction, cheapest_recruit_cost);

    // Collect unit IDs upfront to avoid borrow conflicts during apply_action.
    let unit_ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .map(|(id, _)| *id)
        .collect();

    // Collect enemy IDs once before the loop; filter out dead ones each iteration.
    let enemy_ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction != faction)
        .map(|(id, _)| *id)
        .collect();

    for uid in unit_ids {
        // Unit may have been killed by retaliation from a prior action this turn.
        if !state.units.contains_key(&uid) || state.units[&uid].attacked {
            continue;
        }

        let is_leader = leader_id == Some(uid);

        // Leader discipline: stay on keep if can recruit more
        if is_leader && stay {
            continue;
        }

        let start = state.positions[&uid];

        // Extract unit data before pathfinding to avoid cloning movement_costs.
        let unit_ref = &state.units[&uid];
        let movement = if unit_ref.slowed { unit_ref.movement / 2 } else { unit_ref.movement };

        let zoc = get_zoc_hexes(state, faction);
        let candidates_raw =
            reachable_hexes(&state.board, &state.units[&uid].movement_costs, 1, start, movement, &zoc, false);

        // Build the occupied set (everyone except this unit).
        let all_occupied: HashSet<Hex> = state
            .hex_to_unit
            .iter()
            .filter(|(_, &id)| id != uid)
            .map(|(&h, _)| h)
            .collect();

        // Reachable hexes the unit can actually land on.
        let candidates: Vec<Hex> = candidates_raw
            .into_iter()
            .filter(|&h| h == start || !all_occupied.contains(&h))
            .collect();

        // Leader discipline: move back to keep if off-keep and can recruit
        if is_leader {
            if let Some(keep_hex) = return_keep {
                if let Some(&march_dest) = candidates
                    .iter()
                    .filter(|&&h| h != start)
                    .min_by_key(|&&c| c.distance(keep_hex))
                {
                    if march_dest.distance(keep_hex) < start.distance(keep_hex) {
                        let _ = apply_action(state, Action::Move { unit_id: uid, destination: march_dest });
                    }
                }
                continue;
            }
        }

        // Build enemy data from pre-collected IDs, skipping any killed by retaliation.
        let enemies: Vec<(u32, Hex, Unit)> = enemy_ids
            .iter()
            .filter(|id| state.units.contains_key(id))
            .map(|&id| (id, state.positions[&id], state.units[&id].clone()))
            .collect();

        // Score all (destination, enemy) pairs — keep all borrows in this block.
        let (best_dest, best_target) = {
            let mut best_score = 0.0f32;
            let mut best_dest = start;
            let mut best_target: Option<u32> = None;

            let unit = &state.units[&uid];
            for c in &candidates {
                for (eid, epos, enemy) in &enemies {
                    let can_engage = unit.attacks.iter().any(|a| {
                        (a.range == "melee" && c.neighbors().contains(epos))
                            || (a.range == "ranged" && c.distance(*epos) == 2)
                    });
                    if can_engage {
                        let s = score_attack(unit, *c, enemy, *epos, state);
                        if s > best_score {
                            best_score = s;
                            best_dest = *c;
                            best_target = Some(*eid);
                        }
                    }
                }
            }
            (best_dest, best_target)
        }; // immutable borrows of state released here

        if let Some(eid) = best_target {
            if best_dest != start {
                let _ = apply_action(
                    state,
                    Action::Move { unit_id: uid, destination: best_dest },
                );
            }
            let _ =
                apply_action(state, Action::Attack { attacker_id: uid, defender_id: eid });
        } else if !enemies.is_empty() {
            // March: move to the reachable hex closest to any enemy.
            if let Some(&march_dest) = candidates
                .iter()
                .filter(|&&h| h != start)
                .min_by_key(|&&c| {
                    enemies
                        .iter()
                        .map(|(_, epos, _)| c.distance(*epos))
                        .min()
                        .unwrap_or(u32::MAX)
                })
            {
                let _ = apply_action(state, Action::Move { unit_id: uid, destination: march_dest });
            }
        }
    }

    apply_action(state, Action::EndTurn).expect("EndTurn must always succeed");
}

/// Plan an AI turn on a cloned state, returning the list of actions taken.
///
/// The real `state` is NOT modified. The caller can replay these actions
/// one at a time with animations on the presentation side.
///
/// `cheapest_recruit_cost`: the cost of the cheapest recruitable unit (0 = no recruit info).
pub fn ai_plan_turn(state: &GameState, faction: u8, cheapest_recruit_cost: u32) -> Vec<ActionRecord> {
    let mut clone = state.clone();
    let mut records = Vec::new();

    let leader_id = find_leader(&clone, faction);
    let stay = should_leader_stay(&clone, faction, cheapest_recruit_cost);
    let return_keep = leader_should_return_to_keep(&clone, faction, cheapest_recruit_cost);

    let unit_ids: Vec<u32> = clone
        .units
        .iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .map(|(id, _)| *id)
        .collect();

    let enemy_ids: Vec<u32> = clone
        .units
        .iter()
        .filter(|(_, u)| u.faction != faction)
        .map(|(id, _)| *id)
        .collect();

    for uid in unit_ids {
        if !clone.units.contains_key(&uid) || clone.units[&uid].attacked {
            continue;
        }

        let is_leader = leader_id == Some(uid);

        // Leader discipline: stay on keep if can recruit more
        if is_leader && stay {
            continue;
        }

        let start = clone.positions[&uid];

        let unit_ref = &clone.units[&uid];
        let movement = if unit_ref.slowed { unit_ref.movement / 2 } else { unit_ref.movement };

        let zoc = get_zoc_hexes(&clone, faction);
        let candidates_raw =
            reachable_hexes(&clone.board, &clone.units[&uid].movement_costs, 1, start, movement, &zoc, false);

        let all_occupied: HashSet<Hex> = clone
            .hex_to_unit
            .iter()
            .filter(|(_, &id)| id != uid)
            .map(|(&h, _)| h)
            .collect();

        let candidates: Vec<Hex> = candidates_raw
            .into_iter()
            .filter(|&h| h == start || !all_occupied.contains(&h))
            .collect();

        // Leader discipline: move back to keep if off-keep and can recruit
        if is_leader {
            if let Some(keep_hex) = return_keep {
                if let Some(&march_dest) = candidates
                    .iter()
                    .filter(|&&h| h != start)
                    .min_by_key(|&&c| c.distance(keep_hex))
                {
                    if march_dest.distance(keep_hex) < start.distance(keep_hex) {
                        let (c, r) = march_dest.to_offset();
                        records.push(ActionRecord::Move { unit_id: uid, to_col: c, to_row: r });
                        let _ = apply_action(&mut clone, Action::Move { unit_id: uid, destination: march_dest });
                    }
                }
                continue;
            }
        }

        let enemies: Vec<(u32, Hex, Unit)> = enemy_ids
            .iter()
            .filter(|id| clone.units.contains_key(id))
            .map(|&id| (id, clone.positions[&id], clone.units[&id].clone()))
            .collect();

        let (best_dest, best_target) = {
            let mut best_score = 0.0f32;
            let mut best_dest = start;
            let mut best_target: Option<u32> = None;

            let unit = &clone.units[&uid];
            for c in &candidates {
                for (eid, epos, enemy) in &enemies {
                    let can_engage = unit.attacks.iter().any(|a| {
                        (a.range == "melee" && c.neighbors().contains(epos))
                            || (a.range == "ranged" && c.distance(*epos) == 2)
                    });
                    if can_engage {
                        let s = score_attack(unit, *c, enemy, *epos, &clone);
                        if s > best_score {
                            best_score = s;
                            best_dest = *c;
                            best_target = Some(*eid);
                        }
                    }
                }
            }
            (best_dest, best_target)
        };

        if let Some(eid) = best_target {
            if best_dest != start {
                let (c, r) = best_dest.to_offset();
                records.push(ActionRecord::Move { unit_id: uid, to_col: c, to_row: r });
                let _ = apply_action(
                    &mut clone,
                    Action::Move { unit_id: uid, destination: best_dest },
                );
            }
            records.push(ActionRecord::Attack { attacker_id: uid, defender_id: eid });
            let _ =
                apply_action(&mut clone, Action::Attack { attacker_id: uid, defender_id: eid });
        } else if !enemies.is_empty() {
            if let Some(&march_dest) = candidates
                .iter()
                .filter(|&&h| h != start)
                .min_by_key(|&&c| {
                    enemies
                        .iter()
                        .map(|(_, epos, _)| c.distance(*epos))
                        .min()
                        .unwrap_or(u32::MAX)
                })
            {
                let (c, r) = march_dest.to_offset();
                records.push(ActionRecord::Move { unit_id: uid, to_col: c, to_row: r });
                let _ = apply_action(&mut clone, Action::Move { unit_id: uid, destination: march_dest });
            }
        }
    }

    records
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::game_state::GameState;
    use crate::schema::AttackDef;
    use crate::unit::Unit;

    #[test]
    fn test_expected_damage_no_defense() {
        // 7 damage × 3 strikes × 1.0 hit_chance = 21.0
        let result = expected_outgoing_damage(7, 3, 0, 0, 0);
        assert_eq!(result, 21.0);
    }

    #[test]
    fn test_expected_damage_40pct_defense() {
        // 7 × 3 × 0.6 = 12.6
        let result = expected_outgoing_damage(7, 3, 40, 0, 0);
        assert!((result - 12.6).abs() < 0.01, "expected ~12.6, got {}", result);
    }

    #[test]
    fn test_score_prefers_kill() {
        let board = Board::new(5, 5);
        let state = GameState::new(board);

        let sword = AttackDef {
            id: "sword".to_string(),
            name: "Sword".to_string(),
            damage: 100,
            strikes: 1,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        };
        let mut attacker = Unit::new(1, "fighter", 30, 0);
        attacker.attacks = vec![sword];
        attacker.default_defense = 0;

        let enemy_weak = Unit::new(2, "enemy", 1, 1);
        let enemy_strong = Unit::new(3, "enemy", 200, 1);

        let attacker_hex = Hex::ORIGIN;
        let enemy_hex = Hex::from_offset(1, 0);

        let score_weak = score_attack(&attacker, attacker_hex, &enemy_weak, enemy_hex, &state);
        let score_strong = score_attack(&attacker, attacker_hex, &enemy_strong, enemy_hex, &state);

        assert!(
            score_weak > score_strong,
            "kill bonus must make weak-enemy score ({}) > strong-enemy score ({})",
            score_weak,
            score_strong
        );
    }

    /// Helper: set up a board with keep at `keep_pos` and castle hexes adjacent.
    fn setup_keep_board(keep_col: i32, keep_row: i32) -> Board {
        let mut board = Board::new(8, 5);
        let keep = Hex::from_offset(keep_col, keep_row);
        board.set_terrain(keep, "keep");
        for &n in keep.neighbors().iter() {
            if board.contains(n) {
                board.set_terrain(n, "castle");
            }
        }
        // Fill remaining hexes with flat
        for col in 0..8 {
            for row in 0..5 {
                let h = Hex::from_offset(col, row);
                if board.terrain_at(h).is_none() {
                    board.set_terrain(h, "flat");
                }
            }
        }
        board
    }

    /// Helper: create a leader unit with a melee attack.
    fn make_leader(id: u32, faction: u8) -> Unit {
        let sword = AttackDef {
            id: "sword".to_string(),
            name: "Sword".to_string(),
            damage: 7,
            strikes: 3,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        };
        let mut u = Unit::new(id, "lieutenant", 40, faction);
        u.abilities = vec!["leader".to_string()];
        u.attacks = vec![sword];
        u.movement = 5;
        u
    }

    #[test]
    fn test_leader_stays_on_keep_when_can_recruit() {
        let board = setup_keep_board(0, 0);
        let mut state = GameState::new(board);
        state.active_faction = 1;
        state.gold[1] = 100;

        // Place leader on keep
        let keep_hex = Hex::from_offset(0, 0);
        let leader = make_leader(1, 1);
        state.units.insert(1, leader);
        state.positions.insert(1, keep_hex);
        state.hex_to_unit.insert(keep_hex, 1);

        // Place an enemy somewhere to attract the leader
        let mut enemy = Unit::new(2, "fighter", 30, 0);
        enemy.attacks = vec![AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 7, strikes: 3, attack_type: "blade".to_string(),
            range: "melee".to_string(), ..Default::default()
        }];
        let enemy_hex = Hex::from_offset(3, 2);
        state.units.insert(2, enemy);
        state.positions.insert(2, enemy_hex);
        state.hex_to_unit.insert(enemy_hex, 2);

        // cheapest_recruit_cost = 15 (affordable with 100g)
        let records = ai_plan_turn(&state, 1, 15);

        // Leader should NOT have a Move record (stays on keep)
        let leader_moved = records.iter().any(|r| matches!(r, ActionRecord::Move { unit_id: 1, .. }));
        assert!(!leader_moved, "Leader should stay on keep when recruiting is possible, but got: {:?}", records);
    }

    #[test]
    fn test_leader_moves_to_keep_when_off_keep() {
        let board = setup_keep_board(0, 0);
        let mut state = GameState::new(board);
        state.active_faction = 1;
        state.gold[1] = 100;

        // Place leader NOT on keep, but nearby
        let leader_hex = Hex::from_offset(3, 2);
        let leader = make_leader(1, 1);
        state.units.insert(1, leader);
        state.positions.insert(1, leader_hex);
        state.hex_to_unit.insert(leader_hex, 1);

        // Place an enemy far away (to tempt leader toward enemy instead)
        let mut enemy = Unit::new(2, "fighter", 30, 0);
        enemy.attacks = vec![AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 7, strikes: 3, attack_type: "blade".to_string(),
            range: "melee".to_string(), ..Default::default()
        }];
        let enemy_hex = Hex::from_offset(7, 4);
        state.units.insert(2, enemy);
        state.positions.insert(2, enemy_hex);
        state.hex_to_unit.insert(enemy_hex, 2);

        let records = ai_plan_turn(&state, 1, 15);

        // Leader should move toward keep (col 0, row 0), not toward enemy (col 7, row 4)
        let leader_move = records.iter().find_map(|r| match r {
            ActionRecord::Move { unit_id: 1, to_col, to_row } => Some((*to_col, *to_row)),
            _ => None,
        });
        let keep_hex = Hex::from_offset(0, 0);
        assert!(leader_move.is_some(), "Leader should move toward keep, got: {:?}", records);
        let (mc, mr) = leader_move.unwrap();
        let move_hex = Hex::from_offset(mc, mr);
        assert!(
            move_hex.distance(keep_hex) < leader_hex.distance(keep_hex),
            "Leader should move closer to keep: was at {:?} (dist {}), moved to {:?} (dist {})",
            leader_hex, leader_hex.distance(keep_hex), move_hex, move_hex.distance(keep_hex)
        );
    }

    #[test]
    fn test_leader_attacks_when_no_gold() {
        let board = setup_keep_board(0, 0);
        let mut state = GameState::new(board);
        state.active_faction = 1;
        state.gold[1] = 0; // No gold

        // Place leader on keep
        let keep_hex = Hex::from_offset(0, 0);
        let leader = make_leader(1, 1);
        state.units.insert(1, leader);
        state.positions.insert(1, keep_hex);
        state.hex_to_unit.insert(keep_hex, 1);

        // Place enemy adjacent to keep
        let mut enemy = Unit::new(2, "fighter", 30, 0);
        enemy.attacks = vec![AttackDef {
            id: "sword".to_string(), name: "Sword".to_string(),
            damage: 7, strikes: 3, attack_type: "blade".to_string(),
            range: "melee".to_string(), ..Default::default()
        }];
        let enemy_hex = Hex::from_offset(1, 0);
        state.units.insert(2, enemy);
        state.positions.insert(2, enemy_hex);
        state.hex_to_unit.insert(enemy_hex, 2);

        // cheapest_recruit_cost = 15 but gold is 0
        let records = ai_plan_turn(&state, 1, 15);

        // Leader should attack normally (not stay idle)
        let leader_attacked = records.iter().any(|r| matches!(r, ActionRecord::Attack { attacker_id: 1, .. }));
        assert!(leader_attacked, "Leader should attack when no gold: {:?}", records);
    }
}
