#!/usr/bin/env bash
# generate_ai_sprites.sh — AI sprite generation pipeline for The Clash for Norrust
#
# Uses Gemini 2.0 Flash image generation API to create unit sprites.
# Generates individual frames per animation state, removes backgrounds via
# ImageMagick flood-fill, and assembles horizontal spritesheets.
#
# Prerequisites:
#   - GEMINI_API_KEY environment variable set
#   - ImageMagick 7+ (magick, montage, identify commands)
#   - python3 with stdlib (urllib, json, base64)
#
# Usage:
#   ./generate_ai_sprites.sh <unit_name>
#
# Example:
#   ./generate_ai_sprites.sh mage
#
# The script reads sprite.toml from the unit's asset directory to determine
# animation states and frame counts. Generated sprites are placed directly
# into the unit's asset directory, replacing existing files.
#
# Pipeline steps:
#   1. Parse sprite.toml for animation states + frame counts
#   2. Generate individual frames via Gemini API (one API call per frame)
#   3. Remove background via flood-fill from corners (ImageMagick)
#   4. Resize/pad each frame to 256x256 with transparent background
#   5. Assemble frames into horizontal spritesheets (montage)
#   6. Verify output dimensions match sprite.toml spec

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ASSETS_DIR="$(cd "$SCRIPT_DIR/../assets/units" && pwd)"

# ── Config ──────────────────────────────────────────────────────────────

GEMINI_MODEL="gemini-2.0-flash-exp-image-generation"
GEMINI_URL="https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent"
FRAME_SIZE=256
FUZZ_PERCENT=20    # background removal sensitivity (lower = more conservative)
PORTRAIT_FUZZ=8    # lower fuzz for portraits to preserve white hair/beards
RATE_LIMIT_SEC=1   # seconds between API calls

# ── Prompt Templates ────────────────────────────────────────────────────
#
# Each unit needs a BASE_DESC that describes the character's appearance.
# Animation-specific suffixes are appended to create per-frame prompts.
#
# Key prompt engineering notes:
# - "white background" or "plain white background" works best for background removal
# - "facing to the right" ensures correct game orientation (game flips for left-facing)
# - "full body visible from head to feet" prevents cropping
# - "2D game character sprite" / "painterly game sprite style" gets best results
# - Describe specific pose details for each frame to get animation progression
# - Include the character's distinctive features in every prompt for consistency

# ── Functions ───────────────────────────────────────────────────────────

generate_frame() {
    local prompt="$1"
    local output_path="$2"
    local retries=2

    for attempt in $(seq 0 "$retries"); do
        local response
        response=$(curl -s "${GEMINI_URL}?key=${GEMINI_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "$(python3 -c "
import json
print(json.dumps({
    'contents': [{'parts': [{'text': 'Generate an image: $prompt'}]}],
    'generationConfig': {'responseModalities': ['TEXT', 'IMAGE']}
}))
")")

        # Extract base64 image data from response
        local img_data
        img_data=$(echo "$response" | python3 -c "
import sys, json, base64
d = json.load(sys.stdin)
parts = d.get('candidates', [{}])[0].get('content', {}).get('parts', [])
for p in parts:
    if 'inlineData' in p:
        sys.stdout.buffer.write(base64.b64decode(p['inlineData']['data']))
        sys.exit(0)
sys.exit(1)
" 2>/dev/null > "$output_path")

        if [ $? -eq 0 ] && [ -s "$output_path" ]; then
            echo "  Generated: $(basename "$output_path")"
            return 0
        fi

        echo "  Retry $((attempt + 1))..."
        sleep 3
    done

    echo "  FAILED: $(basename "$output_path")"
    return 1
}

remove_background() {
    local input="$1"
    local output="$2"
    local fuzz="${3:-$FUZZ_PERCENT}"

    # Flood-fill from all four corners to remove background
    # This preserves interior detail (unlike global color replace)
    magick "$input" \
        -alpha set \
        -fuzz "${fuzz}%" \
        -fill none \
        -draw "color 0,0 floodfill" \
        -draw "color 0,%[fx:h-1] floodfill" \
        -draw "color %[fx:w-1],0 floodfill" \
        -draw "color %[fx:w-1],%[fx:h-1] floodfill" \
        -trim +repage \
        -resize "${FRAME_SIZE}x${FRAME_SIZE}" \
        -gravity center \
        -background none \
        -extent "${FRAME_SIZE}x${FRAME_SIZE}" \
        "$output"
}

assemble_spritesheet() {
    local output="$1"
    shift
    local frames=("$@")
    local n=${#frames[@]}

    montage "${frames[@]}" \
        -tile "${n}x1" \
        -geometry "${FRAME_SIZE}x${FRAME_SIZE}+0+0" \
        -background none \
        "$output"

    echo "  Assembled: $(identify "$output" | awk '{print $3}')"
}

# ── Main ────────────────────────────────────────────────────────────────

if [ $# -lt 1 ]; then
    echo "Usage: $0 <unit_name>"
    echo "Example: $0 mage"
    exit 1
fi

UNIT="$1"
UNIT_DIR="${ASSETS_DIR}/${UNIT}"
TOML_FILE="${UNIT_DIR}/sprite.toml"
TMP_DIR="${UNIT_DIR}/tmp"

if [ ! -f "$TOML_FILE" ]; then
    echo "ERROR: sprite.toml not found at $TOML_FILE"
    exit 1
fi

if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo "ERROR: GEMINI_API_KEY not set"
    exit 1
fi

mkdir -p "$TMP_DIR"

echo "=== Generating sprites for: $UNIT ==="
echo "  Asset dir: $UNIT_DIR"
echo "  Temp dir:  $TMP_DIR"
echo ""
echo "IMPORTANT: Edit the BASE_DESC and per-frame prompts in this script"
echo "for each unit before running. The prompts below are for the mage."
echo ""

# ── Mage-specific prompts (edit these per unit) ────────────────────────
#
# To adapt for another unit:
# 1. Change BASE_DESC to describe the new unit's appearance
# 2. Adjust animation-specific suffixes if the unit has different animations
# 3. For units without ranged attacks, skip attack-ranged generation
# 4. Run and iterate on prompts until quality is satisfactory

BASE_DESC="2D fantasy game character sprite on a plain white background. An elderly wizard mage facing to the right. He has a long flowing white beard, wears purple/violet ornate robes with gold trim and a tall pointed wizard hat. He holds a tall wooden staff in his right hand topped with a glowing purple crystal orb. Detailed painterly art style. Full body visible from head to feet, character centered."

# Animation states and their frame prompts
# Format: STATE_NAME FRAME_COUNT PROMPT_SUFFIX_1 | PROMPT_SUFFIX_2 | ...
#
# Read frame counts from sprite.toml (manual for now, automate in Phase 45+)

declare -A ANIMS
declare -A PROMPTS

ANIMS[idle]=4
PROMPTS[idle_0]="Standing idle neutral pose."
PROMPTS[idle_1]="Standing idle, staff crystal glowing brighter with magical sparkles."
PROMPTS[idle_2]="Standing idle, robes swaying gently in a breeze."
PROMPTS[idle_3]="Standing idle, head slightly tilted, contemplative expression."

ANIMS[attack-melee]=6
PROMPTS[attack-melee_0]="Beginning to raise staff overhead for a melee strike."
PROMPTS[attack-melee_1]="Staff raised high above head with both hands, winding up."
PROMPTS[attack-melee_2]="Mid-swing, staff sweeping forward and downward."
PROMPTS[attack-melee_3]="Full swing, staff extended forward at waist height, body lunging right."
PROMPTS[attack-melee_4]="Follow-through, staff low after a downward strike."
PROMPTS[attack-melee_5]="Recovering, pulling staff back to upright position."

ANIMS[attack-ranged]=4
PROMPTS[attack-ranged_0]="Preparing a spell, raising staff with crystal starting to glow intensely."
PROMPTS[attack-ranged_1]="Casting a ranged spell, staff crystal blazing with purple energy, left hand extended forward channeling magic."
PROMPTS[attack-ranged_2]="Spell release, a bolt of purple magical energy shooting from extended hand toward the right."
PROMPTS[attack-ranged_3]="After casting, lowering staff, purple magic fading from hands."

ANIMS[defend]=3
PROMPTS[defend_0]="Defensive stance, pulling staff close to body, crouching slightly."
PROMPTS[defend_1]="Full defense, staff held horizontally as a shield, a shimmering purple magical barrier surrounding character."
PROMPTS[defend_2]="Recovering from defense, straightening up, barrier fading away."

ANIMS[death]=4
PROMPTS[death_0]="Hit and staggering backward, staff tilting, pained expression."
PROMPTS[death_1]="Falling backward, staff slipping from grasp, robes billowing."
PROMPTS[death_2]="Nearly fallen, body at 45 degree angle to the ground, staff falling separately."
PROMPTS[death_3]="Collapsed on the ground lying on his back, staff fallen beside him, robes spread out, defeated."

ANIMS[portrait]=1
PROMPTS[portrait_0]="Close-up portrait on a plain white background. An elderly wizard mage with a long flowing white beard, kind wise eyes, wearing purple/violet ornate robes with gold trim and a tall pointed wizard hat. Glowing purple crystal staff visible at his shoulder. Detailed painterly fantasy game portrait style. Head and upper chest visible."

# ── Generate ────────────────────────────────────────────────────────────

for anim_name in idle attack-melee attack-ranged defend death portrait; do
    frame_count=${ANIMS[$anim_name]}
    echo ""
    echo "=== $anim_name ($frame_count frames) ==="

    proc_frames=()
    for i in $(seq 0 $((frame_count - 1))); do
        raw="${TMP_DIR}/${anim_name}_raw_${i}.png"
        proc="${TMP_DIR}/${anim_name}_proc_${i}.png"

        # Build full prompt
        if [ "$anim_name" = "portrait" ]; then
            prompt="${PROMPTS[${anim_name}_${i}]}"
        else
            prompt="${BASE_DESC} ${PROMPTS[${anim_name}_${i}]}"
        fi

        echo "  Frame $((i + 1))/$frame_count..."
        generate_frame "$prompt" "$raw"

        # Use lower fuzz for portrait (preserves white hair)
        local_fuzz=$FUZZ_PERCENT
        [ "$anim_name" = "portrait" ] && local_fuzz=$PORTRAIT_FUZZ
        remove_background "$raw" "$proc" "$local_fuzz"

        proc_frames+=("$proc")
        sleep "$RATE_LIMIT_SEC"
    done

    # Assemble spritesheet
    output="${UNIT_DIR}/${anim_name}.png"
    assemble_spritesheet "$output" "${proc_frames[@]}"
done

# ── Verify ──────────────────────────────────────────────────────────────

echo ""
echo "=== Verification ==="
for anim_name in idle attack-melee attack-ranged defend death portrait; do
    output="${UNIT_DIR}/${anim_name}.png"
    if [ -f "$output" ]; then
        dims=$(identify "$output" | awk '{print $3}')
        expected_w=$(( ${ANIMS[$anim_name]} * FRAME_SIZE ))
        expected="${expected_w}x${FRAME_SIZE}"
        if [ "$dims" = "$expected" ]; then
            echo "  OK: $anim_name = $dims"
        else
            echo "  MISMATCH: $anim_name = $dims (expected $expected)"
        fi
    else
        echo "  MISSING: $anim_name"
    fi
done

echo ""
echo "Done. Review sprites in-game: cd norrust_love && love ."
echo "Or in viewer: cd norrust_love && love . --viewer"
