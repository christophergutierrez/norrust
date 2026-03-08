//! Scenario loading from TOML files — board, units, triggers, and win conditions.

use std::path::Path;

use crate::board::Board;
use crate::hex::Hex;
use crate::schema::{BoardDef, TriggerDef, UnitPlacement, UnitsDef};

/// Result of loading a board file — includes board plus optional scenario metadata.
#[derive(Debug)]
pub struct LoadedBoard {
    pub board: Board,
    /// Objective hex — reaching it wins the game.
    pub objective_hex: Option<Hex>,
    /// Maximum turns before defender wins by timeout.
    pub max_turns: Option<u32>,
}

/// Load a Board from a TOML board file.
///
/// The file must have `width`, `height`, and `tiles` fields.
/// `tiles` is a flat row-major array of terrain ID strings (left→right, top→bottom).
/// Optional `objective_col`/`objective_row` and `max_turns` fields set win conditions.
/// Returns Err if the file cannot be read, parsed, or if
/// `tiles.len() != width * height`.
pub fn load_board(path: &Path) -> Result<LoadedBoard, String> {
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

    let objective_hex = match (def.objective_col, def.objective_row) {
        (Some(col), Some(row)) => Some(Hex::from_offset(col, row)),
        _ => None,
    };

    Ok(LoadedBoard {
        board,
        objective_hex,
        max_turns: def.max_turns,
    })
}

/// Read and parse a TOML units file into a `UnitsDef` (units + triggers).
///
/// Call this once and extract `.units` / `.triggers` to avoid reading the file twice.
pub fn load_units_file(path: &Path) -> Result<UnitsDef, String> {
    let text = std::fs::read_to_string(path)
        .map_err(|e| format!("load_units_file: cannot read {:?}: {}", path, e))?;
    let def: UnitsDef = toml::from_str(&text)
        .map_err(|e| format!("load_units_file: parse error in {:?}: {}", path, e))?;
    Ok(def)
}

/// Load unit placements from a TOML units file.
///
/// The file must contain one or more `[[units]]` entries, each with
/// `id`, `unit_type`, `faction`, `col`, `row` fields.
/// Returns Err if the file cannot be read or parsed.
pub fn load_units(path: &Path) -> Result<Vec<UnitPlacement>, String> {
    load_units_file(path).map(|def| def.units)
}

/// Load trigger zone definitions from a TOML units file.
///
/// Parses the same file as `load_units()` but extracts the optional `[[triggers]]`
/// section. Returns an empty vec if no triggers are defined.
pub fn load_triggers(path: &Path) -> Result<Vec<TriggerDef>, String> {
    load_units_file(path).map(|def| def.triggers)
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
