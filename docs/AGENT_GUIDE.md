# AI Agent Guide

A practical guide for building an agent that plays The Clash for Norrust. Assumes you've read
[BRIDGE_API.md](BRIDGE_API.md) for the raw API contract.

## Fog of War

The game supports fog of war based on unit vision ranges. When FOW is enabled:

- `get_state` returns the **full, unfiltered** state (useful for AI that should see everything)
- `norrust_get_state_json_fow(engine, faction)` returns state **filtered by visibility** — only
  units within the faction's vision range are included

Vision is range-based (not line-of-sight). Each unit has a `vision_range` (defaults to its
movement value if 0). A hex is visible if any friendly unit is within vision range.

Hexes have three states from the client's perspective:
- **Visible** — currently in vision range, full information
- **Fog** — previously seen but not currently visible (50% black overlay)
- **Shroud** — never seen (80% black overlay)

For agents that should play "fairly" (without full map knowledge), use the FOW-filtered state.

## Connection

Start the game with the agent server enabled:

```bash
cd norrust_love && love . -- --agent-server
```

Connect via TCP on `localhost:9876`. Protocol is line-based: send a command, receive one line back.

```
get_state       → full JSON state snapshot
get_faction     → active faction number (0 or 1)
check_winner    → winner faction (-1 if none)
ai_turn N       → run built-in AI for faction N
{"action":...}  → submit an ActionRequest JSON, returns result code (0=success)
```

A Python client library is provided at `tools/agent_client.py`:

```python
from agent_client import NorRustClient
client = NorRustClient()
state = client.get_state()
client.move_unit(unit_id=1, col=3, row=2)
client.attack(attacker_id=1, defender_id=5)
client.end_turn()
```

## Turn Lifecycle

Each turn belongs to one **active faction** (0 or 1). During your turn:

1. **Move** units (each unit can move once per turn)
2. **Attack** with units (each unit can attack once per turn, after or instead of moving)
3. **Recruit** new units on castle hexes (requires a leader on a keep hex)
4. **Advance** units with `advancement_pending = true`
5. **End turn** when done

After EndTurn:
- Active faction switches
- Turn counter increments (when faction 0 becomes active again)
- Time of Day advances: Day → Dusk → Night → Dawn → Day
- Healing applies: villages heal 8 HP, regeneration heals 8 HP
- Poison ticks for 8 damage on the ending faction's poisoned units

**Win conditions** (checked in priority order):
1. **Objective hex** — any unit reaching the target hex wins for that faction
2. **Turn limit** — if `turn > max_turns`, the defender (faction 1) wins
3. **Elimination** — if a faction has no units left, the other wins

## Reading the State

`get_state` returns a JSON snapshot. Key fields on each unit:

| Field | Meaning | Agent Use |
|-------|---------|-----------|
| `id` | Unique unit ID | Required for all actions |
| `def_id` | Unit type (e.g., "Spearman") | Lookup stats, identify threats |
| `faction` | 0 or 1 | Filter your units vs enemies |
| `col`, `row` | Hex position | Spatial reasoning |
| `hp`, `max_hp` | Current / max health | Prioritize weak targets |
| `moved`, `attacked` | Already acted this turn? | Skip exhausted units |
| `movement` | Movement points per turn | Pathfinding budget |
| `attacks` | Array of {name, damage, strikes, range, damage_type} | Damage calculation |
| `abilities` | Array of strings ("leader", "regenerates", etc.) | Special behavior |
| `xp`, `xp_needed` | Experience progress | Track advancement |
| `advancement_pending` | Ready to promote? | Must advance before other actions |

Terrain entries have `terrain_id`, `col`, `row`, `color`.

Global state: `turn`, `active_faction`, `gold[0]`, `gold[1]`.

## Legal Moves

### Movement
- Unit must belong to active faction and `moved = false`
- Destination must be within movement range (respects terrain movement costs)
- **Zone of Control (ZOC):** entering a hex adjacent to an enemy stops movement immediately
- Destination must be unoccupied

### Attack
- Attacker must be adjacent to defender (distance = 1) for melee
- Ranged attacks work at distance 2+ if the unit has a ranged weapon
- Attacker must not have `attacked = true`
- Can attack without moving first

### Recruit
- Requires a unit with "leader" ability on a keep hex
- Target hex must be a castle hex, unoccupied
- Costs gold (varies by unit type, query with `norrust_get_unit_cost`)

## Combat Math

Each attack has `damage` (per hit) and `strikes` (number of swings). Hit probability:

```
base_chance = 100 - defender_terrain_defense
```

Terrain defense varies: flat=30%, forest=50%, hills=50%, mountains=60%, castle=60%, village=50%.

**Time of Day modifiers:**
- Lawful units: +25% damage at Day, -25% at Night
- Chaotic units: +25% damage at Night, -25% at Day
- Neutral/Liminal: no modifier

**Combat sequence:**
1. Attacker swings `strikes` times, each has `base_chance`% to hit for `damage` (modified by ToD)
2. Defender retaliates with their weapon of matching range
3. Both sides earn 1 XP per hit landed, +8 XP for a kill

**Combat specials** (from unit attacks):
- `poison` — deals 8 damage/turn until healed at village
- `charge` — doubles damage for both attacker and defender
- `backstab` — doubles damage if an ally is on the opposite side of the defender
- `drain` — heals attacker for half damage dealt
- `firststrike` — this weapon attacks before the other side retaliates
- `marksman` — hit chance is always exactly 60%, ignoring terrain
- `magical` — hit chance is always exactly 70%, ignoring terrain

**Unit abilities:**
- `leadership` — adjacent allies of lower level get +25% damage
- `steadfast` — resistance bonuses are doubled (but never above 50%)
- `regenerates` — heals 8 HP per turn
- `skirmisher` — ignores ZOC (can move freely past enemies)

## Terrain Reference

| Terrain | Move Cost | Defense | Healing | Notes |
|---------|-----------|---------|---------|-------|
| flat/grassland | 1 | 30% | 0 | Open ground |
| forest | 2 | 50% | 0 | Good defense, slow |
| hills | 2 | 50% | 0 | Good defense, slow |
| mountains | 3 | 60% | 0 | Best defense, very slow |
| shallow_water | 3 | 20% | 0 | Avoid if possible |
| swamp_water | 3 | 30% | 0 | Poor terrain |
| sand | 2 | 30% | 0 | Open, slow |
| castle | 1 | 60% | 0 | High defense, recruitment hex |
| keep | 1 | 60% | 0 | Leader stands here to recruit |
| village | 1 | 50% | 8 | Heals units each turn |
| cave | 2 | 40% | 0 | Underground |
| frozen | 2 | 30% | 0 | Slippery |
| reef | 3 | 30% | 0 | Coastal |
| fungus | 2 | 40% | 0 | Underground |

Movement costs are per-unit in their TOML definition. The values above are defaults.

## The Baseline AI

The built-in `ai_take_turn` is a greedy N=0 lookahead scorer:

1. **For each unit:** find all reachable hexes, score each by expected damage to adjacent enemies
2. **Scoring:** `expected_damage = hit_chance * damage * strikes` per attack; kill bonus = 3x
3. **Move to best-scoring hex** and attack if adjacent to enemy
4. **March fallback:** if no attack is reachable, move toward the nearest enemy
5. **End turn** when all units have acted

**Known weaknesses to exploit:**
- No positional awareness — doesn't value terrain defense for its own units
- No healing behavior — won't retreat to villages
- No focus fire — picks individually optimal attacks, not team-coordinated ones
- No recruitment strategy — recruits greedily by cost
- Ignores ZOC for strategic positioning
- Doesn't block objective hexes

## Strategy Tips

- **Control villages** for sustained healing advantage
- **Use terrain** — position units on forests/hills before the enemy's turn
- **Focus fire** — concentrate attacks on one enemy to get the kill (and XP bonus)
- **Protect your leader** — leader death means no more recruitment
- **Time of Day** — push with lawful units during Day, defensive at Night (reverse for chaotic)
- **ZOC blocking** — place units adjacent to chokepoints to restrict enemy movement

## Action Examples

```python
# Move unit 3 to hex (4, 2)
client.move_unit(3, 4, 2)  # returns 0 on success

# Attack enemy unit 7 with unit 3
client.attack(3, 7)  # returns 0 on success

# Recruit a Spearman at castle hex (0, 1)
client.send_action({
    "action": "Recruit",
    "unit_id": 99,       # pick an unused ID
    "def_id": "spearman",
    "col": 0, "row": 1
})

# End your turn
client.end_turn()

# Full turn loop
state = client.get_state()
my_faction = state["active_faction"]
for unit in state["units"]:
    if unit["faction"] == my_faction and not unit["moved"]:
        # ... decide where to move and who to attack
        pass
client.end_turn()
```

## Error Handling

All actions return an integer code. Handle these:

| Code | Meaning | Common Cause |
|------|---------|--------------|
| 0 | Success | — |
| -1 | Unit not found | Wrong unit ID |
| -2 | Not your turn | Faction mismatch |
| -5 | Already moved | Unit exhausted |
| -6 | Unreachable | Path blocked or too far |
| -7 | Not adjacent | Target too far for melee |
| -8 | Not enough gold | Can't afford recruit |
| -9 | Not castle | Recruit on wrong hex |

If an action fails, the game state is unchanged — retry with different parameters or skip that unit.

## Veteran Units and Campaigns

In campaign mode, units carry over between scenarios. Veteran units retain their XP and
advancement level but heal to full HP. The agent server currently exposes single-scenario
play — campaign progression is handled by the Love2D client.

---
*See also: [BRIDGE_API.md](BRIDGE_API.md) for the complete C ABI reference.*
