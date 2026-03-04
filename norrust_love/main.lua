-- norrust_love/main.lua — The Clash for Norrust — Love2D client
-- Port of norrust_client/scripts/game.gd (706 lines)

local norrust = require("norrust")
local assets = require("assets")

-- ── Constants ───────────────────────────────────────────────────────────────

local BOARD_COLS = 8   -- set dynamically after scenario load
local BOARD_ROWS = 5   -- set dynamically after scenario load
local HEX_RADIUS = 96
local HEX_CELL_W = 166   -- HEX_RADIUS * sqrt(3)
local HEX_CELL_H = 192   -- HEX_RADIUS * 2
local COLOR_FLAT = {0.29, 0.49, 0.31}
local CAMERA_PAN_SPEED = 500
local CAMERA_LERP_SPEED = 8.0
local BLUE = {0.25, 0.42, 0.88}
local RED  = {0.80, 0.12, 0.12}

-- Game modes
local PICK_SCENARIO     = -1
local PICK_FACTION_BLUE = 0
local PICK_FACTION_RED  = 1
local SETUP_BLUE = 2
local SETUP_RED  = 3
local PLAYING    = 4

-- Available scenarios
-- preset_units: if true, units come from TOML file — skip manual leader placement
local SCENARIOS = {
    {name = "Contested (8x5)",  board = "contested.toml",  units = "contested_units.toml", preset_units = false},
    {name = "Crossing (16x10)", board = "crossing.toml",   units = "crossing_units.toml",  preset_units = true},
    {name = "Ambush (12x8)",    board = "ambush.toml",     units = "ambush_units.toml",    preset_units = true},
}

-- Available campaigns
local CAMPAIGNS = {
    {name = "The Road to Norrust", file = "tutorial.toml"},
}

-- ── State variables ─────────────────────────────────────────────────────────

local engine
local scenarios_path = ""
local scenario_board = ""
local scenario_units = ""
local scenario_preset = false
local selected_unit_id = -1
local reachable_cells = {}     -- array of {col=N, row=N}
local reachable_set = {}       -- "col,row" -> true for fast lookup
local game_over = false
local winner_faction = -1

local game_mode = PICK_SCENARIO
local factions = {}            -- [{id, name}, ...]
local sel_faction_idx = 0      -- 0-indexed (matches game.gd)
local faction_id = {"", ""}    -- Lua 1-indexed: [1]=blue, [2]=red
local leader_placed = {false, false}
local leader_level = {1, 1}
local next_unit_id = 1
local recruit_mode = false
local recruit_palette = {}
local selected_recruit_idx = 0
local recruit_error = ""
local inspect_unit_id = -1

-- Campaign
local campaigns_path = ""
local campaign_active = false
local campaign_data = nil        -- parsed JSON from norrust_load_campaign
local campaign_index = 0         -- 0-indexed current scenario in campaign
local campaign_veterans = {}     -- array of veteran unit tables from previous scenario
local campaign_gold = 0          -- carried gold for next scenario

-- Assets (loaded in love.load)
local terrain_tiles = {}
local unit_sprites = {}
local FACTION_COLORS = {[0] = {0.25, 0.42, 0.88}, [1] = {0.80, 0.12, 0.12}}

-- Camera
local board_origin_x, board_origin_y = 0, 0
local camera_offset_x, camera_offset_y = 0, 0
local camera_min_x, camera_min_y = 0, 0
local camera_max_x, camera_max_y = 0, 0
local drag_active = false
local drag_start_x, drag_start_y = 0, 0
local drag_camera_start_x, drag_camera_start_y = 0, 0
local camera_target_x, camera_target_y = 0, 0
local camera_lerping = false

-- Fonts (created in love.load)
local fonts = {}

-- ── Hex math ────────────────────────────────────────────────────────────────

local function hex_to_pixel(col, row)
    local x = HEX_CELL_W * (col + 0.5 * (row % 2))
    local y = HEX_CELL_H * 0.75 * row
    return x, y
end

local function pixel_to_hex(px, py)
    local row_f = py / (HEX_CELL_H * 0.75)
    local best_col, best_row = 0, 0
    local best_dist = math.huge
    for _, r in ipairs({math.floor(row_f), math.ceil(row_f)}) do
        local col_f = px / HEX_CELL_W - 0.5 * (r % 2)
        for _, c in ipairs({math.floor(col_f), math.ceil(col_f)}) do
            local cx = HEX_CELL_W * (c + 0.5 * (r % 2))
            local cy = HEX_CELL_H * 0.75 * r
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

local function hex_polygon(cx, cy, radius)
    local pts = {}
    for i = 0, 5 do
        local angle = math.rad(60 * i - 30)
        pts[#pts + 1] = cx + math.cos(angle) * radius
        pts[#pts + 1] = cy + math.sin(angle) * radius
    end
    return pts
end

-- ── Utility helpers ─────────────────────────────────────────────────────────

local function clamp(val, lo, hi)
    return math.max(lo, math.min(hi, val))
end

local function parse_html_color(hex_str)
    if not hex_str or hex_str == "" then return nil end
    local r = tonumber(hex_str:sub(2, 3), 16) / 255
    local g = tonumber(hex_str:sub(4, 5), 16) / 255
    local b = tonumber(hex_str:sub(6, 7), 16) / 255
    return {r, g, b}
end

local function int(v) return math.floor(v) end

-- ── Camera ──────────────────────────────────────────────────────────────────

local function apply_camera_offset()
    camera_offset_x = clamp(camera_offset_x, camera_min_x, camera_max_x)
    camera_offset_y = clamp(camera_offset_y, camera_min_y, camera_max_y)
end

local function center_camera()
    local tlx, tly = hex_to_pixel(0, 0)
    local brx, bry = hex_to_pixel(BOARD_COLS - 1, BOARD_ROWS - 1)
    local vp_w, vp_h = love.graphics.getDimensions()
    board_origin_x = vp_w / 2 - (tlx + brx) / 2
    board_origin_y = vp_h / 2 - (tly + bry) / 2

    local board_half_w = (brx - tlx) / 2 + HEX_RADIUS
    local board_half_h = (bry - tly) / 2 + HEX_RADIUS
    local pan_range_x = math.max(board_half_w - vp_w / 2 + HEX_RADIUS, 0)
    local pan_range_y = math.max(board_half_h - vp_h / 2 + HEX_RADIUS, 0)
    camera_min_x, camera_min_y = -pan_range_x, -pan_range_y
    camera_max_x, camera_max_y = pan_range_x, pan_range_y
    apply_camera_offset()
end

-- ── Game logic helpers ──────────────────────────────────────────────────────

local function clear_selection()
    selected_unit_id = -1
    reachable_cells = {}
    reachable_set = {}
    inspect_unit_id = -1
end

local function build_unit_pos_map(state)
    local result = {}
    for _, unit in ipairs(state.units or {}) do
        local key = int(unit.col) .. "," .. int(unit.row)
        result[key] = {id = int(unit.id), faction = int(unit.faction)}
    end
    return result
end

local function select_unit(uid)
    selected_unit_id = uid
    inspect_unit_id = uid
    reachable_cells = norrust.get_reachable_hexes(engine, uid)
    reachable_set = {}
    for _, cell in ipairs(reachable_cells) do
        reachable_set[cell.col .. "," .. cell.row] = true
    end

    -- Camera follow: center unit in viewport
    local state = norrust.get_state(engine)
    for _, unit in ipairs(state.units or {}) do
        if int(unit.id) == uid then
            local ux, uy = hex_to_pixel(int(unit.col), int(unit.row))
            local vp_w, vp_h = love.graphics.getDimensions()
            camera_target_x = clamp(vp_w / 2 - board_origin_x - ux, camera_min_x, camera_max_x)
            camera_target_y = clamp(vp_h / 2 - board_origin_y - uy, camera_min_y, camera_max_y)
            camera_lerping = true
            break
        end
    end
end

local function check_game_over()
    local w = norrust.get_winner(engine)
    if w >= 0 then
        game_over = true
        winner_faction = w
    end
end

local function faction_index_for_mode()
    return game_mode == SETUP_BLUE and 0 or 1
end

-- ── Drawing helpers ─────────────────────────────────────────────────────────

local function draw_units(state)
    for _, unit in ipairs(state.units or {}) do
        local col = int(unit.col)
        local row = int(unit.row)
        local faction = int(unit.faction)
        local hp = int(unit.hp)
        local exhausted = unit.moved or unit.attacked
        local cx, cy = hex_to_pixel(col, row)
        local alpha = exhausted and 0.4 or 1.0

        -- Try sprite rendering first; fall back to colored circle
        local drawn = assets.draw_unit_sprite(unit_sprites, unit.def_id, cx, cy, HEX_RADIUS, faction, alpha, FACTION_COLORS)
        if not drawn then
            -- Fallback: colored circle + abbreviation
            if faction == 0 then
                love.graphics.setColor(BLUE[1], BLUE[2], BLUE[3], alpha)
            else
                love.graphics.setColor(RED[1], RED[2], RED[3], alpha)
            end
            love.graphics.circle("fill", cx, cy, HEX_RADIUS * 0.45)

            -- Unit type abbreviation
            local word = (unit.def_id or ""):match("^([^_]+)") or unit.def_id or ""
            local abbrev = (word:sub(1, 1):upper() .. word:sub(2):lower()):sub(1, 7)
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.setFont(fonts[14])
            love.graphics.printf(abbrev, cx - 42, cy - 14, 84, "center")
        end

        -- HP (always drawn on top, whether sprite or fallback)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.setFont(fonts[18])
        love.graphics.print(tostring(hp), cx - 12, cy - 2)

        -- Advancement ring
        if unit.advancement_pending then
            love.graphics.setColor(1.0, 0.85, 0.0, 1)
            love.graphics.setLineWidth(3.5)
            love.graphics.arc("line", "open", cx, cy, HEX_RADIUS * 0.52, 0, math.pi * 2, 24)
        end

        -- XP text
        if unit.xp_needed and int(unit.xp_needed) > 0 then
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.setFont(fonts[14])
            love.graphics.print(int(unit.xp) .. "/" .. int(unit.xp_needed), cx - 15, cy + 14)
        end
    end
end

local function draw_setup_hud()
    local vp_w, vp_h = love.graphics.getDimensions()

    -- Scenario selection screen (full screen, no sidebar)
    if game_mode == PICK_SCENARIO then
        love.graphics.setFont(fonts[18])
        love.graphics.setColor(1, 0.85, 0, 1)
        love.graphics.printf("The Clash for Norrust", 0, vp_h / 2 - 60, vp_w, "center")

        love.graphics.setFont(fonts[14])
        love.graphics.setColor(0.83, 0.83, 0.83, 1)
        love.graphics.printf("Select a scenario:", 0, vp_h / 2 - 20, vp_w, "center")

        for i, sc in ipairs(SCENARIOS) do
            love.graphics.setFont(fonts[15])
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.printf(string.format("[%d] %s", i, sc.name), 0, vp_h / 2 + 10 + (i - 1) * 28, vp_w, "center")
        end

        -- Campaign section
        local cy = vp_h / 2 + 10 + #SCENARIOS * 28 + 10
        love.graphics.setFont(fonts[14])
        love.graphics.setColor(0.83, 0.83, 0.83, 1)
        love.graphics.printf("Campaigns:", 0, cy, vp_w, "center")
        cy = cy + 22
        for i, camp in ipairs(CAMPAIGNS) do
            love.graphics.setFont(fonts[15])
            love.graphics.setColor(1, 0.85, 0, 1)
            love.graphics.printf(string.format("[C] %s", camp.name), 0, cy + (i - 1) * 28, vp_w, "center")
        end
        return
    end

    local is_blue = (game_mode == PICK_FACTION_BLUE or game_mode == SETUP_BLUE)
    local faction_name = is_blue and "Blue" or "Red"
    local fc = is_blue and BLUE or RED

    -- Sidebar background
    love.graphics.setColor(0, 0, 0, 0.6)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    if game_mode == PICK_FACTION_BLUE or game_mode == PICK_FACTION_RED then
        love.graphics.setFont(fonts[15])
        love.graphics.setColor(fc[1], fc[2], fc[3])
        love.graphics.print("FACTION — " .. faction_name, vp_w - 190, 10)

        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("Press 1-" .. #factions .. " to pick", vp_w - 190, 30)

        for i, f in ipairs(factions) do
            local y = 56 + (i - 1) * 22
            local label = "[" .. i .. "] " .. f.name
            if (i - 1) == sel_faction_idx then
                love.graphics.setColor(1, 1, 0, 1)
            else
                love.graphics.setColor(1, 1, 1, 1)
            end
            love.graphics.setFont(fonts[13])
            love.graphics.print(label, vp_w - 190, y)
        end
    else
        love.graphics.setFont(fonts[15])
        love.graphics.setColor(fc[1], fc[2], fc[3])
        love.graphics.print("SETUP — " .. faction_name, vp_w - 190, 10)

        local fi = faction_index_for_mode()
        if not leader_placed[fi + 1] then
            local leader_def = norrust.get_faction_leader(engine, faction_id[fi + 1])

            love.graphics.setFont(fonts[11])
            love.graphics.setColor(0.83, 0.83, 0.83)
            love.graphics.print("Place leader:", vp_w - 190, 30)
            love.graphics.setFont(fonts[14])
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.print(leader_def, vp_w - 190, 48)

            -- Board-center prompt
            local bx, by = hex_to_pixel(int(BOARD_COLS / 2), int(BOARD_ROWS / 2))
            local sx = bx + board_origin_x + camera_offset_x
            local sy = by + board_origin_y + camera_offset_y
            local prompt = "Click a hex on the board to place " .. leader_def
            love.graphics.setColor(0, 0, 0, 0.75)
            love.graphics.rectangle("fill", sx - 200, sy - 14, 400, 24)
            love.graphics.setFont(fonts[13])
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.print(prompt, sx - 196, sy - 8)
        else
            love.graphics.setFont(fonts[11])
            love.graphics.setColor(0.83, 0.83, 0.83)
            love.graphics.print("Leader placed.", vp_w - 190, 30)
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.print("[Enter] Continue", vp_w - 190, 44)
        end
    end
end

local function draw_recruit_panel(state)
    local faction = norrust.get_active_faction(engine)
    local vp_w, vp_h = love.graphics.getDimensions()
    local fc = faction == 0 and BLUE or RED
    local gold_arr = state.gold or {0, 0}
    local gold = int(gold_arr[faction + 1] or 0)

    -- Sidebar background
    love.graphics.setColor(0, 0, 0, 0.6)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    love.graphics.setFont(fonts[15])
    love.graphics.setColor(fc[1], fc[2], fc[3])
    love.graphics.print(string.format("RECRUIT — %dg", gold), vp_w - 190, 10)

    love.graphics.setFont(fonts[11])
    love.graphics.setColor(1, 1, 0, 1)
    love.graphics.print("Leader must be on gold hex", vp_w - 190, 30)
    love.graphics.setColor(0.83, 0.83, 0.83)
    love.graphics.print("Click adjacent blue hex", vp_w - 190, 44)
    love.graphics.print("[R] Cancel", vp_w - 190, 58)

    if recruit_error ~= "" then
        love.graphics.setColor(1, 0, 0, 1)
        love.graphics.print(recruit_error, vp_w - 190, 72)
    end

    for i, def_id in ipairs(recruit_palette) do
        local cost = norrust.get_unit_cost(engine, def_id)
        local y = 94 + (i - 1) * 20
        local label = string.format("[%d] %s (%dg)", i, def_id, cost)
        if (i - 1) == selected_recruit_idx then
            love.graphics.setColor(1, 1, 0, 1)
        else
            love.graphics.setColor(1, 1, 1, 1)
        end
        love.graphics.print(label, vp_w - 190, y)
    end
end

local function draw_unit_panel(unit)
    local vp_w, vp_h = love.graphics.getDimensions()

    love.graphics.setColor(0, 0, 0, 0.75)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    local faction = int(unit.faction)
    local faction_name = faction == 0 and "Blue" or "Red"
    local fc = faction == 0 and BLUE or RED

    local y = 10
    -- Unit name + faction
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(fc[1], fc[2], fc[3])
    love.graphics.print(unit.def_id or "", vp_w - 190, y)
    y = y + 18
    love.graphics.setFont(fonts[11])
    love.graphics.print(faction_name, vp_w - 190, y)
    y = y + 20

    -- HP
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.setFont(fonts[12])
    love.graphics.print(string.format("HP: %d / %d", int(unit.hp), int(unit.max_hp)), vp_w - 190, y)
    y = y + 16

    -- XP
    if unit.xp_needed and int(unit.xp_needed) > 0 then
        love.graphics.print(string.format("XP: %d / %d", int(unit.xp), int(unit.xp_needed)), vp_w - 190, y)
        y = y + 16
    end

    -- Movement
    local move_status = ""
    if unit.moved and unit.attacked then
        move_status = " (done)"
    elseif unit.moved then
        move_status = " (moved)"
    elseif unit.attacked then
        move_status = " (attacked)"
    end
    love.graphics.print(string.format("Move: %d%s", int(unit.movement), move_status), vp_w - 190, y)
    y = y + 20

    -- Attacks
    local attacks = unit.attacks or {}
    if #attacks > 0 then
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("── Attacks ──", vp_w - 190, y)
        y = y + 15
        for _, atk in ipairs(attacks) do
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.setFont(fonts[12])
            love.graphics.print(atk.name or "", vp_w - 190, y)
            y = y + 14
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.setFont(fonts[11])
            love.graphics.print(string.format("  %dx%d %s", int(atk.damage), int(atk.strikes), atk.range or ""), vp_w - 190, y)
            y = y + 15
        end
    end

    -- Abilities
    local abilities = unit.abilities or {}
    if #abilities > 0 then
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("── Abilities ──", vp_w - 190, y)
        y = y + 15
        for _, ab in ipairs(abilities) do
            love.graphics.setColor(0.6, 1.0, 0.6)
            love.graphics.print(ab, vp_w - 190, y)
            y = y + 14
        end
    end
end

-- ── Scenario loading ──────────────────────────────────────────────────────

local function load_selected_scenario()
    assert(norrust.load_board(engine, scenarios_path .. "/" .. scenario_board, 42), "Failed to load board")

    -- Read board dimensions from state
    local state = norrust.get_state(engine)
    BOARD_COLS = int(state.cols or 8)
    BOARD_ROWS = int(state.rows or 5)

    center_camera()
end

-- ── Campaign helpers ─────────────────────────────────────────────────────

--- Find the player keep hex and its adjacent castle hexes for veteran placement.
local function find_keep_and_castles()
    local state = norrust.get_state(engine)
    local keep_col, keep_row = nil, nil
    local castle_hexes = {}

    for _, tile in ipairs(state.terrain or {}) do
        local tc, tr = int(tile.col), int(tile.row)
        if tile.terrain_id == "keep" then
            -- Use leftmost keep (player side)
            if keep_col == nil or tc < keep_col then
                keep_col, keep_row = tc, tr
            end
        end
    end

    if keep_col then
        -- Collect adjacent castle hexes
        for _, tile in ipairs(state.terrain or {}) do
            if tile.terrain_id == "castle" then
                local tc, tr = int(tile.col), int(tile.row)
                -- Check adjacency (distance ~1 in offset coords via hex neighbors)
                local dx = math.abs(tc - keep_col)
                local dy = math.abs(tr - keep_row)
                if dx <= 1 and dy <= 1 and not (dx == 0 and dy == 0) then
                    castle_hexes[#castle_hexes + 1] = {col = tc, row = tr}
                end
            end
        end
    end

    return keep_col, keep_row, castle_hexes
end

--- Place veteran units on keep + adjacent castles, skipping occupied hexes.
local function place_veterans()
    if #campaign_veterans == 0 then return end

    local keep_col, keep_row, castle_hexes = find_keep_and_castles()
    if not keep_col then return end

    local state = norrust.get_state(engine)
    local pos_map = build_unit_pos_map(state)

    -- Build placement list: keep first, then castles
    local slots = {{col = keep_col, row = keep_row}}
    for _, ch in ipairs(castle_hexes) do
        slots[#slots + 1] = ch
    end

    local placed = 0
    for _, vet in ipairs(campaign_veterans) do
        if placed >= #slots then break end

        -- Find next unoccupied slot
        local slot = nil
        for si = placed + 1, #slots do
            local key = int(slots[si].col) .. "," .. int(slots[si].row)
            if not pos_map[key] then
                slot = slots[si]
                placed = si
                break
            end
        end
        if not slot then break end

        local uid = norrust.get_next_unit_id(engine)
        norrust.place_veteran_unit(
            engine, uid,
            vet.def_id, 0,
            int(slot.col), int(slot.row),
            int(vet.hp), int(vet.xp), int(vet.xp_needed),
            vet.advancement_pending
        )
        -- Update pos_map so next veteran doesn't collide
        pos_map[int(slot.col) .. "," .. int(slot.row)] = {id = uid, faction = 0}
    end
end

--- Load the next campaign scenario (or the first one).
--- Engine keeps registries (units, terrain, factions); load_board replaces GameState.
local function load_campaign_scenario()
    local sc = campaign_data.scenarios[campaign_index + 1]
    scenario_board = sc.board
    scenario_units = sc.units
    scenario_preset = sc.preset_units

    -- Reset client state for new scenario
    game_over = false
    winner_faction = -1
    clear_selection()
    recruit_mode = false

    -- Load board (creates fresh GameState; registries stay)
    load_selected_scenario()

    -- Load preset units + starting gold
    if scenario_preset then
        norrust.apply_starting_gold(engine, faction_id[1], faction_id[2])
        norrust.load_units(engine, scenarios_path .. "/" .. scenario_units)
        next_unit_id = norrust.get_next_unit_id(engine)
    end

    -- Place veterans from previous scenario
    if campaign_index > 0 and #campaign_veterans > 0 then
        place_veterans()
        next_unit_id = norrust.get_next_unit_id(engine)
    end

    -- Apply carry-over gold (override faction 0's starting gold)
    if campaign_index > 0 and campaign_gold > 0 then
        norrust.set_faction_gold(engine, 0, campaign_gold)
    end

    game_mode = PLAYING
end

-- ── love.load ───────────────────────────────────────────────────────────────

function love.load()
    -- Check for --generate-tiles flag
    for _, arg in ipairs(arg or {}) do
        if arg == "--generate-tiles" then
            local gen = require("generate_tiles")
            gen.run()
            love.event.quit()
            return
        end
    end

    love.graphics.setBackgroundColor(0.1, 0.1, 0.12)

    -- Create fonts
    for _, size in ipairs({9, 11, 12, 13, 14, 15, 18, 32}) do
        fonts[size] = love.graphics.newFont(size)
    end

    -- Create engine
    engine = norrust.new()

    -- Paths (norrust_love is one level inside project root)
    local source = love.filesystem.getSource()
    local project_root = source .. "/.."
    local data_path = project_root .. "/data"
    scenarios_path = project_root .. "/scenarios"

    campaigns_path = project_root .. "/campaigns"

    -- Load data + factions (scenario loaded after selection)
    assert(norrust.load_data(engine, data_path), "Failed to load data")
    assert(norrust.load_factions(engine, data_path), "Failed to load factions")

    -- Parse faction list
    factions = norrust.get_faction_ids(engine)

    -- Load visual assets (graceful fallback if assets/ missing)
    terrain_tiles = assets.load_terrain_tiles("assets")
    unit_sprites = assets.load_unit_sprites("assets")

    -- Start at scenario selection
    game_mode = PICK_SCENARIO
end

-- ── love.update ─────────────────────────────────────────────────────────────

function love.update(dt)
    -- Arrow key panning
    local pan_x, pan_y = 0, 0
    if love.keyboard.isDown("left") then pan_x = pan_x + 1 end
    if love.keyboard.isDown("right") then pan_x = pan_x - 1 end
    if love.keyboard.isDown("up") then pan_y = pan_y + 1 end
    if love.keyboard.isDown("down") then pan_y = pan_y - 1 end

    if pan_x ~= 0 or pan_y ~= 0 then
        camera_lerping = false
        local len = math.sqrt(pan_x * pan_x + pan_y * pan_y)
        camera_offset_x = camera_offset_x + (pan_x / len) * CAMERA_PAN_SPEED * dt
        camera_offset_y = camera_offset_y + (pan_y / len) * CAMERA_PAN_SPEED * dt
        apply_camera_offset()
        return
    end

    -- Camera lerp toward selection target
    if camera_lerping then
        local t = CAMERA_LERP_SPEED * dt
        camera_offset_x = camera_offset_x + (camera_target_x - camera_offset_x) * t
        camera_offset_y = camera_offset_y + (camera_target_y - camera_offset_y) * t
        apply_camera_offset()
        local dx = camera_offset_x - camera_target_x
        local dy = camera_offset_y - camera_target_y
        if math.sqrt(dx * dx + dy * dy) < 1.0 then
            camera_offset_x = camera_target_x
            camera_offset_y = camera_target_y
            apply_camera_offset()
            camera_lerping = false
        end
    end
end

-- ── love.draw ───────────────────────────────────────────────────────────────

function love.draw()
    -- Scenario selection: no board loaded yet
    if game_mode == PICK_SCENARIO then
        draw_setup_hud()
        return
    end

    local state = norrust.get_state(engine)

    -- Build tile color + terrain_id maps
    local tile_colors = {}
    local tile_ids = {}
    for _, tile in ipairs(state.terrain or {}) do
        local key = int(tile.col) .. "," .. int(tile.row)
        tile_colors[key] = parse_html_color(tile.color) or COLOR_FLAT
        tile_ids[key] = tile.terrain_id
    end

    -- Board-space drawing (push camera transform)
    local tx = board_origin_x + camera_offset_x
    local ty = board_origin_y + camera_offset_y
    love.graphics.push()
    love.graphics.translate(tx, ty)

    -- 1. Terrain hexes
    for col = 0, BOARD_COLS - 1 do
        for row = 0, BOARD_ROWS - 1 do
            local cx, cy = hex_to_pixel(col, row)
            local key = col .. "," .. row
            local c = tile_colors[key] or COLOR_FLAT
            local tid = tile_ids[key]
            assets.draw_terrain_hex(terrain_tiles, tid, cx, cy, HEX_RADIUS, c, hex_polygon)
        end
    end

    -- 2. Reachable hex highlights
    if game_mode == PLAYING then
        love.graphics.setColor(1, 1, 0, 0.35)
        for _, cell in ipairs(reachable_cells) do
            local cx, cy = hex_to_pixel(cell.col, cell.row)
            love.graphics.polygon("fill", hex_polygon(cx, cy, HEX_RADIUS))
        end
    end

    -- 3. Selected unit outline
    if game_mode == PLAYING and selected_unit_id ~= -1 then
        for _, unit in ipairs(state.units or {}) do
            if int(unit.id) == selected_unit_id then
                local cx, cy = hex_to_pixel(int(unit.col), int(unit.row))
                love.graphics.setColor(1, 1, 1, 1)
                love.graphics.setLineWidth(2.5)
                love.graphics.polygon("line", hex_polygon(cx, cy, HEX_RADIUS))
                break
            end
        end
    end

    -- 4. Objective hex highlight
    if state.objective_col and state.objective_row then
        local ocol = int(state.objective_col)
        local orow = int(state.objective_row)
        local ox, oy = hex_to_pixel(ocol, orow)
        -- Pulsing gold border
        love.graphics.setColor(1.0, 0.85, 0.0, 0.9)
        love.graphics.setLineWidth(4.0)
        love.graphics.polygon("line", hex_polygon(ox, oy, HEX_RADIUS))
        -- Inner star marker
        love.graphics.setColor(1.0, 0.85, 0.0, 0.3)
        love.graphics.polygon("fill", hex_polygon(ox, oy, HEX_RADIUS * 0.3))
    end

    -- 5. Units
    draw_units(state)

    -- 6. Recruit-mode hex highlights (drawn after units, matching game.gd Z-order)
    if recruit_mode then
        for _, tile in ipairs(state.terrain or {}) do
            local tid = tile.terrain_id or ""
            local cx, cy = hex_to_pixel(int(tile.col), int(tile.row))
            if tid == "keep" then
                love.graphics.setColor(1.0, 0.75, 0.0, 0.7)
                love.graphics.polygon("fill", hex_polygon(cx, cy, HEX_RADIUS))
                love.graphics.setColor(1, 1, 0, 1)
                love.graphics.setLineWidth(3.0)
                love.graphics.polygon("line", hex_polygon(cx, cy, HEX_RADIUS))
            elseif tid == "castle" then
                love.graphics.setColor(0.0, 0.9, 0.9, 0.65)
                love.graphics.polygon("fill", hex_polygon(cx, cy, HEX_RADIUS))
                love.graphics.setColor(1, 1, 1, 1)
                love.graphics.setLineWidth(2.5)
                love.graphics.polygon("line", hex_polygon(cx, cy, HEX_RADIUS))
            end
        end
    end

    love.graphics.pop() -- back to screen space

    -- ── Screen-space UI ─────────────────────────────────────────────────

    if game_mode ~= PLAYING then
        draw_setup_hud()
    else
        -- Win overlay
        if game_over then
            local vp_w, vp_h = love.graphics.getDimensions()
            local winner_name = winner_faction == 0 and "Blue" or "Red"
            local msg, sub_msg
            if winner_faction == 0 then
                if campaign_active then
                    if campaign_index + 1 < #campaign_data.scenarios then
                        msg = "Victory!"
                        sub_msg = "Press Enter for next battle"
                    else
                        msg = "Campaign Victory!"
                        sub_msg = "Press Enter to continue"
                    end
                else
                    msg = "Victory! " .. winner_name .. " wins!"
                    sub_msg = "Press Enter to continue"
                end
            else
                -- Check if it was a timeout or elimination
                local max_t = state.max_turns
                local cur_t = int(state.turn or 1)
                if max_t and cur_t > int(max_t) then
                    msg = "Defeat — Turn limit reached!"
                else
                    msg = winner_name .. " wins!"
                end
                if campaign_active then
                    sub_msg = "Campaign over — Press Enter"
                else
                    sub_msg = "Press Enter to continue"
                end
            end
            love.graphics.setFont(fonts[32])
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.printf(msg, vp_w / 2 - 240, vp_h / 2 - 16, 480, "center")
            if sub_msg then
                love.graphics.setFont(fonts[14])
                love.graphics.setColor(0.83, 0.83, 0.83, 1)
                love.graphics.printf(sub_msg, vp_w / 2 - 240, vp_h / 2 + 24, 480, "center")
            end
        end

        -- HUD
        if not game_over then
            local faction = norrust.get_active_faction(engine)
            local faction_name = faction == 0 and "Blue" or "Red"
            local fc = faction == 0 and BLUE or RED
            local tod = norrust.get_time_of_day_name(engine)
            local gold_arr = state.gold or {0, 0}
            local gold = int(gold_arr[faction + 1] or 0)
            local turn = norrust.get_turn(engine)
            local turn_str
            if state.max_turns then
                turn_str = string.format("Turn %d / %d", turn, int(state.max_turns))
            else
                turn_str = string.format("Turn %d", turn)
            end
            local hud_text = string.format("%s  ·  %s  ·  %s's Turn  ·  %dg",
                turn_str, tod, faction_name, gold)
            love.graphics.setFont(fonts[14])
            love.graphics.setColor(fc[1], fc[2], fc[3])
            love.graphics.print(hud_text, 10, 6)
        end

        if recruit_mode then
            draw_recruit_panel(state)
        elseif inspect_unit_id ~= -1 then
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == inspect_unit_id then
                    draw_unit_panel(unit)
                    break
                end
            end
        end
    end
end

-- ── love.keypressed ─────────────────────────────────────────────────────────

function love.keypressed(key)
    -- Scenario selection
    if game_mode == PICK_SCENARIO then
        local num = tonumber(key)
        if num and num >= 1 and num <= #SCENARIOS then
            campaign_active = false
            scenario_board = SCENARIOS[num].board
            scenario_units = SCENARIOS[num].units
            scenario_preset = SCENARIOS[num].preset_units
            load_selected_scenario()
            game_mode = PICK_FACTION_BLUE
        elseif key == "c" then
            -- Start campaign
            local camp = CAMPAIGNS[1]
            campaign_data = norrust.load_campaign(engine, campaigns_path .. "/" .. camp.file)
            if campaign_data then
                campaign_active = true
                campaign_index = 0
                campaign_veterans = {}
                campaign_gold = 0
                -- Load first scenario's board for faction selection
                local sc = campaign_data.scenarios[1]
                scenario_board = sc.board
                scenario_units = sc.units
                scenario_preset = sc.preset_units
                load_selected_scenario()
                game_mode = PICK_FACTION_BLUE
            end
        end
        return
    end

    -- Setup mode
    if game_mode ~= PLAYING then
        -- Faction picker: number keys
        if game_mode == PICK_FACTION_BLUE or game_mode == PICK_FACTION_RED then
            local num = tonumber(key)
            if num and num >= 1 and num <= #factions then
                local fi = game_mode == PICK_FACTION_BLUE and 0 or 1
                faction_id[fi + 1] = factions[num].id
                sel_faction_idx = 0

                if scenario_preset then
                    -- Preset scenarios: skip manual setup, go straight through
                    if game_mode == PICK_FACTION_BLUE then
                        game_mode = PICK_FACTION_RED
                    elseif campaign_active then
                        -- Campaign: use campaign loader (handles gold, veterans)
                        load_campaign_scenario()
                    else
                        -- Both factions chosen — load units and start
                        norrust.apply_starting_gold(engine, faction_id[1], faction_id[2])
                        norrust.load_units(engine, scenarios_path .. "/" .. scenario_units)
                        next_unit_id = norrust.get_next_unit_id(engine)
                        game_mode = PLAYING
                    end
                else
                    game_mode = game_mode == PICK_FACTION_BLUE and SETUP_BLUE or SETUP_RED
                end
            end
            return
        end

        -- Setup: Enter to continue (manual placement scenarios only)
        if key == "return" or key == "kpenter" then
            if game_mode == SETUP_BLUE then
                game_mode = PICK_FACTION_RED
            else
                -- Both factions chosen — wire starting gold
                norrust.apply_starting_gold(engine, faction_id[1], faction_id[2])
                game_mode = PLAYING
            end
        end
        return
    end

    -- Playing mode
    if game_over then
        if key == "return" or key == "kpenter" then
            if campaign_active and winner_faction == 0 then
                -- Player won — check if more scenarios remain
                local survivors = norrust.get_survivors(engine, 0)
                campaign_veterans = survivors
                campaign_gold = norrust.get_carry_gold(
                    engine, 0,
                    campaign_data.gold_carry_percent,
                    campaign_data.early_finish_bonus
                )
                campaign_index = campaign_index + 1
                if campaign_index < #campaign_data.scenarios then
                    load_campaign_scenario()
                else
                    -- Campaign complete — return to scenario selection
                    campaign_active = false
                    game_mode = PICK_SCENARIO
                end
            else
                -- Individual scenario win/loss, or campaign defeat
                campaign_active = false
                game_mode = PICK_SCENARIO
            end
        end
        return
    end

    if key == "e" then
        -- End turn + AI
        norrust.end_turn(engine)
        clear_selection()
        check_game_over()
        if not game_over and norrust.get_active_faction(engine) == 1 then
            local n = norrust.ai_recruit(engine, faction_id[2], next_unit_id)
            next_unit_id = next_unit_id + n
            norrust.ai_take_turn(engine, 1)
            check_game_over()
        end

    elseif key == "a" then
        -- Advance selected unit
        if selected_unit_id ~= -1 then
            local state = norrust.get_state(engine)
            local active = norrust.get_active_faction(engine)
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == selected_unit_id
                    and int(unit.faction) == active
                    and unit.advancement_pending then
                    norrust.apply_advance(engine, selected_unit_id)
                    clear_selection()
                    break
                end
            end
        end

    elseif key == "r" then
        -- Toggle recruit mode
        if not recruit_mode then
            local faction = norrust.get_active_faction(engine)
            recruit_palette = norrust.get_faction_recruits(engine, faction_id[faction + 1], 0)
            selected_recruit_idx = 0
            recruit_error = ""
            recruit_mode = true
            clear_selection()
        else
            recruit_mode = false
        end

    else
        -- Number keys for recruit selection
        local num = tonumber(key)
        if num and num >= 1 and num <= 9 then
            if recruit_mode and #recruit_palette > 0 then
                selected_recruit_idx = math.min(num - 1, #recruit_palette - 1)
            end
        end
    end
end

-- ── love.mousepressed ───────────────────────────────────────────────────────

function love.mousepressed(x, y, button)
    if button ~= 1 then return end
    if game_mode == PICK_SCENARIO then return end

    -- Setup mode click
    if game_mode ~= PLAYING then
        if game_mode == PICK_FACTION_BLUE or game_mode == PICK_FACTION_RED then
            return
        end

        local local_x = x - (board_origin_x + camera_offset_x)
        local local_y = y - (board_origin_y + camera_offset_y)
        local col, row = pixel_to_hex(local_x, local_y)

        if col < 0 or col >= BOARD_COLS or row < 0 or row >= BOARD_ROWS then
            return
        end

        local state = norrust.get_state(engine)
        local pos_map = build_unit_pos_map(state)
        local fi = faction_index_for_mode()
        local faction = fi

        if not leader_placed[fi + 1] then
            local key = col .. "," .. row
            if not pos_map[key] then
                local leader_def = norrust.get_faction_leader(engine, faction_id[fi + 1])
                norrust.place_unit_at(engine, next_unit_id, leader_def, 0, faction, col, row)
                next_unit_id = next_unit_id + 1
                leader_placed[fi + 1] = true
            end
        end
        return
    end

    -- Playing mode
    if game_over then return end

    -- Sidebar check — don't process board clicks in sidebar area
    local vp_w = love.graphics.getWidth()
    if x > vp_w - 200 then return end

    -- Convert screen coords to hex
    local local_x = x - (board_origin_x + camera_offset_x)
    local local_y = y - (board_origin_y + camera_offset_y)
    local col, row = pixel_to_hex(local_x, local_y)

    -- Off-board click: start drag
    if col < 0 or col >= BOARD_COLS or row < 0 or row >= BOARD_ROWS then
        drag_active = true
        drag_start_x, drag_start_y = x, y
        drag_camera_start_x = camera_offset_x
        drag_camera_start_y = camera_offset_y
        clear_selection()
        return
    end

    local clicked_key = col .. "," .. row
    local state = norrust.get_state(engine)
    local pos_map = build_unit_pos_map(state)
    local active = norrust.get_active_faction(engine)

    -- Recruit mode click
    if recruit_mode then
        local def_id = recruit_palette[selected_recruit_idx + 1] or ""
        if def_id ~= "" then
            local result = norrust.recruit_unit_at(engine, next_unit_id, def_id, col, row)
            if result == 0 then
                next_unit_id = next_unit_id + 1
                recruit_error = ""
                recruit_mode = false
            else
                local err_map = {
                    [-4] = "Hex is occupied",
                    [-8] = "Not enough gold",
                    [-9] = "Must click a castle hex",
                    [-10] = "Move leader to the keep first",
                }
                recruit_error = err_map[result] or string.format("Recruit failed (code %d)", result)
            end
        end
        return
    end

    -- Attack: selected unit + enemy at clicked hex
    if selected_unit_id ~= -1 and pos_map[clicked_key] and pos_map[clicked_key].faction ~= active then
        local enemy_id = pos_map[clicked_key].id
        norrust.apply_attack(engine, selected_unit_id, enemy_id)
        clear_selection()
        inspect_unit_id = enemy_id
        check_game_over()

    -- Move: selected unit + reachable hex
    elseif selected_unit_id ~= -1 and reachable_set[clicked_key] then
        norrust.apply_move(engine, selected_unit_id, col, row)
        clear_selection()
        check_game_over()

    -- Select friendly unit
    elseif pos_map[clicked_key] and pos_map[clicked_key].faction == active then
        select_unit(pos_map[clicked_key].id)

    -- Inspect enemy unit (no friendly selected)
    elseif pos_map[clicked_key] then
        inspect_unit_id = pos_map[clicked_key].id

    -- Empty hex: start drag
    else
        drag_active = true
        drag_start_x, drag_start_y = x, y
        drag_camera_start_x = camera_offset_x
        drag_camera_start_y = camera_offset_y
        clear_selection()
    end
end

-- ── love.mousereleased ──────────────────────────────────────────────────────

function love.mousereleased(x, y, button)
    if button == 1 then
        drag_active = false
    end
end

-- ── love.mousemoved ─────────────────────────────────────────────────────────

function love.mousemoved(x, y, dx, dy)
    if drag_active then
        camera_lerping = false
        camera_offset_x = drag_camera_start_x + (x - drag_start_x)
        camera_offset_y = drag_camera_start_y + (y - drag_start_y)
        apply_camera_offset()
    end
end

-- ── love.resize ─────────────────────────────────────────────────────────────

function love.resize(w, h)
    center_camera()
end
