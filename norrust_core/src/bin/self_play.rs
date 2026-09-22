//! Standalone headless self-play runner.
//!
//! Example:
//! cargo run --release --bin self-play -- --scenario big_battle_6 \
//!   --team1 northerners --team2 undead --ai1 greedy-look-ahead --ai2 greedy \
//!   --games 100

use norrust_core::save::SaveState;
use std::collections::HashSet;
use std::env;
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

use norrust_core::ai::{
    ai_take_turn_coordinated, ai_take_turn_greedy, ai_take_turn_with_recruits_recorded,
    ActionRecord,
};
use norrust_core::board::Tile;
use norrust_core::game_state::{apply_action, apply_recruit, Action, GameState};
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::pathfinding::{get_zoc_hexes, reachable_hexes};
use norrust_core::scenario::load_board;
use norrust_core::schema::{AttackDef, FactionDef, RecruitGroup, TerrainDef, UnitDef};
use norrust_core::unit::Unit;

#[derive(Clone, Copy)]
enum AiKind {
    Greedy,
    Lookahead,
    Coordinated,
    Random,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RecruitPolicy {
    FirstAffordable,
    Balanced,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum RecruitRole {
    Melee,
    Ranged,
    Other,
}

#[derive(Clone, Copy, Debug, Default)]
struct RecruitSummary {
    recruited: u32,
    melee: u32,
    ranged: u32,
    other: u32,
    balanced_fallbacks: u32,
}

fn role_for_attacks(attacks: &[AttackDef]) -> RecruitRole {
    if attacks.iter().any(|attack| attack.range == "ranged") {
        RecruitRole::Ranged
    } else if attacks.iter().any(|attack| attack.range == "melee") {
        RecruitRole::Melee
    } else {
        RecruitRole::Other
    }
}

fn role_for_def(def: &UnitDef) -> RecruitRole {
    role_for_attacks(&def.attacks)
}

fn recruit_policy_name(policy: RecruitPolicy) -> &'static str {
    match policy {
        RecruitPolicy::FirstAffordable => "first-affordable",
        RecruitPolicy::Balanced => "balanced",
    }
}

fn recruit_policy_for_side(config: &Config, side: u8) -> RecruitPolicy {
    match side {
        0 => config.recruit1_policy,
        1 => config.recruit2_policy,
        _ => panic!("invalid self-play side {side}"),
    }
}

fn side_turn_cap(config: &Config) -> u32 {
    config.max_side_turns.unwrap_or(DEFAULT_SIDE_TURN_CAP)
}

fn choose_balanced_recruit(
    affordable: &[&UnitDef],
    state: &GameState,
    side: u8,
) -> Option<(usize, RecruitRole, bool)> {
    let (melee, ranged) = state
        .units
        .values()
        .filter(|unit| unit.faction == side)
        .map(|unit| role_for_attacks(&unit.attacks))
        .fold((0, 0), |(melee, ranged), role| match role {
            RecruitRole::Melee => (melee + 1, ranged),
            RecruitRole::Ranged => (melee, ranged + 1),
            RecruitRole::Other => (melee, ranged),
        });
    let wanted = if ranged < melee {
        RecruitRole::Ranged
    } else {
        RecruitRole::Melee
    };
    affordable
        .iter()
        .position(|def| role_for_def(def) == wanted)
        .map(|index| (index, wanted, false))
        .or_else(|| affordable.first().map(|def| (0, role_for_def(def), true)))
}

#[derive(Clone, Copy)]
enum FirstPlayer {
    Team1,
    Team2,
    CoinFlip,
}

#[derive(Clone)]
struct Config {
    scenario: String,
    team1: String,
    team2: String,
    ai1: AiKind,
    ai2: AiKind,
    games: u32,
    seed: u64,
    gold: Option<u32>,
    gold1: Option<u32>,
    gold2: Option<u32>,
    max_side_turns: Option<u32>,
    verbose: bool,
    compact: bool,
    json: bool,
    threads: usize,
    first: FirstPlayer,
    second_gold: u32,
    record_dir: Option<PathBuf>,
    recruit1_policy: RecruitPolicy,
    recruit2_policy: RecruitPolicy,
}

#[derive(Clone)]
struct Faction {
    def: FactionDef,
    recruits: Vec<String>,
}

#[derive(Clone, Copy, Debug)]
struct GameResult {
    game: u32,
    raw_seed: u64,
    effective_seed: u64,
    winner: Option<u8>,
    termination_reason: TerminationReason,
    completed_side_turns: u32,
    engine_turn: u32,
    material: i32,
    first: u8,
    starting_gold: [u32; 2],
    ending_gold: [u32; 2],
    recruits: [u32; 2],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TerminationReason {
    Winner,
    SideTurnCap,
}

const DEFAULT_SIDE_TURN_CAP: u32 = 200;

fn usage() -> ! {
    eprintln!(
        "Usage: self-play --team1 ID --team2 ID [options]

Options:
  --scenario NAME       Scenario directory name (default: big_battle_6)
  --team1 ID            Faction on side 1
  --team2 ID            Faction on side 2
  --ai1 KIND             greedy | greedy-look-ahead | coordinated | random (default: greedy)
  --ai2 KIND             greedy | greedy-look-ahead | coordinated | random (default: greedy)
  --games N             Number of games (default: 100)
  --seed N              First deterministic seed (default: 1)
  --gold N              Starting gold for both teams
  --gold1 N             Starting gold for team 1
  --gold2 N             Starting gold for team 2
  --max-side-turns N    Side-turn safety cap (default: 200)
  --threads N           Worker threads (default: available CPUs)
  --first SIDE           team1 | team2 | coin-flip (default: team1)
  --second-gold N        Extra starting gold for the second player (default: 5)
  --record-dir PATH     Write isolated state trajectories (directory must be new)
  --recruit1-policy KIND  team 1 recruitment: first-affordable | balanced
  --recruit2-policy KIND  team 2 recruitment: first-affordable | balanced
  --verbose             CSV header plus one line per game
  --compact             One comma-separated summary line
  --json                One structured JSON result object per game
  -h, --help            Show this help"
    );
    std::process::exit(2)
}

fn parse_ai(s: &str) -> AiKind {
    match s {
        "greedy" => AiKind::Greedy,
        "greedy-look-ahead" => AiKind::Lookahead,
        "coordinated" => AiKind::Coordinated,
        "random" => AiKind::Random,
        _ => usage(),
    }
}

fn parse_first(s: &str) -> FirstPlayer {
    match s {
        "team1" => FirstPlayer::Team1,
        "team2" => FirstPlayer::Team2,
        "coin-flip" => FirstPlayer::CoinFlip,
        _ => usage(),
    }
}

fn parse_args() -> Config {
    let mut c = Config {
        scenario: "big_battle_6".into(),
        team1: String::new(),
        team2: String::new(),
        ai1: AiKind::Greedy,
        ai2: AiKind::Greedy,
        games: 100,
        seed: 1,
        gold: None,
        gold1: None,
        gold2: None,
        max_side_turns: None,
        verbose: false,
        compact: false,
        json: false,
        threads: thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1),
        first: FirstPlayer::Team1,
        second_gold: 5,
        record_dir: None,
        recruit1_policy: RecruitPolicy::FirstAffordable,
        recruit2_policy: RecruitPolicy::FirstAffordable,
    };
    let args: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        let key = &args[i];
        if key == "--verbose" {
            c.verbose = true;
            i += 1;
            continue;
        }
        if key == "--compact" {
            c.compact = true;
            i += 1;
            continue;
        }
        if key == "--json" {
            c.json = true;
            i += 1;
            continue;
        }
        if key == "-h" || key == "--help" {
            usage();
        }
        if i + 1 >= args.len() {
            usage();
        }
        let value = &args[i + 1];
        match key.as_str() {
            "--record-dir" => c.record_dir = Some(PathBuf::from(value)),
            "--recruit1-policy" => {
                c.recruit1_policy = match value.as_str() {
                    "first-affordable" => RecruitPolicy::FirstAffordable,
                    "balanced" => RecruitPolicy::Balanced,
                    _ => usage(),
                }
            }
            "--recruit2-policy" => {
                c.recruit2_policy = match value.as_str() {
                    "first-affordable" => RecruitPolicy::FirstAffordable,
                    "balanced" => RecruitPolicy::Balanced,
                    _ => usage(),
                }
            }
            "--scenario" => c.scenario = value.clone(),
            "--team1" => c.team1 = value.clone(),
            "--team2" => c.team2 = value.clone(),
            "--ai1" => c.ai1 = parse_ai(value),
            "--ai2" => c.ai2 = parse_ai(value),
            "--games" => c.games = value.parse().unwrap_or_else(|_| usage()),
            "--seed" => c.seed = value.parse().unwrap_or_else(|_| usage()),
            "--gold" => c.gold = Some(value.parse().unwrap_or_else(|_| usage())),
            "--gold1" => c.gold1 = Some(value.parse().unwrap_or_else(|_| usage())),
            "--gold2" => c.gold2 = Some(value.parse().unwrap_or_else(|_| usage())),
            "--max-side-turns" => {
                let cap = value.parse().unwrap_or_else(|_| usage());
                if cap == 0 {
                    usage();
                }
                c.max_side_turns = Some(cap);
            }
            "--threads" => c.threads = value.parse().unwrap_or_else(|_| usage()),
            "--first" => c.first = parse_first(value),
            "--second-gold" => c.second_gold = value.parse().unwrap_or_else(|_| usage()),
            _ => usage(),
        }
        i += 2;
    }
    if c.team1.is_empty() || c.team2.is_empty() || c.games == 0 || c.threads == 0 {
        usage();
    }
    if c.verbose as u8 + c.compact as u8 + c.json as u8 > 1 {
        eprintln!("--verbose, --compact, and --json cannot be combined");
        usage();
    }
    c
}

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

fn mix_seed(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e3779b97f4a7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d049bb133111eb);
    let mixed = value ^ (value >> 31);
    if mixed == 0 {
        1
    } else {
        mixed
    }
}

fn load_factions(data: &Path) -> Vec<Faction> {
    let groups: Registry<RecruitGroup> =
        Registry::load_from_dir(&data.join("recruit_groups")).expect("load recruit groups");
    let registry: Registry<FactionDef> =
        Registry::load_from_dir(&data.join("factions")).expect("load factions");
    registry
        .all()
        .map(|def| {
            let mut recruits = Vec::new();
            for entry in &def.recruits {
                if let Some(group) = groups.get(entry) {
                    recruits.extend(group.members.iter().cloned());
                } else {
                    recruits.push(entry.clone());
                }
            }
            let mut seen = HashSet::new();
            recruits.retain(|id| seen.insert(id.clone()));
            Faction {
                def: def.clone(),
                recruits,
            }
        })
        .collect()
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

fn keep_for(state: &GameState, side: u8) -> Hex {
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
        keeps[0]
    } else {
        *keeps.last().expect("scenario needs two keeps")
    }
}

fn recruit(
    state: &mut GameState,
    side: u8,
    faction: &Faction,
    units: &Registry<UnitDef>,
    next_id: &mut u32,
    policy: RecruitPolicy,
) -> RecruitSummary {
    let mut summary = RecruitSummary::default();
    loop {
        let keep = state
            .positions
            .iter()
            .filter_map(|(&id, &h)| {
                let u = state.units.get(&id)?;
                (u.faction == side
                    && u.can_recruit
                    && state
                        .board
                        .tile_at(h)
                        .map(|t| t.terrain_id == "keep")
                        .unwrap_or(false))
                .then_some((h.to_offset(), id, h))
            })
            .min_by_key(|(offset, id, _)| (*offset, *id))
            .map(|(_, _, h)| h);
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
            if apply_action(
                state,
                Action::Move {
                    unit_id: id,
                    destination: move_dest,
                },
            )
            .is_err()
            {
                break;
            }
            dest = Some(castle);
        }
        let dest = dest.expect("recruitment destination must exist");
        let affordable: Vec<&UnitDef> = faction
            .recruits
            .iter()
            .filter_map(|id| units.get(id))
            .filter(|d| state.gold[side as usize] >= d.cost)
            .collect();
        let choice = match policy {
            RecruitPolicy::FirstAffordable => {
                affordable.first().map(|def| (0, role_for_def(def), false))
            }
            RecruitPolicy::Balanced => choose_balanced_recruit(&affordable, state, side),
        };
        let Some((choice_index, role, balanced_fallback)) = choice else {
            break;
        };
        let def = affordable[choice_index];
        let cost = def.cost;
        if apply_recruit(state, Unit::from_def(*next_id, def, side), dest, cost).is_err() {
            break;
        }
        *next_id += 1;
        summary.recruited += 1;
        match role {
            RecruitRole::Melee => summary.melee += 1,
            RecruitRole::Ranged => summary.ranged += 1,
            RecruitRole::Other => summary.other += 1,
        }
        if balanced_fallback {
            summary.balanced_fallbacks += 1;
        }
    }
    summary
}

fn legal_random_action(state: &GameState, side: u8) -> Vec<Action> {
    let mut actions = Vec::new();
    let ids: Vec<u32> = state
        .units
        .iter()
        .filter(|(_, u)| u.faction == side && (!u.moved || !u.attacked))
        .map(|(&id, _)| id)
        .collect();
    for id in ids {
        let u = &state.units[&id];
        let start = state.positions[&id];
        if !u.moved {
            let occupied: HashSet<Hex> = state
                .hex_to_unit
                .keys()
                .copied()
                .filter(|h| *h != start)
                .collect();
            let zoc = get_zoc_hexes(state, side);
            for dest in reachable_hexes(
                &state.board,
                &u.movement_costs,
                1,
                start,
                if u.slowed { u.movement / 2 } else { u.movement },
                &zoc,
                false,
            ) {
                if !occupied.contains(&dest) && dest != start {
                    actions.push(Action::Move {
                        unit_id: id,
                        destination: dest,
                    });
                }
            }
        }
        if !u.attacked {
            for (&eid, enemy) in &state.units {
                if enemy.faction == 1 - side {
                    let dist = start.distance(state.positions[&eid]);
                    if u.attacks.iter().any(|a| {
                        (a.range == "melee" && dist == 1) || (a.range == "ranged" && dist == 2)
                    }) {
                        actions.push(Action::Attack {
                            attacker_id: id,
                            defender_id: eid,
                        });
                    }
                }
            }
        }
    }
    actions
}

fn random_turn(state: &mut GameState, side: u8, rng: &mut u64) {
    for _ in 0..256 {
        let actions = legal_random_action(state, side);
        if actions.is_empty() {
            break;
        }
        *rng ^= *rng << 7;
        *rng ^= *rng >> 9;
        *rng ^= *rng << 8;
        let action = actions[(*rng as usize) % actions.len()].clone();
        let _ = apply_action(state, action);
    }
    let _ = apply_action(state, Action::EndTurn);
}

fn play_turn(
    state: &mut GameState,
    side: u8,
    kind: AiKind,
    rng: &mut u64,
    faction: &Faction,
    units: &Registry<UnitDef>,
) -> Vec<ActionRecord> {
    match kind {
        AiKind::Greedy => {
            ai_take_turn_greedy(state, side);
            Vec::new()
        }
        AiKind::Lookahead => {
            let recruit_defs: Vec<(u32, u32)> = faction
                .recruits
                .iter()
                .filter_map(|id| units.get(id).map(|def| (def.cost, def.movement)))
                .collect();
            let cheapest = recruit_defs
                .iter()
                .map(|(cost, _)| *cost)
                .min()
                .unwrap_or(0);
            ai_take_turn_with_recruits_recorded(state, side, cheapest, &recruit_defs)
        }
        AiKind::Coordinated => {
            let recruit_defs: Vec<(u32, u32)> = faction
                .recruits
                .iter()
                .filter_map(|id| units.get(id).map(|def| (def.cost, def.movement)))
                .collect();
            let cheapest = recruit_defs
                .iter()
                .map(|(cost, _)| *cost)
                .min()
                .unwrap_or(0);
            ai_take_turn_coordinated(state, side, cheapest, &recruit_defs);
            Vec::new()
        }
        AiKind::Random => {
            random_turn(state, side, rng);
            Vec::new()
        }
    }
}

fn record_actions(
    writer: &mut Option<BufWriter<std::fs::File>>,
    step: u32,
    side: u8,
    actions: &[ActionRecord],
) {
    if actions.is_empty() {
        return;
    }
    if let Some(writer) = writer {
        serde_json::to_writer(
            &mut *writer,
            &serde_json::json!({
                "type": "actions",
                "phase": "committed_turn_actions",
                "step": step,
                "side": side,
                "coverage": "lookahead_executor_prefix",
                "actions": actions,
            }),
        )
        .expect("write trajectory actions");
        writeln!(writer).expect("write trajectory action newline");
    }
}

fn record_recruitment(
    writer: &mut Option<BufWriter<std::fs::File>>,
    step: u32,
    side: u8,
    policy: RecruitPolicy,
    summary: RecruitSummary,
) {
    if let Some(writer) = writer {
        serde_json::to_writer(
            &mut *writer,
            &serde_json::json!({
                "type": "recruitment",
                "phase": "committed_recruitment",
                "step": step,
                "side": side,
                "policy": match policy {
                    RecruitPolicy::FirstAffordable => "first-affordable",
                    RecruitPolicy::Balanced => "balanced",
                },
                "recruited": summary.recruited,
                "roles": {
                    "melee": summary.melee,
                    "ranged": summary.ranged,
                    "other": summary.other,
                },
                "balanced_fallbacks": summary.balanced_fallbacks,
            }),
        )
        .expect("write recruitment record");
        writeln!(writer).expect("write recruitment newline");
    }
}

fn record_state(
    writer: &mut Option<BufWriter<std::fs::File>>,
    state: &GameState,
    board: &str,
    phase: &str,
    step: u32,
    recruits: [u32; 2],
    next_id: u32,
) {
    if let Some(writer) = writer {
        let mut save = SaveState::build(state, board, None, None, None, None);
        // Recruitment in this runner owns its own ID allocator.
        save.next_unit_id = next_id;
        serde_json::to_writer(
            &mut *writer,
            &serde_json::json!({
                "type": "snapshot", "phase": phase, "step": step,
                "recruits": recruits, "state": save
            }),
        )
        .expect("write trajectory snapshot");
        writeln!(writer).expect("write trajectory newline");
    }
}

fn run_game(c: &Config, game: u32) -> GameResult {
    let base = root();
    let data = base.join("data");
    let units: Registry<UnitDef> =
        Registry::load_from_dir(&data.join("units")).expect("load units");
    let terrain: Registry<TerrainDef> =
        Registry::load_from_dir(&data.join("terrain")).expect("load terrain");
    let factions = load_factions(&data);
    let f1 = factions
        .iter()
        .find(|f| f.def.id == c.team1)
        .unwrap_or_else(|| panic!("unknown faction {}", c.team1));
    let f2 = factions
        .iter()
        .find(|f| f.def.id == c.team2)
        .unwrap_or_else(|| panic!("unknown faction {}", c.team2));
    let board = load_board(&base.join("scenarios").join(&c.scenario).join("board.toml"))
        .expect("load board");
    let game_index = c.seed.wrapping_add(game as u64 - 1);
    let game_seed = mix_seed(game_index);
    let mut state = GameState::new_seeded(board.board, game_seed);
    // Self-play is symmetric: objectives and timeout victories are scenario
    // attacker/defender rules, not player-vs-player rules. The scenario limit
    // remains disabled and the explicit side-turn cap produces a draw if
    // neither side is eliminated.
    state.objective_hex = None;
    let side_turn_cap = side_turn_cap(c);
    upgrade_tiles(&mut state, &terrain);
    let k1 = keep_for(&state, 0);
    let k2 = keep_for(&state, 1);
    state.place_unit(
        Unit::from_def(1, units.get(&f1.def.leader_def).unwrap(), 0),
        k1,
    );
    state.place_unit(
        Unit::from_def(2, units.get(&f2.def.leader_def).unwrap(), 1),
        k2,
    );
    let default_gold = if c.scenario == "final_battle" || c.scenario.starts_with("big_battle_") {
        300
    } else {
        100
    };
    let first = match c.first {
        FirstPlayer::Team1 => 0,
        FirstPlayer::Team2 => 1,
        FirstPlayer::CoinFlip => (mix_seed(game_index ^ 0xd1b54a32d192ed03) & 1) as u8,
    };
    let mut gold = [
        c.gold1.or(c.gold).unwrap_or(default_gold),
        c.gold2.or(c.gold).unwrap_or(default_gold),
    ];
    gold[1 - first as usize] = gold[1 - first as usize].saturating_add(c.second_gold);
    state.gold = gold;
    let starting_gold = gold;
    let mut recruits = [0, 0];
    state.active_faction = first;
    let mut rng = mix_seed(game_seed ^ 0xa0761d6478bd642f);
    let mut next_id = 3;
    let limit = side_turn_cap;
    let board_path = base.join("scenarios").join(&c.scenario).join("board.toml");
    let board_path = board_path.to_str().expect("UTF-8 board path");
    let mut recording = c.record_dir.as_ref().map(|dir| {
        let file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(dir.join(format!("game-{game:05}.ndjson")))
            .expect("create trajectory");
        let mut writer = BufWriter::new(file);
        let meta = serde_json::json!({"type":"metadata", "schema_version":1,
            "game":game, "input_seed":game_index, "effective_seed":game_seed,
            "scenario":c.scenario, "factions":[c.team1,c.team2],
            "algorithms":[ai_name(c.ai1),ai_name(c.ai2)], "first":first,
            "recruitment_policies":[recruit_policy_name(c.recruit1_policy), recruit_policy_name(c.recruit2_policy)],
            "starting_gold":starting_gold, "side_turn_cap":limit,
            "coverage":"state_boundaries_plus_lookahead_actions", "model_calls":0});
        serde_json::to_writer(&mut writer, &meta).expect("write metadata");
        writeln!(writer).expect("write newline");
        writer
    });
    record_state(
        &mut recording,
        &state,
        board_path,
        "opening",
        0,
        recruits,
        next_id,
    );
    for step in 0..limit {
        let side = state.active_faction;
        if side == 0 {
            let policy = recruit_policy_for_side(c, 0);
            let recruitment = recruit(&mut state, 0, f1, &units, &mut next_id, policy);
            recruits[0] += recruitment.recruited;
            record_recruitment(&mut recording, step, 0, policy, recruitment);
            record_state(
                &mut recording,
                &state,
                board_path,
                "after_recruitment",
                step,
                recruits,
                next_id,
            );
            let actions = play_turn(&mut state, 0, c.ai1, &mut rng, f1, &units);
            record_actions(&mut recording, step, 0, &actions);
        } else {
            let policy = recruit_policy_for_side(c, 1);
            let recruitment = recruit(&mut state, 1, f2, &units, &mut next_id, policy);
            recruits[1] += recruitment.recruited;
            record_recruitment(&mut recording, step, 1, policy, recruitment);
            record_state(
                &mut recording,
                &state,
                board_path,
                "after_recruitment",
                step,
                recruits,
                next_id,
            );
            let actions = play_turn(&mut state, 1, c.ai2, &mut rng, f2, &units);
            record_actions(&mut recording, step, 1, &actions);
        }
        record_state(
            &mut recording,
            &state,
            board_path,
            "after_turn",
            step + 1,
            recruits,
            next_id,
        );
        if let Some(winner) = state.check_winner() {
            if let Some(writer) = &mut recording {
                writeln!(writer, "{}", serde_json::json!({"type":"terminal", "reason":"winner", "winner":winner, "completed_side_turns":step+1, "side_turns_executed":step+1, "side_turn_cap":limit})).expect("write terminal");
                writer.flush().expect("flush trajectory");
            }
            let value = |side: u8| {
                state
                    .units
                    .values()
                    .filter(|u| u.faction == side)
                    .filter_map(|u| units.get(&u.def_id).map(|def| def.cost as i32))
                    .sum::<i32>()
            };
            return GameResult {
                game,
                raw_seed: game_index,
                effective_seed: game_seed,
                winner: Some(winner),
                termination_reason: TerminationReason::Winner,
                completed_side_turns: step + 1,
                engine_turn: state.turn,
                material: value(winner) - value(1 - winner),
                first,
                starting_gold,
                ending_gold: state.gold,
                recruits,
            };
        }
    }
    if let Some(writer) = &mut recording {
        writeln!(writer, "{}", serde_json::json!({"type":"terminal", "reason":"safety_cap", "winner":null, "completed_side_turns":limit, "side_turns_executed":limit, "side_turn_cap":limit})).expect("write terminal");
        writer.flush().expect("flush trajectory");
    }
    GameResult {
        game,
        raw_seed: game_index,
        effective_seed: game_seed,
        winner: None,
        termination_reason: TerminationReason::SideTurnCap,
        completed_side_turns: limit,
        engine_turn: state.turn,
        material: 0,
        first,
        starting_gold,
        ending_gold: state.gold,
        recruits,
    }
}

fn percentile(sorted: &[u32], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let x = (sorted.len() - 1) as f64 * p;
    let lo = x.floor() as usize;
    let hi = x.ceil() as usize;
    sorted[lo] as f64 + (sorted[hi] - sorted[lo]) as f64 * (x - lo as f64)
}

fn print_results(c: &Config, mut results: Vec<GameResult>) {
    results.sort_by_key(|r| r.game);
    let w1 = results.iter().filter(|r| r.winner == Some(0)).count();
    let w2 = results.iter().filter(|r| r.winner == Some(1)).count();
    let draws = results.len() - w1 - w2;
    let first_team1 = results.iter().filter(|r| r.first == 0).count();
    let first_team2 = results.iter().filter(|r| r.first == 1).count();
    let first_wins = results.iter().filter(|r| r.winner == Some(r.first)).count();
    let second_wins = results
        .iter()
        .filter(|r| r.winner.is_some() && r.winner != Some(r.first))
        .count();
    let mut turns: Vec<u32> = results.iter().map(|r| r.completed_side_turns).collect();
    turns.sort_unstable();
    let mats: Vec<i32> = results
        .iter()
        .filter(|r| r.winner.is_some())
        .map(|r| r.material)
        .collect();
    let avg_mat = mats.iter().sum::<i32>() as f64 / mats.len().max(1) as f64;
    let avg = |f: fn(&GameResult) -> u32| {
        results.iter().map(f).sum::<u32>() as f64 / results.len().max(1) as f64
    };
    if c.json {
        for r in results {
            println!(
                "{}",
                serde_json::json!({
                    "type": "self_play_result",
                    "schema_version": 1,
                    "game": r.game,
                    "raw_seed": r.raw_seed,
                    "effective_seed": r.effective_seed,
                    "winner_side": r.winner,
                    "termination_reason": match r.termination_reason {
                        TerminationReason::Winner => "winner",
                        TerminationReason::SideTurnCap => "side_turn_cap",
                    },
                    "completed_side_turns": r.completed_side_turns,
                    "side_turn_cap": side_turn_cap(c),
                    "engine_turn": r.engine_turn,
                    "scenario": c.scenario,
                    "factions": [c.team1, c.team2],
                    "algorithms": [ai_name(c.ai1), ai_name(c.ai2)],
                    "recruitment_policies": [recruit_policy_name(c.recruit1_policy), recruit_policy_name(c.recruit2_policy)],
                    "first_side": r.first,
                    "second_gold": c.second_gold,
                    "starting_gold": r.starting_gold,
                    "ending_gold": r.ending_gold,
                    "recruits": r.recruits,
                    "winner_material_advantage": r.material,
                })
            );
        }
    } else if c.verbose {
        println!("game,raw_seed,effective_seed,first,winner,termination_reason,completed_side_turns,side_turn_cap,engine_turn,winner_material_advantage,start_gold1,start_gold2,end_gold1,end_gold2,recruits1,recruits2");
        for r in results {
            println!(
                "{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}",
                r.game,
                r.raw_seed,
                r.effective_seed,
                if r.first == 0 { "team1" } else { "team2" },
                match r.winner {
                    Some(0) => "team1",
                    Some(1) => "team2",
                    _ => "draw",
                },
                match r.termination_reason {
                    TerminationReason::Winner => "winner",
                    TerminationReason::SideTurnCap => "side_turn_cap",
                },
                r.completed_side_turns,
                side_turn_cap(c),
                r.engine_turn,
                r.material,
                r.starting_gold[0],
                r.starting_gold[1],
                r.ending_gold[0],
                r.ending_gold[1],
                r.recruits[0],
                r.recruits[1]
            );
        }
    } else if c.compact {
        println!(
            "{},{},{},{},{},{},{},{},{},{},{},{},{:.1},{:.1},{:.1},{},{:+.1}",
            c.scenario,
            c.team1,
            c.team2,
            ai_name(c.ai1),
            ai_name(c.ai2),
            match c.first {
                FirstPlayer::Team1 => "team1",
                FirstPlayer::Team2 => "team2",
                FirstPlayer::CoinFlip => "coin-flip",
            },
            c.second_gold,
            results.len(),
            w1,
            w2,
            draws,
            turns[0],
            percentile(&turns, 0.25),
            percentile(&turns, 0.5),
            percentile(&turns, 0.75),
            turns[turns.len() - 1],
            avg_mat
        );
    } else {
        println!("Scenario: {}\nFirst player: {}\nSecond-player gold bonus: {}\nSide-turn cap: {}\nTeam 1: {} ({}, {})\nTeam 2: {} ({}, {})\nGames: {}\n\nFirst-player assignment: team 1 {}, team 2 {}\nFirst-player wins: {} ({:.1}%)\nSecond-player wins: {} ({:.1}%)\n\nTeam 1 wins: {} ({:.1}%)\nTeam 2 wins: {} ({:.1}%)\nDraws: {}\n\nCompleted side turns: min {}, Q1 {:.1}, median {:.1}, Q3 {:.1}, max {}\nWinner material advantage: average {:+.1} gold-worth\nAverage starting gold: team 1 {:.1}, team 2 {:.1}\nAverage ending gold: team 1 {:.1}, team 2 {:.1}\nAverage recruits: team 1 {:.1}, team 2 {:.1}", c.scenario, match c.first { FirstPlayer::Team1 => "team1", FirstPlayer::Team2 => "team2", FirstPlayer::CoinFlip => "coin-flip" }, c.second_gold, side_turn_cap(c), c.team1, ai_name(c.ai1), recruit_policy_name(c.recruit1_policy), c.team2, ai_name(c.ai2), recruit_policy_name(c.recruit2_policy), results.len(), first_team1, first_team2, first_wins, first_wins as f64 * 100.0 / results.len() as f64, second_wins, second_wins as f64 * 100.0 / results.len() as f64, w1, w1 as f64 * 100.0 / results.len() as f64, w2, w2 as f64 * 100.0 / results.len() as f64, draws, turns[0], percentile(&turns, 0.25), percentile(&turns, 0.5), percentile(&turns, 0.75), turns[turns.len()-1], avg_mat, avg(|r| r.starting_gold[0]), avg(|r| r.starting_gold[1]), avg(|r| r.ending_gold[0]), avg(|r| r.ending_gold[1]), avg(|r| r.recruits[0]), avg(|r| r.recruits[1]));
    }
}

fn ai_name(ai: AiKind) -> &'static str {
    match ai {
        AiKind::Greedy => "greedy",
        AiKind::Lookahead => "greedy-look-ahead",
        AiKind::Coordinated => "coordinated",
        AiKind::Random => "random",
    }
}

fn main() {
    let c = Arc::new(parse_args());
    if let Some(dir) = &c.record_dir {
        std::fs::create_dir(dir).expect("record directory must be new with existing parent");
    }
    let next = Arc::new(AtomicU32::new(1));
    let results = Arc::new(Mutex::new(Vec::with_capacity(c.games as usize)));
    let mut workers = Vec::new();
    for _ in 0..c.threads.min(c.games as usize) {
        let c = Arc::clone(&c);
        let next = Arc::clone(&next);
        let results = Arc::clone(&results);
        workers.push(thread::spawn(move || loop {
            let game = next.fetch_add(1, Ordering::Relaxed);
            if game > c.games {
                break;
            }
            results.lock().unwrap().push(run_game(&c, game));
        }));
    }
    for worker in workers {
        worker.join().expect("worker panicked");
    }
    print_results(&c, Arc::try_unwrap(results).unwrap().into_inner().unwrap());
}

#[cfg(test)]
mod tests {
    use super::*;

    fn attack(range: &str) -> AttackDef {
        AttackDef {
            range: range.to_string(),
            ..AttackDef::default()
        }
    }

    fn unit(id: &str, range: &str, cost: u32) -> UnitDef {
        UnitDef {
            id: id.to_string(),
            cost,
            attacks: vec![attack(range)],
            ..UnitDef::default()
        }
    }

    fn test_state() -> GameState {
        let board = load_board(
            &root()
                .join("scenarios")
                .join("big_battle_6")
                .join("board.toml"),
        )
        .expect("test board");
        GameState::new_seeded(board.board, 1)
    }

    fn test_config() -> Config {
        Config {
            scenario: "big_battle_6".into(),
            team1: "undead".into(),
            team2: "undead".into(),
            ai1: AiKind::Greedy,
            ai2: AiKind::Greedy,
            games: 1,
            seed: 1,
            gold: Some(0),
            gold1: None,
            gold2: None,
            max_side_turns: Some(1),
            verbose: false,
            compact: false,
            json: false,
            threads: 1,
            first: FirstPlayer::Team1,
            second_gold: 0,
            record_dir: None,
            recruit1_policy: RecruitPolicy::FirstAffordable,
            recruit2_policy: RecruitPolicy::FirstAffordable,
        }
    }

    #[test]
    fn role_classification_prefers_ranged_and_marks_unknown_as_other() {
        assert_eq!(role_for_attacks(&[attack("melee")]), RecruitRole::Melee);
        assert_eq!(role_for_attacks(&[attack("ranged")]), RecruitRole::Ranged);
        assert_eq!(
            role_for_attacks(&[attack("ranged"), attack("melee")]),
            RecruitRole::Ranged
        );
        assert_eq!(role_for_attacks(&[]), RecruitRole::Other);
    }

    #[test]
    fn balanced_choice_is_deterministic_and_targets_missing_role() {
        let melee = unit("melee", "melee", 10);
        let ranged = unit("ranged", "ranged", 10);
        let affordable = vec![&melee, &ranged];
        let mut state = test_state();

        assert_eq!(
            choose_balanced_recruit(&affordable, &state, 0),
            Some((0, RecruitRole::Melee, false))
        );

        state.place_unit(Unit::from_def(1, &melee, 0), Hex::from_offset(0, 0));
        assert_eq!(
            choose_balanced_recruit(&affordable, &state, 0),
            Some((1, RecruitRole::Ranged, false))
        );
    }

    #[test]
    fn balanced_choice_reports_fallback_when_requested_role_is_unavailable() {
        let ranged = unit("ranged", "ranged", 10);
        let affordable = vec![&ranged];
        let state = test_state();

        assert_eq!(
            choose_balanced_recruit(&affordable, &state, 0),
            Some((0, RecruitRole::Ranged, true))
        );
    }

    #[test]
    fn side_recruitment_policy_changes_selected_side_only() {
        let data = root().join("data");
        let units: Registry<UnitDef> = Registry::load_from_dir(&data.join("units")).unwrap();
        let factions = load_factions(&data);
        let faction = factions.iter().find(|f| f.def.id == "undead").unwrap();
        let mut base = test_state();
        let keep = keep_for(&base, 1);
        assert_eq!(base.board.tile_at(keep).unwrap().terrain_id, "keep");
        assert!(keep.neighbors().iter().any(|h| {
            base.board
                .tile_at(*h)
                .is_some_and(|tile| tile.terrain_id == "castle")
        }));
        base.place_unit(
            Unit::from_def(1, units.get(&faction.def.leader_def).unwrap(), 1),
            keep,
        );
        // An existing melee unit makes balanced recruitment choose the ranged
        // definition, while first-affordable chooses Skeleton.
        base.place_unit(
            Unit::from_def(2, units.get("Skeleton").unwrap(), 1),
            Hex::from_offset(15, 7),
        );
        base.place_unit(
            Unit::from_def(3, units.get("Skeleton").unwrap(), 1),
            Hex::from_offset(16, 7),
        );
        base.gold = [0, 20];
        base.active_faction = 1;

        let mut first = base.clone();
        let mut balanced = base;
        let mut first_id = 100;
        let mut balanced_id = 100;
        let first_summary = recruit(
            &mut first,
            1,
            faction,
            &units,
            &mut first_id,
            RecruitPolicy::FirstAffordable,
        );
        let balanced_summary = recruit(
            &mut balanced,
            1,
            faction,
            &units,
            &mut balanced_id,
            RecruitPolicy::Balanced,
        );
        assert_eq!(first_summary.recruited, 1);
        assert_eq!(balanced_summary.recruited, 1);
        assert_eq!(first.units[&100].def_id, "Skeleton");
        assert_eq!(balanced.units[&100].def_id, "Skeleton Archer");

        let mut config = test_config();
        config.recruit1_policy = RecruitPolicy::Balanced;
        config.recruit2_policy = RecruitPolicy::FirstAffordable;
        assert_eq!(recruit_policy_for_side(&config, 0), RecruitPolicy::Balanced);
        assert_eq!(
            recruit_policy_for_side(&config, 1),
            RecruitPolicy::FirstAffordable
        );
    }

    #[test]
    fn side_turn_cap_is_exact_and_terminal_result_is_accounted() {
        for (first, cap) in [
            (FirstPlayer::Team1, 1),
            (FirstPlayer::Team2, 2),
            (FirstPlayer::Team1, 3),
            (FirstPlayer::Team2, 100),
        ] {
            let mut config = test_config();
            config.first = first;
            config.max_side_turns = Some(cap);
            let result = run_game(&config, 1);
            assert_eq!(result.completed_side_turns, cap);
            assert_eq!(result.winner, None);
            assert_eq!(result.termination_reason, TerminationReason::SideTurnCap);
        }
    }
}
