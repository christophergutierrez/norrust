#!/usr/bin/env python3
"""Convert a Wesnoth .map file to a NorRust board.toml.

Usage:
    python tools/convert_wesnoth_map.py <map_file> [options]

Examples:
    # Convert with auto-detected dimensions
    python tools/convert_wesnoth_map.py ~/git_home/wesnoth/data/campaigns/Two_Brothers/maps/01_Rooting_Out_a_Mage.map

    # Set win conditions
    python tools/convert_wesnoth_map.py map.map --max-turns 18 --objective 5,10

    # Crop to a region (col_start,row_start,width,height)
    python tools/convert_wesnoth_map.py map.map --crop 25,15,16,12

    # Output to specific file
    python tools/convert_wesnoth_map.py map.map -o scenarios/new/board.toml

    # Preview terrain mapping without writing
    python tools/convert_wesnoth_map.py map.map --preview

    # Show unmapped terrain codes
    python tools/convert_wesnoth_map.py map.map --show-unmapped
"""

import argparse
import re
import sys
from pathlib import Path
from collections import Counter

# Wesnoth terrain code → NorRust terrain ID
# Base terrain is the part before ^, overlay is after ^
# We map based on base terrain first, then check overlays for villages/forests
TERRAIN_MAP = {
    # --- Base terrains ---
    # Grassland variants
    "Gs":  "flat",
    "Gd":  "flat",
    "Gg":  "flat",
    "Gll": "flat",
    "Gt":  "flat",      # tundra
    "Rb":  "flat",      # farmland
    # Roads / paths
    "Re":  "flat",
    "Rp":  "flat",
    "Rr":  "flat",
    "Rd":  "flat",
    # Hills
    "Hh":  "hills",
    "Hhd": "hills",
    "Ha":  "hills",     # arid hills
    # Mountains
    "Mm":  "mountains",
    "Md":  "mountains",
    "Ms":  "mountains",
    # Water
    "Ww":  "shallow_water",
    "Wwf": "shallow_water",  # ford
    "Wwg": "shallow_water",  # swamp edge
    "Wwt": "shallow_water",
    "Wo":  "shallow_water",  # deep water (no deep_water terrain in norrust)
    # Swamp
    "Ss":  "swamp_water",
    "Sm":  "swamp_water",
    "Ds":  "swamp_water",    # dark swamp
    # Sand / desert
    "Dd":  "sand",
    "Ds":  "swamp_water",
    "Dr":  "sand",
    # Frozen
    "Ai":  "frozen",
    "Ha":  "frozen",
    # Cave
    "Uu":  "cave",
    "Ur":  "cave",
    # Fungus
    "Uf":  "fungus",
    "Uu^Uf": "fungus",
    # Castle parts
    "Ce":  "castle",
    "Chr": "castle",
    "Chw": "castle",
    "Cme": "castle",
    "Cvr": "castle",
    "Cv":  "castle",
    "Co":  "castle",
    # Keeps
    "Ke":  "keep",
    "Kh":  "keep",
    "Khr": "keep",
    "Kvr": "keep",
    "Kv":  "keep",
    "Ko":  "keep",
    # Reef
    "Wwr": "reef",
}

# Overlay patterns that override base terrain
OVERLAY_MAP = {
    "Vh":   "village",   # human village
    "Vhh":  "village",   # hill village
    "Vhcr": "village",   # ruined village
    "Vl":   "village",   # log village
    "Vc":   "village",   # cave village
    "Vct":  "village",   # tent village
    "Vca":  "village",   # adobe village
    "Vha":  "village",
    "Vhc":  "village",
    "Ve":   "village",
    "Gvs":  "village",   # village on ground
    # Forest overlays
    "Fp":   "forest",    # pine forest
    "Fms":  "forest",    # mixed forest
    "Fds":  "forest",    # deciduous forest
    "Ftp":  "forest",    # tropical
    "Ftd":  "forest",    # tropical deciduous
    "Fm":   "forest",
    "Fd":   "forest",
}


def parse_terrain_code(code):
    """Parse a Wesnoth terrain code like '2 Khr' or 'Gs^Fms' into components.

    Returns (base, overlays, side_num) where:
    - base: the base terrain code (e.g., 'Khr')
    - overlays: list of overlay codes (e.g., ['Fms'])
    - side_num: starting position number if present (e.g., 2), else None
    """
    code = code.strip()
    side_num = None

    # Check for side number prefix like "2 Khr" or "1 Ke"
    m = re.match(r"^(\d+)\s+(.+)$", code)
    if m:
        side_num = int(m.group(1))
        code = m.group(2)

    parts = code.split("^")
    base = parts[0]
    overlays = parts[1:] if len(parts) > 1 else []
    return base, overlays, side_num


def map_terrain(code, unmapped_codes=None):
    """Map a Wesnoth terrain code to a NorRust terrain ID.

    Priority: overlay village > overlay forest > base terrain > fallback.
    """
    base, overlays, side_num = parse_terrain_code(code)

    # Keeps always map regardless of overlays
    if base in TERRAIN_MAP and TERRAIN_MAP[base] == "keep":
        return "keep", side_num

    # Check overlays first (village overrides forest overrides base)
    for overlay in overlays:
        # Strip common decorative prefixes
        clean = overlay.lstrip("E")  # Embellishments like ^Efm, ^Eff, ^Es, ^Edb
        if clean in OVERLAY_MAP:
            return OVERLAY_MAP[clean], side_num
        if overlay in OVERLAY_MAP:
            return OVERLAY_MAP[overlay], side_num

    # Check full code (base^overlay combined)
    full = f"{base}^{overlays[0]}" if overlays else base
    if full in TERRAIN_MAP:
        return TERRAIN_MAP[full], side_num

    # Check base terrain
    if base in TERRAIN_MAP:
        return TERRAIN_MAP[base], side_num

    # Bridge codes — treat as shallow_water
    for overlay in overlays:
        if overlay.startswith("Bw") or overlay.startswith("Bs"):
            return "shallow_water", side_num

    # Unmapped — track and return flat as fallback
    if unmapped_codes is not None:
        unmapped_codes[code] = unmapped_codes.get(code, 0) + 1
    return "flat", side_num


def parse_map_file(path):
    """Parse a Wesnoth .map file into a 2D grid of terrain codes.

    Returns list of rows, each row is a list of terrain code strings.
    """
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # Skip WML comment lines sometimes found in maps
            if line.startswith("#"):
                continue
            cells = [c.strip() for c in line.split(",") if c.strip()]
            if cells:
                rows.append(cells)
    return rows


def crop_grid(grid, col_start, row_start, width, height):
    """Crop a 2D grid to a rectangular region."""
    result = []
    for r in range(row_start, min(row_start + height, len(grid))):
        row = grid[r][col_start:col_start + width]
        # Pad if needed
        while len(row) < width:
            row.append("Gs")
        result.append(row)
    # Pad rows if needed
    while len(result) < height:
        result.append(["Gs"] * width)
    return result


def convert_map(grid, unmapped_codes=None):
    """Convert a 2D grid of Wesnoth terrain codes to NorRust terrain IDs.

    Returns (terrain_ids, side_positions) where:
    - terrain_ids: 2D list of NorRust terrain ID strings
    - side_positions: dict of {side_num: (col, row)}
    """
    terrain_ids = []
    side_positions = {}

    for row_idx, row in enumerate(grid):
        terrain_row = []
        for col_idx, code in enumerate(row):
            terrain_id, side_num = map_terrain(code, unmapped_codes)
            terrain_row.append(terrain_id)
            if side_num is not None:
                side_positions[side_num] = (col_idx, row_idx)
        terrain_ids.append(terrain_row)

    return terrain_ids, side_positions


def write_board_toml(terrain_ids, width, height, output_path,
                     max_turns=None, objective_col=None, objective_row=None,
                     comment=None):
    """Write a NorRust board.toml file."""
    lines = []
    if comment:
        for c in comment.split("\n"):
            lines.append(f"# {c}")
        lines.append("")

    lines.append(f"width = {width}")
    lines.append(f"height = {height}")

    if objective_col is not None and objective_row is not None:
        lines.append(f"objective_col = {objective_col}")
        lines.append(f"objective_row = {objective_row}")

    if max_turns is not None:
        lines.append(f"max_turns = {max_turns}")

    lines.append("")
    lines.append("tiles = [")

    for row_idx, row in enumerate(terrain_ids):
        # Format with padding for alignment
        quoted = [f'"{t}"' for t in row]
        line = "  " + ", ".join(quoted) + ","
        lines.append(line)

    lines.append("]")
    lines.append("")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    return output_path


def preview_terrain(terrain_ids, side_positions):
    """Print a compact visual preview of the map."""
    SYMBOLS = {
        "flat": ".",  "forest": "F",  "hills": "h",  "mountains": "M",
        "village": "V", "castle": "C", "keep": "K", "shallow_water": "~",
        "swamp_water": "s", "sand": "d", "frozen": "i", "cave": "u",
        "fungus": "f", "reef": "r", "grassland": ".",
    }
    print(f"\nMap preview ({len(terrain_ids[0])}x{len(terrain_ids)}):")
    print("  " + "".join(str(i % 10) for i in range(len(terrain_ids[0]))))
    for row_idx, row in enumerate(terrain_ids):
        chars = []
        for col_idx, t in enumerate(row):
            # Check if this is a side start position
            for side, (sc, sr) in side_positions.items():
                if sc == col_idx and sr == row_idx:
                    chars.append(str(side))
                    break
            else:
                chars.append(SYMBOLS.get(t, "?"))
        print(f"{row_idx:2d} " + "".join(chars))


def main():
    parser = argparse.ArgumentParser(
        description="Convert a Wesnoth .map file to NorRust board.toml",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("map_file", help="Path to Wesnoth .map file")
    parser.add_argument("-o", "--output", help="Output board.toml path (default: stdout summary)")
    parser.add_argument("--max-turns", type=int, help="Turn limit for the scenario")
    parser.add_argument("--objective", help="Objective hex as col,row (e.g., 5,10)")
    parser.add_argument("--crop", help="Crop region as col,row,width,height (e.g., 25,15,16,12)")
    parser.add_argument("--preview", action="store_true", help="Show visual map preview")
    parser.add_argument("--show-unmapped", action="store_true", help="Show unmapped terrain codes")
    parser.add_argument("--comment", help="Comment to add at top of output file")

    args = parser.parse_args()

    map_path = Path(args.map_file)
    if not map_path.exists():
        print(f"Error: {map_path} not found", file=sys.stderr)
        sys.exit(1)

    # Parse the map
    grid = parse_map_file(map_path)
    if not grid:
        print("Error: empty map file", file=sys.stderr)
        sys.exit(1)

    # Crop if requested
    if args.crop:
        parts = [int(x) for x in args.crop.split(",")]
        if len(parts) != 4:
            print("Error: --crop requires col,row,width,height", file=sys.stderr)
            sys.exit(1)
        grid = crop_grid(grid, *parts)

    height = len(grid)
    width = max(len(row) for row in grid)

    # Pad rows to consistent width
    for row in grid:
        while len(row) < width:
            row.append("Gs")

    # Convert terrain
    unmapped = {} if args.show_unmapped else None
    terrain_ids, side_positions = convert_map(grid, unmapped)

    # Stats
    terrain_counts = Counter()
    for row in terrain_ids:
        for t in row:
            terrain_counts[t] += 1

    print(f"Map: {map_path.name}")
    print(f"Dimensions: {width} x {height} ({width * height} hexes)")
    print(f"Side positions: {side_positions}")
    print(f"Terrain distribution:")
    for terrain, count in terrain_counts.most_common():
        pct = 100 * count / (width * height)
        print(f"  {terrain:20s} {count:4d} ({pct:.0f}%)")

    if unmapped:
        print(f"\nUnmapped terrain codes ({len(unmapped)} unique):")
        for code, count in sorted(unmapped.items(), key=lambda x: -x[1]):
            print(f"  {code:20s} {count:4d}")

    if args.preview:
        preview_terrain(terrain_ids, side_positions)

    # Parse objective
    obj_col, obj_row = None, None
    if args.objective:
        obj_col, obj_row = [int(x) for x in args.objective.split(",")]

    # Write output
    if args.output:
        comment = args.comment or f"Converted from {map_path.name}"
        out = write_board_toml(
            terrain_ids, width, height, args.output,
            max_turns=args.max_turns,
            objective_col=obj_col, objective_row=obj_row,
            comment=comment,
        )
        print(f"\nWrote {out}")
    elif not args.preview:
        print("\nUse -o <path> to write board.toml, or --preview to see the map")


if __name__ == "__main__":
    main()
