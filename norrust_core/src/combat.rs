//! Combat resolution with deterministic RNG, time-of-day modifiers, and Monte Carlo simulation.

use crate::game_state::GameState;
use crate::hex::Hex;
use crate::schema::AttackDef;
use crate::unit::{has_special, Alignment, Unit};

/// Exact cumulative damage result for one target receiving one or more
/// independent attack volleys. This is read-only and never consumes RNG.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct DamageSequenceForecast {
    /// Probability that cumulative damage reaches the target's starting HP.
    pub kill_bps: u32,
    /// Expected cumulative damage in tenths of HP.
    pub expected_damage_tenths: u32,
}

/// Fully resolved parameters for one immediate combat exchange.
///
/// This is a pure, engine-owned description shared by previews, tactical
/// analysis, and AI policy code. Damage values include all live combat
/// modifiers; hit percentages include the opposing terrain defense.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct CombatParameters {
    pub attacker_attack_id: String,
    pub defender_attack_id: Option<String>,
    pub attacker_hit_pct: u32,
    pub defender_hit_pct: u32,
    pub attacker_damage_per_hit: u32,
    pub attacker_strikes: u32,
    pub defender_damage_per_hit: u32,
    pub defender_strikes: u32,
    pub attacker_hp: u32,
    pub defender_hp: u32,
    pub attacker_terrain_defense: u32,
    pub defender_terrain_defense: u32,
}

/// Exact outcome summary for the current immediate exchange order.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ExchangeForecast {
    /// [defender killed, both survive, attacker killed], in basis points.
    pub outcome_bps: [u32; 3],
    /// Expected damage [to defender, to attacker], in tenths of HP.
    pub expected_damage_tenths: [u32; 2],
}

fn binomial_probability(strikes: u32, hits: u32, hit_pct: u32) -> f64 {
    if hits > strikes {
        return 0.0;
    }
    let p = hit_pct.min(100) as f64 / 100.0;
    let q = 1.0 - p;
    let mut coefficient = 1.0;
    for i in 1..=hits {
        coefficient *= (strikes - hits + i) as f64 / i as f64;
    }
    coefficient * p.powi(hits as i32) * q.powi((strikes - hits) as i32)
}

fn round_bps(probabilities: [f64; 3]) -> [u32; 3] {
    let scaled = probabilities.map(|p| (p.max(0.0) * 10_000.0).min(10_000.0));
    let mut result = scaled.map(|p| p.floor() as u32);
    let mut remainder = 10_000u32.saturating_sub(result.iter().sum());
    let mut order = [0usize, 1, 2];
    order.sort_by(|&a, &b| {
        scaled[b]
            .fract()
            .partial_cmp(&scaled[a].fract())
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| a.cmp(&b))
    });
    for index in order {
        if remainder == 0 {
            break;
        }
        result[index] += 1;
        remainder -= 1;
    }
    result
}

/// Calculate exact immediate-exchange probabilities without RNG or state mutation.
pub fn exact_exchange(parameters: &CombatParameters) -> ExchangeForecast {
    let mut outcomes = [0.0f64; 3];
    let mut expected_attacker_damage = 0.0f64;
    let mut expected_defender_damage = 0.0f64;
    for attacker_hits in 0..=parameters.attacker_strikes {
        let attacker_probability = binomial_probability(
            parameters.attacker_strikes,
            attacker_hits,
            parameters.attacker_hit_pct,
        );
        let attacker_damage = attacker_hits * parameters.attacker_damage_per_hit;
        expected_defender_damage += attacker_probability * attacker_damage as f64;
        if attacker_damage >= parameters.defender_hp {
            outcomes[0] += attacker_probability;
            continue;
        }
        if parameters.defender_strikes == 0 || parameters.defender_hit_pct == 0 {
            outcomes[1] += attacker_probability;
            continue;
        }
        for defender_hits in 0..=parameters.defender_strikes {
            let defender_probability = binomial_probability(
                parameters.defender_strikes,
                defender_hits,
                parameters.defender_hit_pct,
            );
            let probability = attacker_probability * defender_probability;
            let defender_damage = defender_hits * parameters.defender_damage_per_hit;
            expected_attacker_damage += probability * defender_damage as f64;
            if defender_damage >= parameters.attacker_hp {
                outcomes[2] += probability;
            } else {
                outcomes[1] += probability;
            }
        }
    }
    ExchangeForecast {
        outcome_bps: round_bps(outcomes),
        expected_damage_tenths: [
            (expected_defender_damage * 10.0).round() as u32,
            (expected_attacker_damage * 10.0).round() as u32,
        ],
    }
}

/// Calculate the exact probability of killing a target with several volleys.
///
/// Each volley uses the same damage distribution as the attacker's side of
/// `exact_exchange`. Retaliation is intentionally irrelevant here: this is a
/// target-focused bound, and each selected attacker is assumed to reach its
/// declared attack. Callers are responsible for selecting legal, compatible
/// attacker origins.
pub fn exact_damage_sequence(
    defender_hp: u32,
    attacks: &[CombatParameters],
) -> DamageSequenceForecast {
    if defender_hp == 0 {
        return DamageSequenceForecast {
            kill_bps: 10_000,
            expected_damage_tenths: 0,
        };
    }
    if attacks.is_empty() {
        return DamageSequenceForecast {
            kill_bps: 0,
            expected_damage_tenths: 0,
        };
    }
    let mut distribution = vec![(0u32, 1.0f64)];
    let mut expected_damage = 0.0f64;
    for parameters in attacks {
        let mut volley = Vec::with_capacity(parameters.attacker_strikes as usize + 1);
        for hits in 0..=parameters.attacker_strikes {
            volley.push((
                hits.saturating_mul(parameters.attacker_damage_per_hit),
                binomial_probability(
                    parameters.attacker_strikes,
                    hits,
                    parameters.attacker_hit_pct,
                ),
            ));
        }
        expected_damage += parameters.attacker_strikes as f64
            * (parameters.attacker_hit_pct.min(100) as f64 / 100.0)
            * parameters.attacker_damage_per_hit as f64;
        let mut next = Vec::new();
        for (prior_damage, prior_probability) in &distribution {
            for (damage, probability) in &volley {
                next.push((
                    prior_damage.saturating_add(*damage),
                    prior_probability * probability,
                ));
            }
        }
        distribution = next;
    }
    let kill_probability = distribution
        .iter()
        .filter(|(damage, _)| *damage >= defender_hp)
        .map(|(_, probability)| *probability)
        .sum::<f64>();
    DamageSequenceForecast {
        kill_bps: round_bps([kill_probability, 1.0 - kill_probability, 0.0])[0],
        expected_damage_tenths: (expected_damage * 10.0).round() as u32,
    }
}

/// Time of day phase — drives alignment-based damage modifiers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TimeOfDay {
    Day,     // Lawful bonus, Chaotic penalty
    Night,   // Chaotic bonus, Lawful penalty
    Neutral, // No modifier for any alignment
}

/// Map a turn number to a time-of-day phase.
///
/// 6-phase repeating cycle (1-indexed turns):
///   phase 0 = Dawn (Neutral)
///   phase 1 = Midmorning (Day)
///   phase 2 = Afternoon (Day)
///   phase 3 = Dusk (Neutral)
///   phase 4 = First Watch (Night)
///   phase 5 = Second Watch (Night)
pub fn time_of_day(turn: u32) -> TimeOfDay {
    match turn.saturating_sub(1) % 6 {
        1 | 2 => TimeOfDay::Day,
        4 | 5 => TimeOfDay::Night,
        _ => TimeOfDay::Neutral,
    }
}

/// Six-phase playbook labels; Day and Night intentionally each occur twice.
pub fn tod_phase(turn: u32) -> u8 {
    turn.saturating_sub(1) as u8 % 6
}
pub fn tod_label(turn: u32) -> &'static str {
    match tod_phase(turn) {
        0 => "Dawn",
        1 | 2 => "Day",
        3 => "Dusk",
        4 | 5 => "Night",
        _ => unreachable!(),
    }
}

/// Damage modifier in percentage points for the given alignment at this time of day.
/// Returns +25, -25, or 0.
pub fn tod_damage_modifier(alignment: Alignment, tod: TimeOfDay) -> i32 {
    match (alignment, tod) {
        (Alignment::Lawful, TimeOfDay::Day) => 25,
        (Alignment::Lawful, TimeOfDay::Night) => -25,
        (Alignment::Chaotic, TimeOfDay::Night) => 25,
        (Alignment::Chaotic, TimeOfDay::Day) => -25,
        _ => 0,
    }
}

/// Deterministic seeded RNG (Xorshift64).
///
/// No external crate required. Sufficient for reproducible combat simulation.
#[derive(Debug, Clone)]
pub struct Rng {
    state: u64,
}

impl Rng {
    /// Seed must be non-zero.
    pub fn new(seed: u64) -> Self {
        assert!(seed != 0, "Rng seed must be non-zero");
        Self { state: seed }
    }

    /// Return the current RNG state (for save serialization).
    pub fn state(&self) -> u64 {
        self.state
    }

    /// Generate the next pseudorandom u64 using xorshift64.
    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.state = x;
        x
    }

    /// Returns `true` with probability `hit_pct / 100`.
    /// `hit_pct >= 100` always hits; `hit_pct == 0` always misses.
    pub fn roll_hit(&mut self, hit_pct: u32) -> bool {
        if hit_pct >= 100 {
            return true;
        }
        if hit_pct == 0 {
            return false;
        }
        ((self.next_u64() % 100) as u32) < hit_pct
    }
}

/// Simulate `strikes` attack strikes and return total damage dealt.
///
/// Each strike hits with probability `(100 - terrain_defense_pct)%`.
/// On a hit, `base_damage` is scaled by `(100 + tod_modifier) / 100` using
/// integer arithmetic (minimum 0 damage per strike).
pub fn resolve_attack(
    rng: &mut Rng,
    base_damage: u32,
    strikes: u32,
    terrain_defense_pct: u32,
    tod_modifier: i32,
) -> u32 {
    let hit_pct = 100u32.saturating_sub(terrain_defense_pct);
    let modified_damage = ((base_damage as i64 * (100 + tod_modifier as i64)) / 100).max(0) as u32;
    let mut total = 0u32;
    for _ in 0..strikes {
        if rng.roll_hit(hit_pct) {
            total += modified_damage;
        }
    }
    total
}

/// Result of a Monte Carlo combat simulation, containing damage distributions and kill probabilities for both sides.
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
pub struct CombatPreview {
    pub attacker_hit_pct: u32,
    pub defender_hit_pct: u32,
    pub attacker_damage_per_hit: u32,
    pub attacker_strikes: u32,
    pub defender_damage_per_hit: u32,
    pub defender_strikes: u32,
    pub attacker_damage_min: u32,
    pub attacker_damage_max: u32,
    pub attacker_damage_mean: f64,
    pub defender_damage_min: u32,
    pub defender_damage_max: u32,
    pub defender_damage_mean: f64,
    pub attacker_kill_pct: f64,
    pub defender_kill_pct: f64,
    pub attacker_attack_name: String,
    pub defender_attack_name: String,
    pub attacker_hp: u32,
    pub defender_hp: u32,
    pub attacker_terrain_defense: u32,
    pub defender_terrain_defense: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PreviewError {
    #[error("unit not found")]
    UnitNotFound,
    #[error("ghost position is invalid")]
    InvalidGhost,
    #[error("target belongs to the same faction")]
    FriendlyTarget,
    #[error("units are out of attack range")]
    OutOfRange,
    #[error("n_sims must be between 1 and 1000")]
    InvalidNSims,
}

pub fn validate_combat_preview(
    state: &GameState,
    attacker_id: u32,
    defender_id: u32,
    ghost_hex: Hex,
    n_sims: u32,
) -> Result<(), PreviewError> {
    if !(1..=1000).contains(&n_sims) {
        return Err(PreviewError::InvalidNSims);
    }
    let attacker = state
        .units
        .get(&attacker_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let defender = state
        .units
        .get(&defender_id)
        .ok_or(PreviewError::UnitNotFound)?;
    if attacker.faction == defender.faction {
        return Err(PreviewError::FriendlyTarget);
    }
    let defender_hex = *state
        .positions
        .get(&defender_id)
        .ok_or(PreviewError::UnitNotFound)?;
    if !state.board.contains(ghost_hex) {
        return Err(PreviewError::InvalidGhost);
    }
    let range = match ghost_hex.distance(defender_hex) {
        1 => "melee",
        2 => "ranged",
        _ => return Err(PreviewError::OutOfRange),
    };
    if !attacker.attacks.iter().any(|a| a.range == range) {
        return Err(PreviewError::OutOfRange);
    }
    Ok(())
}

/// Resolve the live combat modifiers for an attack from a current or legal
/// ghost position. This function is read-only; the returned values are the
/// same parameters consumed by the resolver's attack rules.
pub fn combat_parameters(
    state: &GameState,
    attacker_id: u32,
    defender_id: u32,
    ghost_hex: Hex,
) -> Result<CombatParameters, PreviewError> {
    validate_combat_preview(state, attacker_id, defender_id, ghost_hex, 1)?;
    let attacker = state
        .units
        .get(&attacker_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let defender = state
        .units
        .get(&defender_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let defender_hex = *state
        .positions
        .get(&defender_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let range = if ghost_hex.distance(defender_hex) == 1 {
        "melee"
    } else {
        "ranged"
    };
    let attack = attacker
        .attacks
        .iter()
        .find(|a| a.range == range)
        .ok_or(PreviewError::OutOfRange)?;
    let defender_attack = defender.attacks.iter().find(|a| a.range == range);

    let mut ghost_state = state.clone();
    if let Some(old_hex) = ghost_state.positions.insert(attacker_id, ghost_hex) {
        ghost_state.hex_to_unit.remove(&old_hex);
    }
    ghost_state.hex_to_unit.insert(ghost_hex, attacker_id);

    let defense_on = |unit: &Unit, hex: Hex| {
        state
            .board
            .tile_at(hex)
            .and_then(|tile| {
                unit.defense
                    .get(&tile.terrain_id)
                    .copied()
                    .or(Some(tile.defense))
            })
            .unwrap_or(unit.default_defense)
    };
    let attacker_terrain_defense = defense_on(attacker, ghost_hex);
    let defender_terrain_defense = defense_on(defender, defender_hex);
    let tod = time_of_day(state.turn);

    let mut attacker_resistance = defender
        .resistances
        .get(&attack.attack_type)
        .copied()
        .unwrap_or(0);
    if attacker_resistance < 0 && defender.abilities.iter().any(|a| a == "steadfast") {
        attacker_resistance = (attacker_resistance * 2).max(-100);
    }
    let mut attacker_damage =
        ((attack.damage as i64 * (100 + attacker_resistance as i64)) / 100).max(0) as u32;
    if attacker.slowed {
        attacker_damage /= 2;
    }
    if has_special(attack, "charge") && range == "melee" {
        attacker_damage *= 2;
    }
    if has_special(attack, "backstab") {
        let opposite = Hex {
            x: defender_hex.x + (defender_hex.x - ghost_hex.x),
            y: defender_hex.y + (defender_hex.y - ghost_hex.y),
            z: defender_hex.z + (defender_hex.z - ghost_hex.z),
        };
        if ghost_state
            .hex_to_unit
            .get(&opposite)
            .and_then(|id| ghost_state.units.get(id))
            .is_some_and(|unit| unit.faction == attacker.faction)
        {
            attacker_damage *= 2;
        }
    }
    let attacker_leadership = crate::game_state::leadership_bonus(&ghost_state, attacker_id);
    if attacker_leadership > 0 {
        attacker_damage =
            (attacker_damage as u64 * (100 + attacker_leadership as u64) / 100) as u32;
    }
    let attacker_damage = ((attacker_damage as i64
        * (100 + tod_damage_modifier(attacker.alignment, tod) as i64))
        / 100)
        .max(0) as u32;

    let (defender_damage, defender_strikes, defender_hit_pct, defender_attack_id) =
        if let Some(counter) = defender_attack {
            let mut resistance = attacker
                .resistances
                .get(&counter.attack_type)
                .copied()
                .unwrap_or(0);
            if resistance < 0 && attacker.abilities.iter().any(|a| a == "steadfast") {
                resistance = (resistance * 2).max(-100);
            }
            let mut damage =
                ((counter.damage as i64 * (100 + resistance as i64)) / 100).max(0) as u32;
            if defender.slowed {
                damage /= 2;
            }
            if has_special(attack, "charge") && range == "melee" {
                damage *= 2;
            }
            let leadership = crate::game_state::leadership_bonus(state, defender_id);
            if leadership > 0 {
                damage = (damage as u64 * (100 + leadership as u64) / 100) as u32;
            }
            let damage = ((damage as i64
                * (100 + tod_damage_modifier(defender.alignment, tod) as i64))
                / 100)
                .max(0) as u32;
            (
                damage,
                counter.strikes,
                100u32.saturating_sub(attacker_terrain_defense),
                Some(counter.id.clone()),
            )
        } else {
            (0, 0, 0, None)
        };

    Ok(CombatParameters {
        attacker_attack_id: attack.id.clone(),
        defender_attack_id,
        attacker_hit_pct: 100u32.saturating_sub(defender_terrain_defense),
        defender_hit_pct,
        attacker_damage_per_hit: attacker_damage,
        attacker_strikes: attack.strikes,
        defender_damage_per_hit: defender_damage,
        defender_strikes,
        attacker_hp: attacker.hp,
        defender_hp: defender.hp,
        attacker_terrain_defense,
        defender_terrain_defense,
    })
}

/// Preview an engagement with the attacker standing on `ghost_hex`.
pub fn preview_combat(
    state: &GameState,
    attacker_id: u32,
    defender_id: u32,
    ghost_hex: Hex,
    n_sims: u32,
) -> Result<CombatPreview, PreviewError> {
    validate_combat_preview(state, attacker_id, defender_id, ghost_hex, n_sims)?;
    let attacker = state
        .units
        .get(&attacker_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let defender = state
        .units
        .get(&defender_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let defender_hex = *state
        .positions
        .get(&defender_id)
        .ok_or(PreviewError::UnitNotFound)?;
    let range = if ghost_hex.distance(defender_hex) == 1 {
        "melee"
    } else {
        "ranged"
    };
    let atk_def = state
        .board
        .tile_at(ghost_hex)
        .map(|t| {
            attacker
                .defense
                .get(&t.terrain_id)
                .copied()
                .unwrap_or(t.defense)
        })
        .unwrap_or(attacker.default_defense);
    let def_def = state
        .board
        .tile_at(defender_hex)
        .map(|t| {
            defender
                .defense
                .get(&t.terrain_id)
                .copied()
                .unwrap_or(t.defense)
        })
        .unwrap_or(defender.default_defense);
    let mut ghost_state = state.clone();
    ghost_state.positions.insert(attacker_id, ghost_hex);
    let leadership = crate::game_state::leadership_bonus(&ghost_state, attacker_id);
    let def_leadership = crate::game_state::leadership_bonus(state, defender_id);
    let flanked = false;
    Ok(simulate_combat(
        attacker,
        defender,
        atk_def,
        def_def,
        state.turn,
        n_sims,
        range,
        flanked,
        leadership,
        def_leadership,
    ))
}

/// Run `num_simulations` Monte Carlo combat simulations without mutating game state.
///
/// Simulates combat between attacker and defender, including retaliation.
/// `range_needed` is "melee" (distance 1) or "ranged" (distance 2).
/// Each simulation uses an independent RNG seed for reproducibility.
/// `flanked` indicates whether the defender has an enemy on the opposite hex (for backstab).
/// `atk_leadership_pct` / `def_leadership_pct` are leadership bonuses (0, 25, 50, etc.).
pub fn simulate_combat(
    attacker: &Unit,
    defender: &Unit,
    attacker_terrain_defense: u32,
    defender_terrain_defense: u32,
    turn: u32,
    num_simulations: u32,
    range_needed: &str,
    flanked: bool,
    atk_leadership_pct: u32,
    def_leadership_pct: u32,
) -> CombatPreview {
    let tod = time_of_day(turn);

    // Find attacker's melee attack
    let atk_attack: Option<&AttackDef> = attacker.attacks.iter().find(|a| a.range == range_needed);

    let Some(atk_attack) = atk_attack else {
        return CombatPreview {
            attacker_hit_pct: 0,
            defender_hit_pct: 0,
            attacker_damage_per_hit: 0,
            attacker_strikes: 0,
            defender_damage_per_hit: 0,
            defender_strikes: 0,
            attacker_damage_min: 0,
            attacker_damage_max: 0,
            attacker_damage_mean: 0.0,
            defender_damage_min: 0,
            defender_damage_max: 0,
            defender_damage_mean: 0.0,
            attacker_kill_pct: 0.0,
            defender_kill_pct: 0.0,
            attacker_attack_name: String::new(),
            defender_attack_name: "none".to_string(),
            attacker_hp: attacker.hp,
            defender_hp: defender.hp,
            attacker_terrain_defense,
            defender_terrain_defense,
        };
    };

    // Attacker effective damage (resistance + steadfast + ToD + specials + leadership)
    let atk_tod = tod_damage_modifier(attacker.alignment, tod);
    let mut atk_resistance = defender
        .resistances
        .get(&atk_attack.attack_type)
        .copied()
        .unwrap_or(0);
    // Steadfast: double positive resistances when defending
    if atk_resistance < 0 && defender.abilities.iter().any(|a| a == "steadfast") {
        atk_resistance = (atk_resistance * 2).max(-100);
    }
    let mut atk_effective_dmg =
        ((atk_attack.damage as i64 * (100 + atk_resistance as i64)) / 100).max(0) as u32;
    if attacker.slowed {
        atk_effective_dmg /= 2;
    }
    if has_special(atk_attack, "charge") && range_needed == "melee" {
        atk_effective_dmg *= 2;
    }
    if has_special(atk_attack, "backstab") && flanked {
        atk_effective_dmg *= 2;
    }
    if atk_leadership_pct > 0 {
        atk_effective_dmg =
            (atk_effective_dmg as u64 * (100 + atk_leadership_pct as u64) / 100) as u32;
    }
    let atk_hit_pct = 100u32.saturating_sub(defender_terrain_defense);

    // Find defender's retaliation attack
    let def_attack: Option<&AttackDef> = defender.attacks.iter().find(|a| a.range == range_needed);

    let (def_effective_dmg, def_hit_pct, def_tod) = if let Some(da) = def_attack {
        let dt = tod_damage_modifier(defender.alignment, tod);
        let mut dr = attacker
            .resistances
            .get(&da.attack_type)
            .copied()
            .unwrap_or(0);
        // Steadfast: double positive resistances for attacker when being retaliated against
        if dr < 0 && attacker.abilities.iter().any(|a| a == "steadfast") {
            dr = (dr * 2).max(-100);
        }
        let mut de = ((da.damage as i64 * (100 + dr as i64)) / 100).max(0) as u32;
        if defender.slowed {
            de /= 2;
        }
        if has_special(atk_attack, "charge") && range_needed == "melee" {
            de *= 2;
        }
        if def_leadership_pct > 0 {
            de = (de as u64 * (100 + def_leadership_pct as u64) / 100) as u32;
        }
        let dh = 100u32.saturating_sub(attacker_terrain_defense);
        (de, dh, dt)
    } else {
        (0, 0, 0)
    };

    let mut atk_dmg_min = u32::MAX;
    let mut atk_dmg_max = 0u32;
    let mut atk_dmg_total = 0u64;
    let mut def_dmg_min = u32::MAX;
    let mut def_dmg_max = 0u32;
    let mut def_dmg_total = 0u64;
    let mut atk_kills = 0u32;
    let mut def_kills = 0u32;

    for i in 0..num_simulations {
        let mut rng = Rng::new((i + 1) as u64);

        // Attacker strikes defender
        let atk_dmg = resolve_attack(
            &mut rng,
            atk_effective_dmg,
            atk_attack.strikes,
            defender_terrain_defense,
            atk_tod,
        );
        atk_dmg_min = atk_dmg_min.min(atk_dmg);
        atk_dmg_max = atk_dmg_max.max(atk_dmg);
        atk_dmg_total += atk_dmg as u64;

        let defender_survives = defender.hp > atk_dmg;
        if !defender_survives {
            atk_kills += 1;
        }

        // Defender retaliates if alive and has matching attack
        if defender_survives {
            if let Some(da) = def_attack {
                let def_dmg = resolve_attack(
                    &mut rng,
                    def_effective_dmg,
                    da.strikes,
                    attacker_terrain_defense,
                    def_tod,
                );
                def_dmg_min = def_dmg_min.min(def_dmg);
                def_dmg_max = def_dmg_max.max(def_dmg);
                def_dmg_total += def_dmg as u64;
                if attacker.hp <= def_dmg {
                    def_kills += 1;
                }
            }
        }
    }

    // Fix min for cases where defender never retaliated or attacker always killed
    if def_attack.is_none() || atk_kills == num_simulations {
        def_dmg_min = 0;
    }
    if atk_dmg_min == u32::MAX {
        atk_dmg_min = 0;
    }
    if def_dmg_min == u32::MAX {
        def_dmg_min = 0;
    }

    let n = num_simulations as f64;
    CombatPreview {
        attacker_hit_pct: atk_hit_pct,
        defender_hit_pct: def_hit_pct,
        attacker_damage_per_hit: ((atk_effective_dmg as i64 * (100 + atk_tod as i64)) / 100).max(0)
            as u32,
        attacker_strikes: atk_attack.strikes,
        defender_damage_per_hit: ((def_effective_dmg as i64 * (100 + def_tod as i64)) / 100).max(0)
            as u32,
        defender_strikes: def_attack.map(|a| a.strikes).unwrap_or(0),
        attacker_damage_min: atk_dmg_min,
        attacker_damage_max: atk_dmg_max,
        attacker_damage_mean: atk_dmg_total as f64 / n,
        defender_damage_min: def_dmg_min,
        defender_damage_max: def_dmg_max,
        defender_damage_mean: def_dmg_total as f64 / n,
        attacker_kill_pct: atk_kills as f64 / n * 100.0,
        defender_kill_pct: def_kills as f64 / n * 100.0,
        attacker_attack_name: atk_attack.name.clone(),
        defender_attack_name: def_attack
            .map(|a| a.name.clone())
            .unwrap_or_else(|| "none".to_string()),
        attacker_hp: attacker.hp,
        defender_hp: defender.hp,
        attacker_terrain_defense,
        defender_terrain_defense,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tod_damage_chaotic_night() {
        let tod = time_of_day(5); // turn 5 = Night (Second Watch)
        assert_eq!(tod, TimeOfDay::Night);
        let modifier = tod_damage_modifier(Alignment::Chaotic, tod);
        assert_eq!(modifier, 25);
        let mut rng = Rng::new(1);
        // 4 damage × 125% = 5; 1 strike; 0% defense → always hits
        let dmg = resolve_attack(&mut rng, 4, 1, 0, modifier);
        assert_eq!(dmg, 5, "Chaotic at Night: 4 × 1.25 = 5 exactly");
    }

    #[test]
    fn test_hit_rate_matches_defense() {
        let mut rng = Rng::new(1);
        let mut hits = 0u32;
        for _ in 0..10_000 {
            // 60% terrain defense → 40% hit rate; 1 damage, no ToD modifier
            let dmg = resolve_attack(&mut rng, 1, 1, 60, 0);
            if dmg > 0 {
                hits += 1;
            }
        }
        assert!(
            hits >= 3500 && hits <= 4500,
            "expected ~4000 hits (40% rate), got {}",
            hits
        );
    }

    #[test]
    fn test_simulate_combat_distribution() {
        use std::collections::HashMap;

        let sword = AttackDef {
            id: "sword".into(),
            name: "sword".into(),
            damage: 7,
            strikes: 3,
            attack_type: "blade".into(),
            range: "melee".into(),
            ..Default::default()
        };
        let spear = AttackDef {
            id: "spear".into(),
            name: "spear".into(),
            damage: 5,
            strikes: 2,
            attack_type: "pierce".into(),
            range: "melee".into(),
            ..Default::default()
        };
        let attacker = Unit {
            id: 1,
            def_id: "fighter".into(),
            hp: 38,
            max_hp: 38,
            faction: 0,
            moved: false,
            attacked: false,
            alignment: Alignment::Lawful,
            attacks: vec![sword],
            resistances: HashMap::new(),
            defense: HashMap::new(),
            default_defense: 40,
            movement: 6,
            movement_costs: HashMap::new(),
            xp: 0,
            xp_needed: 40,
            advancement_pending: false,
            level: 1,
            abilities: vec![],
            poisoned: false,
            slowed: false,
            vision_range: 0,
            cost: 0,
            advances_to: Vec::new(),
            can_recruit: false,
        };
        let defender = Unit {
            id: 2,
            def_id: "spearman".into(),
            hp: 36,
            max_hp: 36,
            faction: 1,
            moved: false,
            attacked: false,
            alignment: Alignment::Lawful,
            attacks: vec![spear],
            resistances: HashMap::new(),
            defense: HashMap::new(),
            default_defense: 40,
            movement: 5,
            movement_costs: HashMap::new(),
            xp: 0,
            xp_needed: 40,
            advancement_pending: false,
            level: 1,
            abilities: vec![],
            poisoned: false,
            slowed: false,
            vision_range: 0,
            cost: 0,
            advances_to: Vec::new(),
            can_recruit: false,
        };
        let preview = simulate_combat(&attacker, &defender, 40, 50, 1, 1000, "melee", false, 0, 0);

        // Hit percentages match terrain defense
        assert_eq!(preview.attacker_hit_pct, 50); // 100 - 50 defender defense
        assert_eq!(preview.defender_hit_pct, 60); // 100 - 40 attacker defense

        // Damage ranges are sane
        assert!(preview.attacker_damage_min <= preview.attacker_damage_max);
        assert!(preview.attacker_damage_mean >= preview.attacker_damage_min as f64);
        assert!(preview.attacker_damage_mean <= preview.attacker_damage_max as f64);
        assert!(preview.defender_damage_min <= preview.defender_damage_max);

        // Kill percentages in valid range
        assert!(preview.attacker_kill_pct >= 0.0 && preview.attacker_kill_pct <= 100.0);
        assert!(preview.defender_kill_pct >= 0.0 && preview.defender_kill_pct <= 100.0);

        // Attack names correct
        assert_eq!(preview.attacker_attack_name, "sword");
        assert_eq!(preview.defender_attack_name, "spear");

        // HP values passed through
        assert_eq!(preview.attacker_hp, 38);
        assert_eq!(preview.defender_hp, 36);

        // Terrain defense values passed through
        assert_eq!(preview.attacker_terrain_defense, 40);
        assert_eq!(preview.defender_terrain_defense, 50);
    }

    #[test]
    fn test_exact_exchange_has_expected_immediate_outcomes() {
        let lethal = CombatParameters {
            attacker_attack_id: "sword".into(),
            defender_attack_id: Some("spear".into()),
            attacker_hit_pct: 100,
            defender_hit_pct: 100,
            attacker_damage_per_hit: 10,
            attacker_strikes: 1,
            defender_damage_per_hit: 10,
            defender_strikes: 1,
            attacker_hp: 10,
            defender_hp: 5,
            attacker_terrain_defense: 0,
            defender_terrain_defense: 0,
        };
        assert_eq!(exact_exchange(&lethal).outcome_bps, [10_000, 0, 0]);

        let mixed = CombatParameters {
            attacker_hit_pct: 50,
            defender_hit_pct: 50,
            ..lethal
        };
        assert_eq!(exact_exchange(&mixed).outcome_bps, [5_000, 2_500, 2_500]);
    }

    #[test]
    fn exact_damage_sequence_accumulates_independent_volleys() {
        let attack = CombatParameters {
            attacker_attack_id: "sword".into(),
            defender_attack_id: None,
            attacker_hit_pct: 50,
            defender_hit_pct: 0,
            attacker_damage_per_hit: 10,
            attacker_strikes: 1,
            defender_strikes: 0,
            defender_damage_per_hit: 0,
            attacker_hp: 10,
            defender_hp: 20,
            attacker_terrain_defense: 0,
            defender_terrain_defense: 0,
        };
        assert_eq!(
            exact_damage_sequence(20, &[attack.clone()]),
            DamageSequenceForecast {
                kill_bps: 0,
                expected_damage_tenths: 50,
            }
        );
        assert_eq!(
            exact_damage_sequence(20, &[attack.clone(), attack]),
            DamageSequenceForecast {
                kill_bps: 2_500,
                expected_damage_tenths: 100,
            }
        );
    }

    #[test]
    fn exact_damage_sequence_handles_guaranteed_and_empty_attacks() {
        let attack = CombatParameters {
            attacker_attack_id: "sword".into(),
            defender_attack_id: None,
            attacker_hit_pct: 100,
            defender_hit_pct: 0,
            attacker_damage_per_hit: 7,
            attacker_strikes: 2,
            defender_strikes: 0,
            defender_damage_per_hit: 0,
            attacker_hp: 10,
            defender_hp: 13,
            attacker_terrain_defense: 0,
            defender_terrain_defense: 0,
        };
        assert_eq!(exact_damage_sequence(13, &[attack]).kill_bps, 10_000);
        assert_eq!(exact_damage_sequence(13, &[]).kill_bps, 0);
    }
}
