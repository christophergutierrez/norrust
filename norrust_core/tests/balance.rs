//! Balance testing — run AI-vs-AI games and report win rates.
//!
//! Run with: cargo test --test balance -- --nocapture
//! Or for a specific scenario: cargo test --test balance crossing -- --nocapture

use std::collections::HashSet;
use std::path::{Path, PathBuf};

use norrust_core::ai::ai_take_turn;
use norrust_core::board::Tile;
use norrust_core::game_state::{apply_recruit, GameState, PendingSpawn, TriggerZone};
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::scenario::{load_board, load_units, load_triggers};
use norrust_core::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use norrust_core::unit::Unit;

fn data_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../data")
}

fn scenarios_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../scenarios")
}

/// Expanded faction: definition + flat recruit list + unit registry reference.
struct Faction {
    def: FactionDef,
    recruits: Vec<String>,
}

fn load_factions(data: &Path) -> Vec<Faction> {
    let groups: Registry<RecruitGroup> =
        Registry::load_from_dir(&data.join("recruit_groups")).unwrap();
    let faction_reg: Registry<FactionDef> =
        Registry::load_from_dir(&data.join("factions")).unwrap();

    faction_reg
        .all()
        .map(|f| {
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
            Faction { def: f.clone(), recruits }
        })
        .collect()
}

fn upgrade_tiles(state: &mut GameState, terrain_reg: &Registry<TerrainDef>) {
    let width = state.board.width as i32;
    let height = state.board.height as i32;
    let assignments: Vec<(Hex, Tile)> = (0..width)
        .flat_map(|col| (0..height).map(move |row| (col, row)))
        .filter_map(|(col, row)| {
            let hex = Hex::from_offset(col, row);
            let terrain_id = state.board.terrain_at(hex)?.to_string();
            let def = terrain_reg.get(&terrain_id)?;
            Some((hex, Tile::from_def(def)))
        })
        .collect();
    for (hex, tile) in assignments {
        state.board.set_tile(hex, tile);
    }
}

/// AI recruitment: fill castle hexes adjacent to leader's keep.
fn ai_recruit(
    state: &mut GameState,
    faction: u8,
    recruits: &[String],
    unit_reg: &Registry<UnitDef>,
    next_id: &mut u32,
) {
    for _ in 0..12 {
        // Find leader on a keep.
        let keep = state.positions.iter().find_map(|(&uid, &hex)| {
            let unit = state.units.get(&uid)?;
            if unit.faction != faction { return None; }
            if !unit.abilities.iter().any(|a| a == "leader") { return None; }
            state.board.tile_at(hex).filter(|t| t.terrain_id == "keep").map(|_| hex)
        });
        let Some(keep_hex) = keep else { break };

        // Find empty castle adjacent to keep.
        let dest = keep_hex.neighbors().iter().copied().find(|&h| {
            state.board.contains(h)
                && state.board.tile_at(h).map(|t| t.terrain_id == "castle").unwrap_or(false)
                && !state.positions.values().any(|&p| p == h)
        });
        let Some(dest_hex) = dest else { break };

        // Pick first affordable recruit.
        let affordable = recruits.iter().find(|did| {
            unit_reg.get(did.as_str())
                .map(|def| state.gold[faction as usize] >= def.cost)
                .unwrap_or(false)
        });
        let Some(def_id) = affordable else { break };
        let def = unit_reg.get(def_id.as_str()).unwrap();
        let cost = def.cost;

        let unit = Unit::from_def(*next_id, def, faction);
        match apply_recruit(state, unit, dest_hex, cost) {
            Ok(()) => { *next_id += 1; }
            Err(_) => break,
        }
    }
}

struct BalanceResult {
    wins: [u32; 2],
    draws: u32,
    total: u32,
}

impl std::fmt::Display for BalanceResult {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        let pct0 = if self.total > 0 { self.wins[0] as f64 / self.total as f64 * 100.0 } else { 0.0 };
        let pct1 = if self.total > 0 { self.wins[1] as f64 / self.total as f64 * 100.0 } else { 0.0 };
        write!(
            f,
            "F0: {}/{} ({:.1}%)  F1: {}/{} ({:.1}%)  Draws: {}",
            self.wins[0], self.total, pct0,
            self.wins[1], self.total, pct1,
            self.draws,
        )
    }
}

fn run_balance(
    scenario: &str,
    num_games: u32,
    f0_faction: &str,
    f1_faction: &str,
) -> BalanceResult {
    let data = data_dir();
    let unit_reg: Registry<UnitDef> = Registry::load_from_dir(&data.join("units")).unwrap();
    let terrain_reg: Registry<TerrainDef> = Registry::load_from_dir(&data.join("terrain")).unwrap();
    let factions = load_factions(&data);

    let f0 = factions.iter().find(|f| f.def.id == f0_faction).unwrap();
    let f1 = factions.iter().find(|f| f.def.id == f1_faction).unwrap();

    let scenario_dir = scenarios_dir().join(scenario);
    let board_path = scenario_dir.join("board.toml");
    let units_path = scenario_dir.join("units.toml");

    let mut result = BalanceResult { wins: [0, 0], draws: 0, total: num_games };

    for seed in 1..=num_games {
        let loaded = load_board(&board_path).unwrap();
        let placements = load_units(&units_path).unwrap();
        let triggers = load_triggers(&units_path).unwrap_or_default();

        let mut state = GameState::new_seeded(loaded.board, seed as u64);
        state.objective_hex = loaded.objective_hex;
        state.max_turns = loaded.max_turns;

        upgrade_tiles(&mut state, &terrain_reg);

        // Place scenario units.
        let mut next_id = 1u32;
        for p in &placements {
            let faction = p.faction as u8;
            if let Some(def) = unit_reg.get(&p.unit_type) {
                let unit = Unit::from_def(next_id, def, faction);
                state.place_unit(unit, Hex::from_offset(p.col, p.row));
                next_id += 1;
            }
        }

        // Register trigger zones.
        for tdef in &triggers {
            let spawns: Vec<PendingSpawn> = tdef.spawns.iter().map(|s| {
                let uid = next_id;
                next_id += 1;
                let unit = if let Some(def) = unit_reg.get(&s.unit_type) {
                    Unit::from_def(uid, def, s.faction)
                } else {
                    Unit::new(uid, &s.unit_type, 1, s.faction)
                };
                PendingSpawn { unit, destination: Hex::from_offset(s.col, s.row) }
            }).collect();
            state.trigger_zones.push(TriggerZone {
                trigger_hex: Hex::from_offset(tdef.trigger_col, tdef.trigger_row),
                trigger_faction: tdef.trigger_faction,
                spawns,
                triggered: false,
            });
        }

        // Set starting gold.
        state.gold = [f0.def.starting_gold, f1.def.starting_gold];

        let faction_data: [&Faction; 2] = [f0, f1];
        let max_turns = 200;

        for _ in 0..max_turns {
            let active = state.active_faction;
            let fd = faction_data[active as usize];

            // Recruit before moving/attacking.
            ai_recruit(&mut state, active, &fd.recruits, &unit_reg, &mut next_id);

            // AI takes turn (move, attack, end turn).
            ai_take_turn(&mut state, active);

            if let Some(winner) = state.check_winner() {
                result.wins[winner as usize] += 1;
                break;
            }
        }

        // If no winner after max_turns, count as draw.
        if state.check_winner().is_none() {
            result.draws += 1;
        }
    }

    result
}

#[test]
fn balance_crossing() {
    let r = run_balance("crossing", 1000, "loyalists", "orcs");
    println!("Crossing (Loyalists vs Orcs, 1000 games): {}", r);
}

#[test]
fn balance_night_orcs() {
    let r = run_balance("night_orcs", 1000, "loyalists", "orcs");
    println!("Night Orcs (Loyalists vs Orcs, 1000 games): {}", r);
}

#[test]
fn balance_final_battle() {
    let r = run_balance("final_battle", 1000, "loyalists", "orcs");
    println!("Final Battle (Loyalists vs Orcs, 1000 games): {}", r);
}

#[test]
fn balance_contested() {
    let r = run_balance("contested", 1000, "loyalists", "orcs");
    println!("Contested (Loyalists vs Orcs, 1000 games): {}", r);
}
