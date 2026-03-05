//! Hex-aware pathfinding using Dijkstra's algorithm with terrain movement costs.

use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashMap, HashSet};

use crate::board::Board;
use crate::game_state::GameState;
use crate::hex::Hex;

/// Returns all hexes adjacent to units that do NOT belong to `moving_faction`.
///
/// These hexes exert a Zone of Control against `moving_faction`. A non-skirmisher
/// unit entering one of these hexes must stop there.
pub fn get_zoc_hexes(state: &GameState, moving_faction: u8) -> HashSet<Hex> {
    let mut zoc = HashSet::new();
    for (&unit_id, unit) in &state.units {
        if unit.faction != moving_faction {
            if let Some(&pos) = state.positions.get(&unit_id) {
                for n in pos.neighbors() {
                    zoc.insert(n);
                }
            }
        }
    }
    zoc
}

/// Find the lowest-cost path from `start` to `destination` using A*.
///
/// Movement cost for each hex is looked up by terrain id from `movement_costs`.
/// If the terrain id is not found, `default_movement_cost` is used. A cost of
/// 99 or higher is treated as impassable.
///
/// ZOC rules: a non-skirmisher unit that enters a hex in `zoc_hexes` must stop
/// there (neighbors of that hex are not expanded). Skirmishers ignore this rule.
///
/// Returns `Some((path, total_cost))` where `path` runs from `start` to
/// `destination` inclusive. Returns `None` if the destination is unreachable
/// within `movement_budget` or is blocked by ZOC.
#[allow(clippy::too_many_arguments)]
pub fn find_path(
    board: &Board,
    movement_costs: &HashMap<String, u32>,
    default_movement_cost: u32,
    start: Hex,
    destination: Hex,
    movement_budget: u32,
    zoc_hexes: &HashSet<Hex>,
    is_skirmisher: bool,
) -> Option<(Vec<Hex>, u32)> {
    // Min-heap: Reverse((f_cost, g_cost, hex))
    let mut open: BinaryHeap<Reverse<(u32, u32, Hex)>> = BinaryHeap::new();
    let mut g_cost: HashMap<Hex, u32> = HashMap::new();
    let mut came_from: HashMap<Hex, Hex> = HashMap::new();
    let mut closed: HashSet<Hex> = HashSet::new();

    g_cost.insert(start, 0);
    open.push(Reverse((h(start, destination), 0, start)));

    while let Some(Reverse((_, g, current))) = open.pop() {
        if current == destination {
            return Some((reconstruct_path(&came_from, start, destination), g));
        }

        if closed.contains(&current) {
            continue;
        }
        closed.insert(current);

        // ZOC stop rule: if we are AT a ZOC hex and are not a skirmisher,
        // this unit cannot continue moving — do not expand neighbours.
        if zoc_hexes.contains(&current) && !is_skirmisher && current != start {
            continue;
        }

        for neighbor in current.neighbors() {
            if !board.contains(neighbor) {
                continue;
            }
            if closed.contains(&neighbor) {
                continue;
            }

            let terrain_id = board.terrain_at(neighbor).unwrap_or("");
            let step_cost = movement_costs
                .get(terrain_id)
                .copied()
                .unwrap_or(default_movement_cost);

            if step_cost >= 99 {
                continue;
            }

            let tentative_g = g + step_cost;
            if tentative_g > movement_budget {
                continue;
            }

            if tentative_g < g_cost.get(&neighbor).copied().unwrap_or(u32::MAX) {
                g_cost.insert(neighbor, tentative_g);
                came_from.insert(neighbor, current);
                let f = tentative_g + h(neighbor, destination);
                open.push(Reverse((f, tentative_g, neighbor)));
            }
        }
    }

    None
}

/// Return all hexes reachable from `start` within `movement_budget` movement points.
///
/// Uses Dijkstra (single-pass flood fill) rather than repeated A* calls.
/// The result always includes `start` (cost = 0).
///
/// ZOC stop rule: a non-skirmisher that enters a ZOC hex is added to the
/// reachable set but its neighbours are not expanded (unit must stop there).
#[allow(clippy::too_many_arguments)]
pub fn reachable_hexes(
    board: &Board,
    movement_costs: &HashMap<String, u32>,
    default_movement_cost: u32,
    start: Hex,
    movement_budget: u32,
    zoc_hexes: &HashSet<Hex>,
    is_skirmisher: bool,
) -> HashSet<Hex> {
    let mut reachable: HashSet<Hex> = HashSet::new();
    // Min-heap: Reverse((g_cost, hex))
    let mut open: BinaryHeap<Reverse<(u32, Hex)>> = BinaryHeap::new();
    let mut g_cost: HashMap<Hex, u32> = HashMap::new();

    g_cost.insert(start, 0);
    open.push(Reverse((0, start)));

    while let Some(Reverse((g, current))) = open.pop() {
        if reachable.contains(&current) {
            continue;
        }
        reachable.insert(current);

        // ZOC stop rule: don't expand from a ZOC hex (unless skirmisher or start)
        if zoc_hexes.contains(&current) && !is_skirmisher && current != start {
            continue;
        }

        for neighbor in current.neighbors() {
            if !board.contains(neighbor) {
                continue;
            }
            if reachable.contains(&neighbor) {
                continue;
            }

            let terrain_id = board.terrain_at(neighbor).unwrap_or("");
            let step_cost = movement_costs
                .get(terrain_id)
                .copied()
                .unwrap_or(default_movement_cost);

            if step_cost >= 99 {
                continue;
            }

            let tentative_g = g + step_cost;
            if tentative_g > movement_budget {
                continue;
            }

            if tentative_g < g_cost.get(&neighbor).copied().unwrap_or(u32::MAX) {
                g_cost.insert(neighbor, tentative_g);
                open.push(Reverse((tentative_g, neighbor)));
            }
        }
    }

    reachable
}

fn h(a: Hex, b: Hex) -> u32 {
    a.distance(b)
}

fn reconstruct_path(came_from: &HashMap<Hex, Hex>, start: Hex, end: Hex) -> Vec<Hex> {
    let mut path = Vec::new();
    let mut current = end;
    while current != start {
        path.push(current);
        current = came_from[&current];
    }
    path.push(start);
    path.reverse();
    path
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_terrain_cost_accumulation() {
        // Straight-line path along row 0: cols 0..=3, all "forest" (cost 1 each)
        let mut board = Board::new(10, 10);
        for col in 0..4_i32 {
            board.set_terrain(Hex::from_offset(col, 0), "forest");
        }
        let mut movement_costs = HashMap::new();
        movement_costs.insert("forest".to_string(), 1u32);
        let zoc: HashSet<Hex> = HashSet::new();

        let result = find_path(
            &board,
            &movement_costs,
            2,
            Hex::from_offset(0, 0),
            Hex::from_offset(3, 0),
            10,
            &zoc,
            false,
        );

        let (path, cost) = result.expect("path through forest hexes should exist");
        assert_eq!(cost, 3, "3 forest hexes × 1 mp each = 3");
        assert_eq!(path.first(), Some(&Hex::from_offset(0, 0)));
        assert_eq!(path.last(), Some(&Hex::from_offset(3, 0)));
    }

    #[test]
    fn test_zoc_blocks_path_beyond() {
        // A 1-row board forces strictly left/right movement — no way to route
        // around a ZOC hex, so the test reliably isolates the ZOC stop rule.
        let board = Board::new(10, 1);
        let movement_costs: HashMap<String, u32> = HashMap::new(); // default_cost = 1

        // ZOC covers (2,0) — the only path from (0,0) to (4,0) must pass through it
        let mut zoc: HashSet<Hex> = HashSet::new();
        zoc.insert(Hex::from_offset(2, 0));

        // Cannot reach (4,0): must enter ZOC hex (2,0) and stop
        let blocked = find_path(
            &board,
            &movement_costs,
            1,
            Hex::from_offset(0, 0),
            Hex::from_offset(4, 0),
            10,
            &zoc,
            false,
        );
        assert!(blocked.is_none(), "path past ZOC hex must be blocked for non-skirmisher");

        // Can still reach the ZOC hex itself
        let to_zoc = find_path(
            &board,
            &movement_costs,
            1,
            Hex::from_offset(0, 0),
            Hex::from_offset(2, 0),
            10,
            &zoc,
            false,
        );
        assert!(to_zoc.is_some(), "unit can enter (and stop at) a ZOC hex");
    }

    #[test]
    fn test_reachable_hexes_respects_budget() {
        let mut board = Board::new(5, 5);
        for col in 0..5_i32 {
            for row in 0..5_i32 {
                board.set_terrain(Hex::from_offset(col, row), "flat");
            }
        }
        let mut movement_costs = HashMap::new();
        movement_costs.insert("flat".to_string(), 1u32);
        let zoc: HashSet<Hex> = HashSet::new();

        let start = Hex::from_offset(2, 2);
        let reachable = reachable_hexes(&board, &movement_costs, 1, start, 2, &zoc, false);

        // Own hex always reachable
        assert!(reachable.contains(&start), "start hex must be reachable");
        // Adjacent hex (1 step) must be reachable
        assert!(reachable.contains(&Hex::from_offset(1, 2)), "(1,2) is 1 step away");
        // Corner (0,0) is far from center — 4 movement points — must be out of budget
        assert!(!reachable.contains(&Hex::from_offset(0, 0)), "(0,0) is beyond budget 2");
        // At budget=2 from center of 5×5, expect 7+ hexes reachable (own + 6 adjacent)
        assert!(reachable.len() >= 7, "expected at least 7 reachable hexes, got {}", reachable.len());
    }

    #[test]
    fn test_skirmisher_bypasses_zoc() {
        // Same 1-row setup — skirmisher must be able to continue through ZOC hex
        let board = Board::new(10, 1);
        let movement_costs: HashMap<String, u32> = HashMap::new();

        let mut zoc: HashSet<Hex> = HashSet::new();
        zoc.insert(Hex::from_offset(2, 0));

        let result = find_path(
            &board,
            &movement_costs,
            1,
            Hex::from_offset(0, 0),
            Hex::from_offset(4, 0),
            10,
            &zoc,
            true, // is_skirmisher
        );
        assert!(result.is_some(), "skirmisher must be able to path past a ZOC hex");
    }
}
