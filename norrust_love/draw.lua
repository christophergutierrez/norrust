-- draw.lua — All rendering functions extracted from main.lua
-- Uses a context table (ctx) passed to each function for shared state access.

local draw = {}

--- Draw all units on the board.
function draw.draw_units(ctx, state)
    local int = ctx.int
    local fonts = ctx.fonts
    local alive_ids = {}

    for _, unit in ipairs(state.units or {}) do
        local col = int(unit.col)
        local row = int(unit.row)
        local faction = int(unit.faction)
        local hp = int(unit.hp)
        local uid = int(unit.id)
        local exhausted = unit.moved or unit.attacked

        alive_ids[uid] = true

        -- Skip ghost unit at original position (drawn separately)
        if ctx.ghost_col ~= nil and uid == ctx.ghost_unit_id then
            local ox, oy = ctx.hex.to_pixel(col, row)
            love.graphics.setColor(0.5, 0.5, 0.5, 0.3)
            love.graphics.setLineWidth(2)
            love.graphics.circle("line", ox, oy, ctx.hex.RADIUS * 0.4)
            goto continue
        end

        local cx, cy = ctx.hex.to_pixel(col, row)
        local alpha = exhausted and 0.4 or 1.0

        -- Get or create animation state for this unit
        local anim_state = ctx.unit_anims[uid]
        if not anim_state then
            anim_state = ctx.anim_module.new_state()
            anim_state.def_id = unit.def_id
            ctx.unit_anims[uid] = anim_state
        end

        -- Determine facing based on faction (like chess: always face opponent)
        anim_state.facing = faction == 0 and "right" or "left"

        -- Try sprite rendering first; fall back to colored circle
        local drawn = ctx.assets.draw_unit_sprite(ctx.unit_sprites, unit.def_id, cx, cy, ctx.hex.RADIUS, faction, alpha, ctx.FACTION_COLORS, anim_state)
        if not drawn then
            if faction == 0 then
                love.graphics.setColor(ctx.BLUE[1], ctx.BLUE[2], ctx.BLUE[3], alpha)
            else
                love.graphics.setColor(ctx.RED[1], ctx.RED[2], ctx.RED[3], alpha)
            end
            love.graphics.circle("fill", cx, cy, ctx.hex.RADIUS * 0.45)

            local word = (unit.def_id or ""):match("^([^_]+)") or unit.def_id or ""
            local abbrev = (word:sub(1, 1):upper() .. word:sub(2):lower()):sub(1, 7)
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.setFont(fonts[14])
            love.graphics.printf(abbrev, cx - 42, cy - 14, 84, "center")
        end

        -- HP (always drawn on top)
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.setFont(fonts[18])
        love.graphics.print(tostring(hp), cx - 12, cy - 2)

        -- Advancement ring
        if unit.advancement_pending then
            love.graphics.setColor(1.0, 0.85, 0.0, 1)
            love.graphics.setLineWidth(3.5)
            love.graphics.arc("line", "open", cx, cy, ctx.hex.RADIUS * 0.52, 0, math.pi * 2, 24)
        end

        -- XP text
        if unit.xp_needed and int(unit.xp_needed) > 0 then
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.setFont(fonts[14])
            love.graphics.print(int(unit.xp) .. "/" .. int(unit.xp_needed), cx - 15, cy + 14)
        end
        ::continue::
    end

    -- Clean up stale animation states for dead/removed units
    for uid in pairs(ctx.unit_anims) do
        if not alive_ids[uid] then
            ctx.unit_anims[uid] = nil
        end
    end
end

--- Draw the setup HUD (scenario selection, faction picking, leader placement).
function draw.draw_setup_hud(ctx)
    local int = ctx.int
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()

    -- Scenario selection screen
    if ctx.game_mode == ctx.PICK_SCENARIO then
        love.graphics.setFont(fonts[18])
        love.graphics.setColor(1, 0.85, 0, 1)
        love.graphics.printf("The Clash for Norrust", 0, vp_h / 2 - 60, vp_w, "center")

        love.graphics.setFont(fonts[14])
        love.graphics.setColor(0.83, 0.83, 0.83, 1)
        love.graphics.printf("Select a scenario:", 0, vp_h / 2 - 20, vp_w, "center")

        for i, sc in ipairs(ctx.SCENARIOS) do
            love.graphics.setFont(fonts[15])
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.printf(string.format("[%d] %s", i, sc.name), 0, vp_h / 2 + 10 + (i - 1) * 28, vp_w, "center")
        end

        -- Campaign section
        local cy = vp_h / 2 + 10 + #ctx.SCENARIOS * 28 + 10
        love.graphics.setFont(fonts[14])
        love.graphics.setColor(0.83, 0.83, 0.83, 1)
        love.graphics.printf("Campaigns:", 0, cy, vp_w, "center")
        cy = cy + 22
        for i, camp in ipairs(ctx.CAMPAIGNS) do
            love.graphics.setFont(fonts[15])
            love.graphics.setColor(1, 0.85, 0, 1)
            love.graphics.printf(string.format("[C] %s", camp.name), 0, cy + (i - 1) * 28, vp_w, "center")
        end
        return
    end

    local is_blue = (ctx.game_mode == ctx.PICK_FACTION_BLUE or ctx.game_mode == ctx.SETUP_BLUE)
    local faction_name = is_blue and "Blue" or "Red"
    local fc = is_blue and ctx.BLUE or ctx.RED

    -- Sidebar background
    love.graphics.setColor(0, 0, 0, 0.6)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    if ctx.game_mode == ctx.PICK_FACTION_BLUE or ctx.game_mode == ctx.PICK_FACTION_RED then
        love.graphics.setFont(fonts[15])
        love.graphics.setColor(fc[1], fc[2], fc[3])
        love.graphics.print("FACTION — " .. faction_name, vp_w - 190, 10)

        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("Press 1-" .. #ctx.factions .. " to pick", vp_w - 190, 30)

        for i, f in ipairs(ctx.factions) do
            local y = 56 + (i - 1) * 22
            local label = "[" .. i .. "] " .. f.name
            if (i - 1) == ctx.sel_faction_idx then
                love.graphics.setColor(1, 1, 0, 1)
            else
                love.graphics.setColor(1, 1, 1, 1)
            end
            love.graphics.setFont(fonts[13])
            love.graphics.print(label, vp_w - 190, y)
        end
    else
        love.graphics.setFont(fonts[15])
        love.graphics.setColor(fc[1], fc[2], fc[3])
        love.graphics.print("SETUP — " .. faction_name, vp_w - 190, 10)

        local fi = ctx.faction_index_for_mode()
        if not ctx.leader_placed[fi + 1] then
            local leader_def = ctx.norrust.get_faction_leader(ctx.engine, ctx.faction_id[fi + 1])

            love.graphics.setFont(fonts[11])
            love.graphics.setColor(0.83, 0.83, 0.83)
            love.graphics.print("Place leader:", vp_w - 190, 30)
            love.graphics.setFont(fonts[14])
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.print(leader_def, vp_w - 190, 48)

            -- Board-center prompt
            local bx, by = ctx.hex.to_pixel(int(ctx.BOARD_COLS / 2), int(ctx.BOARD_ROWS / 2))
            local sx = bx + ctx.board_origin_x + ctx.camera_offset_x
            local sy = by + ctx.board_origin_y + ctx.camera_offset_y
            local prompt = "Click a hex on the board to place " .. leader_def
            love.graphics.setColor(0, 0, 0, 0.75)
            love.graphics.rectangle("fill", sx - 200, sy - 14, 400, 24)
            love.graphics.setFont(fonts[13])
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.print(prompt, sx - 196, sy - 8)
        else
            love.graphics.setFont(fonts[11])
            love.graphics.setColor(0.83, 0.83, 0.83)
            love.graphics.print("Leader placed.", vp_w - 190, 30)
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.print("[Enter] Continue", vp_w - 190, 44)
        end
    end
end

--- Draw the recruit panel sidebar.
function draw.draw_recruit_panel(ctx, state)
    local int = ctx.int
    local fonts = ctx.fonts
    local faction = ctx.norrust.get_active_faction(ctx.engine)
    local vp_w, vp_h = ctx.get_viewport()
    local fc = faction == 0 and ctx.BLUE or ctx.RED
    local gold_arr = state.gold or {0, 0}
    local gold = int(gold_arr[faction + 1] or 0)

    -- Sidebar background
    love.graphics.setColor(0, 0, 0, 0.6)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    love.graphics.setFont(fonts[15])
    love.graphics.setColor(fc[1], fc[2], fc[3])
    love.graphics.print(string.format("RECRUIT — %dg", gold), vp_w - 190, 10)

    love.graphics.setFont(fonts[11])
    love.graphics.setColor(1, 1, 0, 1)
    love.graphics.print("Leader must be on gold hex", vp_w - 190, 30)
    love.graphics.setColor(0.83, 0.83, 0.83)
    love.graphics.print("Click adjacent blue hex", vp_w - 190, 44)
    love.graphics.print("[R] Cancel", vp_w - 190, 58)

    if ctx.recruit_error ~= "" then
        love.graphics.setColor(1, 0, 0, 1)
        love.graphics.print(ctx.recruit_error, vp_w - 190, 72)
    end

    for i, def_id in ipairs(ctx.recruit_palette) do
        local cost = ctx.norrust.get_unit_cost(ctx.engine, def_id)
        local y = 94 + (i - 1) * 20
        local label = string.format("[%d] %s (%dg)", i, def_id, cost)
        if (i - 1) == ctx.selected_recruit_idx then
            love.graphics.setColor(1, 1, 0, 1)
        else
            love.graphics.setColor(1, 1, 1, 1)
        end
        love.graphics.print(label, vp_w - 190, y)
    end
end

--- Draw the unit inspection panel sidebar.
function draw.draw_unit_panel(ctx, unit)
    local int = ctx.int
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()

    love.graphics.setColor(0, 0, 0, 0.75)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    local faction = int(unit.faction)
    local faction_name = faction == 0 and "Blue" or "Red"
    local fc = faction == 0 and ctx.BLUE or ctx.RED

    local y = 10

    -- Portrait
    local portrait_h = ctx.assets.draw_portrait(ctx.unit_sprites, unit.def_id, vp_w - 195, y, 180, 120)
    if portrait_h > 0 then
        y = y + portrait_h + 6
    end

    -- Unit name + faction
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(fc[1], fc[2], fc[3])
    love.graphics.print(unit.def_id or "", vp_w - 190, y)
    y = y + 18
    love.graphics.setFont(fonts[11])
    love.graphics.print(faction_name, vp_w - 190, y)
    y = y + 20

    -- HP
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.setFont(fonts[12])
    love.graphics.print(string.format("HP: %d / %d", int(unit.hp), int(unit.max_hp)), vp_w - 190, y)
    y = y + 16

    -- XP
    if unit.xp_needed and int(unit.xp_needed) > 0 then
        love.graphics.print(string.format("XP: %d / %d", int(unit.xp), int(unit.xp_needed)), vp_w - 190, y)
        y = y + 16
    end

    -- Movement
    local move_status = ""
    if unit.moved and unit.attacked then
        move_status = " (done)"
    elseif unit.moved then
        move_status = " (moved)"
    elseif unit.attacked then
        move_status = " (attacked)"
    end
    love.graphics.print(string.format("Move: %d%s", int(unit.movement), move_status), vp_w - 190, y)
    y = y + 20

    -- Attacks
    local attacks = unit.attacks or {}
    if #attacks > 0 then
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("── Attacks ──", vp_w - 190, y)
        y = y + 15
        for _, atk in ipairs(attacks) do
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.setFont(fonts[12])
            love.graphics.print(atk.name or "", vp_w - 190, y)
            y = y + 14
            love.graphics.setColor(1, 1, 1, 1)
            love.graphics.setFont(fonts[11])
            love.graphics.print(string.format("  %dx%d %s", int(atk.damage), int(atk.strikes), atk.range or ""), vp_w - 190, y)
            y = y + 15
        end
    end

    -- Abilities
    local abilities = unit.abilities or {}
    if #abilities > 0 then
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("── Abilities ──", vp_w - 190, y)
        y = y + 15
        for _, ab in ipairs(abilities) do
            love.graphics.setColor(0.6, 1.0, 0.6)
            love.graphics.print(ab, vp_w - 190, y)
            y = y + 14
        end
    end
end

--- Draw the terrain inspection panel sidebar.
function draw.draw_terrain_panel(ctx)
    local fonts = ctx.fonts
    local int = ctx.int
    local vp_w, vp_h = ctx.get_viewport()
    local t = ctx.inspect_terrain

    love.graphics.setColor(0, 0, 0, 0.75)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    local y = 10

    -- Terrain name
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(0.9, 0.85, 0.6)
    love.graphics.print(t.terrain_id or "", vp_w - 190, y)
    y = y + 22

    -- Coordinates
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.6, 0.6, 0.6)
    love.graphics.print(string.format("(%d, %d)", t.col, t.row), vp_w - 190, y)
    y = y + 20

    -- Base stats
    love.graphics.setFont(fonts[12])
    love.graphics.setColor(1, 1, 1, 1)
    love.graphics.print(string.format("Defense: %d%%", t.defense), vp_w - 190, y)
    y = y + 16
    love.graphics.print(string.format("Move cost: %d", t.movement_cost), vp_w - 190, y)
    y = y + 16

    if t.healing and t.healing > 0 then
        love.graphics.setColor(0.4, 1.0, 0.4)
        love.graphics.print(string.format("Healing: +%d HP", t.healing), vp_w - 190, y)
        y = y + 16
    end

    -- Unit-specific stats
    if t.unit_defense then
        y = y + 8
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(0.83, 0.83, 0.83)
        love.graphics.print("── Unit on terrain ──", vp_w - 190, y)
        y = y + 15
        love.graphics.setFont(fonts[12])
        love.graphics.setColor(1, 1, 0, 1)
        love.graphics.print(string.format("Eff. defense: %d%%", t.unit_defense), vp_w - 190, y)
        y = y + 16
        love.graphics.setColor(1, 1, 1, 1)
        love.graphics.print(string.format("Eff. move cost: %d", t.unit_move_cost), vp_w - 190, y)
    end
end

--- Draw the combat preview panel sidebar.
function draw.draw_combat_preview(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()
    local p = ctx.combat_preview

    love.graphics.setColor(0, 0, 0, 0.85)
    love.graphics.rectangle("fill", vp_w - 200, 0, 200, vp_h)

    local y = 10

    -- Header
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(1.0, 0.9, 0.3)
    love.graphics.print("COMBAT PREVIEW", vp_w - 190, y)
    y = y + 24

    -- Attacker section
    love.graphics.setFont(fonts[12])
    love.graphics.setColor(0.5, 0.8, 1.0)
    love.graphics.print("── Attacker ──", vp_w - 190, y)
    y = y + 16

    love.graphics.setColor(0.6, 0.8, 0.6)
    love.graphics.print(string.format("Terrain: %d%% def", p.attacker_terrain_defense or 0), vp_w - 190, y)
    y = y + 14

    love.graphics.setColor(1, 1, 1)
    love.graphics.print(string.format("%s", p.attacker_attack_name or "?"), vp_w - 190, y)
    y = y + 14
    love.graphics.print(string.format("%dx%d  (max %d)",
        p.attacker_damage_per_hit or 0, p.attacker_strikes or 0,
        p.attacker_damage_max or 0), vp_w - 190, y)
    y = y + 14
    love.graphics.print(string.format("Hit: %d%%", p.attacker_hit_pct or 0), vp_w - 190, y)
    y = y + 14

    love.graphics.setColor(0.9, 0.9, 0.9)
    love.graphics.print(string.format("Dmg: %d - %.1f - %d",
        p.attacker_damage_min or 0, p.attacker_damage_mean or 0, p.attacker_damage_max or 0), vp_w - 190, y)
    y = y + 14

    -- Kill % with color
    local ak = p.attacker_kill_pct or 0
    if ak >= 30 then
        love.graphics.setColor(0.3, 1.0, 0.3)
    elseif ak >= 10 then
        love.graphics.setColor(1.0, 1.0, 0.3)
    else
        love.graphics.setColor(0.7, 0.7, 0.7)
    end
    love.graphics.print(string.format("Kill: %.0f%%", ak), vp_w - 190, y)
    y = y + 14

    love.graphics.setColor(0.6, 0.6, 0.6)
    love.graphics.print(string.format("Target HP: %d", p.defender_hp or 0), vp_w - 190, y)
    y = y + 20

    -- Defender retaliation section
    love.graphics.setFont(fonts[12])
    love.graphics.setColor(1.0, 0.5, 0.3)
    love.graphics.print("── Retaliation ──", vp_w - 190, y)
    y = y + 16

    love.graphics.setColor(0.6, 0.8, 0.6)
    love.graphics.print(string.format("Terrain: %d%% def", p.defender_terrain_defense or 0), vp_w - 190, y)
    y = y + 14

    local def_name = p.defender_attack_name or "none"
    if def_name == "none" then
        love.graphics.setColor(0.5, 0.5, 0.5)
        love.graphics.print("No retaliation", vp_w - 190, y)
        y = y + 14
    else
        love.graphics.setColor(1, 1, 1)
        love.graphics.print(string.format("%s", def_name), vp_w - 190, y)
        y = y + 14
        love.graphics.print(string.format("%dx%d  (max %d)",
            p.defender_damage_per_hit or 0, p.defender_strikes or 0,
            p.defender_damage_max or 0), vp_w - 190, y)
        y = y + 14
        love.graphics.print(string.format("Hit: %d%%", p.defender_hit_pct or 0), vp_w - 190, y)
        y = y + 14

        love.graphics.setColor(0.9, 0.9, 0.9)
        love.graphics.print(string.format("Dmg: %d - %.1f - %d",
            p.defender_damage_min or 0, p.defender_damage_mean or 0, p.defender_damage_max or 0), vp_w - 190, y)
        y = y + 14

        -- Defender kill % with danger color
        local dk = p.defender_kill_pct or 0
        if dk >= 20 then
            love.graphics.setColor(1.0, 0.2, 0.2)
        elseif dk >= 5 then
            love.graphics.setColor(1.0, 0.7, 0.3)
        else
            love.graphics.setColor(0.7, 0.7, 0.7)
        end
        love.graphics.print(string.format("Kill: %.0f%%", dk), vp_w - 190, y)
        y = y + 14

        love.graphics.setColor(0.6, 0.6, 0.6)
        love.graphics.print(string.format("Your HP: %d", p.attacker_hp or 0), vp_w - 190, y)
        y = y + 14
    end

    -- Controls hint
    y = y + 12
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.5, 0.8, 0.5)
    love.graphics.print("[Enter] Attack", vp_w - 190, y)
    y = y + 14
    love.graphics.setColor(0.8, 0.5, 0.5)
    love.graphics.print("[Esc] Cancel", vp_w - 190, y)
end

--- Main draw dispatch — contains the love.draw body logic.
function draw.draw_frame(ctx, state)
    love.graphics.push()
    love.graphics.scale(ctx.UI_SCALE, ctx.UI_SCALE)

    -- Scenario selection: no board loaded yet
    if ctx.game_mode == ctx.PICK_SCENARIO then
        draw.draw_setup_hud(ctx)
        love.graphics.pop()
        return
    end

    local int = ctx.int

    -- Build tile color + terrain_id maps
    local tile_colors = {}
    local tile_ids = {}
    for _, tile in ipairs(state.terrain or {}) do
        local key = int(tile.col) .. "," .. int(tile.row)
        tile_colors[key] = ctx.parse_html_color(tile.color) or ctx.COLOR_FLAT
        tile_ids[key] = tile.terrain_id
    end

    -- Board-space drawing (push camera transform)
    local tx = ctx.board_origin_x + ctx.camera_offset_x
    local ty = ctx.board_origin_y + ctx.camera_offset_y
    love.graphics.push()
    love.graphics.translate(tx, ty)

    -- 1. Terrain hexes
    for col = 0, ctx.BOARD_COLS - 1 do
        for row = 0, ctx.BOARD_ROWS - 1 do
            local cx, cy = ctx.hex.to_pixel(col, row)
            local key = col .. "," .. row
            local c = tile_colors[key] or ctx.COLOR_FLAT
            local tid = tile_ids[key]
            ctx.assets.draw_terrain_hex(ctx.terrain_tiles, tid, cx, cy, ctx.hex.RADIUS, c, ctx.hex.polygon)
        end
    end

    -- 2. Reachable hex highlights
    if ctx.game_mode == ctx.PLAYING then
        love.graphics.setColor(1, 1, 0, 0.35)
        for _, cell in ipairs(ctx.reachable_cells) do
            local cx, cy = ctx.hex.to_pixel(cell.col, cell.row)
            love.graphics.polygon("fill", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
        end
    end

    -- 3. Selected unit outline (at ghost position if ghosting)
    if ctx.game_mode == ctx.PLAYING and ctx.selected_unit_id ~= -1 then
        if ctx.ghost_col ~= nil then
            local gx, gy = ctx.hex.to_pixel(ctx.ghost_col, ctx.ghost_row)
            love.graphics.setColor(1, 1, 1, 0.8)
            love.graphics.setLineWidth(2.5)
            love.graphics.polygon("line", ctx.hex.polygon(gx, gy, ctx.hex.RADIUS))
        else
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == ctx.selected_unit_id then
                    local cx, cy = ctx.hex.to_pixel(int(unit.col), int(unit.row))
                    love.graphics.setColor(1, 1, 1, 1)
                    love.graphics.setLineWidth(2.5)
                    love.graphics.polygon("line", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
                    break
                end
            end
        end
    end

    -- 4. Objective hex highlight
    if state.objective_col and state.objective_row then
        local ocol = int(state.objective_col)
        local orow = int(state.objective_row)
        local ox, oy = ctx.hex.to_pixel(ocol, orow)
        love.graphics.setColor(1.0, 0.85, 0.0, 0.9)
        love.graphics.setLineWidth(4.0)
        love.graphics.polygon("line", ctx.hex.polygon(ox, oy, ctx.hex.RADIUS))
        love.graphics.setColor(1.0, 0.85, 0.0, 0.3)
        love.graphics.polygon("fill", ctx.hex.polygon(ox, oy, ctx.hex.RADIUS * 0.3))
    end

    -- 5. Units
    draw.draw_units(ctx, state)

    -- 5b. Ghost unit rendering
    if ctx.ghost_col ~= nil then
        local gx, gy = ctx.hex.to_pixel(ctx.ghost_col, ctx.ghost_row)
        for _, unit in ipairs(state.units or {}) do
            if int(unit.id) == ctx.ghost_unit_id then
                local faction = int(unit.faction)
                local hp = int(unit.hp)
                local ghost_alpha = 0.5

                local anim_state = ctx.unit_anims[ctx.ghost_unit_id]
                if anim_state then
                    anim_state.facing = int(unit.faction) == 0 and "right" or "left"
                end

                local drawn = ctx.assets.draw_unit_sprite(ctx.unit_sprites, unit.def_id, gx, gy, ctx.hex.RADIUS, faction, ghost_alpha, ctx.FACTION_COLORS, anim_state)
                if not drawn then
                    if faction == 0 then
                        love.graphics.setColor(ctx.BLUE[1], ctx.BLUE[2], ctx.BLUE[3], ghost_alpha)
                    else
                        love.graphics.setColor(ctx.RED[1], ctx.RED[2], ctx.RED[3], ghost_alpha)
                    end
                    love.graphics.circle("fill", gx, gy, ctx.hex.RADIUS * 0.45)
                    local word = (unit.def_id or ""):match("^([^_]+)") or unit.def_id or ""
                    local abbrev = (word:sub(1, 1):upper() .. word:sub(2):lower()):sub(1, 7)
                    love.graphics.setColor(1, 1, 1, ghost_alpha)
                    love.graphics.setFont(ctx.fonts[14])
                    love.graphics.printf(abbrev, gx - 42, gy - 14, 84, "center")
                end

                love.graphics.setColor(1, 1, 1, ghost_alpha)
                love.graphics.setFont(ctx.fonts[18])
                love.graphics.print(tostring(hp), gx - 12, gy - 2)
                break
            end
        end

        -- Highlight attackable enemies
        for _, enemy in ipairs(ctx.ghost_attackable) do
            local ex, ey = ctx.hex.to_pixel(enemy.col, enemy.row)
            love.graphics.setColor(1, 0.4, 0.1, 0.9)
            love.graphics.setLineWidth(3)
            love.graphics.polygon("line", ctx.hex.polygon(ex, ey, ctx.hex.RADIUS))
        end
    end

    -- 6. Recruit-mode hex highlights
    if ctx.recruit_mode then
        for _, tile in ipairs(state.terrain or {}) do
            local tid = tile.terrain_id or ""
            local cx, cy = ctx.hex.to_pixel(int(tile.col), int(tile.row))
            if tid == "keep" then
                love.graphics.setColor(1.0, 0.75, 0.0, 0.7)
                love.graphics.polygon("fill", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
                love.graphics.setColor(1, 1, 0, 1)
                love.graphics.setLineWidth(3.0)
                love.graphics.polygon("line", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
            elseif tid == "castle" then
                love.graphics.setColor(0.0, 0.9, 0.9, 0.65)
                love.graphics.polygon("fill", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
                love.graphics.setColor(1, 1, 1, 1)
                love.graphics.setLineWidth(2.5)
                love.graphics.polygon("line", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
            end
        end
    end

    love.graphics.pop() -- back to screen space

    -- ── Screen-space UI ─────────────────────────────────────────────────

    if ctx.game_mode ~= ctx.PLAYING then
        draw.draw_setup_hud(ctx)
    else
        -- Win overlay
        if ctx.game_over then
            local vp_w, vp_h = ctx.get_viewport()
            local winner_name = ctx.winner_faction == 0 and "Blue" or "Red"
            local msg, sub_msg
            if ctx.winner_faction == 0 then
                if ctx.campaign_active then
                    if ctx.campaign_index + 1 < #ctx.campaign_data.scenarios then
                        msg = "Victory!"
                        sub_msg = "Press Enter for next battle"
                    else
                        msg = "Campaign Victory!"
                        sub_msg = "Press Enter to continue"
                    end
                else
                    msg = "Victory! " .. winner_name .. " wins!"
                    sub_msg = "Press Enter to continue"
                end
            else
                local max_t = state.max_turns
                local cur_t = int(state.turn or 1)
                if max_t and cur_t > int(max_t) then
                    msg = "Defeat — Turn limit reached!"
                else
                    msg = winner_name .. " wins!"
                end
                if ctx.campaign_active then
                    sub_msg = "Campaign over — Press Enter"
                else
                    sub_msg = "Press Enter to continue"
                end
            end
            love.graphics.setFont(ctx.fonts[32])
            love.graphics.setColor(1, 1, 0, 1)
            love.graphics.printf(msg, vp_w / 2 - 240, vp_h / 2 - 16, 480, "center")
            if sub_msg then
                love.graphics.setFont(ctx.fonts[14])
                love.graphics.setColor(0.83, 0.83, 0.83, 1)
                love.graphics.printf(sub_msg, vp_w / 2 - 240, vp_h / 2 + 24, 480, "center")
            end
        end

        -- HUD
        if not ctx.game_over then
            local faction = ctx.norrust.get_active_faction(ctx.engine)
            local faction_name = faction == 0 and "Blue" or "Red"
            local fc = faction == 0 and ctx.BLUE or ctx.RED
            local tod = ctx.norrust.get_time_of_day_name(ctx.engine)
            local gold_arr = state.gold or {0, 0}
            local gold = int(gold_arr[faction + 1] or 0)
            local turn = ctx.norrust.get_turn(ctx.engine)
            local turn_str
            if state.max_turns then
                turn_str = string.format("Turn %d / %d", turn, int(state.max_turns))
            else
                turn_str = string.format("Turn %d", turn)
            end
            local hud_text = string.format("%s  ·  %s  ·  %s's Turn  ·  %dg",
                turn_str, tod, faction_name, gold)
            love.graphics.setFont(ctx.fonts[14])
            love.graphics.setColor(fc[1], fc[2], fc[3])
            love.graphics.print(hud_text, 10, 6)
        end

        if ctx.combat_preview ~= nil then
            draw.draw_combat_preview(ctx)
        elseif ctx.recruit_mode then
            draw.draw_recruit_panel(ctx, state)
        elseif ctx.inspect_unit_id ~= -1 then
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == ctx.inspect_unit_id then
                    draw.draw_unit_panel(ctx, unit)
                    break
                end
            end
        elseif ctx.inspect_terrain then
            draw.draw_terrain_panel(ctx)
        end
    end

    love.graphics.pop()
end

return draw
