use crate::board::Board;
use crate::combat::{time_of_day, TimeOfDay};
use crate::game_state::{apply_action, apply_recruit, Action, ActionError, GameState};
use crate::hex::Hex;
use crate::loader::Registry;
use crate::pathfinding::{get_zoc_hexes, reachable_hexes};
use crate::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use crate::snapshot::{ActionRequest, StateSnapshot};
use crate::unit::{advance_unit, parse_alignment, Unit};
use godot::builtin::PackedInt32Array;
use godot::prelude::*;

/// GDExtension entry point — registers all Rust classes with Redot.
struct NorRustExtension;

#[gdextension]
unsafe impl ExtensionLibrary for NorRustExtension {}

/// The primary Rust node exposed to Redot.
/// Instantiate via NorRustCore.new() in GDScript.
#[derive(GodotClass)]
#[class(base=Node)]
pub struct NorRustCore {
    base: Base<Node>,
    units: Option<Registry<UnitDef>>,
    terrain: Option<Registry<TerrainDef>>,
    game: Option<GameState>,
    factions: Vec<(FactionDef, Vec<String>)>,  // (def, expanded+deduped recruit ids)
}

#[godot_api]
impl INode for NorRustCore {
    fn init(base: Base<Node>) -> Self {
        Self {
            base,
            units: None,
            terrain: None,
            game: None,
            factions: Vec::new(),
        }
    }
}

/// Map an ActionError to a negative integer error code for GDScript.
///
/// Codes:
///   -1 = UnitNotFound
///   -2 = NotYourTurn
///   -3 = DestinationOutOfBounds
///   -4 = DestinationOccupied
///   -5 = UnitAlreadyMoved
///   -6 = DestinationUnreachable
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
    }
}

#[godot_api]
impl NorRustCore {
    /// Returns the norrust_core library version string.
    #[func]
    fn get_core_version(&self) -> GString {
        "0.1.0".into()
    }

    /// Load all game data from `data_path/units/` and `data_path/terrain/`.
    /// Returns true on success, false on any IO or parse error.
    /// From GDScript: pass `ProjectSettings.globalize_path("res://") + "/../data"`
    #[func]
    fn load_data(&mut self, data_path: GString) -> bool {
        use std::path::PathBuf;
        let base = PathBuf::from(data_path.to_string());

        match Registry::<UnitDef>::load_from_dir(&base.join("units")) {
            Ok(registry) => self.units = Some(registry),
            Err(e) => {
                godot_error!("load_data: failed to load units: {}", e);
                return false;
            }
        }

        match Registry::<TerrainDef>::load_from_dir(&base.join("terrain")) {
            Ok(registry) => self.terrain = Some(registry),
            Err(e) => {
                godot_error!("load_data: failed to load terrain: {}", e);
                return false;
            }
        }

        godot_print!(
            "load_data: loaded {} units, {} terrain types",
            self.units.as_ref().map(|r| r.len()).unwrap_or(0),
            self.terrain.as_ref().map(|r| r.len()).unwrap_or(0),
        );
        true
    }

    /// Returns max_hp for the unit, or -1 if not found or data not loaded.
    #[func]
    fn get_unit_max_hp(&self, unit_id: GString) -> i32 {
        self.units
            .as_ref()
            .and_then(|r| r.get(&unit_id.to_string()))
            .map(|u| u.max_hp as i32)
            .unwrap_or(-1)
    }

    // ── GameState lifecycle ────────────────────────────────────────────────

    /// Create a new game with a `cols × rows` board and a deterministic RNG seed.
    /// Returns true on success. seed must be > 0.
    #[func]
    fn create_game(&mut self, cols: i32, rows: i32, seed: i64) -> bool {
        if cols <= 0 || rows <= 0 || seed <= 0 {
            godot_error!("create_game: cols, rows, and seed must all be > 0");
            return false;
        }
        let board = Board::new(cols as u32, rows as u32);
        self.game = Some(GameState::new_seeded(board, seed as u64));
        true
    }

    /// Set the terrain type for the hex at offset (col, row).
    /// Does nothing if no game has been created.
    #[func]
    fn set_terrain_at(&mut self, col: i32, row: i32, terrain_id: GString) {
        let Some(state) = self.game.as_mut() else { return };
        let hex = Hex::from_offset(col, row);
        if let Some(def) = self.terrain.as_ref().and_then(|r| r.get(&terrain_id.to_string())) {
            state.board.set_tile(hex, crate::board::Tile::from_def(def));
        } else {
            state.board.set_terrain(hex, terrain_id.to_string());
        }
    }

    /// Generate a procedural map layout using `seed`.
    /// Fills every hex with terrain, then upgrades all tiles via the TerrainDef registry.
    /// Returns true on success, false if no game exists or seed <= 0.
    ///
    /// Call this after `create_game()` instead of multiple `set_terrain_at()` calls.
    #[func]
    fn generate_map(&mut self, seed: i64) -> bool {
        if seed <= 0 { return false; }
        let Some(state) = self.game.as_mut() else { return false };

        // Generate terrain string IDs (registry-free)
        crate::mapgen::generate_map(&mut state.board, seed as u64);

        // Upgrade all tiles to Tile::from_def() using the terrain registry
        // Collect assignments first to avoid borrow conflicts
        let Some(registry) = self.terrain.as_ref() else { return true };
        let width = state.board.width as i32;
        let height = state.board.height as i32;
        let assignments: Vec<(Hex, crate::board::Tile)> = (0..width)
            .flat_map(|col| (0..height).map(move |row| (col, row)))
            .filter_map(|(col, row)| {
                let hex = Hex::from_offset(col, row);
                let terrain_id = state.board.terrain_at(hex)?.to_string();
                let def = registry.get(&terrain_id)?;
                Some((hex, crate::board::Tile::from_def(def)))
            })
            .collect();
        for (hex, tile) in assignments {
            state.board.set_tile(hex, tile);
        }
        true
    }

    /// Load board terrain from a TOML scenario file and create a new game.
    ///
    /// The board file must have `width`, `height`, and `tiles` (flat row-major array of terrain IDs).
    /// This replaces `create_game()` + `generate_map()` for scenario-based play.
    /// `seed` must be > 0 (used for combat RNG).
    /// Returns true on success, false on any error.
    #[func]
    fn load_board(&mut self, board_path: GString, seed: i64) -> bool {
        if seed <= 0 {
            godot_error!("load_board: seed must be > 0");
            return false;
        }
        let path = std::path::PathBuf::from(board_path.to_string());
        let board = match crate::scenario::load_board(&path) {
            Ok(b) => b,
            Err(e) => {
                godot_error!("{}", e);
                return false;
            }
        };
        self.game = Some(GameState::new_seeded(board, seed as u64));

        // Upgrade tiles from TerrainDef registry if available.
        // Collect-then-apply pattern avoids borrow conflict between terrain_at (&board)
        // and set_tile (&mut board).
        let Some(registry) = self.terrain.as_ref() else { return true };
        let Some(state) = self.game.as_mut() else { return true };
        let width = state.board.width as i32;
        let height = state.board.height as i32;
        let assignments: Vec<(Hex, crate::board::Tile)> = (0..width)
            .flat_map(|col| (0..height).map(move |row| (col, row)))
            .filter_map(|(col, row)| {
                let hex = Hex::from_offset(col, row);
                let terrain_id = state.board.terrain_at(hex)?.to_string();
                let def = registry.get(&terrain_id)?;
                Some((hex, crate::board::Tile::from_def(def)))
            })
            .collect();
        for (hex, tile) in assignments {
            state.board.set_tile(hex, tile);
        }
        true
    }

    /// Load unit placements from a TOML units file and place all units on the board.
    ///
    /// The file must contain `[[units]]` entries with `id`, `unit_type`, `faction`,
    /// `col`, `row`. Stats (hp, movement, attacks, etc.) are copied from the UnitDef
    /// registry by the existing `place_unit_at()` logic.
    /// Returns true on success, false if no game exists or the file cannot be read.
    #[func]
    fn load_units(&mut self, units_path: GString) -> bool {
        if self.game.is_none() {
            godot_error!("load_units: no game exists — call load_board() first");
            return false;
        }
        let path = std::path::PathBuf::from(units_path.to_string());
        let placements = match crate::scenario::load_units(&path) {
            Ok(p) => p,
            Err(e) => {
                godot_error!("{}", e);
                return false;
            }
        };
        for p in placements {
            self.place_unit_at(
                p.id as i32,
                p.unit_type.as_str().into(),
                0, // hp ignored — place_unit_at always sets max_hp from registry
                p.faction as i32,
                p.col,
                p.row,
            );
        }
        true
    }

    /// Returns the terrain id at offset (col, row), or "" if none is set.
    #[func]
    fn get_terrain_at(&self, col: i32, row: i32) -> GString {
        let Some(state) = self.game.as_ref() else { return "".into() };
        state.board.terrain_at(Hex::from_offset(col, row)).unwrap_or("").into()
    }

    /// Place a unit on the board at offset (col, row).
    /// Copies movement, movement_costs, attacks, and defense from the matching UnitDef
    /// if data has been loaded. Does nothing if no game has been created.
    #[func]
    fn place_unit_at(
        &mut self,
        unit_id: i32,
        def_id: GString,
        hp: i32,
        faction: i32,
        col: i32,
        row: i32,
    ) {
        if self.game.is_none() { return }

        let mut unit = Unit::new(unit_id as u32, def_id.to_string(), hp as u32, faction as u8);

        // Clone stat fields from UnitDef before mutably borrowing game.
        let def_stats = self.units.as_ref().and_then(|r| r.get(&def_id.to_string())).map(|def| {
            (def.max_hp, def.movement, def.movement_costs.clone(), def.attacks.clone(), def.defense.clone(), def.resistances.clone(), def.experience, def.alignment.clone())
        });

        if let Some((max_hp, movement, movement_costs, attacks, defense, resistances, experience, alignment)) = def_stats {
            unit.max_hp = max_hp;
            unit.hp = max_hp;
            unit.movement = movement;
            unit.movement_costs = movement_costs;
            unit.attacks = attacks;
            unit.defense = defense;
            unit.resistances = resistances;
            unit.xp_needed = experience;
            unit.alignment = parse_alignment(&alignment);
        } else {
            godot_warn!("place_unit_at: UnitDef '{}' not found, unit uses defaults", def_id);
        }

        let state = self.game.as_mut().unwrap();
        state.place_unit(unit, Hex::from_offset(col, row));
    }

    /// Remove the unit at offset (col, row). Returns true if a unit was removed.
    #[func]
    fn remove_unit_at(&mut self, col: i32, row: i32) -> bool {
        let Some(state) = self.game.as_mut() else { return false };
        let target_hex = Hex::from_offset(col, row);
        let uid = state.positions.iter()
            .find(|(_, &hex)| hex == target_hex)
            .map(|(&id, _)| id);
        let Some(uid) = uid else { return false };
        state.units.remove(&uid);
        state.positions.remove(&uid);
        true
    }

    /// Recruit a unit of `def_id` type onto the castle hex at (col, row).
    /// Uses the active faction and deducts the unit's gold cost from state.gold.
    /// Returns 0 on success, -1 if no game/registry/def not found, or a negative error code.
    #[func]
    fn recruit_unit_at(&mut self, unit_id: i32, def_id: GString, col: i32, row: i32) -> i32 {
        if self.game.is_none() { return -1; }
        let def_id_str = def_id.to_string();

        // Clone all needed data from def before mutably borrowing game
        let def_data = self.units.as_ref()
            .and_then(|r| r.get(&def_id_str))
            .map(|def| (
                def.max_hp,
                def.movement,
                def.movement_costs.clone(),
                def.attacks.clone(),
                def.defense.clone(),
                def.resistances.clone(),
                def.experience,
                def.alignment.clone(),
                def.cost,
            ));

        let Some((max_hp, movement, movement_costs, attacks, defense, resistances, experience, alignment, cost)) = def_data else {
            godot_warn!("recruit_unit_at: UnitDef '{}' not found", def_id);
            return -1;
        };

        let state = self.game.as_mut().unwrap();
        let faction = state.active_faction;

        let mut unit = Unit::new(unit_id as u32, def_id_str, max_hp, faction);
        unit.max_hp = max_hp;
        unit.hp = max_hp;
        unit.movement = movement;
        unit.movement_costs = movement_costs;
        unit.attacks = attacks;
        unit.defense = defense;
        unit.resistances = resistances;
        unit.xp_needed = experience;
        unit.alignment = parse_alignment(&alignment);

        let destination = Hex::from_offset(col, row);
        match apply_recruit(state, unit, destination, cost) {
            Ok(()) => 0,
            Err(e) => action_err_code(e),
        }
    }

    /// Returns the gold cost of the unit def, or 0 if not found.
    #[func]
    fn get_unit_cost(&self, def_id: GString) -> i32 {
        self.units.as_ref()
            .and_then(|r| r.get(&def_id.to_string()))
            .map(|u| u.cost as i32)
            .unwrap_or(0)
    }

    /// Apply a Move action. Returns 0 on success, a negative error code on failure.
    /// Error codes: -1=UnitNotFound, -2=NotYourTurn, -3=OutOfBounds,
    ///              -4=Occupied, -5=AlreadyMoved, -6=Unreachable
    #[func]
    fn apply_move(&mut self, unit_id: i32, col: i32, row: i32) -> i32 {
        let Some(state) = self.game.as_mut() else { return -1 };
        match apply_action(
            state,
            Action::Move {
                unit_id: unit_id as u32,
                destination: Hex::from_offset(col, row),
            },
        ) {
            Ok(()) => 0,
            Err(e) => action_err_code(e),
        }
    }

    /// Advance a unit to its next form. The unit must belong to the active faction
    /// and have advancement_pending = true.
    ///
    /// Returns:
    ///   0  = success
    ///  -1  = unit not found
    ///  -2  = not your turn (unit belongs to wrong faction)
    ///  -8  = unit not ready to advance (advancement_pending is false)
    ///  -9  = no advancement target (advances_to is empty)
    /// -10  = target UnitDef not found in registry
    #[func]
    fn apply_advance(&mut self, unit_id: i32) -> i32 {
        let Some(state) = self.game.as_mut() else { return -1 };
        let uid = unit_id as u32;

        let (current_def_id, advancement_pending, faction) = match state.units.get(&uid) {
            Some(u) => (u.def_id.clone(), u.advancement_pending, u.faction),
            None => return -1,
        };
        if faction != state.active_faction {
            return -2;
        }
        if !advancement_pending {
            return -8;
        }

        let target_def_id = match self.units.as_ref()
            .and_then(|r| r.get(&current_def_id))
            .and_then(|def| def.advances_to.first().cloned())
        {
            Some(id) => id,
            None => return -9,
        };

        let new_def = match self.units.as_ref().and_then(|r| r.get(&target_def_id)) {
            Some(def) => def.clone(),
            None => return -10,
        };

        advance_unit(state.units.get_mut(&uid).unwrap(), &new_def);
        0
    }

    /// Apply an Attack action. Returns 0 on success, a negative error code on failure.
    #[func]
    fn apply_attack(&mut self, attacker_id: i32, defender_id: i32) -> i32 {
        let Some(state) = self.game.as_mut() else { return -1 };
        match apply_action(
            state,
            Action::Attack {
                attacker_id: attacker_id as u32,
                defender_id: defender_id as u32,
            },
        ) {
            Ok(()) => 0,
            Err(e) => action_err_code(e),
        }
    }

    /// Apply an EndTurn action. Returns 0 on success, -1 if no game exists.
    #[func]
    fn end_turn(&mut self) -> i32 {
        let Some(state) = self.game.as_mut() else { return -1 };
        match apply_action(state, Action::EndTurn) {
            Ok(()) => 0,
            Err(e) => action_err_code(e),
        }
    }

    // ── GameState queries ──────────────────────────────────────────────────

    /// Returns the active faction (0 or 1), or -1 if no game exists.
    #[func]
    fn get_active_faction(&self) -> i32 {
        self.game.as_ref().map(|s| s.active_faction as i32).unwrap_or(-1)
    }

    /// Returns the current turn number, or -1 if no game exists.
    #[func]
    fn get_turn(&self) -> i32 {
        self.game.as_ref().map(|s| s.turn as i32).unwrap_or(-1)
    }

    /// Returns "Day", "Night", or "Neutral" for the current turn's time of day.
    /// Returns "Neutral" if no game exists.
    #[func]
    fn get_time_of_day_name(&self) -> GString {
        let turn = self.game.as_ref().map(|s| s.turn).unwrap_or(1);
        match time_of_day(turn) {
            TimeOfDay::Day     => "Day",
            TimeOfDay::Night   => "Night",
            TimeOfDay::Neutral => "Neutral",
        }.into()
    }

    /// Returns the winning faction (0 or 1) when one faction has no units left.
    /// Returns -1 if the game is ongoing or no game exists.
    #[func]
    fn get_winner(&self) -> i32 {
        let Some(state) = self.game.as_ref() else { return -1 };
        let has_0 = state.units.values().any(|u| u.faction == 0);
        let has_1 = state.units.values().any(|u| u.faction == 1);
        match (has_0, has_1) {
            (true, false) => 0,
            (false, true) => 1,
            _ => -1,
        }
    }

    /// Returns reachable hexes for a unit as a flat PackedInt32Array: [col, row, ...].
    /// Uses the unit's movement budget and movement_costs. Returns empty if unit not found.
    #[func]
    fn get_reachable_hexes(&self, unit_id: i32) -> PackedInt32Array {
        let Some(state) = self.game.as_ref() else {
            return PackedInt32Array::new();
        };
        let uid = unit_id as u32;
        let Some(unit) = state.units.get(&uid) else {
            return PackedInt32Array::new();
        };
        let Some(&start) = state.positions.get(&uid) else {
            return PackedInt32Array::new();
        };

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

        let mut arr = PackedInt32Array::new();
        for hex in hexes {
            let (col, row) = hex.to_offset();
            arr.push(col);
            arr.push(row);
        }
        arr
    }

    // ── AI / External API ──────────────────────────────────────────────────

    /// Let the AI play all units for `faction` (must be 0 or 1), then call EndTurn.
    /// No-op if no game exists or faction is invalid.
    /// After this call, `get_active_faction()` will return the opposite faction.
    #[func]
    fn ai_take_turn(&mut self, faction: i32) {
        let Some(state) = self.game.as_mut() else { return };
        if faction < 0 || faction > 1 { return }
        crate::ai::ai_take_turn(state, faction as u8);
    }

    /// Serializes the current game state as a JSON string for external consumers.
    /// Returns "" if no game has been created or serialization fails.
    ///
    /// JSON shape:
    ///   { "turn": N, "active_faction": 0|1, "cols": N, "rows": N,
    ///     "terrain": [{"col":C,"row":R,"terrain_id":"..."}, ...],
    ///     "units":   [{"id":N,"def_id":"...","col":C,"row":R,
    ///                  "faction":0|1,"hp":N,"max_hp":N,"moved":bool,"attacked":bool}, ...] }
    #[func]
    fn get_state_json(&self) -> GString {
        let Some(state) = self.game.as_ref() else { return "".into() };
        match serde_json::to_string(&StateSnapshot::from_game_state(state)) {
            Ok(s) => s.into(),
            Err(e) => {
                godot_error!("get_state_json: serialization failed: {}", e);
                "".into()
            }
        }
    }

    // ── Faction / recruitment ──────────────────────────────────────────────

    /// Load faction and recruit-group data from `data_path/factions/` and
    /// `data_path/recruit_groups/`. Expands group references, deduplicates, and
    /// stores the results in `self.factions`. Returns true on success.
    #[func]
    fn load_factions(&mut self, data_path: GString) -> bool {
        use std::path::PathBuf;
        let base = PathBuf::from(data_path.to_string());

        let groups = match Registry::<RecruitGroup>::load_from_dir(&base.join("recruit_groups")) {
            Ok(r) => r,
            Err(e) => { godot_error!("load_factions: {}", e); return false; }
        };
        let faction_reg = match Registry::<FactionDef>::load_from_dir(&base.join("factions")) {
            Ok(r) => r,
            Err(e) => { godot_error!("load_factions: {}", e); return false; }
        };

        self.factions = faction_reg.all().map(|f| {
            let mut recruits: Vec<String> = Vec::new();
            for entry in &f.recruits {
                if let Some(grp) = groups.get(entry) {
                    recruits.extend(grp.members.iter().cloned());
                } else {
                    recruits.push(entry.clone());
                }
            }
            // Dedup preserving insertion order
            let mut seen = std::collections::HashSet::new();
            recruits.retain(|id| seen.insert(id.clone()));
            (f.clone(), recruits)
        }).collect();

        godot_print!("load_factions: loaded {} factions", self.factions.len());
        true
    }

    /// Returns a JSON array of faction objects: [{"id":"loyalists","name":"Loyalists"}, ...]
    #[func]
    fn get_faction_ids_json(&self) -> GString {
        let arr: Vec<String> = self.factions.iter()
            .map(|(f, _)| format!("{{\"id\":\"{}\",\"name\":\"{}\"}}", f.id, f.name))
            .collect();
        format!("[{}]", arr.join(",")).into()
    }

    /// Returns the `leader_def` string for the given faction, or `""` if not found.
    #[func]
    fn get_faction_leader(&self, faction_id: GString) -> GString {
        let id = faction_id.to_string();
        self.factions.iter()
            .find(|(f, _)| f.id == id)
            .map(|(f, _)| f.leader_def.as_str())
            .unwrap_or("")
            .into()
    }

    /// Returns JSON array of def_id strings for the faction's recruits, filtered by
    /// level ≤ max_level. `max_level <= 0` means no filter.
    #[func]
    fn get_faction_recruits_json(&self, faction_id: GString, max_level: i32) -> GString {
        let id = faction_id.to_string();
        let Some((_, recruits)) = self.factions.iter().find(|(f, _)| f.id == id) else {
            return "[]".into();
        };
        let filtered: Vec<String> = recruits.iter()
            .filter(|def_id| {
                if max_level <= 0 { return true; }
                self.units.as_ref()
                    .and_then(|r| r.get(*def_id))
                    .map(|u| u.level as i32 <= max_level)
                    .unwrap_or(true)
            })
            .map(|id| format!("\"{}\"", id))
            .collect();
        format!("[{}]", filtered.join(",")).into()
    }

    /// Set state.gold from the loaded faction definitions.
    /// Call after load_factions() + load_board(), once both faction IDs are known.
    /// Returns true on success, false if either faction ID not found or no game loaded.
    #[func]
    fn apply_starting_gold(&mut self, f0_id: GString, f1_id: GString) -> bool {
        let Some(state) = self.game.as_mut() else { return false; };
        let f0_id = f0_id.to_string();
        let f1_id = f1_id.to_string();
        let gold0 = self.factions.iter()
            .find(|(f, _)| f.id == f0_id)
            .map(|(f, _)| f.starting_gold);
        let gold1 = self.factions.iter()
            .find(|(f, _)| f.id == f1_id)
            .map(|(f, _)| f.starting_gold);
        match (gold0, gold1) {
            (Some(g0), Some(g1)) => { state.gold = [g0, g1]; true }
            _ => { godot_error!("apply_starting_gold: faction id not found"); false }
        }
    }

    /// Returns the level of the unit def, or 1 if not found.
    #[func]
    fn get_unit_level(&self, def_id: GString) -> i32 {
        self.units.as_ref()
            .and_then(|r| r.get(&def_id.to_string()))
            .map(|u| u.level as i32)
            .unwrap_or(1)
    }

    /// Parse a JSON action string and apply it to the game.
    /// Returns 0 on success, -99 on JSON parse error, or a negative ActionError code.
    ///
    /// Supported formats:
    ///   {"action":"Move","unit_id":1,"col":3,"row":2}
    ///   {"action":"Attack","attacker_id":1,"defender_id":2}
    ///   {"action":"EndTurn"}
    #[func]
    fn apply_action_json(&mut self, json: GString) -> i32 {
        if self.game.is_none() { return -1 }
        let req: ActionRequest = match serde_json::from_str(&json.to_string()) {
            Ok(r) => r,
            Err(e) => {
                godot_error!("apply_action_json: parse error: {}", e);
                return -99;
            }
        };
        match req {
            ActionRequest::Advance { unit_id } => self.apply_advance(unit_id as i32),
            ActionRequest::Recruit { unit_id, def_id, col, row } => {
                self.recruit_unit_at(unit_id as i32, def_id.into(), col, row)
            }
            other => {
                let Some(state) = self.game.as_mut() else { return -1 };
                match apply_action(state, other.into()) {
                    Ok(()) => 0,
                    Err(e) => action_err_code(e),
                }
            }
        }
    }
}
