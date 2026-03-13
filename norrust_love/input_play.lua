-- norrust_love/input_play.lua — PLAYING mode input handlers
-- Split from input.lua. Receives context references via init().

local M = {}

-- Context references (set by init)
local vars, scn, sel, ghost, campaign, dlg, camera
local shared, combat_state, pending_anims, sound
local game_data, mods
local MODES
local int
local center_camera, clear_selection, cancel_ghost, cancel_combat_preview
local is_ranged_attack, commit_ghost_move, execute_attack, check_game_over
local build_unit_pos_map, unit_max_range, select_unit
local get_attackable_enemies, ghost_attackable_set
local call_load_campaign_scenario
local campaign_client

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
    call_load_campaign_scenario = ctx.call_load_campaign_scenario
    campaign_client = ctx.campaign_client
end

function M.keypressed(key)
    -- Block input when active faction is not human-controlled
    local active_f = mods.norrust.get_active_faction(vars.engine)
    local ctrl = game_data.controllers and game_data.controllers[active_f + 1] or "human"
    if ctrl ~= "human" and not vars.game_over then return end

    -- Advance choice mode: pick advancement branch
    if sel.advance_choice then
        local ac = sel.advance_choice
        if key == "return" or key == "kpenter" then
            mods.norrust.apply_advance(vars.engine, ac.unit_id, ac.selected - 1)
            sel.advance_choice = nil
            clear_selection()
        elseif key == "escape" then
            sel.advance_choice = nil
        elseif key == "up" then
            ac.selected = math.max(1, ac.selected - 1)
        elseif key == "down" then
            ac.selected = math.min(#ac.options, ac.selected + 1)
        else
            local num = tonumber(key)
            if num and num >= 1 and num <= #ac.options then
                ac.selected = num
                mods.norrust.apply_advance(vars.engine, ac.unit_id, num - 1)
                sel.advance_choice = nil
                clear_selection()
            end
        end
        return
    end

    if vars.game_over then
        if key == "return" or key == "kpenter" then
            if campaign.active and vars.winner_faction == 0 then
                -- Player won — engine handles roster sync, veteran extraction, gold, index advance
                local result = mods.norrust.campaign_record_victory(vars.engine, 0)
                if result and result.status == "next_scenario" then
                    call_load_campaign_scenario()
                else
                    -- Campaign complete — return to scenario selection
                    campaign.active = false
                    vars.game_over = false
                    vars.winner_faction = -1
                    vars.game_mode = MODES.PICK_SCENARIO
                    sound.play_music("data/sounds/menu_music.ogg")
                end
            else
                -- Individual scenario win/loss, or campaign defeat
                campaign.active = false
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

        -- End turn — AI/Port turns auto-triggered by love.update
        mods.norrust.end_turn(vars.engine)
        clear_selection()
        check_game_over()
        dlg.active = {}
        mods.events.emit("dialogue", {trigger = "turn_start"})

    elseif key == "a" then
        -- Advance selected unit (with branch choice if multiple options)
        if sel.advance_choice then
            -- Already in choice mode — ignore 'a' press
        elseif sel.unit_id ~= -1 then
            local state = mods.norrust.get_state(vars.engine)
            local active = mods.norrust.get_active_faction(vars.engine)
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == sel.unit_id
                    and int(unit.faction) == active
                    and unit.advancement_pending then
                    local options = mods.norrust.get_advance_options(vars.engine, sel.unit_id)
                    if #options > 1 then
                        -- Multiple options: enter choice mode
                        sel.advance_choice = {unit_id = sel.unit_id, options = options, selected = 1}
                    else
                        -- Single option or auto-advance
                        mods.norrust.apply_advance(vars.engine, sel.unit_id, 0)
                        clear_selection()
                    end
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
            -- Build veteran recruit list from engine roster (campaign only)
            sel.recruit_state.veterans = {}
            if campaign.active then
                local living = mods.norrust.campaign_get_living(vars.engine)
                -- Filter out veterans already on the board (mapped to engine IDs)
                local mapped_uuids = mods.norrust.campaign_get_mapped_uuids(vars.engine)
                local mapped = {}
                for _, uuid in ipairs(mapped_uuids) do
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

function M.mousepressed(col, row, clicked_key, state, pos_map, active, x, y)
    if vars.game_over then return end

    -- Block mouse input when active faction is not human-controlled
    local ctrl = game_data.controllers and game_data.controllers[active + 1] or "human"
    if ctrl ~= "human" then return end

    -- Recruit mode click
    if sel.recruit_mode then
        local vet_count = #sel.recruit_state.veterans
        if sel.recruit_idx < vet_count then
            -- Veteran recruitment: place veteran unit from roster
            local vet = sel.recruit_state.veterans[sel.recruit_idx + 1]
            local uid = mods.norrust.place_veteran_unit(
                vars.engine,
                vet.def_id, 0,
                col, row,
                int(vet.hp), int(vet.xp), int(vet.xp_needed),
                vet.advancement_pending
            )
            if uid > 0 then
                mods.norrust.campaign_map_id(vars.engine, uid, vet.uuid)
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
                sel.recruit_error = err_map[uid] or string.format("Place failed (code %d)", uid)
            end
        else
            -- Normal recruitment from palette
            local palette_idx = sel.recruit_idx - vet_count
            local def_id = sel.recruit_palette[palette_idx + 1] or ""
            if def_id ~= "" then
                local uid = mods.norrust.recruit_unit_at(vars.engine, def_id, col, row)
                if uid > 0 then
                    -- Add recruited unit to campaign roster via engine
                    if campaign.active then
                        local st = mods.norrust.get_state(vars.engine)
                        for _, u in ipairs(st.units or {}) do
                            if int(u.id) == uid then
                                mods.norrust.campaign_add_unit(vars.engine,
                                    u.def_id, uid,
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
                    sel.recruit_error = err_map[uid] or string.format("Recruit failed (code %d)", uid)
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

return M
