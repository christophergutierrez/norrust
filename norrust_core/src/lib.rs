//! The Clash for Norrust — headless simulation core.
//! Provides hex grid, combat, pathfinding, AI, and data loading for the game engine.

pub mod ai;
pub mod board;
pub mod campaign;
pub mod combat;
pub mod dialogue;
pub mod events;
pub mod ffi;
pub mod game_state;
pub mod hex;
pub mod loader;
pub mod mapgen;
pub mod pathfinding;
pub mod recruitment;
pub mod routine;
pub mod routine_decision;
pub mod routine_independent;
pub mod save;
pub mod scenario;
pub mod schema;
pub mod selector;
pub mod snapshot;
pub mod tactics;
pub mod unit;
pub mod visibility;
