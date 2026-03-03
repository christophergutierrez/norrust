pub mod ai;
pub mod board;
pub mod combat;
pub mod ffi;
pub mod game_state;
pub mod gdext_node;
pub mod hex;
pub mod loader;
pub mod mapgen;
pub mod pathfinding;
pub mod scenario;
pub mod schema;
pub mod snapshot;
pub mod unit;

/// Primary game state — populated in Phase 2: The Headless Core.
#[derive(Debug, Default)]
pub struct GameState {}
