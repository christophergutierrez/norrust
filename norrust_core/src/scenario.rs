use std::path::Path;

use crate::board::Board;
use crate::hex::Hex;
use crate::schema::{BoardDef, UnitPlacement, UnitsDef};

/// Load a Board from a TOML board file.
///
/// The file must have `width`, `height`, and `tiles` fields.
/// `tiles` is a flat row-major array of terrain ID strings (left→right, top→bottom).
/// Returns Err if the file cannot be read, parsed, or if
/// `tiles.len() != width * height`.
pub fn load_board(path: &Path) -> Result<Board, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("load_board: cannot read {:?}: {}", path, e))?;
    let def: BoardDef = toml::from_str(&text)
        .map_err(|e| format!("load_board: parse error in {:?}: {}", path, e))?;
    let expected = (def.width * def.height) as usize;
    if def.tiles.len() != expected {
        return Err(format!(
            "load_board: tiles.len()={} but width×height={}",
            def.tiles.len(),
            expected
        ));
    }
    let mut board = Board::new(def.width, def.height);
    for row in 0..def.height as i32 {
        for col in 0..def.width as i32 {
            let idx = (row as usize) * (def.width as usize) + (col as usize);
            let terrain_id = def.tiles[idx].clone();
            board.set_terrain(Hex::from_offset(col, row), terrain_id);
        }
    }
    Ok(board)
}

/// Load unit placements from a TOML units file.
///
/// The file must contain one or more `[[units]]` entries, each with
/// `id`, `unit_type`, `faction`, `col`, `row` fields.
/// Returns Err if the file cannot be read or parsed.
pub fn load_units(path: &Path) -> Result<Vec<UnitPlacement>, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("load_units: cannot read {:?}: {}", path, e))?;
    let def: UnitsDef = toml::from_str(&text)
        .map_err(|e| format!("load_units: parse error in {:?}: {}", path, e))?;
    Ok(def.units)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_board_tile_count_mismatch() {
        let tmp_path = std::env::temp_dir().join("norrust_test_bad_board.toml");
        std::fs::write(&tmp_path, "width = 3\nheight = 2\ntiles = [\"flat\", \"flat\"]\n")
            .unwrap();
        let result = load_board(&tmp_path);
        assert!(result.is_err(), "mismatched tile count must return Err");
        assert!(
            result.unwrap_err().contains("tiles.len()"),
            "error message must mention tile count"
        );
    }
}
