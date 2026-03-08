//! The Clash for Norrust — headless simulation core.
//! Provides hex grid, combat, pathfinding, AI, and data loading for the game engine.

pub mod ai;
pub mod board;
pub mod campaign;
pub mod combat;
pub mod dialogue;
pub mod ffi;
pub mod game_state;
pub mod hex;
pub mod loader;
pub mod mapgen;
pub mod pathfinding;
pub mod scenario;
pub mod schema;
pub mod snapshot;
pub mod unit;