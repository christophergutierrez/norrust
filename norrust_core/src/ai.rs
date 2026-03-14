//! AI opponent logic using scored move evaluation with combat and terrain awareness.

use std::collections::HashSet;

use serde::Serialize;

use crate::board::Board;
use crate::combat::{time_of_day, tod_damage_modifier};
use crate::game_state::{apply_action, Action, GameState};
use crate::hex::Hex;
use crate::pathfinding::{get_zoc_hexes, reachable_hexes};
use crate::schema::AttackDef;
use crate::unit::Unit;

/// A recorded AI action for animated replay on the client side.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "action")]
pub enum ActionRecord {
    Move { unit_id: u32, to_col: i32, to_row: i32 },
    Attack { attacker_id: u32, defender_id: u32 },
    Recruit,
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

// ── 2-ply evaluation ────────────────────────────────────────────────────────

/// Evaluate a state by simulating the opponent's best greedy response first.
/// Each enemy unit takes its best 1-ply action, then we evaluate the result.
/// This lets the AI see consequences of its actions one step ahead.
fn evaluate_with_opponent_response(state: &GameState, faction: u8) -> f32 {
    let enemy = 1 - faction;
    let mut sim = state.clone();

    // Collect enemy unit IDs (snapshot before simulation)
    let enemy_ids: Vec<u32> = sim.units.iter()
        .filter(|(_, u)| u.faction == enemy && !u.attacked)
        .map(|(&id, _)| id)
        .collect();

    for &eid in &enemy_ids {
        if !sim.units.contains_key(&eid) { continue; } // May have died
        if let Some((dest, target)) = plan_unit_action(&sim, eid, enemy, 1) {
            let start = sim.positions[&eid];
            if dest != start {
                let _ = apply_action(&mut sim, Action::Move { unit_id: eid, destination: dest });
            }
            if let Some(tid) = target {
                if sim.units.contains_key(&eid) && sim.units.contains_key(&tid) {
                    let _ = apply_action(&mut sim, Action::Attack { attacker_id: eid, defender_id: tid });
                }
            }
        }
    }

    evaluate_state(&sim, faction)
}

// ── 1-ply lookahead unit planner ─────────────────────────────────────────────

/// Find the best retreat destination toward a healing hex.
/// Prefers a reachable hex with healing > 0; otherwise picks the reachable hex
/// closest to any healing hex on the board.
fn retreat_toward_healing(
    state: &GameState,
    candidates: &[Hex],
    start: Hex,
) -> Option<(Hex, Option<u32>)> {
    // Collect all healing hexes on the board
    let healing_hexes: Vec<Hex> = (0..state.board.height as i32)
        .flat_map(|row| (0..state.board.width as i32).map(move |col| Hex::from_offset(col, row)))
        .filter(|&h| state.board.tile_at(h).map(|t| t.healing > 0).unwrap_or(false))
        .collect();

    if healing_hexes.is_empty() {
        return None;
    }

    // First: check if any candidate IS a healing hex
    if let Some(&heal_dest) = candidates
        .iter()
        .filter(|&&h| h != start)
        .filter(|&&h| healing_hexes.contains(&h))
        .min_by_key(|&&h| healing_hexes.iter().map(|hh| h.distance(*hh)).min().unwrap_or(u32::MAX))
    {
        return Some((heal_dest, None));
    }

    // Otherwise: pick the reachable hex that minimizes distance to nearest healing hex
    if let Some(&retreat_dest) = candidates
        .iter()
        .filter(|&&h| h != start)
        .min_by_key(|&&c| {
            healing_hexes.iter().map(|&hh| c.distance(hh)).min().unwrap_or(u32::MAX)
        })
    {
        return Some((retreat_dest, None));
    }

    None
}

/// For a single unit, try all reachable (move, optional attack) combinations
/// on a cloned state, evaluate each result, and return the best action.
///
/// Returns `Some((destination, optional_attack_target))` if an action improves
/// over staying put, or `None` if the unit should not act.
fn plan_unit_action(state: &GameState, uid: u32, faction: u8, depth: u8) -> Option<(Hex, Option<u32>)> {
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

            // Capture enemy HP ratio BEFORE simulation (enemy may die)
            let enemy_hp_ratio = state.units.get(eid).map(|e| {
                e.hp as f32 / e.max_hp.max(1) as f32
            }).unwrap_or(1.0);

            // Check if this is a ranged attack from distance 2
            let epos = state.positions[eid];
            let is_ranged_distance2 = unit.attacks.iter().any(|a| a.range == "ranged")
                && cand.distance(epos) == 2;

            let mut sim = state.clone();
            if cand != start {
                let _ = apply_action(&mut sim, Action::Move { unit_id: uid, destination: cand });
            }
            if sim.units.contains_key(&uid) && sim.units.contains_key(eid) {
                let _ = apply_action(&mut sim, Action::Attack { attacker_id: uid, defender_id: *eid });
            }
            let mut score = if depth >= 2 {
                evaluate_with_opponent_response(&sim, faction)
            } else {
                evaluate_state(&sim, faction)
            };

            // Tactical bonus: prefer ranged attacks from distance 2 (no retaliation)
            if is_ranged_distance2 {
                score += 2.0;
            }

            // Tactical bonus: focus fire on wounded enemies (up to +5.0)
            score += (1.0 - enemy_hp_ratio) * 5.0;

            if score > best_score {
                best_score = score;
                best_action = Some((cand, Some(*eid)));
            }
        }
    }

    // Retreat threshold: units below this HP ratio prefer healing over fighting
    const RETREAT_HP_RATIO: f32 = 0.30;
    let unit = &state.units[&uid];
    let hp_ratio = unit.hp as f32 / unit.max_hp.max(1) as f32;
    let is_wounded = hp_ratio < RETREAT_HP_RATIO;

    // If wounded and has attacks but no kill available, override with retreat
    if is_wounded && has_any_attack {
        let can_kill = {
            let mut found_kill = false;
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
                    let mut sim = state.clone();
                    if cand != start {
                        let _ = apply_action(&mut sim, Action::Move { unit_id: uid, destination: cand });
                    }
                    if sim.units.contains_key(&uid) && sim.units.contains_key(eid) {
                        let _ = apply_action(&mut sim, Action::Attack { attacker_id: uid, defender_id: *eid });
                    }
                    if !sim.units.contains_key(eid) {
                        found_kill = true;
                        break;
                    }
                }
                if found_kill { break; }
            }
            found_kill
        };
        if !can_kill {
            // Override attack decision — retreat instead
            best_action = retreat_toward_healing(state, &candidates, start);
        }
    }

    // If no attack was possible, march toward the nearest enemy (or retreat if wounded).
    if !has_any_attack {
        if is_wounded {
            best_action = retreat_toward_healing(state, &candidates, start);
        } else if depth >= 2 {
            // 2-ply march: evaluate each candidate with opponent response
            for &cand in candidates.iter().filter(|&&h| h != start) {
                let mut sim = state.clone();
                let _ = apply_action(&mut sim, Action::Move { unit_id: uid, destination: cand });
                let score = evaluate_with_opponent_response(&sim, faction);
                if score > best_score {
                    best_score = score;
                    best_action = Some((cand, None));
                }
            }
        } else if let Some(&march_dest) = candidates
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

// ── Turn-level planner ──────────────────────────────────────────────────────

/// Number of unit orderings to try per turn. More orderings = better
/// coordination but slower planning. First ordering is the natural order;
/// subsequent orderings rotate the unit list.
const TURN_PLAN_ORDERINGS: usize = 3;

/// Simulate recruitment on a cloned state: spend all gold on placeholder units
/// placed on empty castle hexes adjacent to the leader's keep.
/// Returns IDs of recruited placeholder units.
fn simulate_recruitment(
    clone: &mut GameState,
    faction: u8,
    recruit_defs: &[(u32, u32)], // (cost, movement)
) -> Vec<u32> {
    if recruit_defs.is_empty() {
        return Vec::new();
    }

    // Find leader on keep
    let leader_id = find_leader(clone, faction);
    let leader_hex = leader_id.and_then(|lid| clone.positions.get(&lid).copied());
    let keep_hex = match leader_hex {
        Some(h) if clone.board.tile_at(h).map(|t| t.terrain_id == "keep").unwrap_or(false) => h,
        _ => return Vec::new(),
    };

    let cheapest = recruit_defs.iter().map(|&(c, _)| c).min().unwrap_or(u32::MAX);
    let mut recruited_ids = Vec::new();
    let mut rotation = 0usize;

    while clone.gold[faction as usize] >= cheapest {
        // Find empty castle hex adjacent to keep
        let castle_hex = keep_hex.neighbors().iter().copied().find(|&h| {
            clone.board.tile_at(h).map(|t| t.terrain_id == "castle").unwrap_or(false)
                && !clone.hex_to_unit.contains_key(&h)
        });
        let Some(dest) = castle_hex else { break };

        // Pick recruit type round-robin (only affordable ones)
        let affordable: Vec<&(u32, u32)> = recruit_defs.iter()
            .filter(|&&(cost, _)| clone.gold[faction as usize] >= cost)
            .collect();
        if affordable.is_empty() { break; }
        let &(cost, movement) = affordable[rotation % affordable.len()];
        rotation += 1;

        // Create placeholder unit
        let uid = clone.next_unit_id;
        clone.next_unit_id += 1;
        let mut unit = Unit::new(uid, "recruit", 20, faction);
        unit.max_hp = 20;
        unit.movement = movement;
        unit.default_defense = 30;
        unit.attacks = vec![AttackDef {
            id: "sword".to_string(),
            name: "Sword".to_string(),
            damage: 5,
            strikes: 2,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        }];

        clone.place_unit(unit, dest);
        clone.gold[faction as usize] -= cost;
        recruited_ids.push(uid);
    }

    recruited_ids
}

/// Plan a single turn attempt with the given unit ordering on a clone.
/// Returns (action_records, final_score).
///
/// Order: non-leaders move first → recruit into freed castle slots → new recruits
/// move → leader decides last (stay on keep if can recruit, else plan normally).
fn run_turn_ordering(
    state: &GameState,
    faction: u8,
    leader_id: Option<u32>,
    return_keep: Option<Hex>,
    unit_order: &[u32],
    cheapest_recruit_cost: u32,
    recruit_defs: &[(u32, u32)],
) -> (Vec<ActionRecord>, f32) {
    let mut clone = state.clone();
    let mut records = Vec::new();

    // Initial recruitment
    let initial_recruits = simulate_recruitment(&mut clone, faction, recruit_defs);
    let mut did_recruit = !initial_recruits.is_empty();
    if did_recruit {
        records.push(ActionRecord::Recruit);
    }

    // Move all non-leader units first (original units from unit_order)
    for &uid in unit_order {
        if leader_id == Some(uid) { continue; } // Leader goes last
        if !clone.units.contains_key(&uid) || clone.units[&uid].attacked { continue; }

        if let Some((dest, target)) = plan_unit_action(&clone, uid, faction, 1) {
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

    // Move initial recruits off castle hexes (freeing slots for more recruitment)
    for &uid in &initial_recruits {
        if !clone.units.contains_key(&uid) { continue; }
        if let Some((dest, target)) = plan_unit_action(&clone, uid, faction, 1) {
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

    // Recruit again into freed castle slots, move new recruits out (repeat until done)
    for _wave in 0..6 {
        if !should_leader_stay(&clone, faction, cheapest_recruit_cost) { break; }
        let new_ids = simulate_recruitment(&mut clone, faction, recruit_defs);
        if new_ids.is_empty() { break; }
        did_recruit = true;
        records.push(ActionRecord::Recruit);
        for &uid in &new_ids {
            if !clone.units.contains_key(&uid) { continue; }
            if let Some((dest, target)) = plan_unit_action(&clone, uid, faction, 1) {
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
    }

    // Leader decides last: stay on keep if recruited this turn or can still recruit
    if let Some(lid) = leader_id {
        if clone.units.contains_key(&lid) && !clone.units[&lid].attacked {
            if did_recruit || should_leader_stay(&clone, faction, cheapest_recruit_cost) {
                // Stay on keep, but attack adjacent enemies
                let leader_hex = clone.positions[&lid];
                let adjacent_enemy = clone.units.iter()
                    .filter(|(_, u)| u.faction != faction)
                    .find_map(|(&eid, _)| {
                        let epos = clone.positions[&eid];
                        if leader_hex.neighbors().contains(&epos) { Some(eid) } else { None }
                    });
                if let Some(eid) = adjacent_enemy {
                    if clone.units.contains_key(&lid) && clone.units.contains_key(&eid) {
                        records.push(ActionRecord::Attack { attacker_id: lid, defender_id: eid });
                        let _ = apply_action(&mut clone, Action::Attack { attacker_id: lid, defender_id: eid });
                    }
                }
            } else if let Some(keep_hex) = return_keep {
                // Move back toward keep
                let start = clone.positions[&lid];
                let unit_ref = &clone.units[&lid];
                let movement = if unit_ref.slowed { unit_ref.movement / 2 } else { unit_ref.movement };
                let zoc = get_zoc_hexes(&clone, faction);
                let candidates = reachable_hexes(&clone.board, &clone.units[&lid].movement_costs, 1, start, movement, &zoc, false);
                let occupied: HashSet<Hex> = clone.hex_to_unit.iter()
                    .filter(|(_, &id)| id != lid).map(|(&h, _)| h).collect();
                if let Some(&march_dest) = candidates.iter()
                    .filter(|&&h| h != start && !occupied.contains(&h))
                    .min_by_key(|&&c| c.distance(keep_hex))
                {
                    if march_dest.distance(keep_hex) < start.distance(keep_hex) {
                        let (c, r) = march_dest.to_offset();
                        records.push(ActionRecord::Move { unit_id: lid, to_col: c, to_row: r });
                        let _ = apply_action(&mut clone, Action::Move { unit_id: lid, destination: march_dest });
                    }
                }
            } else {
                // Leader has no recruitment duties — plan normally with 2-ply
                if let Some((dest, target)) = plan_unit_action(&clone, lid, faction, 2) {
                    let start = clone.positions[&lid];
                    if dest != start {
                        let (c, r) = dest.to_offset();
                        records.push(ActionRecord::Move { unit_id: lid, to_col: c, to_row: r });
                        let _ = apply_action(&mut clone, Action::Move { unit_id: lid, destination: dest });
                    }
                    if let Some(eid) = target {
                        if clone.units.contains_key(&lid) && clone.units.contains_key(&eid) {
                            records.push(ActionRecord::Attack { attacker_id: lid, defender_id: eid });
                            let _ = apply_action(&mut clone, Action::Attack { attacker_id: lid, defender_id: eid });
                        }
                    }
                }
            }
        }
    }

    let score = evaluate_state(&clone, faction);
    (records, score)
}

/// Plan a full AI turn by trying multiple unit orderings and picking the best.
/// Returns (action_records, final_score).
///
/// Non-leaders move first (reordered across attempts), then leader acts last.
fn plan_full_turn(
    state: &GameState,
    faction: u8,
    cheapest_recruit_cost: u32,
    recruit_defs: &[(u32, u32)],
) -> (Vec<ActionRecord>, f32) {
    let leader_id = find_leader(state, faction);
    let return_keep = leader_should_return_to_keep(state, faction, cheapest_recruit_cost);

    // Collect non-leader units
    let mut non_leader_ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .filter(|(&id, _)| leader_id != Some(id))
        .map(|(&id, _)| id)
        .collect();

    // Sort for deterministic base ordering
    non_leader_ids.sort();

    let n = non_leader_ids.len();
    let orderings = if n <= 1 { 1 } else { TURN_PLAN_ORDERINGS.min(n) };

    let mut best_records = Vec::new();
    let mut best_score = f32::NEG_INFINITY;

    for i in 0..orderings {
        // Build ordering: non-leaders only (leader handled inside run_turn_ordering)
        let mut order: Vec<u32> = Vec::with_capacity(n);
        for j in 0..n {
            order.push(non_leader_ids[(j + i) % n]);
        }

        let (records, score) = run_turn_ordering(
            state, faction, leader_id, return_keep, &order,
            cheapest_recruit_cost, recruit_defs,
        );
        if score > best_score {
            best_score = score;
            best_records = records;
        }
    }

    (best_records, best_score)
}

// ── Core AI turn logic ──────────────────────────────────────────────────────

/// AI turn using multi-ordering turn planner: tries several unit orderings,
/// picks the one producing the best evaluated final state.
///
/// `cheapest_recruit_cost`: the cost of the cheapest recruitable unit (0 = no recruit info).
/// When > 0, the leader will stay on keep if recruiting is possible, or move back to keep.
pub fn ai_take_turn(state: &mut GameState, faction: u8, cheapest_recruit_cost: u32) {
    ai_take_turn_with_recruits(state, faction, cheapest_recruit_cost, &[]);
}

/// AI turn with recruit simulation: placeholder recruits are simulated in the
/// planning clone so the planner sees their value and keeps the leader on keep.
pub fn ai_take_turn_with_recruits(
    state: &mut GameState,
    faction: u8,
    cheapest_recruit_cost: u32,
    recruit_defs: &[(u32, u32)],
) {
    let (records, _score) = plan_full_turn(state, faction, cheapest_recruit_cost, recruit_defs);

    // Replay the best plan on the real state.
    // Skip actions for simulated recruit IDs (they don't exist in the real state).
    for record in &records {
        match record {
            ActionRecord::Move { unit_id, to_col, to_row } => {
                if !state.units.contains_key(unit_id) { continue; }
                let dest = Hex::from_offset(*to_col, *to_row);
                let _ = apply_action(state, Action::Move { unit_id: *unit_id, destination: dest });
            }
            ActionRecord::Attack { attacker_id, defender_id } => {
                if state.units.contains_key(attacker_id) && state.units.contains_key(defender_id) {
                    let _ = apply_action(state, Action::Attack { attacker_id: *attacker_id, defender_id: *defender_id });
                }
            }
            ActionRecord::Recruit => {
                // Handled by FFI layer which has registry access
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
    ai_plan_turn_with_recruits(state, faction, cheapest_recruit_cost, &[])
}

/// Plan an AI turn with recruit simulation for more accurate planning.
pub fn ai_plan_turn_with_recruits(
    state: &GameState,
    faction: u8,
    cheapest_recruit_cost: u32,
    recruit_defs: &[(u32, u32)],
) -> Vec<ActionRecord> {
    let (records, _score) = plan_full_turn(state, faction, cheapest_recruit_cost, recruit_defs);
    records
}

// ── Incremental planning session ────────────────────────────────────────────

/// Holds state for incremental AI planning (one ordering per frame).
pub struct PlanningSession {
    state: GameState,
    recruit_defs: Vec<(u32, u32)>,
    faction: u8,
    cheapest_recruit_cost: u32,
    current_ordering: usize,
    total_orderings: usize,
    best_result: Option<(Vec<ActionRecord>, f32)>,
    leader_id: Option<u32>,
    return_keep: Option<Hex>,
    non_leader_ids: Vec<u32>,
}

/// Create a new PlanningSession for incremental turn planning.
pub fn start_planning(
    state: &GameState,
    faction: u8,
    cheapest_recruit_cost: u32,
    recruit_defs: Vec<(u32, u32)>,
) -> PlanningSession {
    let leader_id = find_leader(state, faction);
    let return_keep = leader_should_return_to_keep(state, faction, cheapest_recruit_cost);

    let mut non_leader_ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .filter(|(&id, _)| leader_id != Some(id))
        .map(|(&id, _)| id)
        .collect();
    non_leader_ids.sort();

    let n = non_leader_ids.len();
    let total_orderings = if n <= 1 { 1 } else { TURN_PLAN_ORDERINGS.min(n) };

    PlanningSession {
        state: state.clone(),
        recruit_defs,
        faction,
        cheapest_recruit_cost,
        current_ordering: 0,
        total_orderings,
        best_result: None,
        leader_id,
        return_keep,
        non_leader_ids,
    }
}

/// Run one ordering step. Returns None if more orderings remain,
/// Some(best_actions) when all orderings are done.
pub fn plan_next_step(session: &mut PlanningSession) -> Option<Vec<ActionRecord>> {
    if session.current_ordering >= session.total_orderings {
        // Already done — return best
        return Some(
            session.best_result.take().map(|(r, _)| r).unwrap_or_default(),
        );
    }

    let n = session.non_leader_ids.len();
    let i = session.current_ordering;

    // Build ordering: rotate non-leader IDs
    let mut order: Vec<u32> = Vec::with_capacity(n);
    for j in 0..n {
        order.push(session.non_leader_ids[(j + i) % n]);
    }

    let (records, score) = run_turn_ordering(
        &session.state,
        session.faction,
        session.leader_id,
        session.return_keep,
        &order,
        session.cheapest_recruit_cost,
        &session.recruit_defs,
    );

    // Update best result
    let is_better = match &session.best_result {
        None => true,
        Some((_, best_score)) => score > *best_score,
    };
    if is_better {
        session.best_result = Some((records, score));
    }

    session.current_ordering += 1;

    if session.current_ordering >= session.total_orderings {
        // All orderings done
        Some(
            session.best_result.take().map(|(r, _)| r).unwrap_or_default(),
        )
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Tile};
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

        let result = plan_unit_action(&state, 1, 0, 1);
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

        let result = plan_unit_action(&state, 1, 0, 1);
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

        let result = plan_unit_action(&state, 1, 0, 1);
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

    // ── Turn planner tests ──────────────────────────────────────────

    #[test]
    fn test_turn_planner_returns_actions() {
        // Simple setup: 2 friendly units and 1 enemy.
        // plan_full_turn should return non-empty actions and a finite score.
        let mut board = Board::new(8, 3);
        for col in 0..8 {
            for row in 0..3 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        let u1 = make_fighter(1, 0, 30);
        state.place_unit(u1, Hex::from_offset(0, 1));
        let u2 = make_fighter(2, 0, 30);
        state.place_unit(u2, Hex::from_offset(1, 1));

        let enemy = make_fighter(3, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 1));

        let (records, score) = plan_full_turn(&state, 0, u32::MAX, &[]);
        assert!(!records.is_empty(), "Turn planner should produce actions");
        assert!(score.is_finite(), "Score should be finite, got {}", score);
    }

    #[test]
    fn test_turn_planner_multiple_orderings() {
        // 3 friendly units and 2 enemies. Multi-ordering should complete
        // and produce a score >= single ordering baseline.
        let mut board = Board::new(8, 5);
        for col in 0..8 {
            for row in 0..5 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        let u1 = make_fighter(1, 0, 30);
        state.place_unit(u1, Hex::from_offset(0, 1));
        let u2 = make_fighter(2, 0, 30);
        state.place_unit(u2, Hex::from_offset(0, 2));
        let u3 = make_fighter(3, 0, 30);
        state.place_unit(u3, Hex::from_offset(0, 3));

        let e1 = make_fighter(4, 1, 15);
        state.place_unit(e1, Hex::from_offset(5, 2));
        let e2 = make_fighter(5, 1, 15);
        state.place_unit(e2, Hex::from_offset(5, 3));

        // Run the multi-ordering planner
        let (records, score) = plan_full_turn(&state, 0, u32::MAX, &[]);

        // Should produce actions and a reasonable score
        assert!(!records.is_empty(), "Should produce actions with 3 units");
        assert!(score.is_finite(), "Score should be finite");

        // Run single ordering (just the first/natural order) as baseline
        let mut unit_ids: Vec<u32> = state.units.iter()
            .filter(|(_, u)| u.faction == 0 && !u.attacked)
            .map(|(id, _)| *id).collect();
        unit_ids.sort();
        let (_, single_score) = run_turn_ordering(&state, 0, None, None, &unit_ids, 0, &[]);

        assert!(
            score >= single_score,
            "Multi-ordering score ({}) should be >= single ordering ({})",
            score, single_score
        );
    }

    // ── Tactical behavior tests (Phase 101) ──────────────────────────────

    fn make_archer(id: u32, faction: u8, hp: u32) -> Unit {
        let bow = AttackDef {
            id: "bow".to_string(),
            name: "Bow".to_string(),
            damage: 5,
            strikes: 3,
            attack_type: "pierce".to_string(),
            range: "ranged".to_string(),
            ..Default::default()
        };
        let dagger = AttackDef {
            id: "dagger".to_string(),
            name: "Dagger".to_string(),
            damage: 4,
            strikes: 2,
            attack_type: "blade".to_string(),
            range: "melee".to_string(),
            ..Default::default()
        };
        let mut u = Unit::new(id, "archer", hp, faction);
        u.max_hp = hp;
        u.attacks = vec![bow, dagger];
        u.movement = 5;
        u.default_defense = 30;
        u
    }

    #[test]
    fn test_ranged_prefers_distance() {
        // Ranged unit can attack from distance 1 (melee) or distance 2 (ranged).
        // Should prefer distance 2 to avoid retaliation.
        let mut board = Board::new(5, 3);
        for col in 0..5 {
            for row in 0..3 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        // Archer at (0,1) with movement 5 — can reach both adjacent and distance-2
        let archer = make_archer(1, 0, 20);
        state.place_unit(archer, Hex::from_offset(0, 1));

        // Enemy at (3,1)
        let enemy = make_fighter(2, 1, 20);
        state.place_unit(enemy, Hex::from_offset(3, 1));

        let result = plan_unit_action(&state, 1, 0, 1);
        assert!(result.is_some(), "AI should choose an action");
        let (dest, target) = result.unwrap();
        assert_eq!(target, Some(2), "Should attack the enemy");
        let enemy_hex = Hex::from_offset(3, 1);
        assert_eq!(dest.distance(enemy_hex), 2,
            "Ranged unit should prefer distance-2 position, got distance {}",
            dest.distance(enemy_hex));
    }

    #[test]
    fn test_focus_fire_wounded() {
        // Two enemies attackable from the same position — one full HP, one wounded.
        // AI should prefer the wounded one (focus fire bonus).
        let mut board = Board::new(5, 5);
        for col in 0..5 {
            for row in 0..5 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut state = GameState::new(board);
        state.active_faction = 0;

        // Our fighter at (2,2)
        let attacker = make_fighter(1, 0, 30);
        state.place_unit(attacker, Hex::from_offset(2, 2));

        // Full HP enemy at (3,2)
        let full_enemy = make_fighter(2, 1, 30);
        state.place_unit(full_enemy, Hex::from_offset(3, 2));

        // Wounded enemy at (3,3) — set hp to 30% of max (9/30)
        let mut wounded_enemy = make_fighter(3, 1, 30);
        wounded_enemy.hp = 9;
        state.place_unit(wounded_enemy, Hex::from_offset(3, 3));

        let result = plan_unit_action(&state, 1, 0, 1);
        assert!(result.is_some(), "AI should choose an action");
        let (_, target) = result.unwrap();
        assert_eq!(target, Some(3),
            "AI should focus fire on the wounded enemy (id 3), got {:?}", target);
    }

    #[test]
    fn test_wounded_retreats_to_village() {
        // Wounded unit (below 30% HP) with a village reachable and no enemies
        // in attack range. Should move toward village.
        let mut board = Board::new(8, 3);
        for col in 0..8 {
            for row in 0..3 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        // Place a village (healing hex) at (1,1)
        let village_tile = Tile {
            terrain_id: "village".to_string(),
            movement_cost: 1,
            defense: 60,
            healing: 8,
            color: "#808080".to_string(),
        };
        board.set_tile(Hex::from_offset(1, 1), village_tile);

        let mut state = GameState::new(board);
        state.active_faction = 0;

        // Wounded unit at (3,1) — 5 HP out of 30 (16.7%, below 30%)
        let mut wounded = make_fighter(1, 0, 30);
        wounded.hp = 5;
        state.place_unit(wounded, Hex::from_offset(3, 1));

        // Enemy far away at (7,1) — not in attack range
        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 1));

        let result = plan_unit_action(&state, 1, 0, 1);
        assert!(result.is_some(), "Wounded unit should retreat");
        let (dest, target) = result.unwrap();
        assert!(target.is_none(), "Should not attack — retreating");
        let village_hex = Hex::from_offset(1, 1);
        let start_hex = Hex::from_offset(3, 1);
        assert!(dest.distance(village_hex) < start_hex.distance(village_hex),
            "Unit should move closer to village (dest dist: {}, start dist: {})",
            dest.distance(village_hex), start_hex.distance(village_hex));
    }

    #[test]
    fn test_wounded_still_attacks_for_kill() {
        // Wounded unit (20% HP) adjacent to a 1-HP enemy.
        // Should still attack for the kill rather than retreating.
        let mut board = Board::new(5, 3);
        for col in 0..5 {
            for row in 0..3 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        // Village available at (0,1)
        let village_tile = Tile {
            terrain_id: "village".to_string(),
            movement_cost: 1,
            defense: 60,
            healing: 8,
            color: "#808080".to_string(),
        };
        board.set_tile(Hex::from_offset(0, 1), village_tile);

        let mut state = GameState::new(board);
        state.active_faction = 0;

        // Wounded unit at (2,1) — 6 HP out of 30 (20%, below 30%)
        let mut wounded = make_fighter(1, 0, 30);
        wounded.hp = 6;
        state.place_unit(wounded, Hex::from_offset(2, 1));

        // Enemy at (3,1) with 1 HP — easy kill
        let mut dying_enemy = make_fighter(2, 1, 30);
        dying_enemy.hp = 1;
        state.place_unit(dying_enemy, Hex::from_offset(3, 1));

        let result = plan_unit_action(&state, 1, 0, 1);
        assert!(result.is_some(), "Wounded unit should still act");
        let (_, target) = result.unwrap();
        assert_eq!(target, Some(2),
            "Wounded unit should attack the 1-HP enemy for the kill");
    }

    // ── Recruit-first tests (Phase 102) ──────────────────────────────────

    #[test]
    fn test_recruit_first_leader_stays() {
        // Leader on keep with gold and castle slots.
        // With recruit_defs, leader should stay on keep.
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 100;

        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 2));

        let recruit_defs = vec![(10u32, 5u32)];
        let (records, _) = plan_full_turn(&state, 0, 10, &recruit_defs);

        // Leader (id=1) should NOT have a Move action
        let leader_moved = records.iter().any(|r| matches!(r, ActionRecord::Move { unit_id: 1, .. }));
        assert!(!leader_moved,
            "Leader should stay on keep when recruits are possible, got: {:?}", records);
    }

    #[test]
    fn test_recruit_first_fills_castle() {
        // Leader on keep with enough gold. simulate_recruitment should fill castle slots.
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 200; // plenty

        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 2));

        let recruit_defs = vec![(10u32, 5u32)];
        let mut clone = state.clone();
        let recruited = simulate_recruitment(&mut clone, 0, &recruit_defs);

        // setup_keep_board places castle on all 6 neighbors within board bounds
        assert!(recruited.len() >= 2,
            "Should recruit at least 2 units, got {}", recruited.len());
        // Gold should be reduced
        assert!(clone.gold[0] < 200,
            "Gold should be spent on recruits, still at {}", clone.gold[0]);
        // All recruited units should exist in the clone
        for &uid in &recruited {
            assert!(clone.units.contains_key(&uid),
                "Recruited unit {} should exist in clone", uid);
        }
    }

    #[test]
    fn test_no_recruit_when_broke() {
        // Leader on keep with 0 gold. Should not recruit.
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 0;

        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 2));

        let recruit_defs = vec![(10u32, 5u32)];
        let mut clone = state.clone();
        let recruited = simulate_recruitment(&mut clone, 0, &recruit_defs);

        assert!(recruited.is_empty(),
            "Should not recruit with 0 gold, got {} recruits", recruited.len());
    }

    #[test]
    fn test_recruit_move_recruit_cycle() {
        // Leader on keep with gold. Initial recruits fill castle slots.
        // When recruits move off castle hexes, leader recruits MORE into freed slots.
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 200; // Enough for many recruits

        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 2));

        let recruit_defs = vec![(15u32, 5u32)];

        // Count how many castle slots exist
        let keep = Hex::from_offset(0, 2);
        let castle_count = keep.neighbors().iter()
            .filter(|&&h| state.board.contains(h)
                && state.board.tile_at(h).map(|t| t.terrain_id == "castle").unwrap_or(false))
            .count();

        // Plan a full turn — should recruit, move recruits out, recruit again
        let (records, _) = plan_full_turn(&state, 0, 15, &recruit_defs);

        // Count how many units were planned to move (not the leader)
        let units_moved: HashSet<u32> = records.iter().filter_map(|r| match r {
            ActionRecord::Move { unit_id, .. } if *unit_id != 1 => Some(*unit_id),
            _ => None,
        }).collect();

        // Should have more units moving than the initial castle slots
        // because recruits moved out and new recruits filled the freed slots
        eprintln!("Castle slots: {}, units moved: {}, total actions: {}",
            castle_count, units_moved.len(), records.len());

        assert!(units_moved.len() >= castle_count,
            "Should recruit-move-recruit: {} castle slots but only {} units moved. Actions: {:?}",
            castle_count, units_moved.len(), records);
    }

    #[test]
    fn test_2ply_leader_catches_oscillation() {
        // Leader on keep with gold + castle slots + enemy far away.
        // With 2-ply, leader should stay on keep because leaving would be
        // punished by opponent response (wasted turn returning).
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 100;

        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        // Enemy far away — temptation to leave keep
        let enemy = make_fighter(2, 1, 30);
        state.place_unit(enemy, Hex::from_offset(7, 2));

        // With recruit_defs, the planner simulates recruits so leader stays.
        // But even without recruits, 2-ply leader should recognize leaving is bad.
        let records = ai_plan_turn(&state, 0, 15);

        // Leader should NOT move off keep
        let leader_moved = records.iter().any(|r| matches!(r, ActionRecord::Move { unit_id: 1, .. }));
        assert!(!leader_moved,
            "2-ply leader should stay on keep with gold available, got: {:?}", records);
    }

    #[test]
    fn test_2ply_leader_performance() {
        // Realistic scenario: 8x5 board, 5 units per side, leader on keep.
        // Verify plan_full_turn completes in reasonable time with 2-ply leader.
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 50;

        // Place leader on keep
        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        // Place 4 friendly fighters
        for i in 0..4 {
            let f = make_fighter(10 + i, 0, 30);
            let col = 1 + (i as i32 % 3);
            let row = (i as i32 / 3) + 1;
            state.place_unit(f, Hex::from_offset(col, row));
        }

        // Place 5 enemy fighters
        for i in 0..5 {
            let e = make_fighter(20 + i, 1, 30);
            let col = 5 + (i as i32 % 3);
            let row = (i as i32 / 3) + 1;
            state.place_unit(e, Hex::from_offset(col, row));
        }

        let recruit_defs = vec![(15u32, 5u32)];
        let start = std::time::Instant::now();
        let (records, score) = plan_full_turn(&state, 0, 15, &recruit_defs);
        let elapsed = start.elapsed();

        assert!(elapsed.as_secs() < 30,
            "2-ply planning took {:?}, exceeds 30s debug bound", elapsed);
        assert!(!records.is_empty(), "Should produce some actions");
        assert!(score > f32::NEG_INFINITY, "Score should be finite");

        // Log timing for reference
        eprintln!("2-ply leader performance: {:?} ({} actions, score {:.1})", elapsed, records.len(), score);
    }

    #[test]
    fn test_2ply_all_units_performance() {
        // Same scenario but measure what happens if ALL units use 2-ply.
        // This test just measures — it doesn't fail on time (informational).
        let board = setup_keep_board(0, 2);
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 50;

        let leader = make_leader(1, 0);
        state.place_unit(leader, Hex::from_offset(0, 2));

        for i in 0..4 {
            let f = make_fighter(10 + i, 0, 30);
            let col = 1 + (i as i32 % 3);
            let row = (i as i32 / 3) + 1;
            state.place_unit(f, Hex::from_offset(col, row));
        }

        for i in 0..5 {
            let e = make_fighter(20 + i, 1, 30);
            let col = 5 + (i as i32 % 3);
            let row = (i as i32 / 3) + 1;
            state.place_unit(e, Hex::from_offset(col, row));
        }

        let recruit_defs = vec![(15u32, 5u32)];
        let start = std::time::Instant::now();

        // Manually run with all units at depth 2 by calling plan_unit_action directly
        let mut clone = state.clone();
        let _recruited = simulate_recruitment(&mut clone, 0, &recruit_defs);
        let unit_ids: Vec<u32> = clone.units.iter()
            .filter(|(_, u)| u.faction == 0 && !u.attacked)
            .map(|(&id, _)| id)
            .collect();

        for &uid in &unit_ids {
            if !clone.units.contains_key(&uid) { continue; }
            if let Some((dest, target)) = plan_unit_action(&clone, uid, 0, 2) {
                let s = clone.positions[&uid];
                if dest != s {
                    let _ = apply_action(&mut clone, Action::Move { unit_id: uid, destination: dest });
                }
                if let Some(tid) = target {
                    if clone.units.contains_key(&uid) && clone.units.contains_key(&tid) {
                        let _ = apply_action(&mut clone, Action::Attack { attacker_id: uid, defender_id: tid });
                    }
                }
            }
        }
        let elapsed = start.elapsed();

        eprintln!("2-ply ALL units performance: {:?}", elapsed);

        // If all-unit 2-ply is under 30s, it's viable
        if elapsed.as_secs() < 30 {
            eprintln!("All-unit 2-ply is fast enough! Consider enabling for all units.");
        } else {
            eprintln!("All-unit 2-ply too slow ({:?}), keeping leader-only.", elapsed);
        }

        // Soft assertion — just ensure it finishes at all
        assert!(elapsed.as_secs() < 120,
            "All-unit 2-ply took {:?}, even the generous bound exceeded", elapsed);
    }
}
