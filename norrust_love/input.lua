-- norrust_love/input.lua — Input dispatcher module
-- Entry point for all input handling. Delegates to sub-modules by game mode.
-- Extracted from main.lua Phase 79. Receives context tables by reference.

local input_play   = require("input_play")
local input_setup  = require("input_setup")
local input_deploy = require("input_deploy")
local input_saves  = require("input_saves")

local M = {}

-- Context references (set by M.init)
local vars, scn, sel, ghost, campaign, dlg, camera
local shared, combat_state, pending_anims, sound
local game_data, mods
local MODES
local UI_SCALE
-- Helper functions from main.lua
local get_viewport, screen_to_game, int
local center_camera, clear_selection, cancel_ghost, cancel_combat_preview
local is_ranged_attack, commit_ghost_move, execute_attack, check_game_over
local build_unit_pos_map, unit_max_range, select_unit
local get_attackable_enemies, ghost_attackable_set
local call_load_scenario, call_load_campaign_scenario
local faction_index_for_mode
local apply_camera_offset
local campaign_client

--- Restore game state after loading a save file.
-- @param data  The table returned by save.load_save
local function restore_from_save(data)
    -- Detect format: new (top-level board_path) vs old (nested game.board_path)
    if data.board_path then
        -- New Rust-format: extract relative board path from full path
        local prefix = scn.path .. "/"
        if data.board_path:sub(1, #prefix) == prefix then
            scn.board = data.board_path:sub(#prefix + 1)
        else
            scn.board = data.board_path
        end
    else
        -- Old format
        scn.board = data.game.board_path
        scn.path = data.game.scenarios_path
    end

    vars.game_over = false
    vars.winner_faction = -1
    clear_selection()
    -- Update board dimensions from loaded state
    local state = mods.norrust.get_state(vars.engine)
    scn.COLS = int(state.cols or 8)
    scn.ROWS = int(state.rows or 5)
    center_camera()

    -- Restore campaign context
    if data.board_path and data.campaign then
        -- New format: campaign from Rust CampaignState (engine already restored)
        local c = data.campaign
        campaign.active = true
        campaign.data = c.campaign_def
        campaign.index = int(c.scenario_index)
        campaign.gold = int(c.carry_gold)
        if c.campaign_def.faction_0 and c.campaign_def.faction_0 ~= "" then
            game_data.faction_id[1] = c.campaign_def.faction_0
        end
        if c.campaign_def.faction_1 and c.campaign_def.faction_1 ~= "" then
            game_data.faction_id[2] = c.campaign_def.faction_1
        end
        campaign.veterans = c.veterans or {}
        -- Reconstruct Lua roster from Rust format
        if c.roster then
            campaign.roster = mods.roster_mod.new()
            for uuid, entry in pairs(c.roster) do
                local status = entry.status
                -- Rust enum serializes as "Alive"/"Dead", Lua uses "alive"/"dead"
                if type(status) == "string" then status = status:lower() end
                campaign.roster.entries[uuid] = {
                    uuid = uuid,
                    def_id = entry.def_id,
                    hp = int(entry.hp),
                    max_hp = int(entry.max_hp),
                    xp = int(entry.xp),
                    xp_needed = int(entry.xp_needed),
                    advancement_pending = entry.advancement_pending or false,
                    status = status or "alive",
                }
            end
            -- Restore id_map (JSON keys are strings, Lua uses numbers)
            if c.id_map then
                for str_id, uuid in pairs(c.id_map) do
                    campaign.roster.id_map[tonumber(str_id)] = uuid
                end
            end
        else
            campaign.roster = mods.roster_mod.new()
        end
    elseif data.campaign then
        -- Old format: campaign from Lua-format save
        local c = data.campaign
        campaign.active = true
        campaign.data = mods.norrust.load_campaign(vars.engine, campaign.path .. "/" .. c.campaign_file)
        campaign.index = int(c.campaign_index)
        campaign.gold = int(c.campaign_gold)
        game_data.faction_id[1] = c.faction_id_0
        game_data.faction_id[2] = c.faction_id_1
        campaign.veterans = data.veterans or {}
        if data.roster and #data.roster > 0 then
            campaign.roster = mods.roster_mod.from_save_array(data.roster)
            local st = mods.norrust.get_state(vars.engine)
            for _, u in ipairs(st.units or {}) do
                if int(u.faction) == 0 then
                    for uuid, entry in pairs(campaign.roster.entries) do
                        if entry.status == "alive" and not campaign.roster.id_map[int(u.id)]
                           and entry.def_id == u.def_id then
                            local already_mapped = false
                            for _, mapped_uuid in pairs(campaign.roster.id_map) do
                                if mapped_uuid == uuid then already_mapped = true; break end
                            end
                            if not already_mapped then
                                mods.roster_mod.map_id(campaign.roster, int(u.id), uuid)
                                break
                            end
                        end
                    end
                end
            end
        else
            campaign.roster = mods.roster_mod.new()
        end
    else
        campaign.active = false
        campaign.data = nil
        campaign.index = 0
        campaign.veterans = {}
        campaign.gold = 0
        campaign.roster = nil
    end
    vars.game_mode = MODES.PLAYING
end

--- Initialize the input module with context from main.lua.
-- All table arguments are references — mutations here are visible in main.lua.
function M.init(ctx)
    vars = ctx.vars
    scn = ctx.scn
    sel = ctx.sel
    ghost = ctx.ghost
    campaign = ctx.campaign
    dlg = ctx.dlg
    camera = ctx.camera
    shared = ctx.shared
    sound = ctx.sound
    combat_state = ctx.combat_state
    pending_anims = ctx.pending_anims
    game_data = ctx.game_data
    mods = ctx.mods
    MODES = ctx.MODES
    UI_SCALE = ctx.UI_SCALE
    get_viewport = ctx.get_viewport
    screen_to_game = ctx.screen_to_game
    int = ctx.int
    center_camera = ctx.center_camera
    clear_selection = ctx.clear_selection
    cancel_ghost = ctx.cancel_ghost
    cancel_combat_preview = ctx.cancel_combat_preview
    is_ranged_attack = ctx.is_ranged_attack
    commit_ghost_move = ctx.commit_ghost_move
    execute_attack = ctx.execute_attack
    check_game_over = ctx.check_game_over
    build_unit_pos_map = ctx.build_unit_pos_map
    unit_max_range = ctx.unit_max_range
    select_unit = ctx.select_unit
    get_attackable_enemies = ctx.get_attackable_enemies
    ghost_attackable_set = ctx.ghost_attackable_set
    call_load_scenario = ctx.call_load_scenario
    call_load_campaign_scenario = ctx.call_load_campaign_scenario
    faction_index_for_mode = ctx.faction_index_for_mode
    apply_camera_offset = ctx.apply_camera_offset
    campaign_client = ctx.campaign_client

    -- Initialize sub-modules with the same context
    input_play.init(ctx)
    input_setup.init(ctx)
    input_deploy.init(ctx)
    input_saves.init(ctx)
    input_saves.set_restore(restore_from_save)
end

-- ── Keyboard input ────────────────────────────────────────────────────────

-- Handle global keys (F5, F9, /, m, -, =).
-- Returns true if the key was consumed.
local function handle_global_keys(key)
    -- Save (F5, playing only)
    if key == "f5" and vars.game_mode == MODES.PLAYING then
        local filename = mods.save.write_save(vars.engine, mods.norrust, scn.board)
        if filename then
            vars.status_message = "Saved: " .. filename
        else
            vars.status_message = "Save failed!"
        end
        vars.status_timer = 3.0
        return true
    end

    -- Quick-load (F9)
    if key == "f9" then
        local filepath = mods.save.find_latest()
        if filepath then
            local data = mods.save.load_save(vars.engine, mods.norrust, filepath, center_camera)
            if data then
                restore_from_save(data)
                vars.status_message = "Loaded: " .. filepath
            else
                vars.status_message = "Load failed!"
            end
        else
            vars.status_message = "No save files found"
        end
        vars.status_timer = 3.0
        return true
    end

    -- Help overlay toggle
    if key == "/" then
        shared.show_help = not shared.show_help
        return true
    end

    -- Sound controls
    if key == "m" then
        sound.toggle_mute()
        vars.status_message = sound.is_muted() and "Sound muted" or "Sound unmuted"
        vars.status_timer = 1.5
        return true
    elseif key == "-" then
        sound.set_volume(sound.get_volume() - 0.1)
        vars.status_message = string.format("Volume: %d%%", math.floor(sound.get_volume() * 100 + 0.5))
        vars.status_timer = 1.5
        return true
    elseif key == "=" then
        sound.set_volume(sound.get_volume() + 0.1)
        vars.status_message = string.format("Volume: %d%%", math.floor(sound.get_volume() * 100 + 0.5))
        vars.status_timer = 1.5
        return true
    end

    return false
end

-- Handle exit confirmation (Y/N/Escape during PLAYING).
local function handle_exit_confirm(key)
    if key == "y" then
        -- Save and return to menu
        mods.save.write_save(vars.engine, mods.norrust, scn.board)
        shared.exit_confirm = false
        campaign.active = false
        campaign.roster = nil
        vars.game_over = false
        vars.winner_faction = -1
        vars.game_mode = MODES.PICK_SCENARIO
        sound.play_music("data/sounds/menu_music.ogg")
    elseif key == "n" then
        -- Return to menu without saving
        shared.exit_confirm = false
        campaign.active = false
        campaign.roster = nil
        vars.game_over = false
        vars.winner_faction = -1
        vars.game_mode = MODES.PICK_SCENARIO
        sound.play_music("data/sounds/menu_music.ogg")
    elseif key == "escape" then
        shared.exit_confirm = false
    end
end

-- ── Mode dispatch table (populated by M.init once MODES is available) ────

local mode_handlers

function M.keypressed(key)
    -- Block input during animation or AI turn
    if pending_anims.move or pending_anims.combat_slide or shared.ai_queue then return end

    -- Build mode dispatch table on first call (MODES not available at load time)
    if not mode_handlers then
        mode_handlers = {
            [MODES.PICK_SCENARIO]    = input_setup.handle_pick_scenario,
            [MODES.DEPLOY_VETERANS]  = input_deploy.keypressed,
            [MODES.LOAD_SAVE]        = input_saves.keypressed,
            [MODES.PICK_FACTION_BLUE] = input_setup.handle_setup,
            [MODES.PICK_FACTION_RED]  = input_setup.handle_setup,
            [MODES.SETUP_BLUE]       = input_setup.handle_setup,
            [MODES.SETUP_RED]        = input_setup.handle_setup,
            [MODES.PLAYING]          = input_play.keypressed,
        }
    end

    -- Global keys (F5, F9, /, m, -, =)
    if handle_global_keys(key) then return end

    -- Close help on any key
    if shared.show_help then shared.show_help = false end

    -- Exit confirmation interceptor
    if shared.exit_confirm then handle_exit_confirm(key); return end

    -- Mode dispatch
    local handler = mode_handlers[vars.game_mode]
    if handler then handler(key) end
end

--- Check if a sidebar button was clicked and handle it.
function M.handle_sidebar_button(x, y, button, gm, go)
    if button ~= 1 then return end
    local btns = shared.buttons
    if not btns then return end
    local function hit(b)
        return b and x >= b.x and x <= b.x + b.w and y >= b.y and y <= b.y + b.h
    end
    if hit(btns.help) then
        shared.show_help = not shared.show_help
    elseif hit(btns.exit) and not go then
        if gm == MODES.PLAYING then
            shared.exit_confirm = true
        else
            -- During setup/faction-pick: no save needed, return to menu
            vars.game_over = false
            vars.winner_faction = -1
            vars.game_mode = MODES.PICK_SCENARIO
            sound.play_music("data/sounds/menu_music.ogg")
        end
    elseif hit(btns.end_turn) and gm == MODES.PLAYING and not go then
        M.keypressed("e")
    elseif hit(btns.recruit) and gm == MODES.PLAYING and not go then
        M.keypressed("r")
    end
end

-- ── Mouse input ───────────────────────────────────────────────────────────

function M.mousepressed(sx, sy, button)
    -- Block input during animation or AI turn
    if pending_anims.move or pending_anims.combat_slide or shared.ai_queue then return end

    local x, y = screen_to_game(sx, sy)

    -- Sidebar: check button clicks, otherwise ignore panel area
    local vp_w = select(1, get_viewport())
    if x >= vp_w - 200 then
        M.handle_sidebar_button(x, y, button, vars.game_mode, vars.game_over)
        return
    end

    -- Right-click: terrain inspection (any mode with a board)
    if button == 2 and vars.game_mode == MODES.PLAYING and not vars.game_over then
        local local_x = (x - camera.origin_x) / camera.zoom - camera.offset_x
        local local_y = (y - camera.origin_y) / camera.zoom - camera.offset_y
        local col, row = mods.hex.from_pixel(local_x, local_y)
        if col >= 0 and col < scn.COLS and row >= 0 and row < scn.ROWS then
            local state = mods.norrust.get_state(vars.engine)
            for _, tile in ipairs(state.terrain or {}) do
                if int(tile.col) == col and int(tile.row) == row then
                    sel.inspect_terrain = {
                        col = col, row = row,
                        terrain_id = tile.terrain_id,
                        defense = int(tile.defense),
                        movement_cost = int(tile.movement_cost),
                        healing = int(tile.healing),
                        owner = tile.owner and int(tile.owner) or -1,
                    }
                    if sel.unit_id ~= -1 then
                        local info = mods.norrust.get_unit_terrain_info(vars.engine, sel.unit_id, col, row)
                        if info then
                            sel.inspect_terrain.unit_defense = int(info.defense)
                            sel.inspect_terrain.unit_move_cost = int(info.movement_cost)
                        end
                    end
                    sel.inspect_id = -1
                    return
                end
            end
        end
        return
    end

    if button ~= 1 then return end
    if vars.game_mode == MODES.PICK_SCENARIO then return end
    if vars.game_mode == MODES.LOAD_SAVE then return end
    if vars.game_mode == MODES.DEPLOY_VETERANS then return end

    -- Setup mode click
    if vars.game_mode ~= MODES.PLAYING then
        local local_x = (x - camera.origin_x) / camera.zoom - camera.offset_x
        local local_y = (y - camera.origin_y) / camera.zoom - camera.offset_y
        local col, row = mods.hex.from_pixel(local_x, local_y)
        input_setup.mousepressed_setup(col, row, x, y)
        return
    end

    -- Playing mode: convert screen coords to hex
    local local_x = (x - camera.origin_x) / camera.zoom - camera.offset_x
    local local_y = (y - camera.origin_y) / camera.zoom - camera.offset_y
    local col, row = mods.hex.from_pixel(local_x, local_y)

    -- Off-board click: start drag
    if col < 0 or col >= scn.COLS or row < 0 or row >= scn.ROWS then
        camera.drag_active = true
        camera.drag_start_x, camera.drag_start_y = x, y
        camera.drag_cam_x = camera.offset_x
        camera.drag_cam_y = camera.offset_y
        clear_selection()
        return
    end

    local clicked_key = col .. "," .. row
    local state = mods.norrust.get_state(vars.engine)
    local pos_map = build_unit_pos_map(state)
    local active = mods.norrust.get_active_faction(vars.engine)

    input_play.mousepressed(col, row, clicked_key, state, pos_map, active, x, y)
end

-- ── Mouse release / move / wheel ──────────────────────────────────────────

function M.mousereleased(x, y, button)
    if button == 1 then
        camera.drag_active = false
    end
end

function M.mousemoved(sx, sy, dx, dy)
    if camera.drag_active then
        camera.lerping = false
        local x, y = screen_to_game(sx, sy)
        camera.offset_x = camera.drag_cam_x + (x - camera.drag_start_x) / camera.zoom
        camera.offset_y = camera.drag_cam_y + (y - camera.drag_start_y) / camera.zoom
        apply_camera_offset()
    end
end

function M.wheelmoved(x, y)
    if dlg.show_history then
        -- Scroll history panel (y > 0 = scroll up = show earlier entries)
        dlg.scroll = math.max(0, dlg.scroll - y * 20)
        return
    end
    if y > 0 then
        camera.zoom = math.min(camera.zoom + camera.ZOOM_STEP, camera.ZOOM_MAX)
    elseif y < 0 then
        camera.zoom = math.max(camera.zoom - camera.ZOOM_STEP, camera.ZOOM_MIN)
    end
    center_camera()
end

return M
