//! Combat resolution with deterministic RNG, time-of-day modifiers, and Monte Carlo simulation.

use crate::schema::AttackDef;
use crate::unit::{Alignment, Unit};

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
    let modified_damage =
        ((base_damage as i64 * (100 + tod_modifier as i64)) / 100).max(0) as u32;
    let mut total = 0u32;
    for _ in 0..strikes {
        if rng.roll_hit(hit_pct) {
            total += modified_damage;
        }
    }
    total
}

/// Result of a Monte Carlo combat simulation, containing damage distributions and kill probabilities for both sides.
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

/// Run `num_simulations` Monte Carlo combat simulations without mutating game state.
///
/// Simulates combat between attacker and defender, including retaliation.
/// `range_needed` is "melee" (distance 1) or "ranged" (distance 2).
/// Each simulation uses an independent RNG seed for reproducibility.
pub fn simulate_combat(
    attacker: &Unit,
    defender: &Unit,
    attacker_terrain_defense: u32,
    defender_terrain_defense: u32,
    turn: u32,
    num_simulations: u32,
    range_needed: &str,
) -> CombatPreview {
    let tod = time_of_day(turn);

    // Find attacker's melee attack
    let atk_attack: Option<&AttackDef> = attacker.attacks.iter()
        .find(|a| a.range == range_needed);

    let Some(atk_attack) = atk_attack else {
        return CombatPreview {
            attacker_hit_pct: 0, defender_hit_pct: 0,
            attacker_damage_per_hit: 0, attacker_strikes: 0,
            defender_damage_per_hit: 0, defender_strikes: 0,
            attacker_damage_min: 0, attacker_damage_max: 0, attacker_damage_mean: 0.0,
            defender_damage_min: 0, defender_damage_max: 0, defender_damage_mean: 0.0,
            attacker_kill_pct: 0.0, defender_kill_pct: 0.0,
            attacker_attack_name: String::new(),
            defender_attack_name: "none".to_string(),
            attacker_hp: attacker.hp, defender_hp: defender.hp,
            attacker_terrain_defense, defender_terrain_defense,
        };
    };

    // Attacker effective damage (resistance + ToD)
    let atk_tod = tod_damage_modifier(attacker.alignment, tod);
    let atk_resistance = defender.resistances.get(&atk_attack.attack_type).copied().unwrap_or(0);
    let atk_effective_dmg = ((atk_attack.damage as i64 * (100 + atk_resistance as i64)) / 100).max(0) as u32;
    let atk_hit_pct = 100u32.saturating_sub(defender_terrain_defense);

    // Find defender's melee retaliation attack
    let def_attack: Option<&AttackDef> = defender.attacks.iter()
        .find(|a| a.range == range_needed);

    let (def_effective_dmg, def_hit_pct, def_tod) = if let Some(da) = def_attack {
        let dt = tod_damage_modifier(defender.alignment, tod);
        let dr = attacker.resistances.get(&da.attack_type).copied().unwrap_or(0);
        let de = ((da.damage as i64 * (100 + dr as i64)) / 100).max(0) as u32;
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
        let atk_dmg = resolve_attack(&mut rng, atk_effective_dmg, atk_attack.strikes, defender_terrain_defense, atk_tod);
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
                let def_dmg = resolve_attack(&mut rng, def_effective_dmg, da.strikes, attacker_terrain_defense, def_tod);
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
        attacker_damage_per_hit: atk_effective_dmg,
        attacker_strikes: atk_attack.strikes,
        defender_damage_per_hit: def_effective_dmg,
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
        defender_attack_name: def_attack.map(|a| a.name.clone()).unwrap_or_else(|| "none".to_string()),
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
            id: "sword".into(), name: "sword".into(),
            damage: 7, strikes: 3, attack_type: "blade".into(), range: "melee".into(),
            ..Default::default()
        };
        let spear = AttackDef {
            id: "spear".into(), name: "spear".into(),
            damage: 5, strikes: 2, attack_type: "pierce".into(), range: "melee".into(),
            ..Default::default()
        };
        let attacker = Unit {
            id: 1, def_id: "fighter".into(), hp: 38, max_hp: 38,
            faction: 0, moved: false, attacked: false,
            alignment: Alignment::Lawful,
            attacks: vec![sword], resistances: HashMap::new(),
            defense: HashMap::new(), default_defense: 40,
            movement: 6, movement_costs: HashMap::new(),
            xp: 0, xp_needed: 40, advancement_pending: false,
            abilities: vec![],
        };
        let defender = Unit {
            id: 2, def_id: "spearman".into(), hp: 36, max_hp: 36,
            faction: 1, moved: false, attacked: false,
            alignment: Alignment::Lawful,
            attacks: vec![spear], resistances: HashMap::new(),
            defense: HashMap::new(), default_defense: 40,
            movement: 5, movement_costs: HashMap::new(),
            xp: 0, xp_needed: 40, advancement_pending: false,
            abilities: vec![],
        };
        let preview = simulate_combat(&attacker, &defender, 40, 50, 1, 1000, "melee");

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
}
