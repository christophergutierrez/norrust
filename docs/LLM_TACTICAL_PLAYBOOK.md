# TACTICAL DECISION PRIORITIES

Guide version: `tactics-v1`. Cite these stable IDs in decision annotations.
Apply to live facts using the supplied contract and legal options.

Execute routine actions promptly. Analyze recruiter safety and contested
combat carefully.

## Shared combat doctrine

1. Protect recruiter survival and recruitment; judge retaliation and next-turn enemy focus.
2. Maintain army strength with useful recruits; contest villages and avoid idle gold.
3. Durable units screen vulnerable damage dealers; ranged units stay close enough to support the screen. Choose durability against the enemy's actual weapons.
4. Advance together; rotate wounded units behind healthy replacements. Verify enemy attack origins; a frontline does not guarantee safety.
5. Compare a supported counterattack with retreat. Coordinate attacks to remove threats and hold useful ground; independent retreats can expose allies and concede villages.
6. Focus available damage on reachable targets; reassess survivors before switching targets.

## Strategy

- **S1.** Assign scouts to named villages and give the army one objective. Village ownership persists after leaving;
  reassign safe holders. Replan on completion, block, or changed facts; recruiter emergencies
  interrupt.
- **S2.** Convert advantage into recruiter pressure. Measure progress by kills,
  denied attacks, villages, or position. Damage alone proves none of these.
  Break defenses when the whole exchange pays; a cap draw is not a win.

## Tactical priorities

- **T0.** Recruit, deploy, refill: one recruit at a time when exact placement
  matters; reuse freed forward hexes. Full castle: move eligible occupants
  toward objectives, then recruit again. Recruit a screen before deploying if
  needed. Spend until no useful recruit is affordable or no safe deployment
  frees capacity; explain deliberate saving. Choose by cost, durability,
  enemy weapons, terrain, and role. Replacing casualties costs gold, travel
  time, and XP.
- **T1.** Prefer the keep while recruiting. Recruiter combat must justify
  next-turn exposure. A guard count alone proves nothing.
- **T2.** Use supplied coordinates, targets, recruitment, and promotion
  options — documented mechanics, not another game's rules. Empty
  choice list does not mean no legal moves: inspect the unit or use
  authoritative coordinates. For an uncertain attack origin, inspect the
  enemy target; before retreat or deployment, inspect the specific unit.
  Read-only inspection supplies facts; no action choice. Among
  similar legal alternatives, choose one; reuse it instead of re-deriving
  settled paths.
- **T3.** Prioritize outcomes, including the enemy response:
  - **T3.1.** Take a winning recruiter kill when available.
  - **T3.2.** Save a threatened recruiter: remove threats, screen, or retreat.
  - **T3.3.** Focus fire; judge the combined attack. Reserve enough attackers
    and distinct origins.
    "Finish next turn" requires surviving attackers and continued target access.
    Prefer safe near-promotion finishes. Threshold
    crossing makes advancement pending: the unit must survive combat, then
    legal `Advance` restores its new maximum HP. Advance before further combat.
- **T4.** Compare current and proposed positions with the same threat measure.
  Low retaliation is not safety. Reject unfavorable chip damage unless it
  enables a named kill, objective, or necessary sacrifice; useful attrition
  need not guarantee a kill. Use favorable terrain
  and weapon matchups (melee avoids ranged retaliation). Survival can precede healing.
  When healing matters, name the verified healing hex or regeneration ability
  and check recovery; preserve veteran value. Once routine meets the objective at
  acceptable risk, stop; consequential combat still warrants one legal
  alternative.
- **T5.** Compare both alignments and the next enemy turn's time of day.
  Shared alignment gives no automatic relative advantage; neutral ignores
  time of day. Use forecasts rather than an automatic fight/wait rule.
- **T6.** Keep later actions legal after earlier moves, recruits, and kills.
  Each unit has one independent Move and one independent Attack per side turn;
  unused movement does not create another Move. Move then Attack and Attack
  then Move may both be legal, while Move then Attack then Move is not.
  Coordinates use the engine's odd-r `(col,row)` layout.
  Reserve distinct destinations unless freed earlier. `Engage` may use a
  stationary attacker at its current hex and stops when its target dies;
  completing one engagement does not end the turn. Attacking does not spend
  unused movement: consider attack then retreat; verify live movement flags and
  legal destinations. Refresh after consequential results; batch
  known-dependency work.
  Batches are sequential and atomic; repair rejected batches.
  Recruits occupy their hexes until moved.
- **T7.** Before finishing: affordable recruits, unfinished assignments,
  useful idle units, exposed recruiter? Resolve or explain consequential
  omissions. Distinguish remaining movement and attack flags from actual
  `attack_coverage`; an unused attack flag alone does not prove a legal target.
  Delegate routine healthy units; use selective finishing to retain scouts,
  healing moves, and screens. Hold for a concrete purpose with a condition for
  revisiting or release; do not treat a hold as a permanent garrison. Explain
  only consequential idle units or deliberate saving.
- **T8 — Concede a clearly lost game.** Resign only when live facts leave no
  credible recovery or victory route; name why. A bad roll, deficit, or one
  simulated loss is insufficient.

Submit useful, legal actions at acceptable risk promptly. Inspect missing facts;
reconsider on new evidence or mistaken assumptions. Never trade legality for speed. Forecasts
are uncertain; simulation is not live state.
