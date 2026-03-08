-- norrust_love/input.lua — Input handler module
-- Extracted from main.lua Phase 79. Receives context tables by reference.

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
end

--- Restore game state after loading a save file.
-- @param data  The table returned by save.load_save
local function restore_from_save(data)
    scn.board = data.game.board_path
    scn.path = data.game.scenarios_path
    vars.game_over = false
    vars.winner_faction = -1
    clear_selection()
    -- Update board dimensions from loaded state
    local state = mods.norrust.get_state(vars.engine)
    scn.COLS = int(state.cols or 8)
    scn.ROWS = int(state.rows or 5)
    center_camera()
    -- Restore campaign context if present
    if data.campaign then
        local c = data.campaign
        campaign.active = true
        campaign.data = mods.norrust.load_campaign(vars.engine, campaign.path .. "/" .. c.campaign_file)
        campaign.index = int(c.campaign_index)
        campaign.gold = int(c.campaign_gold)
        game_data.faction_id[1] = c.faction_id_0
        game_data.faction_id[2] = c.faction_id_1
        -- Restore veterans
        campaign.veterans = data.veterans or {}
        -- Restore roster
        if data.roster and #data.roster > 0 then
            campaign.roster = mods.roster_mod.from_save_array(data.roster)
            -- Re-map engine IDs to roster UUIDs by matching def_id
            local st = mods.norrust.get_state(vars.engine)
            for _, u in ipairs(st.units or {}) do
                if int(u.faction) == 0 then
                    for uuid, entry in pairs(campaign.roster.entries) do
                        if entry.status == "alive" and not campaign.roster.id_map[int(u.id)]
                           and entry.def_id == u.def_id then
                            -- Check no other engine_id already maps to this uuid
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

-- ── Keyboard input ────────────────────────────────────────────────────────

-- Build campaign context for save (nil if not in campaign).
-- Module-scope so both F5 and exit_confirm handlers can use it.
local function build_save_campaign_ctx()
    if not campaign.active then return nil end
    return {
        file = game_data.CAMPAIGNS[1].file,
        index = campaign.index,
        gold = campaign.gold,
        veterans = campaign.veterans,
        faction_id = game_data.faction_id,
        roster = campaign.roster and mods.roster_mod.to_save_array(campaign.roster) or nil,
    }
end

-- Handle global keys (F5, F9, /, m, -, =).
-- Returns true if the key was consumed.
local function handle_global_keys(key)
    -- Save (F5, playing only)
    if key == "f5" and vars.game_mode == MODES.PLAYING then
        local filename = mods.save.write_save(vars.engine, mods.norrust, scn.board, scn.path, build_save_campaign_ctx())
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
        mods.save.write_save(vars.engine, mods.norrust, scn.board, scn.path, build_save_campaign_ctx())
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

-- ── Mode-specific key handlers ───────────────────────────────────────────

local function handle_pick_scenario(key)
    local num = tonumber(key)
    if num and num >= 1 and num <= #game_data.SCENARIOS then
        sound.stop_music()
        campaign.active = false
        scn.board = game_data.SCENARIOS[num].board
        scn.units = game_data.SCENARIOS[num].units
        scn.preset = game_data.SCENARIOS[num].preset_units
        call_load_scenario()
        if scn.preset then
            -- Preset scenarios: auto-assign factions and start directly
            game_data.faction_id[1] = game_data.factions[1].id
            game_data.faction_id[2] = game_data.factions[2].id
            mods.norrust.apply_starting_gold(vars.engine, game_data.faction_id[1], game_data.faction_id[2])
            mods.norrust.load_units(vars.engine, scn.path .. "/" .. scn.units)
            vars.game_mode = MODES.PLAYING
            mods.events.emit("scenario_loaded", {board = scn.board})
        else
            vars.game_mode = MODES.PICK_FACTION_BLUE
        end
    elseif key == "l" then
        -- Open save list screen
        game_data.save_list = mods.save.list_saves()
        game_data.save_idx = 1
        vars.game_mode = MODES.LOAD_SAVE
    elseif key == "c" then
        -- Start campaign
        sound.stop_music()
        local camp = game_data.CAMPAIGNS[1]
        campaign.data = mods.norrust.load_campaign(vars.engine, campaign.path .. "/" .. camp.file)
        if campaign.data then
            campaign.active = true
            campaign.index = 0
            campaign.veterans = {}
            campaign.gold = 0
            campaign.roster = mods.roster_mod.new()
            -- Assign factions from campaign data, or fall back to auto-assign
            if campaign.data.faction_0 and campaign.data.faction_0 ~= "" then
                game_data.faction_id[1] = campaign.data.faction_0
            else
                game_data.faction_id[1] = game_data.factions[1].id
            end
            if campaign.data.faction_1 and campaign.data.faction_1 ~= "" then
                game_data.faction_id[2] = campaign.data.faction_1
            else
                game_data.faction_id[2] = game_data.factions[2].id
            end
            local sc = campaign.data.scenarios[1]
            scn.board = sc.board
            scn.units = sc.units
            scn.preset = sc.preset_units
            call_load_scenario()
            call_load_campaign_scenario()
        end
    elseif key == "q" or key == "escape" then
        love.event.quit()
    end
end

local function handle_deploy_veterans(key)
    local deploy = campaign.deploy
    local dvets = deploy.veterans or {}

    if key == "up" then
        if deploy.selected > 1 then deploy.selected = deploy.selected - 1 end
    elseif key == "down" then
        if deploy.selected < #dvets then deploy.selected = deploy.selected + 1 end
    elseif key == "space" then
        local dv = dvets[deploy.selected]
        if dv then
            if dv.deployed then
                dv.deployed = false
            else
                -- Count currently deployed
                local count = 0
                for _, v in ipairs(dvets) do
                    if v.deployed then count = count + 1 end
                end
                if count < deploy.slots then
                    dv.deployed = true
                else
                    vars.status_message = "All " .. deploy.slots .. " slots full"
                    vars.status_timer = 2.0
                end
            end
        end
    elseif key == "return" or key == "kpenter" then
        -- Build campaign ctx and commit
        local ctx = {
            norrust = mods.norrust, engine = vars.engine, int = int,
            hex = mods.hex, scenarios_path = scn.path,
            campaign_veterans = campaign.veterans,
            campaign_roster = campaign.roster, roster_mod = mods.roster_mod,
            campaign_deploy = campaign.deploy,
            build_unit_pos_map = build_unit_pos_map,
            PLAYING = MODES.PLAYING,
        }
        campaign_client.commit_deployment(ctx)
        vars.game_mode = ctx.game_mode
        mods.events.emit("scenario_loaded", {board = scn.board})
    elseif key == "escape" then
        -- Deploy all (up to slot limit)
        local count = 0
        for _, dv in ipairs(dvets) do
            if count < deploy.slots then
                dv.deployed = true
                count = count + 1
            else
                dv.deployed = false
            end
        end
        local ctx = {
            norrust = mods.norrust, engine = vars.engine, int = int,
            hex = mods.hex, scenarios_path = scn.path,
            campaign_veterans = campaign.veterans,
            campaign_roster = campaign.roster, roster_mod = mods.roster_mod,
            campaign_deploy = campaign.deploy,
            build_unit_pos_map = build_unit_pos_map,
            PLAYING = MODES.PLAYING,
        }
        campaign_client.commit_deployment(ctx)
        vars.game_mode = ctx.game_mode
        mods.events.emit("scenario_loaded", {board = scn.board})
    else
        -- Number keys 1-9 toggle deploy
        local num = tonumber(key)
        if num and num >= 1 and num <= #dvets then
            local dv = dvets[num]
            if dv.deployed then
                dv.deployed = false
            else
                local count = 0
                for _, v in ipairs(dvets) do
                    if v.deployed then count = count + 1 end
                end
                if count < deploy.slots then
                    dv.deployed = true
                else
                    vars.status_message = "All " .. deploy.slots .. " slots full"
                    vars.status_timer = 2.0
                end
            end
        end
    end
end

local function handle_load_save(key)
    local saves = game_data.save_list or {}

    -- Rename mode intercepts keys
    if game_data.save_renaming then
        if key == "return" or key == "kpenter" then
            local selected = saves[game_data.save_idx]
            if selected then
                mods.save.update_display_name(selected.filepath, game_data.save_rename_text)
                game_data.save_list = mods.save.list_saves()
            end
            game_data.save_renaming = false
        elseif key == "escape" then
            game_data.save_renaming = false
        elseif key == "backspace" then
            local t = game_data.save_rename_text
            if #t > 0 then
                -- Remove last byte (ASCII-safe; UTF-8 multi-byte unlikely in save names)
                game_data.save_rename_text = t:sub(1, #t - 1)
            end
        end
        return
    end

    if key == "escape" then
        vars.game_mode = MODES.PICK_SCENARIO
    elseif key == "up" then
        if game_data.save_idx > 1 then
            game_data.save_idx = game_data.save_idx - 1
        end
    elseif key == "down" then
        if game_data.save_idx < #saves then
            game_data.save_idx = game_data.save_idx + 1
        end
    elseif key == "return" and #saves > 0 then
        local selected = saves[game_data.save_idx]
        if selected then
            local data = mods.save.load_save(vars.engine, mods.norrust, selected.filepath, center_camera)
            if data then
                restore_from_save(data)
                vars.status_message = "Loaded: " .. selected.filepath
            else
                vars.status_message = "Load failed!"
            end
            vars.status_timer = 3.0
        end
    elseif key == "d" and #saves > 0 then
        local selected = saves[game_data.save_idx]
        if selected then
            mods.save.delete_save(selected.filepath)
            game_data.save_list = mods.save.list_saves()
            if game_data.save_idx > #game_data.save_list then
                game_data.save_idx = math.max(1, #game_data.save_list)
            end
        end
    elseif key == "r" and #saves > 0 then
        local selected = saves[game_data.save_idx]
        if selected then
            game_data.save_renaming = true
            game_data.save_rename_skip = true
            game_data.save_rename_text = selected.display_name or ""
        end
    end
end

local function handle_setup(key)
    -- Faction picker: number keys (non-preset scenarios only)
    if vars.game_mode == MODES.PICK_FACTION_BLUE or vars.game_mode == MODES.PICK_FACTION_RED then
        if key == "escape" then
            vars.game_mode = MODES.PICK_SCENARIO
            sound.play_music("data/sounds/menu_music.ogg")
            return
        end
        local num = tonumber(key)
        if num and num >= 1 and num <= #game_data.factions then
            local fi = vars.game_mode == MODES.PICK_FACTION_BLUE and 0 or 1
            game_data.faction_id[fi + 1] = game_data.factions[num].id
            vars.sel_faction_idx = 0
            vars.game_mode = vars.game_mode == MODES.PICK_FACTION_BLUE and MODES.SETUP_BLUE or MODES.SETUP_RED
        end
        return
    end

    -- Setup: Escape to return to menu
    if key == "escape" then
        vars.game_mode = MODES.PICK_SCENARIO
        sound.play_music("data/sounds/menu_music.ogg")
    end
end

local function handle_playing(key)
    if vars.game_over then
        if key == "return" or key == "kpenter" then
            if campaign.active and vars.winner_faction == 0 then
                -- Player won — sync roster then derive veterans
                if campaign.roster then
                    mods.roster_mod.sync_from_engine(campaign.roster, mods.norrust.get_state(vars.engine))
                    local living = mods.roster_mod.get_living(campaign.roster)
                    campaign.veterans = {}
                    for _, entry in ipairs(living) do
                        campaign.veterans[#campaign.veterans + 1] = {
                            def_id = entry.def_id,
                            hp = entry.max_hp,
                            max_hp = entry.max_hp,
                            xp = entry.xp,
                            xp_needed = entry.xp_needed,
                            advancement_pending = entry.advancement_pending,
                        }
                    end
                else
                    local survivors = mods.norrust.get_survivors(vars.engine, 0)
                    for _, s in ipairs(survivors) do s.hp = s.max_hp end
                    campaign.veterans = survivors
                end
                campaign.gold = mods.norrust.get_carry_gold(
                    vars.engine, 0,
                    campaign.data.gold_carry_percent,
                    campaign.data.early_finish_bonus
                )
                campaign.index = campaign.index + 1
                if campaign.index < #campaign.data.scenarios then
                    call_load_campaign_scenario()
                else
                    -- Campaign complete — return to scenario selection
                    campaign.active = false
                    campaign.roster = nil
                    vars.game_over = false
                    vars.winner_faction = -1
                    vars.game_mode = MODES.PICK_SCENARIO
                    sound.play_music("data/sounds/menu_music.ogg")
                end
            else
                -- Individual scenario win/loss, or campaign defeat
                campaign.active = false
                campaign.roster = nil
                vars.game_over = false
                vars.winner_faction = -1
                vars.game_mode = MODES.PICK_SCENARIO
                sound.play_music("data/sounds/menu_music.ogg")
            end
        end
        return
    end

    if key == "escape" then
        -- Cancel combat preview, or ghost, or selection
        if combat_state.preview ~= nil then
            cancel_combat_preview()
        elseif ghost.col ~= nil then
            cancel_ghost()
        else
            clear_selection()
        end

    elseif (key == "return" or key == "kpenter") then
        if combat_state.preview ~= nil and combat_state.target >= 0 and ghost.col ~= nil then
            -- Commit ghost move + attack previewed target
            local enemy_id = combat_state.target
            local ranged = is_ranged_attack()
            cancel_combat_preview()
            commit_ghost_move(function()
                execute_attack(sel.unit_id, enemy_id, ranged, function()
                    clear_selection()
                    sel.inspect_id = enemy_id
                    check_game_over()
                end)
            end)
        elseif combat_state.preview ~= nil and combat_state.target >= 0 and sel.unit_id ~= -1 then
            -- Direct adjacent attack from preview
            local enemy_id = combat_state.target
            local ranged = is_ranged_attack()
            cancel_combat_preview()
            execute_attack(sel.unit_id, enemy_id, ranged, function()
                clear_selection()
                sel.inspect_id = enemy_id
                check_game_over()
            end)
        elseif ghost.col ~= nil then
            -- Commit ghost move only
            commit_ghost_move()
        end

    elseif key == "e" then
        mods.events.emit("dialogue", {trigger = "turn_end"})
        sound.play("turn_end")

        -- End turn + AI
        mods.norrust.end_turn(vars.engine)
        clear_selection()
        check_game_over()
        if not vars.game_over and mods.norrust.get_active_faction(vars.engine) == 1 then
            mods.norrust.ai_recruit(vars.engine, game_data.faction_id[2], mods.norrust.get_next_unit_id(vars.engine))
            mods.norrust.ai_take_turn(vars.engine, 1)
            check_game_over()
        end

        -- New turn dialogue (reset panel so only new messages show)
        dlg.active = {}
        mods.events.emit("dialogue", {trigger = "turn_start"})

    elseif key == "a" then
        -- Advance selected unit
        if sel.unit_id ~= -1 then
            local state = mods.norrust.get_state(vars.engine)
            local active = mods.norrust.get_active_faction(vars.engine)
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == sel.unit_id
                    and int(unit.faction) == active
                    and unit.advancement_pending then
                    mods.norrust.apply_advance(vars.engine, sel.unit_id)
                    clear_selection()
                    break
                end
            end
        end

    elseif key == "h" then
        -- Toggle dialogue history
        dlg.show_history = not dlg.show_history
        if dlg.show_history then dlg.scroll = 0 end

    elseif key == "p" then
        -- Toggle agent server
        if shared.agent then
            shared.agent_mod.stop(shared.agent)
            shared.agent = nil
            vars.status_message = "Agent server stopped"
        else
            shared.agent = shared.agent_mod.new(9876)
            vars.status_message = shared.agent and "Agent server on port 9876" or "Failed to start server"
        end
        vars.status_timer = 3.0

    elseif key == "r" then
        -- Toggle recruit mode
        if not sel.recruit_mode then
            local faction = mods.norrust.get_active_faction(vars.engine)
            sel.recruit_palette = mods.norrust.get_faction_recruits(vars.engine, game_data.faction_id[faction + 1], 0)
            -- Build veteran recruit list from roster (campaign only)
            sel.recruit_state.veterans = {}
            if campaign.active and campaign.roster then
                local living = mods.roster_mod.get_living(campaign.roster)
                -- Filter out veterans already on the board (have engine_id mapped)
                local mapped = {}
                for _, uuid in pairs(campaign.roster.id_map) do
                    mapped[uuid] = true
                end
                for _, entry in ipairs(living) do
                    if not mapped[entry.uuid] then
                        sel.recruit_state.veterans[#sel.recruit_state.veterans + 1] = entry
                    end
                end
            end
            sel.recruit_idx = 0
            sel.recruit_error = ""
            sel.recruit_mode = true
            clear_selection()
        else
            sel.recruit_mode = false
        end

    else
        -- Number keys for recruit selection
        local num = tonumber(key)
        if num and num >= 1 and num <= 9 then
            local total = #sel.recruit_state.veterans + #sel.recruit_palette
            if sel.recruit_mode and total > 0 then
                sel.recruit_idx = math.min(num - 1, total - 1)
            end
        end
    end
end

-- ── Mode dispatch table (populated by M.init once MODES is available) ────

local mode_handlers

function M.keypressed(key)
    -- Block input during movement animation
    if pending_anims.move or pending_anims.combat_slide then return end

    -- Build mode dispatch table on first call (MODES not available at load time)
    if not mode_handlers then
        mode_handlers = {
            [MODES.PICK_SCENARIO]    = handle_pick_scenario,
            [MODES.DEPLOY_VETERANS]  = handle_deploy_veterans,
            [MODES.LOAD_SAVE]        = handle_load_save,
            [MODES.PICK_FACTION_BLUE] = handle_setup,
            [MODES.PICK_FACTION_RED]  = handle_setup,
            [MODES.SETUP_BLUE]       = handle_setup,
            [MODES.SETUP_RED]        = handle_setup,
            [MODES.PLAYING]          = handle_playing,
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
    -- Block input during movement animation
    if pending_anims.move or pending_anims.combat_slide then return end

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
        if vars.game_mode == MODES.PICK_FACTION_BLUE or vars.game_mode == MODES.PICK_FACTION_RED then
            return
        end

        local local_x = (x - camera.origin_x) / camera.zoom - camera.offset_x
        local local_y = (y - camera.origin_y) / camera.zoom - camera.offset_y
        local col, row = mods.hex.from_pixel(local_x, local_y)

        if col < 0 or col >= scn.COLS or row < 0 or row >= scn.ROWS then
            return
        end

        local state = mods.norrust.get_state(vars.engine)
        local pos_map = build_unit_pos_map(state)
        local fi = faction_index_for_mode()
        local faction = fi

        if not game_data.leader_placed[fi + 1] then
            local key = col .. "," .. row
            if not pos_map[key] then
                local leader_def = mods.norrust.get_faction_leader(vars.engine, game_data.faction_id[fi + 1])
                mods.norrust.place_unit_at(vars.engine, mods.norrust.get_next_unit_id(vars.engine), leader_def, 0, faction, col, row)
                game_data.leader_placed[fi + 1] = true
                -- Auto-advance after leader placement
                if vars.game_mode == MODES.SETUP_BLUE then
                    vars.game_mode = MODES.PICK_FACTION_RED
                else
                    mods.norrust.apply_starting_gold(vars.engine, game_data.faction_id[1], game_data.faction_id[2])
                    vars.game_mode = MODES.PLAYING
                    mods.events.emit("scenario_loaded", {board = scn.board})
                end
            end
        end
        return
    end

    -- Playing mode
    if vars.game_over then return end

    -- Convert screen coords to hex
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

    -- Recruit mode click
    if sel.recruit_mode then
        local vet_count = #sel.recruit_state.veterans
        if sel.recruit_idx < vet_count then
            -- Veteran recruitment: place veteran unit from roster
            local vet = sel.recruit_state.veterans[sel.recruit_idx + 1]
            local uid = mods.norrust.get_next_unit_id(vars.engine)
            local rc = mods.norrust.place_veteran_unit(
                vars.engine, uid,
                vet.def_id, 0,
                col, row,
                int(vet.hp), int(vet.xp), int(vet.xp_needed),
                vet.advancement_pending
            )
            if rc == 0 then
                mods.roster_mod.map_id(campaign.roster, uid, vet.uuid)
                sound.play("recruit")
                table.remove(sel.recruit_state.veterans, sel.recruit_idx + 1)
                if sel.recruit_idx >= #sel.recruit_state.veterans + #sel.recruit_palette then
                    sel.recruit_idx = math.max(0, #sel.recruit_state.veterans + #sel.recruit_palette - 1)
                end
                sel.recruit_error = ""
            else
                local err_map = {
                    [-4] = "Hex is occupied",
                    [-9] = "Must click a castle hex",
                    [-10] = "Move leader to the keep first",
                }
                sel.recruit_error = err_map[rc] or string.format("Place failed (code %d)", rc)
            end
        else
            -- Normal recruitment from palette
            local palette_idx = sel.recruit_idx - vet_count
            local def_id = sel.recruit_palette[palette_idx + 1] or ""
            if def_id ~= "" then
                local uid = mods.norrust.get_next_unit_id(vars.engine)
                local result = mods.norrust.recruit_unit_at(vars.engine, uid, def_id, col, row)
                if result == 0 then
                    -- Add recruited unit to campaign roster
                    if campaign.active and campaign.roster then
                        local st = mods.norrust.get_state(vars.engine)
                        for _, u in ipairs(st.units or {}) do
                            if int(u.id) == uid then
                                mods.roster_mod.add(campaign.roster, u.def_id, uid,
                                    int(u.hp), int(u.max_hp), int(u.xp), int(u.xp_needed),
                                    u.advancement_pending or false)
                                break
                            end
                        end
                    end
                    sel.recruit_error = ""
                    sel.recruit_mode = false
                    sound.play("recruit")
                else
                    local err_map = {
                        [-4] = "Hex is occupied",
                        [-8] = "Not enough gold",
                        [-9] = "Must click a castle hex",
                        [-10] = "Move leader to the keep first",
                    }
                    sel.recruit_error = err_map[result] or string.format("Recruit failed (code %d)", result)
                end
            end
        end
        return
    end

    -- Ghost active: handle clicks from ghost state
    if ghost.col ~= nil then
        local atk_set = ghost_attackable_set()

        -- Click highlighted enemy → show combat preview (or execute if same target clicked twice)
        if pos_map[clicked_key] and atk_set[pos_map[clicked_key].id] then
            local enemy_id = pos_map[clicked_key].id
            if combat_state.target == enemy_id then
                -- Second click on same enemy → commit move + attack
                local ranged = is_ranged_attack()
                cancel_combat_preview()
                commit_ghost_move(function()
                    execute_attack(sel.unit_id, enemy_id, ranged, function()
                        clear_selection()
                        sel.inspect_id = enemy_id
                        check_game_over()
                    end)
                end)
            else
                -- First click (or different enemy) → show combat preview
                combat_state.preview = mods.norrust.simulate_combat(vars.engine, ghost.unit_id, enemy_id, ghost.col, ghost.row, 100)
                combat_state.target = enemy_id
                sel.inspect_id = enemy_id
            end

        -- Click the ghost hex itself → commit move only
        elseif col == ghost.col and row == ghost.row then
            commit_ghost_move()

        -- Click a different reachable hex → re-ghost, auto-preview if same target adjacent
        elseif sel.reachable_set[clicked_key] and not pos_map[clicked_key] then
            local prev_target = combat_state.target
            cancel_combat_preview()
            ghost.col = col
            ghost.row = row
            ghost.attackable = get_attackable_enemies(pos_map, col, row, active, unit_max_range(ghost.unit_id))
            ghost.path = mods.norrust.find_path(vars.engine, ghost.unit_id, col, row)
            -- Auto-preview: if previously previewed enemy is still in range, re-show preview
            if prev_target ~= -1 then
                for _, e in ipairs(ghost.attackable) do
                    if e.id == prev_target then
                        combat_state.preview = mods.norrust.simulate_combat(vars.engine, ghost.unit_id, prev_target, ghost.col, ghost.row, 100)
                        combat_state.target = prev_target
                        sel.inspect_id = prev_target
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
    elseif sel.unit_id ~= -1 and pos_map[clicked_key] and pos_map[clicked_key].faction ~= active then
        local enemy_id = pos_map[clicked_key].id
        if combat_state.target == enemy_id then
            -- Second click on same enemy → execute attack
            local ranged = is_ranged_attack()
            cancel_combat_preview()
            execute_attack(sel.unit_id, enemy_id, ranged, function()
                clear_selection()
                sel.inspect_id = enemy_id
                check_game_over()
            end)
        else
            -- First click → show combat preview (attacker at current position)
            local atk_col, atk_row = nil, nil
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == sel.unit_id then
                    atk_col = int(unit.col)
                    atk_row = int(unit.row)
                    break
                end
            end
            if atk_col then
                combat_state.preview = mods.norrust.simulate_combat(vars.engine, sel.unit_id, enemy_id, atk_col, atk_row, 100)
                combat_state.target = enemy_id
                sel.inspect_id = enemy_id
            end
        end

    -- Ghost: selected unit + reachable empty hex → enter ghost state
    elseif sel.unit_id ~= -1 and sel.reachable_set[clicked_key] and not pos_map[clicked_key] then
        ghost.col = col
        ghost.row = row
        ghost.unit_id = sel.unit_id
        ghost.attackable = get_attackable_enemies(pos_map, col, row, active, unit_max_range(sel.unit_id))
        ghost.path = mods.norrust.find_path(vars.engine, sel.unit_id, col, row)

    -- Select friendly unit
    elseif pos_map[clicked_key] and pos_map[clicked_key].faction == active then
        select_unit(pos_map[clicked_key].id)

    -- Inspect enemy unit (no friendly selected)
    elseif pos_map[clicked_key] then
        sel.inspect_id = pos_map[clicked_key].id
        sel.inspect_terrain = nil

    -- Empty hex: start drag
    else
        camera.drag_active = true
        camera.drag_start_x, camera.drag_start_y = x, y
        camera.drag_cam_x = camera.offset_x
        camera.drag_cam_y = camera.offset_y
        clear_selection()
    end
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
