-- norrust_love/main.lua — The Clash for Norrust — Love2D client
-- Main game module: love.load, love.update, love.draw, context tables, event wiring

local norrust = require("norrust")
local assets = require("assets")
local anim_module = require("animation")
local hex = require("hex")
local draw_mod = require("draw")
local campaign_client = require("campaign_client")
local events = require("events")
local save = require("save")
local roster_mod = require("roster")
local agent_server = require("agent_server")
local input = require("input")
local state_mod = require("state")
local camera_mod = require("camera_mod")
local combat_mod = require("combat_mod")

-- ── Constants ───────────────────────────────────────────────────────────────

local COLOR_FLAT = {0.29, 0.49, 0.31}
local UI_SCALE = 2.5
local BLUE = {0.25, 0.42, 0.88}
local RED  = {0.80, 0.12, 0.12}

-- Game modes
local MODES = {
    PICK_SCENARIO = -1,
    PICK_FACTION_BLUE = 0, PICK_FACTION_RED = 1,
    SETUP_BLUE = 2, SETUP_RED = 3,
    PLAYING = 4,
    LOAD_SAVE = 5,
    DEPLOY_VETERANS = 6,
}

-- Game data: scenarios, campaigns, faction state
local game_data = {
    SCENARIOS = {
        {name = "Contested (8x5)",  board = "contested/board.toml",  units = "contested/units.toml", preset_units = false},
        {name = "Crossing (16x10)", board = "crossing/board.toml",   units = "crossing/units.toml",  preset_units = true},
        {name = "Ambush (12x8)",    board = "ambush/board.toml",     units = "ambush/units.toml",    preset_units = true},
        {name = "Night Orcs (20x12)", board = "night_orcs/board.toml", units = "night_orcs/units.toml", preset_units = true},
        {name = "Final Battle (24x14)", board = "final_battle/board.toml", units = "final_battle/units.toml", preset_units = true},
    },
    CAMPAIGNS = {
        {name = "The Road to Norrust", file = "tutorial.toml"},
    },
    factions = {},
    faction_id = {"", ""},
    leader_placed = {false, false},
    save_list = {},
    save_idx = 1,
    save_renaming = false,
    save_rename_text = "",
}

-- ── State (from state.lua) ────────────────────────────────────────────────

local vars = state_mod.vars
local combat_state = state_mod.combat_state
local ai = state_mod.ai
local shared = state_mod.shared
local terrain_tiles = state_mod.terrain_tiles
local unit_sprites = state_mod.unit_sprites
local tile_color_cache = state_mod.tile_color_cache
local FACTION_COLORS = state_mod.FACTION_COLORS
local unit_anims = state_mod.unit_anims
local dying_units = state_mod.dying_units
local pending_anims = state_mod.pending_anims
local fonts = state_mod.fonts
local scn = state_mod.scn
local sel = state_mod.sel
local ghost = state_mod.ghost
local campaign = state_mod.campaign
local dlg = state_mod.dlg
local camera = state_mod.camera

local sound = require("sound")
shared.agent_mod = agent_server

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

--- Build tile color cache from current engine state.
local function build_tile_color_cache()
    for k in pairs(tile_color_cache) do tile_color_cache[k] = nil end
    if not vars.engine then return end
    local state = norrust.get_state(vars.engine)
    for _, tile in ipairs(state.terrain or {}) do
        local key = int(tile.col) .. "," .. int(tile.row)
        tile_color_cache[key] = parse_html_color(tile.color) or COLOR_FLAT
    end
end

-- ── Camera (delegated to camera_mod.lua) ────────────────────────────────────

local function apply_camera_offset() camera_mod.apply_offset() end
local function center_camera(reset) camera_mod.center(reset) end

-- ── Combat (delegated to combat_mod.lua) ─────────────────────────────────

local function is_ranged_attack() return combat_mod.is_ranged_attack() end
local function execute_attack(...) return combat_mod.execute_attack(...) end

-- ── Dialogue subscriber ─────────────────────────────────────────────────
-- Subscribes to gameplay events and manages dialogue UI state.

events.on("dialogue", function(data)
    local turn = norrust.get_turn(vars.engine)
    local faction = norrust.get_active_faction(vars.engine)
    local msgs = norrust.get_dialogue(vars.engine, data.trigger, turn, faction, data.col, data.row)
    if #msgs > 0 then
        for _, m in ipairs(msgs) do dlg.active[#dlg.active + 1] = m end
        for _, m in ipairs(msgs) do
            dlg.history[#dlg.history + 1] = {turn = turn, text = m.text}
        end
    end
end)

events.on("scenario_loaded", function(data)
    dlg.history = {}
    dlg.scroll = 0
    dlg.show_history = false
    dlg.active = {}

    local dialogue_path = scn.path .. "/" .. data.board:gsub("board%.toml$", "dialogue.toml")
    norrust.load_dialogue(vars.engine, dialogue_path)
    events.emit("dialogue", {trigger = "scenario_start"})

    -- Per-scenario music (optional music.ogg in scenario directory)
    local music_vfs = "scenarios/" .. data.board:gsub("board%.toml$", "music.ogg")
    sound.play_music(music_vfs)
end)

-- ── Game logic helpers ──────────────────────────────────────────────────────

--- Clear the combat preview state.
local function cancel_combat_preview()
    combat_state.preview = nil
    combat_state.target = -1
end

--- Cancel ghost positioning and clear combat preview.
local function cancel_ghost()
    ghost.col = nil
    ghost.row = nil
    ghost.unit_id = -1
    ghost.attackable = {}
    ghost.path = {}
    cancel_combat_preview()
end

--- Deselect everything: unit, reachable hexes, inspection, ghost, and preview.
local function clear_selection()
    sel.unit_id = -1
    sel.reachable_cells = {}
    sel.reachable_set = {}
    sel.inspect_id = -1
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
    local s = norrust.get_state(vars.engine)
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
    sound.play("select")
    sel.unit_id = uid
    sel.inspect_id = uid
    sel.inspect_terrain = nil
    sel.reachable_cells = norrust.get_reachable_hexes(vars.engine, uid)
    sel.reachable_set = {}
    for _, cell in ipairs(sel.reachable_cells) do
        sel.reachable_set[cell.col .. "," .. cell.row] = true
    end

    -- Camera follow: center unit in viewport
    local state = norrust.get_state(vars.engine)
    for _, unit in ipairs(state.units or {}) do
        if int(unit.id) == uid then
            local ux, uy = hex.to_pixel(int(unit.col), int(unit.row))
            local vp_w, vp_h = get_viewport()
            local usable_w = vp_w - 200
            camera.target_x = clamp((usable_w / 2 - camera.origin_x) / camera.zoom - ux, camera.min_x, camera.max_x)
            camera.target_y = clamp((vp_h / 2 - camera.origin_y) / camera.zoom - uy, camera.min_y, camera.max_y)
            camera.lerping = true
            break
        end
    end
end

--- Check if a faction has won and set vars.game_over state.
local function check_game_over()
    local w = norrust.get_winner(vars.engine)
    if w >= 0 then
        vars.game_over = true
        vars.winner_faction = w
        if w == 0 then
            save.write_save(vars.engine, norrust, scn.board, scn.path, nil)
        end
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

--- Build a set of ghost.attackable IDs for fast lookup.
local function ghost_attackable_set()
    local s = {}
    for _, e in ipairs(ghost.attackable) do
        s[e.id] = true
    end
    return s
end

--- Start a movement animation along a path, then run on_complete.
-- Applies vars.engine move immediately; animation is visual only.
local function start_move_anim(uid, path, on_complete)
    norrust.apply_move(vars.engine, uid, path[#path].col, path[#path].row)
    sound.play("move")
    pending_anims.move = {uid = uid, path = path, seg = 1, t = 0, speed = 10, on_complete = on_complete}
end

--- Emit hex_entered event for a destination hex.
local function fire_hex_entered(dest_col, dest_row)
    events.emit("dialogue", {trigger = "hex_entered", col = dest_col, row = dest_row})
end

--- Commit the ghost position as an actual move via the vars.engine.
-- If a path exists (>= 2 waypoints), animates movement. Otherwise instant.
local function commit_ghost_move(on_complete)
    local uid = ghost.unit_id
    local path = ghost.path
    local dest_col, dest_row = ghost.col, ghost.row
    cancel_ghost()

    if path and #path >= 2 then
        start_move_anim(uid, path, function()
            sel.unit_id = uid
            sel.inspect_id = uid
            sel.reachable_cells = {}
            sel.reachable_set = {}
            check_game_over()
            fire_hex_entered(path[#path].col, path[#path].row)
            if on_complete then on_complete() end
        end)
    else
        norrust.apply_move(vars.engine, uid, dest_col, dest_row)
        sel.unit_id = uid
        sel.inspect_id = uid
        sel.reachable_cells = {}
        sel.reachable_set = {}
        check_game_over()
        fire_hex_entered(dest_col, dest_row)
        if on_complete then on_complete() end
    end
end

--- Return 0 for blue setup, 1 for red setup.
local function faction_index_for_mode()
    return vars.game_mode == MODES.SETUP_BLUE and 0 or 1
end

-- ── Campaign context helpers ────────────────────────────────────────────────

--- Build a mutable context table for campaign_client module calls.
local function build_campaign_ctx()
    return {
        norrust = norrust, engine = vars.engine, int = int, hex = hex,
        scenarios_path = scn.path, scenario_board = scn.board,
        scenario_units = scn.units, scenario_preset = scn.preset,
        BOARD_COLS = scn.COLS, BOARD_ROWS = scn.ROWS,
        center_camera = center_camera,
        campaign_data = campaign.data, campaign_index = campaign.index,
        campaign_veterans = campaign.veterans, campaign_gold = campaign.gold,
        campaign_roster = campaign.roster, roster_mod = roster_mod,
        faction_id = game_data.faction_id, game_over = vars.game_over,
        winner_faction = vars.winner_faction, recruit_mode = sel.recruit_mode,
        game_mode = vars.game_mode,
        PLAYING = MODES.PLAYING, DEPLOY_VETERANS = MODES.DEPLOY_VETERANS,
        clear_selection = clear_selection,
        build_unit_pos_map = build_unit_pos_map,
        campaign_deploy = campaign.deploy,
    }
end

--- Write back state modified by campaign_client into main.lua locals.
local function apply_campaign_ctx(ctx)
    scn.COLS = ctx.BOARD_COLS
    scn.ROWS = ctx.BOARD_ROWS
    scn.board = ctx.scenario_board
    scn.units = ctx.scenario_units
    scn.preset = ctx.scenario_preset
    vars.game_over = ctx.game_over
    vars.winner_faction = ctx.winner_faction
    sel.recruit_mode = ctx.recruit_mode
    vars.game_mode = ctx.game_mode
end

--- Load the selected scenario board via campaign_client with ctx writeback.
local function call_load_scenario()
    local ctx = build_campaign_ctx()
    campaign_client.load_selected_scenario(ctx)
    apply_campaign_ctx(ctx)
    build_tile_color_cache()
end

--- Load the next campaign scenario via campaign_client with ctx writeback.
local function call_load_campaign_scenario()
    local ctx = build_campaign_ctx()
    campaign_client.load_campaign_scenario(ctx)
    apply_campaign_ctx(ctx)
    build_tile_color_cache()
    events.emit("scenario_loaded", {board = scn.board})
end

-- ── love.load ───────────────────────────────────────────────────────────────

--- Initialize vars.engine, load data/factions/assets, and start at scenario selection.
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

    -- Create vars.engine
    vars.engine = norrust.new()

    -- Paths (norrust_love is one level inside project root)
    local source = love.filesystem.getSource()
    local project_root = source .. "/.."
    local data_path = project_root .. "/data"
    scn.path = project_root .. "/scenarios"

    campaign.path = project_root .. "/campaigns"

    -- Load data + factions (scenario loaded after selection)
    assert(norrust.load_data(vars.engine, data_path), "Failed to load data")
    assert(norrust.load_factions(vars.engine, data_path), "Failed to load factions")

    -- Parse faction list
    game_data.factions = norrust.get_faction_ids(vars.engine)
    table.sort(game_data.factions, function(a, b) return a.name < b.name end)

    -- Load visual assets from data/ via symlink (data -> ../data)
    terrain_tiles = assets.load_terrain_tiles("data")
    unit_sprites = assets.load_unit_sprites("data")

    -- Load sound effects and start menu music
    sound.load()
    sound.play_music("data/sounds/menu_music.ogg")

    -- Maximize window (keeps title bar with close button)
    love.window.maximize()

    -- Check for CLI flags
    local args = arg or {}
    for i, a in ipairs(args) do
        if a == "--agent-server" then
            shared.agent = agent_server.new(9876)
            if shared.agent then
                vars.status_message = "Agent server on port 9876"
                vars.status_timer = 5.0
            end
        elseif a == "--ai-vs-ai" then
            ai.vs_ai = true
            -- Also start agent server for external observation
            if not shared.agent then
                shared.agent = agent_server.new(9876)
            end
        elseif a == "--ai-delay" and args[i + 1] then
            ai.delay = tonumber(args[i + 1]) or 0.5
        end
    end

    -- Start at scenario selection
    vars.game_mode = MODES.PICK_SCENARIO

    -- Initialize camera module
    camera_mod.init({camera = camera, hex = hex, scn = scn, get_viewport = get_viewport, clamp = clamp})

    -- Initialize combat module
    combat_mod.init({
        unit_anims = unit_anims, unit_sprites = unit_sprites,
        anim_module = anim_module, pending_anims = pending_anims,
        dying_units = dying_units, norrust = norrust, vars = vars,
        hex = hex, sound = sound, combat_state = combat_state,
        ghost = ghost, sel = sel, events = events, int = int,
    })

    -- Initialize input handler module with all context references
    input.init({
        vars = vars, scn = scn, sel = sel, ghost = ghost,
        campaign = campaign, dlg = dlg, camera = camera,
        shared = shared, combat_state = combat_state, sound = sound,
        pending_anims = pending_anims,
        game_data = game_data,
        mods = {norrust = norrust, hex = hex, events = events, save = save, roster_mod = roster_mod},
        MODES = MODES,
        UI_SCALE = UI_SCALE,
        get_viewport = get_viewport, screen_to_game = screen_to_game,
        int = int,
        center_camera = center_camera, clear_selection = clear_selection,
        cancel_ghost = cancel_ghost, cancel_combat_preview = cancel_combat_preview,
        is_ranged_attack = is_ranged_attack, commit_ghost_move = commit_ghost_move,
        execute_attack = execute_attack, check_game_over = check_game_over,
        build_unit_pos_map = build_unit_pos_map, unit_max_range = unit_max_range,
        select_unit = select_unit, get_attackable_enemies = get_attackable_enemies,
        ghost_attackable_set = ghost_attackable_set,
        call_load_scenario = call_load_scenario,
        call_load_campaign_scenario = call_load_campaign_scenario,
        campaign_client = campaign_client,
        faction_index_for_mode = faction_index_for_mode,
        apply_camera_offset = apply_camera_offset,
    })
end

-- ── love.update ─────────────────────────────────────────────────────────────

--- Per-frame update: animate units, handle camera panning and lerp.
function love.update(dt)
    -- Agent server: process TCP commands
    if shared.agent then
        agent_server.update(shared.agent, norrust, vars.engine)
    end

    -- AI vs AI: auto-play both factions
    if ai.vs_ai and vars.game_mode == MODES.PLAYING and not vars.game_over
       and not pending_anims.move and #pending_anims == 0 and not pending_anims.combat_slide then
        ai.timer = ai.timer - dt
        if ai.timer <= 0 then
            local f = norrust.get_active_faction(vars.engine)
            local fid = game_data.faction_id[f + 1]
            if fid and fid ~= "" then
                norrust.ai_recruit(vars.engine, fid)
                norrust.ai_take_turn(vars.engine, f)
                check_game_over()
            end
            ai.timer = ai.delay
        end
    end

    -- Status message countdown
    if vars.status_timer > 0 then
        vars.status_timer = vars.status_timer - dt
        if vars.status_timer <= 0 then vars.status_message = nil end
    end

    -- Combat and animation tick
    combat_mod.update_anims(dt)

    -- Camera panning and lerp
    camera_mod.update(dt)
end

-- ── love.draw ───────────────────────────────────────────────────────────────

--- Build draw context state table.
local function build_draw_ctx_state()
    return {
        game_mode = vars.game_mode, game_over = vars.game_over, winner_faction = vars.winner_faction,
        selected_unit_id = sel.unit_id, inspect_unit_id = sel.inspect_id,
        inspect_terrain = sel.inspect_terrain, recruit_mode = sel.recruit_mode,
        recruit_palette = sel.recruit_palette, recruit_veterans = sel.recruit_state.veterans,
        selected_recruit_idx = sel.recruit_idx,
        recruit_error = sel.recruit_error, reachable_cells = sel.reachable_cells,
        reachable_set = sel.reachable_set,
        ghost_col = ghost.col, ghost_row = ghost.row, ghost_unit_id = ghost.unit_id,
        ghost_attackable = ghost.attackable, ghost_path = ghost.path,
        move_anim = pending_anims.move, combat_slide = pending_anims.combat_slide,
        combat_preview = combat_state.preview, combat_preview_target = combat_state.target,
        active_dialogue = dlg.active,
        dialogue_history = dlg.history,
        show_dialogue_history = dlg.show_history,
        history_scroll = dlg.scroll,
        status_message = vars.status_message,
        campaign_active = campaign.active, campaign_index = campaign.index,
        campaign_data = campaign.data,
        factions = game_data.factions, sel_faction_idx = vars.sel_faction_idx,
        faction_id = game_data.faction_id, leader_placed = game_data.leader_placed,
        faction_index_for_mode = faction_index_for_mode,
    }
end

--- Dispatch to draw module with full context.
function love.draw()
    local state = vars.engine and norrust.get_state(vars.engine) or {}
    local ctx = build_draw_ctx_state()
    -- Modules
    ctx.hex = hex; ctx.assets = assets; ctx.anim_module = anim_module; ctx.norrust = norrust
    ctx.engine = vars.engine
    -- Constants
    ctx.BLUE = BLUE; ctx.RED = RED; ctx.COLOR_FLAT = COLOR_FLAT
    ctx.UI_SCALE = UI_SCALE; ctx.BOARD_COLS = scn.COLS; ctx.BOARD_ROWS = scn.ROWS
    ctx.FACTION_COLORS = FACTION_COLORS; ctx.SCENARIOS = game_data.SCENARIOS; ctx.CAMPAIGNS = game_data.CAMPAIGNS
    -- Mode constants
    ctx.PICK_SCENARIO = MODES.PICK_SCENARIO; ctx.PICK_FACTION_BLUE = MODES.PICK_FACTION_BLUE
    ctx.PICK_FACTION_RED = MODES.PICK_FACTION_RED; ctx.SETUP_BLUE = MODES.SETUP_BLUE
    ctx.SETUP_RED = MODES.SETUP_RED; ctx.PLAYING = MODES.PLAYING; ctx.LOAD_SAVE = MODES.LOAD_SAVE
    ctx.save_list = game_data.save_list; ctx.save_idx = game_data.save_idx
    ctx.save_renaming = game_data.save_renaming; ctx.save_rename_text = game_data.save_rename_text
    ctx.DEPLOY_VETERANS = MODES.DEPLOY_VETERANS; ctx.deploy = campaign.deploy
    -- Fonts, sprites
    ctx.fonts = fonts; ctx.terrain_tiles = terrain_tiles; ctx.unit_sprites = unit_sprites
    ctx.unit_anims = unit_anims
    ctx.dying_units = dying_units
    ctx.show_help = shared.show_help
    ctx.exit_confirm = shared.exit_confirm
    -- Camera
    ctx.board_origin_x = camera.origin_x; ctx.board_origin_y = camera.origin_y
    ctx.camera_offset_x = camera.offset_x; ctx.camera_offset_y = camera.offset_y
    ctx.camera_zoom = camera.zoom
    -- Functions from main
    ctx.get_viewport = get_viewport; ctx.screen_to_game = screen_to_game
    ctx.int = int; ctx.parse_html_color = parse_html_color
    ctx.tile_color_cache = tile_color_cache
    draw_mod.draw_frame(ctx, state)
    shared.buttons = ctx.buttons or {}

    -- Status flash message (save/load feedback)
    if vars.status_message then
        love.graphics.push()
        love.graphics.scale(UI_SCALE)
        local vp_w = select(1, get_viewport())
        local f = fonts[14] or love.graphics.getFont()
        love.graphics.setFont(f)
        local tw = f:getWidth(vars.status_message)
        local x = (vp_w - 200 - tw) / 2
        love.graphics.setColor(0, 0, 0, 0.7)
        love.graphics.rectangle("fill", x - 10, 10, tw + 20, f:getHeight() + 10, 6, 6)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.print(vars.status_message, x, 15)
        love.graphics.pop()
    end
end

-- ── Input dispatchers (handlers in input.lua) ─────────────────────────────

function love.keypressed(key) input.keypressed(key) end
function love.mousepressed(sx, sy, button) input.mousepressed(sx, sy, button) end
function love.mousereleased(x, y, button) input.mousereleased(x, y, button) end
function love.mousemoved(sx, sy, dx, dy) input.mousemoved(sx, sy, dx, dy) end
function love.wheelmoved(x, y) input.wheelmoved(x, y) end
function love.textinput(t)
    if game_data.save_renaming then
        if game_data.save_rename_skip then
            game_data.save_rename_skip = false
            return
        end
        game_data.save_rename_text = game_data.save_rename_text .. t
    end
end

-- ── love.resize ─────────────────────────────────────────────────────────────

--- Re-center camera when window is resized.
function love.resize(w, h)
    center_camera()
end

-- ── love.quit ───────────────────────────────────────────────────────────────

--- Clean up agent server on exit.
function love.quit()
    if shared.agent then
        agent_server.stop(shared.agent)
        shared.agent = nil
    end
end
