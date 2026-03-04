-- generate_tiles.lua — Programmatic terrain tile generator
-- Run with: cd norrust_love && love . --generate-tiles
-- Generates 15 terrain tiles as textured PNGs in assets/terrain/

-- Terrain definitions: id, base color (RGB 0-1), pattern type
local TERRAINS = {
    {id = "flat",           r = 0.29, g = 0.49, b = 0.31, pattern = "grass"},
    {id = "grassland",      r = 0.35, g = 0.55, b = 0.37, pattern = "grass"},
    {id = "forest",         r = 0.18, g = 0.35, b = 0.15, pattern = "trees"},
    {id = "hills",          r = 0.55, g = 0.45, b = 0.33, pattern = "bumps"},
    {id = "mountains",      r = 0.42, g = 0.42, b = 0.42, pattern = "peaks"},
    {id = "shallow_water",  r = 0.29, g = 0.54, b = 0.67, pattern = "waves"},
    {id = "swamp_water",    r = 0.35, g = 0.48, b = 0.29, pattern = "waves"},
    {id = "sand",           r = 0.78, g = 0.66, b = 0.35, pattern = "dots"},
    {id = "cave",           r = 0.29, g = 0.29, b = 0.29, pattern = "cracks"},
    {id = "frozen",         r = 0.66, g = 0.78, b = 0.85, pattern = "crystals"},
    {id = "fungus",         r = 0.42, g = 0.36, b = 0.18, pattern = "dots"},
    {id = "reef",           r = 0.24, g = 0.48, b = 0.54, pattern = "waves"},
    {id = "castle",         r = 0.78, g = 0.71, b = 0.48, pattern = "bricks"},
    {id = "keep",           r = 0.78, g = 0.63, b = 0.19, pattern = "bricks"},
    {id = "village",        r = 0.72, g = 0.60, b = 0.19, pattern = "roofs"},
}

local SIZE = 512

-- Simple seeded pseudo-random for deterministic textures
local function hash(x, y, seed)
    local n = x * 374761393 + y * 668265263 + seed * 1274126177
    n = bit.bxor(n, bit.rshift(n, 13))
    n = n * 1103515245 + 12345
    n = bit.bxor(n, bit.rshift(n, 16))
    return (n % 1000) / 1000
end

local function clamp01(v) return math.max(0, math.min(1, v)) end

local function generate_tile(t)
    local canvas = love.graphics.newCanvas(SIZE, SIZE)
    love.graphics.setCanvas(canvas)
    love.graphics.clear(0, 0, 0, 0)

    local imageData = love.image.newImageData(SIZE, SIZE)

    for y = 0, SIZE - 1 do
        for x = 0, SIZE - 1 do
            local r, g, b = t.r, t.g, t.b
            local noise = hash(x, y, 42) * 0.15 - 0.075
            local noise2 = hash(x * 3, y * 3, 99) * 0.1 - 0.05

            if t.pattern == "grass" then
                -- Fine grass-like variation
                local blade = hash(x, y, 7) * 0.12 - 0.06
                local clump = hash(math.floor(x / 8), math.floor(y / 8), 13) * 0.08 - 0.04
                r = clamp01(r + noise + blade * 0.3)
                g = clamp01(g + noise * 1.5 + blade + clump)
                b = clamp01(b + noise * 0.5)

            elseif t.pattern == "trees" then
                -- Dark circles for tree canopy
                local tx = math.floor(x / 24)
                local ty = math.floor(y / 24)
                local cx = tx * 24 + hash(tx, ty, 5) * 16
                local cy = ty * 24 + hash(tx, ty, 6) * 16
                local dx, dy = x - cx, y - cy
                local dist = math.sqrt(dx * dx + dy * dy)
                local tree_r = 8 + hash(tx, ty, 7) * 8
                if dist < tree_r then
                    local shade = 0.7 + 0.3 * (dist / tree_r)
                    r = clamp01(r * shade + noise * 0.5)
                    g = clamp01(g * shade + noise)
                    b = clamp01(b * shade + noise * 0.3)
                else
                    r = clamp01(r * 1.1 + noise)
                    g = clamp01(g * 1.1 + noise)
                    b = clamp01(b * 0.9 + noise)
                end

            elseif t.pattern == "bumps" then
                -- Rolling hill contours
                local hill = math.sin(x * 0.04 + hash(0, math.floor(y / 32), 3) * 6) *
                             math.cos(y * 0.05 + hash(math.floor(x / 32), 0, 4) * 6) * 0.12
                r = clamp01(r + noise + hill)
                g = clamp01(g + noise + hill * 0.8)
                b = clamp01(b + noise * 0.5 + hill * 0.5)

            elseif t.pattern == "peaks" then
                -- Angular rocky peaks
                local ridge = math.abs(math.sin(x * 0.08 + y * 0.06)) * 0.15
                local snow = (y < SIZE * 0.3 or hash(x, y, 11) > 0.7) and 0.1 or 0
                r = clamp01(r + noise + ridge + snow)
                g = clamp01(g + noise + ridge + snow)
                b = clamp01(b + noise + ridge * 0.5 + snow * 1.2)

            elseif t.pattern == "waves" then
                -- Wavy water pattern
                local wave = math.sin(x * 0.06 + y * 0.03 + hash(0, math.floor(y / 16), 8) * 3) * 0.08
                local sparkle = hash(x * 7, y * 7, 55) > 0.95 and 0.15 or 0
                r = clamp01(r + noise + wave * 0.5 + sparkle)
                g = clamp01(g + noise + wave * 0.7 + sparkle)
                b = clamp01(b + noise + wave + sparkle)

            elseif t.pattern == "dots" then
                -- Scattered dots / pebbles
                local dot = hash(math.floor(x / 6), math.floor(y / 6), 9) > 0.7 and 0.08 or 0
                r = clamp01(r + noise + dot)
                g = clamp01(g + noise + dot * 0.8)
                b = clamp01(b + noise * 0.5)

            elseif t.pattern == "cracks" then
                -- Dark cracks on grey surface
                local crack = (math.abs(math.sin(x * 0.1 + hash(0, math.floor(y / 12), 10) * 10)) < 0.05) and -0.15 or 0
                r = clamp01(r + noise + crack)
                g = clamp01(g + noise + crack)
                b = clamp01(b + noise + crack)

            elseif t.pattern == "crystals" then
                -- Ice crystal facets
                local facet = math.abs(math.sin(x * 0.12) * math.cos(y * 0.12)) * 0.1
                local shimmer = hash(x * 5, y * 5, 44) > 0.9 and 0.12 or 0
                r = clamp01(r + noise + facet + shimmer * 0.5)
                g = clamp01(g + noise + facet + shimmer * 0.7)
                b = clamp01(b + noise + facet + shimmer)

            elseif t.pattern == "bricks" then
                -- Stone brick pattern
                local bx = x % 32
                local by = (y + (math.floor(x / 32) % 2) * 16) % 32
                local mortar = (bx < 2 or by < 2) and -0.12 or 0
                local brick_var = hash(math.floor(x / 32), math.floor(y / 32), 15) * 0.06
                r = clamp01(r + noise + mortar + brick_var)
                g = clamp01(g + noise + mortar + brick_var)
                b = clamp01(b + noise * 0.5 + mortar)

            elseif t.pattern == "roofs" then
                -- Small rooftop rectangles
                local rx = math.floor(x / 40)
                local ry = math.floor(y / 40)
                local in_roof = (x % 40 > 4 and x % 40 < 36 and y % 40 > 4 and y % 40 < 36)
                if in_roof and hash(rx, ry, 20) > 0.3 then
                    local roof_hue = hash(rx, ry, 21) * 0.1
                    r = clamp01(0.6 + roof_hue + noise)
                    g = clamp01(0.35 + roof_hue * 0.5 + noise)
                    b = clamp01(0.2 + noise)
                else
                    -- Path between buildings
                    r = clamp01(0.5 + noise)
                    g = clamp01(0.45 + noise)
                    b = clamp01(0.35 + noise)
                end
            end

            imageData:setPixel(x, y, r, g, b, 1)
        end
    end

    love.graphics.setCanvas()
    return love.graphics.newImage(imageData), imageData
end

local function run_generator()
    -- Ensure output directory exists
    local dir = "assets/terrain"
    love.filesystem.createDirectory("assets")
    love.filesystem.createDirectory(dir)

    local count = 0
    for _, t in ipairs(TERRAINS) do
        local _, imageData = generate_tile(t)
        local fileData = imageData:encode("png")
        local path = dir .. "/" .. t.id .. ".png"
        love.filesystem.write(path, fileData)
        count = count + 1
        print(string.format("  [%2d/15] %s.png", count, t.id))
    end

    print(string.format("\nGenerated %d terrain tiles in %s/", count, dir))
    print("Save directory: " .. love.filesystem.getSaveDirectory())
    return count
end

return {
    TERRAINS = TERRAINS,
    generate_tile = generate_tile,
    run = run_generator,
}
