#!/usr/bin/env python3
"""generate_sprites.py — Generate unit sprites one pose at a time via Gemini.

Generates each pose as a separate API call. The idle pose is generated first,
then fed back as a reference image for subsequent poses to maintain consistency.

Usage:
    # Generate all poses for a unit
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit lieutenant

    # Redo just one pose, using idle as reference
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit bowman --redo defend

    # Redo one pose with a specific reference image
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit bowman --redo defend --base data/units/bowman/idle.png

    # Generate only the portrait
    GEMINI_API_KEY=... python3 tools/generate_sprites.py --unit lieutenant --portrait

    # List all units
    python3 tools/generate_sprites.py --list
"""

import argparse
import base64
import io
import json
import math
import os
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_UNITS_DIR = os.path.join(PROJECT_ROOT, "data", "units")
SPRITES_RAW_DIR = os.path.join(PROJECT_ROOT, "sprites_raw")

FRAME_SIZE = 256
PORTRAIT_SIZE = 128

POSE_NAMES = ["idle", "attack-melee", "attack-ranged", "defend"]

STYLE_PROMPT = """Style: HD-2D aesthetic. High-fidelity pixel art sprite (32-bit era detail). \
Character has a clean, dark outline. \
Perspective: Slight 3/4 top-down view (isometric-lite). \
Lighting: Even, flat studio lighting with no dramatic shadows or rim-lighting \
(this keeps the color palette clean for masking). \
Background: Solid, uniform #FF00FF (pure magenta) color. \
No floor, no background elements, and no environment lighting effects. \
The sprite is centered on the mask."""

# Unit definitions
# (description, melee_weapon, ranged_weapon_or_None, defend_desc)
# defend_desc describes how the character defends WITHOUT adding equipment they don't have.
UNITS = {
    "spearman": (
        "human spearman soldier, chain mail armor, iron helmet, long spear, blue tabard",
        "spear", "spear throw",
        "bracing with spear held crosswise, crouching low to absorb impact",
    ),
    "bowman": (
        "human bowman archer, leather armor, green hood, longbow, quiver of arrows",
        "short sword", "longbow",
        "dodging sideways, leaning away from attack with arm raised to protect face",
    ),
    "cavalryman": (
        "human cavalryman on horseback, plate armor, lance, mounted knight on brown horse",
        "sword from horseback", None,
        "horse rearing back, rider pulling reins defensively",
    ),
    "heavy_infantryman": (
        "human heavy infantryman, full plate armor, great helm, heavy iron mace, tower shield",
        "mace", None,
        "crouching behind tower shield, braced for impact",
    ),
    "mage": (
        "human mage wizard, blue robes, pointed hat, wooden staff with glowing crystal top",
        "staff", "fireball magic blast from staff",
        "holding staff up defensively with a faint magic barrier shimmering in front",
    ),
    "sergeant": (
        "human sergeant officer, chain mail, red cape, sword and shield, commanding officer",
        "sword", "crossbow bolt shot",
        "crouching behind shield, sword held back ready to counter",
    ),
    "lieutenant": (
        "human lieutenant commander, plate armor, white cape, longsword, gold crown, leader",
        "sword", "crossbow bolt shot",
        "parrying with longsword held high, armored shoulder turned forward",
    ),
    "elvish_fighter": (
        "elf warrior, green leather armor, long blonde hair, elven sword, leaf-pattern shield",
        "sword", "bow shot",
        "crouching behind leaf-pattern shield, sword ready at side",
    ),
    "elvish_archer": (
        "elvish archer, green hooded cloak, brown boots, longbow, quiver",
        "sword", "longbow",
        "leaping back evasively, cloak swirling, bow held to the side",
    ),
    "elvish_captain": (
        "elf captain leader, ornate green and gold armor, elven longsword, flowing cape, crown circlet",
        "sword", "bow",
        "parrying with elven longsword, cape flowing behind",
    ),
    "elvish_scout": (
        "elf scout rider on white horse, light green leather armor, sword, mounted",
        "sword from horseback", "bow shot from horseback",
        "horse turning sideways, rider ducking low against horse's neck",
    ),
    "elvish_shaman": (
        "female elf shaman healer, white and green robes, wooden staff with leaves, nature magic",
        "staff", "magic healing energy blast",
        "holding staff forward with a nature magic ward of swirling leaves",
    ),
    "orcish_grunt": (
        "orc grunt warrior, green skin, leather and bone armor, crude iron sword, muscular",
        "sword", None,
        "raising muscular forearm to block, snarling, crude sword held back",
    ),
    "orcish_archer": (
        "orc archer, green skin, leather armor, crude shortbow, bone-tipped arrows",
        "dagger", "shortbow",
        "ducking low with bow clutched to chest, turning sideways to present smaller target",
    ),
    "orcish_assassin": (
        "orc assassin rogue, green skin, dark leather armor, twin daggers, hooded, stealthy",
        "throwing daggers", "poison darts",
        "crossed daggers in front of face, crouching low in defensive stance",
    ),
    "orcish_warrior": (
        "orc warrior chieftain, green skin, heavy bone and iron armor, great two-handed sword, leader",
        "greatsword", None,
        "holding greatsword crosswise in front as a barrier, roaring defiantly",
    ),
    "dark_adept": (
        "dark adept necromancer, pale skin, dark purple/black hooded robe, glowing purple eyes, skeletal staff with skull top",
        "staff jab", "purple chill wave magic blast",
        "raising skeletal staff with skull glowing, dark energy shield swirling around",
    ),
}


def load_image_base64(path):
    """Load an image file and return base64-encoded data."""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def generate_image(api_key, prompt, reference_image_path=None, retries=3):
    """Generate an image via Gemini API, optionally with a reference image."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash-exp-image-generation:generateContent"
    )

    parts = []

    if reference_image_path:
        img_b64 = load_image_base64(reference_image_path)
        parts.append({
            "inlineData": {
                "mimeType": "image/png",
                "data": img_b64,
            }
        })

    parts.append({"text": prompt})

    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }).encode()

    for attempt in range(retries):
        if attempt > 0:
            wait = 30 * attempt
            print(f"    Retry {attempt} (waiting {wait}s)...", flush=True)
            time.sleep(wait)

        try:
            req = urllib.request.Request(
                url, data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"    API error: {type(e).__name__}", flush=True)
            continue

        candidates = data.get("candidates", [])
        if not candidates:
            print("    No candidates in response", flush=True)
            continue
        parts_resp = candidates[0].get("content", {}).get("parts", [])
        for p in parts_resp:
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])

        print("    No image in response", flush=True)

    return None


def process_single_image(img_data, out_path, threshold=100):
    """Process a single generated image: resize to single frame, remove bg, center."""
    from PIL import Image

    img = Image.open(io.BytesIO(img_data)).convert("RGBA")

    # Scale to square, fitting into FRAME_SIZE x FRAME_SIZE
    max_dim = max(img.width, img.height)
    scale = FRAME_SIZE / max_dim
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.NEAREST)

    # Sample background color from corners
    corners = [
        (0, 0), (new_w - 1, 0),
        (0, new_h - 1), (new_w - 1, new_h - 1),
    ]
    bg = tuple(
        sum(img.getpixel(c)[i] for c in corners) // 4
        for i in range(3)
    )

    # Find content bounding box
    pixels = img.load()
    left_c, right_c = new_w, 0
    top_c, bot_c = new_h, 0
    for y in range(new_h):
        for x in range(new_w):
            r, g, b, a = pixels[x, y]
            if math.sqrt((r - bg[0])**2 + (g - bg[1])**2 + (b - bg[2])**2) >= threshold:
                left_c = min(left_c, x)
                right_c = max(right_c, x)
                top_c = min(top_c, y)
                bot_c = max(bot_c, y)

    # No content found — save blank frame
    if right_c < left_c:
        frame = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (0, 0, 0, 0))
        frame.save(out_path)
        return False, 0, 0

    content_w = right_c - left_c + 1
    content_h = bot_c - top_c + 1

    # Crop to content
    crop = img.crop((left_c, top_c, right_c + 1, bot_c + 1))

    # Fit into FRAME_SIZE with padding
    fit_scale = min((FRAME_SIZE - 10) / content_w, (FRAME_SIZE - 10) / content_h)
    if fit_scale < 1.0:
        crop = crop.resize((int(content_w * fit_scale), int(content_h * fit_scale)), Image.NEAREST)

    # Center on FRAME_SIZE x FRAME_SIZE canvas
    frame = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (bg[0], bg[1], bg[2], 255))
    x_off = (FRAME_SIZE - crop.width) // 2
    y_off = (FRAME_SIZE - crop.height) // 2
    frame.paste(crop, (x_off, y_off))

    # Remove background + pink artifacts
    pixels = frame.load()
    bg2 = tuple(
        sum(frame.getpixel(c)[i] for c in [
            (0, 0), (FRAME_SIZE - 1, 0),
            (0, FRAME_SIZE - 1), (FRAME_SIZE - 1, FRAME_SIZE - 1),
        ]) // 4
        for i in range(3)
    )
    for y in range(FRAME_SIZE):
        for x in range(FRAME_SIZE):
            r, g, b, a = pixels[x, y]
            if math.sqrt((r - bg2[0])**2 + (g - bg2[1])**2 + (b - bg2[2])**2) < threshold:
                pixels[x, y] = (0, 0, 0, 0)
            elif r > 180 and b > 150 and g < 120:
                pixels[x, y] = (0, 0, 0, 0)

    # Verify padding
    top_p, bot_p = FRAME_SIZE, 0
    for y in range(FRAME_SIZE):
        for x in range(FRAME_SIZE):
            if pixels[x, y][3] > 0:
                top_p = min(top_p, y)
                bot_p = max(bot_p, y)
                break

    pad_top = top_p
    pad_bot = FRAME_SIZE - 1 - bot_p
    ok = pad_bot >= 3 and pad_top >= 3

    frame.save(out_path)
    return ok, pad_top, pad_bot


def check_multi_blob(img_path):
    """Detect multiple disconnected figures via flood-fill connected components."""
    from PIL import Image

    img = Image.open(img_path).convert("RGBA")
    pixels = img.load()
    w, h = img.width, img.height

    # Build binary mask
    visited = [[False] * w for _ in range(h)]
    total_opaque = 0
    for y in range(h):
        for x in range(w):
            if pixels[x, y][3] > 0:
                total_opaque += 1

    if total_opaque == 0:
        return True, 0

    threshold = total_opaque * 0.05
    blob_count = 0

    for sy in range(h):
        for sx in range(w):
            if visited[sy][sx] or pixels[sx, sy][3] == 0:
                continue
            # BFS flood-fill
            queue = [(sx, sy)]
            visited[sy][sx] = True
            size = 0
            while queue:
                cx, cy = queue.pop()
                size += 1
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and pixels[nx, ny][3] > 0:
                        visited[ny][nx] = True
                        queue.append((nx, ny))
            if size >= threshold:
                blob_count += 1

    return blob_count <= 1, blob_count


def check_size(img_path, hard_limit=30720, warn_limit=20480):
    """Check file size against limits. Hard fail >30KB, warn >20KB."""
    file_bytes = os.path.getsize(img_path)
    if file_bytes > hard_limit:
        return False, file_bytes
    if file_bytes > warn_limit:
        print(f"    SIZE WARNING: {file_bytes} bytes (>{warn_limit} target)", flush=True)
    return True, file_bytes


def check_edges(img_path, border=2):
    """Check that no opaque pixels exist in outermost border pixels."""
    from PIL import Image

    img = Image.open(img_path).convert("RGBA")
    pixels = img.load()
    w, h = img.width, img.height
    edge_count = 0

    for y in range(h):
        for x in range(w):
            if x < border or x >= w - border or y < border or y >= h - border:
                if pixels[x, y][3] > 0:
                    edge_count += 1

    return edge_count == 0, edge_count


def validate_sprite(img_path):
    """Run all validation checks on a processed sprite. Returns (ok, issues)."""
    issues = []

    # Multi-blob check
    blob_ok, blob_count = check_multi_blob(img_path)
    if not blob_ok:
        issues.append(f"multi-blob ({blob_count} significant blobs)")
        print(f"    MULTI-BLOB: FAIL ({blob_count} blobs)", flush=True)
    else:
        print(f"    MULTI-BLOB: ok ({blob_count} blob)", flush=True)

    # Size check
    size_ok, file_bytes = check_size(img_path)
    if not size_ok:
        issues.append(f"oversized ({file_bytes} bytes > 30KB)")
        print(f"    SIZE: FAIL ({file_bytes} bytes)", flush=True)
    else:
        print(f"    SIZE: ok ({file_bytes} bytes)", flush=True)

    # Edge check
    edge_ok, edge_count = check_edges(img_path)
    if not edge_ok:
        issues.append(f"edge-clipped ({edge_count} border pixels)")
        print(f"    EDGES: FAIL ({edge_count} border pixels)", flush=True)
    else:
        print(f"    EDGES: ok", flush=True)

    return len(issues) == 0, issues


def write_sprite_toml(unit_dir, unit_name, has_ranged=True):
    """Write sprite.toml for a unit. Single frame per pose (v2 pipeline)."""
    toml_path = os.path.join(unit_dir, "sprite.toml")
    with open(toml_path, "w") as f:
        f.write(f'id = "{unit_name}"\n')
        for name in POSE_NAMES:
            if name == "attack-ranged" and not has_ranged:
                continue
            # Only write if the png exists
            png_path = os.path.join(unit_dir, f"{name}.png")
            if not os.path.exists(png_path):
                continue
            if name.startswith("attack-"):
                attack_type = name.split("-", 1)[1]
                f.write(f"\n[attacks.{attack_type}]\n")
            else:
                f.write(f"\n[{name}]\n")
            f.write(f'file = "{name}.png"\n')
            f.write(f"frame_width = {FRAME_SIZE}\n")
            f.write(f"frame_height = {FRAME_SIZE}\n")
            f.write(f"frames = 1\n")
            f.write(f"fps = 1\n")
        portrait_path = os.path.join(unit_dir, "portrait.png")
        if os.path.exists(portrait_path):
            f.write("\n[portrait]\n")
            f.write('file = "portrait.png"\n')


def build_prompt(unit_name, pose, ref_path):
    """Build the generation prompt for a unit + pose."""
    desc, melee_weapon, ranged_weapon, defend_desc = UNITS[unit_name]

    pose_descriptions = {
        "idle": "standing idle, weapon at rest, relaxed stance.",
        "attack-melee": f"mid-swing {melee_weapon} melee attack, dynamic action pose.",
        "attack-ranged": f"aiming {ranged_weapon or melee_weapon} ranged attack, ready to fire.",
        "defend": defend_desc,
    }
    pose_desc = pose_descriptions[pose]

    if ref_path is None:
        # First generation — no reference
        return (
            f"{STYLE_PROMPT}\n\n"
            f"Make a {desc}.\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"Just one character, facing right, centered on the magenta background."
        )
    else:
        # With reference image for consistency
        return (
            f"This is a reference image of the character. "
            f"Generate the SAME character in a new pose.\n\n"
            f"{STYLE_PROMPT}\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"SAME character as the reference — same colors, same proportions, "
            f"same outfit, same style. Facing right. "
            f"Do NOT add equipment the character does not have."
        )


def build_portrait_prompt(unit_name):
    """Build prompt for a painterly portrait on black background."""
    desc = UNITS[unit_name][0]
    return (
        f"A painterly close-up portrait of a {desc}. "
        f"Show the face and upper body only, slightly angled, with dramatic lighting. "
        f"Rich detail, oil painting style, fantasy RPG character portrait. "
        f"Background: solid, uniform black (#000000). "
        f"No environment, no props, no text. Just the character portrait on black."
    )


def process_portrait(img_data, out_path, threshold=60):
    """Process a portrait: scale to 128x128, replace background with black."""
    from PIL import Image

    img = Image.open(io.BytesIO(img_data)).convert("RGB")

    # Scale to fit PORTRAIT_SIZE x PORTRAIT_SIZE
    max_dim = max(img.width, img.height)
    scale = PORTRAIT_SIZE / max_dim
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center on black canvas
    frame = Image.new("RGB", (PORTRAIT_SIZE, PORTRAIT_SIZE), (0, 0, 0))
    x_off = (PORTRAIT_SIZE - new_w) // 2
    y_off = (PORTRAIT_SIZE - new_h) // 2
    frame.paste(img, (x_off, y_off))

    # Clean near-black edges to pure black
    pixels = frame.load()
    for y in range(PORTRAIT_SIZE):
        for x in range(PORTRAIT_SIZE):
            r, g, b = pixels[x, y]
            if r < threshold and g < threshold and b < threshold:
                pixels[x, y] = (0, 0, 0)

    frame.save(out_path)
    file_bytes = os.path.getsize(out_path)
    return True, file_bytes


def generate_portrait(api_key, unit_name, max_attempts=3):
    """Generate a portrait for a unit. Returns True on success."""
    if unit_name not in UNITS:
        print(f"Unknown unit: {unit_name}")
        return False

    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    os.makedirs(unit_dir, exist_ok=True)
    os.makedirs(SPRITES_RAW_DIR, exist_ok=True)

    out_path = os.path.join(unit_dir, "portrait.png")
    raw_path = os.path.join(SPRITES_RAW_DIR, f"{unit_name}_v2_portrait.png")

    prompt = build_portrait_prompt(unit_name)

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"\n  Retry {attempt}/{max_attempts} for portrait...", flush=True)
            time.sleep(10)
        else:
            print(f"\n  Generating portrait...", end=" ", flush=True)

        img_data = generate_image(api_key, prompt)

        if not img_data:
            print("FAILED (no image)")
            continue

        # Save raw
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"raw saved ({len(img_data)} bytes)", end=" ", flush=True)

        # Process
        _, file_bytes = process_portrait(img_data, out_path)
        print(f"processed ({file_bytes} bytes)", flush=True)

        # Size check (100KB limit)
        if file_bytes > 102400:
            print(f"  portrait: OVERSIZED ({file_bytes} bytes > 100KB)", flush=True)
            continue

        print(f"  portrait: PASSED ({file_bytes} bytes)", flush=True)
        return True

    print(f"  NEEDS REVIEW: portrait failed after {max_attempts} attempts", flush=True)
    return False


def generate_pose(api_key, unit_name, pose, ref_path=None, max_attempts=3):
    """Generate a single pose with validation + retry. Returns (ok, raw_path)."""
    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    os.makedirs(unit_dir, exist_ok=True)
    os.makedirs(SPRITES_RAW_DIR, exist_ok=True)

    out_path = os.path.join(unit_dir, f"{pose}.png")
    raw_path = os.path.join(SPRITES_RAW_DIR, f"{unit_name}_v2_{pose}.png")

    prompt = build_prompt(unit_name, pose, ref_path)

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            print(f"\n  Retry {attempt}/{max_attempts} for {pose}...", flush=True)
            time.sleep(10)
        else:
            print(f"\n  Generating {pose}...", end=" ", flush=True)

        img_data = generate_image(api_key, prompt, reference_image_path=ref_path)

        if not img_data:
            print("FAILED (no image)")
            continue

        # Save raw
        with open(raw_path, "wb") as f:
            f.write(img_data)
        print(f"raw saved ({len(img_data)} bytes)", end=" ", flush=True)

        # Process
        _, pad_top, pad_bot = process_single_image(img_data, out_path)
        print(f"processed (top={pad_top} bot={pad_bot})")

        # Validate
        print(f"  Validating {pose}:", flush=True)
        valid, issues = validate_sprite(out_path)

        if valid:
            print(f"  {pose}: PASSED", flush=True)
            return True, raw_path
        else:
            print(f"  {pose}: FAILED validation — {', '.join(issues)}", flush=True)

    print(f"  NEEDS REVIEW: {pose} failed after {max_attempts} attempts", flush=True)
    return False, raw_path


def generate_unit(api_key, unit_name, reference_path=None):
    """Generate all poses for one unit."""
    if unit_name not in UNITS:
        print(f"Unknown unit: {unit_name}")
        return False

    _, _, ranged_weapon, _ = UNITS[unit_name]
    has_ranged = ranged_weapon is not None

    poses = POSE_NAMES if has_ranged else [p for p in POSE_NAMES if p != "attack-ranged"]

    ref_path = reference_path
    passed = []
    failed = []

    for pose in poses:
        ok, raw_path = generate_pose(api_key, unit_name, pose, ref_path=ref_path)
        if ok:
            passed.append(pose)
        else:
            failed.append(pose)

        # After idle, use it as reference for remaining poses
        if pose == "idle" and ref_path is None and raw_path:
            ref_path = raw_path
            print(f"  (idle will be used as reference for remaining poses)")

        time.sleep(10)

    # Generate portrait
    time.sleep(10)
    portrait_ok = generate_portrait(api_key, unit_name)
    if not portrait_ok:
        failed.append("portrait")

    unit_dir = os.path.join(DATA_UNITS_DIR, unit_name)
    write_sprite_toml(unit_dir, unit_name, has_ranged)

    total = len(poses) + 1  # poses + portrait
    print(f"\n{'=' * 50}")
    print(f"Summary: {len(passed) + (1 if portrait_ok else 0)}/{total} assets passed validation")
    if failed:
        print(f"NEEDS REVIEW: {', '.join(failed)}")
    print(f"Sprites in {unit_dir}/")
    print(f"{'=' * 50}")
    return len(failed) == 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate unit sprites one pose at a time with reference feedback"
    )
    parser.add_argument("--unit", help="Unit name (e.g., lieutenant)")
    parser.add_argument("--redo", help="Regenerate only this pose (e.g., defend)")
    parser.add_argument("--base", help="Reference image for --redo (default: idle raw)")
    parser.add_argument("--portrait", action="store_true", help="Generate only the portrait")
    parser.add_argument("--list", action="store_true", help="List available units")
    args = parser.parse_args()

    if args.list:
        for name in sorted(UNITS.keys()):
            desc, melee, ranged, defend = UNITS[name]
            r = f" + {ranged}" if ranged else ""
            print(f"  {name}: {desc}")
            print(f"    weapons: {melee}{r}")
            print(f"    defend: {defend}")
        return 0

    if not args.unit:
        parser.error("--unit is required (use --list to see available units)")

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY not set", file=sys.stderr)
        return 1

    if args.portrait:
        print(f"{'=' * 50}")
        print(f"Portrait: {args.unit}")
        print(f"{'=' * 50}")

        ok = generate_portrait(api_key, args.unit)
        print(f"\nResult: {'OK' if ok else 'NEEDS REVIEW'}")
        return 0 if ok else 1

    if args.redo:
        # Single pose redo
        if args.unit not in UNITS:
            print(f"Unknown unit: {args.unit}")
            return 1

        _, _, ranged_weapon, _ = UNITS[args.unit]
        has_ranged = ranged_weapon is not None
        valid_poses = POSE_NAMES if has_ranged else [p for p in POSE_NAMES if p != "attack-ranged"]

        if args.redo not in valid_poses:
            print(f"Invalid pose '{args.redo}'. Valid: {valid_poses}")
            return 1

        # Determine reference
        if args.base:
            ref_path = os.path.abspath(args.base)
            if not os.path.exists(ref_path):
                print(f"Reference not found: {ref_path}")
                return 1
        else:
            # Default to idle raw
            ref_path = os.path.join(SPRITES_RAW_DIR, f"{args.unit}_v2_idle.png")
            if not os.path.exists(ref_path):
                print(f"No idle reference found at {ref_path}")
                print("Use --base to specify a reference image")
                return 1

        print(f"{'=' * 50}")
        print(f"Redo: {args.unit} / {args.redo}")
        print(f"Reference: {ref_path}")
        print(f"{'=' * 50}")

        ok, _ = generate_pose(api_key, args.unit, args.redo, ref_path=ref_path)

        unit_dir = os.path.join(DATA_UNITS_DIR, args.unit)
        write_sprite_toml(unit_dir, args.unit, has_ranged)

        print(f"\nResult: {'OK' if ok else 'NEEDS REVIEW'}")
        return 0 if ok else 1
    else:
        # Full unit generation
        print(f"{'=' * 50}")
        print(f"Generating: {args.unit} (v2 pipeline)")
        print(f"{'=' * 50}")

        ok = generate_unit(api_key, args.unit, reference_path=args.base)

        print(f"\nResult: {'OK' if ok else 'NEEDS REVIEW'}")
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
