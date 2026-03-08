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

    ctx.center_camera(true)
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
--- If roster is available, maps engine IDs to existing UUIDs.
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

    -- Clear roster id_map for new scenario
    if ctx.campaign_roster and ctx.roster_mod then
        ctx.roster_mod.clear_id_map(ctx.campaign_roster)
    end

    -- Build UUID list from living roster entries (parallel to campaign_veterans)
    local vet_uuids = {}
    if ctx.campaign_roster then
        local living = ctx.roster_mod.get_living(ctx.campaign_roster)
        for i, entry in ipairs(living) do
            vet_uuids[i] = entry.uuid
        end
    end


    local uid = ctx.norrust.get_next_unit_id(ctx.engine)
    local placed = 0
    for vi, vet in ipairs(ctx.campaign_veterans) do
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

        local rc = ctx.norrust.place_veteran_unit(
            ctx.engine, uid,
            vet.def_id, 0,
            int(slot.col), int(slot.row),
            int(vet.hp), int(vet.xp), int(vet.xp_needed),
            vet.advancement_pending
        )
        -- Map engine ID to roster UUID
        if ctx.campaign_roster and vet_uuids[vi] then
            ctx.roster_mod.map_id(ctx.campaign_roster, uid, vet_uuids[vi])
        end

        -- Update pos_map so next veteran doesn't collide
        pos_map[int(slot.col) .. "," .. int(slot.row)] = {id = uid, faction = 0}
        uid = uid + 1
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

    -- Populate roster from preset units on first scenario
    if ctx.campaign_index == 0 and ctx.campaign_roster and ctx.roster_mod then
        local state = ctx.norrust.get_state(ctx.engine)
        local int = ctx.int
        for _, u in ipairs(state.units or {}) do
            if int(u.faction) == 0 then
                ctx.roster_mod.add(ctx.campaign_roster, u.def_id, int(u.id),
                    int(u.hp), int(u.max_hp), int(u.xp), int(u.xp_needed),
                    u.advancement_pending or false)
            end
        end
    end

    -- Place veterans from previous scenario
    if ctx.campaign_index > 0 and #ctx.campaign_veterans > 0 then
        -- Count available slots
        local keep_col, keep_row, castle_hexes = campaign_client.find_keep_and_castles(ctx)
        local state = ctx.norrust.get_state(ctx.engine)
        local pos_map = ctx.build_unit_pos_map(state)
        local available = 0
        if keep_col then
            -- Count keep + unoccupied castles
            local check_key = ctx.int(keep_col) .. "," .. ctx.int(keep_row)
            if not pos_map[check_key] then available = available + 1 end
            for _, ch in ipairs(castle_hexes) do
                local ck = ctx.int(ch.col) .. "," .. ctx.int(ch.row)
                if not pos_map[ck] then available = available + 1 end
            end
        end

        if #ctx.campaign_veterans > available and available > 0 then
            -- Overflow: show deploy screen
            local deploy = ctx.campaign_deploy
            deploy.veterans = {}
            local living = ctx.roster_mod and ctx.campaign_roster
                and ctx.roster_mod.get_living(ctx.campaign_roster) or {}
            for i, vet in ipairs(ctx.campaign_veterans) do
                local uuid = living[i] and living[i].uuid or nil
                deploy.veterans[#deploy.veterans + 1] = {
                    def_id = vet.def_id,
                    hp = ctx.int(vet.hp),
                    xp = ctx.int(vet.xp),
                    xp_needed = ctx.int(vet.xp_needed),
                    advancement_pending = vet.advancement_pending,
                    deployed = (i <= available),
                    uuid = uuid,
                }
            end
            deploy.slots = available
            deploy.selected = 1
            deploy.active = true

            -- Apply carry-over gold before deploy screen
            if ctx.campaign_gold > 0 then
                ctx.norrust.set_faction_gold(ctx.engine, 0, ctx.campaign_gold)
            end

            ctx.game_mode = ctx.DEPLOY_VETERANS
            return
        end

        campaign_client.place_veterans(ctx)
        ctx.next_unit_id = ctx.norrust.get_next_unit_id(ctx.engine)
    end

    -- Apply carry-over gold (override faction 0's starting gold)
    if ctx.campaign_index > 0 and ctx.campaign_gold > 0 then
        ctx.norrust.set_faction_gold(ctx.engine, 0, ctx.campaign_gold)
    end

    ctx.game_mode = ctx.PLAYING
end

--- Commit veteran deployment: place only deployed veterans, start scenario.
function campaign_client.commit_deployment(ctx)
    local deploy = ctx.campaign_deploy

    -- Build filtered veterans list from deployed entries
    local filtered = {}
    for _, dv in ipairs(deploy.veterans) do
        if dv.deployed then
            filtered[#filtered + 1] = {
                def_id = dv.def_id,
                hp = dv.hp,
                xp = dv.xp,
                xp_needed = dv.xp_needed,
                advancement_pending = dv.advancement_pending,
            }
        end
    end

    -- Temporarily replace campaign_veterans with filtered list
    local orig = ctx.campaign_veterans
    ctx.campaign_veterans = filtered
    campaign_client.place_veterans(ctx)
    ctx.campaign_veterans = orig

    ctx.next_unit_id = ctx.norrust.get_next_unit_id(ctx.engine)
    deploy.active = false
    ctx.game_mode = ctx.PLAYING
end

return campaign_client
