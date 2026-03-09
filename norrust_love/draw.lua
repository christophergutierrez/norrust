-- draw.lua — Main rendering entry point. Dispatches to sub-modules.
-- Uses a context table (ctx) passed to each function for shared state access.

local common       = require("draw_common")
local draw_board   = require("draw_board")
local draw_sidebar = require("draw_sidebar")
local draw_hud     = require("draw_hud")
local draw_screens = require("draw_screens")

local SIDEBAR_W = common.SIDEBAR_W

local draw = {}

--- Main draw dispatch — contains the love.draw body logic.
function draw.draw_frame(ctx, state)
    -- Cache viewport dimensions for the entire frame
    ctx.vp_w, ctx.vp_h = ctx.get_viewport()

    love.graphics.push()
    love.graphics.scale(ctx.UI_SCALE, ctx.UI_SCALE)

    -- Scenario selection or save list: no board loaded yet
    if ctx.game_mode == ctx.PICK_SCENARIO or ctx.game_mode == ctx.LOAD_SAVE or ctx.game_mode == ctx.DEPLOY_VETERANS then
        draw_screens.draw_setup_hud(ctx)
        love.graphics.pop()
        return
    end

    local int = ctx.int

    -- Tile colors cached at scenario load; terrain_ids built per-frame for asset lookup
    local tile_colors = ctx.tile_color_cache or {}
    local tile_ids = {}
    local village_owners = {}
    for _, tile in ipairs(state.terrain or {}) do
        local key = int(tile.col) .. "," .. int(tile.row)
        tile_ids[key] = tile.terrain_id
        if tile.owner and int(tile.owner) >= 0 then
            village_owners[key] = int(tile.owner)
        end
    end

    -- Attach per-frame data to ctx for sub-modules
    ctx.tile_ids = tile_ids
    ctx.village_owners = village_owners

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

    -- Draw board contents (terrain, highlights, units, ghosts, recruit hexes)
    draw_board.draw_board(ctx, state)

    love.graphics.pop() -- back to screen space
    love.graphics.setScissor() -- clear scissor for UI drawing

    -- ── Screen-space UI ─────────────────────────────────────────────────

    if ctx.game_mode ~= ctx.PLAYING then
        draw_screens.draw_setup_hud(ctx)
    else
        -- Win overlay
        if ctx.game_over then
            draw_hud.draw_game_over(ctx, state)
        end

        -- HUD
        if not ctx.game_over then
            draw_hud.draw_hud_bar(ctx, state)
        end

        if ctx.show_dialogue_history then
            draw_sidebar.draw_dialogue_history(ctx)
        elseif ctx.combat_preview ~= nil then
            draw_sidebar.draw_combat_preview(ctx)
        elseif ctx.recruit_mode then
            draw_sidebar.draw_recruit_panel(ctx, state)
        elseif ctx.inspect_unit_id ~= -1 then
            for _, unit in ipairs(state.units or {}) do
                if int(unit.id) == ctx.inspect_unit_id then
                    draw_sidebar.draw_unit_panel(ctx, unit)
                    break
                end
            end
        elseif ctx.inspect_terrain then
            draw_sidebar.draw_terrain_panel(ctx)
        elseif ctx.active_dialogue and #ctx.active_dialogue > 0 then
            draw_sidebar.draw_dialogue_panel(ctx)
        end
    end

    -- Sidebar buttons (bottom of sidebar, always rendered)
    draw_sidebar.draw_sidebar_buttons(ctx)

    -- Help overlay (drawn on top of everything)
    if ctx.show_help then
        draw_hud.draw_help_overlay(ctx)
    end

    love.graphics.pop()
end

return draw
