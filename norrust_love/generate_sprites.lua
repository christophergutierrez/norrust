-- generate_sprites.lua — Programmatic unit sprite generator
-- Run with: cd norrust_love && love . --generate-sprites
-- Generates spritesheets + portrait for unit types

local FRAME_SIZE = 256

-- Simple seeded pseudo-random (same as generate_tiles.lua)
local function hash(x, y, seed)
    local n = x * 374761393 + y * 668265263 + seed * 1274126177
    n = bit.bxor(n, bit.rshift(n, 13))
    n = n * 1103515245 + 12345
    n = bit.bxor(n, bit.rshift(n, 16))
    return (n % 1000) / 1000
end

local function clamp01(v) return math.max(0, math.min(1, v)) end

-- ── Drawing primitives ─────────────────────────────────────────────────

local function draw_ellipse(imageData, cx, cy, rx, ry, r, g, b, a)
    a = a or 1
    local x0 = math.max(0, math.floor(cx - rx))
    local x1 = math.min(imageData:getWidth() - 1, math.ceil(cx + rx))
    local y0 = math.max(0, math.floor(cy - ry))
    local y1 = math.min(imageData:getHeight() - 1, math.ceil(cy + ry))
    for py = y0, y1 do
        for px = x0, x1 do
            local dx = (px - cx) / rx
            local dy = (py - cy) / ry
            if dx * dx + dy * dy <= 1 then
                imageData:setPixel(px, py, r, g, b, a)
            end
        end
    end
end

local function draw_rect(imageData, x, y, w, h, r, g, b, a)
    a = a or 1
    local x0 = math.max(0, math.floor(x))
    local x1 = math.min(imageData:getWidth() - 1, math.floor(x + w - 1))
    local y0 = math.max(0, math.floor(y))
    local y1 = math.min(imageData:getHeight() - 1, math.floor(y + h - 1))
    for py = y0, y1 do
        for px = x0, x1 do
            imageData:setPixel(px, py, r, g, b, a)
        end
    end
end

local function draw_line(imageData, x0, y0, x1, y1, thickness, r, g, b, a)
    a = a or 1
    local dx = x1 - x0
    local dy = y1 - y0
    local len = math.sqrt(dx * dx + dy * dy)
    if len < 1 then return end
    local steps = math.ceil(len * 2)
    for i = 0, steps do
        local t = i / steps
        local px = x0 + dx * t
        local py = y0 + dy * t
        draw_ellipse(imageData, px, py, thickness / 2, thickness / 2, r, g, b, a)
    end
end

-- ── Spearman figure drawing ────────────────────────────────────────────

-- Colors
local SKIN     = {0.82, 0.68, 0.55}
local TUNIC    = {0.45, 0.32, 0.22}
local TUNIC_LT = {0.55, 0.40, 0.28}
local PANTS    = {0.35, 0.28, 0.20}
local BOOT     = {0.25, 0.18, 0.12}
local SPEAR_SHAFT = {0.50, 0.38, 0.22}
local SPEAR_TIP   = {0.70, 0.72, 0.75}
local HAIR     = {0.30, 0.22, 0.15}
local OUTLINE  = {0.12, 0.10, 0.08}

--- Draw a single spearman figure on the imageData.
--- ox, oy: pixel offset for the figure's center-bottom (ground point).
--- pose table: {body_lean, arm_angle, spear_dx, spear_dy, leg_spread, crouch}
local function draw_spearman(imageData, ox, oy, pose)
    local lean = pose.body_lean or 0    -- horizontal body offset
    local arm_dx = pose.arm_dx or 0     -- arm extension
    local arm_dy = pose.arm_dy or 0
    local spear_dx = pose.spear_dx or 0
    local spear_dy = pose.spear_dy or -90
    local leg_spread = pose.leg_spread or 0
    local crouch = pose.crouch or 0
    local alpha = pose.alpha or 1

    -- Ground point
    local gx = ox + lean
    local gy = oy - 10

    -- Legs
    local hip_y = gy - 55 - crouch
    draw_line(imageData, gx - 8 - leg_spread, gy, gx - 4, hip_y, 10, PANTS[1], PANTS[2], PANTS[3], alpha)
    draw_line(imageData, gx + 8 + leg_spread, gy, gx + 4, hip_y, 10, PANTS[1], PANTS[2], PANTS[3], alpha)
    -- Boots
    draw_ellipse(imageData, gx - 8 - leg_spread, gy, 8, 5, BOOT[1], BOOT[2], BOOT[3], alpha)
    draw_ellipse(imageData, gx + 8 + leg_spread, gy, 8, 5, BOOT[1], BOOT[2], BOOT[3], alpha)

    -- Torso
    local torso_y = hip_y - 45
    draw_rect(imageData, gx - 16, torso_y, 32, 50, TUNIC[1], TUNIC[2], TUNIC[3], alpha)
    -- Tunic highlight stripe
    draw_rect(imageData, gx - 4, torso_y + 5, 8, 40, TUNIC_LT[1], TUNIC_LT[2], TUNIC_LT[3], alpha)

    -- Head
    local head_y = torso_y - 22
    draw_ellipse(imageData, gx, head_y, 14, 16, SKIN[1], SKIN[2], SKIN[3], alpha)
    -- Hair
    draw_ellipse(imageData, gx, head_y - 6, 14, 10, HAIR[1], HAIR[2], HAIR[3], alpha)

    -- Right arm (weapon arm) + spear
    local shoulder_x = gx + 14
    local shoulder_y = torso_y + 8
    local hand_x = shoulder_x + 10 + arm_dx
    local hand_y = shoulder_y + 20 + arm_dy
    draw_line(imageData, shoulder_x, shoulder_y, hand_x, hand_y, 8, SKIN[1], SKIN[2], SKIN[3], alpha)

    -- Spear shaft
    local spear_base_x = hand_x
    local spear_base_y = hand_y
    local spear_end_x = spear_base_x + spear_dx
    local spear_end_y = spear_base_y + spear_dy
    draw_line(imageData, spear_base_x, spear_base_y, spear_end_x, spear_end_y, 4,
        SPEAR_SHAFT[1], SPEAR_SHAFT[2], SPEAR_SHAFT[3], alpha)
    -- Spear tip
    draw_ellipse(imageData, spear_end_x, spear_end_y, 4, 8,
        SPEAR_TIP[1], SPEAR_TIP[2], SPEAR_TIP[3], alpha)

    -- Left arm (at side)
    local lshoulder_x = gx - 14
    local lshoulder_y = torso_y + 8
    draw_line(imageData, lshoulder_x, lshoulder_y, lshoulder_x - 6, lshoulder_y + 22, 8,
        SKIN[1], SKIN[2], SKIN[3], alpha)
end

-- ── Animation frame sets ───────────────────────────────────────────────

local function make_idle_frames()
    -- 4 frames: subtle body sway
    return {
        {body_lean = 0, arm_dx = 0, arm_dy = 0, spear_dx = 2, spear_dy = -90, leg_spread = 0, crouch = 0},
        {body_lean = 1, arm_dx = 1, arm_dy = -1, spear_dx = 3, spear_dy = -88, leg_spread = 0, crouch = 0},
        {body_lean = 0, arm_dx = 0, arm_dy = 0, spear_dx = 2, spear_dy = -90, leg_spread = 0, crouch = 0},
        {body_lean = -1, arm_dx = -1, arm_dy = 1, spear_dx = 1, spear_dy = -92, leg_spread = 0, crouch = 0},
    }
end

local function make_attack_melee_frames()
    -- 6 frames: wind up → thrust → recover
    return {
        {body_lean = -3, arm_dx = -8, arm_dy = -5, spear_dx = -10, spear_dy = -85, leg_spread = 2, crouch = 0},
        {body_lean = -5, arm_dx = -12, arm_dy = -10, spear_dx = -20, spear_dy = -70, leg_spread = 4, crouch = 2},
        {body_lean = 5, arm_dx = 15, arm_dy = 5, spear_dx = 40, spear_dy = -30, leg_spread = 6, crouch = 4},
        {body_lean = 8, arm_dx = 25, arm_dy = 10, spear_dx = 55, spear_dy = -10, leg_spread = 8, crouch = 5},
        {body_lean = 4, arm_dx = 15, arm_dy = 5, spear_dx = 35, spear_dy = -25, leg_spread = 5, crouch = 3},
        {body_lean = 0, arm_dx = 0, arm_dy = 0, spear_dx = 2, spear_dy = -90, leg_spread = 0, crouch = 0},
    }
end

local function make_attack_ranged_frames()
    -- 4 frames: arm raises → throw
    return {
        {body_lean = -2, arm_dx = -5, arm_dy = -15, spear_dx = 0, spear_dy = -80, leg_spread = 2, crouch = 0},
        {body_lean = -4, arm_dx = -8, arm_dy = -25, spear_dx = -5, spear_dy = -65, leg_spread = 4, crouch = 2},
        {body_lean = 6, arm_dx = 20, arm_dy = -10, spear_dx = 45, spear_dy = -40, leg_spread = 6, crouch = 3},
        {body_lean = 2, arm_dx = 25, arm_dy = 5, spear_dx = 0, spear_dy = 0, leg_spread = 2, crouch = 0},
    }
end

local function make_defend_frames()
    -- 3 frames: brace → shield up → hold
    return {
        {body_lean = -2, arm_dx = -5, arm_dy = 0, spear_dx = -10, spear_dy = -70, leg_spread = 4, crouch = 5},
        {body_lean = -4, arm_dx = -10, arm_dy = -5, spear_dx = -15, spear_dy = -60, leg_spread = 6, crouch = 8},
        {body_lean = -3, arm_dx = -8, arm_dy = -3, spear_dx = -12, spear_dy = -65, leg_spread = 5, crouch = 7},
    }
end

local function make_death_frames()
    -- 4 frames: stagger → fall
    return {
        {body_lean = 3, arm_dx = 5, arm_dy = 5, spear_dx = 10, spear_dy = -70, leg_spread = 2, crouch = 3, alpha = 1},
        {body_lean = 8, arm_dx = 12, arm_dy = 15, spear_dx = 25, spear_dy = -40, leg_spread = 4, crouch = 8, alpha = 0.9},
        {body_lean = 15, arm_dx = 18, arm_dy = 25, spear_dx = 40, spear_dy = -10, leg_spread = 6, crouch = 15, alpha = 0.7},
        {body_lean = 22, arm_dx = 20, arm_dy = 35, spear_dx = 50, spear_dy = 10, leg_spread = 8, crouch = 25, alpha = 0.5},
    }
end

-- ── Spritesheet generator ──────────────────────────────────────────────

local function generate_spritesheet(frames, frame_w, frame_h)
    local total_w = frame_w * #frames
    local imageData = love.image.newImageData(total_w, frame_h)

    -- Center-bottom anchor within each frame
    local anchor_x = frame_w / 2
    local anchor_y = frame_h - 20  -- 20px from bottom

    for i, pose in ipairs(frames) do
        local ox = (i - 1) * frame_w + anchor_x
        draw_spearman(imageData, ox, anchor_y, pose)
    end

    return imageData
end

local function generate_portrait()
    local size = FRAME_SIZE
    local imageData = love.image.newImageData(size, size)

    -- Larger close-up bust
    local cx = size / 2
    local cy = size / 2 + 20

    -- Shoulders / torso upper
    draw_rect(imageData, cx - 50, cy + 10, 100, 80, TUNIC[1], TUNIC[2], TUNIC[3])
    draw_rect(imageData, cx - 10, cy + 15, 20, 70, TUNIC_LT[1], TUNIC_LT[2], TUNIC_LT[3])

    -- Neck
    draw_rect(imageData, cx - 8, cy - 5, 16, 20, SKIN[1], SKIN[2], SKIN[3])

    -- Head
    draw_ellipse(imageData, cx, cy - 30, 32, 38, SKIN[1], SKIN[2], SKIN[3])
    -- Hair
    draw_ellipse(imageData, cx, cy - 50, 32, 22, HAIR[1], HAIR[2], HAIR[3])

    -- Eyes (simple dots)
    draw_ellipse(imageData, cx - 10, cy - 30, 3, 3, 0.15, 0.12, 0.10)
    draw_ellipse(imageData, cx + 10, cy - 30, 3, 3, 0.15, 0.12, 0.10)

    -- Spear tip peeking from side
    draw_line(imageData, cx + 45, cy - 60, cx + 48, cy + 40, 5,
        SPEAR_SHAFT[1], SPEAR_SHAFT[2], SPEAR_SHAFT[3])
    draw_ellipse(imageData, cx + 46, cy - 65, 5, 10,
        SPEAR_TIP[1], SPEAR_TIP[2], SPEAR_TIP[3])

    return imageData
end

-- ── Unit definitions ───────────────────────────────────────────────────

local UNITS = {
    {
        def_id = "Spearman",
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_attack_melee_frames,  count = 6},
            {name = "attack-ranged",  frames = make_attack_ranged_frames, count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
}

-- ── Main generator ─────────────────────────────────────────────────────

local function run_generator()
    love.filesystem.createDirectory("assets")
    love.filesystem.createDirectory("assets/units")

    local total = 0
    for _, unit in ipairs(UNITS) do
        local dir = "assets/units/" .. unit.def_id
        love.filesystem.createDirectory(dir)

        for _, anim in ipairs(unit.anims) do
            local frames = anim.frames()
            local imageData = generate_spritesheet(frames, FRAME_SIZE, FRAME_SIZE)
            local fileData = imageData:encode("png")
            local path = dir .. "/" .. anim.name .. ".png"
            love.filesystem.write(path, fileData)
            total = total + 1
            print(string.format("  [%s] %s (%d frames, %dx%d)",
                unit.def_id, anim.name, anim.count,
                FRAME_SIZE * anim.count, FRAME_SIZE))
        end

        -- Portrait
        local portraitData = generate_portrait()
        local portraitFile = portraitData:encode("png")
        love.filesystem.write(dir .. "/portrait.png", portraitFile)
        total = total + 1
        print(string.format("  [%s] portrait (%dx%d)", unit.def_id, FRAME_SIZE, FRAME_SIZE))
    end

    print(string.format("\nGenerated %d sprite files", total))
    print("Save directory: " .. love.filesystem.getSaveDirectory())
    return total
end

return {
    UNITS = UNITS,
    run = run_generator,
}
