-- draw.lua — All rendering functions extracted from main.lua
-- Uses a context table (ctx) passed to each function for shared state access.

local draw = {}

-- ── Layout constants ────────────────────────────────────────────────────────
local SIDEBAR_W = 200
local SIDEBAR_PAD = 10
local SIDEBAR_X_OFF = SIDEBAR_W - SIDEBAR_PAD  -- 190, content inset from right edge

-- ── Frequently used colors ──────────────────────────────────────────────────
local C_GRAY       = {0.83, 0.83, 0.83}
local C_GOLD       = {1, 0.85, 0}
local C_WARM_TITLE = {0.9, 0.85, 0.6}
local C_WHITE      = {1, 1, 1}
local C_YELLOW     = {1, 1, 0}

-- ── Helpers ─────────────────────────────────────────────────────────────────

--- Draw a full-height sidebar background panel.
local function draw_sidebar_bg(vp_w, vp_h, alpha)
    love.graphics.setColor(0, 0, 0, alpha or 0.6)
    love.graphics.rectangle("fill", vp_w - SIDEBAR_W, 0, SIDEBAR_W, vp_h)
end

--- Get faction color table from ctx.
local function faction_color(ctx, faction)
    return faction == 0 and ctx.BLUE or ctx.RED
end

--- Draw a unit as a colored circle with abbreviation and HP (fallback when no sprite).
local function draw_unit_fallback(ctx, cx, cy, faction, alpha, def_id, hp)
    local color = faction == 0 and ctx.BLUE or ctx.RED
    love.graphics.setColor(color[1], color[2], color[3], alpha)
    love.graphics.circle("fill", cx, cy, ctx.hex.RADIUS * 0.45)
    local word = (def_id or ""):match("^([^_]+)") or def_id or ""
    local abbrev = (word:sub(1,1):upper() .. word:sub(2):lower()):sub(1, 7)
    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], alpha)
    love.graphics.setFont(ctx.fonts[14])
    love.graphics.printf(abbrev, cx - 42, cy - 14, 84, "center")
    love.graphics.setColor(C_WHITE[1], C_WHITE[2], C_WHITE[3], alpha)
    love.graphics.setFont(ctx.fonts[18])
    love.graphics.print(tostring(hp), cx - 12, cy - 2)
end

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
            draw_unit_fallback(ctx, cx, cy, faction, alpha, unit.def_id, hp)
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

    -- Draw dying units (death animation still playing)
    for uid, info in pairs(ctx.dying_units or {}) do
        local anim_state = ctx.unit_anims[uid]
        if anim_state then
            local cx, cy = ctx.hex.to_pixel(info.col, info.row)
            local faction = info.faction
            anim_state.facing = faction == 0 and "right" or "left"
            ctx.assets.draw_unit_sprite(ctx.unit_sprites, info.def_id, cx, cy, ctx.hex.RADIUS, faction, 1.0, ctx.FACTION_COLORS, anim_state)
        end
    end

    -- Clean up stale animation states for dead/removed units (skip dying units)
    for uid in pairs(ctx.unit_anims) do
        if not alive_ids[uid] and not (ctx.dying_units and ctx.dying_units[uid]) then
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

        love.graphics.setFont(fonts[11])
        love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
        love.graphics.print("Press 1-" .. #ctx.factions .. " to pick", vp_w - SIDEBAR_X_OFF, 30)

        for i, f in ipairs(ctx.factions) do
            local y = 56 + (i - 1) * 22
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
        else
            love.graphics.setFont(fonts[11])
            love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3])
            love.graphics.print("Leader placed.", vp_w - SIDEBAR_X_OFF, 30)
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            love.graphics.print("[Enter] Continue", vp_w - SIDEBAR_X_OFF, 44)
        end
    end
end

--- Draw the recruit panel sidebar.
function draw.draw_recruit_panel(ctx, state)
    local int = ctx.int
    local fonts = ctx.fonts
    local faction = ctx.norrust.get_active_faction(ctx.engine)
    local vp_w, vp_h = ctx.get_viewport()
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
function draw.draw_unit_panel(ctx, unit)
    local int = ctx.int
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()

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
    local move_status = ""
    if unit.moved and unit.attacked then
        move_status = " (done)"
    elseif unit.moved then
        move_status = " (moved)"
    elseif unit.attacked then
        move_status = " (attacked)"
    end
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
function draw.draw_terrain_panel(ctx)
    local fonts = ctx.fonts
    local int = ctx.int
    local vp_w, vp_h = ctx.get_viewport()
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
function draw.draw_dialogue_panel(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()

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
function draw.draw_dialogue_history(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()
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
function draw.draw_combat_preview(ctx)
    local fonts = ctx.fonts
    local vp_w, vp_h = ctx.get_viewport()
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

    -- Tile colors cached at scenario load; terrain_ids built per-frame for asset lookup
    local tile_colors = ctx.tile_color_cache or {}
    local tile_ids = {}
    for _, tile in ipairs(state.terrain or {}) do
        local key = int(tile.col) .. "," .. int(tile.row)
        tile_ids[key] = tile.terrain_id
    end

    -- Clip board rendering at panel edge (scissor in pixel coords)
    local panel_w = SIDEBAR_W
    local sw, sh = love.graphics.getDimensions()
    love.graphics.setScissor(0, 0, sw - panel_w * ctx.UI_SCALE, sh)

    -- Board-space drawing (push camera transform with zoom)
    local zoom = ctx.camera_zoom or 1.0
    love.graphics.push()
    love.graphics.translate(ctx.board_origin_x, ctx.board_origin_y)
    love.graphics.scale(zoom, zoom)
    love.graphics.translate(ctx.camera_offset_x, ctx.camera_offset_y)

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
    draw.draw_units(ctx, state)

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
                    draw_unit_fallback(ctx, gx, gy, faction, ghost_alpha, unit.def_id, hp)
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

    love.graphics.pop() -- back to screen space
    love.graphics.setScissor() -- clear scissor for UI drawing

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
            love.graphics.setColor(C_YELLOW[1], C_YELLOW[2], C_YELLOW[3], 1)
            love.graphics.printf(msg, vp_w / 2 - 240, vp_h / 2 - 16, 480, "center")
            if sub_msg then
                love.graphics.setFont(ctx.fonts[14])
                love.graphics.setColor(C_GRAY[1], C_GRAY[2], C_GRAY[3], 1)
                love.graphics.printf(sub_msg, vp_w / 2 - 240, vp_h / 2 + 24, 480, "center")
            end
        end

        -- HUD
        if not ctx.game_over then
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

        if ctx.show_dialogue_history then
            draw.draw_dialogue_history(ctx)
        elseif ctx.combat_preview ~= nil then
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
        elseif ctx.active_dialogue and #ctx.active_dialogue > 0 then
            draw.draw_dialogue_panel(ctx)
        end
    end

    -- Sidebar buttons (bottom of sidebar, always rendered)
    draw.draw_sidebar_buttons(ctx)

    -- Help overlay (drawn on top of everything)
    if ctx.show_help then
        draw.draw_help_overlay(ctx)
    end

    love.graphics.pop()
end

--- Draw clickable buttons at the bottom of the sidebar.
function draw.draw_sidebar_buttons(ctx)
    local vp_w, vp_h = ctx.get_viewport()
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

    if ctx.game_mode == ctx.PLAYING and not ctx.game_over then
        local faction = ctx.norrust.get_active_faction(ctx.engine)
        local fc = faction_color(ctx, faction)

        -- Recruit button
        local recruit_y = help_y - btn_h - gap
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

--- Draw a semi-transparent help overlay showing all keybindings.
function draw.draw_help_overlay(ctx)
    local vp_w, vp_h = ctx.get_viewport()
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

return draw
