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
    ai_take_turn_coordinated_with_memory, ai_take_turn_coordinated_with_memory_selected,
    ai_take_turn_greedy, ai_take_turn_greedy_lookahead_with_unit_defs_recorded, ActionRecord,
    PlannerMemory,
};
use norrust_core::board::Tile;
use norrust_core::game_state::{apply_action, Action, GameState};
use norrust_core::hex::Hex;
use norrust_core::loader::Registry;
use norrust_core::pathfinding::{get_zoc_hexes, reachable_hexes};
use norrust_core::recruitment::{
    execute_recruitment, RecruitmentPolicy as RecruitPolicy, RecruitmentSummary,
};
use norrust_core::scenario::load_board;
use norrust_core::schema::{FactionDef, RecruitGroup, TerrainDef, UnitDef};
use norrust_core::selector::{
    DecisionTelemetry, SelectorRequest, SelectorResponse, SELECTOR_SCHEMA_VERSION,
};
use norrust_core::selector_backend::{
    invoke_command, read_response_file, selector_request_sha256, BackendError, SelectorBudget,
    SelectorCommandRequest, SelectorLimits,
};
use norrust_core::unit::Unit;

#[derive(Clone, Copy)]
enum AiKind {
    Greedy,
    Lookahead,
    Coordinated,
    Random,
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
    selector_candidate: Option<String>,
    selector_failure: bool,
    selector_response_file: Option<PathBuf>,
    selector_command: Option<PathBuf>,
    selector_args: Vec<String>,
    selector_side: Option<u8>,
    selector_usage_sidecar: Option<PathBuf>,
    selector_evidence_dir: Option<PathBuf>,
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
  --selector-candidate ID  Test selector: choose a current plan ID on close decisions
  --selector-fail       Test selector: force fallback on close decisions
  --selector-response-file PATH  Local selector v1 JSON reply, used on close decisions
  --selector-command PROGRAM  Run one request-dependent local selector command
  --selector-arg ARG      Append one argument to --selector-command (repeatable)
  --selector-side SIDE    Controlled side: 1 or 2; must use coordinated AI
  --selector-usage-sidecar PATH  Export environment path for provider usage records
  --selector-evidence-dir PATH  Export environment path for provider evidence
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
        selector_candidate: None,
        selector_failure: false,
        selector_response_file: None,
        selector_command: None,
        selector_args: Vec::new(),
        selector_side: None,
        selector_usage_sidecar: None,
        selector_evidence_dir: None,
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
        if key == "--selector-fail" {
            c.selector_failure = true;
            i += 1;
            continue;
        }
        if key == "--selector-arg" {
            if i + 1 >= args.len() {
                usage();
            }
            c.selector_args.push(args[i + 1].clone());
            i += 2;
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
            "--selector-candidate" => c.selector_candidate = Some(value.clone()),
            "--selector-response-file" => c.selector_response_file = Some(PathBuf::from(value)),
            "--selector-command" => c.selector_command = Some(PathBuf::from(value)),
            "--selector-side" => {
                c.selector_side = Some(match value.as_str() {
                    "1" => 0,
                    "2" => 1,
                    _ => usage(),
                })
            }
            "--selector-usage-sidecar" => c.selector_usage_sidecar = Some(PathBuf::from(value)),
            "--selector-evidence-dir" => c.selector_evidence_dir = Some(PathBuf::from(value)),
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
    let selector_modes = c.selector_failure as u8
        + c.selector_candidate.is_some() as u8
        + c.selector_response_file.is_some() as u8
        + c.selector_command.is_some() as u8;
    if selector_modes > 1 {
        eprintln!("fake, response-file, and command selector backends are mutually exclusive");
        usage();
    }
    if (!c.selector_args.is_empty() && c.selector_command.is_none())
        || ((c.selector_usage_sidecar.is_some() || c.selector_evidence_dir.is_some())
            && c.selector_command.is_none())
    {
        eprintln!("--selector-arg, usage-sidecar, and evidence-dir require --selector-command");
        usage();
    }
    if configured_selector(&c) {
        let Some(side) = c.selector_side else {
            eprintln!("a selector backend requires --selector-side 1|2");
            usage();
        };
        let kind = if side == 0 { c.ai1 } else { c.ai2 };
        if !matches!(kind, AiKind::Coordinated) {
            eprintln!(
                "selector controlled side must use --ai{} coordinated",
                side + 1
            );
            usage();
        }
    } else if c.selector_side.is_some() {
        eprintln!("--selector-side requires a configured selector backend");
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

fn recruit_definitions(faction: &Faction, units: &Registry<UnitDef>) -> Vec<UnitDef> {
    faction
        .recruits
        .iter()
        .filter_map(|id| units.get(id).cloned())
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
    game_id: &str,
    kind: AiKind,
    rng: &mut u64,
    recruit_defs: &[UnitDef],
    policy: RecruitPolicy,
    planner_memory: &mut PlannerMemory,
    selector_enabled: bool,
    selector_config: &Config,
    selector_budget: &mut SelectorBudget,
) -> (
    Vec<ActionRecord>,
    Option<(SelectorRequest, DecisionTelemetry)>,
) {
    match kind {
        AiKind::Greedy => {
            ai_take_turn_greedy(state, side);
            (Vec::new(), None)
        }
        AiKind::Lookahead => (
            ai_take_turn_greedy_lookahead_with_unit_defs_recorded(
                state,
                side,
                recruit_defs,
                policy,
            ),
            None,
        ),
        AiKind::Coordinated => {
            if selector_enabled {
                let selector_budget = std::cell::RefCell::new(selector_budget);
                let selector = |request: &SelectorRequest| {
                    if let Some(program) = selector_config.selector_command.as_deref() {
                        let decision_id = format!(
                            "{game_id}-turn-{}-side-{}-revision-{}",
                            request.turn, request.side, request.state_revision
                        );
                        let envelope = SelectorCommandRequest::new(
                            game_id.to_string(),
                            decision_id,
                            request.clone(),
                        );
                        selector_budget
                            .borrow_mut()
                            .invoke(request, |_| {
                                invoke_command(
                                    program,
                                    &selector_config.selector_args,
                                    &envelope,
                                    SelectorLimits::default().timeout,
                                    SelectorLimits::default().max_response_bytes,
                                    selector_config.selector_usage_sidecar.as_deref(),
                                    selector_config.selector_evidence_dir.as_deref(),
                                )
                                .and_then(|response| {
                                    serde_json::to_vec(&response).map_err(|error| {
                                        format!("serialize selector response: {error}")
                                    })
                                })
                            })
                            .map_err(backend_error_text)
                    } else if let Some(path) = selector_config.selector_response_file.as_deref() {
                        selector_budget
                            .borrow_mut()
                            .invoke(request, |_| {
                                read_response_file(
                                    path,
                                    SelectorLimits::default().max_response_bytes,
                                )
                            })
                            .map_err(backend_error_text)
                    } else {
                        selector_budget
                            .borrow_mut()
                            .invoke(request, |_| {
                                fake_selector_response(selector_config, request).map(|response| {
                                    serde_json::to_vec(&response)
                                        .expect("serialize fake v1 response")
                                })
                            })
                            .map_err(backend_error_text)
                    }
                };
                let (actions, request, telemetry) = ai_take_turn_coordinated_with_memory_selected(
                    state,
                    side,
                    recruit_defs,
                    policy,
                    planner_memory,
                    Some(&selector),
                );
                (actions, Some((request, telemetry)))
            } else {
                (
                    ai_take_turn_coordinated_with_memory(
                        state,
                        side,
                        recruit_defs,
                        policy,
                        planner_memory,
                    ),
                    None,
                )
            }
        }
        AiKind::Random => {
            random_turn(state, side, rng);
            (Vec::new(), None)
        }
    }
}

fn backend_error_text(error: BackendError) -> String {
    match error {
        BackendError::BudgetExhausted => "budget_exhausted".into(),
        BackendError::CircuitOpen => "circuit_open".into(),
        BackendError::Provider(message) => format!("provider_error:{message}"),
        BackendError::Timeout => "timeout".into(),
        BackendError::Oversized => "oversized_response".into(),
        BackendError::Malformed => "malformed_response".into(),
        BackendError::InvalidResponse(message) => format!("invalid_response:{message}"),
    }
}

fn record_decision(
    writer: &mut Option<BufWriter<std::fs::File>>,
    step: u32,
    side: u8,
    game_id: &str,
    request: &SelectorRequest,
    telemetry: &DecisionTelemetry,
    backend: &str,
) {
    if let Some(writer) = writer {
        serde_json::to_writer(
            &mut *writer,
            &serde_json::json!({
                "type": "coordinated_decision", "step": step, "side": side,
                "game_id": game_id,
                "decision_id": format!("{game_id}-turn-{}-side-{}-revision-{}", request.turn, side, request.state_revision),
                "request_id": format!("{game_id}-turn-{}-side-{}-revision-{}", request.turn, side, request.state_revision),
                "request_sha256": selector_request_sha256(request),
                "backend": if telemetry.selector_invoked { backend } else { "none" },
                "request": request,
                "response": if telemetry.response_status == "accepted" {
                    serde_json::json!({"schema_version": 1, "candidate_id": telemetry.selected_candidate_id})
                } else { serde_json::Value::Null },
                "response_status": telemetry.response_status,
                "fallback_reason": telemetry.fallback_reason,
                "usage": {"input_tokens": null, "output_tokens": null, "cost_microusd": null},
                "telemetry": telemetry,
            }),
        )
        .expect("write selector telemetry");
        writeln!(writer).expect("write selector telemetry newline");
    }
}

fn fake_selector_response(
    config: &Config,
    _request: &SelectorRequest,
) -> Result<SelectorResponse, String> {
    if config.selector_failure {
        return Err("fake_selector_failure".into());
    }
    let candidate_id = config.selector_candidate.as_deref().unwrap_or("objective");
    Ok(SelectorResponse {
        schema_version: SELECTOR_SCHEMA_VERSION,
        candidate_id: candidate_id.to_string(),
        reason_code: None,
    })
}

fn configured_selector(config: &Config) -> bool {
    config.selector_candidate.is_some()
        || config.selector_failure
        || config.selector_response_file.is_some()
        || config.selector_command.is_some()
}

fn configured_selector_for_side(config: &Config, side: u8) -> bool {
    configured_selector(config) && config.selector_side == Some(side)
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
    summary: &RecruitmentSummary,
) {
    if let Some(writer) = writer {
        serde_json::to_writer(
            &mut *writer,
            &serde_json::json!({
                "type": "recruitment",
                "phase": "committed_recruitment",
                "step": step,
                "side": side,
                "policy": recruit_policy_name(policy),
                "recruited": summary.recruited,
                "spent": summary.spent,
                "purchases": summary.purchases,
                "composition_before": summary.composition_before,
                "composition_after": summary.composition_after,
                "fallback_reason": summary.fallback_reason,
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
    let f1_recruit_defs = recruit_definitions(f1, &units);
    let f2_recruit_defs = recruit_definitions(f2, &units);
    let board = load_board(&base.join("scenarios").join(&c.scenario).join("board.toml"))
        .expect("load board");
    let game_index = c.seed.wrapping_add(game as u64 - 1);
    let game_seed = mix_seed(game_index);
    let game_id = format!("input-seed-{game_index}-effective-{game_seed}");
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
    let mut planner_memory = [PlannerMemory::default(), PlannerMemory::default()];
    let mut selector_budget = SelectorBudget::new(SelectorLimits::default());
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
            "game_id":game_id,
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
            let recruitment =
                execute_recruitment(&mut state, 0, &f1_recruit_defs, &mut next_id, policy);
            state.next_unit_id = next_id;
            recruits[0] += recruitment.recruited;
            record_recruitment(&mut recording, step, 0, policy, &recruitment);
            record_state(
                &mut recording,
                &state,
                board_path,
                "after_recruitment",
                step,
                recruits,
                next_id,
            );
            let (actions, telemetry) = play_turn(
                &mut state,
                0,
                &game_id,
                c.ai1,
                &mut rng,
                &f1_recruit_defs,
                policy,
                &mut planner_memory[0],
                configured_selector_for_side(c, 0),
                c,
                &mut selector_budget,
            );
            record_actions(&mut recording, step, 0, &actions);
            if let Some((request, telemetry)) = telemetry {
                record_decision(
                    &mut recording,
                    step,
                    0,
                    &game_id,
                    &request,
                    &telemetry,
                    if c.selector_response_file.is_some() {
                        "local-response-file"
                    } else if c.selector_command.is_some() {
                        "command"
                    } else {
                        "test-fake"
                    },
                );
            }
        } else {
            let policy = recruit_policy_for_side(c, 1);
            let recruitment =
                execute_recruitment(&mut state, 1, &f2_recruit_defs, &mut next_id, policy);
            state.next_unit_id = next_id;
            recruits[1] += recruitment.recruited;
            record_recruitment(&mut recording, step, 1, policy, &recruitment);
            record_state(
                &mut recording,
                &state,
                board_path,
                "after_recruitment",
                step,
                recruits,
                next_id,
            );
            let (actions, telemetry) = play_turn(
                &mut state,
                1,
                &game_id,
                c.ai2,
                &mut rng,
                &f2_recruit_defs,
                policy,
                &mut planner_memory[1],
                configured_selector_for_side(c, 1),
                c,
                &mut selector_budget,
            );
            record_actions(&mut recording, step, 1, &actions);
            if let Some((request, telemetry)) = telemetry {
                record_decision(
                    &mut recording,
                    step,
                    1,
                    &game_id,
                    &request,
                    &telemetry,
                    if c.selector_response_file.is_some() {
                        "local-response-file"
                    } else if c.selector_command.is_some() {
                        "command"
                    } else {
                        "test-fake"
                    },
                );
            }
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
            selector_candidate: None,
            selector_failure: false,
            selector_response_file: None,
            selector_command: None,
            selector_args: Vec::new(),
            selector_side: None,
            selector_usage_sidecar: None,
            selector_evidence_dir: None,
            recruit1_policy: RecruitPolicy::FirstAffordable,
            recruit2_policy: RecruitPolicy::FirstAffordable,
        }
    }

    #[test]
    fn side_recruitment_policy_changes_selected_side_only() {
        let data = root().join("data");
        let units: Registry<UnitDef> = Registry::load_from_dir(&data.join("units")).unwrap();
        let factions = load_factions(&data);
        let faction = factions.iter().find(|f| f.def.id == "undead").unwrap();
        let definitions = vec![
            units.get("Skeleton").unwrap().clone(),
            units.get("Skeleton Archer").unwrap().clone(),
        ];
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
        let first_summary = execute_recruitment(
            &mut first,
            1,
            &definitions,
            &mut first_id,
            RecruitPolicy::FirstAffordable,
        );
        let balanced_summary = execute_recruitment(
            &mut balanced,
            1,
            &definitions,
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

    #[test]
    fn coordinated_play_turn_retains_memory_between_side_turns() {
        let data = root().join("data");
        let units: Registry<UnitDef> = Registry::load_from_dir(&data.join("units")).unwrap();
        let factions = load_factions(&data);
        let undead = factions.iter().find(|f| f.def.id == "undead").unwrap();
        let mut state = test_state();
        let own_keep = keep_for(&state, 0);
        let enemy_keep = keep_for(&state, 1);
        state.place_unit(
            Unit::from_def(1, units.get(&undead.def.leader_def).unwrap(), 0),
            own_keep,
        );
        state.place_unit(
            Unit::from_def(2, units.get(&undead.def.leader_def).unwrap(), 1),
            enemy_keep,
        );
        state.active_faction = 0;
        let mut memory = PlannerMemory {
            objective: Some(norrust_core::ai::CoordinatedObjective::Concentrate),
            target: Some(enemy_keep),
            age: 0,
            no_progress: 0,
            progress_marker: None,
        };
        let mut rng = 17;
        let definitions: Vec<UnitDef> = Vec::new();

        let _ = play_turn(
            &mut state,
            0,
            "test-game",
            AiKind::Coordinated,
            &mut rng,
            &definitions,
            RecruitPolicy::FirstAffordable,
            &mut memory,
            false,
            &test_config(),
            &mut SelectorBudget::new(SelectorLimits::default()),
        );
        let first_age = memory.age;
        let first_objective = memory.objective;
        state.active_faction = 0;
        let _ = play_turn(
            &mut state,
            0,
            "test-game",
            AiKind::Coordinated,
            &mut rng,
            &definitions,
            RecruitPolicy::FirstAffordable,
            &mut memory,
            false,
            &test_config(),
            &mut SelectorBudget::new(SelectorLimits::default()),
        );

        assert!(first_age > 0);
        assert!(memory.age > first_age);
        assert_eq!(memory.objective, first_objective);
    }

    #[test]
    fn command_selector_choice_controls_the_live_coordinated_turn() {
        let data = root().join("data");
        let units: Registry<UnitDef> = Registry::load_from_dir(&data.join("units")).unwrap();
        let factions = load_factions(&data);
        let undead = factions.iter().find(|f| f.def.id == "undead").unwrap();
        let mut initial = test_state();
        initial.active_faction = 0;
        initial.gold = [0, 0];
        initial.place_unit(
            Unit::from_def(1, units.get(&undead.def.leader_def).unwrap(), 0),
            keep_for(&initial, 0),
        );
        initial.place_unit(
            Unit::from_def(2, units.get(&undead.def.leader_def).unwrap(), 1),
            keep_for(&initial, 1),
        );
        initial.place_unit(
            Unit::from_def(3, units.get("Skeleton").unwrap(), 0),
            Hex::from_offset(2, 0),
        );

        let responder = r#"import json, os, sys
request = json.load(sys.stdin)
assert os.environ["NORRUST_GAME_ID"] == request["game_id"]
assert os.environ["NORRUST_REQUEST_ID"] == request["decision_id"]
assert os.environ["NORRUST_USAGE_SIDECAR"] == "/tmp/selector-usage.ndjson"
assert os.environ["NORRUST_EVIDENCE_DIR"] == "/tmp/selector-evidence"
response = {"schema_version": 1, "candidate_id": "lookahead"}
print(json.dumps({"schema_version": 1, "game_id": request["game_id"],
    "decision_id": request["decision_id"], "request_sha256": request["request_sha256"],
    "response": response}))
"#;
        let mut config = test_config();
        config.selector_command = Some(PathBuf::from("python3"));
        config.selector_args = vec!["-c".into(), responder.into()];
        config.selector_side = Some(0);
        config.selector_usage_sidecar = Some(PathBuf::from("/tmp/selector-usage.ndjson"));
        config.selector_evidence_dir = Some(PathBuf::from("/tmp/selector-evidence"));
        let mut live = initial.clone();
        let mut live_memory = PlannerMemory::default();
        let mut rng = 17;
        let (actions, decision) = play_turn(
            &mut live,
            0,
            "fixture-game",
            AiKind::Coordinated,
            &mut rng,
            &[],
            RecruitPolicy::FirstAffordable,
            &mut live_memory,
            true,
            &config,
            &mut SelectorBudget::new(SelectorLimits::default()),
        );
        let (request, telemetry) = decision.expect("selector decision");
        assert!(request.validate().is_ok());
        assert!(telemetry.selector_invoked, "{telemetry:?}");
        assert_eq!(telemetry.response_status, "accepted");
        assert_eq!(telemetry.selected_candidate_id, "lookahead");

        let mut expected = initial.clone();
        let mut expected_memory = PlannerMemory::default();
        let choose_objective = |_request: &SelectorRequest| {
            Ok(SelectorResponse {
                schema_version: SELECTOR_SCHEMA_VERSION,
                candidate_id: "lookahead".into(),
                reason_code: None,
            })
        };
        let (expected_actions, _, _) = ai_take_turn_coordinated_with_memory_selected(
            &mut expected,
            0,
            &[],
            RecruitPolicy::FirstAffordable,
            &mut expected_memory,
            Some(&choose_objective),
        );
        assert_eq!(format!("{actions:?}"), format!("{expected_actions:?}"));
        assert_eq!(format!("{live:?}"), format!("{expected:?}"));

        let mut baseline = initial;
        let mut baseline_memory = PlannerMemory::default();
        let _ = ai_take_turn_coordinated_with_memory(
            &mut baseline,
            0,
            &[],
            RecruitPolicy::FirstAffordable,
            &mut baseline_memory,
        );
        assert_ne!(
            format!("{live:?}"),
            format!("{baseline:?}"),
            "fixture must show that the accepted non-baseline choice changes live state"
        );
    }
}
