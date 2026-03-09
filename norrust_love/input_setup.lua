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

function M.handle_pick_scenario(key)
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
            game_data.leader_placed[1] = false
            game_data.leader_placed[2] = false
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

function M.handle_setup(key)
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
                mods.norrust.apply_starting_gold(vars.engine, game_data.faction_id[1], game_data.faction_id[2])
                vars.game_mode = MODES.PLAYING
                mods.events.emit("scenario_loaded", {board = scn.board})
            end
        end
    end
end

return M
