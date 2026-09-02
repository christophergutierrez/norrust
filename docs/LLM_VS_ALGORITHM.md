# LLM vs Algorithm

Use this when the question is: **can a language model play The Clash for Norrust**, not whether it can call an existing planner. A win is useful evidence, but it is neither guaranteed nor required.

Headless AI-vs-AI recipes, board fairness, and algorithm baselines live in [SELF_PLAY.md](SELF_PLAY.md). Combat math, ZOC, and the TCP protocol live in [AGENT_GUIDE.md](AGENT_GUIDE.md). This document is the playbook for an LLM sitting in the player's chair.

## What this measures

The LLM must **choose actions**. Legal actions are Move, Attack, Recruit, optional RecruitBatch, Advance, and EndTurn.

**Does not count** as an LLM playing:

- Calling `greedy` or `greedy-look-ahead` (`ai_take_turn`, `ai_turn`, “just run the AI”) on the LLM's faction
- Copying another model's move list without seeing the state
- Playing a different game and calling it Norrust

**Does count:**

- The model reads the board (GUI, `get_state` JSON, or the headless client prompt) and outputs moves
- A tool the **LLM wrote** for this match (a script, a scoring function). If it is good, consider adding it as a third algorithm later. Label the match **LLM+its-code vs greedy**, not “the LLM played by hand.”

Report: opponent algorithm, who moved first, faction, scenario, gold, wins–losses, and whether the LLM used extra code it authored.

## The two opponents

| Name in docs | What it does | How you actually face it |
| --- | --- | --- |
| **Greedy** | Each unit, in ID order: every reachable hex, expected-damage fight (`hit% × damage × strikes`, ×3 if that would kill), else walk toward the nearest enemy. No reply, no “is this forest?”, no focus fire, no village hunt. Fast. | `self-play --ai2 greedy`, or the headless LLM client described below. **Not** the Love2D “AI” controller. |
| **Look-ahead** (`greedy-look-ahead`) | Same game, but scores a **structured beam** (current hex, attack tiles, villages, high defense, one march hex), drops bad melee terrain trades unless a kill is likely, uses expected damage (not one combat roll), and simulates nearby enemy replies. Slower. | Love2D opponent set to **AI**, and the agent-server command `ai_turn N`. Both call `norrust_ai_take_turn`, which is look-ahead. Also `self-play --ai2 greedy-look-ahead`. |

Greedy weaknesses to play against: it walks onto 30% flat to poke 60% castle; it does not stack attacks on one wounded unit; it does not park on villages; it does not respect ToD except insofar as damage numbers change this turn; it will leave the leader if a fight scores well.

That last one is worth more than it sounds, and it is measurable. Greedy can march its leader off the keep and stop recruiting. Any economy claim should cite a committed run log with its seed, command, and result.

Two consequences for anyone designing a match. A side that keeps its own leader home out-produces greedy several-fold over a long game, so an equal-unit opening is **not** a symmetric position—it diverges in the other side's favour from turn 3. And greedy's lone leader is a high-value target that walks to you. Do not report a win over greedy as a tactical result without saying which of these did the work.

Look-ahead is harder: it already likes villages, defense, and not taking stupid melee trades. It can still be baited if you threaten something its local 3-enemy / 7-hex reply window does not see, or if you win the economy and ToD war.

Default self-play gold is not the GUI. For a fair algorithm match on `big_battle_6` use **300 gold** and **`--second-gold 0`** unless you are testing a second-player bonus. See [SELF_PLAY.md](SELF_PLAY.md).

There is **no Love2D toggle for greedy** today, and **GUI and `ai_turn` are look-ahead.** The ready headless loop is `norrust_core/src/bin/greedy_driver.rs`. It accepts one configured `--llm-side`; after the model's successful final `EndTurn`, it automatically supplies faction-legal recruitment and executes movement and combat for the greedy opponent.

## Headless LLM client

Build the driver and run the committed deterministic orders fixture from the repository root:

```bash
cargo build --bin greedy_driver --manifest-path norrust_core/Cargo.toml
python -m tools.llm_client \
  --driver norrust_core/target/debug/greedy_driver \
  --orders-file tools/orders_fixture.jsonl \
  --scenario big_battle_6 --faction0 undead --faction1 undead \
  --gold 300 --seed 202 --llm-side 0 --max-turns 4 \
  --log /tmp/norrust-llm-vs-greedy.ndjson
```

The client—not the model—issues singleton `{"action":"Query","what":"turn_options"}` and `{"action":"Query","what":"recruit_options"}` requests before each memoryless model call. `turn_options` maps current and reachable positions to target IDs. `recruit_options` supplies the active faction, legal definitions, costs, affordability, placement hexes, and macro availability. Engine responses are authoritative; the client and model must not reconstruct legality.

The model returns only a non-empty JSON array of at most 256 objects, with exactly one final `{"action":"EndTurn"}`. Each object has exactly the fields in one schema:

```text
Move         {action, unit_id: integer, col: integer, row: integer}
Attack       {action, attacker_id: integer, defender_id: integer}
Recruit      {action, def_id: string, col: integer, row: integer}
RecruitBatch {action, def_id: string, count: positive integer}  [optional]
Advance      {action, unit_id: integer, exactly one of target_index: integer or def_id: string}
EndTurn      {action}
```

`RecruitBatch` is driver-assisted placement, attempts up to the requested positive
count, and reports actual progress; it is unavailable with
`--disable-recruit-batch`. The configured model-side restriction applies to every
action, including `EndTurn`; actor IDs must belong to that side. The model never
submits `Query` or opponent actions.

Greedy recruitment, planning, actions, and its successful turn boundary form one transaction. A failure emits a typed `game_end` with `reason: "infrastructure_failure"`, a stable `code`, and a `message`, without committing state, events, allocated IDs, or side-turn accounting. The client records `infrastructure_invalid: true` and exits nonzero; the result is not a draw, win, or continuation.

Any failed driver status after forwarding a model batch is also an
infrastructure-invalid client result, so malformed or illegal model output cannot
deadlock the match.

The headless driver explicitly disables `objective_hex` and scenario turn-limit win conditions. Headless win evaluation is recruiter loss, then elimination. Recruiter loss applies when exactly one side that previously had recruiting capability has no living recruiter; that side loses. If both sides or neither side meet that predicate, evaluation falls through to elimination. The broader GUI/campaign win rule below remains useful for those modes, but does not describe this driver.

`--max-turns` is an external completed-side-turn safety cap, distinct from the engine round counter and scenario rules. Each completed model side-turn and completed greedy side-turn increments it once. A failed greedy turn adds no opponent side-turn and is terminal; the preceding completed model side-turn remains counted.

For the headless client, terminal reasons `winner` and `max_turns` are gameplay-valid. `setup_error`, `timeout`, `eof`, `infrastructure_failure`, and unknown or malformed terminal reasons are infrastructure-invalid; the client exits nonzero and records `infrastructure_invalid: true`.

## How to play

### At the board (Love2D) — vs look-ahead

```bash
cargo build --manifest-path norrust_core/Cargo.toml
export DISPLAY=:0   # if you are on this machine over SSH
export XAUTHORITY=/run/user/$(id -u)/gdm/Xauthority
love norrust_love
```

1. Pick a scenario. For a fair large map use **Big Battle** (`big_battle_6`: 180° hex-symmetric, keeps `(2,7)` and `(21,6)`).
2. You are **Blue (west / left)**. You go first unless you change that.
3. On the Red faction screen, set the controller to **AI** (`Tab` cycles Human / AI / Port). That AI is look-ahead.
4. Place your leader on the **glowing keep**. Recruits need the leader on the keep and empty **castle** hexes next to it.
5. In play: click unit → click hex (ghost) → Enter or click to commit. Click an enemy for a combat preview, again or Enter to fight. **E** end turn, **R** recruit, **A** advance. **/** help.

Do not press anything that runs AI on **your** side.

### Over the wire — LLM outputs JSON

Start Love2D with `--agent-server` (Port controller and/or `P` in play). TCP `localhost:9876`, one command per line. Client: `tools/agent_client.py`. Details: [AGENT_GUIDE.md](AGENT_GUIDE.md).

On the LLM's turn, **only** send actions, for example:

```json
{"action": "Move", "unit_id": 1, "col": 4, "row": 7}
{"action": "Attack", "attacker_id": 1, "defender_id": 5}
{"action": "EndTurn"}
```

`0` is success. Then `get_state` again.

On the opponent's turn, `ai_turn 1` (or `0`) runs **look-ahead** for that faction. Do **not** `ai_turn` your faction.

Recruit and advance JSON are in [BRIDGE_API.md](BRIDGE_API.md). Prefer `get_state` fields `moved` / `attacked` / `advancement_pending` so you do not double-act.

## Rules the model needs

Hex game, **odd-r** offset (`col`, `row`). Distance 1 = adjacent (six neighbors, not a square).

**A turn (your faction):** each of your living units may **move once** and **attack once** (move then attack, or attack in place). Then recruit if you still can, advance anyone with `advancement_pending`, **EndTurn**.

**Move:** unoccupied hex, within that unit's movement points after terrain costs. Stepping **adjacent to an enemy** ends that unit's move (**ZOC**), unless it has **skirmisher**.

**Attack:** melee if hex distance is 1 and the unit has a melee weapon. Ranged if distance is 2 and it has a ranged weapon. Defender **retaliates** with a weapon of the **same range** (melee vs melee, ranged vs ranged). No retaliation if you shoot from range 2 and they have no ranged weapon.

**Hit chance** = `100 − defender's terrain defense` (percent). Forest/hills/village ~50%, castle/keep/mountains ~60%, flat ~30%. **Marksman** = 60% always. **Magical** = 70% always.

Each weapon: `damage` per hit × `strikes` swings. ToD then scales damage:

| Alignment | Day | Night | Dawn/Dusk |
| --- | --- | --- | --- |
| Lawful | +25% | −25% | none |
| Chaotic | −25% | +25% | none |
| Neutral / Liminal | none | none | none |

Round clock: **both sides share the same ToD** on the same round (turn advances after both have acted). Cycle of six round numbers: Dawn, Day, Day, Dusk, Night, Night, repeat. Undead are **chaotic**—push at Night, do not take even fights at Day.

**Villages** (not keeps) pay **2 gold per owned village** at the start of your turn. Capture by **ending your turn standing on it**. Ownership stays when you walk off until the enemy ends a turn on it. Neutral village = 0 gold. Villages also **heal 8 HP** (and clear poison) at turn start for the unit on them.

**Keep / castle:** no gold. A recruiter on a **keep** recruits onto adjacent empty **castle** hexes for gold.

**Win (GUI/campaign rules):** precedence is scenario objective, scenario turn limit, recruiter loss, then elimination. Recruiter loss applies when exactly one side that previously had recruiting capability has no living recruiter; that side loses. If both sides or neither side meet that predicate, winner evaluation falls through to elimination. This broader rule applies to GUI/campaign gameplay, including `big_battle_6`; the headless driver disables the first two conditions and uses recruiter loss then elimination.

**XP:** 1 per hit landed, +8 for a kill. At `xp_needed`, advance (`A` or Advance action).

## Units (Undead — usual self-play roster)

Leader on this faction is **Dark Sorcerer**. All listed are **chaotic**.

| Unit | Cost | HP | Move | Attacks (range) | Notes |
| --- | ---: | ---: | ---: | --- | --- |
| Walking Corpse | 8 | 18 | 4 | 6×2 impact melee (plague) | Cheap chaff |
| Vampire Bat | 13 | 16 | 8 | 4×2 blade melee | Scout; flimsy |
| Skeleton Archer | 14 | 31 | 5 | 3×2 impact melee, **6×3 pierce ranged** | Shoot from distance 2 |
| Skeleton | 15 | 34 | 5 | 7×3 blade melee | Front line; resists blade/pierce, hates fire |
| Dark Adept | 16 | 28 | 5 | 10×2 cold **ranged**, 7×2 arcane ranged | Magician; stay back |
| Ghoul | 16 | 33 | 5 | 4×3 blade melee | Durable-ish |
| Ghost | 19 | 18 | 7 | 4×3 arcane melee, 3×3 cold ranged | Fast; forest often costs 1 |
| Dark Sorcerer | 34 | 48 | 5 | 4×3 impact melee, **13×2 cold ranged**, 9×2 arcane ranged | **Leader**—keep alive to recruit |

Resistances in data files: **negative = resists** (takes less), **positive = weak**. Skeletons: strong vs blade/pierce/cold, weak vs fire/arcane.

Other factions (Loyalists, Rebels, Northerners) are in `data/units/` and `data/factions/`. If you are not Undead, read those TOMLs before the first recruit.

## Starter strategy

1. **Leader on keep, fill castle, then fight.** Recruits need the leader on the keep. After the castle is full, the leader can leave; if you want more recruits later, bring them back.
2. **Take villages and stay on them until they are yours.** End the turn on the hex. Heal there. Greedy often will not contest this on purpose.
3. **Fight from forest, hills, village, castle.** Do not step onto flat to melee someone in a castle unless you will kill them. That is the main greedy leak.
4. **Focus fire.** Pick one enemy you can finish this turn; pile on. Greedy picks a local best fight per unit and leaves wounded threats alive.
5. **Range 2 if you have a bow or cold wave.** They often cannot hit back. Dark Adept / Sorcerer / Skeleton Archer should not walk into melee.
6. **ToD.** Chaotic: take even or losing fights at Night, not at Day. Delay a bad engagement one round if Dawn is next.
7. **ZOC.** One unit in a choke stops a walker. Do not feed units adjacent to three enemies on open ground.
8. **Do not chase.** If greedy walks onto your forest, hit it; do not follow it onto its forest.
9. vs **look-ahead:** expect it to sit on villages and refuse bad trades. Win by numbers, ToD, and threats outside its short reply range—not by offering it a 30% vs 60% melee.

Suggested first match: Undead vs Undead on `big_battle_6`, you Blue, opponent look-ahead (GUI AI), 300 gold if you can set it, you first. Then use the headless client above for the same matchup against greedy.

## After the match

Write down: model name, opponent (`greedy` or `look-ahead`), first player, scenario, factions, gold, seed, source revision, configured model side, win rule, side-turn cap, terminal result, and whether extra LLM-authored code ran. Also record whether the model issued a non-`EndTurn` action and whether greedy recruitment/events occurred. A loss or safety-cap result can still be valid evidence; an infrastructure-invalid result cannot. Do not mix these games into [SELF_PLAY.md](SELF_PLAY.md) algorithm-vs-algorithm tables.

Balance tests are excluded from this client/documentation milestone and must not be run.
