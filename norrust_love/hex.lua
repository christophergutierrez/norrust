-- hex.lua — Pure hex math for pointy-top odd-r offset coordinates
-- No state dependencies — all functions are pure.

local hex = {}

hex.RADIUS = 96
hex.CELL_W = 166   -- RADIUS * sqrt(3)
hex.CELL_H = 192   -- RADIUS * 2

--- Convert axial (col, row) to pixel center coordinates.
function hex.to_pixel(col, row)
    local x = hex.CELL_W * (col + 0.5 * (row % 2))
    local y = hex.CELL_H * 0.75 * row
    return x, y
end

--- Convert pixel coordinates to nearest hex (col, row).
function hex.from_pixel(px, py)
    local row_f = py / (hex.CELL_H * 0.75)
    local best_col, best_row = 0, 0
    local best_dist = math.huge
    for _, r in ipairs({math.floor(row_f), math.ceil(row_f)}) do
        local col_f = px / hex.CELL_W - 0.5 * (r % 2)
        for _, c in ipairs({math.floor(col_f), math.ceil(col_f)}) do
            local cx = hex.CELL_W * (c + 0.5 * (r % 2))
            local cy = hex.CELL_H * 0.75 * r
            local dx, dy = px - cx, py - cy
            local dist = dx * dx + dy * dy
            if dist < best_dist then
                best_dist = dist
                best_col, best_row = c, r
            end
        end
    end
    return best_col, best_row
end

--- Precomputed unit hex vertices (pointy-top, radius=1).
local HEX_UNIT = {}
for i = 0, 5 do
    local angle = math.rad(60 * i - 30)
    HEX_UNIT[i*2 + 1] = math.cos(angle)
    HEX_UNIT[i*2 + 2] = math.sin(angle)
end

--- Generate pointy-top hex polygon vertices.
function hex.polygon(cx, cy, radius)
    local pts = {}
    for i = 1, 12, 2 do
        pts[i]     = cx + HEX_UNIT[i] * radius
        pts[i + 1] = cy + HEX_UNIT[i + 1] * radius
    end
    return pts
end

--- Get the 6 neighboring hex coordinates (odd-r offset).
function hex.neighbors(col, row)
    local offsets
    if row % 2 == 0 then
        offsets = {{-1,-1},{0,-1},{1,0},{0,1},{-1,1},{-1,0}}
    else
        offsets = {{0,-1},{1,-1},{1,0},{1,1},{0,1},{-1,0}}
    end
    local result = {}
    for _, d in ipairs(offsets) do
        result[#result + 1] = {col = col + d[1], row = row + d[2]}
    end
    return result
end

--- Convert odd-r offset to cube coordinates.
local function to_cube(col, row)
    local x = col - (row - (row % 2)) / 2
    local z = row
    local y = -x - z
    return x, y, z
end

--- Hex distance between two offset coordinates (odd-r).
function hex.distance(c1, r1, c2, r2)
    local x1, y1, z1 = to_cube(c1, r1)
    local x2, y2, z2 = to_cube(c2, r2)
    return math.max(math.abs(x1 - x2), math.abs(y1 - y2), math.abs(z1 - z2))
end

return hex
