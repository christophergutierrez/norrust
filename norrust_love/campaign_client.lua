-- campaign_client.lua — Scenario and campaign loading helpers extracted from main.lua
-- Functions modify ctx fields in place; main.lua reads back state changes.
--
-- Orchestration logic (keep/castle finding, veteran placement, gold carry-over)
-- is now handled by the Rust engine via norrust_campaign_load_next_scenario.
-- This module is a thin wrapper that calls the FFI and updates UI state.

local campaign_client = {}

--- Load the selected scenario board and update board dimensions.
--- For preset scenarios, also loads units from the units TOML file.
--- Modifies ctx.BOARD_COLS, ctx.BOARD_ROWS.
function campaign_client.load_selected_scenario(ctx)
    assert(ctx.norrust.load_board(ctx.engine, ctx.scenarios_path .. "/" .. ctx.scenario_board, 42), "Failed to load board")

    -- For preset scenarios, load units from TOML
    if ctx.scenario_preset and ctx.scenario_units then
        ctx.norrust.load_units(ctx.engine, ctx.scenarios_path .. "/" .. ctx.scenario_units)
    end

    -- Read board dimensions from state
    local state = ctx.norrust.get_state(ctx.engine)
    ctx.BOARD_COLS = ctx.int(state.cols or 8)
    ctx.BOARD_ROWS = ctx.int(state.rows or 5)

    ctx.center_camera(true)
end

--- Load the next campaign scenario via the Rust engine.
--- The engine handles board loading, unit placement, veteran deployment,
--- and gold carry-over in a single FFI call.
function campaign_client.load_campaign_scenario(ctx)
    -- Reset client state for new scenario
    ctx.game_over = false
    ctx.winner_faction = -1
    ctx.clear_selection()
    ctx.recruit_mode = false

    -- Single FFI call: loads board, places units, places veterans, applies gold
    local result = ctx.norrust.campaign_load_next_scenario(ctx.engine, ctx.scenarios_path)

    -- Update scenario metadata from engine result (for save system / events)
    if result.board then
        ctx.scenario_board = result.board
    end

    -- Read board dimensions and center camera
    local state = ctx.norrust.get_state(ctx.engine)
    ctx.BOARD_COLS = ctx.int(state.cols or 8)
    ctx.BOARD_ROWS = ctx.int(state.rows or 5)
    ctx.center_camera(true)

    if result.status == "deploy_needed" then
        -- Populate deploy screen from engine response
        local deploy = ctx.campaign_deploy
        deploy.veterans = {}
        for _, vet in ipairs(result.veterans or {}) do
            deploy.veterans[#deploy.veterans + 1] = {
                def_id = vet.def_id,
                hp = ctx.int(vet.hp),
                xp = ctx.int(vet.xp),
                xp_needed = ctx.int(vet.xp_needed),
                advancement_pending = vet.advancement_pending,
                deployed = vet.deployed,
                uuid = vet.uuid,
            }
        end
        deploy.slots = result.slots
        deploy.selected = 1
        deploy.active = true
        ctx.game_mode = ctx.DEPLOY_VETERANS
    elseif result.status == "complete" then
        -- Campaign finished (shouldn't normally happen here)
        ctx.game_mode = ctx.PLAYING
    else
        -- "playing" or error — start playing
        ctx.game_mode = ctx.PLAYING
    end
end

--- Commit veteran deployment: send deployed veteran indices to engine for placement.
function campaign_client.commit_deployment(ctx)
    local deploy = ctx.campaign_deploy

    -- Build JSON array of deployed veteran indices (0-based for Rust)
    local indices = {}
    for i, dv in ipairs(deploy.veterans) do
        if dv.deployed then
            indices[#indices + 1] = i - 1  -- Lua 1-based → Rust 0-based
        end
    end

    -- Single FFI call: engine finds keep/castles, places veterans, maps UUIDs
    local json = "[" .. table.concat(indices, ",") .. "]"
    ctx.norrust.campaign_commit_deployment(ctx.engine, json)

    deploy.active = false
    ctx.game_mode = ctx.PLAYING
end

return campaign_client
