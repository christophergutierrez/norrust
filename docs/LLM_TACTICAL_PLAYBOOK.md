# TACTICAL DECISION PRIORITIES

Guide version: `tactics-v1`. Return an `actions` envelope with `decisions` on
every action response, including review, repair, finish, and resignation.
Each decision group has exactly `orders`, `rules`, `expected`, and `risk`:

- `orders`: zero-based authored action indices, before macros or greedy actions
  expand. Cover every action exactly once; related actions may share a group.
- `rules`: one to four unique IDs from the labeled rules below.
- `expected` and `risk`: a concrete expected effect and main tradeoff, each a
  nonempty string of at most 240 UTF-8 bytes. A rule citation alone is not
  enough.
- Use at most 16 groups and 256 action references. Add an empty `orders` group
  for consequential omissions (holding healthy units, saving affordable
  recruitment, or declining an attack); name the unit/resource in `expected`.

Example: `{"actions":[{"action":"DoneWithImportantMoves"}],"decisions":[{"orders":[0],"rules":["T7"],"expected":"Delegate routine units; keep the recruiter in place.","risk":"Delegated destinations may expose units."}]}`

The optional agenda is an object shaped as `{"tasks": [...], "holds": [...]}`.
Each task has exactly `id`, `goal`, `units`, and `status`; status is one of
`pending`, `active`, `done`, or `deferred`, and at most one task is active. Task
goals are bookkeeping text; `units` and `holds` contain integer friendly IDs.
Agenda and decision prose do not issue moves or create engine holds. To
selectively finish, list delegated units in groups and encode held units in the
executable `FinishWithGreedy` holds list, for example:
`{"actions":[{"action":"FinishWithGreedy","groups":[{"mode":"greedy","unit_ids":[12]}],"holds":[{"unit_id":14,"reason":"screen recruiter; release when threat ends"}]}],"decisions":[{"orders":[0],"rules":["T7"],"expected":"U12 advances with the screen; U14 keeps the recruiter safe.","risk":"U14 forgoes its attack until the threat ends."}]}`.
Only listed IDs are swept or held; other units remain unswept. The executable
hold's `reason` names its job and release condition; decision `expected` and
`risk` describe effect and forgone contribution. Earlier authored moves,
recruitment or auto-vacating, and later opponent attacks are unaffected.
An explicit recruiter in a group may move the leader; automatic finish
eligibility excludes the recruiter; selective groups may explicitly delegate
it.

Handoff facts distinguish delegated, held, omitted, and recruiter IDs. They are
boundary instructions, not final positions or safety certificates: automatic
eligibility is not delegation, and earlier actions, vacates, and opponent
effects may change the result.

Compact forecast `e` and `focus_e` values are expected damage in tenths of HP
(`24` = 2.4 HP); `p` and `focus_p` are probabilities in basis points
(`6400` = 64%). Direct maximum-damage fields remain whole HP. Ordinary exchange
forecasts give exact supplied probabilities under their assumptions; threat and
focus summaries are bounds, and none are guarantees.

Preview and bounded-rollout results are hypothetical under
`SIMULATION — NOT EXECUTED`; do not treat them as current. Queries execute no
actions. Before final actions, use the live-state reminder for revision, side,
gold, unit/HP totals, and recruiters.
If a draft is revised, re-plan from that live revision; a rolled-back draft
leaves it unchanged.

`TYPE` resistance values describe incoming damage with a signed modifier:
positive means vulnerability (`+40` takes 40% more damage), negative means
resistance (`-60` takes 60% less damage), and zero means unchanged damage.
Missing values are unknown. Apply this base modifier with the supplied combat
context; do not reverse the signs.

Use these priorities as guidance on every turn; they do not prescribe one move.
When a consequential choice is uncertain, compare the complete action
batch with one legal alternative. For a hold, consider a concrete
contribution elsewhere; for an attack, consider retaining or repositioning the
unit. Explain the difference in decision fields.
Routine moves do not need previews.

**T8 — Concede a clearly lost game.** At each decision, assess whether live
facts still show a credible recovery or victory route. A material deficit in
units, gold, villages, or position alone is not proof that recovery is
impossible; state the concrete threat, economy, timing, or combat facts that
close every plausible route. If the position is clearly lost—for example, the
recruiter cannot escape a decisive threat, or the remaining force and economy
cannot rebuild a competitive army—concede with `[ {"action":"Resign"} ]`.
Resignation is immediately legal, final, and must be the only action; it needs
no extra call or approval. Do not prolong an unavoidable defeat, but do not
resign merely for being behind, after a bad roll, under a temporary threat, or
before reaching the enemy.

**S1.** Keep a simple plan across turns: fast units can capture villages, a
durable frontline protects the main force, and ranged units operate behind a
screen. Keep the army together around one purpose (enemy keep, isolated group,
or village route). Before the boundary, account for every consequential move,
recruitment, attack, retreat, and formation change. Advance support with the
frontline while retaining a screen and distance; do not freeze healthy ranged
support under a generic formation reason. Routine healthy non-recruiters are
normally delegated after specific rescue, recruit, attack, and guard work is
complete. An explicit guard exception may hold a unit, but its decision group
must name its job, the action or pressure forgone, and the condition that
releases it in the existing `reason`, `expected`, and `risk` fields.

**T1.** Treat recruiter survival as non-negotiable. Prefer the keep and a
screen, but compare legal destinations and retreat if the current hex is
threatened. Identify actual attack origins and whether the screen blocks them;
a fixed guard count is not enough. The recruiter may attack from the keep, but
survival takes priority.

**T2.** Read authoritative `turn_options` and `recruit_options`; use supplied
positions and `target_ids` exactly. Do not invent coordinates, targets, paths,
or legality.

**T3.** Build legal candidates in this order, rejecting candidates that
needlessly expose the recruiter:

- **T3.1.** Kill the enemy recruiter when a lethal sequence is available.
- **T3.2.** Save a threatened recruiter by removing the threat, retreating, or
  restoring its screen.
- **T3.3.** Focus fire on a living target when possible, assigning attackers
  until a combined kill is plausible, but judge coordinated attacks by total
  expected effect, survivability, and enemy response. A useful attack need not
  independently kill its target or meet an instant-kill prerequisite; use a
  second target if useful attackers remain. Use `Engage` for ordered
  move-and-attack steps; it skips remaining steps when the target dies. Inspect
  the updated state before reserve movements when useful.
- **T3.4.** Improve economy and advancement: vacate castle hexes for useful
  placements, recruit when legal, then take useful advances or forward
  positions. Recruit while useful, while allowing a stated reason to save gold.
  After vacating, recruit into every useful empty castle hex and repeat only
  while affordability and legal capacity support progress; auto-vacating can
  make later waves exceed the initially empty spaces. Every extra wave spends
  gold and may cost position or movement. Use `TYPE` profiles and the
  visible roster for composition. If `RecruitBatch` is enabled, count by type;
  otherwise issue one `Recruit` per empty castle hex.

**T4.** Form a line and fight with coordinated pressure; do not passively wait
or march every unit into the enemy. Expect attrition over many Time-of-Day
cycles, not a turn-2 all-in. Use forest, hills, village, or castle; put durable
high-HP units in front and ranged units behind a screen, generally attacking
from distance 2. When a destination exposes a desired `target_id`, emit its
legal `Move` followed by the matching `Attack`. Compare the combined forecast,
follow-up positions, and enemy response: a coordinated attack can be useful
even when no single action kills. Retreat badly damaged front units behind
healthier ones and close rank. Fast units may capture another village when it
helps the route; do not detach the main force for a marginal gain. Prefer
healing valuable damaged units, keep recruiting after the opening dump, and do
not donate the army on Day.

**T5.** Time of day changes both sides' damage. Compare both alignments before
treating it as a fight gate. In an Undead mirror, Night is not automatically a
relative advantage. Delay a bad exchange when the opponent benefits equally or
more, comparing absolute kill and retaliation odds with supplied forecasts;
neutral units ignore ToD.

**T6.** Plan against sequential mutation: reserve a unique destination for
each move and ensure later actions remain valid after earlier actions execute.
Avoid speculative, unreachable, or redundant actions.

**S2.** Greedy may concentrate attacks on the nearest exposed unit; do not
assume a screen survives. Look-ahead may sit on villages and refuse bad melee
for many turns. Break a hex with coordinated focus fire when the combined
forecast justifies it, account for ToD, and keep recruiting when it is the best
use of gold. A stalemate reaches the safety cap and is not a win.

**T7.** Make important moves first: protect the recruiter, recruit or deliberately
save gold, arrange attacks and retreats, capture useful villages, advance key
units, and set the formation. Then review handoff facts for healthy idle units,
held and delegated IDs, current attacks, gold, affordable recruits, and open
placements. Default to delegating routine healthy units after specific rescue
and other consequential work. For each explicit guard hold, use the existing
`reason`, `expected`, and `risk` fields to name the current job, the action or
pressure forgone, and a release condition; prose alone does not hold a unit.
Use `FinishWithGreedy` for units that must avoid delegation and list only
intended delegated IDs in its groups. An explicit recruiter group is permitted
to move the leader; automatic finish excludes it. When work is complete,
emit `DoneWithImportantMoves`; bare `EndTurn` is a fallback that runs the same
sweep and records an implicit handoff. `TURN_PROGRESS` shows moved/attacked
units and remaining attackers. An affordable recruit supports continuing;
saving gold is valid when the intent states why.

When using `Engage`, actions execute sequentially. If an earlier attack kills
the target, later steps, including moves, are skipped. Prefer short sequences
when the target may die, or inspect the resulting state before reserve moves.
