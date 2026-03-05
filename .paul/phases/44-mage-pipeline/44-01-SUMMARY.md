---
phase: 44-mage-pipeline
plan: 01
subsystem: assets
tags: [gemini, imagen, imagemagick, sprites, ai-generation]

requires:
  - phase: 43-lua-documentation
    provides: documented codebase, stable sprite.toml format
provides:
  - AI-generated Mage sprites (6 files, all animation states + portrait)
  - Reusable sprite generation shell script
  - Validated pipeline: Gemini API → flood-fill bg removal → spritesheet assembly
affects: [45-pipeline-refinement, 46-full-unit-generation]

tech-stack:
  added: [gemini-2.0-flash-exp-image-generation API]
  patterns: [flood-fill background removal, white-background prompting]

key-files:
  created: [norrust_love/tools/generate_ai_sprites.sh]
  modified: [norrust_love/assets/units/mage/*.png]

key-decisions:
  - "Direct Gemini API instead of nana-banana MCP (MCP doesn't generate actual images)"
  - "White background prompts + flood-fill removal (green screen was unreliable)"
  - "Lower fuzz (8%) for portraits to preserve white beards"

patterns-established:
  - "Prompt template: BASE_DESC + per-frame pose suffix"
  - "Background removal: magick flood-fill from 4 corners, fuzz 20% general / 8% portrait"
  - "Spritesheet assembly: montage Nx1 with -background none"

duration: ~45min
completed: 2026-03-05
---

# Phase 44 Plan 01: Mage Pipeline Summary

**AI-generated Mage sprites via Gemini 2.0 Flash with ImageMagick post-processing pipeline**

## Performance

| Metric | Value |
|--------|-------|
| Duration | ~45min |
| Completed | 2026-03-05 |
| Tasks | 3 completed |
| Files modified | 7 (6 PNGs + 1 script) |
| API calls | 22 (21 frames + 1 test) |

## Acceptance Criteria Results

| Criterion | Status | Notes |
|-----------|--------|-------|
| AC-1: Pipeline Script Exists | Pass | generate_ai_sprites.sh created, syntax check passes |
| AC-2: Mage Sprites Match Spec | Pass | All 6 files match sprite.toml dimensions exactly |
| AC-3: Visual Quality Acceptable | Pass | User approved in-game rendering — "looked perfect" |

## Accomplishments

- **Gemini 2.0 Flash image generation pipeline** — direct API calls generating painterly fantasy sprites from text prompts
- **Flood-fill background removal** — corner-based flood-fill with ImageMagick preserves interior detail while cleanly removing backgrounds
- **6 Mage sprite files replaced** — idle (4f), attack-melee (6f), attack-ranged (4f), defend (3f), death (4f), portrait (1f) — all 256px frames
- **Reusable shell script** — `generate_ai_sprites.sh` documents full pipeline with per-unit prompt customization

## Files Created/Modified

| File | Change | Purpose |
|------|--------|---------|
| `norrust_love/assets/units/mage/idle.png` | Replaced | 4-frame idle spritesheet (1024×256) |
| `norrust_love/assets/units/mage/attack-melee.png` | Replaced | 6-frame melee attack spritesheet (1536×256) |
| `norrust_love/assets/units/mage/attack-ranged.png` | Replaced | 4-frame ranged attack spritesheet (1024×256) |
| `norrust_love/assets/units/mage/defend.png` | Replaced | 3-frame defend spritesheet (768×256) |
| `norrust_love/assets/units/mage/death.png` | Replaced | 4-frame death spritesheet (1024×256) |
| `norrust_love/assets/units/mage/portrait.png` | Replaced | 256×256 portrait close-up |
| `norrust_love/tools/generate_ai_sprites.sh` | Created | Reusable generation pipeline script |

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| Direct Gemini API (not MCP nana-banana) | MCP tool returns text suggestions, not actual images | Pipeline calls API directly via curl/python |
| White background + flood-fill | Green screen approach failed — AI generates inconsistent greens | Reliable bg removal from corners |
| Portrait fuzz 8% (vs 20% general) | 20% fuzz ate into white beard detail | Per-asset-type fuzz tuning needed |
| v1 raw images reprocessed (not v2 green screen) | v1 white-background images had better artistic quality | Kept first generation, improved post-processing |

## Deviations from Plan

### Summary

| Type | Count | Impact |
|------|-------|--------|
| Auto-fixed | 2 | Essential pipeline fixes |
| Deferred | 2 | Logged to STATE.md |

**Total impact:** Pipeline adjustments — no scope change.

### Auto-fixed Issues

**1. MCP tool non-functional for image generation**
- **Found during:** Task 1
- **Issue:** nana-banana MCP generate_image returns text suggestions, not binary images
- **Fix:** Switched to direct Gemini API via curl/python
- **Verification:** Successfully generated all 22 frames

**2. Background removal approach**
- **Found during:** Task 1 (after v1 white-background and v2 green-screen attempts)
- **Issue:** Global color replace (-transparent white) left artifacts; green screen was unreliable
- **Fix:** Corner flood-fill approach with per-type fuzz levels
- **Verification:** User confirmed "looked perfect" in-game

### Deferred Items

- Viewer shows old/broken sprites for some units (Phase 47)
- Board-position sprite flip looks odd with detailed AI sprites (v1.8+)

## Issues Encountered

| Issue | Resolution |
|-------|------------|
| nana-banana MCP doesn't generate images | Switched to direct Gemini 2.0 Flash API |
| Green screen bg inconsistent from AI | Switched to white bg + flood-fill |
| Portrait flood-fill ate white beard at fuzz 20% | Reduced to fuzz 8% for portraits |
| Only idle animation plays in gameplay | Known deferred issue (Phase 33) — combat triggers not wired |

## Next Phase Readiness

**Ready:**
- Working generation pipeline with proven prompts for mage archetype
- Shell script template ready for per-unit prompt customization
- Background removal technique validated

**Concerns:**
- Each unit needs custom BASE_DESC prompt — significant prompt engineering per unit
- Frame-to-frame consistency varies (inherent to per-frame AI generation)
- Portrait fuzz level may need tuning per unit based on hair/skin color

**Blockers:**
- None

---
*Phase: 44-mage-pipeline, Plan: 01*
*Completed: 2026-03-05*
