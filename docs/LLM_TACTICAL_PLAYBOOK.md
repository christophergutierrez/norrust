# TACTICAL DECISION PRIORITIES

Guide version: `tactics-v1`. Cite these stable IDs in decision annotations.
These are priorities to weigh against the live position, not a fixed move script.
The client supplies the response contract, tool syntax, and current board separately.

## Strategy

- **S1.** Open with village capture and army deployment. Assign fast scouts to
  named villages and keep the main army together around one objective. For
  Undead side 0 on `big_battle_6`, route bats toward (5,3) and (6,11), and a
  combat recruit toward (2,4), subject to live legality and threats; other
  maps/sides need their own routes. Village ownership persists after leaving:
  move an unthreatened holder to its next useful job.
- **S2.** Convert an advantage into pressure on the enemy recruiter. Greedy may
  concentrate attacks on the nearest exposed unit; look-ahead may hold villages
  and refuse bad melee. Break defended positions with coordinated attacks when
  the combined exchange justifies it. A stalemate at the safety cap is not a win.

## Tactical priorities

- **T1.** Protect the recruiter so the army can win. Prefer the keep while
  recruiting; retain a screen that blocks actual enemy attack origins. If the
  position is threatened, compare removing attackers, restoring the screen,
  and legal retreats. The recruiter can fight when the expected gain justifies
  its exposure; a fixed guard count does not establish safety.
- **T2.** Use authoritative options for coordinates, targets, recruitment, and
  advancement. Inspect missing details needed for a specific decision; use
  supplied positions and `target_ids` exactly, including move-and-attack origins.
- **T3.** Prioritize consequential actions in the following order, accounting
  for the enemy response and recruiter survival:
  - **T3.1.** Kill the enemy recruiter when a lethal sequence is available.
  - **T3.2.** Save a threatened recruiter by removing the threat, retreating,
    or restoring its screen.
  - **T3.3.** Focus fire on a living target: judge the combined attack, not
    whether each attacker can kill alone. Prefer safe finishing blows by units
    near advancement; compare XP, threshold, and likely gain. Preserve their
    accumulated value over an ordinary trade. Threshold crossing marks
    advancement pending: the unit must survive combat, then a legal `Advance`
    upgrades it and restores its new maximum HP. Advance eligible units before
    further combat.
  - **T3.4.** Recruit useful units and deploy them efficiently. Default to one
    recruit at a time on the best legal castle hex, move it toward its assigned
    job, then reuse the freed forward hex. Observe new IDs and legal moves
    before ordering recruits. Recruit a stationary group first when it must
    screen the recruiter. Continue while gold and safe capacity permit useful
    recruitment; explain deliberate saving. Compare cost with HP, resistance
    to enemy weapons, terrain, and role: durable units can heal and fight again,
    while replacing casualties costs gold, travel time, and accumulated XP.
- **T4.** Advance durable frontline units with ranged support and attack from
  favorable terrain. Use weapon matchups, including melee against units with
  no melee retaliation, and coordinated pressure rather than waiting for a
  guaranteed individual kill. Rotate damaged units toward healing behind
  healthier ones, especially veterans near advancement. Accept useful
  attrition without committing the whole army to a poor exchange.
- **T5.** Evaluate time of day for both sides' alignments. Night gives no
  automatic relative advantage in an Undead mirror; neutral units ignore it.
  Use supplied kill and retaliation forecasts to decide whether to fight or
  delay, rather than treating time of day as a categorical fight gate.
- **T6.** Plan against sequential mutation. Reserve distinct destinations
  unless an earlier action frees the hex, and ensure later actions remain
  legal after movement, recruitment, and combat. Use `Engage` for ordered
  focus fire that stops when its target dies; reassess the resulting state
  before committing reserves when needed.
- **T7.** After consequential work, delegate routine healthy units. Check
  handoff facts for useful idle attackers or recruits. Use selective finishing
  when a sweep would undo a scout assignment, healing move, or defensive job.
  For a hold, name its job, contribution forgone, and release condition in
  the existing decision/hold fields; compare it with a useful action elsewhere.
- **T8 — Concede a clearly lost game.** Resign when live facts leave no
  credible recovery or victory route; state the decisive reason. A bad roll,
  temporary threat, or material deficit alone is insufficient. A material deficit
  in units, gold, villages, or position alone is not proof. do not resign merely
  for being behind.

For an uncertain consequential choice, compare the complete batch with one
legal alternative. Record the concrete expected effect and main tradeoff in
the decision fields. Routine decisions need neither previews nor a narrated
checklist.
