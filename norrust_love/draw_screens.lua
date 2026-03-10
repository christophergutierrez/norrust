-- draw_screens.lua — Non-gameplay screens: scenario select, faction pick,
-- setup/leader placement, save list, deploy veterans

local common = require("draw_common")

local SIDEBAR_W     = common.SIDEBAR_W
local SIDEBAR_PAD   = common.SIDEBAR_PAD
local SIDEBAR_X_OFF = common.SIDEBAR_X_OFF
local C_GRAY        = common.C_GRAY
local C_GOLD        = common.C_GOLD
local C_WARM_TITLE  = common.C_WARM_TITLE
local C_WHITE       = common.C_WHITE
local C_YELLOW      = common.C_YELLOW

local draw_sidebar_bg = common.draw_sidebar_bg

local M = {}

--- Draw the setup HUD (scenario selection, faction picking, leader placement).
function M.draw_setup_hud(ctx)
    local int = ctx.int
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.vp_w, ctx.vp_h

    -- Scenario selection screen
    if ctx.game_mode == ctx.PICK_SCENARIO then
        love.graphics.setFont(fonts[18])
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
        love.graphics.printf("The Clash for Norrust", 0, vp_h / 2 - 60, vp_w, "center")

        love.graphics.setFont(fonts[14])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
        love.graphics.printf("Select a scenario:", 0, vp_h / 2 - 20, vp_w, "center")

        for i, sc in ipairs(ctx.SCENARIOS) do
            love.graphics.setFont(fonts[15])
            love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
            love.graphics.printf(string.format("[%d] %s", i, sc.name), 0, vp_h / 2 + 10 + (i - 1) * 28, vp_w, "center")
        end

        -- Campaign section
        local cy = vp_h / 2 + 10 + #ctx.SCENARIOS * 28 + 10
        love.graphics.setFont(fonts[14])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
        love.graphics.printf("Campaigns:", 0, cy, vp_w, "center")
        cy = cy + 22
        for i, camp in ipairs(ctx.CAMPAIGNS) do
            love.graphics.setFont(fonts[15])
            love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
            love.graphics.printf(string.format("[C] %s", camp.name), 0, cy + (i - 1) * 28, vp_w, "center")
        end

        -- Load game hint
        local ly = cy + #ctx.CAMPAIGNS * 28 + 16
        love.graphics.setFont(fonts[14])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
        love.graphics.printf("[L] Load Game", 0, ly, vp_w, "center")

        -- Quit hint
        love.graphics.printf("[Q] Quit", 0, ly + 24, vp_w, "center")
        return
    end

    -- Save management screen
    if ctx.game_mode == ctx.LOAD_SAVE then
        love.graphics.setFont(fonts[18])
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
        love.graphics.printf("Load Game", 0, 30, vp_w, "center")

        local saves = ctx.save_list or {}
        if #saves == 0 then
            love.graphics.setFont(fonts[14])
            love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
            love.graphics.printf("No save files found", 0, vp_h / 2 - 10, vp_w, "center")
        else
            local max_visible = math.floor((vp_h - 120) / 32)
            local idx = ctx.save_idx or 1
            -- Scroll window: keep selected item visible
            local scroll_top = 1
            if idx > max_visible then
                scroll_top = idx - max_visible + 1
            end
            local scroll_end = math.min(#saves, scroll_top + max_visible - 1)

            for i = scroll_top, scroll_end do
                local s = saves[i]
                local y = 70 + (i - scroll_top) * 32
                local primary, secondary
                if s.display_name then
                    primary = s.display_name
                    secondary = s.date_str .. "  —  " .. s.scenario .. "  —  Turn " .. s.turn
                    if s.campaign then secondary = secondary .. "  [" .. s.campaign .. "]" end
                else
                    primary = s.date_str .. "  —  " .. s.scenario .. "  —  Turn " .. s.turn
                    if s.campaign then primary = primary .. "  [" .. s.campaign .. "]" end
                    secondary = nil
                end

                if i == idx then
                    love.graphics.setFont(fonts[13])
                    love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
                    love.graphics.printf("> " .. primary, 20, y, vp_w - 40, "left")
                    if secondary then
                        love.graphics.setFont(fonts[11])
                        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 0.8)
                        love.graphics.printf("    " .. secondary, 20, y + 14, vp_w - 40, "left")
                    end
                else
                    love.graphics.setFont(fonts[13])
                    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
                    love.graphics.printf("  " .. primary, 20, y, vp_w - 40, "left")
                    if secondary then
                        love.graphics.setFont(fonts[11])
                        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 0.6)
                        love.graphics.printf("    " .. secondary, 20, y + 14, vp_w - 40, "left")
                    end
                end
            end

            -- Scroll indicators
            if scroll_top > 1 then
                love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
                love.graphics.printf("▲ more", 0, 58, vp_w, "center")
            end
            if scroll_end < #saves then
                love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
                love.graphics.printf("▼ more", 0, 70 + (scroll_end - scroll_top + 1) * 32, vp_w, "center")
            end
        end

        -- Rename prompt bar
        if ctx.save_renaming then
            local bar_h = 40
            local bar_y = vp_h - 70
            love.graphics.setColor(0.1, 0.1, 0.15, 0.9)
            love.graphics.rectangle("fill", 20, bar_y, vp_w - 40, bar_h, 6, 6)
            love.graphics.setFont(fonts[14])
            love.graphics.setColor(C_WARM_TITLE[1], C_WARM_TITLE[2], C_WARM_TITLE[3], 1)
            local cursor = (math.floor(love.timer.getTime() * 2) % 2 == 0) and "_" or ""
            love.graphics.print("Rename: " .. (ctx.save_rename_text or "") .. cursor, 30, bar_y + 6)
            love.graphics.setFont(fonts[11])
            love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 0.8)
            love.graphics.print("[Enter] Confirm    [Esc] Cancel", 30, bar_y + 24)
        end

        -- Controls hint at bottom
        love.graphics.setFont(fonts[12])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
        love.graphics.printf("[Enter] Load    [R] Rename    [D] Delete    [Esc] Back", 0, vp_h - 20, vp_w, "center")
        return
    end

    -- Veteran deployment screen
    if ctx.game_mode == ctx.DEPLOY_VETERANS then
        local deploy = ctx.deploy or {}
        local dvets = deploy.veterans or {}
        local slots = deploy.slots or 0
        local sel_idx = deploy.selected or 1

        -- Count deployed
        local deployed_count = 0
        for _, dv in ipairs(dvets) do
            if dv.deployed then deployed_count = deployed_count + 1 end
        end

        love.graphics.setFont(fonts[18])
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
        love.graphics.printf("Deploy Veterans", 0, 30, vp_w, "center")

        love.graphics.setFont(fonts[14])
        love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
        love.graphics.printf(
            string.format("Deployed: %d / %d slots", deployed_count, slots),
            0, 56, vp_w, "center"
        )

        for i, dv in ipairs(dvets) do
            local y = 90 + (i - 1) * 28
            local prefix = dv.deployed and "[+]" or "[-]"
            local label = string.format(
                "%s [%d] %s  HP:%d  XP:%d/%d",
                prefix, i, dv.def_id, dv.hp, dv.xp, dv.xp_needed
            )
            if dv.advancement_pending then
                label = label .. " *"
            end

            love.graphics.setFont(fonts[13])
            if i == sel_idx then
                love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
                love.graphics.printf("> " .. label, 20, y, vp_w - 40, "left")
            elseif dv.deployed then
                love.graphics.setColor(0.5, 1.0, 0.5, 1)
                love.graphics.printf("  " .. label, 20, y, vp_w - 40, "left")
            else
                love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 0.6)
                love.graphics.printf("  " .. label, 20, y, vp_w - 40, "left")
            end
        end

        -- Controls hint
        love.graphics.setFont(fonts[12])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
        love.graphics.printf("[Space] Toggle    [Enter] Confirm    [Esc] Deploy All", 0, vp_h - 20, vp_w, "center")
        return
    end

    local is_blue = (ctx.game_mode == ctx.PICK_FACTION_BLUE or ctx.game_mode == ctx.SETUP_BLUE)
    local faction_name = is_blue and "Blue" or "Red"
    local fc = is_blue and ctx.BLUE or ctx.RED

    -- Sidebar background
    draw_sidebar_bg(vp_w, vp_h)

    if ctx.game_mode == ctx.PICK_FACTION_BLUE or ctx.game_mode == ctx.PICK_FACTION_RED then
        love.graphics.setFont(fonts[15])
        love.graphics.setColor(fc[1], fc[2], fc[3])
        love.graphics.print("FACTION — " .. faction_name, vp_w - SIDEBAR_X_OFF, SIDEBAR_PAD)

        -- Controller selection
        local side = is_blue and 1 or 2
        local ctrl = (ctx.controllers or {"human","human"})[side]
        local ctrl_labels = {human = "Human", ai = "AI", port = "Port"}
        love.graphics.setFont(fonts[13])
        love.graphics.setColor(C_GOLD[1], C_GOLD[2], C_GOLD[3], 1)
        love.graphics.print("Controller: " .. (ctrl_labels[ctrl] or ctrl), vp_w - SIDEBAR_X_OFF, 30)
        love.graphics.setFont(fonts[11])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
        love.graphics.print("[Tab] cycle  [H] human", vp_w - SIDEBAR_X_OFF, 46)

        love.graphics.setFont(fonts[11])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
        love.graphics.print("Press 1-" .. #ctx.factions .. " to pick faction", vp_w - SIDEBAR_X_OFF, 64)

        for i, f in ipairs(ctx.factions) do
            local y = 86 + (i - 1) * 22
            local label = "[" .. i .. "] " .. f.name
            if (i - 1) == ctx.sel_faction_idx then
                love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            else
                love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], 1)
            end
            love.graphics.setFont(fonts[13])
            love.graphics.print(label, vp_w - SIDEBAR_X_OFF, y)
        end
    else
        love.graphics.setFont(fonts[15])
        love.graphics.setColor(fc[1], fc[2], fc[3])
        love.graphics.print("SETUP — " .. faction_name, vp_w - SIDEBAR_X_OFF, SIDEBAR_PAD)

        local fi = ctx.faction_index_for_mode()
        if not ctx.leader_placed[fi + 1] then
            local leader_def = ctx.norrust.get_faction_leader(ctx.engine, ctx.faction_id[fi + 1])

            love.graphics.setFont(fonts[11])
            love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
            love.graphics.print("Place leader:", vp_w - SIDEBAR_X_OFF, 30)
            love.graphics.setFont(fonts[14])
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            love.graphics.print(leader_def, vp_w - SIDEBAR_X_OFF, 48)

            -- Board-center prompt (account for zoom in position)
            local bx, by = ctx.hex.to_pixel(int(ctx.BOARD_COLS / 2), int(ctx.BOARD_ROWS / 2))
            local zoom = ctx.camera_zoom or 1
            local sx = ctx.board_origin_x + zoom * (bx + ctx.camera_offset_x)
            local sy = ctx.board_origin_y + zoom * (by + ctx.camera_offset_y)
            local prompt = "Click a hex on the board to place " .. leader_def
            love.graphics.setColor(0, 0, 0, 0.75)
            love.graphics.rectangle("fill", sx - 200, sy - 14, 400, 24)
            love.graphics.setFont(fonts[13])
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            love.graphics.print(prompt, sx - 196, sy - 8)
        end
    end
end

return M
