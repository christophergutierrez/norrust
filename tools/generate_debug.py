#!/usr/bin/env python3
"""Generate debug game data from config overrides.

Reads debug/debug_config.toml, copies real game data into debug/data/,
and patches specified fields (experience, max_hp, cost, etc.) for rapid testing.

Usage:
    python3 tools/generate_debug.py          # from project root
    python3 tools/generate_debug.py --clean  # remove debug/data/ first
"""

import os
import re
import shutil
import sys
import tomllib
from pathlib import Path

# Project root = parent of tools/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "debug" / "debug_config.toml"
DATA_SRC = PROJECT_ROOT / "data"
DATA_DST = PROJECT_ROOT / "debug" / "data"

# Fields we know how to patch in unit TOMLs (top-level simple key = value)
UNIT_PATCHABLE = {"experience", "max_hp", "movement", "cost", "level", "alignment"}

# Fields we know how to patch in faction TOMLs
FACTION_PATCHABLE = {"starting_gold"}


def load_config():
    """Load and return the debug config dict."""
    if not CONFIG_PATH.exists():
        print(f"Error: Config not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def patch_toml_lines(lines, patches):
    """Patch simple top-level key=value fields in TOML lines.

    Only patches lines matching `^key = value` where key is in patches dict.
    Preserves all other lines (including [[attacks]], [resistances], etc.) unchanged.

    Returns (patched_lines, patched_count).
    """
    patched = []
    count = 0
    in_section = False  # Track if we're inside a [section] or [[array]]

    for line in lines:
        stripped = line.strip()

        # Track sections — fields inside [resistances], [[attacks]], etc. are NOT patched
        if stripped.startswith("["):
            in_section = True
            patched.append(line)
            continue

        # Blank line after a section can reset to top-level (before next section)
        # But actually in TOML, once you're in a section, subsequent bare keys
        # belong to that section. Top-level fields come BEFORE any [section].
        # So we only patch when NOT in a section.
        if not in_section:
            matched = False
            for field, value in patches.items():
                pattern = rf"^{re.escape(field)}\s*="
                if re.match(pattern, stripped):
                    # Preserve original formatting: find the = and replace after it
                    eq_idx = line.index("=")
                    if isinstance(value, str):
                        patched.append(f"{line[:eq_idx + 1]} \"{value}\"\n")
                    else:
                        patched.append(f"{line[:eq_idx + 1]} {value}\n")
                    count += 1
                    matched = True
                    break
            if not matched:
                patched.append(line)
        else:
            patched.append(line)

    return patched, count


def extract_unit_id(lines):
    """Extract the id field value from unit TOML lines."""
    for line in lines:
        m = re.match(r'^id\s*=\s*"([^"]+)"', line.strip())
        if m:
            return m.group(1)
    return None


def generate_units(config):
    """Copy and patch unit TOMLs from data/units/ to debug/data/units/."""
    defaults = config.get("defaults", {})
    overrides = config.get("overrides", {}).get("units", {})

    # Build default patches (only UNIT_PATCHABLE fields that are set)
    default_patches = {k: v for k, v in defaults.items() if k in UNIT_PATCHABLE}

    units_src = DATA_SRC / "units"
    units_dst = DATA_DST / "units"

    total_units = 0
    total_patched = 0

    for root, dirs, files in os.walk(units_src):
        rel = Path(root).relative_to(units_src)
        dst_dir = units_dst / rel
        dst_dir.mkdir(parents=True, exist_ok=True)

        for fname in files:
            if not fname.endswith(".toml"):
                continue

            src_file = Path(root) / fname
            dst_file = dst_dir / fname

            with open(src_file, "r") as f:
                lines = f.readlines()

            # Determine patches: defaults + per-unit overrides
            unit_id = extract_unit_id(lines)
            patches = dict(default_patches)  # copy defaults

            if unit_id and unit_id in overrides:
                unit_overrides = overrides[unit_id]
                for k, v in unit_overrides.items():
                    if k in UNIT_PATCHABLE:
                        patches[k] = v

            if patches:
                patched_lines, count = patch_toml_lines(lines, patches)
                with open(dst_file, "w") as f:
                    f.writelines(patched_lines)
                if count > 0:
                    total_patched += 1
            else:
                # No patches — straight copy
                shutil.copy2(src_file, dst_file)

            total_units += 1

    return total_units, total_patched


def generate_factions(config):
    """Copy and patch faction TOMLs."""
    faction_defaults = config.get("defaults", {}).get("faction", {})
    patches = {k: v for k, v in faction_defaults.items() if k in FACTION_PATCHABLE}

    factions_src = DATA_SRC / "factions"
    factions_dst = DATA_DST / "factions"
    factions_dst.mkdir(parents=True, exist_ok=True)

    count = 0
    for fname in os.listdir(factions_src):
        if not fname.endswith(".toml"):
            continue
        src_file = factions_src / fname
        dst_file = factions_dst / fname

        if patches:
            with open(src_file, "r") as f:
                lines = f.readlines()
            patched_lines, _ = patch_toml_lines(lines, patches)
            with open(dst_file, "w") as f:
                f.writelines(patched_lines)
        else:
            shutil.copy2(src_file, dst_file)
        count += 1

    return count


def copy_dir(name):
    """Copy a data subdirectory as-is (no patching)."""
    src = DATA_SRC / name
    dst = DATA_DST / name
    if src.exists():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return sum(1 for f in dst.rglob("*.toml"))
    return 0


def main():
    if "--clean" in sys.argv:
        if DATA_DST.exists():
            shutil.rmtree(DATA_DST)
            print(f"Cleaned {DATA_DST}")

    if not DATA_SRC.exists():
        print(f"Error: Source data not found at {DATA_SRC}")
        sys.exit(1)

    config = load_config()

    # Clean output
    if DATA_DST.exists():
        shutil.rmtree(DATA_DST)
    DATA_DST.mkdir(parents=True)

    # Generate each data type
    num_units, num_patched = generate_units(config)
    num_factions = generate_factions(config)
    num_terrain = copy_dir("terrain")
    num_recruit = copy_dir("recruit_groups")

    # Summary
    print(f"Debug data generated in {DATA_DST.relative_to(PROJECT_ROOT)}/")
    print(f"  Units:          {num_units} ({num_patched} patched)")
    print(f"  Factions:       {num_factions}")
    print(f"  Terrain:        {num_terrain}")
    print(f"  Recruit groups: {num_recruit}")

    # Show what defaults were applied
    defaults = config.get("defaults", {})
    unit_patches = {k: v for k, v in defaults.items() if k in UNIT_PATCHABLE}
    faction_patches = defaults.get("faction", {})
    if unit_patches:
        print(f"  Unit defaults:  {unit_patches}")
    if faction_patches:
        print(f"  Faction defaults: {faction_patches}")


if __name__ == "__main__":
    main()
