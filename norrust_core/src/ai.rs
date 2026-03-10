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
#[allow(dead_code)]
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
#[allow(dead_code)]
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

// ── State evaluation ────────────────────────────────────────────────────────

/// Evaluate a game state from the perspective of `faction`.
/// Returns a score where higher is better for `faction`.
///
/// Used by lookahead AI to compare candidate states after simulated actions.
pub fn evaluate_state(state: &GameState, faction: u8) -> f32 {
    // Terminal states: decided games get extreme scores
    if let Some(winner) = state.check_winner() {
        return if winner == faction { f32::MAX } else { f32::MIN };
    }

    let enemy = 1 - faction;
    let mut score = 0.0f32;

    // Gather unit stats per side
    let mut own_hp: f32 = 0.0;
    let mut enemy_hp: f32 = 0.0;
    let mut own_count: f32 = 0.0;
    let mut enemy_count: f32 = 0.0;
    let mut own_leader_ratio: Option<f32> = None;
    let mut enemy_leader_hp: Option<(f32, f32)> = None; // (hp, max_hp)

    for (uid, unit) in &state.units {
        let hp = unit.hp as f32;
        if unit.faction == faction {
            own_hp += hp;
            own_count += 1.0;
            if unit.abilities.iter().any(|a| a == "leader") {
                own_leader_ratio = Some(hp / unit.max_hp.max(1) as f32);
            }
        } else {
            enemy_hp += hp;
            enemy_count += 1.0;
            if unit.abilities.iter().any(|a| a == "leader") {
                enemy_leader_hp = Some((hp, unit.max_hp as f32));
            }
        }

        // Positional value: objective proximity
        // Both attacker and defender benefit from being near the objective
        if let Some(obj) = state.objective_hex {
            if let Some(&pos) = state.positions.get(uid) {
                let board_diam = (state.board.width + state.board.height) as f32;
                let dist = pos.distance(obj) as f32;
                let proximity = (board_diam - dist) * 3.0 / board_diam;
                if unit.faction == faction {
                    score += proximity;
                } else if enemy == 0 {
                    // Enemy attacker near objective is bad for us (defender)
                    score -= proximity;
                }
            }
        }
    }

    // HP advantage (weight 2.0)
    score += (own_hp - enemy_hp) * 2.0;

    // Unit count advantage (weight 10.0)
    score += (own_count - enemy_count) * 10.0;

    // HP ratio bonus (weight 5.0) — centered at 0 when equal
    let total_hp = own_hp + enemy_hp;
    if total_hp > 0.0 {
        score += (own_hp / total_hp - 0.5) * 2.0 * 100.0 * 5.0;
    }

    // Village control (weight 8.0)
    let own_villages = state.village_owners.values()
        .filter(|&&owner| owner == faction as i8)
        .count() as f32;
    score += own_villages * 8.0;

    // Gold advantage (weight 0.5)
    let own_gold = state.gold[faction as usize] as f32;
    let enemy_gold = state.gold[enemy as usize] as f32;
    score += (own_gold - enemy_gold) * 0.5;

    // Leader safety (weight 15.0)
    if let Some(ratio) = own_leader_ratio {
        score += ratio * 15.0;
    }
    // Bonus for enemy leader being low HP (opportunity to kill)
    if let Some((hp, max_hp)) = enemy_leader_hp {
        let enemy_ratio = hp / max_hp.max(1.0);
        score += (1.0 - enemy_ratio) * 10.0; // More bonus when enemy leader is hurt
    }

    score
}

// ── 1-ply lookahead unit planner ─────────────────────────────────────────────

/// For a single unit, try all reachable (move, optional attack) combinations
/// on a cloned state, evaluate each result, and return the best action.
///
/// Returns `Some((destination, optional_attack_target))` if an action improves
/// over staying put, or `None` if the unit should not act.
fn plan_unit_action(state: &GameState, uid: u32, faction: u8) -> Option<(Hex, Option<u32>)> {
    let start = *state.positions.get(&uid)?;
    let unit = state.units.get(&uid)?;
    let movement = if unit.slowed { unit.movement / 2 } else { unit.movement };

    let zoc = get_zoc_hexes(state, faction);
    let candidates_raw =
        reachable_hexes(&state.board, &unit.movement_costs, 1, start, movement, &zoc, false);

    let all_occupied: HashSet<Hex> = state
        .hex_to_unit
        .iter()
        .filter(|(_, &id)| id != uid)
        .map(|(&h, _)| h)
        .collect();

    let candidates: Vec<Hex> = candidates_raw
        .into_iter()
        .filter(|&h| h == start || !all_occupied.contains(&h))
        .collect();

    // Collect enemies
    let enemies: Vec<(u32, Hex)> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction != faction)
        .map(|(&id, _)| (id, state.positions[&id]))
        .collect();

    if enemies.is_empty() {
        return None;
    }

    // Try all (move, attack) combinations — pick the best one by evaluate_state.
    // When attacks exist, always pick the best attack (don't compare against baseline,
    // since retaliation damage would make the AI too passive).
    // When no attacks exist, march toward the nearest enemy.
    let mut best_score = f32::NEG_INFINITY;
    let mut best_action: Option<(Hex, Option<u32>)> = None;
    let mut has_any_attack = false;

    for &cand in &candidates {
        let unit = &state.units[&uid];
        let attackable: Vec<u32> = enemies.iter().filter_map(|&(eid, epos)| {
            let can_engage = unit.attacks.iter().any(|a| {
                (a.range == "melee" && cand.neighbors().contains(&epos))
                    || (a.range == "ranged" && cand.distance(epos) == 2)
            });
            if can_engage { Some(eid) } else { None }
        }).collect();

        for eid in &attackable {
            has_any_attack = true;
            let mut sim = state.clone();
            if cand != start {
                let _ = apply_action(&mut sim, Action::Move { unit_id: uid, destination: cand });
            }
            if sim.units.contains_key(&uid) && sim.units.contains_key(eid) {
                let _ = apply_action(&mut sim, Action::Attack { attacker_id: uid, defender_id: *eid });
            }
            let score = evaluate_state(&sim, faction);
            if score > best_score {
                best_score = score;
                best_action = Some((cand, Some(*eid)));
            }
        }
    }

    // If no attack was possible, march toward the nearest enemy.
    if !has_any_attack {
        if let Some(&march_dest) = candidates
            .iter()
            .filter(|&&h| h != start)
            .min_by_key(|&&c| {
                enemies.iter().map(|(_, epos)| c.distance(*epos)).min().unwrap_or(u32::MAX)
            })
        {
            best_action = Some((march_dest, None));
        }
    }

    best_action
}

// ── Core AI turn logic ──────────────────────────────────────────────────────

/// AI turn using 1-ply lookahead: for each unit, simulate all (move, attack)
/// combinations, pick the one producing the best evaluated state.
///
/// `cheapest_recruit_cost`: the cost of the cheapest recruitable unit (0 = no recruit info).
/// When > 0, the leader will stay on keep if recruiting is possible, or move back to keep.
pub fn ai_take_turn(state: &mut GameState, faction: u8, cheapest_recruit_cost: u32) {
    let leader_id = find_leader(state, faction);
    let stay = should_leader_stay(state, faction, cheapest_recruit_cost);
    let return_keep = leader_should_return_to_keep(state, faction, cheapest_recruit_cost);

    let unit_ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .map(|(id, _)| *id)
        .collect();

    for uid in unit_ids {
        if !state.units.contains_key(&uid) || state.units[&uid].attacked {
            continue;
        }

        let is_leader = leader_id == Some(uid);

        // Leader discipline: stay on keep if can recruit more
        if is_leader && stay {
            continue;
        }

        // Leader discipline: move back to keep if off-keep and can recruit
        if is_leader {
            if let Some(keep_hex) = return_keep {
                let start = state.positions[&uid];
                let unit_ref = &state.units[&uid];
                let movement = if unit_ref.slowed { unit_ref.movement / 2 } else { unit_ref.movement };
                let zoc = get_zoc_hexes(state, faction);
                let candidates = reachable_hexes(&state.board, &state.units[&uid].movement_costs, 1, start, movement, &zoc, false);
                let occupied: HashSet<Hex> = state.hex_to_unit.iter()
                    .filter(|(_, &id)| id != uid).map(|(&h, _)| h).collect();
                if let Some(&march_dest) = candidates.iter()
                    .filter(|&&h| h != start && !occupied.contains(&h))
                    .min_by_key(|&&c| c.distance(keep_hex))
                {
                    if march_dest.distance(keep_hex) < start.distance(keep_hex) {
                        let _ = apply_action(state, Action::Move { unit_id: uid, destination: march_dest });
                    }
                }
                continue;
            }
        }

        // 1-ply lookahead: try all actions, pick best
        if let Some((dest, target)) = plan_unit_action(state, uid, faction) {
            let start = state.positions[&uid];
            if dest != start {
                let _ = apply_action(state, Action::Move { unit_id: uid, destination: dest });
            }
            if let Some(eid) = target {
                if state.units.contains_key(&uid) && state.units.contains_key(&eid) {
                    let _ = apply_action(state, Action::Attack { attacker_id: uid, defender_id: eid });
                }
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

    for uid in unit_ids {
        if !clone.units.contains_key(&uid) || clone.units[&uid].attacked {
            continue;
        }

        let is_leader = leader_id == Some(uid);

        // Leader discipline: stay on keep if can recruit more
        if is_leader && stay {
            continue;
        }

        // Leader discipline: move back to keep if off-keep and can recruit
        if is_leader {
            if let Some(keep_hex) = return_keep {
                let start = clone.positions[&uid];
                let unit_ref = &clone.units[&uid];
                let movement = if unit_ref.slowed { unit_ref.movement / 2 } else { unit_ref.movement };
                let zoc = get_zoc_hexes(&clone, faction);
                let candidates = reachable_hexes(&clone.board, &clone.units[&uid].movement_costs, 1, start, movement, &zoc, false);
                let occupied: HashSet<Hex> = clone.hex_to_unit.iter()
                    .filter(|(_, &id)| id != uid).map(|(&h, _)| h).collect();
                if let Some(&march_dest) = candidates.iter()
                    .filter(|&&h| h != start && !occupied.contains(&h))
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

        // 1-ply lookahead: try all actions, pick best
        if let Some((dest, target)) = plan_unit_action(&clone, uid, faction) {
            let start = clone.positions[&uid];
            if dest != start {
                let (c, r) = dest.to_offset();
                records.push(ActionRecord::Move { unit_id: uid, to_col: c, to_row: r });
                let _ = apply_action(&mut clone, Action::Move { unit_id: uid, destination: dest });
            }
            if let Some(eid) = target {
                if clone.units.contains_key(&uid) && clone.units.contains_key(&eid) {
                    records.push(ActionRecord::Attack { attacker_id: uid, defender_id: eid });
                    let _ = apply_action(&mut clone, Action::Attack { attacker_id: uid, defender_id: eid });
                }
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

    // ── evaluate_state tests ────────────────────────────────────────────

    #[test]
    fn test_eval_hp_advantage() {
        let board = Board::new(5, 5);
        let mut state = GameState::new(board);

        // Faction 0: 2 units with 30 HP each
        let mut u1 = Unit::new(1, "fighter", 30, 0);
        u1.max_hp = 30;
        state.place_unit(u1, Hex::from_offset(0, 0));
        let mut u2 = Unit::new(2, "fighter", 30, 0);
        u2.max_hp = 30;
        state.place_unit(u2, Hex::from_offset(1, 0));

        // Faction 1: 2 units with 10 HP each
        let mut u3 = Unit::new(3, "fighter", 10, 1);
        u3.max_hp = 30;
        state.place_unit(u3, Hex::from_offset(3, 0));
        let mut u4 = Unit::new(4, "fighter", 10, 1);
        u4.max_hp = 30;
        state.place_unit(u4, Hex::from_offset(4, 0));

        let score_0 = evaluate_state(&state, 0);
        let score_1 = evaluate_state(&state, 1);
        assert!(score_0 > score_1, "Faction with more HP should score higher: f0={}, f1={}", score_0, score_1);
    }

    #[test]
    fn test_eval_village_control() {
        let board = Board::new(5, 5);
        let mut state_a = GameState::new(board.clone());
        let mut state_b = state_a.clone();

        // Both states have same units
        let u1 = Unit::new(1, "fighter", 30, 0);
        let u2 = Unit::new(2, "fighter", 30, 1);
        state_a.place_unit(u1.clone(), Hex::from_offset(0, 0));
        state_a.place_unit(u2.clone(), Hex::from_offset(4, 0));
        state_b.place_unit(u1, Hex::from_offset(0, 0));
        state_b.place_unit(u2, Hex::from_offset(4, 0));

        // State A: faction 0 owns 2 villages
        let v1 = Hex::from_offset(2, 2);
        let v2 = Hex::from_offset(3, 2);
        state_a.village_owners.insert(v1, 0);
        state_a.village_owners.insert(v2, 0);
        // State B: faction 0 owns 0 villages
        state_b.village_owners.insert(v1, 1);
        state_b.village_owners.insert(v2, 1);

        let score_a = evaluate_state(&state_a, 0);
        let score_b = evaluate_state(&state_b, 0);
        assert!(score_a > score_b, "More villages should give higher score: a={}, b={}", score_a, score_b);
    }

    #[test]
    fn test_eval_terminal_win() {
        let board = Board::new(5, 5);
        let mut state = GameState::new(board);

        // Only faction 0 has units → faction 0 wins by elimination
        let u1 = Unit::new(1, "fighter", 30, 0);
        state.place_unit(u1, Hex::from_offset(0, 0));

        assert_eq!(evaluate_state(&state, 0), f32::MAX);
        assert_eq!(evaluate_state(&state, 1), f32::MIN);
    }

    #[test]
    fn test_eval_terminal_loss() {
        let board = Board::new(5, 5);
        let mut state = GameState::new(board);

        // Only faction 1 has units → faction 1 wins
        let u1 = Unit::new(1, "fighter", 30, 1);
        state.place_unit(u1, Hex::from_offset(0, 0));

        assert_eq!(evaluate_state(&state, 1), f32::MAX);
        assert_eq!(evaluate_state(&state, 0), f32::MIN);
    }

    #[test]
    fn test_eval_leader_safety() {
        let board = Board::new(5, 5);

        // State A: leader at full HP
        let mut state_a = GameState::new(board.clone());
        let mut leader_a = make_leader(1, 0);
        leader_a.hp = 40;
        leader_a.max_hp = 40;
        state_a.place_unit(leader_a, Hex::from_offset(0, 0));
        let enemy_a = Unit::new(2, "fighter", 30, 1);
        state_a.place_unit(enemy_a, Hex::from_offset(4, 0));

        // State B: leader at 10 HP
        let mut state_b = GameState::new(board);
        let mut leader_b = make_leader(1, 0);
        leader_b.hp = 10;
        leader_b.max_hp = 40;
        state_b.place_unit(leader_b, Hex::from_offset(0, 0));
        let enemy_b = Unit::new(2, "fighter", 30, 1);
        state_b.place_unit(enemy_b, Hex::from_offset(4, 0));

        let score_a = evaluate_state(&state_a, 0);
        let score_b = evaluate_state(&state_b, 0);
        assert!(score_a > score_b, "Healthier leader should score higher: full={}, wounded={}", score_a, score_b);
    }

    #[test]
    fn test_eval_symmetric() {
        let board = Board::new(5, 5);
        let mut state = GameState::new(board);

        // Equal forces, symmetric positions
        let mut u1 = Unit::new(1, "fighter", 30, 0);
        u1.max_hp = 30;
        state.place_unit(u1, Hex::from_offset(0, 2));
        let mut u2 = Unit::new(2, "fighter", 30, 1);
        u2.max_hp = 30;
        state.place_unit(u2, Hex::from_offset(4, 2));

        let score_0 = evaluate_state(&state, 0);
        let score_1 = evaluate_state(&state, 1);
        // Scores should be approximately opposite (equal forces)
        // Allow some tolerance for positional asymmetry
        assert!(
            (score_0 + score_1).abs() < 30.0,
            "Symmetric state should have roughly opposite scores: f0={}, f1={}, sum={}",
            score_0, score_1, score_0 + score_1
        );
    }

    // ── Lookahead behavior tests ────────────────────────────────────

    /// Helper: create a basic fighter unit with a melee attack and flat movement costs.
    fn make_fighter(id: u32, faction: u8, hp: u32) -> Unit {
        let sword = AttackDef {
            id: "sword".to_string(),
            name: "Sword".to_string(),
            damage: 7,
            strikes: 3,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        };
        let mut u = Unit::new(id, "fighter", hp, faction);
        u.max_hp = hp;
        u.attacks = vec![sword];
        u.movement = 5;
        u.default_defense = 30;
        u
    }

    #[test]
    fn test_lookahead_prefers_kill_for_victory() {
        // One enemy at 1 HP (killing it wins the game). AI should pick that
        // target over any other action since it produces a terminal win state.
        let mut board = Board::new(5, 3);
        for col in 0..5 {
            for row in 0..3 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        // Our unit at (2,1)
        let attacker = make_fighter(1, 0, 30);
        state.place_unit(attacker, Hex::from_offset(2, 1));

        // Only enemy at (3,1): 1 HP — killing wins the game
        let weak_enemy = make_fighter(2, 1, 1);
        state.place_unit(weak_enemy, Hex::from_offset(3, 1));

        let result = plan_unit_action(&state, 1, 0);
        assert!(result.is_some(), "AI should choose to attack");
        let (_, target) = result.unwrap();
        assert_eq!(target, Some(2), "AI should attack the last enemy for the win");
    }

    #[test]
    fn test_lookahead_considers_attack_positions() {
        // Verify that the lookahead evaluates different attack positions.
        // Unit has one enemy to attack — it should pick a position and attack.
        let mut board = Board::new(5, 5);
        for col in 0..5 {
            for row in 0..5 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        let attacker = make_fighter(1, 0, 30);
        state.place_unit(attacker, Hex::from_offset(0, 2));

        let enemy = make_fighter(2, 1, 20);
        state.place_unit(enemy, Hex::from_offset(3, 2));

        let result = plan_unit_action(&state, 1, 0);
        assert!(result.is_some(), "AI should choose an action");
        let (dest, target) = result.unwrap();
        assert_eq!(target, Some(2), "AI should attack the enemy");
        // Destination should be adjacent to enemy at (3,2)
        let enemy_hex = Hex::from_offset(3, 2);
        assert_eq!(dest.distance(enemy_hex), 1,
            "AI should move adjacent to enemy to attack");
    }

    #[test]
    fn test_lookahead_moves_without_attack() {
        // No enemies in range, but enemies exist on the board.
        // AI should move toward them (not stay put).
        let mut board = Board::new(10, 3);
        for col in 0..10 {
            for row in 0..3 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        let fighter = make_fighter(1, 0, 30);
        state.place_unit(fighter, Hex::from_offset(0, 1));

        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(9, 1));

        let result = plan_unit_action(&state, 1, 0);
        assert!(result.is_some(), "AI should move even without attack targets");
        let (dest, target) = result.unwrap();
        assert!(target.is_none(), "No attack should be possible");
        let start = Hex::from_offset(0, 1);
        let enemy_pos = Hex::from_offset(9, 1);
        assert!(
            dest.distance(enemy_pos) < start.distance(enemy_pos),
            "AI should move closer to enemy: start dist={}, dest dist={}",
            start.distance(enemy_pos), dest.distance(enemy_pos)
        );
    }
}
