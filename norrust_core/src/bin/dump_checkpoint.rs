//! Read-only checkpoint renderer.
//!
//! `greedy_driver`'s checkpoints hold an opaque `SaveState` plus a reference
//! to the scenario board; rebuilding it into the renderer's full state shape
//! (movement, attacks, resistances -- everything that comes from the unit
//! registry rather than the save) requires the same registries the driver
//! itself loads. `tools/game_history.py` has no engine-independent way to do
//! that, so a checkpoint-only snapshot in a recorded game could not be
//! replayed even though the checkpoint proves the game reached that state.
//!
//! This binary closes that gap without resuming the game: it loads a
//! checkpoint plus the current unit/terrain registries, restores the engine
//! state, and prints the renderer-shaped state JSON (the same shape as the
//! driver's own `type:"state"` lines, via `norrust_core::snapshot::StateSnapshot`)
//! to stdout, then exits.
//!
//! It deliberately does the least possible with the restored state: no
//! gameplay loop, no action application, no turn advance, and no Greedy.
//! Resuming a checkpoint through the driver is avoided elsewhere in this
//! project precisely because resume can immediately execute a Greedy turn,
//! which would silently replay history rather than show it; this tool never
//! reaches that code path at all.
//!
//! Usage: dump_checkpoint CHECKPOINT_PATH

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use norrust_core::loader::Registry;
use norrust_core::save::SaveState;
use norrust_core::schema::{TerrainDef, UnitDef};
use norrust_core::snapshot::StateSnapshot;
use serde::Deserialize;
use serde_json::Value;
use sha2::{Digest, Sha256};

/// Only the fields needed to restore and verify a checkpoint. Deliberately a
/// separate, minimal type rather than sharing `greedy_driver`'s private
/// `DriverCheckpoint` struct across a binary boundary; both must agree with
/// the on-disk shape `greedy_driver::write_checkpoint` produces.
#[derive(Debug, Deserialize)]
struct CheckpointEnvelope {
    version: u32,
    save_state: SaveState,
    board_path: String,
    board_sha256: String,
}

fn checkpoint_digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn root() -> PathBuf {
    // Test-only escape hatch (debug builds only), mirroring the same knob in
    // greedy_driver.rs: lets an integration test point this tool's registry
    // loading at a fixture data tree instead of the real repository data.
    if cfg!(debug_assertions) {
        if let Ok(test_root) = env::var("NORRUST_TEST_ROOT_DIR") {
            return PathBuf::from(test_root);
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn dump(path: &Path) -> Result<Value, String> {
    let bytes = fs::read(path).map_err(|e| format!("read checkpoint: {e}"))?;
    let expected = checkpoint_digest(&bytes);
    let filename = path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or("invalid checkpoint filename")?;
    let actual = filename
        .strip_suffix(".json")
        .and_then(|name| name.rsplit('-').next())
        .ok_or("invalid checkpoint filename")?;
    if actual != expected {
        return Err("checkpoint digest mismatch".into());
    }
    let checkpoint: CheckpointEnvelope =
        serde_json::from_slice(&bytes).map_err(|e| format!("decode checkpoint: {e}"))?;
    if checkpoint.version != 1 {
        return Err("unsupported checkpoint version".into());
    }
    // Historical resources are honored as recorded, not silently replaced
    // with today's data. A checkpoint whose board no longer exists or no
    // longer matches its recorded digest is a real gap, not a state to
    // approximate from the current scenario file.
    let board_bytes = fs::read(&checkpoint.board_path)
        .map_err(|e| format!("checkpoint board is unavailable: {e}"))?;
    if checkpoint_digest(&board_bytes) != checkpoint.board_sha256 {
        return Err("checkpoint board no longer matches its recorded digest".into());
    }
    let data = root().join("data");
    let units: Registry<UnitDef> = Registry::load_from_dir(&data.join("units"))
        .map_err(|e| format!("load units: {e}"))?;
    let terrain: Registry<TerrainDef> = Registry::load_from_dir(&data.join("terrain"))
        .map_err(|e| format!("load terrain: {e}"))?;
    let state = SaveState::restore_game_state(&checkpoint.save_state, &units, &terrain)
        .map_err(|message| format!("restore checkpoint state: {message}"))?;
    serde_json::to_value(StateSnapshot::from_game_state(&state))
        .map_err(|e| format!("encode state: {e}"))
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.len() != 1 || args[0] == "-h" || args[0] == "--help" {
        eprintln!(
            "Usage: dump_checkpoint CHECKPOINT_PATH\n\n\
             Read-only: loads a driver checkpoint plus the current unit/terrain\n\
             registries, restores the engine state, and prints its renderer-shaped\n\
             state JSON to stdout. Never runs a gameplay loop, applies an action,\n\
             advances a turn, or executes Greedy."
        );
        std::process::exit(2);
    }
    match dump(Path::new(&args[0])) {
        Ok(value) => println!("{value}"),
        Err(message) => {
            eprintln!("{}", serde_json::json!({"error": message}));
            std::process::exit(1);
        }
    }
}
