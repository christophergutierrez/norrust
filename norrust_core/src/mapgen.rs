use crate::board::Board;
use crate::hex::Hex;

/// Generate a procedural terrain layout for `board` using `seed`.
///
/// Layout rules:
///   - Outer 2 columns (spawn zones): always "flat"
///   - Structural village positions: (cols/3, rows/2) and (cols*2/3, rows/2)
///   - Contested zone (remaining hexes): noise-based flat/forest/hills/mountains
///     where mountains are confined to the innermost columns
///
/// Uses `Board::set_terrain()` (string IDs only). The caller is responsible for
/// upgrading tiles to `Tile::from_def()` if a TerrainDef registry is available.
pub fn generate_map(board: &mut Board, seed: u64) {
    let cols = board.width as i32;
    let rows = board.height as i32;

    // Structural village positions: 1/3 and 2/3 across, middle row
    let mid_row = rows / 2;
    let v1_col = cols / 3;
    let v2_col = (cols * 2) / 3;

    for col in 0..cols {
        for row in 0..rows {
            let hex = Hex::from_offset(col, row);

            // Village positions take priority
            if (col == v1_col && row == mid_row) || (col == v2_col && row == mid_row) {
                board.set_terrain(hex, "village");
                continue;
            }

            // Spawn zones (outer 2 cols): always flat
            if col < 2 || col >= cols - 2 {
                board.set_terrain(hex, "flat");
                continue;
            }

            // Contested zone: noise-based terrain
            let n = terrain_noise(col, row, seed);
            let center_col = cols / 2;
            let dist_center = (col - center_col).abs();
            let terrain = contested_terrain(n, dist_center);
            board.set_terrain(hex, terrain);
        }
    }
}

/// Deterministic hash producing a value 0..=255 for a hex position and seed.
fn terrain_noise(col: i32, row: i32, seed: u64) -> u8 {
    let h = (col as u64)
        .wrapping_mul(2654435761)
        .wrapping_add((row as u64).wrapping_mul(2246822519))
        .wrapping_add(seed);
    ((h ^ (h >> 16)) & 0xFF) as u8
}

/// Map a noise value to a terrain ID for the contested zone.
/// Mountains only appear in the innermost columns (dist_center <= 1).
fn contested_terrain(n: u8, dist_center: i32) -> &'static str {
    match n {
        0..=109  => "flat",      // ~43% flat
        110..=164 => "forest",   // ~21% forest
        165..=219 => "hills",    // ~21% hills
        _ => {
            // ~15% — mountains only at center, hills elsewhere
            if dist_center <= 1 { "mountains" } else { "hills" }
        }
    }
}
