-- norrust_love/input_setup.lua — Setup/menu/faction selection input handlers
-- Split from input.lua. Receives context references via init().

local M = {}

-- Context references (set by init)
local vars, scn, sel, campaign, camera
local shared, sound
local game_data, mods
local MODES
local int
local center_camera, clear_selection
local build_unit_pos_map
local call_load_scenario, call_load_campaign_scenario
local faction_index_for_mode
local campaign_client

function M.init(ctx)
    vars = ctx.vars
    scn = ctx.scn
    sel = ctx.sel
    campaign = ctx.campaign
    camera = ctx.camera
    shared = ctx.shared
    sound = ctx.sound
    game_data = ctx.game_data
    mods = ctx.mods
    MODES = ctx.MODES
    int = ctx.int
    center_camera = ctx.center_camera
    clear_selection = ctx.clear_selection
    build_unit_pos_map = ctx.build_unit_pos_map
    call_load_scenario = ctx.call_load_scenario
    call_load_campaign_scenario = ctx.call_load_campaign_scenario
    faction_index_for_mode = ctx.faction_index_for_mode
    campaign_client = ctx.campaign_client
end

--- Auto-place leader on a keep hex for AI/Port controlled side.
-- @param fi  faction index (0 = blue, 1 = red)
local function auto_place_leader(fi)
    local state = mods.norrust.get_state(vars.engine)
    local keep_hexes = {}
    for _, tile in ipairs(state.terrain or {}) do
        if tile.terrain_id == "keep" then
            keep_hexes[#keep_hexes + 1] = {col = int(tile.col), row = int(tile.row)}
        end
    end
    -- Sort by col: blue (fi=0) gets leftmost, red (fi=1) gets rightmost
    table.sort(keep_hexes, function(a, b) return a.col < b.col end)
    local hex_choice = keep_hexes[fi == 0 and 1 or #keep_hexes]
    if hex_choice then
        local leader_def = mods.norrust.get_faction_leader(vars.engine, game_data.faction_id[fi + 1])
        mods.norrust.place_unit_at(vars.engine, leader_def, fi, hex_choice.col, hex_choice.row)
        game_data.leader_placed[fi + 1] = true
    end
end

--- Apply starting gold and enter PLAYING mode.
local function finalize_setup()
    mods.norrust.apply_starting_gold(vars.engine, game_data.faction_id[1], game_data.faction_id[2])
    if scn.starting_gold then
        mods.norrust.set_faction_gold(vars.engine, 0, scn.starting_gold)
        mods.norrust.set_faction_gold(vars.engine, 1, scn.starting_gold)
    end
    -- Auto-start agent server if any controller is "port"
    if game_data.controllers[1] == "port" or game_data.controllers[2] == "port" then
        if not shared.agent then
            shared.agent = shared.agent_mod.new(9876)
            if shared.agent then
                vars.status_message = "Agent server on port 9876"
                vars.status_timer = 3.0
            end
        end
    end
    vars.game_mode = MODES.PLAYING
    mods.events.emit("scenario_loaded", {board = scn.board})
end

function M.handle_pick_scenario(key)
    local num = tonumber(key)
    if num and num >= 1 and num <= #game_data.SCENARIOS then
        sound.stop_music()
        campaign.active = false
        scn.board = game_data.SCENARIOS[num].board
        scn.units = game_data.SCENARIOS[num].units
        scn.preset = game_data.SCENARIOS[num].preset_units
        scn.starting_gold = game_data.SCENARIOS[num].starting_gold
        -- Preset scenarios default to human vs AI; non-preset to human vs human
        if scn.preset then
            game_data.controllers[1] = "human"
            game_data.controllers[2] = "ai"
        else
            game_data.controllers[1] = "human"
            game_data.controllers[2] = "human"
        end
        call_load_scenario()
        game_data.leader_placed[1] = false
        game_data.leader_placed[2] = false
        if scn.preset then
            -- Preset scenarios: auto-assign first two factions, skip setup
            game_data.faction_id[1] = game_data.factions[1] and game_data.factions[1].id or "loyalists"
            game_data.faction_id[2] = game_data.factions[2] and game_data.factions[2].id or "northerners"
            finalize_setup()
        else
            vars.game_mode = MODES.PICK_FACTION_BLUE
        end
    elseif key == "l" then
        -- Open save list screen
        game_data.save_list = mods.save.list_saves()
        game_data.save_idx = 1
        vars.game_mode = MODES.LOAD_SAVE
    elseif key == "c" or key == "d" or key == "f" or key == "g" then
        -- Start campaign (c=1, d=2, f=3, g=4)
        local camp_keys = {c = 1, d = 2, f = 3, g = 4}
        local camp_idx = camp_keys[key]
        if not camp_idx or not game_data.CAMPAIGNS[camp_idx] then return end
        sound.stop_music()
        local camp = game_data.CAMPAIGNS[camp_idx]
        campaign.data = mods.norrust.start_campaign(vars.engine, campaign.path .. "/" .. camp.file)
        if campaign.data then
            campaign.active = true
            campaign.index = 0
            campaign.veterans = {}
            campaign.gold = 0
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
            -- Campaign: player is human, enemy is AI
            game_data.controllers[1] = "human"
            game_data.controllers[2] = "ai"
            local sc = campaign.data.scenarios[1]
            scn.board = sc.board
            scn.units = sc.units
            scn.preset = sc.preset_units
            scn.starting_gold = nil
            call_load_scenario()
            call_load_campaign_scenario()
        end
    elseif key == "q" or key == "escape" then
        love.event.quit()
    end
end

--- Cycle controller for a faction side.
-- @param side  1 or 2 (Lua index into controllers)
local function cycle_controller(side)
    local cur = game_data.controllers[side]
    if cur == "human" then
        game_data.controllers[side] = "ai"
    elseif cur == "ai" then
        game_data.controllers[side] = "port"
    else
        game_data.controllers[side] = "human"
    end
end

function M.handle_setup(key)
    -- Faction picker: number keys + controller keys (non-preset scenarios only)
    if vars.game_mode == MODES.PICK_FACTION_BLUE or vars.game_mode == MODES.PICK_FACTION_RED then
        if key == "escape" then
            vars.game_mode = MODES.PICK_SCENARIO
            sound.play_music("data/sounds/menu_music.ogg")
            return
        end

        local is_blue = (vars.game_mode == MODES.PICK_FACTION_BLUE)
        local side = is_blue and 1 or 2

        -- Controller toggle keys
        if key == "h" then
            game_data.controllers[side] = "human"
            return
        elseif key == "tab" then
            cycle_controller(side)
            return
        end

        local num = tonumber(key)
        if num and num >= 1 and num <= #game_data.factions then
            local fi = is_blue and 0 or 1
            game_data.faction_id[fi + 1] = game_data.factions[num].id
            vars.sel_faction_idx = 0
            local ctrl = game_data.controllers[fi + 1]
            if ctrl == "ai" or ctrl == "port" then
                -- Auto-place leader for non-human controller
                auto_place_leader(fi)
                if is_blue then
                    vars.game_mode = MODES.PICK_FACTION_RED
                else
                    finalize_setup()
                end
            else
                vars.game_mode = is_blue and MODES.SETUP_BLUE or MODES.SETUP_RED
            end
        end
        return
    end

    -- Setup: Escape to return to menu
    if key == "escape" then
        vars.game_mode = MODES.PICK_SCENARIO
        sound.play_music("data/sounds/menu_music.ogg")
    end
end

function M.mousepressed_setup(col, row, x, y)
    if vars.game_mode == MODES.PICK_FACTION_BLUE or vars.game_mode == MODES.PICK_FACTION_RED then
        return
    end

    if col < 0 or col >= scn.COLS or row < 0 or row >= scn.ROWS then
        return
    end

    local state = mods.norrust.get_state(vars.engine)
    local pos_map = build_unit_pos_map(state)
    local fi = faction_index_for_mode()
    local faction = fi

    if not game_data.leader_placed[fi + 1] then
        local pkey = col .. "," .. row
        if not pos_map[pkey] then
            local leader_def = mods.norrust.get_faction_leader(vars.engine, game_data.faction_id[fi + 1])
            mods.norrust.place_unit_at(vars.engine, leader_def, faction, col, row)
            game_data.leader_placed[fi + 1] = true
            -- Auto-advance after leader placement
            if vars.game_mode == MODES.SETUP_BLUE then
                vars.game_mode = MODES.PICK_FACTION_RED
            else
                finalize_setup()
            end
        end
    end
end

return M
