-- draw_hud.lua — HUD overlays: game-over screen, turn/faction bar, help overlay

local common = require("draw_common")

local SIDEBAR_W    = common.SIDEBAR_W
local C_GRAY       = common.C_GRAY
local C_WHITE      = common.C_WHITE
local C_YELLOW     = common.C_YELLOW

local faction_color = common.faction_color

local M = {}

--- Draw the game-over overlay (victory/defeat message).
function M.draw_game_over(ctx, state)
    local int = ctx.int
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
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
    love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
    love.graphics.printf(msg, vp_w / 2 - 240, vp_h / 2 - 16, 480, "center")
    if sub_msg then
        love.graphics.setFont(ctx.fonts[14])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
        love.graphics.printf(sub_msg, vp_w / 2 - 240, vp_h / 2 + 24, 480, "center")
    end
end

--- Draw the top-left HUD bar (turn, time of day, faction, gold).
function M.draw_hud_bar(ctx, state)
    local int = ctx.int
    local faction = ctx.norrust.get_active_faction(ctx.engine)
    local faction_name = faction == 0 and "Blue" or "Red"
    local fc = faction_color(ctx, faction)
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

--- Draw a semi-transparent help overlay showing all keybindings.
function M.draw_help_overlay(ctx)
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h
    local panel_w = SIDEBAR_W
    local board_w = vp_w - panel_w

    -- Semi-transparent background over board area
    love.graphics.setColor(0, 0, 0, 0.85)
    love.graphics.rectangle("fill", 0, 0, board_w, vp_h)

    -- Title
    love.graphics.setFont(ctx.fonts[32])
    love.graphics.setColor(1, 1, 0.7, 1)
    love.graphics.printf("Controls", 0, 30, board_w, "center")

    local col_w = math.floor(board_w / 3)
    local y_start = 90
    local line_h = 24

    local function draw_section(x, title, bindings)
        love.graphics.setFont(ctx.fonts[15])
        love.graphics.setColor(0.9, 0.8, 0.3, 1)
        love.graphics.print(title, x + 20, y_start)
        love.graphics.setFont(ctx.fonts[13])
        for i, b in ipairs(bindings) do
            local y = y_start + 30 + (i - 1) * line_h
            love.graphics.setColor(0.6, 0.85, 1.0, 1)
            love.graphics.print(b[1], x + 20, y)
            love.graphics.setColor(0.85, 0.85, 0.85, 1)
            love.graphics.print(b[2], x + 100, y)
        end
    end

    draw_section(0, "Global", {
        {"?", "Toggle this help"},
        {"M", "Mute / unmute"},
        {"- / =", "Volume down / up"},
        {"F5", "Save game"},
        {"F9", "Load last save"},
        {"Scroll", "Zoom in / out"},
        {"Drag", "Pan the board"},
    })

    draw_section(col_w, "Gameplay", {
        {"Click", "Select unit"},
        {"Click", "Move / ghost"},
        {"Right-click", "Inspect terrain"},
        {"Enter", "Confirm move / attack"},
        {"Escape", "Cancel selection"},
        {"E", "End turn"},
        {"R", "Recruit units"},
        {"A", "Advance unit (when ready)"},
        {"H", "Dialogue history"},
        {"P", "Toggle agent server"},
    })

    draw_section(col_w * 2, "Menu", {
        {"1-9", "Select scenario"},
        {"C", "Start campaign"},
    })

    -- Footer
    love.graphics.setFont(ctx.fonts[11])
    love.graphics.setColor(0.5, 0.5, 0.5, 1)
    love.graphics.printf("Press ? to close  ·  Any key dismisses", 0, vp_h - 30, board_w, "center")
end

return M
