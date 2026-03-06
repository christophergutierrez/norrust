-- norrust_love/main.lua — The Clash for Norrust — Love2D client
-- Port of norrust_client/scripts/game.gd (706 lines)

local norrust = require("norrust")
local assets = require("assets")
local anim_module = require("animation")
local hex = require("hex")
local draw_mod = require("draw")
local campaign_client = require("campaign_client")
local events = require("events")
local save = require("save")

-- ── Constants ───────────────────────────────────────────────────────────────

local BOARD_COLS = 8   -- set dynamically after scenario load
local BOARD_ROWS = 5   -- set dynamically after scenario load
local COLOR_FLAT = {0.29, 0.49, 0.31}
local UI_SCALE = 2.5
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
local inspect_terrain = nil    -- {col, row, terrain_id, defense, movement_cost, healing, unit_defense, unit_move_cost} or nil
local status_message = nil     -- temporary flash message (e.g. "Saved!")
local status_timer = 0         -- seconds remaining for status_message

-- Ghost movement
local ghost_col = nil          -- ghost hex col, or nil if not ghosting
local ghost_row = nil          -- ghost hex row
local ghost_unit_id = -1       -- the unit being ghosted
local ghost_attackable = {}    -- array of {id=N, col=C, row=R} for enemies attackable from ghost
local ghost_path = {}          -- array of {col=N, row=N} for path from unit to ghost position

-- Combat preview
local combat_preview = nil       -- table from simulate_combat JSON, or nil
local combat_preview_target = -1 -- defender unit id being previewed

-- Campaign
local campaigns_path = ""
local campaign_active = false
local campaign_data = nil        -- parsed JSON from norrust_load_campaign
local campaign_index = 0         -- 0-indexed current scenario in campaign
local campaign_veterans = {}     -- array of veteran unit tables from previous scenario
local campaign_gold = 0          -- carried gold for next scenario

-- Dialogue
local active_dialogue = {}     -- array of {id, text} currently displayed
local dialogue_history = {}    -- array of {turn, text} — all fired dialogue this scenario
local show_dialogue_history = false
local history_scroll = 0

-- Assets (loaded in love.load)
local terrain_tiles = {}
local unit_sprites = {}
local FACTION_COLORS = {[0] = {0.25, 0.42, 0.88}, [1] = {0.80, 0.12, 0.12}}
local unit_anims = {}  -- unit_id -> animation state (from anim_module.new_state())
local pending_anims = {}  -- array of {uid, end_time, return_to} for combat animations
-- move_anim stored as pending_anims.move to avoid exceeding LuaJIT 60-upvalue limit
-- pending_anims.move = {uid, path, seg, t, speed, on_complete} or nil

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
local camera_zoom = 1.0
local ZOOM_MIN = 0.15
local ZOOM_MAX = 3.0
local ZOOM_STEP = 0.1

-- Fonts (created in love.load)
local fonts = {}

-- ── Scale helpers ────────────────────────────────────────────────────────────

--- Return viewport dimensions scaled by UI_SCALE.
local function get_viewport()
    local w, h = love.graphics.getDimensions()
    return w / UI_SCALE, h / UI_SCALE
end

--- Convert screen coordinates to game (viewport) coordinates.
local function screen_to_game(x, y)
    return x / UI_SCALE, y / UI_SCALE
end

-- ── Utility helpers ─────────────────────────────────────────────────────────

--- Clamp a value between lo and hi.
local function clamp(val, lo, hi)
    return math.max(lo, math.min(hi, val))
end

--- Parse an HTML hex color string (e.g. "#4a7c4e") to {r, g, b} normalized floats.
local function parse_html_color(hex_str)
    if not hex_str or hex_str == "" then return nil end
    local r = tonumber(hex_str:sub(2, 3), 16) / 255
    local g = tonumber(hex_str:sub(4, 5), 16) / 255
    local b = tonumber(hex_str:sub(6, 7), 16) / 255
    return {r, g, b}
end

--- Truncate a number to integer (floor).
local function int(v) return math.floor(v) end

-- ── Camera ──────────────────────────────────────────────────────────────────

--- Clamp camera offset to allowed pan range.
local function apply_camera_offset()
    camera_offset_x = clamp(camera_offset_x, camera_min_x, camera_max_x)
    camera_offset_y = clamp(camera_offset_y, camera_min_y, camera_max_y)
end

--- Center camera on the board and compute pan limits.
--- If reset is true, auto-fit zoom so the whole board is visible and reset offset.
--- Called after every zoom change and on window resize.
local function center_camera(reset)
    local tlx, tly = hex.to_pixel(0, 0)
    local brx, bry = hex.to_pixel(BOARD_COLS - 1, BOARD_ROWS - 1)
    local vp_w, vp_h = get_viewport()
    -- Account for right-side panel (200px in game coords)
    local usable_w = vp_w - 200
    local center_px = (tlx + brx) / 2
    local center_py = (tly + bry) / 2

    if reset then
        -- Auto-fit: compute zoom so the full board fits in the usable viewport
        local board_w = (brx - tlx) + hex.RADIUS * 2
        local board_h = (bry - tly) + hex.RADIUS * 2
        local fit_zoom = math.min(usable_w / board_w, vp_h / board_h)
        camera_zoom = clamp(fit_zoom, ZOOM_MIN, ZOOM_MAX)
        camera_offset_x, camera_offset_y = 0, 0
        camera_lerping = false
    end

    -- Origin must account for zoom so board center stays at screen center
    -- Screen position of point px: board_origin_x + zoom * (offset_x + px)
    -- At offset=0, board center at screen center: origin = usable_w/2 - zoom * center
    board_origin_x = usable_w / 2 - camera_zoom * center_px
    board_origin_y = vp_h / 2 - camera_zoom * center_py

    -- Effective viewport in board-space coords (for pan limits)
    local eff_w = usable_w / camera_zoom
    local eff_h = vp_h / camera_zoom
    local board_half_w = (brx - tlx) / 2 + hex.RADIUS
    local board_half_h = (bry - tly) / 2 + hex.RADIUS
    local pan_range_x = math.max(board_half_w - eff_w / 2 + hex.RADIUS, 0)
    local pan_range_y = math.max(board_half_h - eff_h / 2 + hex.RADIUS, 0)
    camera_min_x, camera_min_y = -pan_range_x, -pan_range_y
    camera_max_x, camera_max_y = pan_range_x, pan_range_y
    apply_camera_offset()
end

-- ── Animation helpers ─────────────────────────────────────────────────────

--- Play a combat animation on a unit, returning to idle after it finishes.
-- @param uid number: unit id
-- @param anim_name string: animation state name (e.g. "attack-melee", "defend", "death")
-- @param duration number: seconds before returning to idle (0 = hold forever, e.g. death)
local function play_combat_anim(uid, anim_name, duration)
    local anim_state = unit_anims[uid]
    if not anim_state then return end
    local key = anim_state.def_id and anim_state.def_id:lower():gsub(" ", "_")
    local entry = key and unit_sprites[key]
    if not entry or not entry.anims or not entry.anims[anim_name] then return end
    anim_module.play(anim_state, anim_name)
    if duration > 0 then
        pending_anims[#pending_anims + 1] = {
            uid = uid,
            end_time = love.timer.getTime() + duration,
            return_to = "idle",
        }
    end
end

--- Trigger attack animations on attacker and defender.
-- Call BEFORE apply_attack so both units are still alive.
-- @param attacker_id number: attacking unit id
-- @param defender_id number: defending unit id
-- @param is_ranged boolean: true if ranged attack
local function trigger_attack_anims(attacker_id, defender_id, is_ranged)
    local atk_anim = is_ranged and "attack-ranged" or "attack-melee"
    play_combat_anim(attacker_id, atk_anim, 0.75)
    play_combat_anim(defender_id, "defend", 0.5)
end

--- Play death animation on a unit (holds on last frame, cleaned up when unit removed).
local function trigger_death_anim(uid)
    play_combat_anim(uid, "death", 0)  -- 0 = hold forever
end

--- Detect whether current combat preview is a ranged attack.
-- Checks hex distance between attacker and defender. Distance > 1 means ranged.
-- Must be called BEFORE cancel_combat_preview() and while ghost/selection state is valid.
local function is_ranged_attack()
    if not combat_preview or combat_preview_target < 0 then return false end
    local state = norrust.get_state(engine)
    local atk_col, atk_row, def_col, def_row
    -- Attacker position: ghost position if ghosting, else unit state position
    local atk_id = ghost_col ~= nil and ghost_unit_id or selected_unit_id
    if ghost_col ~= nil then
        atk_col, atk_row = ghost_col, ghost_row
    end
    for _, unit in ipairs(state.units or {}) do
        local uid = int(unit.id)
        if uid == atk_id and not atk_col then
            atk_col, atk_row = int(unit.col), int(unit.row)
        end
        if uid == combat_preview_target then
            def_col, def_row = int(unit.col), int(unit.row)
        end
    end
    if atk_col and def_col then
        return hex.distance(atk_col, atk_row, def_col, def_row) > 1
    end
    return false
end

--- Apply attack damage, trigger anims and check death.
-- @param attacker_id number: attacking unit id
-- @param defender_id number: defending unit id
-- @param is_ranged boolean: true if ranged attack
local function apply_attack_with_anims(attacker_id, defender_id, is_ranged)
    trigger_attack_anims(attacker_id, defender_id, is_ranged)
    norrust.apply_attack(engine, attacker_id, defender_id)
    local new_state = norrust.get_state(engine)
    local defender_alive = false
    for _, unit in ipairs(new_state.units or {}) do
        if int(unit.id) == defender_id then
            defender_alive = true
            break
        end
    end
    if not defender_alive then
        trigger_death_anim(defender_id)
    end
end

-- ── Dialogue helpers ────────────────────────────────────────────────────

-- ── Dialogue subscriber ─────────────────────────────────────────────────
-- Subscribes to gameplay events and manages dialogue UI state.

events.on("dialogue", function(data)
    local turn = norrust.get_turn(engine)
    local faction = norrust.get_active_faction(engine)
    local msgs = norrust.get_dialogue(engine, data.trigger, turn, faction, data.col, data.row)
    if #msgs > 0 then
        for _, m in ipairs(msgs) do active_dialogue[#active_dialogue + 1] = m end
        for _, m in ipairs(msgs) do
            dialogue_history[#dialogue_history + 1] = {turn = turn, text = m.text}
        end
    end
end)

events.on("scenario_loaded", function(data)
    dialogue_history = {}
    history_scroll = 0
    show_dialogue_history = false
    active_dialogue = {}

    local dialogue_path = scenarios_path .. "/" .. data.board:gsub("%.toml$", "_dialogue.toml")
    norrust.load_dialogue(engine, dialogue_path)
    events.emit("dialogue", {trigger = "scenario_start"})
end)

--- Execute an attack with combat animations.
-- Melee: attacker slides toward defender, attacks at contact, slides back.
-- Ranged: attacks in place (no movement).
-- @param attacker_id number: attacking unit id
-- @param defender_id number: defending unit id
-- @param is_ranged boolean: true if ranged attack
-- @param on_done function|nil: called after attack fully resolves
local function execute_attack(attacker_id, defender_id, is_ranged, on_done)
    -- Check if defender is a leader — fire leader_attacked trigger
    local pre_state = norrust.get_state(engine)
    for _, unit in ipairs(pre_state.units or {}) do
        if int(unit.id) == defender_id then
            for _, ab in ipairs(unit.abilities or {}) do
                if ab == "leader" then
                    events.emit("dialogue", {trigger = "leader_attacked"})
                    break
                end
            end
            break
        end
    end

    if is_ranged then
        apply_attack_with_anims(attacker_id, defender_id, true)
        if on_done then on_done() end
        return
    end

    -- Melee: look up positions for slide
    local state = norrust.get_state(engine)
    local ax, ay, dx, dy
    for _, unit in ipairs(state.units or {}) do
        local uid = int(unit.id)
        if uid == attacker_id then
            ax, ay = hex.to_pixel(int(unit.col), int(unit.row))
        elseif uid == defender_id then
            dx, dy = hex.to_pixel(int(unit.col), int(unit.row))
        end
    end

    if not ax or not dx then
        -- Fallback: can't find positions, attack without slide
        apply_attack_with_anims(attacker_id, defender_id, false)
        if on_done then on_done() end
        return
    end

    -- Slide 40% toward defender
    local mid_x = ax + (dx - ax) * 0.4
    local mid_y = ay + (dy - ay) * 0.4

    pending_anims.combat_slide = {
        uid = attacker_id,
        start_x = ax, start_y = ay,
        target_x = mid_x, target_y = mid_y,
        t = 0, speed = 6,
        phase = "approach",
        defender_id = defender_id,
        pause_remaining = nil,
        on_done = on_done,
    }
end

-- ── Game logic helpers ──────────────────────────────────────────────────────

--- Clear the combat preview state.
local function cancel_combat_preview()
    combat_preview = nil
    combat_preview_target = -1
end

--- Cancel ghost positioning and clear combat preview.
local function cancel_ghost()
    ghost_col = nil
    ghost_row = nil
    ghost_unit_id = -1
    ghost_attackable = {}
    ghost_path = {}
    cancel_combat_preview()
end

--- Deselect everything: unit, reachable hexes, inspection, ghost, and preview.
local function clear_selection()
    selected_unit_id = -1
    reachable_cells = {}
    reachable_set = {}
    inspect_unit_id = -1
    cancel_combat_preview()
    cancel_ghost()
end

--- Build a "col,row" → {id, faction} lookup from current game state units.
local function build_unit_pos_map(state)
    local result = {}
    for _, unit in ipairs(state.units or {}) do
        local c, r = int(unit.col), int(unit.row)
        local key = c .. "," .. r
        result[key] = {id = int(unit.id), faction = int(unit.faction), col = c, row = r}
    end
    return result
end

--- Get the max attack range for a unit (1=melee only, 2=has ranged).
local function unit_max_range(uid)
    local s = norrust.get_state(engine)
    for _, unit in ipairs(s.units or {}) do
        if int(unit.id) == uid then
            for _, atk in ipairs(unit.attacks or {}) do
                if atk.range == "ranged" then return 2 end
            end
            return 1
        end
    end
    return 1
end

--- Select a friendly unit: compute reachable hexes and lerp camera to it.
local function select_unit(uid)
    selected_unit_id = uid
    inspect_unit_id = uid
    inspect_terrain = nil
    reachable_cells = norrust.get_reachable_hexes(engine, uid)
    reachable_set = {}
    for _, cell in ipairs(reachable_cells) do
        reachable_set[cell.col .. "," .. cell.row] = true
    end

    -- Camera follow: center unit in viewport
    local state = norrust.get_state(engine)
    for _, unit in ipairs(state.units or {}) do
        if int(unit.id) == uid then
            local ux, uy = hex.to_pixel(int(unit.col), int(unit.row))
            local vp_w, vp_h = get_viewport()
            local usable_w = vp_w - 200
            camera_target_x = clamp((usable_w / 2 - board_origin_x) / camera_zoom - ux, camera_min_x, camera_max_x)
            camera_target_y = clamp((vp_h / 2 - board_origin_y) / camera_zoom - uy, camera_min_y, camera_max_y)
            camera_lerping = true
            break
        end
    end
end

--- Check if a faction has won and set game_over state.
local function check_game_over()
    local w = norrust.get_winner(engine)
    if w >= 0 then
        game_over = true
        winner_faction = w
    end
end

--- Odd-r offset neighbor table
--- Find enemy units within attack range of (col, row).
-- max_range: 1 for melee-only, 2 if unit has a ranged attack.
local function get_attackable_enemies(pos_map, col, row, faction, max_range)
    max_range = max_range or 1
    local enemies = {}
    for key, occ in pairs(pos_map) do
        if occ.faction ~= faction then
            local dist = hex.distance(col, row, occ.col, occ.row)
            if dist >= 1 and dist <= max_range then
                enemies[#enemies + 1] = {id = occ.id, col = occ.col, row = occ.row}
            end
        end
    end
    return enemies
end

--- Build a set of ghost_attackable IDs for fast lookup.
local function ghost_attackable_set()
    local s = {}
    for _, e in ipairs(ghost_attackable) do
        s[e.id] = true
    end
    return s
end

--- Start a movement animation along a path, then run on_complete.
-- Applies engine move immediately; animation is visual only.
local function start_move_anim(uid, path, on_complete)
    norrust.apply_move(engine, uid, path[#path].col, path[#path].row)
    pending_anims.move = {uid = uid, path = path, seg = 1, t = 0, speed = 10, on_complete = on_complete}
end

--- Emit hex_entered event for a destination hex.
local function fire_hex_entered(dest_col, dest_row)
    events.emit("dialogue", {trigger = "hex_entered", col = dest_col, row = dest_row})
end

--- Commit the ghost position as an actual move via the engine.
-- If a path exists (>= 2 waypoints), animates movement. Otherwise instant.
local function commit_ghost_move(on_complete)
    local uid = ghost_unit_id
    local path = ghost_path
    local dest_col, dest_row = ghost_col, ghost_row
    cancel_ghost()

    if path and #path >= 2 then
        start_move_anim(uid, path, function()
            selected_unit_id = uid
            inspect_unit_id = uid
            reachable_cells = {}
            reachable_set = {}
            check_game_over()
            fire_hex_entered(path[#path].col, path[#path].row)
            if on_complete then on_complete() end
        end)
    else
        norrust.apply_move(engine, uid, dest_col, dest_row)
        selected_unit_id = uid
        inspect_unit_id = uid
        reachable_cells = {}
        reachable_set = {}
        check_game_over()
        fire_hex_entered(dest_col, dest_row)
        if on_complete then on_complete() end
    end
end

--- Return 0 for blue setup, 1 for red setup.
local function faction_index_for_mode()
    return game_mode == SETUP_BLUE and 0 or 1
end

-- ── Campaign context helpers ────────────────────────────────────────────────

--- Build a mutable context table for campaign_client module calls.
local function build_campaign_ctx()
    return {
        norrust = norrust, engine = engine, int = int, hex = hex,
        scenarios_path = scenarios_path, scenario_board = scenario_board,
        scenario_units = scenario_units, scenario_preset = scenario_preset,
        BOARD_COLS = BOARD_COLS, BOARD_ROWS = BOARD_ROWS,
        center_camera = center_camera,
        campaign_data = campaign_data, campaign_index = campaign_index,
        campaign_veterans = campaign_veterans, campaign_gold = campaign_gold,
        faction_id = faction_id, game_over = game_over,
        winner_faction = winner_faction, recruit_mode = recruit_mode,
        next_unit_id = next_unit_id, game_mode = game_mode,
        PLAYING = PLAYING, clear_selection = clear_selection,
        build_unit_pos_map = build_unit_pos_map,
    }
end

--- Write back state modified by campaign_client into main.lua locals.
local function apply_campaign_ctx(ctx)
    BOARD_COLS = ctx.BOARD_COLS
    BOARD_ROWS = ctx.BOARD_ROWS
    scenario_board = ctx.scenario_board
    scenario_units = ctx.scenario_units
    scenario_preset = ctx.scenario_preset
    game_over = ctx.game_over
    winner_faction = ctx.winner_faction
    recruit_mode = ctx.recruit_mode
    next_unit_id = ctx.next_unit_id
    game_mode = ctx.game_mode
end

--- Load the selected scenario board via campaign_client with ctx writeback.
local function call_load_scenario()
    local ctx = build_campaign_ctx()
    campaign_client.load_selected_scenario(ctx)
    apply_campaign_ctx(ctx)
end

--- Load the next campaign scenario via campaign_client with ctx writeback.
local function call_load_campaign_scenario()
    local ctx = build_campaign_ctx()
    campaign_client.load_campaign_scenario(ctx)
    apply_campaign_ctx(ctx)
    events.emit("scenario_loaded", {board = scenario_board})
end

-- ── love.load ───────────────────────────────────────────────────────────────

--- Initialize engine, load data/factions/assets, and start at scenario selection.
function love.load()
    -- Check for generation flags
    for _, arg in ipairs(arg or {}) do
        if arg == "--generate-tiles" then
            local gen = require("generate_tiles")
            gen.run()
            love.event.quit()
            return
        elseif arg == "--viewer" then
            local viewer = require("viewer")
            viewer.set_scale(UI_SCALE)
            viewer.load()
            love.update = function(dt) viewer.update(dt) end
            love.draw = function()
                love.graphics.push()
                love.graphics.scale(UI_SCALE, UI_SCALE)
                viewer.draw()
                love.graphics.pop()
            end
            love.keypressed = function(key) viewer.keypressed(key) end
            love.wheelmoved = function(x, y) viewer.wheelmoved(x, y) end
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
    table.sort(factions, function(a, b) return a.name < b.name end)

    -- Load visual assets (graceful fallback if assets/ missing)
    terrain_tiles = assets.load_terrain_tiles("assets")
    unit_sprites = assets.load_unit_sprites("assets")

    -- Maximize window (keeps title bar with close button)
    love.window.maximize()

    -- Start at scenario selection
    game_mode = PICK_SCENARIO
end

-- ── love.update ─────────────────────────────────────────────────────────────

--- Per-frame update: animate units, handle camera panning and lerp.
function love.update(dt)
    -- Status message countdown
    if status_timer > 0 then
        status_timer = status_timer - dt
        if status_timer <= 0 then status_message = nil end
    end

    -- Update unit animations
    for uid, anim_state in pairs(unit_anims) do
        local entry = nil
        -- Find the unit's def_id to look up anim_data
        -- We need the state to map uid → def_id; cache is built during draw_units
        -- For efficiency, store def_id on the anim_state when created
        if anim_state.def_id then
            entry = unit_sprites[anim_state.def_id]
        end
        if entry and entry.anims then
            anim_module.update(anim_state, entry.anims, dt)
        end
    end

    -- Return combat animations to idle when their duration expires
    local now = love.timer.getTime()
    local i = 1
    while i <= #pending_anims do
        local pa = pending_anims[i]
        if now >= pa.end_time then
            local anim_state = unit_anims[pa.uid]
            if anim_state then
                anim_module.play(anim_state, pa.return_to)
            end
            table.remove(pending_anims, i)
        else
            i = i + 1
        end
    end

    -- Movement interpolation animation
    local ma = pending_anims.move
    if ma then
        ma.t = ma.t + ma.speed * dt
        while ma and ma.t >= 1.0 do
            ma.seg = ma.seg + 1
            ma.t = ma.t - 1.0
            if ma.seg >= #ma.path then
                local cb = ma.on_complete
                pending_anims.move = nil
                ma = nil
                if cb then cb() end
            end
        end
    end

    -- Combat slide animation (melee approach/return)
    local cs = pending_anims.combat_slide
    if cs then
        if cs.pause_remaining then
            -- Pausing at contact point (attack anims playing)
            cs.pause_remaining = cs.pause_remaining - dt
            if cs.pause_remaining <= 0 then
                -- Start return phase
                cs.phase = "return"
                cs.t = 0
                cs.pause_remaining = nil
                -- Swap direction: slide back to start
                cs.target_x, cs.start_x = cs.start_x, cs.target_x
                cs.target_y, cs.start_y = cs.start_y, cs.target_y
            end
        else
            cs.t = cs.t + cs.speed * dt
            if cs.t >= 1.0 then
                cs.t = 1.0
                if cs.phase == "approach" then
                    -- At contact: trigger attack, pause for anims
                    apply_attack_with_anims(cs.uid, cs.defender_id, false)
                    cs.pause_remaining = 0.3
                elseif cs.phase == "return" then
                    -- Back at start: done
                    local cb = cs.on_done
                    pending_anims.combat_slide = nil
                    if cb then cb() end
                end
            end
        end
    end

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

--- Build draw context (split into two functions to stay under LuaJIT 60-upvalue limit).
local function build_draw_ctx_state()
    return {
        -- State
        game_mode = game_mode, game_over = game_over, winner_faction = winner_faction,
        selected_unit_id = selected_unit_id, inspect_unit_id = inspect_unit_id,
        inspect_terrain = inspect_terrain, recruit_mode = recruit_mode,
        recruit_palette = recruit_palette, selected_recruit_idx = selected_recruit_idx,
        recruit_error = recruit_error, reachable_cells = reachable_cells,
        reachable_set = reachable_set,
        ghost_col = ghost_col, ghost_row = ghost_row, ghost_unit_id = ghost_unit_id,
        ghost_attackable = ghost_attackable, ghost_path = ghost_path,
        move_anim = pending_anims.move, combat_slide = pending_anims.combat_slide,
        combat_preview = combat_preview, combat_preview_target = combat_preview_target,
        -- Dialogue
        active_dialogue = active_dialogue,
        dialogue_history = dialogue_history,
        show_dialogue_history = show_dialogue_history,
        history_scroll = history_scroll,
        -- Status
        status_message = status_message,
        -- Campaign
        campaign_active = campaign_active, campaign_index = campaign_index,
        campaign_data = campaign_data,
        -- Setup state
        factions = factions, sel_faction_idx = sel_faction_idx,
        faction_id = faction_id, leader_placed = leader_placed,
        faction_index_for_mode = faction_index_for_mode,
    }
end

--- Dispatch to draw module with full context.
function love.draw()
    local state = engine and norrust.get_state(engine) or {}
    local ctx = build_draw_ctx_state()
    -- Modules
    ctx.hex = hex; ctx.assets = assets; ctx.anim_module = anim_module; ctx.norrust = norrust
    ctx.engine = engine
    -- Constants
    ctx.BLUE = BLUE; ctx.RED = RED; ctx.COLOR_FLAT = COLOR_FLAT
    ctx.UI_SCALE = UI_SCALE; ctx.BOARD_COLS = BOARD_COLS; ctx.BOARD_ROWS = BOARD_ROWS
    ctx.FACTION_COLORS = FACTION_COLORS; ctx.SCENARIOS = SCENARIOS; ctx.CAMPAIGNS = CAMPAIGNS
    -- Mode constants
    ctx.PICK_SCENARIO = PICK_SCENARIO; ctx.PICK_FACTION_BLUE = PICK_FACTION_BLUE
    ctx.PICK_FACTION_RED = PICK_FACTION_RED; ctx.SETUP_BLUE = SETUP_BLUE
    ctx.SETUP_RED = SETUP_RED; ctx.PLAYING = PLAYING
    -- Fonts, sprites
    ctx.fonts = fonts; ctx.terrain_tiles = terrain_tiles; ctx.unit_sprites = unit_sprites
    ctx.unit_anims = unit_anims
    -- Camera
    ctx.board_origin_x = board_origin_x; ctx.board_origin_y = board_origin_y
    ctx.camera_offset_x = camera_offset_x; ctx.camera_offset_y = camera_offset_y
    ctx.camera_zoom = camera_zoom
    -- Functions from main
    ctx.get_viewport = get_viewport; ctx.screen_to_game = screen_to_game
    ctx.int = int; ctx.parse_html_color = parse_html_color
    draw_mod.draw_frame(ctx, state)

    -- Status flash message (save/load feedback)
    if status_message then
        local vp_w = select(1, get_viewport())
        local f = fonts and fonts.medium or love.graphics.getFont()
        love.graphics.setFont(f)
        local tw = f:getWidth(status_message)
        local x = (vp_w - 200 - tw) / 2
        love.graphics.setColor(0, 0, 0, 0.7)
        love.graphics.rectangle("fill", x - 10, 10, tw + 20, f:getHeight() + 10, 6, 6)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.print(status_message, x, 15)
    end
end

-- ── love.keypressed ─────────────────────────────────────────────────────────

--- Handle keyboard input: scenario selection, setup, and gameplay controls.
function love.keypressed(key)
    -- Block input during movement animation
    if pending_anims.move or pending_anims.combat_slide then return end

    -- Build campaign context for save (nil if not in campaign)
    local function build_save_campaign_ctx()
        if not campaign_active then return nil end
        return {
            file = CAMPAIGNS[1].file,
            index = campaign_index,
            gold = campaign_gold,
            veterans = campaign_veterans,
            faction_id = faction_id,
        }
    end

    -- Save/Load (available from any mode)
    if key == "f5" and game_mode == PLAYING then
        local filename = save.write_save(engine, norrust, scenario_board, scenarios_path, build_save_campaign_ctx())
        if filename then
            status_message = "Saved: " .. filename
        else
            status_message = "Save failed!"
        end
        status_timer = 3.0
        return
    elseif key == "f9" then
        local filepath = save.find_latest()
        if filepath then
            local data = save.load_save(engine, norrust, filepath, center_camera)
            if data then
                scenario_board = data.game.board_path
                scenarios_path = data.game.scenarios_path
                game_over = false
                winner_faction = -1
                clear_selection()
                next_unit_id = norrust.get_next_unit_id(engine)
                -- Update board dimensions from loaded state
                local state = norrust.get_state(engine)
                BOARD_COLS = int(state.cols or 8)
                BOARD_ROWS = int(state.rows or 5)
                center_camera()
                -- Restore campaign context if present
                if data.campaign then
                    local c = data.campaign
                    campaign_active = true
                    campaign_data = norrust.load_campaign(engine, campaigns_path .. "/" .. c.campaign_file)
                    campaign_index = int(c.campaign_index)
                    campaign_gold = int(c.campaign_gold)
                    faction_id = {c.faction_id_0, c.faction_id_1}
                    -- Restore veterans
                    campaign_veterans = data.veterans or {}
                else
                    campaign_active = false
                    campaign_data = nil
                    campaign_index = 0
                    campaign_veterans = {}
                    campaign_gold = 0
                end
                game_mode = PLAYING
                status_message = "Loaded: " .. filepath
            else
                status_message = "Load failed!"
            end
        else
            status_message = "No save files found"
        end
        status_timer = 3.0
        return
    end

    -- Scenario selection
    if game_mode == PICK_SCENARIO then
        local num = tonumber(key)
        if num and num >= 1 and num <= #SCENARIOS then
            campaign_active = false
            scenario_board = SCENARIOS[num].board
            scenario_units = SCENARIOS[num].units
            scenario_preset = SCENARIOS[num].preset_units
            call_load_scenario()
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
                call_load_scenario()
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
                        call_load_campaign_scenario()
                    else
                        -- Both factions chosen — load units and start
                        norrust.apply_starting_gold(engine, faction_id[1], faction_id[2])
                        norrust.load_units(engine, scenarios_path .. "/" .. scenario_units)
                        next_unit_id = norrust.get_next_unit_id(engine)
                        game_mode = PLAYING
                        events.emit("scenario_loaded", {board = scenario_board})
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
                events.emit("scenario_loaded", {board = scenario_board})
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
                    call_load_campaign_scenario()
                else
                    -- Campaign complete — return to scenario selection
                    campaign_active = false
                    game_over = false
                    winner_faction = -1
                    game_mode = PICK_SCENARIO
                end
            else
                -- Individual scenario win/loss, or campaign defeat
                campaign_active = false
                game_over = false
                winner_faction = -1
                game_mode = PICK_SCENARIO
            end
        end
        return
    end

    if key == "escape" then
        -- Cancel combat preview, or ghost, or selection
        if combat_preview ~= nil then
            cancel_combat_preview()
        elseif ghost_col ~= nil then
            cancel_ghost()
        else
            clear_selection()
        end

    elseif (key == "return" or key == "kpenter") then
        if combat_preview ~= nil and combat_preview_target >= 0 and ghost_col ~= nil then
            -- Commit ghost move + attack previewed target
            local enemy_id = combat_preview_target
            local ranged = is_ranged_attack()
            cancel_combat_preview()
            commit_ghost_move(function()
                execute_attack(selected_unit_id, enemy_id, ranged, function()
                    clear_selection()
                    inspect_unit_id = enemy_id
                    check_game_over()
                end)
            end)
        elseif combat_preview ~= nil and combat_preview_target >= 0 and selected_unit_id ~= -1 then
            -- Direct adjacent attack from preview
            local enemy_id = combat_preview_target
            local ranged = is_ranged_attack()
            cancel_combat_preview()
            execute_attack(selected_unit_id, enemy_id, ranged, function()
                clear_selection()
                inspect_unit_id = enemy_id
                check_game_over()
            end)
        elseif ghost_col ~= nil then
            -- Commit ghost move only
            commit_ghost_move()
        end

    elseif key == "e" then
        -- Auto-save before ending turn
        save.write_save(engine, norrust, scenario_board, scenarios_path, build_save_campaign_ctx())

        events.emit("dialogue", {trigger = "turn_end"})

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

        -- New turn dialogue (reset panel so only new messages show)
        active_dialogue = {}
        events.emit("dialogue", {trigger = "turn_start"})

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

    elseif key == "h" then
        -- Toggle dialogue history
        show_dialogue_history = not show_dialogue_history
        if show_dialogue_history then history_scroll = 0 end

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

--- Handle mouse clicks: unit selection, movement, attack, recruitment, and camera drag.
function love.mousepressed(sx, sy, button)
    -- Block input during movement animation
    if pending_anims.move or pending_anims.combat_slide then return end

    local x, y = screen_to_game(sx, sy)

    -- Ignore clicks in the right panel area (rightmost 200px of viewport)
    local vp_w = select(1, get_viewport())
    if x >= vp_w - 200 then return end

    -- Right-click: terrain inspection (any mode with a board)
    if button == 2 and game_mode == PLAYING and not game_over then
        local local_x = (x - board_origin_x) / camera_zoom - camera_offset_x
        local local_y = (y - board_origin_y) / camera_zoom - camera_offset_y
        local col, row = hex.from_pixel(local_x, local_y)
        if col >= 0 and col < BOARD_COLS and row >= 0 and row < BOARD_ROWS then
            local state = norrust.get_state(engine)
            for _, tile in ipairs(state.terrain or {}) do
                if int(tile.col) == col and int(tile.row) == row then
                    inspect_terrain = {
                        col = col, row = row,
                        terrain_id = tile.terrain_id,
                        defense = int(tile.defense),
                        movement_cost = int(tile.movement_cost),
                        healing = int(tile.healing),
                    }
                    if selected_unit_id ~= -1 then
                        local info = norrust.get_unit_terrain_info(engine, selected_unit_id, col, row)
                        if info then
                            inspect_terrain.unit_defense = int(info.defense)
                            inspect_terrain.unit_move_cost = int(info.movement_cost)
                        end
                    end
                    inspect_unit_id = -1
                    return
                end
            end
        end
        return
    end

    if button ~= 1 then return end
    if game_mode == PICK_SCENARIO then return end

    -- Setup mode click
    if game_mode ~= PLAYING then
        if game_mode == PICK_FACTION_BLUE or game_mode == PICK_FACTION_RED then
            return
        end

        local local_x = (x - board_origin_x) / camera_zoom - camera_offset_x
        local local_y = (y - board_origin_y) / camera_zoom - camera_offset_y
        local col, row = hex.from_pixel(local_x, local_y)

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
    local vp_w = love.graphics.getWidth() / UI_SCALE
    if x > vp_w - 200 then return end

    -- Convert screen coords to hex
    local local_x = (x - board_origin_x) / camera_zoom - camera_offset_x
    local local_y = (y - board_origin_y) / camera_zoom - camera_offset_y
    local col, row = hex.from_pixel(local_x, local_y)

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

    -- Ghost active: handle clicks from ghost state
    if ghost_col ~= nil then
        local atk_set = ghost_attackable_set()

        -- Click highlighted enemy → show combat preview (or execute if same target clicked twice)
        if pos_map[clicked_key] and atk_set[pos_map[clicked_key].id] then
            local enemy_id = pos_map[clicked_key].id
            if combat_preview_target == enemy_id then
                -- Second click on same enemy → commit move + attack
                local ranged = is_ranged_attack()
                cancel_combat_preview()
                commit_ghost_move(function()
                    execute_attack(selected_unit_id, enemy_id, ranged, function()
                        clear_selection()
                        inspect_unit_id = enemy_id
                        check_game_over()
                    end)
                end)
            else
                -- First click (or different enemy) → show combat preview
                combat_preview = norrust.simulate_combat(engine, ghost_unit_id, enemy_id, ghost_col, ghost_row, 100)
                combat_preview_target = enemy_id
                inspect_unit_id = enemy_id
            end

        -- Click the ghost hex itself → commit move only
        elseif col == ghost_col and row == ghost_row then
            commit_ghost_move()

        -- Click a different reachable hex → re-ghost, auto-preview if same target adjacent
        elseif reachable_set[clicked_key] and not pos_map[clicked_key] then
            local prev_target = combat_preview_target
            cancel_combat_preview()
            ghost_col = col
            ghost_row = row
            ghost_attackable = get_attackable_enemies(pos_map, col, row, active, unit_max_range(ghost_unit_id))
            ghost_path = norrust.find_path(engine, ghost_unit_id, col, row)
            -- Auto-preview: if previously previewed enemy is still in range, re-show preview
            if prev_target ~= -1 then
                for _, e in ipairs(ghost_attackable) do
                    if e.id == prev_target then
                        combat_preview = norrust.simulate_combat(engine, ghost_unit_id, prev_target, ghost_col, ghost_row, 100)
                        combat_preview_target = prev_target
                        inspect_unit_id = prev_target
                        break
                    end
                end
            end

        -- Click friendly unit → cancel ghost, select new unit
        elseif pos_map[clicked_key] and pos_map[clicked_key].faction == active then
            cancel_ghost()
            select_unit(pos_map[clicked_key].id)

        -- Anything else → cancel ghost and clear
        else
            clear_selection()
        end

    -- No ghost: direct adjacent attack → show combat preview first
    elseif selected_unit_id ~= -1 and pos_map[clicked_key] and pos_map[clicked_key].faction ~= active then
        local enemy_id = pos_map[clicked_key].id
        if combat_preview_target == enemy_id then
            -- Second click on same enemy → execute attack
            local ranged = is_ranged_attack()
            cancel_combat_preview()
            execute_attack(selected_unit_id, enemy_id, ranged, function()
                clear_selection()
                inspect_unit_id = enemy_id
                check_game_over()
            end)
        else
            -- First click → show combat preview (attacker at current position)
            local atk_col, atk_row = nil, nil
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == selected_unit_id then
                    atk_col = int(unit.col)
                    atk_row = int(unit.row)
                    break
                end
            end
            if atk_col then
                combat_preview = norrust.simulate_combat(engine, selected_unit_id, enemy_id, atk_col, atk_row, 100)
                combat_preview_target = enemy_id
                inspect_unit_id = enemy_id
            end
        end

    -- Ghost: selected unit + reachable empty hex → enter ghost state
    elseif selected_unit_id ~= -1 and reachable_set[clicked_key] and not pos_map[clicked_key] then
        ghost_col = col
        ghost_row = row
        ghost_unit_id = selected_unit_id
        ghost_attackable = get_attackable_enemies(pos_map, col, row, active, unit_max_range(selected_unit_id))
        ghost_path = norrust.find_path(engine, selected_unit_id, col, row)

    -- Select friendly unit
    elseif pos_map[clicked_key] and pos_map[clicked_key].faction == active then
        select_unit(pos_map[clicked_key].id)

    -- Inspect enemy unit (no friendly selected)
    elseif pos_map[clicked_key] then
        inspect_unit_id = pos_map[clicked_key].id
        inspect_terrain = nil

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

--- End camera drag on mouse release.
function love.mousereleased(x, y, button)
    if button == 1 then
        drag_active = false
    end
end

-- ── love.mousemoved ─────────────────────────────────────────────────────────

--- Update camera offset during drag.
function love.mousemoved(sx, sy, dx, dy)
    if drag_active then
        camera_lerping = false
        local x, y = screen_to_game(sx, sy)
        camera_offset_x = drag_camera_start_x + (x - drag_start_x) / camera_zoom
        camera_offset_y = drag_camera_start_y + (y - drag_start_y) / camera_zoom
        apply_camera_offset()
    end
end

-- ── love.wheelmoved ─────────────────────────────────────────────────────────

--- Zoom board in/out with scroll wheel.
function love.wheelmoved(x, y)
    if show_dialogue_history then
        -- Scroll history panel (y > 0 = scroll up = show earlier entries)
        history_scroll = math.max(0, history_scroll - y * 20)
        return
    end
    if y > 0 then
        camera_zoom = math.min(camera_zoom + ZOOM_STEP, ZOOM_MAX)
    elseif y < 0 then
        camera_zoom = math.max(camera_zoom - ZOOM_STEP, ZOOM_MIN)
    end
    center_camera()
end

-- ── love.resize ─────────────────────────────────────────────────────────────

--- Re-center camera when window is resized.
function love.resize(w, h)
    center_camera()
end
