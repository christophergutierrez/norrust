use std::collections::HashMap;

use crate::hex::Hex;

/// Defines the playable area of a map in offset coordinate space.
///
/// Board dimensions are specified in grid cells (width × height), matching
/// how Wesnoth-compatible map files describe their layout. Boundary checks
/// convert to offset coordinates internally.
///
/// Each hex may have a terrain type (stored as a terrain id string). Hexes
/// without an assigned terrain return `None` from `terrain_at`.
#[derive(Debug, Clone)]
pub struct Board {
    pub width: u32,
    pub height: u32,
    terrain: HashMap<Hex, String>,
    healing_map: HashMap<String, u32>,
}

impl Board {
    pub fn new(width: u32, height: u32) -> Self {
        assert!(width > 0 && height > 0, "Board dimensions must be positive");
        Self { width, height, terrain: HashMap::new(), healing_map: HashMap::new() }
    }

    /// Returns true if `hex` lies within the board's bounds.
    pub fn contains(&self, hex: Hex) -> bool {
        let (col, row) = hex.to_offset();
        col >= 0 && row >= 0 && col < self.width as i32 && row < self.height as i32
    }

    /// Assign a terrain type to `hex`. Panics if `hex` is out of bounds.
    pub fn set_terrain(&mut self, hex: Hex, terrain_id: impl Into<String>) {
        assert!(self.contains(hex), "set_terrain: hex out of bounds");
        self.terrain.insert(hex, terrain_id.into());
    }

    /// Return the terrain id at `hex`, or `None` if no terrain is set.
    pub fn terrain_at(&self, hex: Hex) -> Option<&str> {
        self.terrain.get(&hex).map(String::as_str)
    }

    /// Store the healing value for a terrain type.
    pub fn set_healing(&mut self, terrain_id: impl Into<String>, healing: u32) {
        self.healing_map.insert(terrain_id.into(), healing);
    }

    /// Return healing per turn for a terrain id (0 if unknown).
    pub fn healing_for(&self, terrain_id: &str) -> u32 {
        self.healing_map.get(terrain_id).copied().unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_board_contains_origin() {
        let board = Board::new(10, 10);
        assert!(board.contains(Hex::ORIGIN));
    }

    #[test]
    fn test_board_excludes_negative_offset() {
        let board = Board::new(10, 10);
        assert!(!board.contains(Hex::from_offset(-1, 0)));
        assert!(!board.contains(Hex::from_offset(0, -1)));
    }

    #[test]
    fn test_board_excludes_beyond_size() {
        let board = Board::new(5, 5);
        assert!(!board.contains(Hex::from_offset(5, 0)));
        assert!(!board.contains(Hex::from_offset(0, 5)));
        assert!(!board.contains(Hex::from_offset(5, 5)));
    }

    #[test]
    fn test_board_includes_last_cell() {
        let board = Board::new(5, 5);
        assert!(board.contains(Hex::from_offset(4, 4)));
    }

    #[test]
    fn test_board_1x1() {
        let board = Board::new(1, 1);
        assert!(board.contains(Hex::ORIGIN));
        // The only valid cell is (0,0) — immediate neighbors are out of bounds
        for n in Hex::ORIGIN.neighbors() {
            assert!(!board.contains(n), "neighbor {:?} should be out of 1x1 board", n);
        }
    }

    #[test]
    fn test_terrain_set_and_get() {
        let mut board = Board::new(5, 5);
        board.set_terrain(Hex::ORIGIN, "forest");
        assert_eq!(board.terrain_at(Hex::ORIGIN), Some("forest"));
        assert_eq!(board.terrain_at(Hex::from_offset(1, 0)), None);
    }
}
