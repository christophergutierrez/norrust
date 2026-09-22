//! Deterministic, engine-backed recruitment shared by live play and rollouts.

use serde::Serialize;

use crate::game_state::{apply_action, apply_recruit, eligible_recruiter_keep, Action, GameState};
use crate::hex::Hex;
use crate::pathfinding::{get_zoc_hexes, reachable_hexes};
use crate::schema::{AttackDef, UnitDef};
use crate::unit::Unit;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum RecruitmentPolicy {
    FirstAffordable,
    Balanced,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecruitRole {
    Frontline,
    Support,
    Scout,
    Other,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RecruitmentFallback {
    NoRecruiter,
    NoDefinitions,
    InsufficientGold,
    RoleUnavailable,
    BlockedCastle,
    EngineRejected,
}

#[derive(Clone, Debug, Serialize)]
pub struct Composition {
    pub frontline: u32,
    pub support: u32,
    pub scout: u32,
    pub other: u32,
}

impl Composition {
    fn count_mut(&mut self, role: RecruitRole) -> &mut u32 {
        match role {
            RecruitRole::Frontline => &mut self.frontline,
            RecruitRole::Support => &mut self.support,
            RecruitRole::Scout => &mut self.scout,
            RecruitRole::Other => &mut self.other,
        }
    }

    fn increment(&mut self, role: RecruitRole) {
        *self.count_mut(role) += 1;
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct RecruitmentPurchase {
    pub unit_id: u32,
    pub def_id: String,
    pub cost: u32,
    pub desired_role: RecruitRole,
    pub actual_role: RecruitRole,
    pub col: i32,
    pub row: i32,
}

#[derive(Clone, Debug, Serialize)]
pub struct RecruitmentSummary {
    pub policy: RecruitmentPolicy,
    pub recruited: u32,
    pub spent: u32,
    pub purchases: Vec<RecruitmentPurchase>,
    pub composition_before: Composition,
    pub composition_after: Composition,
    pub fallback_reason: Option<RecruitmentFallback>,
}

fn role_for_attacks(attacks: &[AttackDef], max_hp: u32, movement: u32) -> RecruitRole {
    let ranged = attacks.iter().any(|attack| attack.range == "ranged");
    let melee = attacks.iter().any(|attack| attack.range == "melee");
    let max_damage = attacks
        .iter()
        .map(|attack| attack.damage.saturating_mul(attack.strikes))
        .max()
        .unwrap_or(0);

    // This order is the classification contract. A dual-range unit fills one
    // role only: fast ranged units are scouts; all other ranged units support.
    if ranged && movement >= 7 {
        RecruitRole::Scout
    } else if ranged {
        RecruitRole::Support
    } else if melee && (max_hp >= 30 || max_damage >= 10) {
        RecruitRole::Frontline
    } else if movement >= 6 {
        RecruitRole::Scout
    } else if melee {
        RecruitRole::Frontline
    } else {
        RecruitRole::Other
    }
}

pub fn classify_recruit(def: &UnitDef) -> RecruitRole {
    role_for_attacks(&def.attacks, def.max_hp, def.movement)
}

fn composition(state: &GameState, side: u8, definitions: &[UnitDef]) -> Composition {
    let mut result = Composition {
        frontline: 0,
        support: 0,
        scout: 0,
        other: 0,
    };
    for unit in state
        .units
        .values()
        .filter(|unit| unit.faction == side && unit.hp > 0)
    {
        if let Some(def) = definitions.iter().find(|def| def.id == unit.def_id) {
            result.increment(classify_recruit(def));
        }
    }
    result
}

fn wanted_role(composition: &Composition, affordable: &[&UnitDef]) -> (RecruitRole, bool) {
    // Fill required roles in a stable order before balancing counts. The bool
    // records that the desired role is unavailable, so fallback evidence is
    // retained even when the first affordable definition can still be bought.
    for role in [
        RecruitRole::Frontline,
        RecruitRole::Support,
        RecruitRole::Scout,
    ] {
        let count = match role {
            RecruitRole::Frontline => composition.frontline,
            RecruitRole::Support => composition.support,
            RecruitRole::Scout => composition.scout,
            RecruitRole::Other => composition.other,
        };
        if count == 0 {
            return (
                role,
                !affordable.iter().any(|def| classify_recruit(def) == role),
            );
        }
    }
    let role = [
        (RecruitRole::Frontline, composition.frontline),
        (RecruitRole::Support, composition.support),
        (RecruitRole::Scout, composition.scout),
    ]
    .into_iter()
    .min_by_key(|(role, count)| {
        let order = match role {
            RecruitRole::Frontline => 0,
            RecruitRole::Support => 1,
            RecruitRole::Scout => 2,
            RecruitRole::Other => 3,
        };
        (*count, order)
    })
    .map(|(role, _)| role)
    .unwrap_or_else(|| classify_recruit(affordable[0]));
    (
        role,
        !affordable.iter().any(|def| classify_recruit(def) == role),
    )
}

fn clear_castle(state: &mut GameState, side: u8, keep: Hex) -> Option<RecruitmentFallback> {
    let occupied: Vec<Hex> = keep
        .neighbors()
        .iter()
        .copied()
        .filter(|hex| {
            state
                .board
                .tile_at(*hex)
                .is_some_and(|tile| tile.terrain_id == "castle")
                && state.hex_to_unit.contains_key(hex)
        })
        .collect();
    let zoc = get_zoc_hexes(state, side);
    for origin in occupied {
        let Some(&unit_id) = state.hex_to_unit.get(&origin) else {
            continue;
        };
        let Some(unit) = state.units.get(&unit_id).cloned() else {
            continue;
        };
        if unit.faction != side || unit.moved || unit.can_recruit {
            continue;
        }
        let movement = if unit.slowed {
            unit.movement / 2
        } else {
            unit.movement
        };
        let mut destinations: Vec<Hex> = reachable_hexes(
            &state.board,
            &unit.movement_costs,
            1,
            origin,
            movement,
            &zoc,
            false,
        )
        .into_iter()
        .filter(|hex| *hex != origin && !state.hex_to_unit.contains_key(hex))
        .collect();
        destinations.sort_unstable_by_key(|hex| {
            let remains_castle = state
                .board
                .tile_at(*hex)
                .is_some_and(|tile| tile.terrain_id == "castle");
            (!remains_castle, *hex)
        });
        let Some(destination) = destinations.first().copied() else {
            continue;
        };
        if state.active_faction != side
            || apply_action(
                state,
                Action::Move {
                    unit_id,
                    destination,
                },
            )
            .is_err()
        {
            return Some(RecruitmentFallback::EngineRejected);
        }
        return None;
    }
    Some(RecruitmentFallback::BlockedCastle)
}

fn empty_castle(state: &GameState, keep: Hex) -> Option<Hex> {
    keep.neighbors().iter().copied().find(|hex| {
        state
            .board
            .tile_at(*hex)
            .is_some_and(|tile| tile.terrain_id == "castle")
            && !state.hex_to_unit.contains_key(hex)
    })
}

fn living_recruiter_keep(state: &GameState, side: u8) -> Option<Hex> {
    eligible_recruiter_keep(state, side).filter(|keep| {
        state
            .hex_to_unit
            .get(keep)
            .and_then(|id| state.units.get(id))
            .is_some_and(|unit| unit.hp > 0)
    })
}

/// Execute every legal affordable purchase currently available to `side`.
/// The same function is used against a live state and a planning clone.
pub fn execute_recruitment(
    state: &mut GameState,
    side: u8,
    definitions: &[UnitDef],
    next_id: &mut u32,
    policy: RecruitmentPolicy,
) -> RecruitmentSummary {
    let composition_before = composition(state, side, definitions);
    let mut composition_after = composition_before.clone();
    let mut summary = RecruitmentSummary {
        policy,
        recruited: 0,
        spent: 0,
        purchases: Vec::new(),
        composition_before,
        composition_after: composition_after.clone(),
        fallback_reason: None,
    };
    loop {
        let Some(keep) = living_recruiter_keep(state, side) else {
            summary.fallback_reason = Some(RecruitmentFallback::NoRecruiter);
            break;
        };
        let affordable: Vec<&UnitDef> = definitions
            .iter()
            .filter(|def| state.gold[side as usize] >= def.cost)
            .collect();
        if affordable.is_empty() {
            if summary.fallback_reason.is_none() {
                summary.fallback_reason = Some(if definitions.is_empty() {
                    RecruitmentFallback::NoDefinitions
                } else {
                    RecruitmentFallback::InsufficientGold
                });
            }
            break;
        }
        let destination = match empty_castle(state, keep) {
            Some(destination) => destination,
            None => {
                if let Some(reason) = clear_castle(state, side, keep) {
                    summary.fallback_reason = Some(reason);
                    break;
                }
                match empty_castle(state, keep) {
                    Some(destination) => destination,
                    None => {
                        summary.fallback_reason = Some(RecruitmentFallback::BlockedCastle);
                        break;
                    }
                }
            }
        };
        let (desired_role, role_unavailable) = match policy {
            RecruitmentPolicy::FirstAffordable => (classify_recruit(affordable[0]), false),
            RecruitmentPolicy::Balanced => wanted_role(&composition_after, &affordable),
        };
        if role_unavailable && summary.fallback_reason.is_none() {
            summary.fallback_reason = Some(RecruitmentFallback::RoleUnavailable);
        }
        let Some(def) = affordable
            .iter()
            .copied()
            .find(|def| classify_recruit(def) == desired_role)
            .or_else(|| affordable.first().copied())
        else {
            summary.fallback_reason = Some(RecruitmentFallback::RoleUnavailable);
            break;
        };
        let id = *next_id;
        let cost = def.cost;
        if apply_recruit(state, Unit::from_def(id, def, side), destination, cost).is_err() {
            summary.fallback_reason = Some(RecruitmentFallback::EngineRejected);
            break;
        }
        *next_id = next_id.saturating_add(1);
        let (col, row) = destination.to_offset();
        let actual_role = classify_recruit(def);
        summary.purchases.push(RecruitmentPurchase {
            unit_id: id,
            def_id: def.id.clone(),
            cost,
            desired_role,
            actual_role,
            col,
            row,
        });
        summary.recruited += 1;
        summary.spent += cost;
        composition_after.increment(actual_role);
        summary.composition_after = composition_after.clone();
    }
    summary
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::board::{Board, Tile};

    fn unit(id: &str, hp: u32, movement: u32, range: &str, damage: u32) -> UnitDef {
        UnitDef {
            id: id.into(),
            max_hp: hp,
            movement,
            attacks: vec![AttackDef {
                range: range.into(),
                damage,
                strikes: 2,
                ..AttackDef::default()
            }],
            cost: 10,
            ..UnitDef::default()
        }
    }

    #[test]
    fn role_classification_assigns_dual_range_to_one_deterministic_role() {
        let dual = UnitDef {
            id: "dual".into(),
            max_hp: 30,
            movement: 7,
            attacks: vec![
                AttackDef {
                    range: "melee".into(),
                    ..AttackDef::default()
                },
                AttackDef {
                    range: "ranged".into(),
                    ..AttackDef::default()
                },
            ],
            ..UnitDef::default()
        };
        assert_eq!(classify_recruit(&dual), RecruitRole::Scout);
    }

    #[test]
    fn balanced_recruitment_spends_once_and_records_roles() {
        let keep = Hex::from_offset(1, 1);
        let castle = Hex::from_offset(2, 1);
        let mut board = Board::new(4, 3);
        board.set_tile(keep, Tile::new("keep"));
        board.set_tile(castle, Tile::new("castle"));
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 15;
        let mut leader = Unit::new(1, "leader", 20, 0);
        leader.can_recruit = true;
        state.place_unit(leader, keep);
        let defs = vec![
            unit("front", 40, 4, "melee", 8),
            unit("support", 20, 4, "ranged", 4),
        ];
        let mut next_id = 2;
        let result = execute_recruitment(
            &mut state,
            0,
            &defs,
            &mut next_id,
            RecruitmentPolicy::Balanced,
        );
        assert_eq!(result.recruited, 1);
        assert_eq!(result.spent, 10);
        assert_eq!(result.purchases[0].unit_id, 2);
        assert_eq!(next_id, 3);
        assert_eq!(state.gold[0], 5);
    }

    #[test]
    fn blocked_castles_and_missing_recruiter_are_explicit_fallbacks() {
        let keep = Hex::from_offset(1, 1);
        let castle = Hex::from_offset(2, 1);
        let mut board = Board::new(4, 3);
        board.set_tile(keep, Tile::new("keep"));
        board.set_tile(castle, Tile::new("castle"));
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 10;
        let mut next_id = 1;
        let defs = vec![unit("front", 40, 4, "melee", 8)];
        let result = execute_recruitment(
            &mut state,
            0,
            &defs,
            &mut next_id,
            RecruitmentPolicy::FirstAffordable,
        );
        assert_eq!(
            result.fallback_reason,
            Some(RecruitmentFallback::NoRecruiter)
        );

        let mut blocked_board = Board::new(4, 3);
        blocked_board.set_tile(keep, Tile::new("keep"));
        blocked_board.set_tile(castle, Tile::new("castle"));
        let mut blocked = GameState::new(blocked_board);
        blocked.active_faction = 0;
        blocked.gold[0] = 10;
        let mut leader = Unit::new(1, "leader", 20, 0);
        leader.can_recruit = true;
        blocked.place_unit(leader, keep);
        let mut blocker = Unit::new(2, "blocker", 20, 0);
        blocker.movement = 0;
        blocked.place_unit(blocker, castle);
        let result = execute_recruitment(
            &mut blocked,
            0,
            &defs,
            &mut next_id,
            RecruitmentPolicy::FirstAffordable,
        );
        assert_eq!(result.recruited, 0);
        assert_eq!(
            result.fallback_reason,
            Some(RecruitmentFallback::BlockedCastle)
        );
        assert_eq!(blocked.gold[0], 10);
    }

    #[test]
    fn unavailable_balanced_role_falls_back_without_overspending() {
        let keep = Hex::from_offset(1, 1);
        let castle = Hex::from_offset(2, 1);
        let mut board = Board::new(4, 3);
        board.set_tile(keep, Tile::new("keep"));
        board.set_tile(castle, Tile::new("castle"));
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 11;
        let mut leader = Unit::new(1, "leader", 20, 0);
        leader.can_recruit = true;
        state.place_unit(leader, keep);
        let defs = vec![unit("front", 40, 4, "melee", 8)];
        // Frontline is already represented, so balanced recruitment asks for
        // support. The faction offers no support definition and must record
        // the role fallback while buying the affordable frontline unit.
        state.place_unit(Unit::from_def(2, &defs[0], 0), Hex::from_offset(0, 1));
        let mut next_id = 3;
        let result = execute_recruitment(
            &mut state,
            0,
            &defs,
            &mut next_id,
            RecruitmentPolicy::Balanced,
        );
        assert_eq!(result.recruited, 1);
        assert_eq!(
            result.fallback_reason,
            Some(RecruitmentFallback::RoleUnavailable)
        );
        assert_eq!(state.gold[0], 1);
    }

    #[test]
    fn occupied_castle_is_cleared_before_recruiting_and_ids_remain_unique() {
        let keep = Hex::from_offset(1, 1);
        let castle = Hex::from_offset(2, 1);
        let escape = Hex::from_offset(3, 1);
        let mut board = Board::new(5, 3);
        board.set_tile(keep, Tile::new("keep"));
        board.set_tile(castle, Tile::new("castle"));
        board.set_tile(escape, Tile::new("flat"));
        let mut state = GameState::new(board);
        state.active_faction = 0;
        state.gold[0] = 10;
        let mut leader = Unit::new(1, "leader", 20, 0);
        leader.can_recruit = true;
        state.place_unit(leader, keep);
        let mut blocker = Unit::new(2, "blocker", 20, 0);
        blocker.movement = 4;
        state.place_unit(blocker, castle);
        let defs = vec![unit("front", 40, 4, "melee", 8)];
        let mut next_id = 3;
        let result = execute_recruitment(
            &mut state,
            0,
            &defs,
            &mut next_id,
            RecruitmentPolicy::FirstAffordable,
        );
        assert_eq!(result.recruited, 1);
        assert_eq!(result.spent, 10);
        assert_eq!(next_id, 4);
        assert_ne!(state.positions[&2], castle);
        assert_ne!(state.positions[&2], keep);
        assert_eq!(state.positions[&3], castle);
    }
}
