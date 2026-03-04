-- viewer.lua — Standalone asset viewer for The Clash for Norrust
-- Run with: cd norrust_love && love . --viewer
-- Browse terrain tiles and unit sprites, cycle animations, zoom, flip.

local assets = require("assets")
local anim_module = require("animation")
local toml_parser = require("toml_parser")

local viewer = {}

-- ── State ──────────────────────────────────────────────────────────────

local terrain_tiles = {}
local unit_sprites = {}
local asset_list = {}       -- {type="terrain"|"unit", id=string}
local selected_idx = 1
local zoom = 1.0
local flipped = false
local fonts = {}
local scroll_offset = 0     -- sidebar scroll

-- Unit animation state
local anim_state = nil
local anim_names = {}       -- available anim states for current unit
local anim_name_idx = 1

local SIDEBAR_W = 220
local ZOOM_MIN = 0.25
local ZOOM_MAX = 4.0

-- ── Hex math (for hex-clipped terrain preview) ─────────────────────────

local function hex_polygon(cx, cy, r)
    local pts = {}
    for i = 0, 5 do
        local angle = math.rad(30 + 60 * i)
        pts[#pts + 1] = cx + r * math.cos(angle)
        pts[#pts + 1] = cy + r * math.sin(angle)
    end
    return pts
end

-- ── Build asset list ───────────────────────────────────────────────────

local function build_asset_list()
    asset_list = {}

    -- Terrain tiles (sorted)
    local terrain_ids = {}
    for id in pairs(terrain_tiles) do
        terrain_ids[#terrain_ids + 1] = id
    end
    table.sort(terrain_ids)
    for _, id in ipairs(terrain_ids) do
        asset_list[#asset_list + 1] = {type = "terrain", id = id}
    end

    -- Unit sprites (sorted)
    local unit_ids = {}
    for id in pairs(unit_sprites) do
        unit_ids[#unit_ids + 1] = id
    end
    table.sort(unit_ids)
    for _, id in ipairs(unit_ids) do
        asset_list[#asset_list + 1] = {type = "unit", id = id}
    end
end

-- ── Select asset ───────────────────────────────────────────────────────

local function select_asset(idx)
    if idx < 1 then idx = 1 end
    if idx > #asset_list then idx = #asset_list end
    selected_idx = idx

    local item = asset_list[idx]
    if not item then return end

    -- Reset view
    zoom = 1.0
    flipped = false

    if item.type == "unit" then
        local entry = unit_sprites[item.id]
        -- Build anim names list
        anim_names = {}
        if entry and entry.anims then
            -- Always start with idle
            if entry.anims.idle then
                anim_names[#anim_names + 1] = "idle"
            end
            -- Add attack variants
            for key in pairs(entry.anims) do
                if key:match("^attack%-") then
                    anim_names[#anim_names + 1] = key
                end
            end
            if entry.anims.defend then
                anim_names[#anim_names + 1] = "defend"
            end
            if entry.anims.death then
                anim_names[#anim_names + 1] = "death"
            end
        end
        anim_name_idx = 1
        anim_state = anim_module.new_state()
        if #anim_names > 0 then
            anim_module.play(anim_state, anim_names[1])
        end
    else
        anim_state = nil
        anim_names = {}
        anim_name_idx = 1
    end
end

-- ── Lifecycle ──────────────────────────────────────────────────────────

function viewer.load()
    for _, size in ipairs({11, 12, 13, 14, 15, 18, 32}) do
        fonts[size] = love.graphics.newFont(size)
    end

    love.graphics.setBackgroundColor(0.12, 0.12, 0.14)

    terrain_tiles = assets.load_terrain_tiles("assets")
    unit_sprites = assets.load_unit_sprites("assets")
    build_asset_list()

    if #asset_list > 0 then
        select_asset(1)
    end
end

function viewer.update(dt)
    if anim_state then
        local item = asset_list[selected_idx]
        if item and item.type == "unit" then
            local entry = unit_sprites[item.id]
            if entry and entry.anims then
                anim_module.update(anim_state, entry.anims, dt)
            end
        end
    end
end

-- ── Drawing ────────────────────────────────────────────────────────────

local function draw_sidebar()
    local vp_w, vp_h = love.graphics.getDimensions()

    -- Background
    love.graphics.setColor(0.08, 0.08, 0.10, 0.95)
    love.graphics.rectangle("fill", 0, 0, SIDEBAR_W, vp_h)

    -- Title
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(1, 0.85, 0, 1)
    love.graphics.print("Asset Viewer", 10, 8)

    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.5, 0.5, 0.5)
    love.graphics.print(string.format("%d assets", #asset_list), 10, 28)

    local y = 50 - scroll_offset
    local item_h = 20
    local last_type = ""

    for i, item in ipairs(asset_list) do
        -- Section header
        if item.type ~= last_type then
            last_type = item.type
            if y >= 40 and y < vp_h then
                love.graphics.setFont(fonts[12])
                love.graphics.setColor(0.6, 0.6, 0.6)
                local header = item.type == "terrain" and "TERRAIN" or "UNITS"
                love.graphics.print(header, 10, y)
            end
            y = y + 18
        end

        -- Item
        if y >= 40 and y < vp_h then
            if i == selected_idx then
                love.graphics.setColor(0.2, 0.2, 0.3, 1)
                love.graphics.rectangle("fill", 2, y - 1, SIDEBAR_W - 4, item_h)
                love.graphics.setColor(1, 1, 0, 1)
            else
                love.graphics.setColor(0.85, 0.85, 0.85, 1)
            end
            love.graphics.setFont(fonts[13])
            love.graphics.print(item.id, 18, y)
        end
        y = y + item_h
    end

    -- Divider line
    love.graphics.setColor(0.3, 0.3, 0.35)
    love.graphics.line(SIDEBAR_W, 0, SIDEBAR_W, vp_h)
end

local function draw_terrain_preview(terrain_id)
    local vp_w, vp_h = love.graphics.getDimensions()
    local img = terrain_tiles[terrain_id]
    if not img then return end

    local iw, ih = img:getWidth(), img:getHeight()
    local area_w = vp_w - SIDEBAR_W
    local cx = SIDEBAR_W + area_w / 2

    -- Raw image preview (top half)
    local raw_scale = zoom * math.min(200 / iw, 200 / ih)
    local raw_x = cx - (iw * raw_scale) / 2
    local raw_y = 60
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(img, raw_x, raw_y, 0, raw_scale, raw_scale)

    -- Label
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.6, 0.6, 0.6)
    love.graphics.print("Raw image", raw_x, raw_y - 16)

    -- Hex-clipped preview (bottom half)
    local hex_r = 80 * zoom
    local hex_cx = cx
    local hex_cy = raw_y + ih * raw_scale + 40 + hex_r

    love.graphics.setColor(0.6, 0.6, 0.6)
    love.graphics.setFont(fonts[11])
    love.graphics.print("Hex clipped", hex_cx - 35, hex_cy - hex_r - 18)

    -- Draw hex outline
    love.graphics.setColor(0.4, 0.4, 0.4)
    love.graphics.setLineWidth(1)
    love.graphics.polygon("line", hex_polygon(hex_cx, hex_cy, hex_r))

    -- Stencil clip
    local stencil_fn = function()
        love.graphics.polygon("fill", hex_polygon(hex_cx, hex_cy, hex_r))
    end
    love.graphics.stencil(stencil_fn, "replace", 1)
    love.graphics.setStencilTest("greater", 0)

    local diameter = hex_r * 2
    local sx = diameter / iw
    local sy = diameter / ih
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(img, hex_cx - hex_r, hex_cy - hex_r, 0, sx, sy)

    love.graphics.setStencilTest()

    -- Metadata
    local my = hex_cy + hex_r + 20
    love.graphics.setFont(fonts[13])
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.print(string.format("Terrain: %s", terrain_id), SIDEBAR_W + 20, my)
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.7, 0.7, 0.7)
    love.graphics.print(string.format("Image: %dx%d px", iw, ih), SIDEBAR_W + 20, my + 18)
    love.graphics.print(string.format("Zoom: %.0f%%", zoom * 100), SIDEBAR_W + 20, my + 34)
end

local function draw_unit_preview(def_id)
    local vp_w, vp_h = love.graphics.getDimensions()
    local entry = unit_sprites[def_id]
    if not entry then return end

    local area_w = vp_w - SIDEBAR_W
    local cx = SIDEBAR_W + area_w / 2

    -- Current animation frame (large)
    if entry.anims and anim_state then
        local img, quad, fw, fh = anim_module.get_quad(anim_state, entry.anims)
        if img and quad then
            local scale = zoom * math.min(250 / fw, 250 / fh)
            local flip = flipped and -1 or 1
            local draw_x = cx - (fw * scale * flip) / 2
            local draw_y = 60
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.draw(img, quad, draw_x, draw_y, 0, scale * flip, scale)

            -- Frame indicator below preview
            local preview_bottom = 60 + fh * scale + 10

            -- Draw spritesheet strip (all frames, small)
            local current_anim_name = anim_state.current
            local anim_data = entry.anims[current_anim_name]
            if anim_data then
                local strip_scale = math.min((area_w - 40) / (anim_data.frame_width * anim_data.frames), 60 / anim_data.frame_height)
                local strip_w = anim_data.frame_width * strip_scale
                local strip_h = anim_data.frame_height * strip_scale
                local strip_x = cx - (strip_w * anim_data.frames) / 2
                local strip_y = preview_bottom + 10

                love.graphics.setFont(fonts[11])
                love.graphics.setColor(0.6, 0.6, 0.6)
                love.graphics.print("Spritesheet frames:", strip_x, strip_y - 16)

                for f = 1, anim_data.frames do
                    local fx = strip_x + (f - 1) * strip_w
                    -- Highlight current frame
                    if f == anim_state.frame then
                        love.graphics.setColor(1, 1, 0, 0.3)
                        love.graphics.rectangle("fill", fx, strip_y, strip_w, strip_h)
                    end
                    love.graphics.setColor(1, 1, 1, 1)
                    love.graphics.draw(anim_data.img, anim_data.quads[f], fx, strip_y, 0, strip_scale, strip_scale)
                    -- Frame border
                    love.graphics.setColor(0.4, 0.4, 0.4)
                    love.graphics.rectangle("line", fx, strip_y, strip_w, strip_h)
                end

                -- Metadata below strip
                local my = strip_y + strip_h + 15
                love.graphics.setFont(fonts[13])
                love.graphics.setColor(1, 1, 1, 1)
                love.graphics.print(string.format("Unit: %s", def_id), SIDEBAR_W + 20, my)

                love.graphics.setFont(fonts[11])
                love.graphics.setColor(0.7, 0.7, 0.7)
                love.graphics.print(string.format("State: %s  [%d/%d]", current_anim_name, anim_state.frame, anim_data.frames), SIDEBAR_W + 20, my + 18)
                love.graphics.print(string.format("FPS: %d   Frame: %dx%d px", anim_data.fps, anim_data.frame_width, anim_data.frame_height), SIDEBAR_W + 20, my + 34)
                love.graphics.print(string.format("Zoom: %.0f%%   Flip: %s", zoom * 100, flipped and "Yes" or "No"), SIDEBAR_W + 20, my + 50)

                -- Available states
                love.graphics.setColor(0.5, 0.5, 0.5)
                local states_str = ""
                for si, sn in ipairs(anim_names) do
                    if si == anim_name_idx then
                        states_str = states_str .. "[" .. sn .. "] "
                    else
                        states_str = states_str .. sn .. " "
                    end
                end
                love.graphics.print("States: " .. states_str, SIDEBAR_W + 20, my + 70)
            end
        end
    end

    -- Portrait (top right)
    if entry.portrait then
        local pw, ph = entry.portrait:getWidth(), entry.portrait:getHeight()
        local pscale = math.min(100 / pw, 100 / ph)
        local px = vp_w - pw * pscale - 20
        local py = 10
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.draw(entry.portrait, px, py, 0, pscale, pscale)
        love.graphics.setColor(0.4, 0.4, 0.4)
        love.graphics.rectangle("line", px, py, pw * pscale, ph * pscale)
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.5, 0.5, 0.5)
        love.graphics.print("Portrait", px, py + ph * pscale + 2)
    end
end

local function draw_controls_bar()
    local vp_w, vp_h = love.graphics.getDimensions()

    love.graphics.setColor(0.08, 0.08, 0.10, 0.9)
    love.graphics.rectangle("fill", SIDEBAR_W, vp_h - 30, vp_w - SIDEBAR_W, 30)

    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.5, 0.5, 0.5)
    love.graphics.print("Up/Down: select   Left/Right: anim state   +/-: zoom   F: flip   R: reset   Esc: quit", SIDEBAR_W + 10, vp_h - 22)
end

function viewer.draw()
    draw_sidebar()

    local item = asset_list[selected_idx]
    if item then
        if item.type == "terrain" then
            draw_terrain_preview(item.id)
        elseif item.type == "unit" then
            draw_unit_preview(item.id)
        end
    end

    draw_controls_bar()
end

-- ── Input ──────────────────────────────────────────────────────────────

function viewer.keypressed(key)
    if key == "escape" then
        love.event.quit()
        return
    end

    if key == "up" then
        select_asset(selected_idx - 1)
    elseif key == "down" then
        select_asset(selected_idx + 1)
    elseif key == "left" then
        -- Previous animation state
        if #anim_names > 0 then
            anim_name_idx = anim_name_idx - 1
            if anim_name_idx < 1 then anim_name_idx = #anim_names end
            anim_module.play(anim_state, anim_names[anim_name_idx])
        end
    elseif key == "right" then
        -- Next animation state
        if #anim_names > 0 then
            anim_name_idx = anim_name_idx + 1
            if anim_name_idx > #anim_names then anim_name_idx = 1 end
            anim_module.play(anim_state, anim_names[anim_name_idx])
        end
    elseif key == "=" or key == "+" or key == "kp+" then
        zoom = math.min(ZOOM_MAX, zoom * 1.25)
    elseif key == "-" or key == "kp-" then
        zoom = math.max(ZOOM_MIN, zoom / 1.25)
    elseif key == "f" then
        flipped = not flipped
    elseif key == "r" then
        zoom = 1.0
        flipped = false
    elseif key == "1" or key == "2" or key == "3" or key == "4" or key == "5" then
        local n = tonumber(key)
        if n and n <= #anim_names then
            anim_name_idx = n
            anim_module.play(anim_state, anim_names[n])
        end
    end

    -- Keep sidebar scrolled to show selected item
    local vp_h = love.graphics.getHeight()
    local item_y = 50 + (selected_idx - 1) * 20
    if item_y - scroll_offset > vp_h - 60 then
        scroll_offset = item_y - vp_h + 80
    elseif item_y - scroll_offset < 50 then
        scroll_offset = math.max(0, item_y - 60)
    end
end

function viewer.wheelmoved(x, y)
    if y > 0 then
        zoom = math.min(ZOOM_MAX, zoom * 1.15)
    elseif y < 0 then
        zoom = math.max(ZOOM_MIN, zoom / 1.15)
    end
end

return viewer
