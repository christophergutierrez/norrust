# Contributing Content to The Clash for Norrust

This guide explains how to add game content — units, scenarios, sounds, factions, and terrain — without writing any code. All content is defined in TOML files and image assets organized in the `data/` and `scenarios/` directories.

## Directory Layout

```
data/
  units/<name>/          # One directory per unit type
    <name>.toml          # Unit stats (required)
    sprite.toml          # Sprite metadata (optional)
    idle.png             # Animation spritesheets (optional)
    attack-melee.png
    ...
  terrain/               # Terrain definitions + tile images
    flat.toml
    flat.png
    ...
  factions/              # Faction definitions
    loyalists.toml
    ...
  recruit_groups/        # Named groups of recruitable units
    human_base.toml
    ...
  sounds/                # Sound effect overrides (.ogg or .wav)
    hit.ogg
    ...

scenarios/<name>/        # One directory per scenario
  board.toml             # Map layout (required)
  units.toml             # Starting unit placements (required)
  dialogue.toml          # Narrator dialogue (optional)
  music.ogg              # Background music (optional)
```

## Adding a Unit

Create a directory `data/units/<name>/` with a `<name>.toml` file inside.

**Example:** To add a "Pikeman" unit, create `data/units/pikeman/pikeman.toml`:

```toml
id = "Pikeman"
name = "Pikeman"
race = "human"
level = 2
experience = 65
max_hp = 48
movement = 5
alignment = "lawful"
cost = 23
abilities = []
advances_to = []

[[attacks]]
id = "pike"
name = "pike"
damage = 10
strikes = 3
attack_type = "pierce"
range = "melee"
specials = []

[resistances]
arcane = -10
blade = 10
cold = 0
fire = 0
impact = 0
pierce = 40

[movement_costs]
castle = 1
cave = 2
flat = 1
forest = 2
frozen = 3
fungus = 2
hills = 2
mountains = 3
reef = 2
sand = 2
shallow_water = 3
swamp_water = 3
village = 1

[defense]
castle = 40
cave = 60
flat = 60
forest = 50
frozen = 80
fungus = 50
hills = 50
mountains = 40
reef = 70
sand = 70
shallow_water = 80
swamp_water = 80
village = 40
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (used in unit_type references) |
| `name` | string | Display name |
| `race` | string | Race name |
| `level` | integer | Unit level (1 = base, 2 = advanced) |
| `max_hp` | integer | Maximum hit points |
| `movement` | integer | Movement points per turn |
| `attacks` | array | At least one attack (see below) |
| `resistances` | table | Damage type modifiers (% reduction, negative = weakness) |
| `movement_costs` | table | Movement cost per terrain type |
| `defense` | table | Chance to be hit per terrain (lower = better defense) |

### Optional Fields

| Field | Default | Description |
|-------|---------|-------------|
| `experience` | 0 | XP needed to advance |
| `advances_to` | [] | Unit types this can promote to |
| `alignment` | "neutral" | "lawful", "neutral", or "chaotic" (affects time-of-day combat) |
| `cost` | 0 | Gold cost to recruit |
| `abilities` | [] | Special abilities (e.g., "leader", "leadership") |
| `usage` | "" | Unit role category |

### Attack Fields

Each `[[attacks]]` entry needs:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Attack identifier |
| `name` | string | Display name |
| `damage` | integer | Damage per strike |
| `strikes` | integer | Number of strikes per attack |
| `attack_type` | string | "blade", "pierce", "impact", "fire", "cold", "arcane" |
| `range` | string | "melee" or "ranged" |
| `specials` | array | Attack special abilities (e.g., "charge", "poison") |

### Adding Sprites (Optional)

Units without sprites render as colored circles — perfectly functional. To add sprites:

1. Create spritesheet PNGs in the unit directory (256x256 frames, horizontal strip):
   - `idle.png` — idle animation (4 frames typical)
   - `attack-melee.png` — melee attack (6 frames typical)
   - `attack-ranged.png` — ranged attack, if unit has ranged (4 frames typical)
   - `defend.png` — taking damage (3 frames typical)
   - `death.png` — death animation (4 frames typical)
   - `portrait.png` — single 256x256 portrait for the info panel

2. Create `sprite.toml` describing the spritesheets:

```toml
id = "pikeman"

[idle]
file = "idle.png"
frame_width = 256
frame_height = 256
frames = 4
fps = 4

[attacks.melee]
file = "attack-melee.png"
frame_width = 256
frame_height = 256
frames = 6
fps = 8

[defend]
file = "defend.png"
frame_width = 256
frame_height = 256
frames = 3
fps = 6

[death]
file = "death.png"
frame_width = 256
frame_height = 256
frames = 4
fps = 6

[portrait]
file = "portrait.png"
```

## Creating a Scenario

Create a directory `scenarios/<name>/` with at least `board.toml` and `units.toml`.

### board.toml — Map Layout

Defines the hex grid using terrain IDs in a flat row-major array (left to right, top to bottom).

```toml
width = 8
height = 5

# Optional win conditions
objective_col = 6
objective_row = 2
max_turns = 20

tiles = [
  "flat", "flat", "forest", "hills", "flat", "flat", "flat", "flat",
  "castle", "castle", "flat", "forest", "flat", "village", "castle", "castle",
  "keep", "castle", "hills", "flat", "flat", "hills", "castle", "keep",
  "castle", "castle", "flat", "forest", "flat", "village", "castle", "castle",
  "flat", "flat", "forest", "hills", "flat", "flat", "flat", "flat",
]
```

The `tiles` array must have exactly `width * height` entries. Available terrain IDs: `flat`, `forest`, `hills`, `mountains`, `castle`, `keep`, `village`, `cave`, `frozen`, `fungus`, `sand`, `shallow_water`, `swamp_water`, `reef`.

**Win conditions:**
- `objective_col` + `objective_row`: a unit reaching this hex wins for that faction
- `max_turns`: defender (faction 1) wins if the turn limit is reached
- If neither is set, the game ends when one faction is eliminated

### units.toml — Starting Positions

Place units on the board. Each `[[units]]` entry needs a unique `id`, a `unit_type` matching a unit TOML `id`, a `faction` (0 = player/blue, 1 = AI/red), and hex coordinates.

```toml
[[units]]
id = 1
unit_type = "Lieutenant"
faction = 0
col = 2
row = 2

[[units]]
id = 2
unit_type = "Lieutenant"
faction = 1
col = 6
row = 2

[[units]]
id = 3
unit_type = "Spearman"
faction = 1
col = 7
row = 2
```

Units with the "leader" ability can recruit on castle hexes. Place leaders on `keep` hexes with adjacent `castle` hexes for recruitment zones.

### dialogue.toml — Narrator Text (Optional)

Trigger narrative text at specific moments during gameplay.

```toml
[[dialogue]]
id = "intro"
trigger = "scenario_start"
text = "Your forces have reached the crossing."

[[dialogue]]
id = "turn3_warning"
trigger = "turn_start"
turn = 3
faction = 0
text = "Enemy reinforcements are approaching from the east."

[[dialogue]]
id = "leader_hit"
trigger = "leader_attacked"
text = "The commander is under attack!"

[[dialogue]]
id = "bridge_reached"
trigger = "hex_entered"
col = 8
row = 4
text = "Your forces have reached the bridge."
```

**Trigger types:**
| Trigger | When it fires | Extra fields |
|---------|--------------|--------------|
| `scenario_start` | When scenario loads | — |
| `turn_start` | Start of a turn | `turn` (optional), `faction` (optional) |
| `turn_end` | End of a turn | `turn` (optional), `faction` (optional) |
| `leader_attacked` | First attack on a leader unit | — |
| `hex_entered` | A unit moves to a specific hex | `col`, `row` (required) |

Each dialogue entry fires once per scenario (one-shot).

### music.ogg — Background Music (Optional)

Drop a `music.ogg` file in the scenario directory. It loops automatically when the scenario loads.

### Wiring a Scenario into the Game

This is the one step that requires a code change. Add an entry to the `SCENARIOS` table in `norrust_love/main.lua`:

```lua
{name = "My Scenario (8x5)", board = "myscenario/board.toml", units = "myscenario/units.toml", preset_units = true},
```

Set `preset_units = true` if units are placed from the TOML file (most scenarios). Set `preset_units = false` for sandbox-style scenarios where players pick units manually.

## Adding Sounds

The game uses procedural placeholder sounds by default. To replace any effect with a real audio file, drop an `.ogg` or `.wav` file into `data/sounds/` with the matching name.

**Available effect names:**

| Name | When it plays |
|------|--------------|
| `hit` | Attack connects |
| `miss` | Attack misses |
| `death` | Unit dies |
| `move` | Unit moves |
| `recruit` | Unit recruited |
| `turn_end` | Turn ends |
| `select` | Unit selected |

**Example:** To replace the hit sound, place `data/sounds/hit.ogg`. The game prefers `.ogg`, then `.wav`, then falls back to the procedural sound.

## Factions

Faction files live in `data/factions/<name>.toml`.

```toml
id = "loyalists"
name = "Loyalists"
leader_def = "Lieutenant"
recruits = ["human_base"]
starting_gold = 100
```

| Field | Description |
|-------|-------------|
| `id` | Unique faction identifier |
| `name` | Display name |
| `leader_def` | Unit type ID for the faction's leader |
| `recruits` | List of recruit group IDs (see below) |
| `starting_gold` | Gold at game start |

### Recruit Groups

Recruit groups live in `data/recruit_groups/<name>.toml` and define which units a faction can recruit.

```toml
id = "human_base"
members = ["Spearman", "Bowman", "Cavalryman", "Mage", "Heavy Infantryman", "Sergeant"]
```

## Terrain

Terrain files live in `data/terrain/<id>.toml` alongside an optional `<id>.png` tile image.

```toml
id = "forest"
name = "Forest"
symbol = "F"
default_defense = 50
default_movement_cost = 2
healing = 0
color = "#2d5a1e"
```

| Field | Description |
|-------|-------------|
| `id` | Terrain identifier (used in board tiles arrays) |
| `name` | Display name |
| `default_defense` | Base chance to be hit (%) when unit has no terrain-specific defense |
| `default_movement_cost` | Base movement cost when unit has no terrain-specific cost |
| `healing` | HP healed per turn (villages typically use 8) |
| `color` | Hex color for fallback rendering |

## Testing Your Content

1. Run the game: `cd norrust_love && love .`
2. Select your scenario from the menu
3. Verify units appear with correct stats (click a unit to inspect)
4. Play through to confirm win conditions and dialogue triggers work

If a unit has no sprites, it renders as a colored circle with the unit name — this is normal and fully playable.
