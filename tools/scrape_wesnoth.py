#!/usr/bin/env python3
"""
scrape_wesnoth.py — One-shot Wesnoth WML → norrust TOML scraper.

Reads:
  /home/chris/git_home/wesnoth/data/core/units.cfg   (movement types)
  /home/chris/git_home/wesnoth/data/core/units/**    (unit definitions)

Outputs:
  /home/chris/git_home/norrust/data/units/{safe_id}.toml
  /home/chris/git_home/norrust/data/terrain/{terrain_id}.toml
"""

import re
import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
WESNOTH_CORE   = Path("/home/chris/git_home/wesnoth/data/core")
UNITS_CFG      = WESNOTH_CORE / "units.cfg"
UNITS_DIR      = WESNOTH_CORE / "units"
OUT_UNITS      = Path("/home/chris/git_home/norrust/data/units")
OUT_TERRAIN    = Path("/home/chris/git_home/norrust/data/terrain")

# ── Helpers ────────────────────────────────────────────────────────────────────
def parse_value(raw: str) -> str:
    """Strip WML translation markers and quotes: _ "foo" → foo, "foo" → foo.

    Uses non-greedy first-quote match so inline WML comments (# ...) after
    the closing quote are ignored.
    """
    v = raw.strip()
    # Match _ "content" or "content" — stop at first closing quote
    m = re.match(r'^_?\s*"([^"]*)"', v)
    if m:
        return m.group(1)
    # Unquoted value — strip inline comment
    if '#' in v:
        v = v[:v.index('#')].rstrip()
    return v

def safe_id(unit_id: str) -> str:
    """Convert Wesnoth unit ID to a safe filename (no spaces, lowercase)."""
    return re.sub(r"[^a-z0-9_]", "", unit_id.lower().replace(" ", "_").replace("-", "_").replace("'", ""))

def toml_str_list(lst: list) -> str:
    if not lst:
        return "[]"
    return "[" + ", ".join(f'"{x}"' for x in lst) + "]"

# ── Resistance conversion ──────────────────────────────────────────────────────
# Wesnoth: 100 = normal, 90 = resistant (less damage), 120 = weak (more damage)
# Our formula: damage * (100 + our_val) / 100
# So our_val = wesnoth_val - 100
# Wesnoth 100 → 0, Wesnoth 90 → -10, Wesnoth 120 → +20
def convert_resistance(wesnoth_val: int) -> int:
    return wesnoth_val - 100

# ── Step 1: Parse movement types from units.cfg ────────────────────────────────
def parse_movetypes(path: Path) -> dict:
    """
    Returns dict: {movetype_name: {
        'movement_costs': {terrain: int},
        'defense': {terrain: int},
        'resistance': {attack_type: int}  # already converted to our format
    }}
    """
    movetypes = {}
    current = None
    section = None   # 'movement_costs' | 'defense' | 'resistance' | None

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            if stripped == "[movetype]":
                current = {"movement_costs": {}, "defense": {}, "resistance": {}}
                section = None
                continue
            if stripped == "[/movetype]":
                if current and "name" in current:
                    movetypes[current["name"]] = {
                        "movement_costs": current["movement_costs"],
                        "defense": current["defense"],
                        "resistance": current["resistance"],
                    }
                current = None
                section = None
                continue

            if current is None:
                continue

            if stripped == "[movement_costs]":
                section = "movement_costs"
            elif stripped == "[/movement_costs]":
                section = None
            elif stripped == "[defense]":
                section = "defense"
            elif stripped == "[/defense]":
                section = None
            elif stripped == "[resistance]":
                section = "resistance"
            elif stripped == "[/resistance]":
                section = None
            elif "=" in stripped and not stripped.startswith("["):
                key, _, val = stripped.partition("=")
                key = key.strip()
                val = val.strip()
                if section == "movement_costs":
                    try:
                        current["movement_costs"][key] = int(val)
                    except ValueError:
                        pass
                elif section == "defense":
                    try:
                        # Wesnoth sometimes writes negative defense (cap indicator)
                        # Store absolute value — defense % can't be negative
                        current["defense"][key] = abs(int(val))
                    except ValueError:
                        pass
                elif section == "resistance":
                    try:
                        current["resistance"][key] = convert_resistance(int(val))
                    except ValueError:
                        pass
                elif section is None and key == "name":
                    current["name"] = val

    return movetypes


# ── Step 2: Parse unit_type blocks from a single .cfg file ────────────────────
def parse_units_from_file(path: Path, movetypes: dict) -> list:
    """
    Returns list of unit dicts ready for TOML serialization.
    Skips units that are invalid/templated/have no attacks.
    """
    units = []
    u = None          # current unit being built
    unit_depth = 0    # nesting depth inside [unit_type]
    atk = None        # current [attack] being built
    in_resistance = False   # unit-level [resistance] block

    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # ── Unit type boundaries ───────────────────────────────────────────
            if stripped == "[unit_type]":
                u = {
                    "id": "", "name": "", "race": "", "max_hp": 0,
                    "movement": 0, "experience": 0, "level": 1,
                    "alignment": "liminal", "advances_to": [],
                    "cost": 0, "usage": "", "abilities": [],
                    "movement_type": "",
                    "attacks": [],
                    "resistance_overrides": {},  # unit-level overrides
                }
                unit_depth = 0
                atk = None
                in_resistance = False
                continue

            if stripped == "[/unit_type]":
                if u:
                    units.append(u)
                u = None
                unit_depth = 0
                atk = None
                in_resistance = False
                continue

            if u is None:
                continue

            # ── Inside unit_type ───────────────────────────────────────────────
            if stripped == "[attack]" and unit_depth == 0:
                atk = {"id": "", "name": "", "damage": 0, "strikes": 0,
                       "attack_type": "", "range": ""}
                unit_depth = 1
                continue

            if stripped == "[/attack]" and unit_depth == 1 and atk is not None:
                u["attacks"].append(atk)
                atk = None
                unit_depth = 0
                continue

            if stripped == "[resistance]" and unit_depth == 0:
                in_resistance = True
                unit_depth = 1
                continue

            if stripped == "[/resistance]" and unit_depth == 1 and in_resistance:
                in_resistance = False
                unit_depth = 0
                continue

            # Track nesting depth for other blocks we want to skip
            if stripped.startswith("[") and not stripped.startswith("[/") and unit_depth == 0:
                unit_depth = 1
                continue
            if stripped.startswith("[/") and unit_depth == 1 and atk is None and not in_resistance:
                unit_depth = 0
                continue
            if stripped.startswith("[") and not stripped.startswith("[/") and unit_depth >= 1:
                unit_depth += 1
                continue
            if stripped.startswith("[/") and unit_depth > 1:
                unit_depth -= 1
                continue

            # ── Parse key=value ────────────────────────────────────────────────
            if "=" not in stripped or stripped.startswith("["):
                continue
            key, _, raw_val = stripped.partition("=")
            key = key.strip()
            val = parse_value(raw_val)

            # Inside attack block
            if atk is not None and unit_depth == 1:
                if key == "name":
                    atk["id"] = val
                elif key == "description":
                    atk["name"] = val
                elif key == "damage":
                    try:
                        atk["damage"] = int(val)
                    except ValueError:
                        pass
                elif key == "number":
                    try:
                        atk["strikes"] = int(val)
                    except ValueError:
                        pass
                elif key == "type":
                    atk["attack_type"] = val
                elif key == "range":
                    atk["range"] = val
                continue

            # Inside unit-level resistance override
            if in_resistance and unit_depth == 1:
                try:
                    u["resistance_overrides"][key] = convert_resistance(int(val))
                except ValueError:
                    pass
                continue

            # Unit-level fields (depth == 0)
            if unit_depth == 0:
                if key == "id":
                    u["id"] = val
                elif key == "name":
                    u["name"] = val
                elif key == "race":
                    u["race"] = val
                elif key == "hitpoints":
                    try:
                        u["max_hp"] = int(val)
                    except ValueError:
                        pass
                elif key == "movement":
                    try:
                        u["movement"] = int(val)
                    except ValueError:
                        pass
                elif key == "experience":
                    try:
                        u["experience"] = int(val)
                    except ValueError:
                        pass
                elif key == "level":
                    try:
                        u["level"] = int(val)
                    except ValueError:
                        pass
                elif key == "alignment":
                    u["alignment"] = val
                elif key == "advances_to":
                    parts = [p.strip() for p in val.split(",")]
                    u["advances_to"] = [p for p in parts if p and p.lower() != "null" and p.lower() != "none"]
                elif key == "cost":
                    try:
                        u["cost"] = int(val)
                    except ValueError:
                        pass
                elif key == "usage":
                    u["usage"] = val.strip()
                elif key == "abilities_list":
                    parts = [p.strip() for p in val.split(",")]
                    u["abilities"] = [p for p in parts if p]
                elif key == "movement_type":
                    u["movement_type"] = val

    return units


# ── Step 3: Filter and resolve units ──────────────────────────────────────────
def resolve_unit(u: dict, movetypes: dict) -> dict | None:
    """
    Validate and resolve a unit dict. Returns None if unit should be skipped.
    """
    mt_name = u["movement_type"]

    # Skip templated or missing movement types
    if not mt_name or "{" in mt_name:
        return None

    # Skip if movement type not in our table
    if mt_name not in movetypes:
        return None

    # Skip units with no attacks (transport/non-combat units)
    if not u["attacks"]:
        return None

    # Skip units with missing essential fields
    if not u["id"] or u["max_hp"] == 0:
        return None

    mt = movetypes[mt_name]

    # Merge resistances: movetype base + unit overrides
    resistances = dict(mt["resistance"])
    resistances.update(u["resistance_overrides"])

    # Ensure attack names are filled (fallback to id if description missing)
    for atk in u["attacks"]:
        if not atk["name"]:
            atk["name"] = atk["id"]

    return {
        "id": u["id"],
        "name": u["name"] or u["id"],
        "race": u["race"],
        "level": u["level"],
        "experience": u["experience"],
        "max_hp": u["max_hp"],
        "movement": u["movement"],
        "alignment": u["alignment"],
        "cost": u["cost"],
        "usage": u["usage"],
        "abilities": u["abilities"],
        "advances_to": u["advances_to"],
        "attacks": u["attacks"],
        "resistances": resistances,
        "movement_costs": dict(mt["movement_costs"]),
        "defense": dict(mt["defense"]),
    }


# ── Step 4: Serialize unit to TOML string ─────────────────────────────────────
def unit_to_toml(u: dict) -> str:
    lines = []
    lines.append(f'id = "{u["id"]}"')
    lines.append(f'name = "{u["name"]}"')
    lines.append(f'race = "{u["race"]}"')
    lines.append(f'level = {u["level"]}')
    lines.append(f'experience = {u["experience"]}')
    lines.append(f'max_hp = {u["max_hp"]}')
    lines.append(f'movement = {u["movement"]}')
    lines.append(f'alignment = "{u["alignment"]}"')
    lines.append(f'cost = {u["cost"]}')
    lines.append(f'usage = "{u["usage"]}"')
    lines.append(f'abilities = {toml_str_list(u["abilities"])}')
    lines.append(f'advances_to = {toml_str_list(u["advances_to"])}')
    lines.append("")

    for atk in u["attacks"]:
        lines.append("[[attacks]]")
        lines.append(f'id = "{atk["id"]}"')
        lines.append(f'name = "{atk["name"]}"')
        lines.append(f'damage = {atk["damage"]}')
        lines.append(f'strikes = {atk["strikes"]}')
        lines.append(f'attack_type = "{atk["attack_type"]}"')
        lines.append(f'range = "{atk["range"]}"')
        lines.append(f'specials = []')
        lines.append("")

    lines.append("[resistances]")
    for k, v in sorted(u["resistances"].items()):
        lines.append(f"{k} = {v}")
    lines.append("")

    lines.append("[movement_costs]")
    for k, v in sorted(u["movement_costs"].items()):
        lines.append(f"{k} = {v}")
    lines.append("")

    lines.append("[defense]")
    for k, v in sorted(u["defense"].items()):
        lines.append(f"{k} = {v}")
    lines.append("")

    return "\n".join(lines)


# ── Step 5: Write terrain TOMLs ───────────────────────────────────────────────
TERRAIN_NAMES = {
    "flat": "Flat",
    "hills": "Hills",
    "mountains": "Mountains",
    "forest": "Forest",
    "village": "Village",
    "castle": "Castle",
    "cave": "Cave",
    "frozen": "Frozen",
    "fungus": "Fungus",
    "sand": "Sand",
    "shallow_water": "Shallow Water",
    "reef": "Reef",
    "swamp_water": "Swamp",
    "deep_sea": "Deep Sea",
    "coastal_reef": "Coastal Reef",
}

def write_terrain_tomls(movetypes: dict):
    """Generate terrain TOMLs for all terrain codes in movement types, skip existing."""
    # Collect all terrain codes
    terrains = set()
    smallfoot = movetypes.get("smallfoot", {})
    for code in smallfoot.get("movement_costs", {}):
        terrains.add(code)

    written = 0
    for terrain_id in sorted(terrains):
        out_path = OUT_TERRAIN / f"{terrain_id}.toml"
        if out_path.exists():
            continue

        name = TERRAIN_NAMES.get(terrain_id, terrain_id.replace("_", " ").title())
        symbol = terrain_id[0]
        defense = smallfoot["defense"].get(terrain_id, 60)
        cost = smallfoot["movement_costs"].get(terrain_id, 1)

        content = (
            f'id = "{terrain_id}"\n'
            f'name = "{name}"\n'
            f'symbol = "{symbol}"\n'
            f'default_defense = {defense}\n'
            f'default_movement_cost = {cost}\n'
            f'healing = 0\n'
        )
        out_path.write_text(content, encoding="utf-8")
        written += 1

    return written


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    OUT_UNITS.mkdir(parents=True, exist_ok=True)
    OUT_TERRAIN.mkdir(parents=True, exist_ok=True)

    print("Parsing movement types...")
    movetypes = parse_movetypes(UNITS_CFG)
    print(f"  Found {len(movetypes)} movement types: {sorted(movetypes.keys())}")

    print("\nParsing unit files...")
    all_units_raw = []
    cfg_files = sorted(UNITS_DIR.rglob("*.cfg"))
    for cfg_path in cfg_files:
        raw = parse_units_from_file(cfg_path, movetypes)
        all_units_raw.extend(raw)

    print(f"  Parsed {len(all_units_raw)} [unit_type] blocks from {len(cfg_files)} files")

    print("\nResolving and filtering units...")
    resolved = []
    for u in all_units_raw:
        r = resolve_unit(u, movetypes)
        if r:
            resolved.append(r)

    skipped_total = len(all_units_raw) - len(resolved)
    print(f"  Accepted: {len(resolved)} | Skipped: {skipped_total} (templated/no-attacks/missing fields)")

    print("\nWriting unit TOMLs...")
    written = 0
    skipped_existing = 0
    seen_ids = set()

    for u in resolved:
        sid = safe_id(u["id"])
        if not sid:
            continue

        # Deduplicate (same unit may appear in multiple files)
        if u["id"] in seen_ids:
            continue
        seen_ids.add(u["id"])

        out_path = OUT_UNITS / f"{sid}.toml"
        if out_path.exists():
            skipped_existing += 1
            continue

        out_path.write_text(unit_to_toml(u), encoding="utf-8")
        written += 1

    print(f"  Units written: {written}")
    print(f"  Units skipped (file already exists): {skipped_existing}")

    print("\nWriting terrain TOMLs...")
    terrain_written = write_terrain_tomls(movetypes)
    print(f"  Terrain files written: {terrain_written}")

    print(f"\nDone. data/units/ now contains {len(list(OUT_UNITS.iterdir()))} files.")


if __name__ == "__main__":
    main()
