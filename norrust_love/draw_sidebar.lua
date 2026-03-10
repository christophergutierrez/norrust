-- draw_sidebar.lua — Right sidebar panels: unit stats, terrain info,
-- recruit panel, combat preview, dialogue, sidebar buttons

local common = require("draw_common")

local SIDEBAR_W     = common.SIDEBAR_W
local SIDEBAR_PAD   = common.SIDEBAR_PAD
local SIDEBAR_X_OFF = common.SIDEBAR_X_OFF
local C_GRAY        = common.C_GRAY
local C_GOLD        = common.C_GOLD
local C_WARM_TITLE  = common.C_WARM_TITLE
local C_WHITE       = common.C_WHITE
local C_YELLOW      = common.C_YELLOW
local MOVE_STATUS   = common.MOVE_STATUS

local draw_sidebar_bg = common.draw_sidebar_bg
local faction_color   = common.faction_color

local M = {}

--- Draw the recruit panel sidebar.
function M.draw_recruit_panel(ctx, state)
    local int = ctx.int
    local fonts = ctx.fonts
    local faction = ctx.norrust.get_active_faction(ctx.engine)
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local fc = faction_color(ctx, faction)
    local gold_arr = state.gold or {0, 0}
    local gold = int(gold_arr[faction + 1] or 0)

    -- Sidebar background
    draw_sidebar_bg(vp_w, vp_h)

    love.graphics.setFont(fonts[15])
    love.graphics.setColor(fc[1], fc[2], fc[3])
    love.graphics.print(string.format("RECRUIT — %dg", gold), vp_w - SIDEBAR_X_OFF, SIDEBAR_PAD)

    love.graphics.setFont(fonts[11])
    love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
    love.graphics.print("Leader must be on gold hex", vp_w - SIDEBAR_X_OFF, 30)
    love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
    love.graphics.print("Click adjacent blue hex", vp_w - SIDEBAR_X_OFF, 44)
    love.graphics.print("[R] Cancel", vp_w - SIDEBAR_X_OFF, 58)

    if ctx.recruit_error ~= "" then
        love.graphics.setColor(1, 0, 0, 1)
        love.graphics.print(ctx.recruit_error, vp_w - SIDEBAR_X_OFF, 72)
    end

    local idx = 0
    local y_start = 94

    -- Veterans first (free, from roster)
    local vets = ctx.recruit_veterans or {}
    for i, vet in ipairs(vets) do
        local y = y_start + (idx) * 20
        local label = string.format("[%d] [V] %s (free)", idx + 1, vet.def_id)
        if idx == ctx.selected_recruit_idx then
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
        else
            love.graphics.setColor(0.5, 1, 0.5, 1)
        end
        love.graphics.print(label, vp_w - SIDEBAR_X_OFF, y)
        idx = idx + 1
    end

    -- Normal recruits
    for i, def_id in ipairs(ctx.recruit_palette) do
        local cost = ctx.norrust.get_unit_cost(ctx.engine, def_id)
        local y = y_start + (idx) * 20
        local label = string.format("[%d] %s (%dg)", idx + 1, def_id, cost)
        if idx == ctx.selected_recruit_idx then
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
        else
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
        end
        love.graphics.print(label, vp_w - SIDEBAR_X_OFF, y)
        idx = idx + 1
    end
end

--- Draw the unit inspection panel sidebar.
function M.draw_unit_panel(ctx, unit)
    local int = ctx.int
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h

    draw_sidebar_bg(vp_w, vp_h, 0.75)

    local faction = int(unit.faction)
    local faction_name = faction == 0 and "Blue" or "Red"
    local fc = faction_color(ctx, faction)

    local y = SIDEBAR_PAD

    -- Portrait
    local portrait_h = ctx.assets.draw_portrait(ctx.unit_sprites, unit.def_id, vp_w - 195, y, 180, 120)
    if portrait_h > 0 then
        y = y + portrait_h + 6
    end

    -- Unit name + faction
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(fc[1], fc[2], fc[3])
    love.graphics.print(unit.def_id or "", vp_w - SIDEBAR_X_OFF, y)
    y = y + 18
    love.graphics.setFont(fonts[11])
    love.graphics.print(faction_name, vp_w - SIDEBAR_X_OFF, y)
    y = y + 14
    if unit.level then
        love.graphics.setColor(0.8, 0.8, 0.8)
        love.graphics.print("Level " .. int(unit.level), vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
    end
    y = y + 4

    -- HP
    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
    love.graphics.setFont(fonts[12])
    love.graphics.print(string.format("HP: %d / %d", int(unit.hp), int(unit.max_hp)), vp_w - SIDEBAR_X_OFF, y)
    y = y + 16

    -- XP
    if unit.xp_needed and int(unit.xp_needed) > 0 then
        love.graphics.print(string.format("XP: %d / %d", int(unit.xp), int(unit.xp_needed)), vp_w - SIDEBAR_X_OFF, y)
        y = y + 16
    end
    if unit.advancement_pending then
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
        love.graphics.print("Ready to advance! [A]", vp_w - SIDEBAR_X_OFF, y)
        y = y + 16
    end

    -- Status effects
    if unit.poisoned then
        love.graphics.setColor(0.2, 0.9, 0.2)
        love.graphics.print("Poisoned", vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
    end
    if unit.slowed then
        love.graphics.setColor(0.3, 0.6, 1.0)
        love.graphics.print("Slowed", vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
    end

    -- Movement
    local key = (unit.moved and 1 or 0) + (unit.attacked and 2 or 0)
    local move_status = MOVE_STATUS[key]
    love.graphics.print(string.format("Move: %d%s", int(unit.movement), move_status), vp_w - SIDEBAR_X_OFF, y)
    y = y + 20

    -- Attacks
    local attacks = unit.attacks or {}
    if #attacks > 0 then
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
        love.graphics.print("── Attacks ──", vp_w - SIDEBAR_X_OFF, y)
        y = y + 15
        for _, atk in ipairs(attacks) do
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            love.graphics.setFont(fonts[12])
            love.graphics.print(atk.name or "", vp_w - SIDEBAR_X_OFF, y)
            y = y + 14
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
            love.graphics.setFont(fonts[11])
            love.graphics.print(string.format("  %dx%d %s", int(atk.damage), int(atk.strikes), atk.range or ""), vp_w - SIDEBAR_X_OFF, y)
            y = y + 15
            local specials = atk.specials
            if specials and #specials > 0 then
                love.graphics.setColor(0.7, 0.85, 1.0)
                love.graphics.print("  (" .. table.concat(specials, ", ") .. ")", vp_w - SIDEBAR_X_OFF, y)
                y = y + 14
            end
        end
    end

    -- Abilities
    local abilities = unit.abilities or {}
    if #abilities > 0 then
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
        love.graphics.print("── Abilities ──", vp_w - SIDEBAR_X_OFF, y)
        y = y + 15
        for _, ab in ipairs(abilities) do
            love.graphics.setColor(0.6, 1.0, 0.6)
            love.graphics.print(ab, vp_w - SIDEBAR_X_OFF, y)
            y = y + 14
        end
    end
end

--- Draw the terrain inspection panel sidebar.
function M.draw_terrain_panel(ctx)
    local fonts = ctx.fonts
    local int = ctx.int
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local t = ctx.inspect_terrain

    draw_sidebar_bg(vp_w, vp_h, 0.75)

    local y = SIDEBAR_PAD

    -- Terrain name
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(C_WARM_TITLE[1], C_WARM_TITLE[2], C_WARM_TITLE[3])
    love.graphics.print(t.terrain_id or "", vp_w - SIDEBAR_X_OFF, y)
    y = y + 22

    -- Coordinates
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.6, 0.6, 0.6)
    love.graphics.print(string.format("(%d, %d)", t.col, t.row), vp_w - SIDEBAR_X_OFF, y)
    y = y + 20

    -- Base stats
    love.graphics.setFont(fonts[12])
    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
    love.graphics.print(string.format("Defense: %d%%", t.defense), vp_w - SIDEBAR_X_OFF, y)
    y = y + 16
    love.graphics.print(string.format("Move cost: %d", t.movement_cost), vp_w - SIDEBAR_X_OFF, y)
    y = y + 16

    if t.healing and t.healing > 0 then
        love.graphics.setColor(0.4, 1.0, 0.4)
        love.graphics.print(string.format("Healing: +%d HP", t.healing), vp_w - SIDEBAR_X_OFF, y)
        y = y + 16
        if t.owner and t.owner >= 0 then
            local fc = faction_color(ctx, t.owner)
            love.graphics.setColor(fc[1], fc[2], fc[3])
            love.graphics.print(t.owner == 0 and "Owner: Blue" or "Owner: Red", vp_w - SIDEBAR_X_OFF, y)
            y = y + 16
        end
    end

    -- Unit-specific stats
    if t.unit_defense then
        y = y + 8
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
        love.graphics.print("── Unit on terrain ──", vp_w - SIDEBAR_X_OFF, y)
        y = y + 15
        love.graphics.setFont(fonts[12])
        love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
        love.graphics.print(string.format("Eff. defense: %d%%", t.unit_defense), vp_w - SIDEBAR_X_OFF, y)
        y = y + 16
        love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
        love.graphics.print(string.format("Eff. move cost: %d", t.unit_move_cost), vp_w - SIDEBAR_X_OFF, y)
    end
end

--- Draw the narrator dialogue panel in the right sidebar.
function M.draw_dialogue_panel(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h

    draw_sidebar_bg(vp_w, vp_h, 0.75)

    local y = SIDEBAR_PAD

    -- Title
    love.graphics.setFont(fonts[13])
    love.graphics.setColor(C_WARM_TITLE[1], C_WARM_TITLE[2], C_WARM_TITLE[3])
    love.graphics.print("Narrator", vp_w - SIDEBAR_X_OFF, y)
    y = y + 20

    -- Separator
    love.graphics.setColor(0.5, 0.5, 0.5, 0.6)
    love.graphics.line(vp_w - SIDEBAR_X_OFF, y, vp_w - 10, y)
    y = y + 8

    -- Dialogue entries
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.85, 0.85, 0.85)
    for _, entry in ipairs(ctx.active_dialogue) do
        love.graphics.printf(entry.text, vp_w - SIDEBAR_X_OFF, y, 180, "left")
        local _, lines = fonts[11]:getWrap(entry.text, 180)
        y = y + #lines * fonts[11]:getHeight() + 10
    end
end

--- Draw the dialogue history overlay panel.
function M.draw_dialogue_history(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local panel_x = vp_w - SIDEBAR_W
    local panel_w = SIDEBAR_W
    local text_w = 180
    local pad = 10

    draw_sidebar_bg(vp_w, vp_h, 0.85)

    local y = SIDEBAR_PAD

    -- Title
    love.graphics.setFont(fonts[13])
    love.graphics.setColor(C_WARM_TITLE[1], C_WARM_TITLE[2], C_WARM_TITLE[3])
    love.graphics.print("Dialogue History", panel_x + pad, y)
    y = y + 20

    -- Separator
    love.graphics.setColor(0.5, 0.5, 0.5, 0.6)
    love.graphics.line(panel_x + pad, y, vp_w - pad, y)
    y = y + 8

    local header_h = y

    -- Clip content area
    local sx, sy = (panel_x + pad) * ctx.UI_SCALE, header_h * ctx.UI_SCALE
    local sw, sh = text_w * ctx.UI_SCALE, (vp_h - header_h - 20) * ctx.UI_SCALE
    love.graphics.setScissor(sx, sy, sw, sh)

    -- Apply scroll offset
    y = y - (ctx.history_scroll or 0)

    -- Render entries newest-first
    local font11 = fonts[11]
    local font9 = fonts[9]
    local line_h = font11:getHeight()
    for i = #ctx.dialogue_history, 1, -1 do
        local entry = ctx.dialogue_history[i]

        -- Turn label
        love.graphics.setFont(font9)
        love.graphics.setColor(0.6, 0.6, 0.5)
        love.graphics.print(string.format("Turn %d", entry.turn), panel_x + pad, y)
        y = y + font9:getHeight() + 2

        -- Text
        love.graphics.setFont(font11)
        love.graphics.setColor(0.85, 0.85, 0.85)
        love.graphics.printf(entry.text, panel_x + pad, y, text_w, "left")
        local _, lines = font11:getWrap(entry.text, text_w)
        y = y + #lines * line_h + 12
    end

    love.graphics.setScissor()

    -- Hint at bottom
    love.graphics.setFont(font9)
    love.graphics.setColor(0.5, 0.5, 0.5)
    love.graphics.printf("[H] Close  [Scroll] Navigate", panel_x + pad, vp_h - 16, text_w, "center")
end

--- Draw the combat preview panel sidebar.
function M.draw_combat_preview(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local p = ctx.combat_preview

    draw_sidebar_bg(vp_w, vp_h, 0.85)

    local y = SIDEBAR_PAD

    -- Header
    love.graphics.setFont(fonts[15])
    love.graphics.setColor(1.0, 0.9, 0.3)
    love.graphics.print("COMBAT PREVIEW", vp_w - SIDEBAR_X_OFF, y)
    y = y + 18
    local tod = ctx.norrust.get_time_of_day_name(ctx.engine)
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.7, 0.7, 0.9)
    love.graphics.print("Time: " .. (tod or "?"), vp_w - SIDEBAR_X_OFF, y)
    y = y + 16

    -- Attacker section
    love.graphics.setFont(fonts[12])
    love.graphics.setColor(0.5, 0.8, 1.0)
    love.graphics.print("── Attacker ──", vp_w - SIDEBAR_X_OFF, y)
    y = y + 16

    love.graphics.setColor(0.6, 0.8, 0.6)
    love.graphics.print(string.format("Terrain: %d%% def", p.attacker_terrain_defense or 0), vp_w - SIDEBAR_X_OFF, y)
    y = y + 14

    love.graphics.setColor(1, 1, 1)
    love.graphics.print(string.format("%s", p.attacker_attack_name or "?"), vp_w - SIDEBAR_X_OFF, y)
    y = y + 14
    love.graphics.print(string.format("%dx%d  (max %d)",
        p.attacker_damage_per_hit or 0, p.attacker_strikes or 0,
        p.attacker_damage_max or 0), vp_w - SIDEBAR_X_OFF, y)
    y = y + 14
    love.graphics.print(string.format("Hit: %d%%", p.attacker_hit_pct or 0), vp_w - SIDEBAR_X_OFF, y)
    y = y + 14

    love.graphics.setColor(0.9, 0.9, 0.9)
    love.graphics.print(string.format("Dmg: %d - %.1f - %d",
        p.attacker_damage_min or 0, p.attacker_damage_mean or 0, p.attacker_damage_max or 0), vp_w - SIDEBAR_X_OFF, y)
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
    love.graphics.print(string.format("Kill: %.0f%%", ak), vp_w - SIDEBAR_X_OFF, y)
    y = y + 14

    love.graphics.setColor(0.6, 0.6, 0.6)
    love.graphics.print(string.format("Target HP: %d", p.defender_hp or 0), vp_w - SIDEBAR_X_OFF, y)
    y = y + 20

    -- Defender retaliation section
    love.graphics.setFont(fonts[12])
    love.graphics.setColor(1.0, 0.5, 0.3)
    love.graphics.print("── Retaliation ──", vp_w - SIDEBAR_X_OFF, y)
    y = y + 16

    love.graphics.setColor(0.6, 0.8, 0.6)
    love.graphics.print(string.format("Terrain: %d%% def", p.defender_terrain_defense or 0), vp_w - SIDEBAR_X_OFF, y)
    y = y + 14

    local def_name = p.defender_attack_name or "none"
    if def_name == "none" then
        love.graphics.setColor(0.5, 0.5, 0.5)
        love.graphics.print("No retaliation", vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
    else
        love.graphics.setColor(1, 1, 1)
        love.graphics.print(string.format("%s", def_name), vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
        love.graphics.print(string.format("%dx%d  (max %d)",
            p.defender_damage_per_hit or 0, p.defender_strikes or 0,
            p.defender_damage_max or 0), vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
        love.graphics.print(string.format("Hit: %d%%", p.defender_hit_pct or 0), vp_w - SIDEBAR_X_OFF, y)
        y = y + 14

        love.graphics.setColor(0.9, 0.9, 0.9)
        love.graphics.print(string.format("Dmg: %d - %.1f - %d",
            p.defender_damage_min or 0, p.defender_damage_mean or 0, p.defender_damage_max or 0), vp_w - SIDEBAR_X_OFF, y)
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
        love.graphics.print(string.format("Kill: %.0f%%", dk), vp_w - SIDEBAR_X_OFF, y)
        y = y + 14

        love.graphics.setColor(0.6, 0.6, 0.6)
        love.graphics.print(string.format("Your HP: %d", p.attacker_hp or 0), vp_w - SIDEBAR_X_OFF, y)
        y = y + 14
    end

    -- Controls hint
    y = y + 12
    love.graphics.setFont(fonts[11])
    love.graphics.setColor(0.5, 0.8, 0.5)
    love.graphics.print("[Enter] Attack", vp_w - SIDEBAR_X_OFF, y)
    y = y + 14
    love.graphics.setColor(0.8, 0.5, 0.5)
    love.graphics.print("[Esc] Cancel", vp_w - SIDEBAR_X_OFF, y)
end

--- Draw clickable buttons at the bottom of the sidebar.
function M.draw_sidebar_buttons(ctx)
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local sb_x = vp_w - SIDEBAR_W
    local btn_w = 180
    local btn_h = 32
    local btn_x = sb_x + SIDEBAR_PAD
    local gap = 8
    local bottom_y = vp_h - SIDEBAR_PAD

    -- Initialize buttons table for click detection
    ctx.buttons = {}

    -- Help button (always visible, small)
    local help_y = bottom_y - btn_h
    ctx.buttons.help = {x = btn_x, y = help_y, w = btn_w, h = btn_h}
    love.graphics.setColor(0.3, 0.3, 0.35, 0.9)
    love.graphics.rectangle("fill", btn_x, help_y, btn_w, btn_h, 4, 4)
    love.graphics.setColor(0.7, 0.7, 0.7, 1)
    love.graphics.rectangle("line", btn_x, help_y, btn_w, btn_h, 4, 4)
    love.graphics.setFont(ctx.fonts[13])
    love.graphics.setColor(0.9, 0.9, 0.9, 1)
    love.graphics.printf("?  Help", btn_x, help_y + 8, btn_w, "center")

    if not ctx.game_over then
        -- Exit button (visible in all board modes: setup, faction pick, playing)
        local exit_y = help_y - btn_h - gap
        ctx.buttons.exit = {x = btn_x, y = exit_y, w = btn_w, h = btn_h}
        if ctx.exit_confirm then
            love.graphics.setColor(0.5, 0.2, 0.2, 0.95)
            love.graphics.rectangle("fill", btn_x, exit_y, btn_w, btn_h, 4, 4)
            love.graphics.setColor(1, 0.4, 0.4, 1)
            love.graphics.rectangle("line", btn_x, exit_y, btn_w, btn_h, 4, 4)
            love.graphics.setFont(ctx.fonts[13])
            love.graphics.setColor(1, 0.9, 0.9, 1)
            love.graphics.printf("Save? Y / N / Esc", btn_x, exit_y + 8, btn_w, "center")
        else
            love.graphics.setColor(0.35, 0.15, 0.15, 0.9)
            love.graphics.rectangle("fill", btn_x, exit_y, btn_w, btn_h, 4, 4)
            love.graphics.setColor(0.6, 0.3, 0.3, 1)
            love.graphics.rectangle("line", btn_x, exit_y, btn_w, btn_h, 4, 4)
            love.graphics.setFont(ctx.fonts[13])
            love.graphics.setColor(0.9, 0.7, 0.7, 1)
            love.graphics.printf("Exit", btn_x, exit_y + 8, btn_w, "center")
        end

        if ctx.game_mode == ctx.PLAYING then
            local faction = ctx.norrust.get_active_faction(ctx.engine)
            local fc = faction_color(ctx, faction)

            -- Recruit button
            local recruit_y = exit_y - btn_h - gap
            ctx.buttons.recruit = {x = btn_x, y = recruit_y, w = btn_w, h = btn_h}
            love.graphics.setColor(0.2, 0.35, 0.2, 0.9)
            love.graphics.rectangle("fill", btn_x, recruit_y, btn_w, btn_h, 4, 4)
            love.graphics.setColor(0.4, 0.7, 0.4, 1)
            love.graphics.rectangle("line", btn_x, recruit_y, btn_w, btn_h, 4, 4)
            love.graphics.setFont(ctx.fonts[13])
            love.graphics.setColor(0.85, 1, 0.85, 1)
            love.graphics.printf("R  Recruit", btn_x, recruit_y + 8, btn_w, "center")

            -- End Turn button
            local end_y = recruit_y - btn_h - gap
            ctx.buttons.end_turn = {x = btn_x, y = end_y, w = btn_w, h = btn_h}
            love.graphics.setColor(fc[1] * 0.5, fc[2] * 0.5, fc[3] * 0.5, 0.9)
            love.graphics.rectangle("fill", btn_x, end_y, btn_w, btn_h, 4, 4)
            love.graphics.setColor(fc[1], fc[2], fc[3], 1)
            love.graphics.rectangle("line", btn_x, end_y, btn_w, btn_h, 4, 4)
            love.graphics.setFont(ctx.fonts[13])
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
            love.graphics.printf("E  End Turn", btn_x, end_y + 8, btn_w, "center")
        end
    end
end

--- Draw the advancement branch choice panel.
function M.draw_advance_choice(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local ac = ctx.advance_choice

    draw_sidebar_bg(vp_w, vp_h)

    love.graphics.setFont(fonts[15])
    love.graphics.setColor(C_WARM_TITLE[1], C_WARM_TITLE[2], C_WARM_TITLE[3])
    love.graphics.print("ADVANCE UNIT", vp_w - SIDEBAR_X_OFF, SIDEBAR_PAD)

    love.graphics.setFont(fonts[11])
    love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
    love.graphics.print("Choose advancement:", vp_w - SIDEBAR_X_OFF, 30)
    love.graphics.print("[1-" .. #ac.options .. "] or arrows+enter", vp_w - SIDEBAR_X_OFF, 44)
    love.graphics.print("[Esc] Cancel", vp_w - SIDEBAR_X_OFF, 58)

    for i, opt in ipairs(ac.options) do
        local y = 80 + (i - 1) * 24
        if i == ac.selected then
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            love.graphics.print("> ", vp_w - SIDEBAR_X_OFF, y)
        else
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
        end
        love.graphics.print(string.format("[%d] %s", i, opt.name), vp_w - SIDEBAR_X_OFF + 12, y)
    end
end

return M
