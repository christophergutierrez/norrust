//! C ABI bridge for LuaJIT FFI and other foreign callers.
//!
//! All functions use the `norrust_` prefix and operate on an opaque `*mut NorRustEngine`.
//! String returns are caller-owned: free with `norrust_free_string()`.
//! Integer arrays are caller-owned: free with `norrust_free_int_array()`.
//!
//! # Return value conventions
//!
//! | Function category         | Success           | Failure            |
//! |---------------------------|-------------------|--------------------|
//! | Load / lifecycle          | `1`               | `0`                |
//! | Action / mutation         | `0`               | negative error code|
//! | Placement (unit_id back)  | positive unit_id  | `-1`               |
//! | Scalar queries            | the value         | `-1` (or `0`)      |
//! | String queries            | valid `*mut c_char` | empty string ptr |

use std::collections::{HashMap, HashSet};
use std::ffi::{c_char, CStr, CString};
use std::panic;
use std::path::PathBuf;

use serde::Serialize;

use crate::board::Tile;
use crate::campaign::{self, CampaignState};
use crate::combat::{simulate_combat, time_of_day, Rng, TimeOfDay};
use crate::dialogue::DialogueState;
use crate::game_state::{apply_action, apply_recruit, Action, ActionError, GameState, PendingSpawn, TriggerZone};
use crate::hex::Hex;
use crate::loader::Registry;
use crate::pathfinding::{find_path, get_zoc_hexes, reachable_hexes};
use crate::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use crate::save::SaveState;
use crate::snapshot::{ActionRequest, StateSnapshot};
use crate::unit::{advance_unit, Unit};

// ── FFI helper macros ────────────────────────────────────────────────────────

/// Dereference the engine pointer, returning `$fail` if null.
/// Binds `$e: &mut NorRustEngine`.
macro_rules! with_engine {
    ($ptr:expr, $e:ident, $fail:expr, $body:block) => {{
        let Some($e) = (unsafe { $ptr.as_mut() }) else { return $fail };
        $body
    }};
}

/// Dereference the engine pointer AND its `game` field, returning `$fail` if either is None.
/// Binds `$e: &mut NorRustEngine` and `$state: &mut GameState`.
/// Automatically invalidates `state_cache` after the body runs.
macro_rules! with_game_mut {
    ($ptr:expr, $e:ident, $state:ident, $fail:expr, $body:block) => {{
        let Some($e) = (unsafe { $ptr.as_mut() }) else { return $fail };
        let Some($state) = $e.game.as_mut() else { return $fail };
        let __result = $body;
        $e.state_cache = None;
        __result
    }};
}

/// Dereference the engine pointer AND its `game` field (immutable), returning `$fail` if either is None.
/// Binds `$e: &NorRustEngine` and `$state: &GameState`.
macro_rules! with_game_ref {
    ($ptr:expr, $e:ident, $state:ident, $fail:expr, $body:block) => {{
        let Some($e) = (unsafe { $ptr.as_ref() }) else { return $fail };
        let Some($state) = $e.game.as_ref() else { return $fail };
        $body
    }};
}

// ── Engine struct ────────────────────────────────────────────────────────────

/// Opaque engine handle exposed through the C ABI.
pub struct NorRustEngine {
    units: Option<Registry<UnitDef>>,
    terrain: Option<Registry<TerrainDef>>,
    game: Option<GameState>,
    factions: Vec<(FactionDef, Vec<String>)>,
    dialogue_state: Option<DialogueState>,
    /// Cached JSON from `norrust_get_state_json`. `None` means dirty.
    state_cache: Option<String>,
    /// Campaign progression state (None for standalone scenarios).
    campaign: Option<CampaignState>,
    /// Path to the loaded board.toml (for save serialization).
    board_path: Option<String>,
    /// Path to the loaded dialogue.toml (for save serialization).
    dialogue_path: Option<String>,
    /// Human-readable scenario name (for save list UI).
    display_name: Option<String>,
}

impl NorRustEngine {
    fn new() -> Self {
        Self {
            units: None,
            terrain: None,
            game: None,
            factions: Vec::new(),
            dialogue_state: None,
            state_cache: None,
            campaign: None,
            board_path: None,
            dialogue_path: None,
            display_name: None,
        }
    }
}

// ── Helpers ──────────────────────────────────────────────────────────────────

fn action_err_code(e: ActionError) -> i32 {
    match e {
        ActionError::UnitNotFound(_)        => -1,
        ActionError::NotYourTurn            => -2,
        ActionError::DestinationOutOfBounds => -3,
        ActionError::DestinationOccupied    => -4,
        ActionError::UnitAlreadyMoved       => -5,
        ActionError::DestinationUnreachable => -6,
        ActionError::NotAdjacent            => -7,
        ActionError::NotEnoughGold          => -8,
        ActionError::DestinationNotCastle   => -9,
        ActionError::LeaderNotOnKeep        => -10,
    }
}

/// Convert a C string pointer to a Rust &str. Returns "" for null or invalid UTF-8.
unsafe fn cstr_to_str<'a>(s: *const c_char) -> &'a str {
    if s.is_null() {
        return "";
    }
    CStr::from_ptr(s).to_str().unwrap_or("")
}

/// Allocate a C string from a Rust string. Caller must free with norrust_free_string.
fn to_c_string(s: &str) -> *mut c_char {
    CString::new(s).unwrap_or_default().into_raw()
}

// ── Serde helper structs for JSON serialization ─────────────────────────────

#[derive(Serialize)]
struct FactionIdEntry<'a> {
    id: &'a str,
    name: &'a str,
}

#[derive(Serialize)]
struct TerrainInfoJson<'a> {
    terrain_id: &'a str,
    defense: u32,
    movement_cost: u32,
    base_defense: u32,
    base_movement_cost: u32,
    healing: u32,
}

#[derive(Serialize)]
struct CombatPreviewJson<'a> {
    attacker_hit_pct: u32,
    defender_hit_pct: u32,
    attacker_damage_per_hit: u32,
    attacker_strikes: u32,
    defender_damage_per_hit: u32,
    defender_strikes: u32,
    attacker_damage_min: u32,
    attacker_damage_max: u32,
    attacker_damage_mean: f64,
    defender_damage_min: u32,
    defender_damage_max: u32,
    defender_damage_mean: f64,
    attacker_kill_pct: f64,
    defender_kill_pct: f64,
    attacker_attack_name: &'a str,
    defender_attack_name: &'a str,
    attacker_hp: u32,
    defender_hp: u32,
    attacker_terrain_defense: u32,
    defender_terrain_defense: u32,
}

#[derive(Serialize)]
struct CampaignScenarioJson<'a> {
    board: &'a str,
    units: &'a str,
    preset_units: bool,
}

#[derive(Serialize)]
struct CampaignDefJson<'a> {
    id: &'a str,
    name: &'a str,
    faction_0: &'a str,
    faction_1: &'a str,
    gold_carry_percent: u32,
    early_finish_bonus: u32,
    scenarios: Vec<CampaignScenarioJson<'a>>,
}

#[derive(Serialize)]
struct DialogueEntryJson<'a> {
    id: &'a str,
    text: &'a str,
}

/// Build a fully populated Unit from the registry, same as gdext_node place_unit_at.
fn unit_from_registry(
    engine: &NorRustEngine,
    unit_id: u32,
    def_id: &str,
    faction: u8,
) -> Unit {
    if let Some(def) = engine.units.as_ref().and_then(|r| r.get(def_id)) {
        Unit::from_def(unit_id, def, faction)
    } else {
        Unit::new(unit_id, def_id.to_string(), 0, faction)
    }
}

/// Upgrade all board tiles from the terrain registry (collect-then-apply pattern).
fn upgrade_tiles_mut(engine: &mut NorRustEngine) {
    let Some(registry) = engine.terrain.as_ref() else { return };
    let Some(state) = engine.game.as_ref() else { return };
    let width = state.board.width as i32;
    let height = state.board.height as i32;
    let assignments: Vec<(Hex, Tile)> = (0..width)
        .flat_map(|col| (0..height).map(move |row| (col, row)))
        .filter_map(|(col, row)| {
            let hex = Hex::from_offset(col, row);
            let terrain_id = state.board.terrain_at(hex)?.to_string();
            let def = registry.get(&terrain_id)?;
            Some((hex, Tile::from_def(def)))
        })
        .collect();
    if let Some(state) = engine.game.as_mut() {
        for (hex, tile) in assignments {
            state.board.set_tile(hex, tile);
        }
    }
}

// ── Lifecycle ────────────────────────────────────────────────────────────────

#[no_mangle]
pub extern "C" fn norrust_new() -> *mut NorRustEngine {
    Box::into_raw(Box::new(NorRustEngine::new()))
}

#[no_mangle]
pub unsafe extern "C" fn norrust_free(engine: *mut NorRustEngine) {
    if !engine.is_null() {
        drop(Box::from_raw(engine));
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_free_string(s: *mut c_char) {
    if !s.is_null() {
        drop(CString::from_raw(s));
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_free_int_array(arr: *mut i32, len: i32) {
    if !arr.is_null() && len > 0 {
        drop(Vec::from_raw_parts(arr, len as usize, len as usize));
    }
}

// ── Data loading ─────────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_get_core_version() -> *mut c_char {
    to_c_string("0.1.0")
}

#[no_mangle]
pub unsafe extern "C" fn norrust_load_data(
    engine: *mut NorRustEngine,
    data_path: *const c_char,
) -> i32 {
    with_engine!(engine, e, 0, {
        let base = PathBuf::from(cstr_to_str(data_path));

        match Registry::<UnitDef>::load_from_dir(&base.join("units")) {
            Ok(registry) => e.units = Some(registry),
            Err(_) => return 0,
        }
        match Registry::<TerrainDef>::load_from_dir(&base.join("terrain")) {
            Ok(registry) => e.terrain = Some(registry),
            Err(_) => return 0,
        }
        1
    })
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_unit_max_hp(
    engine: *mut NorRustEngine,
    unit_id: *const c_char,
) -> i32 {
    let Some(e) = engine.as_ref() else { return -1 };
    let id = cstr_to_str(unit_id);
    e.units.as_ref()
        .and_then(|r| r.get(id))
        .map(|u| u.max_hp as i32)
        .unwrap_or(-1)
}

// ── Game initialization ──────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_create_game(
    engine: *mut NorRustEngine,
    cols: i32,
    rows: i32,
    seed: i64,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    if cols <= 0 || rows <= 0 || seed <= 0 { return 0; }
    let board = crate::board::Board::new(cols as u32, rows as u32);
    e.game = Some(GameState::new_seeded(board, seed as u64));
    e.state_cache = None;
    1
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_terrain_at(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
    terrain_id: *const c_char,
) {
    let Some(e) = engine.as_mut() else { return };
    let tid = cstr_to_str(terrain_id).to_string();
    let hex = Hex::from_offset(col, row);
    let Some(state) = e.game.as_mut() else { return };

    if let Some(def) = e.terrain.as_ref().and_then(|r| r.get(&tid)) {
        state.board.set_tile(hex, Tile::from_def(def));
    } else {
        state.board.set_terrain(hex, tid);
    }
    e.state_cache = None;
}

#[no_mangle]
pub unsafe extern "C" fn norrust_generate_map(
    engine: *mut NorRustEngine,
    seed: i64,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    if seed <= 0 { return 0; }
    let Some(state) = e.game.as_mut() else { return 0 };
    crate::mapgen::generate_map(&mut state.board, seed as u64);
    upgrade_tiles_mut(e);
    e.state_cache = None;
    1
}

#[no_mangle]
pub unsafe extern "C" fn norrust_load_board(
    engine: *mut NorRustEngine,
    board_path: *const c_char,
    seed: i64,
) -> i32 {
    panic::catch_unwind(panic::AssertUnwindSafe(|| {
        let Some(e) = (unsafe { engine.as_mut() }) else { return 0 };
        if seed <= 0 { return 0; }
        let path_str = unsafe { cstr_to_str(board_path) };
        let path = PathBuf::from(path_str);
        let loaded = match crate::scenario::load_board(&path) {
            Ok(b) => b,
            Err(_) => return 0,
        };
        let mut state = GameState::new_seeded(loaded.board, seed as u64);
        state.objective_hex = loaded.objective_hex;
        state.max_turns = loaded.max_turns;
        e.game = Some(state);
        e.board_path = Some(path_str.to_string());
        upgrade_tiles_mut(e);
        e.state_cache = None;
        1
    })).unwrap_or(0)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_load_units(
    engine: *mut NorRustEngine,
    units_path: *const c_char,
) -> i32 {
    panic::catch_unwind(panic::AssertUnwindSafe(|| {
        let Some(e) = (unsafe { engine.as_mut() }) else { return 0 };
        if e.game.is_none() { return 0; }
        let path = PathBuf::from(unsafe { cstr_to_str(units_path) });
        let units_def = match crate::scenario::load_units_file(&path) {
            Ok(d) => d,
            Err(_) => return 0,
        };

        // Place units and track highest ID
        let mut max_id: u32 = 0;
        for p in &units_def.units {
            let unit = unit_from_registry(e, p.id, &p.unit_type, p.faction as u8);
            let hex = Hex::from_offset(p.col, p.row);
            if let Some(state) = e.game.as_mut() {
                state.place_unit(unit, hex);
            }
            if p.id > max_id { max_id = p.id; }
        }

        // Set next_unit_id above all placed units
        if let Some(state) = e.game.as_mut() {
            state.next_unit_id = max_id + 1;
        }

        // Resolve trigger zones from the parsed file
        for tdef in units_def.triggers {
            let mut spawns = Vec::new();
            for s in &tdef.spawns {
                let Some(state) = e.game.as_mut() else { continue };
                let uid = state.next_unit_id;
                state.next_unit_id += 1;
                let unit = unit_from_registry(e, uid, &s.unit_type, s.faction);
                spawns.push(PendingSpawn {
                    unit,
                    destination: Hex::from_offset(s.col, s.row),
                });
            }
            if let Some(state) = e.game.as_mut() {
                state.trigger_zones.push(TriggerZone {
                    trigger_hex: Hex::from_offset(tdef.trigger_col, tdef.trigger_row),
                    trigger_faction: tdef.trigger_faction,
                    spawns,
                    triggered: false,
                });
            }
        }

        e.state_cache = None;
        1
    })).unwrap_or(0)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_terrain_at(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) -> *mut c_char {
    with_game_ref!(engine, _e, state, to_c_string(""), {
        let tid = state.board.terrain_at(Hex::from_offset(col, row)).unwrap_or("");
        to_c_string(tid)
    })
}

// ── Unit management ──────────────────────────────────────────────────────────

/// Place a new unit on the board. The engine auto-assigns the next available unit ID.
/// Returns the assigned unit_id (positive) or -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn norrust_place_unit_at(
    engine: *mut NorRustEngine,
    def_id: *const c_char,
    faction: i32,
    col: i32,
    row: i32,
) -> i32 {
    panic::catch_unwind(panic::AssertUnwindSafe(|| {
        let Some(e) = (unsafe { engine.as_mut() }) else { return -1 };
        let did = unsafe { cstr_to_str(def_id) };
        let Some(state) = e.game.as_mut() else { return -1 };
        let uid = state.next_unit_id;
        state.next_unit_id += 1;
        let unit = unit_from_registry(e, uid, did, faction as u8);
        let Some(state) = e.game.as_mut() else { return -1 };
        state.place_unit(unit, Hex::from_offset(col, row));
        e.state_cache = None;
        uid as i32
    })).unwrap_or(-1)
}

/// Place a unit with an explicit unit_id (for save/load restoration).
/// Returns the unit_id on success, -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn norrust_restore_unit_at(
    engine: *mut NorRustEngine,
    unit_id: i32,
    def_id: *const c_char,
    faction: i32,
    col: i32,
    row: i32,
) -> i32 {
    panic::catch_unwind(panic::AssertUnwindSafe(|| {
        let Some(e) = (unsafe { engine.as_mut() }) else { return -1 };
        let did = unsafe { cstr_to_str(def_id) };
        let unit = unit_from_registry(e, unit_id as u32, did, faction as u8);
        let Some(state) = e.game.as_mut() else { return -1 };
        state.place_unit(unit, Hex::from_offset(col, row));
        // Keep next_unit_id above all placed units
        if (unit_id as u32) >= state.next_unit_id {
            state.next_unit_id = unit_id as u32 + 1;
        }
        e.state_cache = None;
        unit_id
    })).unwrap_or(-1)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_remove_unit_at(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) -> i32 {
    with_game_mut!(engine, _e, state, 0, {
        let target = Hex::from_offset(col, row);
        let Some(uid) = state.hex_to_unit.remove(&target) else { return 0 };
        state.units.remove(&uid);
        state.positions.remove(&uid);
        1
    })
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_unit_cost(
    engine: *mut NorRustEngine,
    def_id: *const c_char,
) -> i32 {
    let Some(e) = engine.as_ref() else { return 0 };
    let id = cstr_to_str(def_id);
    e.units.as_ref()
        .and_then(|r| r.get(id))
        .map(|u| u.cost as i32)
        .unwrap_or(0)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_unit_level(
    engine: *mut NorRustEngine,
    def_id: *const c_char,
) -> i32 {
    let Some(e) = engine.as_ref() else { return 1 };
    let id = cstr_to_str(def_id);
    e.units.as_ref()
        .and_then(|r| r.get(id))
        .map(|u| u.level as i32)
        .unwrap_or(1)
}

// ── Recruitment ──────────────────────────────────────────────────────────────

/// Recruit a unit at the given hex. The engine auto-assigns the next available unit ID.
/// Returns the assigned unit_id (positive) on success, or a negative error code on failure.
#[no_mangle]
pub unsafe extern "C" fn norrust_recruit_unit_at(
    engine: *mut NorRustEngine,
    def_id: *const c_char,
    col: i32,
    row: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    if e.game.is_none() { return -1; }
    let did = cstr_to_str(def_id).to_string();

    let cost = match e.units.as_ref().and_then(|r| r.get(&did)) {
        Some(def) => def.cost,
        None => return -1,
    };

    let (faction, uid) = {
        let Some(state) = e.game.as_mut() else { return -1 };
        let uid = state.next_unit_id;
        state.next_unit_id += 1;
        (state.active_faction, uid)
    };
    let unit = unit_from_registry(e, uid, &did, faction);

    let destination = Hex::from_offset(col, row);
    let Some(state) = e.game.as_mut() else { return -1 };
    match apply_recruit(state, unit, destination, cost) {
        Ok(()) => {
            e.state_cache = None;
            uid as i32
        }
        Err(err) => {
            e.state_cache = None;
            action_err_code(err)
        }
    }
}

/// AI recruitment: fill castle hexes adjacent to leader's keep.
/// Engine reads next_unit_id from internal state and auto-advances it.
/// Returns the number of units recruited.
#[no_mangle]
pub unsafe extern "C" fn norrust_ai_recruit(
    engine: *mut NorRustEngine,
    faction_id: *const c_char,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    let id = cstr_to_str(faction_id).to_string();
    let recruits: Vec<String> = match e.factions.iter().find(|(f, _)| f.id == id) {
        Some((_, r)) => r.clone(),
        None => return 0,
    };

    let mut recruited = 0i32;
    let mut recruited_counts: HashMap<String, u32> = HashMap::new();
    let mut rotation_idx: usize = 0;

    for _ in 0..12 {
        let action: Option<(String, i32, i32)> = e.game.as_ref().and_then(|state| {
            let active = state.active_faction;
            let keep = state.positions.iter().find_map(|(&u, &hex)| {
                let unit = state.units.get(&u)?;
                if unit.faction != active { return None; }
                if !unit.abilities.iter().any(|a| a == "leader") { return None; }
                state.board.tile_at(hex).filter(|t| t.terrain_id == "keep").map(|_| hex)
            })?;
            let dest = keep.neighbors().iter().copied().find(|&h| {
                state.board.contains(h)
                    && state.board.tile_at(h).map(|t| t.terrain_id == "castle").unwrap_or(false)
                    && !state.hex_to_unit.contains_key(&h)
            })?;
            // Pick affordable units with round-robin: prefer least-recruited type
            let mut affordable: Vec<(&String, u32)> = recruits.iter()
                .filter_map(|did| {
                    e.units.as_ref()
                        .and_then(|r| r.get(did.as_str()))
                        .filter(|def| state.gold[active as usize] >= def.cost)
                        .map(|def| (did, def.cost))
                })
                .collect();
            if affordable.is_empty() { return None; }
            // Sort by: least recruited count, then rotate through ties
            affordable.sort_by_key(|(did, _)| *recruited_counts.get(*did).unwrap_or(&0));
            let min_count = *recruited_counts.get(affordable[0].0).unwrap_or(&0);
            let ties: Vec<_> = affordable.iter()
                .filter(|(did, _)| *recruited_counts.get(*did).unwrap_or(&0) == min_count)
                .collect();
            let pick = ties[rotation_idx % ties.len()];
            let def_id = pick.0;
            let (col, row) = dest.to_offset();
            Some((def_id.clone(), col, row))
        });

        let Some((did, col, row)) = action else { break };

        let cost = match e.units.as_ref().and_then(|r| r.get(&did)) {
            Some(def) => def.cost,
            None => break,
        };
        let Some(state) = e.game.as_mut() else { break };
        let uid = state.next_unit_id;
        state.next_unit_id += 1;
        let faction = state.active_faction;
        let unit = unit_from_registry(e, uid, &did, faction);
        let destination = Hex::from_offset(col, row);

        let Some(state) = e.game.as_mut() else { break };
        match apply_recruit(state, unit, destination, cost) {
            Ok(()) => {
                recruited += 1;
                *recruited_counts.entry(did.clone()).or_insert(0) += 1;
                rotation_idx += 1;
            }
            Err(_) => break,
        }
    }
    e.state_cache = None;
    recruited
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_starting_gold(
    engine: *mut NorRustEngine,
    f0_id: *const c_char,
    f1_id: *const c_char,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    let f0 = cstr_to_str(f0_id).to_string();
    let f1 = cstr_to_str(f1_id).to_string();
    let Some(state) = e.game.as_mut() else { return 0 };
    let gold0 = e.factions.iter().find(|(f, _)| f.id == f0).map(|(f, _)| f.starting_gold);
    let gold1 = e.factions.iter().find(|(f, _)| f.id == f1).map(|(f, _)| f.starting_gold);
    match (gold0, gold1) {
        (Some(g0), Some(g1)) => { state.gold = [g0, g1]; e.state_cache = None; 1 }
        _ => 0,
    }
}

// ── Faction queries ──────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_load_factions(
    engine: *mut NorRustEngine,
    data_path: *const c_char,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    let base = PathBuf::from(cstr_to_str(data_path));

    let groups = match Registry::<RecruitGroup>::load_from_dir(&base.join("recruit_groups")) {
        Ok(r) => r,
        Err(_) => return 0,
    };
    let faction_reg = match Registry::<FactionDef>::load_from_dir(&base.join("factions")) {
        Ok(r) => r,
        Err(_) => return 0,
    };

    e.factions = faction_reg.all().map(|f| {
        let mut recruits: Vec<String> = Vec::new();
        for entry in &f.recruits {
            if let Some(grp) = groups.get(entry) {
                recruits.extend(grp.members.iter().cloned());
            } else {
                recruits.push(entry.clone());
            }
        }
        let mut seen = HashSet::new();
        recruits.retain(|id| seen.insert(id.clone()));
        (f.clone(), recruits)
    }).collect();
    1
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_faction_ids_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let arr: Vec<FactionIdEntry> = e.factions.iter()
        .map(|(f, _)| FactionIdEntry { id: &f.id, name: &f.name })
        .collect();
    match serde_json::to_string(&arr) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_faction_leader(
    engine: *mut NorRustEngine,
    faction_id: *const c_char,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("") };
    let id = cstr_to_str(faction_id);
    let leader = e.factions.iter()
        .find(|(f, _)| f.id == id)
        .map(|(f, _)| f.leader_def.as_str())
        .unwrap_or("");
    to_c_string(leader)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_faction_recruits_json(
    engine: *mut NorRustEngine,
    faction_id: *const c_char,
    max_level: i32,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let id = cstr_to_str(faction_id);
    let Some((_, recruits)) = e.factions.iter().find(|(f, _)| f.id == id) else {
        return to_c_string("[]");
    };
    let filtered: Vec<&str> = recruits.iter()
        .filter(|did| {
            if max_level <= 0 { return true; }
            e.units.as_ref()
                .and_then(|r| r.get(did.as_str()))
                .map(|u| u.level as i32 <= max_level)
                .unwrap_or(true)
        })
        .map(|id| id.as_str())
        .collect();
    match serde_json::to_string(&filtered) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

// ── Game state queries ───────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_get_active_faction(engine: *mut NorRustEngine) -> i32 {
    engine.as_ref()
        .and_then(|e| e.game.as_ref())
        .map(|s| s.active_faction as i32)
        .unwrap_or(-1)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_turn(engine: *mut NorRustEngine) -> i32 {
    engine.as_ref()
        .and_then(|e| e.game.as_ref())
        .map(|s| s.turn as i32)
        .unwrap_or(-1)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_time_of_day_name(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let turn = engine.as_ref()
        .and_then(|e| e.game.as_ref())
        .map(|s| s.turn)
        .unwrap_or(1);
    let name = match time_of_day(turn) {
        TimeOfDay::Day => "Day",
        TimeOfDay::Night => "Night",
        TimeOfDay::Neutral => "Neutral",
    };
    to_c_string(name)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_winner(engine: *mut NorRustEngine) -> i32 {
    with_game_ref!(engine, _e, state, -1, {
        match state.check_winner() {
            Some(f) => f as i32,
            None => -1,
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_objective_hex(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        state.objective_hex = Some(Hex::from_offset(col, row));
    });
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_max_turns(
    engine: *mut NorRustEngine,
    max_turns: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        state.max_turns = if max_turns > 0 { Some(max_turns as u32) } else { None };
    });
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_state_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else { return to_c_string("") };
    let Some(state) = e.game.as_ref() else { return to_c_string("") };
    if let Some(cached) = &e.state_cache {
        return to_c_string(cached);
    }
    match serde_json::to_string(&StateSnapshot::from_game_state(state)) {
        Ok(s) => {
            e.state_cache = Some(s.clone());
            to_c_string(&s)
        }
        Err(_) => to_c_string(""),
    }
}

/// Return game state JSON filtered by fog of war for the given faction.
/// Enemy units on non-visible hexes are hidden. Includes visible_hexes array.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_state_json_fow(
    engine: *mut NorRustEngine,
    faction: i32,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else { return to_c_string("") };
    let Some(state) = e.game.as_ref() else { return to_c_string("") };
    match serde_json::to_string(&StateSnapshot::from_game_state_fow(state, faction as u8)) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string(""),
    }
}

// ── Unit ID management ──────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_get_next_unit_id(engine: *mut NorRustEngine) -> i32 {
    engine.as_ref()
        .and_then(|e| e.game.as_ref())
        .map(|s| s.next_unit_id as i32)
        .unwrap_or(1)
}

// ── Actions ──────────────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_move(
    engine: *mut NorRustEngine,
    unit_id: i32,
    col: i32,
    row: i32,
) -> i32 {
    with_game_mut!(engine, _e, state, -1, {
        match apply_action(state, Action::Move {
            unit_id: unit_id as u32,
            destination: Hex::from_offset(col, row),
        }) {
            Ok(()) => 0,
            Err(err) => action_err_code(err),
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_attack(
    engine: *mut NorRustEngine,
    attacker_id: i32,
    defender_id: i32,
) -> i32 {
    with_game_mut!(engine, _e, state, -1, {
        match apply_action(state, Action::Attack {
            attacker_id: attacker_id as u32,
            defender_id: defender_id as u32,
        }) {
            Ok(()) => 0,
            Err(err) => action_err_code(err),
        }
    })
}

/// Return the advancement options for a unit as a JSON array.
/// Each option: `{"id":"white_mage","name":"White Mage"}`.
/// Returns empty array `[]` if unit has no advancement options.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_advance_options(
    engine: *mut NorRustEngine,
    unit_id: i32,
) -> *mut c_char {
    #[derive(Serialize)]
    struct AdvanceOption { id: String, name: String }

    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let Some(state) = e.game.as_ref() else { return to_c_string("[]") };
    let uid = unit_id as u32;
    let Some(unit) = state.units.get(&uid) else { return to_c_string("[]") };

    let Some(registry) = e.units.as_ref() else { return to_c_string("[]") };
    let Some(current_def) = registry.get(&unit.def_id) else { return to_c_string("[]") };

    let options: Vec<AdvanceOption> = current_def.advances_to.iter()
        .filter_map(|target_id| {
            registry.get(target_id).map(|def| AdvanceOption {
                id: def.id.clone(),
                name: def.name.clone(),
            })
        })
        .collect();

    let json = serde_json::to_string(&options).unwrap_or_else(|_| "[]".to_string());
    to_c_string(&json)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_advance(
    engine: *mut NorRustEngine,
    unit_id: i32,
    target_index: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    let uid = unit_id as u32;

    let (current_def_id, advancement_pending, faction) = {
        let Some(state) = e.game.as_ref() else { return -1 };
        match state.units.get(&uid) {
            Some(u) => (u.def_id.clone(), u.advancement_pending, u.faction),
            None => return -1,
        }
    };

    let Some(state) = e.game.as_ref() else { return -1 };
    if faction != state.active_faction { return -2; }
    if !advancement_pending { return -8; }

    let idx = if target_index < 0 { 0usize } else { target_index as usize };
    let target_def_id = match e.units.as_ref()
        .and_then(|r| r.get(&current_def_id))
        .and_then(|def| def.advances_to.get(idx).cloned())
    {
        Some(id) => id,
        None => return -9,
    };

    let new_def = match e.units.as_ref().and_then(|r| r.get(&target_def_id)) {
        Some(def) => def.clone(),
        None => return -10,
    };

    let Some(state) = e.game.as_mut() else { return -1 };
    let Some(unit) = state.units.get_mut(&uid) else { return -11 };
    advance_unit(unit, &new_def);
    e.state_cache = None;
    0
}

#[no_mangle]
pub unsafe extern "C" fn norrust_end_turn(engine: *mut NorRustEngine) -> i32 {
    with_game_mut!(engine, _e, state, -1, {
        match apply_action(state, Action::EndTurn) {
            Ok(()) => 0,
            Err(err) => action_err_code(err),
        }
    })
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_action_json(
    engine: *mut NorRustEngine,
    json: *const c_char,
) -> i32 {
    panic::catch_unwind(panic::AssertUnwindSafe(|| {
        let Some(e) = (unsafe { engine.as_mut() }) else { return -1 };
        if e.game.is_none() { return -1; }
        let json_str = unsafe { cstr_to_str(json) };
        let req: ActionRequest = match serde_json::from_str(json_str) {
            Ok(r) => r,
            Err(_) => return -99,
        };
        match req {
            ActionRequest::Advance { unit_id, target_index } => {
                unsafe { norrust_apply_advance(engine, unit_id as i32, target_index as i32) }
            }
            ActionRequest::Recruit { def_id, col, row } => {
                let c_def = CString::new(def_id).unwrap_or_default();
                unsafe { norrust_recruit_unit_at(engine, c_def.as_ptr(), col, row) }
            }
            other => {
                let Some(state) = e.game.as_mut() else { return -1 };
                let result = match apply_action(state, other.into()) {
                    Ok(()) => 0,
                    Err(err) => action_err_code(err),
                };
                e.state_cache = None;
                result
            }
        }
    })).unwrap_or(-1)
}

// ── Pathfinding ──────────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_get_reachable_hexes(
    engine: *mut NorRustEngine,
    unit_id: i32,
    out_len: *mut i32,
) -> *mut i32 {
    if !out_len.is_null() { *out_len = 0; }

    let Some(e) = engine.as_ref() else { return std::ptr::null_mut() };
    let Some(state) = e.game.as_ref() else { return std::ptr::null_mut() };
    let uid = unit_id as u32;
    let Some(unit) = state.units.get(&uid) else { return std::ptr::null_mut() };
    let Some(&start) = state.positions.get(&uid) else { return std::ptr::null_mut() };

    let zoc = get_zoc_hexes(state, unit.faction);
    let movement = if unit.slowed { unit.movement / 2 } else { unit.movement };
    let hexes = reachable_hexes(
        &state.board,
        &unit.movement_costs,
        1,
        start,
        movement,
        &zoc,
        false,
    );

    let mut arr: Vec<i32> = Vec::with_capacity(hexes.len() * 2);
    for hex in hexes {
        let (col, row) = hex.to_offset();
        arr.push(col);
        arr.push(row);
    }

    let len = arr.len() as i32;
    if !out_len.is_null() { *out_len = len; }

    if arr.is_empty() {
        return std::ptr::null_mut();
    }

    let boxed = arr.into_boxed_slice();
    Box::into_raw(boxed) as *mut i32
}

/// Find shortest path from a unit's current position to a destination hex.
/// Returns flat [col, row, col, row, ...] array including start and destination.
/// Returns null if no path exists.
#[no_mangle]
pub unsafe extern "C" fn norrust_find_path(
    engine: *mut NorRustEngine,
    unit_id: i32,
    dest_col: i32,
    dest_row: i32,
    out_len: *mut i32,
) -> *mut i32 {
    if !out_len.is_null() { *out_len = 0; }

    let Some(e) = engine.as_ref() else { return std::ptr::null_mut() };
    let Some(state) = e.game.as_ref() else { return std::ptr::null_mut() };
    let uid = unit_id as u32;
    let Some(unit) = state.units.get(&uid) else { return std::ptr::null_mut() };
    let Some(&start) = state.positions.get(&uid) else { return std::ptr::null_mut() };

    let destination = Hex::from_offset(dest_col, dest_row);
    let zoc = get_zoc_hexes(state, unit.faction);
    let is_skirmisher = unit.abilities.iter().any(|a| a == "skirmisher");

    let Some((path, _cost)) = find_path(
        &state.board,
        &unit.movement_costs,
        1,
        start,
        destination,
        unit.movement,
        &zoc,
        is_skirmisher,
    ) else {
        return std::ptr::null_mut();
    };

    let mut arr: Vec<i32> = Vec::with_capacity(path.len() * 2);
    for hex in path {
        let (col, row) = hex.to_offset();
        arr.push(col);
        arr.push(row);
    }

    let len = arr.len() as i32;
    if !out_len.is_null() { *out_len = len; }

    if arr.is_empty() {
        return std::ptr::null_mut();
    }

    let boxed = arr.into_boxed_slice();
    Box::into_raw(boxed) as *mut i32
}

// ── AI helpers ──────────────────────────────────────────────────────────────

/// Move all faction units sitting on castle hexes to nearby non-castle hexes.
/// Uses cheap pathfinding (reachable hexes) instead of full AI evaluation.
fn deploy_castle_units(e: &mut NorRustEngine, faction: u8) {
    let Some(state) = e.game.as_mut() else { return };

    // Find faction units on castle hexes
    let castle_units: Vec<u32> = state.units.iter()
        .filter(|(_, u)| u.faction == faction && !u.attacked)
        .filter(|(&uid, _)| {
            let hex = state.positions[&uid];
            state.board.tile_at(hex).map(|t| t.terrain_id == "castle").unwrap_or(false)
        })
        .map(|(&uid, _)| uid)
        .collect();

    let zoc = crate::pathfinding::get_zoc_hexes(state, faction);

    for uid in castle_units {
        if !state.units.contains_key(&uid) { continue; }
        let start = state.positions[&uid];
        let unit = &state.units[&uid];
        let movement = if unit.slowed { unit.movement / 2 } else { unit.movement };
        let reachable = crate::pathfinding::reachable_hexes(
            &state.board, &unit.movement_costs, 1, start, movement, &zoc, false,
        );
        // Pick nearest non-castle, non-occupied hex
        let occupied: std::collections::HashSet<crate::hex::Hex> = state.hex_to_unit.iter()
            .filter(|(_, &id)| id != uid).map(|(&h, _)| h).collect();
        if let Some(&dest) = reachable.iter()
            .filter(|&&h| h != start && !occupied.contains(&h))
            .filter(|&&h| !state.board.tile_at(h).map(|t| t.terrain_id == "castle" || t.terrain_id == "keep").unwrap_or(true))
            .min_by_key(|&&h| h.distance(start))
        {
            let _ = apply_action(state, Action::Move { unit_id: uid, destination: dest });
        } else if let Some(&dest) = reachable.iter()
            .filter(|&&h| h != start && !occupied.contains(&h))
            .min_by_key(|&&h| h.distance(start))
        {
            // Fallback: any non-occupied reachable hex (even castle)
            let _ = apply_action(state, Action::Move { unit_id: uid, destination: dest });
        }
    }
}

/// FFI: Move all faction units off castle hexes to free slots for recruitment.
#[no_mangle]
pub unsafe extern "C" fn norrust_ai_deploy_recruits(
    engine: *mut NorRustEngine,
    faction: i32,
) {
    if faction < 0 || faction > 1 { return; }
    let Some(e) = engine.as_mut() else { return };
    deploy_castle_units(e, faction as u8);
    e.state_cache = None;
}

/// Compute the cheapest recruit cost for a faction.
/// Uses faction index to look up in `e.factions` (same order as loaded).
fn cheapest_recruit_cost_ref(e: &NorRustEngine, faction: u8) -> u32 {
    let idx = faction as usize;
    let recruits = if idx < e.factions.len() {
        &e.factions[idx].1
    } else {
        return u32::MAX;
    };
    let registry = match e.units.as_ref() {
        Some(r) => r,
        None => return u32::MAX,
    };
    recruits.iter()
        .filter_map(|did| registry.get(did.as_str()).map(|def| def.cost))
        .min()
        .unwrap_or(u32::MAX)
}

/// Build (cost, movement) tuples for all recruitable unit types of a faction.
fn build_recruit_defs(e: &NorRustEngine, faction: u8) -> Vec<(u32, u32)> {
    let idx = faction as usize;
    let recruits = if idx < e.factions.len() {
        &e.factions[idx].1
    } else {
        return Vec::new();
    };
    let registry = match e.units.as_ref() {
        Some(r) => r,
        None => return Vec::new(),
    };
    recruits.iter()
        .filter_map(|did| registry.get(did.as_str()).map(|def| (def.cost, def.movement)))
        .collect()
}

// ── AI ───────────────────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_ai_take_turn(
    engine: *mut NorRustEngine,
    faction: i32,
) {
    if faction < 0 || faction > 1 { return; }
    let Some(e) = engine.as_mut() else { return };
    let cheapest = cheapest_recruit_cost_ref(e, faction as u8);
    let recruit_defs = build_recruit_defs(e, faction as u8);
    let f = faction as u8;

    // Plan the turn (includes Recruit actions for recruit-move-recruit cycle)
    let records = {
        let Some(state) = e.game.as_ref() else { return };
        crate::ai::ai_plan_turn_with_recruits(state, f, cheapest, &recruit_defs)
    };

    // Replay with real recruitment on Recruit actions
    for record in &records {
        match record {
            crate::ai::ActionRecord::Move { unit_id, to_col, to_row } => {
                let Some(state) = e.game.as_mut() else { return };
                if !state.units.contains_key(unit_id) { continue; }
                let dest = crate::hex::Hex::from_offset(*to_col, *to_row);
                let _ = apply_action(state, Action::Move { unit_id: *unit_id, destination: dest });
            }
            crate::ai::ActionRecord::Attack { attacker_id, defender_id } => {
                let Some(state) = e.game.as_mut() else { return };
                if state.units.contains_key(attacker_id) && state.units.contains_key(defender_id) {
                    let _ = apply_action(state, Action::Attack { attacker_id: *attacker_id, defender_id: *defender_id });
                }
            }
            crate::ai::ActionRecord::Recruit => {
                // Real recruitment into freed castle slots
                norrust_ai_recruit(engine, std::ffi::CString::new(
                    e.factions.get(f as usize).map(|(fd, _)| fd.id.as_str()).unwrap_or("")
                ).unwrap_or_default().as_ptr());
                // Deploy: move all faction units off castle hexes
                deploy_castle_units(e, f);
            }
        }
    }

    let Some(state) = e.game.as_mut() else { return };
    let _ = apply_action(state, Action::EndTurn);
    e.state_cache = None;
}

/// Plan an AI turn without modifying the real game state.
/// Returns a JSON array of `ActionRecord` objects.
/// The caller should replay these actions one at a time with animations.
#[no_mangle]
pub unsafe extern "C" fn norrust_ai_plan_turn(
    engine: *mut NorRustEngine,
    faction: i32,
) -> *mut c_char {
    if faction < 0 || faction > 1 { return to_c_string("[]"); }
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let cheapest = cheapest_recruit_cost_ref(e, faction as u8);
    let recruit_defs = build_recruit_defs(e, faction as u8);
    let Some(state) = e.game.as_ref() else { return to_c_string("[]") };
    let records = crate::ai::ai_plan_turn_with_recruits(state, faction as u8, cheapest, &recruit_defs);
    let json = serde_json::to_string(&records).unwrap_or_else(|_| "[]".to_string());
    to_c_string(&json)
}

// ── Campaign ─────────────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_load_campaign(
    _engine: *mut NorRustEngine,
    path: *const c_char,
) -> *mut c_char {
    let p = PathBuf::from(cstr_to_str(path));
    let campaign = match campaign::load_campaign(&p) {
        Ok(c) => c,
        Err(_) => return to_c_string(""),
    };

    let json_obj = CampaignDefJson {
        id: &campaign.id,
        name: &campaign.name,
        faction_0: &campaign.faction_0,
        faction_1: &campaign.faction_1,
        gold_carry_percent: campaign.gold_carry_percent,
        early_finish_bonus: campaign.early_finish_bonus,
        scenarios: campaign.scenarios.iter().map(|s| CampaignScenarioJson {
            board: &s.board,
            units: &s.units,
            preset_units: s.preset_units,
        }).collect(),
    };
    match serde_json::to_string(&json_obj) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string(""),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_survivors_json(
    engine: *mut NorRustEngine,
    faction: i32,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let Some(state) = e.game.as_ref() else { return to_c_string("[]") };
    let survivors = campaign::get_survivors(state, faction as u8);
    match serde_json::to_string(&survivors) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_carry_gold(
    engine: *mut NorRustEngine,
    faction: i32,
    gold_carry_percent: i32,
    early_finish_bonus: i32,
) -> i32 {
    let Some(e) = engine.as_ref() else { return 0 };
    let Some(state) = e.game.as_ref() else { return 0 };

    let current_gold = state.gold.get(faction as usize).copied().unwrap_or(0);
    let turns_remaining = state
        .max_turns
        .map(|max| max.saturating_sub(state.turn))
        .unwrap_or(0);

    campaign::calculate_carry_gold(
        current_gold,
        gold_carry_percent as u32,
        turns_remaining,
        early_finish_bonus as u32,
    ) as i32
}

/// Place a veteran unit (carried over from a previous scenario).
/// Engine auto-assigns the next available unit ID.
/// Returns the assigned unit_id (positive) on success, or a negative error code.
#[no_mangle]
pub unsafe extern "C" fn norrust_place_veteran_unit(
    engine: *mut NorRustEngine,
    def_id: *const c_char,
    faction: i32,
    col: i32,
    row: i32,
    hp: i32,
    xp: i32,
    xp_needed: i32,
    advancement_pending: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    let did = cstr_to_str(def_id);

    let Some(state) = e.game.as_mut() else { return -1 };
    let uid = state.next_unit_id;
    state.next_unit_id += 1;

    // Build unit from registry (gets full combat stats)
    let mut unit = unit_from_registry(e, uid, did, faction as u8);

    // Override with carried-over progression state (heal to full HP)
    let _ = hp; // hp parameter ignored — veterans heal to full
    unit.hp = unit.max_hp;
    unit.xp = xp as u32;
    unit.xp_needed = xp_needed as u32;
    unit.advancement_pending = advancement_pending != 0;

    let destination = Hex::from_offset(col, row);
    let Some(state) = e.game.as_mut() else { return -1 };
    if !state.board.contains(destination) {
        return -1;
    }
    // Leader must be on a keep tile
    let active = state.active_faction;
    let keep_hex = state.positions.iter().find_map(|(&u, &hex)| {
        let unit = state.units.get(&u)?;
        if unit.faction != active { return None; }
        if !unit.abilities.iter().any(|a| a == "leader") { return None; }
        state.board.tile_at(hex).filter(|t| t.terrain_id == "keep").map(|_| hex)
    });
    let Some(keep_hex) = keep_hex else { return -10 };
    // Destination must be a castle tile adjacent to the keep
    match state.board.tile_at(destination) {
        Some(tile) if tile.terrain_id == "castle" => {}
        _ => return -9,
    }
    if keep_hex.distance(destination) != 1 {
        return -9;
    }
    if state.hex_to_unit.contains_key(&destination) {
        return -4;
    }
    state.place_unit(unit, destination);
    e.state_cache = None;
    uid as i32
}

/// Commit veteran deployment: place user-selected veterans on keep/castle hexes.
/// Takes a JSON array of indices into campaign.veterans (e.g. [0, 2, 3]).
/// Returns JSON: {"status":"ok","placed":N} or {"status":"error","message":"..."}.
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_commit_deployment(
    engine: *mut NorRustEngine,
    deployed_json: *const c_char,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else {
        return to_c_string(r#"{"status":"error","message":"null engine"}"#);
    };

    // Parse deployed indices
    let json_str = cstr_to_str(deployed_json);
    let indices: Vec<usize> = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return to_c_string(r#"{"status":"error","message":"invalid json"}"#),
    };

    // Get veterans and living UUIDs from campaign state
    let (selected_veterans, living_uuids) = {
        let Some(cs) = e.campaign.as_ref() else {
            return to_c_string(r#"{"status":"error","message":"no campaign"}"#);
        };
        let living = cs.get_living();
        let mut vets = Vec::new();
        let mut uuids = Vec::new();
        for &idx in &indices {
            if let Some(vet) = cs.veterans.get(idx) {
                vets.push(vet.clone());
                uuids.push(living.get(idx).map(|e| e.uuid.clone()));
            }
        }
        (vets, uuids)
    };

    // Find keep and castle slots
    let slots = {
        let Some(state) = e.game.as_ref() else {
            return to_c_string(r#"{"status":"error","message":"no game state"}"#);
        };
        let (keep_opt, castles) = campaign::find_keep_and_castles(state, 0);
        match keep_opt {
            Some(keep) => {
                let mut s: Vec<Hex> = vec![keep];
                s.extend_from_slice(&castles);
                s
            }
            None => {
                return to_c_string(r#"{"status":"ok","placed":0}"#);
            }
        }
    };

    // Clear id_map for new scenario placement
    if let Some(cs) = e.campaign.as_mut() {
        cs.clear_id_map();
    }

    // Place each selected veteran
    let mut placed = 0usize;
    for (vi, vet) in selected_veterans.iter().enumerate() {
        if placed >= slots.len() { break; }

        // Find next unoccupied slot
        let slot = {
            let state = e.game.as_ref().unwrap();
            let mut found = None;
            for si in placed..slots.len() {
                if !state.hex_to_unit.contains_key(&slots[si]) {
                    found = Some(si);
                    break;
                }
            }
            found
        };

        let Some(si) = slot else { break };
        placed = si + 1;
        let hex = slots[si];
        let (col, row) = hex.to_offset();

        // Create and place the veteran unit
        let state = e.game.as_mut().unwrap();
        let uid = state.next_unit_id;
        state.next_unit_id += 1;

        let mut unit = unit_from_registry(e, uid, &vet.def_id, 0);
        unit.hp = unit.max_hp; // Heal to full
        unit.xp = vet.xp;
        unit.xp_needed = vet.xp_needed;
        unit.advancement_pending = vet.advancement_pending;

        let state = e.game.as_mut().unwrap();
        state.place_unit(unit, Hex::from_offset(col, row));

        // Map engine ID to roster UUID
        if let Some(uuid) = living_uuids.get(vi).and_then(|u| u.clone()) {
            if let Some(cs) = e.campaign.as_mut() {
                cs.map_id(uid, &uuid);
            }
        }
    }

    e.state_cache = None;
    let result = format!(r#"{{"status":"ok","placed":{}}}"#, placed);
    to_c_string(&result)
}

// ── Campaign State (new v3.7) ────────────────────────────────────────────────

/// Start a campaign: load definition and create CampaignState on the engine.
/// Returns JSON of the campaign definition on success, empty string on failure.
#[no_mangle]
pub unsafe extern "C" fn norrust_start_campaign(
    engine: *mut NorRustEngine,
    path: *const c_char,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else { return to_c_string("") };
    let p = PathBuf::from(cstr_to_str(path));
    let def = match campaign::load_campaign(&p) {
        Ok(c) => c,
        Err(_) => return to_c_string(""),
    };

    // Build JSON response before moving def into CampaignState
    let json_obj = CampaignDefJson {
        id: &def.id,
        name: &def.name,
        faction_0: &def.faction_0,
        faction_1: &def.faction_1,
        gold_carry_percent: def.gold_carry_percent,
        early_finish_bonus: def.early_finish_bonus,
        scenarios: def.scenarios.iter().map(|s| CampaignScenarioJson {
            board: &s.board,
            units: &s.units,
            preset_units: s.preset_units,
        }).collect(),
    };
    let json = match serde_json::to_string(&json_obj) {
        Ok(s) => s,
        Err(_) => return to_c_string(""),
    };

    e.campaign = Some(CampaignState::new(def));
    to_c_string(&json)
}

/// Add a unit to the campaign roster. Returns the assigned UUID as a C string.
/// Returns empty string if no active campaign.
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_add_unit(
    engine: *mut NorRustEngine,
    def_id: *const c_char,
    engine_id: i32,
    hp: i32,
    max_hp: i32,
    xp: i32,
    xp_needed: i32,
    advancement_pending: i32,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else { return to_c_string("") };
    let Some(cs) = e.campaign.as_mut() else { return to_c_string("") };
    let did = cstr_to_str(def_id);

    // Get abilities from game state if unit exists
    let abilities = e.game.as_ref()
        .and_then(|state| state.units.get(&(engine_id as u32)))
        .map(|u| u.abilities.clone())
        .unwrap_or_default();

    let uuid = cs.add_unit(
        did,
        engine_id as u32,
        hp as u32,
        max_hp as u32,
        xp as u32,
        xp_needed as u32,
        advancement_pending != 0,
        abilities,
    );
    to_c_string(&uuid)
}

/// Map an engine unit ID to an existing roster UUID (for veteran placement).
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_map_id(
    engine: *mut NorRustEngine,
    engine_id: i32,
    uuid: *const c_char,
) {
    let Some(e) = engine.as_mut() else { return };
    let Some(cs) = e.campaign.as_mut() else { return };
    let uuid_str = cstr_to_str(uuid);
    cs.map_id(engine_id as u32, uuid_str);
}

/// Sync the campaign roster from the current game state for the given faction.
/// Returns 0 on success, -1 if no campaign or game state.
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_sync_roster(
    engine: *mut NorRustEngine,
    faction: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    let state = match e.game.as_ref() {
        Some(s) => s,
        None => return -1,
    };
    let cs = match e.campaign.as_mut() {
        Some(c) => c,
        None => return -1,
    };
    cs.sync_from_state(state, faction as u8);
    0
}

/// Record a victory: sync roster, extract veterans, calculate gold, advance scenario.
/// Returns JSON with {scenario_index, carry_gold, veterans: [...], living: [...]}.
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_record_victory(
    engine: *mut NorRustEngine,
    faction: i32,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else { return to_c_string("") };
    let state = match e.game.as_ref() {
        Some(s) => s,
        None => return to_c_string(""),
    };
    let cs = match e.campaign.as_mut() {
        Some(c) => c,
        None => return to_c_string(""),
    };
    cs.record_victory(state, faction as u8);

    #[derive(Serialize)]
    struct VictoryResult {
        status: String,
        scenario_index: usize,
        carry_gold: u32,
        veterans: Vec<campaign::VeteranUnit>,
        living: Vec<campaign::RosterEntry>,
    }
    let status = if cs.current_scenario().is_some() {
        "next_scenario"
    } else {
        "campaign_complete"
    };
    let result = VictoryResult {
        status: status.to_string(),
        scenario_index: cs.scenario_index,
        carry_gold: cs.carry_gold,
        veterans: cs.veterans.clone(),
        living: cs.get_living().into_iter().cloned().collect(),
    };
    match serde_json::to_string(&result) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string(""),
    }
}

/// Get the full campaign state as JSON (for save system).
/// Returns empty string if no active campaign.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_campaign_state_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("") };
    let Some(cs) = e.campaign.as_ref() else { return to_c_string("") };
    match serde_json::to_string(cs) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string(""),
    }
}

/// Get living roster entries as JSON array (for deployment UI).
/// Returns "[]" if no active campaign.
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_get_living_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let Some(cs) = e.campaign.as_ref() else { return to_c_string("[]") };
    let living: Vec<&campaign::RosterEntry> = cs.get_living();
    match serde_json::to_string(&living) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

/// Get UUIDs currently mapped to engine unit IDs (i.e., units on the board).
/// Returns JSON array of UUID strings, e.g. ["abc12345", "def67890"].
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_get_mapped_uuids_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let Some(cs) = e.campaign.as_ref() else { return to_c_string("[]") };
    let uuids: Vec<&String> = cs.id_map.values().collect();
    match serde_json::to_string(&uuids) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

/// Load the next campaign scenario: board, units, veterans, gold — all in one call.
///
/// Returns JSON:
/// - `{"status":"playing"}` — scenario ready
/// - `{"status":"deploy_needed","slots":N,"veterans":[...]}` — deployment screen needed
/// - `{"status":"complete"}` — campaign finished
/// - `{"status":"error","message":"..."}` — load failure
#[no_mangle]
pub unsafe extern "C" fn norrust_campaign_load_next_scenario(
    engine: *mut NorRustEngine,
    scenarios_path: *const c_char,
) -> *mut c_char {
    let Some(e) = engine.as_mut() else {
        return to_c_string(r#"{"status":"error","message":"null engine"}"#);
    };
    let base = PathBuf::from(cstr_to_str(scenarios_path));

    // Get current scenario info from campaign state
    let (board_path, units_path, preset, scenario_index, carry_gold, veterans_exist, board_name) = {
        let Some(cs) = e.campaign.as_ref() else {
            return to_c_string(r#"{"status":"error","message":"no campaign"}"#);
        };
        let Some(sc) = cs.current_scenario() else {
            return to_c_string(r#"{"status":"complete"}"#);
        };
        let board_name = sc.board.clone();
        (
            sc.board.clone(),
            sc.units.clone(),
            sc.preset_units,
            cs.scenario_index,
            cs.carry_gold,
            !cs.veterans.is_empty(),
            board_name,
        )
    };

    // 1. Load board (creates fresh GameState)
    let full_board_path = base.join(&board_path);
    let loaded = match crate::scenario::load_board(&full_board_path) {
        Ok(b) => b,
        Err(msg) => {
            let json = format!(r#"{{"status":"error","message":"{}"}}"#, msg.replace('"', "'"));
            return to_c_string(&json);
        }
    };
    let mut state = GameState::new_seeded(loaded.board, 42);
    state.objective_hex = loaded.objective_hex;
    state.max_turns = loaded.max_turns;
    e.game = Some(state);
    e.board_path = Some(full_board_path.to_string_lossy().to_string());
    upgrade_tiles_mut(e);

    // 2. Load preset units if flagged
    if preset {
        // Apply starting gold from faction definitions
        let f0_id = e.campaign.as_ref().map(|c| c.campaign_def.faction_0.clone()).unwrap_or_default();
        let f1_id = e.campaign.as_ref().map(|c| c.campaign_def.faction_1.clone()).unwrap_or_default();
        if let Some(state) = e.game.as_mut() {
            let gold0 = e.factions.iter().find(|(f, _)| f.id == f0_id).map(|(f, _)| f.starting_gold);
            let gold1 = e.factions.iter().find(|(f, _)| f.id == f1_id).map(|(f, _)| f.starting_gold);
            if let (Some(g0), Some(g1)) = (gold0, gold1) {
                state.gold = [g0, g1];
            }
        }

        // Load units
        let full_units_path = base.join(&units_path);
        if let Ok(units_def) = crate::scenario::load_units_file(&full_units_path) {
            let mut max_id: u32 = 0;
            for p in &units_def.units {
                let unit = unit_from_registry(e, p.id, &p.unit_type, p.faction as u8);
                if let Some(state) = e.game.as_mut() {
                    state.place_unit(unit, Hex::from_offset(p.col, p.row));
                }
                if p.id > max_id { max_id = p.id; }
            }
            if let Some(state) = e.game.as_mut() {
                state.next_unit_id = max_id + 1;
            }
            // Resolve trigger zones
            for tdef in units_def.triggers {
                let mut spawns = Vec::new();
                for s in &tdef.spawns {
                    let Some(state) = e.game.as_mut() else { continue };
                    let uid = state.next_unit_id;
                    state.next_unit_id += 1;
                    let unit = unit_from_registry(e, uid, &s.unit_type, s.faction);
                    spawns.push(PendingSpawn {
                        unit,
                        destination: Hex::from_offset(s.col, s.row),
                    });
                }
                if let Some(state) = e.game.as_mut() {
                    state.trigger_zones.push(TriggerZone {
                        trigger_hex: Hex::from_offset(tdef.trigger_col, tdef.trigger_row),
                        trigger_faction: tdef.trigger_faction,
                        spawns,
                        triggered: false,
                    });
                }
            }
        }
    }

    // 3. First scenario: populate roster from placed units
    if scenario_index == 0 {
        if let (Some(cs), Some(state)) = (e.campaign.as_mut(), e.game.as_ref()) {
            cs.populate_initial_roster(state, 0);
        }
    }

    // 4. Place veterans (if any, and scenario > 0)
    if scenario_index > 0 && veterans_exist {
        let deploy_result = {
            let Some(state) = e.game.as_ref() else {
                return to_c_string(r#"{"status":"error","message":"no game state"}"#);
            };
            let (keep_opt, castles) = campaign::find_keep_and_castles(state, 0);
            match keep_opt {
                Some(keep) => {
                    let available = campaign::count_available_slots(state, keep, &castles);
                    let cs = e.campaign.as_ref().unwrap();
                    let num_vets = cs.veterans.len();
                    if num_vets > available && available > 0 {
                        // Deploy screen needed
                        let vet_info = cs.build_veteran_info(available);
                        Some((available, vet_info))
                    } else {
                        // Can place all veterans
                        None
                    }
                }
                None => None, // No keep found, skip placement
            }
        };

        if let Some((slots, vet_info)) = deploy_result {
            // Apply carry-over gold before deploy screen
            if carry_gold > 0 {
                if let Some(state) = e.game.as_mut() {
                    state.gold[0] = carry_gold;
                }
            }
            e.state_cache = None;

            #[derive(Serialize)]
            struct DeployResult {
                status: String,
                board: String,
                slots: usize,
                veterans: Vec<campaign::VeteranInfo>,
            }
            let result = DeployResult {
                status: "deploy_needed".to_string(),
                board: board_name.clone(),
                slots,
                veterans: vet_info,
            };
            return match serde_json::to_string(&result) {
                Ok(s) => to_c_string(&s),
                Err(_) => to_c_string(r#"{"status":"error","message":"json error"}"#),
            };
        }

        // Place all veterans directly
        let state = e.game.as_ref().unwrap();
        let (keep_opt, castles) = campaign::find_keep_and_castles(state, 0);
        if let Some(keep) = keep_opt {
            // Build slots list: keep first, then castles
            let mut slots: Vec<Hex> = vec![keep];
            slots.extend_from_slice(&castles);

            let veterans: Vec<campaign::VeteranUnit> = e.campaign.as_ref()
                .map(|cs| cs.veterans.clone())
                .unwrap_or_default();

            let living_uuids: Vec<Option<String>> = e.campaign.as_ref()
                .map(|cs| {
                    let living = cs.get_living();
                    veterans.iter().enumerate().map(|(i, _)| {
                        living.get(i).map(|e| e.uuid.clone())
                    }).collect()
                })
                .unwrap_or_default();

            // Clear id_map for new scenario
            if let Some(cs) = e.campaign.as_mut() {
                cs.clear_id_map();
            }

            let mut placed = 0;
            for (vi, vet) in veterans.iter().enumerate() {
                if placed >= slots.len() { break; }

                // Find next unoccupied slot
                let slot = {
                    let state = e.game.as_ref().unwrap();
                    let mut found = None;
                    for si in placed..slots.len() {
                        if !state.hex_to_unit.contains_key(&slots[si]) {
                            found = Some(si);
                            break;
                        }
                    }
                    found
                };

                let Some(si) = slot else { break };
                placed = si + 1;
                let hex = slots[si];
                let (col, row) = hex.to_offset();

                // Create and place the veteran unit
                let state = e.game.as_mut().unwrap();
                let uid = state.next_unit_id;
                state.next_unit_id += 1;

                let mut unit = unit_from_registry(e, uid, &vet.def_id, 0);
                unit.hp = unit.max_hp; // Heal to full
                unit.xp = vet.xp;
                unit.xp_needed = vet.xp_needed;
                unit.advancement_pending = vet.advancement_pending;

                let state = e.game.as_mut().unwrap();
                state.place_unit(unit, Hex::from_offset(col, row));

                // Map engine ID to roster UUID
                if let Some(uuid) = living_uuids.get(vi).and_then(|u| u.clone()) {
                    if let Some(cs) = e.campaign.as_mut() {
                        cs.map_id(uid, &uuid);
                    }
                }
            }
        }
    }

    // 5. Apply carry-over gold
    if scenario_index > 0 && carry_gold > 0 {
        if let Some(state) = e.game.as_mut() {
            state.gold[0] = carry_gold;
        }
    }

    e.state_cache = None;
    let playing_json = format!(r#"{{"status":"playing","board":"{}"}}"#, board_name.replace('"', "'"));
    to_c_string(&playing_json)
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_faction_gold(
    engine: *mut NorRustEngine,
    faction: i32,
    gold: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        if faction >= 0 && (faction as usize) < state.gold.len() {
            state.gold[faction as usize] = gold.max(0) as u32;
        }
    });
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_turn(
    engine: *mut NorRustEngine,
    turn: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        state.turn = turn.max(1) as u32;
    });
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_active_faction(
    engine: *mut NorRustEngine,
    faction: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        state.active_faction = faction.max(0) as u8;
    });
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_unit_combat_state(
    engine: *mut NorRustEngine,
    unit_id: i32,
    hp: i32,
    xp: i32,
    moved: i32,
    attacked: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        let uid = unit_id as u32;
        if let Some(unit) = state.units.get_mut(&uid) {
            unit.hp = hp.max(0) as u32;
            unit.xp = xp.max(0) as u32;
            unit.moved = moved != 0;
            unit.attacked = attacked != 0;
        }
    });
}

// ── Terrain query ────────────────────────────────────────────────────────────

/// Returns JSON with a unit's effective defense and movement cost on a specific hex.
///
/// Fallback chain for defense: unit.defense\[terrain_id\] → tile.defense → unit.default_defense
/// Fallback chain for movement: unit.movement_costs\[terrain_id\] → tile.movement_cost
///
/// Returns empty string on invalid unit_id or hex.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_unit_terrain_info(
    engine: *mut NorRustEngine,
    unit_id: i32,
    col: i32,
    row: i32,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("") };
    let Some(state) = e.game.as_ref() else { return to_c_string("") };
    let uid = unit_id as u32;
    let Some(unit) = state.units.get(&uid) else { return to_c_string("") };
    let hex = Hex::from_offset(col, row);
    let Some(tile) = state.board.tile_at(hex) else { return to_c_string("") };

    let terrain_id = &tile.terrain_id;

    // Defense fallback: unit.defense[terrain_id] → tile.defense → unit.default_defense
    let effective_defense = unit.defense.get(terrain_id).copied()
        .unwrap_or(tile.defense);
    // Note: if neither unit.defense nor tile.defense exist, tile.defense is always present (from Tile struct)

    // Movement cost fallback: unit.movement_costs[terrain_id] → tile.movement_cost
    let effective_move_cost = unit.movement_costs.get(terrain_id).copied()
        .unwrap_or(tile.movement_cost);

    let info = TerrainInfoJson {
        terrain_id,
        defense: effective_defense,
        movement_cost: effective_move_cost,
        base_defense: tile.defense,
        base_movement_cost: tile.movement_cost,
        healing: tile.healing,
    };
    match serde_json::to_string(&info) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string(""),
    }
}

// ── Combat preview ──────────────────────────────────────────────────────────

/// Run Monte Carlo combat simulation and return JSON with damage distributions.
///
/// `attacker_col`/`attacker_row` is the ghost position (where the attacker will be).
/// Does NOT mutate game state.
#[no_mangle]
pub unsafe extern "C" fn norrust_simulate_combat(
    engine: *mut NorRustEngine,
    attacker_id: i32,
    defender_id: i32,
    attacker_col: i32,
    attacker_row: i32,
    num_sims: i32,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("") };
    let Some(state) = e.game.as_ref() else { return to_c_string("") };

    let atk_uid = attacker_id as u32;
    let def_uid = defender_id as u32;
    let Some(attacker) = state.units.get(&atk_uid) else { return to_c_string("") };
    let Some(defender) = state.units.get(&def_uid) else { return to_c_string("") };

    // Attacker terrain defense at ghost position
    let atk_hex = Hex::from_offset(attacker_col, attacker_row);
    let atk_terrain_defense = if let Some(tile) = state.board.tile_at(atk_hex) {
        let terrain_id = &tile.terrain_id;
        attacker.defense.get(terrain_id).copied().unwrap_or(tile.defense)
    } else {
        attacker.default_defense
    };

    // Defender terrain defense at current position
    let def_pos = match state.positions.get(&def_uid) {
        Some(p) => *p,
        None => return to_c_string(""),
    };
    let def_terrain_defense = if let Some(tile) = state.board.tile_at(def_pos) {
        let terrain_id = &tile.terrain_id;
        defender.defense.get(terrain_id).copied().unwrap_or(tile.defense)
    } else {
        defender.default_defense
    };

    // Determine engagement range from distance
    let dist = atk_hex.distance(def_pos);
    let range_needed = match dist {
        1 => "melee",
        _ => "ranged",
    };

    // Backstab flanking check: is there an ally of the attacker on the opposite side of the defender?
    let flanked = {
        let atk_attack = attacker.attacks.iter().find(|a| a.range == range_needed);
        if atk_attack.map(|a| crate::unit::has_special(a, "backstab")).unwrap_or(false) {
            let opposite = Hex {
                x: def_pos.x + (def_pos.x - atk_hex.x),
                y: def_pos.y + (def_pos.y - atk_hex.y),
                z: def_pos.z + (def_pos.z - atk_hex.z),
            };
            state.hex_to_unit.get(&opposite)
                .filter(|&&uid| uid != atk_uid)
                .and_then(|&uid| state.units.get(&uid))
                .map(|u| u.faction == attacker.faction)
                .unwrap_or(false)
        } else {
            false
        }
    };

    // Leadership bonuses
    let atk_leadership = crate::game_state::leadership_bonus(state, atk_uid);
    let def_leadership = crate::game_state::leadership_bonus(state, def_uid);

    let n = if num_sims > 0 { num_sims as u32 } else { 100 };
    let preview = simulate_combat(attacker, defender, atk_terrain_defense, def_terrain_defense, state.turn, n, range_needed, flanked, atk_leadership, def_leadership);

    let json_obj = CombatPreviewJson {
        attacker_hit_pct: preview.attacker_hit_pct,
        defender_hit_pct: preview.defender_hit_pct,
        attacker_damage_per_hit: preview.attacker_damage_per_hit,
        attacker_strikes: preview.attacker_strikes,
        defender_damage_per_hit: preview.defender_damage_per_hit,
        defender_strikes: preview.defender_strikes,
        attacker_damage_min: preview.attacker_damage_min,
        attacker_damage_max: preview.attacker_damage_max,
        attacker_damage_mean: preview.attacker_damage_mean,
        defender_damage_min: preview.defender_damage_min,
        defender_damage_max: preview.defender_damage_max,
        defender_damage_mean: preview.defender_damage_mean,
        attacker_kill_pct: preview.attacker_kill_pct,
        defender_kill_pct: preview.defender_kill_pct,
        attacker_attack_name: &preview.attacker_attack_name,
        defender_attack_name: &preview.defender_attack_name,
        attacker_hp: preview.attacker_hp,
        defender_hp: preview.defender_hp,
        attacker_terrain_defense: preview.attacker_terrain_defense,
        defender_terrain_defense: preview.defender_terrain_defense,
    };
    match serde_json::to_string(&json_obj) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string(""),
    }
}

// ── Trigger zones ────────────────────────────────────────────────────────────

/// Returns JSON array of booleans for each trigger zone's fired state.
/// e.g. [true, false, true]. Returns "[]" if no game state.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_trigger_zones_fired(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let Some(state) = e.game.as_ref() else { return to_c_string("[]") };
    let items: Vec<bool> = state.trigger_zones.iter()
        .map(|tz| tz.triggered)
        .collect();
    match serde_json::to_string(&items) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

/// Set the triggered flag on a specific trigger zone by index.
#[no_mangle]
pub unsafe extern "C" fn norrust_set_trigger_zone_fired(
    engine: *mut NorRustEngine,
    index: i32,
    fired: i32,
) {
    with_game_mut!(engine, _e, state, (), {
        if let Some(tz) = state.trigger_zones.get_mut(index as usize) {
            tz.triggered = fired != 0;
        }
    });
}

// ── Dialogue ─────────────────────────────────────────────────────────────────

/// Load dialogue entries from a TOML file. Returns 1 on success, 0 on failure.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn norrust_load_dialogue(
    engine: *mut NorRustEngine,
    path: *const c_char,
) -> i32 {
    let Some(engine) = engine.as_mut() else { return 0 };
    let path_str = unsafe { cstr_to_str(path) };
    match DialogueState::load(std::path::Path::new(path_str)) {
        Ok(state) => {
            engine.dialogue_state = Some(state);
            engine.dialogue_path = Some(path_str.to_string());
            1
        }
        Err(_) => 0,
    }
}

/// Query pending dialogue for the given trigger, turn, faction, and optional hex.
/// Use col=-1, row=-1 for "any hex" (no location filter).
/// Returns a JSON array string: [{"id":"...","text":"..."},...].
/// Matched entries are marked as fired (one-shot). Caller frees the string.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn norrust_get_dialogue(
    engine: *mut NorRustEngine,
    trigger: *const c_char,
    turn: u32,
    faction: u8,
    col: i32,
    row: i32,
) -> *mut c_char {
    let Some(engine) = engine.as_mut() else { return to_c_string("[]") };
    let trigger_str = unsafe { cstr_to_str(trigger) };
    let ds = match engine.dialogue_state.as_mut() {
        Some(ds) => ds,
        None => return to_c_string("[]"),
    };
    let opt_col = if col >= 0 { Some(col) } else { None };
    let opt_row = if row >= 0 { Some(row) } else { None };
    let pending = ds.get_pending(trigger_str, turn, faction, opt_col, opt_row);
    if pending.is_empty() {
        return to_c_string("[]");
    }
    let items: Vec<DialogueEntryJson> = pending
        .iter()
        .map(|e| DialogueEntryJson { id: &e.id, text: &e.text })
        .collect();
    match serde_json::to_string(&items) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

/// Returns JSON array of strings for dialogue entries that have fired.
/// e.g. ["id1","id2"]. Returns "[]" if no dialogue state.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_dialogue_fired(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("[]") };
    let Some(ds) = e.dialogue_state.as_ref() else { return to_c_string("[]") };
    let ids: Vec<&str> = ds.fired_ids().iter().map(|id| id.as_str()).collect();
    match serde_json::to_string(&ids) {
        Ok(s) => to_c_string(&s),
        Err(_) => to_c_string("[]"),
    }
}

/// Mark dialogue entries as fired by passing a JSON array of ID strings.
/// e.g. "[\"id1\",\"id2\"]"
#[no_mangle]
pub unsafe extern "C" fn norrust_set_dialogue_fired(
    engine: *mut NorRustEngine,
    ids_json: *const c_char,
) {
    let Some(e) = engine.as_mut() else { return };
    let Some(ds) = e.dialogue_state.as_mut() else { return };
    let json_str = cstr_to_str(ids_json);
    // Simple JSON array parser for ["id1","id2",...]
    let trimmed = json_str.trim().trim_start_matches('[').trim_end_matches(']');
    for item in trimmed.split(',') {
        let id = item.trim().trim_matches('"');
        if !id.is_empty() {
            ds.mark_fired(id);
        }
    }
    e.state_cache = None;
}

// ── Targeted state queries ──────────────────────────────────────────────────

/// Return board dimensions without a full state JSON dump.
/// Writes width to `*out_cols` and height to `*out_rows`. Returns 1 on success, 0 on failure.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_board_size(
    engine: *mut NorRustEngine,
    out_cols: *mut i32,
    out_rows: *mut i32,
) -> i32 {
    with_game_ref!(engine, e, state, 0, {
        if !out_cols.is_null() { *out_cols = state.board.width as i32; }
        if !out_rows.is_null() { *out_rows = state.board.height as i32; }
        1
    })
}

/// Return the gold for a given faction (0 or 1) without a full state JSON dump.
/// Returns -1 on failure.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_gold(
    engine: *mut NorRustEngine,
    faction: i32,
) -> i32 {
    with_game_ref!(engine, e, state, -1, {
        state.gold.get(faction as usize).map(|&g| g as i32).unwrap_or(-1)
    })
}

/// Return the unit_id at a given hex, or -1 if empty / invalid.
#[no_mangle]
pub unsafe extern "C" fn norrust_get_unit_at(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) -> i32 {
    with_game_ref!(engine, e, state, -1, {
        let hex = Hex::from_offset(col, row);
        state.hex_to_unit.get(&hex).map(|&uid| uid as i32).unwrap_or(-1)
    })
}

// ── Save / Load ─────────────────────────────────────────────────────────────

/// Set the display name for save metadata (human-readable scenario name).
#[no_mangle]
pub unsafe extern "C" fn norrust_set_display_name(
    engine: *mut NorRustEngine,
    name: *const c_char,
) {
    let Some(e) = engine.as_mut() else { return };
    let name_str = cstr_to_str(name);
    e.display_name = if name_str.is_empty() { None } else { Some(name_str.to_string()) };
}

/// Serialize the full engine state to JSON for saving.
///
/// Returns a JSON string containing all game state, campaign state, dialogue
/// fired IDs, and metadata needed to reconstruct the game. Caller frees with
/// `norrust_free_string()`. Returns null if no game state loaded.
#[no_mangle]
pub unsafe extern "C" fn norrust_save_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return std::ptr::null_mut() };
    let Some(state) = e.game.as_ref() else { return std::ptr::null_mut() };
    let Some(board_path) = e.board_path.as_deref() else { return std::ptr::null_mut() };

    let save = SaveState::build(
        state,
        board_path,
        e.dialogue_state.as_ref(),
        e.dialogue_path.as_deref(),
        e.campaign.as_ref(),
        e.display_name.as_deref(),
    );

    match serde_json::to_string(&save) {
        Ok(json) => to_c_string(&json),
        Err(_) => std::ptr::null_mut(),
    }
}

/// Restore full engine state from a JSON save string.
///
/// Reloads the board from the saved path, reconstructs all units from the
/// registry, restores game metadata, dialogue fired state, and campaign state.
/// Returns 0 on success, -1 on error.
#[no_mangle]
pub unsafe extern "C" fn norrust_load_json(
    engine: *mut NorRustEngine,
    json: *const c_char,
) -> i32 {
    panic::catch_unwind(panic::AssertUnwindSafe(|| {
        let Some(e) = engine.as_mut() else { return -1 };
        let json_str = cstr_to_str(json);
        let save: SaveState = match serde_json::from_str(json_str) {
            Ok(s) => s,
            Err(_) => return -1,
        };

        // 1. Reload board from saved path
        let path = PathBuf::from(&save.board_path);
        let loaded = match crate::scenario::load_board(&path) {
            Ok(b) => b,
            Err(_) => return -1,
        };
        let mut state = GameState::new_seeded(loaded.board, save.rng_state);
        state.objective_hex = loaded.objective_hex;
        state.max_turns = loaded.max_turns;
        e.game = Some(state);
        e.board_path = Some(save.board_path.clone());
        upgrade_tiles_mut(e);

        // 2. Override game metadata from save
        let Some(state) = e.game.as_mut() else { return -1 };
        state.rng = Rng::new(save.rng_state);
        state.turn = save.turn;
        state.active_faction = save.active_faction;
        state.gold = save.gold;
        if let Some(mt) = save.max_turns {
            state.max_turns = Some(mt);
        }
        if let Some((col, row)) = save.objective_hex {
            state.objective_hex = Some(Hex::from_offset(col, row));
        }

        // 3. Restore units from registry + saved state
        for su in &save.units {
            let mut unit = unit_from_registry(e, su.id, &su.def_id, su.faction);
            // Override runtime state from save
            unit.hp = su.hp;
            unit.max_hp = su.max_hp;
            unit.xp = su.xp;
            unit.xp_needed = su.xp_needed;
            unit.advancement_pending = su.advancement_pending;
            unit.moved = su.moved;
            unit.attacked = su.attacked;
            unit.poisoned = su.poisoned;
            unit.slowed = su.slowed;
            unit.level = su.level;
            unit.abilities = su.abilities.clone();

            let Some(state) = e.game.as_mut() else { return -1 };
            state.place_unit(unit, Hex::from_offset(su.col, su.row));
        }

        // 4. Set next_unit_id
        let Some(state) = e.game.as_mut() else { return -1 };
        state.next_unit_id = save.next_unit_id;

        // 5. Restore trigger zone fired state
        for (i, fired) in save.trigger_zones_fired.iter().enumerate() {
            if let Some(tz) = state.trigger_zones.get_mut(i) {
                tz.triggered = *fired;
            }
        }

        // 6. Restore village owners
        for &(col, row, owner) in &save.village_owners {
            state.village_owners.insert(Hex::from_offset(col, row), owner);
        }

        // 7. Restore dialogue
        if let Some(ref dlg_path) = save.dialogue_path {
            if let Ok(mut ds) = DialogueState::load(std::path::Path::new(dlg_path)) {
                for id in &save.dialogue_fired {
                    ds.mark_fired(id);
                }
                e.dialogue_state = Some(ds);
                e.dialogue_path = Some(dlg_path.clone());
            }
        }

        // 8. Restore campaign state
        e.campaign = save.campaign;

        // 9. Restore metadata
        e.display_name = save.display_name;

        e.state_cache = None;
        0
    })).unwrap_or(-1)
}

// ── Debug / Cheat FFI ─────────────────────────────────────────────────────

/// Set a unit's XP to its advancement threshold, triggering advancement_pending.
#[no_mangle]
pub unsafe extern "C" fn norrust_cheat_set_xp(
    engine: *mut NorRustEngine,
    unit_id: i32,
) -> i32 {
    with_game_mut!(engine, _e, state, -1, {
        let uid = unit_id as u32;
        let Some(unit) = state.units.get_mut(&uid) else { return -2 };
        if unit.xp_needed > 0 {
            unit.xp = unit.xp_needed;
            unit.advancement_pending = true;
        }
        0
    })
}

/// Add gold to a faction (0 or 1). Amount can be negative to remove gold.
#[no_mangle]
pub unsafe extern "C" fn norrust_cheat_add_gold(
    engine: *mut NorRustEngine,
    faction: i32,
    amount: i32,
) -> i32 {
    with_game_mut!(engine, _e, state, -1, {
        let f = faction as usize;
        if f >= state.gold.len() { return -2; }
        state.gold[f] = (state.gold[f] as i64 + amount as i64).max(0) as u32;
        0
    })
}

/// Set the turn counter directly (affects time of day).
#[no_mangle]
pub unsafe extern "C" fn norrust_cheat_set_turn(
    engine: *mut NorRustEngine,
    turn: i32,
) -> i32 {
    with_game_mut!(engine, _e, state, -1, {
        state.turn = turn as u32;
        0
    })
}
