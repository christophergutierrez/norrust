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

--- Clamp a value to the 0–1 range.
local function clamp01(v) return math.max(0, math.min(1, v)) end

-- ── Drawing primitives ─────────────────────────────────────────────────

--- Draw a filled ellipse onto pixel data at (cx, cy) with radii rx, ry.
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

--- Draw a filled rectangle onto pixel data at (x, y) with size w×h.
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

--- Draw a thick line between two points using ellipse stamping.
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

-- ── Weapon drawing functions ─────────────────────────────────────────

--- Draw a spear weapon (shaft + pointed tip) at the hand position.
local function weapon_spear(imageData, hx, hy, pose, colors, alpha)
    local shaft = colors.shaft or {0.50, 0.38, 0.22}
    local tip   = colors.tip   or {0.70, 0.72, 0.75}
    local wdx = pose.weapon_dx or 2
    local wdy = pose.weapon_dy or -90
    local ex, ey = hx + wdx, hy + wdy
    draw_line(imageData, hx, hy, ex, ey, 4, shaft[1], shaft[2], shaft[3], alpha)
    draw_ellipse(imageData, ex, ey, 4, 8, tip[1], tip[2], tip[3], alpha)
end

--- Draw a sword weapon (blade + crossguard) at the hand position.
local function weapon_sword(imageData, hx, hy, pose, colors, alpha)
    local blade = colors.blade or {0.75, 0.78, 0.80}
    local guard = colors.guard or {0.45, 0.35, 0.20}
    local wdx = pose.weapon_dx or 2
    local wdy = pose.weapon_dy or -60
    local ex, ey = hx + wdx, hy + wdy
    -- Blade
    draw_line(imageData, hx, hy, ex, ey, 5, blade[1], blade[2], blade[3], alpha)
    -- Crossguard
    local mx, my = hx + wdx * 0.1, hy + wdy * 0.1
    draw_line(imageData, mx - 8, my, mx + 8, my, 4, guard[1], guard[2], guard[3], alpha)
end

--- Draw a greatsword weapon (wide blade + large crossguard) at the hand position.
local function weapon_greatsword(imageData, hx, hy, pose, colors, alpha)
    local blade = colors.blade or {0.65, 0.68, 0.70}
    local guard = colors.guard or {0.40, 0.30, 0.18}
    local wdx = pose.weapon_dx or 2
    local wdy = pose.weapon_dy or -75
    local ex, ey = hx + wdx, hy + wdy
    draw_line(imageData, hx, hy, ex, ey, 7, blade[1], blade[2], blade[3], alpha)
    local mx, my = hx + wdx * 0.1, hy + wdy * 0.1
    draw_line(imageData, mx - 10, my, mx + 10, my, 5, guard[1], guard[2], guard[3], alpha)
end

--- Draw a bow weapon (curved limb + bowstring) at the hand position.
local function weapon_bow(imageData, hx, hy, pose, colors, alpha)
    local wood   = colors.wood   or {0.55, 0.38, 0.20}
    local string_c = colors.string or {0.80, 0.78, 0.72}
    local wdx = pose.weapon_dx or 0
    local wdy = pose.weapon_dy or -50
    -- Bow limb (curved via two lines)
    local top_x, top_y = hx + wdx * 0.2 - 5, hy + wdy
    local bot_x, bot_y = hx + wdx * 0.2 - 5, hy - wdy * 0.3
    local mid_x = hx + wdx - 12
    draw_line(imageData, top_x, top_y, mid_x, (top_y + bot_y) / 2, 4, wood[1], wood[2], wood[3], alpha)
    draw_line(imageData, mid_x, (top_y + bot_y) / 2, bot_x, bot_y, 4, wood[1], wood[2], wood[3], alpha)
    -- String
    draw_line(imageData, top_x, top_y, bot_x, bot_y, 2, string_c[1], string_c[2], string_c[3], alpha)
end

--- Draw a staff weapon (shaft + glowing orb) at the hand position.
local function weapon_staff(imageData, hx, hy, pose, colors, alpha)
    local shaft = colors.shaft or {0.45, 0.30, 0.18}
    local orb   = colors.orb   or {0.40, 0.60, 0.90}
    local wdx = pose.weapon_dx or 2
    local wdy = pose.weapon_dy or -85
    local ex, ey = hx + wdx, hy + wdy
    draw_line(imageData, hx, hy, ex, ey, 4, shaft[1], shaft[2], shaft[3], alpha)
    draw_ellipse(imageData, ex, ey, 7, 7, orb[1], orb[2], orb[3], alpha)
end

--- Draw a mace weapon (shaft + round head) at the hand position.
local function weapon_mace(imageData, hx, hy, pose, colors, alpha)
    local shaft = colors.shaft or {0.45, 0.35, 0.22}
    local head  = colors.head  or {0.55, 0.55, 0.58}
    local wdx = pose.weapon_dx or 2
    local wdy = pose.weapon_dy or -55
    local ex, ey = hx + wdx, hy + wdy
    draw_line(imageData, hx, hy, ex, ey, 4, shaft[1], shaft[2], shaft[3], alpha)
    draw_ellipse(imageData, ex, ey, 8, 8, head[1], head[2], head[3], alpha)
end

--- Draw a dagger weapon (short blade + small crossguard) at the hand position.
local function weapon_dagger(imageData, hx, hy, pose, colors, alpha)
    local blade = colors.blade or {0.72, 0.74, 0.76}
    local guard = colors.guard or {0.40, 0.30, 0.18}
    local wdx = pose.weapon_dx or 2
    local wdy = pose.weapon_dy or -30
    local ex, ey = hx + wdx, hy + wdy
    draw_line(imageData, hx, hy, ex, ey, 4, blade[1], blade[2], blade[3], alpha)
    local mx, my = hx + wdx * 0.15, hy + wdy * 0.15
    draw_line(imageData, mx - 5, my, mx + 5, my, 3, guard[1], guard[2], guard[3], alpha)
end

--- Draw a crossbow weapon (stock + limbs + string) at the hand position.
local function weapon_crossbow(imageData, hx, hy, pose, colors, alpha)
    local wood   = colors.wood   or {0.50, 0.35, 0.20}
    local string_c = colors.string or {0.78, 0.76, 0.70}
    local wdx = pose.weapon_dx or 15
    local wdy = pose.weapon_dy or -20
    local ex, ey = hx + wdx, hy + wdy
    -- Stock
    draw_line(imageData, hx, hy, ex, ey, 5, wood[1], wood[2], wood[3], alpha)
    -- Limbs
    draw_line(imageData, ex - 3, ey - 15, ex - 3, ey + 15, 4, wood[1], wood[2], wood[3], alpha)
    -- String
    draw_line(imageData, ex - 3, ey - 15, ex + 3, ey, 2, string_c[1], string_c[2], string_c[3], alpha)
    draw_line(imageData, ex - 3, ey + 15, ex + 3, ey, 2, string_c[1], string_c[2], string_c[3], alpha)
end

-- ── Generic humanoid drawing ─────────────────────────────────────────

--- Draw a full humanoid figure (legs, torso, head, arms, weapon) onto pixel data.
--- @param imageData ImageData Target pixel buffer.
--- @param ox number Horizontal anchor (center foot).
--- @param oy number Vertical anchor (ground level).
--- @param config table Body colors, scale, and weapon draw function.
--- @param pose table Frame-specific offsets (lean, arm, leg, crouch, weapon).
local function draw_humanoid(imageData, ox, oy, config, pose)
    local lean = pose.body_lean or 0
    local arm_dx = pose.arm_dx or 0
    local arm_dy = pose.arm_dy or 0
    local leg_spread = pose.leg_spread or 0
    local crouch = pose.crouch or 0
    local alpha = pose.alpha or 1
    local scale = config.body_scale or 1.0

    local skin     = config.skin     or {0.82, 0.68, 0.55}
    local tunic    = config.tunic    or {0.45, 0.32, 0.22}
    local tunic_lt = config.tunic_lt or {0.55, 0.40, 0.28}
    local pants    = config.pants    or {0.35, 0.28, 0.20}
    local boots    = config.boots    or {0.25, 0.18, 0.12}
    local hair     = config.hair     or {0.30, 0.22, 0.15}

    -- Ground point
    local gx = ox + lean
    local gy = oy - 10

    -- Legs (scaled)
    local hip_y = gy - 55 * scale - crouch
    draw_line(imageData, gx - 8 - leg_spread, gy, gx - 4, hip_y, 10, pants[1], pants[2], pants[3], alpha)
    draw_line(imageData, gx + 8 + leg_spread, gy, gx + 4, hip_y, 10, pants[1], pants[2], pants[3], alpha)
    -- Boots
    draw_ellipse(imageData, gx - 8 - leg_spread, gy, 8, 5, boots[1], boots[2], boots[3], alpha)
    draw_ellipse(imageData, gx + 8 + leg_spread, gy, 8, 5, boots[1], boots[2], boots[3], alpha)

    -- Torso
    local torso_h = 50 * scale
    local torso_w = 32 * scale
    local torso_y = hip_y - torso_h * 0.9
    draw_rect(imageData, gx - torso_w / 2, torso_y, torso_w, torso_h, tunic[1], tunic[2], tunic[3], alpha)
    -- Tunic highlight stripe
    draw_rect(imageData, gx - 4, torso_y + 5, 8, torso_h - 10, tunic_lt[1], tunic_lt[2], tunic_lt[3], alpha)

    -- Head
    local head_y = torso_y - 22 * scale
    draw_ellipse(imageData, gx, head_y, 14, 16, skin[1], skin[2], skin[3], alpha)
    -- Hair
    draw_ellipse(imageData, gx, head_y - 6, 14, 10, hair[1], hair[2], hair[3], alpha)

    -- Right arm (weapon arm)
    local shoulder_x = gx + 14 * scale
    local shoulder_y = torso_y + 8
    local hand_x = shoulder_x + 10 + arm_dx
    local hand_y = shoulder_y + 20 + arm_dy
    draw_line(imageData, shoulder_x, shoulder_y, hand_x, hand_y, 8, skin[1], skin[2], skin[3], alpha)

    -- Weapon
    if config.draw_weapon then
        config.draw_weapon(imageData, hand_x, hand_y, pose, config.weapon_colors or {}, alpha)
    end

    -- Left arm (at side)
    local lshoulder_x = gx - 14 * scale
    local lshoulder_y = torso_y + 8
    draw_line(imageData, lshoulder_x, lshoulder_y, lshoulder_x - 6, lshoulder_y + 22, 8,
        skin[1], skin[2], skin[3], alpha)
end

-- ── Generic portrait drawing ─────────────────────────────────────────

--- Generate a portrait ImageData showing head, shoulders, and optional weapon hint.
--- @param config table Body colors and optional portrait_weapon draw function.
--- @return ImageData The rendered portrait pixel data.
local function draw_portrait_generic(config)
    local size = FRAME_SIZE
    local imageData = love.image.newImageData(size, size)

    local skin     = config.skin     or {0.82, 0.68, 0.55}
    local tunic    = config.tunic    or {0.45, 0.32, 0.22}
    local tunic_lt = config.tunic_lt or {0.55, 0.40, 0.28}
    local hair     = config.hair     or {0.30, 0.22, 0.15}

    local cx = size / 2
    local cy = size / 2 + 20

    -- Shoulders / torso upper
    draw_rect(imageData, cx - 50, cy + 10, 100, 80, tunic[1], tunic[2], tunic[3])
    draw_rect(imageData, cx - 10, cy + 15, 20, 70, tunic_lt[1], tunic_lt[2], tunic_lt[3])

    -- Neck
    draw_rect(imageData, cx - 8, cy - 5, 16, 20, skin[1], skin[2], skin[3])

    -- Head
    draw_ellipse(imageData, cx, cy - 30, 32, 38, skin[1], skin[2], skin[3])
    -- Hair
    draw_ellipse(imageData, cx, cy - 50, 32, 22, hair[1], hair[2], hair[3])

    -- Eyes
    draw_ellipse(imageData, cx - 10, cy - 30, 3, 3, 0.15, 0.12, 0.10)
    draw_ellipse(imageData, cx + 10, cy - 30, 3, 3, 0.15, 0.12, 0.10)

    -- Weapon hint on right side (if portrait_weapon provided)
    if config.portrait_weapon then
        config.portrait_weapon(imageData, cx, cy, config.weapon_colors or {})
    end

    return imageData
end

-- ── Portrait weapon hints ────────────────────────────────────────────

--- Draw a spear hint in the portrait margin.
local function portrait_spear(imageData, cx, cy, colors)
    local shaft = colors.shaft or {0.50, 0.38, 0.22}
    local tip   = colors.tip   or {0.70, 0.72, 0.75}
    draw_line(imageData, cx + 45, cy - 60, cx + 48, cy + 40, 5, shaft[1], shaft[2], shaft[3])
    draw_ellipse(imageData, cx + 46, cy - 65, 5, 10, tip[1], tip[2], tip[3])
end

--- Draw a sword hint in the portrait margin.
local function portrait_sword(imageData, cx, cy, colors)
    local blade = colors.blade or {0.75, 0.78, 0.80}
    local guard = colors.guard or {0.45, 0.35, 0.20}
    draw_line(imageData, cx + 40, cy - 55, cx + 44, cy + 20, 5, blade[1], blade[2], blade[3])
    draw_line(imageData, cx + 35, cy + 20, cx + 50, cy + 20, 4, guard[1], guard[2], guard[3])
end

--- Draw a bow hint in the portrait margin.
local function portrait_bow(imageData, cx, cy, colors)
    local wood = colors.wood or {0.55, 0.38, 0.20}
    draw_line(imageData, cx + 42, cy - 60, cx + 38, cy + 30, 4, wood[1], wood[2], wood[3])
    draw_line(imageData, cx + 42, cy - 60, cx + 50, cy - 15, 2, 0.80, 0.78, 0.72)
    draw_line(imageData, cx + 38, cy + 30, cx + 50, cy - 15, 2, 0.80, 0.78, 0.72)
end

--- Draw a staff hint in the portrait margin.
local function portrait_staff(imageData, cx, cy, colors)
    local shaft = colors.shaft or {0.45, 0.30, 0.18}
    local orb   = colors.orb   or {0.40, 0.60, 0.90}
    draw_line(imageData, cx + 42, cy - 55, cx + 46, cy + 40, 5, shaft[1], shaft[2], shaft[3])
    draw_ellipse(imageData, cx + 41, cy - 60, 9, 9, orb[1], orb[2], orb[3])
end

--- Draw a mace hint in the portrait margin.
local function portrait_mace(imageData, cx, cy, colors)
    local shaft = colors.shaft or {0.45, 0.35, 0.22}
    local head  = colors.head  or {0.55, 0.55, 0.58}
    draw_line(imageData, cx + 42, cy - 45, cx + 45, cy + 30, 5, shaft[1], shaft[2], shaft[3])
    draw_ellipse(imageData, cx + 41, cy - 50, 10, 10, head[1], head[2], head[3])
end

--- Draw a dagger hint in the portrait margin.
local function portrait_dagger(imageData, cx, cy, colors)
    local blade = colors.blade or {0.72, 0.74, 0.76}
    draw_line(imageData, cx + 42, cy - 20, cx + 45, cy + 15, 4, blade[1], blade[2], blade[3])
    draw_line(imageData, cx + 37, cy + 15, cx + 50, cy + 15, 3, 0.40, 0.30, 0.18)
end

--- Draw a crossbow hint in the portrait margin.
local function portrait_crossbow(imageData, cx, cy, colors)
    local wood = colors.wood or {0.50, 0.35, 0.20}
    draw_line(imageData, cx + 30, cy - 10, cx + 55, cy - 10, 5, wood[1], wood[2], wood[3])
    draw_line(imageData, cx + 55, cy - 25, cx + 55, cy + 5, 4, wood[1], wood[2], wood[3])
end

--- Draw a greatsword hint in the portrait margin.
local function portrait_greatsword(imageData, cx, cy, colors)
    local blade = colors.blade or {0.65, 0.68, 0.70}
    local guard = colors.guard or {0.40, 0.30, 0.18}
    draw_line(imageData, cx + 38, cy - 60, cx + 44, cy + 25, 7, blade[1], blade[2], blade[3])
    draw_line(imageData, cx + 33, cy + 25, cx + 52, cy + 25, 5, guard[1], guard[2], guard[3])
end

-- ── Animation frame factories ────────────────────────────────────────

-- Idle: subtle body sway (shared by all)
--- Return idle animation pose frames (subtle body sway).
local function make_idle_frames()
    return {
        {body_lean = 0, arm_dx = 0, arm_dy = 0, weapon_dx = 2, weapon_dy = -90, leg_spread = 0, crouch = 0},
        {body_lean = 1, arm_dx = 1, arm_dy = -1, weapon_dx = 3, weapon_dy = -88, leg_spread = 0, crouch = 0},
        {body_lean = 0, arm_dx = 0, arm_dy = 0, weapon_dx = 2, weapon_dy = -90, leg_spread = 0, crouch = 0},
        {body_lean = -1, arm_dx = -1, arm_dy = 1, weapon_dx = 1, weapon_dy = -92, leg_spread = 0, crouch = 0},
    }
end

-- Defend: brace → shield up → hold (shared by all)
--- Return defend animation pose frames (brace and shield up).
local function make_defend_frames()
    return {
        {body_lean = -2, arm_dx = -5, arm_dy = 0, weapon_dx = -10, weapon_dy = -70, leg_spread = 4, crouch = 5},
        {body_lean = -4, arm_dx = -10, arm_dy = -5, weapon_dx = -15, weapon_dy = -60, leg_spread = 6, crouch = 8},
        {body_lean = -3, arm_dx = -8, arm_dy = -3, weapon_dx = -12, weapon_dy = -65, leg_spread = 5, crouch = 7},
    }
end

-- Death: stagger → fall (shared by all)
--- Return death animation pose frames (stagger and fall with fade).
local function make_death_frames()
    return {
        {body_lean = 3, arm_dx = 5, arm_dy = 5, weapon_dx = 10, weapon_dy = -70, leg_spread = 2, crouch = 3, alpha = 1},
        {body_lean = 8, arm_dx = 12, arm_dy = 15, weapon_dx = 25, weapon_dy = -40, leg_spread = 4, crouch = 8, alpha = 0.9},
        {body_lean = 15, arm_dx = 18, arm_dy = 25, weapon_dx = 40, weapon_dy = -10, leg_spread = 6, crouch = 15, alpha = 0.7},
        {body_lean = 22, arm_dx = 20, arm_dy = 35, weapon_dx = 50, weapon_dy = 10, leg_spread = 8, crouch = 25, alpha = 0.5},
    }
end

-- Melee thrust: wind up → thrust → recover (spear-style)
--- Return melee thrust pose frames (wind up, thrust forward, recover).
local function make_melee_thrust_frames()
    return {
        {body_lean = -3, arm_dx = -8, arm_dy = -5, weapon_dx = -10, weapon_dy = -85, leg_spread = 2, crouch = 0},
        {body_lean = -5, arm_dx = -12, arm_dy = -10, weapon_dx = -20, weapon_dy = -70, leg_spread = 4, crouch = 2},
        {body_lean = 5, arm_dx = 15, arm_dy = 5, weapon_dx = 40, weapon_dy = -30, leg_spread = 6, crouch = 4},
        {body_lean = 8, arm_dx = 25, arm_dy = 10, weapon_dx = 55, weapon_dy = -10, leg_spread = 8, crouch = 5},
        {body_lean = 4, arm_dx = 15, arm_dy = 5, weapon_dx = 35, weapon_dy = -25, leg_spread = 5, crouch = 3},
        {body_lean = 0, arm_dx = 0, arm_dy = 0, weapon_dx = 2, weapon_dy = -90, leg_spread = 0, crouch = 0},
    }
end

-- Melee swing: wind up → slash → recover (sword/mace/dagger-style)
--- Return melee swing pose frames (wind up, slash arc, recover).
local function make_melee_swing_frames()
    return {
        {body_lean = -2, arm_dx = -5, arm_dy = -15, weapon_dx = -5, weapon_dy = -55, leg_spread = 2, crouch = 0},
        {body_lean = -4, arm_dx = -10, arm_dy = -20, weapon_dx = -10, weapon_dy = -50, leg_spread = 4, crouch = 2},
        {body_lean = 3, arm_dx = 20, arm_dy = -5, weapon_dx = 35, weapon_dy = -20, leg_spread = 5, crouch = 3},
        {body_lean = 6, arm_dx = 25, arm_dy = 10, weapon_dx = 40, weapon_dy = 15, leg_spread = 7, crouch = 4},
        {body_lean = 3, arm_dx = 15, arm_dy = 5, weapon_dx = 25, weapon_dy = -10, leg_spread = 4, crouch = 2},
        {body_lean = 0, arm_dx = 0, arm_dy = 0, weapon_dx = 2, weapon_dy = -60, leg_spread = 0, crouch = 0},
    }
end

-- Ranged throw: raise → throw (javelin/knives)
--- Return ranged throw pose frames (raise and throw javelin/knives).
local function make_ranged_throw_frames()
    return {
        {body_lean = -2, arm_dx = -5, arm_dy = -15, weapon_dx = 0, weapon_dy = -80, leg_spread = 2, crouch = 0},
        {body_lean = -4, arm_dx = -8, arm_dy = -25, weapon_dx = -5, weapon_dy = -65, leg_spread = 4, crouch = 2},
        {body_lean = 6, arm_dx = 20, arm_dy = -10, weapon_dx = 45, weapon_dy = -40, leg_spread = 6, crouch = 3},
        {body_lean = 2, arm_dx = 25, arm_dy = 5, weapon_dx = 0, weapon_dy = 0, leg_spread = 2, crouch = 0},
    }
end

-- Ranged draw: nock → draw → release (bow)
--- Return ranged bow draw pose frames (nock, draw, release).
local function make_ranged_draw_frames()
    return {
        {body_lean = -1, arm_dx = 5, arm_dy = -5, weapon_dx = 10, weapon_dy = -50, leg_spread = 2, crouch = 0},
        {body_lean = -2, arm_dx = 8, arm_dy = -10, weapon_dx = 15, weapon_dy = -55, leg_spread = 3, crouch = 1},
        {body_lean = 0, arm_dx = 12, arm_dy = -8, weapon_dx = 20, weapon_dy = -50, leg_spread = 4, crouch = 2},
        {body_lean = 1, arm_dx = 5, arm_dy = 0, weapon_dx = 8, weapon_dy = -45, leg_spread = 2, crouch = 0},
    }
end

-- Ranged cast: charge → release (staff/missile)
--- Return ranged cast pose frames (charge staff and release).
local function make_ranged_cast_frames()
    return {
        {body_lean = -1, arm_dx = -3, arm_dy = -10, weapon_dx = 0, weapon_dy = -85, leg_spread = 2, crouch = 0},
        {body_lean = -3, arm_dx = -5, arm_dy = -20, weapon_dx = -5, weapon_dy = -80, leg_spread = 3, crouch = 2},
        {body_lean = 2, arm_dx = 15, arm_dy = -15, weapon_dx = 30, weapon_dy = -60, leg_spread = 5, crouch = 3},
        {body_lean = 0, arm_dx = 5, arm_dy = 0, weapon_dx = 5, weapon_dy = -85, leg_spread = 2, crouch = 0},
    }
end

-- Ranged crossbow: aim → fire
--- Return ranged crossbow pose frames (aim and fire).
local function make_ranged_crossbow_frames()
    return {
        {body_lean = 0, arm_dx = 8, arm_dy = -5, weapon_dx = 20, weapon_dy = -15, leg_spread = 2, crouch = 1},
        {body_lean = -1, arm_dx = 10, arm_dy = -8, weapon_dx = 25, weapon_dy = -18, leg_spread = 3, crouch = 2},
        {body_lean = 1, arm_dx = 12, arm_dy = -3, weapon_dx = 28, weapon_dy = -12, leg_spread = 3, crouch = 2},
        {body_lean = 0, arm_dx = 5, arm_dy = 0, weapon_dx = 15, weapon_dy = -10, leg_spread = 2, crouch = 0},
    }
end

-- ── Spritesheet generator ──────────────────────────────────────────────

--- Render a horizontal spritesheet from a list of pose frames.
--- @param frames table List of pose tables for each animation frame.
--- @param frame_w number Width of each frame in pixels.
--- @param frame_h number Height of each frame in pixels.
--- @param config table Humanoid config (colors, scale, weapon).
--- @return ImageData The rendered spritesheet pixel data.
local function generate_spritesheet(frames, frame_w, frame_h, config)
    local total_w = frame_w * #frames
    local imageData = love.image.newImageData(total_w, frame_h)

    local anchor_x = frame_w / 2
    local anchor_y = frame_h - 20

    for i, pose in ipairs(frames) do
        local ox = (i - 1) * frame_w + anchor_x
        draw_humanoid(imageData, ox, anchor_y, config, pose)
    end

    return imageData
end

-- ── Unit definitions ───────────────────────────────────────────────────

local UNITS = {
    -- ── Loyalists ────────────────────────────────────────────────────
    {
        def_id = "Spearman",
        config = {
            skin = {0.82, 0.68, 0.55}, tunic = {0.45, 0.32, 0.22}, tunic_lt = {0.55, 0.40, 0.28},
            pants = {0.35, 0.28, 0.20}, boots = {0.25, 0.18, 0.12}, hair = {0.30, 0.22, 0.15},
            body_scale = 1.0,
            draw_weapon = weapon_spear,
            weapon_colors = {shaft = {0.50, 0.38, 0.22}, tip = {0.70, 0.72, 0.75}},
            portrait_weapon = portrait_spear,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_thrust_frames,  count = 6},
            {name = "attack-ranged",  frames = make_ranged_throw_frames,  count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
    {
        def_id = "Lieutenant",
        config = {
            skin = {0.80, 0.66, 0.52}, tunic = {0.22, 0.30, 0.55}, tunic_lt = {0.30, 0.40, 0.65},
            pants = {0.25, 0.22, 0.35}, boots = {0.20, 0.15, 0.10}, hair = {0.25, 0.18, 0.12},
            body_scale = 1.05,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.78, 0.80, 0.82}, guard = {0.50, 0.40, 0.25}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,           count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,    count = 6},
            {name = "attack-ranged",  frames = make_ranged_crossbow_frames, count = 4},
            {name = "defend",         frames = make_defend_frames,         count = 3},
            {name = "death",          frames = make_death_frames,          count = 4},
        },
        ranged_config = {
            draw_weapon = weapon_crossbow,
            weapon_colors = {wood = {0.50, 0.35, 0.20}, string = {0.78, 0.76, 0.70}},
        },
    },
    {
        def_id = "Bowman",
        config = {
            skin = {0.80, 0.67, 0.53}, tunic = {0.30, 0.45, 0.28}, tunic_lt = {0.40, 0.55, 0.35},
            pants = {0.32, 0.30, 0.22}, boots = {0.22, 0.16, 0.10}, hair = {0.35, 0.25, 0.15},
            body_scale = 0.95,
            draw_weapon = weapon_bow,
            weapon_colors = {wood = {0.55, 0.38, 0.20}, string = {0.80, 0.78, 0.72}},
            portrait_weapon = portrait_bow,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_draw_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
        melee_config = {
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.72, 0.74, 0.76}, guard = {0.42, 0.32, 0.20}},
        },
    },
    {
        def_id = "Cavalryman",
        config = {
            skin = {0.82, 0.68, 0.55}, tunic = {0.55, 0.18, 0.15}, tunic_lt = {0.65, 0.25, 0.20},
            pants = {0.30, 0.22, 0.18}, boots = {0.22, 0.16, 0.10}, hair = {0.28, 0.20, 0.12},
            body_scale = 1.1,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.76, 0.78, 0.80}, guard = {0.48, 0.38, 0.22}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
    {
        def_id = "Mage",
        config = {
            skin = {0.85, 0.72, 0.60}, tunic = {0.40, 0.22, 0.50}, tunic_lt = {0.50, 0.30, 0.60},
            pants = {0.30, 0.20, 0.38}, boots = {0.20, 0.14, 0.25}, hair = {0.60, 0.55, 0.50},
            body_scale = 0.95,
            draw_weapon = weapon_staff,
            weapon_colors = {shaft = {0.45, 0.30, 0.18}, orb = {0.50, 0.30, 0.80}},
            portrait_weapon = portrait_staff,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_thrust_frames,  count = 6},
            {name = "attack-ranged",  frames = make_ranged_cast_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
    {
        def_id = "Heavy Infantryman",
        config = {
            skin = {0.78, 0.64, 0.50}, tunic = {0.50, 0.50, 0.52}, tunic_lt = {0.58, 0.58, 0.60},
            pants = {0.38, 0.36, 0.34}, boots = {0.28, 0.26, 0.24}, hair = {0.22, 0.16, 0.10},
            body_scale = 1.15,
            draw_weapon = weapon_mace,
            weapon_colors = {shaft = {0.45, 0.35, 0.22}, head = {0.58, 0.58, 0.60}},
            portrait_weapon = portrait_mace,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
    {
        def_id = "Sergeant",
        config = {
            skin = {0.80, 0.66, 0.52}, tunic = {0.18, 0.22, 0.40}, tunic_lt = {0.25, 0.30, 0.50},
            pants = {0.22, 0.20, 0.30}, boots = {0.18, 0.14, 0.10}, hair = {0.32, 0.24, 0.16},
            body_scale = 1.0,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.74, 0.76, 0.78}, guard = {0.46, 0.36, 0.22}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,           count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,    count = 6},
            {name = "attack-ranged",  frames = make_ranged_crossbow_frames, count = 4},
            {name = "defend",         frames = make_defend_frames,         count = 3},
            {name = "death",          frames = make_death_frames,          count = 4},
        },
        ranged_config = {
            draw_weapon = weapon_crossbow,
            weapon_colors = {wood = {0.48, 0.33, 0.18}, string = {0.76, 0.74, 0.68}},
        },
    },

    -- ── Elves ────────────────────────────────────────────────────────
    {
        def_id = "Elvish Captain",
        config = {
            skin = {0.88, 0.78, 0.65}, tunic = {0.28, 0.45, 0.30}, tunic_lt = {0.40, 0.58, 0.42},
            pants = {0.25, 0.35, 0.25}, boots = {0.18, 0.25, 0.16}, hair = {0.70, 0.65, 0.40},
            body_scale = 1.0,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.80, 0.82, 0.85}, guard = {0.55, 0.50, 0.30}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_draw_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
        ranged_config = {
            draw_weapon = weapon_bow,
            weapon_colors = {wood = {0.50, 0.40, 0.22}, string = {0.82, 0.80, 0.74}},
        },
    },
    {
        def_id = "Elvish Fighter",
        config = {
            skin = {0.88, 0.78, 0.65}, tunic = {0.35, 0.52, 0.35}, tunic_lt = {0.45, 0.62, 0.45},
            pants = {0.28, 0.38, 0.28}, boots = {0.18, 0.24, 0.15}, hair = {0.65, 0.58, 0.32},
            body_scale = 0.95,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.78, 0.80, 0.82}, guard = {0.50, 0.45, 0.28}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_draw_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
        ranged_config = {
            draw_weapon = weapon_bow,
            weapon_colors = {wood = {0.48, 0.38, 0.20}, string = {0.80, 0.78, 0.72}},
        },
    },
    {
        def_id = "Elvish Archer",
        config = {
            skin = {0.86, 0.76, 0.63}, tunic = {0.25, 0.42, 0.28}, tunic_lt = {0.35, 0.52, 0.38},
            pants = {0.22, 0.32, 0.22}, boots = {0.16, 0.22, 0.14}, hair = {0.55, 0.48, 0.28},
            body_scale = 0.9,
            draw_weapon = weapon_bow,
            weapon_colors = {wood = {0.52, 0.38, 0.22}, string = {0.80, 0.78, 0.72}},
            portrait_weapon = portrait_bow,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_draw_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
        melee_config = {
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.74, 0.76, 0.78}, guard = {0.46, 0.40, 0.25}},
        },
    },
    {
        def_id = "Elvish Scout",
        config = {
            skin = {0.86, 0.76, 0.63}, tunic = {0.50, 0.45, 0.30}, tunic_lt = {0.60, 0.55, 0.38},
            pants = {0.35, 0.32, 0.22}, boots = {0.22, 0.20, 0.14}, hair = {0.58, 0.50, 0.30},
            body_scale = 0.9,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.76, 0.78, 0.80}, guard = {0.48, 0.42, 0.26}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_draw_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
        ranged_config = {
            draw_weapon = weapon_bow,
            weapon_colors = {wood = {0.50, 0.38, 0.20}, string = {0.80, 0.78, 0.72}},
        },
    },
    {
        def_id = "Elvish Shaman",
        config = {
            skin = {0.88, 0.78, 0.65}, tunic = {0.80, 0.78, 0.70}, tunic_lt = {0.88, 0.85, 0.78},
            pants = {0.60, 0.58, 0.50}, boots = {0.40, 0.36, 0.28}, hair = {0.75, 0.68, 0.42},
            body_scale = 0.9,
            draw_weapon = weapon_staff,
            weapon_colors = {shaft = {0.50, 0.40, 0.25}, orb = {0.40, 0.75, 0.45}},
            portrait_weapon = portrait_staff,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_thrust_frames,  count = 6},
            {name = "attack-ranged",  frames = make_ranged_cast_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },

    -- ── Orcs ─────────────────────────────────────────────────────────
    {
        def_id = "Orcish Warrior",
        config = {
            skin = {0.45, 0.55, 0.35}, tunic = {0.35, 0.28, 0.18}, tunic_lt = {0.42, 0.34, 0.22},
            pants = {0.28, 0.22, 0.15}, boots = {0.20, 0.16, 0.10}, hair = {0.15, 0.12, 0.08},
            body_scale = 1.2,
            draw_weapon = weapon_greatsword,
            weapon_colors = {blade = {0.58, 0.60, 0.62}, guard = {0.35, 0.28, 0.15}},
            portrait_weapon = portrait_greatsword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
    {
        def_id = "Orcish Grunt",
        config = {
            skin = {0.48, 0.58, 0.38}, tunic = {0.38, 0.30, 0.20}, tunic_lt = {0.45, 0.36, 0.24},
            pants = {0.30, 0.24, 0.16}, boots = {0.22, 0.18, 0.12}, hair = {0.18, 0.14, 0.08},
            body_scale = 1.1,
            draw_weapon = weapon_sword,
            weapon_colors = {blade = {0.62, 0.64, 0.66}, guard = {0.38, 0.30, 0.18}},
            portrait_weapon = portrait_sword,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
    {
        def_id = "Orcish Archer",
        config = {
            skin = {0.45, 0.55, 0.35}, tunic = {0.32, 0.38, 0.22}, tunic_lt = {0.40, 0.45, 0.28},
            pants = {0.26, 0.28, 0.18}, boots = {0.20, 0.18, 0.12}, hair = {0.16, 0.13, 0.08},
            body_scale = 1.0,
            draw_weapon = weapon_bow,
            weapon_colors = {wood = {0.42, 0.30, 0.16}, string = {0.70, 0.68, 0.62}},
            portrait_weapon = portrait_bow,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_draw_frames,   count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
        melee_config = {
            draw_weapon = weapon_dagger,
            weapon_colors = {blade = {0.60, 0.62, 0.64}, guard = {0.35, 0.28, 0.15}},
        },
    },
    {
        def_id = "Orcish Assassin",
        config = {
            skin = {0.42, 0.52, 0.32}, tunic = {0.15, 0.14, 0.12}, tunic_lt = {0.22, 0.20, 0.18},
            pants = {0.12, 0.11, 0.10}, boots = {0.10, 0.09, 0.07}, hair = {0.10, 0.08, 0.06},
            body_scale = 0.95,
            draw_weapon = weapon_dagger,
            weapon_colors = {blade = {0.65, 0.67, 0.68}, guard = {0.32, 0.26, 0.15}},
            portrait_weapon = portrait_dagger,
        },
        anims = {
            {name = "idle",           frames = make_idle_frames,          count = 4},
            {name = "attack-melee",   frames = make_melee_swing_frames,   count = 6},
            {name = "attack-ranged",  frames = make_ranged_throw_frames,  count = 4},
            {name = "defend",         frames = make_defend_frames,        count = 3},
            {name = "death",          frames = make_death_frames,         count = 4},
        },
    },
}

--- Normalize a def_id to snake_case directory name.
local function normalize_dir(def_id)
    return def_id:lower():gsub(" ", "_")
end

-- ── Main generator ─────────────────────────────────────────────────────

--- Generate all unit spritesheets and portraits, writing PNGs to assets/units/.
local function run_generator()
    love.filesystem.createDirectory("assets")
    love.filesystem.createDirectory("assets/units")

    local total = 0
    for _, unit in ipairs(UNITS) do
        local dir = "assets/units/" .. normalize_dir(unit.def_id)
        love.filesystem.createDirectory(dir)

        for _, anim in ipairs(unit.anims) do
            -- Determine which config to use for this animation
            local cfg = unit.config
            if anim.name == "attack-melee" and unit.melee_config then
                -- Use alternate melee weapon (e.g., Bowman uses sword for melee)
                cfg = {}
                for k, v in pairs(unit.config) do cfg[k] = v end
                cfg.draw_weapon = unit.melee_config.draw_weapon
                cfg.weapon_colors = unit.melee_config.weapon_colors
            elseif anim.name == "attack-ranged" and unit.ranged_config then
                -- Use alternate ranged weapon (e.g., Lieutenant uses crossbow for ranged)
                cfg = {}
                for k, v in pairs(unit.config) do cfg[k] = v end
                cfg.draw_weapon = unit.ranged_config.draw_weapon
                cfg.weapon_colors = unit.ranged_config.weapon_colors
            end

            local frames = anim.frames()
            local imageData = generate_spritesheet(frames, FRAME_SIZE, FRAME_SIZE, cfg)
            local fileData = imageData:encode("png")
            local path = dir .. "/" .. anim.name .. ".png"
            love.filesystem.write(path, fileData)
            total = total + 1
            print(string.format("  [%s] %s (%d frames, %dx%d)",
                unit.def_id, anim.name, anim.count,
                FRAME_SIZE * anim.count, FRAME_SIZE))
        end

        -- Portrait
        local portraitData = draw_portrait_generic(unit.config)
        local portraitFile = portraitData:encode("png")
        love.filesystem.write(dir .. "/portrait.png", portraitFile)
        total = total + 1
        print(string.format("  [%s] portrait (%dx%d)", unit.def_id, FRAME_SIZE, FRAME_SIZE))
    end

    print(string.format("\nGenerated %d sprite files for %d units", total, #UNITS))
    print("Save directory: " .. love.filesystem.getSaveDirectory())
    return total
end

return {
    UNITS = UNITS,
    run = run_generator,
}
