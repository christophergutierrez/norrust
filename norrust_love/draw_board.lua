-- draw_board.lua — Board rendering: terrain tiles, hex highlights, units,
-- path visualization, ghost rendering, recruit hex highlights

local common = require("draw_common")

local C_WHITE  = common.C_WHITE
local C_GOLD   = common.C_GOLD
local C_YELLOW = common.C_YELLOW

local M = {}

--- Draw all units on the board.
function M.draw_units(ctx, state)
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

        -- Override position for movement/combat animation
        local cx, cy
        if ctx.move_anim and ctx.move_anim.uid == uid then
            local ma = ctx.move_anim
            local a = ma.path[ma.seg]
            local b = ma.path[ma.seg + 1]
            local ax, ay = ctx.hex.to_pixel(a.col, a.row)
            local bx, by = ctx.hex.to_pixel(b.col, b.row)
            cx = ax + (bx - ax) * ma.t
            cy = ay + (by - ay) * ma.t
        elseif ctx.combat_slide and ctx.combat_slide.uid == uid then
            local cs = ctx.combat_slide
            cx = cs.start_x + (cs.target_x - cs.start_x) * cs.t
            cy = cs.start_y + (cs.target_y - cs.start_y) * cs.t
        else
            cx, cy = ctx.hex.to_pixel(col, row)
        end
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
            common.draw_unit_fallback(ctx, cx, cy, faction, alpha, unit.def_id, hp)
        else
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
            love.graphics.setFont(fonts[18])
            love.graphics.print(tostring(hp), cx - 12, cy - 2)
        end

        -- Advancement ring
        if unit.advancement_pending then
            love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
            love.graphics.setLineWidth(3.5)
            love.graphics.arc("line", "open", cx, cy, ctx.hex.RADIUS * 0.52, 0, math.pi * 2, 24)
        end

        -- XP text
        if unit.xp_needed and int(unit.xp_needed) > 0 then
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
            love.graphics.setFont(fonts[14])
            love.graphics.print(int(unit.xp) .. "/" .. int(unit.xp_needed), cx - 15, cy + 14)
        end

        -- Status effect indicators
        local r = ctx.hex.RADIUS * 0.35
        if unit.poisoned then
            love.graphics.setColor(0.2, 0.9, 0.2, 0.9)
            love.graphics.circle("fill", cx - r, cy + r, 4)
        end
        if unit.slowed then
            love.graphics.setColor(0.3, 0.6, 1.0, 0.9)
            love.graphics.circle("fill", cx + r, cy + r, 4)
        end
        ::continue::
    end

    -- Draw dying units (derived death: idle sprite tilts + fades)
    for uid, info in pairs(ctx.dying_units or {}) do
        local anim_state = ctx.unit_anims[uid]
        if not anim_state then goto continue_dying end

        local key = info.def_id and info.def_id:lower():gsub(" ", "_")
        local entry = key and ctx.unit_sprites[key]
        if not entry or not entry.anims then goto continue_dying end

        local img, quad, fw, fh = ctx.anim_module.get_quad(anim_state, entry.anims)
        if not img or not quad then goto continue_dying end

        local cx, cy = ctx.hex.to_pixel(info.col, info.row)
        local faction = info.faction
        if not faction or not ctx.FACTION_COLORS[faction] then goto continue_dying end
        local flip = faction == 0 and 1 or -1

        -- Progress: 0.0 (just died) to 1.0 (fully gone)
        local progress = 1.0 - (info.timer / (info.duration or 1.0))
        local angle = progress * math.pi / 2  -- tilt 0° to 90°
        local alpha = 1.0 - progress           -- fade 1.0 to 0.0

        -- Faction-colored underlay circle (fading)
        local fc = ctx.FACTION_COLORS[faction]
        love.graphics.setColor(fc[1], fc[2], fc[3], alpha)
        love.graphics.circle("fill", cx, cy, ctx.hex.RADIUS * 0.45)

        -- Draw idle sprite with rotation + fade
        local target_size = ctx.hex.RADIUS * 1.4
        local scale = math.min(target_size / fw, target_size / fh)
        love.graphics.setColor(1, 1, 1, alpha)
        love.graphics.draw(img, quad, cx, cy, angle, scale * flip, scale, fw / 2, fh / 2)

        ::continue_dying::
    end

    -- Clean up stale animation states for dead/removed units (skip dying units)
    for uid in pairs(ctx.unit_anims) do
        if not alive_ids[uid] and not (ctx.dying_units and ctx.dying_units[uid]) then
            ctx.unit_anims[uid] = nil
        end
    end
end

--- Draw terrain hexes, highlights, units, paths, ghosts, and recruit hexes.
-- Called from draw_frame with the camera transform already applied.
function M.draw_board(ctx, state)
    local int = ctx.int
    local tile_colors = ctx.tile_color_cache or {}
    local tile_ids = ctx.tile_ids
    local village_owners = ctx.village_owners
    local faction_color = common.faction_color

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

    -- 1b. Village ownership borders
    love.graphics.setLineWidth(2.5)
    for key, owner in pairs(village_owners) do
        local col_str, row_str = key:match("^(%d+),(%d+)$")
        local cx, cy = ctx.hex.to_pixel(tonumber(col_str), tonumber(row_str))
        local fc = faction_color(ctx, owner)
        love.graphics.setColor(fc[1], fc[2], fc[3], 0.7)
        love.graphics.polygon("line", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS * 0.85))
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
                    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
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
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 0.9)
        love.graphics.setLineWidth(4.0)
        love.graphics.polygon("line", ctx.hex.polygon(ox, oy, ctx.hex.RADIUS))
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 0.3)
        love.graphics.polygon("fill", ctx.hex.polygon(ox, oy, ctx.hex.RADIUS * 0.3))
    end

    -- 5. Units
    M.draw_units(ctx, state)

    -- 5b. Ghost path visualization
    if ctx.ghost_col ~= nil and ctx.ghost_path and #ctx.ghost_path > 2 then
        -- Draw path hexes (skip first=start and last=destination)
        for i = 2, #ctx.ghost_path - 1 do
            local p = ctx.ghost_path[i]
            local px, py = ctx.hex.to_pixel(p.col, p.row)
            love.graphics.setColor(1, 1, 1, 0.15)
            love.graphics.polygon("fill", ctx.hex.polygon(px, py, ctx.hex.RADIUS * 0.85))
        end
        -- Draw connecting line through all path hexes
        if #ctx.ghost_path >= 2 then
            love.graphics.setColor(1, 1, 1, 0.4)
            love.graphics.setLineWidth(3)
            for i = 1, #ctx.ghost_path - 1 do
                local a = ctx.ghost_path[i]
                local b = ctx.ghost_path[i + 1]
                local ax, ay = ctx.hex.to_pixel(a.col, a.row)
                local bx, by = ctx.hex.to_pixel(b.col, b.row)
                love.graphics.line(ax, ay, bx, by)
            end
        end
    end

    -- 5c. Ghost unit rendering
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
                    common.draw_unit_fallback(ctx, gx, gy, faction, ghost_alpha, unit.def_id, hp)
                else
                    love.graphics.setColor(1, 1, 1, ghost_alpha)
                    love.graphics.setFont(ctx.fonts[18])
                    love.graphics.print(tostring(hp), gx - 12, gy - 2)
                end
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

    -- 6. Recruit-mode hex highlights (only castles adjacent to a keep)
    if ctx.recruit_mode then
        -- Collect keep positions
        local keeps = {}
        for _, tile in ipairs(state.terrain or {}) do
            if (tile.terrain_id or "") == "keep" then
                keeps[#keeps + 1] = {col = int(tile.col), row = int(tile.row)}
            end
        end
        for _, tile in ipairs(state.terrain or {}) do
            local tid = tile.terrain_id or ""
            local tc, tr = int(tile.col), int(tile.row)
            local cx, cy = ctx.hex.to_pixel(tc, tr)
            if tid == "keep" then
                love.graphics.setColor(1.0, 0.75, 0.0, 0.7)
                love.graphics.polygon("fill", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
                love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
                love.graphics.setLineWidth(3.0)
                love.graphics.polygon("line", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
            elseif tid == "castle" then
                -- Only highlight castles adjacent to a keep (hex distance 1)
                local adjacent = false
                for _, k in ipairs(keeps) do
                    if ctx.hex.distance(tc, tr, k.col, k.row) == 1 then
                        adjacent = true; break
                    end
                end
                if adjacent then
                    love.graphics.setColor(0.0, 0.9, 0.9, 0.65)
                    love.graphics.polygon("fill", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
                    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
                    love.graphics.setLineWidth(2.5)
                    love.graphics.polygon("line", ctx.hex.polygon(cx, cy, ctx.hex.RADIUS))
                end
            end
        end
    end
end

return M
