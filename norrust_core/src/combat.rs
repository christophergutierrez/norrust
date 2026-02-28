use crate::unit::Alignment;

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
}
