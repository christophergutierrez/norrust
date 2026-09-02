//! Standalone headless self-play runner.
//!
//! Example:
//! cargo run --release --bin self-play -- --scenario big_battle_6 \
//!   --team1 northerners --team2 undead --ai1 greedy-look-ahead --ai2 greedy \
//!   --games 100

use std::collections::HashSet;
use std::env;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;

use norrust_core::ai::{ai_take_turn_greedy, ai_take_turn_greedy_lookahead};
use norrust_core::board::Tile;
use norrust_core::game_state::{apply_action, apply_recruit, Action, GameState};
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::pathfinding::{get_zoc_hexes, reachable_hexes};
use norrust_core::scenario::load_board;
use norrust_core::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use norrust_core::unit::Unit;

#[derive(Clone, Copy)]
enum AiKind {
    Greedy,
    Lookahead,
    Random,
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
    max_turns: Option<u32>,
    verbose: bool,
    compact: bool,
    threads: usize,
    first: FirstPlayer,
    second_gold: u32,
}

#[derive(Clone)]
struct Faction {
    def: FactionDef,
    recruits: Vec<String>,
}

#[derive(Clone, Copy, Debug)]
struct GameResult {
    game: u32,
    seed: u64,
    winner: Option<u8>,
    turns: u32,
    material: i32,
    first: u8,
    starting_gold: [u32; 2],
    ending_gold: [u32; 2],
    recruits: [u32; 2],
}

fn usage() -> ! {
    eprintln!(
        "Usage: self-play --team1 ID --team2 ID [options]

Options:
  --scenario NAME       Scenario directory name (default: big_battle_6)
  --team1 ID            Faction on side 1
  --team2 ID            Faction on side 2
  --ai1 KIND             greedy | greedy-look-ahead | random (default: greedy)
  --ai2 KIND             greedy | greedy-look-ahead | random (default: greedy)
  --games N             Number of games (default: 100)
  --seed N              First deterministic seed (default: 1)
  --gold N              Starting gold for both teams
  --gold1 N             Starting gold for team 1
  --gold2 N             Starting gold for team 2
  --max-turns N         Override the scenario turn limit
  --threads N           Worker threads (default: available CPUs)
  --first SIDE           team1 | team2 | coin-flip (default: team1)
  --second-gold N        Extra starting gold for the second player (default: 5)
  --verbose             CSV header plus one line per game
  --compact             One comma-separated summary line
  -h, --help            Show this help"
    );
    std::process::exit(2)
}

fn parse_ai(s: &str) -> AiKind {
    match s {
        "greedy" => AiKind::Greedy,
        "greedy-look-ahead" => AiKind::Lookahead,
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
        max_turns: None,
        verbose: false,
        compact: false,
        threads: thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1),
        first: FirstPlayer::Team1,
        second_gold: 5,
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
        if key == "-h" || key == "--help" {
            usage();
        }
        if i + 1 >= args.len() {
            usage();
        }
        let value = &args[i + 1];
        match key.as_str() {
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
            "--max-turns" => c.max_turns = Some(value.parse().unwrap_or_else(|_| usage())),
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
    if c.verbose && c.compact {
        eprintln!("--verbose and --compact cannot be combined");
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
) -> u32 {
    let mut recruited = 0;
    loop {
        let keep = state.positions.iter().find_map(|(&id, &h)| {
            let u = state.units.get(&id)?;
            (u.faction == side
                && u.abilities.iter().any(|a| a == "leader")
                && state
                    .board
                    .tile_at(h)
                    .map(|t| t.terrain_id == "keep")
                    .unwrap_or(false))
            .then_some(h)
        });
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
                    .map(|u| {
                        u.faction == side && !u.moved && !u.abilities.iter().any(|a| a == "leader")
                    })
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
        let Some(def) = faction
            .recruits
            .iter()
            .filter_map(|id| units.get(id))
            .find(|d| state.gold[side as usize] >= d.cost)
        else {
            break;
        };
        let cost = def.cost;
        if apply_recruit(state, Unit::from_def(*next_id, def, side), dest, cost).is_err() {
            break;
        }
        *next_id += 1;
        recruited += 1;
    }
    recruited
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
) {
    match kind {
        AiKind::Greedy => ai_take_turn_greedy(state, side),
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
            ai_take_turn_greedy_lookahead(state, side, cheapest, &recruit_defs);
        }
        AiKind::Random => random_turn(state, side, rng),
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
    // remains a safety cap and produces a draw if neither side is eliminated.
    state.objective_hex = None;
    let safety_turns = c.max_turns.or(board.max_turns).unwrap_or(200);
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
    let limit = safety_turns.saturating_mul(2).saturating_add(2);
    for _ in 0..limit {
        let side = state.active_faction;
        if side == 0 {
            recruits[0] += recruit(&mut state, 0, f1, &units, &mut next_id);
            play_turn(&mut state, 0, c.ai1, &mut rng, f1, &units);
        } else {
            recruits[1] += recruit(&mut state, 1, f2, &units, &mut next_id);
            play_turn(&mut state, 1, c.ai2, &mut rng, f2, &units);
        }
        if let Some(winner) = state.check_winner() {
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
                seed: game_seed,
                winner: Some(winner),
                turns: state.turn,
                material: value(winner) - value(1 - winner),
                first,
                starting_gold,
                ending_gold: state.gold,
                recruits,
            };
        }
    }
    GameResult {
        game,
        seed: game_seed,
        winner: None,
        turns: state.turn,
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
    let mut turns: Vec<u32> = results.iter().map(|r| r.turns).collect();
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
    if c.verbose {
        println!("game,seed,first,winner,turns,winner_material_advantage,start_gold1,start_gold2,end_gold1,end_gold2,recruits1,recruits2");
        for r in results {
            println!(
                "{},{},{},{},{},{},{},{},{},{},{},{}",
                r.game,
                r.seed,
                if r.first == 0 { "team1" } else { "team2" },
                match r.winner {
                    Some(0) => "team1",
                    Some(1) => "team2",
                    _ => "draw",
                },
                r.turns,
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
        println!("Scenario: {}\nFirst player: {}\nSecond-player gold bonus: {}\nTeam 1: {} ({})\nTeam 2: {} ({})\nGames: {}\n\nFirst-player assignment: team 1 {}, team 2 {}\nFirst-player wins: {} ({:.1}%)\nSecond-player wins: {} ({:.1}%)\n\nTeam 1 wins: {} ({:.1}%)\nTeam 2 wins: {} ({:.1}%)\nDraws: {}\n\nTurns: min {}, Q1 {:.1}, median {:.1}, Q3 {:.1}, max {}\nWinner material advantage: average {:+.1} gold-worth\nAverage starting gold: team 1 {:.1}, team 2 {:.1}\nAverage ending gold: team 1 {:.1}, team 2 {:.1}\nAverage recruits: team 1 {:.1}, team 2 {:.1}", c.scenario, match c.first { FirstPlayer::Team1 => "team1", FirstPlayer::Team2 => "team2", FirstPlayer::CoinFlip => "coin-flip" }, c.second_gold, c.team1, ai_name(c.ai1), c.team2, ai_name(c.ai2), results.len(), first_team1, first_team2, first_wins, first_wins as f64 * 100.0 / results.len() as f64, second_wins, second_wins as f64 * 100.0 / results.len() as f64, w1, w1 as f64 * 100.0 / results.len() as f64, w2, w2 as f64 * 100.0 / results.len() as f64, draws, turns[0], percentile(&turns, 0.25), percentile(&turns, 0.5), percentile(&turns, 0.75), turns[turns.len()-1], avg_mat, avg(|r| r.starting_gold[0]), avg(|r| r.starting_gold[1]), avg(|r| r.ending_gold[0]), avg(|r| r.ending_gold[1]), avg(|r| r.recruits[0]), avg(|r| r.recruits[1]));
    }
}

fn ai_name(ai: AiKind) -> &'static str {
    match ai {
        AiKind::Greedy => "greedy",
        AiKind::Lookahead => "greedy-look-ahead",
        AiKind::Random => "random",
    }
}

fn main() {
    let c = Arc::new(parse_args());
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
