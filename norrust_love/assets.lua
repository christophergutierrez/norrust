-- norrust_love/assets.lua — Asset loader with fallback rendering
--
-- Loads terrain tiles and unit sprites from assets/ directory.
-- When an asset is missing, rendering falls back to the existing
-- colored polygon / circle behavior.

local toml_parser = require("toml_parser")
local anim = require("animation")

local assets = {}

--- Normalize a unit def_id to a snake_case directory name.
-- Converts "Elvish Archer" -> "elvish_archer", "Spearman" -> "spearman".
-- @param def_id string: unit definition id from game data
-- @return string: snake_case directory name
local function normalize_unit_dir(def_id)
    return def_id:lower():gsub(" ", "_")
end

--- Load terrain tile PNGs from assets/terrain/.
-- @param base_path string: root assets directory (e.g. "assets")
-- @return table: terrain_id -> love.Image
function assets.load_terrain_tiles(base_path)
    local tiles = {}
    local dir = base_path .. "/terrain"
    local info = love.filesystem.getInfo(dir)
    if not info then return tiles end

    local files = love.filesystem.getDirectoryItems(dir)
    for _, filename in ipairs(files) do
        local terrain_id = filename:match("^(.+)%.png$")
        if terrain_id then
            local ok, img = pcall(love.graphics.newImage, dir .. "/" .. filename)
            if ok then
                tiles[terrain_id] = img
            end
        end
    end
    return tiles
end

--- Load unit sprites from assets/units/{def_id}/.
-- If sprite.toml exists, loads full animation data via animation module.
-- Otherwise falls back to static idle.png loading.
-- @param base_path string: root assets directory (e.g. "assets")
-- @return table: def_id -> { anims = anim_data|nil, idle = Image|nil, portrait = Image|nil }
function assets.load_unit_sprites(base_path)
    local sprites = {}
    local dir = base_path .. "/units"
    local info = love.filesystem.getInfo(dir)
    if not info then return sprites end

    local dirs = love.filesystem.getDirectoryItems(dir)
    for _, def_id in ipairs(dirs) do
        local unit_dir = dir .. "/" .. def_id
        local dir_info = love.filesystem.getInfo(unit_dir)
        if dir_info and dir_info.type == "directory" then
            local entry = {}

            -- Try sprite.toml for full animation support
            local toml_path = unit_dir .. "/sprite.toml"
            local toml_data = toml_parser.parse_file(toml_path)
            if toml_data then
                entry.anims = anim.load_unit_anims(unit_dir, toml_data)
                -- Portrait loaded by animation module
                if entry.anims.portrait then
                    entry.portrait = entry.anims.portrait
                end
            end

            -- Fallback: load idle.png as static image (no sprite.toml)
            if not entry.anims then
                local idle_path = unit_dir .. "/idle.png"
                local idle_info = love.filesystem.getInfo(idle_path)
                if idle_info then
                    local ok, img = pcall(love.graphics.newImage, idle_path)
                    if ok then
                        entry.idle = img
                    end
                end
                -- Load portrait standalone
                local portrait_path = unit_dir .. "/portrait.png"
                local portrait_info = love.filesystem.getInfo(portrait_path)
                if portrait_info then
                    local pok, pimg = pcall(love.graphics.newImage, portrait_path)
                    if pok then
                        entry.portrait = pimg
                    end
                end
            end

            -- Only store if we have something to draw
            if entry.anims or entry.idle then
                sprites[def_id] = entry
            end
        end
    end
    return sprites
end

--- Draw a terrain hex — sprite if available, colored polygon if not.
-- @param terrain_tiles table: loaded terrain tiles from load_terrain_tiles()
-- @param terrain_id string|nil: terrain type id
-- @param cx number: hex center x
-- @param cy number: hex center y
-- @param hex_radius number: hex radius in pixels
-- @param fallback_color table: {r, g, b} for polygon fallback
-- @param hex_polygon_fn function: hex_polygon(cx, cy, radius) -> point list
function assets.draw_terrain_hex(terrain_tiles, terrain_id, cx, cy, hex_radius, fallback_color, hex_polygon_fn)
    local img = terrain_id and terrain_tiles[terrain_id]
    if img then
        -- Hex stencil mask: clip rectangular image to hex boundary
        local stencil_fn = function()
            love.graphics.polygon("fill", hex_polygon_fn(cx, cy, hex_radius))
        end
        love.graphics.stencil(stencil_fn, "replace", 1)
        love.graphics.setStencilTest("greater", 0)

        local iw, ih = img:getWidth(), img:getHeight()
        local diameter = hex_radius * 2
        local sx = diameter / iw
        local sy = diameter / ih
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.draw(img, cx - hex_radius, cy - hex_radius, 0, sx, sy)

        love.graphics.setStencilTest()
    else
        love.graphics.setColor(fallback_color[1], fallback_color[2], fallback_color[3])
        love.graphics.polygon("fill", hex_polygon_fn(cx, cy, hex_radius))
    end
end

--- Draw a unit sprite if available. Returns false if no sprite exists (caller draws fallback).
-- @param unit_sprites table: loaded sprites from load_unit_sprites()
-- @param def_id string: unit definition id
-- @param cx number: hex center x
-- @param cy number: hex center y
-- @param hex_radius number: hex radius in pixels
-- @param faction number: 0=blue, 1=red
-- @param alpha number: opacity (0.4=exhausted, 1.0=fresh)
-- @param faction_colors table: {[0]={r,g,b}, [1]={r,g,b}}
-- @param anim_state table|nil: per-unit animation state from animation.new_state()
-- @return boolean: true if sprite was drawn, false if caller should draw fallback
function assets.draw_unit_sprite(unit_sprites, def_id, cx, cy, hex_radius, faction, alpha, faction_colors, anim_state)
    local key = def_id and normalize_unit_dir(def_id)
    local entry = key and unit_sprites[key]
    if not entry then
        return false
    end

    -- Faction-colored underlay circle
    local fc = faction_colors[faction]
    love.graphics.setColor(fc[1], fc[2], fc[3], alpha)
    love.graphics.circle("fill", cx, cy, hex_radius * 0.45)

    local target_size = hex_radius * 1.4

    -- Animated sprite path (sprite.toml loaded)
    if entry.anims and anim_state then
        local img, quad, fw, fh = anim.get_quad(anim_state, entry.anims)
        if img and quad then
            local scale = math.min(target_size / fw, target_size / fh)
            local flip = anim_state.facing == "left" and -1 or 1
            local draw_x = cx - (fw * scale * flip) / 2
            local draw_y = cy - (fh * scale) / 2
            love.graphics.setColor(1, 1, 1, alpha)
            love.graphics.draw(img, quad, draw_x, draw_y, 0, scale * flip, scale)
            return true
        end
    end

    -- Static idle fallback (no sprite.toml, just idle.png)
    if entry.idle then
        local img = entry.idle
        local iw, ih = img:getWidth(), img:getHeight()
        local scale = math.min(target_size / iw, target_size / ih)
        love.graphics.setColor(1, 1, 1, alpha)
        love.graphics.draw(img, cx - (iw * scale) / 2, cy - (ih * scale) / 2, 0, scale, scale)
        return true
    end

    return false
end

--- Draw a portrait image scaled to fit within bounds.
-- @param unit_sprites table: loaded sprites
-- @param def_id string: unit definition id
-- @param x number: draw x position
-- @param y number: draw y position
-- @param max_w number: maximum width
-- @param max_h number: maximum height
-- @return number: height used (0 if no portrait)
function assets.draw_portrait(unit_sprites, def_id, x, y, max_w, max_h)
    local key = def_id and normalize_unit_dir(def_id)
    local entry = key and unit_sprites[key]
    if not entry or not entry.portrait then
        return 0
    end

    local img = entry.portrait
    local iw, ih = img:getWidth(), img:getHeight()
    local scale = math.min(max_w / iw, max_h / ih)
    local draw_w = iw * scale
    local draw_h = ih * scale

    -- Center horizontally within max_w
    local draw_x = x + (max_w - draw_w) / 2

    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.draw(img, draw_x, y, 0, scale, scale)

    return draw_h
end

return assets
