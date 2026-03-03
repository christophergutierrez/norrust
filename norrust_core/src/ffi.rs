//! C ABI bridge for LuaJIT FFI and other foreign callers.
//!
//! All functions use the `norrust_` prefix and operate on an opaque `*mut NorRustEngine`.
//! String returns are caller-owned: free with `norrust_free_string()`.
//! Integer arrays are caller-owned: free with `norrust_free_int_array()`.

use std::collections::HashSet;
use std::ffi::{c_char, CStr, CString};
use std::path::PathBuf;

use crate::board::Tile;
use crate::combat::{time_of_day, TimeOfDay};
use crate::game_state::{apply_action, apply_recruit, Action, ActionError, GameState, PendingSpawn, TriggerZone};
use crate::hex::Hex;
use crate::loader::Registry;
use crate::pathfinding::{get_zoc_hexes, reachable_hexes};
use crate::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use crate::snapshot::{ActionRequest, StateSnapshot};
use crate::unit::{advance_unit, parse_alignment, Unit};

// ── Engine struct ────────────────────────────────────────────────────────────

pub struct NorRustEngine {
    units: Option<Registry<UnitDef>>,
    terrain: Option<Registry<TerrainDef>>,
    game: Option<GameState>,
    factions: Vec<(FactionDef, Vec<String>)>,
}

impl NorRustEngine {
    fn new() -> Self {
        Self {
            units: None,
            terrain: None,
            game: None,
            factions: Vec::new(),
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

/// Build a fully populated Unit from the registry, same as gdext_node place_unit_at.
fn unit_from_registry(
    engine: &NorRustEngine,
    unit_id: u32,
    def_id: &str,
    faction: u8,
) -> Unit {
    let mut unit = Unit::new(unit_id, def_id.to_string(), 0, faction);

    if let Some(def) = engine.units.as_ref().and_then(|r| r.get(def_id)) {
        unit.max_hp = def.max_hp;
        unit.hp = def.max_hp;
        unit.movement = def.movement;
        unit.movement_costs = def.movement_costs.clone();
        unit.attacks = def.attacks.clone();
        unit.defense = def.defense.clone();
        unit.resistances = def.resistances.clone();
        unit.xp_needed = def.experience;
        unit.alignment = parse_alignment(&def.alignment);
        unit.abilities = def.abilities.clone();
    }

    unit
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
        let slice = std::slice::from_raw_parts_mut(arr, len as usize);
        drop(Box::from_raw(slice as *mut [i32]));
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
    let Some(e) = engine.as_mut() else { return 0 };
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
    1
}

#[no_mangle]
pub unsafe extern "C" fn norrust_load_board(
    engine: *mut NorRustEngine,
    board_path: *const c_char,
    seed: i64,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    if seed <= 0 { return 0; }
    let path = PathBuf::from(cstr_to_str(board_path));
    let loaded = match crate::scenario::load_board(&path) {
        Ok(b) => b,
        Err(_) => return 0,
    };
    let mut state = GameState::new_seeded(loaded.board, seed as u64);
    state.objective_hex = loaded.objective_hex;
    state.max_turns = loaded.max_turns;
    e.game = Some(state);
    upgrade_tiles_mut(e);
    1
}

#[no_mangle]
pub unsafe extern "C" fn norrust_load_units(
    engine: *mut NorRustEngine,
    units_path: *const c_char,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    if e.game.is_none() { return 0; }
    let path = PathBuf::from(cstr_to_str(units_path));
    let placements = match crate::scenario::load_units(&path) {
        Ok(p) => p,
        Err(_) => return 0,
    };

    // Place units and track highest ID
    let mut max_id: u32 = 0;
    for p in &placements {
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

    // Load and resolve trigger zones from the same file
    if let Ok(trigger_defs) = crate::scenario::load_triggers(&path) {
        for tdef in trigger_defs {
            let mut spawns = Vec::new();
            for s in &tdef.spawns {
                let state = e.game.as_mut().unwrap();
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

    1
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_terrain_at(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("") };
    let Some(state) = e.game.as_ref() else { return to_c_string("") };
    let tid = state.board.terrain_at(Hex::from_offset(col, row)).unwrap_or("");
    to_c_string(tid)
}

// ── Unit management ──────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_place_unit_at(
    engine: *mut NorRustEngine,
    unit_id: i32,
    def_id: *const c_char,
    _hp: i32,
    faction: i32,
    col: i32,
    row: i32,
) {
    let Some(e) = engine.as_mut() else { return };
    let did = cstr_to_str(def_id);
    let unit = unit_from_registry(e, unit_id as u32, did, faction as u8);
    if let Some(state) = e.game.as_mut() {
        state.place_unit(unit, Hex::from_offset(col, row));
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_remove_unit_at(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    let Some(state) = e.game.as_mut() else { return 0 };
    let target = Hex::from_offset(col, row);
    let uid = state.positions.iter()
        .find(|(_, &hex)| hex == target)
        .map(|(&id, _)| id);
    let Some(uid) = uid else { return 0 };
    state.units.remove(&uid);
    state.positions.remove(&uid);
    1
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

#[no_mangle]
pub unsafe extern "C" fn norrust_recruit_unit_at(
    engine: *mut NorRustEngine,
    unit_id: i32,
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

    let unit = unit_from_registry(e, unit_id as u32, &did, {
        let state = e.game.as_ref().unwrap();
        state.active_faction
    });

    let destination = Hex::from_offset(col, row);
    let state = e.game.as_mut().unwrap();
    match apply_recruit(state, unit, destination, cost) {
        Ok(()) => 0,
        Err(err) => action_err_code(err),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_ai_recruit(
    engine: *mut NorRustEngine,
    faction_id: *const c_char,
    start_unit_id: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return 0 };
    let id = cstr_to_str(faction_id).to_string();
    let recruits: Vec<String> = match e.factions.iter().find(|(f, _)| f.id == id) {
        Some((_, r)) => r.clone(),
        None => return 0,
    };

    let mut recruited = 0i32;
    let mut uid = start_unit_id;

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
                    && !state.positions.values().any(|&p| p == h)
            })?;
            let def_id = recruits.iter().find(|did| {
                e.units.as_ref()
                    .and_then(|r| r.get(did.as_str()))
                    .map(|def| state.gold[active as usize] >= def.cost)
                    .unwrap_or(false)
            })?;
            let (col, row) = dest.to_offset();
            Some((def_id.clone(), col, row))
        });

        let Some((did, col, row)) = action else { break };

        let cost = match e.units.as_ref().and_then(|r| r.get(&did)) {
            Some(def) => def.cost,
            None => break,
        };
        let faction = e.game.as_ref().unwrap().active_faction;
        let unit = unit_from_registry(e, uid as u32, &did, faction);
        let destination = Hex::from_offset(col, row);

        let state = e.game.as_mut().unwrap();
        match apply_recruit(state, unit, destination, cost) {
            Ok(()) => { recruited += 1; uid += 1; }
            Err(_) => break,
        }
    }
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
        (Some(g0), Some(g1)) => { state.gold = [g0, g1]; 1 }
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
    let arr: Vec<String> = e.factions.iter()
        .map(|(f, _)| format!("{{\"id\":\"{}\",\"name\":\"{}\"}}", f.id, f.name))
        .collect();
    to_c_string(&format!("[{}]", arr.join(",")))
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
    let filtered: Vec<String> = recruits.iter()
        .filter(|did| {
            if max_level <= 0 { return true; }
            e.units.as_ref()
                .and_then(|r| r.get(did.as_str()))
                .map(|u| u.level as i32 <= max_level)
                .unwrap_or(true)
        })
        .map(|id| format!("\"{}\"", id))
        .collect();
    to_c_string(&format!("[{}]", filtered.join(",")))
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
    let Some(e) = engine.as_ref() else { return -1 };
    let Some(state) = e.game.as_ref() else { return -1 };
    match state.check_winner() {
        Some(f) => f as i32,
        None => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_objective_hex(
    engine: *mut NorRustEngine,
    col: i32,
    row: i32,
) {
    let Some(e) = engine.as_mut() else { return };
    let Some(state) = e.game.as_mut() else { return };
    state.objective_hex = Some(Hex::from_offset(col, row));
}

#[no_mangle]
pub unsafe extern "C" fn norrust_set_max_turns(
    engine: *mut NorRustEngine,
    max_turns: i32,
) {
    let Some(e) = engine.as_mut() else { return };
    let Some(state) = e.game.as_mut() else { return };
    state.max_turns = if max_turns > 0 { Some(max_turns as u32) } else { None };
}

#[no_mangle]
pub unsafe extern "C" fn norrust_get_state_json(
    engine: *mut NorRustEngine,
) -> *mut c_char {
    let Some(e) = engine.as_ref() else { return to_c_string("") };
    let Some(state) = e.game.as_ref() else { return to_c_string("") };
    match serde_json::to_string(&StateSnapshot::from_game_state(state)) {
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
    let Some(e) = engine.as_mut() else { return -1 };
    let Some(state) = e.game.as_mut() else { return -1 };
    match apply_action(state, Action::Move {
        unit_id: unit_id as u32,
        destination: Hex::from_offset(col, row),
    }) {
        Ok(()) => 0,
        Err(err) => action_err_code(err),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_attack(
    engine: *mut NorRustEngine,
    attacker_id: i32,
    defender_id: i32,
) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    let Some(state) = e.game.as_mut() else { return -1 };
    match apply_action(state, Action::Attack {
        attacker_id: attacker_id as u32,
        defender_id: defender_id as u32,
    }) {
        Ok(()) => 0,
        Err(err) => action_err_code(err),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_advance(
    engine: *mut NorRustEngine,
    unit_id: i32,
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

    let target_def_id = match e.units.as_ref()
        .and_then(|r| r.get(&current_def_id))
        .and_then(|def| def.advances_to.first().cloned())
    {
        Some(id) => id,
        None => return -9,
    };

    let new_def = match e.units.as_ref().and_then(|r| r.get(&target_def_id)) {
        Some(def) => def.clone(),
        None => return -10,
    };

    let state = e.game.as_mut().unwrap();
    advance_unit(state.units.get_mut(&uid).unwrap(), &new_def);
    0
}

#[no_mangle]
pub unsafe extern "C" fn norrust_end_turn(engine: *mut NorRustEngine) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    let Some(state) = e.game.as_mut() else { return -1 };
    match apply_action(state, Action::EndTurn) {
        Ok(()) => 0,
        Err(err) => action_err_code(err),
    }
}

#[no_mangle]
pub unsafe extern "C" fn norrust_apply_action_json(
    engine: *mut NorRustEngine,
    json: *const c_char,
) -> i32 {
    let Some(e) = engine.as_mut() else { return -1 };
    if e.game.is_none() { return -1; }
    let json_str = cstr_to_str(json);
    let req: ActionRequest = match serde_json::from_str(json_str) {
        Ok(r) => r,
        Err(_) => return -99,
    };
    match req {
        ActionRequest::Advance { unit_id } => {
            norrust_apply_advance(engine, unit_id as i32)
        }
        ActionRequest::Recruit { unit_id, def_id, col, row } => {
            let c_def = CString::new(def_id).unwrap_or_default();
            norrust_recruit_unit_at(engine, unit_id as i32, c_def.as_ptr(), col, row)
        }
        other => {
            let Some(state) = e.game.as_mut() else { return -1 };
            match apply_action(state, other.into()) {
                Ok(()) => 0,
                Err(err) => action_err_code(err),
            }
        }
    }
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
    let hexes = reachable_hexes(
        &state.board,
        &unit.movement_costs,
        1,
        start,
        unit.movement,
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

// ── AI ───────────────────────────────────────────────────────────────────────

#[no_mangle]
pub unsafe extern "C" fn norrust_ai_take_turn(
    engine: *mut NorRustEngine,
    faction: i32,
) {
    let Some(e) = engine.as_mut() else { return };
    if faction < 0 || faction > 1 { return; }
    let Some(state) = e.game.as_mut() else { return };
    crate::ai::ai_take_turn(state, faction as u8);
}
