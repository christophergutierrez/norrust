-- campaign_client.lua — Scenario and campaign loading helpers extracted from main.lua
-- Functions modify ctx fields in place; main.lua reads back state changes.

local campaign_client = {}

--- Load the selected scenario board and update board dimensions.
--- Modifies ctx.BOARD_COLS, ctx.BOARD_ROWS.
function campaign_client.load_selected_scenario(ctx)
    assert(ctx.norrust.load_board(ctx.engine, ctx.scenarios_path .. "/" .. ctx.scenario_board, 42), "Failed to load board")

    -- Read board dimensions from state
    local state = ctx.norrust.get_state(ctx.engine)
    ctx.BOARD_COLS = ctx.int(state.cols or 8)
    ctx.BOARD_ROWS = ctx.int(state.rows or 5)

    ctx.center_camera()
end

--- Find the player keep hex and its adjacent castle hexes for veteran placement.
function campaign_client.find_keep_and_castles(ctx)
    local state = ctx.norrust.get_state(ctx.engine)
    local int = ctx.int
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
function campaign_client.place_veterans(ctx)
    if #ctx.campaign_veterans == 0 then return end

    local int = ctx.int
    local keep_col, keep_row, castle_hexes = campaign_client.find_keep_and_castles(ctx)
    if not keep_col then return end

    local state = ctx.norrust.get_state(ctx.engine)
    local pos_map = ctx.build_unit_pos_map(state)

    -- Build placement list: keep first, then castles
    local slots = {{col = keep_col, row = keep_row}}
    for _, ch in ipairs(castle_hexes) do
        slots[#slots + 1] = ch
    end

    local placed = 0
    for _, vet in ipairs(ctx.campaign_veterans) do
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

        local uid = ctx.norrust.get_next_unit_id(ctx.engine)
        ctx.norrust.place_veteran_unit(
            ctx.engine, uid,
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
--- Modifies ctx: scenario_board, scenario_units, scenario_preset, game_over,
--- winner_faction, recruit_mode, next_unit_id, game_mode.
function campaign_client.load_campaign_scenario(ctx)
    local int = ctx.int
    local sc = ctx.campaign_data.scenarios[ctx.campaign_index + 1]
    ctx.scenario_board = sc.board
    ctx.scenario_units = sc.units
    ctx.scenario_preset = sc.preset_units

    -- Reset client state for new scenario
    ctx.game_over = false
    ctx.winner_faction = -1
    ctx.clear_selection()
    ctx.recruit_mode = false

    -- Load board (creates fresh GameState; registries stay)
    campaign_client.load_selected_scenario(ctx)

    -- Load preset units + starting gold
    if ctx.scenario_preset then
        ctx.norrust.apply_starting_gold(ctx.engine, ctx.faction_id[1], ctx.faction_id[2])
        ctx.norrust.load_units(ctx.engine, ctx.scenarios_path .. "/" .. ctx.scenario_units)
        ctx.next_unit_id = ctx.norrust.get_next_unit_id(ctx.engine)
    end

    -- Place veterans from previous scenario
    if ctx.campaign_index > 0 and #ctx.campaign_veterans > 0 then
        campaign_client.place_veterans(ctx)
        ctx.next_unit_id = ctx.norrust.get_next_unit_id(ctx.engine)
    end

    -- Apply carry-over gold (override faction 0's starting gold)
    if ctx.campaign_index > 0 and ctx.campaign_gold > 0 then
        ctx.norrust.set_faction_gold(ctx.engine, 0, ctx.campaign_gold)
    end

    ctx.game_mode = ctx.PLAYING
end

return campaign_client
