#!/usr/bin/env python3
"""generate_sprites.py — AI sprite generation pipeline for The Clash for Norrust.

Uses Gemini 2.0 Flash image generation API to create unit sprites.
Reads character descriptions from unit_prompts.toml, frame counts from
each unit's sprite.toml, generates individual frames, removes backgrounds
via ImageMagick flood-fill, and assembles horizontal spritesheets.

Usage:
    python3 generate_sprites.py --unit mage          # Generate one unit
    python3 generate_sprites.py --all                 # Generate all 16 units
    python3 generate_sprites.py --unit mage --dry-run # Print prompts only
    python3 generate_sprites.py --unit mage --portrait-fuzz 8
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

# ── Config ──────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(SCRIPT_DIR, "..", "assets", "units")
PROMPTS_FILE = os.path.join(SCRIPT_DIR, "unit_prompts.toml")

GEMINI_MODEL = "gemini-2.0-flash-exp-image-generation"
FRAME_SIZE = 256
DEFAULT_FUZZ = 20
DEFAULT_PORTRAIT_FUZZ = 20
RATE_LIMIT_SEC = 1

# ── Minimal TOML parser (stdlib only) ───────────────────────────────────

def parse_toml(text):
    """Parse a minimal TOML subset: [sections], key = "string", key = number."""
    result = {}
    current = result
    current_path = []

    for line in text.splitlines():
        # Strip comments (not inside strings)
        comment_pos = line.find("#")
        if comment_pos >= 0:
            in_str = False
            for i in range(comment_pos):
                if line[i] == '"':
                    in_str = not in_str
            if not in_str:
                line = line[:comment_pos]
        line = line.strip()
        if not line:
            continue

        # Section header
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            current = result
            for part in section.split("."):
                part = part.strip()
                if part not in current:
                    current[part] = {}
                current = current[part]
            continue

        # Key = value
        eq = line.find("=")
        if eq < 0:
            continue
        key = line[:eq].strip()
        val = line[eq + 1:].strip()

        # String
        if val.startswith('"') and val.endswith('"'):
            current[key] = val[1:-1]
        # Number
        else:
            try:
                current[key] = int(val)
            except ValueError:
                try:
                    current[key] = float(val)
                except ValueError:
                    if val == "true":
                        current[key] = True
                    elif val == "false":
                        current[key] = False
                    else:
                        current[key] = val

    return result


def load_toml_file(path):
    """Load and parse a TOML file."""
    with open(path, "r") as f:
        return parse_toml(f.read())


# ── Animation prompt templates ──────────────────────────────────────────

STYLE_PREFIX = "2D fantasy game character sprite on a plain white background. Detailed painterly art style. Full body visible from head to feet, character centered. Facing to the right."

def build_base_prompt(unit_info):
    """Build the base prompt from unit description."""
    return f"{STYLE_PREFIX} {unit_info['base_desc']} Armed with {unit_info['weapon']}."


def get_animation_prompts(unit_info, sprite_toml):
    """Generate per-frame prompts for all animation states."""
    weapon = unit_info.get("weapon", "weapon")
    weapon_short = weapon.split(" and ")[0]  # First weapon for single-weapon refs

    anims = {}

    # Idle (4 frames)
    anims["idle"] = [
        "Standing idle in a neutral ready pose.",
        "Standing idle, slight weight shift, weapon held steady.",
        "Standing idle, garments swaying gently as if in a light breeze.",
        "Standing idle, head tilted slightly, watchful expression.",
    ]

    # Attack-melee (6 frames)
    anims["attack-melee"] = [
        f"Beginning a melee attack, raising {weapon_short} to strike.",
        f"Winding up, {weapon_short} raised high overhead with both hands.",
        f"Mid-swing, {weapon_short} sweeping forward and downward.",
        f"Full strike, {weapon_short} extended forward, body lunging.",
        f"Follow-through, {weapon_short} low after the downward strike.",
        f"Recovering from attack, pulling {weapon_short} back to ready position.",
    ]

    # Attack-ranged (4 frames) — only if sprite.toml has attacks.ranged
    has_ranged = sprite_toml.get("attacks", {}).get("ranged") is not None
    if has_ranged:
        anims["attack-ranged"] = [
            f"Preparing a ranged attack, raising {weapon_short} to aim.",
            f"Channeling energy, {weapon_short} glowing with power, free hand extended forward.",
            "Releasing the ranged attack, projectile or energy bolt shooting toward the right.",
            f"After the ranged attack, lowering {weapon_short}, energy dissipating.",
        ]

    # Defend (3 frames)
    anims["defend"] = [
        "Defensive stance, pulling weapon close, crouching slightly to brace.",
        "Full defensive posture, weapon held as a shield, magical or physical barrier visible.",
        "Recovering from defense, straightening up, barrier fading.",
    ]

    # Death (4 frames)
    anims["death"] = [
        "Hit and staggering backward, weapon tilting, pained expression.",
        "Falling backward, weapon slipping from grasp, garments billowing.",
        "Nearly fallen, body at 45 degree angle, weapon falling separately.",
        "Collapsed on the ground, lying on back, weapon fallen beside, defeated.",
    ]

    # Portrait (1 frame)
    anims["portrait"] = None  # Special handling

    return anims, has_ranged


def get_portrait_prompt(unit_info):
    """Build portrait-specific prompt."""
    desc = unit_info["base_desc"]
    weapon = unit_info.get("weapon", "")
    return (
        f"Close-up portrait on a plain white background. {desc} "
        f"{weapon} partially visible at shoulder. "
        f"Detailed painterly fantasy game portrait style. Head and upper chest visible."
    )


# ── Gemini API ──────────────────────────────────────────────────────────

def get_api_url():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    return f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={key}"


def generate_image(prompt, output_path, retries=2):
    """Call Gemini API to generate an image. Returns True on success."""
    url = get_api_url()
    data = json.dumps({
        "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}
    }).encode()

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())

            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            for p in parts:
                if "inlineData" in p:
                    imgdata = base64.b64decode(p["inlineData"]["data"])
                    with open(output_path, "wb") as f:
                        f.write(imgdata)
                    return True

            print(f"    WARNING: No image in response (attempt {attempt + 1})")
        except Exception as e:
            print(f"    ERROR: {e} (attempt {attempt + 1})")

        if attempt < retries:
            time.sleep(3)

    return False


# ── ImageMagick post-processing ─────────────────────────────────────────

def remove_background(input_path, output_path, fuzz=DEFAULT_FUZZ):
    """Flood-fill from corners to remove background, resize/pad to frame size."""
    cmd = [
        "magick", input_path,
        "-alpha", "set",
        "-fuzz", f"{fuzz}%",
        "-fill", "none",
        "-draw", "color 0,0 floodfill",
        "-draw", f"color 0,%[fx:h-1] floodfill",
        "-draw", f"color %[fx:w-1],0 floodfill",
        "-draw", f"color %[fx:w-1],%[fx:h-1] floodfill",
        "-trim", "+repage",
        "-resize", f"{FRAME_SIZE}x{FRAME_SIZE}",
        "-gravity", "center",
        "-background", "none",
        "-extent", f"{FRAME_SIZE}x{FRAME_SIZE}",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def assemble_spritesheet(frame_paths, output_path):
    """Combine frames into a horizontal spritesheet."""
    n = len(frame_paths)
    cmd = [
        "montage", *frame_paths,
        "-tile", f"{n}x1",
        "-geometry", f"{FRAME_SIZE}x{FRAME_SIZE}+0+0",
        "-background", "none",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def verify_dimensions(path, expected_w, expected_h):
    """Check image dimensions match expected values."""
    result = subprocess.run(["identify", path], capture_output=True, text=True)
    dims = result.stdout.split()[2] if result.stdout else ""
    expected = f"{expected_w}x{expected_h}"
    return dims == expected, dims


# ── Main pipeline ───────────────────────────────────────────────────────

def generate_unit(unit_name, unit_info, sprite_toml, dry_run=False, portrait_fuzz=None):
    """Generate all sprites for a single unit."""
    unit_dir = os.path.join(ASSETS_DIR, unit_name)
    tmp_dir = os.path.join(unit_dir, "tmp")

    if portrait_fuzz is None:
        portrait_fuzz = unit_info.get("portrait_fuzz", DEFAULT_PORTRAIT_FUZZ)

    base_prompt = build_base_prompt(unit_info)
    anim_prompts, has_ranged = get_animation_prompts(unit_info, sprite_toml)

    print(f"\n{'=' * 60}")
    print(f"  Unit: {unit_name} ({unit_info.get('faction', '?')})")
    print(f"  Ranged: {'yes' if has_ranged else 'no'}")
    print(f"  Portrait fuzz: {portrait_fuzz}%")
    print(f"{'=' * 60}")

    if not dry_run:
        os.makedirs(tmp_dir, exist_ok=True)

    # Animation states to process (order matters for output)
    anim_order = ["idle", "attack-melee"]
    if has_ranged:
        anim_order.append("attack-ranged")
    anim_order.extend(["defend", "death", "portrait"])

    for anim_name in anim_order:
        # Get frame count from sprite.toml
        if anim_name == "portrait":
            frame_count = 1
        elif anim_name == "idle":
            frame_count = sprite_toml.get("idle", {}).get("frames", 4)
        elif anim_name.startswith("attack-"):
            attack_type = anim_name.split("-", 1)[1]
            frame_count = sprite_toml.get("attacks", {}).get(attack_type, {}).get("frames", 4)
        elif anim_name == "defend":
            frame_count = sprite_toml.get("defend", {}).get("frames", 3)
        elif anim_name == "death":
            frame_count = sprite_toml.get("death", {}).get("frames", 4)
        else:
            frame_count = 4

        print(f"\n  --- {anim_name} ({frame_count} frames) ---")

        proc_frames = []
        for i in range(frame_count):
            # Build prompt
            if anim_name == "portrait":
                prompt = get_portrait_prompt(unit_info)
            else:
                suffixes = anim_prompts.get(anim_name, [])
                suffix = suffixes[i] if i < len(suffixes) else suffixes[-1] if suffixes else ""
                prompt = f"{base_prompt} {suffix}"

            if dry_run:
                print(f"    Frame {i + 1}/{frame_count}: {prompt[:120]}...")
                proc_frames.append(f"<dry-run-frame-{i}>")
                continue

            raw_path = os.path.join(tmp_dir, f"{anim_name}_raw_{i}.png")
            proc_path = os.path.join(tmp_dir, f"{anim_name}_proc_{i}.png")

            print(f"    Frame {i + 1}/{frame_count}...", end=" ", flush=True)
            if not generate_image(prompt, raw_path):
                print(f"FAILED to generate {anim_name} frame {i}")
                return False

            fuzz = portrait_fuzz if anim_name == "portrait" else DEFAULT_FUZZ
            remove_background(raw_path, proc_path, fuzz)
            print("OK")
            proc_frames.append(proc_path)

            time.sleep(RATE_LIMIT_SEC)

        if dry_run:
            expected_w = frame_count * FRAME_SIZE
            print(f"    -> {anim_name}.png ({expected_w}x{FRAME_SIZE})")
            continue

        # Assemble spritesheet
        output_path = os.path.join(unit_dir, f"{anim_name}.png")
        assemble_spritesheet(proc_frames, output_path)

        expected_w = frame_count * FRAME_SIZE
        ok, dims = verify_dimensions(output_path, expected_w, FRAME_SIZE)
        status = "OK" if ok else f"MISMATCH ({dims})"
        print(f"    -> {anim_name}.png = {dims} [{status}]")

        if not ok:
            print(f"    ERROR: Expected {expected_w}x{FRAME_SIZE}")
            return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Generate AI sprites for The Clash for Norrust")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--unit", help="Generate sprites for a single unit")
    group.add_argument("--all", action="store_true", help="Generate sprites for all units")
    parser.add_argument("--dry-run", action="store_true", help="Print prompts without generating")
    parser.add_argument("--portrait-fuzz", type=int, help="Override portrait fuzz %%")
    args = parser.parse_args()

    # Load unit prompts
    if not os.path.exists(PROMPTS_FILE):
        print(f"ERROR: {PROMPTS_FILE} not found", file=sys.stderr)
        return 1

    prompts = load_toml_file(PROMPTS_FILE)

    # Determine which units to generate
    if args.all:
        units = sorted(prompts.keys())
    else:
        units = [args.unit]

    # Validate units
    for unit_name in units:
        if unit_name not in prompts:
            print(f"ERROR: No prompt entry for '{unit_name}' in unit_prompts.toml", file=sys.stderr)
            return 1

        unit_dir = os.path.join(ASSETS_DIR, unit_name)
        sprite_toml_path = os.path.join(unit_dir, "sprite.toml")
        if not os.path.exists(sprite_toml_path):
            print(f"ERROR: sprite.toml not found for '{unit_name}'", file=sys.stderr)
            return 1

    if not args.dry_run:
        if not os.environ.get("GEMINI_API_KEY"):
            print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
            return 1

    # Generate
    total = len(units)
    for idx, unit_name in enumerate(units, 1):
        print(f"\n[{idx}/{total}] Generating: {unit_name}")

        unit_info = prompts[unit_name]
        sprite_toml_path = os.path.join(ASSETS_DIR, unit_name, "sprite.toml")
        sprite_toml = load_toml_file(sprite_toml_path)

        ok = generate_unit(
            unit_name, unit_info, sprite_toml,
            dry_run=args.dry_run,
            portrait_fuzz=args.portrait_fuzz,
        )

        if not ok and not args.dry_run:
            print(f"\nFAILED: {unit_name}")
            return 1

    print(f"\n{'=' * 60}")
    print(f"  Done. {total} unit(s) processed.")
    print(f"{'=' * 60}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
