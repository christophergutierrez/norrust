-- norrust_love/assets.lua — Asset loader with fallback rendering
--
-- Loads terrain tiles and unit sprites from assets/ directory.
-- When an asset is missing, rendering falls back to the existing
-- colored polygon / circle behavior.

local assets = {}

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

--- Load unit idle sprites from assets/units/{def_id}/.
-- @param base_path string: root assets directory (e.g. "assets")
-- @return table: def_id -> { idle = Image, portrait = Image|nil }
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
            local idle_path = unit_dir .. "/idle.png"
            local idle_info = love.filesystem.getInfo(idle_path)
            if idle_info then
                local ok, img = pcall(love.graphics.newImage, idle_path)
                if ok then
                    local entry = { idle = img }
                    -- Load portrait if it exists
                    local portrait_path = unit_dir .. "/portrait.png"
                    local portrait_info = love.filesystem.getInfo(portrait_path)
                    if portrait_info then
                        local pok, pimg = pcall(love.graphics.newImage, portrait_path)
                        if pok then
                            entry.portrait = pimg
                        end
                    end
                    sprites[def_id] = entry
                end
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
        local iw, ih = img:getWidth(), img:getHeight()
        local diameter = hex_radius * 2
        local sx = diameter / iw
        local sy = diameter / ih
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.draw(img, cx - hex_radius, cy - hex_radius, 0, sx, sy)
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
-- @return boolean: true if sprite was drawn, false if caller should draw fallback
function assets.draw_unit_sprite(unit_sprites, def_id, cx, cy, hex_radius, faction, alpha, faction_colors)
    local entry = def_id and unit_sprites[def_id]
    if not entry or not entry.idle then
        return false
    end

    -- Faction-colored underlay circle
    local fc = faction_colors[faction]
    love.graphics.setColor(fc[1], fc[2], fc[3], alpha)
    love.graphics.circle("fill", cx, cy, hex_radius * 0.45)

    -- Sprite on top, scaled to fit within hex
    local img = entry.idle
    local iw, ih = img:getWidth(), img:getHeight()
    local target_size = hex_radius * 1.4  -- slightly smaller than full hex
    local scale = math.min(target_size / iw, target_size / ih)
    love.graphics.setColor(1, 1, 1, alpha)
    love.graphics.draw(img, cx - (iw * scale) / 2, cy - (ih * scale) / 2, 0, scale, scale)

    return true
end

return assets
