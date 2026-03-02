use std::collections::HashMap;

use crate::hex::Hex;
use crate::schema::TerrainDef;

/// Runtime hex tile — instantiated from `TerrainDef` at placement time.
///
/// Mirrors the `Unit`/`UnitDef` pattern: each hex on the board carries its own
/// autonomous copy of terrain properties so that per-hex customisation is possible
/// without new TOML types.
#[derive(Debug, Clone)]
pub struct Tile {
    pub terrain_id: String,
    /// Default movement cost for units with no entry for this terrain (from TerrainDef).
    pub movement_cost: u32,
    /// Default defense % for units with no entry for this terrain (from TerrainDef).
    pub defense: u32,
    /// HP healed to active-faction units at the start of their turn (0 = no healing).
    pub healing: u32,
    /// Hex color string for rendering (e.g. "#4a7c4e"). "#808080" = no TOML color assigned.
    pub color: String,
}

impl Tile {
    /// Create a Tile with sensible defaults. Used in tests and fallback paths.
    pub fn new(terrain_id: impl Into<String>) -> Self {
        Self { terrain_id: terrain_id.into(), movement_cost: 1, defense: 40, healing: 0, color: "#808080".to_string() }
    }

    /// Create a Tile from a TerrainDef registry entry.
    pub fn from_def(def: &TerrainDef) -> Self {
        Self {
            terrain_id: def.id.clone(),
            movement_cost: def.default_movement_cost,
            defense: def.default_defense,
            healing: def.healing,
            color: def.color.clone(),
        }
    }
}

/// Defines the playable area of a map in offset coordinate space.
///
/// Board dimensions are specified in grid cells (width × height), matching
/// how Wesnoth-compatible map files describe their layout. Boundary checks
/// convert to offset coordinates internally.
///
/// Each hex may have a `Tile` (terrain type + properties). Hexes without an
/// assigned tile return `None` from `tile_at` / `terrain_at`.
#[derive(Debug, Clone)]
pub struct Board {
    pub width: u32,
    pub height: u32,
    tiles: HashMap<Hex, Tile>,
}

impl Board {
    pub fn new(width: u32, height: u32) -> Self {
        assert!(width > 0 && height > 0, "Board dimensions must be positive");
        Self { width, height, tiles: HashMap::new() }
    }

    /// Returns true if `hex` lies within the board's bounds.
    pub fn contains(&self, hex: Hex) -> bool {
        let (col, row) = hex.to_offset();
        col >= 0 && row >= 0 && col < self.width as i32 && row < self.height as i32
    }

    /// Assign a terrain type to `hex` using default Tile values. Panics if out of bounds.
    ///
    /// Use `set_tile()` when a `TerrainDef` is available for full property initialisation.
    pub fn set_terrain(&mut self, hex: Hex, terrain_id: impl Into<String>) {
        assert!(self.contains(hex), "set_terrain: hex out of bounds");
        self.tiles.insert(hex, Tile::new(terrain_id));
    }

    /// Assign a fully-initialised `Tile` to `hex`. Panics if out of bounds.
    pub fn set_tile(&mut self, hex: Hex, tile: Tile) {
        assert!(self.contains(hex), "set_tile: hex out of bounds");
        self.tiles.insert(hex, tile);
    }

    /// Return the terrain id at `hex`, or `None` if no tile is set.
    pub fn terrain_at(&self, hex: Hex) -> Option<&str> {
        self.tiles.get(&hex).map(|t| t.terrain_id.as_str())
    }

    /// Return the `Tile` at `hex`, or `None` if no tile is set.
    pub fn tile_at(&self, hex: Hex) -> Option<&Tile> {
        self.tiles.get(&hex)
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
        assert_eq!(board.tile_at(Hex::ORIGIN).unwrap().terrain_id, "forest");
    }
}
