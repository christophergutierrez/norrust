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
local roster_mod = require("roster")
local agent_server = require("agent_server")
local input = require("input")

-- ── Constants ───────────────────────────────────────────────────────────────

local COLOR_FLAT = {0.29, 0.49, 0.31}
local UI_SCALE = 2.5
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
    {name = "Contested (8x5)",  board = "contested/board.toml",  units = "contested/units.toml", preset_units = false},
    {name = "Crossing (16x10)", board = "crossing/board.toml",   units = "crossing/units.toml",  preset_units = true},
    {name = "Ambush (12x8)",    board = "ambush/board.toml",     units = "ambush/units.toml",    preset_units = true},
    {name = "Night Orcs (20x12)", board = "night_orcs/board.toml", units = "night_orcs/units.toml", preset_units = true},
    {name = "Final Battle (24x14)", board = "final_battle/board.toml", units = "final_battle/units.toml", preset_units = true},
}

-- Available campaigns
local CAMPAIGNS = {
    {name = "The Road to Norrust", file = "tutorial.toml"},
}

-- ── State variables ─────────────────────────────────────────────────────────

local factions = {}
local faction_id = {"", ""}
local leader_placed = {false, false}

-- Mutable scalars grouped for module sharing (input.lua reads/writes these)
local vars = {
    engine = nil,
    game_mode = PICK_SCENARIO,
    game_over = false,
    winner_faction = -1,
    next_unit_id = 1,
    status_message = nil,
    status_timer = 0,
    sel_faction_idx = 0,
}
local combat_state = {preview = nil, target = -1}

local shared = {agent = nil, agent_mod = agent_server, ai_vs_ai = false, ai_delay = 0.5, ai_timer = 0, sound = require("sound"), show_help = false, recruit_palette = {}}

local terrain_tiles = {}
local unit_sprites = {}
local tile_color_cache = {}
local FACTION_COLORS = {[0] = {0.25, 0.42, 0.88}, [1] = {0.80, 0.12, 0.12}}
local unit_anims = {}
local dying_units = {}
local pending_anims = {}
local fonts = {}

-- ── Context tables (grouped to reduce LuaJIT upvalue pressure) ────────────

local scn = {
    path = "", board = "", units = "", preset = false,
    COLS = 8, ROWS = 5,
}

local sel = {
    unit_id = -1, reachable_cells = {}, reachable_set = {},
    recruit_idx = 0, recruit_mode = false, recruit_error = "",
    recruit_state = {veterans = {}},
    inspect_id = -1, inspect_terrain = nil,
}

local ghost = {col = nil, row = nil, unit_id = -1, attackable = {}, path = {}}

local campaign = {
    path = "", active = false, data = nil,
    index = 0, veterans = {}, gold = 0, roster = nil,
}

local dlg = {active = {}, history = {}, show_history = false, scroll = 0}

local camera = {
    origin_x = 0, origin_y = 0,
    offset_x = 0, offset_y = 0,
    min_x = 0, min_y = 0, max_x = 0, max_y = 0,
    drag_active = false,
    drag_start_x = 0, drag_start_y = 0,
    drag_cam_x = 0, drag_cam_y = 0,
    target_x = 0, target_y = 0,
    lerping = false, zoom = 1.0,
    ZOOM_MIN = 0.15, ZOOM_MAX = 3.0, ZOOM_STEP = 0.1,
    PAN_SPEED = 500, LERP_SPEED = 8.0,
}

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
    tile_color_cache = {}
    if not vars.engine then return end
    local state = norrust.get_state(vars.engine)
    for _, tile in ipairs(state.terrain or {}) do
        local key = int(tile.col) .. "," .. int(tile.row)
        tile_color_cache[key] = parse_html_color(tile.color) or COLOR_FLAT
    end
end

-- ── Camera ──────────────────────────────────────────────────────────────────

--- Clamp camera offset to allowed pan range.
local function apply_camera_offset()
    camera.offset_x = clamp(camera.offset_x, camera.min_x, camera.max_x)
    camera.offset_y = clamp(camera.offset_y, camera.min_y, camera.max_y)
end

--- Center camera on the board and compute pan limits.
--- If reset is true, auto-fit zoom so the whole board is visible and reset offset.
--- Called after every zoom change and on window resize.
local function center_camera(reset)
    local tlx, tly = hex.to_pixel(0, 0)
    local brx, bry = hex.to_pixel(scn.COLS - 1, scn.ROWS - 1)
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
        camera.zoom = clamp(fit_zoom, camera.ZOOM_MIN, camera.ZOOM_MAX)
        camera.offset_x, camera.offset_y = 0, 0
        camera.lerping = false
    end

    -- Origin must account for zoom so board center stays at screen center
    -- Screen position of point px: camera.origin_x + zoom * (offset_x + px)
    -- At offset=0, board center at screen center: origin = usable_w/2 - zoom * center
    camera.origin_x = usable_w / 2 - camera.zoom * center_px
    camera.origin_y = vp_h / 2 - camera.zoom * center_py

    -- Effective viewport in board-space coords (for pan limits)
    local eff_w = usable_w / camera.zoom
    local eff_h = vp_h / camera.zoom
    local board_half_w = (brx - tlx) / 2 + hex.RADIUS
    local board_half_h = (bry - tly) / 2 + hex.RADIUS
    local pan_range_x = math.max(board_half_w - eff_w / 2 + hex.RADIUS, 0)
    local pan_range_y = math.max(board_half_h - eff_h / 2 + hex.RADIUS, 0)
    camera.min_x, camera.min_y = -pan_range_x, -pan_range_y
    camera.max_x, camera.max_y = pan_range_x, pan_range_y
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
    if not combat_state.preview or combat_state.target < 0 then return false end
    local state = norrust.get_state(vars.engine)
    local atk_col, atk_row, def_col, def_row
    -- Attacker position: ghost position if ghosting, else unit state position
    local atk_id = ghost.col ~= nil and ghost.unit_id or sel.unit_id
    if ghost.col ~= nil then
        atk_col, atk_row = ghost.col, ghost.row
    end
    for _, unit in ipairs(state.units or {}) do
        local uid = int(unit.id)
        if uid == atk_id and not atk_col then
            atk_col, atk_row = int(unit.col), int(unit.row)
        end
        if uid == combat_state.target then
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
    -- Capture defender position before attack (vars.engine removes dead units)
    local pre_state = norrust.get_state(vars.engine)
    local def_info = nil
    for _, unit in ipairs(pre_state.units or {}) do
        if int(unit.id) == defender_id then
            def_info = {def_id = unit.def_id, col = int(unit.col), row = int(unit.row), faction = int(unit.faction)}
            break
        end
    end

    trigger_attack_anims(attacker_id, defender_id, is_ranged)
    norrust.apply_attack(vars.engine, attacker_id, defender_id)
    local new_state = norrust.get_state(vars.engine)
    local defender_alive = false
    for _, unit in ipairs(new_state.units or {}) do
        if int(unit.id) == defender_id then
            defender_alive = true
            break
        end
    end
    if not defender_alive then
        trigger_death_anim(defender_id)
        if def_info then
            dying_units[defender_id] = {
                def_id = def_info.def_id, col = def_info.col, row = def_info.row,
                faction = def_info.faction, timer = 1.0,
            }
        end
        shared.sound.play("death")
    else
        shared.sound.play("hit")
    end
end

-- ── Dialogue helpers ────────────────────────────────────────────────────

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

-- Stash play_sfx in sel.recruit_state to avoid adding upvalues to mousepressed
sel.recruit_state.play_sfx = function(name) shared.sound.play(name) end

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
    shared.sound.play_music(music_vfs)
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
    local pre_state = norrust.get_state(vars.engine)
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
    local state = norrust.get_state(vars.engine)
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
    shared.sound.play("select")
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
    shared.sound.play("move")
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
    return vars.game_mode == SETUP_BLUE and 0 or 1
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
        faction_id = faction_id, game_over = vars.game_over,
        winner_faction = vars.winner_faction, recruit_mode = sel.recruit_mode,
        next_unit_id = vars.next_unit_id, game_mode = vars.game_mode,
        PLAYING = PLAYING, clear_selection = clear_selection,
        build_unit_pos_map = build_unit_pos_map,
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
    vars.next_unit_id = ctx.next_unit_id
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
    factions = norrust.get_faction_ids(vars.engine)
    table.sort(factions, function(a, b) return a.name < b.name end)

    -- Load visual assets from data/ via symlink (data -> ../data)
    terrain_tiles = assets.load_terrain_tiles("data")
    unit_sprites = assets.load_unit_sprites("data")

    -- Load sound effects and start menu music
    shared.sound.load()
    shared.sound.play_music("data/sounds/menu_music.ogg")

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
            shared.ai_vs_ai = true
            -- Also start agent server for external observation
            if not shared.agent then
                shared.agent = agent_server.new(9876)
            end
        elseif a == "--ai-delay" and args[i + 1] then
            shared.ai_delay = tonumber(args[i + 1]) or 0.5
        end
    end

    -- Start at scenario selection
    vars.game_mode = PICK_SCENARIO

    -- Initialize input handler module with all context references
    input.init({
        vars = vars, scn = scn, sel = sel, ghost = ghost,
        campaign = campaign, dlg = dlg, camera = camera,
        shared = shared, combat_state = combat_state,
        pending_anims = pending_anims,
        factions = factions, faction_id = faction_id, leader_placed = leader_placed,
        norrust = norrust, hex = hex, events = events, save = save, roster_mod = roster_mod,
        SCENARIOS = SCENARIOS, CAMPAIGNS = CAMPAIGNS,
        PICK_SCENARIO = PICK_SCENARIO, PICK_FACTION_BLUE = PICK_FACTION_BLUE,
        PICK_FACTION_RED = PICK_FACTION_RED, SETUP_BLUE = SETUP_BLUE,
        SETUP_RED = SETUP_RED, PLAYING = PLAYING,
        UI_SCALE = UI_SCALE, FACTION_COLORS = FACTION_COLORS,
        get_viewport = get_viewport, screen_to_game = screen_to_game,
        int = int, clamp = clamp,
        center_camera = center_camera, clear_selection = clear_selection,
        cancel_ghost = cancel_ghost, cancel_combat_preview = cancel_combat_preview,
        is_ranged_attack = is_ranged_attack, commit_ghost_move = commit_ghost_move,
        execute_attack = execute_attack, check_game_over = check_game_over,
        build_unit_pos_map = build_unit_pos_map, unit_max_range = unit_max_range,
        select_unit = select_unit, get_attackable_enemies = get_attackable_enemies,
        ghost_attackable_set = ghost_attackable_set,
        call_load_scenario = call_load_scenario,
        call_load_campaign_scenario = call_load_campaign_scenario,
        fire_hex_entered = fire_hex_entered, faction_index_for_mode = faction_index_for_mode,
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
    if shared.ai_vs_ai and vars.game_mode == PLAYING and not vars.game_over
       and not pending_anims.move and #pending_anims == 0 and not pending_anims.combat_slide then
        shared.ai_timer = shared.ai_timer - dt
        if shared.ai_timer <= 0 then
            local f = norrust.get_active_faction(vars.engine)
            local fid = faction_id[f + 1]
            if fid and fid ~= "" then
                local n = norrust.ai_recruit(vars.engine, fid, vars.next_unit_id)
                vars.next_unit_id = vars.next_unit_id + n
                norrust.ai_take_turn(vars.engine, f)
                check_game_over()
            end
            shared.ai_timer = shared.ai_delay
        end
    end

    -- Status message countdown
    if vars.status_timer > 0 then
        vars.status_timer = vars.status_timer - dt
        if vars.status_timer <= 0 then vars.status_message = nil end
    end

    -- Update unit animations
    for uid, anim_state in pairs(unit_anims) do
        local entry = nil
        -- Find the unit's def_id to look up anim_data
        -- We need the state to map uid → def_id; cache is built during draw_units
        -- For efficiency, store def_id on the anim_state when created
        if anim_state.def_id then
            entry = unit_sprites[anim_state.def_id:lower():gsub(" ", "_")]
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

    -- Tick down dying unit timers
    for uid, info in pairs(dying_units) do
        info.timer = info.timer - dt
        if info.timer <= 0 then
            dying_units[uid] = nil
            unit_anims[uid] = nil
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
        camera.lerping = false
        local len = math.sqrt(pan_x * pan_x + pan_y * pan_y)
        camera.offset_x = camera.offset_x + (pan_x / len) * camera.PAN_SPEED * dt
        camera.offset_y = camera.offset_y + (pan_y / len) * camera.PAN_SPEED * dt
        apply_camera_offset()
        return
    end

    -- Camera lerp toward selection target
    if camera.lerping then
        local t = camera.LERP_SPEED * dt
        camera.offset_x = camera.offset_x + (camera.target_x - camera.offset_x) * t
        camera.offset_y = camera.offset_y + (camera.target_y - camera.offset_y) * t
        apply_camera_offset()
        local dx = camera.offset_x - camera.target_x
        local dy = camera.offset_y - camera.target_y
        if math.sqrt(dx * dx + dy * dy) < 1.0 then
            camera.offset_x = camera.target_x
            camera.offset_y = camera.target_y
            apply_camera_offset()
            camera.lerping = false
        end
    end
end

-- ── love.draw ───────────────────────────────────────────────────────────────

--- Build draw context (split into two functions to stay under LuaJIT 60-upvalue limit).
local function build_draw_ctx_state()
    return {
        game_mode = vars.game_mode, game_over = vars.game_over, winner_faction = vars.winner_faction,
        selected_unit_id = sel.unit_id, inspect_unit_id = sel.inspect_id,
        inspect_terrain = sel.inspect_terrain, recruit_mode = sel.recruit_mode,
        recruit_palette = shared.recruit_palette, recruit_veterans = sel.recruit_state.veterans,
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
        factions = factions, sel_faction_idx = vars.sel_faction_idx,
        faction_id = faction_id, leader_placed = leader_placed,
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
    ctx.FACTION_COLORS = FACTION_COLORS; ctx.SCENARIOS = SCENARIOS; ctx.CAMPAIGNS = CAMPAIGNS
    -- Mode constants
    ctx.PICK_SCENARIO = PICK_SCENARIO; ctx.PICK_FACTION_BLUE = PICK_FACTION_BLUE
    ctx.PICK_FACTION_RED = PICK_FACTION_RED; ctx.SETUP_BLUE = SETUP_BLUE
    ctx.SETUP_RED = SETUP_RED; ctx.PLAYING = PLAYING
    -- Fonts, sprites
    ctx.fonts = fonts; ctx.terrain_tiles = terrain_tiles; ctx.unit_sprites = unit_sprites
    ctx.unit_anims = unit_anims
    ctx.dying_units = dying_units
    ctx.show_help = shared.show_help
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
        local vp_w = select(1, get_viewport())
        local f = fonts and fonts.medium or love.graphics.getFont()
        love.graphics.setFont(f)
        local tw = f:getWidth(vars.status_message)
        local x = (vp_w - 200 - tw) / 2
        love.graphics.setColor(0, 0, 0, 0.7)
        love.graphics.rectangle("fill", x - 10, 10, tw + 20, f:getHeight() + 10, 6, 6)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.print(vars.status_message, x, 15)
    end
end

-- ── Input dispatchers (handlers in input.lua) ─────────────────────────────

function love.keypressed(key) input.keypressed(key) end
function love.mousepressed(sx, sy, button) input.mousepressed(sx, sy, button) end
function love.mousereleased(x, y, button) input.mousereleased(x, y, button) end
function love.mousemoved(sx, sy, dx, dy) input.mousemoved(sx, sy, dx, dy) end
function love.wheelmoved(x, y) input.wheelmoved(x, y) end

-- Wire sidebar button handler through input module
shared.handle_sidebar_button = function(x, y, button, gm, go)
    input.handle_sidebar_button(x, y, button, gm, go)
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
