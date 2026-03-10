#!/usr/bin/env python3
"""generate_terrain.py — Generate terrain tile images via Gemini.

Generates terrain tiles with HD-2D pixel art style consistent with unit sprites.

Usage:
    # Generate a single terrain tile (overwrites existing)
    GEMINI_API_KEY=... python3 tools/generate_terrain.py --terrain mountains

    # Preview to tmp/ without overwriting
    GEMINI_API_KEY=... python3 tools/generate_terrain.py --terrain mountains --preview

    # Generate all terrain tiles
    GEMINI_API_KEY=... python3 tools/generate_terrain.py --all

    # List available terrain types
    python3 tools/generate_terrain.py --list
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_TERRAIN_DIR = os.path.join(PROJECT_ROOT, "data", "terrain")
TMP_DIR = os.path.join(PROJECT_ROOT, "tmp")

TILE_SIZE = 256

STYLE = """Style: HD-2D aesthetic. High-fidelity pixel art terrain tile (32-bit era detail).
Top-down view looking straight down at the ground.
Seamless, tileable terrain texture that fills the entire image edge-to-edge.
No borders, no hex outline, no frame — just the terrain surface.
Lighting: Even, flat lighting with subtle depth through color variation.
The tile should look good when clipped to a hexagonal shape."""

TERRAIN_PROMPTS = {
    "mountains": "Rocky mountain peaks with snow-capped grey stone, craggy outcrops, deep crevices. Mix of dark granite and lighter snow patches. Dramatic elevation feel.",
    "hills": "Rolling green hills with grass, gentle slopes, scattered rocks. Earthy tones with green grass patches. Subtle elevation contour lines.",
    "flat": "Open grassland plains. Short green grass with subtle variation. A few tiny wildflowers. Natural, even ground cover.",
    "forest": "Dense forest canopy viewed from above. Green tree crowns packed together, varying shades of green. Occasional dark gaps between trees.",
    "shallow_water": "Clear shallow water with visible sandy bottom. Light blue-green water, subtle ripples, maybe a few small rocks visible through water.",
    "sand": "Desert sand terrain. Golden-tan sand with subtle wind ripple patterns. Warm tones, dry appearance.",
    "frozen": "Frozen ice terrain. Light blue-white ice surface with cracks and frost patterns. Cold, crystalline appearance.",
    "swamp_water": "Murky swamp water. Dark green-brown water with lily pads, reeds poking up, algae patches. Dank and organic.",
    "cave": "Dark cave floor. Grey-brown stone, stalactite shadows, small puddles. Dim, underground feel.",
    "castle": "Stone castle floor. Grey cobblestone or flagstone pattern. Worn, medieval fortress flooring.",
    "keep": "Ornate castle keep floor. Finer stonework than regular castle. Central important location feel.",
    "reef": "Coral reef underwater. Colorful coral formations, blue water, fish shadows. Tropical marine feel.",
    "fungus": "Underground mushroom forest floor. Large colorful fungi caps viewed from above. Bioluminescent hints. Purple and teal tones.",
    "village": "Small village tile. Thatched roof cottage viewed from above, dirt path, garden patch. Cozy settlement.",
    "grassland": "Lush grassland. Rich green grass with gentle wind patterns, a few dandelions. Pastoral feel.",
}


def generate_image(api_key, prompt, retries=3):
    """Generate an image via Gemini API."""
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.0-flash-exp-image-generation:generateContent"
        f"?key={api_key}"
    )

    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }).encode()

    for attempt in range(retries):
        if attempt > 0:
            wait = 30 * attempt
            print(f"  Retry {attempt} (waiting {wait}s)...", flush=True)
            time.sleep(wait)

        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"  API error: {e}", flush=True)
            continue

        candidates = data.get("candidates", [{}])
        parts_resp = candidates[0].get("content", {}).get("parts", [])
        for p in parts_resp:
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])

        print("  No image in response", flush=True)

    return None


def process_terrain(img_data, out_path):
    """Process terrain tile: center-crop to square, resize to TILE_SIZE."""
    from PIL import Image

    img = Image.open(io.BytesIO(img_data)).convert("RGB")

    # Center-crop to square
    w, h = img.width, img.height
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))

    # Resize to tile size
    img = img.resize((TILE_SIZE, TILE_SIZE), Image.LANCZOS)

    img.save(out_path)
    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Saved: {out_path} ({size_kb:.0f}KB)")
    return True


def generate_terrain(api_key, terrain_id, preview=False):
    """Generate a single terrain tile."""
    if terrain_id not in TERRAIN_PROMPTS:
        print(f"Unknown terrain: {terrain_id}")
        return False

    prompt = f"{STYLE}\n\nTerrain: {TERRAIN_PROMPTS[terrain_id]}"

    if preview:
        os.makedirs(TMP_DIR, exist_ok=True)
        out_path = os.path.join(TMP_DIR, f"{terrain_id}.png")
    else:
        out_path = os.path.join(DATA_TERRAIN_DIR, f"{terrain_id}.png")

    print(f"Generating {terrain_id}...", flush=True)
    img_data = generate_image(api_key, prompt)

    if not img_data:
        print(f"  FAILED — no image generated")
        return False

    process_terrain(img_data, out_path)
    return True


def main():
    parser = argparse.ArgumentParser(description="Generate terrain tiles via Gemini")
    parser.add_argument("--terrain", help="Terrain ID to generate")
    parser.add_argument("--all", action="store_true", help="Generate all terrain tiles")
    parser.add_argument("--preview", action="store_true", help="Save to tmp/ instead of data/terrain/")
    parser.add_argument("--list", action="store_true", help="List available terrain types")
    args = parser.parse_args()

    if args.list:
        print("Available terrain types:")
        for tid in sorted(TERRAIN_PROMPTS.keys()):
            existing = os.path.exists(os.path.join(DATA_TERRAIN_DIR, f"{tid}.png"))
            marker = "  [exists]" if existing else ""
            print(f"  {tid}{marker}")
        return

    if not args.terrain and not args.all:
        parser.print_help()
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Set GEMINI_API_KEY environment variable")
        sys.exit(1)

    if args.all:
        passed, failed = [], []
        for tid in sorted(TERRAIN_PROMPTS.keys()):
            ok = generate_terrain(api_key, tid, preview=args.preview)
            (passed if ok else failed).append(tid)
            if tid != sorted(TERRAIN_PROMPTS.keys())[-1]:
                time.sleep(5)  # Rate limit buffer between tiles

        print(f"\nResults: {len(passed)} passed, {len(failed)} failed")
        if failed:
            print(f"Failed: {', '.join(failed)}")
    else:
        generate_terrain(api_key, args.terrain, preview=args.preview)


if __name__ == "__main__":
    main()
