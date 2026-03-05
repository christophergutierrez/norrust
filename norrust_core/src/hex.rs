//! Hex grid coordinate system using cubic coordinates with axial storage.

use std::ops::{Add, Sub};

/// Cubic hex coordinate where x + y + z == 0 always holds.
///
/// Cubic coordinates are superior to offset coordinates for distance
/// calculation, neighbor lookup, and pathfinding. Offset coordinates
/// (used by map layouts and Wesnoth-compatible assets) are derived via
/// `to_offset()` / `from_offset()`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct Hex {
    pub x: i32,
    pub y: i32,
    pub z: i32,
}

/// The 6 unit-step directions in cubic hex space.
const DIRECTIONS: [Hex; 6] = [
    Hex { x: 1, y: -1, z: 0 },
    Hex { x: 1, y: 0, z: -1 },
    Hex { x: 0, y: 1, z: -1 },
    Hex { x: -1, y: 1, z: 0 },
    Hex { x: -1, y: 0, z: 1 },
    Hex { x: 0, y: -1, z: 1 },
];

impl Add for Hex {
    type Output = Hex;
    fn add(self, other: Hex) -> Hex {
        Hex {
            x: self.x + other.x,
            y: self.y + other.y,
            z: self.z + other.z,
        }
    }
}

impl Sub for Hex {
    type Output = Hex;
    fn sub(self, other: Hex) -> Hex {
        Hex {
            x: self.x - other.x,
            y: self.y - other.y,
            z: self.z - other.z,
        }
    }
}

impl Hex {
    /// Construct a Hex from cubic coordinates.
    /// In debug builds, panics if x + y + z != 0.
    pub fn new(x: i32, y: i32, z: i32) -> Self {
        debug_assert_eq!(x + y + z, 0, "cubic invariant violated: x+y+z must be 0");
        Self { x, y, z }
    }

    /// The origin hex (0, 0, 0).
    pub const ORIGIN: Hex = Hex { x: 0, y: 0, z: 0 };

    /// Manhattan distance between two hexes in cubic space.
    pub fn distance(self, other: Hex) -> u32 {
        ((self.x - other.x).abs() + (self.y - other.y).abs() + (self.z - other.z).abs()) as u32
            / 2
    }

    /// The 6 hexes adjacent to this one, in direction order.
    pub fn neighbors(self) -> [Hex; 6] {
        DIRECTIONS.map(|d| self + d)
    }

    /// Convert to odd-r offset coordinates (pointy-top, Wesnoth-compatible).
    ///
    /// Returns `(col, row)` where col is the column and row is the row.
    pub fn to_offset(self) -> (i32, i32) {
        let col = self.x + (self.z - (self.z & 1)) / 2;
        let row = self.z;
        (col, row)
    }

    /// Construct a Hex from odd-r offset coordinates (pointy-top).
    pub fn from_offset(col: i32, row: i32) -> Hex {
        let x = col - (row - (row & 1)) / 2;
        let z = row;
        let y = -x - z;
        Hex::new(x, y, z)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_distance_two() {
        let a = Hex::new(0, 0, 0);
        let b = Hex::new(2, -1, -1);
        assert_eq!(a.distance(b), 2);
    }

    #[test]
    fn test_distance_zero() {
        let a = Hex::new(1, -1, 0);
        assert_eq!(a.distance(a), 0);
    }

    #[test]
    fn test_distance_symmetric() {
        let a = Hex::new(0, 0, 0);
        let b = Hex::new(3, -2, -1);
        assert_eq!(a.distance(b), b.distance(a));
    }

    #[test]
    fn test_neighbors_count_and_invariant() {
        let center = Hex::ORIGIN;
        let neighbors = center.neighbors();
        assert_eq!(neighbors.len(), 6);
        for n in &neighbors {
            assert_eq!(n.x + n.y + n.z, 0, "neighbor {:?} violates cubic invariant", n);
            assert_eq!(center.distance(*n), 1, "neighbor {:?} is not 1 step away", n);
        }
    }

    #[test]
    fn test_neighbors_are_distinct() {
        let neighbors = Hex::ORIGIN.neighbors();
        for i in 0..6 {
            for j in (i + 1)..6 {
                assert_ne!(neighbors[i], neighbors[j], "duplicate neighbors at {} and {}", i, j);
            }
        }
    }

    #[test]
    fn test_offset_roundtrip() {
        // Test lossless roundtrip for an 11×11 neighborhood of the origin
        for x in -5..=5_i32 {
            for z in -5..=5_i32 {
                let y = -x - z;
                let hex = Hex::new(x, y, z);
                let (col, row) = hex.to_offset();
                let recovered = Hex::from_offset(col, row);
                assert_eq!(hex, recovered, "roundtrip failed for {:?} → ({},{}) → {:?}", hex, col, row, recovered);
            }
        }
    }

    #[test]
    fn test_add_subtract_inverse() {
        let start = Hex::new(1, -1, 0);
        for dir in Hex::ORIGIN.neighbors() {
            let moved = start + dir;
            let back = moved - dir;
            assert_eq!(back, start, "add/subtract not inverse for direction {:?}", dir);
        }
    }
}
