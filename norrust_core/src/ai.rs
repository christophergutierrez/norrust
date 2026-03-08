//! AI opponent logic using scored move evaluation with combat and terrain awareness.

use std::collections::HashSet;

use crate::combat::{time_of_day, tod_damage_modifier};
use crate::game_state::{apply_action, Action, GameState};
use crate::hex::Hex;
use crate::pathfinding::{get_zoc_hexes, reachable_hexes};
use crate::unit::Unit;

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

/// Greedy AI: for every unit of `faction`, find the best (destination, target)
/// pair by expected-damage scoring, apply Move + Attack, then end the turn.
///
/// Units dead from retaliation or already attacked are skipped. apply_action
/// errors are ignored — a target may have died earlier this turn.
pub fn ai_take_turn(state: &mut GameState, faction: u8) {
    // Collect unit IDs upfront to avoid borrow conflicts during apply_action.
    let unit_ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .map(|(id, _)| *id)
        .collect();

    for uid in unit_ids {
        // Unit may have been killed by retaliation from a prior action this turn.
        if !state.units.contains_key(&uid) || state.units[&uid].attacked {
            continue;
        }

        let start = state.positions[&uid];

        // Clone movement data before any other borrows of state.
        let movement_costs = state.units[&uid].movement_costs.clone();
        let movement = {
            let m = state.units[&uid].movement;
            if state.units[&uid].slowed { m / 2 } else { m }
        };

        let zoc = get_zoc_hexes(state, faction);
        let candidates_raw =
            reachable_hexes(&state.board, &movement_costs, 1, start, movement, &zoc, false);

        // Build the occupied set (everyone except this unit).
        let all_occupied: HashSet<Hex> = state
            .positions
            .iter()
            .filter(|(&id, _)| id != uid)
            .map(|(_, &h)| h)
            .collect();

        // Reachable hexes the unit can actually land on.
        let candidates: Vec<Hex> = candidates_raw
            .into_iter()
            .filter(|&h| h == start || !all_occupied.contains(&h))
            .collect();

        // Collect enemy data as owned values to avoid borrow conflicts.
        let enemy_ids_units: Vec<(u32, Unit)> = state
            .units
            .iter()
            .filter(|(_, u)| u.faction != faction)
            .map(|(id, u)| (*id, u.clone()))
            .collect();
        let enemies: Vec<(u32, Hex, Unit)> = enemy_ids_units
            .into_iter()
            .map(|(id, u)| (id, state.positions[&id], u))
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

        // enemy_weak: 1 HP — dealt >= hp, kill_bonus = 3.0
        let enemy_weak = Unit::new(2, "enemy", 1, 1);
        // enemy_strong: 30 HP — dealt < hp (100 × 1.0 > 30, but let's adjust:
        //   defender has 40% default_defense → hit_chance 0.6 → expected 60 < hp no...)
        // Actually 100 × 0.6 = 60 >= 30, so both would get kill_bonus.
        // Use a tankier enemy: 200 HP
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
}
