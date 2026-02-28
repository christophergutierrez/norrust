pub mod board;
pub mod combat;
pub mod game_state;
pub mod gdext_node;
pub mod hex;
pub mod loader;
pub mod pathfinding;
pub mod schema;
pub mod unit;

/// Primary game state — populated in Phase 2: The Headless Core.
#[derive(Debug, Default)]
pub struct GameState {}
