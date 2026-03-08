#!/usr/bin/env python3
"""process_spritesheet.py — Slice a 6x5 sprite sheet into individual animation strips.

Takes a single sprite sheet image (6 columns, 5 rows) with magenta background
and outputs the individual animation strip PNGs expected by the game engine.

Row layout:
  Row 1: idle (6 frames)
  Row 2: attack-melee (6 frames)
  Row 3: attack-ranged (6 frames) — or idle-like filler for melee-only units
  Row 4: defend (6 frames)
  Row 5: death (6 frames)

Usage:
    python3 process_spritesheet.py mage.png --unit mage
    python3 process_spritesheet.py mage.png --unit mage --no-ranged
    python3 process_spritesheet.py mage.png --unit mage --preview
"""

import argparse
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_UNITS_DIR = os.path.join(SCRIPT_DIR, "..", "..", "data", "units")

COLS = 6
ROWS = 5
FRAME_SIZE = 256
SHEET_W = COLS * FRAME_SIZE   # 1536
SHEET_H = ROWS * FRAME_SIZE   # 1280

ROW_NAMES = ["idle", "attack-melee", "attack-ranged", "defend", "death"]
FRAMES_PER_ROW = 6
FPS = {"idle": 4, "attack-melee": 8, "attack-ranged": 6, "defend": 6, "death": 6}


def magick_cmd():
    """Return 'magick' (v7) or 'convert' (v6) depending on what's installed."""
    for name in ("magick", "convert"):
        try:
            subprocess.run([name, "--version"], capture_output=True, check=True)
            return name
        except FileNotFoundError:
            continue
    print("ERROR: ImageMagick not found (tried 'magick' and 'convert')", file=sys.stderr)
    sys.exit(1)

MAGICK = None  # set at runtime

def run(cmd, check=True):
    """Run a shell command, return result."""
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def process_sheet(input_path, unit_name, no_ranged=False, preview=False):
    global MAGICK
    MAGICK = magick_cmd()
    print(f"Using ImageMagick command: {MAGICK}")

    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    os.makedirs(unit_dir, exist_ok=True)

    # Step 1: Resize to exact grid dimensions using nearest-neighbor
    resized_path = os.path.join(unit_dir, "_resized_sheet.png")
    print(f"Resizing {input_path} to {SHEET_W}x{SHEET_H}...")
    run([
        MAGICK, input_path,
        "-sample", f"{SHEET_W}x{SHEET_H}!",
        resized_path,
    ])

    # Verify
    result = run(["identify", resized_path])
    dims = result.stdout.split()[2] if result.stdout else "?"
    print(f"  Resized: {dims}")

    # Step 2: Remove magenta background -> transparent
    clean_path = os.path.join(unit_dir, "_clean_sheet.png")
    print("Removing magenta background...")
    run([
        MAGICK, resized_path,
        "-alpha", "set",
        "-fuzz", "15%",
        "-transparent", "magenta",
        clean_path,
    ])

    # Step 3: Crop each row into a horizontal strip
    skip_rows = set()
    if no_ranged:
        skip_rows.add(2)  # row index 2 = attack-ranged

    outputs = []
    for row_idx, anim_name in enumerate(ROW_NAMES):
        if row_idx in skip_rows:
            print(f"  Skipping row {row_idx + 1} ({anim_name}) — no-ranged flag set")
            continue

        y_offset = row_idx * FRAME_SIZE
        strip_path = os.path.join(unit_dir, f"{anim_name}.png")

        print(f"  Row {row_idx + 1}: {anim_name} -> {strip_path}")
        run([
            MAGICK, clean_path,
            "-crop", f"{SHEET_W}x{FRAME_SIZE}+0+{y_offset}",
            "+repage",
            strip_path,
        ])

        # Verify strip dimensions
        result = run(["identify", strip_path])
        strip_dims = result.stdout.split()[2] if result.stdout else "?"
        print(f"         {strip_dims}")
        outputs.append((anim_name, strip_path))

    # Step 4: Clean up temp files
    os.remove(resized_path)
    os.remove(clean_path)

    # Step 5: Write sprite.toml
    toml_path = os.path.join(unit_dir, "sprite.toml")
    print(f"\nWriting {toml_path}")
    has_ranged = not no_ranged

    with open(toml_path, "w") as f:
        f.write(f'id = "{unit_name}"\n')

        for anim_name, _ in outputs:
            fps = FPS.get(anim_name, 6)

            if anim_name.startswith("attack-"):
                attack_type = anim_name.split("-", 1)[1]
                f.write(f"\n[attacks.{attack_type}]\n")
            else:
                f.write(f"\n[{anim_name}]\n")

            f.write(f'file = "{anim_name}.png"\n')
            f.write(f"frame_width = {FRAME_SIZE}\n")
            f.write(f"frame_height = {FRAME_SIZE}\n")
            f.write(f"frames = {FRAMES_PER_ROW}\n")
            f.write(f"fps = {fps}\n")

        f.write("\n[portrait]\n")
        f.write('file = "portrait.png"\n')

    # Step 6: Preview (optional)
    if preview:
        for anim_name, path in outputs:
            print(f"\nPreview: {anim_name}")
            run(["display", path], check=False)

    print(f"\nDone! Sprites written to {unit_dir}/")
    print("Note: portrait.png must be generated separately.")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Process a 6x5 sprite sheet into game-ready animation strips"
    )
    parser.add_argument("input", help="Path to the input sprite sheet PNG")
    parser.add_argument("--unit", required=True, help="Unit name (e.g., mage, bowman)")
    parser.add_argument("--no-ranged", action="store_true",
                        help="Skip row 3 (attack-ranged) for melee-only units")
    parser.add_argument("--preview", action="store_true",
                        help="Display each strip after processing")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1

    ok = process_sheet(args.input, args.unit, no_ranged=args.no_ranged, preview=args.preview)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
