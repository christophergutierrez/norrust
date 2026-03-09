-- draw_common.lua — Shared constants and helpers for all draw sub-modules

local M = {}

-- ── Layout constants ────────────────────────────────────────────────────────
M.SIDEBAR_W = 200
M.SIDEBAR_PAD = 10
M.SIDEBAR_X_OFF = M.SIDEBAR_W - M.SIDEBAR_PAD  -- 190, content inset from right edge

-- ── Frequently used colors ──────────────────────────────────────────────────
M.C_GRAY       = {0.83, 0.83, 0.83}
M.C_GOLD       = {1, 0.85, 0}
M.C_WARM_TITLE = {0.9, 0.85, 0.6}
M.C_WHITE      = {1, 1, 1}
M.C_YELLOW     = {1, 1, 0}

-- Move-status lookup: key = (moved and 1 or 0) + (attacked and 2 or 0)
M.MOVE_STATUS = { [0] = "", [1] = " (moved)", [2] = " (attacked)", [3] = " (done)" }

-- ── Helpers ─────────────────────────────────────────────────────────────────

--- Draw a full-height sidebar background panel.
function M.draw_sidebar_bg(vp_w, vp_h, alpha)
    love.graphics.setColor(0, 0, 0, alpha or 0.6)
    love.graphics.rectangle("fill", vp_w - M.SIDEBAR_W, 0, M.SIDEBAR_W, vp_h)
end

--- Get faction color table from ctx.
function M.faction_color(ctx, faction)
    return faction == 0 and ctx.BLUE or ctx.RED
end

--- Draw a unit as a colored circle with abbreviation and HP (fallback when no sprite).
function M.draw_unit_fallback(ctx, cx, cy, faction, alpha, def_id, hp)
    local color = faction == 0 and ctx.BLUE or ctx.RED
    love.graphics.setColor(color[1], color[2], color[3], alpha)
    love.graphics.circle("fill", cx, cy, ctx.hex.RADIUS * 0.45)
    local word = (def_id or ""):match("^([^_]+)") or def_id or ""
    local abbrev = (word:sub(1,1):upper() .. word:sub(2):lower()):sub(1, 7)
    love.graphics.setColor(M.C_WHITE[1], M.C_WHITE[2], M.C_WHITE[3], alpha)
    love.graphics.setFont(ctx.fonts[14])
    love.graphics.printf(abbrev, cx - 42, cy - 14, 84, "center")
    love.graphics.setColor(M.C_WHITE[1], M.C_WHITE[2], M.C_WHITE[3], alpha)
    love.graphics.setFont(ctx.fonts[18])
    love.graphics.print(tostring(hp), cx - 12, cy - 2)
end

return M
