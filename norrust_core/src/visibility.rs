//! Fog of war visibility calculation — range-based per-faction hex visibility.

use std::collections::HashSet;
use crate::game_state::GameState;
use crate::hex::Hex;

/// Compute the set of hexes visible to the given faction.
///
/// A hex is visible if any unit belonging to `faction` has it within its
/// effective vision range (vision_range if > 0, else movement).
/// Range-based only — no line-of-sight blocking.
pub fn compute_visibility(state: &GameState, faction: u8) -> HashSet<Hex> {
    // Collect friendly units with their positions and effective vision range
    let observers: Vec<(Hex, u32)> = state.units.values()
        .filter(|u| u.faction == faction)
        .filter_map(|u| {
            let pos = state.positions.get(&u.id)?;
            let range = if u.vision_range > 0 { u.vision_range } else { u.movement };
            Some((*pos, range))
        })
        .collect();

    let mut visible = HashSet::new();

    for hex in state.board.tile_hexes() {
        for &(pos, range) in &observers {
            if pos.distance(*hex) <= range {
                visible.insert(*hex);
                break; // already visible, no need to check more observers
            }
        }
    }

    visible
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::Board;
    use crate::unit::Unit;
    use crate::hex::Hex;

    fn make_state(width: u32, height: u32) -> GameState {
        let board = Board::new(width, height);
        let mut state = GameState::new(board);
        // Set all tiles to flat terrain so the board has tiles
        for row in 0..height as i32 {
            for col in 0..width as i32 {
                let hex = Hex::from_offset(col, row);
                state.board.set_terrain(hex, "flat");
            }
        }
        state
    }

    fn place_unit(state: &mut GameState, id: u32, faction: u8, col: i32, row: i32, movement: u32, vision_range: u32) {
        let mut unit = Unit::new(id, "test", 20, faction);
        unit.movement = movement;
        unit.vision_range = vision_range;
        let hex = Hex::from_offset(col, row);
        state.units.insert(id, unit);
        state.positions.insert(id, hex);
        state.hex_to_unit.insert(hex, id);
    }

    #[test]
    fn test_basic_visibility() {
        let mut state = make_state(5, 5);
        place_unit(&mut state, 1, 0, 2, 2, 4, 2); // vision_range=2

        let vis = compute_visibility(&state, 0);
        let center = Hex::from_offset(2, 2);

        // Center should be visible
        assert!(vis.contains(&center));

        // All hexes within distance 2 should be visible
        for hex in state.board.tile_hexes() {
            if center.distance(*hex) <= 2 {
                assert!(vis.contains(hex), "hex {:?} within range 2 should be visible", hex);
            }
        }

        // Hexes beyond distance 2 should not be visible
        for hex in state.board.tile_hexes() {
            if center.distance(*hex) > 2 {
                assert!(!vis.contains(hex), "hex {:?} beyond range 2 should not be visible", hex);
            }
        }
    }

    #[test]
    fn test_vision_range_fallback_to_movement() {
        let mut state = make_state(7, 7);
        place_unit(&mut state, 1, 0, 3, 3, 5, 0); // vision_range=0 → uses movement=5

        let vis = compute_visibility(&state, 0);
        let center = Hex::from_offset(3, 3);

        // All board hexes within distance 5 should be visible
        for hex in state.board.tile_hexes() {
            if center.distance(*hex) <= 5 {
                assert!(vis.contains(hex));
            }
        }
    }

    #[test]
    fn test_multiple_units_union() {
        let mut state = make_state(10, 1);
        // Two units far apart with small vision
        place_unit(&mut state, 1, 0, 0, 0, 4, 1);
        place_unit(&mut state, 2, 0, 9, 0, 4, 1);

        let vis = compute_visibility(&state, 0);
        let h0 = Hex::from_offset(0, 0);
        let h9 = Hex::from_offset(9, 0);

        // Both unit positions visible
        assert!(vis.contains(&h0));
        assert!(vis.contains(&h9));

        // Neighbors of each unit visible
        assert!(vis.contains(&Hex::from_offset(1, 0)));
        assert!(vis.contains(&Hex::from_offset(8, 0)));

        // Middle of the board should NOT be visible (distance > 1 from both)
        let mid = Hex::from_offset(5, 0);
        assert!(!vis.contains(&mid));
    }

    #[test]
    fn test_enemy_not_counted() {
        let mut state = make_state(5, 5);
        place_unit(&mut state, 1, 1, 2, 2, 4, 3); // faction 1, vision_range=3

        let vis = compute_visibility(&state, 0);

        // Faction 0 has no units, so nothing visible
        assert!(vis.is_empty());
    }
}
