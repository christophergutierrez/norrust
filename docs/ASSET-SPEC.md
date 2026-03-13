# Asset Specification — The Clash for Norrust

This document defines the file formats, naming conventions, metadata schema, and pipeline workflow for all visual assets in the game. Any contributor, artist, or AI tool can produce conforming assets by following this specification.

---

## 1. Directory Structure

Unit sprites and terrain tiles live alongside their TOML definitions in `data/`:

```
data/
  terrain/
    flat.toml                    # terrain definition
    flat.png                     # hex terrain tile, keyed by terrain_id
    forest.toml
    forest.png
    ...                          # one TOML + PNG pair per terrain type
  units/
    spearman/                    # directory keyed by def_id (tree-structured)
      spearman.toml              # unit stats (required)
      sprite.toml                # sprite metadata sidecar (required for animations)
      idle.png                   # idle animation spritesheet
      attack-melee.png           # attack animation spritesheet
      defend.png                 # defend animation spritesheet
      portrait.png               # sidebar portrait image
      swordsman/                 # advancement (nested directory)
        swordsman.toml
        sprite.toml
        idle.png
        ...
    mage/
      mage.toml
      sprite.toml
      idle.png
      ...
      red_mage/                  # advancement chain continues
        arch_mage/
          great_mage/            # max nesting depth: 4
```

### Key Conventions

- **Terrain images** are alongside their TOML in `data/terrain/`, named by `terrain_id`.
- **Unit assets** are co-located with their TOML in `data/units/` tree, matching the advancement hierarchy.
- Advancement chains are nested directories (parent → child mirrors `advances_to` in TOML).
- All filenames are lowercase with hyphens for multi-word names (e.g., `attack-melee.png`, `shallow_water.png`).
- Raw/intermediate sprite generation output goes in `sprites_raw/` (gitignored, regeneratable).

---

## 2. Terrain Tile Format

| Property | Value |
|----------|-------|
| Format | PNG with transparency |
| Source size | 256x256 or larger (scaled at runtime) |
| Shape | Rectangular (clipped to hex shape by renderer) or pre-masked to hex shape with transparent corners |
| Naming | `{terrain_id}.png` matching `id` field in `data/terrain/*.toml` |
| Color depth | 32-bit RGBA |

### Current Terrain Types

These terrain IDs must have corresponding PNGs to fully replace colored polygons:

| terrain_id | Name | Current Color |
|------------|------|---------------|
| flat | Flat/Grassland | #4a7c4e |
| forest | Forest | (from TOML) |
| hills | Hills | #8b7355 |
| mountains | Mountains | #6b6b6b |
| shallow_water | Shallow Water | (from TOML) |
| swamp_water | Swamp Water | (from TOML) |
| sand | Sand | (from TOML) |
| cave | Cave | (from TOML) |
| frozen | Frozen | (from TOML) |
| fungus | Fungus | (from TOML) |
| reef | Reef | (from TOML) |
| castle | Castle | (from TOML) |
| keep | Keep | (from TOML) |
| village | Village | (from TOML) |
| grassland | Grassland | (from TOML) |

### Rendering Behavior

- The renderer scales the terrain image to fit the hex cell (diameter = `HEX_RADIUS * 2`).
- The image is drawn centered on the hex center point.
- When no PNG exists for a terrain_id, the renderer falls back to the current colored polygon using the `color` field from the terrain's TOML definition.

---

## 3. sprite.toml Schema (Unit Metadata)

Each unit directory contains a `sprite.toml` file defining its visual properties.

```toml
# Required: matches def_id in data/units/
id = "spearman"

# ── Idle Animation (required) ────────────────────────────
[idle]
file = "idle.png"           # spritesheet or single image
frame_width = 256            # width of each frame in pixels
frame_height = 256           # height of each frame in pixels
frames = 6                   # number of frames (standard: 6 per animation)
fps = 4                      # frames per second for animation
anchor_x = 128               # x offset for centering (from left edge of frame)
anchor_y = 200               # y offset for ground point (from top of frame)

# ── Attack Animations (optional, per attack type) ────────
[attacks.melee]
file = "attack-melee.png"
frame_width = 256
frame_height = 256
frames = 6
fps = 8

[attacks.ranged]
file = "attack-ranged.png"
frame_width = 256
frame_height = 256
frames = 4
fps = 6

# ── Defend Animation (optional) ─────────────────────────
[defend]
file = "defend.png"
frame_width = 256
frame_height = 256
frames = 3
fps = 6

# ── Death Animation (optional) ──────────────────────────
[death]
file = "death.png"
frame_width = 256
frame_height = 256
frames = 4
fps = 6

# ── Portrait (optional) ─────────────────────────────────
[portrait]
file = "portrait.png"        # standalone image, not a spritesheet
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Must match `def_id` in `data/units/*.toml` |
| `[idle]` | table | yes | Default standing animation |
| `[idle].file` | string | yes | Filename relative to unit directory |
| `[idle].frame_width` | integer | yes | Width of each frame in pixels |
| `[idle].frame_height` | integer | yes | Height of each frame in pixels |
| `[idle].frames` | integer | yes | Number of frames (1 = static image) |
| `[idle].fps` | integer | yes | Playback speed |
| `[idle].anchor_x` | integer | no | Horizontal center point (default: frame_width/2) |
| `[idle].anchor_y` | integer | no | Vertical ground point (default: frame_height) |
| `[attacks.*]` | table | no | Per-attack-type animation (keyed by range: melee/ranged) |
| `[defend]` | table | no | Defense/hit reaction animation |
| `[death]` | table | no | Death animation (plays once, not looping) |
| `[portrait]` | table | no | Portrait for sidebar unit panel |

### Defaults

- If `anchor_x` is omitted, it defaults to `frame_width / 2` (horizontally centered).
- If `anchor_y` is omitted, it defaults to `frame_height` (bottom of frame is ground level).
- If `frames = 1`, the image is treated as a static sprite (no animation).
- If an animation section is omitted, the idle sprite is used as fallback.

---

## 4. Team Coloring

### Current Approach: Colored Underlay

Team coloring uses a faction-colored circle drawn behind the unit sprite:

1. Draw a filled circle at the hex center in the faction color (Blue: `{0.25, 0.42, 0.88}`, Red: `{0.80, 0.12, 0.12}`)
2. Apply alpha based on exhaustion state (0.4 if exhausted, 1.0 if fresh)
3. Draw the unit sprite centered on top of the circle

This approach works with any art style and requires no special preparation of sprite assets.

### Future: Tint Shader

A later enhancement may add palette-swapping or tint shaders for marked sprite regions. This would require sprites to designate team-color regions (e.g., via a color mask layer). This is explicitly out of scope for initial implementation.

---

## 5. Animation States

Units cycle through these animation states during gameplay:

| State | Trigger | Looping | Spritesheet |
|-------|---------|---------|-------------|
| idle | Default / no action | Yes | `idle.png` |
| attack-melee | Unit performs melee attack | No (play once) | `attack-melee.png` |
| attack-ranged | Unit performs ranged attack | No (play once) | `attack-ranged.png` |
| defend | Unit receives an attack | No (play once) | `defend.png` |
| death | Unit HP reaches 0 | No (play once) | `death.png` |

### Spritesheet Format

- Horizontal strip: all frames laid out left-to-right in a single row
- Each frame is `frame_width x frame_height` pixels
- Total image width = `frame_width * frames`
- Total image height = `frame_height`

```
+--------+--------+--------+--------+
| Frame 0| Frame 1| Frame 2| Frame 3|   <- idle.png (4 frames)
+--------+--------+--------+--------+
  256px    256px    256px    256px
```

### Animation Playback

- Idle: loops continuously at specified FPS
- Combat animations: play once, then return to idle
- Death: plays once, final frame persists until unit is removed
- Animation library: anim8 for Love2D (integrated in Phase 33)

---

## 6. Naming Conventions

### Terrain Files

| Convention | Example |
|------------|---------|
| Filename matches `id` in terrain TOML | `flat.png` for `id = "flat"` |
| Underscore for multi-word IDs | `shallow_water.png` for `id = "shallow_water"` |
| Always lowercase | `mountains.png`, not `Mountains.png` |

### Unit Directories

| Convention | Example |
|------------|---------|
| Directory matches `id` in unit TOML | `spearman/` for `id = "spearman"` |
| Underscore for multi-word IDs | `elvish_archer/` for `id = "elvish_archer"` |
| Always lowercase | `dark_adept/`, not `DarkAdept/` |

### Animation Files

| Convention | Example |
|------------|---------|
| `idle.png` | Required default sprite |
| `attack-{range}.png` | `attack-melee.png`, `attack-ranged.png` |
| `defend.png` | Defense/hit reaction |
| `death.png` | Death animation |
| `portrait.png` | Sidebar portrait |
| Hyphens between words | `attack-melee.png`, not `attack_melee.png` |

---

## 7. Pipeline Workflow

### Current Pipeline (Gemini 2.0 Flash)

Unit sprites are generated one pose at a time using `tools/generate_sprites.py`:

```
1. Generate       →  Gemini 2.0 Flash API produces single-pose PNG with reference image
2. Validate       →  PIL/Pillow checks: multi-blob (BFS flood-fill), size (<30KB), edge (2px border)
3. Retry          →  Up to 3 retries per pose if validation fails
4. Place          →  Output directly to data/units/<name>/ directory
5. Metadata       →  sprite.toml created/updated automatically
6. Flip check     →  Manual direction flip if needed: `magick <file>.png -flop <file>.png`
```

Portraits are generated separately (painterly style, black background, 128x128, 100KB limit).

Death animations are not generated — they are derived at render time (idle sprite tilts 0° → 90° with fade).

### Generation Tools

| Tool | Purpose |
|------|---------|
| `tools/generate_sprites.py` | Unit sprite generation (single pose per API call) |
| `tools/generate_terrain.py` | Terrain tile generation (`--terrain`, `--all`, `--preview`, `--list`) |
| `tools/review_sprites.py` | Sprite validation and review |

### Terrain Tile Generation

Terrain tiles are 256x256 RGB PNGs, center-cropped to square, LANCZOS resized, no background
removal (full coverage required). Generated via `tools/generate_terrain.py` using Gemini API.

All 15 terrain tiles and all unit sprites have been regenerated in HD-2D style.

### Quality Checklist

- [ ] PNG format with transparency
- [ ] Correct dimensions (consistent frame_width x frame_height)
- [ ] Centered subject (anchor point alignment)
- [ ] Consistent art style with existing assets
- [ ] No artifacts at sprite edges
- [ ] sprite.toml metadata matches actual file dimensions and frame count
- [ ] Renders correctly at game scale (HEX_RADIUS = 96px)

---

## Fallback Behavior

The rendering system supports graceful fallback at every level:

| Asset Missing | Fallback |
|---------------|----------|
| Terrain PNG | Colored hex polygon (using `color` from terrain TOML) |
| Unit idle.png | Colored circle with type abbreviation (current rendering) |
| Unit portrait | Text-only unit panel (current rendering) |
| sprite.toml | Treat idle.png as single static frame |
| Attack animation | Use idle sprite during combat |
| Death animation | Instant removal (current behavior) |

This means the game is fully playable at all stages of art production. Assets can be added incrementally, one terrain type or one unit at a time.
