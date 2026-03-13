-- campaign_client.lua — Scenario and campaign loading helpers extracted from main.lua
-- Functions modify ctx fields in place; main.lua reads back state changes.
--
-- Orchestration logic (keep/castle finding, veteran placement, gold carry-over)
-- is now handled by the Rust engine via norrust_campaign_load_next_scenario.
-- This module is a thin wrapper that calls the FFI and updates UI state.

local campaign_client = {}

--- Load the selected scenario board and update board dimensions.
--- Modifies ctx.BOARD_COLS, ctx.BOARD_ROWS.
function campaign_client.load_selected_scenario(ctx)
    assert(ctx.norrust.load_board(ctx.engine, ctx.scenarios_path .. "/" .. ctx.scenario_board, 42), "Failed to load board")

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

--- Find the player keep hex and its adjacent castle hexes.
--- Used by commit_deployment to place veterans on valid hexes.
--- Note: Phase 121 will move this to Rust entirely.
local function find_keep_and_castles(ctx)
    local hex = require("hex")
    local state = ctx.norrust.get_state(ctx.engine)
    local int = ctx.int
    local keep_col, keep_row = nil, nil
    local castle_hexes = {}

    for _, tile in ipairs(state.terrain or {}) do
        local tc, tr = int(tile.col), int(tile.row)
        if tile.terrain_id == "keep" then
            if keep_col == nil or tc < keep_col then
                keep_col, keep_row = tc, tr
            end
        end
    end

    if keep_col then
        for _, tile in ipairs(state.terrain or {}) do
            if tile.terrain_id == "castle" then
                local tc, tr = int(tile.col), int(tile.row)
                if hex.distance(tc, tr, keep_col, keep_row) == 1 then
                    castle_hexes[#castle_hexes + 1] = {col = tc, row = tr}
                end
            end
        end
    end

    return keep_col, keep_row, castle_hexes
end

--- Commit veteran deployment: place only deployed veterans, start scenario.
--- Note: Phase 121 will migrate this to Rust.
function campaign_client.commit_deployment(ctx)
    local deploy = ctx.campaign_deploy
    local int = ctx.int

    -- Build filtered veterans list
    local filtered = {}
    for _, dv in ipairs(deploy.veterans) do
        if dv.deployed then
            filtered[#filtered + 1] = dv
        end
    end

    -- Find placement slots
    local keep_col, keep_row, castle_hexes = find_keep_and_castles(ctx)
    if not keep_col then
        deploy.active = false
        ctx.game_mode = ctx.PLAYING
        return
    end

    local slots = {{col = keep_col, row = keep_row}}
    for _, ch in ipairs(castle_hexes) do
        slots[#slots + 1] = ch
    end

    local state = ctx.norrust.get_state(ctx.engine)
    local pos_map = ctx.build_unit_pos_map(state)

    local placed = 0
    for _, vet in ipairs(filtered) do
        if placed >= #slots then break end
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

        local uid = ctx.norrust.place_veteran_unit(
            ctx.engine,
            vet.def_id, 0,
            int(slot.col), int(slot.row),
            int(vet.hp), int(vet.xp), int(vet.xp_needed),
            vet.advancement_pending
        )
        if uid > 0 then
            pos_map[int(slot.col) .. "," .. int(slot.row)] = {id = uid, faction = 0}
        end
    end

    deploy.active = false
    ctx.game_mode = ctx.PLAYING
end

return campaign_client
