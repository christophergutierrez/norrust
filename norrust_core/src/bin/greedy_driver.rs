//! Headless turn-by-turn driver for LLM vs Greedy.
//!
//! JSON line protocol:
//! - Driver prints current game state.
//! - Controller sends one action: {"action":"Move","unit_id":1,"col":4,"row":7}
//! - Driver applies, runs greedy opponent, prints new state and return code.
//!
//! Example:
//! cargo build --bin greedy_driver
//! target/debug/greedy_driver --scenario big_battle_6 \
//!   --faction0 undead --faction1 undead --gold 300 --seed 42

use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::env;
use std::fs::{self, OpenOptions};
use std::io::{self, BufRead, Read, Write};
#[cfg(unix)]
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant};

use norrust_core::ai::{ai_take_turn_greedy_actions, run_greedy_side_turn, GreedyTurnError};
use norrust_core::board::Tile;
use norrust_core::combat::{
    combat_parameters, exact_damage_sequence, exact_exchange, preview_combat, tod_label,
    validate_combat_preview, CombatParameters,
};
use norrust_core::events::GameEvent;
use norrust_core::game_state::{
    apply_action, apply_advance, apply_recruit, recruit_from_def, Action, AdvanceTarget, GameState,
    PendingSpawn, TriggerZone,
};
use norrust_core::game_state::{legal_moves, legal_targets};
use norrust_core::hex::Hex;
use norrust_core::loader::{expand_recruits, Registry};
use norrust_core::pathfinding::{get_zoc_hexes, reachable_hexes};
use norrust_core::save::SaveState;
use norrust_core::scenario::{load_board, load_units_file};
use norrust_core::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use norrust_core::tactics::{
    economy_facts, force_summaries, hex_inspection, recruiter_threats_after_end_turn,
    target_inspection, turn_tactics, unit_destination_threats, unit_tactics,
    unit_threats_after_end_turn, ThreatSurface, UnitThreatSurface,
};
use norrust_core::unit::Unit;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Clone)]
struct Config {
    scenario: String,
    faction0: String,
    faction1: String,
    gold: u32,
    seed: u64,
    scripted: bool,
    llm_side: u8,
    max_turns: u32,
    turn_timeout: u64,
    query_timeout: u64,
    max_queries: u32,
    disable_recruit_batch: bool,
    incremental_turns: bool,
    checkpoint_dir: Option<PathBuf>,
    resume_checkpoint: Option<PathBuf>,
}

#[derive(Clone)]
struct Faction {
    def: FactionDef,
    recruits: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct DriverCheckpoint {
    version: u32,
    save_state: SaveState,
    side_turns: u32,
    next_id: u32,
    boundary: String,
    pending_opponent_turn: bool,
    scenario: String,
    faction0: String,
    faction1: String,
    llm_side: u8,
    starting_gold: u32,
    seed: u64,
    max_turns: u32,
    disable_recruit_batch: bool,
    #[serde(default)]
    incremental_turns: bool,
    board_path: String,
    board_sha256: String,
}

fn checkpoint_digest(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path.parent().ok_or("checkpoint has no parent")?;
    fs::create_dir_all(parent).map_err(|e| format!("create checkpoint directory: {e}"))?;
    let temp = parent.join(format!(".{}.tmp", std::process::id()));
    let mut options = OpenOptions::new();
    options.create(true).write(true).truncate(true);
    #[cfg(unix)]
    options.mode(0o600);
    let mut file = options
        .open(&temp)
        .map_err(|e| format!("open checkpoint temp: {e}"))?;
    file.write_all(bytes)
        .map_err(|e| format!("write checkpoint: {e}"))?;
    file.sync_all()
        .map_err(|e| format!("sync checkpoint: {e}"))?;
    drop(file);
    fs::rename(&temp, path).map_err(|e| format!("publish checkpoint: {e}"))?;
    let dir = OpenOptions::new()
        .read(true)
        .open(parent)
        .map_err(|e| format!("open checkpoint directory: {e}"))?;
    dir.sync_all()
        .map_err(|e| format!("sync checkpoint directory: {e}"))?;
    Ok(())
}

fn write_checkpoint(
    c: &Config,
    state: &GameState,
    side_turns: u32,
    next_id: u32,
    boundary: &str,
    pending_opponent_turn: bool,
) -> Result<Option<Value>, String> {
    let Some(dir) = c.checkpoint_dir.as_ref() else {
        return Ok(None);
    };
    let board_path = root()
        .join("scenarios")
        .join(&c.scenario)
        .join("board.toml");
    let board_bytes =
        fs::read(&board_path).map_err(|e| format!("read board for checkpoint: {e}"))?;
    let checkpoint = DriverCheckpoint {
        version: 1,
        save_state: SaveState::build(state, &board_path.to_string_lossy(), None, None, None, None),
        side_turns,
        next_id,
        boundary: boundary.to_string(),
        pending_opponent_turn,
        scenario: c.scenario.clone(),
        faction0: c.faction0.clone(),
        faction1: c.faction1.clone(),
        llm_side: c.llm_side,
        starting_gold: c.gold,
        seed: c.seed,
        max_turns: c.max_turns,
        disable_recruit_batch: c.disable_recruit_batch,
        incremental_turns: c.incremental_turns,
        board_path: board_path.to_string_lossy().into_owned(),
        board_sha256: checkpoint_digest(&board_bytes),
    };
    let bytes = serde_json::to_vec(&checkpoint).map_err(|e| format!("encode checkpoint: {e}"))?;
    let digest = checkpoint_digest(&bytes);
    let filename = format!(
        "{}-{}-{}-{}.json",
        side_turns, state.state_revision, boundary, digest
    );
    let path = dir.join(&filename);
    atomic_write(&path, &bytes)?;
    Ok(Some(json!({"type":"checkpoint", "path":filename,
        "digest":digest, "state_revision":state.state_revision, "side_turns":side_turns,
        "boundary":boundary, "pending_opponent_turn":pending_opponent_turn})))
}

fn read_checkpoint(path: &Path) -> Result<DriverCheckpoint, String> {
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
    let checkpoint: DriverCheckpoint =
        serde_json::from_slice(&bytes).map_err(|e| format!("decode checkpoint: {e}"))?;
    if checkpoint.version != 1 {
        return Err("unsupported checkpoint version".into());
    }
    Ok(checkpoint)
}

fn usage() -> ! {
    eprintln!(
        "Usage: greedy_driver --scenario NAME --faction0 ID --faction1 ID [options]

Options:
  --scenario NAME       Scenario directory name (default: big_battle_6)
  --faction0 ID         Faction for side 0 (default: undead)
  --faction1 ID         Faction for side 1 (default: undead)
  --gold N              Starting gold for both factions (default: 300)
  --seed N              Deterministic seed (default: 42)
  --llm-side 0|1        Side controlled by stdin (default: 0)
  --max-turns N         Side-turn safety cap (default: 200)
  --turn-timeout N      Model stdin wall-clock budget in seconds (default: 300)
  --query-budget-seconds N  Query servicing budget per model turn (default: 300)
  --max-queries-per-turn N  Query cap (default: 256)
  --disable-recruit-batch  Reject the model-only RecruitBatch macro
  --incremental-turns    Allow up to three partial model batches before EndTurn
  --checkpoint-dir DIR     Atomically write resumable checkpoints here
  --resume-checkpoint PATH Restore a driver checkpoint instead of starting a game
  --scripted            Run full game unattended with greedy-vs-greedy (for testing)
  -h, --help            Show this help"
    );
    std::process::exit(2)
}

fn parse_args() -> Config {
    let mut c = Config {
        scenario: "big_battle_6".into(),
        faction0: "undead".into(),
        faction1: "undead".into(),
        gold: 300,
        seed: 42,
        scripted: false,
        llm_side: 0,
        max_turns: 200,
        turn_timeout: 300,
        query_timeout: 300,
        max_queries: 256,
        disable_recruit_batch: false,
        incremental_turns: false,
        checkpoint_dir: None,
        resume_checkpoint: None,
    };
    let args: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        let key = &args[i];
        if key == "-h" || key == "--help" {
            usage();
        }
        if key == "--scripted" {
            c.scripted = true;
            i += 1;
            continue;
        }
        if key == "--disable-recruit-batch" {
            c.disable_recruit_batch = true;
            i += 1;
            continue;
        }
        if key == "--incremental-turns" {
            c.incremental_turns = true;
            i += 1;
            continue;
        }
        if i + 1 >= args.len() {
            usage();
        }
        let value = &args[i + 1];
        match key.as_str() {
            "--scenario" => c.scenario = value.clone(),
            "--faction0" => c.faction0 = value.clone(),
            "--faction1" => c.faction1 = value.clone(),
            "--gold" => c.gold = value.parse().unwrap_or_else(|_| usage()),
            "--seed" => c.seed = value.parse().unwrap_or_else(|_| usage()),
            "--llm-side" => c.llm_side = value.parse().unwrap_or_else(|_| usage()),
            "--max-turns" => c.max_turns = value.parse().unwrap_or_else(|_| usage()),
            "--turn-timeout" => c.turn_timeout = value.parse().unwrap_or_else(|_| usage()),
            "--query-budget-seconds" => c.query_timeout = value.parse().unwrap_or_else(|_| usage()),
            "--max-queries-per-turn" => c.max_queries = value.parse().unwrap_or_else(|_| usage()),
            "--checkpoint-dir" => c.checkpoint_dir = Some(PathBuf::from(value)),
            "--resume-checkpoint" => c.resume_checkpoint = Some(PathBuf::from(value)),
            _ => usage(),
        }
        i += 2;
    }
    c
}

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn load_factions(data: &Path) -> Result<Vec<Faction>, String> {
    let groups: Registry<RecruitGroup> = Registry::load_from_dir(&data.join("recruit_groups"))
        .map_err(|e| format!("load recruit groups: {}", e))?;
    let registry: Registry<FactionDef> = Registry::load_from_dir(&data.join("factions"))
        .map_err(|e| format!("load factions: {}", e))?;
    Ok(registry
        .all()
        .map(|def| {
            let recruits = expand_recruits(def, &groups);
            Faction {
                def: def.clone(),
                recruits,
            }
        })
        .collect())
}

fn upgrade_tiles(state: &mut GameState, terrain: &Registry<TerrainDef>) {
    for col in 0..state.board.width as i32 {
        for row in 0..state.board.height as i32 {
            let h = Hex::from_offset(col, row);
            if let Some(id) = state.board.terrain_at(h).map(str::to_string) {
                if let Some(def) = terrain.get(&id) {
                    state.board.set_tile(h, Tile::from_def(def));
                }
            }
        }
    }
}

fn keep_for(state: &GameState, side: u8) -> Option<Hex> {
    let mut keeps: Vec<Hex> = (0..state.board.width as i32)
        .flat_map(|c| (0..state.board.height as i32).map(move |r| Hex::from_offset(c, r)))
        .filter(|h| {
            state
                .board
                .tile_at(*h)
                .map(|t| t.terrain_id == "keep")
                .unwrap_or(false)
        })
        .collect();
    keeps.sort_by_key(|h| h.x);
    if side == 0 {
        keeps.first().copied()
    } else {
        keeps.last().copied()
    }
}

/// Place recruits for `side`, handling the castle-ring vacate-and-continue cycle.
///
/// `want`: unit def to recruit. `None` = pick the first affordable faction recruit
/// (the opponent's autonomous behavior). `Some(id)` = the caller chose the type.
/// `limit`: stop after this many placements. `None` = recruit until gold or space runs out.
///
/// Placement is mechanical only: it never chooses *what* or *how many* when the
/// caller has specified them, so an LLM using it still makes every strategic choice.
fn recruit_internal(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
    want: Option<&str>,
    limit: Option<u32>,
    mut recorded: Option<&mut Vec<GameEvent>>,
) -> u32 {
    let mut recruited = 0;
    loop {
        if limit.is_some_and(|l| recruited >= l) {
            break;
        }
        let mut keep_candidates: Vec<(i32, i32, u32, Hex)> = state
            .positions
            .iter()
            .filter_map(|(&id, &h)| {
                let u = state.units.get(&id)?;
                (u.faction == side
                    && u.can_recruit
                    && state
                        .board
                        .tile_at(h)
                        .is_some_and(|tile| tile.terrain_id == "keep"))
                .then(|| {
                    let (col, row) = h.to_offset();
                    (row, col, id, h)
                })
            })
            .collect();
        keep_candidates.sort_unstable_by_key(|candidate| (candidate.0, candidate.1, candidate.2));
        let keep = keep_candidates.first().map(|candidate| candidate.3);
        let Some(keep) = keep else { break };
        let mut dest = keep.neighbors().iter().copied().find(|h| {
            state
                .board
                .tile_at(*h)
                .map(|t| t.terrain_id == "castle")
                .unwrap_or(false)
                && !state.hex_to_unit.contains_key(h)
        });
        if dest.is_none() {
            let occupied_castle = keep.neighbors().iter().copied().find(|h| {
                let Some(id) = state.hex_to_unit.get(h) else {
                    return false;
                };
                state
                    .units
                    .get(id)
                    .map(|u| u.faction == side && !u.moved && !u.can_recruit)
                    .unwrap_or(false)
            });
            let Some(castle) = occupied_castle else { break };
            let id = state.hex_to_unit[&castle];
            let unit = state.units[&id].clone();
            let occupied: HashSet<Hex> = state.hex_to_unit.keys().copied().collect();
            let zoc = get_zoc_hexes(state, side);
            let movement = if unit.slowed {
                unit.movement / 2
            } else {
                unit.movement
            };
            let mut move_destinations: Vec<Hex> = reachable_hexes(
                &state.board,
                &unit.movement_costs,
                1,
                castle,
                movement,
                &zoc,
                false,
            )
            .into_iter()
            .filter(|h| *h != castle && !occupied.contains(h))
            .collect();
            move_destinations.sort_unstable_by_key(|h| {
                let remains_on_castle = state
                    .board
                    .tile_at(*h)
                    .is_some_and(|tile| tile.terrain_id == "castle");
                let nearest_enemy = state
                    .units
                    .iter()
                    .filter(|(_, enemy)| enemy.faction != side)
                    .filter_map(|(enemy_id, _)| state.positions.get(enemy_id))
                    .map(|enemy_hex| h.distance(*enemy_hex))
                    .min()
                    .unwrap_or(u32::MAX);
                (remains_on_castle, nearest_enemy, *h)
            });
            let Some(move_dest) = move_destinations.first().copied() else {
                break;
            };
            let move_events = apply_action(
                state,
                Action::Move {
                    unit_id: id,
                    destination: move_dest,
                },
            );
            match move_events {
                Ok(move_events) => {
                    if let Some(events) = recorded.as_deref_mut() {
                        for event in move_events {
                            match event {
                                GameEvent::Move { unit, from, to } => {
                                    events.push(GameEvent::Vacate { unit, from, to });
                                }
                                other => events.push(other),
                            }
                        }
                    }
                }
                Err(_) => break,
            }
            dest = Some(castle);
        }
        let dest = dest.expect("recruitment destination must exist");
        let def = match want {
            // Caller chose the type: recruit exactly that, or stop if unaffordable/unknown.
            Some(did) => match units.get(did) {
                Some(d) if state.gold[side as usize] >= d.cost => d,
                _ => break,
            },
            // No preference: first affordable recruit in the faction list.
            None => match faction
                .recruits
                .iter()
                .filter_map(|id| units.get(id))
                .find(|d| state.gold[side as usize] >= d.cost)
            {
                Some(d) => d,
                None => break,
            },
        };
        let cost = def.cost;
        match apply_recruit(state, Unit::from_def(*next_id, def, side), dest, cost) {
            Ok(events) => {
                if let Some(recorded) = recorded.as_deref_mut() {
                    recorded.extend(events);
                }
            }
            Err(_) => break,
        }
        *next_id += 1;
        recruited += 1;
    }
    recruited
}

#[allow(dead_code)]
fn recruit(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
    want: Option<&str>,
    limit: Option<u32>,
) -> u32 {
    recruit_internal(state, side, faction, units, next_id, want, limit, None)
}

fn recruit_with_events(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
    want: Option<&str>,
    limit: Option<u32>,
    events: &mut Vec<GameEvent>,
) -> u32 {
    recruit_internal(
        state,
        side,
        faction,
        units,
        next_id,
        want,
        limit,
        Some(events),
    )
}

fn recruit_batch_with_events(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
    def_id: &str,
    count: u32,
    events: &mut Vec<GameEvent>,
) -> Result<u32, norrust_core::game_state::ActionError> {
    if !faction.recruits.iter().any(|id| id == def_id) {
        return Err(norrust_core::game_state::ActionError::NotInRecruitList);
    }
    let def = units
        .get(def_id)
        .ok_or(norrust_core::game_state::ActionError::NotInRecruitList)?;
    let mut recruited = 0;
    for _ in 0..count {
        let mut working = state.clone();
        let mut candidate_id = *next_id;
        let mut attempt_events = Vec::new();
        let attempt = recruit_with_events(
            &mut working,
            side,
            faction,
            units,
            &mut candidate_id,
            Some(def_id),
            Some(1),
            &mut attempt_events,
        );
        if attempt != 1 {
            break;
        }
        *state = working;
        *next_id = candidate_id;
        events.extend(attempt_events);
        recruited += 1;
    }
    if recruited > 0 {
        return Ok(recruited);
    }
    if state.gold[side as usize] < def.cost {
        Err(norrust_core::game_state::ActionError::NotEnoughGold)
    } else if !state.units.values().any(|unit| {
        unit.faction == side
            && unit.can_recruit
            && state.positions.get(&unit.id).is_some_and(|hex| {
                state
                    .board
                    .tile_at(*hex)
                    .is_some_and(|tile| tile.terrain_id == "keep")
            })
    }) {
        Err(norrust_core::game_state::ActionError::LeaderNotOnKeep)
    } else {
        Err(norrust_core::game_state::ActionError::DestinationOccupied)
    }
}

fn run_driver_greedy_turn(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
) -> Result<Vec<GameEvent>, GreedyTurnError> {
    // Test-only failure injection; release builds must never activate it.
    let injected_failure = if cfg!(debug_assertions) {
        env::var("NORRUST_TEST_GREEDY_FAILURE").ok()
    } else {
        None
    };
    run_driver_greedy_turn_with_failure(
        state,
        side,
        faction,
        units,
        next_id,
        injected_failure.as_deref(),
    )
}

fn run_driver_greedy_turn_with_failure(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
    injected_failure: Option<&str>,
) -> Result<Vec<GameEvent>, GreedyTurnError> {
    let mut candidate_id = *next_id;
    let mut recruitment_events = Vec::new();
    let events = run_greedy_side_turn(
        state,
        |working| {
            if injected_failure.as_deref() == Some("prepare") {
                return Err(GreedyTurnError::Callback(
                    "test-injected greedy prepare failure".into(),
                ));
            }
            recruit_with_events(
                working,
                side,
                faction,
                units,
                &mut candidate_id,
                None,
                None,
                &mut recruitment_events,
            );
            Ok(std::mem::take(&mut recruitment_events))
        },
        |working| {
            if injected_failure.as_deref() == Some("planner") {
                return Err(GreedyTurnError::Callback(
                    "test-injected greedy planner failure".into(),
                ));
            }
            ai_take_turn_greedy_actions(working, side).map_err(Into::into)
        },
    )?;
    *next_id = candidate_id;
    Ok(events)
}

fn authorize_model_batch(
    orders: &[Value],
    state: &GameState,
    model_side: u8,
) -> Result<(), (&'static str, &'static str)> {
    if state.active_faction != model_side {
        return Err((
            "unauthorized_side",
            "model actions are not authorized while the opponent is active",
        ));
    }
    for order in orders {
        let actor_id = match order.get("action").and_then(Value::as_str) {
            Some("Move") | Some("Advance") => order.get("unit_id"),
            Some("Attack") => order.get("attacker_id"),
            _ => None,
        };
        let Some(actor_id) = actor_id.and_then(Value::as_u64) else {
            continue;
        };
        if state
            .units
            .get(&(actor_id as u32))
            .is_some_and(|unit| unit.faction != model_side)
        {
            return Err((
                "unauthorized_unit",
                "model actions may reference only model-side units",
            ));
        }
        if order.get("action").and_then(Value::as_str) == Some("Engage") {
            let Some(steps) = order.get("steps").and_then(Value::as_array) else {
                return Err(("parse", "Engage steps must be an array"));
            };
            for step in steps {
                let Some(attacker_id) = step.get("attacker_id").and_then(Value::as_u64) else {
                    return Err(("parse", "Engage step needs attacker_id"));
                };
                if state
                    .units
                    .get(&(attacker_id as u32))
                    .is_some_and(|unit| unit.faction != model_side)
                {
                    return Err((
                        "unauthorized_unit",
                        "model actions may reference only model-side units",
                    ));
                }
            }
        }
    }
    Ok(())
}

fn greedy_infrastructure_failure(state: &GameState, side_turns: u32) -> Value {
    json!({
        "type": "game_end",
        "reason": "infrastructure_failure",
        "code": "greedy_turn_failed",
        "message": "greedy opponent turn failed",
        "turns": state.turn,
        "side_turns": side_turns,
    })
}

fn game_state_to_json(state: &GameState, units: &Registry<UnitDef>) -> Value {
    let _ = units;
    serde_json::to_value(norrust_core::snapshot::StateSnapshot::from_game_state(
        state,
    ))
    .unwrap_or_else(|_| json!({}))
}

fn unit_type_profile(def: &UnitDef) -> Value {
    let mut resistances = serde_json::Map::new();
    let mut resistance_keys: Vec<_> = def.resistances.keys().collect();
    resistance_keys.sort();
    for key in resistance_keys {
        resistances.insert(key.clone(), json!(def.resistances[key]));
    }
    json!({
        "def_id": def.id,
        "name": def.name,
        "cost": def.cost,
        "max_hp": def.max_hp,
        "movement": def.movement,
        "alignment": def.alignment,
        "attacks": def.attacks.iter().map(|attack| json!({
            "name": attack.name,
            "damage": attack.damage,
            "strikes": attack.strikes,
            "type": attack.attack_type,
            "range": attack.range,
            "specials": attack.specials,
        })).collect::<Vec<_>>(),
        "resistances": Value::Object(resistances),
    })
}

fn valid_action_shape(order: &Value) -> bool {
    let Some(object) = order.as_object() else {
        return false;
    };
    let Some(action) = object.get("action").and_then(Value::as_str) else {
        return false;
    };
    let (allowed, required): (&[&str], &[&str]) = match action {
        "Move" => (
            &["action", "unit_id", "col", "row"],
            &["unit_id", "col", "row"],
        ),
        "Attack" => (
            &["action", "attacker_id", "defender_id"],
            &["attacker_id", "defender_id"],
        ),
        "Recruit" => (
            &["action", "def_id", "col", "row"],
            &["def_id", "col", "row"],
        ),
        "RecruitBatch" => (&["action", "def_id", "count"], &["def_id", "count"]),
        "Engage" => (&["action", "target_id", "steps"], &["target_id", "steps"]),
        "EndTurn" => (&["action"], &[]),
        "Advance" => (
            &["action", "unit_id", "target_index", "def_id"],
            &["unit_id"],
        ),
        _ => return false,
    };
    let integer = |value: &Value| {
        !value.is_boolean() && (value.as_i64().is_some() || value.as_u64().is_some())
    };
    let in_range = |field: &str, value: &Value| {
        if matches!(
            field,
            "unit_id" | "attacker_id" | "defender_id" | "target_index" | "count"
        ) {
            value
                .as_u64()
                .is_some_and(|number| number <= u32::MAX as u64)
        } else {
            value
                .as_i64()
                .is_some_and(|number| (i32::MIN as i64..=i32::MAX as i64).contains(&number))
        }
    };
    let strings = match action {
        "Recruit" | "RecruitBatch" => ["def_id"].as_slice(),
        "Advance" => {
            if object.contains_key("def_id") {
                &["def_id"][..]
            } else {
                &[][..]
            }
        }
        "Engage" => &[][..],
        _ => &[][..],
    };
    let integer_fields: &[&str] = match action {
        "Move" => &["unit_id", "col", "row"],
        "Attack" => &["attacker_id", "defender_id"],
        "Recruit" => &["col", "row"],
        "RecruitBatch" => &["count"],
        "Advance" => {
            if object.contains_key("target_index") {
                &["unit_id", "target_index"]
            } else {
                &["unit_id"]
            }
        }
        "Engage" => &[],
        _ => &[],
    };
    object.keys().all(|key| allowed.contains(&key.as_str()))
        && required.iter().all(|key| object.contains_key(*key))
        && (action != "Advance"
            || object.contains_key("target_index") != object.contains_key("def_id"))
        && integer_fields.iter().all(|field| {
            object
                .get(*field)
                .is_some_and(|value| integer(value) && in_range(field, value))
        })
        && strings
            .iter()
            .all(|field| object.get(*field).is_some_and(Value::is_string))
        && (action != "RecruitBatch"
            || object
                .get("count")
                .and_then(Value::as_u64)
                .is_some_and(|count| (1..=u32::MAX as u64).contains(&count)))
        && (action != "Engage"
            || object
                .get("target_id")
                .and_then(Value::as_u64)
                .is_some_and(|id| id <= u32::MAX as u64)
                && object
                    .get("steps")
                    .and_then(Value::as_array)
                    .is_some_and(|steps| {
                        !steps.is_empty()
                            && steps.len() <= 256
                            && steps.iter().all(|step| {
                                let Some(step) = step.as_object() else {
                                    return false;
                                };
                                let allowed = ["attacker_id", "col", "row"];
                                step.keys().all(|key| allowed.contains(&key.as_str()))
                                    && allowed.iter().all(|key| step.contains_key(*key))
                                    && step
                                        .get("attacker_id")
                                        .and_then(Value::as_u64)
                                        .is_some_and(|id| id <= u32::MAX as u64)
                                    && step.get("col").and_then(Value::as_i64).is_some_and(|col| {
                                        (i32::MIN as i64..=i32::MAX as i64).contains(&col)
                                    })
                                    && step.get("row").and_then(Value::as_i64).is_some_and(|row| {
                                        (i32::MIN as i64..=i32::MAX as i64).contains(&row)
                                    })
                            })
                    }))
}

fn validate_model_batch_contract(
    orders: &[Value],
    state: &GameState,
    model_side: u8,
) -> Result<(), (&'static str, &'static str)> {
    if orders.is_empty() {
        return Err(("parse", "orders must be a non-empty array"));
    }
    if orders.len() > 256 {
        return Err(("batch_too_large", "action batch exceeds 256 objects"));
    }
    if orders.iter().any(|order| !valid_action_shape(order)) {
        return Err(("parse", "invalid action shape"));
    }
    let end_turns = orders
        .iter()
        .filter(|order| order.get("action").and_then(Value::as_str) == Some("EndTurn"))
        .count();
    if end_turns != 1
        || orders
            .last()
            .and_then(|order| order.get("action"))
            .and_then(Value::as_str)
            != Some("EndTurn")
    {
        return Err(("parse", "invalid action batch structure"));
    }
    authorize_model_batch(orders, state, model_side)
}

struct BatchExecution {
    state: GameState,
    next_id: u32,
    results: Vec<Value>,
    events: Vec<GameEvent>,
    did_end: bool,
    forecasts: Vec<Value>,
    sequence_attacks: BTreeMap<u32, (u32, Vec<(u32, CombatParameters)>)>,
    attack_sequences: Vec<Value>,
    pre_end_threats: Option<ThreatSurface>,
    pre_end_exposure: Option<UnitThreatSurface>,
    preview_error: Option<Value>,
    post_combat_conditional: bool,
    conditional_unit_ids: HashSet<u32>,
    pre_end_recruitment_remaining: Option<bool>,
}

/// Apply one model batch to an isolated state. The commit path and the
/// read-only validation query deliberately share this executor so validation
/// cannot approve a batch with different sequential semantics.
fn execute_model_batch(
    mut state: GameState,
    mut next_id: u32,
    orders: &[Value],
    model_side: u8,
    factions: &[Faction; 2],
    units: &Registry<UnitDef>,
    disable_recruit_batch: bool,
    sample_attacks: bool,
) -> BatchExecution {
    let mut results = Vec::with_capacity(orders.len());
    let mut events = Vec::new();
    let mut did_end = false;
    let mut forecasts = Vec::new();
    let mut sequence_attacks = BTreeMap::<u32, (u32, Vec<(u32, CombatParameters)>)>::new();
    let mut pre_end_threats = None;
    let mut pre_end_exposure = None;
    let mut preview_error = None;
    let mut post_combat_conditional = false;
    let mut pre_end_recruitment_remaining = None;
    let mut conditional_ids = HashSet::new();
    for order in orders {
        let action_name = order.get("action").and_then(Value::as_str);
        let conditional_on_survival = !sample_attacks
            && ["unit_id", "attacker_id", "defender_id"]
                .iter()
                .filter_map(|field| order.get(*field).and_then(Value::as_u64))
                .any(|id| conditional_ids.contains(&(id as u32)));
        if did_end {
            results.push(json!({"ok":true,"code":"game_over","skipped":true}));
            continue;
        }
        if action_name == Some("RecruitBatch") && disable_recruit_batch {
            results.push(
                json!({"ok":false,"code":"macro_disabled","message":"RecruitBatch is disabled"}),
            );
            continue;
        }
        let mut conditional_action = conditional_on_survival;
        let mut conditional_steps = Vec::new();
        let result = match action_name {
            Some("Move") => match (
                order.get("unit_id").and_then(Value::as_u64),
                order.get("col").and_then(Value::as_i64),
                order.get("row").and_then(Value::as_i64),
            ) {
                (Some(id), Some(col), Some(row)) => apply_action(
                    &mut state,
                    Action::Move {
                        unit_id: id as u32,
                        destination: Hex::from_offset(col as i32, row as i32),
                    },
                ),
                _ => Err(norrust_core::game_state::ActionError::UnitNotFound(0)),
            },
            Some("Attack") => match (
                order.get("attacker_id").and_then(Value::as_u64),
                order.get("defender_id").and_then(Value::as_u64),
            ) {
                (Some(attacker), Some(defender)) if sample_attacks => apply_action(
                    &mut state,
                    Action::Attack {
                        attacker_id: attacker as u32,
                        defender_id: defender as u32,
                    },
                ),
                (Some(attacker), Some(defender)) => {
                    let attacker = attacker as u32;
                    let defender = defender as u32;
                    let validation = (|| {
                        let unit = state.units.get(&attacker).ok_or(
                            norrust_core::game_state::ActionError::UnitNotFound(attacker),
                        )?;
                        if unit.faction != state.active_faction {
                            return Err(norrust_core::game_state::ActionError::NotYourTurn);
                        }
                        if unit.attacked {
                            return Err(norrust_core::game_state::ActionError::UnitAlreadyAttacked);
                        }
                        let target = state.units.get(&defender).ok_or(
                            norrust_core::game_state::ActionError::UnitNotFound(defender),
                        )?;
                        if target.faction == unit.faction {
                            return Err(norrust_core::game_state::ActionError::FriendlyTarget);
                        }
                        let origin = *state.positions.get(&attacker).ok_or(
                            norrust_core::game_state::ActionError::UnitNotFound(attacker),
                        )?;
                        let parameters = combat_parameters(&state, attacker, defender, origin)
                            .map_err(|_| norrust_core::game_state::ActionError::NotAdjacent)?;
                        let forecast = exact_exchange(&parameters);
                        let target_hp = target.hp;
                        if forecast.outcome_bps[0] > 0 {
                            conditional_ids.insert(defender);
                            post_combat_conditional = true;
                        }
                        if forecast.outcome_bps[2] > 0 {
                            conditional_ids.insert(attacker);
                            post_combat_conditional = true;
                        }
                        state.units.get_mut(&attacker).unwrap().attacked = true;
                        forecasts.push(json!({"attacker_id":attacker,"defender_id":defender,"forecast":forecast,"sampled":false}));
                        sequence_attacks
                            .entry(defender)
                            .or_insert_with(|| (target_hp, Vec::new()))
                            .1
                            .push((attacker, parameters));
                        let parameters = sequence_attacks
                            .get(&defender)
                            .map(|(_, attacks)| {
                                attacks
                                    .iter()
                                    .map(|(_, parameters)| parameters.clone())
                                    .collect::<Vec<_>>()
                            })
                            .unwrap_or_default();
                        if exact_damage_sequence(target_hp, &parameters).kill_bps > 0 {
                            conditional_ids.insert(defender);
                            post_combat_conditional = true;
                        }
                        Ok(Vec::new())
                    })();
                    validation
                }
                _ => Err(norrust_core::game_state::ActionError::UnitNotFound(0)),
            },
            Some("Engage") => (|| {
                let target_id = order
                    .get("target_id")
                    .and_then(Value::as_u64)
                    .map(|id| id as u32)
                    .ok_or(norrust_core::game_state::ActionError::UnitNotFound(0));
                let steps = order.get("steps").and_then(Value::as_array);
                match (target_id, steps) {
                    (Ok(target_id), Some(steps)) => {
                        let mut produced = Vec::new();
                        for (step_index, step) in steps.iter().enumerate() {
                            if !state.units.contains_key(&target_id) {
                                break;
                            }
                            if !sample_attacks && conditional_ids.contains(&target_id) {
                                conditional_action = true;
                                conditional_steps.push(step_index);
                            }
                            let attacker_id = step
                                .get("attacker_id")
                                .and_then(Value::as_u64)
                                .map(|id| id as u32)
                                .ok_or(norrust_core::game_state::ActionError::UnitNotFound(0))?;
                            let destination = Hex::from_offset(
                                step.get("col").and_then(Value::as_i64).ok_or(
                                    norrust_core::game_state::ActionError::UnitNotFound(
                                        attacker_id,
                                    ),
                                )? as i32,
                                step.get("row").and_then(Value::as_i64).ok_or(
                                    norrust_core::game_state::ActionError::UnitNotFound(
                                        attacker_id,
                                    ),
                                )? as i32,
                            );
                            let current = state.positions.get(&attacker_id).copied().ok_or(
                                norrust_core::game_state::ActionError::UnitNotFound(attacker_id),
                            )?;
                            let mut sub_orders = Vec::with_capacity(2);
                            if current != destination {
                                sub_orders.push(json!({
                                    "action":"Move",
                                    "unit_id":attacker_id,
                                    "col":step.get("col").and_then(Value::as_i64).unwrap(),
                                    "row":step.get("row").and_then(Value::as_i64).unwrap()
                                }));
                            }
                            sub_orders.push(json!({
                                "action":"Attack",
                                "attacker_id":attacker_id,
                                "defender_id":target_id
                            }));
                            let sub = execute_model_batch(
                                state.clone(),
                                next_id,
                                &sub_orders,
                                model_side,
                                factions,
                                units,
                                disable_recruit_batch,
                                sample_attacks,
                            );
                            if !sub
                                .results
                                .iter()
                                .all(|result| result.get("ok") == Some(&Value::Bool(true)))
                            {
                                return Err(norrust_core::game_state::ActionError::UnitNotFound(
                                    attacker_id,
                                ));
                            }
                            state = sub.state;
                            next_id = sub.next_id;
                            produced.extend(sub.events);
                            forecasts.extend(sub.forecasts);
                            for (target, (hp, attacks)) in sub.sequence_attacks {
                                let entry =
                                    sequence_attacks.entry(target).or_insert((hp, Vec::new()));
                                entry.1.extend(attacks);
                            }
                            conditional_ids.extend(sub.conditional_unit_ids);
                            post_combat_conditional |= sub.post_combat_conditional;
                        }
                        Ok(produced)
                    }
                    _ => Err(norrust_core::game_state::ActionError::UnitNotFound(0)),
                }
            })(),
            Some("Recruit") => match (
                order.get("def_id").and_then(Value::as_str),
                order.get("col").and_then(Value::as_i64),
                order.get("row").and_then(Value::as_i64),
            ) {
                (Some(def_id), Some(col), Some(row)) => recruit_from_def(
                    &mut state,
                    model_side,
                    def_id,
                    Hex::from_offset(col as i32, row as i32),
                    &factions[model_side as usize].recruits,
                    units,
                    &mut next_id,
                ),
                _ => Err(norrust_core::game_state::ActionError::UnitNotFound(0)),
            },
            Some("RecruitBatch") => match (
                order.get("def_id").and_then(Value::as_str),
                order.get("count").and_then(Value::as_u64),
            ) {
                (Some(def_id), Some(count)) => match recruit_batch_with_events(
                    &mut state,
                    model_side,
                    &factions[model_side as usize],
                    units,
                    &mut next_id,
                    def_id,
                    count as u32,
                    &mut events,
                ) {
                    Ok(recruited) => {
                        results.push(json!({"ok":true,"requested":count,"recruited":recruited,"partial":(recruited as u64) < count}));
                        continue;
                    }
                    Err(error) => Err(error),
                },
                _ => Err(norrust_core::game_state::ActionError::UnitNotFound(0)),
            },
            Some("EndTurn") => {
                if !sample_attacks {
                    pre_end_recruitment_remaining = Some(if disable_recruit_batch {
                        let has_open_castle = state
                            .units
                            .iter()
                            .filter(|(_, unit)| unit.faction == model_side && unit.can_recruit)
                            .filter_map(|(id, _)| state.positions.get(id))
                            .filter(|hex| {
                                state
                                    .board
                                    .tile_at(**hex)
                                    .is_some_and(|tile| tile.terrain_id == "keep")
                            })
                            .flat_map(|hex| hex.neighbors())
                            .any(|hex| {
                                state
                                    .board
                                    .tile_at(hex)
                                    .is_some_and(|tile| tile.terrain_id == "castle")
                                    && !state.hex_to_unit.contains_key(&hex)
                            });
                        has_open_castle
                            && factions[model_side as usize]
                                .recruits
                                .iter()
                                .filter_map(|id| units.get(id))
                                .any(|def| state.gold[model_side as usize] >= def.cost)
                    } else {
                        factions[model_side as usize].recruits.iter().any(|def_id| {
                            let mut candidate = state.clone();
                            let mut candidate_id = next_id;
                            let mut candidate_events = Vec::new();
                            recruit_batch_with_events(
                                &mut candidate,
                                model_side,
                                &factions[model_side as usize],
                                units,
                                &mut candidate_id,
                                def_id,
                                1,
                                &mut candidate_events,
                            )
                            .is_ok()
                        })
                    });
                    match recruiter_threats_after_end_turn(&state, model_side) {
                        Ok(threats) => pre_end_threats = Some(threats),
                        Err(error) => {
                            preview_error = Some(
                                json!({"code":"threat_preview_error","message":error.to_string()}),
                            );
                        }
                    }
                    match unit_threats_after_end_turn(&state, model_side) {
                        Ok(exposure) => pre_end_exposure = Some(exposure),
                        Err(error) => {
                            preview_error = Some(
                                json!({"code":"exposure_preview_error","message":error.to_string()}),
                            );
                        }
                    }
                }
                apply_action(&mut state, Action::EndTurn)
            }
            Some("Advance") => {
                let id = order.get("unit_id").and_then(Value::as_u64);
                let target = order
                    .get("target_index")
                    .and_then(Value::as_i64)
                    .map(|index| {
                        AdvanceTarget::Index(if index < 0 {
                            usize::MAX
                        } else {
                            index as usize
                        })
                    })
                    .or_else(|| {
                        order
                            .get("def_id")
                            .and_then(Value::as_str)
                            .map(|id| AdvanceTarget::DefId(id.to_string()))
                    });
                match (id, target) {
                    (Some(id), Some(target)) => apply_advance(&mut state, id as u32, target, units),
                    (Some(_), None) => {
                        Err(norrust_core::game_state::ActionError::AdvanceNeedsTarget)
                    }
                    _ => Err(norrust_core::game_state::ActionError::UnitNotFound(0)),
                }
            }
            Some(_) | None => Err(norrust_core::game_state::ActionError::NotAdjacent),
        };
        match result {
            Ok(mut produced) => {
                events.append(&mut produced);
                let mut result_value = if conditional_action {
                    json!({"ok":true,"conditional_on_survival":true})
                } else {
                    json!({"ok":true})
                };
                if !conditional_steps.is_empty() {
                    result_value["conditional_steps"] = json!(conditional_steps);
                }
                results.push(result_value);
                if action_name == Some("EndTurn") {
                    did_end = true;
                }
            }
            Err(error) => {
                results.push(json!({"ok":false,"code":error.code(),"message":error.to_string()}));
                if !sample_attacks {
                    break;
                }
            }
        }
        if state.check_winner().is_some() {
            did_end = true;
        }
    }
    let succeeded = results
        .iter()
        .all(|result| result.get("ok") == Some(&Value::Bool(true)));
    if !succeeded {
        events.clear();
        did_end = false;
    }
    BatchExecution {
        state,
        next_id,
        results,
        events,
        did_end,
        forecasts,
        sequence_attacks: sequence_attacks.clone(),
        attack_sequences: sequence_attacks
            .clone()
            .into_iter()
            .map(|(target_id, (hp, attacks))| {
                let parameters = attacks.iter().map(|(_, parameters)| parameters.clone()).collect::<Vec<_>>();
                json!({
                    "target_id": target_id,
                    "target_hp": hp,
                    "attacker_ids": attacks.iter().map(|(id, _)| *id).collect::<Vec<_>>(),
                    "kill_bps": exact_damage_sequence(hp, &parameters).kill_bps,
                    "expected_damage_tenths": exact_damage_sequence(hp, &parameters).expected_damage_tenths,
                })
            })
            .collect(),
        pre_end_threats,
        pre_end_exposure,
        preview_error,
        post_combat_conditional,
        conditional_unit_ids: conditional_ids,
        pre_end_recruitment_remaining,
    }
}

fn init_game(c: &Config) -> Result<(GameState, Faction, Faction, Registry<UnitDef>), String> {
    let base = root();
    let data = base.join("data");
    let units: Registry<UnitDef> =
        Registry::load_from_dir(&data.join("units")).map_err(|e| format!("load units: {}", e))?;
    let terrain: Registry<TerrainDef> = Registry::load_from_dir(&data.join("terrain"))
        .map_err(|e| format!("load terrain: {}", e))?;
    let factions = load_factions(&data)?;

    let f0 = factions
        .iter()
        .find(|f| f.def.id == c.faction0)
        .ok_or_else(|| format!("unknown faction {}", c.faction0))?
        .clone();
    let f1 = factions
        .iter()
        .find(|f| f.def.id == c.faction1)
        .ok_or_else(|| format!("unknown faction {}", c.faction1))?
        .clone();

    let board = load_board(&base.join("scenarios").join(&c.scenario).join("board.toml"))
        .map_err(|e| e.to_string())?;

    let mut state = GameState::new_seeded(board.board, c.seed);
    state.objective_hex = None;
    upgrade_tiles(&mut state, &terrain);

    // Place leaders on keeps
    let k0 = keep_for(&state, 0).ok_or("scenario needs a faction 0 keep")?;
    let k1 = keep_for(&state, 1).ok_or("scenario needs two keeps")?;

    let leader0 = units
        .get(&f0.def.leader_def)
        .ok_or_else(|| format!("leader definition not found: {}", f0.def.leader_def))?;
    let leader1 = units
        .get(&f1.def.leader_def)
        .ok_or_else(|| format!("leader definition not found: {}", f1.def.leader_def))?;
    state.place_unit(Unit::from_def(1, leader0, 0), k0);
    state.place_unit(Unit::from_def(2, leader1, 1), k1);

    // Load scenario triggers only. Scenario unit placements and scenario win
    // conditions belong to campaign setup and must not contaminate this duel.
    let units_path = base.join("scenarios").join(&c.scenario).join("units.toml");
    if units_path.exists() {
        let units_def = load_units_file(&units_path)?;
        {
            for trigger in units_def.triggers {
                let spawns = trigger
                    .spawns
                    .iter()
                    .filter_map(|spawn| {
                        let def = units.get(&spawn.unit_type)?;
                        let id = state.next_unit_id;
                        state.next_unit_id += 1;
                        Some(PendingSpawn {
                            unit: Unit::from_def(id, def, spawn.faction),
                            destination: Hex::from_offset(spawn.col, spawn.row),
                        })
                    })
                    .collect();
                state.trigger_zones.push(TriggerZone {
                    trigger_hex: Hex::from_offset(trigger.trigger_col, trigger.trigger_row),
                    trigger_faction: trigger.trigger_faction,
                    spawns,
                    triggered: false,
                });
            }
        }
    }

    state.gold = [c.gold, c.gold];
    state.faction_ids = [f0.def.id.clone(), f1.def.id.clone()];
    state.recruit_ids = [f0.recruits.clone(), f1.recruits.clone()];
    state.active_faction = 0;

    eprintln!(
        "[INIT] Scenario: {}, Seed: {}, Factions: {} vs {}, Gold: {} each",
        c.scenario, c.seed, c.faction0, c.faction1, c.gold
    );
    let (k0_col, k0_row) = k0.to_offset();
    let (k1_col, k1_row) = k1.to_offset();
    eprintln!(
        "[INIT] Keep 0 at ({},{}), Keep 1 at ({},{})",
        k0_col, k0_row, k1_col, k1_row
    );

    Ok((state, f0, f1, units))
}

fn scripted_game(c: &Config) {
    println!("{}", json!({"type":"protocol","version":1}));
    io::stdout().flush().unwrap();
    let (mut state, f0, f1, units) = match init_game(c) {
        Ok(game) => game,
        Err(message) => {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"invalid_setup","message":message})
            );
            return;
        }
    };
    let mut next_id = state.next_unit_id;

    // Verify initial setup
    {
        let f0_leaders = state
            .units
            .values()
            .filter(|u| u.faction == 0 && u.can_recruit)
            .count();
        let f1_leaders = state
            .units
            .values()
            .filter(|u| u.faction == 1 && u.can_recruit)
            .count();
        if f0_leaders != 1 || f1_leaders != 1 {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"invalid_setup","message":"each faction must have exactly one leader"})
            );
            return;
        }
        eprintln!("[ASSERT] Each faction has exactly 1 leader on keep. ✓");
    }

    // Run greedy-vs-greedy smoke test
    for _turn in 0..c.max_turns {
        let side = state.active_faction;
        let result = if side == 0 {
            run_driver_greedy_turn(&mut state, 0, &f0, &units, &mut next_id)
        } else {
            run_driver_greedy_turn(&mut state, 1, &f1, &units, &mut next_id)
        };
        let events = match result {
            Ok(events) => events,
            Err(_) => {
                println!("{}", greedy_infrastructure_failure(&state, 0));
                return;
            }
        };
        print_events(&events, "greedy", "greedy");

        if let Some(winner) = state.check_winner() {
            eprintln!(
                "[RESULT] Faction {} wins in {} turns. Final gold: {:?}",
                winner, state.turn, state.gold
            );
            let unit_count = [0, 1].map(|faction| {
                state
                    .units
                    .values()
                    .filter(|u| u.faction == faction)
                    .count()
            });
            eprintln!(
                "[RESULT] Units: faction 0: {}, faction 1: {}",
                unit_count[0], unit_count[1]
            );
            println!(
                "{}",
                json!({"type":"game_end","reason":"winner","winner":winner,"turns":state.turn})
            );
            return;
        }
    }
    eprintln!(
        "[RESULT] Draw after {} side-turns (safety limit).",
        c.max_turns
    );
    println!(
        "{}",
        json!({"type":"game_end","reason":"max_turns","turns":state.turn})
    );
}

#[allow(dead_code)]
fn interactive_game(c: &Config) {
    let (mut state, f0, f1, units) = match init_game(c) {
        Ok(game) => game,
        Err(message) => {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"invalid_setup","message":message})
            );
            return;
        }
    };
    let mut next_id = 3;

    // Verify initial setup
    {
        let f0_leaders = state
            .units
            .values()
            .filter(|u| u.faction == 0 && u.can_recruit)
            .count();
        let f1_leaders = state
            .units
            .values()
            .filter(|u| u.faction == 1 && u.can_recruit)
            .count();
        if f0_leaders != 1 || f1_leaders != 1 {
            eprintln!(
                "[ERROR] Setup failed: f0 leaders={}, f1 leaders={}",
                f0_leaders, f1_leaders
            );
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"invalid_setup","message":"each faction must have exactly one leader"})
            );
            return;
        }
    }
    eprintln!("[OK] Both factions have exactly 1 leader.");

    // Main loop: faction 0 is human (LLM), faction 1 is greedy
    let stdin = io::stdin();
    let mut lines = stdin.lock().lines();

    loop {
        if let Some(winner) = state.check_winner() {
            eprintln!(
                "[GAME_END] Faction {} wins after {} turns",
                winner, state.turn
            );
            println!(
                "{}",
                serde_json::to_string(
                    &json!({"game_end": true, "winner": winner, "turns": state.turn})
                )
                .unwrap()
            );
            break;
        }

        let side = state.active_faction;

        if side == 0 {
            // Human turn: show state, then wait for action
            // NOTE: LLM must decide Recruit actions themselves via action handler
            println!(
                "{}",
                serde_json::to_string(&game_state_to_json(&state, &units)).unwrap()
            );
            std::io::stdout().flush().unwrap();

            // Read one action from stdin
            let line = match lines.next() {
                Some(Ok(l)) => l,
                _ => {
                    eprintln!("[ERROR] EOF or read error on stdin");
                    break;
                }
            };
            eprintln!("[LLM_ACTION] {}", line);

            // Parse and apply action
            match serde_json::from_str::<Value>(&line) {
                Ok(v) => {
                    let action_name = v.get("action").and_then(|a| a.as_str()).unwrap_or("?");
                    match action_name {
                        "Move" => {
                            if let (Some(u), Some(c), Some(r)) = (
                                v.get("unit_id").and_then(|x| x.as_u64()),
                                v.get("col").and_then(|x| x.as_i64()),
                                v.get("row").and_then(|x| x.as_i64()),
                            ) {
                                let dest = Hex::from_offset(c as i32, r as i32);
                                match apply_action(
                                    &mut state,
                                    Action::Move {
                                        unit_id: u as u32,
                                        destination: dest,
                                    },
                                ) {
                                    Ok(_) => eprintln!("[ACTION_OK] Move u{} to ({},{})", u, c, r),
                                    Err(e) => eprintln!("[ACTION_ERR] Move failed: {:?}", e),
                                }
                            }
                        }
                        "Attack" => {
                            if let (Some(attacker), Some(defender)) = (
                                v.get("attacker_id").and_then(|x| x.as_u64()),
                                v.get("defender_id").and_then(|x| x.as_u64()),
                            ) {
                                match apply_action(
                                    &mut state,
                                    Action::Attack {
                                        attacker_id: attacker as u32,
                                        defender_id: defender as u32,
                                    },
                                ) {
                                    Ok(_) => eprintln!(
                                        "[ACTION_OK] Attack u{} vs u{}",
                                        attacker, defender
                                    ),
                                    Err(e) => eprintln!("[ACTION_ERR] Attack failed: {:?}", e),
                                }
                            }
                        }
                        "Recruit" => {
                            if let (Some(def_id), Some(c), Some(r)) = (
                                v.get("def_id").and_then(|x| x.as_str()),
                                v.get("col").and_then(|x| x.as_i64()),
                                v.get("row").and_then(|x| x.as_i64()),
                            ) {
                                let dest = Hex::from_offset(c as i32, r as i32);
                                if let Some(unit_def) = units.get(def_id) {
                                    let cost = unit_def.cost;
                                    let current_id = next_id;
                                    let unit = Unit::from_def(current_id, unit_def, 0);
                                    match apply_recruit(&mut state, unit, dest, cost) {
                                        Ok(_) => {
                                            eprintln!(
                                                "[ACTION_OK] Recruit {} (u{}) at ({},{})",
                                                def_id, current_id, c, r
                                            );
                                            next_id += 1;
                                        }
                                        Err(e) => eprintln!("[ACTION_ERR] Recruit failed: {:?}", e),
                                    }
                                }
                            }
                        }
                        // Recruit `count` of one unit type, letting the driver handle the
                        // castle-ring vacate-and-continue mechanics. The caller still chooses
                        // the unit type and the quantity; only hex placement is automated,
                        // which mirrors the recruitment help the greedy opponent already gets.
                        "RecruitBatch" => {
                            let def_id = v.get("def_id").and_then(|x| x.as_str());
                            let count = v.get("count").and_then(|x| x.as_u64());
                            match (def_id, count) {
                                (Some(did), Some(n)) if n > 0 => {
                                    if units.get(did).is_none() {
                                        eprintln!(
                                            "[ACTION_ERR] RecruitBatch unknown def_id: {}",
                                            did
                                        );
                                    } else {
                                        let placed = recruit(
                                            &mut state,
                                            0,
                                            &f0,
                                            &units,
                                            &mut next_id,
                                            Some(did),
                                            Some(n as u32),
                                        );
                                        eprintln!(
                                            "[ACTION_OK] RecruitBatch {} x{} requested, {} placed, gold now {}",
                                            did, n, placed, state.gold[0]
                                        );
                                    }
                                }
                                _ => {
                                    eprintln!("[ACTION_ERR] RecruitBatch needs def_id and count>0")
                                }
                            }
                        }
                        "EndTurn" => {
                            if let Err(e) = apply_action(&mut state, Action::EndTurn) {
                                eprintln!("[ACTION_ERR] EndTurn failed: {:?}", e);
                            } else {
                                eprintln!("[ACTION_OK] End faction 0 turn");
                            }
                        }
                        _ => eprintln!("[ACTION_ERR] Unknown action: {}", action_name),
                    }
                }
                Err(e) => eprintln!("[PARSE_ERROR] {}", e),
            }
        } else {
            // Faction 1 (greedy AI) turn
            if run_driver_greedy_turn(&mut state, 1, &f1, &units, &mut next_id).is_err() {
                println!("{}", greedy_infrastructure_failure(&state, 0));
                return;
            }
            eprintln!("[AI_TURN] Faction 1 greedy turn complete");
        }
    }
}

fn event_value(event: &GameEvent, source: &str) -> Value {
    let mut value = serde_json::to_value(event).unwrap_or_else(|_| json!({}));
    if let Some(object) = value.as_object_mut() {
        object.insert("source".into(), Value::String(source.into()));
    }
    value
}

fn print_events(events: &[GameEvent], envelope_source: &str, event_source: &str) {
    if events.is_empty() {
        return;
    }
    let body: Vec<Value> = events
        .iter()
        .map(|event| event_value(event, event_source))
        .collect();
    println!(
        "{}",
        json!({"type":"events", "source": envelope_source, "events": body})
    );
    io::stdout().flush().unwrap();
}

fn print_boundary(state: &GameState, units: &Registry<UnitDef>, partial: bool) {
    let mut value = game_state_to_json(state, units);
    if let Some(object) = value.as_object_mut() {
        object.insert("type".into(), json!("state"));
        object.insert("winner".into(), json!(state.check_winner()));
        object.insert(
            "turn_boundary".into(),
            json!(if partial { "partial" } else { "turn" }),
        );
    }
    println!("{}", value);
    io::stdout().flush().unwrap();
}

/// Protocol driver.  Queries are deliberately kept at the boundary: the
/// engine remains the sole authority for mutation and legality.
fn interactive_protocol_game(c: &Config) {
    println!("{}", json!({"type":"protocol", "version":1}));
    io::stdout().flush().unwrap();
    if c.seed == 0
        || c.llm_side > 1
        || c.max_turns == 0
        || c.turn_timeout == 0
        || c.query_timeout == 0
        || c.max_queries == 0
    {
        println!(
            "{}",
            json!({"type":"game_end","reason":"setup_error","code":"invalid_config","message":"invalid driver configuration"})
        );
        return;
    }
    let checkpoint = match c
        .resume_checkpoint
        .as_ref()
        .map(|path| read_checkpoint(path))
    {
        Some(Ok(checkpoint)) => Some(checkpoint),
        Some(Err(message)) => {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"invalid_checkpoint","message":message})
            );
            return;
        }
        None => None,
    };
    let (initial_state, f0, f1, units) = match init_game(c) {
        Ok(game) => game,
        Err(message) => {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"invalid_setup","message":message})
            );
            return;
        }
    };
    let mut state = if let Some(checkpoint) = checkpoint.as_ref() {
        if checkpoint.scenario != c.scenario
            || checkpoint.faction0 != c.faction0
            || checkpoint.faction1 != c.faction1
            || checkpoint.llm_side != c.llm_side
            || checkpoint.max_turns != c.max_turns
            || checkpoint.seed != c.seed
            || checkpoint.starting_gold != c.gold
            || checkpoint.disable_recruit_batch != c.disable_recruit_batch
            || checkpoint.incremental_turns != c.incremental_turns
        {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"checkpoint_config_mismatch"})
            );
            return;
        }
        let board_bytes = match fs::read(&checkpoint.board_path) {
            Ok(bytes) => bytes,
            Err(_) => {
                println!(
                    "{}",
                    json!({"type":"game_end","reason":"setup_error","code":"invalid_checkpoint","message":"checkpoint board is unavailable"})
                );
                return;
            }
        };
        if checkpoint.board_sha256 != checkpoint_digest(&board_bytes) {
            println!(
                "{}",
                json!({"type":"game_end","reason":"setup_error","code":"checkpoint_board_mismatch"})
            );
            return;
        }
        let terrain: Registry<TerrainDef> = match Registry::load_from_dir(
            &root().join("data").join("terrain"),
        ) {
            Ok(registry) => registry,
            Err(error) => {
                println!(
                    "{}",
                    json!({"type":"game_end","reason":"setup_error","code":"invalid_setup","message":error.to_string()})
                );
                return;
            }
        };
        match SaveState::restore_game_state(&checkpoint.save_state, &units, &terrain) {
            Ok(restored) => restored,
            Err(message) => {
                println!(
                    "{}",
                    json!({"type":"game_end","reason":"setup_error","code":"invalid_checkpoint","message":message})
                );
                return;
            }
        }
    } else {
        initial_state
    };
    let mut next_id = checkpoint
        .as_ref()
        .map(|checkpoint| checkpoint.next_id)
        .unwrap_or(state.next_unit_id);
    let factions = [f0, f1];
    let mut side_turns = checkpoint
        .as_ref()
        .map(|checkpoint| checkpoint.side_turns)
        .unwrap_or(0);
    let mut partial_batches = 0u8;
    let mut terminal = false;

    if let Some(checkpoint) = checkpoint.as_ref() {
        if checkpoint.pending_opponent_turn {
            let greedy_side = 1 - c.llm_side;
            match run_driver_greedy_turn(
                &mut state,
                greedy_side,
                &factions[greedy_side as usize],
                &units,
                &mut next_id,
            ) {
                Ok(events) => {
                    side_turns += 1;
                    print_events(&events, "greedy", "greedy");
                }
                Err(_) => {
                    println!("{}", greedy_infrastructure_failure(&state, side_turns));
                    return;
                }
            }
        }
    }
    if state.check_winner().is_some() {
        println!(
            "{}",
            json!({"type":"game_end","reason":"winner","winner":state.check_winner(),"turns":state.turn})
        );
        return;
    }
    if side_turns >= c.max_turns {
        println!(
            "{}",
            json!({"type":"game_end","reason":"max_turns","turns":state.turn,"side_turns":side_turns})
        );
        return;
    }
    if checkpoint.is_none() && c.llm_side == 1 {
        let side = 0usize;
        let events =
            match run_driver_greedy_turn(&mut state, 0, &factions[side], &units, &mut next_id) {
                Ok(events) => events,
                Err(_) => {
                    println!("{}", greedy_infrastructure_failure(&state, side_turns));
                    return;
                }
            };
        side_turns += 1;
        print_events(&events, "greedy", "greedy");
    }
    if state.check_winner().is_some() {
        println!(
            "{}",
            json!({"type":"game_end","reason":"winner","winner":state.check_winner(),"turns":state.turn})
        );
        return;
    }
    if c.llm_side == 1 && side_turns >= c.max_turns {
        println!(
            "{}",
            json!({"type":"game_end","reason":"max_turns","turns":state.turn,"side_turns":side_turns})
        );
        return;
    }
    if let Ok(Some(reference)) = write_checkpoint(c, &state, side_turns, next_id, "model", false) {
        println!("{}", reference);
        io::stdout().flush().unwrap();
    }
    print_boundary(&state, &units, false);

    let (line_tx, line_rx) = mpsc::sync_channel::<Result<String, String>>(8);
    std::thread::spawn(move || {
        let stdin = io::stdin();
        let mut input = stdin.lock();
        loop {
            let mut bytes = Vec::new();
            match input.read_until(b'\n', &mut bytes) {
                Ok(0) => break,
                Ok(_) if bytes.len() > 1024 * 1024 => {
                    let complete = bytes.last() == Some(&b'\n');
                    bytes.clear();
                    while !complete && !bytes.ends_with(b"\n") {
                        let mut tail = [0u8; 4096];
                        match input.read(&mut tail) {
                            Ok(0) => break,
                            Ok(n) => bytes.extend_from_slice(&tail[..n]),
                            Err(_) => break,
                        }
                    }
                    if line_tx.send(Err("line_too_large".into())).is_err() {
                        break;
                    }
                }
                Ok(_) => {
                    let line = String::from_utf8_lossy(&bytes)
                        .trim_end_matches(['\r', '\n'])
                        .to_string();
                    if line_tx.send(Ok(line)).is_err() {
                        break;
                    }
                }
                Err(error) => {
                    let _ = line_tx.send(Err(error.to_string()));
                    break;
                }
            }
        }
    });
    let mut deadline = Instant::now() + Duration::from_secs(c.turn_timeout);
    let mut query_count = 0u32;
    let mut query_elapsed = Duration::ZERO;
    let query_budget = Duration::from_secs(c.query_timeout);
    let mut action_count = 0u32;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let line_result = match line_rx.recv_timeout(remaining) {
            Ok(line) => line,
            Err(RecvTimeoutError::Timeout) => {
                println!(
                    "{}",
                    json!({"type":"game_end","reason":"timeout","turns":state.turn})
                );
                terminal = true;
                break;
            }
            Err(RecvTimeoutError::Disconnected) => Err("eof".into()),
        };
        let line = match line_result {
            Ok(line) => line,
            Err(error) if error == "line_too_large" => {
                println!(
                    "{}",
                    json!({"type":"status","ok":false,"code":"line_too_large","message":"input line exceeds 1 MiB"})
                );
                continue;
            }
            Err(error) if error == "eof" => break,
            Err(_) => break,
        };
        let parsed: Value = match serde_json::from_str(&line) {
            Ok(value) => value,
            Err(error) => {
                println!(
                    "{}",
                    json!({"type":"status","ok":false,"code":"parse","message":error.to_string()})
                );
                continue;
            }
        };
        if parsed.get("action").and_then(Value::as_str) == Some("Query") {
            if query_count >= c.max_queries {
                println!(
                    "{}",
                    json!({"type":"status","ok":false,"code":"query_limit","message":"query limit exceeded"})
                );
                continue;
            }
            query_count += 1;
            if query_elapsed >= query_budget {
                println!(
                    "{}",
                    json!({"type":"status","ok":false,"code":"query_timeout","message":"query budget exceeded"})
                );
                io::stdout().flush().unwrap();
                continue;
            }
            let query_started = Instant::now();
            let what = parsed.get("what").and_then(Value::as_str).unwrap_or("");
            let mut response = match what {
                "validate_batch" => {
                    let requested_revision = parsed.get("state_revision").and_then(Value::as_u64);
                    let orders = parsed.get("orders").and_then(Value::as_array);
                    let error = if requested_revision != Some(state.state_revision) {
                        Some(
                            json!({"code":"stale_state","message":"requested state revision is no longer current"}),
                        )
                    } else if state.active_faction != c.llm_side {
                        Some(
                            json!({"code":"unauthorized_side","message":"model actions are not authorized while the opponent is active"}),
                        )
                    } else if orders.is_none() || orders.is_some_and(|items| items.is_empty()) {
                        Some(json!({"code":"parse","message":"orders must be a non-empty array"}))
                    } else if orders.is_some_and(|items| items.len() > 256) {
                        Some(
                            json!({"code":"batch_too_large","message":"action batch exceeds 256 objects"}),
                        )
                    } else if orders
                        .is_some_and(|items| items.iter().any(|order| !valid_action_shape(order)))
                    {
                        Some(json!({"code":"parse","message":"invalid action shape"}))
                    } else if orders.is_some_and(|items| {
                        let names: Vec<Option<&str>> = items
                            .iter()
                            .map(|order| order.get("action").and_then(Value::as_str))
                            .collect();
                        (!c.incremental_turns
                            && (names
                                .iter()
                                .filter(|name| **name == Some("EndTurn"))
                                .count()
                                != 1
                                || !matches!(names.last(), Some(Some("EndTurn")))))
                            || (c.incremental_turns
                                && (names
                                    .iter()
                                    .filter(|name| **name == Some("EndTurn"))
                                    .count()
                                    > 1
                                    || (names.contains(&Some("EndTurn"))
                                        && !matches!(names.last(), Some(Some("EndTurn"))))))
                    }) {
                        Some(json!({"code":"parse","message":"invalid action batch structure"}))
                    } else if let Some(items) = orders {
                        match authorize_model_batch(items, &state, c.llm_side) {
                            Ok(()) => None,
                            Err((code, message)) => Some(json!({"code":code,"message":message})),
                        }
                    } else {
                        unreachable!()
                    };
                    if let Some(error) = error {
                        let mut response = json!({"type":"status","ok":false,"what":what,"state_revision":state.state_revision});
                        response.as_object_mut().unwrap().extend(
                            error
                                .as_object()
                                .unwrap()
                                .iter()
                                .map(|(key, value)| (key.clone(), value.clone())),
                        );
                        response
                    } else {
                        let items = orders.unwrap();
                        let execution = execute_model_batch(
                            state.clone(),
                            next_id,
                            items,
                            c.llm_side,
                            &factions,
                            &units,
                            c.disable_recruit_batch,
                            true,
                        );
                        let valid = execution
                            .results
                            .iter()
                            .all(|result| result.get("ok") == Some(&Value::Bool(true)));
                        let failed_index = execution
                            .results
                            .iter()
                            .position(|result| result.get("ok") == Some(&Value::Bool(false)));
                        json!({"type":"status","ok":true,"what":what,"state_revision":state.state_revision,
                            "body":{"valid":valid,"results":execution.results,"failed_index":failed_index}})
                    }
                }
                "preview_batch" => {
                    let candidates = parsed.get("candidates").and_then(Value::as_array);
                    if parsed.get("state_revision").and_then(Value::as_u64)
                        != Some(state.state_revision)
                    {
                        json!({"type":"status","ok":false,"what":what,"code":"stale_state","message":"requested state revision is no longer current","state_revision":state.state_revision})
                    } else if state.active_faction != c.llm_side {
                        json!({"type":"status","ok":false,"what":what,"code":"unauthorized_side","message":"model actions are not authorized while the opponent is active"})
                    } else if candidates.is_none()
                        || candidates.is_some_and(|items| items.is_empty() || items.len() > 2)
                    {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"candidates must contain one or two action arrays"})
                    } else {
                        let candidates = candidates.unwrap();
                        let contract_error =
                            candidates
                                .iter()
                                .enumerate()
                                .find_map(|(index, candidate)| {
                                    let Some(orders) = candidate.as_array() else {
                                        return Some((
                                            index,
                                            "parse",
                                            "each candidate must be an action array",
                                        ));
                                    };
                                    validate_model_batch_contract(orders, &state, c.llm_side)
                                        .err()
                                        .map(|(code, message)| (index, code, message))
                                });
                        if let Some((index, code, message)) = contract_error {
                            json!({"type":"status","ok":false,"what":what,"code":code,"message":message,"candidate_index":index})
                        } else {
                            let before_gold = state.gold[c.llm_side as usize];
                            let before_units = state.units.len();
                            let previews = candidates.iter().map(|candidate| {
                            let orders = candidate.as_array().expect("validated candidate");
                            let execution = execute_model_batch(state.clone(), next_id, orders, c.llm_side, &factions, &units, c.disable_recruit_batch, false);
                            let valid = execution.preview_error.is_none() && execution.results.len() == orders.len() && execution.results.iter().all(|result| result.get("ok") == Some(&Value::Bool(true)));
                            let mut recruiter_hp: Vec<Value> = execution.state.units.iter().filter_map(|(id, unit)| {
                                (unit.faction == c.llm_side && unit.can_recruit).then(|| json!({"unit_id":id,"hp":unit.hp}))
                            }).collect();
                            recruiter_hp.sort_by_key(|item| item.get("unit_id").and_then(Value::as_u64));
                            json!({"valid":valid,"results":execution.results,"forecasts":execution.forecasts,
                                "attack_sequences":execution.attack_sequences,
                                "recruiter_threats":if valid { execution.pre_end_threats } else { None },
                                "exposure":if valid { execution.pre_end_exposure } else { None },
                                "preview_error":execution.preview_error,
                                "post_combat_conditional":execution.post_combat_conditional,
                                "assumption":if execution.post_combat_conditional {"all forecast combatants survive in place"} else {"none"},
                                "summary":{"gold_before":before_gold,"gold_after":execution.state.gold[c.llm_side as usize],
                                    "units_before":before_units,"units_after":execution.state.units.len(),"recruiters":recruiter_hp,
                                    "affordable_recruitment_remaining":execution.pre_end_recruitment_remaining}})
                        }).collect::<Vec<_>>();
                            json!({"type":"status","ok":true,"what":what,"state_revision":state.state_revision,
                            "body":{"sampling":false,"candidates":previews}})
                        }
                    }
                }
                "tactical_surface" => {
                    let requested_revision = parsed.get("state_revision").and_then(Value::as_u64);
                    if requested_revision.is_some_and(|revision| revision != state.state_revision) {
                        json!({"type":"status","ok":false,"what":what,"code":"stale_state","message":"requested state revision is no longer current","state_revision":state.state_revision})
                    } else {
                        match turn_tactics(&state, state.active_faction) {
                            Ok(tactical_units) => {
                                let side = state.active_faction as usize;
                                let faction = &factions[side];
                                let placement_hexes: Vec<Value> = state
                                    .units
                                    .iter()
                                    .filter(|(_, unit)| {
                                        unit.faction == state.active_faction && unit.can_recruit
                                    })
                                    .filter_map(|(id, _)| state.positions.get(id))
                                    .filter(|hex| {
                                        state
                                            .board
                                            .tile_at(**hex)
                                            .is_some_and(|tile| tile.terrain_id == "keep")
                                    })
                                    .flat_map(|hex| hex.neighbors())
                                    .filter(|hex| {
                                        state
                                            .board
                                            .tile_at(*hex)
                                            .is_some_and(|tile| tile.terrain_id == "castle")
                                            && !state.hex_to_unit.contains_key(hex)
                                    })
                                    .map(|hex| {
                                        let (col, row) = hex.to_offset();
                                        json!({"col":col,"row":row})
                                    })
                                    .collect();
                                let options: Vec<Value> = faction.recruits.iter().filter_map(|id| units.get(id).map(|def| json!({"def_id":id,"cost":def.cost,"affordable":state.gold[side] >= def.cost}))).collect();
                                let recruiter_on_keep = state.units.iter().any(|(id, unit)| {
                                    unit.faction == state.active_faction
                                        && unit.can_recruit
                                        && state
                                            .positions
                                            .get(id)
                                            .and_then(|hex| state.board.tile_at(*hex))
                                            .is_some_and(|tile| tile.terrain_id == "keep")
                                });
                                let affordable = faction.recruits.iter().any(|id| {
                                    units
                                        .get(id)
                                        .is_some_and(|def| state.gold[side] >= def.cost)
                                });
                                let legal_now =
                                    recruiter_on_keep && affordable && !placement_hexes.is_empty();
                                let recruit_reason = if legal_now {
                                    "none"
                                } else if !recruiter_on_keep {
                                    "recruiter_off_keep"
                                } else if !affordable {
                                    "insufficient_gold"
                                } else {
                                    "no_capacity"
                                };
                                let mut profile_ids = BTreeSet::new();
                                profile_ids.extend(faction.recruits.iter().cloned());
                                profile_ids.extend(
                                    state
                                        .units
                                        .values()
                                        .filter(|unit| unit.faction != state.active_faction)
                                        .map(|unit| unit.def_id.clone()),
                                );
                                let unit_types: Vec<Value> = profile_ids
                                    .iter()
                                    .filter_map(|id| units.get(id).map(unit_type_profile))
                                    .collect();
                                let threats =
                                    recruiter_threats_after_end_turn(&state, state.active_faction)
                                        .map_err(|error| error.to_string());
                                let exposure =
                                    unit_threats_after_end_turn(&state, state.active_faction)
                                        .map_err(|error| error.to_string());
                                let economy = economy_facts(&state, state.active_faction)
                                    .map_err(|error| error.to_string());
                                match (threats, exposure, economy) {
                                    (
                                        Ok(threats),
                                        Ok(exposure),
                                        Ok((next_village_income, vacatable_castles)),
                                    ) => {
                                        json!({"type":"status","ok":true,"what":what,"body":{"visibility":"full","time_of_day":tod_label(state.turn),"next_time_of_day":tod_label(state.turn.saturating_add(1)),"units":tactical_units,"unit_types":unit_types,"threats":threats,"exposure":exposure,"force":force_summaries(&state),"economy":{"gold":state.gold[side],"next_village_income":next_village_income,"vacatable_castles":vacatable_castles},"recruitment":{"gold":state.gold[side],"placement_hexes":placement_hexes,"options":options,"legal_now":legal_now,"reason":recruit_reason,"recruiter_on_keep":recruiter_on_keep,"batch_macro_enabled":!c.disable_recruit_batch}}})
                                    }
                                    (Err(message), _, _) => {
                                        json!({"type":"status","ok":false,"what":what,"code":"tactical_surface_error","message":message})
                                    }
                                    (_, Err(message), _) => {
                                        json!({"type":"status","ok":false,"what":what,"code":"tactical_surface_error","message":message})
                                    }
                                    (_, _, Err(message)) => {
                                        json!({"type":"status","ok":false,"what":what,"code":"tactical_surface_error","message":message})
                                    }
                                }
                            }
                            Err(error) => {
                                json!({"type":"status","ok":false,"what":what,"code":"tactical_surface_error","message":error.to_string()})
                            }
                        }
                    }
                }
                "inspect_unit" => {
                    let requested_revision = parsed.get("state_revision").and_then(Value::as_u64);
                    let unit_id = parsed.get("unit_id").and_then(Value::as_u64);
                    if requested_revision != Some(state.state_revision) {
                        json!({"type":"status","ok":false,"what":what,"code":"stale_state","message":"requested state revision is no longer current","state_revision":state.state_revision})
                    } else if state.active_faction != c.llm_side {
                        json!({"type":"status","ok":false,"what":what,"code":"unauthorized_side","message":"model queries are not authorized while the opponent is active"})
                    } else if unit_id.is_none() || unit_id > Some(u32::MAX as u64) {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"unit_id is required"})
                    } else {
                        let unit_id = unit_id.unwrap() as u32;
                        match state.units.get(&unit_id) {
                            None => {
                                json!({"type":"status","ok":false,"what":what,"code":"UnitNotFound","message":"unit is unavailable"})
                            }
                            Some(unit) if unit.faction != c.llm_side => {
                                json!({"type":"status","ok":false,"what":what,"code":"unauthorized_unit","message":"only model-side units may be inspected"})
                            }
                            Some(_unit) => match unit_tactics(&state, unit_id) {
                                Ok(tactics) => {
                                    let mut body =
                                        serde_json::to_value(tactics).unwrap_or_else(|_| json!({}));
                                    match unit_destination_threats(&state, unit_id) {
                                        Ok(destinations) => {
                                            body["destination_threats"] = json!(destinations);
                                            json!({"type":"status","ok":true,"what":what,"state_revision":state.state_revision,"body":body})
                                        }
                                        Err(error) => {
                                            json!({"type":"status","ok":false,"what":what,"code":"inspect_unit_error","message":error.to_string()})
                                        }
                                    }
                                }
                                Err(error) => {
                                    json!({"type":"status","ok":false,"what":what,"code":"inspect_unit_error","message":error.to_string()})
                                }
                            },
                        }
                    }
                }
                "inspect_target" => {
                    let requested_revision = parsed.get("state_revision").and_then(Value::as_u64);
                    let unit_id = parsed.get("unit_id").and_then(Value::as_u64);
                    if requested_revision != Some(state.state_revision) {
                        json!({"type":"status","ok":false,"what":what,"code":"stale_state","message":"requested state revision is no longer current","state_revision":state.state_revision})
                    } else if state.active_faction != c.llm_side {
                        json!({"type":"status","ok":false,"what":what,"code":"unauthorized_side","message":"model queries are not authorized while the opponent is active"})
                    } else if unit_id.is_none() || unit_id > Some(u32::MAX as u64) {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"unit_id is required"})
                    } else {
                        match target_inspection(&state, c.llm_side, unit_id.unwrap() as u32) {
                            Ok(inspection) => {
                                json!({"type":"status","ok":true,"what":what,"state_revision":state.state_revision,"body":inspection})
                            }
                            Err(error) => {
                                json!({"type":"status","ok":false,"what":what,"code":"inspect_target_error","message":error.to_string()})
                            }
                        }
                    }
                }
                "inspect_targets" => {
                    let requested_revision = parsed.get("state_revision").and_then(Value::as_u64);
                    let ids = parsed.get("unit_ids").and_then(Value::as_array);
                    let parsed_ids = ids
                        .map(|values| {
                            values
                                .iter()
                                .map(|value| value.as_u64())
                                .collect::<Option<Vec<_>>>()
                        })
                        .flatten();
                    let valid_ids = parsed_ids.as_ref().is_some_and(|values| {
                        !values.is_empty()
                            && values.len() <= 8
                            && values.iter().all(|id| *id <= u32::MAX as u64)
                            && values.iter().copied().collect::<BTreeSet<_>>().len() == values.len()
                    });
                    if requested_revision != Some(state.state_revision) {
                        json!({"type":"status","ok":false,"what":what,"code":"stale_state","message":"requested state revision is no longer current","state_revision":state.state_revision})
                    } else if state.active_faction != c.llm_side {
                        json!({"type":"status","ok":false,"what":what,"code":"unauthorized_side","message":"model queries are not authorized while the opponent is active"})
                    } else if !valid_ids {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"unit_ids must contain 1 to 8 unique uint32 ids"})
                    } else {
                        let mut targets = Vec::new();
                        let mut error = None;
                        for id in parsed_ids.unwrap() {
                            match target_inspection(&state, c.llm_side, id as u32) {
                                Ok(inspection) => targets.push(inspection),
                                Err(err) => {
                                    error = Some(err);
                                    break;
                                }
                            }
                        }
                        match error {
                            Some(error) => {
                                json!({"type":"status","ok":false,"what":what,"code":"inspect_targets_error","message":error.to_string()})
                            }
                            None => {
                                json!({"type":"status","ok":true,"what":what,"state_revision":state.state_revision,"body":{"targets":targets}})
                            }
                        }
                    }
                }
                "inspect_hex" => {
                    let requested_revision = parsed.get("state_revision").and_then(Value::as_u64);
                    let col = parsed.get("col").and_then(Value::as_i64);
                    let row = parsed.get("row").and_then(Value::as_i64);
                    let phase = parsed.get("phase").and_then(Value::as_str);
                    if requested_revision != Some(state.state_revision) {
                        json!({"type":"status","ok":false,"what":what,"code":"stale_state","message":"requested state revision is no longer current","state_revision":state.state_revision})
                    } else if state.active_faction != c.llm_side {
                        json!({"type":"status","ok":false,"what":what,"code":"unauthorized_side","message":"model queries are not authorized while the opponent is active"})
                    } else if col.is_none()
                        || row.is_none()
                        || phase.is_none()
                        || col.is_some_and(|value| {
                            !(i32::MIN as i64..=i32::MAX as i64).contains(&value)
                        })
                        || row.is_some_and(|value| {
                            !(i32::MIN as i64..=i32::MAX as i64).contains(&value)
                        })
                    {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"col, row, and phase are required"})
                    } else if !matches!(phase, Some("current" | "next_opponent_turn")) {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"phase must be current or next_opponent_turn"})
                    } else {
                        let mut projected = state.clone();
                        if phase == Some("next_opponent_turn") {
                            let _ = apply_action(&mut projected, Action::EndTurn);
                        }
                        match hex_inspection(
                            &projected,
                            Hex::from_offset(col.unwrap() as i32, row.unwrap() as i32),
                        ) {
                            Ok(inspection) => {
                                json!({"type":"status","ok":true,"what":what,"state_revision":state.state_revision,
                                "body":{"phase":phase.unwrap(),"visibility":"full","inspection":inspection}})
                            }
                            Err(error) => {
                                json!({"type":"status","ok":false,"what":what,"code":"inspect_hex_error","message":error.to_string()})
                            }
                        }
                    }
                }
                "state" => {
                    json!({"type":"status","ok":true,"what":"state","body":game_state_to_json(&state, &units)})
                }
                "legal_moves" => match parsed
                    .get("unit_id")
                    .and_then(Value::as_u64)
                    .and_then(|id| legal_moves(&state, id as u32).ok())
                {
                    Some(hexes) => {
                        json!({"type":"status","ok":true,"what":what,"body":{"hexes":hexes.iter().map(|h| { let (c,r)=h.to_offset(); json!({"col":c,"row":r}) }).collect::<Vec<_>>()}})
                    }
                    None => {
                        json!({"type":"status","ok":false,"what":what,"code":"UnitNotFound","message":"unit is unavailable"})
                    }
                },
                "legal_targets" => match (
                    parsed.get("unit_id").and_then(Value::as_u64),
                    parsed.get("col").and_then(Value::as_i64),
                    parsed.get("row").and_then(Value::as_i64),
                ) {
                    (Some(id), Some(c), Some(r)) => {
                        match legal_targets(&state, id as u32, Hex::from_offset(c as i32, r as i32))
                        {
                            Ok(ids) => {
                                json!({"type":"status","ok":true,"what":what,"body":{"ids":ids}})
                            }
                            Err(e) => {
                                json!({"type":"status","ok":false,"what":what,"code":e.code(),"message":e.to_string()})
                            }
                        }
                    }
                    _ => {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"unit_id, col, and row are required"})
                    }
                },
                "combat_preview" => match (
                    parsed.get("attacker_id").and_then(Value::as_u64),
                    parsed.get("defender_id").and_then(Value::as_u64),
                    parsed.get("col").and_then(Value::as_i64),
                    parsed.get("row").and_then(Value::as_i64),
                ) {
                    (Some(a), Some(d), Some(c), Some(r)) => match preview_combat(
                        &state,
                        a as u32,
                        d as u32,
                        Hex::from_offset(c as i32, r as i32),
                        parsed.get("n_sims").and_then(Value::as_u64).unwrap_or(100) as u32,
                    ) {
                        Ok(preview) => {
                            json!({"type":"status","ok":true,"what":what,"attacker_id":a,"defender_id":d,"col":c,"row":r,"body":serde_json::to_value(preview).unwrap()})
                        }
                        Err(error) => {
                            json!({"type":"status","ok":false,"what":what,"code":format!("{:?}",error),"message":error.to_string()})
                        }
                    },
                    _ => {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"preview identifiers and ghost coordinates are required"})
                    }
                },
                "combat_previews" => {
                    let n_sims = parsed.get("n_sims").and_then(Value::as_u64).unwrap_or(100);
                    let engagements = parsed.get("engagements").and_then(Value::as_array);
                    if engagements.is_none() {
                        json!({"type":"status","ok":false,"what":what,"code":"parse","message":"engagements array is required"})
                    } else if engagements.unwrap().len() > 4096 {
                        json!({"type":"status","ok":false,"what":what,"code":"engagement_limit","message":"engagement count exceeds 4096"})
                    } else if !(1..=1000).contains(&n_sims)
                        || (engagements.unwrap().len() as u64).saturating_mul(n_sims) > 200_000
                    {
                        json!({"type":"status","ok":false,"what":what,"code": if !(1..=1000).contains(&n_sims) {"InvalidNSims"} else {"sim_limit"},"message":"simulation budget exceeded or n_sims is invalid"})
                    } else {
                        let engagements = engagements.unwrap();
                        let mut requests = Vec::with_capacity(engagements.len());
                        let mut invalid = None;
                        for (index, engagement) in engagements.iter().enumerate() {
                            let parsed_engagement = (
                                engagement.get("attacker_id").and_then(Value::as_u64),
                                engagement.get("defender_id").and_then(Value::as_u64),
                                engagement.get("col").and_then(Value::as_i64),
                                engagement.get("row").and_then(Value::as_i64),
                            );
                            let (Some(attacker_id), Some(defender_id), Some(col), Some(row)) =
                                parsed_engagement
                            else {
                                invalid = Some((
                                    index,
                                    "parse".to_string(),
                                    "engagement identifiers are required".to_string(),
                                ));
                                break;
                            };
                            requests.push((
                                index,
                                attacker_id as u32,
                                defender_id as u32,
                                col as i32,
                                row as i32,
                            ));
                        }
                        if let Some((index, code, message)) = invalid {
                            json!({"type":"status","ok":false,"what":what,"code":code,"index":index,"message":message})
                        } else {
                            requests.sort_by_key(|(_, attacker, defender, col, row)| {
                                (*attacker, *row, *col, *defender)
                            });
                            for (index, attacker_id, defender_id, col, row) in &requests {
                                if let Err(error) = validate_combat_preview(
                                    &state,
                                    *attacker_id,
                                    *defender_id,
                                    Hex::from_offset(*col, *row),
                                    n_sims as u32,
                                ) {
                                    invalid =
                                        Some((*index, format!("{:?}", error), error.to_string()));
                                    break;
                                }
                            }
                            if let Some((index, code, message)) = invalid.as_ref() {
                                json!({"type":"status","ok":false,"what":what,"code":code,"index":index,"message":message})
                            } else {
                                let previews = requests.into_iter().map(|(_, attacker_id, defender_id, col, row)| {
                                    let preview = preview_combat(&state, attacker_id, defender_id, Hex::from_offset(col, row), n_sims as u32).expect("validated combat preview");
                                    json!({"attacker_id":attacker_id,"defender_id":defender_id,"col":col,"row":row,"body":preview})
                                }).collect::<Vec<_>>();
                                json!({"type":"status","ok":true,"what":what,"body":{"previews":previews}})
                            }
                        }
                    }
                }
                "turn_options" => {
                    let mut ids: Vec<u32> = state
                        .units
                        .iter()
                        .filter_map(|(&id, unit)| {
                            (unit.faction == state.active_faction
                                && (!unit.moved || !unit.attacked))
                                .then_some(id)
                        })
                        .collect();
                    ids.sort_unstable();
                    let mut options = Vec::new();
                    for id in ids {
                        let unit = &state.units[&id];
                        let current = state.positions[&id];
                        let mut positions = Vec::new();
                        // The unit's present hex and its reachable hexes are both
                        // valid attack origins, but only the latter are Move
                        // destinations: `legal_moves` already excludes the origin
                        // (game_state.rs: `*h != from`), and Move onto your own hex
                        // returns DestinationOccupied. Mark the standing entry so a
                        // consumer can tell "attack from here" from "move here".
                        // Without it the two are indistinguishable, and every client
                        // that has consumed this payload has eventually issued a Move
                        // to the hex the unit was already on.
                        if !unit.attacked {
                            let (c, r) = current.to_offset();
                            positions.push(json!({"col":c,"row":r,"current":true,"movable":false,"target_ids":legal_targets(&state,id,current).unwrap_or_default()}));
                        }
                        if !unit.moved {
                            for hex in legal_moves(&state, id).unwrap_or_default() {
                                let (c, r) = hex.to_offset();
                                positions.push(json!({"col":c,"row":r,"current":false,"movable":true,"target_ids":legal_targets(&state,id,hex).unwrap_or_default()}));
                            }
                        }
                        positions.sort_by_key(|value| {
                            (
                                value.get("row").and_then(Value::as_i64).unwrap_or(0),
                                value.get("col").and_then(Value::as_i64).unwrap_or(0),
                            )
                        });
                        options.push(json!({"unit_id":id,"positions":positions}));
                    }
                    json!({"type":"status","ok":true,"what":what,"body":{"units":options}})
                }
                "recruit_options" => {
                    let side = state.active_faction as usize;
                    let faction = &factions[side];
                    let mut placement_hexes: Vec<Hex> = state
                        .units
                        .iter()
                        .filter(|(_, unit)| {
                            unit.faction == state.active_faction && unit.can_recruit
                        })
                        .filter_map(|(id, _)| state.positions.get(id))
                        .filter(|h| {
                            state
                                .board
                                .tile_at(**h)
                                .is_some_and(|tile| tile.terrain_id == "keep")
                        })
                        .flat_map(|h| h.neighbors())
                        .filter(|dest| {
                            state
                                .board
                                .tile_at(*dest)
                                .is_some_and(|tile| tile.terrain_id == "castle")
                                && !state.hex_to_unit.contains_key(dest)
                        })
                        .collect();
                    placement_hexes.sort_unstable_by_key(|hex| {
                        let (col, row) = hex.to_offset();
                        (row, col)
                    });
                    placement_hexes.dedup();
                    let placement_hexes: Vec<Value> = placement_hexes
                        .into_iter()
                        .map(|h| {
                            let (c, r) = h.to_offset();
                            json!({"col":c,"row":r})
                        })
                        .collect();
                    let options: Vec<Value> = faction.recruits.iter().filter_map(|id| units.get(id).map(|d| json!({"def_id":id,"cost":d.cost,"affordable":state.gold[side] >= d.cost}))).collect();
                    json!({"type":"status","ok":true,"what":what,"body":{"faction_id":faction.def.id,"side_can_place":!placement_hexes.is_empty(),"placement_hexes":placement_hexes,"options":options,"batch_macro_enabled":!c.disable_recruit_batch}})
                }
                _ => {
                    json!({"type":"status","ok":false,"what":what,"code":"unknown_query","message":"unknown query"})
                }
            };
            query_elapsed += query_started.elapsed();
            if let Some(object) = response.as_object_mut() {
                object.insert("state_revision".into(), json!(state.state_revision));
            }
            if query_elapsed > query_budget {
                println!(
                    "{}",
                    json!({"type":"status","ok":false,"code":"query_timeout","message":"query budget exceeded"})
                );
                io::stdout().flush().unwrap();
                continue;
            }
            let response_line = serde_json::to_string(&response).unwrap_or_else(|_| {
                serde_json::to_string(&json!({
                    "type":"status",
                    "ok":false,
                    "code":"internal_error",
                    "message":"failed to encode query response"
                }))
                .unwrap()
            });
            if response_line.len() > 16 * 1024 * 1024 {
                println!(
                    "{}",
                    json!({
                        "type":"status",
                        "ok":false,
                        "code":"reply_too_large",
                        "message":"query response exceeds 16 MiB"
                    })
                );
            } else {
                println!("{}", response_line);
            }
            io::stdout().flush().unwrap();
            continue;
        }
        let orders = if let Some(array) = parsed.as_array() {
            array.clone()
        } else {
            vec![parsed]
        };
        if orders.is_empty() {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"parse","message":"empty action batch"})
            );
            continue;
        }
        if orders.len() > 256 {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"batch_too_large","message":"action batch exceeds 256 objects"})
            );
            continue;
        }
        if action_count.saturating_add(orders.len() as u32) > 256 {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"action_limit","message":"side-turn action limit exceeded"})
            );
            continue;
        }
        let names: Vec<Option<&str>> = orders
            .iter()
            .map(|o| o.get("action").and_then(Value::as_str))
            .collect();
        if names.iter().any(|name| *name == Some("Query")) {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"parse","message":"Query must be a singleton line"})
            );
            continue;
        }
        if names.iter().any(|name| {
            name.is_none()
                || !matches!(
                    name,
                    Some(
                        "Move"
                            | "Attack"
                            | "Recruit"
                            | "RecruitBatch"
                            | "Engage"
                            | "EndTurn"
                            | "Advance"
                    )
                )
        }) {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"unknown_action","message":"unknown or missing action"})
            );
            continue;
        }
        if orders.iter().any(|order| !valid_action_shape(order)) {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"parse","message":"invalid action shape"})
            );
            continue;
        }
        if let Err((code, message)) = authorize_model_batch(&orders, &state, c.llm_side) {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":code,"message":message})
            );
            io::stdout().flush().unwrap();
            continue;
        }
        let end_turn_count = names
            .iter()
            .filter(|name| **name == Some("EndTurn"))
            .count();
        let valid_boundary = if c.incremental_turns {
            end_turn_count <= 1
                && (end_turn_count == 0 || matches!(names.last(), Some(Some("EndTurn"))))
                && (end_turn_count == 1 || partial_batches < 3)
        } else {
            end_turn_count == 1 && matches!(names.last(), Some(Some("EndTurn")))
        };
        if !valid_boundary {
            println!(
                "{}",
                json!({"type":"status","ok":false,"code":"parse","message":"invalid action batch structure"})
            );
            continue;
        }
        let batch_len = orders.len() as u32;
        let BatchExecution {
            state: batch_state,
            next_id: batch_next_id,
            results,
            events,
            did_end,
            forecasts: _,
            sequence_attacks: _,
            attack_sequences: _,
            pre_end_threats: _,
            preview_error: _,
            post_combat_conditional: _,
            conditional_unit_ids: _,
            pre_end_recruitment_remaining: _,
            pre_end_exposure: _,
        } = execute_model_batch(
            state.clone(),
            next_id,
            &orders,
            c.llm_side,
            &factions,
            &units,
            c.disable_recruit_batch,
            true,
        );
        let batch_succeeded = results
            .iter()
            .all(|result| result.get("ok") == Some(&Value::Bool(true)));
        if batch_succeeded {
            if did_end {
                match write_checkpoint(
                    c,
                    &batch_state,
                    side_turns + 1,
                    batch_next_id,
                    "postbatch",
                    true,
                ) {
                    Ok(Some(reference)) => {
                        println!("{}", reference);
                        io::stdout().flush().unwrap();
                    }
                    Ok(None) => {}
                    Err(message) => {
                        println!(
                            "{}",
                            json!({"type":"game_end","reason":"checkpoint_error","message":message})
                        );
                        break;
                    }
                }
            }
            state = batch_state;
            next_id = batch_next_id;
            action_count += batch_len;
        }
        println!(
            "{}",
            json!({"type":"status","ok":true,"results":results,
            "state_revision":state.state_revision})
        );
        io::stdout().flush().unwrap();
        print_events(&events, "llm", "llm");
        if did_end && state.check_winner().is_none() {
            partial_batches = 0;
            side_turns += 1;
            if side_turns >= c.max_turns {
                println!(
                    "{}",
                    json!({"type":"game_end","reason":"max_turns","turns":state.turn,"side_turns":side_turns})
                );
                terminal = true;
                break;
            }
            let greedy_side = 1 - c.llm_side;
            let greedy_events = match run_driver_greedy_turn(
                &mut state,
                greedy_side,
                &factions[greedy_side as usize],
                &units,
                &mut next_id,
            ) {
                Ok(events) => events,
                Err(_) => {
                    println!("{}", greedy_infrastructure_failure(&state, side_turns));
                    terminal = true;
                    break;
                }
            };
            side_turns += 1;
            print_events(&greedy_events, "greedy", "greedy");
        }
        if let Some(winner) = state.check_winner() {
            println!(
                "{}",
                json!({"type":"game_end","reason":"winner","winner":winner,"turns":state.turn})
            );
            terminal = true;
            break;
        }
        if side_turns >= c.max_turns {
            println!(
                "{}",
                json!({"type":"game_end","reason":"max_turns","turns":state.turn,"side_turns":side_turns})
            );
            terminal = true;
            break;
        }
        if did_end {
            query_count = 0;
            query_elapsed = Duration::ZERO;
            action_count = 0;
            if let Ok(Some(reference)) =
                write_checkpoint(c, &state, side_turns, next_id, "model", false)
            {
                println!("{}", reference);
                io::stdout().flush().unwrap();
            }
            print_boundary(&state, &units, false);
            deadline = Instant::now() + Duration::from_secs(c.turn_timeout);
        } else if c.incremental_turns && batch_succeeded {
            partial_batches += 1;
            if let Ok(Some(reference)) =
                write_checkpoint(c, &state, side_turns, next_id, "partial", false)
            {
                println!("{}", reference);
                io::stdout().flush().unwrap();
            }
            print_boundary(&state, &units, true);
        }
    }
    if !terminal && state.check_winner().is_none() {
        println!(
            "{}",
            json!({"type":"game_end","reason":"eof","turns":state.turn})
        );
    }
}

fn main() {
    let c = parse_args();

    if c.scripted {
        scripted_game(&c);
    } else {
        interactive_protocol_game(&c);
    }
}

#[cfg(test)]
mod protocol_tests {
    use super::*;

    #[test]
    fn greedy_planner_failure_rolls_back_real_recruitment_and_accounting() {
        let config = Config {
            scenario: "big_battle_6".into(),
            faction0: "undead".into(),
            faction1: "undead".into(),
            gold: 100,
            seed: 42,
            scripted: false,
            llm_side: 0,
            max_turns: 4,
            turn_timeout: 1,
            query_timeout: 1,
            max_queries: 1,
            disable_recruit_batch: false,
            incremental_turns: false,
            checkpoint_dir: None,
            resume_checkpoint: None,
        };
        let (mut state, faction0, _, units) = init_game(&config).expect("valid fixture");
        let before = state.clone();
        let before_next_id = state.next_unit_id;
        let mut next_id = state.next_unit_id;
        let result = run_driver_greedy_turn_with_failure(
            &mut state,
            0,
            &faction0,
            &units,
            &mut next_id,
            Some("planner"),
        );

        assert!(matches!(result, Err(GreedyTurnError::Callback(_))));
        assert_eq!(state.gold, before.gold);
        assert_eq!(format!("{:?}", state.units), format!("{:?}", before.units));
        assert_eq!(state.positions, before.positions);
        assert_eq!(state.next_unit_id, before_next_id);
        assert_eq!(next_id, before_next_id);
        assert_eq!(state.active_faction, before.active_faction);
        assert_eq!(state.turn, before.turn);
    }

    #[test]
    fn failed_batch_attempt_does_not_commit_castle_vacate_or_accounting() {
        let config = Config {
            scenario: "big_battle_6".into(),
            faction0: "undead".into(),
            faction1: "undead".into(),
            gold: 0,
            seed: 42,
            scripted: false,
            llm_side: 0,
            max_turns: 4,
            turn_timeout: 1,
            query_timeout: 1,
            max_queries: 1,
            disable_recruit_batch: false,
            incremental_turns: false,
            checkpoint_dir: None,
            resume_checkpoint: None,
        };
        let (mut state, faction0, _, units) = init_game(&config).expect("valid fixture");
        let castle = Hex::from_offset(2, 6);
        let def = units.get("Skeleton").expect("fixture unit");
        state.place_unit(Unit::from_def(state.next_unit_id, def, 0), castle);
        state.next_unit_id += 1;
        let before = state.clone();
        let mut next_id = state.next_unit_id;
        let mut events = Vec::new();

        let result = recruit_batch_with_events(
            &mut state,
            0,
            &faction0,
            &units,
            &mut next_id,
            "Skeleton",
            1,
            &mut events,
        );

        assert_eq!(
            result,
            Err(norrust_core::game_state::ActionError::NotEnoughGold)
        );
        assert_eq!(state.gold, before.gold);
        assert_eq!(format!("{:?}", state.units), format!("{:?}", before.units));
        assert_eq!(state.positions, before.positions);
        assert_eq!(state.hex_to_unit, before.hex_to_unit);
        assert_eq!(state.next_unit_id, before.next_unit_id);
        assert_eq!(next_id, before.next_unit_id);
        assert!(events.is_empty());
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn checkpoint_is_digest_named_and_round_trips_atomically() {
        let dir =
            std::env::temp_dir().join(format!("norrust-checkpoint-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        let config = Config {
            scenario: "big_battle_6".into(),
            faction0: "undead".into(),
            faction1: "undead".into(),
            gold: 300,
            seed: 42,
            scripted: false,
            llm_side: 0,
            max_turns: 4,
            turn_timeout: 1,
            query_timeout: 1,
            max_queries: 1,
            disable_recruit_batch: false,
            incremental_turns: false,
            checkpoint_dir: Some(dir.clone()),
            resume_checkpoint: None,
        };
        let state = GameState::new_seeded(norrust_core::board::Board::new(1, 1), 42);
        let reference = write_checkpoint(&config, &state, 0, 1, "model", false)
            .expect("write checkpoint")
            .expect("checkpoint reference");
        let path = dir.join(reference["path"].as_str().expect("path"));
        assert!(path.exists());
        assert!(path
            .file_name()
            .unwrap()
            .to_string_lossy()
            .contains("-model-"));
        let restored = read_checkpoint(&path).expect("read checkpoint");
        assert_eq!(restored.save_state.rng_state, 42);
        assert_eq!(restored.side_turns, 0);
        assert_eq!(restored.boundary, "model");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn authorize_model_batch_rejects_wrong_active_side_including_end_turn() {
        let state = GameState::new(norrust_core::board::Board::new(1, 1));
        let orders = vec![json!({"action":"EndTurn"})];

        assert_eq!(
            authorize_model_batch(&orders, &state, 1),
            Err((
                "unauthorized_side",
                "model actions are not authorized while the opponent is active"
            ))
        );
    }

    #[test]
    fn preview_contract_rejects_malformed_batches_before_execution() {
        let state = GameState::new(norrust_core::board::Board::new(1, 1));
        assert_eq!(
            validate_model_batch_contract(&[], &state, 0),
            Err(("parse", "orders must be a non-empty array"))
        );
        assert_eq!(
            validate_model_batch_contract(&[json!({"action":"Move"})], &state, 0),
            Err(("parse", "invalid action shape"))
        );
        assert_eq!(
            validate_model_batch_contract(
                &[json!({"action":"Move","unit_id":1,"col":0,"row":0})],
                &state,
                0
            ),
            Err(("parse", "invalid action batch structure"))
        );
    }

    #[test]
    fn engage_executes_a_legal_move_and_attack_step() {
        let config = Config {
            scenario: "big_battle_6".into(),
            faction0: "undead".into(),
            faction1: "undead".into(),
            gold: 10,
            seed: 42,
            scripted: false,
            llm_side: 0,
            max_turns: 4,
            turn_timeout: 1,
            query_timeout: 1,
            max_queries: 1,
            disable_recruit_batch: false,
            incremental_turns: false,
            checkpoint_dir: None,
            resume_checkpoint: None,
        };
        let (mut state, faction0, faction1, units) = init_game(&config).expect("valid fixture");
        let (attacker, attacker_hex) = state
            .units
            .values()
            .find_map(|unit| {
                (unit.faction == 0 && !unit.attacks.is_empty())
                    .then(|| (unit.id, state.positions[&unit.id]))
            })
            .expect("fixture has an attacker");
        let target = state
            .units
            .values()
            .find(|unit| unit.faction == 1)
            .map(|unit| unit.id)
            .expect("fixture has a target");
        let target_old_hex = state.positions[&target];
        let target_hex = attacker_hex
            .neighbors()
            .into_iter()
            .find(|hex| state.board.tile_at(*hex).is_some() && !state.hex_to_unit.contains_key(hex))
            .expect("attacker has an open neighboring hex");
        state.positions.insert(target, target_hex);
        state.hex_to_unit.remove(&target_old_hex);
        state.hex_to_unit.insert(target_hex, target);
        let (col, row) = attacker_hex.to_offset();
        let order = json!({
            "action":"Engage",
            "target_id":target,
            "steps":[{"attacker_id":attacker,"col":col,"row":row}]
        });
        assert!(valid_action_shape(&order));
        assert!(authorize_model_batch(&[order.clone()], &state, 0).is_ok());
        let execution = execute_model_batch(
            state,
            100,
            &[order],
            0,
            &[faction0, faction1],
            &units,
            false,
            false,
        );
        assert!(execution
            .results
            .iter()
            .all(|result| result.get("ok") == Some(&Value::Bool(true))));
        assert_eq!(execution.forecasts.len(), 1);
        assert_eq!(execution.attack_sequences.len(), 1);
        assert_eq!(
            execution.attack_sequences[0]["attacker_ids"],
            json!([attacker])
        );
    }

    #[test]
    fn preview_captures_pre_end_threats_without_mutating_source_rng() {
        let config = Config {
            scenario: "big_battle_6".into(),
            faction0: "undead".into(),
            faction1: "undead".into(),
            gold: 10,
            seed: 42,
            scripted: false,
            llm_side: 0,
            max_turns: 4,
            turn_timeout: 1,
            query_timeout: 1,
            max_queries: 1,
            disable_recruit_batch: false,
            incremental_turns: false,
            checkpoint_dir: None,
            resume_checkpoint: None,
        };
        let (state, faction0, faction1, units) = init_game(&config).expect("valid fixture");
        let before_rng = state.rng.state();
        let execution = execute_model_batch(
            state.clone(),
            state.next_unit_id,
            &[json!({"action":"EndTurn"})],
            0,
            &[faction0, faction1],
            &units,
            false,
            false,
        );

        assert_eq!(state.rng.state(), before_rng);
        assert_eq!(execution.state.rng.state(), before_rng);
        assert!(execution.pre_end_threats.is_some());
        assert!(execution.forecasts.is_empty());
    }
}
